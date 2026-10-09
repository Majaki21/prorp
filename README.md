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

Serwis `data` działa wyłącznie wewnątrz sieci Docker Compose i nie publikuje portu na hoście. Zewnętrzni klienci powinni korzystać z warstwy `access` na porcie `8002`:

- `GET http://localhost:8002/health` — stan serwisu dostępowego.
- `GET http://localhost:8002/plans` — plany dostępne dla bieżącej tożsamości; `GET /plans/O` — szczegóły dostępnego planu.
- `GET http://localhost:8002/units` — jednostki w zakresie dostępu.
- `GET http://localhost:8002/tasks?plan_id=ORW-PL-MZ` — dostępne zadania; obsługiwane filtry `unit_id`, `region_id` i `limit`.
- `GET http://localhost:8002/tasks/{plan_id}/{task_id}` — szczegóły zadania.
- `GET http://localhost:8002/state` — przefiltrowany stan operacyjny używany przez symulację.

Wewnętrzny serwis `data` udostępnia surowe endpointy na porcie `8000` tylko kontenerom w sieci Compose. Nie należy kierować do niego zewnętrznych klientów ani traktować go jako API publicznego.

Baza inicjalizuje się tylko wtedy, gdy tabela `plans` jest pusta. Zwykłe `docker compose down` nie usuwa wolumenu. Pełny reset danych demonstracyjnych: `docker compose down -v` (UWAGA: usuwa bazę). Aby ponownie wczytać nowy seed do pustej bazy, wykonaj reset wolumenu i `docker compose up --build`.

Dane statusów, budżetów, zasobów i przypisań są syntetyczne; nie stanowią rzeczywistych danych operacyjnych.

## Warstwa dostępowa (PoC)

Serwis `access` filtruje plany, zadania, jednostki i stan operacyjny według tożsamości osoby, hierarchii organizacyjnej, jawnie zapisanych relacji współpracy oraz klauzul tajności. Szczegóły endpointów, reguł i ograniczeń demonstracyjnych znajdują się w `services/access/README.md`.

W tej wersji `DEFAULT_PERSON_ID=demo-U-PRM` jest ustawione wyłącznie po to, aby istniejący interfejs demonstracyjny nadal działał bez ekranu logowania. To konto ma klauzulę `jawne`. W innych klientach można przekazać `X-Person-Id`. Przed rzeczywistym wdrożeniem należy zastąpić oba mechanizmy integracją z zaufanym dostawcą tożsamości.

## Scenariusz demonstracyjny kontroli dostępu

Przy starcie Data Service stosuje idempotentną konfigurację scenariusza PoC. W selektorze interfejsu dostępne są trzy rozróżnialne konta:

- `demo-premier` — Donald Tusk, konto demonstracyjne poziomu krajowego, klauzula `scisle_tajne`; widzi wszystkie jednostki, plany i zadania w demonstratorze.
- `demo-kgp` — Jan Kowalski, fikcyjna postać demonstracyjna Komendanta Głównego Policji, klauzula `tajne`; widzi planowanie Policji w swojej hierarchii.
- `demo-kgpsp` — Anna Nowak, fikcyjna postać demonstracyjna Komendanta Głównego PSP, klauzula `zastrzezone`; widzi planowanie PSP w swojej hierarchii.

Plany i zadania Policji (ORP/ORPP/ORPPP oraz PP/PPP/PPPP) są w tym scenariuszu oznaczone jako `tajne`; odpowiadające im plany i zadania PSP (ORS/ORSS/ORSSS oraz PS/PSS/PSSS) jako `zastrzezone`. Pozostałe dane zachowują poziom z seedów.

Relacja współpracy jest kierunkowa: `U-KGPSP` udostępnia `U-KGP` wyłącznie agregat postępu. Endpoint `GET /collaboration-summary` zwraca nazwę jednostki współpracującej i liczby agregatowe, bez identyfikatorów, nazw ani szczegółów poszczególnych zadań. Nie rozszerza ona zakresu dostępu do `/tasks`, `/plans` ani `/units`. W ten sposób KGP może zobaczyć np. liczbę zrealizowanych zadań PSP, a konto PSP nie otrzymuje analogicznego dostępu do danych Policji.

Konta i klauzule są syntetycznym scenariuszem hackathonowym, a nie rzeczywistą klasyfikacją informacji ani produkcyjnym systemem uwierzytelniania.
