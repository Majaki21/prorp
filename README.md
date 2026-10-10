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

## Cykl życia planów (aktualizacja PoC)

- `status_operacyjny` rozdziela stan operacyjny (`prepared` / `active`) od formalnego `status_planu`.
- Zadania mają `typ_zadania` (`PRZ` / `REAL`). W nieaktywnych planach REAL są zaplanowane i mają 0%; PRZ zachowują postęp przygotowania.
- `POST /api/plans/{plan_id}/activate` aktywuje wskazany plan i całe poddrzewo. Nie wymaga 100% przygotowania; warstwa Access sprawdza uprawnienie jednostki właścicielskiej lub bezpośrednio nadrzędnej.
- `PATCH /api/tasks/{plan_id}/{task_id}/progress` umożliwia aktualizację REAL dopiero po aktywacji i tylko jednostce, do której zadanie jest przypisane.
- Interfejs zawiera osobne widoki „Plany przygotowane” i „Plany aktywne”. Procent przygotowania opiera się na PRZ, a operacyjna realizacja na REAL.
- Aktywacje są rejestrowane w tabeli `plan_activation_audit`.

## UI: przebudowany cykl planistyczny

Warstwa Streamlit jest podzielona na cztery główne obszary:

- **Obraz sytuacji** — aktywne plany, postęp zadań, zadania wymagające uwagi i budżet jednostek w aktualnym zakresie.
- **Zadania** — filtrowalny rejestr zadań oraz karta szczegółów. Postęp PRZ można raportować po zatwierdzeniu planu, a postęp REAL po aktywacji planu; zapis jest egzekwowany przez Access.
- **Plany** — lista planów, tworzenie projektów planów, wymogi kierowane do bezpośrednio podległych jednostek, przekazanie do zatwierdzenia, akceptacja i aktywacja.
- **Mapa** — podkład mapowy bez fikcyjnych markerów. Markery pojawią się tylko wtedy, gdy źródłowe dane zawierają współrzędne.

Model planu zawiera `data_przegladu` i `wymogi_json`. Kolejny przegląd jest sygnalizowany w UI, ale nie jest traktowany automatycznie jako wygaśnięcie planu. Zapis projektu, wymogów, przekazania i zatwierdzenia odbywa się przez Presentation API i Access, a dopiero potem w Data Service.

Po zmianie kodu uruchom ponownie środowisko:

```bash
docker compose up --build
```

UI: http://localhost:8501 · Presentation API: http://localhost:8000/health

Testy w tym środowisku: `pytest -q` (31 testów). W środowisku implementacyjnym nie było dostępnego polecenia Docker, więc nie wykonano tutaj testu uruchomienia całego stosu w kontenerach.

## Raportowanie rzeczywiste z wykonania zadania

W widoku **Zadania → Szczegóły zadania** uprawniona jednostka może rozwinąć formularz **Złóż raport rzeczywistego wykonania**. Raport zawiera opis wykonanych czynności, postęp po raporcie, przeszkody/ryzyka, potrzebne wsparcie oraz przewidywany termin zakończenia. Raport jest zapisywany w tabeli `task_reports`, a postęp zadania aktualizowany w tej samej transakcji. Historia raportów jest dostępna w szczegółach zadania.

Zapisy raportów przechodzą przez Presentation → Access → Data. Warstwa Access sprawdza widoczność zadania, poziom dostępu, własność zadania i stan planu; identyfikator oraz nazwę autora bierze z uwierzytelnionej tożsamości przekazanej do Access, a nie z pól formularza. Zadania REAL można raportować po aktywacji planu, a PRZ po zatwierdzeniu planu.

## Scenariusz demonstracyjny „Powódź” — widok ról

W zakładce **Symulacja** można przejść przez przygotowania do powodzi i aktywację planów. Stan scenariusza jest nakładką w bieżącej sesji Streamlit, dzięki czemu te same postępy są widoczne w zakładkach **Plany**, **Zadania** i **Analizy operacyjne** po przełączeniu konta demonstracyjnego.

- **Premier RP**: widzi perspektywę krajową i aktywację planu koordynacji krajowej `O`.
- **Komendant Główny PSP**: widzi własny zakres i aktywację planów PSP `PS`, `PSS`, `PSSS`.
- Przed nadejściem fali zadania `PRZ-*` przechodzą od 0% do zakończenia, a zadania `REAL-*` pozostają zaplanowane.
- Po nadejściu fali plany demonstracyjne przechodzą w stan aktywny, a postęp zadań `REAL-*` rośnie wraz z dalszym czasem symulacji.
- **Reset** przywraca początkowy stan symulacji. Scenariusz nie zapisuje statusów ani postępu do operacyjnej bazy danych.

To celowy tryb demo, a nie trwała aktywacja planów w środowisku operacyjnym.
