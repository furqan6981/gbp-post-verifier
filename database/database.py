import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_name TEXT NOT NULL,
    business_name TEXT NOT NULL,
    google_profile_url TEXT NOT NULL,
    client_email TEXT NOT NULL,
    timezone TEXT NOT NULL,
    check_time TEXT NOT NULL,
    retry_interval_minutes INTEGER NOT NULL CHECK (retry_interval_minutes > 0),
    max_retries INTEGER NOT NULL CHECK (max_retries > 0),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_post_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    check_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('pending', 'checking', 'published', 'not_found',
                   'retrying', 'failed', 'draft_created')
    ),
    attempts INTEGER NOT NULL DEFAULT 0,
    screenshot_path TEXT,
    verified_at TEXT,
    error_message TEXT,
    gmail_draft_id TEXT,
    message_id TEXT,
    processing_owner TEXT,
    lease_expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (client_id, check_date)
);

CREATE INDEX IF NOT EXISTS idx_clients_active ON clients(active);
CREATE INDEX IF NOT EXISTS idx_checks_date_status
    ON daily_post_checks(check_date, status);
"""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            existing = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(daily_post_checks)"
                ).fetchall()
            }
            migrations = {
                "message_id": "ALTER TABLE daily_post_checks ADD COLUMN message_id TEXT",
                "processing_owner": (
                    "ALTER TABLE daily_post_checks ADD COLUMN processing_owner TEXT"
                ),
                "lease_expires_at": (
                    "ALTER TABLE daily_post_checks ADD COLUMN lease_expires_at TEXT"
                ),
            }
            for column, statement in migrations.items():
                if column not in existing:
                    connection.execute(statement)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
