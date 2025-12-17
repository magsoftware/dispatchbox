#!/usr/bin/env python3
"""Command-line interface for outbox worker."""

import argparse
import sys
from typing import Optional
from loguru import logger

from dispatchbox.supervisor import start_processes
from dispatchbox.http_server import HttpServer
from dispatchbox.repository import OutboxRepository
from dispatchbox.config import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_NUM_PROCESSES,
    DEFAULT_LOG_LEVEL,
    DEFAULT_HTTP_HOST,
    DEFAULT_HTTP_PORT,
)


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
             "'host=localhost port=5432 dbname=outbox user=postgres password=postgres'"
    )
    parser.add_argument(
        "--processes",
        type=int,
        default=DEFAULT_NUM_PROCESSES,
        help=f"Number of worker processes to start (default: {DEFAULT_NUM_PROCESSES})"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"How many events to fetch per DB round (default: {DEFAULT_BATCH_SIZE})"
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=DEFAULT_POLL_INTERVAL,
        help=f"Seconds to sleep when no work (default: {DEFAULT_POLL_INTERVAL})"
    )
    parser.add_argument(
        "--log-level",
        default=DEFAULT_LOG_LEVEL,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help=f"Logging level (default: {DEFAULT_LOG_LEVEL})"
    )
    parser.add_argument(
        "--show-help",
        action="store_true",
        help="Display this help message and exit"
    )
    parser.add_argument(
        "--http-host",
        default=DEFAULT_HTTP_HOST,
        help=f"HTTP server host (default: {DEFAULT_HTTP_HOST})"
    )
    parser.add_argument(
        "--http-port",
        type=int,
        default=DEFAULT_HTTP_PORT,
        help=f"HTTP server port for health checks and metrics (default: {DEFAULT_HTTP_PORT})"
    )
    parser.add_argument(
        "--disable-http",
        action="store_true",
        help="Disable HTTP server for health checks and metrics"
    )
    return parser.parse_args()


def help() -> None:
    """Display help message for the user."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Outbox worker (multi-process, SKIP LOCKED). "
                    "Fetches pending/retry events from Postgres and processes them in parallel threads."
    )
    parser.print_help()


def main() -> None:
    """Main entry point for the CLI."""
    args: argparse.Namespace = parse_args()

    if args.show_help:
        help()
        return

    # Configure loguru
    log_level = args.log_level.upper()
    logger.remove()  # Remove default handler
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <yellow>{extra[worker]}</yellow> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level=log_level,
        colorize=True,
    )
    # Set default worker name for main process
    logger.configure(extra={"worker": "main"})
    
    logger.info(
        "Starting dispatchbox supervisor: processes={} batch_size={} poll_interval={}",
        args.processes,
        args.batch_size,
        args.poll_interval
    )

    # Start HTTP server for health checks, metrics, and API (if enabled)
    http_server: Optional[HttpServer] = None
    if not args.disable_http:
        # Create a test repository to check DB connectivity
        def check_db() -> bool:
            try:
                repo = OutboxRepository(args.dsn, connect_timeout=2, query_timeout=2)
                is_connected = repo.is_connected()
                repo.close()
                return is_connected
            except Exception:
                return False

        http_server = HttpServer(
            host=args.http_host,
            port=args.http_port,
            db_check_fn=check_db,
        )
        http_server.start()
        logger.info("HTTP server enabled on {}:{}", args.http_host, args.http_port)

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

