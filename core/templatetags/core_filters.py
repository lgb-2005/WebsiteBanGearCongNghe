from django import template

register = template.Library()


@register.filter
def vnd(value):
    if value in (None, ''):
        return ''
    try:
        return f"{int(value):,} đ".replace(',', '.')
    except (TypeError, ValueError):
        return ''
