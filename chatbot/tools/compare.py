from django.db.models import DecimalField
from django.db.models.functions import Coalesce

from chatbot.serializers import serialize_pair
from products.models import Product


MAX_COMPARE_PRODUCTS = 4
MIN_COMPARE_PRODUCTS = 2


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


def compare_products(slugs, ctx=None):
    cleaned_slugs = []
    for slug in slugs or []:
        slug = str(slug).strip()
        if slug and slug not in cleaned_slugs:
            cleaned_slugs.append(slug)

    if len(cleaned_slugs) < MIN_COMPARE_PRODUCTS:
        return {
            'found': False,
            'message': 'Cần ít nhất 2 sản phẩm để so sánh.',
            'products': [],
            'rows_different': [],
            'rows_same': [],
            'missing_slugs': cleaned_slugs,
        }

    cleaned_slugs = cleaned_slugs[:MAX_COMPARE_PRODUCTS]

    products = list(_base_queryset().with_related_data().filter(slug__in=cleaned_slugs))
    product_map = {product.slug: product for product in products}
    ordered_products = [product_map[slug] for slug in cleaned_slugs if slug in product_map]
    missing_slugs = [slug for slug in cleaned_slugs if slug not in product_map]

    llm_products, ui_products = serialize_pair(ordered_products)

    group_rows = {}
    for product in ordered_products:
        for attribute in product.attributes.all():
            group = attribute.attribute_value.group
            row = group_rows.setdefault(group.slug, {
                'group_slug': group.slug,
                'group_name': group.name,
                'display_order': group.display_order,
                'values_by_product': {item.slug: [] for item in ordered_products},
            })
            row['values_by_product'][product.slug].append(attribute.resolved_value)

    rows = []
    for row in group_rows.values():
        values = []
        normalized_values = []
        for product in ordered_products:
            product_values = row['values_by_product'][product.slug]
            if product_values:
                cell = ', '.join(product_values)
            else:
                cell = '—'
            values.append(cell)
            normalized_values.append(cell)

        rows.append({
            'group_slug': row['group_slug'],
            'group_name': row['group_name'],
            'values': values,
            'is_different': len(set(normalized_values)) > 1,
            'display_order': row['display_order'],
        })

    rows.sort(key=lambda item: (item['display_order'], item['group_name']))

    rows_different = [
        {
            'group_slug': row['group_slug'],
            'group_name': row['group_name'],
            'values': row['values'],
            'is_different': row['is_different'],
        }
        for row in rows
        if row['is_different']
    ]
    rows_same = [
        {
            'group_slug': row['group_slug'],
            'group_name': row['group_name'],
            'values': row['values'],
            'is_different': row['is_different'],
        }
        for row in rows
        if not row['is_different']
    ]

    price_row = {
        'group_slug': 'price',
        'group_name': 'Giá',
        'values': [product_payload['final_price'] for product_payload in llm_products],
        'is_different': len({product_payload['final_price'] for product_payload in llm_products}) > 1,
    }

    return {
        'found': bool(ordered_products),
        'products': llm_products,
        'ui_products': ui_products,
        'rows_different': rows_different,
        'rows_same': rows_same,
        'price_row': price_row,
        'missing_slugs': missing_slugs,
    }
