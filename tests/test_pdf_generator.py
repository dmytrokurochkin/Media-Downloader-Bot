import socket

import pytest

from core.pdf_generator import is_safe_url


def _fake_getaddrinfo(ip):
    async def fake(hostname, port):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]
    return fake


@pytest.mark.parametrize("bad_url", [
    "ftp://example.com/file",
    "file:///etc/passwd",
    "not-a-url",
])
async def test_is_safe_url_rejects_non_http_schemes(bad_url):
    assert await is_safe_url(bad_url) is False


async def test_is_safe_url_rejects_url_without_hostname():
    assert await is_safe_url("http:///path-only") is False


@pytest.mark.parametrize("ip", [
    "127.0.0.1",       # loopback
    "10.0.0.5",        # private
    "192.168.1.1",     # private
    "169.254.1.1",     # link-local
    "0.0.0.0",          # unspecified
])
async def test_is_safe_url_blocks_local_and_private_ips(monkeypatch, ip):
    loop = __import__("asyncio").get_event_loop()
    monkeypatch.setattr(type(loop), "getaddrinfo", lambda self, host, port: _fake_getaddrinfo(ip)(host, port))

    assert await is_safe_url("http://internal.example/") is False


async def test_is_safe_url_allows_public_ip(monkeypatch):
    loop = __import__("asyncio").get_event_loop()
    monkeypatch.setattr(type(loop), "getaddrinfo", lambda self, host, port: _fake_getaddrinfo("93.184.216.34")(host, port))

    assert await is_safe_url("http://public.example/") is True


async def test_is_safe_url_dns_failure_is_unsafe(monkeypatch):
    loop = __import__("asyncio").get_event_loop()

    async def raise_dns(self, host, port):
        raise OSError("DNS resolution failed")

    monkeypatch.setattr(type(loop), "getaddrinfo", raise_dns)
    assert await is_safe_url("http://doesnotresolve.invalid/") is False
