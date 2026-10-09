import os
import asyncio
from collections import defaultdict

import httpx
import pandas as pd
import streamlit as st
import folium
from streamlit_folium import st_folium

PRESENTATION_API_URL = os.getenv("PRESENTATION_API_URL", "http://localhost:8000")
RADOM_CENTER = [51.4027, 21.1471]


def fetch_json(url: str, params: dict | None = None, person_id: str | None = None):
    """Fetch data through the Presentation API, carrying the selected demo identity to Access Service."""
    headers = {"X-Person-Id": person_id} if person_id else {}

    async def _get():
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()
    return asyncio.run(_get())


def get_demo_identities():
    return fetch_json(f"{PRESENTATION_API_URL}/api/demo-identities")


def get_me(person_id: str):
    return fetch_json(f"{PRESENTATION_API_URL}/api/me", person_id=person_id)


def get_state(person_id: str):
    return fetch_json(f"{PRESENTATION_API_URL}/api/state", person_id=person_id)


def get_collaboration_summary(person_id: str):
    return fetch_json(f"{PRESENTATION_API_URL}/api/collaboration-summary", person_id=person_id)


def get_plans(person_id: str):
    return fetch_json(f"{PRESENTATION_API_URL}/api/plans", person_id=person_id)


def get_units(person_id: str):
    return fetch_json(f"{PRESENTATION_API_URL}/api/units", person_id=person_id)


def get_tasks(person_id: str, params: dict | None = None):
    return fetch_json(f"{PRESENTATION_API_URL}/api/tasks", params=params, person_id=person_id)


def fmt_money(value):
    try:
        return f"{float(value):,.0f} zł".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def main():
    st.set_page_config(page_title="PRO RP", page_icon="🛡️", layout="wide")
    st.title("Zintegrowana platforma PRO RP")
    st.caption("Demonstrator — widok danych jest filtrowany przez warstwę dostępową API.")

    try:
        identities = get_demo_identities()
    except Exception as exc:
        st.error(f"Nie udało się pobrać kont demonstracyjnych z warstwy dostępowej: {exc}")
        st.info("Sprawdź stan serwisów presentation i access oraz endpoint `/api/demo-identities`.")
        return

    if not identities:
        st.error("Warstwa dostępowa nie zwróciła aktywnych kont demonstracyjnych.")
        return

    identity_by_id = {str(person["id_osoby"]): person for person in identities}
    identity_options = list(identity_by_id)
    preferred_identity = "demo-premier" if "demo-premier" in identity_by_id else identity_options[0]
    if "selected_demo_person_id" not in st.session_state:
        st.session_state["selected_demo_person_id"] = preferred_identity
    if st.session_state["selected_demo_person_id"] not in identity_by_id:
        st.session_state["selected_demo_person_id"] = preferred_identity

    with st.sidebar:
        st.header("Perspektywa dostępu")
        selected_person_id = st.selectbox(
            "Konto demonstracyjne",
            options=identity_options,
            format_func=lambda person_id: (
                f"{identity_by_id[person_id]['imie']} {identity_by_id[person_id]['nazwisko']} — "
                f"{identity_by_id[person_id]['nazwa_jednostki']} · "
                f"{identity_by_id[person_id]['klauzula_tajnosci']}"
            ),
            key="selected_demo_person_id",
        )
        st.caption("Wybór konta służy wyłącznie demonstracji. Tożsamość jest przekazywana do API w nagłówku `X-Person-Id`.")

    try:
        me = get_me(selected_person_id)
        state = get_state(selected_person_id)
        plans = get_plans(selected_person_id)
        units = get_units(selected_person_id)
        tasks = get_tasks(selected_person_id)
        collaboration_summary = get_collaboration_summary(selected_person_id)
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else "?"
        st.error(f"Warstwa dostępowa odrzuciła żądanie lub zwróciła błąd (HTTP {status_code}).")
        st.code(str(exc))
        st.info("Dane interfejsu są pobierane wyłącznie przez Access Service. Sprawdź uprawnienia wybranego konta i logi serwisu access.")
        return
    except Exception as exc:
        st.error(f"Nie udało się pobrać danych z warstwy dostępowej: {exc}")
        st.info("Uruchom system przez `docker compose up --build` i sprawdź serwisy presentation/access/data.")
        return

    with st.sidebar:
        st.divider()
        st.markdown("**Aktywna tożsamość**")
        st.write(f"{me.get('imie', '')} {me.get('nazwisko', '')}")
        st.caption(me.get("stanowisko") or "Konto demonstracyjne")
        st.write(f"**Jednostka:** {identity_by_id.get(selected_person_id, {}).get('nazwa_jednostki', me.get('id_jednostki', '—'))}")
        st.write(f"**Klauzula:** `{me.get('klauzula_tajnosci', '—')}`")
        st.metric("Dostępne jednostki", len(units))
        st.metric("Dostępne plany", len(plans))
        st.metric("Dostępne zadania", len(tasks))

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

    if collaboration_summary:
        st.subheader("Bramka informacyjna — współpraca między jednostkami")
        st.caption("Udostępnione są wyłącznie agregaty. Nazwy, identyfikatory i szczegóły zadań jednostki współpracującej pozostają ukryte.")
        for summary in collaboration_summary:
            st.markdown(f"**{summary['jednostka']}** · zakres: `aggregate_only`")
            a, b, c = st.columns(3)
            a.metric("Zadania zrealizowane", summary["liczba_zrealizowanych"])
            b.metric("Zadań łącznie", summary["liczba_zadan"])
            c.metric("Średni poziom realizacji", f"{summary['poziom_realizacji_proc']:.1f}%")

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
        st.json({"identity": selected_person_id, "plans": len(plans), "units": len(units), "tasks": len(tasks),
                 "operational_tasks": len(state.get("tasks", [])), "resources": len(state.get("resources", [])),
                 "presentation_api": PRESENTATION_API_URL})


if __name__ == "__main__":
    main()
