"""Settings for the agent services, read from the environment once at boot."""

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class WebhookSettings:
    linear_webhook_secret: str = field(repr=False)
    database_url: str = field(repr=False)
    port: int = 5001


@dataclass(frozen=True)
class WorkerSettings:
    database_url: str = field(repr=False)
    broker_url: str = field(repr=False)
    poll_interval_seconds: float = 2.0
    lease_seconds: float = 3600.0


def load_webhook_settings() -> WebhookSettings:
    return WebhookSettings(
        linear_webhook_secret=os.environ["LINEAR_WEBHOOK_SECRET"],
        database_url=os.environ["DATABASE_URL"],
        port=int(os.environ.get("PORT", "5001")),
    )


def load_worker_settings() -> WorkerSettings:
    return WorkerSettings(
        database_url=os.environ["DATABASE_URL"],
        broker_url=os.environ["REDIS_URL"],
        poll_interval_seconds=float(os.environ.get("WORKER_POLL_INTERVAL_SECONDS", "2")),
        lease_seconds=float(os.environ.get("WORKER_LEASE_SECONDS", "3600")),
    )
