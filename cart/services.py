from decimal import Decimal

from django.db import transaction

from .models import CartItem
from products.models import Product

SESSION_CART_KEY = 'cart'


def _ensure_session_key(request):
    if not request.session.session_key:
        request.session.save()
    return request.session.session_key


def get_session_cart(request):
    cart = request.session.get(SESSION_CART_KEY, {})
    if isinstance(cart, dict):
        return cart
    return {}


def save_session_cart(request, cart):
    request.session[SESSION_CART_KEY] = cart
    request.session.modified = True


def add_to_session_cart(request, product_id, quantity=1):
    cart = get_session_cart(request)
    product_key = str(product_id)
    cart[product_key] = cart.get(product_key, 0) + quantity
    save_session_cart(request, cart)


def update_session_cart_item(request, product_id, quantity):
    cart = get_session_cart(request)
    product_key = str(product_id)

    if quantity > 0:
        cart[product_key] = quantity
    elif product_key in cart:
        del cart[product_key]

    save_session_cart(request, cart)


def remove_from_session_cart(request, product_id):
    cart = get_session_cart(request)
    product_key = str(product_id)
    if product_key in cart:
        del cart[product_key]
        save_session_cart(request, cart)


@transaction.atomic
def merge_session_cart_to_user(request):
    if not request.user.is_authenticated:
        return

    session_cart = get_session_cart(request)
    if not session_cart:
        return

    for product_id, quantity in session_cart.items():
        cart_item, created = CartItem.objects.get_or_create(
            user=request.user,
            product_id=product_id,
            defaults={'quantity': quantity},
        )
        if not created:
            cart_item.quantity += quantity
            cart_item.save(update_fields=['quantity', 'updated_at'])

    save_session_cart(request, {})

    session_id = _ensure_session_key(request)
    guest_items = CartItem.objects.filter(session_id=session_id, user__isnull=True)
    for item in guest_items:
        cart_item, created = CartItem.objects.get_or_create(
            user=request.user,
            product=item.product,
            defaults={'quantity': item.quantity},
        )
        if not created:
            cart_item.quantity += item.quantity
            cart_item.save(update_fields=['quantity', 'updated_at'])
    guest_items.delete()


def add_to_cart(request, product, quantity=1):
    if request.user.is_authenticated:
        cart_item, created = CartItem.objects.get_or_create(
            user=request.user,
            product=product,
            defaults={'quantity': quantity},
        )
        if not created:
            cart_item.quantity += quantity
            cart_item.save(update_fields=['quantity', 'updated_at'])
    else:
        add_to_session_cart(request, product.id, quantity)

    try:
        from analytics.services import track_event
        unit_price = product.discount_price if product.discount_price else product.price
        track_event(request, 'add_to_cart', product=product,
                    event_value=unit_price * quantity,
                    metadata={'quantity': quantity})
    except Exception:
        pass


def update_cart_item_quantity(request, product, quantity):
    if request.user.is_authenticated:
        if quantity > 0:
            cart_item, _ = CartItem.objects.get_or_create(
                user=request.user,
                product=product,
                defaults={'quantity': quantity},
            )
            if cart_item.quantity != quantity:
                cart_item.quantity = quantity
                cart_item.save(update_fields=['quantity', 'updated_at'])
        else:
            CartItem.objects.filter(user=request.user, product=product).delete()
            try:
                from analytics.services import track_event
                track_event(request, 'remove_from_cart', product=product)
            except Exception:
                pass
        return

    update_session_cart_item(request, product.id, quantity)
    if quantity <= 0:
        try:
            from analytics.services import track_event
            track_event(request, 'remove_from_cart', product=product)
        except Exception:
            pass


def remove_cart_item(request, product):
    if request.user.is_authenticated:
        CartItem.objects.filter(user=request.user, product=product).delete()
    else:
        remove_from_session_cart(request, product.id)

    try:
        from analytics.services import track_event
        track_event(request, 'remove_from_cart', product=product)
    except Exception:
        pass


def get_cart_items(request):
    if request.user.is_authenticated:
        db_items = (
            CartItem.objects.filter(user=request.user)
            .select_related('product', 'product__brand')
            .order_by('-created_at')
        )
        return [
            {
                'product': item.product,
                'quantity': item.quantity,
            }
            for item in db_items
        ]

    session_cart = get_session_cart(request)
    if not session_cart:
        return []

    product_ids = [int(product_id) for product_id in session_cart.keys()]
    products = {
        product.id: product
        for product in Product.objects.filter(id__in=product_ids).select_related('brand')
    }

    items = []
    for product_id, quantity in session_cart.items():
        product = products.get(int(product_id))
        if product:
            items.append({
                'product': product,
                'quantity': quantity,
            })
    return items


def build_cart_context(request):
    items = []
    subtotal = Decimal('0')
    total_quantity = 0

    for entry in get_cart_items(request):
        product = entry['product']
        quantity = entry['quantity']
        unit_price = product.discount_price if product.discount_price is not None else product.price
        line_total = unit_price * quantity
        subtotal += line_total
        total_quantity += quantity
        items.append({
            'product': product,
            'quantity': quantity,
            'unit_price': unit_price,
            'line_total': line_total,
        })

    return {
        'items': items,
        'subtotal': subtotal,
        'total_quantity': total_quantity,
        'is_empty': len(items) == 0,
    }


def get_cart_count(request):
    if request.user.is_authenticated:
        total = CartItem.objects.filter(user=request.user).values_list('quantity', flat=True)
        return sum(total)

    return sum(get_session_cart(request).values())
