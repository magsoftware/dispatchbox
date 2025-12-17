from faker import Faker
import json
import random

fake = Faker()

num_records = 100
statuses = ['pending', 'retry', 'done', 'dead']

values = []

for i in range(1, num_records + 1):
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

    status = random.choice(statuses)
    attempts = random.randint(0, 5)
    # losowy next_run_at w przeszłości 0-10 minut
    next_run_offset = random.randint(0, 600)
    values.append(f"('{aggregate_type}', '{aggregate_id}', '{event_type}', '{json.dumps(payload)}'::jsonb, '{status}', {attempts}, now() - interval '{next_run_offset} seconds')")

# dzielimy na paczki po 100 rekordów, żeby nie generować 1000 w jednym INSERT (bezpieczniejsze)
batch_size = 100
for start in range(0, len(values), batch_size):
    batch = values[start:start+batch_size]
    sql = "INSERT INTO outbox_event (aggregate_type, aggregate_id, event_type, payload, status, attempts, next_run_at) VALUES\n"
    sql += ",\n".join(batch) + ";\n"
    print(sql)

