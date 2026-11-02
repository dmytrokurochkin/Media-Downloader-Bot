"""
Захист від SSRF для всіх запитів, які бот робить за посиланнями користувачів.

Чому це критично саме в цьому проєкті: поруч із ботом на 127.0.0.1:8081
працює локальний Telegram Bot API у режимі --local. Він приймає виклики методів
звичайним GET-запитом, обслуговує БУДЬ-ЯКИЙ бот-токен і в local-режимі трактує
значення `file:/...` як шлях до локального файлу для відправки. Тобто один
GET із нашого сервера на localhost із чужим токеном = відправка нашого `.env`
чужому боту. Тому тут:
  * перевіряється КОЖЕН хоп — редіректи обробляються вручну, а не aiohttp;
  * дозволені лише http/https, порти 80/443 і жодного `user:pass@` в URL;
  * домен має резолвитися ТІЛЬКИ в публічні адреси (жодних 127/8, 10/8,
    169.254/16, ::1, IPv4-mapped IPv6 тощо);
  * у з'єднаннях aiohttp працює власний resolver, який ще раз відсікає
    приватні адреси, — інакше DNS-rebinding підмінив би адресу між перевіркою
    і власне з'єднанням.

yt-dlp / gallery-dl / spotdl ходять у мережу самі, тож для них можлива лише
перевірка початкового URL (`ensure_public_url`). Редірект усередині них ця
перевірка не бачить — тому Bot API ще й запускається окремим користувачем без
доступу до файлів бота (див. auto_deploy.sh і CLAUDE.md, розділ про пастки).
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, Optional
from urllib.parse import urlsplit

import aiohttp
from aiohttp.abc import AbstractResolver
from yarl import URL

ALLOWED_SCHEMES = frozenset({"http", "https"})
ALLOWED_PORTS = frozenset({80, 443})
MAX_REDIRECTS = 5
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_CHUNK_SIZE = 64 * 1024

ProgressCallback = Optional[Callable[[float], Awaitable[None]]]


class UnsafeURLError(ValueError):
    """Посилання веде туди, куди боту ходити не можна (приватна мережа, інша схема чи порт)."""


class FetchError(Exception):
    """Ресурс не завантажився: HTTP-помилка, забагато редіректів тощо."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class ResponseTooLargeError(FetchError):
    """Відповідь більша за дозволений ліміт — завантаження обірвано."""


@dataclass
class FetchResult:
    body: bytes
    url: str
    charset: Optional[str]
    content_type: str


def is_public_ip(address: str) -> bool:
    """True лише для глобально маршрутизованих unicast-адрес."""
    try:
        # Відкидаємо IPv6 zone id (`fe80::1%eth0`), бо ip_address його не приймає.
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False

    if isinstance(ip, ipaddress.IPv6Address):
        # IPv4, загорнутий в IPv6 (::ffff:127.0.0.1, 6to4, Teredo), перевіряємо як IPv4 —
        # інакше `::ffff:127.0.0.1` проскочив би як «глобальна» IPv6-адреса.
        embedded = ip.ipv4_mapped or ip.sixtofour or (ip.teredo[1] if ip.teredo else None)
        if embedded is not None:
            ip = embedded

    return ip.is_global and not ip.is_multicast


def _parse_target(url: str) -> tuple[str, int]:
    """Перевіряє схему, хост, порт і userinfo; повертає (host, port)."""
    try:
        parts = urlsplit(url)
        explicit_port = parts.port
    except ValueError as exc:
        raise UnsafeURLError("Некоректне посилання.") from exc

    scheme = (parts.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UnsafeURLError("Підтримуються лише посилання http/https.")

    host = parts.hostname
    if not host:
        raise UnsafeURLError("У посиланні немає адреси сайту.")

    # `https://youtube.com@127.0.0.1/` виглядає як YouTube, а веде на localhost.
    if parts.username is not None or parts.password is not None:
        raise UnsafeURLError("Посилання з логіном/паролем не підтримуються.")

    port = explicit_port or (443 if scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise UnsafeURLError("Нестандартний порт у посиланні не підтримується.")

    return host, port


def _check_addresses(addresses: list[str]) -> None:
    if not addresses or not all(is_public_ip(address) for address in addresses):
        raise UnsafeURLError("Посилання веде у приватну мережу.")


async def _resolve(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port)
    return list(dict.fromkeys(info[4][0] for info in infos))


async def ensure_public_url(url: str) -> str:
    """Кидає UnsafeURLError, якщо URL не можна відкривати з сервера. Інакше повертає його ж."""
    host, port = _parse_target(url)
    try:
        addresses = await _resolve(host, port)
    except (OSError, UnicodeError) as exc:
        raise UnsafeURLError("Не вдалося знайти сайт за цим посиланням.") from exc
    _check_addresses(addresses)
    return url


def ensure_public_url_sync(url: str) -> str:
    """Синхронна версія для коду, що працює в потоках (fetcher weasyprint)."""
    host, port = _parse_target(url)
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as exc:
        raise UnsafeURLError("Не вдалося знайти сайт за цим посиланням.") from exc
    _check_addresses(list(dict.fromkeys(info[4][0] for info in infos)))
    return url


class PublicOnlyResolver(AbstractResolver):
    """Resolver для aiohttp, що не дає з'єднатися з непублічною адресою.

    Потрібен на додачу до ensure_public_url: між перевіркою і з'єднанням DNS-запис
    можна підмінити (DNS rebinding). Якщо хоч одна адреса непублічна — відмовляємо
    повністю, а не фільтруємо, щоб змішані відповіді теж не проходили.
    """

    def __init__(self) -> None:
        self._inner = aiohttp.ThreadedResolver()

    async def resolve(self, host, port=0, family=socket.AF_INET):
        records = await self._inner.resolve(host, port, family)
        if not records or not all(is_public_ip(record["host"]) for record in records):
            # aiohttp загортає OSError у ClientConnectorDNSError — як і будь-який збій DNS.
            raise OSError(f"{host} резолвиться в непублічну адресу")
        return records

    async def close(self) -> None:
        await self._inner.close()


def _make_session(timeout: aiohttp.ClientTimeout, headers: Optional[dict]) -> aiohttp.ClientSession:
    connector = aiohttp.TCPConnector(resolver=PublicOnlyResolver())
    return aiohttp.ClientSession(connector=connector, timeout=timeout, headers=headers)


async def _open_following_redirects(session: aiohttp.ClientSession, url: str) -> aiohttp.ClientResponse:
    """GET із ручною обробкою редіректів: кожна нова адреса проходить ensure_public_url."""
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        await ensure_public_url(current)
        response = await session.get(current, allow_redirects=False)
        if response.status not in _REDIRECT_STATUSES:
            return response

        location = response.headers.get("Location")
        response.release()
        if not location:
            raise FetchError("Сервер повернув редірект без адреси.", response.status)
        current = str(response.url.join(URL(location)))

    raise FetchError("Забагато редіректів.")


def _check_declared_size(response: aiohttp.ClientResponse, max_bytes: int) -> None:
    if response.content_length is not None and response.content_length > max_bytes:
        raise ResponseTooLargeError(
            f"Файл завеликий ({response.content_length} байт, ліміт {max_bytes})."
        )


async def safe_get(
    url: str,
    *,
    max_bytes: int,
    timeout: float = 15.0,
    headers: Optional[dict] = None,
) -> FetchResult:
    """Завантажує відповідь у пам'ять (сторінки, невеликі файли) з усіма перевірками."""
    client_timeout = aiohttp.ClientTimeout(total=timeout)
    async with _make_session(client_timeout, headers) as session:
        response = await _open_following_redirects(session, url)
        async with response:
            if response.status != 200:
                raise FetchError(f"Сервер відповів HTTP {response.status}.", response.status)
            _check_declared_size(response, max_bytes)

            body = bytearray()
            async for chunk in response.content.iter_chunked(_CHUNK_SIZE):
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise ResponseTooLargeError(f"Відповідь більша за {max_bytes} байт.")

            return FetchResult(
                body=bytes(body),
                url=str(response.url),
                charset=response.charset,
                content_type=response.content_type,
            )


async def safe_download(
    url: str,
    destination: Path,
    *,
    max_bytes: int,
    progress_callback: ProgressCallback = None,
    headers: Optional[dict] = None,
    connect_timeout: float = 15.0,
    read_timeout: float = 60.0,
) -> Path:
    """Стрімить файл на диск із лімітом розміру; при помилці недокачаний файл видаляється.

    Загальний таймаут не ставимо (архів на 2 ГБ легітимно качається довго), зате
    обмежуємо з'єднання і паузу між шматками — завислий сервер обірве завантаження.
    """
    client_timeout = aiohttp.ClientTimeout(total=None, sock_connect=connect_timeout, sock_read=read_timeout)
    try:
        async with _make_session(client_timeout, headers) as session:
            response = await _open_following_redirects(session, url)
            async with response:
                if response.status != 200:
                    raise FetchError(f"Сервер відповів HTTP {response.status}.", response.status)
                _check_declared_size(response, max_bytes)

                total = response.content_length or 0
                written = 0
                with open(destination, "wb") as file:
                    async for chunk in response.content.iter_chunked(_CHUNK_SIZE):
                        written += len(chunk)
                        if written > max_bytes:
                            raise ResponseTooLargeError(f"Файл більший за {max_bytes} байт.")
                        file.write(chunk)
                        if total and progress_callback:
                            await progress_callback(min(written / total * 100, 100.0))
        return destination
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
