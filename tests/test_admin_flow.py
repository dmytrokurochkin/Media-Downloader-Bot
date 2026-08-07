from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey

import handlers.admin as admin_module
from handlers.admin import (
    admin_command,
    process_give_vip,
    process_remove_vip,
    process_ban_bot,
    is_admin,
)

ADMIN_ID = 5000
NON_ADMIN_ID = 6000


class _FakeMessage(Message):
    pass


def _make_fsm_context(user_id):
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=user_id, user_id=user_id)
    return FSMContext(storage=storage, key=key)


def _make_message(user_id, text=None, **extra):
    return _FakeMessage.model_construct(
        from_user=SimpleNamespace(id=user_id, username="u", full_name="U"),
        chat=SimpleNamespace(id=user_id, type="private"),
        message_id=1,
        text=text,
        **extra,
    )


@pytest.fixture(autouse=True)
def _admin_ids(monkeypatch):
    monkeypatch.setattr(admin_module, "ADMIN_IDS", [ADMIN_ID])


def test_is_admin_reflects_configured_ids():
    assert is_admin(ADMIN_ID) is True
    assert is_admin(NON_ADMIN_ID) is False


async def test_admin_command_blocks_non_admin(db, monkeypatch):
    await db.get_or_create_user(NON_ADMIN_ID, "u", "U", "en")
    reply_mock = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "reply", reply_mock)

    state = _make_fsm_context(NON_ADMIN_ID)
    await admin_command(_make_message(NON_ADMIN_ID), state)

    reply_mock.assert_not_awaited()


async def test_admin_command_allows_admin(db, monkeypatch):
    await db.get_or_create_user(ADMIN_ID, "u", "U", "en")
    reply_mock = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "reply", reply_mock)

    state = _make_fsm_context(ADMIN_ID)
    await admin_command(_make_message(ADMIN_ID), state)

    reply_mock.assert_awaited_once()


async def test_process_give_vip_grants_requested_tier(db, monkeypatch):
    await db.get_or_create_user(ADMIN_ID, "u", "U", "en")
    await db.get_or_create_user(111, "target", "Target", "en")

    reply_mock = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "reply", reply_mock)
    monkeypatch.setattr("handlers.admin.bot.send_message", AsyncMock())

    message = _make_message(ADMIN_ID, text="111 30 pro")
    state = _make_fsm_context(ADMIN_ID)
    await process_give_vip(message, state)

    target = await db.get_or_create_user(111, "target", "Target", "en")
    assert target["tier"] == "pro"
    assert target["is_vip"] == 1


async def test_process_give_vip_invalid_id_shows_error(db, monkeypatch):
    await db.get_or_create_user(ADMIN_ID, "u", "U", "en")
    reply_mock = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "reply", reply_mock)

    message = _make_message(ADMIN_ID, text="not-a-number 30")
    state = _make_fsm_context(ADMIN_ID)
    await process_give_vip(message, state)

    reply_mock.assert_awaited_once()
    args, kwargs = reply_mock.call_args
    assert "numbers" in args[0]


async def test_process_give_vip_unknown_user_shows_not_found(db, monkeypatch):
    await db.get_or_create_user(ADMIN_ID, "u", "U", "en")
    reply_mock = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "reply", reply_mock)

    message = _make_message(ADMIN_ID, text="999999999 30 pro")
    state = _make_fsm_context(ADMIN_ID)
    await process_give_vip(message, state)

    reply_mock.assert_awaited_once()


async def test_process_give_vip_invalid_tier_falls_back_to_max(db, monkeypatch):
    await db.get_or_create_user(ADMIN_ID, "u", "U", "en")
    await db.get_or_create_user(111, "target", "Target", "en")

    monkeypatch.setattr(_FakeMessage, "reply", AsyncMock())
    monkeypatch.setattr("handlers.admin.bot.send_message", AsyncMock())

    message = _make_message(ADMIN_ID, text="111 30 legendary")
    state = _make_fsm_context(ADMIN_ID)
    await process_give_vip(message, state)

    target = await db.get_or_create_user(111, "target", "Target", "en")
    assert target["tier"] == "max"


async def test_process_remove_vip_revokes(db, monkeypatch):
    await db.get_or_create_user(ADMIN_ID, "u", "U", "en")
    await db.get_or_create_user(111, "target", "Target", "en")
    await db.grant_vip(111, 30, tier="max")

    monkeypatch.setattr(_FakeMessage, "reply", AsyncMock())

    message = _make_message(ADMIN_ID, text="111")
    state = _make_fsm_context(ADMIN_ID)
    await process_remove_vip(message, state)

    target = await db.get_or_create_user(111, "target", "Target", "en")
    assert target["tier"] == "free"
    assert target["is_vip"] == 0


async def test_process_ban_bot_temporary(db, monkeypatch):
    await db.get_or_create_user(ADMIN_ID, "u", "U", "en")
    await db.get_or_create_user(111, "target", "Target", "en")

    monkeypatch.setattr(_FakeMessage, "reply", AsyncMock())

    message = _make_message(ADMIN_ID, text="111 7")
    state = _make_fsm_context(ADMIN_ID)
    await process_ban_bot(message, state)

    target = await db.get_or_create_user(111, "target", "Target", "en")
    assert target["banned_bot_until"] is not None
    assert not target["banned_bot_until"].startswith("9999")


async def test_process_ban_bot_permanent_without_days(db, monkeypatch):
    await db.get_or_create_user(ADMIN_ID, "u", "U", "en")
    await db.get_or_create_user(111, "target", "Target", "en")

    monkeypatch.setattr(_FakeMessage, "reply", AsyncMock())

    message = _make_message(ADMIN_ID, text="111")
    state = _make_fsm_context(ADMIN_ID)
    await process_ban_bot(message, state)

    target = await db.get_or_create_user(111, "target", "Target", "en")
    assert target["banned_bot_until"].startswith("9999")
