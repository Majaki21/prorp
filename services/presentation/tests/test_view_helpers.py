from services.presentation.app.view_helpers import task_belongs_to_unit, task_belongs_to_units, task_status, unit_descendants, direct_child_units


def test_unit_descendants_returns_only_descendants_in_hierarchy_order():
    units = [
        {"id": "A", "nazwa": "A", "id_jednostki_nadrzednej": None},
        {"id": "C", "nazwa": "C", "id_jednostki_nadrzednej": "B"},
        {"id": "D", "nazwa": "D", "id_jednostki_nadrzednej": None},
        {"id": "B", "nazwa": "B", "id_jednostki_nadrzednej": "A"},
    ]
    assert [unit["id"] for unit in unit_descendants("A", units)] == ["B", "C"]


def test_task_belongs_only_to_direct_unit_plan_and_assignment():
    own_plans = {"ORP"}
    assert task_belongs_to_unit({"id_planu": "ORP", "id_jednostek": ["U-KGP"]}, "U-KGP", own_plans)
    assert not task_belongs_to_unit({"id_planu": "ORP", "id_jednostek": ["U-KWP-MZ"]}, "U-KGP", own_plans)
    assert not task_belongs_to_unit({"id_planu": "ORPP", "id_jednostek": ["U-KWP-MZ"]}, "U-KGP", own_plans)


def test_unassigned_task_in_direct_plan_belongs_to_unit():
    assert task_belongs_to_unit({"id_planu": "ORP", "id_jednostek": []}, "U-KGP", {"ORP"})


def test_task_status_labels():
    assert task_status({"status": True, "poziom_realizacji": 1}) == "Zakończone"
    assert task_status({"status": False, "poziom_realizacji": 0.25}) == "W toku"
    assert task_status({"status": False, "poziom_realizacji": 0}) == "Zaplanowane"


def test_direct_child_units_excludes_grandchildren():
    units = [
        {"id": "ROOT", "id_jednostki_nadrzednej": None},
        {"id": "A", "id_jednostki_nadrzednej": "ROOT"},
        {"id": "B", "id_jednostki_nadrzednej": "A"},
    ]
    assert [unit["id"] for unit in direct_child_units("ROOT", units)] == ["A"]


def test_aggregate_view_excludes_tasks_assigned_to_grandchildren():
    unit_ids = {"MSWIA", "RCB"}
    plan_ids = {"OR", "OW"}
    plan_owner = {"OR": "MSWIA", "OW": "RCB"}
    assert task_belongs_to_units(
        {"id_planu": "OR", "id_jednostek": ["MSWIA"]}, unit_ids, plan_ids, plan_owner
    )
    assert task_belongs_to_units(
        {"id_planu": "OR", "id_jednostek": []}, unit_ids, plan_ids, plan_owner
    )
    assert not task_belongs_to_units(
        {"id_planu": "OR", "id_jednostek": ["KGP"]}, unit_ids, plan_ids, plan_owner
    )
    assert not task_belongs_to_units(
        {"id_planu": "ORP", "id_jednostek": ["KGP"]}, unit_ids, plan_ids, plan_owner
    )
