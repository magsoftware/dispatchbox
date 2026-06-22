# Dispatchbox load tests

These benchmarks run against a real PostgreSQL database and are intentionally separate from the normal `pytest`
suite. Every high-level scenario truncates the outbox tables before it starts. Never point `LOAD_DSN` at a database
containing data you need.

## Requirements

- PostgreSQL with the schema from `sql/schema.sql`
- `uv`
- PostgreSQL client tools: `psql` and `pgbench`

The default connection is:

```text
host=localhost port=5432 dbname=outbox user=postgres password=postgres
```

Override it for any command:

```bash
make load-drain LOAD_DSN="host=localhost dbname=outbox_load user=postgres"
```

## Scenarios

### Drain a finite backlog

This is the simplest repeatable throughput benchmark. It resets the tables, inserts `LOAD_EVENTS`, starts synthetic
workers, and stops when no `pending`, `retry`, or `processing` events remain.

```bash
make load-drain
make load-drain LOAD_EVENTS=1000000 LOAD_PROCESSES=8 LOAD_HANDLER_DELAY_MS=50
```

### Sustained producer load

This runs `pgbench` producers and Dispatchbox consumers concurrently for a fixed duration. The final
`active_remaining` value shows whether the consumers kept up with the requested rate.

```bash
make load-sustained LOAD_DURATION_SECONDS=300 LOAD_RATE=1000
```

### Parameter matrix

This drains a fresh backlog for every process/batch combination:

```bash
make load-matrix
make load-matrix \
  LOAD_MATRIX_PROCESSES="1 2 4" \
  LOAD_MATRIX_BATCH_SIZES="10 100 500"
```

### Lease recovery after a crash

This scenario claims one event with a deliberately slow handler, terminates that worker process, waits for the lease
to expire, and verifies that a new worker reclaims the event with a different token and completes it:

```bash
make load-lease-recovery
```

## Handler profiles

Synthetic handlers do not write per-event logs. Their behavior is controlled with environment variables:

| Variable | Default | Meaning |
|---|---:|---|
| `LOAD_HANDLER_DELAY_MS` | `0` | Fixed I/O-like delay |
| `LOAD_HANDLER_JITTER_MS` | `0` | Additional random delay between zero and this value |
| `LOAD_FAILURE_RATE` | `0` | Failure probability from `0` to `1` |
| `LOAD_MAX_PARALLEL` | `10` | Handler threads per worker process |

Use delay `0` to measure the database claim/finalize ceiling. Use delay and jitter to model external I/O. A sleeping
handler releases the Python GIL, so it models waiting on HTTP, SMTP, or a broker rather than CPU-bound work.

Jitter is sampled separately for every handler invocation and is added to the fixed delay:

```text
actual delay = LOAD_HANDLER_DELAY_MS + uniform(0, LOAD_HANDLER_JITTER_MS)
```

For example, delay `20` and jitter `480` produce a uniform 20-500 ms range with an average near 260 ms.
Ready-to-use profiles live under `load_tests/scenarios/`:

```bash
LOAD_SCENARIO=load_tests/scenarios/jitter_20_500ms.env make load-drain
LOAD_SCENARIO=load_tests/scenarios/failures_1pct.env make load-drain
```

## Results

JSON summaries and pgbench logs are written under `load_tests/results/`, which is ignored by Git. Important fields:

- `throughput_per_second`: terminal events divided by elapsed time
- `done` and `dead`: terminal transitions during the run
- `active_remaining`: backlog remaining at the end
- `timed_out`: whether a drain scenario exceeded its deadline

Shared defaults live in `load_tests/scripts/common.sh`; scenario files contain only overrides. Environment variables or
Make variables take precedence over those preset values.

## Known measurement caveats

- The `noop` scenario measures the current Dispatchbox implementation, not raw PostgreSQL `SKIP LOCKED` capacity.
  Every repository operation performs a connection check (`SELECT 1`) and sets `statement_timeout` before its actual
  query. Finalization is also one transaction per event. These round-trips are deliberately included in the result.
- The monitoring connection runs a filtered status aggregation at the configured progress interval. This adds a small
  amount of database load, especially for very short tests.
- Exact numbers from a laptop are best used for comparisons between configurations. They are not production capacity
  estimates unless PostgreSQL, networking, hardware, and handler latency resemble production.
- The runner refuses to start if it finds an event whose type is not `load.test`. High-level scenarios still truncate
  both outbox tables, so always use a dedicated database.

The monitor uses bounded connection, statement, TCP keepalive, and user-timeout settings. Configure its base timeout
with `LOAD_MONITOR_TIMEOUT_SECONDS`.
