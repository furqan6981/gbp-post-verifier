from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo


def now_in_timezone(timezone_name: str, now: datetime | None = None) -> datetime:
    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        raise ValueError("A timezone-aware datetime is required")
    return reference.astimezone(ZoneInfo(timezone_name))


def today_in_timezone(timezone_name: str, now: datetime | None = None) -> date:
    return now_in_timezone(timezone_name, now).date()


def date_tokens(target: date) -> set[str]:
    """Common English date strings used by Google Search result cards."""
    return {
        target.isoformat(),
        target.strftime("%b %d, %Y").replace(" 0", " "),
        target.strftime("%B %d, %Y").replace(" 0", " "),
        target.strftime("%m/%d/%Y"),
        target.strftime("%m/%d/%y"),
    }
