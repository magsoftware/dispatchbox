import json
from outbox_generator import STATUSES, generate_event

num_records = 100

values = []

for i in range(1, num_records + 1):
    event = generate_event(i, STATUSES)
    payload_json = json.dumps(event["payload"]).replace("'", "''")
    values.append(
        "('{aggregate_type}', '{aggregate_id}', '{event_type}', "
        "'{payload}'::jsonb, '{status}', {attempts}, "
        "now() - interval '{offset} seconds')".format(
            aggregate_type=event["aggregate_type"],
            aggregate_id=event["aggregate_id"],
            event_type=event["event_type"],
            payload=payload_json,
            status=event["status"],
            attempts=event["attempts"],
            offset=event["next_run_offset"],
        )
    )

# dzielimy na paczki po 100 rekordów, żeby nie generować 1000 w jednym INSERT (bezpieczniejsze)
batch_size = 100
for start in range(0, len(values), batch_size):
    batch = values[start:start+batch_size]
    sql = "INSERT INTO outbox_event (aggregate_type, aggregate_id, event_type, payload, status, attempts, next_run_at) VALUES\n"
    sql += ",\n".join(batch) + ";\n"
    print(sql)

