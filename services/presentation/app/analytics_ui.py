"""Access-scoped operational analytics helpers for the Streamlit UI.

The helpers never fetch data; callers must pass only records already authorized by Access.
"""
from __future__ import annotations
from datetime import date, datetime
from typing import Any

PARENT_KEYS = ("id_zadania_nadrzednego", "id_zadania_rodzica", "parent_task_id", "parent_id", "id_parent")
DEADLINE_KEYS = ("termin_realizacji", "data_terminu", "termin_zakonczenia", "data_zakonczenia_planowana", "deadline", "due_date")


def _task_id(task: dict) -> str:
    return f"{task.get('id_planu', '')}:{task.get('id_zadania', task.get('id', ''))}".strip(":")


def _parent_id(task: dict) -> str | None:
    for key in PARENT_KEYS:
        value = task.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def _flatten_nested_tasks(tasks: list[dict]) -> list[dict]:
    """Flatten nested podzadania objects while inheriting plan/unit context."""
    flat: list[dict] = []
    seen: set[str] = set()

    def visit(task: dict, inherited: dict | None = None, parent_id: str | None = None):
        row = dict(inherited or {})
        row.update({k: v for k, v in task.items() if k != "podzadania"})
        tid = str(row.get("id_zadania", row.get("id", "")))
        if parent_id and not _parent_id(row):
            row["id_zadania_nadrzednego"] = parent_id
        key = _task_id(row) or tid
        if key and key not in seen:
            seen.add(key)
            flat.append(row)
        children = task.get("podzadania")
        if isinstance(children, list):
            for child in children:
                if isinstance(child, dict):
                    visit(child, {k: row.get(k) for k in ("id_planu", "id_jednostek") if row.get(k) is not None}, tid or None)

    for task in tasks:
        visit(task)
    return flat


def leaf_tasks(tasks: list[dict]) -> list[dict]:
    """Return only terminal tasks. Parent tasks with any visible child are excluded."""
    rows = _flatten_nested_tasks(list(tasks))
    ids = {str(t.get("id_zadania", t.get("id", ""))) for t in rows}
    ids |= {_task_id(t) for t in rows}
    parents = set()
    for task in rows:
        parent = _parent_id(task)
        if parent and parent in ids:
            parents.add(parent)
    return [t for t in rows if str(t.get("id_zadania", t.get("id", ""))) not in parents and _task_id(t) not in parents]


def top_level_tasks(tasks: list[dict]) -> list[dict]:
    """Return the highest visible task level for duration reporting (parents with children)."""
    rows = list(tasks)
    ids = {str(t.get("id_zadania", t.get("id", ""))) for t in rows}
    ids |= {_task_id(t) for t in rows}
    result = []
    for task in rows:
        parent = _parent_id(task)
        if parent and parent in ids:
            continue
        result.append(task)
    return result


def _progress(task: dict) -> float:
    try:
        val = float(task.get("poziom_realizacji", task.get("current_progress", 0)) or 0)
    except (TypeError, ValueError):
        val = 0.0
    # Data seed uses a 0..1 fraction; tolerate explicit percentages.
    if val > 1:
        val /= 100
    return max(0.0, min(1.0, val))


def task_status_band(task: dict) -> str:
    p = _progress(task)
    if p >= 0.999:
        return "Zakończone"
    if p <= 0:
        return "Nierozpoczęte"
    if p < 0.25:
        return "Rozpoczęte: 0–25%"
    if p < 0.50:
        return "Realizacja: 25–50%"
    if p < 0.75:
        return "Realizacja: 50–75%"
    return "Realizacja: 75–99,9%"


def days_until(value: Any, as_of: date | None = None) -> int | None:
    """Return whole days until a date-like value, or None when unavailable."""
    parsed = _parse_date(value)
    if parsed is None:
        return None
    return (parsed - (as_of or date.today())).days


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (ValueError, TypeError):
        return None


def _deadline(task: dict) -> date | None:
    for key in DEADLINE_KEYS:
        parsed = _parse_date(task.get(key))
        if parsed:
            return parsed
    return None


def estimate_task_duration(task: dict, as_of: date | None = None) -> dict:
    """Estimate elapsed and remaining time from available progress/date fields only."""
    as_of = as_of or date.today()
    created = _parse_date(task.get("data_utworzenia") or task.get("created_at"))
    elapsed = max(0, (as_of - created).days) if created else None
    progress = _progress(task)
    if progress >= 0.999:
        remaining = 0.0
        total = float(elapsed) if elapsed is not None else None
    elif elapsed is not None and elapsed > 0 and progress > 0:
        pace = progress / elapsed
        remaining = round((1-progress) / pace, 1) if pace > 0 else None
        total = round(elapsed + remaining, 1) if remaining is not None else None
    else:
        remaining, total = None, None
    deadline = _deadline(task)
    forecast_end = as_of.fromordinal(as_of.toordinal() + int(remaining)) if remaining is not None else None
    if progress >= 0.999:
        delay = "Brak"
    elif deadline is None:
        delay = "Brak terminu"
    elif as_of > deadline:
        delay = "Opóźnione"
    elif forecast_end and forecast_end > deadline:
        delay = "Potencjalne"
    else:
        delay = "Brak"
    return {"elapsed_days": elapsed, "remaining_days": remaining, "total_days": total, "deadline": deadline.isoformat() if deadline else None, "delay": delay}


def build_unit_task_rows(tasks: list[dict], plans_by_id: dict, unit_names: dict, owner_by_plan: dict | None = None) -> list[dict]:
    owner_by_plan = owner_by_plan or {}
    rows = []
    for task in tasks:
        pid = str(task.get("id_planu", ""))
        assigned = [str(x) for x in (task.get("id_jednostek") or []) if str(x) in unit_names]
        owners = [unit_names[x] for x in assigned]
        if not owners and owner_by_plan.get(pid) in unit_names:
            owners = [unit_names[owner_by_plan[pid]]]
        duration = estimate_task_duration(task)
        rows.append({
            "Zadanie / plan": task.get("nazwa_zadania") or task.get("nazwa") or task.get("id_zadania", "Zadanie"),
            "Plan": plans_by_id.get(pid, {}).get("nazwa_dokumentu", pid or "—"),
            "Termin realizacji": duration["deadline"] or "Brak terminu w danych",
            "Jednostki uczestniczące": len(set(assigned)) or (1 if owners else 0),
            "Jednostki": ", ".join(dict.fromkeys(owners)) or "Nieprzypisana",
            "Trwa (dni)": duration["elapsed_days"],
            "Prognoza: pozostało (dni)": duration["remaining_days"],
            "Prognozowany czas całości (dni)": duration["total_days"],
            "Opóźnienie": duration["delay"],
        })
    order = {"Opóźnione": 0, "Potencjalne": 1, "Brak terminu": 2, "Brak": 3}
    return sorted(rows, key=lambda x: (order.get(x["Opóźnienie"], 4), -(x["Trwa (dni)"] or 0)))


def unit_metrics(units: list[dict], tasks: list[dict], owner_by_plan: dict | None = None) -> list[dict]:
    owner_by_plan = owner_by_plan or {}
    assigned_by_unit: dict[str, list[dict]] = {str(u.get("id")): [] for u in units}
    for task in tasks:
        assigned = {str(x) for x in (task.get("id_jednostek") or [])}
        if not assigned:
            owner = owner_by_plan.get(str(task.get("id_planu", "")))
            if owner:
                assigned.add(str(owner))
        for uid in assigned:
            if uid in assigned_by_unit:
                assigned_by_unit[uid].append(task)
    raw = []
    for unit in units:
        uid = str(unit.get("id"))
        own = assigned_by_unit.get(uid, [])
        staff = float((unit.get("zasoby") or {}).get("personel") or 0)
        progresses = [_progress(t) for t in own]
        mean_pct = sum(progresses) / len(progresses) * 100 if progresses else None
        tasks_per_person = len(own) / staff if staff > 0 else None
        dated_rates = []
        for task in own:
            d = estimate_task_duration(task)
            if d["elapsed_days"] and d["elapsed_days"] > 0:
                dated_rates.append(_progress(task) / d["elapsed_days"] * 100)
        pace = sum(dated_rates) / len(dated_rates) if dated_rates else 0
        raw.append({"id": uid, "name": unit.get("nazwa", uid), "count": len(own), "staff": staff, "mean": mean_pct, "per_person": tasks_per_person, "pace": pace, "overdue": sum(estimate_task_duration(t)["delay"] == "Opóźnione" for t in own), "potential": sum(estimate_task_duration(t)["delay"] == "Potencjalne" for t in own)})
    max_pace = max((x["pace"] for x in raw), default=0) or 1
    max_load = max((x["per_person"] or 0 for x in raw), default=0) or 1
    out = []
    for x in raw:
        # Efficiency rewards faster progress and higher task throughput per person.
        # The separate overload score penalizes high load when paired with poor progress / schedule risk.
        pace_score = min(1, x["pace"] / max_pace)
        throughput_score = min(1, (x["per_person"] or 0) / max_load) if x["per_person"] is not None else 0
        progress_score = (x["mean"] or 0) / 100
        efficiency = round(100 * (0.45 * pace_score + 0.30 * progress_score + 0.25 * throughput_score), 1) if x["count"] else None
        # High workload per person only signals overload when paired with low progress and schedule risk.
        load_component = min(1, (x["per_person"] or 0) / max_load) if x["per_person"] is not None else 0.5
        progress_component = 1 - (x["mean"] or 0) / 100 if x["mean"] is not None else 0.5
        risk = round(100 * (0.50 * load_component + 0.30 * progress_component + 0.20 * min(1, (x["overdue"] + x["potential"]) / max(1, x["count"]))), 1)
        if x["count"] == 0: level = "Brak danych"
        elif risk >= 70: level = "Wysokie"
        elif risk >= 40: level = "Podwyższone"
        else: level = "Niskie"
        out.append({"Jednostka": x["name"], "Liczba zadań": x["count"], "Personel": int(x["staff"]), "Zadania / osoba": round(x["per_person"], 3) if x["per_person"] is not None else None, "Średni postęp (%)": round(x["mean"], 1) if x["mean"] is not None else None, "Tempo (p.p./dzień)": round(x["pace"], 3) if x["count"] else None, "Wydajność (0–100)": efficiency, "Ryzyko przeciążenia": level, "Zadania opóźnione": x["overdue"], "Zadania z ryzykiem terminu": x["potential"], "_unit_id": x["id"], "_risk_score": risk, "_per_person": x["per_person"]})
    return sorted(out, key=lambda x: (-(x["_risk_score"] or 0), x["Jednostka"]))


def recommend_support(rows: list[dict]) -> list[dict]:
    eligible = [r for r in rows if r.get("Liczba zadań", 0) > 0 and r.get("Zadania / osoba") is not None and r.get("Wydajność (0–100)") is not None]
    if len(eligible) < 2:
        return []
    high_eff = sorted(eligible, key=lambda r: (r["Wydajność (0–100)"], -(r["Zadania / osoba"] or 0)), reverse=True)
    high_load = sorted(eligible, key=lambda r: ((r["Zadania / osoba"] or 0), -(r["_risk_score"] or 0)), reverse=True)
    donors = [r for r in high_eff if r["Wydajność (0–100)"] >= 65 and (r["_risk_score"] or 0) < 45]
    recipients = [r for r in high_load if (r["_risk_score"] or 0) >= 55 and r["Wydajność (0–100)"] < 65]
    result = []
    for recipient in recipients:
        donor = next((d for d in donors if d["_unit_id"] != recipient["_unit_id"]), None)
        if donor:
            result.append({"Jednostka wymagająca wsparcia": recipient["Jednostka"], "Jednostka potencjalnie wspierająca": donor["Jednostka"], "Powód": f"Wyższe obciążenie ({recipient['Zadania / osoba']} zadań/os.) i ryzyko {recipient['_risk_score']}/100; jednostka wspierająca ma wydajność {donor['Wydajność (0–100)']}/100.", "Rekomendacja": "Zweryfikować możliwość czasowego wsparcia; nie przenosić automatycznie zadań ani personelu."})
    return result
