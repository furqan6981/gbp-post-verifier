from pathlib import Path

from config.settings import Settings
from database.models import CheckStatus, Client
from database.repositories import CheckRepository, ClientRepository
from services.gbp_checker import CheckerResult, CheckOutcome
from services.workflow import VerificationWorkflow
from utils.dates import today_in_timezone


class FakeChecker:
    def __init__(self, results: list[CheckerResult]):
        self.results = iter(results)
        self.calls = 0

    def check(self, *_args: object) -> CheckerResult:
        self.calls += 1
        return next(self.results)


class FakeGmail:
    def __init__(self, existing_draft_id: str | None = None) -> None:
        self.calls = 0
        self.existing_draft_id = existing_draft_id

    def create_draft(self, **_kwargs: object) -> str:
        self.calls += 1
        return "draft-123"

    def find_draft_by_message_id(self, _message_id: str) -> str | None:
        return self.existing_draft_id


def make_settings(tmp_path: Path) -> Settings:
    template = tmp_path / "email.txt"
    template.write_text("Hi {{client_name}} — {{date}} — {{agency_name}}")
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'unused.db'}",
        screenshot_dir=tmp_path / "screenshots",
        browser_profile_dir=tmp_path / "profile",
        log_dir=tmp_path / "logs",
        email_template_file=template,
        agency_name="Test Agency",
    )


def test_retry_then_create_one_draft(
    tmp_path: Path,
    client_repository: ClientRepository,
    check_repository: CheckRepository,
    sample_client: Client,
) -> None:
    client_data = sample_client.model_copy(
        update={"retry_interval_minutes": 1, "max_retries": 3}
    )
    client = client_repository.add(client_data)
    screenshot = tmp_path / "post.png"
    screenshot.write_bytes(b"png")
    checker = FakeChecker(
        [
            CheckerResult(CheckOutcome.NOT_FOUND, message="Not yet"),
            CheckerResult(CheckOutcome.PUBLISHED, screenshot_path=str(screenshot)),
        ]
    )
    gmail = FakeGmail()
    sleeps: list[float] = []
    workflow = VerificationWorkflow(
        make_settings(tmp_path),
        check_repository,
        checker,  # type: ignore[arg-type]
        gmail,  # type: ignore[arg-type]
        sleeper=sleeps.append,
    )

    result = workflow.run_client(client)
    duplicate = workflow.run_client(client)

    assert result.status == CheckStatus.DRAFT_CREATED
    assert result.attempts == 2
    assert result.gmail_draft_id == "draft-123"
    assert sleeps == [60]
    assert gmail.calls == 1
    assert checker.calls == 2
    assert duplicate.id == result.id


def test_all_attempts_exhausted_without_draft(
    tmp_path: Path,
    client_repository: ClientRepository,
    check_repository: CheckRepository,
    sample_client: Client,
) -> None:
    client = client_repository.add(
        sample_client.model_copy(
            update={"retry_interval_minutes": 1, "max_retries": 2}
        )
    )
    checker = FakeChecker(
        [
            CheckerResult(CheckOutcome.NOT_FOUND, message="Missing"),
            CheckerResult(CheckOutcome.NOT_FOUND, message="Still missing"),
        ]
    )
    gmail = FakeGmail()
    workflow = VerificationWorkflow(
        make_settings(tmp_path),
        check_repository,
        checker,  # type: ignore[arg-type]
        gmail,  # type: ignore[arg-type]
        sleeper=lambda _seconds: None,
    )

    result = workflow.run_client(client)

    assert result.status == CheckStatus.FAILED
    assert result.attempts == 2
    assert gmail.calls == 0


def test_reconciles_existing_gmail_draft_without_rechecking_browser(
    tmp_path: Path,
    client_repository: ClientRepository,
    check_repository: CheckRepository,
    sample_client: Client,
) -> None:
    client = client_repository.add(sample_client)
    screenshot = tmp_path / "post.png"
    screenshot.write_bytes(b"png")
    check = check_repository.get_or_create(
        client.id or 0, today_in_timezone(client.timezone)
    )
    check_repository.update(
        check.id or 0,
        CheckStatus.PUBLISHED,
        screenshot_path=screenshot,
        message_id="<stable-message-id@gbp-post-verifier.local>",
    )
    checker = FakeChecker([])
    gmail = FakeGmail(existing_draft_id="recovered-draft")
    workflow = VerificationWorkflow(
        make_settings(tmp_path),
        check_repository,
        checker,  # type: ignore[arg-type]
        gmail,  # type: ignore[arg-type]
        sleeper=lambda _seconds: None,
    )

    result = workflow.run_client(client)

    assert result.status == CheckStatus.DRAFT_CREATED
    assert result.gmail_draft_id == "recovered-draft"
    assert checker.calls == 0
    assert gmail.calls == 0
