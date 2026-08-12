from decimal import Decimal
from django.db import transaction
import random
import string
from datetime import datetime

from cart.models import CartItem
from .models import Customer, Order, OrderItem


def validate_checkout_data(data, is_guest=False):

    required_fields = {
        'full_name': 'Vui lòng nhập họ tên',
        'phone': 'Vui lòng nhập số điện thoại',
        'province_code': 'Vui lòng chọn tỉnh/thành',
        'ward_code': 'Vui lòng chọn phường/xã',
        'street_address': 'Vui lòng nhập địa chỉ',
    }

    if is_guest:
        required_fields['email'] = 'Vui lòng nhập email'

    for field, message in required_fields.items():

        if not data.get(field):
            return {
                'success': False,
                'message': message
            }

    return {
        'success': True
    }


def get_user_cart(user):

    return (
        CartItem.objects
        .select_related('product')
        .filter(user=user)
    )


def validate_stock(cart_items):

    for item in cart_items:

        if item.quantity > item.product.stock:

            return {
                'success': False,
                'message':
                    f'{item.product.name} chỉ còn '
                    f'{item.product.stock} sản phẩm'
            }

    return {
        'success': True
    }


def calculate_cart_total(cart_items):

    subtotal = Decimal('0')

    for item in cart_items:

        product = item.product

        unit_price = (
            product.discount_price
            if product.discount_price
            else product.price
        )

        subtotal += unit_price * item.quantity

    return subtotal


def generate_order_code():

    while True:

        date_part = datetime.now().strftime(
            "%Y%m%d"
        )

        random_part = ''.join(
            random.choices(
                string.ascii_uppercase +
                string.digits,
                k=6
            )
        )

        order_code = (
            f"DH{date_part}{random_part}"
        )

        if not Order.objects.filter(
            order_code=order_code
        ).exists():

            return order_code


def _normalize_email(email):

    return (email or '').strip().lower()


def _normalize_phone(phone):

    p = (phone or '').strip()
    p = p.replace(' ', '').replace('-', '').replace('.', '')
    if p.startswith('+84'):
        p = '0' + p[3:]
    elif p.startswith('84') and len(p) == 11:
        p = '0' + p[2:]
    return p


def link_customer_to_user(user):

    customer = Customer.objects.filter(user=user).first()
    if customer:
        return customer

    normalized_phone = _normalize_phone(getattr(user, 'phone', ''))
    normalized_email = _normalize_email(getattr(user, 'email', ''))

    if normalized_phone:
        customer = (
            Customer.objects
            .filter(phone=normalized_phone)
            .order_by('id')
            .first()
        )

    if customer is None and not normalized_phone and normalized_email:
        customer = (
            Customer.objects
            .filter(email__iexact=normalized_email)
            .order_by('id')
            .first()
        )

    if not customer:
        return None

    if customer.user_id is not None:
        return customer

    update_fields = []

    customer.user = user
    update_fields.append('user')

    if not customer.full_name and getattr(user, 'name', None):
        customer.full_name = user.name
        update_fields.append('full_name')

    if not customer.phone and normalized_phone:
        customer.phone = normalized_phone
        update_fields.append('phone')

    if not customer.email and normalized_email:
        customer.email = normalized_email
        update_fields.append('email')

    if update_fields:
        customer.save(update_fields=update_fields)

    return customer


def link_customer_to_user_by_email(user):

    return link_customer_to_user(user)


def get_or_create_customer_for_checkout(user, full_name, email, phone):

    normalized_email = _normalize_email(email)
    normalized_phone = _normalize_phone(phone)
    is_authenticated_user = user is not None and getattr(user, 'is_authenticated', False)
    customer = None

    if is_authenticated_user:
        customer = Customer.objects.filter(user=user).first()

    if customer is None and normalized_phone:
        customer = (
            Customer.objects
            .filter(phone=normalized_phone)
            .order_by('id')
            .first()
        )

    if customer is None and not normalized_phone and normalized_email:
        customer = (
            Customer.objects
            .filter(email__iexact=normalized_email)
            .order_by('id')
            .first()
        )

    if customer is None:
        return Customer.objects.create(
            user=user if is_authenticated_user else None,
            full_name=(full_name or '').strip(),
            email=normalized_email,
            phone=normalized_phone,
        )

    update_fields = []

    if customer.user_id is None and is_authenticated_user:
        customer.user = user
        update_fields.append('user')

    full_name_stripped = (full_name or '').strip()
    if full_name_stripped and not customer.full_name:
        customer.full_name = full_name_stripped
        update_fields.append('full_name')

    if normalized_phone and not customer.phone:
        customer.phone = normalized_phone
        update_fields.append('phone')

    if normalized_email and not customer.email:
        customer.email = normalized_email
        update_fields.append('email')

    if update_fields:
        customer.save(update_fields=update_fields)

    return customer


def create_order(
    customer,
    full_name,
    phone,
    email,
    subtotal,
    shipping_address,
    payment_method='cod',
):
    return Order.objects.create(

        order_code=
            generate_order_code(),

        customer=customer,

        receiver_name=full_name,
        receiver_phone=phone,
        receiver_email=_normalize_email(email),

        shipping_address=shipping_address,

        total_price=subtotal,

        payment_method=payment_method,
        payment_status='pending',
        status='pending'
    )


def create_order_items(
    order,
    cart_items
):

    for item in cart_items:

        product = item.product

        unit_price = (
            product.discount_price
            if product.discount_price
            else product.price
        )

        OrderItem.objects.create(
            order=order,
            product=product,
            quantity=item.quantity,
            price=unit_price
        )

        product.stock -= item.quantity

        product.save(
            update_fields=['stock']
        )


def _get_guest_cart_items(request):
    from cart.services import get_session_cart
    from products.models import Product

    session_cart = get_session_cart(request)
    if not session_cart:
        return []

    product_ids = [int(pid) for pid in session_cart.keys()]
    products = {
        p.id: p
        for p in Product.objects.filter(id__in=product_ids)
    }

    class _CartEntry:
        def __init__(self, product, quantity):
            self.product = product
            self.quantity = quantity

    items = []
    for pid, qty in session_cart.items():
        product = products.get(int(pid))
        if product:
            items.append(_CartEntry(product, qty))
    return items


@transaction.atomic
def create_order_from_checkout(request):

    is_authenticated = request.user.is_authenticated
    is_guest = not is_authenticated

    validation = validate_checkout_data(
        request.POST,
        is_guest=is_guest
    )

    if not validation['success']:
        return validation

    if is_authenticated:
        cart_items = list(get_user_cart(request.user))
    else:
        cart_items = _get_guest_cart_items(request)

    if not cart_items:
        return {
            'success': False,
            'message': 'Giỏ hàng đang trống'
        }

    stock_validation = validate_stock(
        cart_items
    )

    if not stock_validation['success']:
        return stock_validation

    subtotal = calculate_cart_total(
        cart_items
    )

    shipping_address = (
        f"{request.POST['street_address']}, "
        f"{request.POST['ward_name']}, "
        f"{request.POST['province_name']}"
    )

    customer = get_or_create_customer_for_checkout(
        user=request.user if is_authenticated else None,
        full_name=request.POST['full_name'],
        email=request.POST.get('email'),
        phone=request.POST['phone'],
    )

    payment_method = request.POST.get('payment_method', 'cod').strip()
    if payment_method not in ('cod', 'vnpay', 'bank_transfer', 'momo'):
        payment_method = 'cod'

    order = create_order(
        customer=customer,
        full_name=request.POST['full_name'],
        phone=request.POST['phone'],
        email=request.POST.get('email'),
        subtotal=subtotal,
        shipping_address=shipping_address,
        payment_method=payment_method,
    )

    create_order_items(
        order,
        cart_items
    )

    try:
        from analytics.services import track_event
        track_event(request, 'checkout', event_value=subtotal,
                    metadata={'order_code': order.order_code})
    except Exception:
        pass

    if payment_method == 'vnpay':
        return {
            'success': True,
            'requires_payment': True,
            'order_id': order.id,
            'order_code': order.order_code,
        }

    if is_authenticated:
        CartItem.objects.filter(user=request.user).delete()
    else:
        from cart.services import save_session_cart
        save_session_cart(request, {})

    return {
        'success': True,
        'message': 'Đặt hàng thành công',
        'order_id': order.id,
        'order_code': order.order_code
    }


def delete_pending_vnpay_order(order_id):
    try:
        order = Order.objects.get(
            pk=order_id,
            payment_method='vnpay',
            payment_status='pending',
        )
        order.items.all().delete()
        order.delete()
    except Order.DoesNotExist:
        pass


@transaction.atomic
def confirm_vnpay_payment(order_id):
    order = Order.objects.select_for_update().get(
        pk=order_id,
        payment_method='vnpay',
    )
    if order.payment_status == 'paid':
        return order, False

    order.payment_status = 'paid'
    order.save(update_fields=['payment_status', 'updated_at'])

    def send_confirmation_notifications():
        from orders.email import (
            _send_in_background,
            send_new_order_notification_to_admin,
            send_order_confirmation,
        )
        _send_in_background(send_order_confirmation, order)
        _send_in_background(send_new_order_notification_to_admin, order)

    transaction.on_commit(send_confirmation_notifications)
    return order, True


def clear_vnpay_cart(request):
    if request.user.is_authenticated:
        CartItem.objects.filter(user=request.user).delete()
    else:
        from cart.services import save_session_cart
        save_session_cart(request, {})
