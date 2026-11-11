from copy import deepcopy
from datetime import datetime, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase
from django.core.cache import cache
from analytics.models import Event, Session
from analytics.ml.purchase_intent import get_customer_purchase_intent_payload, resolve_analytics_session
from chatbot.context import ChatContext
from chatbot.engine import ChatEngine
from chatbot.models import Conversation
from chatbot.prompts import build_system_prompt
from chatbot.providers.base import LLMResult
from chatbot.tools.customer import get_customer_purchase_intent
from .factories import make_category, make_product, make_user
from .test_engine import MockProvider


def prediction(probability=0.68):
    return {'purchase_probability': probability, 'optimal_threshold': 0.31,
            'champion_model_name': 'gradient_boosting', 'raw_add_to_cart_count': 2,
            'raw_remove_from_cart_count': 1, 'effective_cart_count': 1,
            'features': {'view_count': 6, 'unique_products': 3, 'unique_categories': 1,
                         'session_duration_sec': 215.0, 'repeat_view_ratio': 0.5,
                         'cart_to_view_ratio': 1 / 6, 'cart_count': 1, 'remove_cart_count': 1,
                         'avg_price': 84.0}}


class PurchaseIntentTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = make_user(email='intent-owner@example.test')
        self.other = make_user(email='intent-other@example.test')
        self.product = make_product(make_category(), slug='intent-product', price='1000000')
        self.session = Session.objects.create(user=self.user)
        self.url = '/chatbot/api/purchase-intent/'
        Event.objects.create(session=self.session, user=self.user, event_type='view_product',
                             product=self.product, event_value=1000000)

    def tearDown(self):
        cache.clear()

    def request(self, user=None, sid=None):
        req = RequestFactory().get(self.url)
        req.user = user or AnonymousUser()
        req.session = {'analytics_session_id': str(sid)} if sid else {}
        return req

    def test_resolver_prioritizes_explicit_then_browser_then_own_latest(self):
        newer = Session.objects.create(user=self.user)
        req = self.request(self.user, self.session.pk)
        self.assertEqual(str(resolve_analytics_session(req, session_id=newer.pk).pk), str(newer.pk))
        self.assertEqual(str(resolve_analytics_session(req).pk), str(self.session.pk))
        self.assertEqual(str(resolve_analytics_session(self.request(self.user)).pk), str(newer.pk))
        self.assertIsNone(resolve_analytics_session(self.request(self.other), session_id=self.session.pk))
        self.assertIsNone(resolve_analytics_session(session_id=self.session.pk))

    def test_guest_cannot_read_another_guest_or_logged_in_session(self):
        guest = Session.objects.create()
        browser = self.client.session
        browser['analytics_session_id'] = str(guest.pk)
        browser.save()
        self.assertEqual(self.client.get(self.url, {'session_id': guest.pk}).status_code, 200)
        self.assertEqual(self.client.get(self.url, {'session_id': self.session.pk}).status_code, 404)
        foreign = Session.objects.create()
        self.assertEqual(self.client.get(self.url, {'session_id': foreign.pk}).status_code, 404)
        self.assertEqual(self.client.get(self.url, {'user_id': self.user.pk}).status_code, 404)

    def test_authenticated_scope_and_staff_lookup(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url, {'user_id': self.user.pk}).status_code, 404)
        self.assertEqual(self.client.get(self.url, {'session_id': self.session.pk}).status_code, 404)
        self.other.is_staff = True
        self.other.save()
        self.client.force_login(self.other)
        with patch('analytics.ml.predictor.predict_session_purchase_intent', return_value=prediction()):
            result = self.client.get(self.url, {'user_id': self.user.pk})
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()['available'])
        self.assertEqual(result['Cache-Control'], 'private, no-store')

    def test_missing_events_or_model_are_safe_and_not_real_zero_predictions(self):
        self.assertFalse(self.client.get(self.url).json()['available'])
        self.client.force_login(self.other)
        empty = self.client.get(self.url, {'user_id': self.other.pk})
        self.assertEqual(empty.status_code, 200)
        self.assertFalse(empty.json()['available'])
        req = self.request(self.user)
        with patch('analytics.ml.predictor.predict_session_purchase_intent', side_effect=FileNotFoundError):
            result = get_customer_purchase_intent_payload(req)
        self.assertFalse(result['available'])
        self.assertEqual(result['reason'], 'model_unavailable')
        self.assertEqual(result['purchase_probability'], 0)

    def test_threshold_boundaries_and_behavior_summary(self):
        for probability, expected in [(0, 'low'), (0.154999, 'low'), (0.155, 'medium'),
                                      (0.309999, 'medium'), (0.31, 'high'), (1, 'high')]:
            cache.clear()
            with self.subTest(probability=probability), patch(
                    'analytics.ml.predictor.predict_session_purchase_intent', return_value=prediction(probability)):
                result = get_customer_purchase_intent_payload(self.request(self.user))
                self.assertEqual(result['intent_level'], expected)
                self.assertEqual(result['behavior_summary']['effective_cart_count'], 1)
                self.assertEqual(result['behavior_summary']['avg_price_usd'], 84.0)
                self.assertEqual(result['will_purchase'], probability >= 0.31)

    def test_bad_queries_and_http_method(self):
        for params in [{'user_id': 'bad'}, {'session_id': ''}, {'session_id': 'a', 'user_id': 1}, {'other': 1}]:
            with self.subTest(params=params):
                self.assertEqual(self.client.get(self.url, params).status_code, 400)
        self.assertEqual(self.client.post(self.url).status_code, 405)

    def test_live_naive_dates_are_converted_to_local_timezone_in_memory_only(self):
        moment = datetime(2026, 11, 10, 10, 0)
        Event.objects.filter(session=self.session).update(created_at=moment)
        with patch('analytics.ml.predictor.predict_session_purchase_intent', return_value=prediction()) as predict:
            get_customer_purchase_intent_payload(self.request(self.user))
        events = predict.call_args.args[0]
        self.assertEqual(events[0].created_at.astimezone(dt_timezone.utc).hour, 3)
        self.assertEqual(Event.objects.get(session=self.session).created_at, moment)

    def test_context_tool_prompt_and_chat_response_share_authorized_snapshot(self):
        request = self.request(self.user, self.session.pk)
        # RequestFactory has a dict session; ChatContext only needs a saved key.
        from django.contrib.sessions.backends.db import SessionStore
        store = SessionStore()
        store['analytics_session_id'] = str(self.session.pk)
        store.save()
        request.session = store
        with patch('analytics.ml.predictor.predict_session_purchase_intent', return_value=prediction()):
            ctx = ChatContext.from_request(request)
        snapshot = deepcopy(ctx.purchase_intent)
        tool_payload = get_customer_purchase_intent(ctx)
        tool_payload['behavior_summary']['view_count'] = 999
        self.assertEqual(ctx.purchase_intent['behavior_summary']['view_count'], 6)
        prompt = build_system_prompt(purchase_intent=snapshot)
        self.assertIn('TÍN HIỆU DỰ ĐOÁN', prompt)
        provider = MockProvider([
            LLMResult(tool_calls=[{'name': 'get_customer_purchase_intent', 'arguments': {}}]),
            LLMResult(text='Đây là xác suất ước lượng trong phiên của bạn.'),
        ])
        conversation = Conversation.objects.create(user=self.user)
        response = ChatEngine(provider).process('Kiểm tra khả năng mua hàng hiện tại của tôi', conversation, ctx)
        self.assertEqual(response['purchase_intent'], snapshot)
        self.assertIn('TÍN HIỆU DỰ ĐOÁN', provider.calls[0]['system_prompt'])
        self.assertEqual(provider.calls[1]['messages'][-1].tool_payload, snapshot)

    def test_real_model_reacts_to_cart_removal_with_net_features(self):
        from analytics.ml.predictor import extract_live_session_features
        Event.objects.create(session=self.session, product=self.product, event_type='add_to_cart')
        Event.objects.create(session=self.session, product=self.product, event_type='remove_from_cart')
        extracted = extract_live_session_features(self.session)
        self.assertEqual(extracted['effective_cart_count'], 0)
        self.assertEqual(extracted['raw_remove_from_cart_count'], 1)

    def test_click_and_events_after_checkout_do_not_leak_into_features(self):
        from analytics.ml.predictor import extract_live_session_features
        view = self.session.event_set.first()
        Event.objects.filter(pk=view.pk).update(created_at=datetime(2026, 11, 10, 9, 0))
        click = Event.objects.create(session=self.session, event_type='click', product=self.product)
        checkout = Event.objects.create(session=self.session, event_type='checkout', product=self.product)
        late = Event.objects.create(session=self.session, event_type='add_to_cart', product=self.product)
        Event.objects.filter(pk=click.pk).update(created_at=datetime(2026, 11, 10, 9, 1))
        Event.objects.filter(pk=checkout.pk).update(created_at=datetime(2026, 11, 10, 9, 2))
        Event.objects.filter(pk=late.pk).update(created_at=datetime(2026, 11, 10, 9, 3))
        result = extract_live_session_features(self.session)
        self.assertEqual(result['view_count'], 1)
        self.assertEqual(result['cart_count'], 0)
        self.assertEqual(result['session_duration_sec'], 0)

    def test_cache_reuses_only_same_event_snapshot_and_refreshes_on_remove(self):
        req = self.request(self.user)
        with patch('analytics.ml.predictor.predict_session_purchase_intent', return_value=prediction()) as predict:
            first = get_customer_purchase_intent_payload(req)
            second = get_customer_purchase_intent_payload(req)
            self.assertEqual(predict.call_count, 1)
            self.assertFalse(first['cache_hit'])
            self.assertTrue(second['cache_hit'])
            Event.objects.create(session=self.session, product=self.product, event_type='remove_from_cart')
            get_customer_purchase_intent_payload(req)
            self.assertEqual(predict.call_count, 2)
