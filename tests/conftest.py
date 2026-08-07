import sys
from pathlib import Path

import pytest_asyncio

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

    await database.init_db_connection()
    await database.init_db()

    yield database

    await database.close_db_connection()
