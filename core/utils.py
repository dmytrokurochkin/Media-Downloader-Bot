import asyncio
import datetime
import logging
import os
import shutil
import signal
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# Посилання на фонові задачі: event loop тримає лише слабкі посилання, тож задачу
# без власника теоретично може прибрати збирач сміття посеред виконання.
_background_tasks: set = set()


def spawn(coro) -> asyncio.Task:
    """asyncio.create_task, що зберігає посилання на задачу до її завершення."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def schedule_delete(bot_instance, chat_id: int, message_id: int, delay: int = 60) -> asyncio.Task:
    """Видалити повідомлення через `delay` секунд, не блокуючи хендлер."""
    return spawn(delete_later(bot_instance, chat_id, message_id, delay))


def text_matches(key: str):
    """Фільтр «текст дорівнює кнопці меню `key` будь-якою з мов бота»."""
    from aiogram import F
    from locales import get_text
    return F.text.in_([get_text(lang, key) for lang in ('uk', 'en', 'pl')])


# Що часто «прилипає» до посилання в кінці речення: «дивись https://youtu.be/x).»
_URL_TRAILING_JUNK = '.,;:!?)]}>»"\'\u2019\u201d'


def extract_url(text: Optional[str]) -> Optional[str]:
    """Перше посилання з тексту без пунктуації, що прилипла в кінці.

    URL_PATTERN бере все до пробілу, тож `(https://youtu.be/x).` перетворювалось
    на ID відео `x).` і завантаження падало.
    """
    if not text:
        return None
    from core.config import URL_PATTERN
    match = URL_PATTERN.search(text)
    if not match:
        return None
    url = match.group(0).split('<', 1)[0]
    while url and url[-1] in _URL_TRAILING_JUNK:
        # Закриваюча дужка — частина URL, якщо в ньому є парна відкриваюча
        # (`.../Python_(language)` у Вікіпедії), інакше це дужка з речення.
        if url[-1] == ')' and url.count('(') >= url.count(')'):
            break
        url = url[:-1]
    return url or None


def domain_matches(host: str, *domains: str) -> bool:
    """True, якщо `host` — це один із доменів або його піддомен."""
    host = (host or "").lower().rstrip(".")
    return any(host == domain or host.endswith("." + domain) for domain in domains)


def url_host(url: str) -> str:
    """Хост URL у нижньому регістрі; "" для URL, який urlsplit не розбирає (`http://[::1`)."""
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def host_matches(url: str, *domains: str) -> bool:
    """True, якщо хост URL — це один із доменів або його піддомен.

    Перевірка підрядком (`'instagram.com' in url`) ловила й `https://evil.com/?x=instagram.com`,
    тож маршрутизація йде лише за справжнім хостом.
    """
    return domain_matches(url_host(url), *domains)


def is_forbidden_url(url: str) -> bool:
    """Сторінки артистів/каналів (масове завантаження) на платформах, де бот їх не качає.

    Регексп FORBIDDEN_URL_PATTERN раніше застосовувався до всього URL на будь-якому
    сайті (хибні спрацювання на `/user/` деінде), а YouTube-канали виду `/@handle`
    проходили. Тепер правило діє лише для відомих платформ і по шляху.
    """
    from core.config import FORBIDDEN_URL_PATTERN
    host = url_host(url)
    path = urlsplit(url).path if host else ""
    if domain_matches(host, "youtube.com") and path.startswith("/@"):
        return True
    if domain_matches(host, "youtube.com", "youtu.be", "spotify.com", "soundcloud.com"):
        return bool(FORBIDDEN_URL_PATTERN.search(path))
    return False


def detect_language(telegram_language_code: Optional[str]) -> str:
    """Мова інтерфейсу для НОВОГО користувача за мовою його Telegram-клієнта."""
    code = (telegram_language_code or "").lower().split("-")[0]
    return code if code in ("uk", "en", "pl") else "en"

async def delete_later(bot_instance, chat_id: int, message_id: int, delay: int = 60):
    await asyncio.sleep(delay)
    try:
        await bot_instance.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass

def get_event_user(event):
    """Хто насправді надіслав апдейт.

    У guest_message (Bot API 10.0) `from_user` — це САМ БОТ, а справжній
    відправник лежить у `guest_bot_caller_user`. Middleware, які дивились лише
    на from_user, у гостьовому режимі перевіряли бан/ліміт самого бота.
    """
    caller = getattr(event, "guest_bot_caller_user", None)
    return caller or getattr(event, "from_user", None)


def parse_db_date(date_str: str) -> datetime.datetime:
    """Parses a SQLite ISO datetime string into an aware UTC datetime object."""
    if not date_str: return None
    try:
        dt = datetime.datetime.fromisoformat(date_str.replace(' ', 'T'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt
    except Exception:
        return None

@asynccontextmanager
async def temporary_download_session(session_dir: Path):
    """Context manager to ensure safe cleanup of downloaded files."""
    session_dir.mkdir(parents=True, exist_ok=True)
    try:
        yield session_dir
    finally:
        if session_dir.exists():
            try:
                # To prevent blocking the main thread during I/O
                await asyncio.to_thread(shutil.rmtree, session_dir, ignore_errors=True)
            except Exception as e:
                logger.warning("Failed to cleanup %s: %s", session_dir, e)


class CommandTimeoutError(Exception):
    """Зовнішня програма не вклалась у відведений час і була зупинена."""


def _kill_process_tree(proc) -> None:
    try:
        if os.name != "nt":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except ProcessLookupError:
        pass


async def run_command(cmd: list, *, timeout: float, name: str, env: dict = None) -> tuple:
    """Запускає програму без shell з таймаутом; повертає (код, stdout, stderr).

    Раніше subprocess.run без timeout міг висіти годинами (напр. spotdl, що чекає
    Retry-After від Spotify) і назавжди займав один із трьох слотів семафора
    завантажень. Процес стартує в окремій групі (start_new_session), тож при
    таймауті чи скасуванні вбивається разом із дочірніми (ffmpeg тощо).
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
        start_new_session=(os.name != "nt"),
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
        _kill_process_tree(proc)
        try:
            await asyncio.wait_for(proc.wait(), 10)
        except Exception:
            pass
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise CommandTimeoutError(f"{name} не завершився за {int(timeout)} с і був зупинений.") from None
    return proc.returncode, stdout.decode("utf-8", "replace"), stderr.decode("utf-8", "replace")


def cleanup_stale_downloads(root: Path = Path("downloads")) -> int:
    """Видаляє залишки тимчасових сесій, що лишились після рестарту посеред завантаження.

    Викликається лише на старті, коли жодне завантаження ще не йде. Інакше після
    кожного рестарту (а апдейтер yt-dlp перезапускає бота щотижня) диск поступово
    забивався недокачаними файлами.
    """
    if not root.exists():
        return 0
    removed = 0
    for child in root.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)
        removed += 1
    return removed
