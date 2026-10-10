import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

from fastapi.testclient import TestClient
from services.data.app import main as data


def setup_client(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "DB_PATH", tmp_path / "deadlines.sqlite3")
    monkeypatch.setattr(data, "SEED_PATH", Path(__file__).resolve().parents[1] / "seed_data.json")
    data.init_db()
    return TestClient(data.app)


def test_seeded_tasks_expose_deadlines_in_api(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    response = client.get("/tasks?limit=5000")
    assert response.status_code == 200
    tasks = response.json()
    assert len(tasks) == 101
    assert all(task.get("termin_realizacji") for task in tasks)
    assert any(task["termin_realizacji"] >= "2027-01-01" for task in tasks)
    assert any(task["termin_realizacji"] < "2026-10-10" for task in tasks)


def test_startup_backfills_missing_deadlines_without_overwriting_existing_ones(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    with data.db() as conn:
        conn.execute("UPDATE tasks SET termin_realizacji=NULL WHERE id_zadania='PRZ-001'")
        conn.execute("UPDATE tasks SET termin_realizacji='2030-01-01' WHERE id_zadania='PRZ-002'")
    data.init_db()
    response = client.get("/tasks?limit=5000")
    tasks = {task["id_zadania"]: task for task in response.json()}
    assert tasks["PRZ-001"]["termin_realizacji"]
    assert tasks["PRZ-002"]["termin_realizacji"] == "2030-01-01"
