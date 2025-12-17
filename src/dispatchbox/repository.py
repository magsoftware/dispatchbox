#!/usr/bin/env python3
"""Repository for outbox events database operations."""

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Any

import psycopg2
from psycopg2.extras import RealDictCursor
from loguru import logger

from dispatchbox.models import OutboxEvent


class OutboxRepository:
    """Repository for managing outbox events in the database."""

    def __init__(self, dsn: str, retry_backoff_seconds: int = 30) -> None:
        """
        Initialize OutboxRepository.

        Args:
            dsn: PostgreSQL connection string
            retry_backoff_seconds: Seconds to wait before retrying failed events

        Raises:
            ValueError: If DSN is empty or invalid
            psycopg2.OperationalError: If connection cannot be established
        """
        if not dsn or not dsn.strip():
            raise ValueError("DSN cannot be empty")
        
        self.dsn: str = dsn.strip()
        self.retry_backoff: int = retry_backoff_seconds
        
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be non-negative")
        
        try:
            self.conn: Any = psycopg2.connect(self.dsn)
            self.conn.autocommit = False
        except psycopg2.OperationalError as e:
            logger.error("Failed to connect to database: {}", e)
            raise

    def _check_connection(self) -> None:
        """
        Check if database connection is alive and reconnect if needed.

        Raises:
            psycopg2.OperationalError: If connection cannot be restored
        """
        try:
            # Try to execute a simple query to check connection
            with self.conn.cursor() as cur:
                cur.execute("SELECT 1")
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            logger.warning("Database connection lost, attempting to reconnect...")
            try:
                self.conn.close()
            except Exception:
                pass
            
            try:
                self.conn = psycopg2.connect(self.dsn)
                self.conn.autocommit = False
                logger.info("Database connection restored")
            except psycopg2.OperationalError as e:
                logger.error("Failed to reconnect to database: {}", e)
                raise

    def fetch_pending(self, batch_size: int) -> List[OutboxEvent]:
        """
        Fetch a batch of pending/retry events from the database.

        Args:
            batch_size: Maximum number of events to fetch

        Returns:
            List of OutboxEvent instances
        """
        self._check_connection()
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, aggregate_type, aggregate_id, event_type, payload, 
                       status, attempts, next_run_at, created_at
                FROM outbox_event
                WHERE status IN ('pending','retry')
                  AND next_run_at <= now()
                ORDER BY id
                FOR UPDATE SKIP LOCKED
                LIMIT %s;
                """,
                (batch_size,),
            )
            rows = cur.fetchall()
            self.conn.commit()
            return [OutboxEvent.from_dict(dict(row)) for row in rows]

    def mark_success(self, event_id: int) -> None:
        """
        Mark an event as successfully processed.

        Args:
            event_id: ID of the event to mark as successful
        """
        self._check_connection()
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE outbox_event
                SET status = 'done',
                    attempts = attempts + 1
                WHERE id = %s;
                """,
                (event_id,),
            )
        self.conn.commit()

    def mark_retry(self, event_id: int) -> None:
        """
        Mark an event for retry with updated next_run_at timestamp.

        Args:
            event_id: ID of the event to mark for retry
        """
        self._check_connection()
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE outbox_event
                SET status = 'retry',
                    attempts = attempts + 1,
                    next_run_at = %s
                WHERE id = %s;
                """,
                (datetime.now(timezone.utc) + timedelta(seconds=self.retry_backoff), event_id),
            )
        self.conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        if self.conn:
            self.conn.close()

    def __enter__(self) -> "OutboxRepository":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit."""
        self.close()

