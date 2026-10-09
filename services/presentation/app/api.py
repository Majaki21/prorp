import os
import httpx
from fastapi import FastAPI, HTTPException
from pro_rp_shared.models import SimulationRequest

app = FastAPI(title="PRO RP Presentation Service")

ACCESS_SERVICE_URL = os.getenv("ACCESS_SERVICE_URL", "http://localhost:8002")
SIMULATION_SERVICE_URL = os.getenv("SIMULATION_SERVICE_URL", "http://localhost:8001")


@app.get("/health")
def health():
    return {"service": "presentation", "status": "ok"}


@app.get("/api/state")
async def state():
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(f"{ACCESS_SERVICE_URL}/state")

    if response.status_code != 200:
        raise HTTPException(502, "Access service unavailable")

    return response.json()


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
