"""Shared fixtures for tests."""

from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import MagicMock, Mock

import pytest

from dispatchbox.models import OutboxEvent


@pytest.fixture
def sample_event_dict() -> Dict[str, Any]:
    """Sample event dictionary for testing."""
    return {
        "id": 1,
        "aggregate_type": "order",
        "aggregate_id": "12345",
        "event_type": "order.created",
        "payload": {"orderId": "12345", "customerId": "C001", "totalCents": 5000},
        "status": "pending",
        "attempts": 0,
        "next_run_at": datetime.now(timezone.utc),
        "created_at": datetime.now(timezone.utc),
    }


@pytest.fixture
def sample_event(sample_event_dict: Dict[str, Any]) -> OutboxEvent:
    """Sample OutboxEvent instance for testing."""
    return OutboxEvent.from_dict(sample_event_dict)


@pytest.fixture
def sample_event_dict_minimal() -> Dict[str, Any]:
    """Minimal event dictionary (only required fields)."""
    return {
        "aggregate_type": "order",
        "aggregate_id": "12345",
        "event_type": "order.created",
        "payload": {"orderId": "12345"},
        "status": "pending",
        "attempts": 0,
        "next_run_at": datetime.now(timezone.utc),
    }


@pytest.fixture
def sample_payload() -> Dict[str, Any]:
    """Sample payload for handlers."""
    return {
        "orderId": "12345",
        "customerId": "C001",
        "totalCents": 5000,
    }


@pytest.fixture
def mock_db_connection(mocker):
    """Mock PostgreSQL connection."""
    mock_conn = MagicMock()
    mock_conn.autocommit = False
    mock_conn.cursor.return_value.__enter__ = Mock(return_value=Mock())
    mock_conn.cursor.return_value.__exit__ = Mock(return_value=None)
    mocker.patch("psycopg2.connect", return_value=mock_conn)
    return mock_conn


@pytest.fixture
def mock_cursor(mock_db_connection):
    """Mock database cursor."""
    mock_cur = MagicMock()
    # Setup context manager for cursor
    mock_cur.__enter__ = Mock(return_value=mock_cur)
    mock_cur.__exit__ = Mock(return_value=None)
    # Make cursor() return the mock cursor
    mock_db_connection.cursor.return_value = mock_cur
    return mock_cur


@pytest.fixture
def mock_repository(mocker):
    """Mock OutboxRepository."""
    from dispatchbox.repository import OutboxRepository

    mock_repo = mocker.Mock(spec=OutboxRepository)
    mock_repo.fetch_pending.return_value = []
    mock_repo.mark_success = mocker.Mock()
    mock_repo.mark_retry = mocker.Mock()
    mock_repo.close = mocker.Mock()
    mock_repo.__enter__ = Mock(return_value=mock_repo)
    mock_repo.__exit__ = Mock(return_value=None)
    mock_repo.dsn = "host=localhost dbname=test"
    mock_repo.retry_backoff = 30
    return mock_repo
