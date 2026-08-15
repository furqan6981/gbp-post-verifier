import argparse
import logging
import sys
from dataclasses import dataclass

from config.settings import Settings, get_settings
from database.database import Database
from database.models import CheckStatus
from database.repositories import CheckRepository, ClientRepository
from services.browser import BrowserService
from services.gbp_checker import GoogleBusinessProfileChecker
from services.gmail_service import GmailService
from services.scheduler import ClientScheduler
from services.screenshot_service import ScreenshotService
from services.workflow import VerificationWorkflow
from utils.dates import today_in_timezone
from utils.logger import configure_logging


logger = logging.getLogger(__name__)


@dataclass
class Application:
    settings: Settings
    database: Database
    clients: ClientRepository
    checks: CheckRepository
    checker: GoogleBusinessProfileChecker
    gmail: GmailService
    workflow: VerificationWorkflow


def build_application() -> Application:
    settings = get_settings()
    settings.create_directories()
    configure_logging(settings.logs_path)
    database = Database(settings.database_path)
    database.initialize()
    clients = ClientRepository(database)
    checks = CheckRepository(database)
    browser = BrowserService(
        settings.browser_profile_path,
        headless=settings.headless,
        timeout_seconds=settings.browser_timeout_seconds,
        manual_login_timeout_minutes=settings.manual_login_timeout_minutes,
    )
    checker = GoogleBusinessProfileChecker(
        browser, ScreenshotService(settings.screenshots_path)
    )
    gmail = GmailService(settings.credentials_path, settings.token_path)
    workflow = VerificationWorkflow(settings, checks, checker, gmail)
    return Application(
        settings, database, clients, checks, checker, gmail, workflow
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify daily GBP posts and create reviewable Gmail drafts."
    )
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--setup", action="store_true")
    actions.add_argument("--run-client", type=int, metavar="CLIENT_ID")
    actions.add_argument("--run-all", action="store_true")
    actions.add_argument("--status", action="store_true")
    actions.add_argument("--test-gmail", action="store_true")
    actions.add_argument("--test-client", type=int, metavar="CLIENT_ID")
    return parser.parse_args()


def setup(app: Application) -> int:
    print(f"Database initialized: {app.settings.database_path}")
    print(f"Screenshot directory: {app.settings.screenshots_path}")
    print(f"Browser profile: {app.settings.browser_profile_path}")
    print(f"Log file: {app.settings.logs_path / 'app.log'}")
    if app.settings.credentials_path.exists():
        print(f"Gmail credentials found: {app.settings.credentials_path}")
    else:
        print(
            "Gmail credentials are not installed yet. Place credentials.json at "
            f"{app.settings.credentials_path} before using Gmail."
        )
    print("Setup complete. No email has been sent.")
    return 0


def run_client(app: Application, client_id: int) -> int:
    client = app.clients.get(client_id)
    if client is None:
        print(f"Client {client_id} was not found.", file=sys.stderr)
        return 1
    result = app.workflow.run_client(client)
    print(
        f"{client.client_name}: {result.status.value} "
        f"(attempts={result.attempts})"
    )
    if result.error_message:
        print(f"Details: {result.error_message}")
    return 0 if result.status == CheckStatus.DRAFT_CREATED else 2


def run_all(app: Application) -> int:
    clients = app.clients.list_active()
    if not clients:
        print("No active clients are configured.")
        return 0
    exit_code = 0
    for client in clients:
        code = run_client(app, client.id or 0)
        exit_code = max(exit_code, code)
    return exit_code


def print_status(app: Application) -> int:
    clients = app.clients.list_all()
    print(f"{'Client':30} {'Status':18} {'Attempts':8} {'Local date'}")
    print("-" * 72)
    for client in clients:
        if client.id is None:
            continue
        local_date = today_in_timezone(client.timezone)
        check = app.checks.get(client.id, local_date)
        status = check.status.value.replace("_", " ").title() if check else "Pending"
        attempts = check.attempts if check else 0
        print(
            f"{client.client_name[:30]:30} {status:18} "
            f"{attempts:<8} {local_date}"
        )
    return 0


def test_client(app: Application, client_id: int) -> int:
    client = app.clients.get(client_id)
    if client is None:
        print(f"Client {client_id} was not found.", file=sys.stderr)
        return 1
    result = app.checker.check(
        client.id or client_id,
        client.google_profile_url,
        client.business_name,
        today_in_timezone(client.timezone),
        client.timezone,
    )
    print(f"Browser test result: {result.outcome.value}")
    if result.screenshot_path:
        print(f"Screenshot: {result.screenshot_path}")
    if result.message:
        print(f"Details: {result.message}")
    print("No Gmail draft was created by --test-client.")
    return 0 if result.outcome.value == "published" else 2


def main() -> int:
    args = parse_args()
    app = build_application()
    logger.info("Application started", extra={"event": "application_startup"})

    if args.setup:
        return setup(app)
    if args.run_client is not None:
        return run_client(app, args.run_client)
    if args.run_all:
        return run_all(app)
    if args.status:
        return print_status(app)
    if args.test_gmail:
        account = app.gmail.test_connection()
        print(f"Gmail API connection successful for {account}. No email was sent.")
        return 0
    if args.test_client is not None:
        return test_client(app, args.test_client)

    ClientScheduler(app.clients, app.workflow).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
