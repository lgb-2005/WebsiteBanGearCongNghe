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
