from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

from database.database import Database
from database.models import CheckStatus, Client, DailyPostCheck


def utc_now() -> datetime:
    return datetime.now(UTC)


class ClientRepository:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _from_row(row: Any) -> Client:
        values = dict(row)
        values["active"] = bool(values["active"])
        values["check_time"] = time.fromisoformat(values["check_time"])
        values["created_at"] = datetime.fromisoformat(values["created_at"])
        values["updated_at"] = datetime.fromisoformat(values["updated_at"])
        return Client.model_validate(values)

    def add(self, client: Client) -> Client:
        now = utc_now().isoformat()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO clients (
                    client_name, business_name, google_profile_url, client_email,
                    timezone, check_time, retry_interval_minutes, max_retries,
                    active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    client.client_name,
                    client.business_name,
                    client.google_profile_url,
                    str(client.client_email),
                    client.timezone,
                    client.check_time.isoformat(timespec="minutes"),
                    client.retry_interval_minutes,
                    client.max_retries,
                    int(client.active),
                    now,
                    now,
                ),
            )
            client_id = int(cursor.lastrowid)
        result = self.get(client_id)
        if result is None:
            raise RuntimeError("Client insert did not persist")
        return result

    def get(self, client_id: int) -> Client | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM clients WHERE id = ?", (client_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def list_active(self) -> list[Client]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM clients WHERE active = 1 ORDER BY client_name"
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_all(self) -> list[Client]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM clients ORDER BY client_name"
            ).fetchall()
        return [self._from_row(row) for row in rows]


class CheckRepository:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _from_row(row: Any) -> DailyPostCheck:
        values = dict(row)
        values["check_date"] = date.fromisoformat(values["check_date"])
        values["status"] = CheckStatus(values["status"])
        if values["screenshot_path"]:
            values["screenshot_path"] = Path(values["screenshot_path"])
        for key in ("verified_at", "lease_expires_at", "created_at", "updated_at"):
            if values[key]:
                values[key] = datetime.fromisoformat(values[key])
        return DailyPostCheck.model_validate(values)

    def get(self, client_id: int, check_date: date) -> DailyPostCheck | None:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM daily_post_checks
                WHERE client_id = ? AND check_date = ?
                """,
                (client_id, check_date.isoformat()),
            ).fetchone()
        return self._from_row(row) if row else None

    def get_or_create(self, client_id: int, check_date: date) -> DailyPostCheck:
        now = utc_now().isoformat()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO daily_post_checks (
                    client_id, check_date, status, attempts, created_at, updated_at
                ) VALUES (?, ?, ?, 0, ?, ?)
                """,
                (
                    client_id,
                    check_date.isoformat(),
                    CheckStatus.PENDING.value,
                    now,
                    now,
                ),
            )
        result = self.get(client_id, check_date)
        if result is None:
            raise RuntimeError("Daily check could not be created")
        return result

    def start_attempt(self, check_id: int) -> DailyPostCheck:
        now = utc_now().isoformat()
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE daily_post_checks
                SET status = ?, attempts = attempts + 1, error_message = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (CheckStatus.CHECKING.value, now, check_id),
            )
        return self.get_by_id(check_id)

    def update(
        self,
        check_id: int,
        status: CheckStatus,
        *,
        screenshot_path: Path | None = None,
        verified_at: datetime | None = None,
        error_message: str | None = None,
        gmail_draft_id: str | None = None,
        message_id: str | None = None,
    ) -> DailyPostCheck:
        now = utc_now().isoformat()
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE daily_post_checks SET
                    status = ?,
                    screenshot_path = COALESCE(?, screenshot_path),
                    verified_at = COALESCE(?, verified_at),
                    error_message = ?,
                    gmail_draft_id = COALESCE(?, gmail_draft_id),
                    message_id = COALESCE(?, message_id),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    status.value,
                    str(screenshot_path) if screenshot_path else None,
                    verified_at.isoformat() if verified_at else None,
                    error_message,
                    gmail_draft_id,
                    message_id,
                    now,
                    check_id,
                ),
            )
        return self.get_by_id(check_id)

    def claim(self, check_id: int, owner: str, lease_expires_at: datetime) -> bool:
        now = utc_now().isoformat()
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE daily_post_checks
                SET processing_owner = ?, lease_expires_at = ?, updated_at = ?
                WHERE id = ?
                  AND status != ?
                  AND (
                      processing_owner IS NULL
                      OR lease_expires_at IS NULL
                      OR lease_expires_at < ?
                      OR processing_owner = ?
                  )
                """,
                (
                    owner,
                    lease_expires_at.isoformat(),
                    now,
                    check_id,
                    CheckStatus.DRAFT_CREATED.value,
                    now,
                    owner,
                ),
            )
            return cursor.rowcount == 1

    def release(self, check_id: int, owner: str) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE daily_post_checks
                SET processing_owner = NULL, lease_expires_at = NULL, updated_at = ?
                WHERE id = ? AND processing_owner = ?
                """,
                (utc_now().isoformat(), check_id, owner),
            )

    def get_by_id(self, check_id: int) -> DailyPostCheck:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM daily_post_checks WHERE id = ?", (check_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Daily check {check_id} does not exist")
        return self._from_row(row)
