"""Shared runtime primitives for Dispatchbox load-test scenarios."""

import argparse
import sys
import time
from typing import Any, Dict, List

from loguru import logger
import psycopg2

from dispatchbox.repository import OutboxRepository
from dispatchbox.worker import OutboxWorker
from load_tests.handlers import SyntheticHandler

LOAD_EVENT_TYPE = "load.test"
ACTIVE_STATUSES = ("pending", "retry", "processing")
DEFAULT_MONITOR_TIMEOUT_SECONDS = 10
DEFAULT_SHUTDOWN_TIMEOUT_SECONDS = 30


def positive_int(value: str) -> int:
    """Parse a positive integer for argparse."""
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be at least 1")
    return parsed


def non_negative_float(value: str) -> float:
    """Parse a non-negative float for argparse."""
    parsed = float(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be non-negative")
    return parsed


def failure_rate(value: str) -> float:
    """Parse a probability between zero and one for argparse."""
    parsed = float(value)
    if not 0 <= parsed <= 1:
        raise argparse.ArgumentTypeError("value must be between 0 and 1")
    return parsed


def connect_monitor(dsn: str, timeout_seconds: int) -> Any:
    """Open a bounded monitoring connection for benchmark coordination."""
    timeout_ms = timeout_seconds * 1000
    conn = psycopg2.connect(
        dsn,
        connect_timeout=timeout_seconds,
        keepalives=1,
        keepalives_idle=timeout_seconds,
        keepalives_interval=max(1, timeout_seconds // 3),
        keepalives_count=3,
        tcp_user_timeout=timeout_ms,
    )
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = %s", (timeout_ms,))
    conn.commit()
    return conn


def assert_isolated_load_data(conn: Any) -> None:
    """Refuse to run workers when non-load events are present."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM outbox_event WHERE event_type <> %s",
            (LOAD_EVENT_TYPE,),
        )
        foreign_events = cur.fetchone()[0]
    conn.commit()
    if foreign_events:
        raise RuntimeError(
            f"Refusing to run: found {foreign_events} events whose event_type is not {LOAD_EVENT_TYPE!r}"
        )


def queue_counts(conn: Any) -> Dict[str, int]:
    """Return status counts for synthetic load-test events."""
    counts = {status: 0 for status in (*ACTIVE_STATUSES, "done", "dead")}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT status, COUNT(*)
            FROM outbox_event
            WHERE event_type = %s
            GROUP BY status
            """,
            (LOAD_EVENT_TYPE,),
        )
        for status, count in cur.fetchall():
            counts[status] = count
    conn.commit()
    return counts


def active_count(counts: Dict[str, int]) -> int:
    """Count events that can be claimed or are currently processing."""
    return sum(counts[status] for status in ACTIVE_STATUSES)


def run_worker_process(
    dsn: str,
    stop_event: Any,
    batch_size: int,
    max_parallel: int,
    poll_interval: float,
    lease_seconds: int,
    retry_backoff_seconds: int,
    handler_delay_ms: float,
    handler_jitter_ms: float,
    handler_failure_rate: float,
    log_level: str,
) -> None:
    """Run one isolated worker process with a synthetic handler."""
    logger.remove()
    logger.add(sys.stderr, level=log_level)
    repository = OutboxRepository(
        dsn,
        retry_backoff_seconds=retry_backoff_seconds,
        lease_seconds=lease_seconds,
    )
    handler = SyntheticHandler(handler_delay_ms, handler_jitter_ms, handler_failure_rate)
    worker = OutboxWorker(
        batch_size=batch_size,
        poll_interval=poll_interval,
        max_parallel=max_parallel,
        stop_event=stop_event,
        handlers={LOAD_EVENT_TYPE: handler},
        repository=repository,
    )
    try:
        with repository:
            worker.run_loop()
    finally:
        worker.executor.shutdown(wait=True)


def stop_processes(
    stop_event: Any,
    processes: List[Any],
    timeout_seconds: float = DEFAULT_SHUTDOWN_TIMEOUT_SECONDS,
) -> None:
    """Stop all workers within one shared shutdown deadline."""
    stop_event.set()
    deadline = time.monotonic() + timeout_seconds
    for process in processes:
        process.join(timeout=max(0, deadline - time.monotonic()))

    alive = [process for process in processes if process.is_alive()]
    for process in alive:
        process.terminate()

    if not alive:
        return

    termination_deadline = time.monotonic() + 5
    for process in alive:
        process.join(timeout=max(0, termination_deadline - time.monotonic()))
        if process.is_alive() and hasattr(process, "kill"):
            process.kill()
            process.join(timeout=1)
