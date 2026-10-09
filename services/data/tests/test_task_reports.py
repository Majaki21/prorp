import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

from fastapi.testclient import TestClient
from services.data.app import main as data


def setup_client(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "DB_PATH", tmp_path / "task-reports.sqlite3")
    monkeypatch.setattr(data, "SEED_PATH", Path(__file__).resolve().parents[1] / "seed_data.json")
    data.init_db()
    return TestClient(data.app)


def test_report_is_persisted_and_updates_task_progress_atomically(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    # Activate a seeded operational plan so this test follows the real reporting lifecycle.
    client.post("/plans/OR/activate", json={"activated_by": "test"})
    tasks = client.get("/tasks", params={"plan_id": "OR", "limit": 5000}).json()
    task = next(t for t in tasks if t["typ_zadania"] == "REAL")
    payload = {
        "author_id": "test-user", "author_name": "Test User", "unit_id": "U-PRM",
        "poziom_realizacji": 0.65, "wykonane_czynnosci": "Wykonano kontrolę gotowości zasobów.",
        "przeszkody": "Brak jednego elementu wyposażenia.", "potrzeby": "Uzupełnienie wyposażenia.",
        "przewidywany_termin": "2026-10-20",
    }
    created = client.post(f"/tasks/OR/{task['id_zadania']}/reports", json=payload)
    assert created.status_code == 201, created.text
    assert created.json()["author_id"] == "test-user"
    assert created.json()["poziom_realizacji"] == 0.65
    reports = client.get(f"/tasks/OR/{task['id_zadania']}/reports")
    assert reports.status_code == 200
    assert len(reports.json()) == 1
    assert reports.json()[0]["wykonane_czynnosci"] == payload["wykonane_czynnosci"]
    updated_task = next(t for t in client.get("/tasks", params={"plan_id": "OR", "limit": 5000}).json() if t["id_zadania"] == task["id_zadania"])
    assert updated_task["poziom_realizacji"] == 0.65


def test_report_requires_existing_task_and_valid_progress(tmp_path, monkeypatch):
    client = setup_client(tmp_path, monkeypatch)
    missing = client.post("/tasks/no-plan/no-task/reports", json={
        "author_id": "test", "author_name": "Test", "unit_id": "U-PRM", "poziom_realizacji": 0.5,
        "wykonane_czynnosci": "Raport testowy",
    })
    assert missing.status_code == 404

    task = client.get("/tasks", params={"limit": 5000}).json()[0]
    invalid = client.post(f"/tasks/{task['id_planu']}/{task['id_zadania']}/reports", json={
        "author_id": "test", "author_name": "Test", "unit_id": "U-PRM", "poziom_realizacji": 1.5,
        "wykonane_czynnosci": "Raport testowy",
    })
    assert invalid.status_code == 422
