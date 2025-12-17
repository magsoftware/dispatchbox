"""Integration tests for HTTP server endpoints."""

import pytest
import json
import time
import threading
import socket
import requests
from unittest.mock import Mock, MagicMock
from datetime import datetime, timezone

from dispatchbox.http_server import HttpServer
from dispatchbox.models import OutboxEvent
from dispatchbox.repository import OutboxRepository


def find_free_port():
    """Find a free port for testing."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


@pytest.fixture
def mock_repository():
    """Mock OutboxRepository."""
    mock_repo = MagicMock(spec=OutboxRepository)
    return mock_repo


@pytest.fixture
def sample_dead_event():
    """Sample dead event."""
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
def http_server(mock_repository):
    """Create and start HTTP server for integration tests."""
    def get_repo():
        return mock_repository
    
    def db_check():
        return True
    
    # Find a free port
    port = find_free_port()
    
    server = HttpServer(
        host="127.0.0.1",
        port=port,
        db_check_fn=db_check,
        repository_fn=get_repo,
    )
    
    server.start()
    # Wait for server to start - give it more time
    max_attempts = 10
    for _ in range(max_attempts):
        try:
            # Try to connect to verify server is up
            test_response = requests.get(f"http://127.0.0.1:{port}/health", timeout=0.5)
            if test_response.status_code == 200:
                break
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            time.sleep(0.1)
    else:
        pytest.fail("Server failed to start within timeout")
    
    yield server, mock_repository, f"http://127.0.0.1:{port}"
    
    server.stop()
    time.sleep(0.1)  # Give server time to stop


class TestHealthEndpoint:
    """Tests for /health endpoint."""
    
    def test_health_endpoint_returns_ok(self, http_server):
        """Test /health endpoint returns 200 OK."""
        server, mock_repo, base_url = http_server
        
        response = requests.get(f"{base_url}/health", timeout=1)
        
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
    
    def test_health_endpoint_content_type(self, http_server):
        """Test /health endpoint has correct Content-Type."""
        server, mock_repo, base_url = http_server
        
        response = requests.get(f"{base_url}/health", timeout=1)
        
        assert "application/json" in response.headers.get("Content-Type", "")


class TestReadyEndpoint:
    """Tests for /ready endpoint."""
    
    def test_ready_endpoint_returns_ready(self, http_server):
        """Test /ready endpoint returns ready when DB is connected."""
        server, mock_repo, base_url = http_server
        
        response = requests.get(f"{base_url}/ready", timeout=1)
        
        assert response.status_code == 200
        assert response.json() == {"status": "ready"}
    
    def test_ready_endpoint_db_not_connected(self, mock_repository):
        """Test /ready endpoint returns 503 when DB is not connected."""
        def db_check():
            return False
        
        port = find_free_port()
        server = HttpServer(
            host="127.0.0.1",
            port=port,
            db_check_fn=db_check,
        )
        server.start()
        time.sleep(0.3)  # Wait for server to start
        
        try:
            base_url = f"http://127.0.0.1:{port}"
            response = requests.get(f"{base_url}/ready", timeout=1)
            
            assert response.status_code == 503
            assert response.json()["status"] == "not ready"
            assert "reason" in response.json()
        finally:
            server.stop()
    
    def test_ready_endpoint_db_check_exception(self, mock_repository):
        """Test /ready endpoint handles DB check exceptions."""
        def db_check():
            raise Exception("Connection failed")
        
        port = find_free_port()
        server = HttpServer(
            host="127.0.0.1",
            port=port,
            db_check_fn=db_check,
        )
        server.start()
        time.sleep(0.3)  # Wait for server to start
        
        try:
            base_url = f"http://127.0.0.1:{port}"
            response = requests.get(f"{base_url}/ready", timeout=1)
            
            assert response.status_code == 503
            assert response.json()["status"] == "not ready"
            assert "reason" in response.json()
        finally:
            server.stop()


class TestMetricsEndpoint:
    """Tests for /metrics endpoint."""
    
    def test_metrics_endpoint_with_function(self, mock_repository):
        """Test /metrics endpoint returns metrics when function is provided."""
        def metrics_fn():
            return "# HELP test_metric\n# TYPE test_metric counter\ntest_metric 1\n"
        
        port = find_free_port()
        server = HttpServer(
            host="127.0.0.1",
            port=port,
            metrics_fn=metrics_fn,
        )
        server.start()
        time.sleep(0.3)  # Wait for server to start
        
        try:
            base_url = f"http://127.0.0.1:{port}"
            response = requests.get(f"{base_url}/metrics", timeout=1)
            
            assert response.status_code == 200
            assert "# HELP test_metric" in response.text
            assert response.headers.get("Content-Type") == "text/plain; version=0.0.4; charset=utf-8"
        finally:
            server.stop()
    
    def test_metrics_endpoint_no_function(self, mock_repository):
        """Test /metrics endpoint returns 404 when no function is provided (endpoint not registered)."""
        port = find_free_port()
        server = HttpServer(
            host="127.0.0.1",
            port=port,
        )
        server.start()
        time.sleep(0.3)  # Wait for server to start
        
        try:
            base_url = f"http://127.0.0.1:{port}"
            response = requests.get(f"{base_url}/metrics", timeout=1)
            
            # When metrics_fn is not provided, endpoint is not registered, so 404
            assert response.status_code == 404
        finally:
            server.stop()


class TestDeadEventsListEndpoint:
    """Tests for GET /api/dead-events endpoint."""
    
    def test_list_dead_events_success(self, http_server, sample_dead_event):
        """Test listing dead events returns correct data."""
        server, mock_repo, base_url = http_server
        mock_repo.fetch_dead_events.return_value = [sample_dead_event]
        
        response = requests.get(f"{base_url}/api/dead-events", timeout=1)
        
        assert response.status_code == 200
        data = response.json()
        assert "events" in data
        assert len(data["events"]) == 1
        assert data["events"][0]["id"] == 1
        assert data["events"][0]["status"] == "dead"
        assert "next_run_at" in data["events"][0]
        assert isinstance(data["events"][0]["next_run_at"], str)  # ISO 8601 string
        assert data["count"] == 1
    
    def test_list_dead_events_with_pagination(self, http_server, sample_dead_event):
        """Test listing dead events with limit and offset."""
        server, mock_repo, base_url = http_server
        mock_repo.fetch_dead_events.return_value = [sample_dead_event]
        
        response = requests.get(
            f"{base_url}/api/dead-events?limit=50&offset=10",
            timeout=1
        )
        
        assert response.status_code == 200
        mock_repo.fetch_dead_events.assert_called_once_with(
            limit=50,
            offset=10,
            aggregate_type=None,
            event_type=None,
        )
    
    def test_list_dead_events_with_filters(self, http_server, sample_dead_event):
        """Test listing dead events with aggregate_type and event_type filters."""
        server, mock_repo, base_url = http_server
        mock_repo.fetch_dead_events.return_value = [sample_dead_event]
        
        response = requests.get(
            f"{base_url}/api/dead-events?aggregate_type=order&event_type=order.created",
            timeout=1
        )
        
        assert response.status_code == 200
        mock_repo.fetch_dead_events.assert_called_once_with(
            limit=100,
            offset=0,
            aggregate_type="order",
            event_type="order.created",
        )
    
    def test_list_dead_events_limit_max(self, http_server):
        """Test listing dead events limits max to 1000."""
        server, mock_repo, base_url = http_server
        mock_repo.fetch_dead_events.return_value = []
        
        response = requests.get(
            f"{base_url}/api/dead-events?limit=5000",
            timeout=1
        )
        
        assert response.status_code == 200
        mock_repo.fetch_dead_events.assert_called_once_with(
            limit=1000,  # Capped at 1000
            offset=0,
            aggregate_type=None,
            event_type=None,
        )
    
    def test_list_dead_events_no_repository(self, mock_repository):
        """Test listing dead events returns 404 when no repository (endpoint not registered)."""
        port = find_free_port()
        server = HttpServer(
            host="127.0.0.1",
            port=port,
        )
        server.start()
        time.sleep(0.3)  # Wait for server to start
        
        try:
            base_url = f"http://127.0.0.1:{port}"
            response = requests.get(f"{base_url}/api/dead-events", timeout=1)
            
            # When repository_fn is not provided, DLQ endpoints are not registered, so 404
            assert response.status_code == 404
        finally:
            server.stop()
    
    def test_list_dead_events_invalid_limit(self, http_server):
        """Test listing dead events with invalid limit parameter."""
        server, mock_repo, base_url = http_server
        mock_repo.fetch_dead_events.side_effect = ValueError("limit must be at least 1")
        
        response = requests.get(
            f"{base_url}/api/dead-events?limit=0",
            timeout=1
        )
        
        assert response.status_code == 400
        assert "error" in response.json()
    
    def test_list_dead_events_invalid_offset(self, http_server):
        """Test listing dead events with invalid offset parameter."""
        server, mock_repo, base_url = http_server
        mock_repo.fetch_dead_events.side_effect = ValueError("offset must be non-negative")
        
        response = requests.get(
            f"{base_url}/api/dead-events?offset=-1",
            timeout=1
        )
        
        assert response.status_code == 400
        assert "error" in response.json()


class TestDeadEventsStatsEndpoint:
    """Tests for GET /api/dead-events/stats endpoint."""
    
    def test_dead_events_stats_success(self, http_server):
        """Test getting dead events statistics."""
        server, mock_repo, base_url = http_server
        mock_repo.count_dead_events.return_value = 42
        
        response = requests.get(f"{base_url}/api/dead-events/stats", timeout=1)
        
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 42
        assert data["aggregate_type"] is None
        assert data["event_type"] is None
    
    def test_dead_events_stats_with_filters(self, http_server):
        """Test getting dead events statistics with filters."""
        server, mock_repo, base_url = http_server
        mock_repo.count_dead_events.return_value = 5
        
        response = requests.get(
            f"{base_url}/api/dead-events/stats?aggregate_type=order&event_type=order.created",
            timeout=1
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 5
        assert data["aggregate_type"] == "order"
        assert data["event_type"] == "order.created"


class TestGetDeadEventEndpoint:
    """Tests for GET /api/dead-events/:id endpoint."""
    
    def test_get_dead_event_success(self, http_server, sample_dead_event):
        """Test getting a single dead event."""
        server, mock_repo, base_url = http_server
        mock_repo.get_dead_event.return_value = sample_dead_event
        
        response = requests.get(f"{base_url}/api/dead-events/1", timeout=1)
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1
        assert data["status"] == "dead"
        assert "next_run_at" in data
        assert isinstance(data["next_run_at"], str)  # ISO 8601 string
    
    def test_get_dead_event_not_found(self, http_server):
        """Test getting non-existent dead event returns 404."""
        server, mock_repo, base_url = http_server
        mock_repo.get_dead_event.return_value = None
        
        response = requests.get(f"{base_url}/api/dead-events/999", timeout=1)
        
        assert response.status_code == 404
        assert "error" in response.json()
        assert "not found" in response.json()["error"].lower()
    
    def test_get_dead_event_invalid_id(self, http_server):
        """Test getting dead event with invalid ID returns 400."""
        server, mock_repo, base_url = http_server
        mock_repo.get_dead_event.side_effect = ValueError("event_id must be a positive integer")
        
        response = requests.get(f"{base_url}/api/dead-events/0", timeout=1)
        
        assert response.status_code == 400
        assert "error" in response.json()


class TestRetryDeadEventEndpoint:
    """Tests for POST /api/dead-events/:id/retry endpoint."""
    
    def test_retry_dead_event_success(self, http_server):
        """Test retrying a single dead event."""
        server, mock_repo, base_url = http_server
        mock_repo.retry_dead_event.return_value = True
        
        response = requests.post(f"{base_url}/api/dead-events/123/retry", timeout=1)
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["event_id"] == 123
        assert "reset to pending" in data["message"]
        mock_repo.retry_dead_event.assert_called_once_with(123)
    
    def test_retry_dead_event_not_found(self, http_server):
        """Test retrying non-existent dead event returns 404."""
        server, mock_repo, base_url = http_server
        mock_repo.retry_dead_event.return_value = False
        
        response = requests.post(f"{base_url}/api/dead-events/999/retry", timeout=1)
        
        assert response.status_code == 404
        assert "error" in response.json()
        assert "not found" in response.json()["error"].lower()
    
    def test_retry_dead_event_invalid_id(self, http_server):
        """Test retrying dead event with invalid ID returns 400."""
        server, mock_repo, base_url = http_server
        mock_repo.retry_dead_event.side_effect = ValueError("event_id must be a positive integer")
        
        response = requests.post(f"{base_url}/api/dead-events/0/retry", timeout=1)
        
        assert response.status_code == 400
        assert "error" in response.json()


class TestRetryDeadEventsBatchEndpoint:
    """Tests for POST /api/dead-events/retry-batch endpoint."""
    
    def test_retry_dead_events_batch_success(self, http_server):
        """Test retrying multiple dead events."""
        server, mock_repo, base_url = http_server
        mock_repo.retry_dead_events_batch.return_value = 3
        
        payload = {"event_ids": [1, 2, 3]}
        response = requests.post(
            f"{base_url}/api/dead-events/retry-batch",
            json=payload,
            timeout=1
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["requested"] == 3
        assert data["processed"] == 3
        assert "reset to pending" in data["message"]
        mock_repo.retry_dead_events_batch.assert_called_once_with([1, 2, 3])
    
    def test_retry_dead_events_batch_empty_list(self, http_server):
        """Test retrying with empty list returns 400."""
        server, mock_repo, base_url = http_server
        
        payload = {"event_ids": []}
        response = requests.post(
            f"{base_url}/api/dead-events/retry-batch",
            json=payload,
            timeout=1
        )
        
        assert response.status_code == 400
        assert "error" in response.json()
        assert "non-empty list" in response.json()["error"]
    
    def test_retry_dead_events_batch_invalid_json(self, http_server):
        """Test retrying with invalid JSON returns 400."""
        server, mock_repo, base_url = http_server
        
        response = requests.post(
            f"{base_url}/api/dead-events/retry-batch",
            data="invalid json",
            headers={"Content-Type": "application/json"},
            timeout=1
        )
        
        assert response.status_code == 400
        assert "error" in response.json()
        assert "Invalid JSON" in response.json()["error"]
    
    def test_retry_dead_events_batch_missing_event_ids(self, http_server):
        """Test retrying with missing event_ids field returns 400."""
        server, mock_repo, base_url = http_server
        
        payload = {}  # Missing event_ids
        response = requests.post(
            f"{base_url}/api/dead-events/retry-batch",
            json=payload,
            timeout=1
        )
        
        assert response.status_code == 400
        assert "error" in response.json()
    
    def test_retry_dead_events_batch_no_repository(self, mock_repository):
        """Test retrying batch returns 404 when no repository (endpoint not registered)."""
        port = find_free_port()
        server = HttpServer(
            host="127.0.0.1",
            port=port,
        )
        server.start()
        time.sleep(0.3)  # Wait for server to start
        
        try:
            base_url = f"http://127.0.0.1:{port}"
            payload = {"event_ids": [1, 2, 3]}
            response = requests.post(
                f"{base_url}/api/dead-events/retry-batch",
                json=payload,
                timeout=1
            )
            
            # When repository_fn is not provided, DLQ endpoints are not registered, so 404
            assert response.status_code == 404
        finally:
            server.stop()


class TestErrorHandling:
    """Tests for error handling in HTTP endpoints."""
    
    def test_internal_server_error(self, http_server):
        """Test handling of internal server errors."""
        server, mock_repo, base_url = http_server
        mock_repo.fetch_dead_events.side_effect = Exception("Database error")
        
        response = requests.get(f"{base_url}/api/dead-events", timeout=1)
        
        assert response.status_code == 500
        assert "error" in response.json()
        assert "Internal server error" in response.json()["error"]
    
    def test_not_found_endpoint(self, http_server):
        """Test accessing non-existent endpoint returns 404."""
        server, mock_repo, base_url = http_server
        
        response = requests.get(f"{base_url}/api/nonexistent", timeout=1)
        
        assert response.status_code == 404
    
    def test_method_not_allowed(self, http_server):
        """Test using wrong HTTP method returns 405."""
        server, mock_repo, base_url = http_server
        
        # POST to GET-only endpoint
        response = requests.post(f"{base_url}/api/dead-events/stats", timeout=1)
        
        assert response.status_code == 405

