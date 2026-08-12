from django.db import models
from django.utils import timezone
from accounts.models import User
from products.models import Product
from core.models import BaseModel
import uuid

class Session(BaseModel):
    id = models.CharField(primary_key=True, max_length=255, default=uuid.uuid4)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    device_type = models.CharField(max_length=50, blank=True)  # mobile, desktop...

    def __str__(self):
        return str(self.id)

class Event(BaseModel):
    EVENT_TYPES = [
        ('view_product', 'Xem sản phẩm'),
        ('add_to_cart', 'Thêm vào giỏ'),
        ('remove_from_cart', 'Xóa khỏi giỏ'),
        ('checkout', 'Thanh toán'),
        ('click', 'Click'),
    ]

    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    session = models.ForeignKey(Session, on_delete=models.CASCADE)
    event_type = models.CharField(max_length=50, choices=EVENT_TYPES)
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True)
    event_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['event_type']),
            models.Index(fields=['product']),
            models.Index(fields=['created_at']),
        ]