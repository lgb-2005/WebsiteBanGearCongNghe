import pytest

from chatbot.context import ChatContext
from chatbot.engine import ChatEngine
from chatbot.models import Conversation, Message
from chatbot.providers.base import LLMMessage, LLMProvider, LLMResult
from chatbot.providers.exceptions import ProviderError, ProviderTimeout, QuotaExceeded
from chatbot.tools.registry import TOOL_REGISTRY

from .factories import make_brand, make_category, make_product, make_user, make_value


class MockProvider(LLMProvider):
    """Provider giả lập cho test, trả về các kết quả được cấu hình trước.

    Nếu hết phản hồi thì tự động trả về text rỗng để tránh StopIteration
    trong vòng lặp tool-calling.
    """

    DEFAULT_TEXT = LLMResult(text='Đây là câu trả lời cuối cùng.')

    def __init__(self, responses):
        self.responses = list(responses)
        self.index = 0
        self.calls = []

    def generate(self, system_prompt, messages, tools):
        if self.index < len(self.responses):
            result = self.responses[self.index]
        else:
            result = self.DEFAULT_TEXT
        self.index += 1
        self.calls.append({
            'system_prompt': system_prompt,
            'messages': messages,
            'tools': tools,
            'result': result,
        })
        return result


def _search_response(tool_args):
    return LLMResult(
        text='Dưới đây là các sản phẩm phù hợp.',
        tool_calls=[{'name': 'search_products', 'arguments': tool_args}],
    )


def _text_response(text):
    return LLMResult(text=text)


def _compare_response(slugs):
    return LLMResult(
        text='Bảng so sánh như sau.',
        tool_calls=[{'name': 'compare_products', 'arguments': {'slugs': slugs}}],
    )


@pytest.fixture
def ctx():
    return ChatContext(user=None, session_id='test-session')


@pytest.fixture
def category(db):
    return make_category()


@pytest.fixture
def brand(db):
    return make_brand()


@pytest.fixture
def product(category, brand, db):
    return make_product(category=category, brand=brand, name='Chuột Test', slug='chuot-test', price='800000')


@pytest.mark.django_db
def test_engine_calls_search_and_persist(category, brand, product, ctx):
    conversation = Conversation.objects.create(session_id='s1')
    engine = ChatEngine(provider=MockProvider([
        _search_response({'category_slug': 'chuot', 'limit': 5}),
    ]))

    response = engine.process('tư vấn chuột', conversation, ctx)

    assert response['conversation_id'] == conversation.pk
    assert 'reply' in response
    assert response['products']
    assert len(response['products']) >= 1

    messages = list(conversation.messages.order_by('created_at'))
    assert len(messages) == 2
    assert messages[0].role == Message.ROLE_USER
    assert messages[1].role == Message.ROLE_ASSISTANT
    assert messages[1].products == response['products']


@pytest.mark.django_db
def test_engine_clarify_increments_count(category, ctx):
    conversation = Conversation.objects.create(session_id='s2')
    engine = ChatEngine(provider=MockProvider([
        _text_response('Bạn đang cần tư vấn sản phẩm nào?'),
    ]))

    response = engine.process('tư vấn', conversation, ctx)
    assert 'Bạn đang cần' in response['reply']
    conversation.refresh_from_db()
    assert conversation.clarify_count == 1


@pytest.mark.django_db
def test_engine_force_search_after_max_clarify(category, product, ctx):
    conversation = Conversation.objects.create(session_id='s3', clarify_count=2)
    engine = ChatEngine(provider=MockProvider([
        _search_response({'category_slug': 'chuot', 'limit': 5}),
    ]))

    response = engine.process('tư vấn', conversation, ctx)
    assert response['products']
    conversation.refresh_from_db()
    assert conversation.clarify_count == 0

    call = engine.provider.calls[0]
    assert 'Hãy tìm kiếm ngay' in call['messages'][-1].content


@pytest.mark.django_db
def test_engine_handles_quota_error(ctx):
    conversation = Conversation.objects.create(session_id='s4')

    class ErrorProvider(LLMProvider):
        def generate(self, system_prompt, messages, tools):
            raise QuotaExceeded('quota exceeded')

    engine = ChatEngine(provider=ErrorProvider())
    response = engine.process('hello', conversation, ctx)

    assert 'quá tải' in response['reply']
    assert response['products'] is None


@pytest.mark.django_db
def test_engine_handles_timeout(ctx):
    conversation = Conversation.objects.create(session_id='s5')

    class TimeoutProvider(LLMProvider):
        def generate(self, system_prompt, messages, tools):
            raise ProviderTimeout('timeout')

    engine = ChatEngine(provider=TimeoutProvider())
    response = engine.process('hello', conversation, ctx)

    assert 'chậm' in response['reply'] or 'thử lại' in response['reply']


@pytest.mark.django_db
def test_engine_compare_products(category, brand, ctx):
    make_product(category=category, brand=brand, name='Chuột A', slug='chuot-a', price='1000000')
    make_product(category=category, brand=brand, name='Chuột B', slug='chuot-b', price='1200000')
    conversation = Conversation.objects.create(session_id='s6')

    engine = ChatEngine(provider=MockProvider([
        _compare_response(['chuot-a', 'chuot-b']),
    ]))

    response = engine.process('so sánh chuot-a và chuot-b', conversation, ctx)
    assert response['comparison'] is not None
    assert len(response['products']) == 2


@pytest.mark.django_db
def test_engine_resets_clarify_count_after_tool_call(category, product, ctx):
    conversation = Conversation.objects.create(session_id='s7', clarify_count=1)
    engine = ChatEngine(provider=MockProvider([
        _search_response({'category_slug': 'chuot', 'limit': 5}),
    ]))

    response = engine.process('chuột dưới 1 triệu', conversation, ctx)
    assert response['products']
    conversation.refresh_from_db()
    assert conversation.clarify_count == 0


@pytest.mark.django_db
def test_engine_does_not_duplicate_user_message_in_provider_messages(category, ctx):
    conversation = Conversation.objects.create(session_id='s8')
    provider = MockProvider([
        _text_response('Bạn cần tìm chuột trong tầm giá bao nhiêu?'),
    ])
    engine = ChatEngine(provider=provider)
    engine.process('tư vấn chuột', conversation, ctx)

    first_call_messages = provider.calls[0]['messages']
    user_msgs = [m for m in first_call_messages if m.role == 'user']
    assert len(user_msgs) == 1
    assert user_msgs[0].content == 'tư vấn chuột'


@pytest.mark.django_db
def test_engine_includes_product_slugs_in_history_for_next_turn(category, brand, product, ctx):
    conversation = Conversation.objects.create(session_id='s9')
    provider_turn1 = MockProvider([
        _search_response({'category_slug': 'chuot', 'limit': 5}),
        _text_response('Mình gợi ý mẫu Chuột Test nhé.'),
    ])
    ChatEngine(provider=provider_turn1).process('tư vấn chuột dưới 1 triệu', conversation, ctx)

    provider_turn2 = MockProvider([
        _text_response('Chi tiết mẫu Chuột Test như sau.'),
    ])
    ChatEngine(provider=provider_turn2).process('chi tiết mẫu đầu tiên', conversation, ctx)

    turn2_messages = provider_turn2.calls[0]['messages']
    assistant_history = [m for m in turn2_messages if m.role == 'assistant']
    assert len(assistant_history) == 1
    assert 'slug: chuot-test' in assistant_history[0].content


@pytest.mark.django_db
def test_engine_accumulates_tokens_across_tool_rounds(category, brand, product, ctx):
    conversation = Conversation.objects.create(session_id='s10')
    round1 = LLMResult(
        text='',
        tool_calls=[{'name': 'search_products', 'arguments': {'category_slug': 'chuot'}}],
        prompt_tokens=120,
        completion_tokens=30,
    )
    round2 = LLMResult(
        text='Đây là kết quả tư vấn.',
        prompt_tokens=200,
        completion_tokens=50,
    )
    engine = ChatEngine(provider=MockProvider([round1, round2]))
    engine.process('chuột gaming dưới 1 triệu', conversation, ctx)

    log = conversation.turn_logs.first()
    assert log is not None
    assert log.prompt_tokens == 320
    assert log.completion_tokens == 80


@pytest.mark.django_db
def test_engine_strips_ui_fields_from_llm_tool_payload(category, brand, product, ctx):
    conversation = Conversation.objects.create(session_id='s11')
    provider = MockProvider([
        _search_response({'category_slug': 'chuot', 'limit': 5}),
        _text_response('Mình tìm thấy mẫu Chuột Test.'),
    ])
    response = ChatEngine(provider=provider).process('tư vấn chuột', conversation, ctx)

    assert response['products']
    assert response['products'][0]['slug'] == 'chuot-test'

    round2_messages = provider.calls[1]['messages']
    tool_msgs = [m for m in round2_messages if m.role == 'tool']
    assert len(tool_msgs) == 1
    assert 'ui_results' not in tool_msgs[0].tool_payload
    assert 'results' in tool_msgs[0].tool_payload


@pytest.mark.django_db
def test_engine_extracts_relaxation_ui_results_when_no_exact_match(category, brand, product, ctx):
    conversation = Conversation.objects.create(session_id='s12')
    provider = MockProvider([
        _search_response({'category_slug': 'chuot', 'price_max': 700000, 'limit': 5}),
        _text_response('Không có mẫu dưới 700k, nhưng có mẫu 800k rất đáng cân nhắc.'),
    ])
    response = ChatEngine(provider=provider).process('chuột dưới 700k', conversation, ctx)

    assert response['products']
    assert response['products'][0]['slug'] == 'chuot-test'

    round2_messages = provider.calls[1]['messages']
    tool_msgs = [m for m in round2_messages if m.role == 'tool']
    assert 'ui_results' not in (tool_msgs[0].tool_payload.get('relaxation') or {})


def test_gemini_provider_retries_on_503_unavailable(monkeypatch):
    from google.genai.errors import APIError
    from chatbot.providers.gemini import GeminiProvider

    provider = GeminiProvider(
        api_key='test-key',
        model='gemini-2.5-flash',
        thinking_budget=0,
        max_transient_retries=2,
        transient_retry_delay=0,
    )

    calls = []

    class DummyPart:
        text = 'Phản hồi thành công sau khi retry 503.'
        function_call = None

    class DummyContent:
        parts = [DummyPart()]

    class DummyCandidate:
        content = DummyContent()

    class DummyResponse:
        usage_metadata = None
        candidates = [DummyCandidate()]

    def fake_call_api(system_prompt, messages, tools):
        calls.append(1)
        if len(calls) == 1:
            raise APIError(503, {'error': {'code': 503, 'message': 'This model is currently experiencing high demand.'}})
        return DummyResponse()

    monkeypatch.setattr(provider, '_call_api', fake_call_api)
    result = provider.generate('system', [LLMMessage(role='user', content='hi')], [])

    assert len(calls) == 2
    assert 'thành công' in result.text


@pytest.mark.django_db
def test_engine_fast_path_answers_in_single_llm_round(category, brand, product, ctx):
    conversation = Conversation.objects.create(session_id='s13')
    provider = MockProvider([
        _text_response('Mình tìm thấy mẫu **Chuột Test** (800.000đ) phù hợp với bạn.'),
    ])
    engine = ChatEngine(provider=provider, enable_fast_path=True)
    response = engine.process('tư vấn chuột dưới 1tr5', conversation, ctx)

    assert len(provider.calls) == 1
    assert response['meta']['loop_rounds'] == 1
    assert response['products']
    assert response['products'][0]['slug'] == 'chuot-test'
    assert 'chuot-test' in provider.calls[0]['messages'][-1].content
