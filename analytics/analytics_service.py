"""
Customer Behavior Analytics Service — PHASE 6

All functions are read-only. No business logic is modified.
Performance notes:
- Each function issues the minimum number of queries (annotate/aggregate over values).
- Session-based funnels use distinct session counts, not event counts.
- Shared helper `_apply_date_filter` from dashboard.py is reused.
"""

from collections import defaultdict
from decimal import Decimal

from django.db.models import Avg, Count, F, Q, Sum
from django.utils import timezone

from analytics.dashboard import (
    _apply_date_filter,
    _date_to_period_key,
    _dates_for_qs,
    _period_key_label,
    get_event_distribution,       # reused for Section 5
    get_top_viewed_products,      # reused for Section 6
    get_top_cart_products,        # reused for Section 6
)


# ---------------------------------------------------------------------------
# Section 1 — Conversion Funnel (Session-based)
# ---------------------------------------------------------------------------

def get_conversion_funnel(date_from=None, date_to=None):
    """
    Returns session counts at each funnel step.
    Each session counted at most ONCE per step.
    Steps: Sessions → View Product → Add To Cart → Checkout → Paid
    """
    try:
        from analytics.models import Session, Event
        from orders.models import Order

        session_qs = Session.objects.all()
        event_qs   = Event.objects.all()
        session_qs = _apply_date_filter(session_qs, date_from, date_to)
        event_qs   = _apply_date_filter(event_qs, date_from, date_to)

        total_sessions = session_qs.count()

        # Sessions that fired each event_type (distinct)
        def _session_count(event_type):
            return (
                event_qs
                .filter(event_type=event_type)
                .values('session_id')
                .distinct()
                .count()
            )

        view_sessions     = _session_count('view_product')
        cart_sessions     = _session_count('add_to_cart')
        checkout_sessions = _session_count('checkout')

        # Paid = completed orders in the same date range
        paid_qs = _apply_date_filter(
            __import__('orders.models', fromlist=['Order']).Order.objects.filter(status='completed'),
            date_from, date_to
        )
        paid_orders = paid_qs.count()

        def _rate(numerator, denominator):
            if denominator and denominator > 0:
                return round(numerator / denominator * 100, 1)
            return None

        steps = [
            {'label': 'Sessions',      'count': total_sessions,    'rate': None},
            {'label': 'View Product',  'count': view_sessions,     'rate': _rate(view_sessions,     total_sessions)},
            {'label': 'Add To Cart',   'count': cart_sessions,     'rate': _rate(cart_sessions,     view_sessions)},
            {'label': 'Checkout',      'count': checkout_sessions, 'rate': _rate(checkout_sessions, cart_sessions)},
            {'label': 'Paid',          'count': paid_orders,       'rate': _rate(paid_orders,       checkout_sessions)},
        ]
        return steps
    except Exception as e:
        print(f'[analytics_service] get_conversion_funnel error: {e}')
        return []


# ---------------------------------------------------------------------------
# Section 2 — Customer Journey
# ---------------------------------------------------------------------------

def get_customer_journey(date_from=None, date_to=None):
    """
    Metrics derivable from existing data only:
    - Avg events per session
    - Avg product views per session (before any checkout event in that session)
    - Avg add-to-cart per session (before checkout)

    No session duration — not tracked.
    No checkout time  — not tracked.
    """
    try:
        from analytics.models import Event, Session

        event_qs = Event.objects.all()
        event_qs = _apply_date_filter(event_qs, date_from, date_to)

        # Avg events per session — one aggregate query
        agg = (
            event_qs
            .values('session_id')
            .annotate(event_count=Count('id'))
            .aggregate(avg_events=Avg('event_count'))
        )
        avg_events_per_session = round(float(agg['avg_events'] or 0), 2)

        # Sessions that had a checkout event
        checkout_session_ids = list(
            event_qs
            .filter(event_type='checkout')
            .values_list('session_id', flat=True)
            .distinct()
        )

        avg_views_before_checkout    = 0.0
        avg_cart_before_checkout     = 0.0

        if checkout_session_ids:
            # All events in those sessions (same date filter already applied)
            session_events = (
                event_qs
                .filter(session_id__in=checkout_session_ids)
                .values('session_id', 'event_type')
                .annotate(cnt=Count('id'))
            )
            # Aggregate per session
            view_map = defaultdict(int)
            cart_map = defaultdict(int)
            for row in session_events:
                if row['event_type'] == 'view_product':
                    view_map[row['session_id']] += row['cnt']
                elif row['event_type'] == 'add_to_cart':
                    cart_map[row['session_id']] += row['cnt']

            n = len(checkout_session_ids)
            avg_views_before_checkout = round(sum(view_map.values()) / n, 2) if n else 0.0
            avg_cart_before_checkout  = round(sum(cart_map.values()) / n, 2) if n else 0.0

        return {
            'avg_events_per_session':      avg_events_per_session,
            'avg_views_before_checkout':   avg_views_before_checkout,
            'avg_cart_before_checkout':    avg_cart_before_checkout,
            'checkout_sessions_count':     len(checkout_session_ids),
        }
    except Exception as e:
        print(f'[analytics_service] get_customer_journey error: {e}')
        return {
            'avg_events_per_session':    0.0,
            'avg_views_before_checkout': 0.0,
            'avg_cart_before_checkout':  0.0,
            'checkout_sessions_count':   0,
        }


# ---------------------------------------------------------------------------
# Section 3 — Product Conversion
# ---------------------------------------------------------------------------

MIN_VIEWS_FOR_CONVERSION_SORT = 10


def _get_category_descendant_ids(category_id):
    from products.models import Category

    category_ids = [category_id]
    parent_ids = [category_id]
    while parent_ids:
        child_ids = list(
            Category.objects.filter(parent_id__in=parent_ids).values_list('id', flat=True)
        )
        category_ids.extend(child_ids)
        parent_ids = child_ids
    return category_ids


def get_product_conversion(
    limit=10,
    date_from=None,
    date_to=None,
    product_query=None,
    category_id=None,
    sort_by='views_desc',
):
    try:
        from analytics.models import Event
        from products.models import Category, Product

        product_query = ' '.join((product_query or '').split())
        has_product_filter = bool(product_query or category_id)
        product_qs = Product.objects.select_related('category', 'brand')

        if product_query:
            product_qs = product_qs.filter(
                Q(name__icontains=product_query) | Q(product_code__icontains=product_query)
            )

        if category_id:
            if not Category.objects.filter(pk=category_id).exists():
                return []
            product_qs = product_qs.filter(
                category_id__in=_get_category_descendant_ids(category_id)
            )

        event_qs = Event.objects.filter(
            product__isnull=False,
            product_id__in=product_qs.values('id'),
            event_type__in=['view_product', 'add_to_cart', 'checkout'],
        )
        event_qs = _apply_date_filter(event_qs, date_from, date_to)
        rows = event_qs.values('product_id', 'event_type').annotate(cnt=Count('id'))

        data_map = defaultdict(lambda: {'view_product': 0, 'add_to_cart': 0, 'checkout': 0})
        for row in rows:
            data_map[row['product_id']][row['event_type']] = row['cnt']

        if has_product_filter:
            products = list(product_qs)
        else:
            products = list(product_qs.filter(pk__in=data_map.keys()))

        result = []
        for product in products:
            counts = data_map[product.pk]
            views = counts['view_product']
            cart = counts['add_to_cart']
            checkout = counts['checkout']
            result.append({
                'product': product,
                'views': views,
                'cart': cart,
                'checkout': checkout,
                'conv_rate': round(checkout / views * 100, 1) if views else 0.0,
            })

        sort_options = {'views_desc', 'cart_desc', 'checkout_desc', 'conversion_desc', 'conversion_asc'}
        if sort_by not in sort_options:
            sort_by = 'views_desc'

        if sort_by == 'views_desc':
            result.sort(key=lambda row: (row['views'], row['checkout']), reverse=True)
        elif sort_by == 'cart_desc':
            result.sort(key=lambda row: (row['cart'], row['views']), reverse=True)
        elif sort_by == 'checkout_desc':
            result.sort(key=lambda row: (row['checkout'], row['views']), reverse=True)
        elif sort_by == 'conversion_desc':
            result.sort(
                key=lambda row: (
                    row['views'] >= MIN_VIEWS_FOR_CONVERSION_SORT,
                    row['conv_rate'],
                    row['views'],
                ),
                reverse=True,
            )
        else:
            result.sort(
                key=lambda row: (
                    not (row['views'] >= MIN_VIEWS_FOR_CONVERSION_SORT),
                    row['conv_rate'],
                    -row['views'],
                )
            )

        return result if has_product_filter else result[:limit]
    except Exception as e:
        print(f'[analytics_service] get_product_conversion error: {e}')
        return []


# ---------------------------------------------------------------------------
# Section 4 — Traffic Trend (AnalyticsSession-based)
# ---------------------------------------------------------------------------

def get_traffic_trend(period='day', n=30, date_from=None, date_to=None):
    """
    Sessions over time. Source: AnalyticsSession only.
    Reuses _dates_for_qs / _period_key_label helpers from dashboard.
    """
    try:
        from analytics.models import Session

        base_qs = Session.objects.all()
        base_qs = _apply_date_filter(base_qs, date_from, date_to)

        all_dates = _dates_for_qs(base_qs, period, n)
        period_keys, seen = [], set()
        for d in all_dates:
            key = _date_to_period_key(d, period)
            if key not in seen:
                seen.add(key)
                period_keys.append(key)
        period_keys = list(reversed(period_keys[:n]))

        result = []
        for key in period_keys:
            if period == 'day':
                qs_f = base_qs.filter(created_at__date=key)
            elif period == 'month':
                qs_f = base_qs.filter(created_at__year=key[0], created_at__month=key[1])
            elif period == 'quarter':
                months = [key[1]*3-2, key[1]*3-1, key[1]*3]
                qs_f = base_qs.filter(created_at__year=key[0], created_at__month__in=months)
            elif period == 'year':
                qs_f = base_qs.filter(created_at__year=key[0])
            else:
                continue
            agg = qs_f.aggregate(
                session_count=Count('id'),
                guest_count=Count('id', filter=Q(user__isnull=True)),
                user_count=Count('id', filter=Q(user__isnull=False)),
            )
            result.append({
                'period_label':  _period_key_label(key, period),
                'session_count': agg['session_count'] or 0,
                'guest_count':   agg['guest_count']   or 0,
                'user_count':    agg['user_count']    or 0,
            })
        return result
    except Exception as e:
        print(f'[analytics_service] get_traffic_trend error: {e}')
        return []


# ---------------------------------------------------------------------------
# Section 5 — Event Distribution  [REUSED from dashboard.get_event_distribution]
# ---------------------------------------------------------------------------
# Caller: just call analytics.dashboard.get_event_distribution(date_from, date_to)


# ---------------------------------------------------------------------------
# Section 6 — Product Interest
# ---------------------------------------------------------------------------

def get_product_interest(limit=10, date_from=None, date_to=None):
    """
    Returns top viewed, top add-to-cart, top checkout products.
    Reuses get_top_viewed_products and get_top_cart_products from dashboard.
    Checkout top computed here.
    """
    try:
        from analytics.models import Event
        from products.models import Product

        top_viewed = get_top_viewed_products(limit=limit, date_from=date_from, date_to=date_to)
        top_cart   = get_top_cart_products(limit=limit, date_from=date_from, date_to=date_to)

        # Top checkout products
        qs = Event.objects.filter(event_type='checkout', product__isnull=False)
        qs = _apply_date_filter(qs, date_from, date_to)
        rows = (
            qs
            .values('product')
            .annotate(checkout_count=Count('id'))
            .order_by('-checkout_count')[:limit]
        )
        product_ids = [r['product'] for r in rows]
        product_map = {
            p.pk: p for p in Product.objects.filter(pk__in=product_ids).select_related('brand')
        }
        top_checkout = [
            {'product': product_map[r['product']], 'checkout_count': r['checkout_count']}
            for r in rows if r['product'] in product_map
        ]

        return {
            'top_viewed':   top_viewed,
            'top_cart':     top_cart,
            'top_checkout': top_checkout,
        }
    except Exception as e:
        print(f'[analytics_service] get_product_interest error: {e}')
        return {'top_viewed': [], 'top_cart': [], 'top_checkout': []}


# ---------------------------------------------------------------------------
# Section 7 — Abandoned Cart (Session-based)
# ---------------------------------------------------------------------------

def get_abandoned_cart(date_from=None, date_to=None):
    """
    Abandoned = Sessions with add_to_cart MINUS sessions with checkout.
    Uses Session distinct counts only — no event multiplication.
    """
    try:
        from analytics.models import Event

        event_qs = Event.objects.all()
        event_qs = _apply_date_filter(event_qs, date_from, date_to)

        cart_session_ids = set(
            event_qs
            .filter(event_type='add_to_cart')
            .values_list('session_id', flat=True)
            .distinct()
        )
        checkout_session_ids = set(
            event_qs
            .filter(event_type='checkout')
            .values_list('session_id', flat=True)
            .distinct()
        )

        cart_sessions      = len(cart_session_ids)
        checkout_sessions  = len(checkout_session_ids)
        abandoned_sessions = len(cart_session_ids - checkout_session_ids)
        abandoned_rate     = round(abandoned_sessions / cart_sessions * 100, 1) if cart_sessions > 0 else 0.0

        return {
            'cart_sessions':      cart_sessions,
            'checkout_sessions':  checkout_sessions,
            'abandoned_sessions': abandoned_sessions,
            'abandoned_rate':     abandoned_rate,
        }
    except Exception as e:
        print(f'[analytics_service] get_abandoned_cart error: {e}')
        return {
            'cart_sessions': 0, 'checkout_sessions': 0,
            'abandoned_sessions': 0, 'abandoned_rate': 0.0,
        }


# ---------------------------------------------------------------------------
# Section 8 — Session Analytics
# ---------------------------------------------------------------------------

def get_session_analytics(date_from=None, date_to=None):
    """
    Total, guest, user sessions and avg events/session.
    No session duration — not tracked.
    """
    try:
        from analytics.models import Session, Event

        session_qs = Session.objects.all()
        session_qs = _apply_date_filter(session_qs, date_from, date_to)

        agg = session_qs.aggregate(
            total=Count('id'),
            guest=Count('id', filter=Q(user__isnull=True)),
            user=Count('id', filter=Q(user__isnull=False)),
        )
        total_sessions = agg['total'] or 0
        guest_sessions = agg['guest'] or 0
        user_sessions  = agg['user']  or 0

        # Avg events per session
        event_qs = Event.objects.all()
        event_qs = _apply_date_filter(event_qs, date_from, date_to)

        avg_agg = (
            event_qs
            .values('session_id')
            .annotate(cnt=Count('id'))
            .aggregate(avg=Avg('cnt'))
        )
        avg_events = round(float(avg_agg['avg'] or 0), 2)

        return {
            'total_sessions': total_sessions,
            'guest_sessions': guest_sessions,
            'user_sessions':  user_sessions,
            'avg_events_per_session': avg_events,
        }
    except Exception as e:
        print(f'[analytics_service] get_session_analytics error: {e}')
        return {
            'total_sessions': 0, 'guest_sessions': 0,
            'user_sessions': 0, 'avg_events_per_session': 0.0,
        }


# ---------------------------------------------------------------------------
# Section 9 — ML Purchase Intent Dashboard (Admin Analytics)
# ---------------------------------------------------------------------------

def get_ml_purchase_intent_dashboard(
    request=None,
    limit=15,
    date_from=None,
    date_to=None,
    intent_filter='all',
    search_query='',
):
    """
    Tổng hợp dữ liệu Dự đoán Ý định Mua hàng (ML Purchase Intent) cho trang
    /admin-dashboard/analytics/.
    - Chỉ đọc dữ liệu (Read-only), tận dụng cache 30s của get_customer_purchase_intent_payload.
    - Trả về 4 chỉ số KPI phân tầng ý định mua + danh sách phiên đã chấm điểm kèm
      thông tin khách hàng, trạng thái phiên Chatbot và chiến lược tư vấn.
    """
    from types import SimpleNamespace

    search_query = ' '.join((search_query or '').split())
    intent_filter = (intent_filter or 'all').strip().lower()
    if intent_filter not in {'all', 'high', 'medium', 'low'}:
        intent_filter = 'all'

    try:
        limit = max(1, int(limit or 15))
    except (TypeError, ValueError):
        limit = 15

    optimal_threshold = 0.31
    champion_model_name = 'HistGradientBoosting'
    try:
        from analytics.ml.purchase_intent import _metadata
        meta_threshold, meta_model = _metadata()
        if meta_threshold and 0 < float(meta_threshold) <= 1:
            optimal_threshold = float(meta_threshold)
        if meta_model and meta_model != 'unknown':
            champion_model_name = str(meta_model)
    except Exception:
        pass

    optimal_threshold_pct = round(optimal_threshold * 100, 1)
    medium_threshold_pct = round(optimal_threshold * 50, 1)

    default_payload = {
        'champion_model_name': champion_model_name,
        'optimal_threshold': optimal_threshold,
        'optimal_threshold_pct': optimal_threshold_pct,
        'medium_threshold_pct': medium_threshold_pct,
        'total_scored_sessions': 0,
        'high_intent_count': 0,
        'medium_intent_count': 0,
        'low_intent_count': 0,
        'high_intent_rate': 0.0,
        'medium_intent_rate': 0.0,
        'low_intent_rate': 0.0,
        'avg_probability_pct': 0.0,
        'intent_filter': intent_filter,
        'search_query': search_query,
        'is_filtered': bool(search_query or intent_filter != 'all'),
        'sessions': [],
    }

    try:
        from analytics.models import Event, Session
        from analytics.ml.purchase_intent import get_customer_purchase_intent_payload

        relevant_types = ('view_product', 'add_to_cart', 'remove_from_cart')
        event_qs = _apply_date_filter(
            Event.objects.filter(event_type__in=relevant_types),
            date_from,
            date_to,
        )
        active_session_ids = event_qs.values_list('session_id', flat=True).distinct()
        session_qs = Session.objects.select_related('user').filter(pk__in=active_session_ids)

        if search_query:
            q_filter = (
                Q(id__icontains=search_query)
                | Q(user__email__icontains=search_query)
                | Q(user__name__icontains=search_query)
                | Q(device_type__icontains=search_query)
            )
            if search_query.isdigit():
                q_filter |= Q(user_id=int(search_query))
            session_qs = session_qs.filter(q_filter)

        max_scan = max(limit * 4, 60)
        candidate_sessions = list(session_qs.order_by('-updated_at', '-created_at')[:max_scan])
        if not candidate_sessions:
            return default_payload

        actor = getattr(request, 'admin_user', None) or getattr(request, 'user', None)
        if (
            actor is None
            or not getattr(actor, 'is_authenticated', False)
            or not getattr(actor, 'is_staff', False)
        ):
            actor = SimpleNamespace(pk=0, is_authenticated=True, is_staff=True)
        scoring_request = SimpleNamespace(
            user=actor,
            session=getattr(request, 'session', {}) if request is not None else {},
        )

        user_chat_map = {}
        session_chat_map = {}
        try:
            from chatbot.models import ChatTurnLog, Conversation

            user_ids = {s.user_id for s in candidate_sessions if s.user_id}
            if user_ids:
                convs = (
                    Conversation.objects
                    .filter(user_id__in=user_ids)
                    .annotate(
                        turn_count=Count('turn_logs', distinct=True),
                        user_msg_count=Count(
                            'messages',
                            filter=Q(messages__role='user'),
                            distinct=True,
                        ),
                    )
                    .order_by('-updated_at')
                )
                for conv in convs:
                    turns = conv.turn_count or conv.user_msg_count or 0
                    existing = user_chat_map.get(conv.user_id)
                    if existing is None:
                        user_chat_map[conv.user_id] = {
                            'conversation_id': conv.pk,
                            'turn_count': turns,
                        }
                    else:
                        existing['turn_count'] += turns

            candidate_sid_set = {str(s.pk) for s in candidate_sessions}
            if candidate_sid_set:
                recent_logs = (
                    ChatTurnLog.objects
                    .filter(conversation__isnull=False, resolved_aliases__isnull=False)
                    .order_by('-created_at')[:300]
                )
                for log in recent_logs:
                    aliases = log.resolved_aliases if isinstance(log.resolved_aliases, dict) else {}
                    ml_snap = aliases.get('_ml_purchase_intent')
                    if isinstance(ml_snap, dict):
                        snap_sid = str(ml_snap.get('user_session') or '')
                        if snap_sid in candidate_sid_set:
                            info = session_chat_map.setdefault(
                                snap_sid,
                                {'conversation_id': log.conversation_id, 'turn_count': 0},
                            )
                            info['turn_count'] += 1
        except Exception:
            pass

        total_scored_sessions = 0
        high_intent_count = 0
        medium_intent_count = 0
        low_intent_count = 0
        prob_sum = 0.0
        sessions = []

        for session in candidate_sessions:
            sid_str = str(session.pk)
            payload = get_customer_purchase_intent_payload(
                scoring_request,
                session_id=sid_str,
            )
            if not payload.get('available'):
                continue

            level = payload.get('intent_level', 'low')
            prob_pct = float(payload.get('purchase_probability_pct', 0.0) or 0.0)

            total_scored_sessions += 1
            prob_sum += prob_pct
            if level == 'high':
                high_intent_count += 1
            elif level == 'medium':
                medium_intent_count += 1
            else:
                low_intent_count += 1

            if intent_filter in ('high', 'medium', 'low') and level != intent_filter:
                continue

            if len(sessions) >= limit:
                continue

            behavior = payload.get('behavior_summary') or {}
            chat_info = session_chat_map.get(sid_str) or (
                user_chat_map.get(session.user_id) if session.user_id else None
            ) or {}
            has_chat = bool(chat_info.get('conversation_id') and chat_info.get('turn_count', 0) > 0)
            avg_price_usd = float(behavior.get('avg_price_usd', 0.0) or 0.0)

            sessions.append({
                'session_id': sid_str,
                'short_session_id': f'{sid_str[:8]}...',
                'updated_at': session.updated_at,
                'created_at': session.created_at,
                'device_type': session.device_type or 'desktop',
                'is_authenticated_user': bool(session.user_id),
                'user_id': session.user_id,
                'customer_name': (
                    (session.user.name or session.user.email)
                    if session.user else 'Khách vãng lai (Guest)'
                ),
                'customer_email': session.user.email if session.user else '',
                'has_chatbot_session': has_chat,
                'conversation_id': chat_info.get('conversation_id'),
                'chat_turn_count': int(chat_info.get('turn_count', 0) or 0),
                'purchase_probability': payload.get('purchase_probability', 0.0),
                'purchase_probability_pct': round(prob_pct, 2),
                'will_purchase': bool(payload.get('will_purchase', False)),
                'intent_level': level,
                'intent_label_vi': payload.get('intent_label_vi', 'Mới tham khảo'),
                'view_count': int(behavior.get('view_count', 0) or 0),
                'unique_products': int(behavior.get('unique_products', 0) or 0),
                'effective_cart_count': int(behavior.get('effective_cart_count', 0) or 0),
                'raw_add_to_cart_count': int(behavior.get('raw_add_to_cart_count', 0) or 0),
                'raw_remove_from_cart_count': int(behavior.get('raw_remove_from_cart_count', 0) or 0),
                'session_duration_sec': round(float(behavior.get('session_duration_sec', 0.0) or 0.0)),
                'avg_price_usd': round(avg_price_usd, 2),
                'avg_price_vnd': int(round(avg_price_usd * 25000)),
                'consultation_strategy': payload.get('consultation_strategy', ''),
            })

        return {
            'champion_model_name': champion_model_name,
            'optimal_threshold': optimal_threshold,
            'optimal_threshold_pct': optimal_threshold_pct,
            'medium_threshold_pct': medium_threshold_pct,
            'total_scored_sessions': total_scored_sessions,
            'high_intent_count': high_intent_count,
            'medium_intent_count': medium_intent_count,
            'low_intent_count': low_intent_count,
            'high_intent_rate': (
                round(high_intent_count / total_scored_sessions * 100, 1)
                if total_scored_sessions else 0.0
            ),
            'medium_intent_rate': (
                round(medium_intent_count / total_scored_sessions * 100, 1)
                if total_scored_sessions else 0.0
            ),
            'low_intent_rate': (
                round(low_intent_count / total_scored_sessions * 100, 1)
                if total_scored_sessions else 0.0
            ),
            'avg_probability_pct': (
                round(prob_sum / total_scored_sessions, 2)
                if total_scored_sessions else 0.0
            ),
            'intent_filter': intent_filter,
            'search_query': search_query,
            'is_filtered': bool(search_query or intent_filter != 'all'),
            'sessions': sessions,
        }
    except Exception as e:
        print(f'[analytics_service] get_ml_purchase_intent_dashboard error: {e}')
        return default_payload

