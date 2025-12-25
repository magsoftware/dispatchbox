"""Tests for OutboxWorker."""

from concurrent.futures import Future, ThreadPoolExecutor
from multiprocessing import Event
from unittest.mock import MagicMock, Mock, patch

import pytest

from dispatchbox.models import OutboxEvent
from dispatchbox.repository import OutboxRepository
from dispatchbox.worker import HandlerNotFoundError, OutboxWorker


def test_worker_init_with_repository(mock_repository):
    """Test OutboxWorker initialization with repository."""
    worker = OutboxWorker(
        batch_size=10,
        poll_interval=1.0,
        max_parallel=5,
        repository=mock_repository,
    )

    assert worker.batch_size == 10
    assert worker.poll_interval == 1.0
    assert worker.repository == mock_repository
    assert isinstance(worker.executor, ThreadPoolExecutor)


def test_worker_init_without_repository():
    """Test OutboxWorker raises ValueError when repository is None."""
    with pytest.raises(ValueError, match="repository is required"):
        OutboxWorker(
            batch_size=10,
            poll_interval=1.0,
            repository=None,
        )


def test_worker_init_with_custom_handlers(mock_repository):
    """Test OutboxWorker initialization with custom handlers."""
    custom_handlers = {"custom.event": Mock()}

    worker = OutboxWorker(
        batch_size=10,
        poll_interval=1.0,
        handlers=custom_handlers,
        repository=mock_repository,
    )

    assert worker.handlers == custom_handlers


def test_worker_init_with_default_handlers(mock_repository):
    """Test OutboxWorker uses default HANDLERS when not provided."""
    from dispatchbox.handlers import HANDLERS

    worker = OutboxWorker(
        batch_size=10,
        poll_interval=1.0,
        repository=mock_repository,
    )

    assert worker.handlers == HANDLERS


def test_process_event_success(mock_repository, sample_event):
    """Test process_event successfully calls handler."""
    mock_handler = Mock()
    handlers = {sample_event.event_type: mock_handler}

    worker = OutboxWorker(
        batch_size=10,
        poll_interval=1.0,
        handlers=handlers,
        repository=mock_repository,
    )

    worker.process_event(sample_event)

    mock_handler.assert_called_once_with(sample_event.payload)


def test_process_event_handler_not_found(mock_repository):
    """Test process_event raises HandlerNotFoundError when handler is missing."""
    # Create event with event_type that doesn't exist in handlers
    event = OutboxEvent(
        id=1,
        aggregate_type="order",
        aggregate_id="123",
        event_type="unknown.event",
        payload={},
        status="pending",
        attempts=0,
        next_run_at=Mock(),
    )

    worker = OutboxWorker(
        batch_size=10,
        poll_interval=1.0,
        handlers={},  # Empty handlers
        repository=mock_repository,
    )

    with pytest.raises(HandlerNotFoundError, match="No handler for event_type"):
        worker.process_event(event)


def test_run_loop_fetches_and_processes_events(mock_repository, sample_event):
    """Test run_loop fetches events and processes them."""
    # Setup repository to return events, then empty list to stop loop
    mock_repository.fetch_pending.side_effect = [[sample_event], []]

    # Mock handler
    mock_handler = Mock()
    handlers = {sample_event.event_type: mock_handler}

    # Mock executor to execute immediately
    mock_future = Future()
    mock_future.set_result(None)

    stop_event = Event()

    worker = OutboxWorker(
        batch_size=10,
        poll_interval=1.0,
        handlers=handlers,
        repository=mock_repository,
        stop_event=stop_event,
    )
    worker.executor.submit = Mock(return_value=mock_future)

    # Set stop_event after first iteration
    def stop_after_first(*args, **kwargs):
        stop_event.set()

    with patch("dispatchbox.worker.time.sleep", side_effect=stop_after_first):
        worker.run_loop()

    mock_repository.fetch_pending.assert_called()
    mock_repository.mark_success.assert_called_once_with(sample_event.id)


def test_run_loop_mark_success_on_success(mock_repository, sample_event):
    """Test run_loop marks event as success when handler succeeds."""
    # Return event first, then empty to stop
    mock_repository.fetch_pending.side_effect = [[sample_event], []]

    mock_handler = Mock()
    handlers = {sample_event.event_type: mock_handler}

    stop_event = Event()

    worker = OutboxWorker(
        batch_size=10,
        poll_interval=1.0,
        handlers=handlers,
        repository=mock_repository,
        stop_event=stop_event,
    )

    # Mock executor to return successful future
    mock_future = Future()
    mock_future.set_result(None)
    worker.executor.submit = Mock(return_value=mock_future)

    def stop_after_first(*args, **kwargs):
        stop_event.set()

    with patch("dispatchbox.worker.time.sleep", side_effect=stop_after_first):
        worker.run_loop()

    mock_repository.mark_success.assert_called_once_with(sample_event.id)
    mock_repository.mark_retry.assert_not_called()


def test_run_loop_mark_retry_on_error(mock_repository, sample_event):
    """Test run_loop marks event for retry when handler fails."""
    # Return event first, then empty to stop
    mock_repository.fetch_pending.side_effect = [[sample_event], []]

    mock_handler = Mock(side_effect=Exception("Handler error"))
    handlers = {sample_event.event_type: mock_handler}

    stop_event = Event()

    worker = OutboxWorker(
        batch_size=10,
        poll_interval=1.0,
        handlers=handlers,
        repository=mock_repository,
        stop_event=stop_event,
    )

    # Mock executor to return failed future
    mock_future = Future()
    mock_future.set_exception(Exception("Handler error"))
    worker.executor.submit = Mock(return_value=mock_future)

    def stop_after_first(*args, **kwargs):
        stop_event.set()

    with patch("dispatchbox.worker.time.sleep", side_effect=stop_after_first):
        worker.run_loop()

    mock_repository.mark_retry.assert_called_once_with(sample_event.id)
    mock_repository.mark_success.assert_not_called()


def test_run_loop_skips_event_without_id(mock_repository):
    """Test run_loop skips events without ID."""
    from unittest.mock import patch

    event_no_id = OutboxEvent(
        id=None,
        aggregate_type="order",
        aggregate_id="123",
        event_type="order.created",
        payload={},
        status="pending",
        attempts=0,
        next_run_at=Mock(),
    )

    # Return event without ID first, then empty to stop
    mock_repository.fetch_pending.side_effect = [[event_no_id], []]

    stop_event = Event()

    worker = OutboxWorker(
        batch_size=10,
        poll_interval=1.0,
        repository=mock_repository,
        stop_event=stop_event,
    )

    # Mock executor to return a future that will be processed
    mock_future = Future()
    mock_future.set_result(None)
    worker.executor.submit = Mock(return_value=mock_future)

    with patch("dispatchbox.worker.logger") as mock_logger:

        def stop_after_first(*args, **kwargs):
            stop_event.set()

        with patch("dispatchbox.worker.time.sleep", side_effect=stop_after_first):
            worker.run_loop()

        # Should log error about missing ID (logger.error is called in run_loop when event_id is None)
        # The error is logged at line 97 in worker.py
        mock_logger.error.assert_called_once()
        error_message = mock_logger.error.call_args[0][0]
        assert "no ID" in error_message.lower() or "has no ID" in error_message or "Event has no ID" in error_message

    # Should not call mark_success or mark_retry
    mock_repository.mark_success.assert_not_called()
    mock_repository.mark_retry.assert_not_called()


def test_run_loop_sleeps_when_no_events(mock_repository):
    """Test run_loop sleeps when no events are available."""
    mock_repository.fetch_pending.return_value = []

    stop_event = Event()

    worker = OutboxWorker(
        batch_size=10,
        poll_interval=1.0,
        repository=mock_repository,
        stop_event=stop_event,
    )

    call_count = 0

    def stop_after_sleep(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count >= 1:
            stop_event.set()

    with patch("dispatchbox.worker.time.sleep", side_effect=stop_after_sleep) as mock_sleep:
        worker.run_loop()

    # Should sleep when no events
    mock_sleep.assert_called_with(1.0)


def test_run_loop_processes_multiple_events(mock_repository, sample_event):
    """Test run_loop processes multiple events in batch."""
    event2 = OutboxEvent(
        id=2,
        aggregate_type="order",
        aggregate_id="456",
        event_type="order.created",
        payload={"orderId": "456"},
        status="pending",
        attempts=0,
        next_run_at=Mock(),
    )

    # Return events first, then empty to stop
    mock_repository.fetch_pending.side_effect = [[sample_event, event2], []]

    mock_handler = Mock()
    handlers = {sample_event.event_type: mock_handler}

    stop_event = Event()

    worker = OutboxWorker(
        batch_size=10,
        poll_interval=1.0,
        handlers=handlers,
        repository=mock_repository,
        stop_event=stop_event,
    )

    # Mock executor to return successful futures
    mock_future1 = Future()
    mock_future1.set_result(None)
    mock_future2 = Future()
    mock_future2.set_result(None)

    call_count = 0

    def mock_submit(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return mock_future1
        return mock_future2

    worker.executor.submit = mock_submit

    def stop_after_first(*args, **kwargs):
        stop_event.set()

    with patch("dispatchbox.worker.time.sleep", side_effect=stop_after_first):
        worker.run_loop()

    # Should mark both events as success
    assert mock_repository.mark_success.call_count == 2
