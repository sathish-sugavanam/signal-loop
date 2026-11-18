"""Settings for the agent services, read from the environment once at boot."""

import os
from dataclasses import dataclass, field

# Credentials the run container may receive. Whichever are set get passed on.
# ANTHROPIC_AUTH_TOKEN with ANTHROPIC_BASE_URL is how a gateway such as OpenRouter is used.
AGENT_CREDENTIALS = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_AUTH_TOKEN")
# Other settings passed through to the run container when set.
AGENT_SETTINGS = ("ANTHROPIC_BASE_URL", "DEV_AGENT_MODEL")


def agent_env() -> dict[str, str]:
    env = {k: os.environ[k] for k in AGENT_CREDENTIALS + AGENT_SETTINGS if os.environ.get(k)}
    if "ANTHROPIC_AUTH_TOKEN" in env:
        # A gateway token must not be shadowed by an API key (OpenRouter's instructions).
        env["ANTHROPIC_API_KEY"] = ""
    return env


@dataclass(frozen=True)
class WebhookSettings:
    linear_webhook_secret: str = field(repr=False)
    database_url: str = field(repr=False)
    port: int = 5001


@dataclass(frozen=True)
class WorkerSettings:
    database_url: str = field(repr=False)
    broker_url: str = field(repr=False)
    github_token: str = field(default="", repr=False)
    github_repo: str = ""
    agent_env: dict[str, str] = field(default_factory=dict, repr=False)
    poll_interval_seconds: float = 2.0
    lease_seconds: float = 3600.0
    run_image: str = "signal-loop-agents"
    runs_volume: str = "agent_runs"
    runs_dir: str = "/runs"
    work_dir: str = "/work"


def load_webhook_settings() -> WebhookSettings:
    return WebhookSettings(
        linear_webhook_secret=os.environ["LINEAR_WEBHOOK_SECRET"],
        database_url=os.environ["DATABASE_URL"],
        port=int(os.environ.get("PORT", "5001")),
    )


def load_worker_settings() -> WorkerSettings:
    if not any(os.environ.get(k) for k in AGENT_CREDENTIALS):
        raise RuntimeError(f"set one of {', '.join(AGENT_CREDENTIALS)} for the dev agent")
    return WorkerSettings(
        database_url=os.environ["DATABASE_URL"],
        broker_url=os.environ["REDIS_URL"],
        github_token=os.environ["GITHUB_TOKEN"],
        github_repo=os.environ["GITHUB_REPO"],
        agent_env=agent_env(),
        poll_interval_seconds=float(os.environ.get("WORKER_POLL_INTERVAL_SECONDS", "2")),
        lease_seconds=float(os.environ.get("WORKER_LEASE_SECONDS", "3600")),
    )
