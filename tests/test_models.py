"""Tests for OutboxEvent model."""

from datetime import datetime, timezone

import pytest

from dispatchbox.models import OutboxEvent


def test_from_dict_with_all_fields(sample_event_dict):
    """Test creating OutboxEvent from dictionary with all fields."""
    event = OutboxEvent.from_dict(sample_event_dict)

    assert event.id == 1
    assert event.aggregate_type == "order"
    assert event.aggregate_id == "12345"
    assert event.event_type == "order.created"
    assert event.payload == {"orderId": "12345", "customerId": "C001", "totalCents": 5000}
    assert event.status == "pending"
    assert event.attempts == 0
    assert isinstance(event.next_run_at, datetime)
    assert isinstance(event.created_at, datetime)


def test_from_dict_with_minimal_fields(sample_event_dict_minimal):
    """Test creating OutboxEvent from dictionary with only required fields."""
    event = OutboxEvent.from_dict(sample_event_dict_minimal)

    assert event.id is None
    assert event.aggregate_type == "order"
    assert event.aggregate_id == "12345"
    assert event.event_type == "order.created"
    assert event.status == "pending"
    assert event.attempts == 0
    assert isinstance(event.next_run_at, datetime)
    assert event.created_at is None


def test_from_dict_missing_next_run_at():
    """Test that ValueError is raised when next_run_at is missing."""
    data = {
        "aggregate_type": "order",
        "aggregate_id": "123",
        "event_type": "order.created",
        "payload": {},
        "status": "pending",
        "attempts": 0,
    }

    with pytest.raises(ValueError, match="next_run_at is required"):
        OutboxEvent.from_dict(data)


def test_from_dict_with_defaults():
    """Test that default values are used when fields are missing."""
    data = {
        "aggregate_type": "order",
        "aggregate_id": "123",
        "event_type": "order.created",
        "payload": {},
        "next_run_at": datetime.now(timezone.utc),
    }

    event = OutboxEvent.from_dict(data)

    assert event.status == "pending"  # default
    assert event.attempts == 0  # default
    assert event.id is None
    assert event.created_at is None


def test_to_dict_with_all_fields(sample_event):
    """Test converting OutboxEvent to dictionary with all fields."""
    result = sample_event.to_dict()

    assert result["id"] == 1
    assert result["aggregate_type"] == "order"
    assert result["aggregate_id"] == "12345"
    assert result["event_type"] == "order.created"
    assert result["payload"] == {"orderId": "12345", "customerId": "C001", "totalCents": 5000}
    assert result["status"] == "pending"
    assert result["attempts"] == 0
    assert isinstance(result["next_run_at"], str)  # ISO 8601 string for JSON serialization
    assert isinstance(result["created_at"], str)  # ISO 8601 string for JSON serialization


def test_to_dict_without_optional_fields(sample_event_dict_minimal):
    """Test converting OutboxEvent to dictionary without optional fields."""
    event = OutboxEvent.from_dict(sample_event_dict_minimal)
    result = event.to_dict()

    assert "id" not in result
    assert "created_at" not in result
    assert result["aggregate_type"] == "order"
    assert result["status"] == "pending"


def test_round_trip(sample_event_dict):
    """Test round-trip conversion: dict -> OutboxEvent -> dict -> OutboxEvent."""
    # First conversion
    event1 = OutboxEvent.from_dict(sample_event_dict)
    dict1 = event1.to_dict()

    # Second conversion (need to ensure next_run_at is present)
    dict1["next_run_at"] = event1.next_run_at
    event2 = OutboxEvent.from_dict(dict1)
    dict2 = event2.to_dict()

    # Compare key fields
    assert event1.id == event2.id
    assert event1.aggregate_type == event2.aggregate_type
    assert event1.aggregate_id == event2.aggregate_id
    assert event1.event_type == event2.event_type
    assert event1.payload == event2.payload
    assert event1.status == event2.status
    assert event1.attempts == event2.attempts


def test_different_status_values():
    """Test that different status values are accepted."""
    statuses = ["pending", "retry", "done", "dead"]

    for status in statuses:
        data = {
            "aggregate_type": "order",
            "aggregate_id": "123",
            "event_type": "order.created",
            "payload": {},
            "status": status,
            "attempts": 0,
            "next_run_at": datetime.now(timezone.utc),
        }
        event = OutboxEvent.from_dict(data)
        assert event.status == status


def test_event_with_high_attempts():
    """Test event with high attempts count."""
    data = {
        "id": 100,
        "aggregate_type": "order",
        "aggregate_id": "123",
        "event_type": "order.created",
        "payload": {},
        "status": "retry",
        "attempts": 5,
        "next_run_at": datetime.now(timezone.utc),
    }

    event = OutboxEvent.from_dict(data)
    assert event.attempts == 5
    assert event.status == "retry"
