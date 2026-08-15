from pathlib import Path

import pytest

from services.browser import BrowserService, SecurityChallengeError
from services.selectors import SECURITY_CHALLENGE_TEXT


class FakePage:
    def __init__(self) -> None:
        self.url = "https://www.google.com/sorry/"
        self.challenge_visible = True

    def wait_for_timeout(self, _milliseconds: int) -> None:
        self.challenge_visible = False
        self.url = "https://www.google.com/search?q=example"


def make_service(tmp_path: Path, *, headless: bool) -> BrowserService:
    return BrowserService(
        tmp_path / "browser-profile",
        headless=headless,
        timeout_seconds=1,
        manual_login_timeout_minutes=1,
    )


def test_visible_browser_waits_for_security_challenge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = make_service(tmp_path, headless=False)
    page = FakePage()

    monkeypatch.setattr(
        service,
        "_page_contains",
        lambda current_page, phrases: (
            current_page.challenge_visible if phrases == SECURITY_CHALLENGE_TEXT else False
        ),
    )

    service.ensure_authenticated(page)  # type: ignore[arg-type]


def test_headless_browser_reports_security_challenge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = make_service(tmp_path, headless=True)
    page = FakePage()

    monkeypatch.setattr(
        service,
        "_page_contains",
        lambda _page, phrases: phrases == SECURITY_CHALLENGE_TEXT,
    )

    with pytest.raises(SecurityChallengeError, match="HEADLESS=false"):
        service.ensure_authenticated(page)  # type: ignore[arg-type]
