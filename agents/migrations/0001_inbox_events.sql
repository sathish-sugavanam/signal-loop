-- Durable inbox of Linear webhook deliveries. The webhook inserts, the worker claims.
CREATE TABLE inbox_events (
    id               bigserial PRIMARY KEY,
    source           text        NOT NULL DEFAULT 'linear',
    delivery_id      text        NOT NULL UNIQUE,
    action           text,
    issue_id         text,       -- Linear's readable key (SIG-7); the UUID if Linear omits it
    payload          jsonb       NOT NULL,
    status           text        NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'processing', 'done', 'failed')),
    attempts         integer     NOT NULL DEFAULT 0,
    received_at      timestamptz NOT NULL DEFAULT now(),
    claimed_at       timestamptz,
    finished_at      timestamptz,
    last_error       text
);

-- The worker scans pending rows oldest first.
CREATE INDEX inbox_events_pending_idx ON inbox_events (id) WHERE status = 'pending';

-- At most one event per issue is being worked on at any time, even with several workers.
CREATE UNIQUE INDEX inbox_events_one_processing_per_issue
    ON inbox_events (issue_id) WHERE status = 'processing';
