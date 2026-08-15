"""Add a validated client to SQLite.

Example:
python -m scripts.add_client --client-name "ABC Plumbing" \
  --business-name "ABC Plumbing" --url "https://www.google.com/..." \
  --email owner@example.com --timezone America/Chicago --check-time 18:00
"""

import argparse
from datetime import time

from config.settings import get_settings
from database.database import Database
from database.models import Client
from database.repositories import ClientRepository


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add a GBP verification client")
    parser.add_argument("--client-name", required=True)
    parser.add_argument("--business-name", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--timezone", required=True)
    parser.add_argument("--check-time", required=True, help="24-hour HH:MM")
    parser.add_argument("--retry-interval", type=int)
    parser.add_argument("--max-retries", type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    database = Database(settings.database_path)
    database.initialize()
    repository = ClientRepository(database)
    client = repository.add(
        Client(
            client_name=args.client_name,
            business_name=args.business_name,
            google_profile_url=args.url,
            client_email=args.email,
            timezone=args.timezone,
            check_time=time.fromisoformat(args.check_time),
            retry_interval_minutes=(
                args.retry_interval or settings.default_retry_interval_minutes
            ),
            max_retries=args.max_retries or settings.default_max_retries,
        )
    )
    print(f"Added client {client.id}: {client.client_name}")


if __name__ == "__main__":
    main()
