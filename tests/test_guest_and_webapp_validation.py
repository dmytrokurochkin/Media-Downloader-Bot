import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message
from pydantic import ValidationError

import handlers.media as media
import middlewares.ban as ban_module
from core.webapp_data import normalize_guest_quality, parse_webapp_payload
from handlers.user import web_app_data_handler
from middlewares.ban import BanCheckMiddleware
from middlewares.throttling import ThrottlingMiddleware


class _FakeMessage(Message):
    pass


BOT_USER = SimpleNamespace(id=999, username="TestBot", full_name="Test Bot")


def _make_message(user_id, **extra):
    return _FakeMessage.model_construct(
        from_user=SimpleNamespace(id=user_id, username="u", full_name="U"),
        chat=SimpleNamespace(id=user_id, type="private"),
        message_id=1,
        **extra,
    )


def _make_guest_message(caller_id):
    # У guest_message from_user — сам бот, справжній відправник — guest_bot_caller_user.
    return _FakeMessage.model_construct(
        from_user=BOT_USER,
        guest_bot_caller_user=SimpleNamespace(id=caller_id, username="caller", full_name="Caller"),
        guest_query_id="guest-query-1",
        chat=SimpleNamespace(id=caller_id, type="private"),
        message_id=1,
    )


def _make_fsm_context(user_id):
    return FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=user_id, user_id=user_id))


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    monkeypatch.setattr(media, "user_cooldowns", set())
    monkeypatch.setattr(ban_module, "BANNED_NOTIFIED_CACHE", {})
    monkeypatch.setattr(ban_module, "LAST_ACTIVE_CACHE", {})


# --- схема web_app_data ---

@pytest.mark.parametrize("payload", [
    {"action": "save_settings", "default_quality": "4k"},
    {"action": "save_settings", "language": "ru"},
    {"action": "smart_trim", "url": "https://youtu.be/x", "start_sec": 100, "end_sec": 50},
    {"action": "smart_trim", "url": "https://youtu.be/x", "start_sec": -5, "end_sec": 5},
    {"action": "smart_trim", "url": "https://youtu.be/x", "start_sec": "zero", "end_sec": 5},
    {"action": "smart_trim", "url": "--exec=id instagram.com", "start_sec": 0, "end_sec": 5},
    {"action": "edit_tags", "url": "-i/etc/passwd spotify.com"},
    {"action": "buy_theme", "theme": "standard"},
    {"action": "drop_tables"},
])
def test_forged_payloads_are_rejected(payload):
    with pytest.raises(ValidationError):
        parse_webapp_payload(json.dumps(payload))


def test_valid_trim_payload_exposes_duration():
    payload = parse_webapp_payload(json.dumps(
        {"action": "smart_trim", "url": "https://youtu.be/x", "start_sec": 10, "end_sec": 40, "start": "0:10"}
    ))
    assert payload.duration == 30


@pytest.mark.parametrize("quality,tier,expected", [
    ("xyz", "free", "720p"),      # невідоме значення більше не дає «best»
    (None, "free", "720p"),
    ("best", "free", "720p"),
    ("1080p", "free", "720p"),
    ("best", "pro", "1080p"),
    ("best", "max", "best"),
    ("audio", "free", "audio"),
])
def test_normalize_guest_quality(quality, tier, expected):
    assert normalize_guest_quality(quality, tier) == expected


# --- web_app_data_handler ---

async def test_invalid_webapp_data_is_rejected_without_side_effects(db, monkeypatch):
    await db.get_or_create_user(111, "u", "U", "en")
    answer = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "answer", answer)
    trim = AsyncMock()
    monkeypatch.setattr(media, "process_smart_trim", trim)

    forged = {"action": "smart_trim", "url": "https://youtu.be/x", "start_sec": 500, "end_sec": 0}
    await web_app_data_handler(_make_message(111, web_app_data=SimpleNamespace(data=json.dumps(forged))), _make_fsm_context(111))

    trim.assert_not_called()
    assert "Mini App" in answer.await_args.args[0]


async def test_free_trim_over_limit_is_rejected(db, monkeypatch):
    await db.get_or_create_user(111, "u", "U", "en")
    answer = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "answer", answer)
    trim = AsyncMock()
    monkeypatch.setattr(media, "process_smart_trim", trim)

    payload = {"action": "smart_trim", "url": "https://youtu.be/x", "start_sec": 0, "end_sec": 31}
    await web_app_data_handler(_make_message(111, web_app_data=SimpleNamespace(data=json.dumps(payload))), _make_fsm_context(111))

    trim.assert_not_called()
    assert "30" in answer.await_args.args[0]


async def test_trim_respects_daily_limit(db, monkeypatch):
    await db.get_or_create_user(111, "u", "U", "en")
    for _ in range(25):  # денний ліміт Free
        await db.add_download_record(111, "https://youtu.be/x", "youtu.be", "", 1, True)

    answer = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "answer", answer)
    trim = AsyncMock()
    monkeypatch.setattr(media, "process_smart_trim", trim)

    payload = {"action": "smart_trim", "url": "https://youtu.be/x", "start_sec": 0, "end_sec": 10}
    await web_app_data_handler(_make_message(111, web_app_data=SimpleNamespace(data=json.dumps(payload))), _make_fsm_context(111))

    trim.assert_not_called()
    assert "ліміт" in answer.await_args.args[0].lower() or "limit" in answer.await_args.args[0].lower()


# --- єдиний допуск у start_download ---

async def test_start_download_refuses_while_previous_download_runs(db, monkeypatch):
    user = await db.get_or_create_user(111, "u", "U", "en")
    media.user_cooldowns.add(111)
    download = AsyncMock()
    monkeypatch.setattr(media, "download_media", download)
    reply = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "reply", reply)

    ok = await media.start_download(_make_message(111), "https://youtu.be/x", "best", user)

    assert ok is False
    download.assert_not_called()
    reply.assert_awaited_once()


async def test_start_download_refuses_when_daily_limit_reached(db, monkeypatch):
    user = await db.get_or_create_user(111, "u", "U", "en")
    for _ in range(25):
        await db.add_download_record(111, "https://youtu.be/x", "youtu.be", "", 1, True)
    download = AsyncMock()
    monkeypatch.setattr(media, "download_media", download)
    monkeypatch.setattr(_FakeMessage, "reply", AsyncMock())

    ok = await media.start_download(_make_message(111), "https://youtu.be/x", "best", user)

    assert ok is False
    download.assert_not_called()
    # Відмова не повинна «залипати» cooldown.
    assert 111 not in media.user_cooldowns


async def test_blocked_guest_download_answers_guest_query(db, monkeypatch):
    user = await db.get_or_create_user(111, "u", "U", "en")
    media.user_cooldowns.add(111)
    answer_guest = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "answer_guest_query", answer_guest)

    ok = await media.start_download(_make_guest_message(111), "https://youtu.be/x", "best", user, is_guest_mode=True)

    assert ok is False
    answer_guest.assert_awaited_once()


# --- middleware у гостьовому режимі ---

async def test_throttling_counts_guest_caller_not_bot():
    mw = ThrottlingMiddleware(rate_limit=1.0)
    handler = AsyncMock(return_value="ok")

    # Два різні користувачі кличуть бота: from_user у обох — бот, але ліміт окремий.
    assert await mw(handler, _make_guest_message(111), {}) == "ok"
    assert await mw(handler, _make_guest_message(222), {}) == "ok"
    assert await mw(handler, _make_guest_message(111), {}) is None


async def test_banned_user_is_blocked_in_guest_mode(db, monkeypatch):
    await db.get_or_create_user(111, "caller", "Caller", "en")
    await db.ban_user_bot(111, days=1)
    answer_guest = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "answer_guest_query", answer_guest)
    handler = AsyncMock()

    await BanCheckMiddleware()(handler, _make_guest_message(111), {})

    handler.assert_not_called()
    answer_guest.assert_awaited_once()
