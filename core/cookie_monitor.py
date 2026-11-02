"""
Стан кук сервісів і сповіщення адмінів, коли доступ до контенту ламається.

Куки сторонніх сервісів рано чи пізно вмирають (вихід з акаунта, перевірка безпеки,
блокування IP), і цього не уникнути. Але раніше про це дізнавались від користувачів,
тижнями пізніше. Тепер перший же збій приходить адміну з поясненням, що робити.
"""

import html
import logging
import time
from typing import Dict, Optional

from aiogram.exceptions import TelegramAPIError
from aiogram.types import LinkPreviewOptions

from core import cookies
from core.config import ADMIN_IDS
from locales import get_text

logger = logging.getLogger(__name__)

# Одна й та сама проблема (сервіс + тип) — не частіше ніж раз на 6 годин: якщо куки
# померли, кожне наступне завантаження впиратиметься в те саме.
ALERT_COOLDOWN = 6 * 3600
# Успішне використання кук пишемо в БД не частіше ніж раз на 10 хвилин.
OK_WRITE_INTERVAL = 600

_last_alert: Dict[tuple, float] = {}
_last_ok_write: Dict[str, float] = {}


def hint_key(kind: str, had_cookies: bool) -> str:
    if kind == 'rate_limited':
        return 'cookie_hint_rate'
    if not had_cookies:
        return 'cookie_hint_missing'
    return {
        'cookies_invalid': 'cookie_hint_refresh',
        'bot_check': 'cookie_hint_bot_check',
        'age_restricted': 'cookie_hint_age',
        'login_required': 'cookie_hint_login',
    }.get(kind, 'cookie_hint_refresh')


def alert_text(lang: str, error, url: str) -> str:
    return get_text(
        lang, 'cookie_alert',
        service=html.escape(cookies.service_title(error.service)),
        problem=get_text(lang, f'cookie_problem_{error.kind}'),
        hint=get_text(lang, hint_key(error.kind, error.had_cookies)),
        detail=html.escape(str(error)[:300]),
        url=html.escape(url[:200]),
    )


async def report_success(service: Optional[str]) -> None:
    if not service:
        return
    now = time.monotonic()
    if now - _last_ok_write.get(service, -OK_WRITE_INTERVAL) < OK_WRITE_INTERVAL:
        return
    _last_ok_write[service] = now
    from database import record_cookie_ok
    await record_cookie_ok(service)


async def report_problem(bot, error, url: str) -> bool:
    """Записує проблему й (з обмеженням частоти) пише адмінам. True — якщо сповіщення пішло."""
    if error.service is None:
        # Сайт поза списком сервісів із куками: адмін нічим не допоможе.
        return False
    from database import get_user, record_cookie_error
    if error.kind in cookies.ALERT_KINDS:
        await record_cookie_error(error.service, f"{error.kind}: {error}")
    else:
        return False

    key = (error.service, error.kind, error.had_cookies)
    now = time.monotonic()
    if key in _last_alert and now - _last_alert[key] < ALERT_COOLDOWN:
        return False
    _last_alert[key] = now

    sent = False
    for admin_id in ADMIN_IDS:
        admin = await get_user(admin_id)
        lang = admin['language_code'] if admin else 'uk'
        try:
            await bot.send_message(admin_id, alert_text(lang, error, url),
                                   link_preview_options=LinkPreviewOptions(is_disabled=True))
            sent = True
        except TelegramAPIError as e:
            logger.warning("Could not send cookie alert to %s: %s", admin_id, e)
    return sent


def reset_alerts(service: str) -> None:
    """Після оновлення кук наступна проблема знову має дійти до адміна одразу."""
    for key in [k for k in _last_alert if k[0] == service]:
        del _last_alert[key]
