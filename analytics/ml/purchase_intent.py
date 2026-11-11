"""Request-scoped ML advice; importing this module never loads sklearn/joblib.

Selectors may only access the browser's guest session, the authenticated user's
sessions, or staff-authorized sessions. Prediction failures degrade to unavailable.
"""
from copy import deepcopy
import json
import hashlib
import logging
import math
from time import perf_counter

from .config import BEST_MODEL_META_PATH, BEST_MODEL_PATH

logger = logging.getLogger(__name__)
_LABELS = {'high': 'Khả năng mua cao', 'medium': 'Đang cân nhắc', 'low': 'Mới tham khảo'}


def _authenticated(user):
    return bool(user is not None and getattr(user, 'is_authenticated', False))


def resolve_analytics_session(request=None, session_id=None, user=None):
    from analytics.models import Session

    actor = getattr(request, 'user', None) if request is not None else user
    authenticated = _authenticated(actor)
    staff = authenticated and actor.is_staff
    browser_sid = request.session.get('analytics_session_id') if request is not None else None

    def allowed(session):
        if session is None:
            return False
        if staff or (authenticated and session.user_id == actor.pk):
            return True
        return (str(session.pk) == str(browser_sid) and
                (session.user_id is None or (authenticated and session.user_id == actor.pk)))

    if session_id is not None:
        session = Session.objects.filter(pk=str(session_id)).first()
        return session if allowed(session) else None
    if user is not None and (not authenticated or (user.pk != actor.pk and not staff)):
        return None
    if browser_sid and user is None:
        session = Session.objects.filter(pk=str(browser_sid)).first()
        if allowed(session):
            return session
    selected_user = user or (actor if authenticated else None)
    if selected_user is not None:
        return Session.objects.filter(user=selected_user).order_by('-updated_at', '-created_at', '-pk').first()
    return None


def _metadata():
    try:
        data = json.loads(BEST_MODEL_META_PATH.read_text(encoding='utf-8'))
        threshold = float(data['optimal_threshold'])
        if not math.isfinite(threshold) or not 0 < threshold <= 1:
            raise ValueError('Invalid threshold')
        return threshold, str(data.get('champion_model_name', 'unknown'))
    except (OSError, ValueError, TypeError, KeyError):
        return 0.31, 'unknown'


def unavailable_payload(reason='no_session', session_id=None):
    threshold, model_name = _metadata()
    return {
        'available': False, 'reason': reason, 'user_session': str(session_id) if session_id else None,
        'purchase_probability': 0.0, 'purchase_probability_pct': 0.0,
        'will_purchase': False, 'intent_level': 'low', 'intent_label_vi': _LABELS['low'],
        'optimal_threshold': threshold, 'champion_model_name': model_name,
        'behavior_summary': {},
        'consultation_strategy': 'Chưa có dự đoán đáng tin cậy. Hãy tư vấn theo yêu cầu khách đã nêu, không suy diễn khả năng mua.',
    }


def build_consultation_strategy(prediction_result):
    if not prediction_result.get('available', True):
        return 'Chưa có dự đoán đáng tin cậy. Hãy tư vấn theo yêu cầu khách đã nêu, không suy diễn khả năng mua.'
    level = prediction_result.get('intent_level', 'low')
    behavior = prediction_result.get('behavior_summary', prediction_result.get('features', {}))
    cart = int(behavior.get('effective_cart_count', behavior.get('cart_count', 0)) or 0)
    views = int(behavior.get('view_count', 0) or 0)
    repeat = float(behavior.get('repeat_view_ratio', 0) or 0)
    prefix = f'Tín hiệu tham khảo: {views} lượt xem, {cart} lượt thêm giỏ ròng'
    if repeat > 0:
        prefix += ', có xem lại sản phẩm'
    if level == 'high':
        advice = 'Tư vấn ngắn gọn, xác nhận giá/tồn kho từ tool, giúp khách đi tới lựa chọn khi nhu cầu đã đủ rõ.'
    elif level == 'medium':
        advice = 'Ưu tiên tháo gỡ phân vân, so sánh 2–3 lựa chọn phù hợp ngân sách và nhu cầu đã nêu.'
    else:
        advice = 'Gợi mở nhu cầu bằng một câu hỏi ngắn nếu còn thiếu thông tin, tránh gây áp lực đặt mua.'
    return prefix + '. ' + advice + ' Xác suất là ước lượng, không thay thế yêu cầu thực tế của khách và không cho phép bịa ưu đãi.'


def get_customer_purchase_intent_payload(request=None, session_id=None, user_id=None):
    from accounts.models import User

    start = perf_counter()
    selected_user = None
    if user_id is not None:
        actor = getattr(request, 'user', None)
        if not _authenticated(actor) or (not actor.is_staff and actor.pk != user_id):
            return unavailable_payload('not_found')
        selected_user = User.objects.filter(pk=user_id).first()
        if selected_user is None:
            return unavailable_payload('not_found')
    session = resolve_analytics_session(request, session_id=session_id, user=selected_user)
    if session is None:
        return unavailable_payload('not_found' if session_id is not None else 'no_session')
    relevant = ('view_product', 'add_to_cart', 'remove_from_cart')
    from django.core.cache import cache
    from django.db.models import Count, Max, Q
    stamp = session.event_set.aggregate(total=Count('pk'), last_id=Max('pk'),
                                        updated=Max('updated_at'), relevant=Count('pk', filter=Q(event_type__in=relevant)))
    if not stamp['relevant']:
        return unavailable_payload('no_activity', session.pk)
    try:
        # Append/delete changes count; normal Event.save edits change updated_at.
        # Bulk edits of historical events may remain cached for at most 30s.
        model_stamp = [BEST_MODEL_PATH.stat().st_mtime_ns, BEST_MODEL_META_PATH.stat().st_mtime_ns]
        digest = hashlib.sha256(json.dumps([str(session.pk), session.user_id, stamp, model_stamp], default=str, sort_keys=True).encode()).hexdigest()
        cache_key = f'analytics:purchase-intent:v1:{digest}'
        cached = cache.get(cache_key)
        if cached is not None:
            cached['cache_hit'] = True
            cached['inference_latency_ms'] = round((perf_counter() - start) * 1000, 2)
            return deepcopy(cached)
        from .predictor import predict_session_purchase_intent
        from django.conf import settings
        from zoneinfo import ZoneInfo
        events = list(session.event_set.select_related('product', 'product__category').order_by('created_at', 'pk'))
        # Django's naive live timestamps are local time; training hours are UTC.
        # Convert only the in-memory instances, never persist modified timestamps.
        for event in events:
            if event.created_at.tzinfo is None:
                event.created_at = event.created_at.replace(tzinfo=ZoneInfo(settings.TIME_ZONE))
        predicted = predict_session_purchase_intent(events)
        probability = float(predicted['purchase_probability'])
        threshold = float(predicted['optimal_threshold'])
        if not math.isfinite(probability) or not 0 <= probability <= 1 or not 0 < threshold <= 1:
            raise ValueError('Invalid prediction output')
        features = predicted['features']
        summary = {key: features[key] for key in ('view_count', 'unique_products', 'unique_categories',
                   'session_duration_sec', 'repeat_view_ratio', 'cart_to_view_ratio')}
        summary.update({
            'raw_add_to_cart_count': predicted.get('raw_add_to_cart_count', features['cart_count']),
            'raw_remove_from_cart_count': predicted.get('raw_remove_from_cart_count', features['remove_cart_count']),
            'effective_cart_count': predicted.get('effective_cart_count', features['cart_count']),
            'avg_price_usd': features['avg_price'],
        })
        if summary['view_count'] == summary['raw_add_to_cart_count'] == summary['raw_remove_from_cart_count'] == 0:
            return unavailable_payload('no_pre_checkout_activity', session.pk)
        level = 'high' if probability >= threshold else 'medium' if probability >= threshold * 0.5 else 'low'
        payload = {
            'available': True, 'reason': None, 'user_session': str(session.pk),
            'purchase_probability': probability, 'purchase_probability_pct': round(probability * 100, 2),
            'will_purchase': probability >= threshold, 'intent_level': level, 'intent_label_vi': _LABELS[level],
            'optimal_threshold': threshold, 'champion_model_name': predicted['champion_model_name'],
            'behavior_summary': summary,
        }
        payload['consultation_strategy'] = build_consultation_strategy(payload)
        payload['inference_latency_ms'] = round((perf_counter() - start) * 1000, 2)
        payload['cache_hit'] = False
        cache.set(cache_key, payload, timeout=30)
        return deepcopy(payload)
    except Exception as exc:
        # No provider secrets, paths or traceback are exposed to the client/LLM.
        logger.warning('Purchase-intent prediction unavailable: %s', type(exc).__name__)
        return unavailable_payload('model_unavailable', session.pk)
