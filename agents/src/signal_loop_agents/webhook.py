"""Linear webhook receiver.

Verifies the signature, logs the delivery and returns 200. No agent work
happens here. Writing the event to the inbox table comes next.
"""

import hashlib
import hmac
import json
import logging
import time
from collections.abc import Awaitable, Callable

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

from signal_loop_agents.config import Settings, load_settings

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


async def handle_linear_webhook(request: Request, secret: str) -> JSONResponse:
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

    data = payload.get("data") or {}
    log.info(
        "received delivery=%s event=%s action=%s id=%s identifier=%s",
        request.headers.get("linear-delivery"),
        request.headers.get("linear-event") or payload.get("type"),
        payload.get("action"),
        data.get("id"),
        data.get("identifier"),
    )
    return JSONResponse({"ok": True})


async def health(request: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


def linear_webhook(secret: str) -> Callable[[Request], Awaitable[JSONResponse]]:
    async def endpoint(request: Request) -> JSONResponse:
        return await handle_linear_webhook(request, secret)

    return endpoint


def create_app(settings: Settings) -> Starlette:
    return Starlette(
        routes=[
            Route(
                "/webhooks/linear",
                linear_webhook(settings.linear_webhook_secret),
                methods=["POST"],
            ),
            Route("/healthz", health, methods=["GET"]),
        ]
    )


def main() -> None:
    import uvicorn

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    settings = load_settings()
    uvicorn.run(
        create_app(settings),
        host="0.0.0.0",
        port=settings.port,
        proxy_headers=True,
    )


if __name__ == "__main__":
    main()
