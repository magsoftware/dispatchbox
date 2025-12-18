import psycopg2
import json
from psycopg2.extras import execute_values
from outbox_generator import STATUSES, generate_event

DSN = "host=localhost port=5432 dbname=outbox user=postgres password=postgres"
NUM_RECORDS = 1000
BATCH_SIZE = 100

def generate_record(index):
    event = generate_event(index, STATUSES)
    return (
        event["aggregate_type"],
        event["aggregate_id"],
        event["event_type"],
        json.dumps(event["payload"]),
        event["status"],
        event["attempts"],
        event["next_run_at"],
    )

with psycopg2.connect(DSN) as conn:
    with conn.cursor() as cur:
        for batch_start in range(1, NUM_RECORDS + 1, BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, NUM_RECORDS + 1)
            batch = [generate_record(i) for i in range(batch_start, batch_end)]

            execute_values(
                cur,
                """
                INSERT INTO outbox_event
                (aggregate_type, aggregate_id, event_type, payload, status, attempts, next_run_at)
                VALUES %s
                """,
                batch,
                template="(%s,%s,%s,%s::jsonb,%s,%s,%s)"
            )

            conn.commit()
            if batch_start % 100_000 == 1:
                print(f"Inserted {batch_start - 1} records...")

print("Finished inserting all records!")

