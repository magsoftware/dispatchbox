# Dlaczego nie używam dekoratorów Bottle w HttpServer?

## Obecne podejście

```python
class HttpServer:
    def __init__(self, ...):
        self.app = Bottle()
        self._setup_routes()
    
    def _setup_routes(self):
        self.app.get("/health")(self._health)  # Funkcyjne rejestrowanie
        self.app.get("/ready")(self._ready)
    
    def _health(self):
        return {"status": "ok"}
```

## Alternatywa z dekoratorami

```python
class HttpServer:
    def __init__(self, ...):
        self.app = Bottle()
        self._setup_routes()
    
    def _setup_routes(self):
        # Dekoratory wymagają self.app jako kontekstu
        @self.app.get("/health")
        def health():
            return {"status": "ok"}
        
        @self.app.get("/ready")
        def ready():
            # Problem: jak dostać się do self.db_check_fn?
            # Trzeba użyć closure lub lambda
            if self.db_check_fn:
                ...
```

## Problem z dekoratorami w klasie

### 1. **Dostęp do `self` w dekoratorach**

Gdy używamy dekoratorów wewnątrz metody klasy, funkcje są zdefiniowane lokalnie i nie mają bezpośredniego dostępu do `self`:

```python
def _setup_routes(self):
    @self.app.get("/health")
    def health():
        # ❌ Nie mam dostępu do self!
        return {"status": "ok"}
```

**Rozwiązanie:** Closure lub lambda:

```python
def _setup_routes(self):
    @self.app.get("/health")
    def health():
        return self._health()  # ✅ Działa, ale to wrapper
    
    # LUB bezpośrednio:
    @self.app.get("/health")
    def health():
        return {"status": "ok"}  # ✅ Działa, ale nie ma dostępu do self.db_check_fn
```

### 2. **Warunkowe rejestrowanie route'ów**

Obecne podejście:
```python
if self.metrics_fn:
    self.app.get("/metrics")(self._metrics)  # ✅ Proste warunkowe
```

Z dekoratorami:
```python
if self.metrics_fn:
    @self.app.get("/metrics")
    def metrics():
        return self.metrics_fn()  # ✅ Działa, ale mniej czytelne
```

### 3. **Testowanie**

Obecne podejście:
```python
# Łatwo mockować lub podmienić
server.app.get = Mock()
server._health()  # ✅ Można testować bezpośrednio
```

Z dekoratorami:
```python
# Trudniejsze - funkcje są zagnieżdżone w _setup_routes
# Trzeba testować przez app, nie bezpośrednio metody
```

## Kiedy dekoratory mają sens?

Dekoratory są lepsze gdy:
1. **Funkcje są na poziomie modułu** (nie w klasie)
2. **Nie potrzebujesz dostępu do stanu klasy**
3. **Chcesz bardziej deklaratywny kod**

Przykład (moduł-level):
```python
# http_server.py (moduł-level, nie klasa)
app = Bottle()

@app.get('/health')
def health():
    return {'status': 'ok'}

@app.get('/ready')
def ready():
    if is_db_connected():
        return {'status': 'ready'}
    response.status = 503
    return {'status': 'not ready'}
```

## Dlaczego wybrałem obecne podejście?

1. ✅ **Jasny dostęp do `self`** - metody klasy mają pełny dostęp do atrybutów
2. ✅ **Łatwiejsze testowanie** - metody można testować bezpośrednio
3. ✅ **Warunkowe route'y** - łatwo dodać route tylko jeśli funkcja jest dostępna
4. ✅ **Czytelność** - wyraźnie widać że metody są częścią klasy
5. ✅ **Spójność** - wszystkie metody są w jednej klasie, nie rozproszone

## Czy powinienem zmienić na dekoratory?

**Odpowiedź: NIE** - obecne podejście jest lepsze dla tego przypadku, bo:

1. **Mamy klasę z stanem** (`db_check_fn`, `metrics_fn`) - dekoratory wymagałyby closure'ów
2. **Warunkowe route'y** - łatwiej z funkcjonalnym podejściem
3. **Testowanie** - metody klasy są łatwiejsze do testowania

## Alternatywa: Hybrydowe podejście

Można użyć dekoratorów, ale z wrapperami:

```python
def _setup_routes(self):
    @self.app.get("/health")
    def health():
        return self._health()
    
    @self.app.get("/ready")
    def ready():
        return self._ready()
    
    if self.metrics_fn:
        @self.app.get("/metrics")
        def metrics():
            return self._metrics()
```

**Ale to dodaje tylko boilerplate** - wrapper funkcje, które wywołują metody klasy. Obecne podejście jest prostsze.

## Podsumowanie

| Aspekt | Funkcyjne (`app.get()(method)`) | Dekoratory (`@app.get()`) |
|--------|--------------------------------|---------------------------|
| **Dostęp do `self`** | ✅ Bezpośredni | ⚠️ Wymaga closure |
| **Warunkowe route'y** | ✅ Proste | ⚠️ Trudniejsze |
| **Testowanie** | ✅ Łatwe (bezpośrednie) | ⚠️ Przez app |
| **Czytelność** | ✅ Jasne | ⚠️ Zagnieżdżone |
| **Boilerplate** | ✅ Minimalny | ⚠️ Więcej kodu |

**Verdict:** Obecne podejście jest lepsze dla klasy z stanem. Dekoratory są lepsze dla moduł-level funkcji.

