"""Functional and negative API tests."""

import os
import sqlite3


def make_payment(client, amount=500, card="4111111111111111", key="test-key-1"):
    return client.post(
        "/payments",
        headers={"Idempotency-Key": key},
        json={"amount_rupees": amount, "card_number": card},
    )


def test_valid_payment_is_successful(client):
    response = make_payment(client)
    assert response.status_code == 201
    assert response.json()["status"] == "SUCCESS"
    assert response.json()["amount_rupees"] == 500


def test_declined_card_returns_failed_status(client):
    response = make_payment(client, card="4111111111110002")
    assert response.status_code == 201
    assert response.json()["status"] == "FAILED"
    assert response.json()["failure_reason"] == "Simulated card decline"


def test_zero_amount_is_rejected(client):
    assert make_payment(client, amount=0).status_code == 422


def test_negative_amount_is_rejected(client):
    assert make_payment(client, amount=-100).status_code == 422


def test_invalid_card_number_is_rejected(client):
    assert make_payment(client, card="12345").status_code == 422


def test_missing_idempotency_key_is_rejected(client):
    response = client.post("/payments", json={"amount_rupees": 500, "card_number": "4111111111111111"})
    assert response.status_code == 400


def test_repeated_request_does_not_create_duplicate(client):
    first = make_payment(client, key="repeat-123")
    second = make_payment(client, key="repeat-123")
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    connection = sqlite3.connect(os.environ["PAYMENT_DB_PATH"])
    try:
        count = connection.execute("SELECT COUNT(*) FROM payments").fetchone()[0]
    finally:
        connection.close()
    assert count == 1


def test_same_key_with_different_payment_is_rejected(client):
    assert make_payment(client, amount=500, key="same-key").status_code == 201
    assert make_payment(client, amount=900, key="same-key").status_code == 409


def test_payment_can_be_retrieved(client):
    created = make_payment(client)
    payment_id = created.json()["id"]
    retrieved = client.get(f"/payments/{payment_id}")
    assert retrieved.status_code == 200
    assert retrieved.json()["id"] == payment_id
    assert retrieved.json()["status"] == "SUCCESS"


def test_unknown_payment_returns_404(client):
    assert client.get("/payments/not-a-real-payment").status_code == 404


def test_health_endpoint_returns_healthy_status(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
