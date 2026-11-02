import sqlite3
import stat

import pytest

from core import backup


def _make_db(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE payments (charge_id TEXT)")
    conn.execute("INSERT INTO payments VALUES ('ch_1')")
    conn.commit()
    return conn


def test_backup_copies_uncheckpointed_wal_data(tmp_path):
    db_path = tmp_path / "database.db"
    conn = _make_db(db_path)  # з'єднання відкрите: дані ще в -wal, а не в основному файлі
    try:
        target = backup.backup_database(db_path, tmp_path / "backups", keep=3)
    finally:
        conn.close()

    copy = sqlite3.connect(target)
    assert copy.execute("SELECT charge_id FROM payments").fetchall() == [("ch_1",)]
    copy.close()
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert not list((tmp_path / "backups").glob("*.part"))


def test_prune_keeps_newest(tmp_path):
    names = [f"database-2026010{i}-000000.db" for i in range(1, 6)]
    for name in names:
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "unrelated.txt").write_text("keep me")

    removed = backup.prune_backups(tmp_path, keep=2)

    assert sorted(p.name for p in removed) == names[:3]
    assert sorted(p.name for p in tmp_path.glob("database-*.db")) == names[3:]
    assert (tmp_path / "unrelated.txt").exists()


def test_backup_missing_database_fails_loudly(tmp_path, capsys):
    assert backup.main(["--db", str(tmp_path / "nope.db"), "--dir", str(tmp_path / "b")]) == 1
    assert "Backup failed" in capsys.readouterr().err


def test_backup_rejects_corrupt_copy(tmp_path, monkeypatch):
    db_path = tmp_path / "database.db"
    _make_db(db_path).close()

    monkeypatch.setattr(backup, "check_integrity", lambda conn: "*** corrupt ***")

    with pytest.raises(RuntimeError, match="integrity"):
        backup.backup_database(db_path, tmp_path / "backups", keep=3)
    assert not list((tmp_path / "backups").iterdir())
