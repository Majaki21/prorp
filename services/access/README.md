# Access Service

Serwis `access` jest punktem egzekwowania reguł dostępu. Odczytuje dane z `data`, ale udostępnia klientom tylko zakres dopuszczony przez tożsamość, hierarchię jednostek, jawnie zarejestrowane relacje współpracy oraz klauzule tajności.

## Tożsamość w PoC

- Nagłówek `X-Person-Id` wskazuje konto z tabeli `people`.
- Konta nieaktywne są odrzucane.
- `DEFAULT_PERSON_ID` jest opcjonalnym ułatwieniem demonstracyjnym, skonfigurowanym w `docker-compose.yml` jako `demo-U-PRM`, aby obecny interfejs działał bez formularza logowania. To **nie jest uwierzytelnianie produkcyjne**. Przed wdrożeniem należy usunąć tę zmienną i weryfikować tożsamość z zaufanego IdP/tokena; nie wolno ufać dowolnemu nagłówkowi ustawianemu przez niezaufanego klienta.

## Reguły PoC

1. Osoba widzi własną jednostkę i jednostki podrzędne.
2. Jednostka równoległa jest dostępna tylko przy istniejącym wpisie w `unit_cooperation`; współpraca jest jawna, nie wynika z podobieństwa nazw ani wspólnego regionu.
3. Klauzule są porządkowane od najniższej do najwyższej: `jawne`, `zastrzezone`, `poufne`, `tajne`, `scisle_tajne`.
4. Nieznana klauzula powoduje odmowę dostępu (fail closed).
5. Dostęp do zadania wymaga zarówno zakresu organizacyjnego, jak i dostępu do planu oraz odpowiedniej klauzuli planu i zadania.

## Endpointy

- `GET /me` — aktywna tożsamość
- `GET /state` — przefiltrowany stan dla symulacji
- `GET /plans` — widoczne plany
- `GET /tasks` — widoczne zadania (opcjonalne `plan_id`, `unit_id`)
- `GET /units` — widoczne jednostki; lista pracowników jest zwracana tylko dla własnej jednostki

Warstwa `data` nie publikuje portu hosta w Compose, aby zwykli klienci nie mogli ominąć kontroli w `access`.

## Ograniczenia demonstratora

Nagłówek identyfikacyjny i domyślne konto są wyłącznie mechanizmem PoC. Nie należy używać tej wersji do rzeczywistych informacji niejawnych. Brakuje integracji z PKI/IdP, audytu decyzji dostępowych, zarządzania zgodami na współpracę i formalnej walidacji polityki bezpieczeństwa.
