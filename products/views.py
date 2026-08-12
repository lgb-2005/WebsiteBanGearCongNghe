from django.http import Http404
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, ListView, UpdateView
from django.db.models import Count, F, Prefetch, Q
from django.utils import timezone
from django.db.models.functions import Coalesce
from django.core.paginator import Paginator
from .forms import BrandForm, ProductAdminForm, ProductReviewForm
from .models import AttributeGroup, AttributeValue, Brand, Category, Product, Favorite, ProductReview
from .serializers import ProductSerializer

# Create your views here.

_REVIEW_PAGE_SIZE = 10
_LISTING_PAGE_SIZE = 50


def _pagination_window(page_obj, window=2):
    paginator = page_obj.paginator
    current = page_obj.number
    pages = set()
    for i in range(max(1, current - window), min(paginator.num_pages, current + window) + 1):
        pages.add(i)
    pages.add(1)
    pages.add(paginator.num_pages)
    sorted_pages = sorted(pages)
    result = []
    prev = None
    for page in sorted_pages:
        if prev is not None and page > prev + 1:
            result.append(None)
        result.append(page)
        prev = page
    return result


def _parse_brand_param(request):
    brand_param = request.GET.get('brand', '')
    if not brand_param:
        return []
    brand_ids = []
    for raw in brand_param.split(','):
        try:
            brand_ids.append(int(raw.strip()))
        except ValueError:
            continue
    return brand_ids


def _get_brand_options(queryset):
    brand_ids = (
        queryset.filter(brand__isnull=False)
        .values('brand__id')
        .distinct()
    )
    return list(
        Brand.objects.filter(id__in=brand_ids)
        .values('id', 'name')
        .order_by('name')
    )


def _has_purchased(user, product):
    if not user.is_authenticated:
        return False
    from orders.models import Order
    return Order.objects.filter(
        customer__user=user,
        status='completed',
        items__product=product,
    ).exists()


def _serialize_review(review):
    user = review.user
    name = getattr(user, 'name', None) or getattr(user, 'username', '') or user.email
    avatar_url = ''
    if user.avatar:
        try:
            avatar_url = user.avatar.url
        except Exception:
            avatar_url = ''
    return {
        'id': review.id,
        'user_name': name,
        'avatar_url': avatar_url,
        'rating': review.rating,
        'comment': review.comment,
        'created_at': review.created_at.strftime('%d/%m/%Y %H:%M'),
    }


def _resolve_image_url(image_value):
    if not image_value:
        return ''
    image_url = getattr(image_value, 'url', None)
    if image_url:
        return image_url
    return str(image_value)


def _format_currency(value):
    if value in (None, ''):
        return ''
    try:
        return f"{int(value):,} đ".replace(',', '.')
    except (TypeError, ValueError):
        return ''


def _parse_product_information(product_information):
    items = []
    for raw_line in (product_information or '').splitlines():
        line = raw_line.strip()
        if not line or ':' not in line:
            continue
        label, value = [part.strip() for part in line.split(':', 1)]
        if label and value:
            items.append({
                'label': label,
                'value': value,
            })
    return items


def _build_attribute_filters(query_dict, allowed_group_slugs=None):

    filters = {}
    allowed_group_slugs = set(allowed_group_slugs or [])
    reserved_keys = {'q', 'sort', 'price_min', 'price_max'}

    for key in query_dict.keys():

        if key in reserved_keys:
            continue

        if allowed_group_slugs and key not in allowed_group_slugs:
            continue

        raw_values = query_dict.getlist(key)

        values = []

        for raw in raw_values:
            values.extend([
                item.strip()
                for item in raw.split(',')
                if item.strip()
            ])

        if not values:
            continue

        filters[key] = values

    return filters


def _serialize_listing_product(product):
    current_price = product.discount_price if product.discount_price is not None else product.price
    old_price = product.price if product.discount_price is not None and product.discount_price < product.price else None
    discount_percent = None

    if old_price:
        try:
            discount_percent = int(round(((product.price - product.discount_price) / product.price) * 100))
        except (TypeError, ValueError, ZeroDivisionError):
            discount_percent = None

    return {
        'id': product.id,
        'name': product.name,
        'slug': product.slug,
        'image_url': _resolve_image_url(product.main_image),
        'price': _format_currency(current_price),
        'old_price': _format_currency(old_price) if old_price else '',
        'discount_percent': discount_percent,
        'brand_name': product.brand.name if product.brand else '',
        'stock': product.stock,
    }


def _get_sort_label(sort_param):
    return {
        'featured': 'Nổi bật',
        'name-asc': 'Tên từ A-Z',
        'name-desc': 'Tên từ Z-A',
        'price-asc': 'Giá tăng dần',
        'price-desc': 'Giá giảm dần',
    }.get(sort_param, 'Tên từ A-Z')


def _apply_price_filters(queryset, price_min, price_max):
    if price_min and price_min.isdigit():
        queryset = queryset.filter(effective_price__gte=float(price_min))

    if price_max and price_max.isdigit():
        queryset = queryset.filter(effective_price__lte=float(price_max))

    return queryset


def _apply_listing_sorting(queryset, sort_param):
    if sort_param == 'featured':
        return queryset.order_by('-effective_price', '-created_at')

    if sort_param == 'name-asc':
        return queryset.order_by('name')

    if sort_param == 'name-desc':
        return queryset.order_by('-name')

    if sort_param == 'price-asc':
        return queryset.order_by('effective_price', '-created_at')

    if sort_param == 'price-desc':
        return queryset.order_by('-effective_price', '-created_at')

    return queryset.order_by('name')


def _apply_search_query(queryset, search_query):
    normalized_query = ' '.join((search_query or '').split())

    if not normalized_query:
        return queryset.none()

    tokens = [token for token in normalized_query.split(' ') if token]

    search_filters = (
        Q(name__icontains=normalized_query)
        | Q(brand__name__icontains=normalized_query)
        | Q(product_code__icontains=normalized_query)
    )

    for token in tokens:
        search_filters |= (
            Q(name__icontains=token)
            | Q(brand__name__icontains=token)
            | Q(product_code__icontains=token)
        )

    return queryset.filter(search_filters).distinct()


def _build_filter_group_options(filter_groups, attribute_filters):
    filter_group_options = []

    for group in filter_groups:
        prefetched_values = getattr(group, 'filtered_values', None)
        filter_group_options.append(
            {
                'group': group,
                'values': list(prefetched_values) if prefetched_values is not None else list(group.values.filter(is_active=True).order_by('display_order', 'value')),
                'selected_values': attribute_filters.get(group.slug, []),
            }
        )

    return filter_group_options


def _get_search_filter_groups(products_queryset, attribute_filters):
    product_ids = list(products_queryset.values_list('id', flat=True))

    if not product_ids:
        return []

    groups = list(
        AttributeGroup.objects.filter(
            is_filterable=True,
            is_active=True,
            values__productattribute__product_id__in=product_ids,
        )
        .prefetch_related(
            Prefetch(
                'values',
                queryset=(
                    AttributeValue.objects.filter(
                        is_active=True,
                        productattribute__product_id__in=product_ids,
                    )
                    .select_related('group')
                    .order_by('display_order', 'value')
                    .distinct()
                ),
                to_attr='filtered_values',
            )
        )
        .distinct()
        .order_by('display_order', 'name')
    )

    selected_group_slugs = set(attribute_filters.keys())
    selected_value_slugs = {
        value_slug
        for values in attribute_filters.values()
        for value_slug in values
    }

    if not selected_group_slugs:
        return groups

    selected_groups = list(
        AttributeGroup.objects.filter(
            slug__in=selected_group_slugs,
            is_filterable=True,
            is_active=True,
            values__slug__in=selected_value_slugs,
        )
        .prefetch_related(
            Prefetch(
                'values',
                queryset=(
                    AttributeValue.objects.filter(
                        is_active=True,
                        slug__in=selected_value_slugs,
                    )
                    .select_related('group')
                    .order_by('display_order', 'value')
                    .distinct()
                ),
                to_attr='filtered_values',
            )
        )
        .distinct()
        .order_by('display_order', 'name')
    )

    existing_group_slugs = {group.slug for group in groups}
    for group in selected_groups:
        if group.slug not in existing_group_slugs:
            groups.append(group)

    groups.sort(key=lambda item: (item.display_order, item.name))
    return groups


def category_products(request, category_slug):
    category = get_object_or_404(Category, slug=category_slug)

    sort_param = request.GET.get('sort', 'name-asc')
    sort_label = _get_sort_label(sort_param)

    base_queryset = (
        Product.objects
        .filter(category=category, is_active=True)
        .with_related_data()
        .annotate(
            effective_price=Coalesce('discount_price', 'price')
        )
    )

    # Apply price range filter
    price_min = request.GET.get('price_min')
    price_max = request.GET.get('price_max')
    products_queryset = _apply_price_filters(base_queryset, price_min, price_max)

    # Build filter groups/values based on the current product set
    filter_groups = _get_search_filter_groups(products_queryset, {})
    attribute_filters = _build_attribute_filters(
        request.GET,
        allowed_group_slugs=[group.slug for group in filter_groups],
    )

    products_queryset = products_queryset.filter_by_attributes(**attribute_filters)
    filter_groups = _get_search_filter_groups(products_queryset, attribute_filters)

    # Apply brand filter
    selected_brands = _parse_brand_param(request)
    brand_options = _get_brand_options(products_queryset)
    if selected_brands:
        products_queryset = products_queryset.filter(brand__id__in=selected_brands)

    products_queryset = _apply_listing_sorting(products_queryset, sort_param)

    paginator = Paginator(products_queryset, _LISTING_PAGE_SIZE)
    try:
        page_number = max(1, int(request.GET.get('page', 1)))
    except ValueError:
        page_number = 1
    page_obj = paginator.get_page(page_number)
    category_products_list = [_serialize_listing_product(product) for product in page_obj]

    query_params = request.GET.copy()
    query_params.pop('page', None)

    filter_groups = list(filter_groups)
    filter_group_options = _build_filter_group_options(filter_groups, attribute_filters)

    category_navigation = [
        {
            'name': item.name,
            'slug': item.slug,
            'is_active': item.id == category.id,
        }
        for item in Category.objects.filter(parent__isnull=True).order_by('name')
    ]

    context = {
        'category': category,
        'category_slug': category_slug,
        'products': category_products_list,
        'products_count': paginator.count,
        'filter_groups': filter_groups,
        'filter_group_options': filter_group_options,
        'active_attribute_filters': attribute_filters,
        'brand_options': brand_options,
        'selected_brands': selected_brands,
        'category_navigation': category_navigation,
        'sort_label': sort_label,
        'price_min': price_min if price_min and price_min.isdigit() else 0,
        'price_max': price_max if price_max and price_max.isdigit() else 10000000,
        'show_filters': True,
        'page_obj': page_obj,
        'paginator': paginator,
        'is_paginated': paginator.num_pages > 1,
        'page_numbers': _pagination_window(page_obj),
        'query_params': query_params.urlencode(),
    }
    return render(request, 'products/category_products.html', context)


def search_products(request):
    search_query = (request.GET.get('q') or '').strip()
    price_min = request.GET.get('price_min')
    price_max = request.GET.get('price_max')
    sort_param = request.GET.get('sort', 'name-asc')
    sort_label = _get_sort_label(sort_param)

    base_queryset = (
        Product.objects
        .filter(is_active=True)
        .with_related_data()
        .annotate(effective_price=Coalesce('discount_price', 'price'))
    )

    products_queryset = base_queryset.none()
    filter_groups = []
    attribute_filters = {}
    validation_message = ''
    selected_brands = []
    brand_options = []

    if search_query:
        print(search_query)
        search_queryset = _apply_search_query(base_queryset, search_query)
        print(search_queryset.query)
        print(search_queryset.count())
        search_queryset = _apply_price_filters(search_queryset, price_min, price_max)

        filter_groups = _get_search_filter_groups(search_queryset, {})
        attribute_filters = _build_attribute_filters(
            request.GET,
            allowed_group_slugs=[group.slug for group in filter_groups],
        )
        print(attribute_filters)

        products_queryset = search_queryset.filter_by_attributes(**attribute_filters)
        filter_groups = _get_search_filter_groups(products_queryset, attribute_filters)

        selected_brands = _parse_brand_param(request)
        brand_options = _get_brand_options(products_queryset)
        if selected_brands:
            products_queryset = products_queryset.filter(brand__id__in=selected_brands)

        products_queryset = _apply_listing_sorting(products_queryset, sort_param)
    elif 'q' in request.GET:
        validation_message = 'Vui lòng nhập từ khóa tìm kiếm'

    paginator = Paginator(products_queryset, _LISTING_PAGE_SIZE)
    try:
        page_number = max(1, int(request.GET.get('page', 1)))
    except ValueError:
        page_number = 1
    page_obj = paginator.get_page(page_number)
    products = [_serialize_listing_product(product) for product in page_obj]

    query_params = request.GET.copy()
    query_params.pop('page', None)
    filter_group_options = _build_filter_group_options(filter_groups, attribute_filters) if paginator.count else []

    context = {
        'page_title': 'Kết quả tìm kiếm',
        'page_description': 'Tìm thấy %(count)s sản phẩm cho từ khóa:' % {'count': paginator.count},
        'search_query': search_query,
        'products': products,
        'products_count': paginator.count,
        'filter_groups': filter_groups,
        'filter_group_options': filter_group_options,
        'active_attribute_filters': attribute_filters,
        'brand_options': brand_options,
        'selected_brands': selected_brands,
        'sort_label': sort_label,
        'price_min': price_min if price_min and price_min.isdigit() else 0,
        'price_max': price_max if price_max and price_max.isdigit() else 10000000,
        'empty_message': validation_message or 'Không tìm thấy sản phẩm phù hợp.',
        'validation_message': validation_message,
        'show_filters': bool(paginator.count),
        'page_obj': page_obj,
        'paginator': paginator,
        'is_paginated': paginator.num_pages > 1,
        'page_numbers': _pagination_window(page_obj),
        'query_params': query_params.urlencode(),
    }
    return render(request, 'products/search_results.html', context)


def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.with_related_data(),
        slug=slug,
        is_active=True
    )

    # tăng view
    Product.objects.filter(pk=product.pk).update(
        view_count=F('view_count') + 1
    )
    product.refresh_from_db()

    try:
        from analytics.services import track_event
        track_event(request, 'view_product', product=product)
    except Exception:
        pass

    # lấy reviews
    reviews_qs = product.reviews.filter(is_visible=True).select_related('user').order_by('-created_at')
    review_count = reviews_qs.count()
    initial_reviews = list(reviews_qs[:_REVIEW_PAGE_SIZE])

    # favorite + review eligibility
    is_favorited = False
    has_purchased = False
    existing_review = None
    if request.user.is_authenticated:
        is_favorited = Favorite.objects.filter(
            user=request.user,
            product=product
        ).exists()
        has_purchased = _has_purchased(request.user, product)
        if has_purchased:
            existing_review = ProductReview.objects.filter(
                user=request.user,
                product=product,
            ).first()

    gallery_images = product.image_urls or [_resolve_image_url(product.main_image)]
    gallery_images = [img for img in gallery_images if img]

    current_price = (
        product.discount_price
        if product.discount_price is not None
        else product.price
    )

    old_price = (
        product.price
        if product.discount_price is not None
        and product.discount_price < product.price
        else None
    )

    discount_percent = None
    if old_price:
        discount_percent = int(
            round(
                ((product.price - product.discount_price)
                 / product.price) * 100
            )
        )

    related_products = []
    related_queryset = (
        Product.objects.filter(category=product.category, is_active=True)
        .exclude(pk=product.pk)
        .select_related('brand', 'category')
        .prefetch_related('images')
        .order_by('-created_at')[:4]
    )

    for item in related_queryset:
        related_products.append({
            'name': item.name,
            'slug': item.slug,
            'image_url': _resolve_image_url(item.main_image),
            'price': _format_currency(
                item.discount_price if item.discount_price else item.price
            ),
            'old_price': _format_currency(item.price)
            if item.discount_price else '',
            'discount_percent': (
                int(round(
                    ((item.price - item.discount_price)
                     / item.price) * 100
                ))
                if item.discount_price else None
            ),
            'brand_name': item.brand.name if item.brand else '',
        })

    _r = float(product.rating) if product.rating else 0.0
    rating_display = str(int(_r)) if _r == int(_r) else f'{_r:g}'

    context = {
        'product': product,
        'gallery_images': gallery_images,
        'current_price': _format_currency(current_price),
        'old_price': _format_currency(old_price) if old_price else '',
        'discount_percent': discount_percent,
        'product_information_items':
            _parse_product_information(product.product_information),
        'related_products': related_products,
        'review_count': review_count,
        'reviews': initial_reviews,
        'has_more_reviews': review_count > _REVIEW_PAGE_SIZE,
        'is_favorited': is_favorited,
        'has_purchased': has_purchased,
        'existing_review': existing_review,
        'rating_display': rating_display,
    }

    return render(
        request,
        'products/product_detail.html',
        context
    )


class BrandListView(ListView):
    model = Brand
    template_name = 'products/brand_list.html'
    context_object_name = 'brands'
    ordering = ['name']

    def get_queryset(self):
        return Brand.objects.annotate(product_count=Count('products')).order_by('name')


class BrandCreateView(CreateView):
    model = Brand
    form_class = BrandForm
    template_name = 'products/brand_form.html'
    success_url = reverse_lazy('products:brand_list')

class BrandUpdateView(UpdateView):
    model = Brand
    form_class = BrandForm
    template_name = 'products/brand_form.html'
    success_url = reverse_lazy('products:brand_list')

class BrandDeleteView(DeleteView):
    model = Brand
    template_name = 'products/brand_confirm_delete.html'
    success_url = reverse_lazy('products:brand_list')

@csrf_exempt
@require_POST
def product_create_api(request):
    form = ProductAdminForm(request.POST, request.FILES)
    if not form.is_valid():
        return JsonResponse({'errors': form.errors}, status=400)

    product = form.save()
    form.save_images(product)
    serializer = ProductSerializer(product, request=request)
    return JsonResponse(serializer.data(), status=201)

@login_required
def toggle_favorite(request, slug):
    product = get_object_or_404(Product, slug=slug)

    favorite = Favorite.objects.filter(user=request.user, product=product)

    if favorite.exists():
        favorite.delete()
        is_favorited = False
    else:
        Favorite.objects.create(user=request.user, product=product)
        is_favorited = True

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True, 'is_favorited': is_favorited})

    return redirect('products:product_detail', slug=slug)


@login_required
def favorite_list(request):
    favorites = Favorite.objects.filter(
        user=request.user
    ).select_related('product')

    return render(request, 'products/favorite_list.html', {
        'favorites': favorites
    })

@login_required
@require_POST
def add_review(request, slug):
    product = get_object_or_404(Product, slug=slug)

    if not _has_purchased(request.user, product):
        return redirect('products:product_detail', slug=slug)

    review = ProductReview.objects.filter(
        user=request.user,
        product=product
    ).first()

    form = ProductReviewForm(request.POST, instance=review)

    if form.is_valid():
        new_review = form.save(commit=False)
        new_review.user = request.user
        new_review.product = product
        new_review.save()

        reviews = ProductReview.objects.filter(product=product)

        if reviews.exists():
            avg_rating = sum(r.rating for r in reviews) / reviews.count()
            product.rating = round(avg_rating, 1)
            product.save()

    return redirect('products:product_detail', slug=slug)


@require_GET
def product_reviews_json(request, slug):
    product = get_object_or_404(Product, slug=slug, is_active=True)
    try:
        offset = max(0, int(request.GET.get('offset', 0)))
    except (TypeError, ValueError):
        offset = 0

    reviews_qs = product.reviews.filter(is_visible=True).select_related('user').order_by('-created_at')
    total = reviews_qs.count()
    batch = list(reviews_qs[offset: offset + _REVIEW_PAGE_SIZE])

    return JsonResponse({
        'reviews': [_serialize_review(r) for r in batch],
        'has_more': (offset + _REVIEW_PAGE_SIZE) < total,
        'next_offset': offset + len(batch),
    })