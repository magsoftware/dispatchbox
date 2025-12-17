"""Tests for HTTP server module."""

import pytest
import json
import threading
import time
from unittest.mock import Mock, patch, MagicMock
from dispatchbox.http_server import HealthServer


def test_health_endpoint():
    """Test /health endpoint returns ok."""
    server = HealthServer(port=0)  # Use random port
    
    # Mock bottle's run to avoid actually starting server
    with patch('dispatchbox.http_server.run'):
        server.start()
        time.sleep(0.1)  # Give thread time to start
        
        # Simulate request
        result = server._health()
        assert result == {"status": "ok"}


def test_ready_endpoint_with_db_check():
    """Test /ready endpoint with DB check function."""
    mock_db_check = Mock(return_value=True)
    server = HealthServer(port=0, db_check_fn=mock_db_check)
    
    result = server._ready()
    assert result == {"status": "ready"}
    mock_db_check.assert_called_once()


def test_ready_endpoint_db_not_connected():
    """Test /ready endpoint when DB is not connected."""
    from bottle import response as bottle_response
    
    mock_db_check = Mock(return_value=False)
    server = HealthServer(port=0, db_check_fn=mock_db_check)
    
    # Call endpoint - it should set status to 503
    result = server._ready()
    assert result["status"] == "not ready"
    assert "reason" in result
    assert "503" in str(bottle_response.status)


def test_ready_endpoint_db_check_exception():
    """Test /ready endpoint when DB check raises exception."""
    from bottle import response as bottle_response
    
    mock_db_check = Mock(side_effect=Exception("Connection failed"))
    server = HealthServer(port=0, db_check_fn=mock_db_check)
    
    # Call endpoint - it should set status to 503
    result = server._ready()
    assert result["status"] == "not ready"
    assert "reason" in result
    assert "503" in str(bottle_response.status)


def test_ready_endpoint_no_db_check():
    """Test /ready endpoint without DB check function."""
    server = HealthServer(port=0, db_check_fn=None)
    
    result = server._ready()
    assert result == {"status": "ready"}


def test_metrics_endpoint_with_function():
    """Test /metrics endpoint with metrics function."""
    from bottle import response as bottle_response
    
    mock_metrics = Mock(return_value="# HELP test_metric\n# TYPE test_metric counter\ntest_metric 1\n")
    server = HealthServer(port=0, metrics_fn=mock_metrics)
    
    # Reset response for test
    bottle_response.content_type = None
    result = server._metrics()
    assert "# HELP test_metric" in result
    assert bottle_response.content_type == "text/plain; version=0.0.4; charset=utf-8"
    mock_metrics.assert_called_once()


def test_metrics_endpoint_no_function():
    """Test /metrics endpoint without metrics function."""
    from bottle import response as bottle_response
    
    server = HealthServer(port=0, metrics_fn=None)
    
    # Call endpoint - it should set status to 501
    result = server._metrics()
    assert "# Metrics not available" in result
    assert "501" in str(bottle_response.status)


def test_metrics_endpoint_exception():
    """Test /metrics endpoint when metrics function raises exception."""
    from bottle import response as bottle_response
    
    mock_metrics = Mock(side_effect=Exception("Metrics error"))
    server = HealthServer(port=0, metrics_fn=mock_metrics)
    
    # Call endpoint - it should set status to 500
    result = server._metrics()
    assert "Error generating metrics" in result
    assert "500" in str(bottle_response.status)


def test_server_start_stop():
    """Test server start and stop."""
    server = HealthServer(port=0)
    
    with patch('dispatchbox.http_server.run') as mock_run:
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
    server = HealthServer(port=0)
    
    with patch('dispatchbox.http_server.run') as mock_run:
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
    server = HealthServer(port=0)
    
    assert not server.is_running()
    
    with patch('dispatchbox.http_server.run') as mock_run:
        # Make run block to keep thread alive
        mock_run.side_effect = lambda *args, **kwargs: time.sleep(0.2)
        
        server.start()
        time.sleep(0.05)  # Give thread time to start
        assert server.is_running()

