"""Hai serializer tách biệt: bản gọn cho LLM (tiết kiệm token) và bản giàu cho UI."""

import html as html_module
import re

from django.urls import reverse
from django.utils.html import strip_tags

LLM_SUMMARY_LENGTH = 200
LLM_MAX_SPEC_GROUPS = 5
LLM_REVIEW_LENGTH = 150

_WHITESPACE_RE = re.compile(r'\s+')


def strip_rich_text(value, limit=None):
    """Chuyển HTML CKEditor thành plain text gọn (cạm bẫy T3)."""
    if not value:
        return ''

    text = strip_tags(value)
    text = html_module.unescape(text)
    text = _WHITESPACE_RE.sub(' ', text).strip()

    if limit and len(text) > limit:
        text = text[:limit].rsplit(' ', 1)[0] + '...'

    return text


def to_money(value):
    """Decimal -> int (VND không dùng phần thập phân)."""
    if value is None:
        return None
    return int(round(float(value)))


def final_price_of(product):
    return to_money(product.discount_price or product.price)


def _ordered_attributes(product):
    """Trả [(group_name, resolved_value)] theo AttributeGroup.display_order.

    Dựa hoàn toàn vào prefetch của ``with_related_data()`` nên không sinh query mới.
    """
    rows = []
    for product_attribute in product.attributes.all():
        attribute_value = product_attribute.attribute_value
        group = attribute_value.group
        rows.append((
            group.display_order,
            group.name,
            group.slug,
            product_attribute.resolved_value,
        ))

    rows.sort(key=lambda row: (row[0], row[1]))
    return rows


def _visible_reviews(product):
    return [review for review in product.reviews.all() if review.is_visible]


def to_llm(product, include_all_specs=False, include_reviews=False):
    """Bản tối giản dành cho LLM. Không chứa ảnh, view_count, HTML."""
    attribute_rows = _ordered_attributes(product)

    specs = {}
    for _order, group_name, _group_slug, value in attribute_rows:
        if group_name in specs:
            specs[group_name] = f'{specs[group_name]}, {value}'
            continue
        if not include_all_specs and len(specs) >= LLM_MAX_SPEC_GROUPS:
            continue
        specs[group_name] = value

    payload = {
        'slug': product.slug,
        'name': product.name,
        'brand': product.brand.name if product.brand_id else None,
        'category': product.category.name if product.category_id else None,
        'price': to_money(product.price),
        'final_price': final_price_of(product),
        'discount_percent': product.discount_percent,
        'in_stock': product.stock > 0,
        'rating': float(product.rating or 0),
        'key_specs': specs,
        'summary': strip_rich_text(product.description, LLM_SUMMARY_LENGTH),
    }

    if include_all_specs:
        payload['product_code'] = product.product_code
        payload['stock'] = product.stock
        payload['extra_info'] = strip_rich_text(product.product_information, 400)

    if include_reviews:
        reviews = _visible_reviews(product)
        reviews.sort(key=lambda review: review.created_at, reverse=True)
        payload['review_count'] = len(reviews)
        payload['recent_reviews'] = [
            {
                'rating': review.rating,
                'comment': strip_rich_text(review.comment, LLM_REVIEW_LENGTH),
            }
            for review in reviews[:3]
        ]

    return payload


def to_ui(product):
    """Bản giàu dành cho render card trong widget chat."""
    images = product.image_urls

    reviews = _visible_reviews(product)

    return {
        'id': product.pk,
        'slug': product.slug,
        'name': product.name,
        'url': reverse('products:product_detail', kwargs={'slug': product.slug}),
        'image': images[0] if images else '',
        'brand': product.brand.name if product.brand_id else '',
        'category': product.category.name if product.category_id else '',
        'price': to_money(product.price),
        'discount_price': to_money(product.discount_price),
        'final_price': final_price_of(product),
        'discount_percent': product.discount_percent,
        'rating': float(product.rating or 0),
        'review_count': len(reviews),
        'stock': product.stock,
        'in_stock': product.stock > 0,
        'add_to_cart': {
            'product_id': product.pk,
            'url': reverse('cart:add_to_cart'),
        },
    }


def serialize_pair(products, include_all_specs=False, include_reviews=False):
    """Trả về (danh sách cho LLM, danh sách cho UI) từ cùng một iterable."""
    items = list(products)
    return (
        [
            to_llm(
                product,
                include_all_specs=include_all_specs,
                include_reviews=include_reviews,
            )
            for product in items
        ],
        [to_ui(product) for product in items],
    )
