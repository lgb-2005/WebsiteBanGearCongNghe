from django.db.models import Count, Max, Sum, F
from django.db.models import Q
from django.core.paginator import Paginator
from django.contrib.auth import authenticate
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.utils import timezone
from functools import wraps
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
import datetime
import json

from django.conf import settings

from accounts.models import User
from orders.models import Customer, Order, OrderItem
from products.forms import AttributeGroupForm, AttributeValueForm, BrandForm, CategoryForm, ProductAdminForm
from products.models import AttributeGroup, AttributeValue, Brand, Category, Product, ProductAttribute, ProductReview
from .models import Banner

ADMIN_SESSION_KEY = 'admin_dashboard_user_id'

def _is_admin_user(user):
    return bool(user.is_authenticated and (user.is_staff or user.is_superuser))

def _get_admin_session_user(request):
    admin_user_id = request.session.get(ADMIN_SESSION_KEY)
    if not admin_user_id:
        return None

    admin_user = User.objects.filter(pk=admin_user_id).first()
    if admin_user is None or not _is_admin_user(admin_user):
        request.session.pop(ADMIN_SESSION_KEY, None)
        return None

    return admin_user

def _set_admin_session_user(request, user):
    request.session.cycle_key()
    request.session[ADMIN_SESSION_KEY] = user.pk

def _clear_admin_session_user(request):
    request.session.pop(ADMIN_SESSION_KEY, None)

def _datetime_bound(date_obj, is_max=False):
    t = datetime.time.max if is_max else datetime.time.min
    dt = datetime.datetime.combine(date_obj, t)
    if settings.USE_TZ:
        dt = timezone.make_aware(dt)
    return dt

def admin_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        admin_user = _get_admin_session_user(request)
        if admin_user is None:
            return redirect(f"{redirect('core:admin_login').url}?next={request.get_full_path()}")
        request.admin_user = admin_user
        return view_func(request, *args, **kwargs)

    return _wrapped_view

def _get_showcase_category_ids(category):
    child_ids = list(category.children.values_list('id', flat=True))
    return [category.id, *child_ids]

def _format_currency(value):
    if value in (None, ''):
        return ''
    try:
        return f"{int(value):,} đ".replace(',', '.')
    except (TypeError, ValueError):
        return ''

def _get_order_status_meta(status):
    status_map = {
        'pending': {'label': 'Chờ xử lý', 'badge_class': 'neutral'},
        'processing': {'label': 'Đang xử lý', 'badge_class': 'warning'},
        'completed': {'label': 'Hoàn thành', 'badge_class': 'success'},
        'cancelled': {'label': 'Đã hủy', 'badge_class': 'danger'},
    }
    return status_map.get(status, {'label': status, 'badge_class': 'neutral'})

def _get_payment_status_meta(payment_status):
    payment_map = {
        'pending': {'label': 'Chưa thanh toán', 'badge_class': 'warning'},
        'paid': {'label': 'Đã thanh toán', 'badge_class': 'success'},
        'failed': {'label': 'Thanh toán thất bại', 'badge_class': 'danger'},
        'cancelled': {'label': 'Đã hủy', 'badge_class': 'danger'},
        'refunded': {'label': 'Đã hoàn tiền', 'badge_class': 'info'},
    }
    return payment_map.get(
        payment_status,
        {'label': str(payment_status).replace('_', ' ').title(), 'badge_class': 'neutral'},
    )

def _get_allowed_order_status_transitions(current_status):
    transition_map = {
        'pending': ['processing', 'cancelled'],
        'processing': ['completed', 'cancelled'],
        'completed': [],
        'cancelled': [],
    }
    return transition_map.get(current_status, [])

def _serialize_admin_order_item(item):
    product_images = item.product.image_urls
    line_total = item.price * item.quantity
    return {
        'product': item.product,
        'product_code': getattr(item.product, 'product_code', ''),
        'image_url': product_images[0] if product_images else '',
        'price': _format_currency(item.price),
        'quantity': item.quantity,
        'line_total': _format_currency(line_total),
    }

def _build_admin_order_list_context(request):
    search_query = ' '.join((request.GET.get('q') or '').split())
    status_filter = (request.GET.get('status') or '').strip()
    payment_filter = (request.GET.get('payment') or '').strip()
    date_from_raw = (request.GET.get('date_from') or '').strip()
    date_to_raw = (request.GET.get('date_to') or '').strip()

    date_from = None
    date_to = None
    try:
        if date_from_raw:
            date_from = datetime.datetime.strptime(date_from_raw, '%Y-%m-%d').date()
    except ValueError:
        pass
    try:
        if date_to_raw:
            date_to = datetime.datetime.strptime(date_to_raw, '%Y-%m-%d').date()
    except ValueError:
        pass

    orders_queryset = Order.objects.select_related('customer', 'customer__user').order_by('-created_at')

    if search_query:
        orders_queryset = orders_queryset.filter(
            Q(order_code__icontains=search_query)
            | Q(receiver_name__icontains=search_query)
            | Q(receiver_phone__icontains=search_query)
        )

    if status_filter in {'pending', 'processing', 'completed', 'cancelled'}:
        orders_queryset = orders_queryset.filter(status=status_filter)

    if payment_filter in {'pending', 'paid'}:
        orders_queryset = orders_queryset.filter(payment_status=payment_filter)

    if date_from:
        dt_from = _datetime_bound(date_from, is_max=False)
        orders_queryset = orders_queryset.filter(created_at__gte=dt_from)
    if date_to:
        dt_to = _datetime_bound(date_to, is_max=True)
        orders_queryset = orders_queryset.filter(created_at__lte=dt_to)

    orders_page, _ = _paginate_queryset(request, orders_queryset, per_page=20, page_param='page')

    orders = []
    for order in orders_page.object_list:
        orders.append(
            {
                'id': order.id,
                'order_code': order.order_code,
                'customer_name': order.receiver_name,
                'customer_email': order.effective_customer_email,
                'receiver_phone': order.receiver_phone,
                'total_price': _format_currency(order.total_price),
                'created_at': order.created_at.strftime('%d-%m-%Y, %H:%M'),
                'status': _get_order_status_meta(order.status),
                'payment_status': _get_payment_status_meta(order.payment_status),
            }
        )

    return {
        'orders': orders,
        'orders_page': orders_page,
        'orders_total': orders_queryset.count(),
        'orders_search_query': search_query,
        'orders_status_filter': status_filter,
        'orders_payment_filter': payment_filter,
        'orders_date_from': date_from_raw,
        'orders_date_to': date_to_raw,
        'orders_query_string': _build_query_string(request, excluded_keys=['page']),
        'orders_stats': {
            'total': Order.objects.count(),
            'pending': Order.objects.filter(status='pending').count(),
            'processing': Order.objects.filter(status='processing').count(),
            'completed': Order.objects.filter(status='completed').count(),
            'cancelled': Order.objects.filter(status='cancelled').count(),
        },
    }

def _build_admin_order_detail_context(order):
    order_items = [_serialize_admin_order_item(item) for item in order.items.all()]
    total_products = sum(item.quantity for item in order.items.all())
    order_status_meta = _get_order_status_meta(order.status)
    payment_status_meta = _get_payment_status_meta(order.payment_status)
    return {
        'order_detail': {
            'id': order.id,
            'order_code': order.order_code,
            'created_at': order.created_at.strftime('%d-%m-%Y, %H:%M'),
            'status': {'value': order.status, **order_status_meta},
            'payment_status': {'value': order.payment_status, **payment_status_meta},
            'payment_method': order.get_payment_method_display(),
            'total_price': _format_currency(order.total_price),
            'receiver_name': order.receiver_name,
            'receiver_email': order.effective_customer_email,
            'receiver_phone': order.receiver_phone,
            'shipping_address': order.shipping_address,
        },
        'order_items': order_items,
        'order_summary': {
            'total_products': total_products,
            'total_price': _format_currency(order.total_price),
        },
        'allowed_status_transitions': [
            {'value': value, **_get_order_status_meta(value)}
            for value in _get_allowed_order_status_transitions(order.status)
        ],
        'payment_status_options': [
            {'value': value, **_get_payment_status_meta(value)}
            for value in ['pending', 'paid']
        ],
    }

def _resolve_image_url(image_value):
    if not image_value:
        return ''
    image_url = getattr(image_value, 'url', None)
    if image_url:
        return image_url
    return str(image_value)

def _paginate_queryset(request, queryset, per_page=10, page_param='page'):
    paginator = Paginator(queryset, per_page)
    page_number = request.GET.get(page_param) or 1
    page_obj = paginator.get_page(page_number)
    return page_obj, paginator

def _build_query_string(request, excluded_keys=None):
    params = request.GET.copy()
    for key in excluded_keys or []:
        params.pop(key, None)
    query_string = params.urlencode()
    return f'&{query_string}' if query_string else ''

def _serialize_admin_product_row(product, index):
    prefetched_images = list(product.images.all())
    image_url = ''

    if prefetched_images:
        first_image = prefetched_images[0]
        if first_image.image:
            image_url = first_image.image.url
    elif product.image_url:
        image_url = product.image_url

    current_price = product.discount_price if product.discount_price is not None else product.price

    return {
        'index': index,
        'id': product.id,
        'product_code': product.product_code,
        'name': product.name,
        'slug': product.slug,
        'image_url': image_url,
        'category_name': product.category.name if product.category else '',
        'brand_name': product.brand.name if product.brand else 'Chưa gán',
        'price': _format_currency(current_price),
        'original_price': _format_currency(product.price) if product.discount_price is not None else '',
        'stock': product.stock,
        'is_active': product.is_active,
        'created_at': product.created_at.strftime('%d-%m-%Y, %H:%M'),
    }

def _build_admin_products_list_context(request):
    search_query = ' '.join((request.GET.get('search') or request.GET.get('q') or '').split())
    category_filter = (request.GET.get('category_id') or '').strip()
    status_filter = (request.GET.get('status') or '').strip()

    products_queryset = (
        Product.objects
        .select_related('brand', 'category')
        .prefetch_related('images')
        .order_by('-created_at')
    )

    if search_query:
        products_queryset = products_queryset.filter(
            Q(product_code__icontains=search_query)
            | Q(name__icontains=search_query)
        )

    if category_filter:
        try:
            products_queryset = products_queryset.filter(category_id=int(category_filter))
        except (TypeError, ValueError):
            category_filter = ''

    if status_filter == 'active':
        products_queryset = products_queryset.filter(is_active=True)
    elif status_filter == 'inactive':
        products_queryset = products_queryset.filter(is_active=False)
    else:
        status_filter = ''

    products_page, _ = _paginate_queryset(request, products_queryset, per_page=20, page_param='page')
    start_index = (products_page.number - 1) * products_page.paginator.per_page
    products = [
        _serialize_admin_product_row(product, start_index + index)
        for index, product in enumerate(products_page.object_list, start=1)
    ]

    return {
        'products': products,
        'products_page': products_page,
        'products_total': products_queryset.count(),
        'products_search_query': search_query,
        'products_category_filter': category_filter,
        'products_status_filter': status_filter,
        'products_query_string': _build_query_string(request, excluded_keys=['page']),
    }

def _serialize_product_card(product):
    old_price = product.price
    current_price = product.discount_price if product.discount_price is not None else product.price
    discount_percent = None

    if product.discount_price is not None and product.price:
        try:
            if product.price > 0 and product.discount_price < product.price:
                discount_percent = int(round(((product.price - product.discount_price) / product.price) * 100))
        except (TypeError, ValueError, ZeroDivisionError):
            discount_percent = None

    return {
        'id': product.id,
        'name': product.name,
        'slug': product.slug,
        'image_url': _resolve_image_url(product.main_image),
        'price': _format_currency(current_price),
        'old_price': _format_currency(old_price) if discount_percent else '',
        'discount_percent': discount_percent,
        'brand_name': product.brand.name if product.brand else '',
        'stock': product.stock,
    }

def _build_showcase_section(category):
    showcase_category_ids = _get_showcase_category_ids(category)
    products = list(
        Product.objects.filter(category_id__in=showcase_category_ids, is_active=True)
        .select_related('brand', 'category')
        .prefetch_related('images')
        .order_by('-created_at')[:8]
    )

    if not products:
        return None

    all_brands = (
        Brand.objects.filter(
            products__category_id__in=showcase_category_ids,
            products__is_active=True,
        )
        .annotate(product_total=Count('products__id', distinct=True))
        .filter(product_total__gt=0)
        .order_by('-product_total', 'name')
    )

    filter_pills = [{'label': 'Tất cả', 'brand': '', 'brand_id': ''}]
    for brand in all_brands:
        filter_pills.append({'label': brand.name, 'brand': brand.name, 'brand_id': brand.id})

    top_selling_products = list(
        Product.objects.filter(category_id__in=showcase_category_ids, is_active=True)
        .select_related('brand', 'category')
        .prefetch_related('images')
        .annotate(
            total_sold=Sum(
                'orderitem__quantity',
                filter=Q(orderitem__order__status='completed'),
            )
        )
        .filter(total_sold__gt=0)
        .order_by('-total_sold', '-created_at')[:6]
    )

    highlight_items = []
    for product in top_selling_products:
        highlight_items.append(
            {
                'name': product.name,
                'meta': f"Đã bán {int(product.total_sold or 0)}",
                'image_url': _resolve_image_url(product.main_image),
                'slug': product.slug,
            }
        )

    if not highlight_items:
        for product in products[:6]:
            highlight_items.append(
                {
                    'name': product.name,
                    'meta': 'Chưa có lượt bán',
                    'image_url': _resolve_image_url(product.main_image),
                    'slug': product.slug,
                }
            )

    product_count = Product.objects.filter(
        category_id__in=showcase_category_ids, is_active=True
    ).count()

    return {
        'category': category,
        'category_id': category.id,
        'showcase_category_ids': list(showcase_category_ids),
        'title': category.name,
        'filters': filter_pills,
        'product_count': product_count,
        'products': [_serialize_product_card(product) for product in products],
        'panel_label': f'Bán chạy nhất trong {category.name}',
        'highlights': highlight_items[:6],
    }

def showcase_products_api(request):
    category_ids_raw = request.GET.get('category_ids', '')
    brand_id = request.GET.get('brand_id', '')

    try:
        category_ids = [int(x) for x in category_ids_raw.split(',') if x.strip()]
    except ValueError:
        return JsonResponse({'error': 'invalid category_ids'}, status=400)

    if not category_ids:
        return JsonResponse({'products': []})

    qs = Product.objects.filter(category_id__in=category_ids, is_active=True).select_related('brand').prefetch_related('images').order_by('-created_at')

    if brand_id:
        try:
            qs = qs.filter(brand_id=int(brand_id))
        except ValueError:
            pass

    products = [_serialize_product_card(p) for p in qs[:32]]
    return JsonResponse({'products': products})

def home(request):
    root_categories = list(
        Category.objects.filter(parent__isnull=True)
        .prefetch_related('children')
        .order_by('name')
    )

    ranked_categories = []
    for category in root_categories:
        product_total = Product.objects.filter(category_id__in=_get_showcase_category_ids(category), is_active=True).count()
        if product_total > 0:
            ranked_categories.append((category, product_total))

    ranked_categories.sort(key=lambda item: (-item[1], item[0].name))
    showcase_categories = [category for category, _ in ranked_categories]

    showcase_sections = []
    for category in showcase_categories:
        section = _build_showcase_section(category)
        if section:
            showcase_sections.append(section)

    from .services import get_active_hero_banners
    hero_banners = list(get_active_hero_banners())

    context = {
        'title': 'TechGear - Gear Công Nghệ & Gaming',
        'showcase_sections': showcase_sections,
        'hero_banners': hero_banners,
    }
    return render(request, 'core/home.html', context)

def build_admin_base_context(active_panel='overview', page_title='Tổng quan vận hành'):
    products = Product.objects.select_related('brand', 'category').order_by('-created_at')
    categories = Category.objects.select_related('parent').annotate(product_total=Count('products')).order_by('name')
    brands = Brand.objects.annotate(product_count=Count('products')).order_by('name')
    attribute_groups = AttributeGroup.objects.prefetch_related('categories').annotate(
        values_total=Count('values', distinct=True),
        product_usage_count=Count('values__productattribute', distinct=True),
    ).order_by('display_order', 'name')
    attribute_values = AttributeValue.objects.select_related('group').annotate(
        product_usage_count=Count('productattribute', distinct=True),
    ).order_by(
        'group__display_order',
        'group__name',
        'display_order',
        'value',
    )

    low_stock_count = products.filter(stock__lte=10).count()

    return {
        'title': 'TechGear Admin Dashboard',
        'products': products,
        'categories': categories,
        'category_overview': categories[:5],
        'brands': brands,
        'attribute_groups': attribute_groups,
        'attribute_values': attribute_values,
        'product_total': products.count(),
        'brand_total': Brand.objects.count(),
        'category_total': Category.objects.count(),
        'attribute_group_total': AttributeGroup.objects.count(),
        'attribute_value_total': AttributeValue.objects.count(),
        'low_stock_count': low_stock_count,
        'active_panel': active_panel,
        'admin_page_title': page_title,
    }

def _build_admin_product_form_context(request, form, editing_product=None):
    page_title = 'Chỉnh sửa sản phẩm' if editing_product is not None else 'Thêm sản phẩm'
    context = build_admin_base_context(active_panel='products', page_title=page_title)
    context.update(
        {
            'product_form': form,
            'editing_product': editing_product,
            'product_form_query_string': _build_query_string(request, excluded_keys=['page']),
        }
    )
    return context

def _get_product_form_kwargs(selected_category_id=None, editing_product=None):
    form_kwargs = {}

    if editing_product is not None:
        form_kwargs['instance'] = editing_product

    if selected_category_id:
        initial = {}
        if editing_product is not None and editing_product.category_id:
            initial['category'] = editing_product.category_id
        try:
            initial['category'] = int(selected_category_id)
        except (TypeError, ValueError):
            pass
        if initial:
            form_kwargs['initial'] = initial

    return form_kwargs

def admin_login(request):
    if _get_admin_session_user(request) is not None:
        return redirect('core:admin_dashboard')

    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        next_url = request.POST.get('next') or request.GET.get('next') or redirect('core:admin_dashboard').url

        user = authenticate(request, username=email, password=password)

        if user is not None and _is_admin_user(user):
            _set_admin_session_user(request, user)
            return redirect(next_url)

        context = {
            'title': 'Đăng nhập Admin Dashboard',
            'error_message': 'Chỉ tài khoản admin mới có thể đăng nhập vào admin dashboard.',
            'next_url': next_url,
        }
        return render(request, 'core/admin/login.html', context, status=403)

    context = {
        'title': 'Đăng nhập Admin Dashboard',
        'next_url': request.GET.get('next', redirect('core:admin_dashboard').url),
    }
    return render(request, 'core/admin/login.html', context)

def admin_logout(request):
    _clear_admin_session_user(request)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'message': 'Bạn đã đăng xuất khỏi khu vực quản trị.',
            'redirect_url': redirect('core:admin_login').url,
        })

    return redirect('core:admin_login')

@admin_required
def admin_dashboard(request):
    period = request.GET.get('period', 'day')
    if period not in ('day', 'month', 'quarter', 'year'):
        period = 'day'
    date_from_raw = request.GET.get('date_from', '')
    date_to_raw = request.GET.get('date_to', '')
    try:
        top_limit = max(1, int(request.GET.get('top_limit', 10)))
    except (TypeError, ValueError):
        top_limit = 10

    date_from = None
    date_to = None
    try:
        if date_from_raw:
            date_from = datetime.datetime.strptime(date_from_raw, '%Y-%m-%d').date()
    except ValueError:
        pass
    try:
        if date_to_raw:
            date_to = datetime.datetime.strptime(date_to_raw, '%Y-%m-%d').date()
    except ValueError:
        pass

    from analytics.dashboard import (
        get_revenue_stats, get_top_selling_products,
        get_summary_stats, get_store_operations_stats,
    )

    revenue_stats = get_revenue_stats(period=period)
    summary = get_summary_stats()
    top_selling = get_top_selling_products(limit=top_limit, date_from=date_from, date_to=date_to)
    ops = get_store_operations_stats(period=period, date_from=date_from, date_to=date_to, top_limit=top_limit)

    revenue_labels = [r['period_label'] for r in revenue_stats]
    revenue_data = [float(r['revenue']) for r in revenue_stats]

    context = build_admin_base_context(active_panel='overview', page_title='Tổng quan vận hành')
    context.update({
        'summary': summary,
        'top_selling': top_selling,
        'ops': ops,
        'revenue_labels_json': json.dumps(revenue_labels),
        'revenue_data_json': json.dumps(revenue_data),
        'payment_labels_json': json.dumps(ops['payment_labels']),
        'payment_data_json': json.dumps(ops['payment_data']),
        'payment_colors_json': json.dumps(ops['payment_colors']),
        'current_period': period,
        'current_date_from': date_from_raw,
        'current_date_to': date_to_raw,
        'current_top_limit': top_limit,
    })
    return render(request, 'core/admin/overview.html', context)


@admin_required
def admin_analytics(request):
    period = request.GET.get('period', 'day')
    if period not in ('day', 'month', 'quarter', 'year'):
        period = 'day'
    date_from_raw = request.GET.get('date_from', '')
    date_to_raw   = request.GET.get('date_to', '')
    try:
        top_limit = max(1, int(request.GET.get('top_limit', 10)))
    except (TypeError, ValueError):
        top_limit = 10

    product_query = ' '.join((request.GET.get('product_q') or '').split())
    product_category_raw = (request.GET.get('product_category') or '').strip()
    try:
        product_category_id = int(product_category_raw) if product_category_raw else None
    except ValueError:
        product_category_id = None
    if product_category_id and not Category.objects.filter(pk=product_category_id).exists():
        product_category_id = None
    product_sort = (request.GET.get('product_sort') or 'views_desc').strip()
    if product_sort not in {
        'views_desc', 'cart_desc', 'checkout_desc', 'conversion_desc', 'conversion_asc'
    }:
        product_sort = 'views_desc'

    date_from = None
    date_to   = None
    try:
        if date_from_raw:
            date_from = datetime.datetime.strptime(date_from_raw, '%Y-%m-%d').date()
    except ValueError:
        pass
    try:
        if date_to_raw:
            date_to = datetime.datetime.strptime(date_to_raw, '%Y-%m-%d').date()
    except ValueError:
        pass

    from analytics.analytics_service import (
        get_conversion_funnel,
        get_customer_journey,
        get_product_conversion,
        get_traffic_trend,
        get_product_interest,
        get_abandoned_cart,
        get_session_analytics,
    )
    from analytics.dashboard import get_event_distribution

    funnel           = get_conversion_funnel(date_from=date_from, date_to=date_to)
    journey          = get_customer_journey(date_from=date_from, date_to=date_to)
    product_conv     = get_product_conversion(
        limit=top_limit,
        date_from=date_from,
        date_to=date_to,
        product_query=product_query,
        category_id=product_category_id,
        sort_by=product_sort,
    )
    traffic          = get_traffic_trend(period=period, date_from=date_from, date_to=date_to)
    event_dist       = get_event_distribution(date_from=date_from, date_to=date_to)
    interest         = get_product_interest(limit=top_limit, date_from=date_from, date_to=date_to)
    abandoned        = get_abandoned_cart(date_from=date_from, date_to=date_to)
    session_stats    = get_session_analytics(date_from=date_from, date_to=date_to)

    traffic_labels   = [t['period_label']  for t in traffic]
    traffic_sessions = [t['session_count'] for t in traffic]
    traffic_guests   = [t['guest_count']   for t in traffic]
    traffic_users    = [t['user_count']    for t in traffic]

    context = build_admin_base_context(active_panel='analytics', page_title='Phân Tích Hành Vi Khách Hàng')
    context.update({
        'funnel':            funnel,
        'funnel_json':       json.dumps(funnel),
        'journey':           journey,
        'product_conv':      product_conv,
        'product_categories': Category.objects.all(),
        'product_query':     product_query,
        'product_category_id': product_category_id,
        'product_sort':      product_sort,
        'product_conv_is_filtered': bool(product_query or product_category_id),
        'event_dist':        event_dist,
        'interest':          interest,
        'abandoned':         abandoned,
        'session_stats':     session_stats,
        'traffic_labels_json':   json.dumps(traffic_labels),
        'traffic_sessions_json': json.dumps(traffic_sessions),
        'traffic_guests_json':   json.dumps(traffic_guests),
        'traffic_users_json':    json.dumps(traffic_users),
        'event_dist_labels_json': json.dumps(event_dist['labels']),
        'event_dist_data_json':   json.dumps(event_dist['data']),
        'event_dist_colors_json': json.dumps(event_dist['colors']),
        'current_period':    period,
        'current_date_from': date_from_raw,
        'current_date_to':   date_to_raw,
        'current_top_limit': top_limit,
    })
    return render(request, 'core/admin/analytics.html', context)


@admin_required
def admin_products(request):
    context = build_admin_base_context(active_panel='products', page_title='Quản lý sản phẩm')
    context.update(_build_admin_products_list_context(request))
    return render(request, 'core/admin/products.html', context)


@admin_required
def admin_brands(request):
    editing_brand = None
    edit_brand_id = request.GET.get('edit_brand')
    search_query = (request.GET.get('q') or '').strip()
    delete_blocked = request.GET.get('delete_blocked') == '1'

    if edit_brand_id:
        editing_brand = get_object_or_404(Brand, pk=edit_brand_id)

    context = build_admin_base_context(active_panel='brands', page_title='Quản lý thương hiệu')
    brands_queryset = Brand.objects.annotate(product_count=Count('products')).order_by('name')

    if search_query:
        brands_queryset = brands_queryset.filter(name__icontains=search_query)

    brands_page, _ = _paginate_queryset(request, brands_queryset, per_page=10, page_param='page')
    context.update(
        {
            'brand_form': BrandForm(instance=editing_brand),
            'editing_brand': editing_brand,
            'brands': brands_page.object_list,
            'brands_page': brands_page,
            'brands_total': brands_queryset.count(),
            'brands_search_query': search_query,
            'delete_blocked': delete_blocked,
            'brands_query_string': _build_query_string(request, excluded_keys=['page']),
            'brands_edit_query_string': _build_query_string(request, excluded_keys=['page', 'edit_brand']),
        }
    )
    return render(request, 'core/admin/brands.html', context)


@admin_required
def admin_categories(request):
    editing_category = None
    edit_category_id = request.GET.get('edit_category')

    if edit_category_id:
        editing_category = get_object_or_404(Category, pk=edit_category_id)

    context = build_admin_base_context(active_panel='categories', page_title='Quản lý danh mục')
    context.update({'category_form': CategoryForm(instance=editing_category), 'editing_category': editing_category})
    return render(request, 'core/admin/categories.html', context)


@admin_required
def admin_attribute_groups(request):
    editing_group = None
    edit_group_id = request.GET.get('edit_group')
    search_query = (request.GET.get('q') or '').strip()

    if edit_group_id:
        editing_group = get_object_or_404(AttributeGroup, pk=edit_group_id)

    context = build_admin_base_context(active_panel='attribute_groups', page_title='Quản lý nhóm thuộc tính')

    groups_queryset = AttributeGroup.objects.prefetch_related('categories').annotate(
        values_total=Count('values', distinct=True),
        product_usage_count=Count('values__productattribute', distinct=True),
    ).order_by('display_order', 'name')

    if search_query:
        groups_queryset = groups_queryset.filter(
            Q(name__icontains=search_query) | Q(slug__icontains=search_query)
        )

    groups_page, _ = _paginate_queryset(request, groups_queryset, per_page=15, page_param='page')

    context.update({
        'attribute_group_form': AttributeGroupForm(instance=editing_group),
        'editing_group': editing_group,
        'attribute_groups': groups_page.object_list,
        'attribute_groups_page': groups_page,
        'attribute_groups_total': groups_queryset.count(),
        'attribute_groups_search_query': search_query,
        'attribute_groups_query_string': _build_query_string(request, excluded_keys=['page']),
        'attribute_groups_edit_query_string': _build_query_string(request, excluded_keys=['page', 'edit_group']),
    })
    return render(request, 'core/admin/attribute_groups.html', context)


@admin_required
def admin_attribute_values(request):
    editing_value = None
    edit_value_id = request.GET.get('edit_value')
    search_query = (request.GET.get('q') or '').strip()
    group_filter = (request.GET.get('group') or '').strip()

    if edit_value_id:
        editing_value = get_object_or_404(AttributeValue, pk=edit_value_id)

    context = build_admin_base_context(active_panel='attribute_values', page_title='Quản lý giá trị thuộc tính')

    values_queryset = AttributeValue.objects.select_related('group').annotate(
        product_usage_count=Count('productattribute', distinct=True),
    ).order_by(
        'group__display_order',
        'group__name',
        'display_order',
        'value',
    )

    if search_query:
        values_queryset = values_queryset.filter(
            Q(value__icontains=search_query) | Q(slug__icontains=search_query)
        )

    if group_filter.isdigit():
        values_queryset = values_queryset.filter(group_id=int(group_filter))

    values_page, _ = _paginate_queryset(request, values_queryset, per_page=15, page_param='page')

    filter_groups = AttributeGroup.objects.order_by('display_order', 'name')

    context.update({
        'attribute_value_form': AttributeValueForm(instance=editing_value),
        'editing_value': editing_value,
        'attribute_values': values_page.object_list,
        'attribute_values_page': values_page,
        'attribute_values_total': values_queryset.count(),
        'attribute_values_search_query': search_query,
        'attribute_values_group_filter': group_filter,
        'attribute_values_filter_groups': filter_groups,
        'attribute_values_query_string': _build_query_string(request, excluded_keys=['page']),
        'attribute_values_edit_query_string': _build_query_string(request, excluded_keys=['page', 'edit_value']),
    })
    return render(request, 'core/admin/attribute_values.html', context)


@admin_required
def admin_attribute_value_products(request, value_id):
    attribute_value = get_object_or_404(
        AttributeValue.objects.select_related('group'), pk=value_id
    )

    product_attributes = (
        ProductAttribute.objects
        .filter(attribute_value=attribute_value)
        .select_related('product', 'product__brand', 'product__category')
        .order_by('product__name')
    )

    products = []
    for pa in product_attributes:
        product = pa.product
        images = product.image_urls
        products.append({
            'id': product.id,
            'name': product.name,
            'product_code': getattr(product, 'product_code', ''),
            'slug': product.slug,
            'brand': product.brand.name if product.brand else '',
            'category': product.category.name if product.category else '',
            'image_url': images[0] if images else '',
            'is_active': product.is_active,
            'custom_value': pa.custom_value or '',
        })

    return JsonResponse({
        'success': True,
        'attribute_value': {
            'id': attribute_value.id,
            'value': attribute_value.value,
            'group': attribute_value.group.name,
        },
        'count': len(products),
        'products': products,
    })


@admin_required
@require_POST
def admin_attribute_value_remove_product(request, value_id, product_id):
    attribute_value = get_object_or_404(AttributeValue, pk=value_id)
    deleted, _ = ProductAttribute.objects.filter(
        attribute_value=attribute_value,
        product_id=product_id,
    ).delete()

    if not deleted:
        return JsonResponse(
            {'success': False, 'message': 'Sản phẩm không được gán giá trị thuộc tính này.'},
            status=404,
        )

    remaining = ProductAttribute.objects.filter(attribute_value=attribute_value).count()
    return JsonResponse({'success': True, 'remaining': remaining})


@admin_required
def admin_orders(request):
    context = build_admin_base_context(active_panel='orders', page_title='Quản lý đơn hàng')
    context.update(_build_admin_order_list_context(request))
    return render(request, 'core/admin/orders.html', context)


@admin_required
def admin_order_detail(request, order_id):
    order = get_object_or_404(
        Order.objects.select_related('customer', 'customer__user').prefetch_related('items', 'items__product', 'items__product__images'),
        pk=order_id,
    )
    context = build_admin_base_context(active_panel='orders', page_title=f'Chi tiết đơn hàng {order.order_code}')
    context.update(_build_admin_order_detail_context(order))
    context.update(
        {
            'status_updated': request.GET.get('status_updated') == '1',
            'payment_updated': request.GET.get('payment_updated') == '1',
            'invalid_transition': request.GET.get('invalid_transition') == '1',
        }
    )
    return render(request, 'core/admin/order_detail.html', context)


@admin_required
@require_POST
def admin_order_update_status(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    next_status = (request.POST.get('status') or '').strip()

    if next_status not in _get_allowed_order_status_transitions(order.status):
        return redirect(f"{redirect('core:admin_order_detail', order_id=order.id).url}?invalid_transition=1")

    old_status = order.status
    order.status = next_status
    if next_status == 'completed':
        order.payment_status = 'paid'
        order.save(update_fields=['status', 'payment_status', 'updated_at'])
    else:
        order.save(update_fields=['status', 'updated_at'])

    if next_status == 'cancelled' and old_status != 'cancelled':
        for item in order.items.select_related('product'):
            product = item.product
            product.stock = F('stock') + item.quantity
            product.save(update_fields=['stock'])

    from orders.email import send_order_status_update, _send_in_background
    _send_in_background(send_order_status_update, order, old_status, next_status)

    return redirect(f"{redirect('core:admin_order_detail', order_id=order.id).url}?status_updated=1")


@admin_required
@require_POST
def admin_order_update_payment(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    next_payment_status = (request.POST.get('payment_status') or '').strip()

    if next_payment_status not in {'pending', 'paid'}:
        return redirect('core:admin_order_detail', order_id=order.id)

    order.payment_status = next_payment_status
    order.save(update_fields=['payment_status', 'updated_at'])
    return redirect(f"{redirect('core:admin_order_detail', order_id=order.id).url}?payment_updated=1")


@admin_required
def admin_users(request):
    search_query = ' '.join((request.GET.get('q') or '').split())
    status_filter = (request.GET.get('status') or '').strip()
    users_qs = (
        User.objects
        .filter(is_staff=False, is_superuser=False)
        .annotate(
            order_count=Count('customer_profile__orders', distinct=True),
            total_spent=Sum(
                'customer_profile__orders__total_price',
                filter=Q(customer_profile__orders__status='completed'),
            ),
        )
        .order_by('-date_joined')
    )

    if search_query:
        users_qs = users_qs.filter(
            Q(name__icontains=search_query)
            | Q(email__icontains=search_query)
            | Q(phone__icontains=search_query)
        )

    if status_filter == 'active':
        users_qs = users_qs.filter(is_active=True)
    elif status_filter == 'inactive':
        users_qs = users_qs.filter(is_active=False)

    users_stats = {
        'total': User.objects.count(),
        'active': User.objects.filter(is_active=True).count(),
        'inactive': User.objects.filter(is_active=False).count(),
        'admin_count': User.objects.filter(is_staff=True).count(),
        'user_count': User.objects.filter(is_staff=False, is_superuser=False).count(),
    }

    users_page, _ = _paginate_queryset(request, users_qs, per_page=20, page_param='page')
    context = build_admin_base_context(active_panel='users', page_title='Quản lý người dùng')
    context.update({
        'users': users_page.object_list,
        'users_page': users_page,
        'users_total': users_qs.count(),
        'users_stats': users_stats,
        'users_search_query': search_query,
        'users_status_filter': status_filter,
        'users_query_string': _build_query_string(request, excluded_keys=['page']),
    })
    return render(request, 'core/admin/users.html', context)


@admin_required
def admin_user_detail(request, user_id):
    target_user = get_object_or_404(User, pk=user_id)

    order_stats = Order.objects.filter(
        customer__user=target_user
    ).aggregate(
        total_orders=Count('id'),
        total_spent=Sum('total_price', filter=Q(status='completed')),
        completed=Count('id', filter=Q(status='completed')),
        cancelled=Count('id', filter=Q(status='cancelled')),
        processing=Count('id', filter=Q(status='processing')),
    )

    recent_orders = (
        Order.objects
        .filter(customer__user=target_user)
        .order_by('-created_at')[:5]
    )

    def _order_status_badge(status):
        return {
            'pending': ('neutral', 'Chờ xử lý'),
            'processing': ('info', 'Đang xử lý'),
            'completed': ('success', 'Hoàn thành'),
            'cancelled': ('danger', 'Đã hủy'),
        }.get(status, ('neutral', status))

    recent_orders_data = []
    for order in recent_orders:
        badge_class, badge_label = _order_status_badge(order.status)
        recent_orders_data.append({
            'id': order.id,
            'order_code': order.order_code,
            'created_at': order.created_at.strftime('%d/%m/%Y %H:%M'),
            'total_price': _format_currency(order.total_price),
            'status_badge': badge_class,
            'status_label': badge_label,
        })

    context = build_admin_base_context(active_panel='users', page_title=f'Chi tiết: {target_user.name}')
    context.update({
        'target_user': target_user,
        'order_stats': order_stats,
        'recent_orders': recent_orders_data,
        'status_updated': request.GET.get('status_updated') == '1',
    })
    return render(request, 'core/admin/user_detail.html', context)


@admin_required
@require_POST
def admin_user_toggle_status(request, user_id):
    target_user = get_object_or_404(User, pk=user_id)
    target_user.is_active = not target_user.is_active
    target_user.save(update_fields=['is_active'])
    return redirect(f"{redirect('core:admin_user_detail', user_id=target_user.id).url}?status_updated=1")


@admin_required
@require_POST
def admin_user_update(request, user_id):
    target_user = get_object_or_404(User, pk=user_id)
    name = (request.POST.get('name') or '').strip()
    phone = (request.POST.get('phone') or '').strip()

    errors = {}
    if not name:
        errors['name'] = 'Họ tên không được để trống.'

    if phone and User.objects.filter(phone=phone).exclude(pk=target_user.pk).exists():
        errors['phone'] = 'Số điện thoại này đã được sử dụng bởi tài khoản khác.'

    if errors:
        return JsonResponse({'success': False, 'errors': errors}, status=400)

    target_user.name = name
    target_user.phone = phone or None
    update_fields = ['name', 'phone']

    if 'avatar' in request.FILES:
        target_user.avatar = request.FILES['avatar']
        update_fields.append('avatar')

    target_user.save(update_fields=update_fields)
    return JsonResponse({'success': True})


@admin_required
@require_POST
def admin_user_change_password(request, user_id):
    target_user = get_object_or_404(User, pk=user_id)
    new_password = (request.POST.get('new_password') or '').strip()
    confirm_password = (request.POST.get('confirm_password') or '').strip()

    errors = {}
    if not new_password:
        errors['new_password'] = 'Mật khẩu mới không được để trống.'
    elif len(new_password) < 8:
        errors['new_password'] = 'Mật khẩu phải có ít nhất 8 ký tự.'
    if new_password and new_password != confirm_password:
        errors['confirm_password'] = 'Xác nhận mật khẩu không khớp.'

    if errors:
        return JsonResponse({'success': False, 'errors': errors}, status=400)

    target_user.set_password(new_password)
    target_user.save()
    return JsonResponse({'success': True})


@admin_required
def admin_customers(request):
    search_query = ' '.join((request.GET.get('search') or '').split())
    type_filter = (request.GET.get('type') or '').strip()
    sort_by = (request.GET.get('sort') or 'total_spent').strip()

    customers_qs = (
        Customer.objects
        .select_related('user')
        .annotate(
            order_count=Count('orders', filter=Q(orders__status='completed'), distinct=True),
            total_spent=Sum('orders__total_price', filter=Q(orders__status='completed')),
            last_order_at=Max('orders__created_at'),
        )
    )

    if search_query:
        customers_qs = customers_qs.filter(
            Q(full_name__icontains=search_query)
            | Q(phone__icontains=search_query)
            | Q(email__icontains=search_query)
        )

    if type_filter == 'registered':
        customers_qs = customers_qs.filter(user__isnull=False)
    elif type_filter == 'guest':
        customers_qs = customers_qs.filter(user__isnull=True)

    valid_sorts = {
        'total_spent': '-total_spent',
        'order_count': '-order_count',
        'last_order_at': '-last_order_at',
    }
    order_expr = valid_sorts.get(sort_by, '-total_spent')
    customers_qs = customers_qs.order_by(order_expr, '-id')

    customers_page, _ = _paginate_queryset(request, customers_qs, per_page=25)

    context = build_admin_base_context(active_panel='customers', page_title='Khách hàng')
    context.update({
        'customers_page': customers_page,
        'customers': customers_page.object_list,
        'customers_total': customers_qs.count(),
        'search_query': search_query,
        'type_filter': type_filter,
        'sort_by': sort_by,
        'query_string': _build_query_string(request, excluded_keys=['page']),
    })
    return render(request, 'core/admin/customers.html', context)


@admin_required
def admin_customer_detail(request, customer_id):
    customer = get_object_or_404(Customer.objects.select_related('user'), pk=customer_id)

    order_stats = Order.objects.filter(customer=customer).aggregate(
        total_orders=Count('id'),
        total_spent=Sum('total_price', filter=Q(status='completed')),
        completed=Count('id', filter=Q(status='completed')),
        cancelled=Count('id', filter=Q(status='cancelled')),
        processing=Count('id', filter=Q(status='processing')),
    )

    def _order_status_badge(status):
        return {
            'pending': ('neutral', 'Chờ xử lý'),
            'processing': ('info', 'Đang xử lý'),
            'completed': ('success', 'Hoàn thành'),
            'cancelled': ('danger', 'Đã hủy'),
        }.get(status, ('neutral', status))

    recent_orders_qs = (
        Order.objects
        .filter(customer=customer)
        .order_by('-created_at')[:10]
    )

    recent_orders_data = []
    for order in recent_orders_qs:
        badge_class, badge_label = _order_status_badge(order.status)
        recent_orders_data.append({
            'id': order.id,
            'order_code': order.order_code,
            'created_at': order.created_at.strftime('%d/%m/%Y %H:%M'),
            'total_price': _format_currency(order.total_price),
            'status_badge': badge_class,
            'status_label': badge_label,
        })

    display_name = customer.full_name or customer.phone or customer.email or f'Customer #{customer.pk}'
    context = build_admin_base_context(active_panel='customers', page_title=f'Chi tiết: {display_name}')
    context.update({
        'customer': customer,
        'order_stats': order_stats,
        'recent_orders': recent_orders_data,
    })
    return render(request, 'core/admin/customer_detail.html', context)


@admin_required
def admin_content(request):
    from .forms import BannerForm
    from .services import get_active_banners

    banners = Banner.objects.all().order_by('position', 'display_order', '-id')
    context = build_admin_base_context(active_panel='content', page_title='Quản lý banner')
    context.update({
        'banners': banners,
        'now': timezone.now(),
    })
    return render(request, 'core/admin/content.html', context)


@admin_required
def admin_banner_create(request):
    from .forms import BannerForm

    if request.method == 'POST':
        form = BannerForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            return redirect('core:admin_content')
        context = build_admin_base_context(active_panel='content', page_title='Thêm banner')
        context.update({'banner_form': form, 'editing_banner': None})
        return render(request, 'core/admin/banner_form.html', context, status=400)

    form = BannerForm()
    context = build_admin_base_context(active_panel='content', page_title='Thêm banner')
    context.update({'banner_form': form, 'editing_banner': None})
    return render(request, 'core/admin/banner_form.html', context)


@admin_required
def admin_banner_edit(request, banner_id):
    from .forms import BannerForm
    from .models import Banner

    banner = get_object_or_404(Banner, pk=banner_id)
    form = BannerForm(instance=banner)
    context = build_admin_base_context(active_panel='content', page_title='Sửa banner')
    context.update({'banner_form': form, 'editing_banner': banner})
    return render(request, 'core/admin/banner_form.html', context)


@admin_required
def admin_banner_update(request, banner_id):
    from .forms import BannerForm
    from .models import Banner

    banner = get_object_or_404(Banner, pk=banner_id)
    if request.method != 'POST':
        return redirect('core:admin_banner_edit', banner_id=banner.id)

    form = BannerForm(request.POST, request.FILES, instance=banner)
    if form.is_valid():
        form.save()
        return redirect('core:admin_content')

    context = build_admin_base_context(active_panel='content', page_title='Sửa banner')
    context.update({'banner_form': form, 'editing_banner': banner})
    return render(request, 'core/admin/banner_form.html', context, status=400)


@admin_required
def admin_banner_delete(request, banner_id):
    from .models import Banner

    banner = get_object_or_404(Banner, pk=banner_id)
    if request.method == 'POST':
        image = banner.image
        banner.delete()
        if image:
            image.delete(save=False)
    return redirect('core:admin_content')


@admin_required
def admin_banner_toggle(request, banner_id):
    from .models import Banner

    banner = get_object_or_404(Banner, pk=banner_id)
    if request.method == 'POST':
        banner.is_active = not banner.is_active
        banner.save(update_fields=['is_active'])
    return redirect('core:admin_content')


@admin_required
def admin_product_create(request):
    if request.method == 'POST':
        form = ProductAdminForm(request.POST, request.FILES)
        if form.is_valid():
            product = form.save()
            form.save_images(product)
            return redirect('core:admin_products')
        context = _build_admin_product_form_context(request, form)
        return render(request, 'core/admin/product_form.html', context, status=400)

    form = ProductAdminForm(**_get_product_form_kwargs(request.GET.get('category')))
    context = _build_admin_product_form_context(request, form)
    return render(request, 'core/admin/product_form.html', context)


@admin_required
def admin_product_edit(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    form = ProductAdminForm(**_get_product_form_kwargs(request.GET.get('category'), editing_product=product))
    context = _build_admin_product_form_context(request, form, editing_product=product)
    return render(request, 'core/admin/product_form.html', context)


@admin_required
def admin_product_update(request, product_id):
    product = get_object_or_404(Product, pk=product_id)

    if request.method != 'POST':
        return redirect('core:admin_product_edit', product_id=product.id)

    form = ProductAdminForm(request.POST, request.FILES, instance=product)
    if form.is_valid():
        product = form.save()
        form.save_images(product)
        return redirect('core:admin_products')

    context = _build_admin_product_form_context(request, form, editing_product=product)
    return render(request, 'core/admin/product_form.html', context, status=400)


@admin_required
def admin_product_delete(request, product_id):
    product = get_object_or_404(
        Product,
        pk=product_id
    )

    if request.method == 'POST':
        product.soft_delete()

    return redirect('core:admin_products')

@admin_required
def admin_product_restore(request, product_id):
    product = get_object_or_404(Product, pk=product_id)

    if request.method == 'POST':
        product.restore()

    return redirect('core:admin_products')


@admin_required
def admin_product_attribute_sections(request):
    category_id = (request.GET.get('category_id') or '').strip()
    product_id = (request.GET.get('product_id') or '').strip()

    editing_product = None
    if product_id:
        try:
            editing_product = Product.objects.get(pk=int(product_id))
        except (Product.DoesNotExist, TypeError, ValueError):
            editing_product = None

    form_kwargs = _get_product_form_kwargs(
        selected_category_id=category_id if category_id else None,
        editing_product=editing_product,
    )
    form = ProductAdminForm(**form_kwargs)

    html = render_to_string(
        'core/admin/_product_attribute_sections.html',
        {'dynamic_attribute_sections': form.dynamic_attribute_sections},
        request=request,
    )
    return HttpResponse(html)


@admin_required
@require_POST
def admin_attribute_value_quick_create(request):
    group_id = request.POST.get('group_id')
    raw_value = request.POST.get('value')
    value = ProductAdminForm.normalize_attribute_value(raw_value)

    if not group_id:
        return JsonResponse({'success': False, 'message': 'Thiếu nhóm thuộc tính.'}, status=400)

    if not value:
        return JsonResponse({'success': False, 'message': 'Vui lòng nhập giá trị mới.'}, status=400)

    group = get_object_or_404(AttributeGroup, pk=group_id)
    attribute_value = group.values.filter(value__iexact=value).first()
    created = False

    if attribute_value is None:
        attribute_value = AttributeValue.objects.create(group=group, value=value)
        created = True

    return JsonResponse({'success': True, 'created': created, 'attribute_value': {'id': attribute_value.id, 'value': attribute_value.value, 'slug': attribute_value.slug, 'group_id': group.id, 'group_slug': group.slug, 'filter_type': group.filter_type}})


@admin_required
def admin_brand_create(request):
    if request.method != 'POST':
        return redirect('core:admin_brands')

    form = BrandForm(request.POST)
    if form.is_valid():
        form.save()
        return redirect('core:admin_brands')

    context = build_admin_base_context(active_panel='brands', page_title='Quản lý thương hiệu')
    context.update({'brand_form': form, 'editing_brand': None})
    return render(request, 'core/admin/brands.html', context, status=400)


@admin_required
def admin_brand_update(request, brand_id):
    brand = get_object_or_404(Brand, pk=brand_id)

    if request.method != 'POST':
        return redirect('core:admin_brands')

    form = BrandForm(request.POST, instance=brand)
    if form.is_valid():
        form.save()
        return redirect('core:admin_brands')

    context = build_admin_base_context(active_panel='brands', page_title='Quản lý thương hiệu')
    context.update({'brand_form': form, 'editing_brand': brand})
    return render(request, 'core/admin/brands.html', context, status=400)


@admin_required
def admin_brand_delete(request, brand_id):
    brand = get_object_or_404(Brand, pk=brand_id)

    if request.method == 'POST':
        if brand.products.exists():
            return redirect(f"{redirect('core:admin_brands').url}?delete_blocked=1")
        brand.delete()

    return redirect('core:admin_brands')


@admin_required
def admin_category_create(request):
    if request.method != 'POST':
        return redirect('core:admin_categories')

    form = CategoryForm(request.POST)
    if form.is_valid():
        form.save()
        return redirect('core:admin_categories')

    context = build_admin_base_context(active_panel='categories', page_title='Quản lý danh mục')
    context.update({'category_form': form, 'editing_category': None})
    return render(request, 'core/admin/categories.html', context, status=400)


@admin_required
def admin_category_update(request, category_id):
    category = get_object_or_404(Category, pk=category_id)

    if request.method != 'POST':
        return redirect('core:admin_categories')

    form = CategoryForm(request.POST, instance=category)
    if form.is_valid():
        form.save()
        return redirect('core:admin_categories')

    context = build_admin_base_context(active_panel='categories', page_title='Quản lý danh mục')
    context.update({'category_form': form, 'editing_category': category})
    return render(request, 'core/admin/categories.html', context, status=400)


@admin_required
def admin_category_delete(request, category_id):
    category = get_object_or_404(Category, pk=category_id)

    if request.method == 'POST':
        category.delete()

    return redirect('core:admin_categories')


@admin_required
def admin_attribute_group_create(request):
    if request.method != 'POST':
        return redirect('core:admin_attribute_groups')

    form = AttributeGroupForm(request.POST)
    if form.is_valid():
        form.save()
        return redirect('core:admin_attribute_groups')

    context = build_admin_base_context(active_panel='attribute_groups', page_title='Quản lý nhóm thuộc tính')
    context.update({'attribute_group_form': form, 'editing_group': None})
    return render(request, 'core/admin/attribute_groups.html', context, status=400)


@admin_required
def admin_attribute_group_update(request, group_id):
    group = get_object_or_404(AttributeGroup, pk=group_id)

    if request.method != 'POST':
        return redirect('core:admin_attribute_groups')

    form = AttributeGroupForm(request.POST, instance=group)
    if form.is_valid():
        form.save()
        return redirect('core:admin_attribute_groups')

    context = build_admin_base_context(active_panel='attribute_groups', page_title='Quản lý nhóm thuộc tính')
    context.update({'attribute_group_form': form, 'editing_group': group})
    return render(request, 'core/admin/attribute_groups.html', context, status=400)


@admin_required
def admin_attribute_group_delete(request, group_id):
    group = get_object_or_404(AttributeGroup, pk=group_id)

    if request.method == 'POST':
        if group.has_product_usage():
            group.is_active = False
            group.save(update_fields=['is_active'])
        else:
            group.delete()

    return redirect('core:admin_attribute_groups')


@admin_required
def admin_attribute_value_create(request):
    if request.method != 'POST':
        return redirect('core:admin_attribute_values')

    form = AttributeValueForm(request.POST)
    if form.is_valid():
        form.save()
        return redirect('core:admin_attribute_values')

    context = build_admin_base_context(active_panel='attribute_values', page_title='Quản lý giá trị thuộc tính')
    context.update({'attribute_value_form': form, 'editing_value': None})
    return render(request, 'core/admin/attribute_values.html', context, status=400)


@admin_required
def admin_attribute_value_update(request, value_id):
    attribute_value = get_object_or_404(AttributeValue, pk=value_id)

    if request.method != 'POST':
        return redirect('core:admin_attribute_values')

    form = AttributeValueForm(request.POST, instance=attribute_value)
    if form.is_valid():
        form.save()
        return redirect('core:admin_attribute_values')

    context = build_admin_base_context(active_panel='attribute_values', page_title='Quản lý giá trị thuộc tính')
    context.update({'attribute_value_form': form, 'editing_value': attribute_value})
    return render(request, 'core/admin/attribute_values.html', context, status=400)


@admin_required
def admin_attribute_value_delete(request, value_id):
    attribute_value = get_object_or_404(AttributeValue, pk=value_id)

    if request.method == 'POST':
        if attribute_value.has_product_usage():
            attribute_value.deactivate()
        else:
            attribute_value.delete()

    return redirect('core:admin_attribute_values')


# ===== REVIEW MODERATION =====

def _recalculate_product_rating(product):
    visible_reviews = ProductReview.objects.filter(product=product, is_visible=True)
    if visible_reviews.exists():
        avg = sum(r.rating for r in visible_reviews) / visible_reviews.count()
        product.rating = round(avg, 1)
    else:
        product.rating = 0.0
    product.save(update_fields=['rating'])


def _build_admin_reviews_context(request):
    search_query = ' '.join((request.GET.get('q') or '').split())
    rating_filter = (request.GET.get('rating') or '').strip()
    visibility_filter = (request.GET.get('visibility') or '').strip()
    date_from_raw = (request.GET.get('date_from') or '').strip()
    date_to_raw = (request.GET.get('date_to') or '').strip()

    date_from = None
    date_to = None
    try:
        if date_from_raw:
            date_from = datetime.datetime.strptime(date_from_raw, '%Y-%m-%d').date()
    except ValueError:
        pass
    try:
        if date_to_raw:
            date_to = datetime.datetime.strptime(date_to_raw, '%Y-%m-%d').date()
    except ValueError:
        pass

    qs = (
        ProductReview.objects
        .select_related('user', 'product', 'product__category', 'product__brand')
        .order_by('-created_at')
    )

    if search_query:
        qs = qs.filter(
            Q(product__name__icontains=search_query)
            | Q(user__name__icontains=search_query)
            | Q(user__email__icontains=search_query)
            | Q(user__phone__icontains=search_query)
            | Q(comment__icontains=search_query)
        )

    if rating_filter and rating_filter.isdigit() and 1 <= int(rating_filter) <= 5:
        qs = qs.filter(rating=int(rating_filter))

    if visibility_filter == 'visible':
        qs = qs.filter(is_visible=True)
    elif visibility_filter == 'hidden':
        qs = qs.filter(is_visible=False)

    if date_from:
        dt_from = _datetime_bound(date_from, is_max=False)
        qs = qs.filter(created_at__gte=dt_from)
    if date_to:
        dt_to = _datetime_bound(date_to, is_max=True)
        qs = qs.filter(created_at__lte=dt_to)

    total_qs = ProductReview.objects.all()
    reviews_stats = {
        'total': total_qs.count(),
        'visible': total_qs.filter(is_visible=True).count(),
        'hidden': total_qs.filter(is_visible=False).count(),
    }

    reviews_page, _ = _paginate_queryset(request, qs, per_page=20, page_param='page')

    reviews = []
    for idx, review in enumerate(reviews_page.object_list, start=1 + (reviews_page.number - 1) * 20):
        reviews.append({
            'id': review.id,
            'index': idx,
            'product_name': review.product.name,
            'product_slug': review.product.slug,
            'product_id': review.product.id,
            'user_name': review.user.name or review.user.email,
            'user_email': review.user.email,
            'user_phone': review.user.phone or '',
            'rating': review.rating,
            'comment': review.comment,
            'is_visible': review.is_visible,
            'created_at': review.created_at.strftime('%d-%m-%Y, %H:%M'),
        })

    return {
        'reviews': reviews,
        'reviews_page': reviews_page,
        'reviews_total': qs.count(),
        'reviews_stats': reviews_stats,
        'reviews_search_query': search_query,
        'reviews_rating_filter': rating_filter,
        'reviews_visibility_filter': visibility_filter,
        'reviews_date_from': date_from_raw,
        'reviews_date_to': date_to_raw,
        'reviews_query_string': _build_query_string(request, excluded_keys=['page']),
    }


@admin_required
def admin_reviews(request):
    context = build_admin_base_context(active_panel='reviews', page_title='Quản lý đánh giá')
    context.update(_build_admin_reviews_context(request))
    return render(request, 'core/admin/reviews.html', context)


@admin_required
def admin_review_detail(request, review_id):
    review = get_object_or_404(
        ProductReview.objects.select_related('user', 'product'),
        pk=review_id,
    )
    context = build_admin_base_context(active_panel='reviews', page_title='Chi tiết đánh giá')
    context['review_detail'] = {
        'id': review.id,
        'product': review.product,
        'user_name': review.user.name or review.user.email,
        'user_email': review.user.email,
        'user_phone': review.user.phone or '',
        'rating': review.rating,
        'comment': review.comment,
        'is_visible': review.is_visible,
        'created_at': review.created_at.strftime('%d-%m-%Y, %H:%M'),
    }
    return render(request, 'core/admin/review_detail.html', context)


@admin_required
@require_POST
def admin_review_toggle(request, review_id):
    review = get_object_or_404(ProductReview, pk=review_id)
    review.is_visible = not review.is_visible
    review.save(update_fields=['is_visible'])
    _recalculate_product_rating(review.product)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'is_visible': review.is_visible})

    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or 'core:admin_reviews'
    if next_url.startswith('/'):
        from django.http import HttpResponseRedirect
        return HttpResponseRedirect(next_url)
    return redirect('core:admin_reviews')


@admin_required
@require_POST
def admin_review_bulk(request):
    action = request.POST.get('bulk_action')
    ids_raw = request.POST.getlist('review_ids')

    try:
        ids = [int(i) for i in ids_raw if i.isdigit()]
    except (ValueError, TypeError):
        ids = []

    if not ids:
        return redirect('core:admin_reviews')

    reviews = ProductReview.objects.filter(pk__in=ids).select_related('product')

    if action == 'hide':
        reviews.update(is_visible=False)
    elif action == 'show':
        reviews.update(is_visible=True)

    affected_product_ids = list(reviews.values_list('product_id', flat=True).distinct())
    for product in Product.objects.filter(pk__in=affected_product_ids):
        _recalculate_product_rating(product)

    return redirect('core:admin_reviews')


@admin_required
def admin_revenue_report(request):
    from analytics.revenue_service import (
        RevenueFilters,
        export_revenue_xlsx,
        get_revenue_report,
    )

    period = request.GET.get('period', 'day')
    if period not in ('day', 'month', 'quarter', 'year'):
        period = 'day'

    date_from_raw = request.GET.get('date_from', '')
    date_to_raw = request.GET.get('date_to', '')
    date_from = None
    date_to = None
    if date_from_raw:
        try:
            date_from = datetime.datetime.strptime(date_from_raw, '%Y-%m-%d').date()
        except ValueError:
            pass
    if date_to_raw:
        try:
            date_to = datetime.datetime.strptime(date_to_raw, '%Y-%m-%d').date()
        except ValueError:
            pass

    try:
        top_limit = max(1, int(request.GET.get('top_limit', 10)))
    except (TypeError, ValueError):
        top_limit = 10

    brand_ids = [int(x) for x in request.GET.getlist('brand') if x.isdigit()]
    category_ids = [int(x) for x in request.GET.getlist('category') if x.isdigit()]
    payment_methods = [x for x in request.GET.getlist('payment_method') if x in {'cod', 'bank_transfer', 'momo', 'vnpay'}]

    filters = RevenueFilters(
        period=period,
        date_from=date_from,
        date_to=date_to,
        top_limit=top_limit,
        brand_ids=brand_ids,
        category_ids=category_ids,
        payment_methods=payment_methods,
    )

    export = request.GET.get('export')
    if export == 'xlsx':
        xlsx_data = export_revenue_xlsx(filters, request=request)
        response = HttpResponse(
            xlsx_data,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = 'attachment; filename="revenue_report.xlsx"'
        return response

    try:
        page = max(1, int(request.GET.get('page', 1)))
    except (TypeError, ValueError):
        page = 1

    report = get_revenue_report(filters, page=page)
    trend = report['trend']

    context = build_admin_base_context(active_panel='revenue', page_title='Thống Kê Doanh Thu')
    context.update({
        'report': report,
        'current_period': period,
        'current_date_from': date_from_raw,
        'current_date_to': date_to_raw,
        'current_top_limit': top_limit,
        'selected_brands': brand_ids,
        'selected_categories': category_ids,
        'selected_payment_methods': payment_methods,
        'revenue_labels_json': json.dumps([row['period_label'] for row in trend]),
        'revenue_data_json': json.dumps([float(row['revenue']) for row in trend]),
        'orders_data_json': json.dumps([row['orders'] for row in trend]),
        'aov_data_json': json.dumps([float(row['aov']) for row in trend]),
    })
    return render(request, 'core/admin/revenue_report.html', context)
