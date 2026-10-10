import hashlib
import json
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.db.models import Case, Count, DecimalField, IntegerField, Max, Min, Q, Value, When
from django.db.models.functions import Coalesce

from chatbot.intent.aliases import BOOLEAN_LIKE_GROUPS, SUGGESTABLE_GROUPS
from chatbot.intent.resolver import normalize_sort_by, validate_filters_against_db
from chatbot.serializers import serialize_pair, strip_rich_text
from products.models import AttributeGroup, Brand, Category, Product

from .recovery import recover_no_results

_ACTIVE_PRODUCTS_CACHE_TTL = 300
_OVERVIEW_CACHE_TTL = 3600
_FILTER_OPTIONS_CACHE_TTL = 3600
_PRODUCT_DETAIL_CACHE_TTL = 600


def _base_queryset():
    return Product.objects.filter(
        is_active=True,
        deleted_at__isnull=True,
    ).annotate(
        effective_price=Coalesce(
            'discount_price',
            'price',
            output_field=DecimalField(max_digits=10, decimal_places=2),
        )
    )


def _normalize_brand_names(brand_name):
    if not brand_name:
        return []

    if isinstance(brand_name, str):
        raw_items = [brand_name]
    else:
        raw_items = list(brand_name)

    names = []
    for raw in raw_items:
        for item in str(raw).split(','):
            cleaned = ' '.join(item.split())
            if cleaned and cleaned.lower() not in {name.lower() for name in names}:
                names.append(cleaned)
    return names


def _parse_decimal(value):
    if value in (None, ''):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _keyword_score_expression(keyword, tokens):
    score = Value(0, output_field=IntegerField())

    if keyword:
        score = score + Case(
            When(product_code__iexact=keyword, then=Value(100)),
            default=Value(0),
            output_field=IntegerField(),
        )
        score = score + Case(
            When(name__istartswith=keyword, then=Value(60)),
            default=Value(0),
            output_field=IntegerField(),
        )
        score = score + Case(
            When(name__icontains=keyword, then=Value(40)),
            default=Value(0),
            output_field=IntegerField(),
        )
        score = score + Case(
            When(brand__name__icontains=keyword, then=Value(25)),
            default=Value(0),
            output_field=IntegerField(),
        )
        score = score + Case(
            When(description__icontains=keyword, then=Value(10)),
            default=Value(0),
            output_field=IntegerField(),
        )
        score = score + Case(
            When(product_information__icontains=keyword, then=Value(8)),
            default=Value(0),
            output_field=IntegerField(),
        )

    for token in tokens:
        score = score + Case(
            When(name__icontains=token, then=Value(8)),
            default=Value(0),
            output_field=IntegerField(),
        )
        score = score + Case(
            When(brand__name__icontains=token, then=Value(6)),
            default=Value(0),
            output_field=IntegerField(),
        )
        score = score + Case(
            When(product_code__icontains=token, then=Value(12)),
            default=Value(0),
            output_field=IntegerField(),
        )
        score = score + Case(
            When(description__icontains=token, then=Value(3)),
            default=Value(0),
            output_field=IntegerField(),
        )
    return score


def _apply_keyword_search(queryset, keyword):
    keyword = ' '.join((keyword or '').split())
    if not keyword:
        return queryset

    tokens = [token for token in keyword.split(' ') if token]

    for token in tokens:
        token_query = (
            Q(name__icontains=token)
            | Q(product_code__icontains=token)
            | Q(brand__name__icontains=token)
            | Q(description__icontains=token)
            | Q(product_information__icontains=token)
        )
        queryset = queryset.filter(token_query)

    return queryset.annotate(
        relevance_score=_keyword_score_expression(keyword, tokens)
    )


def _apply_sort(queryset, sort_by):
    sort_by = normalize_sort_by(sort_by)

    if sort_by == 'price_asc':
        return queryset.order_by('effective_price', '-rating', 'name')
    if sort_by == 'price_desc':
        return queryset.order_by('-effective_price', '-rating', 'name')
    if sort_by == 'rating':
        return queryset.order_by('-rating', 'effective_price', 'name')
    if sort_by == 'popular':
        return queryset.order_by('-view_count', '-rating', 'effective_price', 'name')

    if 'relevance_score' in getattr(queryset.query, 'annotations', {}):
        return queryset.order_by('-relevance_score', '-rating', 'effective_price', 'name')
    return queryset.order_by('-rating', 'effective_price', 'name')


def _tree_categories(categories):
    by_parent = {}
    for category in categories:
        by_parent.setdefault(category.parent_id, []).append(category)

    def build_node(category):
        return {
            'name': category.name,
            'slug': category.slug,
            'children': [build_node(child) for child in by_parent.get(category.id, [])],
        }

    roots = by_parent.get(None, [])
    return [build_node(root) for root in roots]


def get_catalog_overview(ctx=None):
    cache_key = 'chatbot:tool:get_catalog_overview:v1'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    categories = list(Category.objects.select_related('parent').order_by('name'))
    brands = list(Brand.objects.order_by('name').values_list('name', flat=True))
    stats = _base_queryset().aggregate(
        total_products=Count('id'),
        price_min=Min('effective_price'),
        price_max=Max('effective_price'),
    )

    payload = {
        'categories': _tree_categories(categories),
        'brands': brands,
        'price_min': int(stats['price_min']) if stats['price_min'] is not None else None,
        'price_max': int(stats['price_max']) if stats['price_max'] is not None else None,
        'total_products': stats['total_products'],
    }
    cache.set(cache_key, payload, _OVERVIEW_CACHE_TTL)
    return payload


def get_filter_options(category_slug, ctx=None):
    cache_key = f'chatbot:tool:get_filter_options:v3:{category_slug}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    category = Category.objects.filter(slug=category_slug).first()
    if category is None:
        return {
            'found': False,
            'category_slug': category_slug,
            'filters': [],
        }

    filter_groups = AttributeGroup.get_filter_groups_for_category(category)

    filters = []
    for group in filter_groups:
        if group.slug not in SUGGESTABLE_GROUPS:
            continue

        values = []
        allowed_boolean_values = BOOLEAN_LIKE_GROUPS.get(group.slug)
        for value in group.values.all()[:20]:
            if allowed_boolean_values and value.slug not in allowed_boolean_values:
                continue
            values.append({
                'slug': value.slug,
                'value': value.value,
                'hex_color': value.hex_color,
            })

        if not values:
            continue

        filters.append({
            'group_slug': group.slug,
            'group_name': group.name,
            'data_type': group.data_type,
            'filter_type': group.filter_type,
            'values': values,
        })

    payload = {
        'found': True,
        'category_slug': category.slug,
        'category_name': category.name,
        'filters': filters,
    }
    cache.set(cache_key, payload, _FILTER_OPTIONS_CACHE_TTL)
    return payload


def _search_cache_key(payload):
    normalized = {
        'keyword': ' '.join((payload.get('keyword') or '').split()),
        'category_slug': payload.get('category_slug') or '',
        'brand_names': tuple(sorted(_normalize_brand_names(payload.get('brand_name')))),
        'price_min': str(payload.get('price_min') or ''),
        'price_max': str(payload.get('price_max') or ''),
        'attributes': tuple(
            sorted((group, tuple(sorted(values))) for group, values in (payload.get('attributes') or {}).items())
        ),
        'in_stock': bool(payload.get('in_stock')),
        'sort_by': normalize_sort_by(payload.get('sort_by')),
        'limit': min(int(payload.get('limit') or 5), settings.CHATBOT_MAX_SEARCH_LIMIT),
    }
    encoded = json.dumps(normalized, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.md5(encoded.encode('utf-8')).hexdigest()
    return f'chatbot:tool:search:v1:{digest}'


def search_products(
    keyword='',
    category_slug='',
    brand_name=None,
    price_min=None,
    price_max=None,
    attributes=None,
    in_stock=False,
    sort_by='relevance',
    limit=5,
    ctx=None,
):
    limit = max(1, min(int(limit or 5), settings.CHATBOT_MAX_SEARCH_LIMIT))
    price_min = _parse_decimal(price_min)
    price_max = _parse_decimal(price_max)
    if price_min and price_max and price_min > price_max:
        price_min, price_max = price_max, price_min

    brand_names = _normalize_brand_names(brand_name)
    validated_attributes = validate_filters_against_db(attributes or {}, category_slug=category_slug or None)

    cache_payload = {
        'keyword': keyword,
        'category_slug': category_slug,
        'brand_name': brand_names,
        'price_min': price_min,
        'price_max': price_max,
        'attributes': validated_attributes,
        'in_stock': in_stock,
        'sort_by': sort_by,
        'limit': limit,
    }
    cache_key = _search_cache_key(cache_payload)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    queryset = _base_queryset()

    category = None
    if category_slug:
        category = Category.objects.filter(slug=category_slug).first()
        if category is None:
            return {
                'found': False,
                'keyword': keyword,
                'category_slug': category_slug,
                'results': [],
                'ui_results': [],
                'filters_applied': {'attributes': validated_attributes},
                'relaxation': None,
                'message': 'Danh mục không tồn tại.',
            }
        queryset = queryset.filter(category=category)

    if brand_names:
        brand_query = Q()
        for name in brand_names:
            brand_query |= Q(brand__name__iexact=name)
        queryset = queryset.filter(brand_query)

    if price_min is not None:
        queryset = queryset.filter(effective_price__gte=price_min)
    if price_max is not None:
        queryset = queryset.filter(effective_price__lte=price_max)

    if in_stock:
        queryset = queryset.filter(stock__gt=0)

    if validated_attributes:
        queryset = queryset.filter_by_attributes(**validated_attributes)

    queryset = _apply_keyword_search(queryset, keyword)
    queryset = _apply_sort(queryset, sort_by)

    product_ids = list(queryset.values_list('id', flat=True)[:limit])
    product_map = {
        product.id: product
        for product in _base_queryset().filter(id__in=product_ids).with_related_data()
    }
    products = [product_map[product_id] for product_id in product_ids if product_id in product_map]

    llm_results, ui_results = serialize_pair(products)

    payload = {
        'found': bool(products),
        'keyword': keyword,
        'category_slug': category.slug if category else '',
        'category_name': category.name if category else '',
        'brand_names': brand_names,
        'results': llm_results,
        'ui_results': ui_results,
        'filters_applied': {
            'attributes': validated_attributes,
            'price_min': int(price_min) if price_min is not None else None,
            'price_max': int(price_max) if price_max is not None else None,
            'in_stock': bool(in_stock),
            'sort_by': normalize_sort_by(sort_by),
        },
        'relaxation': None,
    }

    if not products:
        payload['relaxation'] = recover_no_results(
            keyword=keyword,
            category=category,
            brand_names=brand_names,
            price_min=price_min,
            price_max=price_max,
            attributes=validated_attributes,
            in_stock=in_stock,
            sort_by=sort_by,
            limit=limit,
        )

    cache.set(cache_key, payload, _ACTIVE_PRODUCTS_CACHE_TTL)
    return payload


def _name_tokens_from_lookup(value):
    return [token for token in str(value or '').replace('-', ' ').split() if token]


def get_product_detail(slug='', product_code='', ctx=None):
    identifier = slug or product_code
    cache_key = f'chatbot:tool:get_product_detail:v2:{slug}:{product_code}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    queryset = _base_queryset().with_related_data()
    if slug:
        product = queryset.filter(slug=slug).first()
    else:
        product = queryset.filter(product_code=product_code).first()

    if product is None:
        tokens = _name_tokens_from_lookup(identifier)
        suggestions_qs = _base_queryset()
        for token in tokens[:3]:
            suggestions_qs = suggestions_qs.filter(Q(name__icontains=token) | Q(product_code__icontains=token))
        suggestions = list(suggestions_qs.with_related_data()[:3])
        llm_results, ui_results = serialize_pair(suggestions)
        payload = {
            'found': False,
            'identifier': identifier,
            'suggestions': llm_results,
            'ui_suggestions': ui_results,
        }
        cache.set(cache_key, payload, _PRODUCT_DETAIL_CACHE_TTL)
        return payload

    llm_results, ui_results = serialize_pair([product], include_all_specs=True, include_reviews=True)

    specs = []
    grouped = {}
    for attribute in product.attributes.all():
        group = attribute.attribute_value.group
        grouped.setdefault(group.slug, {
            'group_slug': group.slug,
            'group_name': group.name,
            'display_order': group.display_order,
            'values': [],
        })
        grouped[group.slug]['values'].append(attribute.resolved_value)

    grouped_items = list(grouped.values())
    grouped_items.sort(key=lambda item: (item['display_order'], item['group_name']))

    for item in grouped_items:
        specs.append({
            'group_slug': item['group_slug'],
            'group_name': item['group_name'],
            'values': item['values'],
        })

    reviews = [review for review in product.reviews.all() if review.is_visible]
    reviews.sort(key=lambda review: review.created_at, reverse=True)

    payload = {
        'found': True,
        'product': llm_results[0],
        'ui_product': ui_results[0],
        'specs': specs,
        'review_count': len(reviews),
        'recent_reviews': [
            {
                'rating': review.rating,
                'comment': strip_rich_text(review.comment, 150),
                'created_at': review.created_at.strftime('%d/%m/%Y %H:%M'),
            }
            for review in reviews[:3]
        ],
    }
    cache.set(cache_key, payload, _PRODUCT_DETAIL_CACHE_TTL)
    return payload
