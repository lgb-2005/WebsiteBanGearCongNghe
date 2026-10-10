from decimal import Decimal

from django.db.models import Count, DecimalField, Q
from django.db.models.functions import Coalesce

from chatbot.serializers import serialize_pair
from products.models import Category, Product, ProductAttribute


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


def _apply_common_filters(queryset, category=None, brand_names=None, price_min=None, price_max=None,
                          attributes=None, in_stock=False):
    if category is not None:
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

    if attributes:
        queryset = queryset.filter_by_attributes(**attributes)

    return queryset


def _serialize_suggestions(products):
    llm_results, ui_results = serialize_pair(products)
    return {
        'results': llm_results,
        'ui_results': ui_results,
    }


def _try_price_relaxation(keyword, category, brand_names, price_min, price_max, attributes, in_stock, sort_by, limit):
    if price_min is None and price_max is None:
        return None

    new_min = price_min
    new_max = price_max
    applied = []

    if price_min is not None:
        new_min = max(Decimal('0'), price_min * Decimal('0.8'))
        applied.append(f'price_min:{int(price_min)}->{int(new_min)}')
    if price_max is not None:
        new_max = price_max * Decimal('1.2')
        applied.append(f'price_max:{int(price_max)}->{int(new_max)}')

    queryset = _apply_common_filters(
        _base_queryset(),
        category=category,
        brand_names=brand_names,
        price_min=new_min,
        price_max=new_max,
        attributes=attributes,
        in_stock=in_stock,
    )

    if keyword:
        for token in keyword.split():
            queryset = queryset.filter(
                Q(name__icontains=token)
                | Q(product_code__icontains=token)
                | Q(brand__name__icontains=token)
                | Q(description__icontains=token)
                | Q(product_information__icontains=token)
            )

    products = list(queryset.order_by('-rating', 'effective_price', 'name').with_related_data()[:limit])
    if not products:
        return None

    payload = _serialize_suggestions(products)
    payload.update({
        'applied': applied,
        'dropped_filters': [],
        'strategy': 'price_relaxation',
    })
    return payload


def _attribute_usage_counts(attributes):
    flattened = []
    for group_slug, values in (attributes or {}).items():
        for value_slug in values:
            count = ProductAttribute.objects.filter(
                attribute_value__group__slug=group_slug,
                attribute_value__slug=value_slug,
            ).count()
            flattened.append((count, group_slug, value_slug))
    return sorted(flattened, key=lambda item: (item[0], item[1], item[2]))


def _drop_attribute(attributes, group_slug, value_slug):
    cloned = {group: list(values) for group, values in (attributes or {}).items()}
    current = [value for value in cloned.get(group_slug, []) if value != value_slug]
    if current:
        cloned[group_slug] = current
    else:
        cloned.pop(group_slug, None)
    return cloned


def _try_attribute_relaxation(keyword, category, brand_names, price_min, price_max, attributes, in_stock, limit):
    dropped_filters = []
    current_attributes = {group: list(values) for group, values in (attributes or {}).items()}

    for _count, group_slug, value_slug in _attribute_usage_counts(current_attributes)[:2]:
        current_attributes = _drop_attribute(current_attributes, group_slug, value_slug)
        dropped_filters.append(f'{group_slug}:{value_slug}')

        queryset = _apply_common_filters(
            _base_queryset(),
            category=category,
            brand_names=brand_names,
            price_min=price_min,
            price_max=price_max,
            attributes=current_attributes,
            in_stock=in_stock,
        )
        if keyword:
            for token in keyword.split():
                queryset = queryset.filter(
                    Q(name__icontains=token)
                    | Q(product_code__icontains=token)
                    | Q(brand__name__icontains=token)
                    | Q(description__icontains=token)
                    | Q(product_information__icontains=token)
                )

        products = list(queryset.order_by('-rating', 'effective_price', 'name').with_related_data()[:limit])
        if products:
            payload = _serialize_suggestions(products)
            payload.update({
                'applied': [],
                'dropped_filters': dropped_filters,
                'strategy': 'attribute_relaxation',
            })
            return payload

    return None


def _try_parent_category(keyword, category, brand_names, price_min, price_max, attributes, in_stock, limit):
    if category is None or category.parent_id is None:
        return None

    parent = Category.objects.filter(pk=category.parent_id).first()
    if parent is None:
        return None

    queryset = _apply_common_filters(
        _base_queryset(),
        category=parent,
        brand_names=brand_names,
        price_min=price_min,
        price_max=price_max,
        attributes={},
        in_stock=in_stock,
    )
    if keyword:
        for token in keyword.split():
            queryset = queryset.filter(
                Q(name__icontains=token)
                | Q(product_code__icontains=token)
                | Q(brand__name__icontains=token)
                | Q(description__icontains=token)
                | Q(product_information__icontains=token)
            )

    products = list(queryset.order_by('-rating', 'effective_price', 'name').with_related_data()[:limit])
    if not products:
        return None

    payload = _serialize_suggestions(products)
    payload.update({
        'applied': [f'category:{category.slug}->{parent.slug}'],
        'dropped_filters': list(attributes.keys()),
        'strategy': 'parent_category',
    })
    return payload


def _fallback_products(category, brand_names, in_stock, limit):
    queryset = _base_queryset()
    if category is not None:
        queryset = queryset.filter(category=category)
    if brand_names:
        brand_query = Q()
        for name in brand_names:
            brand_query |= Q(brand__name__iexact=name)
        queryset = queryset.filter(brand_query)
    if in_stock:
        queryset = queryset.filter(stock__gt=0)

    products = list(queryset.order_by('-rating', '-view_count', 'effective_price', 'name').with_related_data()[:limit])
    if not products and category is not None:
        products = list(
            _base_queryset().filter(category=category).order_by('-rating', '-view_count', 'effective_price', 'name').with_related_data()[:limit]
        )

    payload = _serialize_suggestions(products)
    payload.update({
        'applied': [],
        'dropped_filters': [],
        'strategy': 'fallback_top_rated',
    })
    return payload


def recover_no_results(keyword='', category=None, brand_names=None, price_min=None, price_max=None,
                       attributes=None, in_stock=False, sort_by='relevance', limit=5):
    keyword = ' '.join((keyword or '').split())
    attributes = attributes or {}
    brand_names = brand_names or []

    for strategy in (
        lambda: _try_price_relaxation(keyword, category, brand_names, price_min, price_max, attributes, in_stock, sort_by, limit),
        lambda: _try_attribute_relaxation(keyword, category, brand_names, price_min, price_max, attributes, in_stock, limit),
        lambda: _try_parent_category(keyword, category, brand_names, price_min, price_max, attributes, in_stock, limit),
    ):
        result = strategy()
        if result is not None:
            return result

    return _fallback_products(category, brand_names, in_stock, limit)
