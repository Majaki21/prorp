import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

from fastapi.testclient import TestClient
from services.access.app import main as access


PERSON = {
    "id_osoby": "demo-A", "imie": "Demo", "nazwisko": "User",
    "id_jednostki": "A", "stanowisko": "Demo", "klauzula_tajnosci": "poufne", "aktywna": True,
}
UNITS = [
    {"id": "A", "nazwa": "Jednostka A", "id_jednostki_nadrzednej": None,
     "id_planow": ["P-PUBLIC", "P-SECRET"], "id_regionu": "PL-MZ", "pracownicy": [{"id_osoby": "demo-A"}], "zasoby": {}},
    {"id": "B", "nazwa": "Jednostka B", "id_jednostki_nadrzednej": "A",
     "id_planow": ["P-CHILD"], "id_regionu": "PL-MZ", "pracownicy": [{"id_osoby": "demo-B"}], "zasoby": {}},
    {"id": "X", "nazwa": "Jednostka X", "id_jednostki_nadrzednej": None,
     "id_planow": ["P-OTHER"], "id_regionu": "PL-PD", "pracownicy": [{"id_osoby": "demo-X"}], "zasoby": {}},
]
PLANS = [
    {"id_planu": "P-PUBLIC", "id_planu_nadrzednego": None, "nazwa_dokumentu": "Jawny", "klauzula_tajnosci": "jawne", "podplany": []},
    {"id_planu": "P-SECRET", "id_planu_nadrzednego": None, "nazwa_dokumentu": "Tajny", "klauzula_tajnosci": "tajne", "podplany": []},
    {"id_planu": "P-CHILD", "id_planu_nadrzednego": "P-PUBLIC", "nazwa_dokumentu": "Podplan", "klauzula_tajnosci": "poufne", "podplany": []},
    {"id_planu": "P-OTHER", "id_planu_nadrzednego": None, "nazwa_dokumentu": "Obcy", "klauzula_tajnosci": "jawne", "podplany": []},
]
TASKS = [
    {"id_planu": "P-PUBLIC", "id_zadania": "T1", "id_jednostek": ["A"], "nazwa_zadania": "Dostępne", "klauzula_tajnosci": "jawne", "status": False, "poziom_realizacji": 0.2, "zasoby": {}},
    {"id_planu": "P-SECRET", "id_zadania": "T2", "id_jednostek": ["A"], "nazwa_zadania": "Zbyt tajne", "klauzula_tajnosci": "tajne", "status": False, "poziom_realizacji": 0.2, "zasoby": {}},
    {"id_planu": "P-CHILD", "id_zadania": "T3", "id_jednostek": ["B", "X"], "nazwa_zadania": "Częściowo dostępne", "klauzula_tajnosci": "poufne", "status": False, "poziom_realizacji": 0.5, "zasoby": {}},
    {"id_planu": "P-SECRET", "id_zadania": "T4", "id_jednostek": ["A"], "nazwa_zadania": "Jawne zadanie w tajnym planie", "klauzula_tajnosci": "jawne", "status": False, "poziom_realizacji": 0.1, "zasoby": {}},
]


async def fake_data_get(path, params=None):
    params = params or {}
    if path == "/people/demo-A":
        return PERSON
    if path == "/people":
        return [PERSON, {
            "id_osoby": "staff-1", "imie": "Jan", "nazwisko": "Test",
            "id_jednostki": "A", "stanowisko": "Pracownik",
            "klauzula_tajnosci": "jawne", "aktywna": True,
        }]
    if path == "/units":
        return UNITS
    if path == "/plans":
        return PLANS
    if path == "/cooperation":
        return []
    if path == "/tasks":
        tasks = TASKS
        if params.get("plan_id"):
            tasks = [t for t in tasks if t["id_planu"] == params["plan_id"]]
        return tasks[: int(params.get("limit", 500))]
    raise AssertionError(f"Unexpected data request: {path} {params}")


def setup_client(monkeypatch):
    monkeypatch.setattr(access, "data_get", fake_data_get)
    monkeypatch.setattr(access, "DEFAULT_PERSON_ID", "")
    return TestClient(access.app)


def test_task_list_filters_by_task_and_parent_plan_clearance(monkeypatch):
    client = setup_client(monkeypatch)
    response = client.get("/tasks", headers={"X-Person-Id": "demo-A"})
    assert response.status_code == 200
    payload = response.json()
    assert {item["id_zadania"] for item in payload} == {"T1", "T3"}
    # A low-clearance task inside a higher-classified plan remains hidden.
    assert "T4" not in {item["id_zadania"] for item in payload}
    # A task cannot leak the identifier of an inaccessible unit through its assignments.
    child = next(item for item in payload if item["id_zadania"] == "T3")
    assert child["id_jednostek"] == ["B"]


def test_task_detail_denies_inaccessible_classification(monkeypatch):
    client = setup_client(monkeypatch)
    response = client.get("/tasks/P-SECRET/T2", headers={"X-Person-Id": "demo-A"})
    assert response.status_code == 404


def test_plan_detail_filters_child_references(monkeypatch):
    client = setup_client(monkeypatch)
    response = client.get("/plans/P-PUBLIC", headers={"X-Person-Id": "demo-A"})
    assert response.status_code == 200
    assert response.json()["podplany"] == ["P-CHILD"]


def test_unit_detail_hides_other_unit_roster(monkeypatch):
    client = setup_client(monkeypatch)
    response = client.get("/units/B", headers={"X-Person-Id": "demo-A"})
    assert response.status_code == 200
    assert response.json()["pracownicy"] == []


def test_inaccessible_unit_detail_is_not_found(monkeypatch):
    client = setup_client(monkeypatch)
    response = client.get("/units/X", headers={"X-Person-Id": "demo-A"})
    assert response.status_code == 404


def test_unit_detail_does_not_disclose_classified_plan_ids(monkeypatch):
    client = setup_client(monkeypatch)
    response = client.get("/units/A", headers={"X-Person-Id": "demo-A"})
    assert response.status_code == 200
    assert response.json()["id_planow"] == ["P-PUBLIC"]


def test_missing_identity_is_rejected(monkeypatch):
    client = setup_client(monkeypatch)
    response = client.get("/plans")
    assert response.status_code == 401


def test_demo_identity_picker_exposes_only_synthetic_accounts(monkeypatch):
    client = setup_client(monkeypatch)
    response = client.get("/demo-identities")
    assert response.status_code == 200
    payload = response.json()
    assert [person["id_osoby"] for person in payload] == ["demo-A"]
    assert payload[0]["nazwa_jednostki"] == "Jednostka A"
    assert "pracownicy" not in payload[0]


def test_requirements_are_visible_to_the_directly_targeted_unit(monkeypatch):
    child_person = {
        "id_osoby": "demo-B", "imie": "Demo", "nazwisko": "Child",
        "id_jednostki": "B", "stanowisko": "Demo", "klauzula_tajnosci": "poufne", "aktywna": True,
    }
    plans_with_requirement = [dict(plan) for plan in PLANS]
    plans_with_requirement[0]["wymogi"] = [{
        "id_jednostki": "B", "opis": "Przygotuj plan podrzędny",
        "termin": "2026-11-01", "status": "Oczekuje na plan",
    }]

    async def fake_child_data_get(path, params=None):
        if path == "/people/demo-B":
            return child_person
        if path == "/people":
            return [child_person]
        if path == "/units":
            return UNITS
        if path == "/plans":
            return plans_with_requirement
        if path == "/cooperation":
            return []
        raise AssertionError(f"Unexpected data request: {path} {params}")

    monkeypatch.setattr(access, "data_get", fake_child_data_get)
    monkeypatch.setattr(access, "DEFAULT_PERSON_ID", "")
    response = TestClient(access.app).get("/requirements", headers={"X-Person-Id": "demo-B"})
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["id_planu_nadrzednego"] == "P-PUBLIC"
    assert response.json()[0]["wymog"]["opis"] == "Przygotuj plan podrzędny"
