from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from services.gbp_checker import GoogleBusinessProfileChecker


class EmptyLocator:
    def count(self) -> int:
        return 0


class TextCard:
    def __init__(self, text: str) -> None:
        self.text = text

    def inner_text(self) -> str:
        return self.text

    def get_attribute(self, _attribute: str) -> None:
        return None

    def locator(self, _selector: str) -> EmptyLocator:
        return EmptyLocator()


def test_yesterday_matches_previous_local_date() -> None:
    timezone_name = "Asia/Karachi"
    today = datetime.now(ZoneInfo(timezone_name)).date()
    card = TextCard("Posted yesterday")

    assert GoogleBusinessProfileChecker._card_matches_date(
        card, today - timedelta(days=1), timezone_name  # type: ignore[arg-type]
    )
    assert not GoogleBusinessProfileChecker._card_matches_date(
        card, today, timezone_name  # type: ignore[arg-type]
    )


def test_days_ago_matches_relative_local_date() -> None:
    timezone_name = "Asia/Karachi"
    today = datetime.now(ZoneInfo(timezone_name)).date()
    card = TextCard("Posted 2 days ago")

    assert GoogleBusinessProfileChecker._card_matches_date(
        card, today - timedelta(days=2), timezone_name  # type: ignore[arg-type]
    )
