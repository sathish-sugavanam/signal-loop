import hashlib
import hmac
import json
import time

import pytest
from starlette.testclient import TestClient

from signal_loop_agents.config import Settings
from signal_loop_agents.webhook import create_app

SECRET = "test-secret"


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(Settings(linear_webhook_secret=SECRET)))


def sign(body: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def issue_payload(**overrides) -> dict:
    payload = {
        "action": "update",
        "type": "Issue",
        "data": {"id": "abc", "identifier": "SIG-1", "title": "Example"},
        "webhookTimestamp": int(time.time() * 1000),
    }
    payload.update(overrides)
    return payload


def post(client: TestClient, body: bytes, signature: str | None):
    headers = {"Content-Type": "application/json", "Linear-Delivery": "d-1", "Linear-Event": "Issue"}
    if signature is not None:
        headers["Linear-Signature"] = signature
    return client.post("/webhooks/linear", content=body, headers=headers)


def test_valid_delivery_returns_200(client):
    body = json.dumps(issue_payload()).encode()
    response = post(client, body, sign(body))
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_missing_signature_is_rejected(client):
    body = json.dumps(issue_payload()).encode()
    assert post(client, body, None).status_code == 401


def test_wrong_secret_is_rejected(client):
    body = json.dumps(issue_payload()).encode()
    assert post(client, body, sign(body, "other-secret")).status_code == 401


def test_tampered_body_is_rejected(client):
    body = json.dumps(issue_payload()).encode()
    signature = sign(body)
    tampered = body.replace(b"SIG-1", b"SIG-2")
    assert post(client, tampered, signature).status_code == 401


def test_stale_timestamp_is_rejected(client):
    old = int(time.time() * 1000) - 5 * 60_000
    body = json.dumps(issue_payload(webhookTimestamp=old)).encode()
    assert post(client, body, sign(body)).status_code == 401


def test_missing_timestamp_is_rejected(client):
    payload = issue_payload()
    del payload["webhookTimestamp"]
    body = json.dumps(payload).encode()
    assert post(client, body, sign(body)).status_code == 401


def test_invalid_json_is_rejected(client):
    body = b"not json"
    assert post(client, body, sign(body)).status_code == 400


def test_get_is_not_allowed(client):
    assert client.get("/webhooks/linear").status_code == 405


def test_healthz(client):
    assert client.get("/healthz").text == "ok"

