#!/usr/bin/env python3
"""HTTP server for health checks, metrics, and API endpoints."""

import threading
import json
from typing import Optional, Callable, List, Any
from bottle import Bottle, run, response, request, HTTPError
from loguru import logger


class HttpServer:
    """HTTP server for health checks, metrics, and API endpoints."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        db_check_fn: Optional[Callable[[], bool]] = None,
        metrics_fn: Optional[Callable[[], str]] = None,
        repository_fn: Optional[Callable[[], Any]] = None,
    ) -> None:
        """
        Initialize HTTP server.

        Args:
            host: Host to bind to (default: 0.0.0.0)
            port: Port to listen on (default: 8080)
            db_check_fn: Function to check database connectivity (optional)
            metrics_fn: Function to generate Prometheus metrics (optional)
            repository_fn: Function that returns OutboxRepository instance (optional)
        """
        self.host: str = host
        self.port: int = port
        self.db_check_fn: Optional[Callable[[], bool]] = db_check_fn
        self.metrics_fn: Optional[Callable[[], str]] = metrics_fn
        self.repository_fn: Optional[Callable[[], Any]] = repository_fn
        self.app: Bottle = Bottle()
        self._setup_routes()
        self._server_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()

    def _setup_routes(self) -> None:
        """Setup HTTP routes."""
        self.app.get("/health")(self._health)
        self.app.get("/ready")(self._ready)
        if self.metrics_fn:
            self.app.get("/metrics")(self._metrics)
        
        # DLQ endpoints
        if self.repository_fn:
            self.app.get("/api/dead-events")(self._list_dead_events)
            self.app.get("/api/dead-events/stats")(self._dead_events_stats)
            self.app.get("/api/dead-events/<event_id:int>")(self._get_dead_event)
            self.app.post("/api/dead-events/<event_id:int>/retry")(self._retry_dead_event)
            self.app.post("/api/dead-events/retry-batch")(self._retry_dead_events_batch)

    def _health(self) -> dict:
        """
        Liveness probe - is process alive?

        Returns:
            JSON response with status
        """
        return {"status": "ok"}

    def _ready(self) -> dict:
        """
        Readiness probe - is worker ready to process events?

        Returns:
            JSON response with status and optional reason
        """
        if self.db_check_fn:
            try:
                is_ready = self.db_check_fn()
                if is_ready:
                    return {"status": "ready"}
                else:
                    response.status = 503
                    return {"status": "not ready", "reason": "database not connected"}
            except Exception as e:
                logger.error("Error checking readiness: {}", e)
                response.status = 503
                return {"status": "not ready", "reason": str(e)}
        
        # If no check function, assume ready
        return {"status": "ready"}

    def _metrics(self) -> str:
        """
        Prometheus metrics endpoint.

        Returns:
            Prometheus metrics in text format
        """
        if not self.metrics_fn:
            response.status = 501
            return "# Metrics not available\n"
        
        try:
            response.content_type = "text/plain; version=0.0.4; charset=utf-8"
            return self.metrics_fn()
        except Exception as e:
            logger.error("Error generating metrics: {}", e)
            response.status = 500
            return f"# Error generating metrics: {e}\n"

    def start(self, daemon: bool = True) -> None:
        """
        Start HTTP server in background thread.

        Args:
            daemon: If True, thread will be daemon (dies with main thread)
        """
        if self._server_thread and self._server_thread.is_alive():
            logger.warning("HTTP server already running")
            return

        def _run_server() -> None:
            try:
                run(
                    self.app,
                    host=self.host,
                    port=self.port,
                    quiet=True,  # Disable Bottle's default logging
                )
            except Exception as e:
                logger.error("HTTP server error: {}", e)

        self._server_thread = threading.Thread(target=_run_server, daemon=daemon)
        self._server_thread.start()
        logger.info("HTTP server started on {}:{} (endpoints: /health, /ready, /metrics)", self.host, self.port)

    def stop(self) -> None:
        """Stop HTTP server."""
        # Bottle doesn't have a clean shutdown, so we just mark it
        # The thread will die when main process exits (if daemon=True)
        self._shutdown_event.set()
        logger.info("HTTP server shutdown requested")

    def is_running(self) -> bool:
        """
        Check if server is running.

        Returns:
            True if server thread is alive
        """
        return self._server_thread is not None and self._server_thread.is_alive()

    def _list_dead_events(self) -> dict:
        """
        List dead events with optional filtering and pagination.

        Query parameters:
            limit: Maximum number of events (default: 100, max: 1000)
            offset: Offset for pagination (default: 0)
            aggregate_type: Filter by aggregate type (optional)
            event_type: Filter by event type (optional)

        Returns:
            JSON response with list of dead events
        """
        if not self.repository_fn:
            response.status = 501
            return {"error": "Repository not available"}

        try:
            repo = self.repository_fn()
            limit = min(int(request.query.get("limit", 100)), 1000)
            offset = int(request.query.get("offset", 0))
            aggregate_type = request.query.get("aggregate_type") or None
            event_type = request.query.get("event_type") or None

            events = repo.fetch_dead_events(
                limit=limit,
                offset=offset,
                aggregate_type=aggregate_type,
                event_type=event_type,
            )

            return {
                "events": [event.to_dict() for event in events],
                "count": len(events),
                "limit": limit,
                "offset": offset,
            }
        except ValueError as e:
            response.status = 400
            return {"error": str(e)}
        except Exception as e:
            logger.error("Error listing dead events: {}", e)
            response.status = 500
            return {"error": "Internal server error"}

    def _dead_events_stats(self) -> dict:
        """
        Get statistics about dead events.

        Query parameters:
            aggregate_type: Filter by aggregate type (optional)
            event_type: Filter by event type (optional)

        Returns:
            JSON response with statistics
        """
        if not self.repository_fn:
            response.status = 501
            return {"error": "Repository not available"}

        try:
            repo = self.repository_fn()
            aggregate_type = request.query.get("aggregate_type") or None
            event_type = request.query.get("event_type") or None

            total = repo.count_dead_events(
                aggregate_type=aggregate_type,
                event_type=event_type,
            )

            return {
                "total": total,
                "aggregate_type": aggregate_type,
                "event_type": event_type,
            }
        except Exception as e:
            logger.error("Error getting dead events stats: {}", e)
            response.status = 500
            return {"error": "Internal server error"}

    def _get_dead_event(self, event_id: int) -> dict:
        """
        Get a single dead event by ID.

        Args:
            event_id: ID of the dead event

        Returns:
            JSON response with event data or error
        """
        if not self.repository_fn:
            response.status = 501
            return {"error": "Repository not available"}

        try:
            repo = self.repository_fn()
            event = repo.get_dead_event(event_id)

            if event:
                return event.to_dict()
            else:
                response.status = 404
                return {"error": f"Dead event {event_id} not found"}
        except ValueError as e:
            response.status = 400
            return {"error": str(e)}
        except Exception as e:
            logger.error("Error getting dead event {}: {}", event_id, e)
            response.status = 500
            return {"error": "Internal server error"}

    def _retry_dead_event(self, event_id: int) -> dict:
        """
        Retry a single dead event (reset to pending).

        Args:
            event_id: ID of the dead event to retry

        Returns:
            JSON response with result
        """
        if not self.repository_fn:
            response.status = 501
            return {"error": "Repository not available"}

        try:
            repo = self.repository_fn()
            success = repo.retry_dead_event(event_id)

            if success:
                return {"status": "success", "message": f"Event {event_id} reset to pending", "event_id": event_id}
            else:
                response.status = 404
                return {"error": f"Dead event {event_id} not found or already processed"}
        except ValueError as e:
            response.status = 400
            return {"error": str(e)}
        except Exception as e:
            logger.error("Error retrying dead event {}: {}", event_id, e)
            response.status = 500
            return {"error": "Internal server error"}

    def _retry_dead_events_batch(self) -> dict:
        """
        Retry multiple dead events (reset to pending).

        Request body (JSON):
            {
                "event_ids": [1, 2, 3, ...]
            }

        Returns:
            JSON response with result
        """
        if not self.repository_fn:
            response.status = 501
            return {"error": "Repository not available"}

        try:
            # Parse JSON body
            try:
                # request.body is a file-like object in Bottle
                body_bytes = request.body.read() if hasattr(request.body, 'read') else request.body
                if isinstance(body_bytes, bytes):
                    body_str = body_bytes.decode('utf-8')
                else:
                    body_str = str(body_bytes)
                data = json.loads(body_str)
            except (json.JSONDecodeError, AttributeError, UnicodeDecodeError) as e:
                response.status = 400
                return {"error": "Invalid JSON in request body"}

            event_ids = data.get("event_ids", [])
            if not isinstance(event_ids, list) or not event_ids:
                response.status = 400
                return {"error": "event_ids must be a non-empty list"}

            repo = self.repository_fn()
            count = repo.retry_dead_events_batch(event_ids)

            return {
                "status": "success",
                "message": f"{count} event(s) reset to pending",
                "requested": len(event_ids),
                "processed": count,
            }
        except ValueError as e:
            response.status = 400
            return {"error": str(e)}
        except Exception as e:
            logger.error("Error retrying dead events batch: {}", e)
            response.status = 500
            return {"error": "Internal server error"}

