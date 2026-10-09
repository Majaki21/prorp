import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pro_rp_shared.models import (
    Infrastructure, OperationalState, Plan, Resource, Task, Osoba,
)

app = FastAPI(title="PRO RP Data Service", version="2.0.0")
DB_PATH = Path(os.getenv("PRO_RP_DB_PATH", "/data/pro_rp.sqlite3"))
SEED_PATH = Path(os.getenv("PRO_RP_SEED_PATH", str(Path(__file__).parent / "seed_data.json")))


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def db():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS plans (
            id_planu TEXT PRIMARY KEY,
            id_planu_nadrzednego TEXT NULL REFERENCES plans(id_planu),
            nazwa_dokumentu TEXT NOT NULL,
            sporzadzil TEXT NOT NULL,
            uzgadnial_json TEXT NOT NULL DEFAULT '[]',
            zatwierdzajacy TEXT,
            komentarz TEXT NOT NULL DEFAULT '',
            data_utworzenia TEXT NOT NULL,
            data_zatwierdzeina TEXT,
            status_planu TEXT NOT NULL DEFAULT 'draft',
            klauzula_tajnosci TEXT NOT NULL DEFAULT 'scisle_tajne'
        );
        CREATE TABLE IF NOT EXISTS units (
            id TEXT PRIMARY KEY,
            nazwa TEXT NOT NULL,
            id_jednostki_nadrzednej TEXT NULL REFERENCES units(id),
            id_planow_json TEXT NOT NULL DEFAULT '[]',
            budzet REAL NOT NULL DEFAULT 0,
            zasoby_json TEXT NOT NULL DEFAULT '{}',
            id_regionu TEXT,
            typ TEXT,
            pracownicy_json TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS tasks (
            id_planu TEXT NOT NULL REFERENCES plans(id_planu),
            id_zadania TEXT NOT NULL,
            id_jednostek_json TEXT NOT NULL DEFAULT '[]',
            nazwa_zadania TEXT NOT NULL,
            data_utworzenia TEXT NOT NULL,
            data_aktualizacji TEXT NOT NULL,
            status INTEGER NOT NULL DEFAULT 0,
            poziom_realizacji REAL NOT NULL DEFAULT 0 CHECK(poziom_realizacji >= 0 AND poziom_realizacji <= 1),
            koszt REAL NOT NULL DEFAULT 0,
            zasoby_json TEXT NOT NULL DEFAULT '{}',
            klauzula_tajnosci TEXT NOT NULL DEFAULT 'scisle_tajne',
            PRIMARY KEY (id_planu, id_zadania)
        );
        CREATE TABLE IF NOT EXISTS people (
            id_osoby TEXT PRIMARY KEY,
            imie TEXT NOT NULL,
            nazwisko TEXT NOT NULL,
            id_jednostki TEXT NOT NULL REFERENCES units(id),
            stanowisko TEXT NOT NULL DEFAULT '',
            klauzula_tajnosci TEXT NOT NULL DEFAULT 'jawne',
            aktywna INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS unit_cooperation (
            unit_id TEXT NOT NULL REFERENCES units(id),
            partner_unit_id TEXT NOT NULL REFERENCES units(id),
            sharing_level TEXT NOT NULL DEFAULT 'details',
            PRIMARY KEY (unit_id, partner_unit_id),
            CHECK(unit_id <> partner_unit_id)
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_plan ON tasks(id_planu);
        CREATE INDEX IF NOT EXISTS idx_units_region ON units(id_regionu);
        """)
        # Lightweight migrations for databases created by earlier PoC versions.
        for table, column, definition in [
            ("plans", "klauzula_tajnosci", "TEXT NOT NULL DEFAULT 'scisle_tajne'"),
            ("units", "pracownicy_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("tasks", "klauzula_tajnosci", "TEXT NOT NULL DEFAULT 'scisle_tajne'"),
            ("unit_cooperation", "sharing_level", "TEXT NOT NULL DEFAULT 'details'"),
        ]:
            existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

        count = conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0]
        if count == 0:
            if not SEED_PATH.exists():
                raise RuntimeError(f"Seed file not found: {SEED_PATH}")
            seed = json.loads(SEED_PATH.read_text(encoding="utf-8"))
            # Insert plans first; parent foreign keys are deferred in ordering by two passes.
            for p in seed.get("plans", []):
                conn.execute("""INSERT INTO plans (id_planu,id_planu_nadrzednego,nazwa_dokumentu,sporzadzil,uzgadnial_json,zatwierdzajacy,komentarz,data_utworzenia,data_zatwierdzeina,status_planu,klauzula_tajnosci) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                    p["id_planu"], None, p["nazwa_dokumentu"], p["sporzadzil"],
                    json.dumps(p.get("uzgadnial", []), ensure_ascii=False), p.get("zatwierdzajacy"),
                    p.get("komentarz", ""), p["data_utworzenia"], p.get("data_zatwierdzeina"),
                    p.get("status_planu", "draft"), p.get("klauzula_tajnosci", "jawne")
                ))
            for p in seed.get("plans", []):
                if p.get("id_planu_nadrzednego"):
                    conn.execute("UPDATE plans SET id_planu_nadrzednego=? WHERE id_planu=?",
                                 (p["id_planu_nadrzednego"], p["id_planu"]))
            for u in seed.get("units", []):
                conn.execute("""INSERT INTO units (id,nazwa,id_jednostki_nadrzednej,id_planow_json,budzet,zasoby_json,id_regionu,typ,pracownicy_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                    str(u["id"]), u["nazwa"], u.get("id_jednostki_nadrzednej"),
                    json.dumps(u.get("id_planow", []), ensure_ascii=False), float(u.get("budzet", 0)),
                    json.dumps(u.get("zasoby", {}), ensure_ascii=False), u.get("id_regionu"), u.get("typ"),
                    json.dumps(u.get("pracownicy", []), ensure_ascii=False)
                ))
            for t in seed.get("tasks", []):
                conn.execute("""INSERT INTO tasks (id_planu,id_zadania,id_jednostek_json,nazwa_zadania,data_utworzenia,data_aktualizacji,status,poziom_realizacji,koszt,zasoby_json,klauzula_tajnosci) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
                    t["id_planu"], t["id_zadania"], json.dumps(t.get("id_jednostek", []), ensure_ascii=False),
                    t["nazwa_zadania"], t["data_utworzenia"], t["data_aktualizacji"],
                    int(bool(t.get("status", False))), float(t.get("poziom_realizacji", 0)),
                    float(t.get("koszt", 0)), json.dumps(t.get("zasoby", {}), ensure_ascii=False),
                    t.get("klauzula_tajnosci", "jawne")
                ))
            # Optional employee seed; when omitted, create one clearly labelled demo account per unit.
            people_seed = seed.get("people", [])
            if not people_seed:
                for u in seed.get("units", []):
                    people_seed.append({
                        "id_osoby": f"demo-{u['id']}", "imie": "Użytkownik", "nazwisko": "Demo",
                        "id_jednostki": str(u["id"]), "stanowisko": "Konto demonstracyjne",
                        "klauzula_tajnosci": "jawne", "aktywna": True,
                    })
            for person in people_seed:
                conn.execute("""INSERT OR IGNORE INTO people
                    (id_osoby,imie,nazwisko,id_jednostki,stanowisko,klauzula_tajnosci,aktywna)
                    VALUES (?,?,?,?,?,?,?)""", (
                    person["id_osoby"], person["imie"], person["nazwisko"], str(person["id_jednostki"]),
                    person.get("stanowisko", ""), person.get("klauzula_tajnosci", "jawne"),
                    int(bool(person.get("aktywna", True)))
                ))
            for relation in seed.get("wspolpraca", []):
                conn.execute("INSERT OR IGNORE INTO unit_cooperation (unit_id,partner_unit_id,sharing_level) VALUES (?,?,?)",
                             (str(relation["unit_id"]), str(relation["partner_unit_id"]), relation.get("sharing_level", "details")))
        # If an older persistent database already had plans, bootstrap demo identities once too.
        if conn.execute("SELECT COUNT(*) FROM people").fetchone()[0] == 0:
            unit_rows = conn.execute("SELECT id FROM units ORDER BY id").fetchall()
            for unit_row in unit_rows:
                uid = str(unit_row["id"])
                conn.execute("INSERT OR IGNORE INTO people (id_osoby,imie,nazwisko,id_jednostki,stanowisko,klauzula_tajnosci,aktywna) VALUES (?,?,?,?,?,?,1)",
                             (f"demo-{uid}", "Użytkownik", "Demo", uid, "Konto demonstracyjne", "jawne"))


def apply_demo_access_scenario() -> None:
    """Apply an idempotent, synthetic access-control scenario for hackathon demos.

    This intentionally uses fictional role accounts except for the explicitly named
    Prime Minister demo perspective. It is not an authentication or classification
    authority for real information.
    """
    police_plans = ("ORP", "ORPP", "ORPPP", "PP", "PPP", "PPPP")
    fire_plans = ("ORS", "ORSS", "ORSSS", "PS", "PSS", "PSSS")
    assignment_by_plan = {
        "ORP": "U-KGP", "PP": "U-KGP",
        "ORPP": "U-KWP-MZ", "PPP": "U-KWP-MZ",
        "ORPPP": "U-KPP-RAD", "PPPP": "U-KPP-RAD",
        "ORS": "U-KGPSP", "PS": "U-KGPSP",
        "ORSS": "U-KWPSP-MZ", "PSS": "U-KWPSP-MZ",
        "ORSSS": "U-KPPSP-RAD", "PSSS": "U-KPPSP-RAD",
    }
    with db() as conn:
        # Keep the demo selector focused and avoid 19 indistinguishable "Użytkownik Demo" accounts.
        conn.execute("UPDATE people SET aktywna=0 WHERE id_osoby LIKE 'demo-U-%'")
        demo_people = [
            ("demo-premier", "Donald", "Tusk", "U-PRM", "Premier RP — konto demonstracyjne, pełny wgląd PoC", "scisle_tajne"),
            ("demo-kgp", "Jan", "Kowalski", "U-KGP", "Komendant Główny Policji — postać fikcyjna do demo", "tajne"),
            ("demo-kgpsp", "Anna", "Nowak", "U-KGPSP", "Komendant Główny PSP — postać fikcyjna do demo", "zastrzezone"),
        ]
        for person_id, first, last, unit_id, role, clearance in demo_people:
            conn.execute("""INSERT INTO people
                (id_osoby,imie,nazwisko,id_jednostki,stanowisko,klauzula_tajnosci,aktywna)
                VALUES (?,?,?,?,?,?,1)
                ON CONFLICT(id_osoby) DO UPDATE SET
                    imie=excluded.imie,nazwisko=excluded.nazwisko,
                    id_jednostki=excluded.id_jednostki,stanowisko=excluded.stanowisko,
                    klauzula_tajnosci=excluded.klauzula_tajnosci,aktywna=1""",
                (person_id, first, last, unit_id, role, clearance))

        for plan_id in police_plans:
            conn.execute("UPDATE plans SET klauzula_tajnosci='tajne' WHERE id_planu=?", (plan_id,))
        for plan_id in fire_plans:
            conn.execute("UPDATE plans SET klauzula_tajnosci='zastrzezone' WHERE id_planu=?", (plan_id,))
        for plan_id in police_plans:
            conn.execute("UPDATE tasks SET klauzula_tajnosci='tajne' WHERE id_planu=?", (plan_id,))
        for plan_id in fire_plans:
            conn.execute("UPDATE tasks SET klauzula_tajnosci='zastrzezone' WHERE id_planu=?", (plan_id,))

        # Give demo tasks explicit organizational ownership so API filtering and UI labels are meaningful.
        for plan_id, unit_id in assignment_by_plan.items():
            conn.execute("UPDATE tasks SET id_jednostek_json=? WHERE id_planu=? AND id_jednostek_json='[]'",
                         (json.dumps([unit_id]), plan_id))

        # Directional aggregate-only release: PSP shares counts with Police, not task details.
        conn.execute("DELETE FROM unit_cooperation WHERE (unit_id='U-KGPSP' AND partner_unit_id='U-KGP') OR (unit_id='U-KGP' AND partner_unit_id='U-KGPSP')")
        conn.execute("INSERT OR REPLACE INTO unit_cooperation (unit_id,partner_unit_id,sharing_level) VALUES ('U-KGPSP','U-KGP','aggregate')")


@app.on_event("startup")
def startup() -> None:
    init_db()
    apply_demo_access_scenario()


def plan_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["uzgadnial"] = json.loads(d.pop("uzgadnial_json"))
    return d


def unit_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["id_planow"] = json.loads(d.pop("id_planow_json"))
    d["zasoby"] = json.loads(d.pop("zasoby_json"))
    d["pracownicy"] = json.loads(d.pop("pracownicy_json", "[]"))
    return d


def task_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["id_jednostek"] = json.loads(d.pop("id_jednostek_json"))
    d["zasoby"] = json.loads(d.pop("zasoby_json"))
    d["status"] = bool(d["status"])
    return d


@app.get("/health")
def health():
    with db() as conn:
        counts = {
            "plans": conn.execute("SELECT COUNT(*) FROM plans").fetchone()[0],
            "units": conn.execute("SELECT COUNT(*) FROM units").fetchone()[0],
            "tasks": conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],
            "people": conn.execute("SELECT COUNT(*) FROM people").fetchone()[0],
            "cooperation_relations": conn.execute("SELECT COUNT(*) FROM unit_cooperation").fetchone()[0],
        }
    return {"service": "data", "status": "ok", "database": "sqlite", "counts": counts}


@app.get("/plans")
def get_plans():
    with db() as conn:
        rows = conn.execute("SELECT * FROM plans ORDER BY id_planu").fetchall()
    return [plan_dict(r) for r in rows]


@app.get("/plans/{plan_id}")
def get_plan(plan_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM plans WHERE id_planu=?", (plan_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Plan not found")
        result = plan_dict(row)
        result["podplany"] = [r[0] for r in conn.execute(
            "SELECT id_planu FROM plans WHERE id_planu_nadrzednego=? ORDER BY id_planu", (plan_id,)
        ).fetchall()]
    return result


@app.get("/units")
def get_units(region_id: str | None = None, plan_id: str | None = None):
    with db() as conn:
        rows = conn.execute("SELECT * FROM units ORDER BY nazwa").fetchall()
        items = [unit_dict(r) for r in rows]
        people_rows = conn.execute("SELECT * FROM people WHERE aktywna=1 ORDER BY nazwisko, imie").fetchall()
        people_by_unit: dict[str, list[dict[str, Any]]] = {}
        for person in people_rows:
            item = dict(person)
            item["aktywna"] = bool(item["aktywna"])
            people_by_unit.setdefault(item["id_jednostki"], []).append(item)
        for unit in items:
            unit["pracownicy"] = people_by_unit.get(str(unit["id"]), [])
    if region_id:
        items = [u for u in items if u.get("id_regionu") == region_id]
    if plan_id:
        items = [u for u in items if plan_id in u["id_planow"]]
    return items


@app.get("/tasks")
def get_tasks(plan_id: str | None = None, unit_id: str | None = None,
              region_id: str | None = None, limit: int = 500):
    limit = max(1, min(int(limit), 5000))
    with db() as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY id_planu, id_zadania LIMIT ?", (limit,)).fetchall()
        tasks = [task_dict(r) for r in rows]
        units = {str(r["id"]): unit_dict(r) for r in conn.execute("SELECT * FROM units").fetchall()}
    if plan_id:
        tasks = [t for t in tasks if t["id_planu"] == plan_id]
    if unit_id:
        tasks = [t for t in tasks if unit_id in t["id_jednostek"]]
    if region_id:
        tasks = [t for t in tasks if any(units.get(uid, {}).get("id_regionu") == region_id for uid in t["id_jednostek"])]
    return tasks


@app.get("/people")
def get_people(unit_id: str | None = None, active_only: bool = True):
    query = "SELECT * FROM people"
    conditions = []
    args: list[Any] = []
    if unit_id:
        conditions.append("id_jednostki=?")
        args.append(unit_id)
    if active_only:
        conditions.append("aktywna=1")
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY nazwisko, imie"
    with db() as conn:
        rows = conn.execute(query, args).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["aktywna"] = bool(item["aktywna"])
        result.append(item)
    return result


@app.get("/people/{person_id}")
def get_person(person_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM people WHERE id_osoby=?", (person_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Person not found")
    item = dict(row)
    item["aktywna"] = bool(item["aktywna"])
    return item


@app.get("/cooperation")
def get_cooperation(unit_id: str | None = None):
    with db() as conn:
        if unit_id:
            rows = conn.execute("SELECT unit_id,partner_unit_id,sharing_level FROM unit_cooperation WHERE unit_id=? OR partner_unit_id=?", (unit_id, unit_id)).fetchall()
        else:
            rows = conn.execute("SELECT unit_id,partner_unit_id,sharing_level FROM unit_cooperation").fetchall()
    return [dict(row) for row in rows]


@app.get("/state", response_model=OperationalState)
def get_state():
    with db() as conn:
        task_rows = conn.execute("SELECT * FROM tasks ORDER BY id_planu, id_zadania").fetchall()
        unit_rows = conn.execute("SELECT * FROM units ORDER BY id").fetchall()
        unit_data = [unit_dict(r) for r in unit_rows]
    unit_by_id = {u["id"]: u for u in unit_data}
    tasks = []
    for row in task_rows:
        t = task_dict(row)
        region = next((unit_by_id[uid].get("id_regionu") for uid in t["id_jednostek"]
                       if uid in unit_by_id and unit_by_id[uid].get("id_regionu")), "PL-MZ")
        status = "completed" if t["status"] else ("in_progress" if t["poziom_realizacji"] > 0 else "planned")
        tasks.append(Task(id=f'{t["id_planu"]}:{t["id_zadania"]}', name=t["nazwa_zadania"],
                          region_id=region, completion=t["poziom_realizacji"], status=status))
    resources = []
    for u in unit_data:
        for resource_type, quantity in u.get("zasoby", {}).items():
            try:
                quantity = float(quantity)
            except (TypeError, ValueError):
                continue
            resources.append(Resource(id=f'{u["id"]}:{resource_type}', type=resource_type,
                                     region_id=u.get("id_regionu") or "PL-00", quantity=quantity))
    # Infrastructure is not present in the supplied seed schema. Return an empty list rather than inventing operational assets.
    return OperationalState(version=datetime.now(timezone.utc).isoformat(), tasks=tasks,
                            resources=resources, infrastructure=[])
