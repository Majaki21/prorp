# Analizy operacyjne — PRO RP (prototyp)

Moduł jest przygotowany po stronie backendu i **nie jest podłączony do UI**.

## Źródła danych
- `data/operational_seed_data.json` — odizolowana kopia operacyjnego seed: plany, jednostki, zadania, budżety, zasoby, statusy.
- `data/analytics_history.db` — 181 dziennych snapshotów dla 100 zadań (18 100 rekordów historii). Wcześniejsze punkty są syntetyczne i służą demonstracji.
- Oryginalne dane operacyjne nie są modyfikowane.

## Analizy
1. **Czas realizacji per zadanie** — dni od daty utworzenia do daty analizy; dla zadań zakończonych to czas do ukończenia (jeżeli stan wskazuje 100%), dla otwartych: estymacja całkowitego czasu i pozostałych dni na podstawie mediany dodatniego tempa z ostatnich 14 dni.
2. **Czas realizacji per jednostka i plan** — średni czas od utworzenia i średni szacowany czas całkowity, plus liczba zadań i średni postęp.
3. **Benchmark jednostek** — ranking średniego postępu i tempa. Benchmark *identycznego zadania* między jednostkami jest celowo pusty, bo aktualne dane przypisują każde zadanie do jednej jednostki. Nie tworzymy fałszywych par porównawczych.
4. **Personel a postęp** — korelacja Pearsona: liczebność personelu vs średni postęp oraz liczba zadań na osobę vs postęp. To korelacja opisowa, nie wniosek przyczynowy.
5. **Wąskie gardła/przeciążenie** — heurystyczny wskaźnik łączący liczbę zadań na osobę, średni postęp i udział zadań poniżej 50%; dodatkowo relacja zapotrzebowania personelu z zadań do personelu jednostki.
6. **Jednostki o wysokiej efektywności** — ranking złożony ze średniego postępu, szacowanego czasu pozostałego i obciążenia zadaniami na osobę. Wynik to ranking demonstracyjny, nie audyt efektywności.
7. **Ryzyko budżetowe** — suma planowanych kosztów przypisanych zadań porównana z budżetem jednostki. `koszt` traktowany jest jako planowany koszt całkowity zadania, a nie wydatek już poniesiony.
8. **Postęp planów** — średni postęp, liczba ukończonych zadań, liczba zadań poniżej 50% i łączny koszt na plan.
9. **Dodatkowa analiza: stagnacja** — zadania, których postęp zmienił się o najwyżej 1 p.p. w ostatnich 7 interwałach historii.
10. **Dodatkowa analiza: zadania zagrożone** — zadania z postępem poniżej 50% po co najmniej 14 dniach od utworzenia.
11. **Lejek realizacji** — ukończone, w toku, nierozpoczęte, poniżej 50% po 14 dniach oraz liczba zadań ze stagnacją.
12. **Kontrola przypisań** — nieprzypisane zadania i wykrywanie powielonych identyfikatorów jednostek.

## Endpointy (bez integracji z UI)
- `GET /analysis/operational` — komplet wyników.
- `GET /analysis/operational/durations` — czasy zadań i podsumowania per jednostka/plan.
- `GET /analysis/operational/units` — wskaźniki jednostek.
- `GET /analysis/operational/staffing` — korelacje z personelem.
- `GET /analysis/operational/bottlenecks` — wąskie gardła.
- `GET /analysis/operational/efficiency` — ranking efektywności.
- `GET /analysis/operational/budget-risks` — ryzyko budżetowe.
- `GET /analysis/operational/plans` — postęp planów.
- `GET /analysis/operational/additional` — stagnacja, zadania zagrożone, lejek i nieprzypisane zadania.

## Ważne ograniczenia
- Wszystkie wyniki odnoszą się do syntetycznych danych prototypu.
- Koszty nie są rzeczywistymi wydatkami ani prognozą księgową.
- Pole `zasoby.personel` przy zadaniu jest traktowane jako zapotrzebowanie personelu; to założenie demonstracyjne.
- Budżet i personel mogą nie być porównywalne między jednostkami bez wspólnej definicji, okresu i zakresu.
- W seedzie jest powielony identyfikator źródłowy `U-PRM`; w wynikach analitycznych kolidujące jednostki dostają rozróżniające klucze `U-PRM::...`, aby nie scalać ich przez pomyłkę.
- Identyczne zadania nie są powielone między jednostkami. Do rzeczywistego rankingu „kto szybciej wykonuje to samo zadanie” trzeba dodać zadania wspólne albo jednoznaczną klasę porównywalności.


## Benchmark identycznych zadań między jednostkami (tryb demonstracyjny)

Raport `same_task_unit_benchmarks` zawiera teraz analityczne kopie do 20 szablonów zadań przypisane do innych jednostek. Kopie mają jawne oznaczenia `analysis_only_copy`, `source_task_id` i `synthetic_scenario_factor`; różnice postępu/tempa są scenariuszem syntetycznym. Nie są dopisywane do danych operacyjnych ani bazy historii i nie wpływają na raporty obciążenia, personelu ani budżetu. W metadanych zwracane są liczba kopii oraz informacja o ich charakterze. Nie należy interpretować tych wyników jako rzeczywistych wyników jednostek.
