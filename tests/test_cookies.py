import datetime
import io
import stat
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import yt_dlp
from aiogram.filters import CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message

import downloader
import handlers.admin as admin_module
from core import cookie_monitor, cookies
from core.error_handler import classify_media_error, handle_media_error
from locales import get_text

ADMIN_ID = 5000

EXPORT = (
    "# Netscape HTTP Cookie File\n"
    "# This is a generated file! Do not edit.\n\n"
    ".youtube.com\tTRUE\t/\tTRUE\t1893456000\tPREF\tf6=40000000\n"
    "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t1893456000\t__Secure-3PSID\tsecret3psid\n"
    ".youtube.com\tTRUE\t/\tTRUE\t1861920000\tSAPISID\tsapisid\n"
    "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t1893456000\tLOGIN_INFO\tlogin\n"
    ".instagram.com\tTRUE\t/\tTRUE\t1893456000\tsessionid\tigsession\n"
    ".instagram.com\tTRUE\t/\tTRUE\t1893456000\tcsrftoken\tcsrf\n"
    ".mybank.com\tTRUE\t/\tTRUE\t1893456000\tsession\tbank-secret\n"
    ".x.com\tTRUE\t/\tTRUE\t1893456000\tauth_token\txtoken\n"
)


# --- розбір і зберігання ---

def test_parse_keeps_httponly_cookies_and_drops_foreign_domains():
    grouped = cookies.parse_cookies("﻿" + EXPORT.replace("\n", "\r\n"))

    # #HttpOnly_ — не коментар: саме так позначені авторизаційні куки YouTube.
    assert [c.name for c in grouped["youtube"]] == ["PREF", "__Secure-3PSID", "SAPISID", "LOGIN_INFO"]
    assert [c.name for c in grouped["instagram"]] == ["sessionid", "csrftoken"]
    assert [c.name for c in grouped["x"]] == ["auth_token"]
    assert "mybank" not in str(grouped)


def test_summary_detects_login_and_earliest_expiry():
    summary = cookies.summarize("youtube", cookies.parse_cookies(EXPORT)["youtube"])
    assert summary.authenticated
    assert summary.auth_expires == datetime.datetime.fromtimestamp(1861920000, datetime.timezone.utc)
    assert not cookies.summarize("tiktok", []).authenticated


def test_import_merges_per_service_and_writes_private_file():
    path = cookies.COOKIES_FILE
    cookies.import_cookies(EXPORT)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert "bank-secret" not in path.read_text()

    # Нові куки Instagram замінюють лише Instagram: YouTube і X лишаються.
    summaries = cookies.import_cookies(".instagram.com\tTRUE\t/\tTRUE\t1893456000\tsessionid\tNEW\n")
    assert list(summaries) == ["instagram"]
    master = cookies.load_master()
    assert [c.raw.split("\t")[-1] for c in master["instagram"]] == ["NEW"]
    assert len(master["youtube"]) == 4 and len(master["x"]) == 1
    assert not list(path.parent.glob(".cookies-*.tmp"))


@pytest.mark.parametrize("text, key", [
    ('[{"domain": ".youtube.com", "name": "SID", "value": "x"}]', "cookies_bad_format"),
    ("just some text", "cookies_bad_format"),
    (".mybank.com\tTRUE\t/\tTRUE\t1893456000\tsession\tx\n", "cookies_no_known"),
])
def test_import_rejects_unusable_files(text, key):
    with pytest.raises(cookies.CookieFileError) as info:
        cookies.import_cookies(text)
    assert info.value.key == key
    assert not cookies.COOKIES_FILE.exists()


def test_clear_service():
    cookies.import_cookies(EXPORT)
    assert cookies.clear_service("instagram")
    assert not cookies.clear_service("instagram")
    assert "instagram" not in cookies.load_master()
    assert cookies.has_cookies("youtube")


@pytest.mark.parametrize("url, service", [
    ("https://youtu.be/abc", "youtube"),
    ("https://music.youtube.com/watch?v=abc", "youtube"),
    ("https://twitter.com/u/status/1", "x"),
    ("https://www.instagram.com/p/abc/", "instagram"),
    ("https://notyoutube.example/watch", None),
])
def test_service_for_url(url, service):
    assert cookies.service_for_url(url) == service


def test_cookiefile_for_contains_only_that_service(tmp_path):
    cookies.import_cookies(EXPORT)
    session = tmp_path / "session"
    session.mkdir()

    copy = cookies.cookiefile_for("https://youtu.be/abc", session)
    text = copy.read_text()
    assert copy.parent == session / ".cookies" and copy != cookies.COOKIES_FILE
    assert "secret3psid" in text and "igsession" not in text and "xtoken" not in text
    assert stat.S_IMODE(copy.stat().st_mode) == 0o600
    assert cookies.cookiefile_for("https://www.tiktok.com/@u/video/1", session) is None
    assert cookies.cookiefile_for("https://example.com/v", session) is None


def test_ytdlp_write_back_hits_only_the_copy(tmp_path):
    # Справжній yt-dlp: на виході з `with` він перезаписує cookiefile. Раніше це був спільний
    # cookies.txt — і паралельні завантаження його псували.
    cookies.import_cookies(EXPORT)
    master_before = cookies.COOKIES_FILE.read_text()
    session = tmp_path / "session"
    session.mkdir()
    copy = cookies.cookiefile_for("https://www.youtube.com/watch?v=x", session)

    with yt_dlp.YoutubeDL({"cookiefile": str(copy), "quiet": True}) as ydl:
        ydl.cookiejar.clear()  # як «прокручена»/втрачена сесія

    assert "secret3psid" not in copy.read_text()
    assert cookies.COOKIES_FILE.read_text() == master_before


# --- розпізнавання проблем доступу ---

@pytest.mark.parametrize("message, kind", [
    ("WARNING: [youtube] The provided YouTube account cookies are no longer valid. They have likely been rotated",
     "cookies_invalid"),
    ("ERROR: [youtube] x: Sign in to confirm you’re not a bot", "bot_check"),
    ("ERROR: [youtube] x: Sign in to confirm your age. This video may be inappropriate for some users.",
     "age_restricted"),
    ("ERROR: [TikTok] 1: This post may not be comfortable for some audiences. Log in for access",
     "age_restricted"),
    ("ERROR: [youtube] x: Private video. Sign in if you've been granted access to this video", "private"),
    ("ERROR: [youtube] x: Join this channel to get access to members-only content", "private"),
    ("[instagram][error] AbortExtraction: HTTP redirect to login page (https://www.instagram.com/accounts/login/)",
     "login_required"),
    ("[instagram][error] AbortExtraction: HTTP redirect to challenge page (https://www.instagram.com/challenge/)",
     "cookies_invalid"),
    ("ERROR: [Instagram] x: Requested content is not available, rate-limit reached or login required",
     "login_required"),
    ("ERROR: [youtube] x: HTTP Error 429: Too Many Requests", "rate_limited"),
    ("ERROR: [youtube] x429abc: Video unavailable. This video has been removed", None),
    ("ERROR: [generic] Unsupported URL", None),
])
def test_classify_auth_problem(message, kind):
    assert cookies.classify_auth_problem([message]) == kind


def _fake_ydl(results, seen):
    """FakeYDL: кожна спроба бере наступний результат: (errors, warnings, write_file)."""
    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts
            seen.append(opts.get("cookiefile"))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download):
            errors, warnings, write_file = results.pop(0)
            for w in warnings:
                self.opts["logger"].warning(w)
            for e in errors:
                self.opts["logger"].error(e)
            if write_file:
                (self.opts_dir() / "clip.mp4").write_bytes(b"x")
                return {"title": "Clip"}
            return None

        def opts_dir(self):
            from pathlib import Path
            return Path(self.opts["outtmpl"]).parent

    return FakeYDL


def test_dead_cookies_are_reported_even_when_fallback_succeeds(monkeypatch, tmp_path):
    cookies.import_cookies(EXPORT)
    seen = []
    results = [
        (["ERROR: [youtube] x: Sign in to confirm you’re not a bot"],
         ["The provided YouTube account cookies are no longer valid."], False),
        ([], [], True),
    ]
    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", _fake_ydl(results, seen))
    meta = {}

    downloader.download_media_sync("https://youtu.be/x", "best", None, None, tmp_path, "free", meta)

    assert seen[0] is not None and seen[0].startswith(str(tmp_path)) and seen[1] is None
    assert meta["cookie_problem"].kind == "cookies_invalid"
    assert meta["cookie_problem"].had_cookies
    assert meta["cookies_used"] is None


def test_age_restricted_failure_raises_auth_error(monkeypatch, tmp_path):
    cookies.import_cookies(EXPORT)
    age = "ERROR: [youtube] x: Sign in to confirm your age. This video may be inappropriate for some users."
    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", _fake_ydl([([age], [], False), ([age], [], False)], []))

    with pytest.raises(downloader.AuthRequiredError) as info:
        downloader.download_media_sync("https://youtu.be/x", "best", None, None, tmp_path, "free")

    assert info.value.kind == "age_restricted" and info.value.had_cookies and info.value.service == "youtube"


def test_cookie_copy_is_never_returned_as_downloaded_media(monkeypatch, tmp_path):
    # yt-dlp нічого не завантажив, а в теці сесії лежить копія кук — її не можна віддати
    # як «результат» і надіслати користувачу.
    cookies.import_cookies(EXPORT)
    error = "ERROR: [youtube] x: Video unavailable. This video has been removed"
    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", _fake_ydl([([error], [], False), ([error], [], False)], []))

    with pytest.raises(downloader.DownloadFailedError, match="Video unavailable"):
        downloader.download_media_sync("https://youtu.be/x", "best", None, None, tmp_path, "free")

    assert (tmp_path / ".cookies" / "youtube.txt").exists()
    assert downloader.collect_media_files(tmp_path) == []
    assert downloader.collect_media_files(tmp_path, recursive=True) == []


def test_dead_cookies_warning_on_successful_download_is_reported(monkeypatch, tmp_path):
    # Найчастіший випадок: куки YouTube вже мертві, але публічне відео завантажилось.
    cookies.import_cookies(EXPORT)
    warning = "The provided YouTube account cookies are no longer valid. They have likely been rotated"
    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", _fake_ydl([([], [warning], True)], []))
    meta = {}
    downloader.download_media_sync("https://youtu.be/x", "best", None, None, tmp_path, "free", meta)
    assert meta["cookie_problem"].kind == "cookies_invalid"
    assert meta["cookies_used"] is None


def test_successful_cookie_download_is_marked(monkeypatch, tmp_path):
    cookies.import_cookies(EXPORT)
    monkeypatch.setattr(downloader.yt_dlp, "YoutubeDL", _fake_ydl([([], [], True)], []))
    meta = {}
    downloader.download_media_sync("https://youtu.be/x", "best", None, None, tmp_path, "free", meta)
    assert meta["cookies_used"] == "youtube" and "cookie_problem" not in meta


async def test_gallery_dl_gets_private_copy_without_write_back(monkeypatch, tmp_path):
    cookies.import_cookies(EXPORT)
    seen = {}

    async def fake_run(cmd, *, timeout, name, env=None):
        seen["cmd"] = cmd
        return 1, "", "[instagram][error] AbortExtraction: HTTP redirect to login page (https://www.instagram.com/accounts/login/)"

    monkeypatch.setattr(downloader, "run_command", fake_run)

    with pytest.raises(downloader.AuthRequiredError) as info:
        await downloader.download_with_gallery_dl("https://www.instagram.com/p/abc/", tmp_path)

    cmd = seen["cmd"]
    cookie_arg = cmd[cmd.index("--cookies") + 1]
    assert cookie_arg.startswith(str(tmp_path)) and cookie_arg != str(cookies.COOKIES_FILE)
    assert cmd[cmd.index("-o") + 1] == "cookies-update=false"
    assert info.value.kind == "login_required" and info.value.service == "instagram"


# --- реакція бота: текст користувачу й сповіщення адміну ---

def _auth_error(kind="cookies_invalid", service="youtube", had_cookies=True):
    return downloader.AuthRequiredError("detail <b>", service=service, kind=kind, had_cookies=had_cookies)


@pytest.mark.parametrize("kind, key", [
    ("cookies_invalid", "auth_blocked"),
    ("bot_check", "auth_blocked"),
    ("age_restricted", "auth_age_restricted"),
    ("private", "auth_private"),
    ("login_required", "auth_login_required"),
    ("rate_limited", "auth_rate_limited"),
])
def test_auth_errors_are_localized_and_not_reported_as_bugs(kind, key):
    assert classify_media_error(_auth_error(kind)) == (key, False)


async def test_admin_alert_is_sent_once_per_problem(db, monkeypatch):
    monkeypatch.setattr(cookie_monitor, "ADMIN_IDS", [ADMIN_ID])
    await db.get_or_create_user(ADMIN_ID, "a", "A", "en")
    bot = SimpleNamespace(send_message=AsyncMock())

    assert await cookie_monitor.report_problem(bot, _auth_error(), "https://youtu.be/x")
    assert not await cookie_monitor.report_problem(bot, _auth_error(), "https://youtu.be/y")

    text = bot.send_message.await_args.args[1]
    assert "YouTube" in text and get_text("en", "cookie_hint_refresh") in text
    assert "detail &lt;b&gt;" in text
    status = await db.get_cookie_status()
    assert status["youtube"]["last_error"].startswith("cookies_invalid")

    # Після оновлення кук наступна проблема знову доходить одразу.
    cookie_monitor.reset_alerts("youtube")
    assert await cookie_monitor.report_problem(bot, _auth_error(), "https://youtu.be/z")


@pytest.mark.parametrize("error", [
    _auth_error(kind="private"),
    _auth_error(service=None),
])
async def test_no_alert_for_content_restrictions_or_unknown_sites(db, monkeypatch, error):
    monkeypatch.setattr(cookie_monitor, "ADMIN_IDS", [ADMIN_ID])
    bot = SimpleNamespace(send_message=AsyncMock())
    assert not await cookie_monitor.report_problem(bot, error, "https://example.com/x")
    bot.send_message.assert_not_awaited()


def test_hint_depends_on_whether_bot_had_cookies():
    assert cookie_monitor.hint_key("age_restricted", had_cookies=False) == "cookie_hint_missing"
    assert cookie_monitor.hint_key("age_restricted", had_cookies=True) == "cookie_hint_age"
    assert cookie_monitor.hint_key("rate_limited", had_cookies=True) == "cookie_hint_rate"


async def test_handle_media_error_tells_user_and_alerts_admin(db, monkeypatch):
    monkeypatch.setattr(cookie_monitor, "ADMIN_IDS", [ADMIN_ID])
    await db.get_or_create_user(ADMIN_ID, "a", "A", "en")
    bot = SimpleNamespace(send_message=AsyncMock(), edit_message_text=AsyncMock(), send_document=AsyncMock())
    status_msg = SimpleNamespace(chat=SimpleNamespace(id=1), message_id=2)
    monkeypatch.setattr("core.error_handler.schedule_delete", lambda *a, **k: None)

    await handle_media_error(_auth_error("age_restricted"), bot, status_msg, "https://youtu.be/x",
                             {"telegram_id": 111}, "en", False)

    assert bot.edit_message_text.await_args.args[0] == get_text("en", "auth_age_restricted")
    assert get_text("en", "cookie_hint_age") in bot.send_message.await_args.args[1]
    bot.send_document.assert_not_awaited()  # не баг — без звіту в канал помилок


# --- /cookies в адмінці ---

class _FakeMessage(Message):
    pass


def _make_message(user_id, chat_type="private", **extra):
    return _FakeMessage.model_construct(
        from_user=SimpleNamespace(id=user_id, username="a", full_name="A"),
        chat=SimpleNamespace(id=user_id, type=chat_type),
        message_id=10,
        **extra,
    )


def _state(user_id):
    return FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=user_id, user_id=user_id))


@pytest.fixture
def admin_env(monkeypatch):
    monkeypatch.setattr(admin_module, "ADMIN_IDS", [ADMIN_ID])
    replies = {"reply": AsyncMock(), "answer": AsyncMock(), "delete": AsyncMock()}
    for name, mock in replies.items():
        monkeypatch.setattr(_FakeMessage, name, mock)
    return replies


async def test_admin_uploads_cookies_file(db, monkeypatch, admin_env):
    monkeypatch.setattr(admin_module.bot, "download", AsyncMock(return_value=io.BytesIO(EXPORT.encode())))
    await db.record_cookie_error("youtube", "cookies_invalid: old")
    document = SimpleNamespace(file_id="F", file_size=len(EXPORT))

    await admin_module.cookies_upload(_make_message(ADMIN_ID, document=document, caption="/cookies"), _state(ADMIN_ID))

    assert cookies.has_cookies("youtube") and cookies.has_cookies("instagram")
    admin_env["delete"].assert_awaited_once()  # файл кук не лишається в історії чату
    saved = admin_env["answer"].await_args.args[0]
    assert "YouTube" in saved and "Instagram" in saved
    assert (await db.get_cookie_status())["youtube"]["last_error"] is None


async def test_cookies_upload_refused_in_groups_and_for_non_admins(db, monkeypatch, admin_env):
    download = AsyncMock(return_value=io.BytesIO(EXPORT.encode()))
    monkeypatch.setattr(admin_module.bot, "download", download)
    document = SimpleNamespace(file_id="F", file_size=100)

    await admin_module.cookies_upload(_make_message(ADMIN_ID, "supergroup", document=document), _state(ADMIN_ID))
    await admin_module.cookies_upload(_make_message(6000, document=document), _state(6000))

    download.assert_not_awaited()
    assert not cookies.COOKIES_FILE.exists()
    assert admin_env["reply"].await_args.args[0] == get_text("en", "cookies_private_only")


async def test_cookies_upload_rejects_bad_file(db, monkeypatch, admin_env):
    monkeypatch.setattr(admin_module.bot, "download", AsyncMock(return_value=io.BytesIO(b"\xff\xfe junk")))
    document = SimpleNamespace(file_id="F", file_size=10)

    await admin_module.cookies_upload(_make_message(ADMIN_ID, document=document), _state(ADMIN_ID))

    assert admin_env["reply"].await_args.args[0] == get_text("en", "cookies_bad_format")
    admin_env["delete"].assert_not_awaited()


async def test_cookies_status_and_clear(db, admin_env):
    cookies.import_cookies(EXPORT)

    await admin_module.cookies_command(_make_message(ADMIN_ID, text="/cookies"),
                                       CommandObject(command="cookies"), _state(ADMIN_ID))
    status_text = admin_env["reply"].await_args.args[0]
    assert "YouTube" in status_text and "TikTok" in status_text
    assert get_text("en", "cookies_help") in status_text

    await admin_module.cookies_command(_make_message(ADMIN_ID, text="/cookies clear instagram"),
                                       CommandObject(command="cookies", args="clear instagram"), _state(ADMIN_ID))
    assert not cookies.has_cookies("instagram")
    assert admin_env["reply"].await_args.args[0] == get_text("en", "cookies_cleared", service="Instagram")
