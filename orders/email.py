import logging
import threading

from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.urls import reverse

logger = logging.getLogger(__name__)

_STATUS_SUBJECTS = {
    'processing': 'đang được xử lý',
    'completed': 'đã hoàn thành',
    'cancelled': 'đã bị huỷ',
}

_STATUS_MESSAGES = {
    'processing': 'Đơn hàng của bạn đang được xử lý. Chúng tôi sẽ liên hệ sớm.',
    'completed': 'Đơn hàng đã giao thành công. Cảm ơn bạn đã tin tưởng TechGear Shop!',
    'cancelled': 'Đơn hàng đã bị huỷ. Vui lòng liên hệ nếu có thắc mắc.',
}

_STATUS_LABELS = {
    'processing': 'Đang xử lý',
    'completed': 'Hoàn thành',
    'cancelled': 'Đã huỷ',
}


def _send_in_background(fn, *args, **kwargs):
    t = threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True)
    t.start()


def _get_order_detail_url(order):
    return f'{settings.SITE_URL}{reverse("orders:order_detail", args=[order.order_code])}'


def send_order_confirmation(order):
    try:
        recipient = order.effective_customer_email
        if not recipient:
            return

        raw_items = order.items.select_related('product').all()
        items = [
            {
                'product': item.product,
                'quantity': item.quantity,
                'price': item.price,
                'line_total': item.price * item.quantity,
            }
            for item in raw_items
        ]
        subject = f'Xác nhận đơn hàng #{order.order_code} - TechGear Shop'
        order_detail_url = _get_order_detail_url(order)

        context = {
            'order': order,
            'items': items,
            'order_detail_url': order_detail_url,
        }

        html_content = render_to_string('orders/email/order_confirmation.html', context)

        plain_lines = [
            f'Xác nhận đơn hàng #{order.order_code}',
            f'Ngày đặt: {order.created_at.strftime("%d/%m/%Y %H:%M")}',
            f'Khách hàng: {order.effective_customer_name}',
            f'Địa chỉ giao: {order.shipping_address}',
            '',
            'Sản phẩm:',
        ]
        for item in items:
            plain_lines.append(
                f'  - {item["product"].name} x{item["quantity"]} = {item["line_total"]:,.0f}đ'
            )
        plain_lines.append(f'\nTổng tiền: {order.total_price:,.0f}đ')
        plain_lines.append(f'\nXem chi tiết đơn hàng: {order_detail_url}')
        plain_lines.append('\nCảm ơn bạn đã mua hàng tại TechGear Shop!')
        plain_content = '\n'.join(plain_lines)

        msg = EmailMultiAlternatives(
            subject=subject,
            body=plain_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient],
        )
        msg.attach_alternative(html_content, 'text/html')
        msg.send()
    except Exception as e:
        logger.error(f'[email] send_order_confirmation failed for order {getattr(order, "order_code", "?")}: {e}')


def send_new_order_notification_to_admin(order):
    try:
        raw_items = order.items.select_related('product').all()
        items = [
            {
                'product': item.product,
                'quantity': item.quantity,
                'price': item.price,
                'line_total': item.price * item.quantity,
            }
            for item in raw_items
        ]
        subject = f'Đơn hàng mới #{order.order_code}'
        context = {
            'order': order,
            'items': items,
        }
        html_content = render_to_string('orders/email/new_order_admin.html', context)
        plain_lines = [
            f'Đơn hàng mới #{order.order_code}',
            f'Thời gian: {order.created_at.strftime("%d/%m/%Y %H:%M")}',
            f'Khách hàng: {order.effective_customer_name}',
            f'SĐT: {order.effective_customer_phone}',
            f'Email: {order.effective_customer_email}',
            f'Địa chỉ: {order.shipping_address}',
            f'Thanh toán: {order.get_payment_method_display()}',
            '',
            'Sản phẩm:',
        ]
        for item in items:
            plain_lines.append(
                f'  - {item["product"].name} x{item["quantity"]} = {item["line_total"]:,.0f}đ'
            )
        plain_lines.append(f'\nTổng tiền: {order.total_price:,.0f}đ')
        plain_content = '\n'.join(plain_lines)
        msg = EmailMultiAlternatives(
            subject=subject,
            body=plain_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=['techgear.shop.vn@gmail.com'],
        )
        msg.attach_alternative(html_content, 'text/html')
        msg.send()
    except Exception as e:
        logger.error(f'[email] send_new_order_notification_to_admin failed for order {getattr(order, "order_code", "?")}: {e}')


def send_order_status_update(order, old_status, new_status):
    try:
        if new_status not in _STATUS_SUBJECTS:
            return

        recipient = order.effective_customer_email
        if not recipient:
            return

        subject = f'Đơn hàng #{order.order_code} {_STATUS_SUBJECTS[new_status]}'
        message = _STATUS_MESSAGES[new_status]
        status_label = _STATUS_LABELS[new_status]
        raw_items = order.items.select_related('product').all()
        items = [
            {
                'product': item.product,
                'quantity': item.quantity,
                'price': item.price,
                'line_total': item.price * item.quantity,
            }
            for item in raw_items
        ]

        order_detail_url = _get_order_detail_url(order)
        context = {
            'order': order,
            'items': items,
            'new_status': new_status,
            'status_label': status_label,
            'message': message,
            'order_detail_url': order_detail_url,
        }

        html_content = render_to_string('orders/email/order_status_update.html', context)

        plain_lines = [
            f'Cập nhật đơn hàng #{order.order_code}',
            f'Trạng thái: {status_label}',
            '',
            message,
            '',
            'Sản phẩm:',
        ]
        for item in items:
            plain_lines.append(
                f'  - {item["product"].name} x{item["quantity"]} = {item["line_total"]:,.0f}đ'
            )
        plain_lines.append(f'\nTổng tiền: {order.total_price:,.0f}đ')
        plain_lines.append(f'\nXem chi tiết đơn hàng: {order_detail_url}')
        plain_content = '\n'.join(plain_lines)

        msg = EmailMultiAlternatives(
            subject=subject,
            body=plain_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient],
        )
        msg.attach_alternative(html_content, 'text/html')
        msg.send()
    except Exception as e:
        logger.error(f'[email] send_order_status_update failed for order {getattr(order, "order_code", "?")}: {e}')
