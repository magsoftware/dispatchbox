# Dispatchbox

Dispatchbox is a high-performance outbox pattern worker for PostgreSQL. It processes events from an outbox table using multi-process and multi-threaded architecture with `FOR UPDATE SKIP LOCKED` for efficient parallel processing.

## Features

- Multi-process architecture for horizontal scaling
- Multi-threaded processing within each process
- PostgreSQL `FOR UPDATE SKIP LOCKED` for safe concurrent access
- Automatic retry mechanism with configurable backoff and max attempts
- Dead Letter Queue (DLQ) - events exceeding max attempts are marked as 'dead'
- Event status tracking (pending, retry, done, dead)
- Connection health check with automatic reconnection
- Configurable timeouts (connection and query)
- Graceful shutdown with signal handling (SIGTERM/SIGINT)
- Structured logging with loguru and worker identification
- HTTP server for health checks, metrics, and API endpoints
- Configurable batch size and polling interval

## Requirements

- Python 3.8+
- PostgreSQL 12+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

## Installation

### 1. Install uv (if not already installed)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 2. Clone and setup the project

```bash
git clone <repository-url>
cd outbox
```

### 3. Install dependencies

```bash
# Install project and dev dependencies
uv pip install -e ".[dev]"
```

## Database Setup

### 1. Create PostgreSQL database

```bash
createdb outbox
# Or using psql:
psql -U postgres -c "CREATE DATABASE outbox;"
```

### 2. Create schema

```bash
psql -U postgres -d outbox -f sql/schema.sql
```

Or manually:

```bash
PGPASSWORD=postgres psql -h localhost -p 5432 -U postgres -d outbox -f sql/schema.sql
```

### 3. Load sample data

You can use one of the provided scripts to generate sample data:

**Option A: Generate SQL file (recommended for small datasets)**

```bash
python scripts/generate_outbox_sql.py | psql -U postgres -d outbox
```

**Option B: Direct database insertion (for large datasets)**

```bash
# Edit scripts/generate_outbox_db.py to configure DSN and NUM_RECORDS
python scripts/generate_outbox_db.py
```

**Option C: Use provided sample data**

```bash
psql -U postgres -d outbox -f sql/insert_outbox.sql
```

## Usage

### Basic usage

```bash
dispatchbox --dsn "host=localhost port=5432 dbname=outbox user=postgres password=postgres"
```

### With custom configuration

```bash
dispatchbox \
  --dsn "host=localhost port=5432 dbname=outbox user=postgres password=postgres" \
  --processes 4 \
  --batch-size 20 \
  --poll-interval 0.5 \
  --log-level DEBUG \
  --http-port 8080
```

### Disable HTTP server

```bash
dispatchbox \
  --dsn "host=localhost port=5432 dbname=outbox user=postgres password=postgres" \
  --disable-http
```

### Using Python module

```bash
python -m dispatchbox.cli \
  --dsn "host=localhost port=5432 dbname=outbox user=postgres password=postgres"
```

### Command-line options

- `--dsn` (required): PostgreSQL connection string (libpq style)
- `--processes`: Number of worker processes (default: 1)
- `--batch-size`: Events to fetch per batch (default: 10)
- `--poll-interval`: Seconds to sleep when no work (default: 1.0)
- `--log-level`: Logging level - DEBUG, INFO, WARNING, ERROR, CRITICAL (default: INFO)
- `--http-host`: HTTP server host (default: 0.0.0.0)
- `--http-port`: HTTP server port for health checks and metrics (default: 8080)
- `--disable-http`: Disable HTTP server

### Configuration defaults

- `max_attempts`: Maximum retry attempts before marking event as dead (default: 5)
- `retry_backoff_seconds`: Seconds to wait before retrying failed events (default: 30)
- `connect_timeout`: Database connection timeout in seconds (default: 10)
- `query_timeout`: Database query timeout in seconds (default: 30)
- `max_parallel`: Maximum parallel threads per worker process (default: 10)
- `http_host`: HTTP server host (default: 0.0.0.0)
- `http_port`: HTTP server port (default: 8080)

## Running Tests

### Run all tests

```bash
uv run pytest
```

### Run with coverage

```bash
uv run pytest --cov=src/dispatchbox --cov-report=term-missing
```

### Run specific test file

```bash
uv run pytest tests/test_models.py
```

### Run specific test

```bash
uv run pytest tests/test_models.py::test_from_dict_with_all_fields
```

### Verbose output

```bash
uv run pytest -v
```

## Project Structure

```
outbox/
├── src/
│   └── dispatchbox/           # Main package
│       ├── __init__.py
│       ├── cli.py             # Command-line interface
│       ├── config.py           # Configuration constants
│       ├── handlers.py        # Event handlers
│       ├── http_server.py     # HTTP server for health checks and API
│       ├── models.py          # Data models (OutboxEvent)
│       ├── repository.py      # Database repository
│       ├── supervisor.py      # Process supervision
│       └── worker.py          # Worker implementation
├── tests/                     # Test suite
│   ├── conftest.py
│   ├── test_handlers.py
│   ├── test_http_server.py
│   ├── test_models.py
│   ├── test_repository.py
│   ├── test_supervisor.py
│   └── test_worker.py
├── scripts/                   # Utility scripts
│   ├── generate_outbox_db.py
│   └── generate_outbox_sql.py
├── sql/                       # SQL scripts
│   ├── schema.sql
│   └── insert_outbox.sql
├── docs/                      # Documentation
│   ├── DEAD_LETTER_QUEUE.md   # Dead Letter Queue documentation
│   ├── HTTP_FRAMEWORK_ANALYSIS.md  # HTTP framework analysis
│   ├── IMPROVEMENTS.md        # Improvement proposals
│   └── SQL_QUERY_BUILDER_ANALYSIS.md  # SQL query builder analysis
├── pyproject.toml             # Project configuration
├── uv.lock                    # Dependency lock file
└── README.md                  # This file
```

## How It Works

1. **Multiple worker processes** are started, each with its own database connection
2. Each worker process has a unique name (e.g., `worker-00-pid12345`) for logging identification
3. Each process runs a **polling loop** that fetches pending/retry events
4. Events are fetched using `FOR UPDATE SKIP LOCKED` to prevent conflicts
5. **Connection health check** is performed before each operation with automatic reconnection
6. Each event is processed in a **separate thread** using ThreadPoolExecutor
7. On success, events are marked as `done`
8. On failure, events are marked as `retry` with updated `next_run_at` and incremented attempts
9. After `max_attempts` (default: 5), events are marked as `dead` and moved to Dead Letter Queue
10. Dead events are logged with warnings and can be reviewed/manually retried (see [Dead Letter Queue docs](docs/DEAD_LETTER_QUEUE.md))

## Dead Letter Queue

Events that exceed the maximum retry attempts are marked as `dead` and stored in the database. These events are not automatically processed anymore, allowing you to:

- Review problematic events
- Analyze failure patterns
- Manually retry after fixing underlying issues

See [Dead Letter Queue documentation](docs/DEAD_LETTER_QUEUE.md) for details on current implementation and future enhancements.

## HTTP Endpoints

Dispatchbox includes an HTTP server (enabled by default) that provides:

### Health Checks

- **`GET /health`** - Liveness probe
  - Returns: `{"status": "ok"}`
  - Status: `200 OK`
  - Use for: Kubernetes liveness probes

- **`GET /ready`** - Readiness probe
  - Returns: `{"status": "ready"}` or `{"status": "not ready", "reason": "..."}`
  - Status: `200 OK` (ready) or `503 Service Unavailable` (not ready)
  - Checks: Database connectivity
  - Use for: Kubernetes readiness probes

### Metrics

- **`GET /metrics`** - Prometheus metrics endpoint
  - Returns: Prometheus metrics in text format
  - Content-Type: `text/plain; version=0.0.4; charset=utf-8`
  - Status: `200 OK` (if metrics available) or `501 Not Implemented` (if not configured)
  - Use for: Prometheus scraping

### Configuration

The HTTP server runs in a background thread and doesn't block worker processes. It can be:
- Configured via `--http-host` and `--http-port` CLI options
- Disabled with `--disable-http` flag
- Used for Kubernetes health checks and monitoring

## Event Handlers

Default handlers are defined in `src/dispatchbox/handlers.py`. You can extend this by:

1. Adding new handler functions
2. Registering them in the `HANDLERS` dictionary
3. Using custom handlers when initializing `OutboxWorker`
