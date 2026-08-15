from datetime import UTC, date, datetime, timedelta

from database.models import CheckStatus, Client
from database.repositories import CheckRepository, ClientRepository


def test_client_round_trip(
    client_repository: ClientRepository, sample_client: Client
) -> None:
    stored = client_repository.add(sample_client)
    loaded = client_repository.get(stored.id or 0)
    assert loaded is not None
    assert loaded.business_name == sample_client.business_name
    assert loaded.timezone == "America/Chicago"


def test_duplicate_daily_check_is_prevented(
    client_repository: ClientRepository,
    check_repository: CheckRepository,
    sample_client: Client,
) -> None:
    client = client_repository.add(sample_client)
    target = date(2026, 8, 8)
    first = check_repository.get_or_create(client.id or 0, target)
    second = check_repository.get_or_create(client.id or 0, target)
    assert first.id == second.id
    assert first.status == CheckStatus.PENDING


def test_attempt_and_status_updates(
    client_repository: ClientRepository,
    check_repository: CheckRepository,
    sample_client: Client,
) -> None:
    client = client_repository.add(sample_client)
    check = check_repository.get_or_create(client.id or 0, date(2026, 8, 8))
    check = check_repository.start_attempt(check.id or 0)
    check = check_repository.update(
        check.id or 0, CheckStatus.RETRYING, error_message="Not found"
    )
    assert check.attempts == 1
    assert check.error_message == "Not found"


def test_daily_check_has_single_processing_lease(
    client_repository: ClientRepository,
    check_repository: CheckRepository,
    sample_client: Client,
) -> None:
    client = client_repository.add(sample_client)
    check = check_repository.get_or_create(client.id or 0, date(2026, 8, 8))
    expires = datetime.now(UTC) + timedelta(hours=1)
    assert check_repository.claim(check.id or 0, "worker-a", expires)
    assert not check_repository.claim(check.id or 0, "worker-b", expires)
    check_repository.release(check.id or 0, "worker-a")
    assert check_repository.claim(check.id or 0, "worker-b", expires)
