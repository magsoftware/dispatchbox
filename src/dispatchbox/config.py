#!/usr/bin/env python3
"""Configuration constants for outbox worker."""

# Default configuration values
DEFAULT_BATCH_SIZE: int = 10
DEFAULT_POLL_INTERVAL: float = 1.0
DEFAULT_MAX_PARALLEL: int = 10
DEFAULT_RETRY_BACKOFF_SECONDS: int = 30
DEFAULT_MAX_ATTEMPTS: int = 5
DEFAULT_NUM_PROCESSES: int = 1
DEFAULT_LOG_LEVEL: str = "INFO"

