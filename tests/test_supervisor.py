"""Tests for supervisor module."""

import pytest
from unittest.mock import Mock, MagicMock, patch
from multiprocessing import Process, Event

from dispatchbox.supervisor import worker_loop, start_processes


def test_worker_loop_initializes_repository_and_worker(mocker):
    """Test worker_loop initializes repository and worker correctly."""
    mock_repository = MagicMock()
    mock_worker = MagicMock()
    
    with patch("dispatchbox.supervisor.OutboxRepository", return_value=mock_repository):
        with patch("dispatchbox.supervisor.OutboxWorker", return_value=mock_worker):
            stop_event = Event()
            stop_event.set()  # Stop immediately
            
            # Mock run_loop to return immediately
            mock_worker.run_loop = Mock()
            
            worker_loop(
                dsn="host=localhost dbname=test",
                stop_event=stop_event,
                batch_size=10,
                poll_interval=1.0,
                worker_name="worker-0",
                max_parallel=5,
                retry_backoff_seconds=30,
            )
            
            # Check that repository and worker were created
            mock_repository.__enter__.assert_called()
            mock_worker.run_loop.assert_called()


def test_worker_loop_uses_context_manager(mocker):
    """Test worker_loop uses repository as context manager."""
    mock_repository = MagicMock()
    mock_worker = MagicMock()
    
    with patch("dispatchbox.supervisor.OutboxRepository", return_value=mock_repository):
        with patch("dispatchbox.supervisor.OutboxWorker", return_value=mock_worker):
            stop_event = Event()
            stop_event.set()
            
            mock_worker.run_loop = Mock()
            
            worker_loop(
                dsn="host=localhost dbname=test",
                stop_event=stop_event,
                batch_size=10,
                poll_interval=1.0,
                worker_name="worker-0",
            )
            
            # Repository should be used as context manager
            mock_repository.__enter__.assert_called()
            mock_repository.__exit__.assert_called()


def test_start_processes_creates_processes(mocker):
    """Test start_processes creates specified number of processes."""
    mock_process = MagicMock(spec=Process)
    mock_process.is_alive.return_value = False  # Process exits immediately
    mock_process.pid = 12345
    
    with patch("dispatchbox.supervisor.Process", return_value=mock_process):
        with patch("dispatchbox.supervisor.signal.signal"):  # Mock signal handlers
            with patch("dispatchbox.supervisor.time.sleep"):  # Mock sleep in wait loop
                # Use threading.Event instead of multiprocessing.Event for testing
                import threading
                stop_event = threading.Event()
                stop_event.set()  # Stop immediately
                
                # Mock the wait loop to exit quickly
                with patch("dispatchbox.supervisor.any", return_value=False):
                    start_processes(
                        dsn="host=localhost dbname=test",
                        num_processes=3,
                        batch_size=10,
                        poll_interval=1.0,
                    )
                
                # Check that Process was called 3 times
                assert mock_process.start.call_count == 3


def test_start_processes_sets_signal_handlers(mocker):
    """Test start_processes sets up signal handlers."""
    mock_process = MagicMock(spec=Process)
    mock_process.is_alive.return_value = False
    
    mock_signal = mocker.patch("dispatchbox.supervisor.signal.signal")
    
    with patch("dispatchbox.supervisor.Process", return_value=mock_process):
        with patch("dispatchbox.supervisor.time.sleep"):
            with patch("dispatchbox.supervisor.any", return_value=False):
                start_processes(
                    dsn="host=localhost dbname=test",
                    num_processes=1,
                    batch_size=10,
                    poll_interval=1.0,
                )
                
                # Should set signal handlers for SIGINT and SIGTERM
                assert mock_signal.call_count >= 2


def test_start_processes_with_custom_parameters(mocker):
    """Test start_processes passes parameters correctly."""
    mock_process = MagicMock(spec=Process)
    mock_process.is_alive.return_value = False
    
    with patch("dispatchbox.supervisor.Process", return_value=mock_process) as mock_process_class:
        with patch("dispatchbox.supervisor.signal.signal"):
            with patch("dispatchbox.supervisor.time.sleep"):
                with patch("dispatchbox.supervisor.any", return_value=False):
                    start_processes(
                        dsn="host=localhost dbname=test",
                        num_processes=2,
                        batch_size=20,
                        poll_interval=2.0,
                        max_parallel=15,
                        retry_backoff_seconds=60,
                    )
                    
                    # Check that Process was created with correct target
                    calls = mock_process_class.call_args_list
                    assert len(calls) == 2
                    # Check that worker_loop is the target
                    for call in calls:
                        assert call[1]["target"] == worker_loop

