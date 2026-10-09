# PRO RP — oddzielna baza historii analitycznej

Ten komponent jest **oddzielony od bazy operacyjnej**. Nie modyfikuje tabel ani schematu istniejącej bazy PRO RP i nie zmienia UI.

## Dane zaimportowane
- Arkusz `D`: 100 zadań, stan początkowy.
- Arkusz `D+2`: te same 100 zadań, stan po dwóch dniach oraz kolumna `Zmiana`.
- Snapshoty w bazie: `D` (umownie 2026-10-07) i `D+2` (umownie 2026-10-09). Excel nie podaje konkretnych dat kalendarzowych; są to założenia demonstracyjne.
- `Zmiana` jest różnicą w skali 0–1, czyli np. `0.04` oznacza wzrost o **4 punkty procentowe**, nie względny wzrost o 4%.

Baza SQLite znajduje się w `data/analytics_history.db`.

## Uruchomienie lokalne
```bash
cd services/analytics_history
python -m venv .venv
# aktywuj środowisko w swoim systemie
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8010
```
API: `http://127.0.0.1:8010/docs`

## Endpointy
- `GET /health`
- `GET /history/snapshots`
- `GET /history/summary?snapshot_id=D%2B2`
- `GET /history/changes?from_snapshot=D&to_snapshot=D%2B2`
- `GET /history/tasks/PRZ-001`
- `POST /simulations/progress` z JSON `{"base_snapshot_id":"D+2","days_ahead":2}`
- `GET /simulations`

## Ponowny import Excela
```bash
python import_excel.py "/ścieżka/do/stan realizacji.xlsx" --date-d 2026-10-07 --date-d2 2026-10-09
```
Import dotyczy wyłącznie `analytics_history.db`. Zastępuje w niej snapshoty o identyfikatorach `D` i `D+2` oraz usuwa zapisane symulacje oparte na tych snapshotach; pozostałe tabele operacyjne nie są dotykane.

## Schemat
- `source_imports`: pochodzenie importu.
- `history_snapshots`: metadane snapshotów.
- `task_progress_history`: stan postępu zadania na snapshot.
- `simulation_runs`: zapis parametrów i wyników symulacji.

## Ważne ograniczenia
1. Dane są demonstracyjne, nie operacyjne.
2. Dwa snapshoty nie wystarczają do wiarygodnego modelu prognozującego; endpoint symulacji wykonuje prostą ekstrapolację liniową i wyraźnie to oznacza.
3. To API jest demonstratorem i nie zawiera uwierzytelniania. Nie wystawiać poza środowisko lokalne/deweloperskie ani nie podłączać do danych niejawnych bez kontroli dostępu, audytu i zatwierdzenia bezpieczeństwa.
4. W tej próbce nie ma jednostek organizacyjnych, budżetów, personelu ani lokalizacji. Analizy regionalne i budżetowe wymagają dodatkowych danych historycznych i autoryzowanego powiązania z jednostkami.


## Automatyczne zbieranie aktualnego stanu

Serwis może pobierać zadania z mikroserwisu `access` (a nie bezpośrednio z bazy operacyjnej).
W Docker Compose ustawiono kontrolę co 24 godziny:
- `ACCESS_SERVICE_URL=http://access:8000`
- `HISTORY_PERSON_ID=demo-U-PRM`
- `HISTORY_COLLECTION_INTERVAL_SECONDS=86400`

`HISTORY_PERSON_ID` musi wskazywać konto, którego zakres uprawnień obejmuje zadania przeznaczone do analizy. Wartość demonstracyjna w Compose służy wyłącznie lokalnemu PoC; przed użyciem z rzeczywistymi danymi należy skonfigurować zatwierdzone konto techniczne i odpowiednie uprawnienia. Historia nie powinna gromadzić danych poza dozwolonym zakresem.

Nowe endpointy:
- `POST /history/collect` — uruchom pojedynczą kontrolę ręcznie.
- `GET /history/collections` — historia udanych i nieudanych kontroli.
- `GET /history/tasks/{task_id}/timeline` — zapisane wartości bazowe i rzeczywiste zmiany zadania.
- `GET /history/state-at?at=2026-10-10T23:59:59%2B00:00` — ostatni znany stan każdego zadania na podany czas ISO 8601.

Każda udana kontrola trafia do `collection_runs`, nawet gdy postęp się nie zmienił. `task_state_events` otrzymuje wartość bazową przy pierwszym pomiarze, a potem tylko wtedy, gdy postęp faktycznie się zmieni. Nieudane pobranie jest odnotowywane jako `failed` i nie jest interpretowane jako brak zmian. Harmonogram można wyłączyć ustawiając `HISTORY_COLLECTION_INTERVAL_SECONDS=0`.

Uwaga: przykładowe konto w Compose może widzieć tylko część zadań ze względu na politykę dostępu. Przed użyciem należy sprawdzić zakres uprawnień konta technicznego. Harmonogram wykonuje pierwszy pomiar przy starcie serwisu, a kolejne po upływie skonfigurowanego interwału.
