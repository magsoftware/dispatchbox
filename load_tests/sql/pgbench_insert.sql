\set aggregate_id random(1, 2000000000)

INSERT INTO outbox_event (
    aggregate_type,
    aggregate_id,
    event_type,
    payload,
    status,
    attempts,
    next_run_at
)
VALUES (
    'load',
    CAST(:aggregate_id AS text),
    'load.test',
    jsonb_build_object('loadId', :aggregate_id),
    'pending',
    0,
    now()
);
