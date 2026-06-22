\set ON_ERROR_STOP on

TRUNCATE TABLE outbox_event, outbox_event_archive RESTART IDENTITY;
