# Zmiany UI PRO RP

## Obraz sytuacji
- Usunięto kafelki „Zadania REAL” i „Średnia realizacja REAL”.
- Zadania wymagające uwagi są prezentowane w osobnych, obramowanych boksach.
- Jednostki bezpośrednio podległe są prezentowane jako klikalne karty. Kliknięcie przełącza zakres obrazu sytuacji i pozostałych widoków na wybraną jednostkę.
- Pod tytułem aplikacji prezentowany jest aktualny poziom widoku.
- Wybór zakresu jest dostępny dla wszystkich kont demonstracyjnych, ale ograniczony do własnej jednostki i jej bezpośrednich podwładnych; Premier ma dodatkowo widok krajowy.

## Plany i cykl planistyczny
- Premier jest przypisany do węzła koordynacyjnego Prezes Rady Ministrów / Rada Ministrów (U-PRM), a nie do KPRM. Może aktywować plan własny lub plan jednostki bezpośrednio podległej; Access egzekwuje tę regułę.
- Kod planu podrzędnego jest budowany z kodu planu nadrzędnego i jednej wielkiej litery (np. `O` → `OR`). Walidacja jest w UI, Access i Data.
- Wymogi planistyczne są definiowane oddzielnie dla każdej wybranej jednostki, z osobnym opisem i terminem.
- Rozwinięcie planu pokazuje realizację planów jednostek bezpośrednio podległych, bez rozwijania dalszych poziomów.

## Dostęp
- Widoki szczegółowe pozostają ograniczone do własnej jednostki i jednostek bezpośrednio podległych. Nie dodano agregowania szczegółów z dalszych szczebli.
- Zmiany uprawnień operacyjnych są egzekwowane w Access; UI nie omija warstwy dostępowej.

## Weryfikacja
- Testy: `pytest -q`.
- Składnia Python: `python -m compileall -q services`.
- Pełny stack Docker należy uruchomić lokalnie poleceniem `docker compose up --build`; ten pakiet był walidowany testami i statycznie, bez uruchomienia kompletnego stacka.

## Dodatkowe poprawki — obsługa zakresu, tworzenie zadań i realizacja planu

- Naprawiono przełączanie zakresu z przycisku „Otwórz obraz sytuacji” poprzez callback Streamlit `on_click`; stan klucza selectboxa nie jest już zmieniany po utworzeniu widgetu.
- W widoku „Zadania” dodano podkartę „Dodaj zadanie”. Formularz wymaga wyboru planu, przypisuje zadanie do jednostki będącej właścicielem planu i rozróżnia typy PRZ/REAL według stanu planu.
- Dodawanie zadania ma dedykowany endpoint w Presentation → Access → Data. Nie zapisuje całego planu ponownie, dzięki czemu istniejące zadania i ich postęp pozostają bez zmian. Access sprawdza właściciela planu i reguły PRZ/REAL.
- Karty realizacji planu przez jednostki bezpośrednio podległe pokazują status zatwierdzenia i datę, stan aktywności oraz procent zadań zakończonych: PRZ dla planu nieaktywnego, REAL dla aktywnego. Usunięto komunikaty „Nieaktywny operacyjnie” i powtarzające się wyjaśnienia o braku raportowania REAL.
- Po przejściu do widoku wybranej jednostki lista „Jednostki w zakresie” nie pokazuje ponownie jednostek z poprzedniego poziomu.
- Testy: 47/47 zakończonych powodzeniem; kompilacja składniowa Pythona również przechodzi. Pełny stos kontenerów nie był uruchamiany end-to-end.


## Ostatnie poprawki UI i cyklu planistycznego

- Usunięto z modelu demonstracyjnego duplikat jednostki KPRM; plan O należy do węzła koordynacyjnego Prezes Rady Ministrów / Rada Ministrów. Migracja aktualizuje również istniejący wolumen SQLite.
- Dodawanie zadań PRZ działa również dla zatwierdzonego, ale nieaktywnego operacyjnie planu. Zadania REAL nadal wymagają aktywnego planu.
- Rejestr zadań ma filtr po planie, zadania REAL są sortowane na górze i wyróżnione żółtym kolorem, a szczegóły wybiera się najpierw przez plan, potem przez zadanie.
- Aktywne plany mają niebieskie wyróżnienie i pokazują wyłącznie realizację operacyjną REAL, bez statusu przygotowania PRZ. Aktywacja jest jednokierunkowa: zakończenie zadań nie kończy planu.
- Dodano panel hierarchii po prawej stronie, z drzewem do dwóch poziomów i klikalnymi jednostkami zmieniającymi zakres prezentacji. To nie zmienia tożsamości ani uprawnień konta.
- Udostępniono jednostce kod planu nadrzędnego potrzebny do tworzenia kolejnych kodów hierarchicznych; przy odczycie wymogów z planu nadrzędnego jednostka widzi wyłącznie wymóg skierowany do niej.


## Poprawki nawigacji i aktywacji (kolejna iteracja)

- Hierarchię przeniesiono z panelu bocznego do pełnej zakładki „Hierarchia” umieszczonej za „Analitykiem”. Panel boczny nie zawiera już drzewa hierarchii.
- Zmiana konta demonstracyjnego resetuje zakres widoku do jednostki przypisanej do wybranego konta. Po przełączeniu na Premiera domyślnie wyświetla się węzeł U-PRM; „Przegląd krajowy” pozostaje dostępny jako osobny zakres.
- Premier może aktywować plany własne oraz plany jednostek bezpośrednio podległych z perspektywy krajowej i U-PRM. UI pokazuje przycisk zgodnie z tą regułą, a Access weryfikuje relację hierarchiczną.
