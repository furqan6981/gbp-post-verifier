import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import StrEnum
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from playwright.sync_api import Locator, Page, TimeoutError as PlaywrightTimeoutError

from services.browser import (
    BrowserService,
    LoginRequiredError,
    SecurityChallengeError,
)
from services.screenshot_service import ScreenshotService
from services.selectors import (
    POST_CARD_SELECTORS,
    PROFILE_CONTAINER_SELECTORS,
    UPDATES_LABELS,
)
from utils.dates import date_tokens


logger = logging.getLogger(__name__)


class CheckOutcome(StrEnum):
    PUBLISHED = "published"
    NOT_FOUND = "not_found"
    ERROR = "error"
    LOGIN_REQUIRED = "login_required"
    SECURITY_CHALLENGE = "security_challenge"


@dataclass(frozen=True)
class CheckerResult:
    outcome: CheckOutcome
    screenshot_path: str | None = None
    message: str | None = None


class GoogleBusinessProfileChecker:
    def __init__(
        self,
        browser: BrowserService,
        screenshots: ScreenshotService,
    ):
        self.browser = browser
        self.screenshots = screenshots

    def check(
        self,
        client_id: int,
        profile_url: str,
        business_name: str,
        check_date: date,
        timezone_name: str,
    ) -> CheckerResult:
        try:
            with self.browser.page(timezone_name) as page:
                logger.info(
                    "Navigating to Google Business Profile",
                    extra={"event": "page_navigation"},
                )
                page.goto(profile_url, wait_until="domcontentloaded")
                try:
                    page.wait_for_load_state("networkidle", timeout=15000)
                except PlaywrightTimeoutError:
                    logger.info(
                        "Google kept background requests open; continuing after DOM load",
                        extra={"event": "network_idle_timeout"},
                    )
                self.browser.ensure_authenticated(page)
                if not self._confirm_profile(page, business_name):
                    return CheckerResult(
                        CheckOutcome.ERROR,
                        message=(
                            "The configured business profile could not be confirmed "
                            f"as '{business_name}'"
                        ),
                    )
                self._open_updates_area(page)
                post = self._find_post_for_date(page, check_date, timezone_name)
                if post is None:
                    logger.info(
                        "No post matching the client date was found",
                        extra={"event": "post_not_found"},
                    )
                    return CheckerResult(
                        CheckOutcome.NOT_FOUND,
                        message=f"No verifiable post dated {check_date.isoformat()} was found",
                    )
                self._open_post_detail(page, post)
                screenshot = self.screenshots.capture(
                    page, None, business_name, client_id, check_date
                )
                logger.info(
                    "Published post verified and screenshot captured",
                    extra={"event": "post_verified"},
                )
                return CheckerResult(
                    CheckOutcome.PUBLISHED, screenshot_path=str(screenshot)
                )
        except LoginRequiredError as exc:
            return CheckerResult(CheckOutcome.LOGIN_REQUIRED, message=str(exc))
        except SecurityChallengeError as exc:
            return CheckerResult(CheckOutcome.SECURITY_CHALLENGE, message=str(exc))
        except PlaywrightTimeoutError as exc:
            logger.exception("Google page timed out", extra={"event": "page_timeout"})
            return CheckerResult(CheckOutcome.ERROR, message=f"Page timeout: {exc}")
        except Exception as exc:
            logger.exception("GBP verification failed", extra={"event": "checker_error"})
            return CheckerResult(CheckOutcome.ERROR, message=str(exc))

    @staticmethod
    def _confirm_profile(page: Page, business_name: str) -> bool:
        expected = business_name.casefold()
        for selector in PROFILE_CONTAINER_SELECTORS:
            try:
                containers = page.locator(selector)
                for index in range(min(containers.count(), 10)):
                    if expected in containers.nth(index).inner_text().casefold():
                        logger.info(
                            "Business profile identified",
                            extra={"event": "profile_detected"},
                        )
                        return True
            except Exception:
                logger.debug("Profile strategy failed: %s", selector, exc_info=True)
        logger.error(
            "Business name was not found in known profile containers",
            extra={"event": "profile_detection_inconclusive"},
        )
        return False

    @staticmethod
    def _open_updates_area(page: Page) -> None:
        for label in UPDATES_LABELS:
            strategies = (
                page.get_by_role("button", name=re.compile(label, re.I)),
                page.get_by_role("link", name=re.compile(label, re.I)),
                page.get_by_text(label, exact=True),
            )
            for locator in strategies:
                try:
                    if locator.count() and locator.first.is_visible():
                        locator.first.click()
                        page.wait_for_timeout(1000)
                        logger.info(
                            "Opened updates/posts area using label '%s'",
                            label,
                            extra={"event": "updates_opened"},
                        )
                        return
                except Exception:
                    logger.debug(
                        "Updates navigation strategy failed for %s",
                        label,
                        exc_info=True,
                    )
        logger.info(
            "No updates navigation control found; inspecting the current page",
            extra={"event": "updates_already_visible"},
        )

    def _find_post_for_date(
        self, page: Page, target: date, timezone_name: str
    ) -> Locator | None:
        seen: set[str] = set()
        for selector in POST_CARD_SELECTORS:
            try:
                cards = page.locator(selector)
                for index in range(min(cards.count(), 100)):
                    card = cards.nth(index)
                    if not card.is_visible():
                        continue
                    identity = card.evaluate(
                        "(el) => el.outerHTML.slice(0, 300)"
                    )
                    if identity in seen:
                        continue
                    seen.add(identity)
                    if self._card_matches_date(card, target, timezone_name):
                        logger.info(
                            "Found post using selector '%s'",
                            selector,
                            extra={"event": "post_detected"},
                        )
                        return card
            except Exception:
                logger.debug("Post strategy failed: %s", selector, exc_info=True)

        # Current Google Search layouts often render update cards as generic
        # nested divs rather than articles. Start from their visible relative
        # timestamp and climb to the nearest substantial image-backed card.
        relative_pattern = re.compile(
            r"\b(?:yesterday|\d+\s+(?:minutes?|mins?|hours?|hrs?|days?)\s+ago)\b",
            re.I,
        )
        try:
            timestamps = page.get_by_text(relative_pattern)
            for index in range(min(timestamps.count(), 50)):
                timestamp = timestamps.nth(index)
                if not timestamp.is_visible():
                    continue
                card = timestamp.locator(
                    "xpath=ancestor::*["
                    "(self::article or @role='article' or self::div)"
                    " and .//img and string-length(normalize-space(.)) >= 80"
                    "][1]"
                )
                if (
                    card.count()
                    and card.first.is_visible()
                    and self._card_matches_date(card.first, target, timezone_name)
                ):
                    logger.info(
                        "Found post from its relative timestamp",
                        extra={"event": "post_detected"},
                    )
                    return card.first
        except Exception:
            logger.debug("Relative timestamp strategy failed", exc_info=True)

        # Last-resort semantic lookup: find visible date text and use its card ancestor.
        for token in date_tokens(target):
            try:
                matches = page.get_by_text(re.compile(re.escape(token), re.I))
                for index in range(min(matches.count(), 20)):
                    match = matches.nth(index)
                    if not match.is_visible():
                        continue
                    ancestor = match.locator(
                        "xpath=ancestor::*[self::article or @role='article'][1]"
                    )
                    if ancestor.count():
                        return ancestor
            except Exception:
                logger.debug("Date text strategy failed: %s", token, exc_info=True)
        return None

    @staticmethod
    def _open_post_detail(page: Page, post: Locator) -> Locator:
        post_id = post.get_attribute("data-post-id")
        if not post_id:
            raise RuntimeError(
                "The matched Google update does not expose a post ID for evidence capture"
            )

        parts = urlsplit(page.url)
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["lpsid"] = f"pid:{post_id}"
        detail_url = urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), "")
        )
        page.goto(detail_url, wait_until="domcontentloaded")

        dialog = page.get_by_role("dialog").filter(has_text="Updates").first
        dialog.wait_for(state="visible")
        detail = dialog.locator(f'[data-post-id="{post_id}"]').first
        detail.wait_for(state="visible")
        detail.locator("[data-content-id]").first.wait_for(state="visible")

        more = detail.get_by_text("More", exact=True)
        if more.count() and more.first.is_visible():
            more.first.click()
            try:
                more.first.wait_for(state="hidden", timeout=3000)
            except PlaywrightTimeoutError:
                logger.info(
                    "Google kept the post caption collapsed; capturing the opened card",
                    extra={"event": "post_text_collapsed"},
                )

        logger.info(
            "Opened full post detail for evidence capture",
            extra={"event": "post_detail_opened"},
        )
        return detail

    @staticmethod
    def _card_matches_date(
        card: Locator, target: date, timezone_name: str
    ) -> bool:
        values: list[str] = []
        try:
            values.append(card.inner_text())
            for attribute in ("aria-label", "data-date", "datetime"):
                value = card.get_attribute(attribute)
                if value:
                    values.append(value)
            times = card.locator("time")
            for index in range(min(times.count(), 5)):
                time_node = times.nth(index)
                values.extend(
                    filter(
                        None,
                        (
                            time_node.inner_text(),
                            time_node.get_attribute("datetime"),
                            time_node.get_attribute("aria-label"),
                        ),
                    )
                )
        except Exception:
            return False

        combined = " ".join(values).strip()
        lowered = combined.casefold()
        local_today = datetime.now(ZoneInfo(timezone_name)).date()
        if re.search(r"\b(today|just now)\b", lowered):
            return local_today == target
        if re.search(r"\byesterday\b", lowered):
            return local_today - timedelta(days=1) == target
        days_ago = re.search(r"\b(\d+)\s+days?\s+ago\b", lowered)
        if days_ago:
            return local_today - timedelta(days=int(days_ago.group(1))) == target
        relative = re.search(
            r"\b(\d+)\s+(minutes?|mins?|hours?|hrs?)\s+ago\b", lowered
        )
        if relative:
            amount = int(relative.group(1))
            delta = (
                timedelta(minutes=amount)
                if relative.group(2).startswith("min")
                else timedelta(hours=amount)
            )
            published = datetime.now(ZoneInfo(timezone_name)) - delta
            return published.date() == target
        if any(token.casefold() in lowered for token in date_tokens(target)):
            return True

        for value in values:
            candidate = value.strip().replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(candidate)
            except ValueError:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
            if parsed.astimezone(ZoneInfo(timezone_name)).date() == target:
                return True
        return False
