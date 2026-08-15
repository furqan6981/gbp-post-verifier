from datetime import date, datetime, time
from enum import StrEnum
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class CheckStatus(StrEnum):
    PENDING = "pending"
    CHECKING = "checking"
    PUBLISHED = "published"
    NOT_FOUND = "not_found"
    RETRYING = "retrying"
    FAILED = "failed"
    DRAFT_CREATED = "draft_created"


class Client(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    client_name: str = Field(min_length=1)
    business_name: str = Field(min_length=1)
    google_profile_url: str = Field(pattern=r"^https://")
    client_email: EmailStr
    timezone: str
    check_time: time
    retry_interval_minutes: int = Field(ge=1)
    max_retries: int = Field(ge=1)
    active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"Unknown IANA timezone: {value}") from exc
        return value


class DailyPostCheck(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int | None = None
    client_id: int
    check_date: date
    status: CheckStatus
    attempts: int = 0
    screenshot_path: Path | None = None
    verified_at: datetime | None = None
    error_message: str | None = None
    gmail_draft_id: str | None = None
    message_id: str | None = None
    processing_owner: str | None = None
    lease_expires_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
