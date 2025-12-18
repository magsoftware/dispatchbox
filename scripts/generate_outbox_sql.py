"""Generate SQL INSERT statements with sample outbox events."""

import json

from outbox_generator import STATUSES, generate_event

NUM_RECORDS = 100

values = []

for i in range(1, NUM_RECORDS + 1):
    event = generate_event(i, STATUSES)
    payload_json = json.dumps(event["payload"]).replace("'", "''")
    values.append(
        (
            f"('{event['aggregate_type']}', "
            f"'{event['aggregate_id']}', "
            f"'{event['event_type']}', "
            f"'{payload_json}'::jsonb, "
            f"'{event['status']}', "
            f"{event['attempts']}, "
            f"now() - interval '{event['next_run_offset']} seconds')"
        )
    )

# dzielimy na paczki po 100 rekordów, żeby nie generować 1000 w jednym INSERT (bezpieczniejsze)
BATCH_SIZE = 100
for start in range(0, len(values), BATCH_SIZE):
    batch = values[start:start + BATCH_SIZE]
    sql = (
        "INSERT INTO outbox_event "
        "(aggregate_type, aggregate_id, event_type, payload, status, attempts, next_run_at) "
        "VALUES\n"
    )
    sql += ",\n".join(batch) + ";\n"
    print(sql)
