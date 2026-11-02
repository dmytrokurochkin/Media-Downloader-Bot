from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message

import handlers.media as media
import handlers.user as user_module
from handlers.payment import paysupport_command
from handlers.user import (
    SupportState,
    help_command,
    language_callback,
    onboarding_test_dl_handler,
    process_support_message,
    set_yt_quality_callback,
    support_ban_text,
    top_command,
)
from locales import get_text

ADMIN_ID = 5000


class _FakeMessage(Message):
    pass


class _FakeCallback(CallbackQuery):
    pass


def _make_message(user_id, text=None, **extra):
    return _FakeMessage.model_construct(
        from_user=SimpleNamespace(id=user_id, username="u", full_name="U <script>"),
        chat=SimpleNamespace(id=user_id, type="private"),
        message_id=7,
        text=text,
        **extra,
    )


def _make_callback(user_id, data, message=None):
    return _FakeCallback.model_construct(
        id="cb-1",
        from_user=SimpleNamespace(id=user_id, username="u", full_name="U"),
        data=data,
        message=message or _make_message(user_id, text="..."),
    )


def _make_fsm_context(user_id):
    return FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=user_id, user_id=user_id))


def _fake_bot():
    return SimpleNamespace(send_message=AsyncMock(), copy_message=AsyncMock())


@pytest.fixture(autouse=True)
def _admins(monkeypatch):
    monkeypatch.setattr(user_module, "ADMIN_IDS", [ADMIN_ID])
    monkeypatch.setattr(user_module, "schedule_delete", lambda *a, **k: None)


# --- підтримка ---

def test_support_filter_lets_non_text_messages_through():
    # Фото без тексту має потрапляти в хендлер підтримки (і не валити його).
    support_filter = ~F.text.startswith('http')
    assert support_filter.resolve(_make_message(1, text=None)) is True
    assert support_filter.resolve(_make_message(1, text="https://youtu.be/x")) is False


async def test_support_photo_is_copied_to_admins(db, monkeypatch):
    await db.get_or_create_user(111, "u", "U", "en")
    reply = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "reply", reply)
    bot = _fake_bot()

    await process_support_message(_make_message(111, text=None, photo=[object()]), _make_fsm_context(111), bot)

    header = bot.send_message.await_args.args[1]
    assert "U &lt;script&gt;" in header
    bot.copy_message.assert_awaited_once_with(ADMIN_ID, from_chat_id=111, message_id=7)
    assert reply.await_args.args[0] == get_text("en", "support_sent")


async def test_support_text_is_escaped_and_not_copied(db, monkeypatch):
    await db.get_or_create_user(111, "u", "U", "en")
    monkeypatch.setattr(_FakeMessage, "reply", AsyncMock())
    bot = _fake_bot()

    await process_support_message(_make_message(111, text="<b>help</b>"), _make_fsm_context(111), bot)

    assert "&lt;b&gt;help&lt;/b&gt;" in bot.send_message.await_args.args[1]
    bot.copy_message.assert_not_awaited()


async def test_support_long_text_is_copied_instead_of_inlined(db, monkeypatch):
    await db.get_or_create_user(111, "u", "U", "en")
    monkeypatch.setattr(_FakeMessage, "reply", AsyncMock())
    bot = _fake_bot()

    await process_support_message(_make_message(111, text="x" * 4000), _make_fsm_context(111), bot)

    assert len(bot.send_message.await_args.args[1]) < 4096
    bot.copy_message.assert_awaited_once()


async def test_support_menu_button_cancels_input(db, monkeypatch):
    await db.get_or_create_user(111, "u", "U", "uk")
    reply = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "reply", reply)
    bot = _fake_bot()
    state = _make_fsm_context(111)
    await state.set_state(SupportState.waiting_for_message)

    await process_support_message(_make_message(111, text=get_text("en", "menu_profile")), state, bot)

    bot.send_message.assert_not_awaited()
    assert await state.get_state() is None
    assert reply.await_args.args[0] == get_text("uk", "input_cancelled")


async def test_support_reports_when_no_admin_received_message(db, monkeypatch):
    from aiogram.exceptions import TelegramForbiddenError
    await db.get_or_create_user(111, "u", "U", "en")
    reply = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "reply", reply)
    bot = _fake_bot()
    bot.send_message.side_effect = TelegramForbiddenError(method=None, message="blocked")

    await process_support_message(_make_message(111, text="hi"), _make_fsm_context(111), bot)

    assert reply.await_args.args[0] == get_text("en", "support_unavailable")


async def test_paysupport_marks_topic_for_admins(db, monkeypatch):
    await db.get_or_create_user(111, "u", "U", "en")
    monkeypatch.setattr(_FakeMessage, "reply", AsyncMock())
    state = _make_fsm_context(111)

    await paysupport_command(_make_message(111, text="/paysupport"), state)
    assert await state.get_state() == SupportState.waiting_for_message.state

    bot = _fake_bot()
    await process_support_message(_make_message(111, text="where is my VIP?"), state, bot)
    assert "/paysupport" in bot.send_message.await_args.args[1]
    assert await state.get_state() is None


async def test_support_ban_blocks_help_and_paysupport(db, monkeypatch):
    await db.get_or_create_user(111, "u", "U", "en")
    await db.ban_user_support(111, None)
    user = await db.get_user(111)
    assert get_text("en", "forever_label") in support_ban_text(user)

    reply = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "reply", reply)
    state = _make_fsm_context(111)

    await help_command(_make_message(111, text="/help"), state)
    assert await state.get_state() is None

    await paysupport_command(_make_message(111, text="/paysupport"), state)
    assert await state.get_state() is None
    assert get_text("en", "forever_label") in reply.await_args.args[0]


def test_support_ban_text_ignores_expired_or_broken_dates():
    assert support_ban_text({"telegram_id": 1, "language_code": "en", "banned_support_until": None}) is None
    assert support_ban_text({"telegram_id": 1, "language_code": "en", "banned_support_until": "2000-01-01T00:00:00"}) is None
    assert support_ban_text({"telegram_id": 1, "language_code": "en", "banned_support_until": "garbage"}) is None


# --- /top ---

async def test_top_command_escapes_names_and_merges_domains(db, monkeypatch):
    await db.get_or_create_user(111, "u", "Evil [*_` <b>", "en")
    for domain in ("youtube.com", "m.youtube.com", "youtu.be"):
        await db.add_download_record(111, f"https://{domain}/x", domain, "", 1, True)
    reply = AsyncMock(return_value=SimpleNamespace(chat=SimpleNamespace(id=222), message_id=8))
    monkeypatch.setattr(_FakeMessage, "reply", reply)

    await top_command(_make_message(222, text="/top"), _make_fsm_context(222))

    text = reply.await_args.args[0]
    # HTML (parse_mode за замовчуванням), а не Markdown: спецсимволи в імені не ламають розмітку.
    assert "parse_mode" not in reply.await_args.kwargs
    assert "Evil [*_` &lt;b&gt;" in text
    assert "YouTube — 3" in text
    assert "m.youtube.com" not in text


# --- онбординг і налаштування ---

async def test_onboarding_success_only_after_successful_download(db, monkeypatch):
    await db.get_or_create_user(111, "u", "U", "en")
    monkeypatch.setattr(_FakeCallback, "answer", AsyncMock())
    monkeypatch.setattr(_FakeMessage, "edit_text", AsyncMock())
    answer = AsyncMock(return_value=SimpleNamespace(chat=SimpleNamespace(id=111), message_id=9))
    monkeypatch.setattr(_FakeMessage, "answer", answer)
    monkeypatch.setattr(user_module, "webapp_url_for", AsyncMock(return_value="https://example.com/app"))

    monkeypatch.setattr(media, "start_download", AsyncMock(return_value=False))
    await onboarding_test_dl_handler(_make_callback(111, "onboarding_test_dl"), _make_fsm_context(111))
    answer.assert_not_awaited()

    monkeypatch.setattr(media, "start_download", AsyncMock(return_value=True))
    await onboarding_test_dl_handler(_make_callback(111, "onboarding_test_dl"), _make_fsm_context(111))
    assert answer.await_args.args[0] == get_text("en", "onboarding_success")
    # Reply-клавіатура з Mini App: лише з неї працює sendData (збереження налаштувань).
    keyboard = answer.await_args.kwargs["reply_markup"]
    assert any(button.web_app for row in keyboard.keyboard for button in row)


async def test_language_callback_ignores_unknown_language(db, monkeypatch):
    await db.get_or_create_user(111, "u", "U", "en")
    monkeypatch.setattr(_FakeCallback, "answer", AsyncMock())

    await language_callback(_make_callback(111, "lang_ru"))

    assert (await db.get_user(111))["language_code"] == "en"


async def test_set_yt_quality_ignores_unknown_quality(db, monkeypatch):
    await db.get_or_create_user(111, "u", "U", "en")
    answer = AsyncMock()
    monkeypatch.setattr(_FakeCallback, "answer", answer)

    await set_yt_quality_callback(_make_callback(111, "setyt_8k"))

    assert (await db.get_user(111))["guest_yt_quality"] == "best"
    answer.assert_awaited_once()


async def test_command_in_document_caption_cancels_support_input(db, monkeypatch):
    # Адмін у стані «звернення» надсилає файл кук із підписом /cookies — це команда,
    # а не звернення: файл не повинен піти іншим адмінам.
    await db.get_or_create_user(111, "u", "U", "en")
    monkeypatch.setattr(_FakeMessage, "reply", AsyncMock(return_value=SimpleNamespace(chat=SimpleNamespace(id=111), message_id=9)))
    bot = _fake_bot()
    state = _make_fsm_context(111)
    await state.set_state(SupportState.waiting_for_message)

    message = _make_message(111, text=None, caption="/cookies", document=SimpleNamespace(file_id="F"))
    await process_support_message(message, state, bot)

    bot.send_message.assert_not_awaited()
    bot.copy_message.assert_not_awaited()
    assert await state.get_state() is None
