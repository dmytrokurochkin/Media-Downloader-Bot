import os
import sys
from pathlib import Path

import pytest_asyncio

# core/loader.py створює Bot(token=...) уже при імпорті хендлерів. Заглушка ставиться ДО
# load_dotenv() (той не перезаписує наявні змінні), тож тести ніколи не беруть справжній
# токен з .env і не потребують його в CI.
os.environ.setdefault("BOT_TOKEN", "123456:FAKE-TOKEN-FOR-CI-0000000000")

# Make the project root importable when pytest is run from elsewhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import database


@pytest_asyncio.fixture
async def db(tmp_path, monkeypatch):
    """Gives each test a fresh, isolated SQLite database with the full schema applied."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(database, "DB_PATH", db_path)
    # The active-ad cache is a long-lived in-process cache in production (by design),
    # but that makes it leak between tests unless it's reset alongside the DB itself.
    monkeypatch.setitem(database._ad_cache, "text", None)
    monkeypatch.setitem(database._ad_cache, "timestamp", 0)
    # Те саме з кешем лідербордів: інакше тест бачив би топ, порахований для БД попереднього.
    monkeypatch.setattr(database, "_leaderboard_cache", {})

    await database.init_db_connection()
    await database.init_db()

    yield database

    await database.close_db_connection()
