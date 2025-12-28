# Dead Letter Queue (DLQ) - Koncepcja i Propozycje

## Co to jest Dead Letter Queue?

**Dead Letter Queue (DLQ)** to mechanizm przechowywania eventów, które nie mogły być przetworzone po wielokrotnych próbach. W kontekście outbox pattern:

1. **Event nie może być przetworzony** - handler rzuca wyjątek, timeout, błąd sieci, etc.
2. **System próbuje ponownie** - zgodnie z `max_attempts` (domyślnie 5)
3. **Po przekroczeniu limitu** - event jest oznaczony jako `'dead'` i **nie jest już automatycznie przetwarzany**
4. **DLQ przechowuje te eventy** - dla analizy, debugowania i potencjalnego ręcznego przetworzenia

## Co mamy obecnie ✅

- ✅ Eventy przekraczające `max_attempts` są oznaczane jako `'dead'`
- ✅ Logowanie ostrzeżenia gdy event staje się dead
- ✅ Status `'dead'` w bazie danych

## Czego brakuje ❌

1. **Brak metody do przeglądania dead eventów** - nie można łatwo zobaczyć co się nie udało
2. **Brak możliwości ponownego przetworzenia** - nie można ręcznie "odrodzić" dead event
3. **Brak alertingu** - nikt nie wie że są dead eventy
4. **Brak metryk** - nie wiemy ile dead eventów mamy
5. **Brak analizy przyczyn** - nie wiemy dlaczego eventy umierają

---

## Propozycje implementacji

### 1. Metody w Repository (PRIORYTET: WYSOKI)

```python
# W OutboxRepository:

def fetch_dead_events(
    self,
    limit: int = 100,
    offset: int = 0,
    aggregate_type: Optional[str] = None,
    event_type: Optional[str] = None,
    since: Optional[datetime] = None
) -> List[OutboxEvent]:
    """
    Fetch dead events for review.

    Args:
        limit: Maximum number of events to fetch
        offset: Offset for pagination
        aggregate_type: Filter by aggregate type (optional)
        event_type: Filter by event type (optional)
        since: Only events marked as dead after this time (optional)

    Returns:
        List of dead OutboxEvent instances
    """
    # SQL query z filtrowaniem
    pass

def count_dead_events(
    self,
    aggregate_type: Optional[str] = None,
    event_type: Optional[str] = None,
    since: Optional[datetime] = None
) -> int:
    """Count dead events matching criteria."""
    pass

def retry_dead_event(self, event_id: int) -> bool:
    """
    Reset a dead event to 'pending' for retry.

    Args:
        event_id: ID of dead event to retry

    Returns:
        True if event was successfully reset, False if not found or not dead

    Raises:
        ValueError: If event is not in 'dead' status
    """
    # UPDATE outbox_event SET status='pending', attempts=0 WHERE id=... AND status='dead'
    pass

def retry_dead_events_batch(
    self,
    event_ids: List[int]
) -> int:
    """
    Reset multiple dead events to 'pending'.

    Returns:
        Number of events successfully reset
    """
    pass
```

**Korzyści:**
- Możliwość przeglądania problematycznych eventów
- Możliwość ręcznego retry po naprawie problemu
- Podstawa do alertingu i monitoringu

---

### 2. CLI Commands (PRIORYTET: ŚREDNI)

```bash
# Lista dead eventów
dispatchbox dead-events list [--limit 100] [--aggregate-type order] [--event-type order.created]

# Statystyki dead eventów
dispatchbox dead-events stats

# Retry pojedynczego eventu
dispatchbox dead-events retry <event_id>

# Retry wielu eventów
dispatchbox dead-events retry-batch <event_id1> <event_id2> ...

# Eksport do JSON/CSV
dispatchbox dead-events export --format json --output dead_events.json
```

**Korzyści:**
- Łatwe zarządzanie dead eventami z linii poleceń
- Integracja ze skryptami/automatyzacją

---

### 3. HTTP API Endpoint (PRIORYTET: ŚREDNI)

Gdy będziemy mieli health check endpoint, możemy dodać:

```
GET  /api/dead-events          # Lista dead eventów (z paginacją)
GET  /api/dead-events/stats    # Statystyki
GET  /api/dead-events/:id      # Szczegóły pojedynczego eventu
POST /api/dead-events/:id/retry  # Retry dead event
POST /api/dead-events/retry-batch  # Retry wielu eventów
```

**Korzyści:**
- Integracja z dashboardami/monitoringiem
- Możliwość zbudowania UI

---

### 4. Metryki Prometheus (PRIORYTET: WYSOKI)

```python
# W worker/repository:
dispatchbox_dead_events_total{event_type, aggregate_type}  # Counter
dispatchbox_dead_events_current{event_type, aggregate_type}  # Gauge
dispatchbox_event_attempts_before_dead{event_type}  # Histogram
```

**Korzyści:**
- Alerting gdy liczba dead eventów rośnie
- Monitoring trendów
- Integracja z Grafana

---

### 5. Alerting (PRIORYTET: WYSOKI)

```python
# W worker, gdy event staje się dead:
if event marked as dead:
    # Emit metric
    dead_events_counter.inc(labels={'event_type': event.event_type})

    # Optional: Send alert (email, Slack, PagerDuty)
    if dead_events_count > threshold:
        send_alert(f"High number of dead events: {dead_events_count}")
```

**Korzyści:**
- Szybka reakcja na problemy
- Wiedza o problematycznych eventach

---

### 6. Analiza przyczyn (PRIORYTET: NISKI)

```sql
-- Dodać kolumnę do tabeli (migration):
ALTER TABLE outbox_event
ADD COLUMN last_error TEXT,
ADD COLUMN last_error_at TIMESTAMPTZ;

-- W mark_retry, zapisać ostatni błąd:
UPDATE outbox_event
SET last_error = %s,
    last_error_at = now()
WHERE id = %s AND status = 'dead';
```

**Korzyści:**
- Łatwiejsze debugowanie
- Analiza wzorców błędów

---

### 7. Automatyczne czyszczenie (PRIORYTET: NISKI)

```python
def cleanup_old_dead_events(
    self,
    older_than_days: int = 30
) -> int:
    """
    Delete dead events older than specified days.

    Returns:
        Number of events deleted
    """
    # DELETE FROM outbox_event
    # WHERE status = 'dead'
    #   AND created_at < now() - interval '%s days'
```

**Korzyści:**
- Zapobieganie rozrostowi tabeli
- Można uruchamiać jako cron job

---

## Rekomendowany plan implementacji

### Faza 1: Podstawowe funkcjonalności (MVP)
1. ✅ Max attempts i oznaczanie jako 'dead' - **DONE**
2. **`fetch_dead_events()`** - metoda do przeglądania
3. **`count_dead_events()`** - liczenie dead eventów
4. **`retry_dead_event()`** - możliwość ponownego przetworzenia
5. **Metryki Prometheus** - `dispatchbox_dead_events_total`

### Faza 2: CLI i użyteczność
6. CLI commands (`dead-events list`, `retry`, `stats`)
7. Eksport do JSON/CSV

### Faza 3: Zaawansowane
8. HTTP API endpoints
9. Alerting (email/Slack)
10. Analiza przyczyn (last_error)
11. Automatyczne czyszczenie

---

## Przykładowe użycie

```python
# W kodzie aplikacji lub CLI:

from dispatchbox.repository import OutboxRepository

repo = OutboxRepository(dsn="...")

# Sprawdź ile mamy dead eventów
count = repo.count_dead_events()
print(f"Dead events: {count}")

# Pobierz ostatnie 10 dead eventów
dead_events = repo.fetch_dead_events(limit=10)
for event in dead_events:
    print(f"Event {event.id}: {event.event_type} - {event.attempts} attempts")

# Retry pojedynczego eventu (po naprawie problemu)
if repo.retry_dead_event(event_id=123):
    print("Event reset to pending, will be retried")
else:
    print("Event not found or not dead")
```

---

## Archiwizacja

**Uwaga:** W schemacie bazy danych (`sql/schema.sql`) jest już zaimplementowana archiwizacja dla eventów ze statusem `'done'`:

- Tabela `outbox_event_archive` przechowuje zarchiwizowane eventy
- Funkcja `archive_outbox_events(retention_days)` przenosi stare eventy `'done'` do archiwum
- Można zaplanować automatyczną archiwizację używając `pg_cron`

**Rozważenie:** Można rozszerzyć funkcję archiwizującą, aby również przenosiła eventy `'dead'` po określonym czasie, zanim zostaną usunięte. To pozwoliłoby zachować historię problematycznych eventów dla analizy.

## Pytania do rozważenia

1. **Czy dead eventy powinny być automatycznie eksportowane** do osobnej tabeli/pliku?
2. **Czy potrzebujemy retention policy** - jak długo przechowywać dead eventy?
3. **Czy retry powinien resetować attempts** do 0 czy zachować historię?
4. **Czy potrzebujemy webhook** gdy event staje się dead?
5. **Czy dead eventy powinny być archiwizowane** przed usunięciem? (Patrz sekcja Archiwizacja powyżej)

---

## Podsumowanie

**Obecny stan:** Mamy podstawę - eventy są oznaczane jako 'dead' ✅

**Następne kroki:**
1. Dodać metody do przeglądania i retry dead eventów
2. Dodać metryki Prometheus
3. Dodać CLI commands dla łatwego zarządzania

**Priorytet:** Wysoki - to jest krytyczne dla production, żeby móc zarządzać problematycznymi eventami.
