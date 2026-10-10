import pytest

from chatbot.context import ChatContext
from chatbot.throttling import check_rate_limit


@pytest.mark.django_db
def test_rate_limit_allows_first_requests():
    ctx = ChatContext(user=None, session_id='session-a')
    for _ in range(5):
        result = check_rate_limit(ctx)
        assert result['allowed'] is True


@pytest.mark.django_db
def test_rate_limit_blocks_after_threshold(monkeypatch):
    monkeypatch.setattr('chatbot.throttling.RATE_LIMIT_PER_HOUR', 2)
    ctx = ChatContext(user=None, session_id='session-b')

    assert check_rate_limit(ctx)['allowed'] is True
    assert check_rate_limit(ctx)['allowed'] is True
    blocked = check_rate_limit(ctx)
    assert blocked['allowed'] is False
    assert blocked['retry_after'] > 0


@pytest.mark.django_db
def test_rate_limit_separates_sessions():
    ctx_a = ChatContext(user=None, session_id='session-a')
    ctx_b = ChatContext(user=None, session_id='session-b')

    check_rate_limit(ctx_a)
    check_rate_limit(ctx_a)
    result_b = check_rate_limit(ctx_b)
    assert result_b['allowed'] is True


@pytest.mark.django_db
def test_rate_limit_disabled_when_zero(monkeypatch):
    monkeypatch.setattr('chatbot.throttling.RATE_LIMIT_PER_HOUR', 0)
    ctx = ChatContext(user=None, session_id='session-c')
    for _ in range(100):
        assert check_rate_limit(ctx)['allowed'] is True
