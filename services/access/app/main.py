"""Policy enforcement for the PRO RP proof of concept.

Identity is supplied by X-Person-Id. DEFAULT_PERSON_ID is only a demo convenience;
production deployments must replace it with a trusted identity-provider integration.
"""
import os
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Query
from pro_rp_shared.models import OperationalState

app = FastAPI(title="PRO RP Access Service", version="2.0.0")
DATA_SERVICE_URL = os.getenv("DATA_SERVICE_URL", "http://localhost:8003")
DEFAULT_PERSON_ID = os.getenv("DEFAULT_PERSON_ID", "")
CLEARANCE_LEVELS = {"jawne": 0, "zastrzezone": 1, "poufne": 2, "tajne": 3, "scisle_tajne": 4}


async def data_get(path: str, params: dict[str, Any] | None = None) -> Any:
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(f"{DATA_SERVICE_URL}{path}", params=params)
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Data service unavailable") from exc
    if response.status_code == 404:
        raise HTTPException(404, "Record not found")
    if response.status_code != 200:
        raise HTTPException(502, "Data service returned an error")
    return response.json()


def clearance_allows(person_level: str, object_level: str) -> bool:
    # Unknown classifications fail closed.
    return person_level in CLEARANCE_LEVELS and object_level in CLEARANCE_LEVELS and CLEARANCE_LEVELS[person_level] >= CLEARANCE_LEVELS[object_level]


async def resolve_person(x_person_id: str | None) -> dict[str, Any]:
    person_id = x_person_id or DEFAULT_PERSON_ID
    if not person_id:
        raise HTTPException(401, "Missing X-Person-Id identity header")
    person = await data_get(f"/people/{person_id}")
    if not person.get("aktywna", False):
        raise HTTPException(403, "Person account is inactive")
    return person


async def access_context(person: dict[str, Any]) -> tuple[set[str], set[str], list[dict[str, Any]]]:
    """Return visible unit IDs, visible plan IDs and raw units for a person."""
    units = await data_get("/units")
    unit_by_id = {str(unit["id"]): unit for unit in units}
    own_id = str(person["id_jednostki"])
    if own_id not in unit_by_id:
        raise HTTPException(403, "Person is not assigned to a known unit")

    # Own unit and all descendants are visible to the employee's organization.
    visible_units = {own_id}
    changed = True
    while changed:
        changed = False
        for unit in units:
            uid = str(unit["id"])
            parent = str(unit.get("id_jednostki_nadrzednej") or "")
            if parent in visible_units and uid not in visible_units:
                visible_units.add(uid)
                changed = True

    # Cooperation grants peer-unit visibility only; it is not transitive.
    relations = await data_get("/cooperation", {"unit_id": own_id})
    for relation in relations:
        a, b = str(relation["unit_id"]), str(relation["partner_unit_id"])
        peer = b if a == own_id else a
        if peer in unit_by_id:
            visible_units.add(peer)
            # Include descendants of an explicitly cooperating unit only when the relation names that unit.
            changed = True
            while changed:
                changed = False
                for unit in units:
                    uid = str(unit["id"])
                    parent = str(unit.get("id_jednostki_nadrzednej") or "")
                    if parent in visible_units and uid not in visible_units:
                        visible_units.add(uid)
                        changed = True

    visible_plans: set[str] = set()
    for unit in units:
        if str(unit["id"]) in visible_units:
            visible_plans.update(str(p) for p in unit.get("id_planow", []))
    plans = await data_get("/plans")
    # Parent plan visibility flows down the plan hierarchy, never upward by itself.
    changed = True
    while changed:
        changed = False
        for plan in plans:
            pid = str(plan["id_planu"])
            parent = str(plan.get("id_planu_nadrzednego") or "")
            if parent in visible_plans and pid not in visible_plans:
                visible_plans.add(pid)
                changed = True
    return visible_units, visible_plans, units


@app.get("/health")
def health():
    return {"service": "access", "status": "ok", "identity_mode": "header_or_demo_default" if DEFAULT_PERSON_ID else "header_required"}


@app.get("/me")
async def me(x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    person = await resolve_person(x_person_id)
    return person


@app.get("/units")
async def get_visible_units(x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    person = await resolve_person(x_person_id)
    visible_units, _, units = await access_context(person)
    # Return no employee records from other units: only the caller's own unit's roster.
    result = []
    for unit in units:
        if str(unit["id"]) not in visible_units:
            continue
        item = dict(unit)
        if str(unit["id"]) != str(person["id_jednostki"]):
            item["pracownicy"] = []
        result.append(item)
    return result


@app.get("/plans")
async def get_visible_plans(x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    person = await resolve_person(x_person_id)
    _, visible_plans, _ = await access_context(person)
    plans = await data_get("/plans")
    return [p for p in plans if str(p["id_planu"]) in visible_plans and clearance_allows(person["klauzula_tajnosci"], p.get("klauzula_tajnosci", "scisle_tajne"))]


@app.get("/tasks")
async def get_visible_tasks(
    plan_id: str | None = None,
    unit_id: str | None = None,
    x_person_id: str | None = Header(default=None, alias="X-Person-Id"),
):
    person = await resolve_person(x_person_id)
    visible_units, visible_plans, _ = await access_context(person)
    tasks = await data_get("/tasks")
    result = []
    for task in tasks:
        pid = str(task["id_planu"])
        assigned = {str(uid) for uid in task.get("id_jednostek", [])}
        # Unassigned tasks are scoped by plan; assigned tasks require an authorized unit relationship.
        in_scope = (pid in visible_plans and not assigned) or bool(assigned & visible_units)
        if not in_scope or pid not in visible_plans:
            continue
        if not clearance_allows(person["klauzula_tajnosci"], task.get("klauzula_tajnosci", "scisle_tajne")):
            continue
        if plan_id and pid != plan_id:
            continue
        if unit_id and unit_id not in assigned:
            continue
        result.append(task)
    return result


@app.get("/state", response_model=OperationalState)
async def get_state(x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    person = await resolve_person(x_person_id)
    visible_units, visible_plans, units = await access_context(person)
    raw_tasks = await data_get("/tasks")
    raw_plans = {str(p["id_planu"]): p for p in await data_get("/plans")}
    filtered_tasks = []
    for task in raw_tasks:
        pid = str(task["id_planu"])
        assigned = {str(uid) for uid in task.get("id_jednostek", [])}
        in_scope = (pid in visible_plans and not assigned) or bool(assigned & visible_units)
        if not in_scope or pid not in visible_plans:
            continue
        if not clearance_allows(person["klauzula_tajnosci"], task.get("klauzula_tajnosci", "scisle_tajne")):
            continue
        plan = raw_plans.get(pid, {})
        if not clearance_allows(person["klauzula_tajnosci"], plan.get("klauzula_tajnosci", "scisle_tajne")):
            continue
        filtered_tasks.append(task)

    unit_by_id = {str(u["id"]): u for u in units}
    tasks = []
    for task in filtered_tasks:
        region = next((unit_by_id[uid].get("id_regionu") for uid in task.get("id_jednostek", [])
                       if uid in unit_by_id and unit_by_id[uid].get("id_regionu")), "PL-MZ")
        status = "completed" if task["status"] else ("in_progress" if task["poziom_realizacji"] > 0 else "planned")
        from pro_rp_shared.models import Task
        tasks.append(Task(id=f'{task["id_planu"]}:{task["id_zadania"]}', name=task["nazwa_zadania"],
                          region_id=region, completion=task["poziom_realizacji"], status=status))

    resources = []
    for unit in units:
        if str(unit["id"]) not in visible_units:
            continue
        for resource_type, quantity in unit.get("zasoby", {}).items():
            try:
                quantity = float(quantity)
            except (TypeError, ValueError):
                continue
            resources.append({"id": f'{unit["id"]}:{resource_type}', "type": resource_type,
                              "region_id": unit.get("id_regionu") or "PL-00", "quantity": quantity})
    from datetime import datetime, timezone
    return OperationalState(version=datetime.now(timezone.utc).isoformat(), tasks=tasks, resources=resources, infrastructure=[])
