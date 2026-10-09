# Analizy realizacji zadań — opis UI i metod

Zakładka analiz korzysta wyłącznie z planów, jednostek i zadań zwróconych przez usługę Access dla wybranego konta. Nie wykonuje własnych zapytań omijających Access.

## 1. Struktura realizacji zadań
- Wykres kołowy i tabela statusów uwzględniają wyłącznie zadania końcowe (liście hierarchii), aby nie liczyć zadania nadrzędnego razem z jego podzadaniami.
- Statusy: nierozpoczęte (pomarańczowy), rozpoczęte 0–25%, 25–50%, 50–75%, 75–99,9% (odcienie zieleni), zakończone (niebieski).
- Dla danych, które przechowują podzadania jako zagnieżdżone obiekty, helper spłaszcza je do liści i dziedziczy plan oraz przypisanie jednostki.

## 2. Czas realizacji i ryzyko terminu
- Tabela pokazuje najwyższy widoczny poziom zadania. Jeśli zadanie ma podzadania, jego podzadania nie są dodatkowo pokazywane w tej tabeli.
- Czas trwania to liczba dni od daty utworzenia do dnia analizy.
- Dla zadań rozpoczętych prognoza pozostałego czasu jest ekstrapolacją tempa od utworzenia: `pozostały czas = czas upływu × (1 − postęp) / postęp`.
- Zadanie zakończone ma zero dni prognozowanych do końca. Przy zerowym postępie albo braku daty utworzenia prognoza jest pusta, nie zgadywana.
- Status terminu: „Opóźnione” gdy termin minął, a zadanie nie jest zakończone; „Potencjalne” gdy prognozowana data ukończenia przekracza termin; „Brak” gdy prognoza mieści się w terminie lub zadanie jest zakończone. Brak terminu w danych jest jawnie oznaczony.

## 3. Możliwości jednostek
- Liczba zadań, postęp i tempo są liczone na liściach hierarchii.
- `Zadania / osoba` = liczba zadań / liczba pracowników; przy braku personelu wskaźnik jest pusty.
- Wydajność (0–100) jest względnym wynikiem porównawczym w widocznym zakresie: 45% tempa postępu, 30% średniego postępu, 25% liczby zadań na osobę. Większy przerób na osobę jest premiowany, ale odrębny wskaźnik ryzyka przeciążenia rośnie, gdy obciążeniu towarzyszą niski postęp i ryzyko terminów.
- Ryzyko przeciążenia jest heurystyką, nie diagnozą kadrową. Niski wynik wydajności jest zaznaczany na czerwono, ryzyko podwyższone pomarańczowo, wysokie czerwono.
- Korelacja personelu i postępu jest liczona współczynnikiem Pearsona na poziomie jednostek w aktualnym zakresie. Korelacja nie dowodzi przyczynowości.

## 4. Porównanie tego samego zadania
- Porównywane są zadania końcowe o identycznej nazwie, które występują w co najmniej dwóch jednostkach widocznych dla konta.
- UI pokazuje postęp, czas od utworzenia, tempo, prognozowany czas pozostały, personel jednostki i zadania na osobę.
- Porównanie tych samych zadań w wielu jednostkach nie jest obecnie prezentowane w UI, ponieważ źródło nie zapewnia wystarczających danych do rzetelnego benchmarku.

## 5. Zakres UI
- Usunięto sekcję sugestii przenoszenia wsparcia między jednostkami oraz porównanie tego samego zadania między jednostkami, ponieważ dostępne dane nie uzasadniają takich rekomendacji.

## Ograniczenia danych
- W danych demonstracyjnych dodano sztuczne terminy realizacji (część w najbliższym tygodniu, część w przyszłym roku, pozostałe w losowym zakresie, w tym kilka terminów już minionych). Nie są to terminy oficjalne. Nowe zadania bez podanego terminu nadal mogą mieć pustą datę.
- Jeżeli model źródłowy nie zawiera daty utworzenia, hierarchii podzadań, jawnych przypisań wielojednostkowych lub liczby personelu, nie da się wiarygodnie odtworzyć tych wartości z samego UI. Wskaźniki zależne od brakujących danych są puste albo opatrzone informacją o ograniczeniu.
- Wartości liczbowe prezentowane w tabelach są zaokrąglane do dwóch miejsc po przecinku.
