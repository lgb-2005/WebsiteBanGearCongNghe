import hashlib
import hmac
import os
import urllib.parse
from decimal import Decimal
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse

from orders.models import Order
from techgear.settings import _env_bool, _env_hosts


class SettingsEnvironmentTests(TestCase):
    def test_environment_helpers_parse_false_and_hosts(self):
        with patch.dict(
            os.environ,
            {
                'TEST_DEBUG_VALUE': 'False',
                'TEST_ALLOWED_HOSTS': 'example.com, api.example.com ,',
            },
        ):
            self.assertFalse(_env_bool('TEST_DEBUG_VALUE', default=True))
            self.assertEqual(
                _env_hosts('TEST_ALLOWED_HOSTS'),
                ['example.com', 'api.example.com'],
            )


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    SITE_URL='https://shop.example.com',
)
class OrderEmailLinkTests(TestCase):
    def setUp(self):
        self.order = Order.objects.create(
            order_code='DHEMAILTEST01',
            receiver_name='Email Test',
            receiver_phone='0900000000',
            receiver_email='email@example.com',
            shipping_address='Ho Chi Minh City',
            total_price=Decimal('150000.00'),
            payment_method='cod',
            payment_status='pending',
            status='pending',
        )
        self.order_detail_url = 'https://shop.example.com/orders/DHEMAILTEST01/'

    def test_confirmation_email_contains_order_detail_link(self):
        from orders.email import send_order_confirmation

        send_order_confirmation(self.order)

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.order_detail_url, mail.outbox[0].body)
        self.assertIn(self.order_detail_url, mail.outbox[0].alternatives[0][0])

    def test_status_update_email_contains_order_detail_link(self):
        from orders.email import send_order_status_update

        send_order_status_update(self.order, 'pending', 'processing')

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.order_detail_url, mail.outbox[0].body)
        self.assertIn(self.order_detail_url, mail.outbox[0].alternatives[0][0])


@override_settings(VNPAY_HASH_SECRET='test-vnpay-secret')
class VNPayCallbackTests(TestCase):
    def setUp(self):
        self.order = Order.objects.create(
            order_code='DHVNPAYTEST01',
            receiver_name='VNPay Test',
            receiver_phone='0900000000',
            receiver_email='vnpay@example.com',
            shipping_address='Ho Chi Minh City',
            total_price=Decimal('150000.00'),
            payment_method='vnpay',
            payment_status='pending',
            status='pending',
        )

    def _signed_params(self, **overrides):
        params = {
            'vnp_Amount': str(int(self.order.total_price * 100)),
            'vnp_ResponseCode': '00',
            'vnp_TmnCode': 'TESTCODE',
            'vnp_TxnRef': self.order.order_code,
            'vnp_TransactionStatus': '00',
            'vnp_Version': '2.1.0',
        }
        params.update(overrides)
        query_string = urllib.parse.urlencode(sorted(params.items()))
        params['vnp_SecureHash'] = hmac.new(
            b'test-vnpay-secret',
            query_string.encode('utf-8'),
            hashlib.sha512,
        ).hexdigest()
        return params

    def test_ipn_confirms_valid_payment_once(self):
        with patch('orders.email._send_in_background') as send_mock:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.get(reverse('orders:vnpay_ipn'), self._signed_params())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'RspCode': '00', 'Message': 'Confirm Success'})
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'paid')
        self.assertEqual(send_mock.call_count, 2)

    def test_ipn_rejects_invalid_checksum_without_updating_order(self):
        params = self._signed_params(vnp_SecureHash='invalid')
        response = self.client.get(reverse('orders:vnpay_ipn'), params)

        self.assertEqual(response.json(), {'RspCode': '97', 'Message': 'Invalid Checksum'})
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'pending')

    def test_ipn_rejects_invalid_amount_without_updating_order(self):
        response = self.client.get(
            reverse('orders:vnpay_ipn'),
            self._signed_params(vnp_Amount='1'),
        )

        self.assertEqual(response.json(), {'RspCode': '04', 'Message': 'Invalid Amount'})
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'pending')

    def test_ipn_reports_missing_order(self):
        response = self.client.get(
            reverse('orders:vnpay_ipn'),
            self._signed_params(vnp_TxnRef='DHUNKNOWN'),
        )

        self.assertEqual(response.json(), {'RspCode': '01', 'Message': 'Order not Found'})

    def test_duplicate_ipn_does_not_send_duplicate_notifications(self):
        with patch('orders.email._send_in_background') as send_mock:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.get(reverse('orders:vnpay_ipn'), self._signed_params())
            response = self.client.get(reverse('orders:vnpay_ipn'), self._signed_params())

        self.assertEqual(response.json(), {'RspCode': '02', 'Message': 'Order already confirmed'})
        self.assertEqual(send_mock.call_count, 2)

    def test_return_url_then_ipn_is_idempotent(self):
        with patch('orders.email._send_in_background') as send_mock:
            with self.captureOnCommitCallbacks(execute=True):
                return_response = self.client.get(
                    reverse('orders:vnpay_return'),
                    self._signed_params(),
                )
            ipn_response = self.client.get(reverse('orders:vnpay_ipn'), self._signed_params())

        self.assertEqual(return_response.status_code, 302)
        self.assertEqual(ipn_response.json(), {'RspCode': '02', 'Message': 'Order already confirmed'})
        self.assertEqual(send_mock.call_count, 2)

    def test_return_url_redirects_to_payment_result_page(self):
        with patch('orders.email._send_in_background'):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.get(
                    reverse('orders:vnpay_return'),
                    self._signed_params(),
                )

        self.assertRedirects(response, reverse('orders:vnpay_payment_result'))
        result_response = self.client.get(reverse('orders:vnpay_payment_result'))
        self.assertContains(result_response, 'Thanh toán thành công')
        self.assertContains(result_response, self.order.order_code)

    def test_ipn_then_return_url_is_idempotent(self):
        with patch('orders.email._send_in_background') as send_mock:
            with self.captureOnCommitCallbacks(execute=True):
                ipn_response = self.client.get(reverse('orders:vnpay_ipn'), self._signed_params())
            return_response = self.client.get(
                reverse('orders:vnpay_return'),
                self._signed_params(),
            )

        self.assertEqual(ipn_response.json(), {'RspCode': '00', 'Message': 'Confirm Success'})
        self.assertEqual(return_response.status_code, 302)
        self.assertEqual(send_mock.call_count, 2)

    def test_failed_callback_does_not_mark_payment_as_paid(self):
        response = self.client.get(
            reverse('orders:vnpay_ipn'),
            self._signed_params(vnp_ResponseCode='24'),
        )

        self.assertEqual(response.json(), {'RspCode': '00', 'Message': 'Confirm Success'})
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, 'pending')

    def test_ipn_accepts_only_get_requests(self):
        response = self.client.post(reverse('orders:vnpay_ipn'), self._signed_params())
        self.assertEqual(response.status_code, 405)
