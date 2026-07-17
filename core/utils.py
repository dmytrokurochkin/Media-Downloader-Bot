import asyncio
import datetime
import shutil
from pathlib import Path
from contextlib import asynccontextmanager

async def delete_later(bot_instance, chat_id: int, message_id: int, delay: int = 60):
    await asyncio.sleep(delay)
    try:
        await bot_instance.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass

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
