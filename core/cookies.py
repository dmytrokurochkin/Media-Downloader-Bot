"""
Куки для завантажувачів (yt-dlp, gallery-dl).

Чому все не так просто, як «передати cookies.txt»: yt-dlp після КОЖНОГО завантаження
перезаписує файл, переданий як cookiefile, причому неатомарно (truncate + write), а
gallery-dl за замовчуванням зберігає туди свою копію сесії (`cookies-update`). При
паралельних завантаженнях один процес читав напівзаписаний файл і потім зберігав його
назад — авторизаційні куки зникали, а свіжі, щойно «прокручені» YouTube, затирались
старими. Звідси «куки постійно ламаються».

Тепер `cookies.txt` змінює лише бот (атомарно, при імпорті), а кожне завантаження
отримує власну копію з куками лише потрібного сервісу у своїй тимчасовій теці.
"""

from __future__ import annotations

import datetime
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from core.utils import domain_matches, url_host

COOKIES_FILE = Path("cookies.txt")
NETSCAPE_HEADER = "# Netscape HTTP Cookie File\n"
HTTPONLY_PREFIX = "#HttpOnly_"
MAX_UPLOAD_BYTES = 1024 * 1024

# Сервіси, для яких бот зберігає куки. Решту з експорту браузера відкидаємо: там можуть
# бути куки пошти чи банку, а боту вони ні до чого.
#   hosts   — за якими доменами посилання визначаємо сервіс;
#   domains — до яких доменів належать його куки;
#   auth    — куки, наявність яких означає «увійдено в акаунт».
SERVICES: Dict[str, dict] = {
    'youtube': {
        'title': 'YouTube',
        'hosts': ('youtube.com', 'youtu.be'),
        'domains': ('youtube.com',),
        'auth': ('SAPISID', '__Secure-3PAPISID', '__Secure-1PAPISID', 'LOGIN_INFO'),
    },
    'instagram': {
        'title': 'Instagram',
        'hosts': ('instagram.com',),
        'domains': ('instagram.com',),
        'auth': ('sessionid',),
    },
    'tiktok': {
        'title': 'TikTok',
        'hosts': ('tiktok.com',),
        'domains': ('tiktok.com',),
        'auth': ('sessionid', 'sid_tt'),
    },
    'facebook': {
        'title': 'Facebook',
        'hosts': ('facebook.com', 'fb.watch'),
        'domains': ('facebook.com',),
        'auth': ('c_user', 'xs'),
    },
    'x': {
        'title': 'X (Twitter)',
        'hosts': ('x.com', 'twitter.com'),
        'domains': ('x.com', 'twitter.com'),
        'auth': ('auth_token',),
    },
    'soundcloud': {
        'title': 'SoundCloud',
        'hosts': ('soundcloud.com',),
        'domains': ('soundcloud.com',),
        'auth': ('oauth_token',),
    },
}


class CookieFileError(ValueError):
    """Файл не схожий на Netscape cookies.txt або не містить кук відомих сервісів.

    `key` — ключ локалі з поясненням для адміна.
    """

    def __init__(self, key: str):
        super().__init__(key)
        self.key = key


@dataclass
class CookieLine:
    raw: str          # рядок як у файлі (зокрема з префіксом #HttpOnly_)
    domain: str       # домен без префікса й крапки, у нижньому регістрі
    name: str
    expires: int      # unix-час; 0 — сесійна кука


@dataclass
class ServiceSummary:
    service: str
    count: int = 0
    authenticated: bool = False
    auth_expires: Optional[datetime.datetime] = None   # найраніший термін серед auth-кук
    auth_names: List[str] = field(default_factory=list)


def service_title(service: Optional[str]) -> str:
    return SERVICES.get(service, {}).get('title', service or '?')


def service_for_url(url: str) -> Optional[str]:
    host = url_host(url)
    for service, spec in SERVICES.items():
        if domain_matches(host, *spec['hosts']):
            return service
    return None


def service_for_domain(domain: str) -> Optional[str]:
    for service, spec in SERVICES.items():
        if domain_matches(domain, *spec['domains']):
            return service
    return None


def parse_line(line: str) -> Optional[CookieLine]:
    """Рядок Netscape cookies.txt → CookieLine; None для коментарів і сміття.

    `#HttpOnly_` — не коментар: так розширення браузерів позначають HttpOnly-куки, і саме
    серед них авторизаційні (наприклад, `__Secure-3PSID` YouTube). Пропустити їх як
    коментарі — означає «зламати» вхід.
    """
    line = line.rstrip("\r\n")
    if not line.strip():
        return None
    body = line[len(HTTPONLY_PREFIX):] if line.startswith(HTTPONLY_PREFIX) else line
    if body.startswith("#"):
        return None
    parts = body.split("\t")
    if len(parts) != 7:
        return None
    domain, _subdomains, _path, _secure, expires, name, _value = parts
    try:
        expires_ts = int(float(expires or 0))
    except ValueError:
        return None
    domain = domain.strip().lstrip(".").lower()
    if not domain or not name:
        return None
    return CookieLine(raw=line, domain=domain, name=name, expires=expires_ts)


def parse_cookies(text: str) -> Dict[str, List[CookieLine]]:
    """Розбирає вміст cookies.txt і групує куки за сервісами (інші домени відкидає)."""
    grouped: Dict[str, List[CookieLine]] = {}
    for raw in text.lstrip("﻿").splitlines():
        cookie = parse_line(raw)
        if cookie is None:
            continue
        service = service_for_domain(cookie.domain)
        if service is not None:
            grouped.setdefault(service, []).append(cookie)
    return grouped


def count_cookie_lines(text: str) -> int:
    return sum(1 for raw in text.lstrip("﻿").splitlines() if parse_line(raw) is not None)


def summarize(service: str, cookies: List[CookieLine]) -> ServiceSummary:
    auth_names = SERVICES[service]['auth']
    summary = ServiceSummary(service=service, count=len(cookies))
    for cookie in cookies:
        if cookie.name not in auth_names:
            continue
        summary.authenticated = True
        summary.auth_names.append(cookie.name)
        if cookie.expires > 0:
            expires = datetime.datetime.fromtimestamp(cookie.expires, datetime.timezone.utc)
            if summary.auth_expires is None or expires < summary.auth_expires:
                summary.auth_expires = expires
    return summary


def load_master(path: Optional[Path] = None) -> Dict[str, List[CookieLine]]:
    path = path or COOKIES_FILE
    try:
        return parse_cookies(path.read_text(encoding="utf-8", errors="replace"))
    except FileNotFoundError:
        return {}


def has_cookies(service: Optional[str], path: Optional[Path] = None) -> bool:
    path = path or COOKIES_FILE
    return bool(service) and bool(load_master(path).get(service))


def _render(grouped: Dict[str, List[CookieLine]]) -> str:
    lines = [NETSCAPE_HEADER, "# Файл веде бот: оновлюйте через /cookies або заміною файлу.\n\n"]
    for service in SERVICES:
        for cookie in grouped.get(service, []):
            lines.append(cookie.raw + "\n")
    return "".join(lines)


def _write_private(path: Path, content: str) -> None:
    """Атомарний запис із правами 0600: читач ніколи не бачить напівзаписаний файл."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".cookies-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            fp.write(content)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def import_cookies(text: str, path: Optional[Path] = None) -> Dict[str, ServiceSummary]:
    """Додає куки з експорту браузера в cookies.txt.

    Замінюються лише сервіси, які є у файлі; куки інших сервісів лишаються. Тож можна
    оновити Instagram, не чіпаючи YouTube.
    """
    path = path or COOKIES_FILE
    if count_cookie_lines(text) == 0:
        raise CookieFileError('cookies_bad_format')
    uploaded = parse_cookies(text)
    if not uploaded:
        raise CookieFileError('cookies_no_known')
    merged = load_master(path)
    merged.update(uploaded)
    _write_private(path, _render(merged))
    return {service: summarize(service, cookies) for service, cookies in uploaded.items()}


def clear_service(service: str, path: Optional[Path] = None) -> bool:
    path = path or COOKIES_FILE
    merged = load_master(path)
    if service not in merged:
        return False
    del merged[service]
    _write_private(path, _render(merged))
    return True


def status(path: Optional[Path] = None) -> Dict[str, ServiceSummary]:
    path = path or COOKIES_FILE
    master = load_master(path)
    return {service: summarize(service, master.get(service, [])) for service in SERVICES}


def cookiefile_for(url: str, session_dir: Path, path: Optional[Path] = None) -> Optional[Path]:
    """Копія кук потрібного сервісу для одного завантаження (або None, якщо кук немає).

    Інструмент може переписувати цю копію скільки завгодно — майстер-файл від цього не
    страждає, а тека сесії видаляється разом із копією. Копія лежить у прихованій
    підтеці `.cookies`: серед файлів сесії її не можна прийняти за завантажене медіа й
    надіслати користувачу.
    """
    path = path or COOKIES_FILE
    service = service_for_url(url)
    if service is None:
        return None
    cookies = load_master(path).get(service)
    if not cookies:
        return None
    copy_path = session_dir / ".cookies" / f"{service}.txt"
    _write_private(copy_path, _render({service: cookies}))
    return copy_path


# --- розпізнавання проблем із доступом ---

# Порядок важливий: перший збіг перемагає. Повідомлення yt-dlp для Instagram, наприклад,
# містить і «rate-limit», і «login required» — вирішальним має бути вхід.
_AUTH_PATTERNS = (
    ('cookies_invalid', ("cookies are no longer valid", "redirect to challenge page", "checkpoint_required",
                         "challenge_required")),
    ('bot_check', ("not a bot",)),
    ('age_restricted', ("confirm your age", "age-restricted", "age restricted", "inappropriate for some users",
                        "may not be comfortable for some audiences", "age verification")),
    # Приватне відео, закритий профіль чи контент для спонсорів каналу: куки бота тут
    # не допоможуть, бо його акаунт не має доступу. Це не збій, адміна не турбуємо.
    ('private', ("private video", "this video is private", "account is private", "members-only",
                 "join this channel")),
    ('login_required', ("login required", "log in to", "sign in to view", "requires authentication",
                        "redirect to login page", "redirect to home page", "use --cookies", "you must log in",
                        "http error 401", "401 unauthorized")),
    # Не просто «429»: ці цифри трапляються в ID відео й розмірах файлів.
    ('rate_limited', ("rate-limit", "rate limit", "http error 429", "too many requests",
                      "please wait a few minutes", "try again later")),
)

# Що варто показати адміну: «private» — це властивість самого контенту, не кук.
ALERT_KINDS = ('cookies_invalid', 'bot_check', 'age_restricted', 'login_required', 'rate_limited')


def classify_auth_problem(messages) -> Optional[str]:
    text = " ".join(str(m) for m in messages if m).lower()
    if not text:
        return None
    for kind, needles in _AUTH_PATTERNS:
        if any(needle in text for needle in needles):
            return kind
    return None
