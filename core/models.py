from django.db import models
from django.utils import timezone
import uuid


class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Banner(BaseModel):
    POSITION_HERO = 'hero'

    POSITION_CHOICES = [
        (POSITION_HERO, 'Hero')
    ]

    title = models.CharField(max_length=255, blank=True)
    subtitle = models.CharField(max_length=500, blank=True)
    image = models.ImageField(upload_to='banners/')
    cta_text = models.CharField(max_length=100, blank=True)
    cta_url = models.CharField(max_length=500, blank=True)
    position = models.CharField(max_length=20, choices=POSITION_CHOICES, default=POSITION_HERO)
    display_order = models.PositiveIntegerField(default=0)
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        name = self.title or f"Banner #{self.id}"
        return f"{name} ({self.position})"

    class Meta:
        ordering = ('position', 'display_order', 'id')
        verbose_name = 'Banner'
        verbose_name_plural = 'Banner'
