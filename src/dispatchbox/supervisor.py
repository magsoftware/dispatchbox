#!/usr/bin/env python3
"""Process supervision for outbox workers."""

import signal
import sys
import time
from multiprocessing import Process, Event
from typing import List, Any

from loguru import logger

from dispatchbox.worker import OutboxWorker
from dispatchbox.repository import OutboxRepository
from dispatchbox.config import DEFAULT_MAX_PARALLEL, DEFAULT_RETRY_BACKOFF_SECONDS


def _setup_worker_logging(worker_name: str) -> str:
    """
    Setup logging with worker name and return full name with PID.

    Args:
        worker_name: Base worker name (e.g., "worker-00")

    Returns:
        Full worker name with PID (e.g., "worker-00-pid12345")
    """
    import os
    
    pid = os.getpid()
    full_worker_name = f"{worker_name}-pid{pid}"
    logger.configure(extra={"worker": full_worker_name})
    
    return full_worker_name


def _setup_worker_signal_handlers(stop_event: Event, worker_name: str) -> None:
    """
    Setup signal handlers for worker process.

    Args:
        stop_event: Event to signal worker to stop
        worker_name: Full worker name for logging
    """
    def _signal_handler(sig: int, frame: Any) -> None:
        logger.info("Worker {} received signal {}, initiating shutdown...", worker_name, sig)
        stop_event.set()
    
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)


def worker_loop(
    dsn: str,
    stop_event: Event,
    batch_size: int,
    poll_interval: float,
    worker_name: str,
    max_parallel: int = DEFAULT_MAX_PARALLEL,
    retry_backoff_seconds: int = DEFAULT_RETRY_BACKOFF_SECONDS,
) -> None:
    """
    Worker process entry point.

    Args:
        dsn: PostgreSQL connection string
        stop_event: Event to signal worker to stop
        batch_size: Number of events to fetch per batch
        poll_interval: Seconds to sleep when no work available
        worker_name: Unique name for this worker (e.g., "worker-00")
        max_parallel: Maximum number of parallel threads
        retry_backoff_seconds: Seconds to wait before retrying failed events
    """
    full_worker_name = _setup_worker_logging(worker_name)
    _setup_worker_signal_handlers(stop_event, full_worker_name)
    
    repository = OutboxRepository(
        dsn=dsn,
        retry_backoff_seconds=retry_backoff_seconds
    )
    
    worker = OutboxWorker(
        batch_size=batch_size,
        poll_interval=poll_interval,
        max_parallel=max_parallel,
        stop_event=stop_event,
        repository=repository,
    )
    
    with repository:
        worker.run_loop()


def _setup_signal_handlers(stop_event: Event, children: List[Process]) -> None:
    """
    Setup signal handlers for graceful shutdown.

    Args:
        stop_event: Event to signal workers to stop
        children: List of child processes
    """
    def _signal_handler(sig: int, frame: Any) -> None:
        logger.info("Parent received signal {}, stopping children...", sig)
        stop_event.set()
        for p in children:
            p.join(timeout=5)
        sys.exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)


def _start_worker_processes(
    dsn: str,
    num_processes: int,
    stop_event: Event,
    batch_size: int,
    poll_interval: float,
    max_parallel: int,
    retry_backoff_seconds: int,
) -> List[Process]:
    """
    Start all worker processes.

    Args:
        dsn: PostgreSQL connection string
        num_processes: Number of worker processes to start
        stop_event: Event to signal workers to stop
        batch_size: Number of events to fetch per batch
        poll_interval: Seconds to sleep when no work available
        max_parallel: Maximum number of parallel threads per process
        retry_backoff_seconds: Seconds to wait before retrying failed events

    Returns:
        List of started Process objects
    """
    children: List[Process] = []

    for i in range(num_processes):
        worker_name = f"worker-{i:02d}"
        p: Process = Process(
            target=worker_loop,
            args=(dsn, stop_event, batch_size, poll_interval, worker_name, max_parallel, retry_backoff_seconds),
            name=f"dispatchbox-worker-{i:02d}",
        )
        p.start()
        children.append(p)
        logger.info("Started worker process: worker-{:02d}-pid{}", i, p.pid)

    return children


def _wait_for_processes(children: List[Process], stop_event: Event) -> None:
    """
    Wait for all worker processes to complete.

    Args:
        children: List of child processes
        stop_event: Event to signal workers to stop
    """
    try:
        while True:
            alive: bool = any(p.is_alive() for p in children)
            if not alive:
                logger.info("All children have exited")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt - stopping")
        stop_event.set()
        for p in children:
            p.join()


def start_processes(
    dsn: str,
    num_processes: int,
    batch_size: int,
    poll_interval: float,
    max_parallel: int = DEFAULT_MAX_PARALLEL,
    retry_backoff_seconds: int = DEFAULT_RETRY_BACKOFF_SECONDS,
) -> None:
    """
    Start and supervise multiple worker processes.

    Args:
        dsn: PostgreSQL connection string
        num_processes: Number of worker processes to start
        batch_size: Number of events to fetch per batch
        poll_interval: Seconds to sleep when no work available
        max_parallel: Maximum number of parallel threads per process
        retry_backoff_seconds: Seconds to wait before retrying failed events
    """
    stop_event: Event = Event()
    children = _start_worker_processes(
        dsn, num_processes, stop_event, batch_size, poll_interval,
        max_parallel, retry_backoff_seconds
    )
    
    _setup_signal_handlers(stop_event, children)
    _wait_for_processes(children, stop_event)

