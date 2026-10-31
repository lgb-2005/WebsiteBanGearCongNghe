"""Gemini provider cho chatbot — dùng SDK ``google-genai`` mới (>=1.0.0)."""

import logging
import time

from django.conf import settings

from google import genai
from google.genai import types
from google.genai.errors import APIError

from .base import LLMMessage, LLMProvider, LLMResult
from .exceptions import ProviderError, ProviderTimeout, QuotaExceeded

logger = logging.getLogger(__name__)

_TYPE_MAP = {
    'string': types.Type.STRING,
    'number': types.Type.NUMBER,
    'integer': types.Type.INTEGER,
    'boolean': types.Type.BOOLEAN,
    'array': types.Type.ARRAY,
    'object': types.Type.OBJECT,
}


def _to_gemini_schema(schema: dict) -> types.Schema:
    if not schema:
        return types.Schema(type=types.Type.OBJECT)

    schema_type = schema.get('type')
    if 'oneOf' in schema or 'anyOf' in schema:
        # Gemini Schema không hỗ trợ oneOf/anyOf; flatten thành string tự do.
        return types.Schema(
            type=types.Type.STRING,
            description=schema.get('description', ''),
        )

    properties = None
    if 'properties' in schema:
        properties = {
            key: _to_gemini_schema(value)
            for key, value in schema['properties'].items()
        }

    items = None
    if 'items' in schema:
        items = _to_gemini_schema(schema['items'])

    enum = schema.get('enum')
    if isinstance(enum, (list, tuple)):
        enum = list(enum)
    else:
        enum = None

    return types.Schema(
        type=_TYPE_MAP.get(schema_type, types.Type.OBJECT),
        description=schema.get('description', ''),
        enum=enum,
        properties=properties,
        required=schema.get('required') or None,
        items=items,
    )


def _convert_tools(tools: list) -> list:
    declarations = []
    for tool in tools:
        declarations.append(
            types.FunctionDeclaration(
                name=tool['name'],
                description=tool['description'],
                parameters=_to_gemini_schema(tool.get('parameters', {})),
            )
        )
    return [types.Tool(function_declarations=declarations)]


def _convert_messages(messages: list[LLMMessage]) -> list:
    """Chuyển messages nội bộ sang định dạng Gemini.

    Dùng dict thay vì SDK types để giữ nguyên ``thought_signature`` của
    function_call trả về từ API (bắt buộc với Gemini 3.x).
    """
    contents = []
    for message in messages:
        if message.role == 'tool':
            contents.append({
                'role': 'user',
                'parts': [{
                    'function_response': {
                        'name': message.tool_name,
                        'response': message.tool_payload or {},
                    }
                }],
            })
        elif message.role == 'assistant' and message.tool_calls:
            parts = []
            if message.content:
                parts.append({'text': message.content})
            for call in message.tool_calls:
                raw_part = call.get('_raw_part')
                if raw_part:
                    parts.append(raw_part)
                else:
                    parts.append({
                        'function_call': {
                            'name': call['name'],
                            'args': call['arguments'],
                        }
                    })
            contents.append({'role': 'model', 'parts': parts})
        else:
            role = 'user' if message.role == 'user' else 'model'
            contents.append({
                'role': role,
                'parts': [{'text': message.content or ''}],
            })
    return contents


class GeminiProvider(LLMProvider):
    def __init__(
        self,
        api_key=None,
        model=None,
        retry_quota=False,
        max_quota_retries=3,
        thinking_budget=None,
        max_transient_retries=2,
        transient_retry_delay=1.5,
    ):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model = model or settings.GEMINI_MODEL or 'gemini-3.5-flash'
        if not self.api_key:
            raise ProviderError('GEMINI_API_KEY chưa được cấu hình.')
        self.client = genai.Client(api_key=self.api_key)
        self.retry_quota = retry_quota
        self.max_quota_retries = max_quota_retries
        if thinking_budget is None:
            thinking_budget = getattr(settings, 'CHATBOT_THINKING_BUDGET', 0)
        self.thinking_budget = thinking_budget
        self.max_transient_retries = max_transient_retries
        self.transient_retry_delay = transient_retry_delay

    def _call_api(self, system_prompt: str, messages: list[LLMMessage], tools: list):
        config_kwargs = {
            'system_instruction': system_prompt,
            'tools': _convert_tools(tools),
        }
        if self.thinking_budget is not None and self.thinking_budget >= 0:
            config_kwargs['thinking_config'] = types.ThinkingConfig(
                thinking_budget=self.thinking_budget,
            )

        contents = _convert_messages(messages)
        try:
            return self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(**config_kwargs),
            )
        except APIError as exc:
            if (
                'thinking_config' in config_kwargs
                and getattr(exc, 'code', None) == 400
                and 'thinking' in str(exc).lower()
            ):
                logger.info('Model %s does not support thinking_budget; retrying without thinking_config', self.model)
                self.thinking_budget = -1
                config_kwargs.pop('thinking_config', None)
                return self.client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=types.GenerateContentConfig(**config_kwargs),
                )
            raise

    @staticmethod
    def _is_transient_error(exc: APIError) -> bool:
        code = getattr(exc, 'code', None)
        if code in (500, 502, 503, 504):
            return True
        msg = str(exc).lower()
        return any(token in msg for token in ('unavailable', 'high demand', 'overloaded'))

    @staticmethod
    def _extract_retry_after(exc):
        try:
            detail = exc.details or []
            for item in detail:
                if getattr(item, 'retry_delay', None):
                    return int(item.retry_delay.seconds)
        except Exception:
            pass
        try:
            match = __import__('re').search(r'retry in ([\d\.]+)s', str(exc))
            if match:
                return int(float(match.group(1))) + 1
        except Exception:
            pass
        return 60

    def generate(self, system_prompt: str, messages: list[LLMMessage], tools: list) -> LLMResult:
        start = time.time()
        quota_attempt = 0
        transient_attempt = 0

        while True:
            try:
                response = self._call_api(system_prompt, messages, tools)
                break
            except APIError as exc:
                if getattr(exc, 'code', None) == 429 or 'quota' in str(exc).lower():
                    if self.retry_quota and quota_attempt < self.max_quota_retries:
                        quota_attempt += 1
                        retry_after = self._extract_retry_after(exc)
                        logger.warning('Gemini quota exceeded. Retry %d/%d after %ds', quota_attempt, self.max_quota_retries, retry_after)
                        time.sleep(retry_after)
                        continue
                    raise QuotaExceeded(str(exc), original=exc) from exc
                if self._is_transient_error(exc) and transient_attempt < self.max_transient_retries:
                    transient_attempt += 1
                    wait_seconds = self.transient_retry_delay * transient_attempt
                    logger.warning(
                        'Gemini transient error (%s). Retry %d/%d after %.1fs',
                        getattr(exc, 'code', '503'),
                        transient_attempt,
                        self.max_transient_retries,
                        wait_seconds,
                    )
                    if wait_seconds > 0:
                        time.sleep(wait_seconds)
                    continue
                logger.warning('Gemini API error: %s', exc)
                raise ProviderError(str(exc), original=exc) from exc
            except TimeoutError as exc:
                raise ProviderTimeout('Gemini timeout.', original=exc) from exc
            except Exception as exc:
                logger.exception('Unexpected error calling Gemini')
                raise ProviderError(str(exc), original=exc) from exc

        latency_ms = int((time.time() - start) * 1000)
        return self._parse_response(response, latency_ms)

    def _parse_response(self, response, latency_ms: int) -> LLMResult:
        text = ''
        tool_calls = []
        prompt_tokens = None
        completion_tokens = None

        if response.usage_metadata:
            prompt_tokens = getattr(response.usage_metadata, 'prompt_token_count', None)
            completion_tokens = getattr(response.usage_metadata, 'candidates_token_count', None)

        candidate = None
        if response.candidates:
            candidate = response.candidates[0]

        if candidate and candidate.content and candidate.content.parts:
            for part in candidate.content.parts:
                if part.text:
                    text += part.text
                function_call = getattr(part, 'function_call', None)
                if function_call:
                    tool_calls.append({
                        'name': function_call.name,
                        'arguments': dict(function_call.args or {}),
                        '_raw_part': part.to_json_dict(),
                    })

        return LLMResult(
            text=text.strip(),
            tool_calls=tool_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            model_name=self.model,
            latency_ms=latency_ms,
            raw=response,
        )
