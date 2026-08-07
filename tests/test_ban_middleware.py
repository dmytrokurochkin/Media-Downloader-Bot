import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import Message, CallbackQuery

import middlewares.ban as ban_module
from middlewares.ban import BanCheckMiddleware


class _FakeMessage(Message):
    pass


class _FakeCallbackQuery(CallbackQuery):
    pass


def _make_message(user_id, username="u", full_name="U"):
    return _FakeMessage.model_construct(
        from_user=SimpleNamespace(id=user_id, username=username, full_name=full_name)
    )


def _make_callback(user_id, username="u", full_name="U"):
    return _FakeCallbackQuery.model_construct(
        from_user=SimpleNamespace(id=user_id, username=username, full_name=full_name)
    )


@pytest.fixture(autouse=True)
def _isolated_middleware_caches(monkeypatch):
    # These caches are plain module-level dicts in middlewares/ban.py; reset them
    # for every test so bans/notifications from one test can't leak into another.
    monkeypatch.setattr(ban_module, "BANNED_NOTIFIED_CACHE", {})
    monkeypatch.setattr(ban_module, "LAST_ACTIVE_CACHE", {})


async def test_non_banned_user_passes_through(db):
    await db.get_or_create_user(111, "u", "U", "en")
    mw = BanCheckMiddleware()
    handler = AsyncMock(return_value="ok")

    result = await mw(handler, _make_message(111), {})
    assert result == "ok"
    handler.assert_awaited_once()


async def test_banned_user_message_blocked_and_notified(db, monkeypatch):
    await db.get_or_create_user(111, "u", "U", "en")
    future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)).isoformat()
    await db._db_connection.execute(
        "UPDATE users SET banned_bot_until = ? WHERE telegram_id = ?", (future, 111)
    )
    await db._db_connection.commit()

    reply_mock = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "reply", reply_mock)

    mw = BanCheckMiddleware()
    handler = AsyncMock(return_value="ok")

    result = await mw(handler, _make_message(111), {})

    assert result is None
    handler.assert_not_awaited()
    reply_mock.assert_awaited_once()


async def test_banned_user_repeat_message_within_cooldown_is_silent(db, monkeypatch):
    await db.get_or_create_user(111, "u", "U", "en")
    future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)).isoformat()
    await db._db_connection.execute(
        "UPDATE users SET banned_bot_until = ? WHERE telegram_id = ?", (future, 111)
    )
    await db._db_connection.commit()

    reply_mock = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "reply", reply_mock)

    mw = BanCheckMiddleware()
    handler = AsyncMock(return_value="ok")

    await mw(handler, _make_message(111), {})
    await mw(handler, _make_message(111), {})

    handler.assert_not_awaited()
    reply_mock.assert_awaited_once()  # second attempt suppressed by the notification cooldown


async def test_expired_ban_does_not_block(db):
    await db.get_or_create_user(111, "u", "U", "en")
    past = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)).isoformat()
    await db._db_connection.execute(
        "UPDATE users SET banned_bot_until = ? WHERE telegram_id = ?", (past, 111)
    )
    await db._db_connection.commit()

    mw = BanCheckMiddleware()
    handler = AsyncMock(return_value="ok")

    result = await mw(handler, _make_message(111), {})
    assert result == "ok"
    handler.assert_awaited_once()


async def test_banned_callback_query_answered_with_alert(db, monkeypatch):
    await db.get_or_create_user(111, "u", "U", "en")
    future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)).isoformat()
    await db._db_connection.execute(
        "UPDATE users SET banned_bot_until = ? WHERE telegram_id = ?", (future, 111)
    )
    await db._db_connection.commit()

    answer_mock = AsyncMock()
    monkeypatch.setattr(_FakeCallbackQuery, "answer", answer_mock)

    mw = BanCheckMiddleware()
    handler = AsyncMock(return_value="ok")

    result = await mw(handler, _make_callback(111), {})

    assert result is None
    handler.assert_not_awaited()
    answer_mock.assert_awaited_once()
    _, kwargs = answer_mock.call_args
    assert kwargs.get("show_alert") is True


async def test_support_ban_alone_does_not_block_bot_usage(db):
    # banned_support_until only restricts the /help flow (checked in handlers/user.py),
    # not general bot usage - the middleware itself must not react to it.
    await db.get_or_create_user(111, "u", "U", "en")
    future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)).isoformat()
    await db._db_connection.execute(
        "UPDATE users SET banned_support_until = ? WHERE telegram_id = ?", (future, 111)
    )
    await db._db_connection.commit()

    mw = BanCheckMiddleware()
    handler = AsyncMock(return_value="ok")

    result = await mw(handler, _make_message(111), {})
    assert result == "ok"
    handler.assert_awaited_once()
