from datetime import time
from pathlib import Path

import pytest

from database.database import Database
from database.models import Client
from database.repositories import CheckRepository, ClientRepository


@pytest.fixture
def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "test.db")
    db.initialize()
    return db


@pytest.fixture
def client_repository(database: Database) -> ClientRepository:
    return ClientRepository(database)


@pytest.fixture
def check_repository(database: Database) -> CheckRepository:
    return CheckRepository(database)


@pytest.fixture
def sample_client() -> Client:
    return Client(
        client_name="ABC Plumbing",
        business_name="ABC Plumbing",
        google_profile_url="https://www.google.com/search?q=ABC+Plumbing",
        client_email="owner@example.com",
        timezone="America/Chicago",
        check_time=time(18, 0),
        retry_interval_minutes=30,
        max_retries=3,
    )
