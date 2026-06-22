#!/usr/bin/env python3
"""Repository for outbox events database operations."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional
from uuid import uuid4

from loguru import logger
import psycopg2
from psycopg2.extras import RealDictCursor

from dispatchbox.config import DEFAULT_LEASE_SECONDS, DEFAULT_MAX_ATTEMPTS
from dispatchbox.models import OutboxEvent


class OutboxRepository:
    """Repository for managing outbox events in the database."""

    # SQL queries as class constants
    FETCH_AND_CLAIM_SQL = """
        WITH picked AS (
            SELECT id
            FROM outbox_event
            WHERE status IN ('pending', 'retry', 'processing')
              AND next_run_at <= now()
            ORDER BY next_run_at ASC
            LIMIT %s
            FOR UPDATE SKIP LOCKED
        )
        UPDATE outbox_event e
        SET status = 'processing',
            claim_token = %s,
            next_run_at = now() + (%s * interval '1 second')
        FROM picked
        WHERE e.id = picked.id
        RETURNING e.id, e.aggregate_type, e.aggregate_id, e.event_type,
                  e.payload, e.status, e.attempts, e.next_run_at, e.created_at,
                  e.claim_token;
    """

    RENEW_CLAIM_SQL = """
        UPDATE outbox_event
        SET next_run_at = now() + (%s * interval '1 second')
        WHERE id = %s
          AND status = 'processing'
          AND claim_token = %s;
    """

    MARK_SUCCESS_SQL = """
        UPDATE outbox_event
        SET status = 'done',
            attempts = attempts + 1,
            claim_token = NULL
        WHERE id = %s
          AND status = 'processing'
          AND claim_token = %s;
    """

    MARK_RETRY_SQL = """
        UPDATE outbox_event
        SET status = CASE
            WHEN attempts + 1 >= %s THEN 'dead'
            ELSE 'retry'
        END,
        attempts = attempts + 1,
        claim_token = NULL,
        next_run_at = CASE
            WHEN attempts + 1 >= %s THEN next_run_at
            ELSE %s
        END
        WHERE id = %s
          AND status = 'processing'
          AND claim_token = %s;
    """

    CHECK_STATUS_SQL = "SELECT status FROM outbox_event WHERE id = %s;"

    CHECK_CONNECTION_SQL = "SELECT 1;"

    SET_TIMEOUT_SQL = "SET statement_timeout = %s;"

    FETCH_DEAD_EVENTS_BASE_SQL = """
        SELECT id, aggregate_type, aggregate_id, event_type, payload,
               status, attempts, next_run_at, created_at
        FROM outbox_event
        WHERE status = 'dead'
    """

    FETCH_DEAD_EVENTS_ORDER_LIMIT_SQL = " ORDER BY created_at DESC LIMIT %s OFFSET %s"

    COUNT_DEAD_EVENTS_BASE_SQL = """
        SELECT COUNT(*) as count
        FROM outbox_event
        WHERE status = 'dead'
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

    def _validate_dsn(self, dsn: str) -> None:
        """
        Validate DSN is not empty.

        Args:
            dsn: PostgreSQL connection string

        Raises:
            ValueError: If DSN is empty or whitespace only
        """
        if not dsn or not dsn.strip():
            raise ValueError("DSN cannot be empty")

    def _validate_parameters(
        self,
        retry_backoff_seconds: int,
        connect_timeout: int,
        query_timeout: int,
        max_attempts: int,
        lease_seconds: int,
    ) -> None:
        """
        Validate all initialization parameters.

        Args:
            retry_backoff_seconds: Seconds to wait before retrying failed events
            connect_timeout: Connection timeout in seconds
            query_timeout: Query timeout in seconds
            max_attempts: Maximum number of retry attempts
            lease_seconds: Claim duration before an event can be reclaimed

        Raises:
            ValueError: If any parameter is invalid
        """
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be non-negative")
        if connect_timeout < 0:
            raise ValueError("connect_timeout must be non-negative")
        if query_timeout < 0:
            raise ValueError("query_timeout must be non-negative")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1")

    def _add_connect_timeout_to_dsn(self, dsn: str, timeout: int) -> str:
        """
        Add connect_timeout to DSN if not present.

        Args:
            dsn: PostgreSQL connection string
            timeout: Connection timeout in seconds

        Returns:
            DSN with connect_timeout parameter added if needed
        """
        if "connect_timeout" not in dsn:
            separator = "&" if "?" in dsn else " "
            return f"{dsn}{separator}connect_timeout={timeout}"
        return dsn

    def _establish_connection(self, dsn_with_timeout: str) -> Any:
        """
        Establish database connection.

        Args:
            dsn_with_timeout: PostgreSQL connection string with timeout

        Returns:
            Database connection object

        Raises:
            psycopg2.OperationalError: If connection cannot be established
        """
        try:
            conn = psycopg2.connect(dsn_with_timeout)
            conn.autocommit = False
            return conn
        except psycopg2.OperationalError as e:
            logger.error("Failed to connect to database: {}", e)
            raise

    def __init__(
        self,
        dsn: str,
        retry_backoff_seconds: int = 30,
        connect_timeout: int = 10,
        query_timeout: int = 30,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
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
            lease_seconds: Claim duration in seconds (default: 300)

        Raises:
            ValueError: If DSN is empty or invalid
            psycopg2.OperationalError: If connection cannot be established
        """
        self._validate_dsn(dsn)
        self._validate_parameters(
            retry_backoff_seconds,
            connect_timeout,
            query_timeout,
            max_attempts,
            lease_seconds,
        )

        self.dsn: str = dsn.strip()
        self.retry_backoff: int = retry_backoff_seconds
        self.query_timeout: int = query_timeout
        self.max_attempts: int = max_attempts
        self.lease_seconds: int = lease_seconds

        dsn_with_timeout = self._add_connect_timeout_to_dsn(self.dsn, connect_timeout)
        self.conn: Any = self._establish_connection(dsn_with_timeout)

    def _set_query_timeout(self, cur: Any) -> None:
        """
        Set query timeout for current cursor.

        Args:
            cur: Database cursor
        """
        timeout_ms = self.query_timeout * 1000  # Convert to milliseconds
        cur.execute(self.SET_TIMEOUT_SQL, (timeout_ms,))

    def _rollback(self) -> None:
        """Rollback the current transaction without masking the original error."""
        try:
            self.conn.rollback()
        except (psycopg2.Error, AttributeError):
            logger.exception("Failed to rollback database transaction")

    @contextmanager
    def _transaction_cursor(self, cursor_factory: Any = None) -> Any:
        """Yield a cursor and always finish the transaction with commit or rollback."""
        try:
            self._check_connection()
            cursor_kwargs = {"cursor_factory": cursor_factory} if cursor_factory else {}
            with self.conn.cursor(**cursor_kwargs) as cur:
                self._set_query_timeout(cur)
                yield cur
            self.conn.commit()
        except Exception:
            self._rollback()
            raise

    def is_connected(self) -> bool:
        """
        Check if database connection is alive (without reconnecting).

        Returns:
            True if connection is alive, False otherwise
        """
        try:
            with self.conn.cursor() as cur:
                cur.execute(self.CHECK_CONNECTION_SQL)
            self.conn.commit()
            return True
        except psycopg2.Error:
            self._rollback()
            return False

    def _reconnect(self) -> None:
        """
        Reconnect to database after connection loss.

        Raises:
            psycopg2.OperationalError: If reconnection fails
        """
        logger.warning("Database connection lost, attempting to reconnect...")
        try:
            self.conn.close()
        # Catching specific psycopg2 exceptions for cleanup safety:
        # - Connection may already be closed or in an invalid state
        # - Prevents cleanup failures from blocking reconnection attempts
        # - Ensures reconnection proceeds regardless of close() outcome
        except (psycopg2.InterfaceError, psycopg2.OperationalError):
            pass

        try:
            # Reconnect with same timeout settings (default 10s for reconnect)
            dsn_with_timeout = self._add_connect_timeout_to_dsn(self.dsn, 10)
            self.conn = self._establish_connection(dsn_with_timeout)
            logger.info("Database connection restored")
        except psycopg2.OperationalError as e:
            logger.error("Failed to reconnect to database: {}", e)
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
                cur.execute(self.CHECK_CONNECTION_SQL)
        except (psycopg2.OperationalError, psycopg2.InterfaceError):
            self._reconnect()
        except psycopg2.Error:
            self._rollback()
            with self.conn.cursor() as cur:
                cur.execute(self.CHECK_CONNECTION_SQL)

    def fetch_pending(self, batch_size: int) -> List[OutboxEvent]:
        """
        Fetch and atomically claim a batch of pending/retry events.

        Uses UPDATE ... RETURNING to atomically set status='processing'
        in the same transaction as the SELECT FOR UPDATE.

        A unique claim token fences stale workers from completing a newer
        claim. Expired processing events can be reclaimed after next_run_at.

        Args:
            batch_size: Maximum number of events to fetch

        Returns:
            List of OutboxEvent instances with status='processing'
        """
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")

        claim_token = str(uuid4())
        with self._transaction_cursor(RealDictCursor) as cur:
            cur.execute(
                self.FETCH_AND_CLAIM_SQL,
                (batch_size, claim_token, self.lease_seconds),
            )
            rows = cur.fetchall()
        return [OutboxEvent.from_dict(dict(row)) for row in rows]

    def renew_claim(self, event_id: int, claim_token: str) -> bool:
        """Extend a claim lease if the caller still owns the event."""
        self._validate_claim(event_id, claim_token)
        with self._transaction_cursor() as cur:
            cur.execute(
                self.RENEW_CLAIM_SQL,
                (self.lease_seconds, event_id, claim_token),
            )
            renewed = cur.rowcount > 0
        return renewed

    def _validate_claim(self, event_id: int, claim_token: str) -> None:
        """Validate identifiers required for fenced claim operations."""
        if event_id is None or event_id < 1:
            raise ValueError("event_id must be a positive integer")
        if not claim_token or not claim_token.strip():
            raise ValueError("claim_token cannot be empty")

    def mark_success(self, event_id: int, claim_token: str) -> bool:
        """
        Mark an event as successfully processed.

        Args:
            event_id: ID of the event to mark as successful
            claim_token: Token returned when the event was claimed

        Returns:
            True if this claim was finalized, False if ownership was lost

        Raises:
            ValueError: If the event ID or claim token is invalid
        """
        self._validate_claim(event_id, claim_token)
        with self._transaction_cursor() as cur:
            cur.execute(self.MARK_SUCCESS_SQL, (event_id, claim_token))
            updated = cur.rowcount > 0
        return updated

    def _calculate_next_run_at(self) -> datetime:
        """
        Calculate next_run_at timestamp based on retry backoff.

        Returns:
            Datetime for next retry attempt
        """
        return datetime.now(timezone.utc) + timedelta(seconds=self.retry_backoff)

    def _log_if_dead(self, event_id: int, cur: Any) -> None:
        """
        Check and log if event was marked as dead.

        Args:
            event_id: ID of the event to check
            cur: Database cursor
        """
        cur.execute(self.CHECK_STATUS_SQL, (event_id,))
        result = cur.fetchone()
        if result and result[0] == "dead":
            logger.warning(
                "Event {} exceeded max_attempts ({}), marked as dead",
                event_id,
                self.max_attempts,
            )

    def mark_retry(self, event_id: int, claim_token: str) -> bool:
        """
        Mark an event for retry with updated next_run_at timestamp.
        If max_attempts is exceeded, mark event as 'dead' instead.

        Args:
            event_id: ID of the event to mark for retry
            claim_token: Token returned when the event was claimed

        Returns:
            True if this claim was finalized, False if ownership was lost

        Raises:
            ValueError: If the event ID or claim token is invalid
        """
        self._validate_claim(event_id, claim_token)
        next_run_at = self._calculate_next_run_at()

        with self._transaction_cursor() as cur:
            cur.execute(
                self.MARK_RETRY_SQL,
                (self.max_attempts, self.max_attempts, next_run_at, event_id, claim_token),
            )
            updated = cur.rowcount > 0
            if updated:
                self._log_if_dead(event_id, cur)
        return updated

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

    def _build_dead_events_sql(
        self,
        aggregate_type: Optional[str],
        event_type: Optional[str],
    ) -> tuple[str, List[Any]]:
        """
        Build SQL query and parameters for fetching dead events.

        Args:
            aggregate_type: Filter by aggregate type (optional)
            event_type: Filter by event type (optional)

        Returns:
            Tuple of (SQL query string, parameters list)
        """
        sql = self.FETCH_DEAD_EVENTS_BASE_SQL
        params: List[Any] = []

        if aggregate_type:
            sql += " AND aggregate_type = %s"
            params.append(aggregate_type)

        if event_type:
            sql += " AND event_type = %s"
            params.append(event_type)

        sql += self.FETCH_DEAD_EVENTS_ORDER_LIMIT_SQL

        return sql, params

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

        sql, params = self._build_dead_events_sql(aggregate_type, event_type)
        params.extend([limit, offset])

        with self._transaction_cursor(RealDictCursor) as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
        return [OutboxEvent.from_dict(dict(row)) for row in rows]

    def _build_count_dead_events_sql(
        self,
        aggregate_type: Optional[str],
        event_type: Optional[str],
    ) -> tuple[str, List[Any]]:
        """
        Build SQL query and parameters for counting dead events.

        Args:
            aggregate_type: Filter by aggregate type (optional)
            event_type: Filter by event type (optional)

        Returns:
            Tuple of (SQL query string, parameters list)
        """
        sql = self.COUNT_DEAD_EVENTS_BASE_SQL
        params: List[Any] = []

        if aggregate_type:
            sql += " AND aggregate_type = %s"
            params.append(aggregate_type)

        if event_type:
            sql += " AND event_type = %s"
            params.append(event_type)

        return sql, params

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
        sql, params = self._build_count_dead_events_sql(aggregate_type, event_type)

        with self._transaction_cursor(RealDictCursor) as cur:
            cur.execute(sql, tuple(params) if params else None)
            result = cur.fetchone()
        return result["count"] if result else 0

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

        with self._transaction_cursor(RealDictCursor) as cur:
            cur.execute(self.FETCH_DEAD_EVENT_BY_ID_SQL, (event_id,))
            row = cur.fetchone()
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

        with self._transaction_cursor() as cur:
            cur.execute(self.RETRY_DEAD_EVENT_SQL, (event_id,))
            updated = cur.rowcount > 0
        return updated

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

        with self._transaction_cursor() as cur:
            # Use ANY(%s) with array parameter for better performance
            cur.execute(self.RETRY_DEAD_EVENTS_BATCH_SQL, (event_ids,))
            updated = cur.rowcount
        return updated
