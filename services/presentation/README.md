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


## Integracja z warstwą dostępową

Interfejs Streamlit pobiera jednostki, plany, zadania i stan operacyjny z lokalnego API Presentation (`PRESENTATION_API_URL`). API prezentacji przekazuje żądania do Access Service, a nagłówek `X-Person-Id` jest przekazywany bez zmian. Lista kont demonstracyjnych pochodzi z endpointu `/api/demo-identities`, który korzysta z `/demo-identities` w serwisie access. Warstwa prezentacji nie łączy się bezpośrednio z Data Service.

Wybór konta w pasku bocznym jest mechanizmem demonstracyjnym, nie uwierzytelnianiem produkcyjnym. Endpoint `/demo-identities` należy zastąpić zaufanym dostawcą tożsamości lub wyłączyć przed wdrożeniem produkcyjnym.

## Widok jednostki i hierarchia planów

- „Plany tej jednostki” pokazuje wyłącznie plany przypisane bezpośrednio do wybranej jednostki.
- „Plany jednostek podległych” jest osobnym przeglądem i prezentuje jedynie plany oraz agregaty zadań dostępne dla bieżącej tożsamości.
- „Zadania tej jednostki” obejmuje tylko zadania z jej własnych planów. Zadania jawnie przypisane do jednostek podrzędnych nie są wliczane do szczegółowego widoku jednostki nadrzędnej.
- Każde zadanie jest prezentowane jako pojedynczy rozwijany element, który pobiera szczegóły z endpointu API. Usunięto osobny, powtarzający listę zadań widok „Wszystkie zadania”.
- „Hierarchia i wykonawcy” pozostaje widokiem nawigacyjnym planów; pokazuje strukturę, status, klauzulę i wykonawców bez ponownego renderowania list zadań. Plan O jest wyróżniony jako plan krajowy.
