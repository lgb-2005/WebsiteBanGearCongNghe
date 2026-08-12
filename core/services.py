from django.db.models import Q
from django.utils import timezone

from .models import Banner


def get_active_banners(position=None, limit=None):
    now = timezone.now()

    queryset = Banner.objects.filter(
        is_active=True,
        start_at__isnull=True,
        end_at__isnull=True,
    ) | Banner.objects.filter(
        is_active=True,
        start_at__isnull=True,
        end_at__gte=now,
    ) | Banner.objects.filter(
        is_active=True,
        start_at__lte=now,
        end_at__isnull=True,
    ) | Banner.objects.filter(
        is_active=True,
        start_at__lte=now,
        end_at__gte=now,
    )

    queryset = queryset.order_by('position', 'display_order', 'id')

    if position:
        queryset = queryset.filter(position=position)

    if limit is not None:
        queryset = queryset[:limit]

    return queryset


def get_active_hero_banners(limit=None):
    return get_active_banners(position=Banner.POSITION_HERO, limit=limit)
