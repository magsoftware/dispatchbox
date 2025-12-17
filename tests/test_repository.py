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
    # _check_connection() calls execute('SELECT 1'), then SET statement_timeout, then actual query
    assert mock_cursor.execute.call_count == 3
    # Verify the actual query was called (last call)
    assert "SELECT id" in mock_cursor.execute.call_args_list[2][0][0]
    mock_db_connection.commit.assert_called()


def test_fetch_pending_empty_result(mock_db_connection, mock_cursor):
    """Test fetch_pending returns empty list when no events."""
    mock_cursor.fetchall.return_value = []
    
    repo = OutboxRepository("host=localhost dbname=test")
    events = repo.fetch_pending(10)
    
    assert events == []
    # _check_connection() calls execute('SELECT 1'), then SET statement_timeout, then actual query
    assert mock_cursor.execute.call_count == 3
    # Verify the actual query was called (last call)
    assert "SELECT id" in mock_cursor.execute.call_args_list[2][0][0]
    mock_db_connection.commit.assert_called()


def test_fetch_pending_calls_correct_sql(mock_db_connection, mock_cursor):
    """Test fetch_pending executes correct SQL query."""
    mock_cursor.fetchall.return_value = []
    
    repo = OutboxRepository("host=localhost dbname=test")
    repo.fetch_pending(5)
    
    # Check SQL query was called with correct parameters (last call, after SELECT 1 and SET timeout)
    assert mock_cursor.execute.call_count == 3
    call_args = mock_cursor.execute.call_args_list[2]
    assert call_args is not None
    # Verify it uses the class constant (normalize whitespace for comparison)
    sql_called = call_args[0][0].strip()
    sql_expected = OutboxRepository.FETCH_PENDING_SQL.strip()
    assert sql_called == sql_expected
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
    
    # _check_connection() calls execute('SELECT 1'), then SET statement_timeout, then UPDATE
    assert mock_cursor.execute.call_count == 3
    # Verify the UPDATE query was called (last call)
    call_args = mock_cursor.execute.call_args_list[2]
    sql = call_args[0][0]
    assert "UPDATE" in sql
    assert "status = 'done'" in sql
    assert call_args[0][1] == (123,)
    mock_db_connection.commit.assert_called()


def test_mark_retry(mock_db_connection, mock_cursor):
    """Test mark_retry updates event status and next_run_at."""
    mock_cursor.rowcount = 1  # Mock rowcount for UPDATE
    mock_cursor.fetchone.return_value = ('retry',)  # Mock fetchone for status check
    
    repo = OutboxRepository("host=localhost dbname=test", retry_backoff_seconds=60)
    
    with patch("dispatchbox.repository.datetime") as mock_datetime:
        mock_now = datetime.now(timezone.utc)
        mock_datetime.now.return_value = mock_now
        mock_datetime.timedelta = timedelta
        mock_datetime.timezone = timezone
        
        repo.mark_retry(456)
        
        # _check_connection() calls execute('SELECT 1'), then SET statement_timeout, then UPDATE, then SELECT status
        assert mock_cursor.execute.call_count == 4
        # Verify the UPDATE query was called (third call)
        call_args = mock_cursor.execute.call_args_list[2]
        sql = call_args[0][0]
        assert "UPDATE" in sql
        assert "status = 'retry'" in sql or "status = CASE" in sql  # Updated to use CASE
        assert "next_run_at" in sql
        # Check that event_id is in parameters
        assert 456 in call_args[0][1]
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


def test_mark_retry_exceeds_max_attempts(mock_db_connection, mock_cursor):
    """Test that mark_retry marks event as 'dead' when max_attempts is exceeded."""
    mock_cursor.rowcount = 1
    mock_cursor.fetchone.return_value = ('dead',)  # Event marked as dead
    
    repo = OutboxRepository("host=localhost dbname=test", max_attempts=3)
    
    # Simulate event with attempts = 2 (next retry will be 3, which equals max_attempts)
    # We need to mock the SQL to return the correct status
    with patch("dispatchbox.repository.datetime") as mock_datetime:
        mock_now = datetime.now(timezone.utc)
        mock_datetime.now.return_value = mock_now
        mock_datetime.timedelta = timedelta
        mock_datetime.timezone = timezone
        
        repo.mark_retry(789)
        
        # Verify UPDATE was called with CASE statement
        assert mock_cursor.execute.call_count == 4
        call_args = mock_cursor.execute.call_args_list[2]
        sql = call_args[0][0]
        assert "UPDATE" in sql
        assert "CASE" in sql  # Should use CASE to check max_attempts
        assert "dead" in sql
        mock_db_connection.commit.assert_called()


def test_repository_init_invalid_max_attempts():
    """Test that max_attempts < 1 raises ValueError."""
    with pytest.raises(ValueError, match="max_attempts must be at least 1"):
        OutboxRepository("host=localhost dbname=test", max_attempts=0)


def test_fetch_pending_invalid_batch_size(mock_db_connection):
    """Test that fetch_pending with invalid batch_size raises ValueError."""
    repo = OutboxRepository("host=localhost dbname=test")
    
    with pytest.raises(ValueError, match="batch_size must be at least 1"):
        repo.fetch_pending(0)
    
    with pytest.raises(ValueError, match="batch_size must be at least 1"):
        repo.fetch_pending(-1)


def test_mark_success_invalid_event_id(mock_db_connection):
    """Test that mark_success with invalid event_id raises ValueError."""
    repo = OutboxRepository("host=localhost dbname=test")
    
    with pytest.raises(ValueError, match="event_id must be a positive integer"):
        repo.mark_success(0)
    
    with pytest.raises(ValueError, match="event_id must be a positive integer"):
        repo.mark_success(-1)
    
    with pytest.raises(ValueError, match="event_id must be a positive integer"):
        repo.mark_success(None)


def test_mark_retry_invalid_event_id(mock_db_connection):
    """Test that mark_retry with invalid event_id raises ValueError."""
    repo = OutboxRepository("host=localhost dbname=test")
    
    with pytest.raises(ValueError, match="event_id must be a positive integer"):
        repo.mark_retry(0)
    
    with pytest.raises(ValueError, match="event_id must be a positive integer"):
        repo.mark_retry(-1)
    
    with pytest.raises(ValueError, match="event_id must be a positive integer"):
        repo.mark_retry(None)

