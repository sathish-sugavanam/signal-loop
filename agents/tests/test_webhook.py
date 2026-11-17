import hashlib
import hmac
import json
import time

import pytest
from starlette.testclient import TestClient

from signal_loop_agents.config import WebhookSettings
from signal_loop_agents.inbox import NewEvent
from signal_loop_agents.webhook import create_app

SECRET = "test-secret"
SETTINGS = WebhookSettings(linear_webhook_secret=SECRET, database_url="unused")


class FakeInbox:
    def __init__(self) -> None:
        self.events: dict[str, NewEvent] = {}

    async def record(self, event: NewEvent) -> bool:
        if event.delivery_id in self.events:
            return False
        self.events[event.delivery_id] = event
        return True


class BrokenInbox:
    async def record(self, event: NewEvent) -> bool:
        raise ConnectionError("database is down")


@pytest.fixture
def inbox() -> FakeInbox:
    return FakeInbox()


@pytest.fixture
def client(inbox) -> TestClient:
    return TestClient(create_app(SETTINGS, inbox=inbox))


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


def post(
    client: TestClient, body: bytes, signature: str | None, delivery: str | None = "d-1"
):
    headers = {"Content-Type": "application/json", "Linear-Event": "Issue"}
    if delivery is not None:
        headers["Linear-Delivery"] = delivery
    if signature is not None:
        headers["Linear-Signature"] = signature
    return client.post("/webhooks/linear", content=body, headers=headers)


def test_valid_delivery_is_stored(client, inbox):
    body = json.dumps(issue_payload()).encode()
    response = post(client, body, sign(body))
    assert response.status_code == 200
    assert response.json() == {"ok": True, "duplicate": False}
    event = inbox.events["d-1"]
    assert (event.action, event.issue_id) == ("update", "SIG-1")


def test_repeated_delivery_is_acknowledged_once(client, inbox):
    body = json.dumps(issue_payload()).encode()
    post(client, body, sign(body))
    response = post(client, body, sign(body))
    assert response.status_code == 200
    assert response.json() == {"ok": True, "duplicate": True}
    assert len(inbox.events) == 1


def test_missing_delivery_id_is_rejected(client, inbox):
    body = json.dumps(issue_payload()).encode()
    assert post(client, body, sign(body), delivery=None).status_code == 400
    assert inbox.events == {}


def test_rejected_delivery_is_not_stored(client, inbox):
    body = json.dumps(issue_payload()).encode()
    post(client, body, "bad")
    assert inbox.events == {}


def test_inbox_failure_returns_500_so_linear_retries():
    client = TestClient(create_app(SETTINGS, inbox=BrokenInbox()), raise_server_exceptions=False)
    body = json.dumps(issue_payload()).encode()
    assert post(client, body, sign(body)).status_code == 500


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

