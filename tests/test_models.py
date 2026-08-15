from datetime import time

import pytest
from pydantic import ValidationError

from database.models import Client


def test_client_rejects_invalid_timezone(sample_client: Client) -> None:
    data = sample_client.model_dump()
    data["timezone"] = "Mars/Olympus"
    with pytest.raises(ValidationError):
        Client.model_validate(data)


def test_client_rejects_invalid_email(sample_client: Client) -> None:
    data = sample_client.model_dump()
    data["client_email"] = "not-an-email"
    with pytest.raises(ValidationError):
        Client.model_validate(data)


def test_client_accepts_valid_configuration(sample_client: Client) -> None:
    assert sample_client.check_time == time(18, 0)
    assert sample_client.max_retries == 3
