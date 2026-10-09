"""Import a workbook with sheets D and D+2 into a separate analytics-history SQLite DB.

This script creates/updates ONLY analytics_history.db. It never connects to the operational DB.
"""
from __future__ import annotations
import argparse
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
DEFAULT_DB = Path(os.getenv("ANALYTICS_HISTORY_DB", HERE / "data" / "analytics_history.db"))
SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS source_imports (
 import_id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT NOT NULL,
 imported_at TEXT NOT NULL, notes TEXT
);
CREATE TABLE IF NOT EXISTS history_snapshots (
 snapshot_id TEXT PRIMARY KEY, snapshot_date TEXT NOT NULL, label TEXT NOT NULL,
 source_import_id INTEGER, created_at TEXT NOT NULL,
 FOREIGN KEY(source_import_id) REFERENCES source_imports(import_id)
);
CREATE TABLE IF NOT EXISTS task_progress_history (
 history_id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
 task_type TEXT NOT NULL, snapshot_id TEXT NOT NULL,
 progress REAL NOT NULL CHECK(progress >= 0 AND progress <= 1),
 source_sheet TEXT NOT NULL,
 FOREIGN KEY(snapshot_id) REFERENCES history_snapshots(snapshot_id),
 UNIQUE(task_id, snapshot_id)
);
CREATE INDEX IF NOT EXISTS idx_task_history_task ON task_progress_history(task_id, snapshot_id);
CREATE INDEX IF NOT EXISTS idx_task_history_snapshot ON task_progress_history(snapshot_id);
CREATE TABLE IF NOT EXISTS simulation_runs (
 simulation_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
 base_snapshot_id TEXT NOT NULL, days_ahead INTEGER NOT NULL,
 method TEXT NOT NULL, parameters_json TEXT NOT NULL, results_json TEXT NOT NULL,
 FOREIGN KEY(base_snapshot_id) REFERENCES history_snapshots(snapshot_id)
);
"""

def import_workbook(workbook: str | Path, db_path: str | Path = DEFAULT_DB,
                    date_d: str = "2026-10-07", date_d2: str = "2026-10-09") -> dict:
    workbook, db_path = Path(workbook), Path(db_path)
    if not workbook.exists():
        raise FileNotFoundError(workbook)
    d = pd.read_excel(workbook, sheet_name="D")
    d2 = pd.read_excel(workbook, sheet_name="D+2")
    required_d = {"ID zadania", "Typ", "Stan realizacji"}
    required_d2 = {"ID", "Stan poprzedni", "Zmiana", "Stan po 2 dniach"}
    if not required_d.issubset(d.columns) or not required_d2.issubset(d2.columns):
        raise ValueError("Nieoczekiwany format. Wymagane arkusze D i D+2 z opisanymi kolumnami.")
    if d["ID zadania"].duplicated().any() or d2["ID"].duplicated().any():
        raise ValueError("ID zadań muszą być unikalne w każdym arkuszu.")
    base = d.set_index("ID zadania")["Stan realizacji"].astype(float)
    prev = d2.set_index("ID")["Stan poprzedni"].astype(float)
    after = d2.set_index("ID")["Stan po 2 dniach"].astype(float)
    delta = d2.set_index("ID")["Zmiana"].astype(float)
    if set(base.index) != set(prev.index):
        raise ValueError("Zestawy ID zadań w arkuszach D i D+2 nie są identyczne.")
    if ((base - prev).abs() > 1e-6).any():
        raise ValueError("Stan poprzedni w arkuszu D+2 nie zgadza się z arkuszem D.")
    if ((prev + delta - after).abs() > 1e-6).any():
        raise ValueError("Stan poprzedni + Zmiana nie zgadza się ze Stan po 2 dniach.")
    for series in [base, after]:
        if ((series < 0) | (series > 1)).any():
            raise ValueError("Postęp musi mieścić się w przedziale 0–1.")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as con:
        con.executescript(SCHEMA)
        con.execute("PRAGMA foreign_keys = ON")
        # Import replaces only snapshots D and D+2 in the history DB.
        con.execute("DELETE FROM simulation_runs WHERE base_snapshot_id IN ('D','D+2')")
        con.execute("DELETE FROM task_progress_history WHERE snapshot_id IN ('D','D+2')")
        con.execute("DELETE FROM history_snapshots WHERE snapshot_id IN ('D','D+2')")
        cur = con.execute("INSERT INTO source_imports(filename, imported_at, notes) VALUES(?,?,?)",
            (workbook.name, now, "Daty snapshotów podane jawnie; arkusz D+2 zawiera zmianę przez 2 dni."))
        import_id = cur.lastrowid
        con.executemany("INSERT INTO history_snapshots VALUES(?,?,?,?,?)", [
            ("D", date_d, "Stan D", import_id, now),
            ("D+2", date_d2, "Stan D+2", import_id, now),
        ])
        for _, row in d.iterrows():
            con.execute("INSERT INTO task_progress_history(task_id,task_type,snapshot_id,progress,source_sheet) VALUES(?,?,?,?,?)",
                (str(row["ID zadania"]), str(row["Typ"]), "D", float(row["Stan realizacji"]), "D"))
        type_map = d.set_index("ID zadania")["Typ"].to_dict()
        for _, row in d2.iterrows():
            tid = str(row["ID"])
            con.execute("INSERT INTO task_progress_history(task_id,task_type,snapshot_id,progress,source_sheet) VALUES(?,?,?,?,?)",
                (tid, str(type_map[tid]), "D+2", float(row["Stan po 2 dniach"]), "D+2"))
    return {"database": str(db_path), "tasks": int(len(d)), "snapshots": 2,
            "history_rows": int(len(d) + len(d2)), "source_file": workbook.name}

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("workbook", help="Ścieżka do pliku Excel z arkuszami D i D+2")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="Ścieżka do osobnej bazy historii")
    parser.add_argument("--date-d", default="2026-10-07")
    parser.add_argument("--date-d2", default="2026-10-09")
    args = parser.parse_args()
    print(import_workbook(args.workbook, args.db, args.date_d, args.date_d2))
