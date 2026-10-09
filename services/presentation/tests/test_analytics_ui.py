from datetime import date

from services.presentation.app.analytics_ui import (
    leaf_tasks,
    task_status_band,
    estimate_task_duration,
    build_unit_task_rows,
    unit_metrics,
    recommend_support,
)


def test_leaf_tasks_excludes_parent_when_child_is_visible():
    tasks = [
        {"id_zadania": "A", "id_planu": "P", "poziom_realizacji": 0.5},
        {"id_zadania": "B", "id_planu": "P", "id_zadania_nadrzednego": "A", "poziom_realizacji": 0.2},
    ]
    assert [t["id_zadania"] for t in leaf_tasks(tasks)] == ["B"]


def test_status_bands_are_mutually_exclusive_and_color_labels_stable():
    assert task_status_band({"poziom_realizacji": 0}) == "Nierozpoczęte"
    assert task_status_band({"poziom_realizacji": 0.1}) == "Rozpoczęte: 0–25%"
    assert task_status_band({"poziom_realizacji": 0.25}) == "Realizacja: 25–50%"
    assert task_status_band({"poziom_realizacji": 0.5}) == "Realizacja: 50–75%"
    assert task_status_band({"poziom_realizacji": 0.75}) == "Realizacja: 75–99,9%"
    assert task_status_band({"poziom_realizacji": 1}) == "Zakończone"


def test_duration_prediction_uses_elapsed_progress_and_deadline():
    task = {"data_utworzenia": "2026-09-01", "poziom_realizacji": 0.25, "termin_realizacji": "2026-12-31"}
    result = estimate_task_duration(task, as_of=date(2026, 9, 21))
    assert result["elapsed_days"] == 20
    assert result["remaining_days"] == 60
    assert result["delay"] == "Brak"


def test_task_rows_do_not_leak_unit_ids_outside_authorized_scope():
    tasks = [{"id_zadania": "T1", "id_planu": "P1", "id_jednostek": ["U1", "U2"], "poziom_realizacji": 0.5}]
    rows = build_unit_task_rows(tasks, {"P1": {"nazwa_dokumentu": "Plan"}}, {"U1": "Widoczna jednostka"})
    assert rows[0]["Jednostki"] == "Widoczna jednostka"
    assert rows[0]["Jednostki uczestniczące"] == 1


def test_unit_metrics_and_support_recommendation_are_bounded():
    units = [
        {"id": "U1", "nazwa": "Szybka", "zasoby": {"personel": 20}},
        {"id": "U2", "nazwa": "Przeciążona", "zasoby": {"personel": 1}},
    ]
    tasks = [
        {"id_zadania": "T1", "id_planu": "P1", "poziom_realizacji": 1, "data_utworzenia": "2026-09-01"},
        {"id_zadania": "T2", "id_planu": "P2", "poziom_realizacji": 0.1, "data_utworzenia": "2026-09-01"},
        {"id_zadania": "T3", "id_planu": "P2", "poziom_realizacji": 0.05, "data_utworzenia": "2026-09-01"},
    ]
    rows = unit_metrics(units, tasks, {"P1": "U1", "P2": "U2"})
    assert all(0 <= r["Wydajność (0–100)"] <= 100 for r in rows if r["Wydajność (0–100)"] is not None)
    assert all(0 <= r["_risk_score"] <= 100 for r in rows)
    assert isinstance(recommend_support(rows), list)


def test_top_level_tasks_keeps_parent_for_duration_table():
    from services.presentation.app.analytics_ui import top_level_tasks
    tasks = [
        {"id_zadania": "A", "id_planu": "P", "poziom_realizacji": 0.5},
        {"id_zadania": "B", "id_planu": "P", "id_zadania_nadrzednego": "A", "poziom_realizacji": 0.2},
    ]
    assert [t["id_zadania"] for t in top_level_tasks(tasks)] == ["A"]


def test_leaf_tasks_flattens_nested_subtasks_and_inherits_plan():
    tasks = [{
        "id_zadania": "A", "id_planu": "P", "id_jednostek": ["U1"], "poziom_realizacji": 0.4,
        "podzadania": [
            {"id_zadania": "A.1", "poziom_realizacji": 0.5},
            {"id_zadania": "A.2", "poziom_realizacji": 0.1},
        ],
    }]
    leaves = leaf_tasks(tasks)
    assert {t["id_zadania"] for t in leaves} == {"A.1", "A.2"}
    assert all(t["id_planu"] == "P" for t in leaves)
    assert all(t["id_jednostek"] == ["U1"] for t in leaves)
