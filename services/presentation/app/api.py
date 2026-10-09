import os
import httpx
from fastapi import FastAPI, Header, HTTPException, Query
from pro_rp_shared.models import SimulationRequest

app = FastAPI(title="PRO RP Presentation Service")

ACCESS_SERVICE_URL = os.getenv("ACCESS_SERVICE_URL", "http://localhost:8002")
SIMULATION_SERVICE_URL = os.getenv("SIMULATION_SERVICE_URL", "http://localhost:8001")


@app.get("/health")
def health():
    return {"service": "presentation", "status": "ok"}


async def access_get(
    path: str,
    params: dict | None = None,
    person_id: str | None = None,
):
    headers = {"X-Person-Id": person_id} if person_id else {}
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(
                f"{ACCESS_SERVICE_URL}{path}", params=params, headers=headers
            )
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Access service unavailable") from exc

    if response.status_code != 200:
        if response.status_code in (401, 403, 404):
            raise HTTPException(response.status_code, response.text)
        raise HTTPException(502, "Access service returned an error")
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(502, "Access service returned invalid JSON") from exc


async def access_mutate(method: str, path: str, payload: dict, person_id: str | None = None):
    headers = {"X-Person-Id": person_id} if person_id else {}
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.request(method, f"{ACCESS_SERVICE_URL}{path}", json=payload, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Access service unavailable") from exc
    if response.status_code in (400, 401, 403, 404, 409, 422):
        raise HTTPException(response.status_code, response.text)
    if response.status_code not in (200, 201):
        raise HTTPException(502, "Access service returned an error")
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(502, "Access service returned invalid JSON") from exc


@app.get("/api/analytics/operational")
async def analytics_operational(x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    return await access_get("/analytics/operational", person_id=x_person_id)


@app.get("/api/analytics/history/snapshots")
async def analytics_snapshots(x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    return await access_get("/analytics/history/snapshots", person_id=x_person_id)


@app.get("/api/analytics/history/summary")
async def analytics_summary(
    snapshot_id: str = "D+2",
    x_person_id: str | None = Header(default=None, alias="X-Person-Id"),
):
    return await access_get("/analytics/history/summary", params={"snapshot_id": snapshot_id}, person_id=x_person_id)


@app.get("/api/analytics/history/changes")
async def analytics_changes(
    from_snapshot: str = "D",
    to_snapshot: str = "D+2",
    task_type: str | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    x_person_id: str | None = Header(default=None, alias="X-Person-Id"),
):
    params = {"from_snapshot": from_snapshot, "to_snapshot": to_snapshot, "limit": limit}
    if task_type:
        params["task_type"] = task_type
    return await access_get("/analytics/history/changes", params=params, person_id=x_person_id)


@app.post("/api/analytics/simulations/progress")
async def analytics_progress_simulation(
    payload: dict,
    x_person_id: str | None = Header(default=None, alias="X-Person-Id"),
):
    headers = {"X-Person-Id": x_person_id} if x_person_id else {}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{ACCESS_SERVICE_URL}/analytics/simulations/progress",
                json=payload, headers=headers,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Access service unavailable") from exc
    if response.status_code in (400, 401, 403, 404, 422):
        raise HTTPException(response.status_code, response.text)
    if response.status_code != 200:
        raise HTTPException(502, "Analytics service returned an error")
    return response.json()


@app.get("/api/analytics/simulations")
async def analytics_simulations(
    limit: int = Query(default=50, ge=1, le=500),
    x_person_id: str | None = Header(default=None, alias="X-Person-Id"),
):
    return await access_get("/analytics/simulations", params={"limit": limit}, person_id=x_person_id)


@app.get("/api/demo-identities")
async def demo_identities():
    return await access_get("/demo-identities")


@app.get("/api/me")
async def me(x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    return await access_get("/me", person_id=x_person_id)


@app.get("/api/collaboration-summary")
async def collaboration_summary(x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    return await access_get("/collaboration-summary", person_id=x_person_id)


@app.get("/api/state")
async def state(x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    return await access_get("/state", person_id=x_person_id)


@app.get("/api/requirements")
async def requirements(x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    return await access_get("/requirements", person_id=x_person_id)

@app.get("/api/plans")
async def plans(x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    return await access_get("/plans", person_id=x_person_id)


@app.get("/api/plans/{plan_id}")
async def plan_detail(
    plan_id: str,
    x_person_id: str | None = Header(default=None, alias="X-Person-Id"),
):
    return await access_get(f"/plans/{plan_id}", person_id=x_person_id)


@app.get("/api/units")
async def units(
    region_id: str | None = None,
    plan_id: str | None = None,
    x_person_id: str | None = Header(default=None, alias="X-Person-Id"),
):
    params = {k: v for k, v in {"region_id": region_id, "plan_id": plan_id}.items() if v is not None}
    return await access_get("/units", params=params, person_id=x_person_id)


@app.get("/api/units/{unit_id}")
async def unit_detail(
    unit_id: str,
    x_person_id: str | None = Header(default=None, alias="X-Person-Id"),
):
    return await access_get(f"/units/{unit_id}", person_id=x_person_id)


@app.get("/api/tasks")
async def tasks(
    plan_id: str | None = None,
    unit_id: str | None = None,
    region_id: str | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    x_person_id: str | None = Header(default=None, alias="X-Person-Id"),
):
    params = {k: v for k, v in {
        "plan_id": plan_id, "unit_id": unit_id, "region_id": region_id, "limit": limit
    }.items() if v is not None}
    return await access_get("/tasks", params=params, person_id=x_person_id)


@app.get("/api/tasks/{plan_id}/{task_id}")
async def task_detail(
    plan_id: str,
    task_id: str,
    x_person_id: str | None = Header(default=None, alias="X-Person-Id"),
):
    return await access_get(f"/tasks/{plan_id}/{task_id}", person_id=x_person_id)


@app.post("/api/plans", status_code=201)
async def create_plan(payload: dict, x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    return await access_mutate("POST", "/plans", payload, person_id=x_person_id)

@app.put("/api/plans/{plan_id}")
async def update_plan(plan_id: str, payload: dict, x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    return await access_mutate("PUT", f"/plans/{plan_id}", payload, person_id=x_person_id)


@app.put("/api/plans/{plan_id}/requirements")
async def update_plan_requirements(plan_id: str, payload: dict, x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    return await access_mutate("PUT", f"/plans/{plan_id}/requirements", payload, person_id=x_person_id)

@app.post("/api/plans/{plan_id}/submit")
async def submit_plan(plan_id: str, x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    return await access_mutate("POST", f"/plans/{plan_id}/submit", {}, person_id=x_person_id)

@app.post("/api/plans/{plan_id}/approve")
async def approve_plan(plan_id: str, x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    return await access_mutate("POST", f"/plans/{plan_id}/approve", {}, person_id=x_person_id)

@app.post("/api/plans/{plan_id}/activate")
async def activate_plan(
    plan_id: str,
    x_person_id: str | None = Header(default=None, alias="X-Person-Id"),
):
    return await access_mutate("POST", f"/plans/{plan_id}/activate", {}, person_id=x_person_id)




@app.post("/api/plans/{plan_id}/tasks", status_code=201)
async def create_task(plan_id: str, payload: dict, x_person_id: str | None = Header(default=None, alias="X-Person-Id")):
    return await access_mutate("POST", f"/plans/{plan_id}/tasks", payload, person_id=x_person_id)


@app.patch("/api/tasks/{plan_id}/{task_id}/progress")
async def update_task_progress(
    plan_id: str,
    task_id: str,
    payload: dict,
    x_person_id: str | None = Header(default=None, alias="X-Person-Id"),
):
    return await access_mutate("PATCH", f"/tasks/{plan_id}/{task_id}/progress", payload, person_id=x_person_id)


@app.post("/api/simulations")
async def simulation(request: SimulationRequest):
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"{SIMULATION_SERVICE_URL}/simulations",
            json=request.model_dump(),
        )

    if response.status_code != 200:
        raise HTTPException(502, "Simulation service unavailable")

    return response.json()
