"""Rate limit đơn giản cho chatbot theo user hoặc session."""

import time

from django.conf import settings
from django.core.cache import cache

from chatbot.context import ChatContext

RATE_LIMIT_PER_HOUR = getattr(settings, 'CHATBOT_RATE_LIMIT_PER_HOUR', 20)
WINDOW_SECONDS = 3600


def _rate_limit_key(ctx: ChatContext):
    if ctx.is_authenticated:
        return f'chatbot:rate_limit:user:{ctx.user.pk}'
    return f'chatbot:rate_limit:session:{ctx.session_id or "anonymous"}'


def check_rate_limit(ctx: ChatContext):
    """Trả dict {'allowed': bool, 'remaining': int, 'retry_after': int}."""
    if not RATE_LIMIT_PER_HOUR:
        return {'allowed': True, 'remaining': 0, 'retry_after': 0}

    key = _rate_limit_key(ctx)
    now = int(time.time())
    window_start = now - WINDOW_SECONDS

    # Sử dụng danh sách timestamp đơn giản trong cache.
    timestamps = cache.get(key) or []
    # Lọc bỏ timestamp cũ
    timestamps = [ts for ts in timestamps if ts > window_start]

    if len(timestamps) >= RATE_LIMIT_PER_HOUR:
        retry_after = max(timestamps[0] + WINDOW_SECONDS - now, 1)
        return {'allowed': False, 'remaining': 0, 'retry_after': retry_after}

    timestamps.append(now)
    cache.set(key, timestamps, WINDOW_SECONDS)
    remaining = RATE_LIMIT_PER_HOUR - len(timestamps)
    return {'allowed': True, 'remaining': remaining, 'retry_after': 0}
