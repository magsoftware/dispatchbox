"""Tests for HTTP server module."""

import json
import threading
import time
from unittest.mock import MagicMock, Mock, patch

from bottle import response as bottle_response
import pytest

from dispatchbox.http_server import HttpServer


def test_health_endpoint():
    """Test /health endpoint returns ok."""
    server = HttpServer(port=0)  # Use random port

    # Mock bottle's run to avoid actually starting server
    with patch("dispatchbox.http_server.run"):
        server.start()
        time.sleep(0.1)  # Give thread time to start

        # Simulate request
        result = server._health()
        assert result == {"status": "ok"}


def test_ready_endpoint_with_db_check():
    """Test /ready endpoint with DB check function."""
    mock_db_check = Mock(return_value=True)
    server = HttpServer(port=0, db_check_fn=mock_db_check)

    result = server._ready()
    assert result == {"status": "ready"}
    mock_db_check.assert_called_once()


def test_ready_endpoint_db_not_connected():
    """Test /ready endpoint when DB is not connected."""
    mock_db_check = Mock(return_value=False)
    server = HttpServer(port=0, db_check_fn=mock_db_check)

    # Call endpoint - it should set status to 503
    result = server._ready()
    assert result["status"] == "not ready"
    assert "reason" in result
    assert "503" in str(bottle_response.status)


def test_ready_endpoint_db_check_exception():
    """Test /ready endpoint when DB check raises exception."""
    import psycopg2

    mock_db_check = Mock(side_effect=psycopg2.OperationalError("Connection failed"))
    server = HttpServer(port=0, db_check_fn=mock_db_check)

    # Call endpoint - it should set status to 503
    result = server._ready()
    assert result["status"] == "not ready"
    assert "reason" in result
    assert "503" in str(bottle_response.status)


def test_ready_endpoint_no_db_check():
    """Test /ready endpoint without DB check function."""
    server = HttpServer(port=0, db_check_fn=None)

    result = server._ready()
    assert result == {"status": "ready"}


def test_metrics_endpoint_with_function():
    """Test /metrics endpoint with metrics function."""
    mock_metrics = Mock(return_value="# HELP test_metric\n# TYPE test_metric counter\ntest_metric 1\n")
    server = HttpServer(port=0, metrics_fn=mock_metrics)

    # Reset response for test
    bottle_response.content_type = None
    result = server._metrics()
    assert "# HELP test_metric" in result
    assert bottle_response.content_type == "text/plain; version=0.0.4; charset=utf-8"
    mock_metrics.assert_called_once()


def test_metrics_endpoint_no_function():
    """Test /metrics endpoint without metrics function."""
    server = HttpServer(port=0, metrics_fn=None)

    # Call endpoint - it should set status to 501
    result = server._metrics()
    assert "# Metrics not available" in result
    assert "501" in str(bottle_response.status)


def test_metrics_endpoint_exception():
    """Test /metrics endpoint when metrics function raises exception."""
    mock_metrics = Mock(side_effect=Exception("Metrics error"))
    server = HttpServer(port=0, metrics_fn=mock_metrics)

    # Call endpoint - it should set status to 500
    result = server._metrics()
    assert "Error generating metrics" in result
    assert "500" in str(bottle_response.status)


def test_server_start_stop():
    """Test server start and stop."""
    server = HttpServer(port=0)

    with patch("dispatchbox.http_server.run") as mock_run:
        # Make run block to keep thread alive
        mock_run.side_effect = lambda *args, **kwargs: time.sleep(0.2)

        server.start()
        time.sleep(0.05)  # Give thread time to start

        assert server.is_running()
        assert mock_run.called

    server.stop()
    # Thread will die when run completes or process exits


def test_server_start_twice():
    """Test starting server twice doesn't create duplicate threads."""
    server = HttpServer(port=0)

    with patch("dispatchbox.http_server.run") as mock_run:
        # Make run block to keep thread alive
        mock_run.side_effect = lambda *args, **kwargs: time.sleep(0.2)

        server.start()
        time.sleep(0.05)
        first_thread = server._server_thread

        server.start()  # Should not create new thread (logs warning)
        time.sleep(0.05)

        # Should still be the same thread
        assert server._server_thread is first_thread


def test_server_is_running():
    """Test is_running method."""
    server = HttpServer(port=0)

    assert not server.is_running()

    with patch("dispatchbox.http_server.run") as mock_run:
        # Make run block to keep thread alive
        mock_run.side_effect = lambda *args, **kwargs: time.sleep(0.2)

        server.start()
        time.sleep(0.05)  # Give thread time to start
        assert server.is_running()


def test_error_500_handler():
    """Test 500 error handler returns JSON response."""
    server = HttpServer(port=0)

    # Verify error handler is registered
    assert 500 in server.app.error_handler
    error_handler = server.app.error_handler[500]

    # Reset response state
    bottle_response.content_type = None
    bottle_response.status = "200 OK"

    # Call the error handler directly to test it
    mock_error = Mock()
    result = error_handler(mock_error)

    # Verify response
    assert bottle_response.content_type == "application/json"
    # Bottle response.status can be string or int, check both
    assert bottle_response.status == 500 or str(bottle_response.status) == "500" or "500" in str(bottle_response.status)
    data = json.loads(result)
    assert data["error"] == "Internal Server Error"
    assert "message" in data


def test_server_start_handles_oserror():
    """Test server start handles OSError (e.g., port already in use)."""
    server = HttpServer(port=0)

    with patch("dispatchbox.http_server.run", side_effect=OSError("Address already in use")):
        with patch("dispatchbox.http_server.logger") as mock_logger:
            server.start()
            time.sleep(0.1)  # Give thread time to start and fail

            # Should log error
            mock_logger.error.assert_called()
            assert "HTTP server error" in mock_logger.error.call_args[0][0]


def test_server_start_handles_valueerror():
    """Test server start handles ValueError (e.g., invalid port)."""
    server = HttpServer(port=0)

    with patch("dispatchbox.http_server.run", side_effect=ValueError("Invalid port")):
        with patch("dispatchbox.http_server.logger") as mock_logger:
            server.start()
            time.sleep(0.1)  # Give thread time to start and fail

            # Should log error
            mock_logger.error.assert_called()
            assert "HTTP server error" in mock_logger.error.call_args[0][0]
