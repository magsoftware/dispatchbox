# Plan testów unitowych dla aplikacji outbox

## Struktura katalogów testów

Proponowana struktura:

```
outbox/
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # Wspólne fixtures i konfiguracja
│   ├── test_models.py           # Testy dla OutboxEvent
│   ├── test_repository.py       # Testy dla OutboxRepository
│   ├── test_worker.py           # Testy dla OutboxWorker
│   ├── test_handlers.py         # Testy dla handlerów
│   └── fixtures/                # Opcjonalnie: dane testowe
│       └── sample_events.py
```

## Konfiguracja pytest

### pyproject.toml - sekcja [tool.pytest.ini_options]

- `testpaths = ["tests"]` - katalog z testami
- `python_files = ["test_*.py"]` - wzorzec nazw plików testowych
- `python_classes = ["Test*"]` - wzorzec nazw klas testowych
- `python_functions = ["test_*"]` - wzorzec nazw funkcji testowych
- `addopts = "-v --tb=short"` - opcje domyślne (verbose, krótkie traceback)
- Opcjonalnie: `--cov=src/outbox --cov-report=term-missing` dla coverage

### Zależności testowe

Dodać do `[project.optional-dependencies]` lub `[tool.uv.dev-dependencies]`:
- `pytest>=7.0.0`
- `pytest-mock>=3.10.0` - dla mockowania
- `pytest-cov>=4.0.0` - opcjonalnie dla coverage

## Zakres testów

### 1. tests/test_models.py - Testy dla OutboxEvent

**Testy dla `from_dict()`:**
- Tworzenie OutboxEvent z pełnym dict (wszystkie pola)
- Tworzenie z minimalnym dict (tylko wymagane pola)
- Błąd gdy brakuje `next_run_at` (ValueError)
- Obsługa opcjonalnych pól (`id`, `created_at`)
- Konwersja typów (datetime z stringa jeśli potrzeba)
- Walidacja statusu (tylko dozwolone wartości)

**Testy dla `to_dict()`:**
- Konwersja pełnego obiektu do dict
- Konwersja obiektu bez opcjonalnych pól
- Sprawdzenie że wszystkie pola są obecne
- Sprawdzenie typów wartości

**Testy integracyjne:**
- Round-trip: `from_dict()` -> `to_dict()` -> `from_dict()`

### 2. tests/test_repository.py - Testy dla OutboxRepository

**Mockowanie:**
- Mock `psycopg2.connect()` i połączenia
- Mock cursor i `RealDictCursor`
- Mock `fetchall()`, `execute()`, `commit()`

**Testy dla `__init__()`:**
- Inicjalizacja z DSN
- Ustawienie `retry_backoff_seconds`
- Utworzenie połączenia do bazy

**Testy dla `fetch_pending()`:**
- Zwraca listę OutboxEvent z wyników bazy
- Prawidłowe wywołanie SQL z parametrami
- Obsługa pustego wyniku (pusta lista)
- Konwersja wyników do OutboxEvent
- Wywołanie `commit()` po fetch

**Testy dla `mark_success()`:**
- Wywołanie UPDATE z poprawnym event_id
- Wywołanie `commit()`
- Sprawdzenie SQL query

**Testy dla `mark_retry()`:**
- Wywołanie UPDATE z poprawnym event_id i next_run_at
- Obliczenie `next_run_at` z retry_backoff
- Wywołanie `commit()`
- Sprawdzenie SQL query

**Testy dla context manager:**
- `__enter__()` zwraca self
- `__exit__()` wywołuje `close()`
- `close()` zamyka połączenie

**Testy błędów:**
- Obsługa błędów połączenia
- Obsługa błędów SQL

### 3. tests/test_worker.py - Testy dla OutboxWorker

**Mockowanie:**
- Mock `OutboxRepository`
- Mock `ThreadPoolExecutor`
- Mock handlers
- Mock `time.sleep()` (dla run_loop)

**Testy dla `__init__()`:**
- Inicjalizacja z wymaganymi parametrami
- Błąd gdy `repository` jest None (ValueError)
- Ustawienie domyślnych handlers (HANDLERS)
- Ustawienie custom handlers
- Utworzenie ThreadPoolExecutor

**Testy dla `process_event()`:**
- Wywołanie handlera z poprawnym payload
- Wywołanie handlera z poprawnym event_type
- Błąd gdy brak handlera (HandlerNotFoundError)
- Obsługa wyjątków z handlera

**Testy dla `run_loop()`:**
- Pobranie batch z repository
- Przetworzenie batch przez executor
- Wywołanie `mark_success()` po sukcesie
- Wywołanie `mark_retry()` po błędzie
- Pominięcie eventu bez ID
- Sleep gdy brak batch
- Zatrzymanie gdy `stop_event` jest ustawione
- Obsługa wielu eventów w batch
- Obsługa równoległego przetwarzania

**Testy edge cases:**
- Pusta lista eventów
- Event z None ID
- Handler rzuca wyjątek
- Repository rzuca wyjątek

### 4. tests/test_handlers.py - Testy dla handlerów

**Testy dla `send_email()`:**
- Wywołanie z payload
- Sprawdzenie output (mock print lub capture)
- Sprawdzenie sleep (mock time.sleep)

**Testy dla `push_to_crm()`:**
- Wywołanie z payload
- Sprawdzenie output

**Testy dla `record_analytics()`:**
- Wywołanie z payload
- Sprawdzenie output

**Testy dla HANDLERS:**
- Sprawdzenie że wszystkie klucze są obecne
- Sprawdzenie że wartości są callable

### 5. tests/test_supervisor.py - Testy dla supervisor (opcjonalnie)

**Uwaga:** Testy multiprocessing są trudne. Można pominąć lub testować tylko logikę bez faktycznego uruchamiania procesów.

**Testy dla `start_processes()`:**
- Mock `Process` i `worker_loop`
- Sprawdzenie utworzenia procesów
- Sprawdzenie signal handlers
- Sprawdzenie zatrzymania procesów

**Testy dla `worker_loop()`:**
- Mock OutboxRepository i OutboxWorker
- Sprawdzenie inicjalizacji
- Sprawdzenie wywołania `run_loop()`

## Wspólne fixtures (conftest.py)

- `sample_event_dict()` - przykładowy dict dla OutboxEvent
- `sample_event()` - przykładowy OutboxEvent
- `mock_repository()` - mock OutboxRepository
- `mock_db_connection()` - mock połączenia do bazy
- `mock_cursor()` - mock cursor
- `mock_worker()` - mock OutboxWorker
- `sample_payload()` - przykładowy payload

## Wykonywanie testów

### Podstawowe komendy

```bash
# Wszystkie testy
uv run pytest

# Konkretny plik
uv run pytest tests/test_models.py

# Konkretny test
uv run pytest tests/test_models.py::test_from_dict

# Z coverage
uv run pytest --cov=src/outbox --cov-report=term-missing

# Z verbose output
uv run pytest -v

# Z pokazaniem print statements
uv run pytest -s

# Tylko testy z określonym markerem
uv run pytest -m "not slow"
```

### Konfiguracja w pyproject.toml

Dodać sekcję:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = "-v --tb=short"
```

### Markery pytest (opcjonalnie)

- `@pytest.mark.slow` - dla wolnych testów
- `@pytest.mark.integration` - dla testów integracyjnych
- `@pytest.mark.unit` - dla testów unitowych

## Priorytetyzacja testów

**Wysoki priorytet:**
1. `test_models.py` - podstawowa funkcjonalność
2. `test_repository.py` - logika biznesowa
3. `test_worker.py` - główna logika przetwarzania

**Średni priorytet:**
4. `test_handlers.py` - prostsze funkcje

**Niski priorytet (opcjonalnie):**
5. `test_supervisor.py` - trudne do testowania (multiprocessing)

## Uwagi techniczne

1. **Mockowanie psycopg2:**
   - Użyć `pytest-mock` lub `unittest.mock`
   - Mockować `psycopg2.connect()` na poziomie modułu
   - Mockować cursor i jego metody

2. **Mockowanie time.sleep:**
   - Dla testów `run_loop()` mockować `time.sleep()` aby testy były szybkie

3. **Mockowanie ThreadPoolExecutor:**
   - Dla testów `run_loop()` można mockować executor lub użyć rzeczywistego z małym max_workers

4. **Testy multiprocessing:**
   - Rozważyć użycie `multiprocessing.dummy` dla testów
   - Lub całkowicie pominąć testy supervisor (są to głównie integracje)

5. **Coverage:**
   - Cel: >80% coverage dla core modułów (models, repository, worker)
   - Supervisor może mieć niższe coverage

## Struktura przykładowego testu

```python
import pytest
from datetime import datetime
from outbox.models import OutboxEvent

def test_from_dict_with_all_fields():
    data = {
        "id": 1,
        "aggregate_type": "order",
        "aggregate_id": "123",
        "event_type": "order.created",
        "payload": {"orderId": "123"},
        "status": "pending",
        "attempts": 0,
        "next_run_at": datetime.now(),
        "created_at": datetime.now(),
    }
    event = OutboxEvent.from_dict(data)
    assert event.id == 1
    assert event.aggregate_type == "order"
    # ...
```

## Kolejność implementacji

1. `conftest.py` - wspólne fixtures
2. `test_models.py` - najprostsze, bez zależności
3. `test_handlers.py` - proste funkcje
4. `test_repository.py` - wymaga mockowania DB
5. `test_worker.py` - wymaga mockowania repository i executor
6. `test_supervisor.py` - opcjonalnie

