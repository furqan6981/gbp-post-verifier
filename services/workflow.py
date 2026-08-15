import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from config.settings import Settings
from database.models import CheckStatus, Client, DailyPostCheck
from database.repositories import CheckRepository
from services.gbp_checker import CheckOutcome, GoogleBusinessProfileChecker
from services.gmail_service import GmailService
from utils.dates import today_in_timezone


logger = logging.getLogger(__name__)


def render_template(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered


class VerificationWorkflow:
    def __init__(
        self,
        settings: Settings,
        checks: CheckRepository,
        checker: GoogleBusinessProfileChecker,
        gmail: GmailService,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.settings = settings
        self.checks = checks
        self.checker = checker
        self.gmail = gmail
        self.sleeper = sleeper

    def run_client(self, client: Client) -> DailyPostCheck:
        if client.id is None:
            raise ValueError("Client must be persisted before it can be processed")
        check_date = today_in_timezone(client.timezone)
        check = self.checks.get_or_create(client.id, check_date)
        if check.status == CheckStatus.DRAFT_CREATED and check.gmail_draft_id:
            logger.info(
                "Skipping client: today's Gmail draft already exists",
                extra={"client_id": client.id, "check_date": str(check_date)},
            )
            return check

        if check.id is None:
            raise RuntimeError("Daily check has no database ID")
        owner = str(uuid.uuid4())
        lease_duration = (
            client.max_retries * client.retry_interval_minutes * 60
            + self.settings.manual_login_timeout_minutes * 60
            + 3600
        )
        if not self.checks.claim(
            check.id,
            owner,
            datetime.now(UTC) + timedelta(seconds=lease_duration),
        ):
            logger.warning(
                "Skipping client because another process owns today's check",
                extra={"client_id": client.id, "event": "check_already_running"},
            )
            return self.checks.get_by_id(check.id)

        try:
            check = self.checks.get_by_id(check.id)
            if (
                check.status == CheckStatus.PUBLISHED
                and check.screenshot_path
                and check.message_id
            ):
                return self._finish_verified_draft(client, check, reconcile=True)

            attempts_remaining = max(client.max_retries - check.attempts, 0)
            if attempts_remaining == 0:
                return self.checks.update(
                    check.id,
                    CheckStatus.FAILED,
                    error_message="Maximum attempts already reached",
                )

            for sequence in range(attempts_remaining):
                check = self.checks.start_attempt(check.id)
                logger.info(
                    "Checking client GBP post",
                    extra={
                        "client_id": client.id,
                        "check_date": str(check_date),
                        "attempt": check.attempts,
                    },
                )
                result = self.checker.check(
                    client.id,
                    client.google_profile_url,
                    client.business_name,
                    check_date,
                    client.timezone,
                )
                if result.outcome == CheckOutcome.PUBLISHED and result.screenshot_path:
                    screenshot = Path(result.screenshot_path)
                    message_id = (
                        f"<gbp-check-{client.id}-{check_date.isoformat()}"
                        "@gbp-post-verifier.local>"
                    )
                    check = self.checks.update(
                        check.id,
                        CheckStatus.PUBLISHED,
                        screenshot_path=screenshot,
                        verified_at=datetime.now(UTC),
                        message_id=message_id,
                    )
                    return self._finish_verified_draft(client, check, reconcile=False)

                error = result.message or f"Checker returned {result.outcome.value}"
                last_attempt = sequence == attempts_remaining - 1
                if last_attempt:
                    logger.error(
                        "Today's post could not be verified after all attempts: %s",
                        error,
                        extra={"client_id": client.id, "event": "verification_failed"},
                    )
                    return self.checks.update(
                        check.id, CheckStatus.FAILED, error_message=error
                    )

                check = self.checks.update(
                    check.id,
                    CheckStatus.RETRYING,
                    error_message=error,
                )
                delay = client.retry_interval_minutes * 60
                logger.warning(
                    "Post not verified; retrying in %s minutes",
                    client.retry_interval_minutes,
                    extra={
                        "client_id": client.id,
                        "attempt": check.attempts,
                        "event": "retry_scheduled",
                    },
                )
                self.sleeper(delay)

            return self.checks.get_by_id(check.id)
        finally:
            self.checks.release(check.id, owner)

    def _finish_verified_draft(
        self,
        client: Client,
        check: DailyPostCheck,
        *,
        reconcile: bool,
    ) -> DailyPostCheck:
        if check.id is None or not check.screenshot_path or not check.message_id:
            raise ValueError("Verified check is missing draft evidence metadata")
        try:
            draft_id = (
                self.gmail.find_draft_by_message_id(check.message_id)
                if reconcile
                else None
            )
            if draft_id is None:
                draft_id = self._create_draft(
                    client,
                    check.check_date,
                    check.screenshot_path,
                    check.message_id,
                )
        except Exception as exc:
            logger.exception(
                "Post is verified, but Gmail draft creation is still pending",
                extra={"client_id": client.id, "event": "draft_failure"},
            )
            return self.checks.update(
                check.id,
                CheckStatus.PUBLISHED,
                error_message=f"Gmail draft creation pending: {exc}",
            )
        return self.checks.update(
            check.id,
            CheckStatus.DRAFT_CREATED,
            gmail_draft_id=draft_id,
            error_message=None,
        )

    def _create_draft(
        self,
        client: Client,
        check_date: date,
        screenshot: Path,
        message_id: str,
    ) -> str:
        values = {
            "client_name": client.client_name,
            "business_name": client.business_name,
            "date": str(check_date),
            "agency_name": self.settings.agency_name,
        }
        subject = render_template(self.settings.email_subject_template, values)
        body = render_template(
            self.settings.template_path.read_text(encoding="utf-8"), values
        )
        return self.gmail.create_draft(
            recipient=str(client.client_email),
            subject=subject,
            body=body,
            attachment=screenshot,
            message_id=message_id,
        )
