from pathlib import Path

import pytest

import downloader
from core.net_guard import FetchError, UnsafeURLError


@pytest.fixture(autouse=True)
def _no_real_dns(monkeypatch):
    """Маршрутизацію тестуємо без мережі: SSRF-перевірку перевіряють окремі тести."""
    async def allow(url):
        return url

    monkeypatch.setattr(downloader, "ensure_public_url", allow)


# --- download_media routing ---

def _patch_all_backends(monkeypatch, calls):
    def make_recorder(name):
        async def recorder(*args, **kwargs):
            calls.append(name)
            return Path("dummy")
        return recorder

    monkeypatch.setattr(downloader, "download_with_gallery_dl", make_recorder("gallery_dl"))
    monkeypatch.setattr(downloader, "download_threads_native", make_recorder("threads"))
    monkeypatch.setattr(downloader, "download_with_spotdl", make_recorder("spotdl"))
    monkeypatch.setattr(downloader, "download_github", make_recorder("github"))

    def fake_sync(*args, **kwargs):
        calls.append("yt_dlp")
        return Path("dummy")

    monkeypatch.setattr(downloader, "download_media_sync", fake_sync)


@pytest.mark.parametrize("url,expected", [
    ("https://www.instagram.com/p/abc123/", "gallery_dl"),
    ("https://www.threads.net/@user/post/abc", "threads"),
    ("https://www.threads.com/@user/post/abc", "threads"),
    ("https://www.facebook.com/photo/?fbid=1", "gallery_dl"),
    ("https://www.facebook.com/media/set/?set=1", "gallery_dl"),
    ("https://open.spotify.com/track/abc", "spotdl"),
    ("https://github.com/user/repo", "github"),
    ("https://www.youtube.com/watch?v=abc", "yt_dlp"),
    ("https://www.tiktok.com/@user/video/123", "yt_dlp"),
    # Домен у query чи шляху не повинен перемикати бекенд — лише справжній хост.
    ("https://evil.example/?next=instagram.com", "yt_dlp"),
    ("https://evil.example/github.com/user/repo", "yt_dlp"),
    ("https://www.facebook.com/watch/?v=1", "yt_dlp"),
])
async def test_download_media_routes_to_correct_backend(monkeypatch, tmp_path, url, expected):
    calls = []
    _patch_all_backends(monkeypatch, calls)

    await downloader.download_media(url, session_dir=tmp_path)
    assert calls == [expected]


async def test_download_media_rejects_unsafe_url_before_any_backend(monkeypatch, tmp_path):
    calls = []
    _patch_all_backends(monkeypatch, calls)

    async def reject(url):
        raise UnsafeURLError("private network")

    monkeypatch.setattr(downloader, "ensure_public_url", reject)

    with pytest.raises(UnsafeURLError):
        await downloader.download_media("http://127.0.0.1:8081/bot123:abc/getMe", session_dir=tmp_path)
    assert calls == []


async def test_download_media_cleans_up_session_dir_on_yt_dlp_failure(monkeypatch, tmp_path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    (session_dir / "partial.mp4").write_bytes(b"data")

    def failing_sync(*args, **kwargs):
        raise RuntimeError("download failed")

    monkeypatch.setattr(downloader, "download_media_sync", failing_sync)

    with pytest.raises(RuntimeError):
        await downloader.download_media("https://www.youtube.com/watch?v=abc", session_dir=session_dir)

    assert not session_dir.exists()


def test_host_matches_requires_real_host():
    assert downloader.host_matches("https://m.youtube.com/watch?v=1", "youtube.com")
    assert downloader.host_matches("https://youtube.com/", "youtube.com")
    assert not downloader.host_matches("https://notyoutube.com/", "youtube.com")
    assert not downloader.host_matches("https://evil.example/?youtube.com", "youtube.com")


# --- download_github ---

def _fake_safe_download(calls, *, fail_status=None, payload=b"zipdata"):
    async def fake(url, destination, *, max_bytes, progress_callback=None, **kwargs):
        calls.append((url, destination.name, max_bytes))
        if fail_status is not None:
            raise FetchError("http error", fail_status)
        destination.write_bytes(payload)
        return destination
    return fake


def test_download_github_rejects_invalid_url():
    with pytest.raises(ValueError):
        import asyncio
        asyncio.run(downloader.download_github("https://not-github.com/foo", Path(".")))


async def test_download_github_downloads_default_branch_archive(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(downloader, "safe_download", _fake_safe_download(calls))

    result = await downloader.download_github("https://github.com/user/repo", tmp_path, max_bytes=1234)

    # HEAD.zip — дефолтна гілка репозиторію, хай то main, master чи dev.
    assert calls == [("https://github.com/user/repo/archive/HEAD.zip", "repo.zip", 1234)]
    assert result.read_bytes() == b"zipdata"


async def test_download_github_strips_git_suffix(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(downloader, "safe_download", _fake_safe_download(calls))

    result = await downloader.download_github("https://github.com/user/repo.git", tmp_path)
    assert result.name == "repo.zip"
    assert calls[0][0] == "https://github.com/user/repo/archive/HEAD.zip"


async def test_download_github_reports_missing_repository(monkeypatch, tmp_path):
    monkeypatch.setattr(downloader, "safe_download", _fake_safe_download([], fail_status=404))

    with pytest.raises(Exception, match="не знайдено"):
        await downloader.download_github("https://github.com/user/repo", tmp_path)


# --- Threads ---

_THREADS_PAGE = (
    'junk "code":"OTHER","video_versions":[{"url":"https:\\/\\/cdn.example\\/other.mp4"}] '
    '"code":"ABC123","video_versions":[{"type":101,"url":"https:\\/\\/cdn.example\\/v.mp4?a=1\\u0026b=2"}],'
    '"image_versions2":{"candidates":[{"url":"https:\\/\\/cdn.example\\/i.webp?x=1"}]}'
    ',"image_versions2":{"candidates":[{"url":"https:\\/\\/cdn.example\\/i.webp?x=1"}]}'
)


def test_extract_threads_media_decodes_urls_and_keeps_order():
    media = downloader.extract_threads_media(_THREADS_PAGE, "ABC123")
    assert media == [
        ("https://cdn.example/v.mp4?a=1&b=2", ".mp4"),
        ("https://cdn.example/i.webp?x=1", ".webp"),
    ]


async def test_download_threads_native_returns_items_in_carousel_order(monkeypatch, tmp_path):
    class _Page:
        body = _THREADS_PAGE.encode()
        charset = "utf-8"

    async def fake_get(url, **kwargs):
        return _Page()

    async def fake_download(url, destination, **kwargs):
        destination.write_bytes(b"data")
        return destination

    monkeypatch.setattr(downloader, "safe_get", fake_get)
    monkeypatch.setattr(downloader, "safe_download", fake_download)

    files = await downloader.download_threads_native("https://www.threads.com/@user/post/ABC123", tmp_path)
    assert [f.name for f in files] == ["threads_ABC123_00.mp4", "threads_ABC123_01.webp"]
