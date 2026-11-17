"""The inbox: durable storage for incoming events.

The webhook writes with `PostgresInbox.record` (async). The worker claims and
finishes events with the plain functions below (sync), each taking an
autocommit connection.
"""

from dataclasses import dataclass
from typing import Any, Protocol

import psycopg
from psycopg.rows import class_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool


@dataclass(frozen=True)
class NewEvent:
    delivery_id: str
    action: str | None
    issue_id: str | None
    payload: dict[str, Any]


@dataclass(frozen=True)
class InboxEvent:
    id: int
    delivery_id: str
    action: str | None
    issue_id: str | None
    payload: dict[str, Any]
    attempts: int


def parse_event_from_linear(delivery_id: str, event_type: str, payload: dict[str, Any]) -> NewEvent:
    """Keys the event by its issue's readable identifier (SIG-7).

    Comment payloads may carry only the issue's UUID; that is used instead.
    """
    data = payload.get("data") or {}
    issue_id = None
    if event_type == "Issue":
        issue_id = data.get("identifier") or data.get("id")
    elif event_type == "Comment":
        issue = data.get("issue") or {}
        issue_id = issue.get("identifier") or data.get("issueId") or issue.get("id")
    return NewEvent(
        delivery_id=delivery_id,
        action=payload.get("action"),
        issue_id=issue_id,
        payload=payload,
    )


class Inbox(Protocol):
    async def record(self, event: NewEvent) -> bool:
        """Stores the event. Returns False if this delivery was already stored."""
        ...


class PostgresInbox:
    def __init__(self, pool: AsyncConnectionPool) -> None:
        self._pool = pool

    async def record(self, event: NewEvent) -> bool:
        async with self._pool.connection() as conn:
            cur = await conn.execute(
                """
                INSERT INTO inbox_events
                    (delivery_id, action, issue_id, payload)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (delivery_id) DO NOTHING
                """,
                (
                    event.delivery_id,
                    event.action,
                    event.issue_id,
                    Jsonb(event.payload),
                ),
            )
            return cur.rowcount == 1


_CLAIM_SQL = """
WITH next AS (
    SELECT e.id
    FROM inbox_events e
    WHERE e.status = 'pending'
      AND NOT EXISTS (
          SELECT 1 FROM inbox_events p
          WHERE p.status = 'processing' AND p.issue_id = e.issue_id
      )
    ORDER BY e.id
    LIMIT 1
    FOR UPDATE SKIP LOCKED
)
UPDATE inbox_events e
SET status = 'processing', attempts = e.attempts + 1, claimed_at = now()
FROM next
WHERE e.id = next.id
RETURNING e.id, e.delivery_id, e.action, e.issue_id, e.payload, e.attempts
"""


def claim_next(conn: psycopg.Connection) -> InboxEvent | None:
    """Claims the oldest pending event whose issue has nothing else in progress."""
    try:
        with conn.transaction(), conn.cursor(row_factory=class_row(InboxEvent)) as cur:
            return cur.execute(_CLAIM_SQL).fetchone()
    except psycopg.errors.UniqueViolation:
        # Another worker claimed an event for the same issue at the same moment.
        return None


def mark_done(conn: psycopg.Connection, event_id: int) -> None:
    conn.execute(
        "UPDATE inbox_events SET status = 'done', finished_at = now(), last_error = NULL"
        " WHERE id = %s",
        (event_id,),
    )


def mark_failed(conn: psycopg.Connection, event_id: int, error: str) -> None:
    conn.execute(
        "UPDATE inbox_events SET status = 'failed', finished_at = now(), last_error = %s"
        " WHERE id = %s",
        (error, event_id),
    )


def fail_stale(conn: psycopg.Connection, lease_seconds: float) -> int:
    """Marks events stuck in progress longer than the lease as failed.

    A worker that crashed mid-event leaves its row in 'processing'; this frees the issue.
    """
    cur = conn.execute(
        "UPDATE inbox_events SET status = 'failed', finished_at = now(),"
        " last_error = 'lease expired'"
        " WHERE status = 'processing' AND claimed_at < now() - make_interval(secs => %s)",
        (lease_seconds,),
    )
    return cur.rowcount
