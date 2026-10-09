# Przebudowa UI: Przegląd i karta jednostki

## Główne widoki

- **Przegląd** — aktywne plany, realizacja zadań w zakresie jednostki, realizacja zadań w aktywnych planach oraz szacowany pozostały budżet. Lista planów zawiera kompaktowe zadania z pełnym kontekstem planu.
- **Przegląd krajowy** — obejmuje wyłącznie jednostki bezpośrednio podległe Premierowi. Zadania przypisane jednostkom niższego szczebla, np. komendzie Policji w Radomiu, nie są wliczane do wskaźników ani pokazywane na liście aktywnych planów.
- **Jednostka** — karta informacyjna bez identyfikatorów technicznych: nazwa, nazwa jednostki nadrzędnej, budżet, plany z pełnymi nazwami, zasoby rozwijane na żądanie i szczegóły zadań tej jednostki.
- **Hierarchia planów** — relacje nadrzędności planów oraz wykonawcy; zachowana jako osobny widok nawigacyjny.
- **Mapa** — dotychczasowy podkład demonstracyjny.

## Reguły prezentacji

- API Access pozostaje jedynym źródłem danych dla UI.
- W perspektywie krajowej selektor zakresu pozwala wybrać cały przegląd albo jednostki bezpośrednio podległe Premierowi; nie pozwala przejść z poziomu tego widoku do komendy miejskiej w Radomiu.
- Hierarchia planów dla konta Premiera pokazuje wyłącznie plany przypisane bezpośrednio podległym jednostkom, a liczniki zadań korzystają z tego samego ograniczonego zakresu.
- Jednostka pokazuje plany przypisane bezpośrednio do niej; jednostki podrzędne mają własne widoki.
- Lista zadań w karcie jednostki pokazuje zadania tej jednostki w jej własnych planach, a nie zadania jednostek podległych.
- W przeglądzie krajowym jawnie przypisane zadania są uwzględniane tylko wtedy, gdy dotyczą jednej z jednostek bezpośrednio podległych. Zadania bez przypisania jednostkowego są przypisywane do jednostki, która bezpośrednio posiada dany plan.
- Wskaźnik „Realizacja zadań w aktywnych planach” obejmuje tylko zadania należące do bieżącego zakresu i aktywnych planów.
- Pełna nazwa planu (np. „Plan OR — działania MSWiA” albo „Plan P — bezpieczeństwo i porządek publiczny”) jest zachowana w nagłówkach i kontekście zadań.
- W przeglądzie zadania są kompaktowymi wierszami; pełne szczegóły znajdują się w karcie jednostki, więc nie powielamy pełnego rejestru.
- Pozostały budżet jest wyłącznie szacunkiem PoC: budżet minus suma kosztów zadań przemnożonych przez ich poziom realizacji. Nie jest to księgowe wykonanie budżetu.
- Endpoint jednostek udostępnia nazwę jednostki nadrzędnej jako metadane organizacyjne, bez ujawniania danych jej planów, budżetu czy pracowników.

## Uruchomienie

```bash
docker compose up --build -d presentation access
```

UI: `http://localhost:8501`
