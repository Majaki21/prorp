import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

from fastapi.testclient import TestClient
from services.data.app import main as data


def test_activation_is_cascaded_and_does_not_require_preparation(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "DB_PATH", tmp_path / "lifecycle.sqlite3")
    monkeypatch.setattr(data, "SEED_PATH", Path(__file__).resolve().parents[1] / "seed_data.json")
    data.init_db()
    client = TestClient(data.app)

    plans_before = {p["id_planu"]: p for p in client.get("/plans").json()}
    tasks_before = client.get("/tasks", params={"limit": 5000}).json()
    assert plans_before["O"]["status_operacyjny"] == "prepared"
    assert all(t["poziom_realizacji"] == 0 for t in tasks_before if t["typ_zadania"] == "REAL")

    # Deliberately incomplete PRZ tasks do not block emergency activation.
    result = client.post("/plans/O/activate", json={"activated_by": "demo-premier"})
    assert result.status_code == 200
    activated = set(result.json()["activated_plan_ids"])
    assert {"O", "OR", "ORP", "ORPP", "ORPPP"}.issubset(activated)

    plans_after = {p["id_planu"]: p for p in client.get("/plans").json()}
    assert all(plans_after[pid]["status_operacyjny"] == "active" for pid in activated)

    real_task = next(t for t in tasks_before if t["typ_zadania"] == "REAL" and t["id_planu"] == "OR")
    updated = client.patch(
        f"/tasks/{real_task['id_planu']}/{real_task['id_zadania']}/progress",
        json={"poziom_realizacji": 0.4},
    )
    assert updated.status_code == 200
    assert updated.json()["poziom_realizacji"] == 0.4
