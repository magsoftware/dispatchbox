#!/usr/bin/env python3
"""Repository for outbox events database operations."""

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Any

import psycopg2
from psycopg2.extras import RealDictCursor
from loguru import logger

from dispatchbox.models import OutboxEvent
from dispatchbox.config import DEFAULT_MAX_ATTEMPTS


class OutboxRepository:
    """Repository for managing outbox events in the database."""

    # SQL queries as class constants
    FETCH_PENDING_SQL = """
        SELECT id, aggregate_type, aggregate_id, event_type, payload, 
               status, attempts, next_run_at, created_at
        FROM outbox_event
        WHERE status IN ('pending','retry')
          AND next_run_at <= now()
        ORDER BY id
        FOR UPDATE SKIP LOCKED
        LIMIT %s;
    """

    MARK_SUCCESS_SQL = """
        UPDATE outbox_event
        SET status = 'done',
            attempts = attempts + 1
        WHERE id = %s;
    """

    MARK_RETRY_SQL = """
        UPDATE outbox_event
        SET status = CASE 
            WHEN attempts + 1 >= %s THEN 'dead'
            ELSE 'retry'
        END,
        attempts = attempts + 1,
        next_run_at = CASE
            WHEN attempts + 1 >= %s THEN next_run_at
            ELSE %s
        END
        WHERE id = %s;
    """

    CHECK_STATUS_SQL = "SELECT status FROM outbox_event WHERE id = %s;"

    CHECK_CONNECTION_SQL = "SELECT 1;"

    SET_TIMEOUT_SQL = "SET statement_timeout = %s;"

    def __init__(
        self,
        dsn: str,
        retry_backoff_seconds: int = 30,
        connect_timeout: int = 10,
        query_timeout: int = 30,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        """
        Initialize OutboxRepository.

        Args:
            dsn: PostgreSQL connection string
            retry_backoff_seconds: Seconds to wait before retrying failed events
            connect_timeout: Connection timeout in seconds (default: 10)
            query_timeout: Query timeout in seconds (default: 30)
            max_attempts: Maximum number of retry attempts before marking event
                as dead (default: 5)

        Raises:
            ValueError: If DSN is empty or invalid
            psycopg2.OperationalError: If connection cannot be established
        """
        # Validate DSN
        if not dsn or not dsn.strip():
            raise ValueError("DSN cannot be empty")
        
        self.dsn: str = dsn.strip()
        self.retry_backoff: int = retry_backoff_seconds
        self.query_timeout: int = query_timeout
        self.max_attempts: int = max_attempts
        
        # Validate parameters
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be non-negative")
        if connect_timeout < 0:
            raise ValueError("connect_timeout must be non-negative")
        if query_timeout < 0:
            raise ValueError("query_timeout must be non-negative")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        
        # Add connect_timeout to DSN if not already present
        dsn_with_timeout = self.dsn
        if "connect_timeout" not in dsn_with_timeout:
            separator = "&" if "?" in dsn_with_timeout else " "
            dsn_with_timeout = f"{dsn_with_timeout}{separator}connect_timeout={connect_timeout}"
        
        # Establish database connection
        try:
            self.conn: Any = psycopg2.connect(dsn_with_timeout)
            self.conn.autocommit = False
        except psycopg2.OperationalError as e:
            logger.error("Failed to connect to database: {}", e)
            raise

    def _set_query_timeout(self, cur: Any) -> None:
        """
        Set query timeout for current cursor.

        Args:
            cur: Database cursor
        """
        timeout_ms = self.query_timeout * 1000  # Convert to milliseconds
        cur.execute(self.SET_TIMEOUT_SQL, (timeout_ms,))

    def _check_connection(self) -> None:
        """
        Check if database connection is alive and reconnect if needed.

        Raises:
            psycopg2.OperationalError: If connection cannot be restored
        """
        try:
            # Try to execute a simple query to check connection
            with self.conn.cursor() as cur:
                cur.execute(self.CHECK_CONNECTION_SQL)
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            logger.warning("Database connection lost, attempting to reconnect...")
            try:
                self.conn.close()
            except Exception:
                pass
            
            try:
                # Reconnect with same timeout settings
                dsn_with_timeout = self.dsn
                if "connect_timeout" not in dsn_with_timeout:
                    separator = "&" if "?" in dsn_with_timeout else " "
                    dsn_with_timeout = f"{dsn_with_timeout}{separator}connect_timeout=10"
                
                self.conn = psycopg2.connect(dsn_with_timeout)
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
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        
        self._check_connection()
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            self._set_query_timeout(cur)
            cur.execute(self.FETCH_PENDING_SQL, (batch_size,))
            rows = cur.fetchall()
            self.conn.commit()
            return [OutboxEvent.from_dict(dict(row)) for row in rows]

    def mark_success(self, event_id: int) -> None:
        """
        Mark an event as successfully processed.

        Args:
            event_id: ID of the event to mark as successful

        Raises:
            ValueError: If event_id is invalid
        """
        if event_id is None or event_id < 1:
            raise ValueError("event_id must be a positive integer")
        
        self._check_connection()
        with self.conn.cursor() as cur:
            self._set_query_timeout(cur)
            cur.execute(self.MARK_SUCCESS_SQL, (event_id,))
        self.conn.commit()

    def mark_retry(self, event_id: int) -> None:
        """
        Mark an event for retry with updated next_run_at timestamp.
        If max_attempts is exceeded, mark event as 'dead' instead.

        Args:
            event_id: ID of the event to mark for retry

        Raises:
            ValueError: If event_id is invalid
        """
        if event_id is None or event_id < 1:
            raise ValueError("event_id must be a positive integer")
        
        self._check_connection()
        next_run_at = datetime.now(timezone.utc) + timedelta(seconds=self.retry_backoff)
        
        with self.conn.cursor() as cur:
            self._set_query_timeout(cur)
            cur.execute(
                self.MARK_RETRY_SQL,
                (self.max_attempts, self.max_attempts, next_run_at, event_id),
            )
            if cur.rowcount > 0:
                # Log if event was marked as dead
                cur.execute(self.CHECK_STATUS_SQL, (event_id,))
                result = cur.fetchone()
                if result and result[0] == 'dead':
                    logger.warning(
                        "Event {} exceeded max_attempts ({}), marked as dead",
                        event_id,
                        self.max_attempts,
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

