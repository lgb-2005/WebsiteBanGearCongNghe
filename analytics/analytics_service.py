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
