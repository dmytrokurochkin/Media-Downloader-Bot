"""
Резервна копія бази: `python -m core.backup [--keep N]`.

Запускається щодня systemd-таймером (див. auto_deploy.sh). Копія робиться через
SQLite online backup API, а не `cp`: база працює в WAL-режимі, і сирий файл без
-wal під час запису бота — це неузгоджений знімок. У базі лежать журнал платежів
і VIP-статуси, тож втрата диска без копії означала б втрату оплачених покупок.
"""

from __future__ import annotations

import argparse
import datetime
import os
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = Path("database.db")
DEFAULT_DIR = Path("backups")
DEFAULT_KEEP = 14
PREFIX = "database-"


def backup_database(db_path: Path = DEFAULT_DB, backup_dir: Path = DEFAULT_DIR, keep: int = DEFAULT_KEEP) -> Path:
    """Робить узгоджену копію `db_path` у `backup_dir` і лишає `keep` найновіших копій."""
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Копії містять те саме, що й база (платежі, ID користувачів), — лише для власника.
    backup_dir.chmod(0o700)

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"{PREFIX}{stamp}.db"
    partial = target.with_suffix(".db.part")

    try:
        source = sqlite3.connect(db_path, timeout=30)
        try:
            dest = sqlite3.connect(partial)
            try:
                source.backup(dest)
                result = check_integrity(dest)
            finally:
                dest.close()
        finally:
            source.close()

        if result != "ok":
            raise RuntimeError(f"Backup failed integrity check: {result}")

        os.chmod(partial, 0o600)
        # Атомарне перейменування: недописана копія ніколи не виглядає як готова.
        partial.replace(target)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise

    prune_backups(backup_dir, keep)
    return target


def check_integrity(conn: sqlite3.Connection) -> str:
    # Перевіряємо саме копію: бита копія гірша за відсутню — про неї дізнаються
    # лише в день, коли вона знадобиться.
    return conn.execute("PRAGMA quick_check").fetchone()[0]


def prune_backups(backup_dir: Path, keep: int) -> list:
    """Видаляє найстаріші копії понад `keep`. Повертає видалені шляхи."""
    backups = sorted(backup_dir.glob(f"{PREFIX}*.db"))
    stale = backups[:-keep] if keep > 0 else backups
    for path in stale:
        path.unlink(missing_ok=True)
    return stale


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="Back up the bot database.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP, help="how many newest backups to keep")
    args = parser.parse_args(argv)

    try:
        target = backup_database(args.db, args.dir, max(args.keep, 1))
    except (OSError, sqlite3.Error, RuntimeError) as exc:
        print(f"Backup failed: {exc}", file=sys.stderr)
        return 1
    print(f"Backup written: {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
