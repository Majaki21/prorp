import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

from fastapi.testclient import TestClient
from services.access.app import main as access

PEOPLE = {
    "demo-premier": {"id_osoby": "demo-premier", "imie": "Donald", "nazwisko": "Tusk", "id_jednostki": "U-PRM", "stanowisko": "Premier — konto demo", "klauzula_tajnosci": "scisle_tajne", "aktywna": True},
    "demo-kgp": {"id_osoby": "demo-kgp", "imie": "Jan", "nazwisko": "Kowalski", "id_jednostki": "U-KGP", "stanowisko": "Komendant Główny Policji — fikcyjne konto demo", "klauzula_tajnosci": "tajne", "aktywna": True},
    "demo-kgpsp": {"id_osoby": "demo-kgpsp", "imie": "Anna", "nazwisko": "Nowak", "id_jednostki": "U-KGPSP", "stanowisko": "Komendant Główny PSP — fikcyjne konto demo", "klauzula_tajnosci": "zastrzezone", "aktywna": True},
}
UNITS = [
    {"id": "U-PRM", "nazwa": "Prezes Rady Ministrów", "id_jednostki_nadrzednej": None, "id_planow": [], "id_regionu": "PL-00", "pracownicy": [], "zasoby": {}},
    {"id": "U-MSWIA", "nazwa": "MSWiA", "id_jednostki_nadrzednej": "U-PRM", "id_planow": ["PRM-CHILD"], "id_regionu": "PL-00", "pracownicy": [], "zasoby": {}},
    {"id": "U-KGP", "nazwa": "Komenda Główna Policji", "id_jednostki_nadrzednej": "U-MSWIA", "id_planow": ["ORP", "PP"], "id_regionu": "PL-00", "pracownicy": [], "zasoby": {}},
    {"id": "U-KWP", "nazwa": "Komenda Wojewódzka Policji", "id_jednostki_nadrzednej": "U-KGP", "id_planow": [], "id_regionu": "PL-MZ", "pracownicy": [], "zasoby": {}},
    {"id": "U-KGPSP", "nazwa": "Komenda Główna PSP", "id_jednostki_nadrzednej": "U-MSWIA", "id_planow": ["ORS", "PS"], "id_regionu": "PL-00", "pracownicy": [], "zasoby": {}},
    {"id": "U-KWPSP", "nazwa": "Komenda Wojewódzka PSP", "id_jednostki_nadrzednej": "U-KGPSP", "id_planow": [], "id_regionu": "PL-MZ", "pracownicy": [], "zasoby": {}},
]
PLANS = [
    {"id_planu": "PRM-CHILD", "id_planu_nadrzednego": None, "nazwa_dokumentu": "Plan MSWiA", "klauzula_tajnosci": "tajne", "status_planu": "approved", "status_operacyjny": "inactive"},
    {"id_planu": "ORP", "id_planu_nadrzednego": None, "nazwa_dokumentu": "Plan Policji", "klauzula_tajnosci": "tajne"},
    {"id_planu": "ORPP", "id_planu_nadrzednego": "ORP", "nazwa_dokumentu": "Plan wojewódzki Policji", "klauzula_tajnosci": "tajne"},
    {"id_planu": "ORS", "id_planu_nadrzednego": None, "nazwa_dokumentu": "Plan PSP", "klauzula_tajnosci": "zastrzezone"},
    {"id_planu": "ORSS", "id_planu_nadrzednego": "ORS", "nazwa_dokumentu": "Plan wojewódzki PSP", "klauzula_tajnosci": "zastrzezone"},
]
TASKS = [
    {"id_planu": "ORP", "id_zadania": "POL-1", "id_jednostek": ["U-KGP"], "nazwa_zadania": "Zadanie Policji — szczegóły tajne", "klauzula_tajnosci": "tajne", "status": True, "poziom_realizacji": 1.0, "zasoby": {}},
    {"id_planu": "ORPP", "id_zadania": "POL-2", "id_jednostek": ["U-KWP"], "nazwa_zadania": "Zadanie wojewódzkie Policji", "klauzula_tajnosci": "tajne", "status": False, "poziom_realizacji": 0.5, "zasoby": {}},
    {"id_planu": "ORS", "id_zadania": "PSP-1", "id_jednostek": ["U-KGPSP"], "nazwa_zadania": "Zadanie PSP — zastrzeżone", "klauzula_tajnosci": "zastrzezone", "status": True, "poziom_realizacji": 1.0, "zasoby": {}},
    {"id_planu": "ORSS", "id_zadania": "PSP-2", "id_jednostek": ["U-KWPSP"], "nazwa_zadania": "Zadanie wojewódzkie PSP", "klauzula_tajnosci": "zastrzezone", "status": False, "poziom_realizacji": 0.5, "zasoby": {}},
]
COOPERATION = [{"unit_id": "U-KGPSP", "partner_unit_id": "U-KGP", "sharing_level": "aggregate"}]

async def fake_data_get(path, params=None):
    params = params or {}
    if path.startswith("/people/"):
        person_id = path.rsplit("/", 1)[-1]
        if person_id not in PEOPLE:
            from fastapi import HTTPException
            raise HTTPException(404, "not found")
        return PEOPLE[person_id]
    if path == "/people":
        return list(PEOPLE.values())
    if path == "/units":
        return UNITS
    if path == "/plans":
        return PLANS
    if path == "/cooperation":
        unit_id = params.get("unit_id")
        return [r for r in COOPERATION if not unit_id or r["unit_id"] == unit_id or r["partner_unit_id"] == unit_id]
    if path == "/tasks":
        tasks = TASKS
        if params.get("plan_id"):
            tasks = [t for t in tasks if t["id_planu"] == params["plan_id"]]
        return tasks[:int(params.get("limit", 500))]
    raise AssertionError(f"Unexpected data request: {path} {params}")


def client(monkeypatch):
    monkeypatch.setattr(access, "data_get", fake_data_get)
    monkeypatch.setattr(access, "DEFAULT_PERSON_ID", "")
    return TestClient(access.app)


def test_kgp_sees_own_hierarchy_but_not_psp_task_details(monkeypatch):
    c = client(monkeypatch)
    headers = {"X-Person-Id": "demo-kgp"}
    tasks = c.get("/tasks", headers=headers).json()
    assert {t["id_zadania"] for t in tasks} == {"POL-1", "POL-2"}
    assert c.get("/tasks/ORS/PSP-1", headers=headers).status_code == 404
    units = c.get("/units", headers=headers).json()
    assert "U-KGPSP" not in {u["id"] for u in units}


def test_kgpsp_cannot_read_police_tasks_with_higher_classification(monkeypatch):
    c = client(monkeypatch)
    headers = {"X-Person-Id": "demo-kgpsp"}
    tasks = c.get("/tasks", headers=headers).json()
    assert {t["id_zadania"] for t in tasks} == {"PSP-1", "PSP-2"}
    assert c.get("/tasks/ORP/POL-1", headers=headers).status_code == 404


def test_kgp_receives_only_aggregate_psp_summary(monkeypatch):
    c = client(monkeypatch)
    response = c.get("/collaboration-summary", headers={"X-Person-Id": "demo-kgp"})
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["jednostka"] == "Komenda Główna PSP"
    assert payload[0]["liczba_zadan"] == 2
    assert payload[0]["liczba_zrealizowanych"] == 1
    assert "nazwa_zadania" not in payload[0]
    assert "id_zadania" not in payload[0]


def test_kgpsp_does_not_receive_police_data_or_aggregate(monkeypatch):
    c = client(monkeypatch)
    response = c.get("/collaboration-summary", headers={"X-Person-Id": "demo-kgpsp"})
    assert response.status_code == 200
    assert response.json() == []


def test_premier_demo_account_can_see_all_units_plans_and_tasks(monkeypatch):
    c = client(monkeypatch)
    headers = {"X-Person-Id": "demo-premier"}
    assert len(c.get("/units", headers=headers).json()) == len(UNITS)
    assert len(c.get("/plans", headers=headers).json()) == len(PLANS)
    assert {t["id_zadania"] for t in c.get("/tasks", headers=headers).json()} == {"POL-1", "POL-2", "PSP-1", "PSP-2"}


def test_premier_can_activate_plan_owned_by_direct_subordinate(monkeypatch):
    c = client(monkeypatch)
    called = {}
    async def fake_mutate(method, path, payload):
        called["method"], called["path"], called["payload"] = method, path, payload
        return {"ok": True}
    monkeypatch.setattr(access, "data_mutate", fake_mutate)
    response = c.post("/plans/PRM-CHILD/activate", headers={"X-Person-Id": "demo-premier"})
    assert response.status_code == 200
    assert called["path"] == "/plans/PRM-CHILD/activate"
    assert called["payload"]["activated_by"] == "demo-premier"
