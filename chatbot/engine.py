"""ChatEngine: vòng lặp tool-calling + persist message + log audit."""

import json
import logging
import time
import traceback

from django.conf import settings

from chatbot.context import ChatContext
from chatbot.intent.resolver import resolve_aliases
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
    def __init__(self, provider: LLMProvider = None):
        self.provider = provider

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
    def _load_history(conversation: Conversation):
        messages = (
            conversation.messages.filter(role__in=[Message.ROLE_USER, Message.ROLE_ASSISTANT])
            .order_by('-created_at', '-id')
            [:HISTORY_LIMIT]
        )
        history = []
        for message in reversed(list(messages)):
            history.append(LLMMessage(role=message.role, content=message.content or ''))
        return history

    @staticmethod
    def _extract_products_and_comparison(tool_results: list):
        products = []
        comparison = None
        for name, result in tool_results:
            if name == 'search_products':
                products.extend(result.get('ui_results') or [])
            elif name == 'get_product_detail':
                ui_product = result.get('ui_product')
                if ui_product:
                    products.append(ui_product)
            elif name == 'compare_products':
                ui_products = result.get('ui_products') or []
                products.extend(ui_products)
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

    def _build_user_content(self, message: str, resolved_aliases: dict, force_search: bool):
        lines = [message]
        if force_search:
            lines.append(build_forced_search_message())
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
        Message.objects.create(
            conversation=conversation,
            role=Message.ROLE_USER,
            content=raw_message,
        )
        conversation.ensure_title(raw_message)

        resolved_aliases = resolve_aliases(raw_message)
        system_prompt = build_system_prompt(resolved_aliases, page_context)

        force_search = conversation.clarify_count >= MAX_CLARIFY_TURNS
        user_content = self._build_user_content(raw_message, resolved_aliases, force_search)

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
            return self._ok_response(conversation, final_text, products, comparison, loop_rounds, total_latency, tool_log_entries)

        history = self._load_history(conversation)
        current_messages = [LLMMessage(role='user', content=user_content)]

        try:
            for round_number in range(MAX_LOOP_ROUNDS):
                loop_rounds = round_number + 1
                provider_messages = history + current_messages

                result = provider.generate(system_prompt, provider_messages, TOOL_SCHEMAS)
                total_latency += result.latency_ms or 0
                if result.prompt_tokens is not None:
                    prompt_tokens = result.prompt_tokens
                if result.completion_tokens is not None:
                    completion_tokens = result.completion_tokens
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
                        current_messages.append(
                            LLMMessage(
                                role='tool',
                                tool_name=call['name'],
                                tool_payload=tool_result['result'],
                            )
                        )

                    # Nếu đã đủ vòng lặp, buộc model trả lời text ở lượt cuối.
                    if loop_rounds >= MAX_LOOP_ROUNDS:
                        final_round = provider.generate(system_prompt, history + current_messages, TOOL_SCHEMAS)
                        total_latency += final_round.latency_ms or 0
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

        return self._ok_response(conversation, final_text, products, comparison, loop_rounds, total_latency, tool_log_entries)

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
