# PRO RP UI — poprawki

## Naprawione problemy

1. **Przegląd krajowy:** usunięto warunkowe wyrażenia wyświetlające zwracany obiekt `DeltaGenerator`; tabele renderują się przez jawne `if/else`.
2. **Wymogi dla jednostek podrzędnych:** wymogi są częścią jednego formularza tworzenia/edycji planu i zapisywane razem z nim. Wybór obejmuje wiele bezpośrednio podległych jednostek. API Access sprawdza zakres jednostek, a endpoint wymogów zwraca tylko wymogi skierowane do jednostki użytkownika i czytelne według klauzuli.
3. **Plany i cykl planistyczny:** dodano barwne statusy zadań PRZ: zielony dla 100%, żółty dla 50–99%, czerwony poniżej 50%. Postęp REAL nie jest pokazywany w karcie planu przed aktywacją operacyjną.
4. **Formularz planu:** etykieta pola to „Plan nadrzędny”; zadania dodaje się w dynamicznym edytorze tabelarycznym; wymogi konfiguruje się w tym samym formularzu; wersję roboczą można trwale zapisać i edytować, a po uzupełnieniu utworzyć z niej projekt planu.
5. **Wymogi i akceptacja:** widok pokazuje otrzymane wymogi oraz plany jednostek bezpośrednio podległych, także wtedy, gdy nie są jeszcze przekazane do zatwierdzenia. Akcja zatwierdzenia pojawia się wyłącznie dla planu ze statusem `in_review`.
6. **Przegląd krajowy i plany własne:** własne plany konta krajowego są dostępne w obszarze „Plany”, bez agregowania zadań jednostek niższego szczebla do przeglądu krajowego.

## Zapis wersji roboczej

Wersja robocza jest zapisywana trwale w źródle danych jako `status_planu=editing`. Można ją ponownie otworzyć i edytować. Przycisk „Utwórz projekt planu” zmienia jej status na `draft`; dopiero taki projekt można przekazać do zatwierdzenia.

## Testy

- `python -m compileall -q services`
- `pytest -q` — 32 testy przechodzą.

Nie wykonano testu pełnego stosu przez Docker w tym środowisku.
