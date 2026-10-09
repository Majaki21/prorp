# Integracja analizy z hack1

## Co zostało połączone
- Skopiowano `services/analytics_history/` z paczki analitycznej do głównego projektu.
- Dodano usługę `analytics-history` do głównego `docker-compose.yml` oraz wolumen `analytics-history-data`.
- Dopisano opis uruchomienia i ograniczeń do `README.md`.
- Nie zmieniano kodu operacyjnej bazy, warstwy dostępu, symulacji ani UI.

## Jak uruchomić
W katalogu głównym projektu:
```bash
docker compose up --build
```
API historii: http://localhost:8010/docs

## Gdzie pliki zostały dodane
- `services/analytics_history/app/main.py` — API historii i demonstracyjnej prognozy.
- `services/analytics_history/import_excel.py` — import arkuszy `D` i `D+2`.
- `services/analytics_history/data/stan realizacji.xlsx` — źródłowy Excel analizy.
- `services/analytics_history/data/analytics_history.db` — demonstracyjna baza historii.
- `services/analytics_history/Dockerfile` i `requirements.txt` — konfiguracja serwisu.
- `services/analytics_history/tests/test_history_api.py` — testy.
- `docker-compose.yml` — konfiguracja uruchamiania nowej usługi.
- `README.md` — instrukcja użycia.

## Ocena merytoryczna
Kierunek ma sens: historia postępu jest trzymana w osobnej bazie, więc nie narusza danych operacyjnych. Import sprawdza zgodność identyfikatorów i obliczeń w arkuszach, a API rozróżnia zmianę w punktach procentowych od zmiany względnej. Zbieranie cykliczne zapisuje stan bazowy i późniejsze rzeczywiste zmiany.

Ograniczenia do pamiętania:
1. `D` i `D+2` są datami demonstracyjnymi przyjętymi w kodzie (2026-10-07 i 2026-10-09), a nie datami potwierdzonymi przez sam Excel.
2. Prognoza jest liniową ekstrapolacją na podstawie tylko dwóch punktów — nie jest wiarygodnym modelem predykcyjnym.
3. Dane z Excela nie są automatycznie łączone z zadaniami operacyjnymi PRO RP. To dwa źródła w jednej usłudze.
4. Zbieranie z Access zapisuje wyłącznie zadania widoczne dla `HISTORY_PERSON_ID`; konto demonstracyjne może nie mieć pełnego zakresu.
5. Serwis nie został połączony z UI Streamlit; działa jako oddzielne API na porcie 8010.
6. `GET /history/state-at` przyjmuje czas ISO, ale zapytanie porównuje znaczniki czasu tekstowo. Dla spójności używaj zawsze jednakowego formatu/strefy (najlepiej UTC), albo popraw implementację na porównanie znormalizowanych czasów.
