-- GŁÓWNA TABELA
CREATE TABLE outbox_event (
  id             BIGSERIAL PRIMARY KEY,
  aggregate_type TEXT        NOT NULL,   -- 'order', 'invoice', 'user'
  aggregate_id   TEXT        NOT NULL,   -- '12345'
  event_type     TEXT        NOT NULL,   -- 'order.created'
  payload        JSONB       NOT NULL,   -- everything consumers need
  status         TEXT        NOT NULL DEFAULT 'pending',  -- pending | retry | done | dead
  attempts       INT         NOT NULL DEFAULT 0,
  next_run_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- OPTYMALNY INDEKS DLA WORKERÓW
CREATE INDEX idx_outbox_due
  ON outbox_event (next_run_at ASC)
  WHERE status IN ('pending','retry');

-- TABELA ARCHIWALNA
CREATE TABLE outbox_event_archive (
    id              BIGINT PRIMARY KEY,
    aggregate_type  TEXT NOT NULL,
    aggregate_id    TEXT NOT NULL,
    event_type      TEXT NOT NULL,
    payload         JSONB NOT NULL,
    status          TEXT NOT NULL,
    attempts        INT NOT NULL,
    next_run_at     TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL,
    archived_at     TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_outbox_archive_date ON outbox_event_archive (archived_at);

-- FUNKCJA ARCHIWIZUJĄCA (DLA PG_CRON)
CREATE OR REPLACE FUNCTION archive_outbox_events(retention_days INT DEFAULT 7)
RETURNS void AS $$
DECLARE
    rows_moved INT;
BEGIN
    LOOP
        WITH moved_rows AS (
            DELETE FROM outbox_event
            WHERE id IN (
                SELECT id FROM outbox_event
                WHERE status = 'done'
                  AND created_at < NOW() - (retention_days || ' days')::interval
                LIMIT 5000 -- Paczkowanie zapobiega długim blokadom
            )
            RETURNING id, aggregate_type, aggregate_id, event_type, payload, status, attempts, next_run_at, created_at
        )
        INSERT INTO outbox_event_archive (id, aggregate_type, aggregate_id, event_type, payload, status, attempts, next_run_at, created_at)
        SELECT * FROM moved_rows;

        GET DIAGNOSTICS rows_moved = ROW_COUNT;
        EXIT WHEN rows_moved = 0;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- PGPASSWORD=postgres psql -h localhost -p 5432 -U postgres -d outbox
-- REJESTRACJA ZADANIA W PG_CRON (Codziennie o 3:00 rano)
-- Uwaga: zadanie rejestrujemy w bazie 'postgres' lub tam, gdzie działa pg_cron
-- SELECT cron.schedule('archive-outbox-job', '0 3 * * *', 'SELECT archive_outbox_events(7)');
