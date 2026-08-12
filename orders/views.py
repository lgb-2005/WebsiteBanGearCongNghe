from django.http import Http404
from django.shortcuts import render
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from cart.services import build_cart_context
from orders.models import Order, OrderItem
from orders.services import create_order_from_checkout
from orders.vnpay import build_vnpay_payment_url


def format_vnd(value):
    return "{:,.0f}".format(value).replace(",", ".")


def get_order_status_badge(status):
    status_map = {
        'pending': {
            'label': 'Chờ xử lý',
            'class_name': 'status-pending',
        },
        'processing': {
            'label': 'Đang xử lý',
            'class_name': 'status-processing',
        },
        'completed': {
            'label': 'Hoàn thành',
            'class_name': 'status-completed',
        },
        'cancelled': {
            'label': 'Đã hủy',
            'class_name': 'status-cancelled',
        },
    }

    return status_map.get(
        status,
        {
            'label': status,
            'class_name': 'status-pending',
        }
    )


def get_payment_status_label(payment_status):
    payment_status_map = {
        'pending': 'Chờ thanh toán',
        'paid': 'Đã thanh toán',
        'failed': 'Thanh toán thất bại',
        'cancelled': 'Đã hủy',
        'refunded': 'Đã hoàn tiền',
    }

    return payment_status_map.get(payment_status, str(payment_status).replace('_', ' ').title())


@login_required
def order_detail(request, order_code):
    try:
        order = (
            Order.objects
            .select_related('customer', 'customer__user')
            .prefetch_related('items', 'items__product', 'items__product__images')
            .filter(customer__user=request.user)
            .get(order_code=order_code)
        )
    except Order.DoesNotExist:
        raise Http404()

    order_status = get_order_status_badge(order.status)
    order_items = []
    subtotal = 0

    for item in order.items.all():
        line_total = item.price * item.quantity
        subtotal += line_total
        product_images = item.product.image_urls

        order_items.append({
            'product': item.product,
            'image_url': product_images[0] if product_images else '',
            'price': format_vnd(item.price),
            'quantity': item.quantity,
            'line_total': format_vnd(line_total),
        })

    context = {
        'order': order,
        'order_info': {
            'order_code': order.order_code,
            'created_at': order.created_at.strftime('%d-%m-%Y, %I:%M %p'),
            'status': order_status['label'],
            'status_class': order_status['class_name'],
            'payment_method': order.get_payment_method_display(),
            'payment_status': get_payment_status_label(order.payment_status),
            'receiver_name': order.receiver_name,
            'receiver_phone': order.receiver_phone,
            'receiver_email': order.effective_customer_email or 'Chưa cập nhật',
            'shipping_address': order.shipping_address,
            'subtotal': f"{format_vnd(subtotal)}đ",
            'total_price': f"{format_vnd(order.total_price)}đ",
        },
        'order_items': order_items,
    }

    return render(request, 'orders/order_detail.html', context)

@ensure_csrf_cookie
def checkout(request):

    cart_context = build_cart_context(request)

    cart_items = cart_context['items']

    stock_error_message = ''
    for item in cart_items:
        product = item['product']
        quantity = item['quantity']
        if product.stock <= 0:
            stock_error_message = f'{product.name} đã hết hàng.'
            break
        elif quantity > product.stock:
            stock_error_message = f'{product.name} chỉ còn {product.stock} sản phẩm.'
            break

    for item in cart_items:
        item['formatted_line_total'] = format_vnd(
            item['line_total']
        )

    context = {
        'cart_items': cart_items,
        'subtotal': cart_context['subtotal'],
        'subtotal_formatted': format_vnd(
            cart_context['subtotal']
        ),
        'total_quantity': cart_context['total_quantity'],
        'has_stock_error': bool(stock_error_message),
        'stock_error_message': stock_error_message,
    }

    if request.user.is_authenticated:
        context['user_info'] = request.user
    else:
        context['user_info'] = None

    return render(
        request,
        'orders/checkout.html',
        context
    )

@require_POST
def place_order(request):

    result = create_order_from_checkout(
        request=request
    )

    if result.get('success') and result.get('order_id'):
        if result.get('requires_payment'):
            try:
                order_obj = Order.objects.get(pk=result['order_id'])
                redirect_url = build_vnpay_payment_url(order_obj, request)
                return JsonResponse({'success': True, 'redirect_url': redirect_url})
            except Exception as e:
                from orders.services import delete_pending_vnpay_order
                delete_pending_vnpay_order(result['order_id'])
                return JsonResponse({'success': False, 'message': 'Không thể khởi tạo thanh toán VNPay. Vui lòng thử lại.'})
        else:
            try:
                from orders.email import (
                    send_order_confirmation,
                    send_new_order_notification_to_admin,
                    _send_in_background,
                )
                order_obj = Order.objects.get(pk=result['order_id'])
                _send_in_background(send_order_confirmation, order_obj)
                _send_in_background(send_new_order_notification_to_admin, order_obj)
            except Exception:
                pass

    return JsonResponse(result)


def vnpay_return(request):
    from django.shortcuts import redirect as _redirect
    from orders.services import clear_vnpay_cart, confirm_vnpay_payment
    from orders.vnpay import (
        get_response_message,
        is_valid_vnpay_amount,
        verify_vnpay_return,
    )

    params = request.GET.dict()
    response_code = params.get('vnp_ResponseCode', '')
    order_code = params.get('vnp_TxnRef', '')
    order = Order.objects.filter(
        order_code=order_code,
        payment_method='vnpay',
    ).first()

    if not verify_vnpay_return(params):
        request.session['vnpay_payment_result'] = {
            'success': False,
            'message': 'Chữ ký thanh toán không hợp lệ. Vui lòng thử lại.',
        }
        return _redirect('orders:vnpay_payment_result')

    if response_code == '00' and order and is_valid_vnpay_amount(order, params.get('vnp_Amount')):
        confirm_vnpay_payment(order.id)
        clear_vnpay_cart(request)
        request.session['vnpay_payment_result'] = {
            'success': True,
            'message': f'Thanh toán đơn hàng thành công.',
            'order_code': order_code,
        }
        return _redirect('orders:vnpay_payment_result')

    if response_code == '00':
        message = 'Không thể xác minh thông tin thanh toán của đơn hàng.'
    else:
        message = get_response_message(response_code)
    request.session['vnpay_payment_result'] = {
        'success': False,
        'message': message,
        'order_code': order_code,
    }
    return _redirect('orders:vnpay_payment_result')


def vnpay_payment_result(request):
    payment_result = request.session.get('vnpay_payment_result')
    if payment_result is None:
        from django.shortcuts import redirect as _redirect
        return _redirect('orders:checkout')

    context = {
        'payment_result': payment_result,
        'can_view_order': bool(
            payment_result.get('success')
            and payment_result.get('order_code')
            and request.user.is_authenticated
        ),
    }
    return render(request, 'orders/vnpay_payment_result.html', context)


@require_GET
def vnpay_ipn(request):
    from orders.services import confirm_vnpay_payment
    from orders.vnpay import is_valid_vnpay_amount, verify_vnpay_return

    params = {
        key: value
        for key, value in request.GET.items()
        if key.startswith('vnp_')
    }
    if not verify_vnpay_return(params):
        return JsonResponse({'RspCode': '97', 'Message': 'Invalid Checksum'})

    order_code = params.get('vnp_TxnRef', '')
    order = Order.objects.filter(
        order_code=order_code,
        payment_method='vnpay',
    ).first()
    if order is None:
        return JsonResponse({'RspCode': '01', 'Message': 'Order not Found'})

    if not is_valid_vnpay_amount(order, params.get('vnp_Amount')):
        return JsonResponse({'RspCode': '04', 'Message': 'Invalid Amount'})

    if params.get('vnp_ResponseCode') != '00':
        return JsonResponse({'RspCode': '00', 'Message': 'Confirm Success'})

    try:
        _, confirmed = confirm_vnpay_payment(order.id)
    except Order.DoesNotExist:
        return JsonResponse({'RspCode': '01', 'Message': 'Order not Found'})
    except Exception:
        return JsonResponse({'RspCode': '99', 'Message': 'Unknown Error'})

    if not confirmed:
        return JsonResponse({'RspCode': '02', 'Message': 'Order already confirmed'})
    return JsonResponse({'RspCode': '00', 'Message': 'Confirm Success'})