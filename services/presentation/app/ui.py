import os
import asyncio
from collections import defaultdict

import httpx
import pandas as pd
import streamlit as st
import folium
from streamlit_folium import st_folium

ACCESS_SERVICE_URL = os.getenv("ACCESS_SERVICE_URL", "http://access:8000")
DATA_SERVICE_URL = os.getenv("DATA_SERVICE_URL", "http://data:8000")
RADOM_CENTER = [51.4027, 21.1471]


def fetch_json(url: str, params: dict | None = None):
    async def _get():
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    return asyncio.run(_get())


def get_state():
    return fetch_json(f"{ACCESS_SERVICE_URL}/state")


def get_plans():
    return fetch_json(f"{DATA_SERVICE_URL}/plans")


def get_units():
    return fetch_json(f"{DATA_SERVICE_URL}/units")


def get_tasks(params: dict | None = None):
    return fetch_json(f"{DATA_SERVICE_URL}/tasks", params=params)


def fmt_money(value):
    try:
        return f"{float(value):,.0f} zł".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def main():
    st.set_page_config(page_title="PRO RP", page_icon="🛡️", layout="wide")
    st.title("Zintegrowana platforma PRO RP")
    st.caption("Demonstrator — plany, jednostki i zadania operacyjne. Dostęp bez uwierzytelniania wyłącznie na potrzeby weryfikacji idei.")

    try:
        state = get_state()
        plans = get_plans()
        units = get_units()
        tasks = get_tasks()
    except Exception as exc:
        st.error(f"Nie udało się pobrać danych z API: {exc}")
        st.info("Uruchom system przez `docker compose up --build` i sprawdź serwisy data/access.")
        return

    plans_by_id = {p["id_planu"]: p for p in plans}
    units_by_id = {str(u["id"]): u for u in units}
    tasks_by_plan = defaultdict(list)
    for task in tasks:
        tasks_by_plan[task["id_planu"]].append(task)

    total_tasks = len(tasks)
    completed_tasks = sum(1 for t in tasks if t.get("status"))
    avg_completion = sum(float(t.get("poziom_realizacji", 0)) for t in tasks) / total_tasks if total_tasks else 0
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Plany", len(plans))
    c2.metric("Jednostki", len(units))
    c3.metric("Zadania", total_tasks)
    c4.metric("Śr. realizacja", f"{avg_completion * 100:.0f}%")

    tab_unit, tab_plans, tab_all, tab_map = st.tabs([
        "Widok jednostki", "Hierarchia planów", "Wszystkie zadania", "Mapa"
    ])

    with tab_unit:
        st.subheader("Perspektywa wybranej jednostki")
        st.caption("Jednostka jest powiązana z planami; zadania pobierane są z tych planów. Zadanie nie jest przypisywane do jednostki na potrzeby tego widoku.")
        unit_labels = {
            f"{u['nazwa']} [{u['id']}]": str(u["id"])
            for u in sorted(units, key=lambda x: x["nazwa"])
        }
        default_idx = next((i for i, value in enumerate(unit_labels.values()) if value == "U-MSWIA"), 0)
        selected_label = st.selectbox("Jednostka", list(unit_labels.keys()), index=default_idx)
        unit_id = unit_labels[selected_label]
        unit = units_by_id[unit_id]

        parent_id = unit.get("id_jednostki_nadrzednej")
        parent = units_by_id.get(str(parent_id)) if parent_id else None
        info1, info2, info3, info4 = st.columns(4)
        info1.metric("Typ jednostki", unit.get("typ") or "—")
        info2.metric("Region", unit.get("id_regionu") or "Poziom krajowy")
        info3.metric("Budżet demonstracyjny", fmt_money(unit.get("budzet", 0)))
        info4.metric("Jednostka nadrzędna", parent["nazwa"] if parent else "Brak / poziom najwyższy")

        st.markdown("#### Plany przypisane do jednostki")
        assigned_plan_ids = unit.get("id_planow", [])
        assigned_plans = [plans_by_id[pid] for pid in assigned_plan_ids if pid in plans_by_id]
        if assigned_plans:
            plan_rows = [{
                "ID planu": p["id_planu"],
                "Nazwa": p["nazwa_dokumentu"],
                "Plan nadrzędny": p.get("id_planu_nadrzednego") or "—",
                "Status": p.get("status_planu", "—"),
                "Utworzono": p.get("data_utworzenia", "—"),
                "Zatwierdzono": p.get("data_zatwierdzeina") or "—",
            } for p in assigned_plans]
            st.dataframe(pd.DataFrame(plan_rows), use_container_width=True, hide_index=True)
        else:
            st.info("Jednostka nie ma przypisanych planów.")

        include_descendants = st.checkbox("Uwzględnij również podplany przypisanych planów", value=True)
        visible_plan_ids = set(assigned_plan_ids)
        if include_descendants:
            changed = True
            while changed:
                changed = False
                for p in plans:
                    if p.get("id_planu_nadrzednego") in visible_plan_ids and p["id_planu"] not in visible_plan_ids:
                        visible_plan_ids.add(p["id_planu"])
                        changed = True
        unit_tasks = [t for t in tasks if t["id_planu"] in visible_plan_ids]
        st.markdown("#### Zadania w planach jednostki")
        if unit_tasks:
            rows = [{
                "Plan": t["id_planu"],
                "ID zadania": t["id_zadania"],
                "Zadanie": t["nazwa_zadania"],
                "Status": "Zakończone" if t.get("status") else ("W toku" if float(t.get("poziom_realizacji", 0)) > 0 else "Zaplanowane"),
                "Realizacja": f"{float(t.get('poziom_realizacji', 0))*100:.0f}%",
                "Koszt": fmt_money(t.get("koszt", 0)),
                "Aktualizacja": t.get("data_aktualizacji", "—"),
            } for t in unit_tasks]
            df = pd.DataFrame(rows)
            plan_filter = st.selectbox("Filtr planu", ["Wszystkie"] + sorted(df["Plan"].unique().tolist()), key="unit_plan_filter")
            if plan_filter != "Wszystkie":
                df = df[df["Plan"] == plan_filter]
            st.dataframe(df, use_container_width=True, hide_index=True)
            avg = sum(float(t.get("poziom_realizacji", 0)) for t in unit_tasks) / len(unit_tasks)
            done = sum(1 for t in unit_tasks if t.get("status"))
            a, b, c = st.columns(3)
            a.metric("Zadania w widoku", len(unit_tasks))
            b.metric("Oznaczone jako zakończone", done)
            c.metric("Średnia realizacja", f"{avg*100:.0f}%")
        else:
            st.info("Brak zadań w planach przypisanych do tej jednostki.")

        with st.expander("Zasoby jednostki"):
            st.json(unit.get("zasoby", {}))

    with tab_plans:
        st.subheader("Hierarchia planów")
        st.caption("Plan nadrzędny → plan podrzędny. Każdy plan zawiera własną listę zadań.")
        children = defaultdict(list)
        for p in plans:
            children[p.get("id_planu_nadrzednego")].append(p)

        def render_plan_tree(parent_id=None, depth=0):
            for p in sorted(children.get(parent_id, []), key=lambda x: x["id_planu"]):
                pid = p["id_planu"]
                count = len(tasks_by_plan.get(pid, []))
                label = f"{'　' * depth}{pid} — {p['nazwa_dokumentu']} ({count} zadań)"
                with st.expander(label, expanded=(depth == 0)):
                    st.write(f"**Status:** {p.get('status_planu', '—')}  |  **Sporządził:** {p.get('sporzadzil', '—')}")
                    st.write(f"**Plan nadrzędny:** {p.get('id_planu_nadrzednego') or 'brak'}")
                    if tasks_by_plan.get(pid):
                        p_rows = [{
                            "ID zadania": t["id_zadania"], "Zadanie": t["nazwa_zadania"],
                            "Status": "Zakończone" if t.get("status") else "W toku / zaplanowane",
                            "Realizacja": f"{float(t.get('poziom_realizacji', 0))*100:.0f}%",
                            "Koszt": fmt_money(t.get("koszt", 0)),
                        } for t in tasks_by_plan[pid]]
                        st.dataframe(pd.DataFrame(p_rows), use_container_width=True, hide_index=True)
                    else:
                        st.caption("Plan nie ma jeszcze zadań w danych demonstracyjnych.")
                    render_plan_tree(pid, depth + 1)
        render_plan_tree()

    with tab_all:
        st.subheader("Wszystkie zadania")
        f1, f2, f3 = st.columns(3)
        plan_options = ["Wszystkie"] + sorted({t["id_planu"] for t in tasks})
        selected_plan = f1.selectbox("Plan", plan_options)
        region_options = ["Wszystkie"] + sorted({str(u.get("id_regionu")) for u in units if u.get("id_regionu")})
        selected_region = f2.selectbox("Region", region_options)
        status_options = ["Wszystkie", "Zakończone", "W toku", "Zaplanowane"]
        selected_status = f3.selectbox("Status", status_options)
        visible = []
        for t in tasks:
            if selected_plan != "Wszystkie" and t["id_planu"] != selected_plan:
                continue
            # Region filtering follows the intended model: units are linked to plans,
            # and tasks are obtained from those plans (no task-to-unit assignment).
            if selected_region != "Wszystkie":
                plan_units = [u for u in units if t["id_planu"] in u.get("id_planow", [])]
                regional_plan_ids = {
                    p["id_planu"] for p in plans
                    if p["id_planu"].endswith(selected_region)
                }
                is_regional_plan = t["id_planu"] in regional_plan_ids
                has_region_unit = any(u.get("id_regionu") == selected_region for u in plan_units)
                # National plans have no single region; retain them as cross-region tasks.
                is_national_plan = not any(u.get("id_regionu") for u in plan_units)
                if not (is_regional_plan or has_region_unit or is_national_plan):
                    continue
            status_label = "Zakończone" if t.get("status") else ("W toku" if float(t.get("poziom_realizacji", 0)) > 0 else "Zaplanowane")
            if selected_status != "Wszystkie" and status_label != selected_status:
                continue
            visible.append({"Plan": t["id_planu"], "ID zadania": t["id_zadania"], "Zadanie": t["nazwa_zadania"],
                            "Status": status_label, "Realizacja": f"{float(t.get('poziom_realizacji', 0))*100:.0f}%",
                            "Koszt": fmt_money(t.get("koszt", 0))})
        st.dataframe(pd.DataFrame(visible), use_container_width=True, hide_index=True)

    with tab_map:
        st.subheader("Mapa sytuacyjna")
        map_col, info_col = st.columns([2, 1])
        with map_col:
            m = folium.Map(location=RADOM_CENTER, zoom_start=6, tiles="OpenStreetMap")
            folium.Marker(RADOM_CENTER, tooltip="Radom — obszar demonstracyjny",
                          popup="Dane geograficzne obiektów nie są jeszcze częścią modelu.").add_to(m)
            st_folium(m, use_container_width=True, height=520)
        with info_col:
            st.info("Mapa jest na razie podkładem demonstracyjnym. Zadania i jednostki nie mają współrzędnych geograficznych w źródłowych danych.")
            st.markdown("**Możliwe rozszerzenia:** regiony, lokalizacje infrastruktury, schrony, zasoby i warstwy scenariuszy.")

    with st.expander("Diagnostyka API"):
        st.json({"plans": len(plans), "units": len(units), "tasks": len(tasks),
                 "operational_tasks": len(state.get("tasks", [])), "resources": len(state.get("resources", [])),
                 "data_service": DATA_SERVICE_URL})


if __name__ == "__main__":
    main()
