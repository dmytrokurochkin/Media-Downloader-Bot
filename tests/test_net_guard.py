import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from core import net_guard
from core.net_guard import (
    PublicOnlyResolver,
    ResponseTooLargeError,
    UnsafeURLError,
    ensure_public_url,
    is_public_ip,
    safe_download,
    safe_get,
)


# --- is_public_ip ---

@pytest.mark.parametrize("address", [
    "93.184.216.34",
    "8.8.8.8",
    "2606:4700:4700::1111",
])
def test_is_public_ip_accepts_global_unicast(address):
    assert is_public_ip(address) is True


@pytest.mark.parametrize("address", [
    "127.0.0.1",            # loopback (тут живе локальний Bot API)
    "10.1.2.3",             # private
    "172.16.0.1",           # private
    "192.168.0.10",         # private
    "169.254.169.254",      # link-local / cloud metadata
    "100.64.0.1",           # CGNAT
    "0.0.0.0",              # unspecified
    "224.0.0.1",            # multicast
    "::1",                  # IPv6 loopback
    "fe80::1%eth0",         # link-local з zone id
    "::ffff:127.0.0.1",     # IPv4-mapped loopback
    "2002:7f00:1::1",       # 6to4-обгортка над 127.0.0.1
    "not-an-ip",
])
def test_is_public_ip_rejects_everything_else(address):
    assert is_public_ip(address) is False


# --- ensure_public_url ---

def _fake_resolve(*addresses):
    async def fake(host, port):
        return list(addresses)
    return fake


async def test_ensure_public_url_accepts_public_host(monkeypatch):
    monkeypatch.setattr(net_guard, "_resolve", _fake_resolve("93.184.216.34"))
    url = "https://www.youtube.com/watch?v=abc"
    assert await ensure_public_url(url) == url


@pytest.mark.parametrize("url", [
    "ftp://example.com/file",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "http:///no-host",
    "not-a-url",
    "https://youtube.com@127.0.0.1/",        # userinfo-трюк
    "https://user:pass@example.com/",
    "https://example.com:8081/",              # нестандартний порт
    "http://example.com:99999/",              # невалідний порт
])
async def test_ensure_public_url_rejects_bad_shapes(monkeypatch, url):
    monkeypatch.setattr(net_guard, "_resolve", _fake_resolve("93.184.216.34"))
    with pytest.raises(UnsafeURLError):
        await ensure_public_url(url)


async def test_ensure_public_url_rejects_private_resolution(monkeypatch):
    monkeypatch.setattr(net_guard, "_resolve", _fake_resolve("127.0.0.1"))
    with pytest.raises(UnsafeURLError):
        await ensure_public_url("http://localtest.me/")


async def test_ensure_public_url_rejects_mixed_resolution(monkeypatch):
    # Достатньо однієї приватної адреси серед відповідей, щоб відмовити.
    monkeypatch.setattr(net_guard, "_resolve", _fake_resolve("93.184.216.34", "10.0.0.1"))
    with pytest.raises(UnsafeURLError):
        await ensure_public_url("https://mixed.example/")


async def test_ensure_public_url_dns_failure_is_unsafe(monkeypatch):
    async def failing(host, port):
        raise OSError("no such host")

    monkeypatch.setattr(net_guard, "_resolve", failing)
    with pytest.raises(UnsafeURLError):
        await ensure_public_url("https://doesnotresolve.invalid/")


def test_ensure_public_url_sync_rejects_literal_loopback():
    with pytest.raises(UnsafeURLError):
        net_guard.ensure_public_url_sync("http://127.0.0.1:80/bot123:abc/sendDocument")


# --- PublicOnlyResolver ---

class _FakeInnerResolver:
    def __init__(self, hosts):
        self._hosts = hosts

    async def resolve(self, host, port=0, family=0):
        return [{"hostname": host, "host": h, "port": port, "family": family, "proto": 0, "flags": 0} for h in self._hosts]

    async def close(self):
        pass


async def test_resolver_rejects_private_records():
    resolver = PublicOnlyResolver()
    await resolver.close()
    resolver._inner = _FakeInnerResolver(["93.184.216.34", "127.0.0.1"])
    with pytest.raises(OSError):
        await resolver.resolve("rebind.example", 443)


async def test_resolver_passes_public_records():
    resolver = PublicOnlyResolver()
    await resolver.close()
    resolver._inner = _FakeInnerResolver(["93.184.216.34"])
    records = await resolver.resolve("example.com", 443)
    assert [r["host"] for r in records] == ["93.184.216.34"]


# --- safe_get / safe_download (локальний тестовий сервер) ---

@pytest.fixture
async def server():
    hits = []

    async def start(request):
        hits.append("start")
        raise web.HTTPFound("/secret")

    async def secret(request):
        hits.append("secret")
        return web.Response(text="LEAK")

    async def big(request):
        return web.Response(body=b"x" * 4096)

    app = web.Application()
    app.router.add_get("/start", start)
    app.router.add_get("/secret", secret)
    app.router.add_get("/big", big)

    test_server = TestServer(app, host="127.0.0.1")
    await test_server.start_server()
    test_server.hits = hits
    yield test_server
    await test_server.close()


def _allow_only(prefix_blocked):
    """Пропускає тестовий сервер, але «блокує» адреси з заданим шляхом, як приватну мережу."""
    async def fake(url):
        if prefix_blocked in url:
            raise UnsafeURLError("blocked")
        return url
    return fake


async def test_safe_get_validates_every_redirect_hop(monkeypatch, server):
    monkeypatch.setattr(net_guard, "ensure_public_url", _allow_only("/secret"))

    with pytest.raises(UnsafeURLError):
        await safe_get(str(server.make_url("/start")), max_bytes=1024)

    # Редірект на заблоковану адресу обірвано ДО запиту туди.
    assert server.hits == ["start"]


async def test_safe_get_enforces_size_limit(monkeypatch, server):
    monkeypatch.setattr(net_guard, "ensure_public_url", _allow_only("/never"))
    with pytest.raises(ResponseTooLargeError):
        await safe_get(str(server.make_url("/big")), max_bytes=1024)


async def test_safe_get_returns_body_within_limit(monkeypatch, server):
    monkeypatch.setattr(net_guard, "ensure_public_url", _allow_only("/never"))
    result = await safe_get(str(server.make_url("/big")), max_bytes=10_000)
    assert result.body == b"x" * 4096


async def test_safe_download_removes_partial_file_on_overflow(monkeypatch, server, tmp_path):
    monkeypatch.setattr(net_guard, "ensure_public_url", _allow_only("/never"))
    destination = tmp_path / "big.bin"
    with pytest.raises(ResponseTooLargeError):
        await safe_download(str(server.make_url("/big")), destination, max_bytes=1024)
    assert not destination.exists()


async def test_safe_download_writes_file_and_reports_progress(monkeypatch, server, tmp_path):
    monkeypatch.setattr(net_guard, "ensure_public_url", _allow_only("/never"))
    destination = tmp_path / "ok.bin"
    progress = []

    async def on_progress(pct):
        progress.append(pct)

    result = await safe_download(str(server.make_url("/big")), destination, max_bytes=10_000, progress_callback=on_progress)
    assert result.read_bytes() == b"x" * 4096
    assert progress and progress[-1] == pytest.approx(100.0)
