from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.types import Message, CallbackQuery

from middlewares.throttling import ThrottlingMiddleware


class _FakeMessage(Message):
    pass


class _FakeCallbackQuery(CallbackQuery):
    pass


def _make_message(user_id):
    return _FakeMessage.model_construct(from_user=SimpleNamespace(id=user_id, username="u", full_name="U"))


def _make_callback(user_id):
    return _FakeCallbackQuery.model_construct(from_user=SimpleNamespace(id=user_id, username="u", full_name="U"))


async def test_throttling_allows_first_message():
    mw = ThrottlingMiddleware(rate_limit=1.0)
    handler = AsyncMock(return_value="ok")

    result = await mw(handler, _make_message(111), {})
    assert result == "ok"
    handler.assert_awaited_once()


async def test_throttling_blocks_rapid_second_message_from_same_user():
    mw = ThrottlingMiddleware(rate_limit=1.0)
    handler = AsyncMock(return_value="ok")

    await mw(handler, _make_message(111), {})
    result = await mw(handler, _make_message(111), {})

    assert result is None
    handler.assert_awaited_once()


async def test_throttling_allows_different_users_independently():
    mw = ThrottlingMiddleware(rate_limit=1.0)
    handler = AsyncMock(return_value="ok")

    await mw(handler, _make_message(111), {})
    result = await mw(handler, _make_message(222), {})

    assert result == "ok"
    assert handler.await_count == 2


async def test_throttling_notifies_callback_query_when_blocked(db, monkeypatch):
    mw = ThrottlingMiddleware(rate_limit=1.0)
    handler = AsyncMock(return_value="ok")

    answer_mock = AsyncMock()
    monkeypatch.setattr(_FakeCallbackQuery, "answer", answer_mock)

    await mw(handler, _make_callback(111), {})
    await mw(handler, _make_callback(111), {})

    answer_mock.assert_awaited_once()
    handler.assert_awaited_once()
