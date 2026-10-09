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
