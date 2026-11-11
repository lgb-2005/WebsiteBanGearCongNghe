"""ChatEngine: vòng lặp tool-calling + persist message + log audit."""

import json
import logging
import time
import traceback

from django.conf import settings

from chatbot.context import ChatContext
from chatbot.intent.resolver import normalize, resolve_aliases
from chatbot.models import ChatTurnLog, Conversation, Message
from chatbot.prompts import build_forced_search_message, build_system_prompt
from chatbot.providers import GeminiProvider, LLMMessage, LLMProvider
from chatbot.providers.exceptions import ProviderError, ProviderTimeout, QuotaExceeded
from chatbot.schemas import TOOL_SCHEMAS
from chatbot.tools.registry import get_tool

logger = logging.getLogger(__name__)

MAX_LOOP_ROUNDS = getattr(settings, 'CHATBOT_MAX_TOOL_ROUNDS', 3)
HISTORY_LIMIT = getattr(settings, 'CHATBOT_HISTORY_LIMIT', 10)
MAX_MESSAGE_LENGTH = getattr(settings, 'CHATBOT_MAX_MESSAGE_LENGTH', 1000)
MAX_CLARIFY_TURNS = getattr(settings, 'CHATBOT_MAX_CLARIFY_TURNS', 2)

_FRIENDLY_ERROR = {
    QuotaExceeded: 'Trợ lý đang quá tải, bạn thử lại sau ít phút nhé.',
    ProviderTimeout: 'Trợ lý phản hồi chậm, bạn thử lại sau ít phút nhé.',
    ProviderError: 'Xin lỗi, tôi gặp lỗi kết nối. Bạn thử lại sau nhé.',
}


class ChatEngine:
    _FAST_PATH_SKIP_KEYWORDS = ('so sanh', ' vs ', 'chi tiet', 'danh gia', 'review')

    def __init__(self, provider: LLMProvider = None, enable_fast_path: bool = True):
        self.provider = provider
        self.enable_fast_path = enable_fast_path

    def _ensure_provider(self):
        if self.provider is None:
            self.provider = GeminiProvider()
        return self.provider

    @staticmethod
    def _truncate(value, max_length=5000):
        text = json.dumps(value, ensure_ascii=False, default=str)
        if len(text) <= max_length:
            return value
        return {
            '_truncated': True,
            '_original_length': len(text),
            '_preview': text[:max_length],
        }

    @staticmethod
    def _format_history_content(message: Message) -> str:
        content = message.content or ''
        if message.role == Message.ROLE_ASSISTANT and message.products:
            items = []
            for idx, prod in enumerate(message.products, start=1):
                if isinstance(prod, dict) and prod.get('slug'):
                    name = prod.get('name') or prod['slug']
                    items.append(f"#{idx} {name} (slug: {prod['slug']})")
            if items:
                note = '[Ngữ cảnh hệ thống - Sản phẩm đã gợi ý ở lượt này: ' + '; '.join(items) + ']'
                content = f'{content}\n{note}' if content else note
        return content

    @classmethod
    def _load_history(cls, conversation: Conversation, exclude_message_id: int = None):
        qs = conversation.messages.filter(role__in=[Message.ROLE_USER, Message.ROLE_ASSISTANT])
        if exclude_message_id is not None:
            qs = qs.exclude(pk=exclude_message_id)
        messages = qs.order_by('-created_at', '-id')[:HISTORY_LIMIT]
        history = []
        for message in reversed(list(messages)):
            history.append(
                LLMMessage(
                    role=message.role,
                    content=cls._format_history_content(message),
                )
            )
        return history

    _UI_ONLY_KEYS = {'ui_results', 'ui_product', 'ui_products', 'ui_suggestions'}

    @classmethod
    def _strip_ui_fields(cls, tool_name: str, payload):
        if not isinstance(payload, dict):
            return payload
        cleaned = {
            key: value
            for key, value in payload.items()
            if key not in cls._UI_ONLY_KEYS
        }
        if isinstance(cleaned.get('relaxation'), dict):
            cleaned['relaxation'] = {
                key: value
                for key, value in cleaned['relaxation'].items()
                if key not in cls._UI_ONLY_KEYS
            }
        if tool_name == 'compare_products':
            cleaned.pop('rows_same', None)
        elif tool_name == 'get_product_detail' and isinstance(cleaned.get('product'), dict):
            cleaned.pop('specs', None)
            cleaned.pop('recent_reviews', None)
        return cleaned

    @staticmethod
    def _extract_products_and_comparison(tool_results: list):
        products = []
        seen_slugs = set()
        comparison = None

        def _add_products(items):
            for item in items or []:
                slug = item.get('slug') if isinstance(item, dict) else None
                if slug and slug in seen_slugs:
                    continue
                if slug:
                    seen_slugs.add(slug)
                products.append(item)

        for name, result in tool_results:
            if not isinstance(result, dict):
                continue
            if name == 'search_products':
                ui_results = result.get('ui_results') or []
                if not ui_results and isinstance(result.get('relaxation'), dict):
                    ui_results = result['relaxation'].get('ui_results') or []
                _add_products(ui_results)
            elif name == 'get_product_detail':
                ui_product = result.get('ui_product')
                if ui_product:
                    _add_products([ui_product])
                elif result.get('ui_suggestions'):
                    _add_products(result.get('ui_suggestions') or [])
            elif name == 'compare_products':
                ui_products = result.get('ui_products') or []
                _add_products(ui_products)
                comparison = {
                    'products': ui_products,
                    'rows_different': result.get('rows_different', []),
                    'rows_same': result.get('rows_same', []),
                    'price_row': result.get('price_row'),
                }
        return products, comparison

    def _execute_tool(self, call: dict, ctx: ChatContext):
        name = call.get('name', '')
        arguments = dict(call.get('arguments') or {})
        tool = get_tool(name)

        start = time.time()
        try:
            call_arguments = dict(arguments)
            if 'ctx' in tool.__code__.co_varnames:
                call_arguments['ctx'] = ctx
            result = tool(**call_arguments)
        except Exception as exc:
            logger.exception('Tool %s failed: %s', name, arguments)
            result = {
                'error': f'Tool {name} failed: {type(exc).__name__}',
                '_traceback': traceback.format_exc(),
            }

        return {
            'name': name,
            'arguments': arguments,
            'result': result,
            'duration_ms': int((time.time() - start) * 1000),
        }

    def _is_clarification(self, final_text: str, has_tool_calls: bool):
        if has_tool_calls:
            return False
        # Nếu không gọi tool và câu trả lời có dấu hỏi hoặc rất ngắn -> coi là clarify.
        text = (final_text or '').strip()
        if not text:
            return True
        if '?' in text or '?' in text:
            return True
        return len(text) < 80

    @classmethod
    def _can_fast_path_search(cls, raw_message: str, resolved_aliases: dict) -> bool:
        if not resolved_aliases or not resolved_aliases.get('category_slug'):
            return False
        has_criteria = (
            resolved_aliases.get('price_min') is not None
            or resolved_aliases.get('price_max') is not None
            or bool(resolved_aliases.get('attributes'))
            or bool(resolved_aliases.get('keywords'))
            or bool(resolved_aliases.get('sort_by'))
        )
        if not has_criteria:
            return False
        norm_msg = f' {normalize(raw_message)} '
        if any(kw in norm_msg for kw in cls._FAST_PATH_SKIP_KEYWORDS):
            return False
        return True

    @staticmethod
    def _build_fast_path_search_args(resolved_aliases: dict) -> dict:
        args = {
            'category_slug': resolved_aliases['category_slug'],
            'limit': 5,
        }
        if resolved_aliases.get('keywords'):
            args['keyword'] = ' '.join(resolved_aliases['keywords'])
        if resolved_aliases.get('price_min') is not None:
            args['price_min'] = resolved_aliases['price_min']
        if resolved_aliases.get('price_max') is not None:
            args['price_max'] = resolved_aliases['price_max']
        if resolved_aliases.get('attributes'):
            args['attributes'] = resolved_aliases['attributes']
        if resolved_aliases.get('sort_by'):
            args['sort_by'] = resolved_aliases['sort_by']
        return args

    def _build_user_content(self, message: str, resolved_aliases: dict, force_search: bool, fast_path_payload: dict = None):
        lines = [message]
        if force_search:
            lines.append(build_forced_search_message())
        if fast_path_payload is not None:
            lines.append(
                '[Hệ thống đã tìm kiếm sẵn danh sách sản phẩm khớp nhu cầu từ DB dưới đây. '
                'Hãy tư vấn ngay dựa trên dữ liệu này mà KHÔNG cần gọi lại tool search_products:]\n'
                + json.dumps(fast_path_payload, ensure_ascii=False, default=str)
            )
        # Alias gợi ý đã nằm trong system prompt, không cần nhồi vào user message.
        return '\n\n'.join(lines)

    def process(self, message: str, conversation: Conversation, ctx: ChatContext, page_context: dict = None) -> dict:
        start_time = time.time()
        tool_log_entries = []
        status = ChatTurnLog.STATUS_OK
        error_detail = ''
        loop_rounds = 0
        total_latency = 0
        prompt_tokens = None
        completion_tokens = None
        final_text = ''
        products = None
        comparison = None
        model_name = getattr(settings, 'GEMINI_MODEL', 'gemini-2.0-flash')

        # Validate
        raw_message = (message or '').strip()
        if not raw_message:
            return self._error_response(conversation, 'Tin nhắn không được để trống.')
        if len(raw_message) > MAX_MESSAGE_LENGTH:
            raw_message = raw_message[:MAX_MESSAGE_LENGTH]

        # Persist user message + title
        user_msg = Message.objects.create(
            conversation=conversation,
            role=Message.ROLE_USER,
            content=raw_message,
        )
        conversation.ensure_title(raw_message)

        resolved_aliases = resolve_aliases(raw_message)
        system_prompt = build_system_prompt(
            resolved_aliases,
            page_context,
            getattr(ctx, 'purchase_intent', None),
        )

        fast_path_payload = None
        if self.enable_fast_path and self._can_fast_path_search(raw_message, resolved_aliases):
            search_args = self._build_fast_path_search_args(resolved_aliases)
            fast_tool_result = self._execute_tool({'name': 'search_products', 'arguments': search_args}, ctx)
            fast_tool_result['fast_path'] = True
            tool_log_entries.append(fast_tool_result)
            fast_path_payload = self._strip_ui_fields('search_products', fast_tool_result['result'])

        force_search = conversation.clarify_count >= MAX_CLARIFY_TURNS
        user_content = self._build_user_content(raw_message, resolved_aliases, force_search, fast_path_payload)

        try:
            provider = self._ensure_provider()
        except ProviderError as exc:
            logger.error('Cannot initialize provider: %s', exc)
            status = ChatTurnLog.STATUS_API_ERROR
            error_detail = str(exc)
            final_text = _FRIENDLY_ERROR.get(type(exc), _FRIENDLY_ERROR[ProviderError])
            self._persist_turn(
                conversation, raw_message, resolved_aliases, tool_log_entries,
                loop_rounds, model_name, prompt_tokens, completion_tokens,
                total_latency, final_text, status, error_detail,
            )
            response = self._ok_response(conversation, final_text, products, comparison, loop_rounds, total_latency, tool_log_entries)
            response['purchase_intent'] = getattr(ctx, 'purchase_intent', {})
            return response

        history = self._load_history(conversation, exclude_message_id=user_msg.pk)
        current_messages = [LLMMessage(role='user', content=user_content)]

        try:
            for round_number in range(MAX_LOOP_ROUNDS):
                loop_rounds = round_number + 1
                provider_messages = history + current_messages

                result = provider.generate(system_prompt, provider_messages, TOOL_SCHEMAS)
                total_latency += result.latency_ms or 0
                if result.prompt_tokens is not None:
                    prompt_tokens = (prompt_tokens or 0) + result.prompt_tokens
                if result.completion_tokens is not None:
                    completion_tokens = (completion_tokens or 0) + result.completion_tokens
                model_name = result.model_name or model_name

                if result.tool_calls:
                    assistant_msg = LLMMessage(
                        role='assistant',
                        content=result.text,
                        tool_calls=result.tool_calls,
                    )
                    current_messages.append(assistant_msg)

                    round_tool_results = []
                    for call in result.tool_calls:
                        tool_result = self._execute_tool(call, ctx)
                        round_tool_results.append((call['name'], tool_result['result']))
                        tool_log_entries.append(tool_result)
                        llm_payload = self._strip_ui_fields(call['name'], tool_result['result'])
                        current_messages.append(
                            LLMMessage(
                                role='tool',
                                tool_name=call['name'],
                                tool_payload=llm_payload,
                            )
                        )

                    # Nếu đã đủ vòng lặp, buộc model trả lời text ở lượt cuối.
                    if loop_rounds >= MAX_LOOP_ROUNDS:
                        final_round = provider.generate(system_prompt, history + current_messages, TOOL_SCHEMAS)
                        total_latency += final_round.latency_ms or 0
                        if final_round.prompt_tokens is not None:
                            prompt_tokens = (prompt_tokens or 0) + final_round.prompt_tokens
                        if final_round.completion_tokens is not None:
                            completion_tokens = (completion_tokens or 0) + final_round.completion_tokens
                        final_text = final_round.text
                        products, comparison = self._extract_products_and_comparison(round_tool_results)
                        break
                    continue

                final_text = result.text
                products, comparison = self._extract_products_and_comparison(
                    [(entry['name'], entry['result']) for entry in tool_log_entries]
                )
                break
            else:
                # Hết vòng lặp mà chưa có text -> dùng text rỗng.
                final_text = final_text or 'Xin lỗi, tôi chưa thể đưa ra câu trả lời. Bạn thử lại sau nhé.'
                products, comparison = self._extract_products_and_comparison(
                    [(entry['name'], entry['result']) for entry in tool_log_entries]
                )

        except QuotaExceeded as exc:
            status = ChatTurnLog.STATUS_API_ERROR
            error_detail = str(exc)
            final_text = _FRIENDLY_ERROR[QuotaExceeded]
        except ProviderTimeout as exc:
            status = ChatTurnLog.STATUS_TIMEOUT
            error_detail = str(exc)
            final_text = _FRIENDLY_ERROR[ProviderTimeout]
        except ProviderError as exc:
            status = ChatTurnLog.STATUS_API_ERROR
            error_detail = str(exc)
            final_text = _FRIENDLY_ERROR[ProviderError]
        except Exception as exc:
            logger.exception('Unexpected engine error')
            status = ChatTurnLog.STATUS_TOOL_ERROR
            error_detail = traceback.format_exc()
            final_text = 'Xin lỗi, tôi gặp lỗi không mong muốn. Bạn thử lại sau nhé.'

        # Persist assistant message
        assistant_message = Message.objects.create(
            conversation=conversation,
            role=Message.ROLE_ASSISTANT,
            content=final_text,
            products=products,
            comparison=comparison,
        )

        # Cập nhật clarify_count
        is_clarify = self._is_clarification(final_text, bool(tool_log_entries))
        if is_clarify:
            conversation.clarify_count += 1
        else:
            conversation.clarify_count = 0
        conversation.save(update_fields=['clarify_count', 'updated_at'])

        total_latency = total_latency or int((time.time() - start_time) * 1000)

        self._persist_turn(
            conversation, raw_message, resolved_aliases, tool_log_entries,
            loop_rounds, model_name, prompt_tokens, completion_tokens,
            total_latency, final_text, status, error_detail,
        )

        response = self._ok_response(conversation, final_text, products, comparison, loop_rounds, total_latency, tool_log_entries)
        response['purchase_intent'] = getattr(ctx, 'purchase_intent', {})
        return response

    def _persist_turn(self, conversation, raw_message, resolved_aliases, tool_log_entries,
                      loop_rounds, model_name, prompt_tokens, completion_tokens,
                      latency_ms, final_text, status, error_detail):
        try:
            ChatTurnLog.objects.create(
                conversation=conversation,
                user_message=raw_message,
                resolved_aliases=resolved_aliases,
                tool_calls=tool_log_entries,
                loop_rounds=loop_rounds,
                provider='gemini',
                model_name=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
                final_answer=final_text,
                status=status,
                error_detail=error_detail,
            )
        except Exception:
            logger.exception('Failed to persist ChatTurnLog')

    @staticmethod
    def _ok_response(conversation, reply, products, comparison, loop_rounds, latency_ms, tool_log_entries=None):
        return {
            'conversation_id': conversation.pk,
            'reply': reply,
            'products': products,
            'comparison': comparison,
            'meta': {
                'loop_rounds': loop_rounds,
                'latency_ms': latency_ms,
                'tools': [entry['name'] for entry in (tool_log_entries or [])],
            },
        }

    @staticmethod
    def _error_response(conversation, reply):
        return {
            'conversation_id': conversation.pk,
            'reply': reply,
            'products': None,
            'comparison': None,
            'meta': {'loop_rounds': 0, 'latency_ms': 0, 'tools': []},
        }
