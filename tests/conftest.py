"""Each test uses a separate temporary SQLite database."""

import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PAYMENT_DB_PATH", str(tmp_path / "test_payments.db"))
    with TestClient(app) as test_client:
        yield test_client
