"""Tests for DLQ endpoints in HttpServer."""

import pytest
import json
from unittest.mock import Mock, MagicMock, patch
from bottle import response as bottle_response

from dispatchbox.http_server import HttpServer
from dispatchbox.models import OutboxEvent
from dispatchbox.repository import OutboxRepository


@pytest.fixture
def mock_repository():
    """Mock OutboxRepository."""
    mock_repo = MagicMock(spec=OutboxRepository)
    return mock_repo


@pytest.fixture
def sample_dead_event():
    """Sample dead event."""
    from datetime import datetime, timezone
    return OutboxEvent(
        id=1,
        aggregate_type="order",
        aggregate_id="12345",
        event_type="order.created",
        payload={"orderId": "12345"},
        status="dead",
        attempts=5,
        next_run_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def http_server_with_repo(mock_repository):
    """HttpServer with repository function."""
    def get_repo():
        return mock_repository
    
    server = HttpServer(
        host="127.0.0.1",
        port=8080,
        repository_fn=get_repo,
    )
    return server, mock_repository


def test_list_dead_events(http_server_with_repo, sample_dead_event):
    """Test GET /api/dead-events lists dead events."""
    server, mock_repo = http_server_with_repo
    mock_repo.fetch_dead_events.return_value = [sample_dead_event]
    
    # Mock request.query
    with patch("dispatchbox.http_server.request") as mock_request:
        mock_request.query.get.side_effect = lambda key, default=None: {
            "limit": "100",
            "offset": "0",
        }.get(key, default)
        
        result = server._list_dead_events()
        
        assert "events" in result
        assert len(result["events"]) == 1
        assert result["events"][0]["id"] == 1
        assert result["events"][0]["status"] == "dead"
        assert result["count"] == 1
        assert result["limit"] == 100
        assert result["offset"] == 0
        mock_repo.fetch_dead_events.assert_called_once_with(
            limit=100,
            offset=0,
            aggregate_type=None,
            event_type=None,
        )


def test_list_dead_events_with_filters(http_server_with_repo, sample_dead_event):
    """Test GET /api/dead-events with filters."""
    server, mock_repo = http_server_with_repo
    mock_repo.fetch_dead_events.return_value = [sample_dead_event]
    
    with patch("dispatchbox.http_server.request") as mock_request:
        mock_request.query.get.side_effect = lambda key, default=None: {
            "limit": "50",
            "offset": "10",
            "aggregate_type": "order",
            "event_type": "order.created",
        }.get(key, default)
        
        result = server._list_dead_events()
        
        mock_repo.fetch_dead_events.assert_called_once_with(
            limit=50,
            offset=10,
            aggregate_type="order",
            event_type="order.created",
        )


def test_list_dead_events_limit_max(http_server_with_repo):
    """Test GET /api/dead-events limits max to 1000."""
    server, mock_repo = http_server_with_repo
    mock_repo.fetch_dead_events.return_value = []
    
    with patch("dispatchbox.http_server.request") as mock_request:
        mock_request.query.get.side_effect = lambda key, default=None: {
            "limit": "5000",  # Should be capped at 1000
        }.get(key, default)
        
        result = server._list_dead_events()
        
        mock_repo.fetch_dead_events.assert_called_once_with(
            limit=1000,  # Capped
            offset=0,
            aggregate_type=None,
            event_type=None,
        )


def test_list_dead_events_no_repository():
    """Test GET /api/dead-events returns 501 if no repository."""
    server = HttpServer(host="127.0.0.1", port=8080)
    
    result = server._list_dead_events()
    
    assert "error" in result
    assert "Repository not available" in result["error"]
    assert "501" in str(bottle_response.status)


def test_list_dead_events_invalid_params(http_server_with_repo):
    """Test GET /api/dead-events with invalid parameters."""
    server, mock_repo = http_server_with_repo
    mock_repo.fetch_dead_events.side_effect = ValueError("limit must be at least 1")
    
    with patch("dispatchbox.http_server.request") as mock_request:
        mock_request.query.get.side_effect = lambda key, default=None: {
            "limit": "0",
        }.get(key, default)
        
        result = server._list_dead_events()
        
        assert "error" in result
        assert "400" in str(bottle_response.status)


def test_dead_events_stats(http_server_with_repo):
    """Test GET /api/dead-events/stats returns statistics."""
    server, mock_repo = http_server_with_repo
    mock_repo.count_dead_events.return_value = 42
    
    with patch("dispatchbox.http_server.request") as mock_request:
        mock_request.query.get.side_effect = lambda key, default=None: default
        
        result = server._dead_events_stats()
        
        assert result["total"] == 42
        assert result["aggregate_type"] is None
        assert result["event_type"] is None
        mock_repo.count_dead_events.assert_called_once_with(
            aggregate_type=None,
            event_type=None,
        )


def test_dead_events_stats_with_filters(http_server_with_repo):
    """Test GET /api/dead-events/stats with filters."""
    server, mock_repo = http_server_with_repo
    mock_repo.count_dead_events.return_value = 5
    
    with patch("dispatchbox.http_server.request") as mock_request:
        mock_request.query.get.side_effect = lambda key, default=None: {
            "aggregate_type": "order",
            "event_type": "order.created",
        }.get(key, default)
        
        result = server._dead_events_stats()
        
        assert result["total"] == 5
        assert result["aggregate_type"] == "order"
        assert result["event_type"] == "order.created"


def test_get_dead_event(http_server_with_repo, sample_dead_event):
    """Test GET /api/dead-events/:id returns event."""
    server, mock_repo = http_server_with_repo
    mock_repo.get_dead_event.return_value = sample_dead_event
    
    result = server._get_dead_event(1)
    
    assert result["id"] == 1
    assert result["status"] == "dead"
    mock_repo.get_dead_event.assert_called_once_with(1)


def test_get_dead_event_not_found(http_server_with_repo):
    """Test GET /api/dead-events/:id returns 404 if not found."""
    server, mock_repo = http_server_with_repo
    mock_repo.get_dead_event.return_value = None
    
    result = server._get_dead_event(999)
    
    assert "error" in result
    assert "not found" in result["error"].lower()
    assert "404" in str(bottle_response.status)


def test_get_dead_event_invalid_id(http_server_with_repo):
    """Test GET /api/dead-events/:id with invalid ID."""
    server, mock_repo = http_server_with_repo
    mock_repo.get_dead_event.side_effect = ValueError("event_id must be a positive integer")
    
    result = server._get_dead_event(0)
    
    assert "error" in result
    assert "400" in str(bottle_response.status)


def test_retry_dead_event(http_server_with_repo):
    """Test POST /api/dead-events/:id/retry resets event."""
    server, mock_repo = http_server_with_repo
    mock_repo.retry_dead_event.return_value = True
    
    result = server._retry_dead_event(123)
    
    assert result["status"] == "success"
    assert result["event_id"] == 123
    assert "reset to pending" in result["message"]
    mock_repo.retry_dead_event.assert_called_once_with(123)


def test_retry_dead_event_not_found(http_server_with_repo):
    """Test POST /api/dead-events/:id/retry returns 404 if not found."""
    server, mock_repo = http_server_with_repo
    mock_repo.retry_dead_event.return_value = False
    
    result = server._retry_dead_event(999)
    
    assert "error" in result
    assert "not found" in result["error"].lower()
    assert "404" in str(bottle_response.status)


def test_retry_dead_event_invalid_id(http_server_with_repo):
    """Test POST /api/dead-events/:id/retry with invalid ID."""
    server, mock_repo = http_server_with_repo
    mock_repo.retry_dead_event.side_effect = ValueError("event_id must be a positive integer")
    
    result = server._retry_dead_event(0)
    
    assert "error" in result
    assert "400" in str(bottle_response.status)


def test_retry_dead_events_batch(http_server_with_repo):
    """Test POST /api/dead-events/retry-batch resets multiple events."""
    server, mock_repo = http_server_with_repo
    mock_repo.retry_dead_events_batch.return_value = 3
    
    with patch("dispatchbox.http_server.request") as mock_request:
        # Bottle's request.body is a file-like object or bytes
        import io
        mock_request.body = io.BytesIO(json.dumps({"event_ids": [1, 2, 3]}).encode())
        
        result = server._retry_dead_events_batch()
        
        assert result["status"] == "success"
        assert result["requested"] == 3
        assert result["processed"] == 3
        assert "reset to pending" in result["message"]
        mock_repo.retry_dead_events_batch.assert_called_once_with([1, 2, 3])


def test_retry_dead_events_batch_invalid_json(http_server_with_repo):
    """Test POST /api/dead-events/retry-batch with invalid JSON."""
    server, mock_repo = http_server_with_repo
    
    with patch("dispatchbox.http_server.request") as mock_request:
        import io
        mock_request.body = io.BytesIO(b"invalid json")
        
        result = server._retry_dead_events_batch()
        
        assert "error" in result
        assert "Invalid JSON" in result["error"]
        assert "400" in str(bottle_response.status)


def test_retry_dead_events_batch_empty_list(http_server_with_repo):
    """Test POST /api/dead-events/retry-batch with empty list."""
    server, mock_repo = http_server_with_repo
    
    with patch("dispatchbox.http_server.request") as mock_request:
        import io
        mock_request.body = io.BytesIO(json.dumps({"event_ids": []}).encode())
        
        result = server._retry_dead_events_batch()
        
        assert "error" in result
        assert "non-empty list" in result["error"]
        assert "400" in str(bottle_response.status)


def test_retry_dead_events_batch_no_repository():
    """Test POST /api/dead-events/retry-batch returns 501 if no repository."""
    server = HttpServer(host="127.0.0.1", port=8080)
    
    with patch("dispatchbox.http_server.request") as mock_request:
        import io
        mock_request.body = io.BytesIO(json.dumps({"event_ids": [1, 2, 3]}).encode())
        
        result = server._retry_dead_events_batch()
        
        assert "error" in result
        assert "Repository not available" in result["error"]
        assert "501" in str(bottle_response.status)

