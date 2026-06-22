"""Tests for load-test result calculations."""

from argparse import Namespace
from unittest.mock import MagicMock, call, patch

import pytest

from load_tests.runtime import (
    active_count,
    assert_isolated_load_data,
    connect_monitor,
    queue_counts,
    stop_processes,
)
from load_tests.worker_runner import _build_summary


def test_active_count_includes_all_claimable_statuses():
    counts = {"pending": 2, "retry": 3, "processing": 4, "done": 5, "dead": 6}

    assert active_count(counts) == 9


def test_build_summary_reports_deltas_and_throughput():
    args = Namespace(
        mode="drain",
        processes=4,
        batch_size=100,
        max_parallel=10,
        handler_delay_ms=0,
        handler_jitter_ms=0,
        failure_rate=0,
    )
    initial = {"pending": 100, "retry": 0, "processing": 0, "done": 10, "dead": 1}
    final = {"pending": 0, "retry": 0, "processing": 0, "done": 108, "dead": 3}

    summary = _build_summary(args, initial, final, elapsed=2, timed_out=False)

    assert summary["processed"] == 100
    assert summary["done"] == 98
    assert summary["dead"] == 2
    assert summary["throughput_per_second"] == 50
    assert summary["active_remaining"] == 0
    assert summary["timed_out"] is False


def test_queue_counts_filters_load_event_type():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [("pending", 3), ("done", 7)]

    counts = queue_counts(conn)

    assert counts["pending"] == 3
    assert counts["done"] == 7
    assert counts["processing"] == 0
    assert cursor.execute.call_args[0][1] == ("load.test",)
    conn.commit.assert_called_once()


def test_preflight_rejects_foreign_events():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (2,)

    with pytest.raises(RuntimeError, match="found 2 events"):
        assert_isolated_load_data(conn)


def test_monitor_connection_uses_bounded_timeouts():
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value

    with patch("load_tests.runtime.psycopg2.connect", return_value=conn) as connect:
        result = connect_monitor("dbname=load", 12)

    assert result is conn
    connect.assert_called_once_with(
        "dbname=load",
        connect_timeout=12,
        keepalives=1,
        keepalives_idle=12,
        keepalives_interval=4,
        keepalives_count=3,
        tcp_user_timeout=12000,
    )
    cursor.execute.assert_called_once_with("SET statement_timeout = %s", (12000,))
    conn.commit.assert_called_once()


def test_stop_processes_uses_one_shared_deadline():
    stop_event = MagicMock()
    processes = [MagicMock(), MagicMock()]
    for process in processes:
        process.is_alive.return_value = False

    with patch("load_tests.runtime.time.monotonic", side_effect=[100, 101, 102]):
        stop_processes(stop_event, processes, timeout_seconds=30)

    stop_event.set.assert_called_once()
    assert processes[0].join.call_args_list == [call(timeout=29)]
    assert processes[1].join.call_args_list == [call(timeout=28)]
