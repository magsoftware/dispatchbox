import random
from datetime import datetime, timedelta, timezone

from faker import Faker


fake = Faker()

STATUSES = ["pending", "retry", "done", "dead"]


def generate_event(index: int, statuses=None):
    """Generate a single outbox event payload for test/demo data."""
    if statuses is None:
        statuses = STATUSES

    aggregate_type = random.choice(["order", "invoice", "user"])

    if aggregate_type == "order":
        aggregate_id = str(1000 + index)
        event_type = "order.created"
        payload = {
            "orderId": aggregate_id,
            "customerId": "C" + str(index).zfill(3),
            "totalCents": random.randint(1000, 20000),
        }
    elif aggregate_type == "invoice":
        aggregate_id = str(2000 + index)
        event_type = "invoice.generated"
        payload = {
            "invoiceId": aggregate_id,
            "orderId": str(1000 + index),
            "amountCents": random.randint(1000, 20000),
        }
    else:  # user
        aggregate_id = f"U{index:04d}"
        event_type = "user.registered"
        payload = {
            "userId": aggregate_id,
            "email": fake.email(),
        }

    status = random.choice(statuses)
    attempts = random.randint(0, 5)
    next_run_offset = random.randint(0, 600)
    next_run_at = datetime.now(timezone.utc) - timedelta(seconds=next_run_offset)

    return {
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "event_type": event_type,
        "payload": payload,
        "status": status,
        "attempts": attempts,
        "next_run_at": next_run_at,
        "next_run_offset": next_run_offset,
    }



