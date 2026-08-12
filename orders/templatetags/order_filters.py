from django import template

register = template.Library()


@register.filter
def vnd(value):
    try:
        return '{:,.0f}'.format(value).replace(',', '.')
    except (ValueError, TypeError):
        return value
