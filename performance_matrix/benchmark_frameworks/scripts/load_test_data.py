#!/usr/bin/env python3.14
"""scripts/load_test_data.py

Insert 1000 sample BlogPost records into every framework's SQLite database.
Run after create_projects.sh has migrated/initialised all databases.

Usage:
    cd benchmark_frameworks
    python3.14 scripts/load_test_data.py
"""

from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DB_PATHS = {
    "openviper": ROOT / "openviper_blog" / "db.sqlite3",
    "fastapi":   ROOT / "fastapi_blog"   / "db.sqlite3",
    "flask":     ROOT / "flask_blog"     / "db.sqlite3",
    "django":    ROOT / "django_blog"    / "db.sqlite3",
}

RECORDS = 1_000
NOW = datetime.datetime.utcnow().isoformat(sep=" ", timespec="seconds")


def _insert(db_path: Path, framework: str) -> None:
    if not db_path.exists():
        print(f"  [SKIP] {db_path} does not exist – run create_projects.sh first")
        return

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Ensure the table exists (Django uses "posts" too via db_table meta).
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS posts (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            title      TEXT    NOT NULL,
            content    TEXT    NOT NULL,
            created_at TEXT    NOT NULL
        )
        """
    )

    rows = [
        (f"Sample Blog Post {n}", "Benchmark content body", NOW)
        for n in range(1, RECORDS + 1)
    ]
    cur.executemany("INSERT INTO posts (title, content, created_at) VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()
    print(f"  [OK]   {framework}: inserted {RECORDS} records → {db_path}")


def main() -> None:
    print(f"Loading {RECORDS} sample records into each database …\n")
    for framework, path in DB_PATHS.items():
        _insert(path, framework)
    print("\nDone.")


if __name__ == "__main__":
    main()
