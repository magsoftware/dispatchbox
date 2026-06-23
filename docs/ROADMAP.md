# Dispatchbox Roadmap

This file lists verified gaps in the current implementation. It is a planning
aid, not a description of features that already exist and not a commitment to
specific delivery dates. Completed behavior belongs in `ARCHITECTURE.md`.

## Reliability

- Implement controlled HTTP shutdown; `HttpServer.stop()` currently does not
  stop Bottle's server thread.
- Define worker shutdown semantics explicitly, including a deadline for the
  active batch and explicit `ThreadPoolExecutor` shutdown.
- Consider exponential retry backoff with jitter and a configurable maximum.
- Distinguish retryable handler/database failures from permanent failures.
- Define and document an idempotency strategy for handler side effects; lease
  fencing protects database finalization but does not provide exactly-once
  execution.

## Observability

- Provide actual Prometheus metrics and wire a metrics callback into CLI
  startup. `HttpServer` has a hook, but the CLI does not currently supply it.
- Add an optional structured JSON logging mode with event and worker context.
- Add DLQ alerting and retain useful failure information such as the last error
  and its timestamp.

## Configuration and operations

- Add environment-variable configuration suitable for container deployments.
- Expose currently internal settings where operationally useful, especially
  maximum parallelism, retry backoff, maximum attempts, and database timeouts.
- Add versioned database migrations instead of relying only on `schema.sql`.
- Add container and Kubernetes deployment artifacts if this repository is to
  own deployment concerns.

## Handler API

- Decide whether handlers need event metadata in addition to `payload`.
- Decide whether database access is an actual handler requirement before
  introducing a repository factory or connection pool.
- Define behavior for handlers that never return. A thread cannot be safely
  force-stopped, so a timeout alone does not cancel its side effects.

## DLQ operations

- Consider CLI commands or export tooling if operators cannot use the HTTP API.
- Decide retention and archival rules for `dead` events.
- Consider filters based on failure time after failure metadata exists.

## Quality gates

- Run real-PostgreSQL repository and concurrency tests in CI, not only when a
  developer supplies `DISPATCHBOX_TEST_DSN` locally.
- Expand CI beyond the current Pylint workflow to include tests, Ruff, and
  Pyright using the same commands as local verification.
