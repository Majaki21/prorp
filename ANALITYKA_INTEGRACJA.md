# Integracja analityki PRO RP

Projekt zachowuje nowe UI z `prorp-final-bugs-fixed.zip` oraz pełny moduł analityczny z `prorp_analityka.zip`. W interfejsie demonstracyjnym pozostawiono widok **Analizy operacyjne** (analiza aktualnych zadań, terminów, obciążenia, efektywności, ryzyk i struktury realizacji). Widok **Historia i scenariusze** został usunięty z nawigacji jako ekran debugowania; usługa historii pozostaje w repozytorium. Widok **Hierarchia** i pozostałe elementy nowszego UI pozostają zachowane.

## Architektura

`Streamlit UI → Presentation API → Access → Analytics History API`. UI nie łączy się bezpośrednio z bazą analityczną. Oddzielna usługa `analytics-history` używa wolumenu `analytics-history-data`, zawierającego `analytics_history.db` oraz `operational_analytics.db`; kopia danych operacyjnych jest odseparowana od bazy usług operacyjnych PRO RP.

## Zakres analityki

- Struktura postępu zadań, z liczeniem zadań końcowych bez podwójnego liczenia rodziców.
- Czas realizacji, prognoza czasu pozostałego oraz ryzyko opóźnienia na podstawie dostępnych dat.
- Obciążenie jednostek, zadania na osobę, tempo, wskaźnik efektywności i heurystyczne ryzyko przeciążenia.
- Operacyjne analizy API: podsumowanie, czas realizacji, jednostki, personel, wąskie gardła, efektywność, ryzyka budżetowe, plany i analizy dodatkowe.
- Historia snapshotów, porównania zmian i scenariusze ekstrapolacji postępu.

## Dostęp i ograniczenia danych

Globalne endpointy historyczne i operacyjne, które nie mają wiarygodnego filtrowania historycznych rekordów do jednostki, są ograniczone przez Access do perspektywy krajowej (`demo-premier` / `U-PRM`). Operacyjny widok UI korzysta wyłącznie z danych zwróconych przez API po kontroli dostępu i ogranicza zakres według wybranej jednostki. Syntetyczne historyczne punkty i heurystyczne prognozy są oznaczone jako demonstracyjne, a nie jako rzeczywiste pomiary lub gwarantowane prognozy.

## Uruchomienie

```bash
docker compose up --build
```

UI: `http://localhost:8501`. Analytics History API nie jest publikowane bezpośrednio na hoście.
