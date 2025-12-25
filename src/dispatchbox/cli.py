#!/usr/bin/env python3
"""Command-line interface for outbox worker."""

import argparse
import sys
from typing import Callable, Optional

from loguru import logger
import psycopg2

from dispatchbox.config import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_HTTP_HOST,
    DEFAULT_HTTP_PORT,
    DEFAULT_LOG_LEVEL,
    DEFAULT_NUM_PROCESSES,
    DEFAULT_POLL_INTERVAL,
)
from dispatchbox.http_server import HttpServer
from dispatchbox.repository import OutboxRepository
from dispatchbox.supervisor import start_processes


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Outbox worker (multi-process, SKIP LOCKED). "
        "Fetches pending/retry events from Postgres and processes them in parallel threads."
    )
    parser.add_argument(
        "--dsn",
        required=True,
        help="Postgres DSN (libpq style) or connection string, e.g. "
        "'host=localhost port=5432 dbname=outbox user=postgres password=postgres'",
    )
    parser.add_argument(
        "--processes",
        type=int,
        default=DEFAULT_NUM_PROCESSES,
        help=f"Number of worker processes to start (default: {DEFAULT_NUM_PROCESSES})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"How many events to fetch per DB round (default: {DEFAULT_BATCH_SIZE})",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=DEFAULT_POLL_INTERVAL,
        help=f"Seconds to sleep when no work (default: {DEFAULT_POLL_INTERVAL})",
    )
    parser.add_argument(
        "--log-level",
        default=DEFAULT_LOG_LEVEL,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help=f"Logging level (default: {DEFAULT_LOG_LEVEL})",
    )
    parser.add_argument(
        "--show-help",
        action="store_true",
        help="Display this help message and exit",
    )
    parser.add_argument(
        "--http-host",
        default=DEFAULT_HTTP_HOST,
        help=f"HTTP server host (default: {DEFAULT_HTTP_HOST})",
    )
    parser.add_argument(
        "--http-port",
        type=int,
        default=DEFAULT_HTTP_PORT,
        help=f"HTTP server port for health checks and metrics (default: {DEFAULT_HTTP_PORT})",
    )
    parser.add_argument(
        "--disable-http",
        action="store_true",
        help="Disable HTTP server for health checks and metrics",
    )
    return parser.parse_args()


def help() -> None:
    """Display help message for the user."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Outbox worker (multi-process, SKIP LOCKED). "
        "Fetches pending/retry events from Postgres and processes them in parallel threads."
    )
    parser.print_help()


def setup_logging(log_level: str) -> None:
    """
    Configure loguru logger with specified level.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    logger.remove()  # Remove default handler
    logger.add(
        sys.stderr,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<yellow>{extra[worker]}</yellow> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        level=log_level.upper(),
        colorize=True,
    )
    # Set default worker name for main process
    logger.configure(extra={"worker": "main"})


def create_db_check_function(dsn: str) -> Callable[[], bool]:
    """
    Create database check function for HTTP server.

    Args:
        dsn: PostgreSQL connection string

    Returns:
        Function that checks database connectivity
    """

    def check_db() -> bool:
        try:
            repo = OutboxRepository(dsn, connect_timeout=2, query_timeout=2)
            is_connected = repo.is_connected()
            repo.close()
            return is_connected
        # Catching psycopg2.Error covers all database-related errors:
        # - OperationalError: connection failures, timeouts
        # - InterfaceError: connection already closed, invalid state
        # - Other psycopg2 errors: all database operation failures
        # Returns False for any database error, maintaining consistent security posture
        except (psycopg2.Error, ValueError):
            return False

    return check_db


def create_repository_factory(dsn: str) -> Callable[[], OutboxRepository]:
    """
    Create repository factory function for DLQ endpoints.

    Args:
        dsn: PostgreSQL connection string

    Returns:
        Factory function that returns a new repository instance
    """

    def get_repository() -> OutboxRepository:
        """Factory function that returns a new repository instance for each request."""
        return OutboxRepository(
            dsn,
            connect_timeout=2,
            query_timeout=5,
        )

    return get_repository


def setup_http_server(args: argparse.Namespace) -> Optional[HttpServer]:
    """
    Setup and start HTTP server if enabled.

    Args:
        args: Parsed command-line arguments

    Returns:
        HttpServer instance if enabled, None otherwise
    """
    if args.disable_http:
        return None

    db_check_fn = create_db_check_function(args.dsn)
    repository_fn = create_repository_factory(args.dsn)

    http_server = HttpServer(
        host=args.http_host,
        port=args.http_port,
        db_check_fn=db_check_fn,
        repository_fn=repository_fn,
    )
    http_server.start()
    logger.info("HTTP server enabled on {}:{}", args.http_host, args.http_port)

    return http_server


def main() -> None:
    """Main entry point for the CLI."""
    args: argparse.Namespace = parse_args()

    if args.show_help:
        help()
        return

    setup_logging(args.log_level)

    logger.info(
        "Starting dispatchbox supervisor: processes={} batch_size={} poll_interval={}",
        args.processes,
        args.batch_size,
        args.poll_interval,
    )

    http_server = setup_http_server(args)

    try:
        start_processes(
            args.dsn,
            args.processes,
            args.batch_size,
            args.poll_interval,
        )
    finally:
        if http_server:
            http_server.stop()
