"""API views cho chatbot widget."""

import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from chatbot.context import ChatContext
from chatbot.engine import ChatEngine
from chatbot.models import Conversation, Message
from chatbot.throttling import check_rate_limit

logger = logging.getLogger(__name__)


def _json_body(request):
    try:
        if request.content_type == 'application/json' or request.body:
            return json.loads(request.body)
    except json.JSONDecodeError:
        pass
    return {}


def _conversation_for_request(request, conversation_id=None):
    if conversation_id:
        try:
            conversation = Conversation.objects.get(pk=conversation_id)
        except Conversation.DoesNotExist:
            return None

        if request.user.is_authenticated:
            if conversation.user_id == request.user.pk:
                return conversation
        elif conversation.session_id == request.session.session_key:
            return conversation
        return None

    return None


def _chatbot_enabled():
    from django.conf import settings
    return getattr(settings, 'CHATBOT_ENABLED', True)


def _rate_limited_response(rate_limit, status=429):
    return JsonResponse(
        {
            'error': 'Bạn đã gửi quá nhiều tin nhắn. Hãy thử lại sau ít phút nhé.',
            'reply': 'Bạn đã gửi quá nhiều tin nhắn. Hãy thử lại sau ít phút nhé.',
            'retry_after': rate_limit['retry_after'],
        },
        status=status,
    )


@ensure_csrf_cookie
@require_POST
def chat_api(request):
    if not _chatbot_enabled():
        return JsonResponse(
            {'error': 'Chatbot hiện đang tắt.', 'reply': 'Chatbot hiện đang tắt.'},
            status=503,
        )

    if not request.session.session_key:
        request.session.save()

    data = _json_body(request)
    message = (data.get('message') or '').strip()
    if not message:
        return JsonResponse({'error': 'Tin nhắn không được để trống.'}, status=400)

    page_context = data.get('page_context') or {}
    if isinstance(page_context, str):
        try:
            page_context = json.loads(page_context)
        except json.JSONDecodeError:
            page_context = {}

    ctx = ChatContext.from_request(request, page_context=page_context)

    rate_limit = check_rate_limit(ctx)
    if not rate_limit['allowed']:
        return _rate_limited_response(rate_limit)

    conversation_id = data.get('conversation_id')
    conversation = _conversation_for_request(request, conversation_id)

    if conversation is None:
        conversation = Conversation.objects.create(
            user=request.user if request.user.is_authenticated else None,
            session_id=request.session.session_key if not request.user.is_authenticated else '',
        )

    engine = ChatEngine()
    try:
        response = engine.process(message, conversation, ctx, page_context=page_context)
    except Exception:
        logger.exception('Chat engine failed')
        return JsonResponse(
            {
                'error': 'Có lỗi xảy ra. Bạn thử lại sau nhé.',
                'reply': 'Có lỗi xảy ra. Bạn thử lại sau nhé.',
                'conversation_id': conversation.pk,
            },
            status=503,
        )

    response['rate_limit'] = {
        'remaining': rate_limit['remaining'],
        'retry_after': rate_limit['retry_after'],
    }
    return JsonResponse(response)


@ensure_csrf_cookie
@require_GET
def history_api(request):
    conversation_id = request.GET.get('conversation_id')
    if not conversation_id:
        return JsonResponse({'error': 'Thiếu conversation_id.'}, status=400)

    conversation = _conversation_for_request(request, conversation_id)
    if conversation is None:
        return JsonResponse({'error': 'Hội thoại không tồn tại.'}, status=404)

    messages = conversation.messages.filter(
        role__in=[Message.ROLE_USER, Message.ROLE_ASSISTANT]
    ).order_by('created_at', 'id')

    return JsonResponse(
        {
            'conversation_id': conversation.pk,
            'messages': [
                {
                    'role': message.role,
                    'content': message.content,
                    'products': message.products,
                    'comparison': message.comparison,
                    'created_at': message.created_at.isoformat(),
                }
                for message in messages
            ],
        }
    )


@ensure_csrf_cookie
@require_POST
def new_conversation_api(request):
    if not _chatbot_enabled():
        return JsonResponse(
            {'error': 'Chatbot hiện đang tắt.', 'reply': 'Chatbot hiện đang tắt.'},
            status=503,
        )

    if not request.session.session_key:
        request.session.save()

    conversation = Conversation.objects.create(
        user=request.user if request.user.is_authenticated else None,
        session_id=request.session.session_key if not request.user.is_authenticated else '',
    )
    return JsonResponse({'conversation_id': conversation.pk})
