from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import CallbackQuery, Message

import handlers.media as media
from locales import get_text


class _FakeMessage(Message):
    pass


class _FakeCallback(CallbackQuery):
    pass


def _make_message(user_id, text=None, chat_type="private", **extra):
    return _FakeMessage.model_construct(
        from_user=SimpleNamespace(id=user_id, username="u", full_name="U"),
        chat=SimpleNamespace(id=user_id, type=chat_type),
        message_id=1,
        text=text,
        **extra,
    )


def _make_fsm_context(user_id):
    return FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=user_id, user_id=user_id))


@pytest.fixture(autouse=True)
def _bot_identity(monkeypatch):
    monkeypatch.setattr(media.bot, "me", AsyncMock(return_value=SimpleNamespace(username="TestBot")))
    monkeypatch.setattr(media, "user_cooldowns", set())
    monkeypatch.setattr(media, "schedule_delete", lambda *a, **k: None)


# --- text_handler ---

async def test_text_handler_strips_bot_mention_and_clears_state(db, monkeypatch):
    process = AsyncMock()
    monkeypatch.setattr(media, "process_url", process)
    state = _make_fsm_context(111)
    await state.set_state(media.AudioEditorState.waiting_for_cover)

    await media.text_handler(_make_message(111, text="https://youtu.be/abc@TestBot"), state)

    assert process.await_args.args[1] == "https://youtu.be/abc"
    # Тег бота більше не вмикає «гостьовий режим» для звичайного повідомлення.
    assert process.await_args.kwargs.get("is_guest_mode", False) is False
    assert await state.get_state() is None


async def test_text_handler_takes_url_from_replied_message_when_bot_is_mentioned(db, monkeypatch):
    process = AsyncMock()
    monkeypatch.setattr(media, "process_url", process)
    replied = _make_message(222, text="глянь https://www.tiktok.com/@x/video/1")

    await media.text_handler(
        _make_message(111, text="@TestBot", chat_type="supergroup", reply_to_message=replied),
        _make_fsm_context(111),
    )

    assert process.await_args.args[1] == "https://www.tiktok.com/@x/video/1"


async def test_text_handler_ignores_text_without_links(db, monkeypatch):
    process = AsyncMock()
    monkeypatch.setattr(media, "process_url", process)
    state = _make_fsm_context(111)
    await state.set_state(media.AudioEditorState.waiting_for_cover)

    await media.text_handler(_make_message(111, text="привіт"), state)

    process.assert_not_awaited()
    assert await state.get_state() == media.AudioEditorState.waiting_for_cover.state


# --- process_url / формати ---

def test_youtube_format_and_tier_quality():
    assert media.youtube_format("audio") == "bestaudio/best"
    assert "height<=720" in media.youtube_format(media.quality_for_tier("free"))
    assert "height<=1080" in media.youtube_format(media.quality_for_tier("pro"))
    assert "height" not in media.youtube_format(media.quality_for_tier("max"))
    # Без жорсткої вимоги mp4/m4a: інакше ролики лише з webm-форматами падали.
    assert media.youtube_format("720p").endswith("/best")


async def test_drm_services_are_refused_before_download(db, monkeypatch):
    user = await db.get_or_create_user(111, "u", "U", "en")
    assert await media.get_download_block_reason(user, "https://music.apple.com/us/album/x/1") == "service_not_supported"
    assert await media.get_download_block_reason(user, "https://www.deezer.com/track/1") == "service_not_supported"
    assert await media.get_download_block_reason(user, "https://open.spotify.com/track/1") is None


async def test_youtube_quality_menu_not_shown_when_blocked(db, monkeypatch):
    user = await db.get_or_create_user(111, "u", "U", "en")
    for _ in range(25):
        await db.add_download_record(111, "https://youtu.be/x", "youtu.be", "", 1, True)
    reply = AsyncMock(return_value=SimpleNamespace(chat=SimpleNamespace(id=111), message_id=2))
    monkeypatch.setattr(_FakeMessage, "reply", reply)

    await media.process_url(_make_message(111, text="https://youtu.be/abc"), "https://youtu.be/abc", user)

    assert reply.await_args.args[0] == get_text("en", "limit_reached")
    assert reply.await_args.kwargs.get("reply_markup") is None


async def test_youtube_quality_menu_escapes_url(db, monkeypatch):
    user = await db.get_or_create_user(111, "u", "U", "en")
    reply = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "reply", reply)
    url = "https://www.youtube.com/watch?v=abc&list=<x>"

    await media.process_url(_make_message(111, text=url), url, user)

    assert "&amp;list=&lt;x&gt;" in reply.await_args.args[0]


# --- youtube_callback ---

def _make_callback(user_id, data, message):
    return _FakeCallback.model_construct(
        id="cb", from_user=SimpleNamespace(id=user_id, username="u", full_name="U"), data=data, message=message,
    )


async def test_youtube_callback_on_inaccessible_message_does_nothing(db, monkeypatch):
    monkeypatch.setattr(_FakeCallback, "answer", AsyncMock())
    download = AsyncMock()
    monkeypatch.setattr(media, "start_download", download)
    # Повідомлення старше 48 год приходить як InaccessibleMessage — без text.
    old_message = SimpleNamespace(chat=SimpleNamespace(id=111), message_id=1, date=0)

    await media.youtube_callback(_make_callback(111, "yt_720", old_message), _make_fsm_context(111))

    download.assert_not_awaited()


async def test_youtube_callback_enforces_tier_quality(db, monkeypatch):
    await db.get_or_create_user(111, "u", "U", "en")
    monkeypatch.setattr(_FakeCallback, "answer", AsyncMock())
    reply = AsyncMock(return_value=SimpleNamespace(chat=SimpleNamespace(id=111), message_id=3))
    monkeypatch.setattr(_FakeMessage, "reply", reply)
    download = AsyncMock()
    monkeypatch.setattr(media, "start_download", download)
    menu = _make_message(111, text="Choose quality\n🔗 https://youtu.be/abc")

    await media.youtube_callback(_make_callback(111, "yt_1080", menu), _make_fsm_context(111))
    download.assert_not_awaited()
    assert reply.await_args.args[0] == get_text("en", "quality_limit")

    monkeypatch.setattr(media, "_safe_edit", AsyncMock())
    await media.youtube_callback(_make_callback(111, "yt_720", menu), _make_fsm_context(111))
    assert download.await_args.args[1] == "https://youtu.be/abc"
    assert download.await_args.args[2] == media.youtube_format("720p")


# --- PDF ---

async def test_pdf_url_step_survives_non_text_message(db, monkeypatch):
    await db.get_or_create_user(111, "u", "U", "en")
    reply = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "reply", reply)
    state = _make_fsm_context(111)
    await state.set_state(media.PdfState.waiting_for_pdf_url)

    await media.process_pdf_url(_make_message(111, text=None, photo=[object()]), state)

    assert reply.await_args.args[0] == get_text("en", "pdf_invalid_url")
    assert await state.get_state() == media.PdfState.waiting_for_pdf_url.state
