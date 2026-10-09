import os
import uuid
import httpx
from fastapi import FastAPI, HTTPException
from pro_rp_shared.models import SimulationRequest, SimulationResult, SimulationEvent

app = FastAPI(title="PRO RP Simulation Service")

ACCESS_SERVICE_URL = os.getenv("ACCESS_SERVICE_URL", "http://localhost:8002")


@app.get("/health")
def health():
    return {"service": "simulation", "status": "ok"}


@app.post("/simulations", response_model=SimulationResult)
async def run_simulation(request: SimulationRequest):
    # 1. Obtain a snapshot of the real operational state.
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(f"{ACCESS_SERVICE_URL}/state")

    if response.status_code != 200:
        raise HTTPException(502, "Access service unavailable")

    state = response.json()

    # 2. Create an isolated simulation state.
    #
    # The real implementation should copy the state into a dedicated
    # SimulationState object and then apply scenario rules to it.
    disabled = set(request.scenario.disabled_resources)
    failed_infra = set(request.scenario.failed_infrastructure)

    events = []
    affected_tasks = []

    for resource in state["resources"]:
        if resource["id"] in disabled:
            events.append(
                SimulationEvent(
                    type="RESOURCE_UNAVAILABLE",
                    message=f"Resource {resource['id']} became unavailable.",
                    severity="warning",
                )
            )

    for infra in state["infrastructure"]:
        if infra["id"] in failed_infra:
            events.append(
                SimulationEvent(
                    type="INFRASTRUCTURE_FAILURE",
                    message=f"Infrastructure {infra['id']} failed.",
                    severity="critical",
                )
            )

    # Minimal demo metric. Replace with the dependency/cascade engine.
    readiness = sum(t["completion"] for t in state["tasks"]) / max(len(state["tasks"]), 1)

    if failed_infra or disabled:
        readiness *= 0.8
        affected_tasks = [t["id"] for t in state["tasks"] if t["status"] != "completed"]

    return SimulationResult(
        simulation_id=str(uuid.uuid4()),
        scenario_id=request.scenario.id,
        initial_state_version=state["version"],
        readiness_score=round(readiness, 3),
        events=events,
        affected_tasks=affected_tasks,
    )
