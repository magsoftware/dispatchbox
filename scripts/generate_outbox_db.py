import random
from datetime import datetime, timedelta, timezone
from faker import Faker
import psycopg2
import json
from psycopg2.extras import execute_values

fake = Faker()

# -----------------------------
# Konfiguracja połączenia DB
# -----------------------------
DSN = "host=localhost port=5432 dbname=outbox user=postgres password=postgres"
NUM_RECORDS = 1000
BATCH_SIZE = 100
STATUSES = ['pending', 'retry', 'done', 'dead']

# -----------------------------
# Funkcja generująca pojedynczy rekord
# -----------------------------
def generate_record(i):
    aggregate_type = random.choice(['order', 'invoice', 'user'])

    if aggregate_type == 'order':
        aggregate_id = str(1000 + i)
        event_type = 'order.created'
        payload = {
            'orderId': aggregate_id,
            'customerId': 'C' + str(i).zfill(3),
            'totalCents': random.randint(1000, 20000)
        }
    elif aggregate_type == 'invoice':
        aggregate_id = str(2000 + i)
        event_type = 'invoice.generated'
        payload = {
            'invoiceId': aggregate_id,
            'orderId': str(1000 + i),
            'amountCents': random.randint(1000, 20000)
        }
    else:  # user
        aggregate_id = f'U{i:04d}'
        event_type = 'user.registered'
        payload = {
            'userId': aggregate_id,
            'email': fake.email()
        }

    status = random.choice(STATUSES)
    attempts = random.randint(0, 5)
    next_run_offset = random.randint(0, 600)  # sekundy w przeszłości
    next_run_at = datetime.utcnow() - timedelta(seconds=next_run_offset)
    next_run_at = datetime.now(timezone.utc) - timedelta(seconds=next_run_offset)

    return (aggregate_type, aggregate_id, event_type, json.dumps(payload), status, attempts, next_run_at)

# -----------------------------
# Wstawianie paczkami do DB
# -----------------------------
with psycopg2.connect(DSN) as conn:
    with conn.cursor() as cur:
        for batch_start in range(1, NUM_RECORDS + 1, BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, NUM_RECORDS + 1)
            batch = [generate_record(i) for i in range(batch_start, batch_end)]

            # execute_values – szybkie bulk insert
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

