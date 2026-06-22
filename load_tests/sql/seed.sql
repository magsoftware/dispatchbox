\set ON_ERROR_STOP on

INSERT INTO outbox_event (
    aggregate_type,
    aggregate_id,
    event_type,
    payload,
    status,
    attempts,
    next_run_at
)
SELECT
    'load',
    generated_id::text,
    :'event_type',
    jsonb_build_object('loadId', generated_id),
    'pending',
    0,
    now()
FROM generate_series(1, :'event_count'::bigint) AS generated_id;
