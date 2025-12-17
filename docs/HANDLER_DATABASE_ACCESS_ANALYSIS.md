# Handler Database Access - Architectural Analysis

## Problem Statement

Event handlers currently receive only the event `payload` and have no access to the database. If handlers need to perform database operations (e.g., read related data, write audit logs, update related entities), we need to decide on the best architectural approach.

## Current Architecture

- **Worker processes**: Each has one dedicated long-lived database connection
- **Handler execution**: Handlers run in separate threads within the worker process
- **Handler database access**: **Handlers do NOT have access to the database** - they only receive the event `payload`
- **Worker database operations**: Worker uses its connection for:
  - Fetching events (`fetch_pending`)
  - Marking events as successful (`mark_success`) - **after** handler completes
  - Marking events for retry (`mark_retry`) - **after** handler fails
- **Transaction isolation**: Worker's connection uses manual transactions (`autocommit = False`)
- **Concurrency**: Multiple handlers run in parallel threads, but they are **completely isolated** - they have no shared state, no database access, and no access to worker's connection

## Option 1: Handler Creates Own Connection

### Implementation
```python
def my_handler(payload: Dict[str, Any]) -> None:
    repo = OutboxRepository(dsn, connect_timeout=2, query_timeout=5)
    try:
        # Use repo for database operations
        data = repo.fetch_something(...)
    finally:
        repo.close()
```

### Pros
- ✅ **Simple**: No framework changes needed
- ✅ **Isolation**: Each handler has independent connection and transactions
- ✅ **No shared state**: No risk of transaction conflicts
- ✅ **Flexible**: Handler controls its own connection lifecycle
- ✅ **Easy to test**: Handler can be tested independently

### Cons
- ❌ **Connection overhead**: Creating/closing connections is expensive
- ❌ **Resource waste**: Many short-lived connections under high load
- ❌ **No connection reuse**: Can't leverage connection pooling benefits
- ❌ **DSN management**: Handler needs access to DSN (security concern)
- ❌ **Timeout configuration**: Each handler must configure timeouts
- ❌ **Connection limits**: PostgreSQL has max_connections limit

### Use Case
Best for: **Occasional database access** in handlers, low-frequency operations

---

## Option 2: Global Connection Pool (Per Worker Process)

### Implementation
```python
# In worker.py or config
from psycopg2 import pool

class OutboxWorker:
    def __init__(self, ...):
        # Create connection pool per worker process
        self.db_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            dsn=dsn,
            connect_timeout=2,
        )
    
    def process_event(self, event: OutboxEvent) -> None:
        handler = self.handlers.get(event.event_type)
        # Pass pool to handler
        handler(payload, db_pool=self.db_pool)

# Handler
def my_handler(payload: Dict[str, Any], db_pool) -> None:
    conn = db_pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT ...")
            conn.commit()
    finally:
        db_pool.putconn(conn)
```

### Pros
- ✅ **Efficient**: Connection reuse reduces overhead
- ✅ **Scalable**: Pool size can be tuned per worker
- ✅ **Resource management**: Limits concurrent connections
- ✅ **Performance**: Faster than creating new connections
- ✅ **Standard pattern**: Well-established connection pooling pattern

### Cons
- ❌ **Complexity**: Requires pool management and lifecycle
- ❌ **Shared resource**: Potential for connection leaks if not properly managed
- ❌ **Thread safety**: Must ensure pool is thread-safe (psycopg2.pool is)
- ❌ **Pool exhaustion**: Can run out of connections if handlers hold them too long
- ❌ **Transaction isolation**: Handlers share pool but have separate connections
- ❌ **Framework changes**: Requires modifying worker and handler signatures

### Use Case
Best for: **Frequent database access** in handlers, high-throughput scenarios

---

## Option 3: Pass Repository Factory to Handlers

### Implementation
```python
# Handler signature change
def my_handler(payload: Dict[str, Any], get_repository: Callable[[], OutboxRepository]) -> None:
    repo = get_repository()
    try:
        # Use repo
        data = repo.fetch_something(...)
    finally:
        repo.close()

# Worker passes factory
def process_event(self, event: OutboxEvent) -> None:
    handler = self.handlers.get(event.event_type)
    handler(payload, get_repository=self._get_repository)

def _get_repository(self) -> OutboxRepository:
    return OutboxRepository(self.dsn, connect_timeout=2, query_timeout=5)
```

### Pros
- ✅ **Abstraction**: Handlers use repository pattern, not raw connections
- ✅ **Flexible**: Can switch between pool and new connections
- ✅ **Testable**: Easy to mock repository factory
- ✅ **Consistent API**: Same repository interface as worker uses
- ✅ **No DSN exposure**: Handler doesn't need DSN directly

### Cons
- ❌ **Still creates connections**: If factory creates new connections, same overhead as Option 1
- ❌ **Signature change**: All handlers must be updated
- ❌ **Lifecycle management**: Handler must remember to close repository
- ❌ **Potential leaks**: If handler forgets to close, connection leaks

### Use Case
Best for: **When you want repository abstraction** but don't want to commit to pooling yet

---

## Option 4: Hybrid - Repository Factory with Optional Pooling

### Implementation
```python
class OutboxWorker:
    def __init__(self, ..., use_connection_pool: bool = False):
        self.use_pool = use_connection_pool
        if use_connection_pool:
            self.db_pool = psycopg2.pool.ThreadedConnectionPool(...)
        else:
            self.dsn = dsn
    
    def _get_repository(self) -> OutboxRepository:
        if self.use_pool:
            # Create repository from pooled connection
            conn = self.db_pool.getconn()
            repo = OutboxRepository.from_connection(conn)
            repo._pool = self.db_pool  # Store pool for cleanup
            return repo
        else:
            return OutboxRepository(self.dsn, ...)
    
    def process_event(self, event: OutboxEvent) -> None:
        handler = self.handlers.get(event.event_type)
        handler(payload, get_repository=self._get_repository)
```

### Pros
- ✅ **Flexible**: Can choose pooling or per-request connections
- ✅ **Configurable**: Per-worker configuration
- ✅ **Best of both worlds**: Simple for low-load, efficient for high-load
- ✅ **Migration path**: Can start without pool, add later

### Cons
- ❌ **Most complex**: Requires supporting both modes
- ❌ **Testing complexity**: Must test both paths
- ❌ **Repository changes**: Need `from_connection()` method

### Use Case
Best for: **Production systems** where you want flexibility and optimization options

---

## Option 5: Shared Repository Instance (NOT RECOMMENDED)

### Implementation
```python
# Pass worker's repository to handler
handler(payload, repository=self.repository)
```

### Pros
- ✅ **No overhead**: Reuses existing connection
- ✅ **Simple**: No new infrastructure

### Cons
- ❌ **Transaction conflicts**: Multiple handlers sharing connection = chaos
- ❌ **Thread safety issues**: Concurrent handlers can interfere
- ❌ **Transaction boundaries**: Can't have independent transactions
- ❌ **Deadlock risk**: High risk of deadlocks and race conditions
- ❌ **Violates isolation**: Handler operations affect worker's transaction state
- ❌ **Worker interference**: Handler operations could interfere with worker's `mark_success`/`mark_retry` operations

### Verdict
**DO NOT USE** - This is a recipe for disaster. Database connections are not thread-safe for concurrent use. Additionally, the worker needs exclusive access to its connection for managing event lifecycle (marking success/retry).

### Current Reality
**This option is NOT currently implemented** - handlers have no database access at all. The worker's connection is used exclusively by the worker thread for event lifecycle management, not by handler threads.

---

## Recommendation: Option 2 (Connection Pool) with Option 3 (Repository Factory)

### Recommended Architecture

**Phase 1: Add Repository Factory (Immediate)**
- Change handler signature to accept `get_repository: Callable[[], OutboxRepository]`
- Factory creates new connections (simple, works immediately)
- Handlers use repository pattern for consistency

**Phase 2: Add Connection Pooling (When Needed)**
- Add optional connection pool to `OutboxWorker`
- Factory can use pool when available
- Backward compatible - handlers don't need changes

### Implementation Details

```python
# 1. Update handler signature (backward compatible with default)
def my_handler(
    payload: Dict[str, Any],
    get_repository: Optional[Callable[[], OutboxRepository]] = None
) -> None:
    if get_repository:
        repo = get_repository()
        try:
            # Database operations
            pass
        finally:
            repo.close()

# 2. Worker passes factory
class OutboxWorker:
    def __init__(self, ..., use_pool: bool = False):
        self.use_pool = use_pool
        if use_pool:
            self.db_pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=2,
                maxconn=min(10, max_parallel),  # Match thread pool size
                dsn=dsn,
            )
        self.dsn = dsn
    
    def _get_repository(self) -> OutboxRepository:
        if self.use_pool:
            conn = self.db_pool.getconn()
            # Wrap pooled connection in repository
            return OutboxRepository.from_connection(conn, pool=self.db_pool)
        return OutboxRepository(self.dsn, connect_timeout=2, query_timeout=5)
    
    def process_event(self, event: OutboxEvent) -> None:
        handler = self.handlers.get(event.event_type)
        # Pass factory only if handler accepts it
        if handler and self._handler_needs_db(handler):
            handler(payload, get_repository=self._get_repository)
        else:
            handler(payload)
```

### Why This Approach?

1. **Repository Factory Pattern**:
   - Handlers don't need DSN
   - Consistent API with worker's repository
   - Easy to test and mock
   - Abstraction layer for future changes

2. **Optional Connection Pooling**:
   - Start simple (new connections)
   - Add pooling when performance matters
   - Configurable per worker
   - No breaking changes to handlers

3. **Best Practices**:
   - Each handler gets its own connection (isolation)
   - Pool prevents connection exhaustion
   - Repository pattern maintains consistency
   - Thread-safe (psycopg2.pool is thread-safe)

4. **Migration Path**:
   - Existing handlers continue to work (backward compatible)
   - New handlers can opt-in to database access
   - Can enable pooling without handler changes

### Configuration

```python
# In supervisor.py or config
worker = OutboxWorker(
    batch_size=10,
    poll_interval=1.0,
    max_parallel=10,
    repository=repository,
    use_connection_pool=True,  # Enable pooling
    pool_min_connections=2,
    pool_max_connections=10,
)
```

### Performance Considerations

- **Pool size**: Should match or be slightly less than `max_parallel` threads
- **Connection timeout**: Keep short (2-5s) for handlers
- **Query timeout**: Handler-specific (5-10s typically)
- **Pool exhaustion**: Monitor and alert if handlers hold connections too long

### Security Considerations

- **DSN not exposed**: Handlers never see DSN directly
- **Connection limits**: Pool prevents connection exhaustion attacks
- **Isolation**: Each handler's operations are isolated

---

## Alternative: Handler-Specific Connection Strategy

If different handlers have different database access patterns, consider:

```python
# Handler metadata
HANDLERS = {
    "order.created": {
        "handler": send_email,
        "needs_db": False,
    },
    "order.audit": {
        "handler": audit_order,
        "needs_db": True,
        "use_pool": True,  # This handler benefits from pooling
    },
    "order.report": {
        "handler": generate_report,
        "needs_db": True,
        "use_pool": False,  # Long-running, use dedicated connection
    },
}
```

This allows fine-grained control per handler type.

---

## Conclusion

**Recommended approach**: **Repository Factory with Optional Connection Pooling**

- Start with factory pattern (simple, flexible)
- Add pooling when performance requires it
- Maintain backward compatibility
- Follow established patterns (repository, factory, pool)
- Balance simplicity and performance

This provides the best balance of:
- ✅ Simplicity (for simple handlers)
- ✅ Performance (when needed via pooling)
- ✅ Flexibility (can choose per handler)
- ✅ Maintainability (consistent patterns)
- ✅ Testability (easy to mock)

