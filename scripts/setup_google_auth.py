"""Run the Gmail OAuth consent flow and save token.json."""

from config.settings import get_settings
from services.gmail_service import GmailService


def main() -> None:
    settings = get_settings()
    service = GmailService(settings.credentials_path, settings.token_path)
    account = service.test_connection()
    print(f"Gmail OAuth configured for {account}. No email was sent.")


if __name__ == "__main__":
    main()
