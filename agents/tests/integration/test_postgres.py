import asyncio
import threading
from datetime import timedelta

import psycopg
import pytest
from psycopg_pool import AsyncConnectionPool

from signal_loop_agents import worker
from signal_loop_agents.config import WorkerSettings
from signal_loop_agents.inbox import (
    NewEvent,
    PostgresInbox,
    claim_next,
    fail_stale,
    mark_done,
)
from signal_loop_agents.worker import pick_next_task, pick_pending_tasks


def new_event(delivery_id: str, issue_id: str | None = "i-1") -> NewEvent:
    return NewEvent(
        delivery_id=delivery_id,
        action="update",
        issue_id=issue_id,
        payload={"delivery": delivery_id},
    )


def record(database_url: str, *events: NewEvent) -> list[bool]:
    async def go() -> list[bool]:
        async with AsyncConnectionPool(database_url, min_size=1, max_size=1) as pool:
            inbox = PostgresInbox(pool)
            return [await inbox.record(e) for e in events]

    return asyncio.run(go())


def statuses(conn) -> dict[str, str]:
    return dict(conn.execute("SELECT delivery_id, status FROM inbox_events").fetchall())


def test_record_dedupes_on_delivery_id(database_url, conn):
    assert record(database_url, new_event("d-1"), new_event("d-1")) == [True, False]
    row = conn.execute("SELECT payload, status, attempts FROM inbox_events").fetchall()
    assert row == [({"delivery": "d-1"}, "pending", 0)]


def test_claim_takes_oldest_pending_event(database_url, conn):
    record(database_url, new_event("d-1", "i-1"), new_event("d-2", "i-2"))
    event = claim_next(conn)
    assert (event.delivery_id, event.attempts, event.payload) == ("d-1", 1, {"delivery": "d-1"})
    assert statuses(conn) == {"d-1": "processing", "d-2": "pending"}


def test_claim_skips_issues_already_in_progress(database_url, conn):
    record(database_url, new_event("d-1", "i-1"), new_event("d-2", "i-1"), new_event("d-3", "i-2"))
    assert claim_next(conn).delivery_id == "d-1"
    assert claim_next(conn).delivery_id == "d-3"
    assert claim_next(conn) is None


def test_next_event_for_issue_is_claimable_once_first_is_done(database_url, conn):
    record(database_url, new_event("d-1", "i-1"), new_event("d-2", "i-1"))
    first = claim_next(conn)
    mark_done(conn, first.id)
    assert claim_next(conn).delivery_id == "d-2"


def test_events_without_an_issue_do_not_block_each_other(database_url, conn):
    record(database_url, new_event("d-1", None), new_event("d-2", None))
    assert claim_next(conn).delivery_id == "d-1"
    assert claim_next(conn).delivery_id == "d-2"


def test_database_forbids_two_events_in_progress_for_one_issue(database_url, conn):
    record(database_url, new_event("d-1", "i-1"), new_event("d-2", "i-1"))
    conn.execute("UPDATE inbox_events SET status = 'processing' WHERE delivery_id = 'd-1'")
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute("UPDATE inbox_events SET status = 'processing' WHERE delivery_id = 'd-2'")


def test_concurrent_claims_never_take_the_same_event(database_url):
    record(database_url, *(new_event(f"d-{n}", f"i-{n}") for n in range(20)))
    claimed: list[str] = []
    lock = threading.Lock()

    def claimer() -> None:
        with psycopg.connect(database_url, autocommit=True) as c:
            while (event := claim_next(c)) is not None:
                with lock:
                    claimed.append(event.delivery_id)

    threads = [threading.Thread(target=claimer) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(claimed) == sorted(f"d-{n}" for n in range(20))


def claimed_ago(conn, delivery_id: str, age: timedelta) -> None:
    conn.execute(
        "UPDATE inbox_events SET claimed_at = now() - %s WHERE delivery_id = %s",
        (age, delivery_id),
    )


def test_fail_stale_fails_events_past_their_lease(database_url, conn):
    record(database_url, new_event("d-1", "i-1"), new_event("d-2", "i-2"))
    claim_next(conn)
    claim_next(conn)
    claimed_ago(conn, "d-1", timedelta(hours=2))
    claimed_ago(conn, "d-2", timedelta(minutes=5))
    assert fail_stale(conn, lease_seconds=3600) == 1
    assert statuses(conn) == {"d-1": "failed", "d-2": "processing"}
    row = conn.execute(
        "SELECT last_error, finished_at IS NOT NULL FROM inbox_events WHERE delivery_id = 'd-1'"
    ).fetchone()
    assert row == ("lease expired", True)


def test_fail_stale_frees_the_issue_for_its_next_event(database_url, conn):
    record(database_url, new_event("d-1", "i-1"), new_event("d-2", "i-1"))
    claim_next(conn)
    claimed_ago(conn, "d-1", timedelta(hours=2))
    assert claim_next(conn) is None
    fail_stale(conn, lease_seconds=3600)
    assert claim_next(conn).delivery_id == "d-2"


SETTINGS = WorkerSettings(database_url="unused", broker_url="memory://")


def replace_handle_task(monkeypatch, fn) -> None:
    monkeypatch.setattr(worker, "handle_task", lambda event, settings: fn(event))


def test_pick_next_task_marks_success_done(database_url, conn, monkeypatch):
    record(database_url, new_event("d-1"))
    seen = []
    replace_handle_task(monkeypatch, seen.append)
    assert pick_next_task(conn, SETTINGS) is True
    assert [e.delivery_id for e in seen] == ["d-1"]
    row = conn.execute("SELECT status, finished_at IS NOT NULL FROM inbox_events").fetchone()
    assert row == ("done", True)


def test_pick_next_task_records_failure(database_url, conn, monkeypatch):
    record(database_url, new_event("d-1"))

    def boom(event):
        raise ValueError("no acceptance criteria")

    replace_handle_task(monkeypatch, boom)
    assert pick_next_task(conn, SETTINGS) is True
    row = conn.execute("SELECT status, last_error FROM inbox_events").fetchone()
    assert row == ("failed", "ValueError: no acceptance criteria")


def test_pick_next_task_with_empty_inbox_returns_false(conn):
    assert pick_next_task(conn, SETTINGS) is False


def test_pick_pending_tasks_handles_every_claimable_event(database_url, conn, monkeypatch):
    record(database_url, new_event("d-1", "i-1"), new_event("d-2", "i-2"))
    handled = []
    replace_handle_task(monkeypatch, lambda e: handled.append(e.delivery_id))
    assert pick_pending_tasks(conn, SETTINGS) == 2
    assert handled == ["d-1", "d-2"]
    assert statuses(conn) == {"d-1": "done", "d-2": "done"}
    assert pick_pending_tasks(conn, SETTINGS) == 0


def test_pick_pending_tasks_keeps_going_after_a_failure(database_url, conn, monkeypatch):
    record(database_url, new_event("d-1", "i-1"), new_event("d-2", "i-2"))

    def fail_first(event):
        if event.delivery_id == "d-1":
            raise RuntimeError("boom")

    replace_handle_task(monkeypatch, fail_first)
    assert pick_pending_tasks(conn, SETTINGS) == 2
    assert statuses(conn) == {"d-1": "failed", "d-2": "done"}
