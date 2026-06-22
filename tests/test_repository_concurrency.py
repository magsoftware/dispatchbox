"""PostgreSQL integration tests for outbox claim concurrency."""

import os
from uuid import uuid4

import psycopg2
from psycopg2 import sql
import pytest

from dispatchbox.repository import OutboxRepository

TEST_DSN = os.getenv("DISPATCHBOX_TEST_DSN")
pytestmark = pytest.mark.skipif(
    not TEST_DSN,
    reason="Set DISPATCHBOX_TEST_DSN to run PostgreSQL concurrency tests",
)


@pytest.fixture
def postgres_claim_context():
    """Create an isolated schema and two independent repository connections."""
    schema = f"dispatchbox_test_{uuid4().hex}"
    admin = psycopg2.connect(TEST_DSN)
    admin.autocommit = True
    repo_a = None
    repo_b = None

    with admin.cursor() as cur:
        cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        cur.execute(
            sql.SQL(
                """
                CREATE TABLE {}.outbox_event (
                    id BIGSERIAL PRIMARY KEY,
                    aggregate_type TEXT NOT NULL,
                    aggregate_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    claim_token TEXT,
                    attempts INT NOT NULL DEFAULT 0,
                    next_run_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            ).format(sql.Identifier(schema))
        )

    try:
        repo_a = OutboxRepository(TEST_DSN, lease_seconds=30)
        repo_b = OutboxRepository(TEST_DSN, lease_seconds=30)
        for repo in (repo_a, repo_b):
            with repo.conn.cursor() as cur:
                cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            repo.conn.commit()
        yield schema, admin, repo_a, repo_b
    finally:
        if repo_a:
            repo_a.close()
        if repo_b:
            repo_b.close()
        with admin.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        admin.close()


def _insert_event(admin, schema, aggregate_id):
    with admin.cursor() as cur:
        cur.execute(
            sql.SQL(
                """
                INSERT INTO {}.outbox_event
                    (aggregate_type, aggregate_id, event_type, payload)
                VALUES ('order', %s, 'order.created', '{}'::jsonb)
                RETURNING id
                """
            ).format(sql.Identifier(schema)),
            (aggregate_id,),
        )
        return cur.fetchone()[0]


def test_skip_locked_claims_another_available_event(postgres_claim_context):
    """A row locked by one transaction is skipped by another repository."""
    schema, admin, _, repo_b = postgres_claim_context
    locked_id = _insert_event(admin, schema, "locked")
    available_id = _insert_event(admin, schema, "available")
    locker = psycopg2.connect(TEST_DSN)

    try:
        with locker.cursor() as cur:
            cur.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            cur.execute("SELECT id FROM outbox_event WHERE id = %s FOR UPDATE", (locked_id,))

        claimed = repo_b.fetch_pending(2)

        assert [event.id for event in claimed] == [available_id]
    finally:
        locker.rollback()
        locker.close()


def test_reclaim_fences_stale_worker(postgres_claim_context):
    """After expiry, the old token cannot overwrite the newer claim."""
    schema, admin, repo_a, repo_b = postgres_claim_context
    event_id = _insert_event(admin, schema, "reclaimed")

    first = repo_a.fetch_pending(1)[0]
    assert repo_b.fetch_pending(1) == []

    with admin.cursor() as cur:
        cur.execute(
            sql.SQL("UPDATE {}.outbox_event SET next_run_at = now() - interval '1 second' WHERE id = %s").format(
                sql.Identifier(schema)
            ),
            (event_id,),
        )

    second = repo_b.fetch_pending(1)[0]

    assert second.claim_token != first.claim_token
    assert repo_a.mark_success(event_id, first.claim_token) is False
    assert repo_b.mark_success(event_id, second.claim_token) is True
