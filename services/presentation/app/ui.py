import os
import asyncio
from collections import defaultdict

import httpx
import pandas as pd
import streamlit as st
import folium
from streamlit_folium import st_folium

from app.view_helpers import (
    unit_descendants, direct_child_units, task_belongs_to_unit,
    task_belongs_to_units, task_status, display_plan_name,
    completion_percent, format_money,
)

PRESENTATION_API_URL = os.getenv("PRESENTATION_API_URL", "http://localhost:8000")
RADOM_CENTER = [51.4027, 21.1471]
NATIONAL_SCOPE = "__national__"
ACTIVE_PLAN_STATUSES = {"active"}
RESOURCE_LABELS = {
    "personel": "Personel",
    "pojazdy": "Pojazdy",
    "stanowiska_dyzurne": "Stanowiska dyżurne",
    "schrony": "Schrony",
    "obiekty": "Obiekty",
    "sprzet": "Sprzęt",
    "sprzęt": "Sprzęt",
}


def fetch_json(url: str, params: dict | None = None, person_id: str | None = None):
    """Fetch data through Presentation API, carrying the selected demo identity."""
    headers = {"X-Person-Id": person_id} if person_id else {}

    async def _get():
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.json()
    return asyncio.run(_get())


def mutate_json(method: str, url: str, person_id: str, payload: dict | None = None):
    headers = {"X-Person-Id": person_id} if person_id else {}
    async def _request():
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.request(method, url, headers=headers, json=payload or {})
            response.raise_for_status()
            return response.json()
    return asyncio.run(_request())


def activate_plan(person_id: str, plan_id: str):
    return mutate_json("POST", f"{PRESENTATION_API_URL}/api/plans/{plan_id}/activate", person_id)


def update_task_progress(person_id: str, plan_id: str, task_id: str, progress: float):
    return mutate_json("PATCH", f"{PRESENTATION_API_URL}/api/tasks/{plan_id}/{task_id}/progress", person_id,
                       {"poziom_realizacji": progress})


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


def get_task_detail(person_id: str, plan_id: str, task_id: str):
    return fetch_json(f"{PRESENTATION_API_URL}/api/tasks/{plan_id}/{task_id}", person_id=person_id)


def pct(tasks):
    return completion_percent(tasks)


def descendant_plan_ids(plan_id: str, plans: list[dict]) -> set[str]:
    """Return the plan subtree for aggregate calculations; callers must still filter displayed detail."""
    children = defaultdict(list)
    for plan in plans:
        children[str(plan.get("id_planu_nadrzednego") or "")].append(str(plan.get("id_planu")))
    result, stack = set(), [str(plan_id)]
    while stack:
        current = stack.pop()
        if current in result:
            continue
        result.add(current)
        stack.extend(children.get(current, []))
    return result


fmt_money = format_money


def humanize_key(value: str) -> str:
    return RESOURCE_LABELS.get(str(value).lower(), str(value).replace("_", " ").capitalize())


def render_resource_value(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            st.markdown(f"**{humanize_key(key)}**")
            render_resource_value(nested)
    elif isinstance(value, list):
        for item in value:
            st.write(f"• {item}")
    else:
        st.write(value if value not in (None, "") else "Brak danych")


def render_resource_panel(resources: dict):
    if not resources:
        st.caption("Brak szczegółowych danych o zasobach w źródle.")
        return
    numeric = [(key, value) for key, value in resources.items() if isinstance(value, (int, float))]
    other = [(key, value) for key, value in resources.items() if not isinstance(value, (int, float))]
    if numeric:
        cols = st.columns(min(4, len(numeric)))
        for idx, (key, value) in enumerate(numeric):
            cols[idx % len(cols)].metric(humanize_key(key), f"{value:,.0f}".replace(",", " "))
    for key, value in other:
        st.markdown(f"**{humanize_key(key)}**")
        render_resource_value(value)


def render_task_summary_row(task: dict, plan: dict | None = None):
    """Compact task row with explicit plan context; details live in Unit view."""
    status = task_status(task)
    progress = max(0.0, min(1.0, float(task.get("poziom_realizacji", 0) or 0)))
    col1, col2, col3 = st.columns([5, 2, 3])
    col1.write(task.get("nazwa_zadania", "Zadanie bez nazwy"))
    if plan:
        col1.caption(f"W ramach: {display_plan_name(plan)}")
    col2.caption(status)
    col3.progress(progress, text=f"{progress * 100:.0f}%")


def main():
    st.set_page_config(page_title="PRO RP", page_icon="🛡️", layout="wide")
    st.markdown("""
    <style>
      .block-container {padding-top: 1.4rem; padding-bottom: 2rem;}
      div[data-testid="stMetric"] {background: rgba(120, 130, 150, .08); padding: .8rem 1rem; border-radius: .8rem; border: 1px solid rgba(120,130,150,.18);}
      .pro-kicker {text-transform: uppercase; letter-spacing: .08em; font-size: .76rem; font-weight: 700; opacity: .72;}
      .pro-subtle {font-size: .9rem; opacity: .75;}
    </style>
    """, unsafe_allow_html=True)
    st.title("🛡️ Zintegrowana platforma PRO RP")
    st.caption("Demonstrator PoC · dane widoczne zgodnie z zakresem uprawnień przekazanym przez warstwę dostępową.")

    try:
        identities = get_demo_identities()
    except Exception as exc:
        st.error(f"Nie udało się pobrać kont demonstracyjnych z warstwy dostępowej: {exc}")
        st.info("Sprawdź serwisy presentation i access oraz endpoint `/api/demo-identities`.")
        return
    if not identities:
        st.error("Warstwa dostępowa nie zwróciła aktywnych kont demonstracyjnych.")
        return

    identity_by_id = {str(person["id_osoby"]): person for person in identities}
    identity_options = list(identity_by_id)
    preferred_identity = "demo-premier" if "demo-premier" in identity_by_id else identity_options[0]
    if st.session_state.get("selected_demo_person_id") not in identity_by_id:
        st.session_state["selected_demo_person_id"] = preferred_identity

    with st.sidebar:
        st.header("Perspektywa dostępu")
        selected_person_id = st.selectbox(
            "Konto demonstracyjne", options=identity_options,
            format_func=lambda person_id: (
                f"{identity_by_id[person_id]['imie']} {identity_by_id[person_id]['nazwisko']} · "
                f"{identity_by_id[person_id]['nazwa_jednostki']}"
            ), key="selected_demo_person_id",
        )
        st.caption("Konto jest demonstracyjne; tożsamość przekazywana jest do API w nagłówku `X-Person-Id`.")

    try:
        me = get_me(selected_person_id)
        state = get_state(selected_person_id)
        plans = get_plans(selected_person_id)
        units = get_units(selected_person_id)
        tasks = get_tasks(selected_person_id)
        collaboration_summary = get_collaboration_summary(selected_person_id)
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code if exc.response is not None else "?"
        st.error(f"Warstwa dostępowa odrzuciła żądanie lub zwróciła błąd (HTTP {code}).")
        st.code(str(exc))
        return
    except Exception as exc:
        st.error(f"Nie udało się pobrać danych z warstwy dostępowej: {exc}")
        st.info("Uruchom system przez `docker compose up --build` i sprawdź logi presentation/access/data.")
        return

    plans_by_id = {str(p["id_planu"]): p for p in plans}
    units_by_id = {str(u["id"]): u for u in units}
    tasks_by_plan = defaultdict(list)
    for task in tasks:
        tasks_by_plan[str(task.get("id_planu", ""))].append(task)

    own_identity_unit_id = str(me.get("id_jednostki", ""))
    is_national_account = selected_person_id == "demo-premier"
    direct_subordinate_units = direct_child_units(own_identity_unit_id, units)
    direct_subordinate_unit_ids = {str(unit["id"]) for unit in direct_subordinate_units}
    plan_owner_by_id: dict[str, str] = {}
    for unit in units:
        for plan_id in unit.get("id_planow", []):
            plan_owner_by_id.setdefault(str(plan_id), str(unit["id"]))
    if is_national_account:
        # The national overview is an executive summary of direct reports only.
        # Lower-level units remain available to their own authorized perspectives,
        # but are not selectable from the Premier's overview scope.
        scope_options = [NATIONAL_SCOPE] + [
            str(u["id"]) for u in sorted(direct_subordinate_units, key=lambda item: item.get("nazwa", ""))
        ]
    else:
        scope_options = [str(u["id"]) for u in sorted(units, key=lambda item: item.get("nazwa", ""))]
    if st.session_state.get("selected_scope") not in scope_options:
        st.session_state["selected_scope"] = NATIONAL_SCOPE if is_national_account else own_identity_unit_id
        if st.session_state["selected_scope"] not in scope_options:
            st.session_state["selected_scope"] = scope_options[0] if scope_options else NATIONAL_SCOPE

    with st.sidebar:
        st.divider()
        st.markdown("**Aktywna tożsamość**")
        st.write(f"{me.get('imie', '')} {me.get('nazwisko', '')}")
        st.caption(me.get("stanowisko") or "Konto demonstracyjne")
        st.write(f"**Klauzula:** `{me.get('klauzula_tajnosci', '—')}`")
        st.divider()
        st.markdown("**Zakres analizy**")
        selected_scope = st.selectbox(
            "Jednostka / obszar", options=scope_options,
            format_func=lambda scope: "Cały kraj — przegląd ogólny" if scope == NATIONAL_SCOPE else units_by_id.get(scope, {}).get("nazwa", "Jednostka niedostępna"),
            key="selected_scope",
        )
        st.caption("Zakres wyboru ograniczają uprawnienia API; nazwy techniczne i identyfikatory są ukryte w selektorze.")

    is_national_scope = selected_scope == NATIONAL_SCOPE
    selected_unit = units_by_id.get(selected_scope) if not is_national_scope else None
    if is_national_scope:
        scoped_units = direct_subordinate_units
        direct_plan_ids = {
            str(plan_id)
            for unit in direct_subordinate_units
            for plan_id in unit.get("id_planow", [])
            if str(plan_id) in plans_by_id
        }
        scoped_plans = [plans_by_id[pid] for pid in direct_plan_ids]
        scoped_tasks = [
            task for task in tasks
            if task_belongs_to_units(
                task, direct_subordinate_unit_ids, direct_plan_ids, plan_owner_by_id
            )
        ]
        overview_title = "Przegląd krajowy"
        own_tasks = scoped_tasks
        plan_scope_tasks = scoped_tasks
        budget = sum(float(u.get("budzet", 0) or 0) for u in direct_subordinate_units)
        budget_cost_tasks = scoped_tasks
    else:
        direct_plan_ids = {str(pid) for pid in (selected_unit or {}).get("id_planow", []) if str(pid) in plans_by_id}
        scoped_plans = [plans_by_id[pid] for pid in direct_plan_ids]
        scoped_units = [selected_unit] if selected_unit else []
        own_tasks = [t for t in tasks if task_belongs_to_unit(t, selected_scope, direct_plan_ids)]
        plan_scope_tasks = own_tasks
        scoped_tasks = own_tasks
        overview_title = (selected_unit or {}).get("nazwa", "Przegląd jednostki")
        budget = float((selected_unit or {}).get("budzet", 0) or 0)
        budget_cost_tasks = own_tasks

    active_plans = [p for p in scoped_plans if p.get("status_planu") in ACTIVE_PLAN_STATUSES]
    active_plan_ids = {str(plan["id_planu"]) for plan in active_plans}
    own_real_tasks = [task for task in own_tasks if task.get("typ_zadania") == "REAL"]
    own_completion = pct(own_real_tasks)
    # Plan-level aggregate includes REAL work in the plan subtree. UI details remain
    # limited to the selected unit and its direct reporting scope.
    active_plan_tasks = [
        task for task in tasks
        if task.get("typ_zadania") == "REAL"
        and str(task.get("id_planu", "")) in set().union(*(descendant_plan_ids(pid, plans) for pid in active_plan_ids))
    ]
    plans_completion = pct(active_plan_tasks)
    estimated_consumed = sum(
        float(task.get("koszt", 0) or 0) * max(0.0, min(1.0, float(task.get("poziom_realizacji", 0) or 0)))
        for task in budget_cost_tasks
    )
    remaining_budget = max(0.0, budget - estimated_consumed)

    if collaboration_summary:
        with st.container(border=True):
            st.markdown("<div class='pro-kicker'>Bramka informacyjna</div>", unsafe_allow_html=True)
            st.subheader("Współpraca między jednostkami")
            st.caption("Dostępne są wyłącznie zagregowane wskaźniki. Szczegóły zadań pozostają po stronie jednostki źródłowej.")
            cols = st.columns(min(3, len(collaboration_summary)))
            for idx, summary in enumerate(collaboration_summary):
                with cols[idx % len(cols)]:
                    st.markdown(f"**{summary['jednostka']}**")
                    st.metric("Zadania zrealizowane", summary["liczba_zrealizowanych"])
                    st.metric("Zadania łącznie", summary["liczba_zadan"])
                    st.caption(f"Średnia realizacja: {summary['poziom_realizacji_proc']:.1f}%")

    tab_overview, tab_unit, tab_prepared, tab_active, tab_plans, tab_map = st.tabs([
        "Przegląd", "Jednostka", "Plany przygotowane", "Plany aktywne", "Hierarchia planów", "Mapa"
    ])

    with tab_overview:
        st.markdown(f"<div class='pro-kicker'>{'Poziom krajowy' if is_national_scope else 'Bieżąca perspektywa'}</div>", unsafe_allow_html=True)
        st.header(overview_title)
        if is_national_scope:
            st.caption("Wskaźniki i lista planów obejmują wyłącznie jednostki bezpośrednio podległe Premierowi. Zadania jednostek niższego szczebla nie są wliczane do tego przeglądu.")
        else:
            st.caption("Podsumowanie dotyczy planów przypisanych bezpośrednio do wybranej jednostki. Jednostki podległe mają osobne widoki.")

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Aktywne plany", len(active_plans))
        k2.metric("Realizacja zadań jednostki", f"{own_completion:.0f}%" if own_completion is not None else "—")
        k3.metric("Realizacja zadań w aktywnych planach", f"{plans_completion:.0f}%" if plans_completion is not None else "—")
        k4.metric("Pozostały budżet · szacunek", fmt_money(remaining_budget))
        st.caption("Szacunek budżetu: budżet jednostki minus koszt zadań przemnożony przez ich poziom realizacji. To wskaźnik demonstracyjny, nie księgowe wykonanie budżetu.")

        st.divider()
        st.subheader("Aktywne plany i realizacja zadań")
        if not active_plans:
            st.info("Brak aktywnych planów przypisanych do tego zakresu albo brak planów dostępnych dla bieżącej tożsamości.")
        for plan in sorted(active_plans, key=lambda p: (p.get("data_utworzenia", ""), p.get("nazwa_dokumentu", ""))):
            pid = str(plan["id_planu"])
            plan_tasks = [
                task for task in tasks_by_plan.get(pid, [])
                if (
                    task_belongs_to_units(task, direct_subordinate_unit_ids, direct_plan_ids, plan_owner_by_id)
                    if is_national_scope
                    else task_belongs_to_unit(task, selected_scope, direct_plan_ids)
                )
            ]
            completion = pct(plan_tasks)
            completion_label = f"{completion:.0f}%" if completion is not None else "Brak zadań"
            with st.container(border=True):
                title_col, metric_col = st.columns([4, 1])
                title_col.markdown(f"### {display_plan_name(plan)}")
                plan_status_label = {"approved": "Zatwierdzony", "in_review": "W uzgodnieniu", "draft": "Projekt", "rejected": "Odrzucony"}.get(plan.get("status_planu"), "Nieznany")
                title_col.caption(f"Status: {plan_status_label} · Klauzula: {plan.get('klauzula_tajnosci', '—')}")
                metric_col.metric("Realizacja", completion_label)
                if completion is not None:
                    st.progress(max(0.0, min(1.0, completion / 100)))
                if plan_tasks:
                    st.markdown("**Zadania w realizacji tego planu dla bieżącego zakresu**")
                    for task in sorted(plan_tasks, key=lambda item: (item.get("nazwa_zadania", ""))):
                        render_task_summary_row(task, plan)
                else:
                    st.caption("Brak zadań przypisanych do tej jednostki w tym planie.")

    with tab_unit:
        if is_national_scope:
            st.info("Wybrano przegląd krajowy. Aby zobaczyć opis, budżet i zasoby konkretnej jednostki, wybierz ją w polu „Zakres analizy” po lewej stronie.")
        elif not selected_unit:
            st.warning("Wybrana jednostka nie jest dostępna w bieżącym zakresie uprawnień.")
        else:
            st.markdown("<div class='pro-kicker'>Karta jednostki</div>", unsafe_allow_html=True)
            st.header(selected_unit.get("nazwa", "Jednostka"))
            parent_name = selected_unit.get("nazwa_jednostki_nadrzednej")
            if parent_name:
                st.caption(f"Jednostka nadrzędna: {parent_name}")
            else:
                st.caption("Jednostka najwyższego poziomu w dostępnym opisie organizacyjnym.")

            budget_col, plan_col, task_col = st.columns(3)
            budget_col.metric("Budżet jednostki", fmt_money(selected_unit.get("budzet", 0)))
            plan_col.metric("Plany przypisane jednostce", len(direct_plan_ids))
            task_col.metric("Zadania tej jednostki", len(own_tasks))

            st.divider()
            st.subheader("Plany jednostki")
            if direct_plan_ids:
                for plan in sorted((plans_by_id[pid] for pid in direct_plan_ids), key=lambda p: display_plan_name(p).casefold()):
                    with st.container(border=True):
                        left, right = st.columns([4, 1])
                        left.markdown(f"**{display_plan_name(plan)}**")
                        left.caption(f"{'Aktywny' if plan.get('status_operacyjny') == 'active' else 'Nieaktywny'} · {plan.get('klauzula_tajnosci', '—')}")
                        right.caption("Status")
                        right.write("W realizacji" if plan.get("status_operacyjny") == "active" else "Nieaktywny")
            else:
                st.info("W dostępnych danych nie ma planów przypisanych bezpośrednio do tej jednostki.")

            with st.expander("Zasoby jednostki", expanded=False):
                render_resource_panel(selected_unit.get("zasoby", {}))

            with st.expander("Dane dodatkowe", expanded=False):
                type_labels = {
                    "wezel_koordynacyjny_poc": "Węzeł koordynacyjny",
                    "ministerstwo": "Ministerstwo",
                    "sluzba": "Służba",
                    "administracja_wojewodzka": "Administracja wojewódzka",
                }
                unit_type = selected_unit.get("typ")
                if unit_type:
                    st.write(f"**Typ jednostki:** {type_labels.get(unit_type, unit_type.replace('_', ' ').capitalize())}")
                if selected_unit.get("id_regionu"):
                    st.write("**Region:** dane regionu są zapisane w źródle; identyfikator techniczny pominięto w widoku.")
                staff = selected_unit.get("pracownicy", [])
                if staff:
                    st.write(f"**Pracownicy widoczni zgodnie z uprawnieniami:** {len(staff)}")

            st.divider()
            st.subheader("Zadania tej jednostki")
            st.caption("Lista zawiera wyłącznie zadania przypisane do tej jednostki w jej własnych planach. Rozwiń pozycję, aby otworzyć szczegóły.")
            filter_col, search_col = st.columns([1, 2])
            status_filter = filter_col.selectbox("Status", ["Wszystkie", "Zakończone", "W toku", "Zaplanowane"], key="unit_task_status_filter")
            task_search = search_col.text_input("Szukaj zadania", placeholder="Wpisz nazwę zadania…", key="unit_task_search").strip().casefold()
            filtered_tasks = []
            for task in own_tasks:
                status = task_status(task)
                if status_filter != "Wszystkie" and status != status_filter:
                    continue
                if task_search and task_search not in str(task.get("nazwa_zadania", "")).casefold():
                    continue
                filtered_tasks.append(task)
            if filtered_tasks:
                done_count = sum(1 for task in filtered_tasks if task.get("status"))
                avg = pct(filtered_tasks)
                c1, c2, c3 = st.columns(3)
                c1.metric("Widoczne zadania", len(filtered_tasks))
                c2.metric("Zakończone", done_count)
                c3.metric("Średnia realizacja", f"{avg:.0f}%" if avg is not None else "—")
                for task in sorted(filtered_tasks, key=lambda item: (str(item.get("id_planu", "")), item.get("nazwa_zadania", ""))):
                    task_id = str(task["id_zadania"])
                    plan_id = str(task["id_planu"])
                    status = task_status(task)
                    progress = max(0.0, min(1.0, float(task.get("poziom_realizacji", 0) or 0)))
                    task_plan = plans_by_id.get(plan_id, {})
                    task_plan_title = display_plan_name(task_plan) if task_plan else "Plan niedostępny"
                    with st.expander(f"{task.get('nazwa_zadania', 'Zadanie bez nazwy')} · {task_plan_title} · {status} · {progress * 100:.0f}%"):
                        try:
                            detail = get_task_detail(selected_person_id, plan_id, task_id)
                        except Exception as exc:
                            st.warning(f"Nie udało się pobrać szczegółów z API: {exc}")
                            detail = task
                        plan = plans_by_id.get(plan_id, {})
                        d1, d2, d3 = st.columns(3)
                        d1.write(f"**Plan realizacji:** {display_plan_name(plan) if plan else 'Plan niedostępny'}")
                        d2.write(f"**Klauzula:** {detail.get('klauzula_tajnosci', task.get('klauzula_tajnosci', '—'))}")
                        d3.write(f"**Koszt zadania:** {fmt_money(detail.get('koszt', task.get('koszt', 0)))}")
                        st.write(f"**Status:** {status}")
                        current_progress = max(0.0, min(1.0, float(detail.get("poziom_realizacji", task.get("poziom_realizacji", 0)) or 0)))
                        st.progress(current_progress)
                        task_type = detail.get("typ_zadania", task.get("typ_zadania", "REAL"))
                        if task_type == "REAL" and plan.get("status_operacyjny") == "active":
                            new_progress = st.slider("Aktualizacja realizacji zadania", 0, 100, int(round(current_progress * 100)), key=f"progress_{plan_id}_{task_id}")
                            if st.button("Zapisz postęp", key=f"save_progress_{plan_id}_{task_id}"):
                                try:
                                    update_task_progress(selected_person_id, plan_id, task_id, new_progress / 100)
                                    st.success("Zapisano postęp zadania.")
                                    st.rerun()
                                except httpx.HTTPStatusError as exc:
                                    st.error(f"Nie udało się zapisać postępu: HTTP {exc.response.status_code} — {exc.response.text}")
                        elif task_type == "REAL":
                            st.caption("Zadanie REAL można aktualizować po aktywacji planu.")
                        else:
                            st.caption("Zadanie przygotowawcze PRZ — postęp przygotowania.")
                        st.caption(f"Ostatnia aktualizacja: {detail.get('data_aktualizacji', task.get('data_aktualizacji', '—'))}")
                        resources = detail.get("zasoby", task.get("zasoby", {}))
                        if resources:
                            st.markdown("**Zasoby przypisane do zadania**")
                            render_resource_panel(resources)
                        assigned_units = detail.get("jednostki", [])
                        if assigned_units:
                            st.write("**Wykonawcy:** " + ", ".join(u.get("nazwa", "Jednostka") for u in assigned_units))
            else:
                st.info("Brak zadań dla tej jednostki w jej własnych planach albo żadne zadanie nie spełnia filtrów.")

    with tab_prepared:
        st.header("Plany przygotowane")
        st.caption("Plany nieaktywne. Przygotowanie PRZ jest wskaźnikiem informacyjnym; aktywację można wykonać także w sytuacji krytycznej.")
        prepared_plans = [p for p in scoped_plans if p.get("status_operacyjny", "prepared") != "active"]
        if not prepared_plans:
            st.info("Brak nieaktywnych planów w bieżącym zakresie.")
        for plan in sorted(prepared_plans, key=lambda p: display_plan_name(p).casefold()):
            pid = str(plan["id_planu"])
            plan_tasks = [t for t in tasks_by_plan.get(pid, []) if t.get("typ_zadania") == "PRZ"]
            real_tasks = [t for t in tasks_by_plan.get(pid, []) if t.get("typ_zadania") == "REAL"]
            prep = pct(plan_tasks)
            with st.container(border=True):
                st.subheader(display_plan_name(plan))
                st.caption(f"Status dokumentu: {plan.get('status_planu', '—')} · Status operacyjny: nieaktywny")
                m1, m2, m3 = st.columns(3)
                m1.metric("Przygotowanie PRZ", f"{prep:.0f}%" if prep is not None else "Brak zadań PRZ")
                m2.metric("Zadania PRZ", len(plan_tasks))
                m3.metric("Zaplanowane zadania REAL", len(real_tasks))
                if plan_tasks:
                    st.progress(max(0.0, min(1.0, (prep or 0) / 100)), text="Poziom przygotowania")
                with st.expander("Zweryfikuj przygotowanie"):
                    st.markdown("**Zadania przygotowawcze (PRZ)**")
                    for task in plan_tasks:
                        st.write(f"• {task.get('nazwa_zadania')} — {float(task.get('poziom_realizacji', 0))*100:.0f}%")
                    st.markdown("**Zadania realizacyjne (REAL) — zaplanowane, przed aktywacją 0%**")
                    for task in real_tasks:
                        st.write(f"• {task.get('nazwa_zadania')} — {float(task.get('poziom_realizacji', 0))*100:.0f}%")
                    allowed_child_owner_ids = direct_subordinate_unit_ids if is_national_scope else {
                        str(u["id"]) for u in units
                        if str(u.get("id_jednostki_nadrzednej") or "") == str(selected_scope)
                    }
                    child_ids = [str(p.get("id_planu")) for p in plans
                                 if str(p.get("id_planu_nadrzednego") or "") == pid
                                 and plan_owner_by_id.get(str(p.get("id_planu"))) in allowed_child_owner_ids]
                    if child_ids:
                        st.markdown("**Podplany jednostek bezpośrednio podległych**")
                        for child_id in child_ids:
                            child = plans_by_id.get(child_id)
                            if child:
                                st.write(f"• {display_plan_name(child)} — {'aktywny' if child.get('status_operacyjny') == 'active' else 'nieaktywny'}")
                if st.button("Aktywuj plan i wszystkie podplany", key=f"activate_{pid}", type="primary"):
                    try:
                        result = activate_plan(selected_person_id, pid)
                        st.success(f"Aktywowano {len(result.get('activated_plan_ids', []))} planów w poddrzewie.")
                        st.rerun()
                    except httpx.HTTPStatusError as exc:
                        st.error(f"Nie udało się aktywować planu: HTTP {exc.response.status_code} — {exc.response.text}")
                    except Exception as exc:
                        st.error(f"Nie udało się aktywować planu: {exc}")

    with tab_active:
        st.header("Plany aktywne")
        st.caption("Postęp planu obejmuje własne zadania REAL oraz agregat planów jednostek podległych. Szczegóły zadań podległych pozostają odseparowane.")
        active_scope_plans = [p for p in scoped_plans if p.get("status_operacyjny") == "active"]
        if not active_scope_plans:
            st.info("Brak aktywnych planów w bieżącym zakresie.")
        for plan in sorted(active_scope_plans, key=lambda p: display_plan_name(p).casefold()):
            pid = str(plan["id_planu"])
            own_real = [t for t in tasks_by_plan.get(pid, []) if t.get("typ_zadania") == "REAL"]
            subtree_ids = descendant_plan_ids(pid, plans)
            subtree_real = [t for t in tasks if t.get("typ_zadania") == "REAL" and str(t.get("id_planu")) in subtree_ids]
            completion = pct(subtree_real)
            with st.container(border=True):
                st.subheader(display_plan_name(plan))
                st.caption(f"Aktywowano: {plan.get('data_aktywacji') or 'data niedostępna'}")
                a, b, c = st.columns(3)
                a.metric("Realizacja planu i podplanów", f"{completion:.0f}%" if completion is not None else "—")
                b.metric("Zadania REAL", len(own_real))
                c.metric("Zakończone", sum(1 for t in own_real if float(t.get('poziom_realizacji', 0) or 0) >= 1))
                for task in own_real:
                    st.write(f"**{task.get('nazwa_zadania')}**")
                    st.progress(max(0.0, min(1.0, float(task.get('poziom_realizacji', 0) or 0))), text=f"{float(task.get('poziom_realizacji', 0) or 0)*100:.0f}%")

    with tab_plans:
        st.markdown("<div class='pro-kicker'>Struktura dokumentów</div>", unsafe_allow_html=True)
        st.header("Hierarchia planów")
        st.caption("Widok pokazuje zależności pomiędzy planami. Szczegółowa realizacja zadań jest dostępna w przeglądzie jednostki, bez dublowania pełnego rejestru.")
        if is_national_account:
            # Keep the Premier's overview and hierarchy at the direct-report level;
            # do not expose subordinate command plans such as the Radom police plan.
            hierarchy_plan_ids = {
                str(plan_id)
                for unit in direct_subordinate_units
                for plan_id in unit.get("id_planow", [])
                if str(plan_id) in plans_by_id
            }
            hierarchy_plans = [plan for plan in plans if str(plan["id_planu"]) in hierarchy_plan_ids]
            hierarchy_tasks = [
                task for task in tasks
                if task_belongs_to_units(
                    task, direct_subordinate_unit_ids, hierarchy_plan_ids, plan_owner_by_id
                )
            ]
            hierarchy_units = direct_subordinate_units
        else:
            hierarchy_plans = plans
            hierarchy_tasks = tasks
            hierarchy_units = units
        hierarchy_tasks_by_plan = defaultdict(list)
        for task in hierarchy_tasks:
            hierarchy_tasks_by_plan[str(task.get("id_planu", ""))].append(task)
        children = defaultdict(list)
        for plan in hierarchy_plans:
            children[str(plan.get("id_planu_nadrzednego") or "")].append(plan)

        def render_plan_tree(parent_id="", depth=0):
            for plan in sorted(children.get(str(parent_id or ""), []), key=lambda item: str(item["id_planu"])):
                pid = str(plan["id_planu"])
                plan_task_count = len(hierarchy_tasks_by_plan.get(pid, []))
                label = f"{'　' * depth}{display_plan_name(plan)} · {plan_task_count} dostępnych zadań"
                executors = [u.get("nazwa", "Jednostka") for u in hierarchy_units if pid in {str(value) for value in u.get("id_planow", [])}]
                executor_label = ", ".join(executors) if executors else "Nie wskazano w danych"
                if depth == 0 and pid == "O":
                    with st.container(border=True):
                        st.markdown("<div style='padding:.7rem 1rem;border-radius:.6rem;background:rgba(70,110,170,.13);border-left:4px solid #5278ad;'>", unsafe_allow_html=True)
                        st.markdown("**PLAN KRAJOWY**")
                        st.subheader(display_plan_name(plan))
                        st.markdown("</div>", unsafe_allow_html=True)
                        st.caption(f"Klauzula: {plan.get('klauzula_tajnosci', '—')} · Status: {plan.get('status_planu', '—')}")
                        st.write(f"**Wykonawcy:** {executor_label}")
                        st.write(f"**Sporządził:** {plan.get('sporzadzil', '—')} · **Zatwierdzający:** {plan.get('zatwierdzajacy', '—')}")
                        render_plan_tree(pid, depth + 1)
                else:
                    with st.expander(label, expanded=(depth == 0)):
                        st.caption("PLAN POCHODNY" if depth > 0 else "PLAN NADRZĘDNY")
                        meta1, meta2 = st.columns(2)
                        meta1.write(f"**Status:** {plan.get('status_planu', '—')}")
                        meta2.write(f"**Klauzula:** {plan.get('klauzula_tajnosci', '—')}")
                        st.write(f"**Wykonawcy:** {executor_label}")
                        st.write(f"**Sporządził:** {plan.get('sporzadzil', '—')} · **Zatwierdzający:** {plan.get('zatwierdzajacy', '—')}")
                        render_plan_tree(pid, depth + 1)
        render_plan_tree()

    with tab_map:
        st.header("Mapa sytuacyjna")
        map_col, info_col = st.columns([2, 1])
        with map_col:
            m = folium.Map(location=RADOM_CENTER, zoom_start=6, tiles="OpenStreetMap")
            folium.Marker(RADOM_CENTER, tooltip="Radom — obszar demonstracyjny", popup="Dane geograficzne obiektów nie są jeszcze częścią modelu.").add_to(m)
            st_folium(m, use_container_width=True, height=520)
        with info_col:
            st.info("Mapa jest na razie podkładem demonstracyjnym. Jednostki i zadania nie mają współrzędnych geograficznych w źródłowych danych.")
            st.markdown("**Możliwe rozszerzenia:** regiony, lokalizacje infrastruktury, schrony, zasoby i warstwy scenariuszy.")

    with st.expander("Diagnostyka API"):
        st.json({"identity": selected_person_id, "plans_in_current_view": len(scoped_plans), "units_in_current_view": len(scoped_units), "tasks_in_current_view": len(scoped_tasks),
                 "operational_tasks_in_current_scope": len(own_tasks), "resources": len(state.get("resources", [])),
                 "presentation_api": PRESENTATION_API_URL})


if __name__ == "__main__":
    main()
