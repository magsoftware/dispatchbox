# ADR 0001: Use Bottle for the HTTP interface

- Status: Accepted
- Date: 2026-06-23

## Context

Dispatchbox needs a small synchronous HTTP interface for liveness, readiness,
and Dead Letter Queue operations. The worker itself is synchronous and uses
processes plus a thread pool, so an asynchronous web stack would add a second
concurrency model without solving a current requirement.

## Decision

Use Bottle with its built-in WSGI server, started in a daemon thread by
`HttpServer`.

Routes are registered explicitly with bound methods, for example:

```python
self.app.get("/health")(self._health)
```

This keeps route handlers directly testable and makes conditional route
registration straightforward. The `/metrics` route is registered only when a
`metrics_fn` callback is supplied.

## Consequences

- The runtime HTTP dependency remains small and synchronous.
- The interface is sufficient for the current health and DLQ API.
- The CLI currently does not supply `metrics_fn`, so standard CLI startup does
  not expose `/metrics`.
- Bottle's built-in server has no shutdown handle in this integration.
  `HttpServer.stop()` only records a shutdown request; the daemon thread ends
  with the main process.
- Reconsider the decision if the API grows substantially or requires async
  request handling, generated OpenAPI documentation, or controlled graceful
  HTTP shutdown.
