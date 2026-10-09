# Integracja modułu analitycznego PRO RP

## Przepływ żądań

`Streamlit UI → Presentation API → Access Service → Analytics History API`

UI nie łączy się bezpośrednio z usługą analityczną ani z bazą SQLite. Access sprawdza tożsamość z nagłówka `X-Person-Id` i pośredniczy w żądaniach do modułu historii. Moduł analityczny pozostaje oddzielną usługą i przechowuje historię w osobnym wolumenie `analytics-history-data`; nie modyfikuje operacyjnej bazy PRO RP.

## Funkcje dostępne w zakładce „Analityk”

- podsumowanie snapshotu i średni postęp z podziałem na typ zadania,
- porównanie dwóch snapshotów (zmiana w punktach procentowych oraz zmiana względna),
- scenariusz liniowej ekstrapolacji postępu z wyborem snapshotu bazowego i horyzontu,
- wyraźne oznaczenie ograniczeń danych i metody.

## Zakres dostępu — istotne ograniczenie

Historia analityczna jest generowana z odseparowanej kopii danych operacyjnych; wcześniejsze punkty czasu są syntetycznym backfillem. Kopia zachowuje pola zadań, plany i jednostki, ale endpointy historii postępu nadal agregują według identyfikatora planu/typu zadania i nie implementują filtrowania każdej historycznej wartości według jednostki i klauzuli. Dlatego endpointy agregujące ten globalny zbiór są dostępne tylko w perspektywie krajowej (`demo-premier` / jednostka `U-PRM`). Pozostałe perspektywy zobaczą wyjaśnienie w UI, a Access zwróci HTTP 403, jeśli spróbują ominąć interfejs.

To celowe ograniczenie bezpieczeństwa, nie docelowy model autoryzacji analityki. Aby udostępnić analizy innym jednostkom, trzeba uzupełnić dane historyczne o wiarygodne powiązania z zadaniami, planami, jednostkami i klauzulami, a następnie filtrować dane przed agregacją. Samo ukrycie zakładki w UI nie jest kontrolą dostępu.

## Uruchomienie

```bash
docker compose up --build
```

UI: `http://localhost:8501`

Analytics History API nie jest publikowane bezpośrednio na hoście. Dostęp do funkcji analitycznych odbywa się przez Presentation API i Access.

## Interpretacja wyników

- `D` oraz `D+2` pozostają identyfikatorami zgodności: `D` oznacza stan z 2026-10-07, a `D+2` stan operacyjny z 2026-10-09. Pozostałe snapshoty stanowią syntetyczną historię dzienną przez 180 dni (181 punktów łącznie) dla wszystkich 100 zadań.
- Wzrost o `4 p.p.` oznacza np. przejście z 20% do 24%.
- Symulacja jest ekstrapolacją liniową z dwóch ostatnich snapshotów; historyczne punkty wstecz są syntetyczne (z okresami stagnacji i skokami) i nie stanowią rzeczywistych pomiarów ani zwalidowanej prognozy.
- Automatyczny zbiór postępu operacyjnego zapisuje tylko zadania widoczne dla skonfigurowanego `HISTORY_PERSON_ID`. W środowisku demonstracyjnym ustawiono `demo-premier`.
