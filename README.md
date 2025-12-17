# Dispatchbox

Dispatchbox is a high-performance outbox pattern worker for PostgreSQL. It processes events from an outbox table using multi-process and multi-threaded architecture with `FOR UPDATE SKIP LOCKED` for efficient parallel processing.

## Features

- Multi-process architecture for horizontal scaling
- Multi-threaded processing within each process
- PostgreSQL `FOR UPDATE SKIP LOCKED` for safe concurrent access
- Automatic retry mechanism with configurable backoff
- Event status tracking (pending, retry, done, dead)
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
  --log-level DEBUG
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
│   └── dispatchbox/      # Main package
│       ├── cli.py        # Command-line interface
│       ├── config.py     # Configuration constants
│       ├── handlers.py   # Event handlers
│       ├── models.py     # Data models (OutboxEvent)
│       ├── repository.py # Database repository
│       ├── supervisor.py # Process supervision
│       └── worker.py     # Worker implementation
├── tests/                # Test suite
├── scripts/              # Utility scripts
│   ├── generate_outbox_db.py
│   └── generate_outbox_sql.py
├── sql/                  # SQL scripts
│   ├── schema.sql
│   └── insert_outbox.sql
└── docs/                 # Documentation
    └── plans/            # Development plans
```

## How It Works

1. **Multiple worker processes** are started, each with its own database connection
2. Each process runs a **polling loop** that fetches pending/retry events
3. Events are fetched using `FOR UPDATE SKIP LOCKED` to prevent conflicts
4. Each event is processed in a **separate thread** using ThreadPoolExecutor
5. On success, events are marked as `done`
6. On failure, events are marked as `retry` with updated `next_run_at`
7. After max attempts, events are marked as `dead`

## Event Handlers

Default handlers are defined in `src/dispatchbox/handlers.py`. You can extend this by:

1. Adding new handler functions
2. Registering them in the `HANDLERS` dictionary
3. Using custom handlers when initializing `OutboxWorker`
