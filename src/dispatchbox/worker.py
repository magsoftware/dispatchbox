#!/usr/bin/env python3
"""OutboxWorker class for processing outbox events."""

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from multiprocessing import Event
import time
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from dispatchbox.handlers import HANDLERS
from dispatchbox.models import OutboxEvent
from dispatchbox.repository import OutboxRepository


class HandlerNotFoundError(RuntimeError):
    """Raised when no handler is found for an event type."""

    ...


class OutboxWorker:
    """Worker for processing outbox events in a single process with multi-threading."""

    def __init__(
        self,
        batch_size: int,
        poll_interval: float,
        max_parallel: int = 10,
        stop_event: Optional[Event] = None,
        handlers: Optional[Dict[str, Callable[[Dict[str, Any]], None]]] = None,
        repository: Optional[OutboxRepository] = None,
    ) -> None:
        """
        Initialize OutboxWorker.

        Args:
            batch_size: Number of events to fetch per batch
            poll_interval: Seconds to sleep when no work available
            max_parallel: Maximum number of parallel threads
            stop_event: Event to signal worker to stop
            handlers: Dictionary of event_type -> handler function (defaults to HANDLERS)
            repository: OutboxRepository instance (required)
        """
        if repository is None:
            raise ValueError("repository is required")

        self.batch_size: int = batch_size
        self.poll_interval: float = poll_interval
        self.stop_event: Optional[Event] = stop_event
        self.handlers: Dict[str, Callable[[Dict[str, Any]], None]] = handlers or HANDLERS
        self.repository: OutboxRepository = repository

        self.executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=max_parallel)

    def process_event(self, event: OutboxEvent) -> None:
        """
        Process a single event by calling its handler.

        Args:
            event: OutboxEvent instance

        Raises:
            HandlerNotFoundError: If no handler is found for the event type
        """
        event_type: str = event.event_type
        payload: Dict[str, Any] = event.payload

        handler: Optional[Callable[[Dict[str, Any]], None]] = self.handlers.get(event_type)
        if not handler:
            raise HandlerNotFoundError(f"No handler for event_type={event_type}")

        handler(payload)

    def run_loop(self) -> None:
        """Main processing loop that fetches and processes events."""
        logger.info("Worker started")

        while not (self.stop_event and self.stop_event.is_set()):
            batch: List[OutboxEvent] = self.repository.fetch_pending(self.batch_size)

            if not batch:
                time.sleep(self.poll_interval)
                continue

            logger.debug("Fetched {} events for processing", len(batch))

            futures: Dict[Future[None], OutboxEvent] = {
                self.executor.submit(self.process_event, evt): evt for evt in batch
            }

            for future in as_completed(futures):
                event: OutboxEvent = futures[future]
                event_id: Optional[int] = event.id

                if event_id is None:
                    logger.error("Event has no ID, skipping")
                    continue

                try:
                    future.result()
                    self.repository.mark_success(event_id)
                    logger.debug("Successfully processed event {}", event_id)
                # Catching generic Exception is intentional here for security reasons:
                # - Prevents information leakage about specific failure types (handler errors, validation failures, etc.)
                # - Ensures all events are properly marked for retry regardless of exception type
                # - Protects against revealing internal implementation details through error handling
                except Exception as e:
                    logger.error("Error processing event {}: {}", event_id, e, exc_info=True)
                    self.repository.mark_retry(event_id)
