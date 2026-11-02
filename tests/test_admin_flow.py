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
    process_reply,
    process_unban,
    is_admin,
)
from locales import get_text

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


@pytest.mark.parametrize("tier", ["legendary", "por", "free"])
async def test_process_give_vip_rejects_unknown_tier(db, monkeypatch, tier):
    # Раніше невідомий рівень мовчки ставав 'max' (опечатка «por» = подарунок MAX),
    # а 'free' видавав «VIP Free».
    await db.get_or_create_user(ADMIN_ID, "u", "U", "en")
    await db.get_or_create_user(111, "target", "Target", "en")

    reply_mock = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "reply", reply_mock)
    send_mock = AsyncMock()
    monkeypatch.setattr("handlers.admin.bot.send_message", send_mock)

    message = _make_message(ADMIN_ID, text=f"111 30 {tier}")
    state = _make_fsm_context(ADMIN_ID)
    await process_give_vip(message, state)

    target = await db.get_user(111)
    assert target["tier"] == "free"
    assert not target["is_vip"]
    assert reply_mock.call_args.args[0] == get_text("en", "admin_err_tier")
    send_mock.assert_not_awaited()


@pytest.mark.parametrize("days", ["0", "-30", "999999"])
async def test_process_give_vip_rejects_days_out_of_range(db, monkeypatch, days):
    await db.get_or_create_user(ADMIN_ID, "u", "U", "en")
    await db.get_or_create_user(111, "target", "Target", "en")

    reply_mock = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "reply", reply_mock)

    await process_give_vip(_make_message(ADMIN_ID, text=f"111 {days} pro"), _make_fsm_context(ADMIN_ID))

    assert (await db.get_user(111))["tier"] == "free"
    assert reply_mock.call_args.args[0] == get_text("en", "admin_err_days_range", max_days=admin_module.MAX_ADMIN_DAYS)


async def test_process_give_vip_unknown_user_is_not_created(db, monkeypatch):
    await db.get_or_create_user(ADMIN_ID, "u", "U", "en")
    reply_mock = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "reply", reply_mock)

    await process_give_vip(_make_message(ADMIN_ID, text="999999999 30 pro"), _make_fsm_context(ADMIN_ID))

    assert await db.get_user(999999999) is None
    assert reply_mock.call_args.args[0] == get_text("en", "admin_err_not_found")


@pytest.mark.parametrize("handler", [process_give_vip, process_remove_vip, process_ban_bot, process_reply, process_unban])
async def test_admin_state_handlers_survive_non_text_messages(db, monkeypatch, handler):
    # Адмін надіслав фото/стікер у кроці «введіть ID» — раніше message.text.split() падав.
    await db.get_or_create_user(ADMIN_ID, "u", "U", "en")
    reply_mock = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "reply", reply_mock)

    await handler(_make_message(ADMIN_ID, text=None), _make_fsm_context(ADMIN_ID))

    reply_mock.assert_awaited_once()


async def test_process_reply_unknown_user_is_not_created(db, monkeypatch):
    await db.get_or_create_user(ADMIN_ID, "u", "U", "en")
    reply_mock = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "reply", reply_mock)
    send_mock = AsyncMock()
    monkeypatch.setattr("handlers.admin.bot.send_message", send_mock)

    await process_reply(_make_message(ADMIN_ID, text="424242 hello"), _make_fsm_context(ADMIN_ID))

    assert await db.get_user(424242) is None
    send_mock.assert_not_awaited()
    assert reply_mock.call_args.args[0] == get_text("en", "admin_err_not_found")


async def test_process_reply_escapes_text_and_reports_send_errors(db, monkeypatch):
    from aiogram.exceptions import TelegramForbiddenError
    await db.get_or_create_user(ADMIN_ID, "u", "U", "en")
    await db.get_or_create_user(111, "target", "Target", "en")
    reply_mock = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "reply", reply_mock)
    send_mock = AsyncMock(side_effect=TelegramForbiddenError(method=None, message="bot was blocked <by> the user"))
    monkeypatch.setattr("handlers.admin.bot.send_message", send_mock)

    state = _make_fsm_context(ADMIN_ID)
    await state.set_state(admin_module.AdminState.waiting_for_reply)
    await process_reply(_make_message(ADMIN_ID, text="111 <b>hi</b>"), state)

    sent_text = send_mock.call_args.args[1]
    assert "&lt;b&gt;hi&lt;/b&gt;" in sent_text
    error_reply = reply_mock.call_args.args[0]
    assert "&lt;by&gt;" in error_reply
    # Відправка не вдалась — стан лишається, адмін може виправити й надіслати ще раз.
    assert await state.get_state() == admin_module.AdminState.waiting_for_reply.state


async def test_process_ban_unknown_user_reports_not_found(db, monkeypatch):
    await db.get_or_create_user(ADMIN_ID, "u", "U", "en")
    reply_mock = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "reply", reply_mock)

    await process_ban_bot(_make_message(ADMIN_ID, text="777 3"), _make_fsm_context(ADMIN_ID))

    assert await db.get_user(777) is None
    assert reply_mock.call_args.args[0] == get_text("en", "admin_err_not_found")


async def test_admin_state_handlers_ignore_admin_menu_buttons():
    # Кнопка іншого розділу посеред введення не повинна стати текстом розсилки/відповіді.
    button = _make_message(ADMIN_ID, text=get_text("uk", "admin_btn_reply"))
    plain = _make_message(ADMIN_ID, text="111 30 pro")
    photo = _make_message(ADMIN_ID, text=None)
    assert admin_module.NOT_ADMIN_BUTTON.resolve(button) is False
    assert admin_module.NOT_ADMIN_BUTTON.resolve(plain) is True
    assert admin_module.NOT_ADMIN_BUTTON.resolve(photo) is True


async def test_run_broadcast_counts_blocked_and_retries_after_flood_limit(monkeypatch):
    from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

    outcomes = {
        1: [None],
        2: [TelegramRetryAfter(method=None, message="flood", retry_after=0), None],
        3: [TelegramForbiddenError(method=None, message="blocked")],
        4: [TelegramBadRequest(method=None, message="chat not found")],
    }
    calls = []

    async def fake_copy(chat_id, **kwargs):
        calls.append(chat_id)
        result = outcomes[chat_id].pop(0)
        if isinstance(result, Exception):
            raise result

    async def no_sleep(_):
        return None

    monkeypatch.setattr("handlers.admin.bot.copy_message", fake_copy)
    monkeypatch.setattr(admin_module.asyncio, "sleep", no_sleep)

    stats = await admin_module.run_broadcast([1, 2, 3, 4], from_chat_id=ADMIN_ID, message_id=10)

    assert stats == {"sent": 2, "blocked": 1, "failed": 1}
    assert calls == [1, 2, 2, 3, 4]


def test_parse_id_and_days():
    assert admin_module.parse_id_and_days("111 7", days_required=False) == (111, 7)
    assert admin_module.parse_id_and_days("111", days_required=False) == (111, None)
    with pytest.raises(ValueError, match="format"):
        admin_module.parse_id_and_days("111", days_required=True)
    with pytest.raises(ValueError, match="days"):
        admin_module.parse_id_and_days("111 0", days_required=False)
    with pytest.raises(ValueError):
        admin_module.parse_id_and_days(None, days_required=False)


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
