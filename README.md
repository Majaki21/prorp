# PRO RP — Microservices PoC

Minimalny, niezależnie rozwijalny szkielet architektury:

- `presentation` — warstwa prezentacji/API agregujące dane
- `simulation` — silnik ćwiczeń/stress-testów
- `access` — warstwa dostępu, normalizacji i polityk
- `data` — aktualny stan operacyjny / repozytorium
- `shared` — wspólne kontrakty JSON/Pydantic
- `docker-compose.yml` — uruchomienie całego systemu

## Architektura

```text
                    +----------------------+
                    |     PRESENTATION     |
                    |  UI / API / map      |
                    +----------+-----------+
                               |
              +----------------+----------------+
              |                                 |
              v                                 v
     +----------------+                 +----------------+
     |     ACCESS     |                 |   SIMULATION   |
     | auth/adapters  |                 | scenario/game  |
     +-------+--------+                 +-------+--------+
             |                                  |
             v                                  v
     +----------------+                 +----------------+
     |      DATA      |<----------------| snapshot/read  |
     | operational DB |                 |                |
     +----------------+                 +----------------+
```

Serwis `data` używa trwałej bazy SQLite w wolumenie Dockera (`pro-rp-data`). Przy pierwszym uruchomieniu ładuje seed z `services/data/seed_data.json`; kolejne restarty zachowują zmiany w bazie. Dostępne są endpointy `/plans`, `/units`, `/tasks` i zgodnościowy `/state`.

## Uruchomienie

```bash
docker compose up --build
```

Healthchecki:

```bash
curl http://localhost:8000/health
curl http://localhost:8001/health
curl http://localhost:8002/health
curl http://localhost:8003/health
```

Porty:

| Service | Port | Rola |
|---|---:|---|
| presentation | 8000 | API prezentacyjne |
| simulation | 8001 | Simulation Engine |
| access | 8002 | Access Layer |
| data | 8003 | Operational Data |

## Przykładowy przepływ

```text
GET /api/state
presentation
    -> access /state
        -> data /state

POST /api/simulations
presentation
    -> simulation /simulations
        -> access /state
            -> data /state
        -> SimulationState
        -> SimulationResult
    -> presentation
```

## Ważna zasada

`OperationalState` i `SimulationState` są rozdzielone.

Symulacja pobiera snapshot aktualnego stanu i działa na jego lokalnej kopii. Symulacja nie może modyfikować rzeczywistego stanu operacyjnego.

## Rozwój

Każdy serwis ma własny katalog, Dockerfile i testy. Można rozwijać go niezależnie:

```bash
cd services/simulation
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
```

W przyszłości kontrakt HTTP można zastąpić gRPC/message brokerem bez zmiany modelu domenowego.


## Smoke test

After `docker compose up --build`:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/api/state
```

Example simulation:

```bash
curl -X POST http://localhost:8000/api/simulations \
  -H 'Content-Type: application/json' \
  -d '{
    "scenario": {
      "id": "scenario-001",
      "name": "Awaria infrastruktury",
      "description": "Demo",
      "failed_infrastructure": ["infra-001"]
    }
  }'
```

Expected behavior: Presentation calls Simulation, Simulation calls Access,
and Access calls Data. The operational state remains owned by Data and the
simulation operates on a snapshot.


## Dane demonstracyjne i trwałość

- `GET http://localhost:8003/health` pokazuje liczbę planów, jednostek i zadań.
- `GET http://localhost:8003/plans` — plany; `GET /plans/O` — plan i bezpośrednie podplany.
- `GET http://localhost:8003/units?region_id=PL-MZ` — jednostki w regionie.
- `GET http://localhost:8003/tasks?plan_id=ORW-PL-MZ` — zadania planu; dostępne filtry `unit_id` i `region_id`.
- `GET http://localhost:8003/state` — uproszczony kontrakt używany przez Access i Simulation.

Baza inicjalizuje się tylko wtedy, gdy tabela `plans` jest pusta. Zwykłe `docker compose down` nie usuwa wolumenu. Pełny reset danych demonstracyjnych: `docker compose down -v` (UWAGA: usuwa bazę). Aby ponownie wczytać nowy seed do pustej bazy, wykonaj reset wolumenu i `docker compose up --build`.

Dane statusów, budżetów, zasobów i przypisań są syntetyczne; nie stanowią rzeczywistych danych operacyjnych.

## Warstwa dostępowa (PoC)

Serwis `access` filtruje plany, zadania, jednostki i stan operacyjny według tożsamości osoby, hierarchii organizacyjnej, jawnie zapisanych relacji współpracy oraz klauzul tajności. Szczegóły endpointów, reguł i ograniczeń demonstracyjnych znajdują się w `services/access/README.md`.

W tej wersji `DEFAULT_PERSON_ID=demo-U-PRM` jest ustawione wyłącznie po to, aby istniejący interfejs demonstracyjny nadal działał bez ekranu logowania. To konto ma klauzulę `jawne`. W innych klientach można przekazać `X-Person-Id`. Przed rzeczywistym wdrożeniem należy zastąpić oba mechanizmy integracją z zaufanym dostawcą tożsamości.
