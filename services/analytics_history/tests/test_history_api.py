import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app import main

client = TestClient(main.app)

def test_health():
    assert client.get("/health").status_code == 200

def test_snapshot_summary():
    r = client.get("/history/summary?snapshot_id=D%2B2")
    assert r.status_code == 200
    data = r.json()
    assert data["tasks"] == 100
    assert data["completed_tasks"] >= 1

def test_changes_and_pp():
    r = client.get("/history/changes?from_snapshot=D&to_snapshot=D%2B2")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 100
    pr = next(x for x in data["changes"] if x["task_id"] == "PRZ-001")
    assert pr["change_pp"] == 4.0

def test_simulation():
    r = client.post("/simulations/progress", json={"base_snapshot_id":"D+2","days_ahead":2})
    assert r.status_code == 200
    assert r.json()["results_count"] == 100
    assert "demonstracyjna" in r.json()["warning"]


def test_collection_records_only_real_changes(monkeypatch, tmp_path):
    db_path = tmp_path / "history.db"
    monkeypatch.setattr(main, "DEFAULT_DB", db_path)
    main.init_history_schema()

    first = main.record_observation([
        {"id_planu": "P1", "id_zadania": "T1", "poziom_realizacji": 0.5}
    ], "2026-10-10T10:00:00+00:00")
    second = main.record_observation([
        {"id_planu": "P1", "id_zadania": "T1", "poziom_realizacji": 0.5}
    ], "2026-10-11T10:00:00+00:00")
    third = main.record_observation([
        {"id_planu": "P1", "id_zadania": "T1", "poziom_realizacji": 0.7}
    ], "2026-10-12T10:00:00+00:00")

    assert first["changes_saved"] == 1  # initial baseline
    assert second["changes_saved"] == 0  # successful check, no change
    assert third["changes_saved"] == 1  # real change
    assert len(main.rows("SELECT * FROM collection_runs")) == 3
    assert len(main.rows("SELECT * FROM task_state_events")) == 2

def test_state_at_reconstructs_last_known_value(monkeypatch, tmp_path):
    monkeypatch.setattr(main, "DEFAULT_DB", tmp_path / "history.db")
    main.init_history_schema()
    main.record_observation([
        {"id_planu": "P1", "id_zadania": "T1", "poziom_realizacji": 0.4}
    ], "2026-10-10T10:00:00+00:00")
    main.record_observation([
        {"id_planu": "P1", "id_zadania": "T1", "poziom_realizacji": 0.8}
    ], "2026-10-12T10:00:00+00:00")
    result = main.state_at("2026-10-11T23:59:59+00:00")
    assert result["tasks"][0]["progress"] == 0.4

def test_progress_rejects_missing_or_out_of_range():
    import pytest
    with pytest.raises(ValueError):
        main.progress_value({"id": "T1"})
    with pytest.raises(ValueError):
        main.progress_value({"id": "T1", "completion": 1.2})
