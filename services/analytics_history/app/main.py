from __future__ import annotations
import json
import os
import sqlite3
import uuid
import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import httpx
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

DEFAULT_DB = Path(os.getenv("ANALYTICS_HISTORY_DB", Path(__file__).resolve().parents[1] / "data" / "analytics_history.db"))
ACCESS_SERVICE_URL = os.getenv("ACCESS_SERVICE_URL", "http://access:8000").rstrip("/")
HISTORY_PERSON_ID = os.getenv("HISTORY_PERSON_ID", os.getenv("DEFAULT_PERSON_ID", "demo-U-PRM"))
COLLECTION_INTERVAL_SECONDS = max(0, int(os.getenv("HISTORY_COLLECTION_INTERVAL_SECONDS", "86400")))

def init_history_schema():
    """Additive migrations only: keep existing demo history and operational DB untouched."""
    with sqlite3.connect(DEFAULT_DB) as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS collection_runs (
            run_id TEXT PRIMARY KEY,
            checked_at TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('success','failed')),
            tasks_seen INTEGER NOT NULL DEFAULT 0,
            changes_saved INTEGER NOT NULL DEFAULT 0,
            error_message TEXT
        );
        CREATE TABLE IF NOT EXISTS task_state_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT NOT NULL,
            task_type TEXT NOT NULL DEFAULT 'unknown',
            progress REAL NOT NULL CHECK(progress >= 0 AND progress <= 1),
            observed_at TEXT NOT NULL,
            run_id TEXT NOT NULL,
            event_kind TEXT NOT NULL CHECK(event_kind IN ('baseline','change')),
            FOREIGN KEY(run_id) REFERENCES collection_runs(run_id)
        );
        CREATE INDEX IF NOT EXISTS idx_state_events_task_time
            ON task_state_events(task_id, observed_at);
        CREATE INDEX IF NOT EXISTS idx_state_events_time
            ON task_state_events(observed_at);
        """)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_history_schema()
    task = None
    if COLLECTION_INTERVAL_SECONDS > 0:
        task = asyncio.create_task(collection_loop())
    try:
        yield
    finally:
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

app = FastAPI(title="PRO RP Analytics History API", version="0.2.0",
              description="Oddzielne API historii analitycznej. Nie modyfikuje bazy operacyjnej.",
              lifespan=lifespan)

def connect():
    if not DEFAULT_DB.exists():
        raise HTTPException(503, "Baza historii nie istnieje. Uruchom import_excel.py.")
    con = sqlite3.connect(DEFAULT_DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con

def rows(sql, params=()):
    with connect() as con:
        return [dict(r) for r in con.execute(sql, params).fetchall()]

def progress_value(task: dict) -> float:
    # /access/tasks currently exposes poziom_realizacji in range 0..1.
    raw = task.get("poziom_realizacji", task.get("completion"))
    if raw is None:
        raise ValueError(f"Brak pola postępu dla zadania {task.get('id_zadania', task.get('id'))}")
    value = float(raw)
    if not 0 <= value <= 1:
        raise ValueError(f"Postęp poza zakresem 0..1 dla zadania {task.get('id_zadania', task.get('id'))}")
    return value

def record_observation(tasks: list[dict], checked_at: str | None = None) -> dict:
    """Record every successful check, but task events only for first observation or actual changes."""
    checked_at = checked_at or datetime.now(timezone.utc).isoformat()
    run_id = str(uuid.uuid4())
    changes = 0
    with sqlite3.connect(DEFAULT_DB) as con:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.execute(
            "INSERT INTO collection_runs(run_id,checked_at,status,tasks_seen,changes_saved) VALUES(?,?,?,?,?)",
            (run_id, checked_at, "success", len(tasks), 0),
        )
        for task in tasks:
            task_id = str(task.get("id") or f"{task.get('id_planu', '')}:{task.get('id_zadania', '')}").strip(":")
            if not task_id:
                raise ValueError("Zadanie nie ma identyfikatora.")
            progress = progress_value(task)
            task_type = str(task.get("typ") or task.get("task_type") or task.get("id_planu") or "unknown")
            previous = con.execute(
                "SELECT progress FROM task_state_events WHERE task_id=? ORDER BY observed_at DESC,event_id DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            if previous is None or abs(float(previous["progress"]) - progress) > 1e-9:
                con.execute("""INSERT INTO task_state_events
                    (task_id,task_type,progress,observed_at,run_id,event_kind)
                    VALUES(?,?,?,?,?,?)""",
                    (task_id, task_type, progress, checked_at, run_id,
                     "baseline" if previous is None else "change"))
                changes += 1
        con.execute("UPDATE collection_runs SET changes_saved=? WHERE run_id=?", (changes, run_id))
        con.commit()
    return {"run_id": run_id, "checked_at": checked_at, "status": "success",
            "tasks_seen": len(tasks), "changes_saved": changes}

async def collect_from_access() -> dict:
    if not HISTORY_PERSON_ID:
        raise RuntimeError("Brak HISTORY_PERSON_ID; ustaw konto techniczne z odpowiednimi uprawnieniami.")
    run_id = str(uuid.uuid4())
    checked_at = datetime.now(timezone.utc).isoformat()
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.get(
                f"{ACCESS_SERVICE_URL}/tasks",
                params={"limit": 5000},
                headers={"X-Person-Id": HISTORY_PERSON_ID},
            )
            response.raise_for_status()
            tasks = response.json()
        if not isinstance(tasks, list):
            raise ValueError("Access API nie zwróciło listy zadań.")
        # Validate all rows before recording, so a partial/invalid response is not treated as a good check.
        for task in tasks:
            progress_value(task)
            if not (task.get("id") or (task.get("id_planu") and task.get("id_zadania"))):
                raise ValueError("Access API zwróciło zadanie bez identyfikatora.")
        return record_observation(tasks, checked_at)
    except Exception as exc:
        with sqlite3.connect(DEFAULT_DB) as con:
            con.execute("""INSERT INTO collection_runs
                (run_id,checked_at,status,tasks_seen,changes_saved,error_message)
                VALUES(?,?, 'failed',0,0,?)""",
                (run_id, checked_at, str(exc)[:1000]))
            con.commit()
        raise

async def collection_loop():
    # Start only after the app has initialized its database schema.
    while True:
        try:
            await collect_from_access()
        except Exception:
            # Failure is recorded in collection_runs; keep the service alive for the next attempt.
            pass
        await asyncio.sleep(COLLECTION_INTERVAL_SECONDS)

@app.post("/history/collect")
async def collect_now():
    """Trigger one collection from the permission-filtered Access API."""
    try:
        return await collect_from_access()
    except Exception as exc:
        raise HTTPException(502, f"Nie udało się pobrać danych z Access API: {exc}") from exc

@app.get("/history/collections")
def collection_history(limit: int = Query(50, ge=1, le=1000)):
    return {"collections": rows("""SELECT run_id, checked_at, status, tasks_seen,
        changes_saved, error_message FROM collection_runs
        ORDER BY checked_at DESC LIMIT ?""", (limit,))}

@app.get("/history/tasks/{task_id}/timeline")
def task_timeline(task_id: str):
    events = rows("""SELECT task_id, task_type, progress, observed_at, event_kind
        FROM task_state_events WHERE task_id=? ORDER BY observed_at,event_id""", (task_id,))
    if not events:
        raise HTTPException(404, "Brak zarejestrowanej historii zadania.")
    return {"task_id": task_id, "events": events}

@app.get("/history/state-at")
def state_at(at: str = Query(..., description="Data/czas ISO, np. 2026-10-09T23:59:59+00:00")):
    """Return each task's last observed value at or before the requested ISO timestamp."""
    try:
        datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(400, "Parametr at musi być datą/czasem ISO 8601.") from exc
    return {"at": at, "tasks": rows("""SELECT e.task_id,e.task_type,e.progress,e.observed_at
        FROM task_state_events e
        JOIN (SELECT task_id,MAX(event_id) AS event_id FROM task_state_events
              WHERE observed_at <= ? GROUP BY task_id) latest ON latest.event_id=e.event_id
        ORDER BY e.task_id""", (at,))}

@app.get("/health")
def health():
    return {"status": "ok", "component": "analytics_history", "database_exists": DEFAULT_DB.exists()}

@app.get("/history/snapshots")
def snapshots():
    return {"snapshots": rows("""SELECT s.snapshot_id, s.snapshot_date, s.label,
       COUNT(h.history_id) AS history_rows, COUNT(DISTINCT h.task_id) AS tasks
       FROM history_snapshots s LEFT JOIN task_progress_history h USING(snapshot_id)
       GROUP BY s.snapshot_id ORDER BY s.snapshot_date""")}

@app.get("/history/summary")
def summary(snapshot_id: str = Query("D+2")):
    if not rows("SELECT snapshot_id FROM history_snapshots WHERE snapshot_id=?", (snapshot_id,)):
        raise HTTPException(404, f"Nie znaleziono snapshotu: {snapshot_id}")
    task_rows = rows("""SELECT task_type, progress FROM task_progress_history WHERE snapshot_id=?""", (snapshot_id,))
    if not task_rows:
        raise HTTPException(404, "Snapshot nie zawiera zadań.")
    values = [float(r["progress"]) for r in task_rows]
    by_type = {}
    for typ in sorted(set(r["task_type"] for r in task_rows)):
        vs = [float(r["progress"]) for r in task_rows if r["task_type"] == typ]
        by_type[typ] = {"tasks": len(vs), "mean_progress": round(sum(vs)/len(vs), 4),
                        "completed_tasks": sum(v >= 1.0 for v in vs)}
    return {"snapshot_id": snapshot_id, "tasks": len(values),
            "mean_progress": round(sum(values)/len(values), 4),
            "completed_tasks": sum(v >= 1.0 for v in values),
            "incomplete_tasks": sum(v < 1.0 for v in values),
            "by_type": by_type,
            "data_note": "Dane demonstracyjne z pliku Excel; nie są danymi operacyjnymi PRO RP."}

@app.get("/history/changes")
def changes(from_snapshot: str = "D", to_snapshot: str = "D+2",
            task_type: Optional[str] = None, limit: int = Query(500, ge=1, le=5000)):
    base = rows("""SELECT task_id, task_type, progress FROM task_progress_history WHERE snapshot_id=?""", (from_snapshot,))
    end = rows("""SELECT task_id, task_type, progress FROM task_progress_history WHERE snapshot_id=?""", (to_snapshot,))
    if not base or not end:
        raise HTTPException(404, "Nie znaleziono jednego ze snapshotów.")
    a = {r["task_id"]: r for r in base}
    b = {r["task_id"]: r for r in end}
    result = []
    for tid in sorted(set(a) & set(b)):
        typ = b[tid]["task_type"]
        if task_type and typ != task_type:
            continue
        p0, p1 = float(a[tid]["progress"]), float(b[tid]["progress"])
        result.append({"task_id": tid, "task_type": typ, "progress_before": p0,
                       "progress_after": p1, "change_pp": round((p1-p0)*100, 2),
                       "relative_change_pct": None if p0 == 0 else round((p1-p0)/p0*100, 2)})
    result.sort(key=lambda r: r["change_pp"])
    return {"from_snapshot": from_snapshot, "to_snapshot": to_snapshot,
            "count": len(result), "changes": result[:limit],
            "definitions": {"change_pp": "różnica w punktach procentowych",
                            "relative_change_pct": "zmiana względna w procentach; null gdy stan początkowy wynosi 0"}}

@app.get("/history/tasks/{task_id}")
def task_history(task_id: str):
    history = rows("""SELECT h.task_id, h.task_type, h.snapshot_id, s.snapshot_date,
                      h.progress, h.source_sheet
                      FROM task_progress_history h JOIN history_snapshots s USING(snapshot_id)
                      WHERE h.task_id=? ORDER BY s.snapshot_date""", (task_id,))
    if not history:
        raise HTTPException(404, "Nie znaleziono historii zadania.")
    return {"task_id": task_id, "history": history}

class SimulationRequest(BaseModel):
    base_snapshot_id: str = "D+2"
    days_ahead: int = Field(default=2, ge=1, le=30)

@app.post("/simulations/progress")
def simulate_progress(req: SimulationRequest):
    base = rows("SELECT task_id, task_type, progress FROM task_progress_history WHERE snapshot_id=?", (req.base_snapshot_id,))
    if not base:
        raise HTTPException(404, "Nie znaleziono snapshotu bazowego.")
    other_id = "D" if req.base_snapshot_id == "D+2" else "D+2"
    other = rows("SELECT task_id, progress FROM task_progress_history WHERE snapshot_id=?", (other_id,))
    prev = {r["task_id"]: float(r["progress"]) for r in other}
    # The workbook's two snapshots are two days apart. This is an illustrative linear extrapolation, not a validated forecast.
    result = []
    for r in base:
        current = float(r["progress"])
        if r["task_id"] in prev:
            delta_per_day = (current - prev[r["task_id"]]) / 2.0
        else:
            delta_per_day = 0.0
        forecast = min(1.0, max(0.0, current + delta_per_day * req.days_ahead))
        result.append({"task_id": r["task_id"], "task_type": r["task_type"],
                       "base_progress": current, "daily_delta_assumed": round(delta_per_day, 4),
                       "forecast_progress": round(forecast, 4),
                       "forecast_change_pp": round((forecast-current)*100, 2)})
    payload = {"simulation_id": str(uuid.uuid4()), "base_snapshot_id": req.base_snapshot_id,
               "days_ahead": req.days_ahead, "method": "linear_extrapolation_from_two_snapshots",
               "results_count": len(result), "results": result,
               "warning": "Symulacja demonstracyjna oparta tylko na dwóch snapshotach z dwudniowego odstępu. Nie jest wiarygodną prognozą bez większej historii i walidacji."}
    with connect() as con:
        con.execute("""INSERT INTO simulation_runs(simulation_id, created_at, base_snapshot_id, days_ahead, method, parameters_json, results_json)
                       VALUES(?,?,?,?,?,?,?)""",
                    (payload["simulation_id"], datetime.now(timezone.utc).isoformat(), req.base_snapshot_id,
                     req.days_ahead, payload["method"], json.dumps(req.model_dump()), json.dumps(payload)))
        con.commit()
    return payload

@app.get("/simulations")
def list_simulations(limit: int = Query(50, ge=1, le=500)):
    return {"simulations": rows("""SELECT simulation_id, created_at, base_snapshot_id, days_ahead, method
                                  FROM simulation_runs ORDER BY created_at DESC LIMIT ?""", (limit,))}
