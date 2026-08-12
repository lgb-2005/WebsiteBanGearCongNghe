from django.db import models
from accounts.models import User
from products.models import Product
from core.models import BaseModel

class CartItem(BaseModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    session_id = models.CharField(max_length=255, null=True, blank=True)   # hỗ trợ guest
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        unique_together = [('user', 'product'), ('session_id', 'product')]

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"