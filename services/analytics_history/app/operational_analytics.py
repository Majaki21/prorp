"""Operational analytics for the PRO RP prototype.

All results are computed from an isolated operational seed copy plus synthetic
history. The module deliberately labels estimates and never changes operational data.
"""
from __future__ import annotations

import json
import math
import sqlite3
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    denom = math.sqrt(sum(x*x for x in dx) * sum(y*y for y in dy))
    return round(sum(x*y for x, y in zip(dx, dy)) / denom, 4) if denom else None


def _safe_div(a: float, b: float) -> float | None:
    return round(a / b, 4) if b else None


def build_operational_analyses(seed_path: str | Path, db_path: str | Path) -> dict[str, Any]:
    """Build the full analysis pack from operational entities and task history."""
    seed = json.loads(Path(seed_path).read_text(encoding="utf-8"))
    tasks = seed.get("tasks", [])
    plans = seed.get("plans", [])
    units = seed.get("units", [])
    if not tasks:
        raise ValueError("Brak zadań w kopii danych operacyjnych.")

    # Plan ownership is inferred from units.id_planow; direct task-unit links take precedence.
    plan_to_unit: dict[str, dict] = {}
    unit_id_counts: dict[str, int] = defaultdict(int)
    for unit in units:
        unit_id_counts[str(unit.get("id"))] += 1
        for plan_id in unit.get("id_planow", []):
            plan_to_unit.setdefault(plan_id, unit)
    plans_by_id = {p.get("id_planu"): p for p in plans}
    units_by_id = {u.get("id"): u for u in units}
    unit_analytics_key: dict[int, str] = {}
    for unit in units:
        source_id = str(unit.get("id"))
        if unit_id_counts[source_id] == 1:
            unit_analytics_key[id(unit)] = source_id
        else:
            plan_suffix = "-".join(str(x) for x in unit.get("id_planow", [])) or str(unit.get("typ", "unit"))
            unit_analytics_key[id(unit)] = f"{source_id}::{plan_suffix}"
    assigned: dict[str, list[dict]] = defaultdict(list)
    task_unit: dict[str, dict | None] = {}
    for task in tasks:
        tid = f"{task.get('id_planu', '')}:{task.get('id_zadania', '')}".strip(":")
        direct = [units_by_id[uid] for uid in task.get("id_jednostek", []) if uid in units_by_id]
        unit = direct[0] if direct else plan_to_unit.get(task.get("id_planu"))
        task_unit[tid] = unit
        if unit:
            assigned[unit_analytics_key[id(unit)]].append(task)

    with sqlite3.connect(db_path) as con:
        con.row_factory = sqlite3.Row
        history = [dict(r) for r in con.execute("""
            SELECT h.task_id, h.task_type, s.snapshot_date, h.progress
            FROM task_progress_history h JOIN history_snapshots s USING(snapshot_id)
            ORDER BY s.snapshot_date
        """).fetchall()]
    hist_by_task: dict[str, list[dict]] = defaultdict(list)
    hist_by_date: dict[str, list[dict]] = defaultdict(list)
    for r in history:
        hist_by_task[r["task_id"]].append(r)
        hist_by_date[r["snapshot_date"]].append(r)
    if not hist_by_task:
        raise ValueError("Brak historii postępu w bazie analitycznej.")
    latest_date = max(hist_by_date)
    latest_values = {r["task_id"]: float(r["progress"]) for r in hist_by_date[latest_date]}

    # Task duration / pace estimates. For unfinished tasks, total duration is a forecast,
    # not an observed completion time; it uses the median positive daily pace over the last 14 days.
    task_rows = []
    for task in tasks:
        tid = f"{task.get('id_planu', '')}:{task.get('id_zadania', '')}".strip(":")
        series = hist_by_task.get(tid, [])
        current = latest_values.get(tid, float(task.get("poziom_realizacji", 0)))
        created_raw = str(task.get("data_utworzenia") or latest_date)[:10]
        try:
            created = date.fromisoformat(created_raw)
        except ValueError:
            created = date.fromisoformat(latest_date)
        elapsed = max(0, (date.fromisoformat(latest_date) - created).days)
        recent = [r for r in series if (date.fromisoformat(r["snapshot_date"]) - date.fromisoformat(latest_date)).days >= -14]
        daily_deltas = []
        for prev, nxt in zip(recent, recent[1:]):
            delta_days = (date.fromisoformat(nxt["snapshot_date"]) - date.fromisoformat(prev["snapshot_date"])).days
            if delta_days > 0:
                daily_deltas.append((float(nxt["progress"]) - float(prev["progress"])) / delta_days)
        positive = sorted(x for x in daily_deltas if x > 1e-5)
        pace = positive[len(positive)//2] if positive else 0.0
        remaining = max(0.0, 1.0-current)
        remaining_days = round(remaining / pace, 1) if pace > 0 and remaining > 0 else (0.0 if remaining == 0 else None)
        forecast_total = round(elapsed + remaining_days, 1) if remaining_days is not None else None
        unit = task_unit.get(tid)
        task_rows.append({
            "task_id": tid, "task_name": task.get("nazwa_zadania"),
            "plan_id": task.get("id_planu"), "unit_id": unit_analytics_key[id(unit)] if unit else None,
            "unit_name": unit.get("nazwa") if unit else "Nieprzypisana",
            "created_at": created_raw, "elapsed_days": elapsed,
            "current_progress": round(current, 4), "remaining_progress": round(remaining, 4),
            "recent_positive_pace_per_day": round(pace, 5),
            "estimated_remaining_days": remaining_days,
            "estimated_total_duration_days": forecast_total,
            "duration_kind": "forecast" if current < 1 else "elapsed_to_completion",
            "status": task.get("status"),
            "cost": float(task.get("koszt") or 0),
            "personnel_required": float((task.get("zasoby") or {}).get("personel") or 0),
            "progress_history_points": len(series),
        })

    # Analysis-only comparison copies: do not write these into the operational seed or
    # history database, and do not include them in unit workload/budget totals. They let
    # the demo show how identical task templates could be compared across units.
    # Progress/pace adjustments are synthetic scenario assumptions, not measured outcomes.
    eligible_units = [u for u in units if assigned.get(unit_analytics_key[id(u)])]
    comparison_rows = list(task_rows)
    factors = (0.72, 1.0, 1.28)
    synthetic_copy_count = 0
    if len(eligible_units) >= 2:
        unit_keys = [unit_analytics_key[id(u)] for u in eligible_units]
        unit_names = {unit_analytics_key[id(u)]: u.get("nazwa") for u in eligible_units}
        for index, template in enumerate(task_rows[:min(20, len(task_rows))]):
            source_unit = template.get("unit_id")
            targets = [key for key in unit_keys if key != source_unit][:2]
            for copy_index, target_key in enumerate(targets):
                factor = factors[(index + copy_index) % len(factors)]
                clone = dict(template)
                clone.update({
                    "task_id": f'{template["task_id"]}::ANALYSIS_COPY::{target_key}',
                    "unit_id": target_key,
                    "unit_name": unit_names.get(target_key, target_key),
                    "current_progress": round(min(0.99, max(0.0, template["current_progress"] * factor)), 4),
                    "recent_positive_pace_per_day": round(template["recent_positive_pace_per_day"] * factor, 5),
                    "estimated_remaining_days": (round(template["remaining_progress"] / (template["recent_positive_pace_per_day"] * factor), 1)
                        if template["recent_positive_pace_per_day"] > 0 and template["remaining_progress"] > 0 else template["estimated_remaining_days"]),
                    "analysis_only_copy": True,
                    "synthetic_scenario_factor": factor,
                    "source_task_id": template["task_id"],
                })
                comparison_rows.append(clone)
                synthetic_copy_count += 1
    by_name: dict[str, list[dict]] = defaultdict(list)
    for row in comparison_rows:
        by_name[str(row["task_name"] or row["task_id"])].append(row)
    same_task_benchmarks = []
    for name, group in by_name.items():
        unit_group = [r for r in group if r["unit_id"]]
        if len({r["unit_id"] for r in unit_group}) >= 2:
            ranked = sorted(unit_group, key=lambda r: (r["recent_positive_pace_per_day"], r["current_progress"]), reverse=True)
            same_task_benchmarks.append({
                "task_name": name, "units_compared": len({r["unit_id"] for r in unit_group}),
                "fastest_unit": ranked[0]["unit_name"], "slowest_unit": ranked[-1]["unit_name"],
                "results": ranked,
                "comparison_mode": "synthetic_analysis_only" if any(r.get("analysis_only_copy") for r in ranked) else "operational_data",
                "synthetic_copy_count": sum(bool(r.get("analysis_only_copy")) for r in ranked),
            })

    # Unit-level workload, staffing and budget risk.
    unit_rows = []
    budget_risks = []
    for unit in units:
        uid = unit_analytics_key[id(unit)]
        own_tasks = assigned.get(uid, [])
        related = [r for r in task_rows if r["unit_id"] == uid]
        staff = float((unit.get("zasoby") or {}).get("personel") or 0)
        task_staff = sum(r["personnel_required"] for r in related)
        progress_mean = sum(r["current_progress"] for r in related) / len(related) if related else None
        slow_share = sum(r["current_progress"] < 0.5 for r in related) / len(related) if related else None
        open_cost = sum(r["cost"] * r["remaining_progress"] for r in related)
        full_cost = sum(r["cost"] for r in related)
        budget = float(unit.get("budzet") or 0)
        budget_ratio = _safe_div(full_cost, budget)
        # Seed task cost is treated as total/planned task cost, not cash already spent.
        # Therefore budget exposure is the sum of task costs, without multiplying by 1/progress.
        estimated_remaining_cost = sum(r["cost"] * r["remaining_progress"] for r in related)
        projected_cost = full_cost
        budget_row = {
            "unit_id": uid, "source_unit_id": unit.get("id"), "unit_name": unit.get("nazwa"), "budget": budget,
            "sum_task_costs": round(full_cost, 2),
            "estimated_remaining_cost": round(estimated_remaining_cost, 2),
            "projected_total_cost": round(projected_cost, 2),
            "projected_budget_overrun": round(max(0.0, projected_cost-budget), 2) if budget > 0 else None,
            "projected_budget_utilization": _safe_div(projected_cost, budget),
            "risk": ("no_budget_data" if budget <= 0 else "high" if projected_cost > budget*1.1 else "watch" if projected_cost > budget else "within_budget"),
            "assumption": "Pole kosztu zadania traktowane jako planowany całkowity koszt zadania; suma porównana z budżetem jednostki. Dane demonstracyjne, nie księgowe."
        }
        if related and budget_row["risk"] in ("high", "watch", "no_budget_data"):
            budget_risks.append(budget_row)
        unit_rows.append({
            "unit_id": uid, "source_unit_id": unit.get("id"), "unit_name": unit.get("nazwa"), "unit_type": unit.get("typ"),
            "budget": budget, "personnel_available": staff, "task_count": len(related),
            "tasks_per_person": _safe_div(len(related), staff),
            "sum_task_personnel_requirements": task_staff,
            "personnel_demand_to_supply": _safe_div(task_staff, staff),
            "mean_progress": round(progress_mean, 4) if progress_mean is not None else None,
            "share_tasks_below_50pct": round(slow_share, 4) if slow_share is not None else None,
            "open_task_cost_weighted": round(open_cost, 2),
            "average_estimated_remaining_days": round(sum(r["estimated_remaining_days"] for r in related if r["estimated_remaining_days"] is not None) / max(1, sum(r["estimated_remaining_days"] is not None for r in related)), 1) if related else None,
            "average_estimated_total_duration_days": round(sum(r["estimated_total_duration_days"] for r in related if r["estimated_total_duration_days"] is not None) / max(1, sum(r["estimated_total_duration_days"] is not None for r in related)), 1) if related else None,
            "unassigned_task_count": 0,
        })

    # Staffing correlation at unit level; this is descriptive, not causal.
    corr_units = [r for r in unit_rows if r["task_count"] >= 2 and r["personnel_available"] > 0 and r["mean_progress"] is not None]
    staffing_corr = _pearson([r["personnel_available"] for r in corr_units], [r["mean_progress"] for r in corr_units])
    load_corr = _pearson([r["tasks_per_person"] or 0 for r in corr_units], [r["mean_progress"] for r in corr_units])

    # Bottleneck / high-load score: high task count per person, low average progress,
    # and a high share of tasks below 50%. Thresholds are prototype heuristics.
    bottlenecks = []
    for u in unit_rows:
        if u["task_count"] == 0:
            continue
        score = (u["tasks_per_person"] or 0) * 0.45 + (1-(u["mean_progress"] or 0)) * 0.35 + (u["share_tasks_below_50pct"] or 0) * 0.20
        u["overload_score"] = round(score, 4)
        if score >= 0.5 or (u["personnel_demand_to_supply"] is not None and u["personnel_demand_to_supply"] > 1):
            bottlenecks.append(u)
    bottlenecks.sort(key=lambda x: x.get("overload_score", 0), reverse=True)

    # Exceptional efficiency: high progress and pace, low task load per staff member.
    eligible = [u for u in unit_rows if u["task_count"] > 0 and u["mean_progress"] is not None]
    for u in eligible:
        u["efficiency_score"] = round((u["mean_progress"] or 0) * 0.55 +
            min(1.0, (u["average_estimated_remaining_days"] or 365) and 1/(1+(u["average_estimated_remaining_days"] or 365)/30)) * 0.25 +
            (1-min(1.0, u["tasks_per_person"] or 0)) * 0.20, 4)
    efficient = sorted(eligible, key=lambda x: x.get("efficiency_score", 0), reverse=True)

    # Two extra analyses: status/completion funnel and task risk by age/progress.
    complete = [r for r in task_rows if r["current_progress"] >= 0.999]
    stagnant = []
    for r in task_rows:
        series = hist_by_task.get(r["task_id"], [])
        last_8 = series[-8:]
        if len(last_8) >= 2 and last_8[-1]["progress"] - last_8[0]["progress"] <= 0.01 and r["current_progress"] < 1:
            stagnant.append({**r, "recent_change_pp_7d": round((last_8[-1]["progress"]-last_8[0]["progress"])*100, 2)})
    risk_tasks = sorted(
        [r for r in task_rows if r["current_progress"] < 0.5 and r["elapsed_days"] >= 14],
        key=lambda r: (r["elapsed_days"], -r["current_progress"]), reverse=True
    )
    unassigned = [r for r in task_rows if not r["unit_id"]]
    by_plan = defaultdict(list)
    for r in task_rows:
        by_plan[r["plan_id"]].append(r)
    plan_summary = []
    for plan_id, group in by_plan.items():
        plan = plans_by_id.get(plan_id, {})
        plan_summary.append({
            "plan_id": plan_id, "plan_name": plan.get("nazwa_dokumentu", plan_id),
            "tasks": len(group), "mean_progress": round(sum(r["current_progress"] for r in group)/len(group),4),
            "completed": sum(r["current_progress"] >= .999 for r in group),
            "below_50pct": sum(r["current_progress"] < .5 for r in group),
            "total_task_cost": round(sum(r["cost"] for r in group),2),
            "average_elapsed_days": round(sum(r["elapsed_days"] for r in group)/len(group),1),
            "average_estimated_total_duration_days": round(sum(r["estimated_total_duration_days"] for r in group if r["estimated_total_duration_days"] is not None)/max(1,sum(r["estimated_total_duration_days"] is not None for r in group)),1),
        })
    plan_summary.sort(key=lambda x: x["mean_progress"])

    return {
        "meta": {
            "as_of": latest_date, "tasks": len(task_rows), "units": len(units),
            "history_rows": len(history), "history_points_per_task_min": min(len(v) for v in hist_by_task.values()),
            "history_points_per_task_max": max(len(v) for v in hist_by_task.values()),
            "data_mode": "synthetic_demo", "duplicate_source_unit_ids": sorted(k for k, v in unit_id_counts.items() if v > 1), "history_note": "Wcześniejszy przebieg postępu jest syntetyczny. Wartości nie są rzeczywistymi pomiarami.",
            "method_note": "Czas ukończenia dla zadań otwartych jest estymacją z tempa z ostatnich 14 dni, nie zaobserwowanym czasem realizacji.",
            "unit_assignment_note": "Jednostkę przypisano bezpośrednio z id_jednostek, a jeśli brak — na podstawie relacji jednostka.id_planow → zadanie.id_planu.",
            "same_task_comparison_note": "Do porównania dodano kopie analityczne wybranych szablonów zadań przypisane do innych jednostek. Kopie i różnice tempa są syntetycznym scenariuszem demonstracyjnym; nie zmieniają seedów operacyjnych, historii ani sum obciążenia/budżetu.",
            "analysis_only_duplicate_tasks": synthetic_copy_count,
            "analysis_only_duplicate_note": "Kopie istnieją wyłącznie w wynikach benchmarku identycznych zadań; nie są zapisywane do operacyjnej bazy ani używane do obliczeń obciążenia jednostek i ryzyka budżetowego.",
            "budget_note": "Koszt zadania jest traktowany jako planowany koszt całkowity. Przekroczenie budżetu oznacza sumę kosztów zadań przypisanych do jednostki większą niż budżet jednostki; nie jest to prognoza wydatków księgowych."
        },
        "task_durations": sorted(task_rows, key=lambda x: (x["estimated_total_duration_days"] is None, -(x["estimated_total_duration_days"] or 0))),
        "duration_summary": {
            "by_unit": sorted([{"unit_id": u["unit_id"], "unit_name": u["unit_name"], "task_count": u["task_count"],
                "average_elapsed_days": round(sum(r["elapsed_days"] for r in task_rows if r["unit_id"] == u["unit_id"])/max(1,u["task_count"]),1),
                "average_estimated_total_duration_days": u["average_estimated_total_duration_days"]} for u in unit_rows if u["task_count"]], key=lambda x: x["average_estimated_total_duration_days"] or 0, reverse=True),
            "by_plan": sorted(plan_summary, key=lambda x: x["average_estimated_total_duration_days"] or 0, reverse=True),
        },
        "same_task_unit_benchmarks": same_task_benchmarks,
        "units": sorted(unit_rows, key=lambda x: (x["mean_progress"] is None, x["mean_progress"] or 0)),
        "staffing_relationship": {
            "unit_count_used": len(corr_units), "pearson_staff_vs_mean_progress": staffing_corr,
            "pearson_tasks_per_person_vs_mean_progress": load_corr,
            "interpretation": "Korelacja opisowa na poziomie jednostek; nie dowodzi związku przyczynowego. Wynik jest słaby przy małej liczbie jednostek lub sztucznych danych."
        },
        "bottlenecks": bottlenecks,
        "efficient_units": efficient,
        "budget_risks": sorted(budget_risks, key=lambda x: (x["projected_budget_overrun"] or 0), reverse=True),
        "plan_progress": plan_summary,
        "additional_analyses": {
            "stagnating_tasks": sorted(stagnant, key=lambda x: x["recent_change_pp_7d"]),
            "at_risk_tasks": risk_tasks,
            "completion_funnel": {
                "total": len(task_rows), "completed": len(complete),
                "in_progress": sum(0 < r["current_progress"] < .999 for r in task_rows),
                "not_started": sum(r["current_progress"] <= 0 for r in task_rows),
                "below_50pct_after_14_days": len(risk_tasks),
                "stagnating_last_7_intervals": len(stagnant)
            },
            "unassigned_tasks": unassigned
        }
    }
