"""Tests for OutboxRepository."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, MagicMock, patch
from dispatchbox.repository import OutboxRepository
from dispatchbox.models import OutboxEvent


def test_repository_init(mock_db_connection):
    """Test OutboxRepository initialization."""
    dsn = "host=localhost dbname=test"
    repo = OutboxRepository(dsn, retry_backoff_seconds=60)
    
    assert repo.dsn == dsn
    assert repo.retry_backoff == 60
    assert repo.conn is not None
    assert repo.conn.autocommit is False


def test_repository_init_default_retry_backoff(mock_db_connection):
    """Test OutboxRepository initialization with default retry_backoff."""
    repo = OutboxRepository("host=localhost dbname=test")
    
    assert repo.retry_backoff == 30  # default value


def test_fetch_pending_returns_events(mock_db_connection, mock_cursor, sample_event_dict):
    """Test fetch_pending returns list of OutboxEvent instances."""
    # Setup mock cursor to return sample data
    # RealDictCursor returns dict-like objects
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
    
    mock_row = MockRow(sample_event_dict)
    mock_cursor.fetchall.return_value = [mock_row]
    
    repo = OutboxRepository("host=localhost dbname=test")
    events = repo.fetch_pending(10)
    
    assert len(events) == 1
    assert isinstance(events[0], OutboxEvent)
    assert events[0].id == 1
    assert events[0].event_type == "order.created"
    mock_cursor.execute.assert_called_once()
    mock_db_connection.commit.assert_called()


def test_fetch_pending_empty_result(mock_db_connection, mock_cursor):
    """Test fetch_pending returns empty list when no events."""
    mock_cursor.fetchall.return_value = []
    
    repo = OutboxRepository("host=localhost dbname=test")
    events = repo.fetch_pending(10)
    
    assert events == []
    mock_cursor.execute.assert_called_once()
    mock_db_connection.commit.assert_called()


def test_fetch_pending_calls_correct_sql(mock_db_connection, mock_cursor):
    """Test fetch_pending executes correct SQL query."""
    mock_cursor.fetchall.return_value = []
    
    repo = OutboxRepository("host=localhost dbname=test")
    repo.fetch_pending(5)
    
    # Check SQL query was called with correct parameters
    call_args = mock_cursor.execute.call_args
    assert call_args is not None
    sql = call_args[0][0]
    assert "SELECT" in sql
    assert "outbox_event" in sql
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert call_args[0][1] == (5,)  # batch_size parameter


def test_fetch_pending_multiple_events(mock_db_connection, mock_cursor, sample_event_dict):
    """Test fetch_pending handles multiple events."""
    # Create multiple mock rows
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
    
    mock_row1 = MockRow(sample_event_dict)
    
    sample_event_dict2 = sample_event_dict.copy()
    sample_event_dict2["id"] = 2
    mock_row2 = MockRow(sample_event_dict2)
    
    mock_cursor.fetchall.return_value = [mock_row1, mock_row2]
    
    repo = OutboxRepository("host=localhost dbname=test")
    events = repo.fetch_pending(10)
    
    assert len(events) == 2
    assert events[0].id == 1
    assert events[1].id == 2


def test_mark_success(mock_db_connection, mock_cursor):
    """Test mark_success updates event status."""
    repo = OutboxRepository("host=localhost dbname=test")
    repo.mark_success(123)
    
    mock_cursor.execute.assert_called_once()
    call_args = mock_cursor.execute.call_args
    sql = call_args[0][0]
    assert "UPDATE" in sql
    assert "status = 'done'" in sql
    assert call_args[0][1] == (123,)
    mock_db_connection.commit.assert_called()


def test_mark_retry(mock_db_connection, mock_cursor):
    """Test mark_retry updates event status and next_run_at."""
    repo = OutboxRepository("host=localhost dbname=test", retry_backoff_seconds=60)
    
    with patch("dispatchbox.repository.datetime") as mock_datetime:
        mock_now = datetime.now(timezone.utc)
        mock_datetime.utcnow.return_value = mock_now
        mock_datetime.timedelta = timedelta
        
        repo.mark_retry(456)
        
        mock_cursor.execute.assert_called_once()
        call_args = mock_cursor.execute.call_args
        sql = call_args[0][0]
        assert "UPDATE" in sql
        assert "status = 'retry'" in sql
        assert "next_run_at" in sql
        # Check that next_run_at is calculated correctly
        assert call_args[0][1][1] == 456  # event_id
        mock_db_connection.commit.assert_called()


def test_close(mock_db_connection):
    """Test close method closes connection."""
    repo = OutboxRepository("host=localhost dbname=test")
    repo.close()
    
    mock_db_connection.close.assert_called_once()


def test_context_manager(mock_db_connection):
    """Test OutboxRepository as context manager."""
    with OutboxRepository("host=localhost dbname=test") as repo:
        assert repo is not None
    
    mock_db_connection.close.assert_called_once()


def test_context_manager_exception_handling(mock_db_connection):
    """Test context manager closes connection even on exception."""
    try:
        with OutboxRepository("host=localhost dbname=test") as repo:
            raise ValueError("Test exception")
    except ValueError:
        pass
    
    mock_db_connection.close.assert_called_once()


def test_repository_init_empty_dsn():
    """Test that empty DSN raises ValueError."""
    with pytest.raises(ValueError, match="DSN cannot be empty"):
        OutboxRepository("")


def test_repository_init_whitespace_only_dsn():
    """Test that whitespace-only DSN raises ValueError."""
    with pytest.raises(ValueError, match="DSN cannot be empty"):
        OutboxRepository("   ")


def test_repository_init_negative_retry_backoff():
    """Test that negative retry_backoff raises ValueError."""
    with pytest.raises(ValueError, match="retry_backoff_seconds must be non-negative"):
        OutboxRepository("host=localhost dbname=test", retry_backoff_seconds=-1)

