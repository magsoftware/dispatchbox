#!/usr/bin/env python3
"""OutboxWorker class for processing outbox events."""

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from multiprocessing import Event
import time
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from dispatchbox.handlers import HANDLERS
from dispatchbox.models import OutboxEvent
from dispatchbox.repository import OutboxRepository


class HandlerNotFoundError(RuntimeError):
    """Raised when no handler is found for an event type."""


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

    def _finalize_event(self, future: Future[None], event: OutboxEvent) -> None:
        """Persist a handler result only while this worker still owns the claim."""
        event_id = event.id
        claim_token = event.claim_token
        if event_id is None or not claim_token:
            logger.error("Event has no ID or claim token, skipping finalization")
            return

        try:
            future.result()
        except Exception as e:
            logger.error("Error processing event {}: {}", event_id, e, exc_info=True)
            try:
                updated = self.repository.mark_retry(event_id, claim_token)
            except Exception:
                logger.exception("Failed to mark event {} for retry", event_id)
                return
            if not updated:
                logger.warning("Ignored retry result for event {} because its claim was lost", event_id)
            return

        try:
            updated = self.repository.mark_success(event_id, claim_token)
        except Exception:
            logger.exception("Failed to mark event {} as successful", event_id)
            return
        if updated:
            logger.debug("Successfully processed event {}", event_id)
        else:
            logger.warning("Ignored success result for event {} because its claim was lost", event_id)

    def _renew_claims(self, pending: Dict[Future[None], OutboxEvent]) -> None:
        """Renew leases for handlers that are still running."""
        for event in pending.values():
            if event.id is None or not event.claim_token:
                continue
            try:
                renewed = self.repository.renew_claim(event.id, event.claim_token)
            except Exception:
                logger.exception("Failed to renew claim for event {}", event.id)
                continue
            if not renewed:
                logger.warning("Claim for event {} is no longer owned by this worker", event.id)

    def _process_batch(self, batch: List[OutboxEvent]) -> None:
        """Process a claimed batch and heartbeat leases until handlers finish."""
        pending: Dict[Future[None], OutboxEvent] = {
            self.executor.submit(self.process_event, event): event for event in batch
        }
        heartbeat_interval = max(0.1, self.repository.lease_seconds / 3)
        next_heartbeat = time.monotonic() + heartbeat_interval

        while pending:
            timeout = max(0.0, next_heartbeat - time.monotonic())
            completed, _ = wait(
                pending,
                timeout=timeout,
                return_when=FIRST_COMPLETED,
            )
            for future in completed:
                event = pending.pop(future)
                self._finalize_event(future, event)

            if pending and time.monotonic() >= next_heartbeat:
                self._renew_claims(pending)
                next_heartbeat = time.monotonic() + heartbeat_interval

    def run_loop(self) -> None:
        """Main processing loop that fetches and processes events."""
        logger.info("Worker started")

        while not (self.stop_event and self.stop_event.is_set()):
            batch: List[OutboxEvent] = self.repository.fetch_pending(self.batch_size)

            if not batch:
                time.sleep(self.poll_interval)
                continue

            logger.debug("Fetched {} events for processing", len(batch))

            self._process_batch(batch)
