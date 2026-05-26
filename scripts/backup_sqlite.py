from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.backup import backup_sqlite_database
from app.cli import _load_env_file
from app.config import Settings


def main() -> None:
    _load_env_file(Path(".env"))
    settings = Settings.from_env()
    backup_path = backup_sqlite_database(settings.database_path, Path("backups"), keep=14)
    print(f"Created backup: {backup_path}")


if __name__ == "__main__":
    main()
