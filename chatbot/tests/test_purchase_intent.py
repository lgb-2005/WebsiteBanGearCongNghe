from copy import deepcopy
from datetime import datetime, timezone as dt_timezone
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase, override_settings
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

    def test_logged_snapshot_copies_aliases_and_normalizes_invalid_numbers(self):
        aliases = {'brand': 'test'}
        payload = {'available': False, 'reason': 'model_unavailable',
                   'purchase_probability': float('nan'),
                   'behavior_summary': {'view_count': 'bad', 'avg_price_usd': float('inf')}}
        original = deepcopy(payload)
        result = ChatEngine._build_logged_aliases(aliases, payload)
        self.assertEqual(aliases, {'brand': 'test'})
        self.assertIsNot(result, aliases)
        snapshot = result['_ml_purchase_intent']
        self.assertFalse(snapshot['available'])
        self.assertEqual(snapshot['purchase_probability'], 0)
        self.assertEqual(snapshot['behavior_summary']['view_count'], 0)
        snapshot['behavior_summary']['view_count'] = 99
        self.assertEqual(payload['behavior_summary'], original['behavior_summary'])
        for empty in (None, {}, [], 'bad'):
            self.assertEqual(ChatEngine._build_logged_aliases(aliases, empty), aliases)

    def test_snapshot_is_persisted_on_success_and_provider_initialization_error(self):
        from chatbot.providers.exceptions import ProviderError
        intent = {'available': True, 'user_session': str(self.session.pk),
                  'intent_level': 'high', 'purchase_probability_pct': 68.0,
                  'behavior_summary': {'effective_cart_count': 1}}
        for broken in (False, True):
            with self.subTest(broken=broken):
                ctx = ChatContext(user=self.user, session_id='snapshot-browser')
                ctx.purchase_intent = deepcopy(intent)
                engine = ChatEngine(MockProvider([LLMResult(text='Tôi sẽ giúp bạn.')]))
                conversation = Conversation.objects.create(user=self.user)
                if broken:
                    with patch.object(engine, '_ensure_provider', side_effect=ProviderError('offline')):
                        engine.process('Xin chào', conversation, ctx)
                else:
                    engine.process('Xin chào', conversation, ctx)
                log = conversation.turn_logs.get()
                snapshot = log.resolved_aliases['_ml_purchase_intent']
                self.assertEqual(snapshot['user_session'], str(self.session.pk))
                self.assertEqual(snapshot['intent_level'], 'high')
                self.assertEqual(snapshot['purchase_probability_pct'], 68.0)
                self.assertEqual(snapshot['behavior_summary']['effective_cart_count'], 1)
                self.assertEqual(ctx.purchase_intent, intent)
                self.assertEqual(log.status, 'api_error' if broken else 'ok')

    def test_admin_actor_sources_and_invalid_dashboard_sessions(self):
        from analytics.ml.purchase_intent import _resolve_actor
        self.other.is_staff = True
        self.other.save()
        req = self.request(self.user)
        req.admin_user = self.other
        self.assertEqual(_resolve_actor(req), self.other)
        del req.admin_user
        req.session['admin_dashboard_user_id'] = self.other.pk
        self.assertEqual(_resolve_actor(req), self.other)
        req.user = self.other
        self.assertEqual(_resolve_actor(req), self.other)
        req.user = AnonymousUser()
        self.other.is_staff = False
        self.other.is_superuser = True
        self.other.save()
        self.assertEqual(_resolve_actor(req), self.other)
        for invalid in ('bad', 2**100, self.user.pk, 999999):
            req.session['admin_dashboard_user_id'] = invalid
            self.assertFalse(getattr(_resolve_actor(req), 'is_staff', False))
        req.session['admin_dashboard_user_id'] = self.other.pk
        self.other.is_superuser = False
        self.other.save()
        self.assertFalse(getattr(_resolve_actor(req), 'is_authenticated', False))
        self.assertIsNone(resolve_analytics_session(self.request(), user=self.user))
        self.assertEqual(str(resolve_analytics_session(user=self.user).pk), str(self.session.pk))

    def test_admin_query_lookup_and_access_denial(self):
        self.user.name = 'Intent Owner'
        self.user.save()
        for actor in (None, self.user, self.other):
            req = self.request(actor)
            self.assertEqual(get_customer_purchase_intent_payload(
                req, query=self.user.email)['reason'], 'not_found')
        self.assertEqual(self.client.get(self.url, {'q': self.user.email}).status_code, 404)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url, {'q': self.user.email}).status_code, 404)
        self.client.logout()
        self.other.is_staff = True
        self.other.save()
        store = self.client.session
        store['admin_dashboard_user_id'] = self.other.pk
        store.save()
        with patch('analytics.ml.predictor.predict_session_purchase_intent', return_value=prediction()), patch(
                'chatbot.engine.GeminiProvider', side_effect=AssertionError('API must not initialize an LLM')):
            for params in ({'q': self.user.email.upper()}, {'q': '  Intent   Owner  '},
                           {'q': str(self.session.pk)}, {'q': str(self.session.pk)[:8]},
                           {'q': str(self.user.pk)}, {'session_id': self.session.pk},
                           {'user_id': self.user.pk}):
                with self.subTest(params=params):
                    response = self.client.get(self.url, params)
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.json()['available'])
                    self.assertEqual(response.json()['user_session'], str(self.session.pk))
                    self.assertEqual(response['Cache-Control'], 'private, no-store')
        self.assertEqual(self.client.get(self.url, {'q': 'missing@example.test'}).status_code, 404)

    def test_staff_prefers_active_session_but_normal_user_keeps_latest(self):
        empty = Session.objects.create(user=self.user)
        self.other.is_staff = True
        self.other.save()
        req = self.request(self.other)
        self.assertEqual(str(resolve_analytics_session(req, query=self.user.email).pk), str(self.session.pk))
        self.assertEqual(str(resolve_analytics_session(req, user=self.user).pk), str(self.session.pk))
        self.assertEqual(str(resolve_analytics_session(req, session_id=empty.pk).pk), str(empty.pk))
        self.assertEqual(str(resolve_analytics_session(self.request(self.user)).pk), str(empty.pk))
        Event.objects.create(session=empty, event_type='add_to_cart', product=self.product)
        self.assertEqual(str(resolve_analytics_session(req, query=self.user.email).pk), str(empty.pk))
        Event.objects.filter(session__user=self.user).delete()
        self.assertEqual(str(resolve_analytics_session(req, user=self.user).pk), str(empty.pk))

    def test_query_validation_and_unavailable_statuses(self):
        for params in ({'q': ''}, {'q': '   '}, {'q': 'x' * 256},
                       {'q': 'abc', 'session_id': '123'}, {'q': 'abc', 'user_id': '1'},
                       {'q': 'abc', 'unknown': '1'}):
            with self.subTest(params=params):
                self.assertEqual(self.client.get(self.url, params).status_code, 400)
        self.assertEqual(self.client.get(self.url, {'q': 'x' * 255}).status_code, 404)
        with override_settings(CHATBOT_ENABLED=False):
            self.assertEqual(self.client.get(self.url).status_code, 503)
        self.other.is_staff = True
        self.other.save()
        self.client.force_login(self.other)
        with patch('analytics.ml.predictor.predict_session_purchase_intent', side_effect=FileNotFoundError):
            response = self.client.get(self.url, {'q': self.user.email})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['reason'], 'model_unavailable')

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
        self.assertEqual(empty.status_code, 404)
        Session.objects.create(user=self.other)
        empty = self.client.get(self.url, {'user_id': self.other.pk})
        self.assertEqual(empty.status_code, 200)
        self.assertFalse(empty.json()['available'])
        self.assertEqual(empty.json()['reason'], 'no_activity')
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
