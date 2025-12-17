# Propozycje ulepszeń dla Dispatchbox

## Kontekst projektu

**Odpowiedzi użytkownika:**
1. **Cel**: Produkcyjny
2. **Skala**: Niewielkie wolumeny (<100 events/second)
3. **Środowisko**: Docker/Kubernetes
4. **Monitoring**: Tak, potrzebne metryki Prometheus/OpenTelemetry
5. **Konfiguracja**: Zmienne środowiskowe (12-factor app)

**Implikacje:**
- Priorytet na reliability i production-ready features
- Mniejsze priorytety na extreme performance optimizations
- Ważne: Docker, Kubernetes, monitoring, health checks
- Konfiguracja przez env vars (nie pliki)

---

## Kategoria: Reliability & Resilience

### 1. Connection Pooling i Reconnection
**Priorytet: WYSOKI**

**Problem**: Każdy worker tworzy jedno połączenie, które może się zerwać. Brak automatycznego reconnect.

**Propozycja**:
- Użyć `psycopg2.pool.ThreadedConnectionPool` lub `psycopg2.pool.SimpleConnectionPool`
- Dodać automatyczny reconnect z exponential backoff
- Dodać health check połączenia przed użyciem
- Dodać timeouty dla operacji DB

**Korzyści**: Wyższa niezawodność, lepsze wykorzystanie połączeń DB

### 2. Max Attempts i Dead Letter Queue
**Priorytet: WYSOKI**

**Problem**: Eventy mogą próbować w nieskończoność. Brak limitu prób i obsługi "dead" eventów.

**Propozycja**:
- Dodać `max_attempts` do konfiguracji (domyślnie np. 5)
- Po przekroczeniu `max_attempts` → status `dead`
- Dodać endpoint/metodę do przeglądania dead eventów
- Opcjonalnie: dead letter queue w osobnym pliku/DB

**Korzyści**: Kontrola nad problematycznymi eventami, łatwiejsze debugowanie

### 3. Exponential Backoff
**Priorytet: ŚREDNI**

**Problem**: Stały backoff (30s) może być nieoptymalny.

**Propozycja**:
- Exponential backoff: `backoff = base_delay * (2 ** attempts)`
- Dodać `max_backoff` (np. 3600s = 1h)
- Dodać jitter (randomization) aby uniknąć thundering herd

**Korzyści**: Lepsze zarządzanie obciążeniem, szybsze odzyskiwanie po przejściowych błędach

### 4. Graceful Shutdown
**Priorytet: ŚREDNI**

**Problem**: Worker może być zabity w trakcie przetwarzania batcha.

**Propozycja**:
- Dodać timeout dla graceful shutdown (np. 30s)
- Poczekać na zakończenie przetwarzania aktualnego batcha
- Zamykać ThreadPoolExecutor gracefully
- Logować status shutdown

**Korzyści**: Brak utraty eventów przy restartach

---

## Kategoria: Performance & Scalability

### 5. Batch Processing Optimization
**Priorytet: NISKI** (dla <100 events/s nie jest krytyczne)

**Problem**: Każdy event jest commitowany osobno, co może być wolne.

**Propozycja**:
- Batch updates: `mark_success()` i `mark_retry()` dla wielu eventów naraz
- Użyć `executemany()` lub `execute_values()` dla bulk updates
- Opcjonalnie: transakcja dla całego batcha (z rollback przy błędzie)

**Korzyści**: Wyższa przepustowość, ale dla małych wolumenów nie jest priorytetem

### 6. Connection Pooling per Worker
**Priorytet: NISKI** (dla <100 events/s jeden connection per worker wystarczy)

**Problem**: Jeden connection per worker może być bottleneck przy wysokich wolumenach.

**Propozycja**:
- Connection pool w każdym workerze (np. 2-5 połączeń)
- Round-robin lub least-used strategy
- Monitorowanie wykorzystania pool

**Korzyści**: Lepsze wykorzystanie zasobów DB, ale dla małych wolumenów nie jest konieczne

### 7. Adaptive Polling
**Priorytet: NISKI**

**Problem**: Stały poll_interval niezależnie od obciążenia.

**Propozycja**:
- Dynamiczny poll_interval: krótszy gdy dużo eventów, dłuższy gdy pusto
- Backpressure: zwiększyć interval gdy DB jest przeciążone
- Metryki do monitorowania

**Korzyści**: Optymalizacja wykorzystania zasobów

---

## Kategoria: Observability & Monitoring

### 8. Prometheus Metrics
**Priorytet: WYSOKI** ✅ **WYMAGANE DLA PRODUCTION**

**Propozycja**:
- Użyć `prometheus-client` library
- Metryki:
  - `dispatchbox_events_processed_total` (counter, labels: status, event_type, worker)
  - `dispatchbox_events_in_flight` (gauge, label: worker)
  - `dispatchbox_processing_duration_seconds` (histogram, labels: event_type, status)
  - `dispatchbox_batch_size` (histogram)
  - `dispatchbox_worker_health` (gauge: 1=healthy, 0=unhealthy, label: worker)
  - `dispatchbox_db_connection_pool_size` (gauge)
  - `dispatchbox_retry_attempts_total` (counter, label: event_type)
- HTTP endpoint `/metrics` (na porcie konfigurowalnym, domyślnie 9090)
- Metrics server jako osobny thread/process (nie blokuje głównego workera)

**Korzyści**: Profesjonalne monitorowanie, łatwa integracja z Prometheus/Grafana, alerting

### 9. Structured Logging (JSON)
**Priorytet: ŚREDNI**

**Propozycja**:
- Opcja JSON output dla loguru (dla production)
- Dodatkowe pola: event_id, event_type, processing_time
- Correlation IDs dla śledzenia eventów przez system

**Korzyści**: Łatwiejsze parsowanie w systemach log aggregation (ELK, Loki)

### 10. Health Check Endpoint
**Priorytet: WYSOKI** ✅ **WYMAGANE DLA KUBERNETES**

**Propozycja**:
- HTTP server z endpointami:
  - `/health` - liveness probe (czy proces żyje)
  - `/ready` - readiness probe (czy worker gotowy do pracy, DB connected)
  - `/metrics` - Prometheus metrics
- Użyć `http.server` (lżejszy) lub `fastapi` (jeśli chcemy więcej features)
- Port konfigurowalny przez `DISPATCHBOX_HEALTH_PORT` (domyślnie 8080)
- `/ready` sprawdza: DB connection, worker status
- Graceful shutdown: `/ready` zwraca 503 podczas shutdown

**Korzyści**: Integracja z Kubernetes (liveness/readiness probes), monitoring, proper lifecycle management

### 11. Event Processing Metrics w Logach
**Priorytet: NISKI**

**Propozycja**:
- Co N sekund logować statystyki:
  - Events processed/sec
  - Success rate
  - Average processing time
  - Queue depth (ile eventów pending)

**Korzyści**: Szybki wgląd w performance bez zewnętrznych narzędzi

---

## Kategoria: Configuration & Deployment

### 12. Konfiguracja przez Zmienne Środowiskowe (12-Factor)
**Priorytet: WYSOKI** ✅ **WYMAGANE DLA PRODUCTION**

**Propozycja**:
- Wszystkie parametry przez zmienne środowiskowe z prefixem `DISPATCHBOX_`
- Hierarchia: env vars > defaults
- Walidacja konfiguracji przy starcie (pydantic)
- Przykłady:
  - `DISPATCHBOX_BATCH_SIZE=20`
  - `DISPATCHBOX_POLL_INTERVAL=1.0`
  - `DISPATCHBOX_MAX_ATTEMPTS=5`
  - `DISPATCHBOX_LOG_LEVEL=INFO`
- Opcjonalnie: `.env` file support dla development (python-dotenv)
- Dokumentacja wszystkich env vars w README

**Korzyści**: 12-factor compliance, łatwe zarządzanie w K8s, security (secrets)

### 13. Docker Support
**Priorytet: WYSOKI** ✅ **WYMAGANE DLA PRODUCTION**

**Propozycja**:
- `Dockerfile` (multi-stage build, Alpine-based dla małego rozmiaru)
- `docker-compose.yml` z PostgreSQL (dla development)
- `.dockerignore`
- Health checks w Dockerfile (HEALTHCHECK)
- Non-root user w kontenerze
- Proper signal handling (SIGTERM)
- Multi-arch support (amd64, arm64) jeśli potrzebne

**Korzyści**: Production deployment, łatwe development environment, security best practices

### 14. Kubernetes Manifests
**Priorytet: WYSOKI** ✅ **WYMAGANE DLA PRODUCTION**

**Propozycja**:
- Deployment manifest z:
  - Resource limits/requests
  - Liveness/readiness probes (HTTP health check)
  - Security context (non-root)
  - Pod disruption budget
- ConfigMap dla non-sensitive config
- Secret dla DSN (nie w ConfigMap!)
- Service dla health checks
- Optional: HorizontalPodAutoscaler (dla <100 events/s prawdopodobnie niepotrzebne)
- Kustomize overlays dla różnych środowisk (dev/staging/prod)

**Korzyści**: Production-ready deployment, proper resource management, security

---

## Kategoria: Code Quality & Architecture

### 15. Async/Await Support (Opcjonalnie)
**Priorytet: NISKI**

**Propozycja**:
- Wersja async używająca `asyncpg` zamiast `psycopg2`
- `asyncio` zamiast ThreadPoolExecutor
- Async handlers
- Może być równoległa implementacja (sync i async)

**Korzyści**: Wyższa wydajność dla I/O-bound operations, nowoczesny kod

### 16. Handler Interface i Middleware
**Priorytet: ŚREDNI**

**Propozycja**:
- Base class/interfejs dla handlerów
- Middleware pattern: logging, metrics, error handling, timeout
- Decorator dla handlerów: `@handler(event_type="order.created")`
- Type safety: handler powinien zwracać `HandlerResult` z statusem

**Korzyści**: Lepsza organizacja, łatwiejsze testowanie, reusable components

### 17. Dependency Injection
**Priorytet: NISKI**

**Propozycja**:
- Użyć `dependency-injector` lub podobne
- Factory pattern dla repository/worker
- Łatwiejsze testowanie, mockowanie

**Korzyści**: Lepsza architektura, łatwiejsze testowanie

### 18. Type Hints i Mypy
**Priorytet: ŚREDNI**

**Propozycja**:
- Dodać `mypy` do dev dependencies
- Uzupełnić type hints (szczególnie `Any` → konkretne typy)
- `py.typed` marker file
- CI check dla type checking

**Korzyści**: Mniej błędów, lepsze IDE support

### 19. Error Handling Improvements
**Priorytet: ŚREDNI**

**Propozycja**:
- Custom exception hierarchy:
  - `DispatchboxError` (base)
  - `DatabaseError`, `HandlerError`, `ConfigurationError`
- Retry logic tylko dla przejściowych błędów
- Różne strategie dla różnych typów błędów

**Korzyści**: Lepsze zarządzanie błędami, łatwiejsze debugowanie

---

## Kategoria: Testing & Quality

### 20. Integration Tests
**Priorytet: WYSOKI**

**Propozycja**:
- Testy z prawdziwą bazą PostgreSQL (testcontainers lub lokalna)
- Testy end-to-end: insert event → process → verify status
- Testy concurrent processing
- Testy reconnection scenarios

**Korzyści**: Wyższa pewność że system działa w production

### 21. Performance Tests
**Priorytet: NISKI**

**Propozycja**:
- Benchmarki: events/second
- Load testing z różnymi konfiguracjami
- Profiling (cProfile, py-spy)

**Korzyści**: Optymalizacja, capacity planning

### 22. Pre-commit Hooks
**Priorytet: ŚREDNI**

**Propozycja**:
- `pre-commit` framework
- Hooks: black, isort, mypy, pytest, ruff
- Automatyczne formatowanie

**Korzyści**: Spójny kod, mniej błędów w PR

### 23. CI/CD Pipeline
**Priorytet: ŚREDNI**

**Propozycja**:
- GitHub Actions / GitLab CI
- Steps: lint, type check, test, build, (optional) publish
- Matrix testing (różne wersje Python)

**Korzyści**: Automatyzacja, jakość kodu

---

## Kategoria: Features

### 24. Event Filtering
**Priorytet: NISKI**

**Propozycja**:
- Filtrowanie po `aggregate_type` lub `event_type`
- CLI flag: `--filter-aggregate-type=order`
- Użyteczne dla specjalizacji workerów

**Korzyści**: Możliwość specjalizacji workerów

### 25. Priority Queue
**Priorytet: NISKI**

**Propozycja**:
- Kolumna `priority` w tabeli
- ORDER BY priority DESC, id ASC
- Wysokopriorytetowe eventy przetwarzane pierwsze

**Korzyści**: Lepsze SLA dla ważnych eventów

### 26. Scheduled Events
**Priorytet: NISKI**

**Propozycja**:
- Eventy z `next_run_at` w przyszłości
- Worker sprawdza tylko eventy "due"
- Użyteczne dla delayed processing

**Korzyści**: Obsługa delayed events (już częściowo jest)

### 27. Handler Timeout
**Priorytet: ŚREDNI**

**Propozycja**:
- Timeout dla każdego handlera (domyślnie np. 30s)
- Użyć `concurrent.futures.TimeoutError`
- Po timeout → mark as retry

**Korzyści**: Ochrona przed zawieszonymi handlerami

### 28. Handler Context
**Priorytet: NISKI**

**Propozycja**:
- Przekazywać do handlera nie tylko payload, ale też `EventContext`:
  - event_id, event_type, aggregate_type, aggregate_id
  - attempts, created_at
- Handler może podejmować decyzje na podstawie kontekstu

**Korzyści**: Większa elastyczność handlerów

---

## Kategoria: Infrastructure

### 29. Database Migrations
**Priorytet: ŚREDNI**

**Propozycja**:
- Użyć `alembic` lub `yoyo-migrations`
- Migracje w katalogu `migrations/`
- Versioning schematu

**Korzyści**: Łatwiejsze zarządzanie zmianami schematu

### 30. Logging do Pliku
**Priorytet: NISKI**

**Propozycja**:
- Opcja logowania do pliku (rotation)
- Różne poziomy do różnych plików
- Loguru ma wbudowane rotation

**Korzyści**: Długoterminowe przechowywanie logów

### 31. Configuration Schema Validation
**Priorytet: ŚREDNI**

**Propozycja**:
- Pydantic models dla konfiguracji
- Walidacja przy starcie
- Czytelne komunikaty błędów

**Korzyści**: Mniej błędów konfiguracji, lepsze UX

---

## Priorytetyzacja - Top 10 (dostosowane do production, <100 events/s, K8s)

1. **Max Attempts i Dead Letter Queue** - krytyczne dla production
2. **Konfiguracja przez Zmienne Środowiskowe** - 12-factor, wymagane dla K8s
3. **Prometheus Metrics** - observability w production
4. **Health Check Endpoint** - wymagane dla Kubernetes
5. **Docker Support** - wymagane dla deployment
6. **Kubernetes Manifests** - wymagane dla production
7. **Connection Pooling i Reconnection** - niezawodność
8. **Graceful Shutdown** - reliability, proper lifecycle
9. **Handler Timeout** - protection przed zawieszonymi handlerami
10. **Structured Logging (JSON)** - production logging, łatwe parsowanie

---

## Quick Wins (łatwe do zaimplementowania)

1. **Max Attempts** - jedna linijka w mark_retry + config
2. **Handler Timeout** - prosty wrapper z concurrent.futures
3. **Structured Logging (JSON)** - opcja w loguru (sink z serialize=True)
4. **Dockerfile** - standardowy multi-stage template
5. **Health Check Endpoint** - prosty HTTP server z http.server
6. **Environment Variables** - użyć `os.getenv()` z defaults, dodać pydantic validation
7. **Pre-commit hooks** - setup w 5 minut

---

## Uwagi techniczne (do naprawienia)

- `datetime.utcnow()` jest deprecated w Python 3.12+ → użyć `datetime.now(timezone.utc)`
- Handlers używają `print()` → zamienić na logger
- Brak walidacji DSN przed użyciem
- Brak obsługi SIGTERM/SIGINT w worker_loop (tylko w supervisor)
- Brak connection health check przed użyciem
- Brak timeoutów dla operacji DB
- Brak obsługi błędów połączenia (reconnect)

---

## Rekomendowany plan implementacji (fazy)

### Faza 1: Production Readiness (MVP dla production)
1. Max Attempts i Dead Letter Queue
2. Konfiguracja przez Environment Variables
3. Health Check Endpoint
4. Dockerfile
5. Handler Timeout
6. Naprawienie uwag technicznych (datetime.utcnow, print → logger)

### Faza 2: Observability
7. Prometheus Metrics
8. Structured Logging (JSON)
9. Kubernetes Manifests

### Faza 3: Reliability
10. Connection Pooling i Reconnection
11. Graceful Shutdown
12. Exponential Backoff

### Faza 4: Quality & Testing
13. Integration Tests
14. Pre-commit hooks
15. CI/CD Pipeline

### Faza 5: Nice to Have
16. Handler Interface i Middleware
17. Type Hints i Mypy
18. Database Migrations
19. Error Handling Improvements

