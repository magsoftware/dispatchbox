# ADR 0002: Keep raw SQL in the repository

- Status: Accepted
- Date: 2026-06-23

## Context

The repository contains PostgreSQL-specific operations, including atomic event
claiming with a CTE, `FOR UPDATE SKIP LOCKED`, `UPDATE ... RETURNING`, fencing
tokens, lease renewal, and filtered DLQ queries.

Introducing an ORM or query builder would require another dependency and table
metadata while the implementation would still need to preserve these exact
PostgreSQL semantics.

## Decision

Keep parameterized raw SQL in `OutboxRepository`.

SQL statements remain named class constants. Dynamic DLQ filters are assembled
only from fixed SQL fragments, while all values are passed separately through
psycopg2 parameters.

## Consequences

- Claiming and fencing behavior stays explicit and easy to inspect against
  PostgreSQL semantics.
- No ORM or query-builder dependency is required.
- The schema and repository queries must be kept aligned manually.
- SQL behavior needs focused repository and real-PostgreSQL concurrency tests.
- Reconsider the decision if the data model grows enough that duplicated table
  metadata, complex composition, or multi-database support outweighs the added
  abstraction.
