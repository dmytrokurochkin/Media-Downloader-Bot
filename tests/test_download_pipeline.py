import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import Message

import downloader
import handlers.media as media
from core.utils import CommandTimeoutError, cleanup_stale_downloads, run_command


class _FakeMessage(Message):
    pass


def _make_message(user_id, message_id=10):
    return _FakeMessage.model_construct(
        from_user=SimpleNamespace(id=user_id, username="u", full_name="U"),
        chat=SimpleNamespace(id=user_id, type="private"),
        message_id=message_id,
    )


def _bad_request(text):
    return TelegramBadRequest(method=None, message=text)


@pytest.fixture(autouse=True)
def _reset_media_state(monkeypatch):
    monkeypatch.setattr(media, "user_cooldowns", set())
    monkeypatch.setattr(media, "active_requests", 0)
    monkeypatch.setattr(media, "queue_waiters", 0)
    monkeypatch.setattr(media, "download_semaphore", None)


# --- downloader: залишки, ліміти, помилки ---

def test_collect_media_files_skips_leftovers(tmp_path):
    for name in ["video.mp4", "video.mp4.part", "video.f137.mp4", "audio.f140.m4a",
                 "video.ytdl", "info.json", "thumb.jpg", "song.mp3"]:
        (tmp_path / name).write_bytes(b"x")

    names = sorted(p.name for p in downloader.collect_media_files(tmp_path, keep_images=False))
    assert names == ["song.mp3", "video.mp4"]


def test_enforce_size_limit_drops_oversized_and_raises_when_nothing_left(tmp_path):
    small = tmp_path / "small.mp4"
    big = tmp_path / "big.mp4"
    small.write_bytes(b"x" * 10)
    big.write_bytes(b"x" * 100)

    assert downloader.enforce_size_limit([small, big], 50) == [small]
    with pytest.raises(downloader.SizeLimitExceeded):
        downloader.enforce_size_limit([big], 50)


async def test_download_media_enforces_actual_size(monkeypatch, tmp_path):
    big = tmp_path / "big.zip"
    big.write_bytes(b"x" * 2048)

    async def allow(url):
        return url

    async def fake_github(*args, **kwargs):
        return big

    monkeypatch.setattr(downloader, "ensure_public_url", allow)
    monkeypatch.setattr(downloader, "download_github", fake_github)
    monkeypatch.setitem(downloader.TIER_LIMITS, "free", {**downloader.TIER_LIMITS["free"], "size": 1024})

    with pytest.raises(downloader.SizeLimitExceeded):
        await downloader.download_media("https://github.com/u/r", session_dir=tmp_path, tier="free")


@pytest.mark.parametrize("messages,expected", [
    (["ERROR: [youtube] x: Sign in to confirm your age. This video may be inappropriate"], "18+"),
    (["ERROR: [youtube] x: Private video. Sign in if you've been granted access"], "приватне"),
    (["ERROR: [generic] Unsupported URL: https://example.com"], "Unsupported URL"),
    ([], "Не вдалося"),
])
def test_describe_ytdlp_failure(messages, expected):
    assert expected in downloader.describe_ytdlp_failure(messages)


async def test_download_media_times_out_and_cancels(monkeypatch, tmp_path):
    seen = {}

    async def allow(url):
        return url

    def slow_sync(url, fmt, cb, loop, session_dir, tier, meta, cancel_event):
        seen["event"] = cancel_event
        cancel_event.wait(5)
        raise downloader.DownloadTimeoutError("cancelled")

    monkeypatch.setattr(downloader, "ensure_public_url", allow)
    monkeypatch.setattr(downloader, "download_media_sync", slow_sync)
    monkeypatch.setattr(downloader, "YTDLP_JOB_TIMEOUT", 0.2)

    started = time.monotonic()
    with pytest.raises(downloader.DownloadTimeoutError):
        await downloader.download_media("https://www.youtube.com/watch?v=x", session_dir=tmp_path / "s")
    assert time.monotonic() - started < 3
    # Потік отримав сигнал зупинитись, а не крутиться далі.
    assert seen["event"].is_set()


def test_download_media_sync_reports_real_error_and_ignores_part_files(monkeypatch, tmp_path):
    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download):
            # Як yt-dlp з ignoreerrors: недокачаний файл лишився, помилка — лише в лозі.
            (tmp_path / "clip.mp4.part").write_bytes(b"partial")
            self.opts["logger"].error("ERROR: [youtube] x: Video unavailable. This video has been removed")
            return None

    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.chdir(tmp_path)  # без cookies.txt — одна спроба

    with pytest.raises(downloader.DownloadFailedError, match="Video unavailable"):
        downloader.download_media_sync("https://youtu.be/x", "best", None, None, tmp_path, "free")


# --- run_command / прибирання ---

async def test_run_command_kills_hung_process():
    started = time.monotonic()
    with pytest.raises(CommandTimeoutError):
        await run_command([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.5, name="sleeper")
    assert time.monotonic() - started < 10


async def test_run_command_returns_output():
    code, out, err = await run_command([sys.executable, "-c", "print('ok')"], timeout=10, name="echo")
    assert code == 0 and out.strip() == "ok"


def test_cleanup_stale_downloads(tmp_path):
    root = tmp_path / "downloads"
    (root / "123").mkdir(parents=True)
    (root / "123" / "a.part").write_bytes(b"x")
    (root / "stray.tmp").write_bytes(b"x")

    assert cleanup_stale_downloads(root) == 2
    assert list(root.iterdir()) == []


# --- доставка ---

async def test_caption_fallback_retries_without_ad():
    calls = []

    async def send(caption):
        calls.append(caption)
        if "AD" in caption:
            raise _bad_request("Bad Request: can't parse entities: unclosed tag")
        return "sent"

    result, used = await media.send_with_caption_fallback(send, "sig AD", "sig")
    assert result == "sent" and used == "sig"
    assert calls == ["sig AD", "sig"]


async def test_caption_fallback_does_not_hide_other_errors():
    async def send(caption):
        raise _bad_request("Bad Request: wrong file identifier")

    with pytest.raises(TelegramBadRequest):
        await media.send_with_caption_fallback(send, "sig AD", "sig")


async def test_prepare_caption_skips_oversized_ad(db):
    await db.set_active_ad("x" * 2000)
    db._ad_cache["timestamp"] = 0

    caption = await media.prepare_caption_with_ad("Signature", {"tier": "free"})
    assert caption == "Signature"


async def test_dispatch_propagates_send_failure(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    fake_bot = SimpleNamespace(send_video=AsyncMock(side_effect=_bad_request("Bad Request: file is too big")))

    with pytest.raises(TelegramBadRequest):
        await media.dispatch_telegram_media(fake_bot, 1, video, {"tier": "max", "telegram_id": 1}, False, _make_message(1), "en")

    # Одна спроба з reply_parameters замість «повторити без reply і проковтнути помилку».
    assert fake_bot.send_video.await_count == 1
    kwargs = fake_bot.send_video.await_args.kwargs
    assert kwargs["reply_parameters"].allow_sending_without_reply is True


async def test_failed_delivery_is_not_counted_as_success(db, monkeypatch, tmp_path):
    user = await db.get_or_create_user(111, "u", "U", "en")
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")

    monkeypatch.setattr(media, "download_media", AsyncMock(return_value=video))
    monkeypatch.setattr(media, "dispatch_telegram_media", AsyncMock(side_effect=_bad_request("Bad Request: file is too big")))
    monkeypatch.setattr(media, "bot", SimpleNamespace(edit_message_text=AsyncMock(), delete_message=AsyncMock(),
                                                      set_chat_menu_button=AsyncMock(), download=AsyncMock()))
    monkeypatch.setattr(_FakeMessage, "reply", AsyncMock(return_value=SimpleNamespace(chat=SimpleNamespace(id=111), message_id=11)))
    monkeypatch.chdir(tmp_path)

    ok = await media.start_download(_make_message(111), "https://youtu.be/x", "best", user)

    assert ok is False
    assert await db.get_daily_download_count(111) == 0
    assert 111 not in media.user_cooldowns


async def test_counters_are_restored_when_status_message_fails(db, monkeypatch, tmp_path):
    user = await db.get_or_create_user(111, "u", "U", "en")
    download = AsyncMock()
    monkeypatch.setattr(media, "download_media", download)
    monkeypatch.setattr(media, "bot", SimpleNamespace(edit_message_text=AsyncMock()))
    # Бот заблокований: навіть статус-повідомлення не відправляється.
    monkeypatch.setattr(_FakeMessage, "reply", AsyncMock(side_effect=TelegramForbiddenError(method=None, message="bot was blocked by the user")))
    monkeypatch.chdir(tmp_path)

    ok = await media.start_download(_make_message(111), "https://youtu.be/x", "best", user)

    assert ok is False
    download.assert_not_called()
    assert media.active_requests == 0
    assert media.queue_waiters == 0
    assert 111 not in media.user_cooldowns


async def test_guest_delivery_asks_to_start_bot_when_pm_is_closed(tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    fake_bot = SimpleNamespace(send_video=AsyncMock(side_effect=TelegramForbiddenError(method=None, message="bot can't initiate conversation")))
    message = _FakeMessage.model_construct(guest_query_id="q1", chat=SimpleNamespace(id=1, type="private"), message_id=1)
    answer = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "answer_guest_query", answer)
    monkeypatch.setattr(media, "STORAGE_CHAT_ID", None)

    await media.dispatch_telegram_media(fake_bot, 1, video, {"tier": "max", "telegram_id": 1}, True, message, "en")

    result = answer.await_args.kwargs["result"]
    assert "Start" in result.input_message_content.message_text


# --- реклама в адмінці ---

class _AdminMessage(Message):
    pass


async def _run_add_ad(db, monkeypatch, text, preview_text=None, preview_error=None):
    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.storage.base import StorageKey
    from aiogram.fsm.storage.memory import MemoryStorage
    import handlers.admin as admin

    monkeypatch.setattr(admin, "ADMIN_IDS", [1])
    await db.get_or_create_user(1, "admin", "Admin", "en")
    answer = AsyncMock(side_effect=preview_error) if preview_error else AsyncMock(return_value=SimpleNamespace(text=preview_text))
    reply = AsyncMock()
    monkeypatch.setattr(_AdminMessage, "answer", answer)
    monkeypatch.setattr(_AdminMessage, "reply", reply)

    message = _AdminMessage.model_construct(
        from_user=SimpleNamespace(id=1, username="admin", full_name="Admin"),
        chat=SimpleNamespace(id=1, type="private"), message_id=1, text=text,
    )
    state = FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=1, user_id=1))
    await admin.process_add_ad(message, state)
    db._ad_cache["timestamp"] = 0
    return await db.get_active_ad(), reply


async def test_ad_with_broken_html_is_not_saved(db, monkeypatch):
    saved, reply = await _run_add_ad(db, monkeypatch, "<b>Buy", preview_error=_bad_request("Bad Request: can't parse entities"))
    assert saved is None
    assert "HTML" in reply.await_args.args[0]


async def test_too_long_ad_is_not_saved(db, monkeypatch):
    saved, _ = await _run_add_ad(db, monkeypatch, "x" * 400, preview_text="x" * 400)
    assert saved is None


async def test_valid_ad_is_saved(db, monkeypatch):
    saved, _ = await _run_add_ad(db, monkeypatch, "<b>Buy</b> now", preview_text="Buy now")
    assert saved == "<b>Buy</b> now"
