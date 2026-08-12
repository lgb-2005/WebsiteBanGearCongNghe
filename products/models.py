import random
import string
from django.utils import timezone
from django.db import models
from django.db.models import Prefetch
from django.utils.text import slugify
from django.db.models import Q
from core.models import BaseModel
from accounts.models import User


def generate_product_code():
    charset = string.ascii_uppercase + string.digits
    while True:
        code = 'SP' + ''.join(random.choices(charset, k=7))
        if not Product.objects.filter(product_code=code).exists():
            return code


class Category(BaseModel):
    parent = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='children')
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, db_index=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name) or 'danh-muc'
            candidate_slug = base_slug
            suffix = 1
            while Category.objects.filter(slug=candidate_slug).exclude(pk=self.pk).exists():
                suffix += 1
                candidate_slug = f'{base_slug}-{suffix}'
            self.slug = candidate_slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ('name',)
        verbose_name = "Danh mục"
        verbose_name_plural = "Danh mục"


class Brand(models.Model):
    name = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = "brands"
        verbose_name = "Thương hiệu"
        verbose_name_plural = "Thương hiệu"

class ProductQuerySet(models.QuerySet):

    def with_related_data(self):

        attribute_queryset = ProductAttribute.objects.select_related(
            'attribute_value__group'
        ).order_by(
            'attribute_value__group__display_order',
            'attribute_value__group__name',
            'attribute_value__value',
            'custom_value',
        )

        return self.select_related(
            'brand',
            'category'
        ).prefetch_related(
            'images',
            'reviews__user',
            Prefetch(
                'attributes',
                queryset=attribute_queryset
            ),
        )

    def filter_by_attributes(self, **filters):

        queryset = self

        for group_slug, raw_values in filters.items():

            if raw_values is None:
                continue

            if isinstance(raw_values, (list, tuple, set)):
                values = [
                    str(value).strip()
                    for value in raw_values
                    if str(value).strip()
                ]
            else:
                values = [str(raw_values).strip()] if str(raw_values).strip() else []

            if not values:
                continue

            group_query = Q()

            # OR trong cùng group
            for value in values:
                group_query |= Q(
                    attributes__attribute_value__group__slug=group_slug,
                    attributes__attribute_value__slug=value,
                )

            # AND giữa các group
            queryset = queryset.filter(group_query).distinct()

        return queryset


class ProductManager(models.Manager.from_queryset(ProductQuerySet)):
    pass


class Product(BaseModel):
    slug = models.SlugField(unique=True)
    product_code = models.CharField(
        max_length=9,
        unique=True,
        db_index=True,
        editable=False,
        blank=True,
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    product_information = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    stock = models.PositiveIntegerField(default=0)
    brand = models.ForeignKey(
        Brand,
        on_delete=models.SET_NULL,
        null=True,
        related_name='products'
    )
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products')
    image_url = models.URLField(max_length=255, blank=True)
    view_count = models.PositiveIntegerField(default=0)
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0.0)
    is_active = models.BooleanField(
        default=True
    )

    deleted_at = models.DateTimeField(
        null=True,
        blank=True
    )

    objects = ProductManager()

    def save(self, *args, **kwargs):
        if not self.product_code:
            self.product_code = generate_product_code()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name
    
    def soft_delete(self):
        self.is_active = False
        self.deleted_at = timezone.now()

        self.save(
            update_fields=[
                'is_active',
                'deleted_at'
            ]
        )

    def restore(self):
        self.is_active = True
        self.deleted_at = None

        self.save(
            update_fields=[
                'is_active',
                'deleted_at'
            ]
        )

    @property
    def main_image(self):
        first_image = self.images.order_by('id').first()
        if first_image:
            return first_image.image
        return self.image_url

    @property
    def image_urls(self):
        uploaded_images = [image.image.url for image in self.images.all() if image.image]
        if uploaded_images:
            return uploaded_images
        return [self.image_url] if self.image_url else []
    
    @property
    def discount_percent(self):
        if self.discount_price:
            return int(
                ((self.price - self.discount_price) / self.price) * 100
            )
        return 0

    class Meta:
        verbose_name = "Sản phẩm"
        verbose_name_plural = "Sản phẩm"


class AttributeGroup(models.Model):
    FILTER_TYPE_CHECKBOX = 'checkbox'
    FILTER_TYPE_RADIO = 'radio'
    FILTER_TYPE_SELECT = 'select'
    FILTER_TYPE_COLOR = 'color'
    FILTER_TYPE_RANGE = 'range'

    DATA_TYPE_TEXT = 'text'
    DATA_TYPE_NUMBER = 'number'
    DATA_TYPE_BOOLEAN = 'boolean'

    FILTER_TYPE_CHOICES = [
        (FILTER_TYPE_CHECKBOX, 'Checkbox'),
        (FILTER_TYPE_RADIO, 'Radio'),
        (FILTER_TYPE_SELECT, 'Select'),
        (FILTER_TYPE_COLOR, 'Color'),
        (FILTER_TYPE_RANGE, 'Range'),
    ]
    DATA_TYPE_CHOICES = [
        (DATA_TYPE_TEXT, 'Text'),
        (DATA_TYPE_NUMBER, 'Number'),
        (DATA_TYPE_BOOLEAN, 'Boolean'),
    ]

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(unique=True, db_index=True)
    is_filterable = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True, db_index=True)
    display_order = models.PositiveIntegerField(default=0)
    filter_type = models.CharField(max_length=20, choices=FILTER_TYPE_CHOICES)
    data_type = models.CharField(max_length=20, choices=DATA_TYPE_CHOICES)
    categories = models.ManyToManyField(Category, related_name='attribute_groups', blank=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ('display_order', 'name')
        verbose_name = 'Nhóm thuộc tính'
        verbose_name_plural = 'Nhóm thuộc tính'
        indexes = [
            models.Index(fields=['display_order', 'name']),
            models.Index(fields=['is_filterable', 'display_order']),
            models.Index(fields=['is_active', 'display_order']),
        ]

    @classmethod
    def get_filter_groups_for_category(cls, category):
        if category is None:
            return cls.objects.none()

        category_ids = [category.pk]
        if category.parent_id:
            category_ids.append(category.parent_id)
        category_ids.extend(category.children.values_list('id', flat=True))

        return cls.objects.filter(
            is_filterable=True,
            is_active=True,
        ).filter(
            models.Q(categories__isnull=True) | models.Q(categories__id__in=category_ids)
        ).prefetch_related(
            'categories',
            Prefetch('values', queryset=AttributeValue.objects.filter(is_active=True).order_by('display_order', 'value')),
        ).distinct().order_by('display_order', 'name')

    @property
    def used_by_products_count(self):
        return ProductAttribute.objects.filter(attribute_value__group=self).count()

    def has_product_usage(self):
        return ProductAttribute.objects.filter(attribute_value__group=self).exists()


class AttributeValue(models.Model):
    group = models.ForeignKey(AttributeGroup, on_delete=models.CASCADE, related_name='values')
    value = models.CharField(max_length=150, db_index=True)
    slug = models.SlugField(db_index=True, blank=True)
    display_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True, db_index=True)
    hex_color = models.CharField(max_length=7, blank=True)

    def __str__(self):
        return f'{self.group.name}: {self.value}'

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.value) or 'value'
            candidate_slug = base_slug
            suffix = 1
            while AttributeValue.objects.filter(group=self.group, slug=candidate_slug).exclude(pk=self.pk).exists():
                suffix += 1
                candidate_slug = f'{base_slug}-{suffix}'
            self.slug = candidate_slug
        super().save(*args, **kwargs)

    @property
    def usage_count(self):
        return self.productattribute_set.count()

    def has_product_usage(self):
        return self.productattribute_set.exists()

    def deactivate(self):
        if self.is_active:
            self.is_active = False
            self.save(update_fields=['is_active'])

    class Meta:
        ordering = ('group__display_order', 'group__name', 'display_order', 'value')
        verbose_name = 'Giá trị thuộc tính'
        verbose_name_plural = 'Giá trị thuộc tính'
        constraints = [
            models.UniqueConstraint(fields=['group', 'value'], name='unique_attribute_value_per_group'),
            models.UniqueConstraint(fields=['group', 'slug'], name='unique_attribute_slug_per_group'),
        ]
        indexes = [
            models.Index(fields=['group', 'slug']),
            models.Index(fields=['group', 'value']),
            models.Index(fields=['group', 'is_active', 'display_order']),
        ]


class ProductAttribute(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='attributes')
    attribute_value = models.ForeignKey(AttributeValue, on_delete=models.CASCADE)
    custom_value = models.CharField(max_length=200, blank=True, null=True)

    def __str__(self):
        return f'{self.product.name} - {self.attribute_value}'

    @property
    def resolved_value(self):
        return self.custom_value or self.attribute_value.value

    class Meta:
        ordering = ('product_id', 'attribute_value_id')
        verbose_name = 'Thuộc tính sản phẩm'
        verbose_name_plural = 'Thuộc tính sản phẩm'
        constraints = [
            models.UniqueConstraint(fields=['product', 'attribute_value'], name='unique_product_attribute'),
        ]
        indexes = [
            models.Index(fields=['product', 'attribute_value']),
            models.Index(fields=['attribute_value', 'product']),
        ]


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='products/')

    def __str__(self):
        return f'{self.product.name} - {self.id}'

    class Meta:
        verbose_name = 'Ảnh sản phẩm'
        verbose_name_plural = 'Ảnh sản phẩm'


class ProductReview(BaseModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    rating = models.PositiveSmallIntegerField()
    comment = models.TextField(blank=True)
    is_visible = models.BooleanField(default=True)

    class Meta:
        unique_together = ('user', 'product')
        verbose_name = "Đánh giá sản phẩm"


class Favorite(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'product')
        verbose_name = 'Sản phẩm yêu thích'
        verbose_name_plural = 'Sản phẩm yêu thích'

    def __str__(self):
        return f'{self.user.username} - {self.product.name}'