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

    FETCH_DEAD_EVENTS_SQL = """
        SELECT id, aggregate_type, aggregate_id, event_type, payload, 
               status, attempts, next_run_at, created_at
        FROM outbox_event
        WHERE status = 'dead'
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s;
    """

    COUNT_DEAD_EVENTS_SQL = """
        SELECT COUNT(*) as count
        FROM outbox_event
        WHERE status = 'dead';
    """

    FETCH_DEAD_EVENT_BY_ID_SQL = """
        SELECT id, aggregate_type, aggregate_id, event_type, payload, 
               status, attempts, next_run_at, created_at
        FROM outbox_event
        WHERE id = %s AND status = 'dead';
    """

    RETRY_DEAD_EVENT_SQL = """
        UPDATE outbox_event
        SET status = 'pending',
            attempts = 0,
            next_run_at = now()
        WHERE id = %s AND status = 'dead';
    """

    RETRY_DEAD_EVENTS_BATCH_SQL = """
        UPDATE outbox_event
        SET status = 'pending',
            attempts = 0,
            next_run_at = now()
        WHERE id = ANY(%s) AND status = 'dead';
    """

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

    def is_connected(self) -> bool:
        """
        Check if database connection is alive (without reconnecting).

        Returns:
            True if connection is alive, False otherwise
        """
        try:
            with self.conn.cursor() as cur:
                cur.execute(self.CHECK_CONNECTION_SQL)
            return True
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            return False

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

    def fetch_dead_events(
        self,
        limit: int = 100,
        offset: int = 0,
        aggregate_type: Optional[str] = None,
        event_type: Optional[str] = None,
    ) -> List[OutboxEvent]:
        """
        Fetch dead events for review.

        Args:
            limit: Maximum number of events to fetch (default: 100)
            offset: Offset for pagination (default: 0)
            aggregate_type: Filter by aggregate type (optional)
            event_type: Filter by event type (optional)

        Returns:
            List of dead OutboxEvent instances
        """
        if limit < 1:
            raise ValueError("limit must be at least 1")
        if offset < 0:
            raise ValueError("offset must be non-negative")

        self._check_connection()
        
        # Build dynamic SQL with optional filters
        sql = """
            SELECT id, aggregate_type, aggregate_id, event_type, payload, 
                   status, attempts, next_run_at, created_at
            FROM outbox_event
            WHERE status = 'dead'
        """
        params: List[Any] = []
        
        if aggregate_type:
            sql += " AND aggregate_type = %s"
            params.append(aggregate_type)
        
        if event_type:
            sql += " AND event_type = %s"
            params.append(event_type)
        
        sql += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            self._set_query_timeout(cur)
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
            self.conn.commit()
            return [OutboxEvent.from_dict(dict(row)) for row in rows]

    def count_dead_events(
        self,
        aggregate_type: Optional[str] = None,
        event_type: Optional[str] = None,
    ) -> int:
        """
        Count dead events matching criteria.

        Args:
            aggregate_type: Filter by aggregate type (optional)
            event_type: Filter by event type (optional)

        Returns:
            Number of dead events
        """
        self._check_connection()
        
        sql = "SELECT COUNT(*) as count FROM outbox_event WHERE status = 'dead'"
        params: List[Any] = []
        
        if aggregate_type:
            sql += " AND aggregate_type = %s"
            params.append(aggregate_type)
        
        if event_type:
            sql += " AND event_type = %s"
            params.append(event_type)
        
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            self._set_query_timeout(cur)
            cur.execute(sql, tuple(params) if params else None)
            result = cur.fetchone()
            self.conn.commit()
            return result['count'] if result else 0

    def get_dead_event(self, event_id: int) -> Optional[OutboxEvent]:
        """
        Get a single dead event by ID.

        Args:
            event_id: ID of the dead event

        Returns:
            OutboxEvent if found and dead, None otherwise
        """
        if event_id is None or event_id < 1:
            raise ValueError("event_id must be a positive integer")

        self._check_connection()
        with self.conn.cursor(cursor_factory=RealDictCursor) as cur:
            self._set_query_timeout(cur)
            cur.execute(self.FETCH_DEAD_EVENT_BY_ID_SQL, (event_id,))
            row = cur.fetchone()
            self.conn.commit()
            if row:
                return OutboxEvent.from_dict(dict(row))
            return None

    def retry_dead_event(self, event_id: int) -> bool:
        """
        Reset a dead event to 'pending' for retry.

        Args:
            event_id: ID of dead event to retry

        Returns:
            True if event was successfully reset, False if not found or not dead

        Raises:
            ValueError: If event_id is invalid
        """
        if event_id is None or event_id < 1:
            raise ValueError("event_id must be a positive integer")

        self._check_connection()
        with self.conn.cursor() as cur:
            self._set_query_timeout(cur)
            cur.execute(self.RETRY_DEAD_EVENT_SQL, (event_id,))
            self.conn.commit()
            return cur.rowcount > 0

    def retry_dead_events_batch(self, event_ids: List[int]) -> int:
        """
        Reset multiple dead events to 'pending'.

        Args:
            event_ids: List of event IDs to retry

        Returns:
            Number of events successfully reset

        Raises:
            ValueError: If event_ids is empty or contains invalid IDs
        """
        if not event_ids:
            raise ValueError("event_ids cannot be empty")
        
        if any(eid is None or eid < 1 for eid in event_ids):
            raise ValueError("All event_ids must be positive integers")

        self._check_connection()
        
        with self.conn.cursor() as cur:
            self._set_query_timeout(cur)
            # Use ANY(%s) with array parameter for better performance
            cur.execute(self.RETRY_DEAD_EVENTS_BATCH_SQL, (event_ids,))
            self.conn.commit()
            return cur.rowcount

