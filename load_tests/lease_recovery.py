#!/usr/bin/env python3
"""Verify recovery of a claimed event after an abrupt worker crash."""

import argparse
from datetime import datetime, timezone
import json
from multiprocessing import Event, Process
from pathlib import Path
import time
from typing import Any, Dict, Optional

from load_tests.runtime import (
    DEFAULT_MONITOR_TIMEOUT_SECONDS,
    LOAD_EVENT_TYPE,
    assert_isolated_load_data,
    connect_monitor,
    non_negative_float,
    positive_int,
    run_worker_process,
    stop_processes,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test lease recovery after a worker crash")
    parser.add_argument("--dsn", required=True, help="PostgreSQL DSN")
    parser.add_argument("--lease-seconds", type=positive_int, default=3)
    parser.add_argument("--timeout-seconds", type=positive_int, default=30)
    parser.add_argument("--recovery-handler-delay-ms", type=non_negative_float, default=200)
    parser.add_argument(
        "--monitor-timeout-seconds",
        type=positive_int,
        default=DEFAULT_MONITOR_TIMEOUT_SECONDS,
    )
    parser.add_argument("--json-output", type=Path)
    return parser.parse_args()


def _event_state(conn: Any) -> Dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, status, claim_token, attempts, next_run_at
            FROM outbox_event
            WHERE event_type = %s
            ORDER BY id
            """,
            (LOAD_EVENT_TYPE,),
        )
        rows = cur.fetchall()
    conn.commit()
    if len(rows) != 1:
        raise RuntimeError(f"Lease recovery requires exactly one {LOAD_EVENT_TYPE!r} event; found {len(rows)}")
    row = rows[0]
    return {
        "id": row[0],
        "status": row[1],
        "claim_token": row[2],
        "attempts": row[3],
        "next_run_at": row[4],
    }


def _wait_for_state(conn: Any, predicate: Any, deadline: float, description: str) -> Dict[str, Any]:
    while time.monotonic() < deadline:
        state = _event_state(conn)
        if predicate(state):
            return state
        time.sleep(0.02)
    raise TimeoutError(f"Timed out waiting for {description}")


def _make_worker(
    dsn: str,
    stop_event: Event,
    lease_seconds: int,
    handler_delay_ms: float,
    name: str,
) -> Process:
    return Process(
        target=run_worker_process,
        kwargs={
            "dsn": dsn,
            "stop_event": stop_event,
            "batch_size": 1,
            "max_parallel": 1,
            "poll_interval": 0.01,
            "lease_seconds": lease_seconds,
            "retry_backoff_seconds": 1,
            "handler_delay_ms": handler_delay_ms,
            "handler_jitter_ms": 0,
            "handler_failure_rate": 0,
            "log_level": "WARNING",
        },
        name=name,
    )


def run(args: argparse.Namespace) -> int:
    monitor = connect_monitor(args.dsn, args.monitor_timeout_seconds)
    assert_isolated_load_data(monitor)
    initial = _event_state(monitor)
    if initial["status"] not in ("pending", "retry"):
        raise RuntimeError(f"Expected a pending event, found status={initial['status']!r}")

    crash_stop = Event()
    recovery_stop = Event()
    crashed_worker = _make_worker(
        args.dsn,
        crash_stop,
        args.lease_seconds,
        args.lease_seconds * 2000,
        "lease-crashed-worker",
    )
    recovery_worker: Optional[Process] = None
    crashed_worker_started = False
    recovery_worker_started = False
    started = time.monotonic()
    deadline = started + args.timeout_seconds

    try:
        crashed_worker.start()
        crashed_worker_started = True
        first_claim = _wait_for_state(
            monitor,
            lambda state: state["status"] == "processing" and bool(state["claim_token"]),
            deadline,
            "the first worker to claim the event",
        )

        crashed_worker.terminate()
        crashed_worker.join(timeout=5)

        recovery_worker = _make_worker(
            args.dsn,
            recovery_stop,
            args.lease_seconds,
            args.recovery_handler_delay_ms,
            "lease-recovery-worker",
        )
        recovery_worker.start()
        recovery_worker_started = True
        reclaimed = _wait_for_state(
            monitor,
            lambda state: (
                state["status"] == "processing"
                and bool(state["claim_token"])
                and state["claim_token"] != first_claim["claim_token"]
            ),
            deadline,
            "a new worker to reclaim the expired event",
        )
        completed = _wait_for_state(
            monitor,
            lambda state: state["status"] == "done",
            deadline,
            "the reclaimed event to complete",
        )
    finally:
        if crashed_worker_started:
            stop_processes(crash_stop, [crashed_worker], timeout_seconds=5)
        if recovery_worker and recovery_worker_started:
            stop_processes(recovery_stop, [recovery_worker], timeout_seconds=5)
        monitor.close()

    elapsed = time.monotonic() - started
    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_id": completed["id"],
        "lease_seconds": args.lease_seconds,
        "elapsed_seconds": round(elapsed, 3),
        "first_claim_token": first_claim["claim_token"],
        "reclaimed_claim_token": reclaimed["claim_token"],
        "token_changed": reclaimed["claim_token"] != first_claim["claim_token"],
        "final_status": completed["status"],
        "attempts": completed["attempts"],
    }
    rendered = json.dumps(summary, indent=2, sort_keys=True)
    print(rendered)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(f"{rendered}\n", encoding="utf-8")
    return 0


def main() -> None:
    raise SystemExit(run(parse_args()))


if __name__ == "__main__":
    main()
