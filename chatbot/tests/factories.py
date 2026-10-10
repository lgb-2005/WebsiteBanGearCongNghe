"""Helper tạo dữ liệu test khớp với schema thật (xem Phụ lục A của plan)."""

from decimal import Decimal

from accounts.models import User
from products.models import (
    AttributeGroup,
    AttributeValue,
    Brand,
    Category,
    Product,
    ProductAttribute,
)


def make_category(slug='chuot', name='Chuột', parent=None):
    return Category.objects.create(slug=slug, name=name, parent=parent)


def make_brand(name='Logitech'):
    brand, _created = Brand.objects.get_or_create(name=name)
    return brand


def make_user(email='user@example.com', name='Test User', password='12345678'):
    user, created = User.objects.get_or_create(
        email=email,
        defaults={'name': name},
    )
    if created:
        user.set_password(password)
        user.save(update_fields=['password'])
    return user


def make_group(slug='ket-noi', name='Kết nối', categories=(), display_order=20,
               data_type=AttributeGroup.DATA_TYPE_TEXT,
               filter_type=AttributeGroup.FILTER_TYPE_CHECKBOX):
    group = AttributeGroup.objects.create(
        slug=slug,
        name=name,
        display_order=display_order,
        data_type=data_type,
        filter_type=filter_type,
    )
    if categories:
        group.categories.set(categories)
    return group


def make_value(group, value='Wireless', slug='wireless', display_order=0):
    return AttributeValue.objects.create(
        group=group,
        value=value,
        slug=slug,
        display_order=display_order,
    )


def make_product(category, brand=None, name='Chuột test', slug=None,
                 price='1000000', discount_price=None, stock=10, rating='4.5',
                 description='', product_information='', is_active=True,
                 attribute_values=()):
    product = Product.objects.create(
        slug=slug or name.lower().replace(' ', '-'),
        name=name,
        category=category,
        brand=brand,
        price=Decimal(price),
        discount_price=Decimal(discount_price) if discount_price else None,
        stock=stock,
        rating=Decimal(rating),
        description=description,
        product_information=product_information,
        is_active=is_active,
    )

    for attribute_value in attribute_values:
        ProductAttribute.objects.create(product=product, attribute_value=attribute_value)

    return product
