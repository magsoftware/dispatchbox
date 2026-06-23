# Dispatchbox — Architektura

> Dokument wygenerowany na podstawie analizy kodu źródłowego (`src/`). Jedynym źródłem prawdy jest kod.

---

## Cel systemu

**Dispatchbox** to worker obsługujący konsumencką część wzorca *transactional outbox* dla PostgreSQL. Atomowo przejmuje zdarzenia zapisane w tabeli `outbox_event`, wywołuje zarejestrowany handler, a następnie w osobnej transakcji zapisuje wynik przetwarzania.

System zapewnia semantykę **at-least-once**, a nie exactly-once. Mechanizm dzierżawy (`claim_token` + `next_run_at`) pozwala odzyskać zdarzenie po awarii workera i chroni rekord przed finalizacją przez właściciela nieaktualnej dzierżawy. Nie chroni jednak efektów ubocznych handlera: awaria po wykonaniu handlera, ale przed `mark_success()`, może spowodować jego ponowne wywołanie. Handlery powinny być idempotentne.

---

## Struktura modułów

```
src/dispatchbox/
├── __init__.py        # wersja pakietu (0.1.0)
├── config.py          # stałe konfiguracyjne z wartościami domyślnymi
├── models.py          # dataclass OutboxEvent
├── repository.py      # OutboxRepository — warstwa bazy danych (psycopg2)
├── handlers.py        # rejestr handlerów event_type → funkcja
├── worker.py          # OutboxWorker — pojedynczy proces, wiele wątków
├── supervisor.py      # start_processes() — nadzorca wielu procesów
├── http_server.py     # HttpServer — liveness/readiness/DLQ API (Bottle)
└── cli.py             # main() — punkt wejścia CLI (argparse)
```

---

## Schemat bazy danych

### `outbox_event`

| Kolumna          | Typ          | Opis                                                         |
|------------------|--------------|--------------------------------------------------------------|
| `id`             | BIGSERIAL PK | identyfikator zdarzenia                                      |
| `aggregate_type` | TEXT NOT NULL| klasa agregatu (np. `order`, `invoice`)                      |
| `aggregate_id`   | TEXT NOT NULL| identyfikator instancji agregatu                             |
| `event_type`     | TEXT NOT NULL| klucz handlera (np. `order.created`)                         |
| `payload`        | JSONB NOT NULL| dane przekazywane do handlera                               |
| `status`         | TEXT NOT NULL| stan zdarzenia; domyślnie `pending`                          |
| `claim_token`    | TEXT         | UUID ustawiany przy przejęciu zdarzenia — fencing token      |
| `attempts`       | INT NOT NULL | liczba zakończonych prób; domyślnie `0`, inkrementowana przy sukcesie i błędzie            |
| `next_run_at`    | TIMESTAMPTZ NOT NULL | kiedy zdarzenie jest gotowe do przetworzenia / wygasa dzierżawa; domyślnie `now()` |
| `created_at`     | TIMESTAMPTZ NOT NULL | czas wstawienia; domyślnie `now()`                                                 |

Schemat nie definiuje ograniczenia `CHECK` dla `status`. Poniższa maszyna stanów jest wymuszana przez kod repozytorium, a nie przez bazę danych.

**Indeks częściowy** (kluczowy dla wydajności workerów):
```sql
CREATE INDEX idx_outbox_due
  ON outbox_event (next_run_at ASC)
  WHERE status IN ('pending','retry','processing');
```

### `outbox_event_archive`

Tabela docelowa dla zakończonych zdarzeń (status `done`). Funkcja PL/pgSQL `archive_outbox_events(retention_days)` usuwa kwalifikujące się rekordy z `outbox_event` i wstawia je do archiwum. Wewnątrz pętli wybiera do 5000 rekordów, ale całe wywołanie funkcji nadal wykonuje się w jednej transakcji — porcjowanie nie oznacza osobnego commitu ani zwolnienia blokad po każdej partii.

W `sql/schema.sql` znajduje się jedynie zakomentowany przykład rejestracji zadania `pg_cron` na godzinę 03:00. Sam schemat nie instaluje harmonogramu; trzeba zrobić to oddzielnie.

---

## Maszyna stanów zdarzenia

```
INSERT ──► pending ──────────────────────────────┐
                                                 │
retry ───────────────────────────────────────────┤ fetch_pending()
                                                 │ SKIP LOCKED + claim_token
expired processing ──────────────────────────────┘
                                                 │
                                                 ▼
                                           processing
                                          /          \
                                   sukces/            \błąd
                                        ▼              ▼
                                      done       attempts + 1 < max ──► retry
                                                 attempts + 1 >= max ─► dead
                                                                             │
                                                    retry_dead_event()       │
                                                    attempts=0               │
                                      pending ◄──────────────────────────────┘
```

Przejścia realizowane przez `OutboxRepository`:

| Metoda              | Zmiana statusu                                      |
|---------------------|-----------------------------------------------------|
| `fetch_pending`     | `pending`/`retry`/`processing` → `processing`       |
| `mark_success`      | `processing` → `done`, `attempts += 1`              |
| `mark_retry`        | `processing` → `retry` lub `dead`, `attempts += 1`  |
| `renew_claim`       | `processing` (tylko `next_run_at` przedłużone)      |
| `retry_dead_event`  | `dead` → `pending`, `attempts = 0`                  |
| `retry_dead_events_batch` | wiele `dead` → `pending`, `attempts = 0`      |

---

## Przepływ przetwarzania

```
CLI (main)
  │
  ├─► HttpServer.start()          # opcjonalny wątek daemon (domyślnie :8080)
  │
  └─► start_processes()           # supervisor.py
        │
        ├── Process[worker-00]
        │     └── worker_loop()
        │           ├── OutboxRepository(dsn)  # własne połączenie na proces
        │           └── OutboxWorker.run_loop()
        │                 │
        │                 ├── fetch_pending(batch_size)
        │                 │     └── UPDATE ... RETURNING  (atomowe przejęcie)
        │                 │
        │                 └── _process_batch(batch)
        │                       ├── executor.submit(process_event, event)  ← wątek
        │                       │     └── HANDLERS[event_type](payload)
        │                       │
        │                       └── heartbeat loop (co lease_seconds/3)
        │                             ├── renew_claim()   ← dla nadal działających
        │                             └── _finalize_event()  ← dla zakończonych
        │                                   ├── mark_success()
        │                                   └── mark_retry()
        │
        ├── Process[worker-01]  (identyczny)
        └── ...
```

---

## Mechanizm dzierżawy (lease / fencing token)

1. `fetch_pending()` generuje `uuid4()` jako `claim_token` dla przejmowanej partii i atomowo ustawia `status='processing'` oraz `next_run_at = now() + lease_seconds`. Jedna instrukcja składa się z CTE `SELECT ... FOR UPDATE SKIP LOCKED` i `UPDATE ... RETURNING`.
2. Jeśli handler nie zakończy się przed wygaśnięciem dzierżawy, inne workery mogą przejąć zdarzenie (`status='processing'` + `next_run_at <= now()`).
3. Stary worker nie może **sfinalizować rekordu** — `mark_success` / `mark_retry` sprawdzają `claim_token` i zwracają `False`, jeśli token nie pasuje. Handler starego workera może jednak nadal się wykonać, dlatego fencing token nie zapewnia exactly-once dla efektów zewnętrznych.
4. `renew_claim()` przedłuża dzierżawę co `lease_seconds / 3` sekund dla wątków, które nadal działają.

Domyślne wartości (`config.py`):

| Stała                         | Wartość | Opis                              |
|-------------------------------|---------|-----------------------------------|
| `DEFAULT_BATCH_SIZE`          | 10      | zdarzeń na batch                  |
| `DEFAULT_POLL_INTERVAL`       | 1.0s    | pauza gdy brak pracy              |
| `DEFAULT_MAX_PARALLEL`        | 10      | wątków na proces                  |
| `DEFAULT_RETRY_BACKOFF_SECONDS` | 30s   | opóźnienie retry                  |
| `DEFAULT_LEASE_SECONDS`       | 300s    | TTL dzierżawy                     |
| `DEFAULT_MAX_ATTEMPTS`        | 5       | prób zanim `dead`                 |
| `DEFAULT_NUM_PROCESSES`       | 1       | procesów roboczych                |

---

## Konfiguracja CLI

```
dispatchbox --dsn "..." [opcje]

--processes N          liczba procesów roboczych (domyślnie: 1)
--batch-size N         zdarzenia na batch DB (domyślnie: 10)
--poll-interval S      pauza gdy brak pracy [s] (domyślnie: 1.0)
--lease-seconds S      TTL dzierżawy (domyślnie: 300)
--log-level LEVEL      DEBUG|INFO|WARNING|ERROR|CRITICAL (domyślnie: INFO)
--http-host HOST       host HTTP (domyślnie: 0.0.0.0)
--http-port PORT       port HTTP (domyślnie: 8080)
--disable-http         wyłącz serwer HTTP
-h, --help             standardowa pomoc argparse
--show-help            wywołaj osobną funkcję help() i zakończ (nadal wymaga --dsn)
```

**Uwaga:** Parametry `max_parallel` (wątki na proces, domyślnie 10) i `retry_backoff_seconds` (domyślnie 30s) istnieją w kodzie (`worker.py`, `repository.py`, `supervisor.py`), ale **nie mają odpowiadających argumentów CLI** — zawsze używają wartości domyślnych.

---

## HTTP API

### Sondy

| Endpoint   | Metoda | Opis                                          |
|------------|--------|-----------------------------------------------|
| `/health`  | GET    | liveness — zawsze `200 {"status":"ok"}`       |
| `/ready`   | GET    | readiness — sprawdza połączenie z DB          |
| `/metrics` | GET    | Prometheus, tylko jeśli `HttpServer` otrzyma `metrics_fn` |

Aktualny przepływ CLI nie przekazuje `metrics_fn`, więc `/metrics` nie jest rejestrowane podczas standardowego uruchomienia `dispatchbox`.

### Dead Letter Queue (DLQ)

| Endpoint                              | Metoda | Opis                                      |
|---------------------------------------|--------|-------------------------------------------|
| `/api/dead-events`                    | GET    | lista dead events (paginacja, filtry)     |
| `/api/dead-events/stats`              | GET    | liczba dead events (z filtrami)           |
| `/api/dead-events/<id>`               | GET    | szczegóły jednego dead event              |
| `/api/dead-events/<id>/retry`         | POST   | reset do `pending` (attempts=0)           |
| `/api/dead-events/retry-batch`        | POST   | batch reset `{"event_ids": [1,2,3]}`      |

---

## Zależności

| Pakiet              | Rola                                       |
|---------------------|--------------------------------------------|
| `psycopg2-binary`   | sterownik PostgreSQL                       |
| `loguru`            | logging ze strukturą (`{extra[worker]}`)   |
| `bottle`            | lekki HTTP server (synchroniczny WSGI)     |

---

## Znalezione błędy logiczne

### ~~BUG-1 — Wyciek połączeń w endpointach DLQ~~ — NAPRAWIONY

**Plik:** [http_server.py](../src/dispatchbox/http_server.py)

Poprawka zastosowana. Wszystkie 5 handlerów DLQ używa teraz `with self.repository_fn() as repo:`, co gwarantuje wywołanie `OutboxRepository.__exit__()` → `close()` po każdym żądaniu, również przy wyjątku.

---

### ~~BUG-2 — Błędny separator dla URI DSN bez parametrów query~~ — NAPRAWIONY

**Plik:** [repository.py:178](../src/dispatchbox/repository.py#L178)

Poprawka zastosowana. Logika rozróżnia teraz trzy przypadki:
```python
if dsn.startswith(("postgresql://", "postgres://")):
    separator = "&" if "?" in dsn else "?"
else:
    separator = " "
```

---

## Podsumowanie przepływu danych

```
Aplikacja biznesowa
  └─► INSERT INTO outbox_event (status='pending')

dispatchbox worker
  └─► SELECT FOR UPDATE SKIP LOCKED
      → UPDATE status='processing', claim_token=uuid4, next_run_at=now()+lease
        └─► handler(payload) [wątek]
              ├─► sukces → UPDATE status='done', attempts+=1, claim_token=NULL
              └─► błąd   → UPDATE status='retry'|'dead', attempts+=1, claim_token=NULL

opcjonalny harmonogram zewnętrzny (np. pg_cron; przykład: codziennie o 3:00)
  └─► archive_outbox_events(7)  # harmonogram nie jest instalowany przez schema.sql
        └─► DELETE FROM outbox_event WHERE status='done' AND created_at < now()-7d
            INSERT INTO outbox_event_archive (...)  [partie po 5000 w jednej transakcji]

operator / monitoring
  └─► GET /api/dead-events        → przegląd
      POST /api/dead-events/{id}/retry  → reset do pending
```
