from django.db import models
from accounts.models import User
from products.models import Product
from core.models import BaseModel


class Customer(BaseModel):
    user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='customer_profile'
    )

    full_name = models.CharField(
        max_length=255,
        blank=True,
        default=''
    )

    email = models.EmailField(
        blank=True,
        default='',
        db_index=True
    )

    phone = models.CharField(
        max_length=20,
        blank=True,
        default='',
        db_index=True
    )

    def __str__(self):
        return self.email or self.full_name or f'Customer #{self.pk}'


class Order(BaseModel):
    STATUS_CHOICES = [
        ('pending', 'Chờ xử lý'),
        ('processing', 'Đang xử lý'),
        ('completed', 'Hoàn thành'),
        ('cancelled', 'Đã hủy'),
    ]

    PAYMENT_METHODS = [
        ('cod', 'Thanh toán khi nhận hàng'),
        ('bank_transfer', 'Chuyển khoản'),
        ('momo', 'MoMo'),
        ('vnpay', 'VNPay'),
    ]

    order_code = models.CharField(
        max_length=20,
        unique=True
    )

    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='orders'
    )

    receiver_name = models.CharField(
        max_length=255
    )

    receiver_phone = models.CharField(
        max_length=20
    )

    receiver_email = models.EmailField(
        blank=True
    )

    shipping_address = models.TextField()

    total_price = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )

    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_METHODS
    )

    payment_status = models.CharField(
        max_length=20,
        default='pending'
    )

    tracking_number = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    @property
    def effective_customer_name(self):
        if self.receiver_name:
            return self.receiver_name
        if self.customer and self.customer.full_name:
            return self.customer.full_name
        if self.customer and self.customer.user and self.customer.user.name:
            return self.customer.user.name
        if self.customer and self.customer.user:
            return self.customer.user.email
        return ''

    @property
    def effective_customer_email(self):
        if self.receiver_email:
            return self.receiver_email
        if self.customer and self.customer.email:
            return self.customer.email
        if self.customer and self.customer.user:
            return self.customer.user.email
        return ''

    @property
    def effective_customer_phone(self):
        if self.receiver_phone:
            return self.receiver_phone
        if self.customer and self.customer.phone:
            return self.customer.phone
        if self.customer and self.customer.user and self.customer.user.phone:
            return self.customer.user.phone
        return ''

    def __str__(self):
        return (
            f"{self.order_code} - "
            f"{self.effective_customer_email or 'unknown'}"
        )


class OrderItem(BaseModel):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"
