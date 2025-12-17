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
        worker_name: Unique name for this worker (e.g., "worker-0-pid12345")
        max_parallel: Maximum number of parallel threads
        retry_backoff_seconds: Seconds to wait before retrying failed events
    """
    import os
    
    # Get actual PID and create full worker name
    pid = os.getpid()
    full_worker_name = f"{worker_name}-pid{pid}"
    
    # Configure logger with worker name for all logs in this process
    logger.configure(extra={"worker": full_worker_name})
    
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
    children: List[Process] = []

    def _signal_handler(sig: int, frame: Any) -> None:
        logger.info("Parent received signal {}, stopping children...", sig)
        stop_event.set()
        for p in children:
            p.join(timeout=5)
        sys.exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

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

    # Wait for children
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

