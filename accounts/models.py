from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email là bắt buộc")

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError("Superuser phải có is_staff=True")
        if extra_fields.get('is_superuser') is not True:
            raise ValueError("Superuser phải có is_superuser=True")

        return self.create_user(email, password, **extra_fields)
    
class User(AbstractUser):
    username = None

    email = models.EmailField(
        unique=True,
        verbose_name="Email"
    )

    name = models.CharField(
        max_length=100,
        verbose_name="Họ và tên"
    )

    phone = models.CharField(
        max_length=20,
        blank=True,
        null=True
    )

    province_code = models.CharField(
        max_length=10,
        blank=True,
        null=True
    )

    ward_code = models.CharField(
        max_length=10,
        blank=True,
        null=True
    )

    province_name = models.CharField(
    max_length=100,
    blank=True,
    null=True
)

    ward_name = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    street_address = models.TextField(
        blank=True,
        null=True
    )

    avatar = models.ImageField(
        upload_to='avatars/',
        null=True,
        blank=True
    )

    is_active = models.BooleanField(
        default=True
    )

    last_login_at = models.DateTimeField(
        null=True,
        blank=True
    )

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name']

    objects = CustomUserManager()

    def __str__(self):
        return self.email
    
    @property
    def full_address(self):
        parts = [
            self.street_address,
            self.ward_name,
            self.province_name
        ]

        return ", ".join(
            str(part)
            for part in parts
            if part
        )