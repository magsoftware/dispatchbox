---
name: Refaktoryzacja struktury projektu
overview: Reorganizacja aplikacji outbox do profesjonalnej struktury pakietu Python z katalogami, pyproject.toml, .gitignore, zarządzaniem zależnościami przez uv oraz wprowadzeniem modelu Event (Pydantic).
todos:
  - id: create-directory-structure
    content: "Utworzenie struktury katalogów: src/outbox/, scripts/, sql/"
    status: completed
  - id: create-pyproject-toml
    content: Utworzenie pyproject.toml z konfiguracją projektu, zależnościami (psycopg2-binary, pydantic, faker) i konfiguracją dla uv
    status: completed
  - id: create-gitignore
    content: Utworzenie .gitignore z standardowymi wzorcami Python, venv, IDE, build artifacts
    status: completed
  - id: create-event-model
    content: Utworzenie src/outbox/models.py z klasą OutboxEvent (Pydantic) mapującą wszystkie pola z tabeli outbox_event
    status: completed
    dependencies:
      - create-directory-structure
  - id: move-core-files
    content: "Przeniesienie plików core do src/outbox/: config.py, repository.py, worker.py, supervisor.py, handlers.py"
    status: completed
    dependencies:
      - create-directory-structure
  - id: refactor-repository
    content: Refaktoryzacja repository.py do używania OutboxEvent zamiast Dict[str, Any]
    status: completed
    dependencies:
      - create-event-model
      - move-core-files
  - id: refactor-worker
    content: Refaktoryzacja worker.py do używania OutboxEvent zamiast Dict[str, Any]
    status: completed
    dependencies:
      - create-event-model
      - move-core-files
  - id: update-imports
    content: Aktualizacja wszystkich importów w cli.py, supervisor.py i innych plikach do nowej struktury
    status: completed
    dependencies:
      - move-core-files
  - id: move-scripts
    content: Przeniesienie generate_outbox_db.py i generate_outbox_sql.py do scripts/ oraz aktualizacja importów
    status: completed
    dependencies:
      - create-directory-structure
  - id: move-sql-files
    content: Przeniesienie schema.sql i insert_outbox.sql do sql/
    status: completed
    dependencies:
      - create-directory-structure
---

# Plan refaktoryzacji aplikacji outbox

## Cel

Przekształcenie aplikacji w profesjonalną strukturę pakietu Python z właściwą organizacją katalogów, konfiguracją projektu i modelem danych.

## Struktura katalogów

Proponowana struktura:

```
outbox/
├── pyproject.toml          # Konfiguracja projektu i zależności (uv)
├── .gitignore              # Pliki do ignorowania w Git
├── README.md               # Dokumentacja projektu
├── src/
│   └── outbox/
│       ├── __init__.py
│       ├── models.py       # Model Event (Pydantic)
│       ├── config.py       # Stałe konfiguracyjne
│       ├── repository.py  # OutboxRepository
│       ├── worker.py       # OutboxWorker
│       ├── supervisor.py   # Zarządzanie procesami
│       └── handlers.py     # Handlery zdarzeń
├── scripts/
│   ├── __init__.py
│   ├── generate_outbox_db.py
│   └── generate_outbox_sql.py
├── sql/
│   ├── schema.sql
│   └── insert_outbox.sql
└── cli.py                  # Entry point (może zostać w root lub przenieść do src/outbox/cli.py)
```

Alternatywnie, `cli.py` można przenieść do `src/outbox/cli.py` i dodać entry point w `pyproject.toml`.

## Zadania do wykonania

### 1. Utworzenie struktury katalogów

- Utworzenie katalogu `src/outbox/`
- Utworzenie katalogu `scripts/`
- Utworzenie katalogu `sql/`
- Przeniesienie plików do odpowiednich katalogów

### 2. Model Event (Pydantic)

- Utworzenie `src/outbox/models.py` z klasą `OutboxEvent`
- Mapowanie wszystkich pól z tabeli `outbox_event`:
  - `id: int | None` (opcjonalne dla nowych eventów)
  - `aggregate_type: str`
  - `aggregate_id: str`
  - `event_type: str`
  - `payload: dict[str, Any] `(lub `JsonDict` z Pydantic)
  - `status: Literal["pending", "retry", "done", "dead"]`
  - `attempts: int`
  - `next_run_at: datetime`
  - `created_at: datetime | None` (opcjonalne)
- Dodanie walidacji i konwersji typów
- Metody pomocnicze do konwersji z/do dict (dla kompatybilności z repository)

**Uwaga**: Pydantic vs dataclass - proponuję Pydantic dla lepszej walidacji i integracji z JSON. Jeśli preferujesz dataclass, można użyć `@dataclass` z Python 3.7+.

### 3. pyproject.toml

- Konfiguracja projektu zgodna z PEP 621
- Zależności:
  - `psycopg2-binary` (lub `psycopg2` jeśli wymagane)
  - `pydantic` (dla modelu Event)
  - `faker` (dla skryptów generujących dane testowe)
- Konfiguracja dla `uv`:
  - `[tool.uv]` sekcja
  - `[project.optional-dependencies]` dla dev dependencies
- Entry points dla CLI (jeśli `cli.py` zostanie w `src/outbox/`)
- Metadata projektu (nazwa, wersja, autor, opis)

### 4. .gitignore

- Standardowe wzorce Python (`__pycache__/`, `*.pyc`, `*.pyo`, `*.pyd`, `.Python`)
- Wirtualne środowiska (`venv/`, `.venv/`, `env/`)
- IDE (`.vscode/`, `.idea/`)
- Build artifacts (`dist/`, `build/`, `*.egg-info/`)
- uv specific (`.uv/` jeśli potrzebne)
- Lokalne pliki konfiguracyjne i bazy danych

### 5. Aktualizacja importów

- Aktualizacja wszystkich importów względnych/bezwzględnych
- Zmiana z `from repository import ...` na `from outbox.repository import ...`
- Aktualizacja importów w `cli.py`, `worker.py`, `supervisor.py`, `handlers.py`

### 6. Refaktoryzacja repository.py

- Zmiana `fetch_pending()` aby zwracała `List[OutboxEvent]` zamiast `List[Dict[str, Any]]`
- Konwersja wyników z bazy danych do obiektów `OutboxEvent`
- Aktualizacja metod `mark_success()` i `mark_retry()` aby przyjmowały `OutboxEvent` lub `int` (id)

### 7. Refaktoryzacja worker.py

- Zmiana `process_event()` aby przyjmowała `OutboxEvent` zamiast `Dict[str, Any]`
- Aktualizacja typów w `run_loop()`
- Aktualizacja dostępu do pól eventu (`.event_type`, `.payload` zamiast `event["event_type"]`)

### 8. Aktualizacja skryptów pomocniczych

- Przeniesienie `generate_outbox_db.py` i `generate_outbox_sql.py` do `scripts/`
- Aktualizacja importów w skryptach
- Opcjonalnie: użycie modelu `OutboxEvent` w skryptach generujących dane

### 9. README.md (opcjonalnie)

- Podstawowa dokumentacja projektu
- Instrukcje instalacji z użyciem `uv`
- Przykłady użycia

## Pliki do zmodyfikowania

- `cli.py` - aktualizacja importów
- `config.py` → `src/outbox/config.py` - bez zmian strukturalnych
- `repository.py` → `src/outbox/repository.py` - użycie modelu Event
- `worker.py` → `src/outbox/worker.py` - użycie modelu Event
- `supervisor.py` → `src/outbox/supervisor.py` - aktualizacja importów
- `handlers.py` → `src/outbox/handlers.py` - bez zmian strukturalnych
- `generate_outbox_db.py` → `scripts/generate_outbox_db.py` - aktualizacja importów
- `generate_outbox_sql.py` → `scripts/generate_outbox_sql.py` - bez zmian strukturalnych
- `schema.sql` → `sql/schema.sql` - bez zmian
- `insert_outbox.sql` → `sql/insert_outbox.sql` - bez zmian

## Pliki do utworzenia

- `pyproject.toml` - konfiguracja projektu
- `.gitignore` - pliki do ignorowania
- `src/outbox/__init__.py` - inicjalizacja pakietu
- `src/outbox/models.py` - model Event
- `scripts/__init__.py` - inicjalizacja pakietu scripts (opcjonalnie)
- `README.md` - dokumentacja (opcjonalnie)

## Uwagi techniczne

1. **Pydantic vs dataclass**: Proponuję Pydantic v2 dla lepszej walidacji, serializacji JSON i type safety. Jeśli preferujesz lżejsze rozwiązanie, można użyć `@dataclass` z Python 3.7+.

2. **Entry point**: Jeśli `cli.py` zostanie w root, można go pozostawić jako `__main__.py` lub dodać entry point w `pyproject.toml` jako `outbox = "outbox.cli:main"`.

3. **Kompatybilność wsteczna**: `outbox_worker.py` może pozostać w root jako wrapper importujący z nowej lokalizacji.

4. **Zależności**: `faker` może być w `[project.optional-dependencies.dev]` jeśli używane tylko w skryptach pomocniczych.

## Kolejność wykonania

1. Utworzenie struktury katalogów
2. Utworzenie `pyproject.toml` i `.gitignore`
3. Utworzenie modelu `OutboxEvent` w `models.py`
4. Przeniesienie i aktualizacja plików źródłowych
5. Refaktoryzacja `repository.py` i `worker.py` do używania modelu
6. Aktualizacja importów we wszystkich plikach
7. Przeniesienie skryptów pomocniczych i plików SQL
8. Testowanie kompilacji i importów