# Analiza: Framework HTTP dla Endpointów

## Wymagania

Potrzebujemy endpointów dla:
1. **Health checks** - `/health`, `/ready` (proste GET, zwraca JSON lub 200/503)
2. **Metryki Prometheus** - `/metrics` (GET, zwraca text/plain w formacie Prometheus)
3. **Dead Letter Queue** - `/api/dead-events` (GET lista, POST retry) - opcjonalnie

## Kryteria wyboru

1. **Lekkość** - to jest worker, nie chcemy dużego footprint
2. **Prostota** - proste endpointy, nie potrzebujemy pełnego web frameworka
3. **Zero/minimal dependencies** - preferowane
4. **Performance** - worker już ma swoje obciążenie
5. **Maintenance** - łatwe w utrzymaniu

---

## Opcje do rozważenia

### 1. http.server (Standard Library) ⭐⭐⭐⭐⭐

**Zalety:**
- ✅ **Zero dependencies** - wbudowane w Python
- ✅ **Minimalny footprint** - 0MB
- ✅ **Pełna kontrola** - wszystko ręcznie
- ✅ **Proste** - dla podstawowych endpointów wystarczy

**Wady:**
- ❌ Więcej boilerplate kodu
- ❌ Brak automatycznego routing (trzeba ręcznie parsować path)
- ❌ Brak automatycznego JSON parsing/serialization
- ❌ Trzeba ręcznie obsługiwać CORS, headers, etc.

**Przykład:**
```python
from http.server import HTTPServer, BaseHTTPRequestHandler
import json

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok'}).encode())
        elif self.path == '/metrics':
            # Prometheus metrics
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'# HELP dispatchbox_events_processed_total\n')
        else:
            self.send_response(404)
            self.end_headers()

server = HTTPServer(('0.0.0.0', 8080), HealthHandler)
server.serve_forever()
```

**Kod:** ~50-100 linii dla podstawowych endpointów

---

### 2. Bottle ⭐⭐⭐⭐

**Zalety:**
- ✅ **Bardzo lekki** - ~50KB, single file
- ✅ **Zero dependencies** (oprócz standard library)
- ✅ **Prosty routing** - dekoratory
- ✅ **Automatyczny JSON** - `return dict()` → JSON
- ✅ **Wbudowany dev server** - łatwe testowanie
- ✅ **Minimalny boilerplate**

**Wady:**
- ⚠️ Mniej popularny niż Flask/FastAPI
- ⚠️ Mniejsza społeczność

**Przykład:**
```python
from bottle import Bottle, run, response
from prometheus_client import generate_latest

app = Bottle()

@app.get('/health')
def health():
    return {'status': 'ok'}

@app.get('/ready')
def ready():
    # Check DB connection
    if db_connected():
        return {'status': 'ready'}
    response.status = 503
    return {'status': 'not ready'}

@app.get('/metrics')
def metrics():
    response.content_type = 'text/plain; version=0.0.4'
    return generate_latest()

if __name__ == '__main__':
    run(app, host='0.0.0.0', port=8080)
```

**Kod:** ~20-30 linii dla podstawowych endpointów

**Dependency:** `bottle>=0.12.0` (~50KB)

---

### 3. FastAPI ⭐⭐⭐

**Zalety:**
- ✅ **Nowoczesny** - async support, type hints
- ✅ **Automatyczna dokumentacja** - Swagger/OpenAPI out of the box
- ✅ **Type safety** - Pydantic validation
- ✅ **Szybki** - oparty na Starlette
- ✅ **Popularny** - duża społeczność

**Wady:**
- ❌ **Duży footprint** - ~50MB dependencies (FastAPI + uvicorn + pydantic)
- ❌ **Overkill** - dla prostych endpointów to za dużo
- ❌ **Async complexity** - jeśli nie potrzebujemy async

**Przykład:**
```python
from fastapi import FastAPI
from prometheus_client import generate_latest
from fastapi.responses import PlainTextResponse

app = FastAPI()

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    return generate_latest()
```

**Dependency:** `fastapi>=0.100.0`, `uvicorn[standard]>=0.23.0` (~50MB)

---

### 4. Flask ⭐⭐⭐

**Zalety:**
- ✅ **Popularny** - duża społeczność, dobrze udokumentowany
- ✅ **Prosty** - łatwy w użyciu
- ✅ **Elastyczny** - można rozbudować w przyszłości

**Wady:**
- ❌ **Średni footprint** - ~10-20MB dependencies
- ❌ **Synchronous** - brak async (ale dla health checks to OK)
- ❌ **Więcej niż potrzebujemy** - dla prostych endpointów

**Przykład:**
```python
from flask import Flask, jsonify
from prometheus_client import generate_latest

app = Flask(__name__)

@app.route('/health')
def health():
    return jsonify({'status': 'ok'})

@app.route('/metrics')
def metrics():
    return generate_latest(), 200, {'Content-Type': 'text/plain'}
```

**Dependency:** `flask>=2.3.0` (~10-20MB)

---

### 5. Starlette (podstawa FastAPI) ⭐⭐⭐⭐

**Zalety:**
- ✅ **Lżejszy niż FastAPI** - ~5MB (bez Pydantic)
- ✅ **Async support** - jeśli potrzebujemy
- ✅ **Minimalny** - tylko to co potrzebne
- ✅ **Szybki** - używany przez FastAPI

**Wady:**
- ⚠️ Mniej popularny niż FastAPI/Flask
- ⚠️ Trzeba więcej boilerplate niż FastAPI

**Przykład:**
```python
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route
from prometheus_client import generate_latest

async def health(request):
    return JSONResponse({'status': 'ok'})

async def metrics(request):
    return PlainTextResponse(generate_latest())

app = Starlette(routes=[
    Route('/health', health),
    Route('/metrics', metrics),
])
```

**Dependency:** `starlette>=0.27.0`, `uvicorn[standard]>=0.23.0` (~5MB)

---

### 6. aiohttp ⭐⭐

**Zalety:**
- ✅ **Async** - jeśli potrzebujemy
- ✅ **Szybki** - dla async workloads

**Wady:**
- ❌ **Overkill** - dla prostych endpointów
- ❌ **Async complexity** - jeśli nie potrzebujemy async
- ❌ **Średni footprint** - ~5-10MB

**Nie rekomendowane** dla tego przypadku.

---

## Porównanie

| Framework | Dependencies | Size | Complexity | Async | Best For |
|-----------|--------------|------|------------|-------|----------|
| **http.server** | ✅ Zero | 0MB | ⚠️ Średnia | ❌ | Minimal footprint |
| **Bottle** | ✅ Minimal | ~50KB | ✅ Niska | ❌ | **BALANCE** ⭐ |
| **Starlette** | ⚠️ Medium | ~5MB | ⚠️ Średnia | ✅ | Async needs |
| **Flask** | ⚠️ Medium | ~10-20MB | ✅ Niska | ❌ | Popularity |
| **FastAPI** | ❌ Duże | ~50MB | ✅ Niska | ✅ | Full-featured |

---

## Rekomendacja

### **Bottle** ⭐⭐⭐⭐ (Najlepszy balans)

**Dlaczego:**
1. ✅ **Minimalny footprint** - ~50KB, praktycznie zero
2. ✅ **Prosty** - dekoratory, automatyczny JSON
3. ✅ **Wystarczający** - dla health checks i metrics
4. ✅ **Zero config** - działa out of the box
5. ✅ **Łatwy w utrzymaniu** - mało kodu

**Przykładowa implementacja:**
```python
# src/dispatchbox/http_server.py
from bottle import Bottle, run, response, request
from prometheus_client import generate_latest, Counter, Gauge
from typing import Optional
import threading

# Metrics
events_processed = Counter('dispatchbox_events_processed_total', 'Events processed', ['status', 'event_type'])
dead_events = Gauge('dispatchbox_dead_events_current', 'Current dead events')

app = Bottle()

@app.get('/health')
def health():
    """Liveness probe - is process alive?"""
    return {'status': 'ok'}

@app.get('/ready')
def ready():
    """Readiness probe - is worker ready?"""
    # Check DB connection
    if is_db_connected():
        return {'status': 'ready'}
    response.status = 503
    return {'status': 'not ready', 'reason': 'database not connected'}

@app.get('/metrics')
def metrics():
    """Prometheus metrics endpoint."""
    response.content_type = 'text/plain; version=0.0.4; charset=utf-8'
    return generate_latest()

# Optional: DLQ endpoints
@app.get('/api/dead-events')
def list_dead_events():
    """List dead events (optional)."""
    limit = int(request.query.get('limit', 100))
    # ... fetch from repository
    return {'events': []}

@app.post('/api/dead-events/<event_id:int>/retry')
def retry_dead_event(event_id: int):
    """Retry a dead event (optional)."""
    # ... retry logic
    return {'status': 'retried', 'event_id': event_id}

def start_http_server(host: str = '0.0.0.0', port: int = 8080, daemon: bool = True):
    """Start HTTP server in background thread."""
    thread = threading.Thread(
        target=lambda: run(app, host=host, port=port, quiet=True),
        daemon=daemon
    )
    thread.start()
    return thread
```

**Użycie w CLI:**
```python
# src/dispatchbox/cli.py
from dispatchbox.http_server import start_http_server

def main():
    # ... existing code ...
    
    # Start HTTP server for health checks and metrics
    if args.enable_http:
        start_http_server(port=args.http_port)
        logger.info("HTTP server started on port {}", args.http_port)
    
    start_processes(...)
```

---

### Alternatywa: **http.server** (jeśli zero dependencies jest krytyczne)

Jeśli absolutnie nie chcemy żadnych dependencies, możemy użyć standard library:

```python
# src/dispatchbox/http_server.py
from http.server import HTTPServer, BaseHTTPRequestHandler
from prometheus_client import generate_latest
import json
import threading

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self._send_json({'status': 'ok'})
        elif self.path == '/ready':
            status = 200 if is_db_connected() else 503
            self._send_json({'status': 'ready' if status == 200 else 'not ready'}, status)
        elif self.path == '/metrics':
            self._send_metrics()
        else:
            self.send_response(404)
            self.end_headers()
    
    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def _send_metrics(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; version=0.0.4')
        self.end_headers()
        self.wfile.write(generate_latest())
    
    def log_message(self, format, *args):
        pass  # Disable default logging

def start_http_server(host='0.0.0.0', port=8080, daemon=True):
    server = HTTPServer((host, port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=daemon)
    thread.start()
    return thread
```

**Kod:** ~60-80 linii vs ~30 linii w Bottle

---

## Finalna rekomendacja

### **Bottle** dla większości przypadków

**Dlaczego:**
- Minimalny footprint (~50KB)
- Prosty kod (~30 linii vs ~80 w http.server)
- Automatyczny JSON
- Łatwy routing
- Zero config

**Kiedy użyć http.server:**
- Jeśli zero dependencies jest absolutnie krytyczne
- Jeśli projekt ma bardzo restrykcyjne wymagania co do dependencies

**Kiedy użyć FastAPI:**
- Jeśli planujemy dużo endpointów (DLQ API, admin panel, etc.)
- Jeśli potrzebujemy async
- Jeśli chcemy automatyczną dokumentację API

---

## Implementacja z Bottle

```python
# pyproject.toml
dependencies = [
    "psycopg2-binary>=2.9.0",
    "loguru>=0.7.0",
    "bottle>=0.12.25",  # ~50KB
    "prometheus-client>=0.18.0",  # dla metryk
]
```

**Kod:** ~50-100 linii dla pełnej implementacji (health, ready, metrics, opcjonalnie DLQ)

**Footprint:** ~50KB + prometheus-client (~200KB) = ~250KB total

---

## Podsumowanie

| Aspekt | Bottle | http.server | FastAPI |
|--------|--------|-------------|---------|
| **Dependencies** | ✅ Minimal | ✅ Zero | ❌ Duże |
| **Kod** | ✅ Prosty | ⚠️ Więcej | ✅ Prosty |
| **Features** | ✅ Wystarczające | ⚠️ Podstawowe | ✅ Pełne |
| **Maintenance** | ✅ Łatwe | ⚠️ Średnie | ✅ Łatwe |
| **Recomendacja** | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |

**Verdict:** **Bottle** jest najlepszym wyborem dla outbox worker - minimalny footprint, prosty kod, wystarczające features.

