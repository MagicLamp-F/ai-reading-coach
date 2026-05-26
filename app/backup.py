from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path


def backup_sqlite_database(
    database_path: Path,
    backup_dir: Path,
    keep: int = 14,
    timestamp: datetime | None = None,
) -> Path:
    if keep < 1:
        raise ValueError("keep must be at least 1")
    if not database_path.exists():
        raise FileNotFoundError(f"database not found: {database_path}")

    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = (timestamp or datetime.now()).strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"reading_coach_{stamp}.db"

    source = sqlite3.connect(database_path)
    try:
        destination = sqlite3.connect(backup_path)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()

    _prune_backups(backup_dir, keep)
    return backup_path


def _prune_backups(backup_dir: Path, keep: int) -> None:
    backups = sorted(
        backup_dir.glob("reading_coach_*.db"),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    for path in backups[keep:]:
        path.unlink()
