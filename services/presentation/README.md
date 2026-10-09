# Presentation Service v2

Warstwa prezentacji PRO RP.

## Funkcje

- dashboard KPI,
- tabela realizacji zadań,
- mapa Radomia,
- placeholdery lokalizacji,
- endpoint `/api/state`,
- endpoint `/api/simulations`,
- healthcheck.

## Porty

- `8000` — API Presentation Service
- `8501` — Streamlit UI

## Uruchomienie w całym systemie

W głównym `docker-compose.yml` należy dodać:

```yaml
presentation:
  build:
    context: .
    dockerfile: ./services/presentation/Dockerfile
  environment:
    ACCESS_SERVICE_URL: http://access:8000
    SIMULATION_SERVICE_URL: http://simulation:8000
  ports:
    - "8000:8000"
    - "8501:8501"
  depends_on:
    - access
    - simulation
```

Następnie:

```bash
docker compose up --build
```

UI:

```text
http://localhost:8501
```

API:

```text
http://localhost:8000
```

## Ważne

Mapa nie udaje, że obecny model posiada dokładną geometrię obiektów.
Pokazuje Radom jako obszar demonstracyjny oraz syntetyczne punkty.
Po rozszerzeniu kontraktu o `geometry` / `latitude` / `longitude`
placeholdery mogą zostać zastąpione rzeczywistymi danymi bez zmiany
pozostałych komponentów.
