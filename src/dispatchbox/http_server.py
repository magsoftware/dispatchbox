#!/usr/bin/env python3
"""HTTP server for health checks, metrics, and API endpoints."""

import threading
from typing import Optional, Callable
from bottle import Bottle, run, response, request
from loguru import logger


class HttpServer:
    """HTTP server for health checks, metrics, and API endpoints."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        db_check_fn: Optional[Callable[[], bool]] = None,
        metrics_fn: Optional[Callable[[], str]] = None,
    ) -> None:
        """
        Initialize HTTP server.

        Args:
            host: Host to bind to (default: 0.0.0.0)
            port: Port to listen on (default: 8080)
            db_check_fn: Function to check database connectivity (optional)
            metrics_fn: Function to generate Prometheus metrics (optional)
        """
        self.host: str = host
        self.port: int = port
        self.db_check_fn: Optional[Callable[[], bool]] = db_check_fn
        self.metrics_fn: Optional[Callable[[], str]] = metrics_fn
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

