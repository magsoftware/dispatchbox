"""Tests for Dead Letter Queue methods in repository."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch

import psycopg2
import pytest

from dispatchbox.models import OutboxEvent
from dispatchbox.repository import OutboxRepository


@pytest.fixture
def mock_db_connection():
    """Mock database connection."""
    with patch("dispatchbox.repository.psycopg2.connect") as mock_connect:
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__ = lambda x: x
        mock_conn.cursor.return_value.__exit__ = lambda *args: None
        mock_conn.commit = Mock()
        mock_connect.return_value = mock_conn
        yield mock_conn


@pytest.fixture
def mock_cursor(mock_db_connection):
    """Mock database cursor."""
    from psycopg2.extras import RealDictCursor

    mock_cur = MagicMock()
    mock_cur.__enter__ = lambda x: x
    mock_cur.__exit__ = lambda *args: None
    mock_db_connection.cursor.return_value = mock_cur
    return mock_cur


@pytest.fixture
def sample_dead_event_dict():
    """Sample dead event dictionary."""
    return {
        "id": 1,
        "aggregate_type": "order",
        "aggregate_id": "12345",
        "event_type": "order.created",
        "payload": {"orderId": "12345", "customerId": "C001"},
        "status": "dead",
        "attempts": 5,
        "next_run_at": datetime.now(timezone.utc),
        "created_at": datetime.now(timezone.utc),
    }


def test_fetch_dead_events(mock_db_connection, mock_cursor, sample_dead_event_dict):
    """Test fetch_dead_events returns dead events."""

    class MockRow:
        def __init__(self, data):
            self._data = data

        def __getitem__(self, key):
            return self._data[key]

        def keys(self):
            return self._data.keys()

        def __iter__(self):
            return iter(self._data)

        def __contains__(self, key):
            return key in self._data

    mock_row = MockRow(sample_dead_event_dict)
    mock_cursor.fetchall.return_value = [mock_row]

    repo = OutboxRepository("host=localhost dbname=test")
    events = repo.fetch_dead_events(limit=10, offset=0)

    assert len(events) == 1
    assert isinstance(events[0], OutboxEvent)
    assert events[0].id == 1
    assert events[0].status == "dead"
    assert events[0].attempts == 5


def test_fetch_dead_events_with_filters(mock_db_connection, mock_cursor):
    """Test fetch_dead_events with filters."""
    mock_cursor.fetchall.return_value = []

    repo = OutboxRepository("host=localhost dbname=test")
    repo.fetch_dead_events(limit=10, offset=0, aggregate_type="order", event_type="order.created")

    # Verify SQL contains filters (after SELECT 1 and SET timeout)
    assert mock_cursor.execute.call_count >= 3
    call_args = mock_cursor.execute.call_args_list[-1]
    sql = call_args[0][0]
    assert "aggregate_type" in sql
    assert "event_type" in sql


def test_fetch_dead_events_invalid_params(mock_db_connection):
    """Test fetch_dead_events with invalid parameters."""
    repo = OutboxRepository("host=localhost dbname=test")

    with pytest.raises(ValueError, match="limit must be at least 1"):
        repo.fetch_dead_events(limit=0)

    with pytest.raises(ValueError, match="offset must be non-negative"):
        repo.fetch_dead_events(limit=10, offset=-1)


def test_count_dead_events(mock_db_connection, mock_cursor):
    """Test count_dead_events returns count."""

    class MockRow:
        def __init__(self, count):
            self._data = {"count": count}

        def __getitem__(self, key):
            return self._data[key]

        def keys(self):
            return self._data.keys()

        def __iter__(self):
            return iter(self._data)

        def __contains__(self, key):
            return key in self._data

    mock_cursor.fetchone.return_value = MockRow(42)

    repo = OutboxRepository("host=localhost dbname=test")
    count = repo.count_dead_events()

    assert count == 42


def test_count_dead_events_with_filters(mock_db_connection, mock_cursor):
    """Test count_dead_events with filters."""

    class MockRow:
        def __init__(self, count):
            self._data = {"count": count}

        def __getitem__(self, key):
            return self._data[key]

        def keys(self):
            return self._data.keys()

        def __iter__(self):
            return iter(self._data)

        def __contains__(self, key):
            return key in self._data

    mock_cursor.fetchone.return_value = MockRow(5)

    repo = OutboxRepository("host=localhost dbname=test")
    count = repo.count_dead_events(aggregate_type="order")

    assert count == 5
    # Verify SQL contains filter (after SELECT 1 and SET timeout)
    assert mock_cursor.execute.call_count >= 3
    call_args = mock_cursor.execute.call_args_list[-1]
    sql = call_args[0][0]
    assert "aggregate_type" in sql


def test_get_dead_event(mock_db_connection, mock_cursor, sample_dead_event_dict):
    """Test get_dead_event returns event if found."""

    class MockRow:
        def __init__(self, data):
            self._data = data

        def __getitem__(self, key):
            return self._data[key]

        def keys(self):
            return self._data.keys()

        def __iter__(self):
            return iter(self._data)

        def __contains__(self, key):
            return key in self._data

    mock_cursor.fetchone.return_value = MockRow(sample_dead_event_dict)

    repo = OutboxRepository("host=localhost dbname=test")
    event = repo.get_dead_event(1)

    assert event is not None
    assert event.id == 1
    assert event.status == "dead"


def test_get_dead_event_not_found(mock_db_connection, mock_cursor):
    """Test get_dead_event returns None if not found."""
    mock_cursor.fetchone.return_value = None

    repo = OutboxRepository("host=localhost dbname=test")
    event = repo.get_dead_event(999)

    assert event is None


def test_get_dead_event_invalid_id(mock_db_connection):
    """Test get_dead_event with invalid event_id."""
    repo = OutboxRepository("host=localhost dbname=test")

    with pytest.raises(ValueError, match="event_id must be a positive integer"):
        repo.get_dead_event(0)

    with pytest.raises(ValueError, match="event_id must be a positive integer"):
        repo.get_dead_event(-1)


def test_retry_dead_event(mock_db_connection, mock_cursor):
    """Test retry_dead_event resets event to pending."""
    mock_cursor.rowcount = 1

    repo = OutboxRepository("host=localhost dbname=test")
    success = repo.retry_dead_event(123)

    assert success is True
    # Verify UPDATE was called (after SELECT 1 and SET timeout)
    assert mock_cursor.execute.call_count >= 3
    call_args = mock_cursor.execute.call_args_list[-1]
    sql = call_args[0][0]
    assert "UPDATE" in sql
    assert "status = 'pending'" in sql
    assert "attempts = 0" in sql
    mock_db_connection.commit.assert_called()


def test_retry_dead_event_not_found(mock_db_connection, mock_cursor):
    """Test retry_dead_event returns False if event not found."""
    mock_cursor.rowcount = 0

    repo = OutboxRepository("host=localhost dbname=test")
    success = repo.retry_dead_event(999)

    assert success is False


def test_retry_dead_event_invalid_id(mock_db_connection):
    """Test retry_dead_event with invalid event_id."""
    repo = OutboxRepository("host=localhost dbname=test")

    with pytest.raises(ValueError, match="event_id must be a positive integer"):
        repo.retry_dead_event(0)


def test_retry_dead_events_batch(mock_db_connection, mock_cursor):
    """Test retry_dead_events_batch resets multiple events."""
    mock_cursor.rowcount = 3

    repo = OutboxRepository("host=localhost dbname=test")
    count = repo.retry_dead_events_batch([1, 2, 3])

    assert count == 3
    # Verify UPDATE was called with ANY clause (after SELECT 1 and SET timeout)
    assert mock_cursor.execute.call_count >= 3
    call_args = mock_cursor.execute.call_args_list[-1]
    sql = call_args[0][0]
    assert "UPDATE" in sql
    assert "ANY" in sql
    assert "status = 'pending'" in sql
    # Verify the list was passed as parameter
    assert call_args[0][1] == ([1, 2, 3],)


def test_retry_dead_events_batch_empty(mock_db_connection):
    """Test retry_dead_events_batch with empty list."""
    repo = OutboxRepository("host=localhost dbname=test")

    with pytest.raises(ValueError, match="event_ids cannot be empty"):
        repo.retry_dead_events_batch([])


def test_retry_dead_events_batch_invalid_ids(mock_db_connection):
    """Test retry_dead_events_batch with invalid IDs."""
    repo = OutboxRepository("host=localhost dbname=test")

    with pytest.raises(ValueError, match="All event_ids must be positive integers"):
        repo.retry_dead_events_batch([0, 1, 2])

    with pytest.raises(ValueError, match="All event_ids must be positive integers"):
        repo.retry_dead_events_batch([-1, 1, 2])
