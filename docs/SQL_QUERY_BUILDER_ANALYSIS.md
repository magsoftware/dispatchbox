# Analiza: Zastąpienie Raw SQL Query Builderem

## Obecny stan

Mamy **4 główne zapytania SQL**:
1. `SELECT ... FOR UPDATE SKIP LOCKED` - kluczowe dla outbox pattern
2. `UPDATE ... SET status='done'` - proste
3. `UPDATE ... SET status=CASE ...` - z CASE statement
4. `SELECT status FROM ...` - proste

## Opcje do rozważenia

### 1. SQLAlchemy Core (Query Builder)

**Zalety:**
- ✅ Wspiera `FOR UPDATE SKIP LOCKED` (`.with_for_update(skip_locked=True)`)
- ✅ Type safety z Column definitions
- ✅ Czytelny, Pythonic API
- ✅ Dobrze udokumentowany
- ✅ Wspiera CASE statements
- ✅ Nie wymaga pełnego ORM (można użyć tylko Core)

**Wady:**
- ❌ Dodatkowa zależność (~2MB)
- ❌ Nieco więcej boilerplate (definicje tabel)
- ❌ Może być overkill dla prostych zapytań

**Przykład:**
```python
from sqlalchemy import create_engine, Table, Column, Integer, String, DateTime, JSON
from sqlalchemy.sql import select, update, case

# Definicja tabeli (raz)
outbox_event = Table(
    'outbox_event',
    metadata,
    Column('id', Integer, primary_key=True),
    Column('status', String),
    Column('attempts', Integer),
    # ...
)

# Query
query = select(outbox_event).where(
    outbox_event.c.status.in_(['pending', 'retry']),
    outbox_event.c.next_run_at <= func.now()
).order_by(
    outbox_event.c.id
).with_for_update(skip_locked=True).limit(batch_size)
```

---

### 2. Pypika (Pure Python Query Builder)

**Zalety:**
- ✅ Pure Python, bez zależności od DB driver
- ✅ Czytelny API
- ✅ Wspiera CASE statements
- ✅ Lżejszy niż SQLAlchemy

**Wady:**
- ❌ **NIE wspiera `FOR UPDATE SKIP LOCKED` natywnie** (trzeba dodać raw SQL)
- ❌ Mniej popularny, mniejsza społeczność
- ❌ Dodatkowa zależność

**Przykład:**
```python
from pypika import Query, Table, functions as fn

outbox_event = Table('outbox_event')

query = Query.from_(outbox_event).select('*').where(
    outbox_event.status.isin(['pending', 'retry']),
    outbox_event.next_run_at <= fn.Now()
).orderby(outbox_event.id).limit(batch_size)

# FOR UPDATE SKIP LOCKED trzeba dodać ręcznie:
sql = str(query) + " FOR UPDATE SKIP LOCKED"
```

---

### 3. Records (Simple wrapper)

**Zalety:**
- ✅ Bardzo prosty API
- ✅ Mały footprint

**Wady:**
- ❌ **NIE wspiera query builder** - nadal raw SQL
- ❌ Nie rozwiązuje problemu

---

### 4. Zostawić Raw SQL (Obecne rozwiązanie)

**Zalety:**
- ✅ **Zero dodatkowych zależności**
- ✅ Pełna kontrola nad SQL
- ✅ `FOR UPDATE SKIP LOCKED` działa out-of-the-box
- ✅ Proste, czytelne zapytania
- ✅ Łatwe do debugowania (można skopiować SQL do psql)
- ✅ Performance - bez overhead query buildera
- ✅ Mały footprint projektu

**Wady:**
- ❌ Brak type safety na poziomie SQL
- ❌ Trzeba ręcznie zarządzać parametrami
- ❌ Mniej "nowoczesne"

---

## Rekomendacja: **ZOSTAWIĆ RAW SQL** (z małymi ulepszeniami)

### Dlaczego?

1. **FOR UPDATE SKIP LOCKED jest kluczowe** - większość query builderów nie wspiera tego dobrze
2. **Mamy tylko 4 proste zapytania** - nie potrzebujemy pełnego ORM
3. **Performance matters** - to jest worker, każdy overhead się liczy
4. **Raw SQL jest czytelny** - nasze zapytania są proste i zrozumiałe
5. **Zero dependencies** - mniejszy footprint, łatwiejsze deployment

### Możliwe ulepszenia (bez query buildera):

#### 1. Wyciągnąć SQL do stałych/konstant

```python
class OutboxRepository:
    # SQL queries as class constants
    FETCH_PENDING_SQL = """
        SELECT id, aggregate_type, aggregate_id, event_type, payload, 
               status, attempts, next_run_at, created_at
        FROM outbox_event
        WHERE status IN ('pending','retry')
          AND next_run_at <= now()
        ORDER BY id
        FOR UPDATE SKIP LOCKED
        LIMIT %s;
    """
    
    MARK_SUCCESS_SQL = """
        UPDATE outbox_event
        SET status = 'done',
            attempts = attempts + 1
        WHERE id = %s;
    """
    
    def fetch_pending(self, batch_size: int) -> List[OutboxEvent]:
        # ...
        cur.execute(self.FETCH_PENDING_SQL, (batch_size,))
```

**Korzyści:**
- Łatwiejsze testowanie (można mockować SQL)
- Łatwiejsze refaktoring
- SQL w jednym miejscu

#### 2. Użyć f-strings z walidacją (dla dynamicznych części)

```python
def fetch_pending(self, batch_size: int, statuses: List[str] = None) -> List[OutboxEvent]:
    statuses = statuses or ['pending', 'retry']
    # Walidacja - zapobiega SQL injection
    valid_statuses = {'pending', 'retry', 'done', 'dead'}
    if not all(s in valid_statuses for s in statuses):
        raise ValueError(f"Invalid status: {statuses}")
    
    placeholders = ','.join(['%s'] * len(statuses))
    sql = f"""
        SELECT ... 
        WHERE status IN ({placeholders})
        ...
    """
    cur.execute(sql, tuple(statuses) + (batch_size,))
```

#### 3. Helper metody dla częstych wzorców

```python
def _build_update_status_query(
    self, 
    event_id: int, 
    new_status: str,
    increment_attempts: bool = True
) -> tuple[str, tuple]:
    """Build UPDATE query for status change."""
    if increment_attempts:
        sql = """
            UPDATE outbox_event
            SET status = %s,
                attempts = attempts + 1
            WHERE id = %s;
        """
        params = (new_status, event_id)
    else:
        sql = """
            UPDATE outbox_event
            SET status = %s
            WHERE id = %s;
        """
        params = (new_status, event_id)
    return sql, params
```

---

## Alternatywa: SQLAlchemy Core (jeśli chcemy query builder)

Jeśli jednak zdecydujemy się na query builder, **SQLAlchemy Core** jest najlepszym wyborem:

### Implementacja z SQLAlchemy Core:

```python
from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, DateTime, JSON, func, case
from sqlalchemy.sql import select, update

class OutboxRepository:
    def __init__(self, dsn: str, ...):
        self.engine = create_engine(dsn)
        self.metadata = MetaData()
        
        # Definicja tabeli
        self.outbox_event = Table(
            'outbox_event',
            self.metadata,
            Column('id', Integer, primary_key=True),
            Column('aggregate_type', String),
            Column('aggregate_id', String),
            Column('event_type', String),
            Column('payload', JSON),
            Column('status', String),
            Column('attempts', Integer),
            Column('next_run_at', DateTime(timezone=True)),
            Column('created_at', DateTime(timezone=True)),
        )
    
    def fetch_pending(self, batch_size: int) -> List[OutboxEvent]:
        query = select(self.outbox_event).where(
            self.outbox_event.c.status.in_(['pending', 'retry']),
            self.outbox_event.c.next_run_at <= func.now()
        ).order_by(
            self.outbox_event.c.id
        ).with_for_update(skip_locked=True).limit(batch_size)
        
        with self.engine.connect() as conn:
            result = conn.execute(query)
            rows = result.fetchall()
            return [OutboxEvent.from_dict(dict(row._mapping)) for row in rows]
    
    def mark_retry(self, event_id: int) -> None:
        new_status = case(
            (self.outbox_event.c.attempts + 1 >= self.max_attempts, 'dead'),
            else_='retry'
        )
        new_next_run_at = case(
            (self.outbox_event.c.attempts + 1 >= self.max_attempts, 
             self.outbox_event.c.next_run_at),
            else_=func.now() + timedelta(seconds=self.retry_backoff)
        )
        
        query = update(self.outbox_event).where(
            self.outbox_event.c.id == event_id
        ).values(
            status=new_status,
            attempts=self.outbox_event.c.attempts + 1,
            next_run_at=new_next_run_at
        )
        
        with self.engine.connect() as conn:
            conn.execute(query)
            conn.commit()
```

**Koszt:**
- Dodatkowa zależność: `sqlalchemy>=2.0` (~2MB)
- Więcej kodu (definicje tabel)
- Trzeba przepisać wszystkie zapytania

---

## Moja rekomendacja

### **ZOSTAWIĆ RAW SQL** + małe ulepszenia:

1. ✅ Wyciągnąć SQL do stałych klasowych
2. ✅ Dodać helper metody dla częstych wzorców
3. ✅ Dodać walidację parametrów
4. ✅ Może dodać type hints dla SQL (typu `SQLQuery = str`)

**Dlaczego:**
- Mamy tylko 4 proste zapytania
- `FOR UPDATE SKIP LOCKED` działa perfekcyjnie
- Zero dependencies
- Performance - bez overhead
- Czytelność - SQL jest prosty i zrozumiały

**Kiedy rozważyć SQLAlchemy Core:**
- Jeśli planujemy dodać więcej zapytań (np. dla DLQ)
- Jeśli potrzebujemy migracji schematu (Alembic)
- Jeśli chcemy type safety na poziomie SQL
- Jeśli zespół preferuje query buildery

---

## Podsumowanie

| Opcja | FOR UPDATE SKIP LOCKED | Dependencies | Complexity | Performance |
|-------|------------------------|--------------|------------|-------------|
| **Raw SQL** | ✅ Pełne wsparcie | ✅ Zero | ✅ Niska | ✅ Najlepsza |
| SQLAlchemy Core | ✅ Pełne wsparcie | ❌ ~2MB | ⚠️ Średnia | ⚠️ Dobra |
| Pypika | ⚠️ Trzeba dodać ręcznie | ❌ ~500KB | ⚠️ Średnia | ⚠️ Dobra |

**Verdict:** Dla outbox pattern worker, raw SQL jest najlepszym wyborem. Query buildery dodają complexity bez znaczących korzyści w tym przypadku.

