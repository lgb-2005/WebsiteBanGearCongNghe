from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from products.models import Product
from .services import add_to_cart, build_cart_context, remove_cart_item, update_cart_item_quantity


def _format_currency(value):
    if value in (None, ''):
        return ''
    try:
        return f"{int(value):,} đ".replace(',', '.')
    except (TypeError, ValueError):
        return ''


def _build_cart_json_response(request, product=None, removed=False):
    context = build_cart_context(request)
    response = {
        'success': True,
        'total_quantity': context['total_quantity'],
        'subtotal_display': _format_currency(context['subtotal']),
        'is_empty': context['is_empty'],
        'removed': removed,
    }

    if product is not None and not removed:
        item = next((entry for entry in context['items'] if entry['product'].id == product.id), None)
        if item is not None:
            response.update({
                'product_id': product.id,
                'quantity': item['quantity'],
                'line_total_display': _format_currency(item['line_total']),
            })

    if product is not None and removed:
        response['product_id'] = product.id

    return response


def cart_detail(request):
    context = build_cart_context(request)
    context.update({
        'subtotal_display': _format_currency(context['subtotal']),
    })

    for item in context['items']:
        item['unit_price_display'] = _format_currency(item['unit_price'])
        item['line_total_display'] = _format_currency(item['line_total'])

    return render(request, 'cart/cart_detail.html', context)


@require_POST
def add_to_cart_view(request):
    product_id = request.POST.get('product_id')
    quantity = request.POST.get('quantity', 1)
    redirect_to_cart = request.POST.get('redirect_to_cart') == '1'

    try:
        quantity = max(1, int(quantity))
    except (TypeError, ValueError):
        quantity = 1

    product = get_object_or_404(Product, pk=product_id)

    if product.stock <= 0:
        error_message = 'Sản phẩm đã hết hàng.'
    elif quantity > product.stock:
        error_message = f'Sản phẩm chỉ còn {product.stock} sản phẩm.'
    else:
        error_message = None

    if error_message:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'message': error_message,
            })
        return redirect('cart:cart_detail')

    add_to_cart(request, product, quantity)

    if redirect_to_cart:
        return redirect('cart:cart_detail')

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        context = build_cart_context(request)
        return JsonResponse({
            'success': True,
            'message': 'Đã thêm sản phẩm vào giỏ hàng.',
            'cart_count': context['total_quantity'],
        })

    return redirect('cart:cart_detail')


@require_POST
def update_cart_view(request):
    product_id = request.POST.get('product_id')
    quantity = request.POST.get('quantity', 1)

    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        quantity = 1

    product = get_object_or_404(Product, pk=product_id)

    if product.stock <= 0 and quantity > 0:
        error_message = 'Sản phẩm đã hết hàng.'
    elif quantity > product.stock:
        error_message = f'Sản phẩm chỉ còn {product.stock} sản phẩm.'
    else:
        error_message = None

    if error_message:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'message': error_message,
            })
        return redirect('cart:cart_detail')

    update_cart_item_quantity(request, product, quantity)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse(_build_cart_json_response(request, product=product, removed=quantity <= 0))

    return redirect('cart:cart_detail')


@require_POST
def remove_cart_view(request):
    product_id = request.POST.get('product_id')
    product = get_object_or_404(Product, pk=product_id)
    remove_cart_item(request, product)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse(_build_cart_json_response(request, product=product, removed=True))

    return redirect('cart:cart_detail')
