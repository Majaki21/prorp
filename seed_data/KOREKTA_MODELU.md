# PRO RP — korekta modelu jednostek, planów i zadań

## Zasady docelowe uzgodnione z użytkownikiem

1. Jednostka jest instytucją (np. KPRM, MSWiA, KGP, urząd wojewódzki).
2. Hierarchia jednostek jest niezależnym, stałym drzewem: `Jednostka.id_jednostki_nadrzednej`.
3. Każda jednostka ma własny plan. Kod planu wynika z pełnej ścieżki hierarchii: jeden znak dla korzenia, dwa dla poziomu niżej, trzy dla następnego itd. Dzieci tej samej jednostki muszą mieć różne znaki na danym poziomie.
4. Plan zawiera zadania należące do jednostki-właściciela planu.
5. Plan może zawierać dyspozycje uruchomienia planów dzieci. Sama relacja rodzic–dziecko między planami nie oznacza jeszcze, że plan dziecka został uruchomiony.
6. Nie zapisujemy `id_jednostek` w zadaniu, jeśli zadanie należy do dokładnie jednego planu. Jednostkę wykonującą można wtedy wyprowadzić przez `zadanie -> plan -> jednostka`.

## Błędy wykryte w obecnym seedzie

- `ORW-PL-*` nie pasuje do opisanej konwencji kodowania literowego.
- Jeden plan regionalny jest przypisany jednocześnie urzędowi wojewódzkiemu, komendzie wojewódzkiej Policji i komendzie wojewódzkiej PSP, mimo że są w różnych gałęziach hierarchii jednostek.
- W `units.json` urzędy wojewódzkie mają rodzica `U-RCB`; to nie zgadza się z przykładową relacją podaną przez użytkownika i wymaga zastąpienia zgodnie z zatwierdzonym drzewem.
- KGP i KG PSP mają regionalne jednostki podrzędne, ale nie mają osobnych planów na własnym poziomie hierarchii.
- RCB występuje pod dwoma identyfikatorami (`U-RCB` oraz `U-PRM-002`). Ta sama instytucja nie powinna mieć dwóch rekordów jednostki.
- `tasks.json` zawiera `id_jednostek`; to pole dubluje odpowiedzialność, którą można ustalić przez plan. Należy je usunąć po migracji.
- `plans.json` zawiera `sporzadzil` jako tekst, zamiast stabilnego `id_jednostki` właściciela planu.

## Docelowy schemat

### Jednostka
- `id_jednostki`
- `nazwa`
- `id_jednostki_nadrzednej` (nullable dla korzenia)
- opcjonalnie: `typ`, `id_regionu`, metadane

### Plan
- `id_planu` (kod literowy)
- `id_jednostki` (właściciel; wymagany)
- `id_planu_nadrzednego` (nullable dla korzenia; odpowiada nadrzędności w drzewie)
- metadane planu

### Zadanie
- `id_zadania`
- `id_planu`
- `nazwa_zadania`, status, daty, zasoby itd.

### Dyspozycja uruchomienia
- `id_dyspozycji`
- `id_planu_zrodlowego`
- `id_planu_uruchamianego`
- `status` / `data_wydania` / `data_uruchomienia` (w zależności od wymagań)

## Co wymaga jeszcze jawnej decyzji

Nie przypisano automatycznie nowych kodów literowych ani nie przepisano wszystkich relacji nadrzędności, ponieważ przykłady nie definiują pełnej hierarchii wszystkich 64 jednostek. Trzeba najpierw zatwierdzić rzeczywiste drzewo i regułę nadawania pojedynczych liter dzieciom (np. czy `R` oznacza MSWiA, a `K` urząd marszałkowski, i jakie litery przypadają pozostałym jednostkom bezpośrednio pod KPRM). Automatyczne wygenerowanie kodów przed tą decyzją tworzyłoby arbitralne dane.

Wszystkie budżety, statusy, terminy, koszty i relacje wykonawcze w seedzie pozostają danymi demonstracyjnymi, nie oficjalnymi danymi operacyjnymi.
