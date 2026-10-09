"""Policy enforcement for the PRO RP proof of concept.

Identity is supplied by X-Person-Id. DEFAULT_PERSON_ID is a demo convenience only;
production deployments must use a trusted identity provider and enforce permissions
at the service boundary.
"""
import os
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, Query
from pro_rp_shared.models import OperationalState, Task

app = FastAPI(title="PRO RP Access Service", version="2.1.0")
DATA_SERVICE_URL = os.getenv("DATA_SERVICE_URL", "http://localhost:8003")
ANALYTICS_HISTORY_SERVICE_URL = os.getenv("ANALYTICS_HISTORY_SERVICE_URL", "http://analytics-history:8010").rstrip("/")
DEFAULT_PERSON_ID = os.getenv("DEFAULT_PERSON_ID", "")
CLEARANCE_LEVELS = {
    "jawne": 0,
    "zastrzezone": 1,
    "poufne": 2,
    "tajne": 3,
    "scisle_tajne": 4,
}


async def data_get(path: str, params: dict[str, Any] | None = None) -> Any:
    """Call the internal data service and normalize upstream errors."""
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(f"{DATA_SERVICE_URL}{path}", params=params)
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Data service unavailable") from exc
    if response.status_code == 404:
        raise HTTPException(404, "Record not found")
    if response.status_code != 200:
        raise HTTPException(502, "Data service returned an error")
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(502, "Data service returned invalid JSON") from exc


async def data_mutate(method: str, path: str, payload: dict[str, Any]) -> Any:
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.request(method, f"{DATA_SERVICE_URL}{path}", json=payload)
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Data service unavailable") from exc
    if response.status_code in (400, 403, 404, 409, 422):
        raise HTTPException(response.status_code, response.text)
    if response.status_code not in (200, 201):
        raise HTTPException(502, "Data service returned an error")
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(502, "Data service returned invalid JSON") from exc


def clearance_allows(person_level: str, object_level: str) -> bool:
    """Unknown or malformed classifications always deny access."""
    return (
        person_level in CLEARANCE_LEVELS
        and object_level in CLEARANCE_LEVELS
        and CLEARANCE_LEVELS[person_level] >= CLEARANCE_LEVELS[object_level]
    )


async def resolve_person(x_person_id: str | None) -> dict[str, Any]:
    person_id = x_person_id or DEFAULT_PERSON_ID
    if not person_id:
        raise HTTPException(401, "Missing X-Person-Id identity header")
    person = await data_get(f"/people/{person_id}")
    if not person.get("aktywna", False):
        raise HTTPException(403, "Person account is inactive")
    if person.get("klauzula_tajnosci") not in CLEARANCE_LEVELS:
        raise HTTPException(403, "Person has an unknown security clearance")
    return person


async def access_context(
    person: dict[str, Any],
) -> tuple[set[str], set[str], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return visible unit IDs, plan IDs, raw units and raw plans.

    Unit visibility follows the hierarchy downward. Only explicit `details` sharing
    can add a peer unit. `aggregate` relations never expand detail visibility; they
    are exposed through a separate summary endpoint. The synthetic Premier account
    has a PoC-only global view.
    """
    units = await data_get("/units")
    plans = await data_get("/plans")
    unit_by_id = {str(unit["id"]): unit for unit in units}
    plan_by_id = {str(plan["id_planu"]): plan for plan in plans}
    own_id = str(person["id_jednostki"])
    if own_id not in unit_by_id:
        raise HTTPException(403, "Person is not assigned to a known unit")

    def add_descendants(visible: set[str]) -> None:
        changed = True
        while changed:
            changed = False
            for unit in units:
                uid = str(unit["id"])
                parent = str(unit.get("id_jednostki_nadrzednej") or "")
                if parent in visible and uid not in visible:
                    visible.add(uid)
                    changed = True

    if str(person.get("id_osoby")) == "demo-premier":
        # Hackathon demo override: this synthetic account represents national-level oversight.
        visible_units = set(unit_by_id)
        visible_plans = set(plan_by_id)
        return visible_units, visible_plans, units, plans

    visible_units = {own_id}
    add_descendants(visible_units)

    # A collaboration link does not automatically grant access to task details.
    # Only an explicitly configured `details` scope expands organizational visibility.
    relations = await data_get("/cooperation", {"unit_id": own_id})
    for relation in relations:
        if relation.get("sharing_level", "details") != "details":
            continue
        a, b = str(relation["unit_id"]), str(relation["partner_unit_id"])
        peer = b if a == own_id else a if b == own_id else ""
        if peer and peer in unit_by_id:
            visible_units.add(peer)
            add_descendants(visible_units)

    visible_plans: set[str] = set()
    for unit in units:
        if str(unit["id"]) in visible_units:
            visible_plans.update(str(pid) for pid in unit.get("id_planow", []))

    # A visible parent plan makes its descendant plans discoverable by hierarchy.
    # Each plan's own classification is still checked before returning it.
    changed = True
    while changed:
        changed = False
        for plan in plans:
            pid = str(plan["id_planu"])
            parent = str(plan.get("id_planu_nadrzednego") or "")
            if parent in visible_plans and pid not in visible_plans:
                visible_plans.add(pid)
                changed = True

    return visible_units, visible_plans, units, plans


def plan_is_readable(person: dict[str, Any], plan: dict[str, Any] | None) -> bool:
    if not plan:
        return False
    return clearance_allows(
        str(person.get("klauzula_tajnosci", "")),
        str(plan.get("klauzula_tajnosci", "scisle_tajne")),
    )


def readable_plan_ids(person: dict[str, Any], plans: list[dict[str, Any]], visible_plan_ids: set[str]) -> set[str]:
    return {
        str(plan["id_planu"]) for plan in plans
        if str(plan["id_planu"]) in visible_plan_ids and plan_is_readable(person, plan)
    }


def task_is_readable(
    person: dict[str, Any], task: dict[str, Any], plan_by_id: dict[str, dict[str, Any]],
    visible_units: set[str], visible_plans: set[str],
) -> bool:
    plan_id = str(task.get("id_planu", ""))
    if plan_id not in visible_plans or not plan_is_readable(person, plan_by_id.get(plan_id)):
        return False
    if not clearance_allows(
        str(person.get("klauzula_tajnosci", "")),
        str(task.get("klauzula_tajnosci", "scisle_tajne")),
    ):
        return False
    assigned = {str(uid) for uid in task.get("id_jednostek", [])}
    # Tasks with explicit unit assignments require at least one visible assignment.
    # Unassigned tasks inherit the visibility of their plan.
    return not assigned or bool(assigned & visible_units)


def not_found() -> HTTPException:
    # Avoid revealing whether an inaccessible record exists.
    return HTTPException(404, "Record not found")


def sanitize_plan(plan: dict[str, Any], visible_plan_ids: set[str]) -> dict[str, Any]:
    result = dict(plan)
    parent = result.get("id_planu_nadrzednego")
    if parent is not None and str(parent) not in visible_plan_ids:
        result["id_planu_nadrzednego"] = None
    if "podplany" in result:
        result["podplany"] = [pid for pid in result["podplany"] if str(pid) in visible_plan_ids]
    return result


def sanitize_task(task: dict[str, Any], visible_unit_ids: set[str]) -> dict[str, Any]:
    result = dict(task)
    result["id_jednostek"] = [uid for uid in result.get("id_jednostek", []) if str(uid) in visible_unit_ids]
    return result


async def analytics_request(method: str, path: str, params: dict[str, Any] | None = None,
                            payload: dict[str, Any] | None = None) -> Any:
    """Proxy analytics requests only after Access has validated the caller."""
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.request(
                method, f"{ANALYTICS_HISTORY_SERVICE_URL}{path}",
                params=params, json=payload,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Analytics history service unavailable") from exc
    if response.status_code in (400, 404, 422):
        raise HTTPException(response.status_code, response.text)
    if response.status_code != 200:
        raise HTTPException(502, "Analytics history service returned an error")
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(502, "Analytics history service returned invalid JSON") from exc


async def require_national_analytics(x_person_id: str | None) -> dict[str, Any]:
    """Imported workbook has no unit mapping; its global aggregates are Premier-only."""
    if not x_person_id:
        raise HTTPException(401, "Missing X-Person-Id identity header")
    person = await resolve_person(x_person_id)
    if str(person.get("id_jednostki")) != "U-PRM" and str(person.get("id_osoby")) != "demo-premier":
        raise HTTPException(403, "Analizy historyczne zbioru demonstracyjnego są dostępne wyłącznie w perspektywie krajowej.")
    return person


@app.get("/analytics/operational")
async def analytics_operational(x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    await require_national_analytics(x_person_id)
    return await analytics_request("GET", "/analysis/operational")


@app.get("/analytics/history/snapshots")
async def analytics_snapshots(x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    await require_national_analytics(x_person_id)
    return await analytics_request("GET", "/history/snapshots")


@app.get("/analytics/history/summary")
async def analytics_summary(
    snapshot_id: str = Query("D+2"),
    x_person_id: str | None = Header(default=None, alias="X-Person-Id"),
):
    await require_national_analytics(x_person_id)
    return await analytics_request("GET", "/history/summary", {"snapshot_id": snapshot_id})


@app.get("/analytics/history/changes")
async def analytics_changes(
    from_snapshot: str = "D",
    to_snapshot: str = "D+2",
    task_type: str | None = None,
    limit: int = Query(500, ge=1, le=5000),
    x_person_id: str | None = Header(default=None, alias="X-Person-Id"),
):
    await require_national_analytics(x_person_id)
    params = {"from_snapshot": from_snapshot, "to_snapshot": to_snapshot, "limit": limit}
    if task_type:
        params["task_type"] = task_type
    return await analytics_request("GET", "/history/changes", params)


@app.post("/analytics/simulations/progress")
async def analytics_progress_simulation(
    payload: dict[str, Any],
    x_person_id: str | None = Header(default=None, alias="X-Person-Id"),
):
    await require_national_analytics(x_person_id)
    return await analytics_request("POST", "/simulations/progress", payload=payload)


@app.get("/analytics/simulations")
async def analytics_simulations(
    limit: int = Query(50, ge=1, le=500),
    x_person_id: str | None = Header(default=None, alias="X-Person-Id"),
):
    await require_national_analytics(x_person_id)
    return await analytics_request("GET", "/simulations", {"limit": limit})


@app.get("/health")
def health():
    return {
        "service": "access",
        "status": "ok",
        "identity_mode": "header_or_demo_default" if DEFAULT_PERSON_ID else "header_required",
    }


@app.get("/demo-identities")
async def get_demo_identities():
    """List synthetic demo accounts for the PoC identity selector.

    This endpoint deliberately exposes only accounts whose IDs use the demo-
    prefix and only the fields needed to choose a demo perspective. It is not
    an authentication endpoint and must be disabled or replaced by an IdP in
    a production deployment.
    """
    people = await data_get("/people")
    units = await data_get("/units")
    unit_names = {str(unit["id"]): unit.get("nazwa", str(unit["id"])) for unit in units}
    result = []
    for person in people:
        person_id = str(person.get("id_osoby", ""))
        if not person_id.startswith("demo-") or not person.get("aktywna", False):
            continue
        unit_id = str(person.get("id_jednostki", ""))
        result.append({
            "id_osoby": person_id,
            "imie": person.get("imie", ""),
            "nazwisko": person.get("nazwisko", ""),
            "id_jednostki": unit_id,
            "nazwa_jednostki": unit_names.get(unit_id, unit_id),
            "stanowisko": person.get("stanowisko", ""),
            "klauzula_tajnosci": person.get("klauzula_tajnosci", "jawne"),
        })
    return result


@app.get("/me")
async def me(x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    person = await resolve_person(x_person_id)
    # Do not expose internal database fields beyond the caller's own identity record.
    return person


@app.get("/units")
async def get_visible_units(
    region_id: str | None = None,
    plan_id: str | None = None,
    x_person_id: str | None = Header(default=None, alias="X-Person-Id"),
):
    person = await resolve_person(x_person_id)
    visible_units, visible_plans, units, plans = await access_context(person)
    readable_ids = readable_plan_ids(person, plans, visible_plans)
    result = []
    unit_by_id = {str(unit["id"]): unit for unit in units}
    for unit in units:
        uid = str(unit["id"])
        if uid not in visible_units:
            continue
        if region_id and unit.get("id_regionu") != region_id:
            continue
        if plan_id and plan_id not in readable_ids:
            continue
        if plan_id and plan_id not in {str(p) for p in unit.get("id_planow", [])}:
            continue
        item = dict(unit)
        item["id_planow"] = [pid for pid in item.get("id_planow", []) if str(pid) in readable_ids]
        parent_id = str(item.get("id_jednostki_nadrzednej") or "")
        parent = unit_by_id.get(parent_id)
        # Expose only the parent display name as organizational context; do not expose
        # the parent's plans, budget, staff, or other record fields through this field.
        item["nazwa_jednostki_nadrzednej"] = parent.get("nazwa") if parent else None
        # A caller can see their own roster, not personnel data of subordinate/peer units.
        if uid != str(person["id_jednostki"]):
            item["pracownicy"] = []
        result.append(item)
    return result


@app.get("/units/{unit_id}")
async def get_visible_unit(
    unit_id: str,
    x_person_id: str | None = Header(default=None, alias="X-Person-Id"),
):
    person = await resolve_person(x_person_id)
    visible_units, visible_plans, units, plans = await access_context(person)
    readable_ids = readable_plan_ids(person, plans, visible_plans)
    unit = next((u for u in units if str(u["id"]) == unit_id), None)
    if unit is None or unit_id not in visible_units:
        raise not_found()
    item = dict(unit)
    item["id_planow"] = [pid for pid in item.get("id_planow", []) if str(pid) in readable_ids]
    parent_id = str(item.get("id_jednostki_nadrzednej") or "")
    parent = next((u for u in units if str(u.get("id")) == parent_id), None)
    item["nazwa_jednostki_nadrzednej"] = parent.get("nazwa") if parent else None
    if unit_id != str(person["id_jednostki"]):
        item["pracownicy"] = []
    return item


@app.get("/requirements")
async def get_unit_requirements(x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    """Return only planning requirements addressed to the caller's own unit."""
    person = await resolve_person(x_person_id)
    _, _, units, plans = await access_context(person)
    own_id = str(person["id_jednostki"])
    own_parent = str(next((u.get("id_jednostki_nadrzednej") for u in units if str(u["id"]) == own_id), "") or "")
    owners = {str(pid): str(u["id"]) for u in units for pid in u.get("id_planow", [])}
    results = []
    for plan in plans:
        if not plan_is_readable(person, plan) or owners.get(str(plan.get("id_planu"))) != own_parent:
            continue
        for requirement in plan.get("wymogi", []) or []:
            if str(requirement.get("id_jednostki")) == own_id:
                results.append({
                    "id_planu_nadrzednego": str(plan["id_planu"]),
                    "nazwa_planu_nadrzednego": str(plan.get("nazwa_dokumentu", "Plan nadrzędny")),
                    "klauzula_tajnosci": plan.get("klauzula_tajnosci", "scisle_tajne"),
                    "wymog": dict(requirement),
                })
    return results


@app.get("/plans")
async def get_visible_plans(x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    person = await resolve_person(x_person_id)
    _, visible_plan_ids, _, plans = await access_context(person)
    readable_ids = readable_plan_ids(person, plans, visible_plan_ids)
    return [sanitize_plan(plan, readable_ids) for plan in plans if str(plan["id_planu"]) in readable_ids]


@app.get("/plans/{plan_id}")
async def get_visible_plan(
    plan_id: str,
    x_person_id: str | None = Header(default=None, alias="X-Person-Id"),
):
    person = await resolve_person(x_person_id)
    _, visible_plan_ids, _, plans = await access_context(person)
    plan = next((p for p in plans if str(p["id_planu"]) == plan_id), None)
    if plan_id not in visible_plan_ids or not plan_is_readable(person, plan):
        raise not_found()
    readable_ids = readable_plan_ids(person, plans, visible_plan_ids)
    result = dict(plan)
    result["podplany"] = [
        str(p["id_planu"]) for p in plans
        if str(p.get("id_planu_nadrzednego") or "") == plan_id
        and str(p["id_planu"]) in readable_ids
    ]
    return sanitize_plan(result, readable_ids)


@app.get("/tasks")
async def get_visible_tasks(
    plan_id: str | None = None,
    unit_id: str | None = None,
    region_id: str | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    x_person_id: str | None = Header(default=None, alias="X-Person-Id"),
):
    person = await resolve_person(x_person_id)
    visible_units, visible_plan_ids, units, plans = await access_context(person)
    if unit_id and unit_id not in visible_units:
        return []
    plan_by_id = {str(p["id_planu"]): p for p in plans}
    tasks = await data_get("/tasks", {"limit": limit})
    unit_by_id = {str(u["id"]): u for u in units}
    result = []
    for task in tasks:
        pid = str(task["id_planu"])
        assigned = {str(uid) for uid in task.get("id_jednostek", [])}
        if not task_is_readable(person, task, plan_by_id, visible_units, visible_plan_ids):
            continue
        if plan_id and pid != plan_id:
            continue
        if unit_id and unit_id not in assigned:
            continue
        visible_assigned = assigned & visible_units
        if region_id and not any(unit_by_id.get(uid, {}).get("id_regionu") == region_id for uid in visible_assigned):
            continue
        result.append(sanitize_task(task, visible_units))
    return result


@app.get("/tasks/{plan_id}/{task_id}")
async def get_visible_task(
    plan_id: str,
    task_id: str,
    x_person_id: str | None = Header(default=None, alias="X-Person-Id"),
):
    person = await resolve_person(x_person_id)
    visible_units, visible_plan_ids, units, plans = await access_context(person)
    if plan_id not in visible_plan_ids:
        raise not_found()
    plan_by_id = {str(p["id_planu"]): p for p in plans}
    tasks = await data_get("/tasks", {"plan_id": plan_id, "limit": 5000})
    task = next((t for t in tasks if str(t["id_zadania"]) == task_id), None)
    if task is None or not task_is_readable(person, task, plan_by_id, visible_units, visible_plan_ids):
        raise not_found()
    result = sanitize_task(task, visible_units)
    # Add only safe, filtered context useful to API consumers.
    result["plan"] = sanitize_plan(plan_by_id[plan_id], readable_plan_ids(person, plans, visible_plan_ids))
    unit_by_id = {str(u["id"]): u for u in units}
    result["jednostki"] = [
        {"id": uid, "nazwa": unit_by_id[uid]["nazwa"], "id_regionu": unit_by_id[uid].get("id_regionu")}
        for uid in result["id_jednostek"] if uid in unit_by_id
    ]
    return result


@app.get("/collaboration-summary")
async def get_collaboration_summary(
    x_person_id: str | None = Header(default=None, alias="X-Person-Id"),
):
    """Return only explicitly released aggregate counts from collaborating units.

    A relation is directional: source `unit_id` releases aggregate information to
    `partner_unit_id`. No plan names, task IDs, task names, or task-level records are
    returned. This is the PoC's information-gate demonstration.
    """
    person = await resolve_person(x_person_id)
    recipient_id = str(person["id_jednostki"])
    relations = await data_get("/cooperation", {"unit_id": recipient_id})
    inbound = [
        r for r in relations
        if str(r.get("partner_unit_id")) == recipient_id
        and r.get("sharing_level") == "aggregate"
    ]
    if not inbound:
        return []

    units = await data_get("/units")
    plans = await data_get("/plans")
    tasks = await data_get("/tasks", {"limit": 5000})
    unit_by_id = {str(u["id"]): u for u in units}
    plan_by_id = {str(p["id_planu"]): p for p in plans}
    summaries = []
    for relation in inbound:
        source_id = str(relation["unit_id"])
        source = unit_by_id.get(source_id)
        if source is None:
            continue
        source_plan_ids = {str(pid) for pid in source.get("id_planow", [])}
        changed = True
        while changed:
            changed = False
            for plan in plans:
                pid = str(plan["id_planu"])
                parent = str(plan.get("id_planu_nadrzednego") or "")
                if parent in source_plan_ids and pid not in source_plan_ids:
                    source_plan_ids.add(pid)
                    changed = True
        source_tasks = [
            task for task in tasks
            if str(task.get("id_planu")) in source_plan_ids
        ]
        completed = sum(1 for task in source_tasks if bool(task.get("status")))
        summaries.append({
            "jednostka": source.get("nazwa", source_id),
            "liczba_zadan": len(source_tasks),
            "liczba_zrealizowanych": completed,
            "poziom_realizacji_proc": round(
                100 * sum(float(task.get("poziom_realizacji", 0)) for task in source_tasks) / len(source_tasks), 1
            ) if source_tasks else 0.0,
            "zakres": "aggregate_only",
        })
    return summaries


@app.get("/state", response_model=OperationalState)
async def get_state(x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    person = await resolve_person(x_person_id)
    visible_units, visible_plan_ids, units, plans = await access_context(person)
    plan_by_id = {str(p["id_planu"]): p for p in plans}
    raw_tasks = await data_get("/tasks", {"limit": 5000})
    filtered_tasks = [
        task for task in raw_tasks
        if task_is_readable(person, task, plan_by_id, visible_units, visible_plan_ids)
    ]

    unit_by_id = {str(u["id"]): u for u in units}
    tasks = []
    for task in filtered_tasks:
        visible_assigned = [str(uid) for uid in task.get("id_jednostek", []) if str(uid) in visible_units]
        region = next((unit_by_id[uid].get("id_regionu") for uid in visible_assigned
                       if unit_by_id.get(uid, {}).get("id_regionu")), "PL-MZ")
        status = "completed" if task["status"] else ("in_progress" if task["poziom_realizacji"] > 0 else "planned")
        tasks.append(Task(
            id=f'{task["id_planu"]}:{task["id_zadania"]}',
            name=task["nazwa_zadania"], region_id=region,
            completion=task["poziom_realizacji"], status=status,
        ))

    resources = []
    for unit in units:
        uid = str(unit["id"])
        if uid not in visible_units:
            continue
        for resource_type, quantity in unit.get("zasoby", {}).items():
            try:
                quantity = float(quantity)
            except (TypeError, ValueError):
                continue
            resources.append({
                "id": f'{uid}:{resource_type}', "type": resource_type,
                "region_id": unit.get("id_regionu") or "PL-00", "quantity": quantity,
            })
    from datetime import datetime, timezone
    return OperationalState(
        version=datetime.now(timezone.utc).isoformat(),
        tasks=tasks, resources=resources, infrastructure=[],
    )


@app.post("/plans", status_code=201)
async def create_visible_plan(payload: dict[str, Any], x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    person = await resolve_person(x_person_id)
    visible_units, visible_plan_ids, units, plans = await access_context(person)
    owner_id = str(payload.get("id_jednostki_wlasciciela", ""))
    own_id = str(person["id_jednostki"])
    if owner_id != own_id:
        raise HTTPException(403, "A user may create plans only for their own unit")
    parent_id = str(payload.get("id_planu_nadrzednego") or "")
    direct_children = {str(u["id"]) for u in units if str(u.get("id_jednostki_nadrzednej") or "") == own_id}
    for requirement in payload.get("wymogi", []):
        if str(requirement.get("id_jednostki")) not in direct_children:
            raise HTTPException(403, "Requirements may target only directly subordinate units")
    if parent_id:
        parent = next((p for p in plans if str(p["id_planu"]) == parent_id), None)
        if not parent or not plan_is_readable(person, parent):
            raise not_found()
        owners = {str(pid): str(u["id"]) for u in units for pid in u.get("id_planow", [])}
        parent_owner = owners.get(parent_id, "")
        own_parent = str(next((u.get("id_jednostki_nadrzednej") for u in units if str(u["id"]) == own_id), "") or "")
        if parent_id not in visible_plan_ids and parent_owner != own_parent:
            raise HTTPException(403, "A child plan must reference an own or directly superior plan")
        if parent_owner != own_id and parent_owner != own_parent:
            raise HTTPException(403, "A child plan must reference an own or directly superior plan")
    return await data_mutate("POST", "/plans", payload)


@app.put("/plans/{plan_id}")
async def update_visible_plan(plan_id: str, payload: dict[str, Any], x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    person = await resolve_person(x_person_id)
    visible_units, visible_plan_ids, units, plans = await access_context(person)
    own_id = str(person["id_jednostki"])
    owners = {str(pid): str(u["id"]) for u in units for pid in u.get("id_planow", [])}
    plan = next((p for p in plans if str(p.get("id_planu")) == plan_id), None)
    if plan_id not in visible_plan_ids or not plan_is_readable(person, plan) or owners.get(plan_id) != own_id:
        raise not_found()
    if plan.get("status_planu") not in ("editing", "draft", "rejected"):
        raise HTTPException(409, "Only editable plans can be changed")
    if str(payload.get("id_jednostki_wlasciciela", "")) != own_id:
        raise HTTPException(403, "A user may edit plans only for their own unit")
    parent_id = str(payload.get("id_planu_nadrzednego") or "")
    if parent_id:
        parent = next((p for p in plans if str(p.get("id_planu")) == parent_id), None)
        if not parent or not plan_is_readable(person, parent):
            raise not_found()
        parent_owner = owners.get(parent_id, "")
        own_parent = str(next((u.get("id_jednostki_nadrzednej") for u in units if str(u["id"]) == own_id), "") or "")
        if parent_id not in visible_plan_ids and parent_owner != own_parent:
            raise HTTPException(403, "A child plan must reference an own or directly superior plan")
        if parent_owner != own_id and parent_owner != own_parent:
            raise HTTPException(403, "A child plan must reference an own or directly superior plan")
    direct_children = {str(u["id"]) for u in units if str(u.get("id_jednostki_nadrzednej") or "") == own_id}
    for requirement in payload.get("wymogi", []):
        if str(requirement.get("id_jednostki")) not in direct_children:
            raise HTTPException(403, "Requirements may target only directly subordinate units")
    return await data_mutate("PUT", f"/plans/{plan_id}", payload)


@app.put("/plans/{plan_id}/requirements")
async def update_visible_requirements(plan_id: str, payload: dict[str, Any], x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    person = await resolve_person(x_person_id)
    visible_units, visible_plan_ids, units, plans = await access_context(person)
    own_id = str(person["id_jednostki"])
    owners = {str(pid): str(u["id"]) for u in units for pid in u.get("id_planow", [])}
    if plan_id not in visible_plan_ids or owners.get(plan_id) != own_id: raise not_found()
    direct_children = {str(u["id"]) for u in units if str(u.get("id_jednostki_nadrzednej") or "") == own_id}
    for requirement in payload.get("wymogi", []):
        if str(requirement.get("id_jednostki")) not in direct_children:
            raise HTTPException(403, "Requirements may target only directly subordinate units")
    return await data_mutate("PUT", f"/plans/{plan_id}/requirements", payload)

@app.post("/plans/{plan_id}/submit")
async def submit_visible_plan(plan_id: str, x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    person = await resolve_person(x_person_id)
    visible_units, visible_plan_ids, units, plans = await access_context(person)
    owners = {str(pid): str(u["id"]) for u in units for pid in u.get("id_planow", [])}
    if plan_id not in visible_plan_ids or owners.get(plan_id) != str(person["id_jednostki"]): raise not_found()
    return await data_mutate("POST", f"/plans/{plan_id}/submit", {})

@app.post("/plans/{plan_id}/approve")
async def approve_visible_plan(plan_id: str, x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    person = await resolve_person(x_person_id)
    visible_units, visible_plan_ids, units, plans = await access_context(person)
    plan = next((p for p in plans if str(p["id_planu"]) == plan_id), None)
    if plan_id not in visible_plan_ids or not plan_is_readable(person, plan): raise not_found()
    owners = {str(pid): str(u["id"]) for u in units for pid in u.get("id_planow", [])}
    owner_id = owners.get(plan_id, "")
    direct_children = {str(u["id"]) for u in units if str(u.get("id_jednostki_nadrzednej") or "") == str(person["id_jednostki"])}
    if owner_id not in direct_children: raise HTTPException(403, "Only the directly superior unit may approve this plan")
    return await data_mutate("POST", f"/plans/{plan_id}/approve", {})

@app.post("/plans/{plan_id}/activate")
async def activate_visible_plan(
    plan_id: str,
    x_person_id: str | None = Header(default=None, alias="X-Person-Id"),
):
    """Only the plan's owning unit or its direct organizational superior may activate it."""
    person = await resolve_person(x_person_id)
    visible_units, visible_plan_ids, units, plans = await access_context(person)
    plan = next((p for p in plans if str(p["id_planu"]) == plan_id), None)
    if plan is None or plan_id not in visible_plan_ids or not plan_is_readable(person, plan):
        raise not_found()
    own_unit_id = str(person["id_jednostki"])
    unit_by_id = {str(u["id"]): u for u in units}
    owners = {str(pid): str(unit["id"]) for unit in units for pid in unit.get("id_planow", [])}
    owner_id = owners.get(plan_id)
    # The user may activate plans assigned to their own unit or to one of their direct reports.
    direct_report_ids = {str(u["id"]) for u in units if str(u.get("id_jednostki_nadrzednej") or "") == own_unit_id}
    if not owner_id or (owner_id != own_unit_id and owner_id not in direct_report_ids):
        raise HTTPException(403, "Only the plan owner or the directly superior unit may activate this plan")
    if owner_id not in visible_units or owner_id not in unit_by_id:
        raise not_found()
    return await data_mutate("POST", f"/plans/{plan_id}/activate", {"activated_by": str(person["id_osoby"])})


@app.patch("/tasks/{plan_id}/{task_id}/progress")
async def update_owned_task_progress(
    plan_id: str,
    task_id: str,
    payload: dict[str, Any],
    x_person_id: str | None = Header(default=None, alias="X-Person-Id"),
):
    person = await resolve_person(x_person_id)
    visible_units, visible_plan_ids, units, plans = await access_context(person)
    if plan_id not in visible_plan_ids:
        raise not_found()
    plan_by_id = {str(p["id_planu"]): p for p in plans}
    tasks = await data_get("/tasks", {"plan_id": plan_id, "limit": 5000})
    task = next((t for t in tasks if str(t.get("id_zadania")) == task_id), None)
    if task is None or not task_is_readable(person, task, plan_by_id, visible_units, visible_plan_ids):
        raise not_found()
    assigned = {str(uid) for uid in task.get("id_jednostek", [])}
    if not assigned:
        owner_id = next((str(u["id"]) for u in units if plan_id in {str(x) for x in u.get("id_planow", [])}), "")
        assigned = {owner_id} if owner_id else set()
    own_unit_id = str(person["id_jednostki"])
    if assigned != {own_unit_id}:
        raise HTTPException(403, "A unit may update only tasks assigned exclusively to that unit")
    task_type = task.get("typ_zadania", "REAL")
    plan = plan_by_id.get(plan_id, {})
    if task_type == "REAL" and plan.get("status_operacyjny", "prepared") != "active":
        raise HTTPException(409, "The plan must be active before REAL tasks can be updated")
    if task_type == "PRZ" and plan.get("status_planu") != "approved":
        raise HTTPException(409, "Preparatory tasks may be reported only after the plan is approved")
    if task_type not in ("REAL", "PRZ"):
        raise HTTPException(409, "Unsupported task type")
    try:
        progress = float(payload.get("poziom_realizacji"))
    except (TypeError, ValueError):
        raise HTTPException(422, "poziom_realizacji must be a number between 0 and 1")
    if not 0 <= progress <= 1:
        raise HTTPException(422, "poziom_realizacji must be between 0 and 1")
    return await data_mutate("PATCH", f"/tasks/{plan_id}/{task_id}/progress", {"poziom_realizacji": progress})
