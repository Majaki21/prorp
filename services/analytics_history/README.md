# PRO RP — oddzielna baza historii analitycznej

Ten komponent jest **oddzielony od bazy operacyjnej**. Nie modyfikuje tabel ani schematu istniejącej bazy PRO RP i nie zmienia UI.

## Dane analityczne — kopia operacyjna i historia

Moduł analityczny korzysta z osobnej kopii `data/operational_seed_data.json` utworzonej z `seed_data/seed_data.json`. Kopia obejmuje wszystkie sekcje danych operacyjnych (plany, jednostki, zadania, infrastrukturę, dyspozycje, osoby i współpracę) i nie jest używana przez operacyjne API. Oryginalne pliki operacyjne nie są modyfikowane.

Historia postępu jest budowana dla wszystkich 100 zadań operacyjnych: 180 dni syntetycznej historii dziennej od 2026-04-12 do 2026-10-09 włącznie. Łącznie daje to 181 snapshotów i 18 100 rekordów historii postępu (100 zadań × 181 dni). Najnowszy punkt każdego zadania dokładnie odpowiada `poziom_realizacji` w kopii operacyjnej. Wartości sprzed bieżącego stanu są **syntetycznym backfillem demonstracyjnym** z indywidualnym tempem, okresami stagnacji i skokami postępu, a nie rzeczywistymi pomiarami historycznymi. Dane są deterministyczne, więc odtworzenie historii daje te same wyniki.

Baza SQLite znajduje się w `data/analytics_history.db`. Przy starcie serwis idempotentnie przygotowuje dane w tej wyłącznie analitycznej bazie. Import i migracja nie zmieniają operacyjnej bazy PRO RP ani jej plików seed.

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
- `GET /history/tasks/OR:PRZ-001`
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
1. Dane operacyjne są kopiowane do odseparowanego pliku analitycznego; wcześniejsze punkty historii są syntetyczne, nie są rzeczywistymi pomiarami.
2. Dwa snapshoty nie wystarczają do wiarygodnego modelu prognozującego; endpoint symulacji wykonuje prostą ekstrapolację liniową i wyraźnie to oznacza.
3. To API jest demonstratorem i nie zawiera uwierzytelniania. Nie wystawiać poza środowisko lokalne/deweloperskie ani nie podłączać do danych niejawnych bez kontroli dostępu, audytu i zatwierdzenia bezpieczeństwa.
4. Kopia operacyjna zawiera jednostki organizacyjne, budżety, personel i inne encje, ale bieżąca tabela historii mierzy wyłącznie postęp zadań; historia budżetów, zasobów i statusów nie jest jeszcze modelowana jako szeregi czasowe. Analizy regionalne i budżetowe wymagają dodatkowych danych historycznych i autoryzowanego powiązania z jednostkami.


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
