# PRO RP — seed danych demonstracyjnych (struktura instytucji PoC)

## Zawartość
- `units.json` — uproszczone drzewo instytucji państwowych i wybranych podmiotów publicznych.
- `plans.json` — 25 planów w pięciu niezależnych rodzinach: O, P, R, S, T. Kody niższych poziomów są tworzone przez dopisywanie liter do kodu planu nadrzędnego (np. O → OR → ORP → ORPP → ORPPP).
- `tasks.json` — 100 zadań z dotychczasowego seed, przypisanych do planów; pole `id_jednostek` pozostaje puste dla zgodności ze starym schematem SQLite, ale nie jest źródłem odpowiedzialności.
- `seed_data.json` — całość w jednym pliku, w tym przykładowe dyspozycje uruchomienia planów.
- `validate_seed.py` — kontrola spójności.

## Ważne rozróżnienie
To **model operacyjny PoC**, a nie oficjalna mapa podległości prawnej. Nazwy instytucji są rzeczywiste, ale przypisanie KPRM → MSWiA oraz wybrane ścieżki koordynacji służą demonstracji planowania. W realnym ustroju ministerstwa, administracja rządowa terenowa i samorząd województwa mają odrębne podstawy organizacyjne; urząd marszałkowski nie podlega wojewodzie. Węzeł Prezesa RM/Rady Ministrów jest abstrakcją koordynacyjną, nie urzędem nadrzędnym dla wszystkich tych podmiotów w sensie prawnym. Policja jest podległa ministrowi właściwemu do spraw wewnętrznych, a KGP opisuje własną strukturę i szczeble wojewódzkie/powiatowe.

Budżety, zasoby, terminy, statusy, postęp i mapowanie zadań na plany są syntetyczne. Nazwy zadań pochodzą z przekazanych arkuszy. Dane nie są oficjalnymi planami ani danymi operacyjnymi.

## Walidacja
`python validate_seed.py`

## Aktualizacja istniejącej bazy
Serwis danych zasila SQLite wyłącznie wtedy, gdy tabela `plans` jest pusta. Aby załadować nowy seed do istniejącej instancji, należy zresetować wolumen (`docker compose down -v`) i uruchomić ponownie `docker compose up --build`. Uwaga: `down -v` usuwa zapisane dane z wolumenu.
