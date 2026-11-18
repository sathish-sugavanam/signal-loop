"""The agent worker: Celery tasks that pick pending tasks from the inbox.

Postgres stays the queue. Celery beat fires two periodic tasks:
- check_pending_tasks picks and runs pending tasks until none are left.
- fail_stale_tasks fails tasks whose worker died mid-run.
Celery keeps no results; each event's outcome lives in its inbox row.

Each task is one dev run (see dev_run): the agent changes the code, the worker opens a PR.
"""

import logging
import time

import psycopg
from celery import Celery

from signal_loop_agents.config import WorkerSettings
from signal_loop_agents.dev_run import (
    docker_run_container,
    github_pull_request_opener,
    run_dev_task,
)
from signal_loop_agents.inbox import (
    InboxEvent,
    fail_stale,
    get_event,
    mark_done,
    mark_failed,
)

log = logging.getLogger("signal_loop_agents.worker")

STALE_CHECK_INTERVAL_SECONDS = 300.0


def handle_task(event: InboxEvent, settings: WorkerSettings) -> None:
    log.info("handling task=%s issue=%s: starting dev run", event.id, event.issue_id)
    run_dev_task(
        event,
        settings,
        run_container=docker_run_container(settings),
        open_pull_request=github_pull_request_opener(settings),
    )


def pick_next_task(conn: psycopg.Connection, settings: WorkerSettings) -> bool:
    event = get_event(conn)
    if event is None:
        return False
    log.info(
        "picked task=%s delivery=%s action=%s issue=%s attempt=%s",
        event.id,
        event.delivery_id,
        event.action,
        event.issue_id,
        event.attempts,
    )
    started = time.monotonic()
    try:
        handle_task(event, settings)
    except Exception as exc:
        log.exception(
            "task=%s issue=%s failed after %.2fs",
            event.id,
            event.issue_id,
            time.monotonic() - started,
        )
        mark_failed(conn, event.id, f"{type(exc).__name__}: {exc}")
    else:
        log.info(
            "task=%s issue=%s done in %.2fs",
            event.id,
            event.issue_id,
            time.monotonic() - started,
        )
        mark_done(conn, event.id)
    return True


def pick_pending_tasks(conn: psycopg.Connection, settings: WorkerSettings) -> int:
    """Handles events until none are claimable. Returns how many were handled."""
    handled = 0
    while pick_next_task(conn, settings):
        handled += 1
    return handled


def create_app(settings: WorkerSettings) -> Celery:
    app = Celery("signal_loop_agents", broker=settings.broker_url)
    app.conf.update(
        task_ignore_result=True,
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
        beat_schedule={
            "check-pending-tasks": {
                "task": "signal_loop_agents.check_pending_tasks",
                "schedule": settings.poll_interval_seconds,
                "options": {"expires": settings.poll_interval_seconds},
            },
            "fail-stale-tasks": {
                "task": "signal_loop_agents.fail_stale_tasks",
                "schedule": STALE_CHECK_INTERVAL_SECONDS,
                "options": {"expires": STALE_CHECK_INTERVAL_SECONDS},
            },
        },
    )

    @app.task(name="signal_loop_agents.check_pending_tasks")
    def check_pending_tasks() -> None:
        with psycopg.connect(settings.database_url, autocommit=True) as conn:
            handled = pick_pending_tasks(conn, settings)
        if handled:
            log.info("picked %s task(s)", handled)

    @app.task(name="signal_loop_agents.fail_stale_tasks")
    def fail_stale_tasks() -> None:
        with psycopg.connect(settings.database_url, autocommit=True) as conn:
            failed = fail_stale(conn, settings.lease_seconds)
        if failed:
            log.warning("failed %s event(s) whose lease expired", failed)

    return app
