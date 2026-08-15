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
        security_challenge = self._page_contains(page, SECURITY_CHALLENGE_TEXT)
        login_url = "accounts.google." in page.url
        login_prompt = self._page_contains(page, LOGIN_TEXT)
        if not security_challenge and not login_url and not login_prompt:
            return

        if self.headless:
            if security_challenge:
                raise SecurityChallengeError(
                    "Google displayed a CAPTCHA/security challenge. Set HEADLESS=false "
                    "and run --test-client to complete it manually."
                )
            raise LoginRequiredError(
                "Google login is required. Set HEADLESS=false and run --test-client "
                "to complete login manually."
            )

        if security_challenge:
            logger.warning(
                "Google displayed a security challenge. Complete it in the open browser "
                "window; the application will wait but will not bypass it.",
                extra={"event": "security_challenge"},
            )
        else:
            logger.warning(
                "Google login is required. Complete login in the open browser window. "
                "No password is stored by this application.",
                extra={"event": "manual_login_required"},
            )

        deadline = time.monotonic() + self.manual_login_timeout_seconds
        while time.monotonic() < deadline:
            page.wait_for_timeout(2000)
            security_challenge = self._page_contains(page, SECURITY_CHALLENGE_TEXT)
            login_url = "accounts.google." in page.url
            login_prompt = self._page_contains(page, LOGIN_TEXT)
            if not security_challenge and not login_url and not login_prompt:
                logger.info("Manual Google login completed", extra={"event": "login_complete"})
                return

        if security_challenge:
            raise SecurityChallengeError(
                "Timed out waiting for the Google security challenge to be completed"
            )
        raise LoginRequiredError("Timed out waiting for manual Google login")
