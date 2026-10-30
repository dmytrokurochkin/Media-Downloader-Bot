import asyncio
import datetime
import os
import shutil
import signal
from pathlib import Path
from contextlib import asynccontextmanager

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
                print(f"Failed to cleanup {session_dir}: {e}")


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
