from pathlib import Path

import pytest

import downloader


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
])
async def test_download_media_routes_to_correct_backend(monkeypatch, tmp_path, url, expected):
    calls = []
    _patch_all_backends(monkeypatch, calls)

    await downloader.download_media(url, session_dir=tmp_path)
    assert calls == [expected]


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


# --- download_github ---

class _FakeResponse:
    def __init__(self, status, chunks=None, content_length=None):
        self.status = status
        self._chunks = chunks or []
        headers = {}
        if content_length is not None:
            headers["content-length"] = str(content_length)
        self.headers = headers
        self.content = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def iter_chunked(self, size):
        chunks = self._chunks

        async def gen():
            for c in chunks:
                yield c

        return gen()


class _FakeSession:
    def __init__(self, responses_by_url):
        self._responses = responses_by_url

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def get(self, url, *args, **kwargs):
        return self._responses[url]


def test_download_github_rejects_invalid_url():
    with pytest.raises(ValueError):
        import asyncio
        asyncio.run(downloader.download_github("https://not-github.com/foo", Path(".")))


async def test_download_github_uses_main_branch_when_available(monkeypatch, tmp_path):
    main_url = "https://github.com/user/repo/archive/refs/heads/main.zip"
    master_url = "https://github.com/user/repo/archive/refs/heads/master.zip"
    responses = {
        main_url: _FakeResponse(200, chunks=[b"zipdata"], content_length=7),
        master_url: _FakeResponse(404),
    }
    monkeypatch.setattr(downloader.aiohttp, "ClientSession", lambda: _FakeSession(responses))

    result = await downloader.download_github("https://github.com/user/repo", tmp_path)
    assert result.name == "repo_main.zip"
    assert result.read_bytes() == b"zipdata"


async def test_download_github_falls_back_to_master_branch(monkeypatch, tmp_path):
    main_url = "https://github.com/user/repo/archive/refs/heads/main.zip"
    master_url = "https://github.com/user/repo/archive/refs/heads/master.zip"
    responses = {
        main_url: _FakeResponse(404),
        master_url: _FakeResponse(200, chunks=[b"masterdata"], content_length=10),
    }
    monkeypatch.setattr(downloader.aiohttp, "ClientSession", lambda: _FakeSession(responses))

    result = await downloader.download_github("https://github.com/user/repo", tmp_path)
    assert result.name == "repo_master.zip"


async def test_download_github_raises_when_neither_branch_found(monkeypatch, tmp_path):
    main_url = "https://github.com/user/repo/archive/refs/heads/main.zip"
    master_url = "https://github.com/user/repo/archive/refs/heads/master.zip"
    responses = {
        main_url: _FakeResponse(404),
        master_url: _FakeResponse(404),
    }
    monkeypatch.setattr(downloader.aiohttp, "ClientSession", lambda: _FakeSession(responses))

    with pytest.raises(Exception):
        await downloader.download_github("https://github.com/user/repo", tmp_path)


async def test_download_github_strips_git_suffix(monkeypatch, tmp_path):
    main_url = "https://github.com/user/repo/archive/refs/heads/main.zip"
    responses = {main_url: _FakeResponse(200, chunks=[b"x"], content_length=1)}
    monkeypatch.setattr(downloader.aiohttp, "ClientSession", lambda: _FakeSession(responses))

    result = await downloader.download_github("https://github.com/user/repo.git", tmp_path)
    assert result.name == "repo_main.zip"


# --- _download_file ---

async def test_download_file_writes_all_chunks_and_reports_progress(tmp_path):
    resp = _FakeResponse(200, chunks=[b"aaaa", b"bbbb", b"cc"], content_length=10)
    progress_values = []

    async def progress_callback(pct):
        progress_values.append(pct)

    filepath = tmp_path / "out.zip"
    result = await downloader._download_file(resp, filepath, progress_callback)

    assert result == filepath
    assert filepath.read_bytes() == b"aaaabbbbcc"
    assert progress_values == pytest.approx([40.0, 80.0, 100.0])


async def test_download_file_without_progress_callback(tmp_path):
    resp = _FakeResponse(200, chunks=[b"data"], content_length=4)
    filepath = tmp_path / "out.zip"
    result = await downloader._download_file(resp, filepath, None)
    assert result.read_bytes() == b"data"
