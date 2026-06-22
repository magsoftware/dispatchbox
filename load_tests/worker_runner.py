#!/usr/bin/env python3
"""Run benchmark workers and report queue throughput."""

import argparse
from datetime import datetime, timezone
import json
from multiprocessing import Event, Process
from pathlib import Path
import signal
import time
from typing import Any, Dict, Optional

from load_tests.runtime import (
    DEFAULT_MONITOR_TIMEOUT_SECONDS,
    active_count,
    assert_isolated_load_data,
    connect_monitor,
    failure_rate,
    non_negative_float,
    positive_int,
    queue_counts,
    run_worker_process,
    stop_processes,
)


def parse_args() -> argparse.Namespace:
    """Parse load-worker configuration."""
    parser = argparse.ArgumentParser(description="Run Dispatchbox load-test workers")
    parser.add_argument("--dsn", required=True, help="PostgreSQL DSN")
    parser.add_argument("--mode", choices=("drain", "duration"), default="drain")
    parser.add_argument("--duration-seconds", type=positive_int, default=60)
    parser.add_argument("--timeout-seconds", type=positive_int, default=600)
    parser.add_argument("--processes", type=positive_int, default=1)
    parser.add_argument("--batch-size", type=positive_int, default=100)
    parser.add_argument("--max-parallel", type=positive_int, default=10)
    parser.add_argument("--poll-interval", type=non_negative_float, default=0.01)
    parser.add_argument("--lease-seconds", type=positive_int, default=300)
    parser.add_argument("--retry-backoff-seconds", type=int, default=1)
    parser.add_argument("--handler-delay-ms", type=non_negative_float, default=0)
    parser.add_argument("--handler-jitter-ms", type=non_negative_float, default=0)
    parser.add_argument("--failure-rate", type=failure_rate, default=0)
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        default="WARNING",
    )
    parser.add_argument("--progress-seconds", type=non_negative_float, default=1)
    parser.add_argument(
        "--monitor-timeout-seconds",
        type=positive_int,
        default=DEFAULT_MONITOR_TIMEOUT_SECONDS,
    )
    parser.add_argument("--stop-file", type=Path)
    parser.add_argument("--json-output", type=Path)
    return parser.parse_args()


def _print_progress(elapsed: float, counts: Dict[str, int]) -> None:
    print(
        "progress"
        f" elapsed={elapsed:.1f}s"
        f" pending={counts['pending']}"
        f" retry={counts['retry']}"
        f" processing={counts['processing']}"
        f" done={counts['done']}"
        f" dead={counts['dead']}",
        flush=True,
    )


def _build_summary(
    args: argparse.Namespace,
    initial: Dict[str, int],
    final: Dict[str, int],
    elapsed: float,
    timed_out: bool,
) -> Dict[str, Any]:
    done_delta = max(0, final["done"] - initial["done"])
    dead_delta = max(0, final["dead"] - initial["dead"])
    terminal_delta = done_delta + dead_delta
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "elapsed_seconds": round(elapsed, 3),
        "timed_out": timed_out,
        "processes": args.processes,
        "batch_size": args.batch_size,
        "max_parallel": args.max_parallel,
        "handler_delay_ms": args.handler_delay_ms,
        "handler_jitter_ms": args.handler_jitter_ms,
        "failure_rate": args.failure_rate,
        "initial": initial,
        "final": final,
        "processed": terminal_delta,
        "done": done_delta,
        "dead": dead_delta,
        "throughput_per_second": round(terminal_delta / elapsed, 3) if elapsed else 0,
        "active_remaining": active_count(final),
    }


def run(args: argparse.Namespace) -> int:
    """Run configured workers and return a process exit status."""
    monitor = connect_monitor(args.dsn, args.monitor_timeout_seconds)
    assert_isolated_load_data(monitor)
    initial = queue_counts(monitor)
    stop_event = Event()
    processes = [
        Process(
            target=run_worker_process,
            kwargs={
                "dsn": args.dsn,
                "stop_event": stop_event,
                "batch_size": args.batch_size,
                "max_parallel": args.max_parallel,
                "poll_interval": args.poll_interval,
                "lease_seconds": args.lease_seconds,
                "retry_backoff_seconds": args.retry_backoff_seconds,
                "handler_delay_ms": args.handler_delay_ms,
                "handler_jitter_ms": args.handler_jitter_ms,
                "handler_failure_rate": args.failure_rate,
                "log_level": args.log_level,
            },
            name=f"load-worker-{index:02d}",
        )
        for index in range(args.processes)
    ]

    interrupted = False

    def request_stop(signum: int, frame: Optional[Any]) -> None:
        del signum, frame
        nonlocal interrupted
        interrupted = True
        stop_event.set()

    previous_sigint = signal.signal(signal.SIGINT, request_stop)
    previous_sigterm = signal.signal(signal.SIGTERM, request_stop)
    start = time.perf_counter()
    next_progress = start
    timed_out = False

    try:
        for process in processes:
            process.start()

        deadline_seconds = args.timeout_seconds if args.mode == "drain" else args.duration_seconds
        deadline = start + deadline_seconds

        while not interrupted:
            now = time.perf_counter()
            counts = queue_counts(monitor)
            if args.progress_seconds and now >= next_progress:
                _print_progress(now - start, counts)
                next_progress = now + args.progress_seconds

            if args.mode == "drain" and active_count(counts) == 0:
                break
            if args.stop_file and args.stop_file.exists():
                break
            if now >= deadline:
                timed_out = args.mode == "drain"
                break
            if any(process.exitcode not in (None, 0) for process in processes):
                raise RuntimeError("A load-test worker exited unexpectedly")
            time.sleep(min(0.1, args.progress_seconds or 0.1))
    finally:
        stop_processes(stop_event, processes)
        elapsed = time.perf_counter() - start
        final = queue_counts(monitor)
        monitor.close()
        signal.signal(signal.SIGINT, previous_sigint)
        signal.signal(signal.SIGTERM, previous_sigterm)

    summary = _build_summary(args, initial, final, elapsed, timed_out)
    rendered = json.dumps(summary, indent=2, sort_keys=True)
    print(rendered)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(f"{rendered}\n", encoding="utf-8")

    return 1 if interrupted or timed_out else 0


def main() -> None:
    raise SystemExit(run(parse_args()))


if __name__ == "__main__":
    main()
