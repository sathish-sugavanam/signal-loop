"""Linear webhook receiver.

Verifies the signature, stores the delivery in the inbox and returns 200.
No agent work happens here; the worker picks events up from the inbox.
"""

import hashlib
import hmac
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from psycopg_pool import AsyncConnectionPool
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from signal_loop_agents.config import WebhookSettings, load_webhook_settings
from signal_loop_agents.inbox import Inbox, PostgresInbox, parse_event_from_linear

log = logging.getLogger("signal_loop_agents.webhook")

# Linear sends `webhookTimestamp` in milliseconds and recommends rejecting
# deliveries older than a minute to block replays.
MAX_AGE_MS = 60_000


def signature_is_valid(secret: str, body: bytes, signature: str) -> bool:
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


def timestamp_is_fresh(timestamp_ms: object, now_ms: int) -> bool:
    if not isinstance(timestamp_ms, int):
        return False
    return abs(now_ms - timestamp_ms) <= MAX_AGE_MS


async def handle_linear_webhook(
    request: Request, secret: str, inbox: Inbox
) -> JSONResponse:
    body = await request.body()

    signature = request.headers.get("linear-signature", "")
    if not signature or not signature_is_valid(secret, body, signature):
        log.warning("rejected delivery: bad signature")
        return JSONResponse({"error": "invalid signature"}, status_code=401)

    try:
        payload = json.loads(body)
    except ValueError:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    if not timestamp_is_fresh(payload.get("webhookTimestamp"), int(time.time() * 1000)):
        log.warning("rejected delivery: stale or missing webhookTimestamp")
        return JSONResponse({"error": "stale delivery"}, status_code=401)

    delivery_id = request.headers.get("linear-delivery", "").strip()
    if not delivery_id:
        return JSONResponse({"error": "missing Linear-Delivery header"}, status_code=400)

    event_type = request.headers.get("linear-event") or payload.get("type") or "unknown"
    event = parse_event_from_linear(delivery_id, event_type, payload)
    stored = await inbox.record(event)

    log.info(
        "%s delivery=%s event=%s action=%s issue=%s",
        "stored" if stored else "duplicate",
        event.delivery_id,
        event_type,
        event.action,
        event.issue_id,
    )
    return JSONResponse({"ok": True, "duplicate": not stored})


async def health(request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


def linear_webhook(
    secret: str, inbox: Inbox
) -> Callable[[Request], Awaitable[JSONResponse]]:
    async def endpoint(request: Request) -> JSONResponse:
        return await handle_linear_webhook(request, secret, inbox)

    return endpoint


def create_app(settings: WebhookSettings, inbox: Inbox | None = None) -> Starlette:
    """Builds the app. Without an `inbox`, it opens a Postgres pool for the app's lifetime."""
    pool: AsyncConnectionPool | None = None
    if inbox is None:
        pool = AsyncConnectionPool(
            settings.database_url, min_size=1, max_size=4, open=False
        )
        inbox = PostgresInbox(pool)

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        if pool is not None:
            await pool.open(wait=True, timeout=10)
        try:
            yield
        finally:
            if pool is not None:
                await pool.close()

    return Starlette(
        routes=[
            Route(
                "/webhooks/linear",
                linear_webhook(settings.linear_webhook_secret, inbox),
                methods=["POST"],
            ),
            Route("/healthz", health, methods=["GET"]),
        ],
        lifespan=lifespan,
    )


def main() -> None:
    import uvicorn

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    settings = load_webhook_settings()
    uvicorn.run(
        create_app(settings),
        host="0.0.0.0",
        port=settings.port,
        proxy_headers=True,
    )


if __name__ == "__main__":
    main()
