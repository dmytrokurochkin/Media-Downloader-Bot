import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey

from handlers.user import web_app_data_handler, watermark_photo_handler, WatermarkState


class _FakeMessage(Message):
    pass


def _make_fsm_context(user_id):
    storage = MemoryStorage()
    key = StorageKey(bot_id=1, chat_id=user_id, user_id=user_id)
    return FSMContext(storage=storage, key=key)


def _make_message(user_id, **extra):
    return _FakeMessage.model_construct(
        from_user=SimpleNamespace(id=user_id, username="u", full_name="U"),
        chat=SimpleNamespace(id=user_id, type="private"),
        message_id=1,
        **extra,
    )


# --- database layer ---

async def test_set_watermark_file_id_persists(db):
    await db.get_or_create_user(111, "u", "U", "en")
    await db.set_watermark_file_id(111, "AgAC123")
    user = await db.get_or_create_user(111, "u", "U", "en")
    assert user["watermark_file_id"] == "AgAC123"


# --- web_app_data_handler gating ---

async def test_save_settings_max_tier_enters_waiting_for_photo_state(db, monkeypatch):
    await db.get_or_create_user(111, "u", "U", "en")
    await db.grant_vip(111, 7, tier="max")

    answer_mock = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "answer", answer_mock)

    payload = {
        "action": "save_settings",
        "language": "en",
        "default_quality": "best",
        "is_anonymous": 0,
        "theme": "standard",
        "watermark_position": "bottom_right",
        "watermark_updated": True,
    }
    message = _make_message(111, web_app_data=SimpleNamespace(data=json.dumps(payload)))
    state = _make_fsm_context(111)

    await web_app_data_handler(message, state)

    current_state = await state.get_state()
    assert current_state == WatermarkState.waiting_for_photo.state


async def test_save_settings_non_max_tier_does_not_enter_watermark_state(db, monkeypatch):
    await db.get_or_create_user(111, "u", "U", "en")  # free tier by default

    answer_mock = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "answer", answer_mock)

    payload = {
        "action": "save_settings",
        "language": "en",
        "default_quality": "best",
        "is_anonymous": 0,
        "theme": "standard",
        "watermark_position": "bottom_right",
        "watermark_updated": True,
    }
    message = _make_message(111, web_app_data=SimpleNamespace(data=json.dumps(payload)))
    state = _make_fsm_context(111)

    await web_app_data_handler(message, state)

    current_state = await state.get_state()
    assert current_state is None


# --- watermark_photo_handler ---

async def test_watermark_photo_handler_saves_file_id_from_photo(db, monkeypatch):
    await db.get_or_create_user(111, "u", "U", "en")
    await db.grant_vip(111, 7, tier="max")

    answer_mock = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "answer", answer_mock)

    photo_sizes = [SimpleNamespace(file_id="small"), SimpleNamespace(file_id="large_file_id")]
    message = _make_message(111, photo=photo_sizes, document=None)
    state = _make_fsm_context(111)
    await state.set_state(WatermarkState.waiting_for_photo)

    await watermark_photo_handler(message, state)

    user = await db.get_or_create_user(111, "u", "U", "en")
    assert user["watermark_file_id"] == "large_file_id"
    assert await state.get_state() is None
    answer_mock.assert_awaited_once()


async def test_watermark_photo_handler_accepts_image_document(db, monkeypatch):
    await db.get_or_create_user(111, "u", "U", "en")

    answer_mock = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "answer", answer_mock)

    document = SimpleNamespace(file_id="doc_file_id", mime_type="image/png")
    message = _make_message(111, photo=None, document=document)
    state = _make_fsm_context(111)

    await watermark_photo_handler(message, state)

    user = await db.get_or_create_user(111, "u", "U", "en")
    assert user["watermark_file_id"] == "doc_file_id"


async def test_watermark_photo_handler_rejects_non_image(db, monkeypatch):
    await db.get_or_create_user(111, "u", "U", "en")

    answer_mock = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "answer", answer_mock)

    document = SimpleNamespace(file_id="doc_file_id", mime_type="application/pdf")
    message = _make_message(111, photo=None, document=document)
    state = _make_fsm_context(111)

    await watermark_photo_handler(message, state)

    user = await db.get_or_create_user(111, "u", "U", "en")
    assert user["watermark_file_id"] is None
