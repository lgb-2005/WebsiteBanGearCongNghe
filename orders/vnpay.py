import hmac
import hashlib
import urllib.parse
from datetime import datetime

from django.conf import settings


_RESPONSE_CODE_MESSAGES = {
    '00': 'Thanh toán thành công',
    '07': 'Trừ tiền thành công. Giao dịch bị nghi ngờ (liên quan tới lừa đảo, giao dịch bất thường)',
    '09': 'Thẻ/Tài khoản chưa đăng ký dịch vụ InternetBanking',
    '10': 'Xác thực thông tin thẻ/tài khoản không đúng quá 3 lần',
    '11': 'Giao dịch đã hết hạn chờ thanh toán',
    '12': 'Thẻ/Tài khoản bị khóa',
    '13': 'Sai mật khẩu OTP',
    '24': 'Khách hàng hủy giao dịch',
    '51': 'Tài khoản không đủ số dư',
    '65': 'Tài khoản vượt hạn mức giao dịch trong ngày',
    '75': 'Ngân hàng thanh toán đang bảo trì',
    '79': 'Sai mật khẩu thanh toán quá số lần quy định',
    '99': 'Lỗi không xác định',
}


def _hmac_sha512(secret: str, data: str) -> str:
    return hmac.new(
        secret.encode('utf-8'),
        data.encode('utf-8'),
        hashlib.sha512
    ).hexdigest()


def _get_client_ip(request) -> str:
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '127.0.0.1')


def build_vnpay_payment_url(order, request) -> str:
    vnp_params = {
        'vnp_Version': '2.1.0',
        'vnp_Command': 'pay',
        'vnp_TmnCode': settings.VNPAY_TMN_CODE,
        'vnp_Amount': str(int(order.total_price * 100)),
        'vnp_CurrCode': 'VND',
        'vnp_TxnRef': order.order_code,
        'vnp_OrderInfo': f'Thanh toan don hang {order.order_code}',
        'vnp_OrderType': 'other',
        'vnp_Locale': 'vn',
        'vnp_ReturnUrl': settings.VNPAY_RETURN_URL,
        'vnp_IpAddr': _get_client_ip(request),
        'vnp_CreateDate': datetime.now().strftime('%Y%m%d%H%M%S'),
    }

    sorted_params = sorted(vnp_params.items())
    query_string = urllib.parse.urlencode(sorted_params)
    secure_hash = _hmac_sha512(settings.VNPAY_HASH_SECRET, query_string)

    return f"{settings.VNPAY_URL}?{query_string}&vnp_SecureHash={secure_hash}"


def verify_vnpay_return(params: dict) -> bool:
    received_hash = params.get('vnp_SecureHash', '')
    if not received_hash or not settings.VNPAY_HASH_SECRET:
        return False
    filtered = {
        key: value
        for key, value in params.items()
        if key not in ('vnp_SecureHash', 'vnp_SecureHashType')
    }
    sorted_params = sorted(filtered.items())
    query_string = urllib.parse.urlencode(sorted_params)
    expected_hash = _hmac_sha512(settings.VNPAY_HASH_SECRET, query_string)
    return hmac.compare_digest(expected_hash.lower(), received_hash.lower())


def get_vnpay_order_amount(order) -> int:
    return int(order.total_price * 100)


def is_valid_vnpay_amount(order, amount) -> bool:
    try:
        return int(amount) == get_vnpay_order_amount(order)
    except (TypeError, ValueError):
        return False


def get_response_message(code: str) -> str:
    return _RESPONSE_CODE_MESSAGES.get(code, 'Thanh toán không thành công. Vui lòng thử lại.')
