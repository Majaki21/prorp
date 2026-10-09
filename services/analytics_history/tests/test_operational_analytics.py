import json
import sqlite3
from pathlib import Path

from app.operational_analytics import build_operational_analyses


def test_operational_analysis_uses_full_operational_seed(tmp_path):
    root = Path(__file__).resolve().parents[3]
    seed_path = root / "services/analytics_history/data/operational_seed_data.json"
    db_path = root / "services/analytics_history/data/analytics_history.db"
    result = build_operational_analyses(seed_path, db_path)

    assert result["meta"]["tasks"] == 100
    assert result["meta"]["units"] == 19
    assert result["meta"]["history_rows"] == 18100
    assert len(result["task_durations"]) == 100
    assert len(result["units"]) == 19
    assert "budget_risks" in result
    assert "bottlenecks" in result
    assert "efficient_units" in result
    assert "stagnating_tasks" in result["additional_analyses"]
    assert "at_risk_tasks" in result["additional_analyses"]


def test_latest_progress_matches_operational_copy():
    root = Path(__file__).resolve().parents[3]
    seed_path = root / "services/analytics_history/data/operational_seed_data.json"
    db_path = root / "services/analytics_history/data/analytics_history.db"
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    result = build_operational_analyses(seed_path, db_path)
    by_id = {r["task_id"]: r for r in result["task_durations"]}
    for task in seed["tasks"]:
        tid = f'{task["id_planu"]}:{task["id_zadania"]}'
        assert by_id[tid]["current_progress"] == round(float(task["poziom_realizacji"]), 4)


def test_budget_risk_uses_sum_of_planned_task_costs():
    root = Path(__file__).resolve().parents[3]
    seed_path = root / "services/analytics_history/data/operational_seed_data.json"
    db_path = root / "services/analytics_history/data/analytics_history.db"
    result = build_operational_analyses(seed_path, db_path)
    unit = next(u for u in result["budget_risks"] if u["budget"] > 0)
    assert unit["projected_total_cost"] == unit["sum_task_costs"]
    assert unit["projected_budget_overrun"] == round(max(0, unit["sum_task_costs"] - unit["budget"]), 2)


def test_duplicate_unit_ids_are_disambiguated():
    root = Path(__file__).resolve().parents[3]
    result = build_operational_analyses(
        root / "services/analytics_history/data/operational_seed_data.json",
        root / "services/analytics_history/data/analytics_history.db")
    assert result["meta"]["duplicate_source_unit_ids"] == ["U-PRM"]
    ids = [u["unit_id"] for u in result["units"]]
    assert len(ids) == len(set(ids))


def test_analysis_only_duplicate_tasks_enable_cross_unit_benchmarks():
    root = Path(__file__).resolve().parents[3]
    result = build_operational_analyses(
        root / "services/analytics_history/data/operational_seed_data.json",
        root / "services/analytics_history/data/analytics_history.db")
    assert result["same_task_unit_benchmarks"]
    assert result["meta"]["analysis_only_duplicate_tasks"] > 0
    assert all(item["comparison_mode"] == "synthetic_analysis_only" for item in result["same_task_unit_benchmarks"])
    assert "nie zmieniają seedów operacyjnych" in result["meta"]["same_task_comparison_note"]
