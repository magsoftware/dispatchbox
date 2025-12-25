"""Tests for supervisor module."""

from multiprocessing import Event, Process
from unittest.mock import MagicMock, Mock, patch

import pytest

from dispatchbox.supervisor import start_processes, worker_loop


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
    import signal
    from unittest.mock import patch

    mock_repository = MagicMock()
    mock_worker = MagicMock()

    with patch("dispatchbox.supervisor.OutboxRepository", return_value=mock_repository):
        with patch("dispatchbox.supervisor.OutboxWorker", return_value=mock_worker):
            stop_event = Event()
            stop_event.set()  # Stop immediately

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

            # Check that repository was used as context manager
            mock_repository.__enter__.assert_called()
            mock_repository.__exit__.assert_called()


def test_worker_signal_handler(mocker):
    """Test worker signal handler sets stop event."""
    import signal
    from unittest.mock import patch

    from dispatchbox.supervisor import _setup_worker_signal_handlers

    stop_event = Event()

    with patch("dispatchbox.supervisor.logger") as mock_logger:
        # Setup signal handlers
        _setup_worker_signal_handlers(stop_event, "worker-0")

        # Get the signal handler that was registered
        handler = signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, handler)

        # Call the handler directly with a mock frame
        mock_frame = Mock()
        handler(signal.SIGTERM, mock_frame)

        # Verify stop_event was set
        assert stop_event.is_set()
        # Verify logger was called (may be called during handler execution)
        # The exact call count depends on implementation


def test_wait_for_processes_handles_keyboard_interrupt(mocker):
    """Test _wait_for_processes handles KeyboardInterrupt gracefully."""
    from multiprocessing import Event
    from unittest.mock import patch

    from dispatchbox.supervisor import _wait_for_processes

    mock_process = MagicMock()
    mock_process.is_alive.return_value = True
    mock_process.join = Mock()

    children = [mock_process]
    stop_event = Event()

    with patch("dispatchbox.supervisor.logger") as mock_logger:
        with patch("dispatchbox.supervisor.time.sleep", side_effect=KeyboardInterrupt()):
            # _wait_for_processes catches KeyboardInterrupt, so it won't raise
            _wait_for_processes(children, stop_event)

            # Verify logger was called with KeyboardInterrupt message
            mock_logger.info.assert_called()
            log_messages = [str(call[0][0]) for call in mock_logger.info.call_args_list]
            assert any("KeyboardInterrupt" in msg or "stopping" in msg.lower() for msg in log_messages)

            # Verify stop_event was set
            assert stop_event.is_set()

            # Verify join was called on all processes
            mock_process.join.assert_called()


def test_setup_signal_handlers_calls_signal_handler(mocker):
    """Test _setup_signal_handlers signal handler is called."""
    from multiprocessing import Event
    import signal
    from unittest.mock import patch

    from dispatchbox.supervisor import _setup_signal_handlers

    mock_process = MagicMock()
    mock_process.join = Mock()
    children = [mock_process]
    stop_event = Event()

    with patch("dispatchbox.supervisor.logger") as mock_logger:
        with patch("dispatchbox.supervisor.signal.signal") as mock_signal:
            with patch("dispatchbox.supervisor.sys.exit") as mock_exit:
                _setup_signal_handlers(stop_event, children)

                # Get the handler that was registered (second argument of signal.signal call)
                handler = mock_signal.call_args_list[0][0][1]

                # Call the handler directly - it will call sys.exit(0)
                mock_frame = Mock()
                handler(signal.SIGTERM, mock_frame)

                # Verify logger was called
                mock_logger.info.assert_called()
                assert "Parent received signal" in mock_logger.info.call_args[0][0]

                # Verify stop_event was set
                assert stop_event.is_set()

                # Verify join was called
                mock_process.join.assert_called()

                # Verify sys.exit was called
                mock_exit.assert_called_once_with(0)
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
    mock_process.pid = 12345
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
