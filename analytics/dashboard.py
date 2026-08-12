from datetime import date
from decimal import Decimal
from collections import defaultdict

from django.db.models import Count, F, Sum
from django.utils import timezone


def _date_to_period_key(d, period):
    if period == 'day':
        return d
    if period == 'month':
        return (d.year, d.month)
    if period == 'quarter':
        return (d.year, (d.month - 1) // 3 + 1)
    if period == 'year':
        return (d.year,)
    return d


def _period_key_label(key, period):
    if period == 'day':
        return key.strftime('%d/%m')
    if period == 'month':
        return f'{key[1]:02d}/{key[0]}'
    if period == 'quarter':
        return f'Q{key[1]}-{key[0]}'
    if period == 'year':
        return str(key[0])
    return str(key)


def _dates_for_qs(qs, period, n):
    kind_map = {'day': 'day', 'month': 'month', 'quarter': 'month', 'year': 'year'}
    kind = kind_map.get(period, 'day')
    return list(qs.dates('created_at', kind, order='DESC')[:n * 4])


def _apply_date_filter(qs, date_from, date_to, field='created_at'):
    if date_from:
        qs = qs.filter(**{f'{field}__date__gte': date_from})
    if date_to:
        qs = qs.filter(**{f'{field}__date__lte': date_to})
    return qs


def get_revenue_stats(period='day', n=30):
    try:
        from orders.models import Order
        base_qs = Order.objects.filter(status='completed')
        all_dates = _dates_for_qs(base_qs, period, n)
        period_keys = []
        seen = set()
        for d in all_dates:
            key = _date_to_period_key(d, period)
            if key not in seen:
                seen.add(key)
                period_keys.append(key)
        period_keys = period_keys[:n]
        period_keys = list(reversed(period_keys))

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
            agg = qs_f.aggregate(revenue=Sum('total_price'), order_count=Count('id'))
            result.append({
                'period_label': _period_key_label(key, period),
                'revenue': agg['revenue'] or Decimal('0'),
                'order_count': agg['order_count'] or 0,
            })
        return result
    except Exception as e:
        print(f'[dashboard] get_revenue_stats error: {e}')
        return []


def get_top_selling_products(limit=10, date_from=None, date_to=None):
    try:
        from orders.models import OrderItem
        qs = OrderItem.objects.filter(order__status='completed')
        qs = _apply_date_filter(qs, date_from, date_to, field='order__created_at')
        rows = (
            qs
            .values('product')
            .annotate(
                total_sold=Sum('quantity'),
                total_revenue=Sum(F('price') * F('quantity')),
            )
            .order_by('-total_sold')[:limit]
        )
        from products.models import Product
        product_ids = [r['product'] for r in rows]
        product_map = {
            p.pk: p
            for p in Product.objects.filter(pk__in=product_ids).select_related('brand')
        }
        result = []
        for row in rows:
            product = product_map.get(row['product'])
            if product:
                result.append({
                    'product': product,
                    'total_sold': row['total_sold'] or 0,
                    'total_revenue': row['total_revenue'] or Decimal('0'),
                })
        return result
    except Exception as e:
        print(f'[dashboard] get_top_selling_products error: {e}')
        return []


def get_top_viewed_products(limit=10, date_from=None, date_to=None):
    try:
        from analytics.models import Event
        from products.models import Product
        qs = Event.objects.filter(event_type='view_product', product__isnull=False)
        qs = _apply_date_filter(qs, date_from, date_to)
        rows = (
            qs
            .values('product')
            .annotate(view_count=Count('id'))
            .order_by('-view_count')[:limit]
        )
        product_ids = [r['product'] for r in rows]
        product_map = {
            p.pk: p
            for p in Product.objects.filter(pk__in=product_ids).select_related('brand')
        }
        result = []
        for row in rows:
            product = product_map.get(row['product'])
            if product:
                result.append({
                    'product': product,
                    'view_count': row['view_count'] or 0,
                })
        return result
    except Exception as e:
        print(f'[dashboard] get_top_viewed_products error: {e}')
        return []


def get_top_cart_products(limit=10, date_from=None, date_to=None):
    try:
        from analytics.models import Event
        from products.models import Product
        qs = Event.objects.filter(event_type='add_to_cart', product__isnull=False)
        qs = _apply_date_filter(qs, date_from, date_to)
        rows = (
            qs
            .values('product')
            .annotate(add_count=Count('id'))
            .order_by('-add_count')[:limit]
        )
        product_ids = [r['product'] for r in rows]
        product_map = {
            p.pk: p
            for p in Product.objects.filter(pk__in=product_ids).select_related('brand')
        }
        result = []
        for row in rows:
            product = product_map.get(row['product'])
            if product:
                result.append({
                    'product': product,
                    'add_count': row['add_count'] or 0,
                })
        return result
    except Exception as e:
        print(f'[dashboard] get_top_cart_products error: {e}')
        return []


def get_conversion_rate(date_from=None, date_to=None):
    try:
        from analytics.models import Session
        add_qs = Session.objects.filter(event__event_type='add_to_cart')
        checkout_qs = Session.objects.filter(event__event_type='checkout')
        if date_from:
            add_qs = add_qs.filter(event__created_at__date__gte=date_from)
            checkout_qs = checkout_qs.filter(event__created_at__date__gte=date_from)
        if date_to:
            add_qs = add_qs.filter(event__created_at__date__lte=date_to)
            checkout_qs = checkout_qs.filter(event__created_at__date__lte=date_to)
        sessions_with_add = add_qs.distinct().count()
        sessions_with_checkout = checkout_qs.distinct().count()
        rate = round(sessions_with_checkout / sessions_with_add * 100, 2) if sessions_with_add > 0 else 0.0
        return {
            'sessions_with_add': sessions_with_add,
            'sessions_with_checkout': sessions_with_checkout,
            'rate': rate,
        }
    except Exception as e:
        print(f'[dashboard] get_conversion_rate error: {e}')
        return {'sessions_with_add': 0, 'sessions_with_checkout': 0, 'rate': 0.0}


def get_visit_stats(period='day', n=30):
    try:
        from analytics.models import Session
        base_qs = Session.objects.all()
        all_dates = _dates_for_qs(base_qs, period, n)
        period_keys = []
        seen = set()
        for d in all_dates:
            key = _date_to_period_key(d, period)
            if key not in seen:
                seen.add(key)
                period_keys.append(key)
        period_keys = period_keys[:n]
        period_keys = list(reversed(period_keys))

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
            agg = qs_f.aggregate(session_count=Count('id'), unique_users=Count('user', distinct=True))
            result.append({
                'period_label': _period_key_label(key, period),
                'session_count': agg['session_count'] or 0,
                'unique_users': agg['unique_users'] or 0,
            })
        return result
    except Exception as e:
        print(f'[dashboard] get_visit_stats error: {e}')
        return []


def get_store_operations_stats(period='day', date_from=None, date_to=None, top_limit=10):
    try:
        from orders.models import Order
        from products.models import Product, ProductReview
        from accounts.models import User
        from django.db.models import Q

        now = timezone.now()
        today = now.date()

        # --- Order Status Summary (filtered by date range if provided) ---
        order_qs = Order.objects.all()
        order_qs = _apply_date_filter(order_qs, date_from, date_to)

        order_status = order_qs.aggregate(
            pending=Count('id', filter=Q(status='pending')),
            processing=Count('id', filter=Q(status='processing')),
            completed=Count('id', filter=Q(status='completed')),
            cancelled=Count('id', filter=Q(status='cancelled')),
        )

        # --- Customer KPI ---
        customer_qs = User.objects.filter(is_staff=False, is_superuser=False)
        new_customers_qs = _apply_date_filter(customer_qs, date_from, date_to, field='date_joined')
        new_customers = new_customers_qs.count()

        purchasing_qs = order_qs.values('customer').distinct()
        purchasing_customers = purchasing_qs.count()

        # --- Product KPI ---
        total_products = Product.objects.count()
        active_products = Product.objects.filter(is_active=True, deleted_at__isnull=True).count()
        inactive_products = total_products - active_products

        # --- Payment Method Distribution ---
        payment_qs = _apply_date_filter(Order.objects.all(), date_from, date_to)
        payment_rows = (
            payment_qs
            .values('payment_method')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        payment_label_map = {
            'cod': 'COD',
            'vnpay': 'VNPay',
            'bank_transfer': 'Chuyển khoản',
            'momo': 'MoMo',
        }
        payment_color_map = {
            'cod':           'rgba(245,158,11,0.85)',
            'vnpay':         'rgba(99,102,241,0.85)',
            'bank_transfer': 'rgba(16,185,129,0.85)',
            'momo':          'rgba(239,68,68,0.85)',
        }
        payment_labels, payment_data, payment_colors = [], [], []
        for row in payment_rows:
            pm = row['payment_method']
            payment_labels.append(payment_label_map.get(pm, pm))
            payment_data.append(row['count'])
            payment_colors.append(payment_color_map.get(pm, 'rgba(156,163,175,0.85)'))

        # --- Low Stock Products ---
        low_stock = (
            Product.objects
            .filter(is_active=True, deleted_at__isnull=True)
            .select_related('category', 'brand')
            .order_by('stock')[:top_limit]
        )

        # --- Recent Orders ---
        recent_orders = (
            Order.objects
            .select_related('customer')
            .order_by('-created_at')[:5]
        )

        # --- Recent Reviews ---
        recent_reviews = (
            ProductReview.objects
            .select_related('user', 'product')
            .order_by('-created_at')[:5]
        )

        return {
            'order_status': order_status,
            'new_customers': new_customers,
            'purchasing_customers': purchasing_customers,
            'total_products': total_products,
            'active_products': active_products,
            'inactive_products': inactive_products,
            'payment_labels': payment_labels,
            'payment_data': payment_data,
            'payment_colors': payment_colors,
            'low_stock': list(low_stock),
            'recent_orders': list(recent_orders),
            'recent_reviews': list(recent_reviews),
        }
    except Exception as e:
        print(f'[dashboard] get_store_operations_stats error: {e}')
        return {
            'order_status': {'pending': 0, 'processing': 0, 'completed': 0, 'cancelled': 0},
            'new_customers': 0,
            'purchasing_customers': 0,
            'total_products': 0,
            'active_products': 0,
            'inactive_products': 0,
            'payment_labels': [],
            'payment_data': [],
            'payment_colors': [],
            'low_stock': [],
            'recent_orders': [],
            'recent_reviews': [],
        }


def get_event_distribution(date_from=None, date_to=None):
    try:
        from analytics.models import Event
        qs = Event.objects.all()
        qs = _apply_date_filter(qs, date_from, date_to)
        rows = (
            qs.values('event_type')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        label_map = {
            'view_product': 'Xem sản phẩm',
            'add_to_cart': 'Thêm giỏ hàng',
            'remove_from_cart': 'Xóa khỏi giỏ',
            'checkout': 'Checkout',
        }
        labels, data, colors = [], [], []
        color_map = {
            'view_product':     'rgba(99,102,241,0.85)',
            'add_to_cart':      'rgba(16,185,129,0.85)',
            'remove_from_cart': 'rgba(239,68,68,0.85)',
            'checkout':         'rgba(245,158,11,0.85)',
        }
        for row in rows:
            et = row['event_type']
            labels.append(label_map.get(et, et))
            data.append(row['count'])
            colors.append(color_map.get(et, 'rgba(156,163,175,0.85)'))
        return {'labels': labels, 'data': data, 'colors': colors}
    except Exception as e:
        print(f'[dashboard] get_event_distribution error: {e}')
        return {'labels': [], 'data': [], 'colors': []}


def get_summary_stats():
    try:
        from orders.models import Order
        from analytics.models import Session
        import calendar
        now = timezone.now()
        today = now.date()
        yesterday = date(today.year, today.month, today.day - 1) if today.day > 1 else None

        # Revenue this month
        revenue_this_month = (
            Order.objects
            .filter(status='completed', created_at__year=now.year, created_at__month=now.month)
            .aggregate(total=Sum('total_price'))['total'] or Decimal('0')
        )
        revenue_all_time = (
            Order.objects
            .filter(status='completed')
            .aggregate(total=Sum('total_price'))['total'] or Decimal('0')
        )

        # Revenue last month for growth %
        if now.month == 1:
            last_month_year, last_month = now.year - 1, 12
        else:
            last_month_year, last_month = now.year, now.month - 1
        revenue_last_month = (
            Order.objects
            .filter(status='completed', created_at__year=last_month_year, created_at__month=last_month)
            .aggregate(total=Sum('total_price'))['total'] or Decimal('0')
        )
        if revenue_last_month > 0:
            growth_pct = round(float((revenue_this_month - revenue_last_month) / revenue_last_month * 100), 1)
        else:
            growth_pct = None

        # Orders
        orders_this_month = Order.objects.filter(
            created_at__year=now.year, created_at__month=now.month
        ).count()
        orders_completed = Order.objects.filter(
            created_at__year=now.year, created_at__month=now.month, status='completed'
        ).count()
        orders_processing = Order.objects.filter(
            created_at__year=now.year, created_at__month=now.month, status__in=('pending', 'processing')
        ).count()

        # Visits
        visits_today = Session.objects.filter(created_at__date=today).count()
        visits_yesterday = 0
        if yesterday:
            visits_yesterday = Session.objects.filter(created_at__date=yesterday).count()

        conversion = get_conversion_rate()

        return {
            'revenue_this_month': revenue_this_month,
            'revenue_all_time': revenue_all_time,
            'revenue_growth_pct': growth_pct,
            'orders_this_month': orders_this_month,
            'orders_completed': orders_completed,
            'orders_processing': orders_processing,
            'visits_today': visits_today,
            'visits_yesterday': visits_yesterday,
            'conversion_rate': conversion['rate'],
            'conversion_sessions_add': conversion['sessions_with_add'],
            'conversion_sessions_checkout': conversion['sessions_with_checkout'],
        }
    except Exception as e:
        print(f'[dashboard] get_summary_stats error: {e}')
        return {
            'revenue_this_month': Decimal('0'),
            'revenue_all_time': Decimal('0'),
            'revenue_growth_pct': None,
            'orders_this_month': 0,
            'orders_completed': 0,
            'orders_processing': 0,
            'visits_today': 0,
            'visits_yesterday': 0,
            'conversion_rate': 0.0,
            'conversion_sessions_add': 0,
            'conversion_sessions_checkout': 0,
        }
