import re

from django import template
from django.utils.html import strip_tags

register = template.Library()


@register.filter
def strip_html(value):
    """Return plain text with HTML tags and common whitespace entities removed."""
    if not value:
        return ''
    text = strip_tags(str(value))
    text = re.sub(r'&nbsp;|\s', '', text)
    return text
