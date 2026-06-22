\set ON_ERROR_STOP on

SELECT status, COUNT(*) AS events
FROM outbox_event
WHERE event_type = :'event_type'
GROUP BY status
ORDER BY status;
