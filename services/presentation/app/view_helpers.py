"""Pure helpers for the unit-centric presentation views."""


def unit_descendants(unit_id: str, units: list[dict]) -> list[dict]:
    """Return all visible descendants in hierarchy order, excluding the selected unit."""
    by_id = {str(unit["id"]): unit for unit in units}
    depths: dict[str, int] = {str(unit_id): 0}
    changed = True
    while changed:
        changed = False
        for unit in units:
            uid = str(unit["id"])
            parent_id = str(unit.get("id_jednostki_nadrzednej") or "")
            if uid not in depths and parent_id in depths:
                depths[uid] = depths[parent_id] + 1
                changed = True
    descendants = [by_id[uid] for uid, depth in depths.items() if depth > 0 and uid in by_id]
    return sorted(descendants, key=lambda item: (depths[str(item["id"])], item.get("nazwa", "")))


def direct_child_units(unit_id: str, units: list[dict]) -> list[dict]:
    """Return only units directly reporting to the supplied unit."""
    parent_id = str(unit_id)
    return [
        unit for unit in units
        if str(unit.get("id_jednostki_nadrzednej") or "") == parent_id
    ]


def task_belongs_to_unit(task: dict, unit_id: str, own_plan_ids: set[str]) -> bool:
    """Keep the unit view strictly local: no tasks assigned to subordinate units."""
    if str(task.get("id_planu", "")) not in {str(pid) for pid in own_plan_ids}:
        return False
    assigned_units = {str(uid) for uid in task.get("id_jednostek", [])}
    # Unassigned tasks belong to the unit whose plan directly contains them.
    # Explicitly assigned tasks belong only to the listed unit(s).
    return str(unit_id) in assigned_units if assigned_units else True


def task_belongs_to_units(
    task: dict,
    unit_ids: set[str],
    plan_ids: set[str],
    plan_owner_by_id: dict[str, str],
) -> bool:
    """Filter aggregate views to tasks owned by a fixed set of units.

    Explicit task assignments take precedence. Unassigned tasks are attributed to
    the unit that directly owns the plan, preventing a parent overview from
    absorbing tasks assigned to deeper descendants.
    """
    plan_id = str(task.get("id_planu", ""))
    if plan_id not in {str(pid) for pid in plan_ids}:
        return False
    assigned_units = {str(uid) for uid in task.get("id_jednostek", [])}
    if assigned_units:
        return bool(assigned_units & {str(uid) for uid in unit_ids})
    return str(plan_owner_by_id.get(plan_id, "")) in {str(uid) for uid in unit_ids}


def task_status(task: dict) -> str:
    if task.get("status"):
        return "Zakończone"
    return "W toku" if float(task.get("poziom_realizacji", 0)) > 0 else "Zaplanowane"


def display_plan_name(plan: dict) -> str:
    """Return the full human-facing plan title, including its useful plan code."""
    return str(plan.get("nazwa_dokumentu") or "Plan bez nazwy")


def completion_percent(tasks: list[dict]) -> float | None:
    """Average task completion as a percentage, or None for an empty set."""
    if not tasks:
        return None
    return sum(float(task.get("poziom_realizacji", 0) or 0) for task in tasks) / len(tasks) * 100


def format_money(value) -> str:
    try:
        return f"{float(value):,.0f} zł".replace(",", " ")
    except (TypeError, ValueError):
        return "—"
