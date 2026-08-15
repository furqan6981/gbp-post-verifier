import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from filelock import FileLock
from playwright.sync_api import BrowserContext, Page, sync_playwright

from services.selectors import LOGIN_TEXT, SECURITY_CHALLENGE_TEXT


logger = logging.getLogger(__name__)


class LoginRequiredError(RuntimeError):
    pass


class SecurityChallengeError(RuntimeError):
    pass


class BrowserService:
    _profile_lock = threading.Lock()

    def __init__(
        self,
        profile_dir: Path,
        *,
        headless: bool,
        timeout_seconds: int,
        manual_login_timeout_minutes: int,
    ):
        self.profile_dir = profile_dir
        self.headless = headless
        self.timeout_ms = timeout_seconds * 1000
        self.manual_login_timeout_seconds = manual_login_timeout_minutes * 60

    @contextmanager
    def page(self, timezone_id: str) -> Iterator[Page]:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Launching persistent Chromium context", extra={"event": "browser_launch"})
        lock_path = self.profile_dir.parent / f".{self.profile_dir.name}.lock"
        with self._profile_lock, FileLock(lock_path, timeout=5):
            with sync_playwright() as playwright:
                context: BrowserContext | None = None
                try:
                    context = playwright.chromium.launch_persistent_context(
                        user_data_dir=str(self.profile_dir),
                        headless=self.headless,
                        viewport={"width": 1440, "height": 1000},
                        locale="en-US",
                        timezone_id=timezone_id,
                        args=["--disable-dev-shm-usage"],
                    )
                    context.set_default_timeout(self.timeout_ms)
                    page = context.pages[0] if context.pages else context.new_page()
                    yield page
                finally:
                    if context is not None:
                        context.close()

    @staticmethod
    def _page_contains(page: Page, phrases: tuple[str, ...]) -> bool:
        body = page.locator("body")
        if body.count() == 0:
            return False
        text = body.inner_text(timeout=5000).lower()
        return any(phrase.lower() in text for phrase in phrases)

    def ensure_authenticated(self, page: Page) -> None:
        if self._page_contains(page, SECURITY_CHALLENGE_TEXT):
            raise SecurityChallengeError(
                "Google displayed a CAPTCHA/security challenge. Complete it manually; "
                "the application will not bypass it."
            )

        login_url = "accounts.google." in page.url
        if not login_url and not self._page_contains(page, LOGIN_TEXT):
            return
        if self.headless:
            raise LoginRequiredError(
                "Google login is required. Set HEADLESS=false and run --test-client "
                "to complete login manually."
            )

        logger.warning(
            "Google login is required. Complete login in the open browser window. "
            "No password is stored by this application.",
            extra={"event": "manual_login_required"},
        )
        deadline = time.monotonic() + self.manual_login_timeout_seconds
        while time.monotonic() < deadline:
            page.wait_for_timeout(2000)
            if self._page_contains(page, SECURITY_CHALLENGE_TEXT):
                logger.warning(
                    "A Google security challenge needs manual completion.",
                    extra={"event": "security_challenge"},
                )
                continue
            if "accounts.google." not in page.url and not self._page_contains(
                page, LOGIN_TEXT
            ):
                logger.info("Manual Google login completed", extra={"event": "login_complete"})
                return
        raise LoginRequiredError("Timed out waiting for manual Google login")
