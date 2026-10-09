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


def test_plan_creation_requirements_submit_and_approval(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "DB_PATH", tmp_path / "create-plan.sqlite3")
    monkeypatch.setattr(data, "SEED_PATH", Path(__file__).resolve().parents[1] / "seed_data.json")
    data.init_db()
    client = TestClient(data.app)
    units = client.get("/units").json()
    parent_unit = next(u for u in units if u.get("id") == "U-KGP")
    child_unit = next(u for u in units if u.get("id") == "U-KWP-MZ")
    parent_plan_id = parent_unit["id_planow"][0]
    created = client.post("/plans", json={
        "id_planu": "ORPX", "nazwa_dokumentu": "Plan demonstracyjny",
        "sporzadzil": "Konto testowe", "id_jednostki_wlasciciela": "U-KGP",
        "id_planu_nadrzednego": parent_plan_id, "klauzula_tajnosci": "jawne",
        "data_przegladu": "2028-10-01", "komentarz": "test",
        "zadania": [{"nazwa_zadania": "Przygotować procedurę", "typ_zadania": "PRZ"},
                    {"nazwa_zadania": "Uruchomić działania", "typ_zadania": "REAL"}],
        "wymogi": [{"id_jednostki": "U-KWP-MZ", "opis": "Wymóg zapisany razem z planem",
                    "termin": "2026-11-01", "status": "Oczekuje na plan"}],
    })
    assert created.status_code == 201, created.text
    assert created.json()["data_przegladu"] == "2028-10-01"
    assert created.json()["wymogi"][0]["id_jednostki"] == "U-KWP-MZ"
    task_types = [t["typ_zadania"] for t in client.get("/tasks", params={"plan_id":"ORPX"}).json()]
    assert task_types == ["PRZ", "REAL"]
    req = client.put("/plans/ORPX/requirements", json={"wymogi":[{
        "id_jednostki":"U-KWP-MZ", "opis":"Plan musi zawierać procedury alarmowania", "termin":"2026-11-01", "status":"Oczekuje na plan"
    }]})
    assert req.status_code == 200
    assert req.json()["wymogi"][0]["id_jednostki"] == child_unit["id"]
    edited = client.put("/plans/ORPX", json={
        "id_planu": "ORPX", "nazwa_dokumentu": "Plan demonstracyjny — po edycji",
        "sporzadzil": "Konto testowe", "id_jednostki_wlasciciela": "U-KGP",
        "id_planu_nadrzednego": parent_plan_id, "klauzula_tajnosci": "jawne",
        "data_przegladu": "2028-10-01", "komentarz": "edytowany",
        "zadania": [{"nazwa_zadania": "Nowe zadanie PRZ", "typ_zadania": "PRZ"}],
        "wymogi": [{"id_jednostki": "U-KWP-MZ", "opis": "Zmieniony wymóg", "termin": "2026-12-01", "status": "Oczekuje na plan"}],
    })
    assert edited.status_code == 200, edited.text
    assert edited.json()["nazwa_dokumentu"] == "Plan demonstracyjny — po edycji"
    assert edited.json()["wymogi"][0]["opis"] == "Zmieniony wymóg"
    assert [t["nazwa_zadania"] for t in client.get("/tasks", params={"plan_id":"ORPX"}).json()] == ["Nowe zadanie PRZ"]
    assert client.post("/plans/ORPX/submit").status_code == 200
    approved = client.post("/plans/ORPX/approve")
    assert approved.status_code == 200
    assert approved.json()["status_planu"] == "approved"


def test_saved_plan_draft_can_be_finalized_as_a_project(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "DB_PATH", tmp_path / "persistent-draft.sqlite3")
    monkeypatch.setattr(data, "SEED_PATH", Path(__file__).resolve().parents[1] / "seed_data.json")
    data.init_db()
    client = TestClient(data.app)
    draft_payload = {
        "id_planu": "PLAN-DRAFT-1", "nazwa_dokumentu": "Plan w opracowaniu",
        "sporzadzil": "Konto testowe", "id_jednostki_wlasciciela": "U-KGP",
        "id_planu_nadrzednego": None, "klauzula_tajnosci": "jawne",
        "data_przegladu": "2028-10-01", "komentarz": "wersja robocza",
        "zadania": [{"nazwa_zadania": "Zadanie PRZ", "typ_zadania": "PRZ"}],
        "wymogi": [], "zapis_roboczy": True,
    }
    created = client.post("/plans", json=draft_payload)
    assert created.status_code == 201, created.text
    assert created.json()["status_planu"] == "editing"
    draft_payload["nazwa_dokumentu"] = "Projekt planu gotowy do zatwierdzenia"
    draft_payload["zapis_roboczy"] = False
    finalized = client.put("/plans/PLAN-DRAFT-1", json=draft_payload)
    assert finalized.status_code == 200, finalized.text
    assert finalized.json()["status_planu"] == "draft"
    assert finalized.json()["nazwa_dokumentu"] == "Projekt planu gotowy do zatwierdzenia"


def test_child_plan_code_must_extend_parent_code_by_one_letter(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "DB_PATH", tmp_path / "hierarchical-code.sqlite3")
    monkeypatch.setattr(data, "SEED_PATH", Path(__file__).resolve().parents[1] / "seed_data.json")
    data.init_db()
    client = TestClient(data.app)
    response = client.post("/plans", json={
        "id_planu": "CHILD-UNRELATED", "nazwa_dokumentu": "Plan demonstracyjny",
        "sporzadzil": "Konto testowe", "id_jednostki_wlasciciela": "U-KGP",
        "id_planu_nadrzednego": "ORP", "klauzula_tajnosci": "jawne",
        "data_przegladu": "2028-10-01", "komentarz": "test",
        "zadania": [], "wymogi": [],
    })
    assert response.status_code == 422


def test_adding_task_preserves_existing_task_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "DB_PATH", tmp_path / "add-task.sqlite3")
    monkeypatch.setattr(data, "SEED_PATH", Path(__file__).resolve().parents[1] / "seed_data.json")
    data.init_db()
    client = TestClient(data.app)
    existing = client.get("/tasks", params={"plan_id": "OR", "limit": 5000}).json()
    assert existing
    first = existing[0]
    client.patch(f"/tasks/OR/{first['id_zadania']}/progress", json={"poziom_realizacji": 0.6})
    before_count = len(client.get("/tasks", params={"plan_id": "OR", "limit": 5000}).json())
    created = client.post("/plans/OR/tasks", json={"nazwa_zadania": "Nowe zadanie testowe", "typ_zadania": "PRZ"})
    assert created.status_code == 201, created.text
    after = client.get("/tasks", params={"plan_id": "OR", "limit": 5000}).json()
    assert len(after) == before_count + 1
    persisted = next(task for task in after if task["id_zadania"] == first["id_zadania"])
    assert persisted["poziom_realizacji"] == 0.6
    assert created.json()["id_jednostek"] and len(created.json()["id_jednostek"]) == 1


def test_completing_all_tasks_does_not_end_an_active_plan(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "DB_PATH", tmp_path / "active-plan-is-not-finished.sqlite3")
    monkeypatch.setattr(data, "SEED_PATH", Path(__file__).resolve().parents[1] / "seed_data.json")
    data.init_db()
    client = TestClient(data.app)
    activated = client.post("/plans/ORP/activate", json={"activated_by": "test"})
    assert activated.status_code == 200
    tasks = client.get("/tasks", params={"plan_id": "ORP", "limit": 5000}).json()
    for task in tasks:
        response = client.patch(f"/tasks/ORP/{task['id_zadania']}/progress", json={"poziom_realizacji": 1.0})
        assert response.status_code == 200
    plan = next(p for p in client.get("/plans").json() if p["id_planu"] == "ORP")
    assert plan["status_operacyjny"] == "active"


def test_seed_uses_prime_minister_coordination_node_as_root_plan_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "DB_PATH", tmp_path / "prm-root-owner.sqlite3")
    monkeypatch.setattr(data, "SEED_PATH", Path(__file__).resolve().parents[1] / "seed_data.json")
    data.init_db()
    client = TestClient(data.app)
    units = client.get("/units").json()
    prm = next(unit for unit in units if unit["id"] == "U-PRM")
    assert "O" in prm["id_planow"]
    assert not any(unit["id"] == "U-KPRM" for unit in units)
    plan_o = next(plan for plan in client.get("/plans").json() if plan["id_planu"] == "O")
    assert "Prezes Rady Ministrów / Rada Ministrów" in plan_o["sporzadzil"]


def test_root_plan_can_use_one_letter_code(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "DB_PATH", tmp_path / "root-one-letter.sqlite3")
    monkeypatch.setattr(data, "SEED_PATH", Path(__file__).resolve().parents[1] / "seed_data.json")
    data.init_db()
    client = TestClient(data.app)
    created = client.post("/plans", json={
        "id_planu": "W", "nazwa_dokumentu": "Plan powodziowy",
        "sporzadzil": "Konto testowe", "id_jednostki_wlasciciela": "U-PRM",
        "id_planu_nadrzednego": None, "klauzula_tajnosci": "jawne",
        "data_przegladu": "2028-10-08", "komentarz": "Plan demonstracyjny PoC",
        "zadania": [], "wymogi": [], "zapis_roboczy": False,
    })
    assert created.status_code == 201, created.text
    assert created.json()["id_planu"] == "W"


def test_prm_zero_budget_is_repaired_on_startup(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "DB_PATH", tmp_path / "budget-migration.sqlite3")
    monkeypatch.setattr(data, "SEED_PATH", Path(__file__).resolve().parents[1] / "seed_data.json")
    data.init_db()
    with data.db() as conn:
        conn.execute("UPDATE units SET budzet=0 WHERE id='U-PRM'")
    data.init_db()
    prm = next(u for u in TestClient(data.app).get("/units").json() if u["id"] == "U-PRM")
    assert prm["budzet"] == 50_000_000
