import os
import asyncio
from datetime import date, datetime, timedelta
from urllib.parse import quote
from collections import defaultdict

import httpx
import pandas as pd
import streamlit as st
import folium
from streamlit_folium import st_folium

from app.view_helpers import direct_child_units, unit_descendants, task_belongs_to_unit, task_belongs_to_units, task_status, display_plan_name, completion_percent, format_money

PRESENTATION_API_URL = os.getenv("PRESENTATION_API_URL", "http://localhost:8000")
RADOM_CENTER = [52.0, 19.2]
NATIONAL_SCOPE = "__national__"
CLASSIFICATIONS = ["jawne", "zastrzezone", "poufne", "tajne", "scisle_tajne"]


def request_json(method: str, path: str, person_id: str | None = None, payload: dict | None = None):
    headers = {"X-Person-Id": person_id} if person_id else {}
    async def _request():
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.request(method, f"{PRESENTATION_API_URL}{path}", headers=headers, json=payload)
            response.raise_for_status()
            return response.json()
    return asyncio.run(_request())


def get(path, person_id=None): return request_json("GET", path, person_id)
def post(path, person_id=None, payload=None): return request_json("POST", path, person_id, payload or {})
def put(path, person_id=None, payload=None): return request_json("PUT", path, person_id, payload or {})
def patch(path, person_id=None, payload=None): return request_json("PATCH", path, person_id, payload or {})


def plan_status(plan):
    return {"editing": "W opracowaniu", "draft": "Projekt", "in_review": "Do zatwierdzenia", "approved": "Zatwierdzony", "rejected": "Do poprawy"}.get(plan.get("status_planu"), plan.get("status_planu", "Nieznany"))


def op_status(plan): return "Aktywny operacyjnie" if plan.get("status_operacyjny") == "active" else "Nieaktywny operacyjnie"


def clamp_progress(task):
    try: return max(0.0, min(1.0, float(task.get("poziom_realizacji", 0) or 0)))
    except (TypeError, ValueError): return 0.0


def _select_scope(scope_id):
    """Widget callback: Streamlit executes this before rebuilding keyed widgets."""
    st.session_state["selected_scope_id"] = scope_id


def main():
    st.set_page_config(page_title="PRO RP | Obraz sytuacji", page_icon="🛡️", layout="wide")
    st.markdown("""<style>
    .block-container{padding-top:1.15rem;padding-bottom:2rem;max-width:1600px}
    div[data-testid="stMetric"]{background:rgba(120,130,150,.07);padding:.75rem 1rem;border-radius:.8rem;border:1px solid rgba(120,130,150,.17)}
    .eyebrow{text-transform:uppercase;letter-spacing:.09em;font-size:.72rem;font-weight:700;opacity:.68}
    .active-plan-marker{display:none}
    div[data-testid="stVerticalBlockBorderWrapper"]:has(.active-plan-marker){border:2px solid #3b82f6!important;background:rgba(59,130,246,.07)!important}
    .active-plan-badge{display:inline-block;background:#2563eb;color:white;font-weight:700;font-size:.78rem;padding:.28rem .6rem;border-radius:.5rem;letter-spacing:.02em}
    .hierarchy-level-2{padding-left:1.15rem;border-left:2px solid rgba(120,130,150,.35);margin-left:.4rem}
    </style>""", unsafe_allow_html=True)
    st.title("🛡️ Zintegrowana platforma PRO RP")
    st.caption("Obraz realizacji zadań i cykl życia planów · widoczność danych egzekwowana przez warstwę Access")
    try:
        identities = get("/api/demo-identities")
        if not identities: st.error("Brak dostępnych kont demonstracyjnych."); return
        identity_by_id = {str(x["id_osoby"]): x for x in identities}
        preferred = "demo-premier" if "demo-premier" in identity_by_id else next(iter(identity_by_id))
        if st.session_state.get("selected_demo_person_id") not in identity_by_id: st.session_state["selected_demo_person_id"] = preferred
        with st.sidebar:
            st.header("Perspektywa dostępu")
            person_id = st.selectbox("Konto demonstracyjne", list(identity_by_id), format_func=lambda pid: f"{identity_by_id[pid].get('imie','')} {identity_by_id[pid].get('nazwisko','')} · {identity_by_id[pid].get('nazwa_jednostki','')}", key="selected_demo_person_id")
            me = get("/api/me", person_id)
            st.divider(); st.write(f"**{me.get('imie','')} {me.get('nazwisko','')}**")
            st.caption(me.get("stanowisko", "Konto demonstracyjne"))
            st.caption(f"Klauzula: {me.get('klauzula_tajnosci','—')}")
        plans = get("/api/plans", person_id)
        received_requirements = get("/api/requirements", person_id)
        units = get("/api/units", person_id)
        tasks = get("/api/tasks?limit=5000", person_id)
        state = get("/api/state", person_id)
    except Exception as exc:
        st.error(f"Nie udało się pobrać danych z API: {exc}")
        st.info("Sprawdź serwisy presentation, access i data. Interfejs nie omija warstwy dostępowej.")
        return

    # The flood scenario overlays the records returned by Access in this Streamlit
    # session only. It deliberately reuses the real plan/task IDs so the Plans,
    # Tasks and operational analytics tabs show the same simulated lifecycle,
    # without mutating the operational database.
    sim_elapsed = max(0, min(11, int(st.session_state.get("flood_demo_elapsed_hours", 0) or 0)))
    sim_flood_arrived = sim_elapsed >= 6
    scenario_plan_ids = {"OR", "ORS", "ORP", "ORPP", "ORPPP", "ORSS", "ORSSS", "PS", "PSS", "PSSS"}
    scenario_active_plan_ids = {"O", "OR", "ORS", "ORP", "ORPP", "ORPPP", "ORSS", "ORSSS", "PS", "PSS", "PSSS"} if sim_flood_arrived else set()
    for plan in plans:
        pid = str(plan.get("id_planu", ""))
        if pid == "O" or pid in scenario_plan_ids:
            plan["status_operacyjny"] = "active" if pid in scenario_active_plan_ids else "prepared"
    for task in tasks:
        pid = str(task.get("id_planu", ""))
        task_id = str(task.get("id_zadania", ""))
        if pid not in scenario_plan_ids:
            continue
        if task_id.startswith("PRZ-"):
            # Preparations begin at 0% and progress before the flood arrives.
            progress = min(1.0, max(0.0, (sim_elapsed / 5.0)))
            task["poziom_realizacji"] = progress
            task["status"] = progress >= 1.0
        elif task_id.startswith("REAL-"):
            # REAL tasks remain planned until the flood triggers activation.
            progress = 0.0 if not sim_flood_arrived else min(1.0, (sim_elapsed - 5) / 5.0)
            task["poziom_realizacji"] = progress
            task["status"] = progress >= 1.0
            task["typ_zadania"] = "REAL"
        if task_id.startswith("PRZ-"):
            task["typ_zadania"] = "PRZ"

    plans_by_id = {str(p.get("id_planu")): p for p in plans}
    units_by_id = {str(u.get("id")): u for u in units}
    owner_by_plan = {str(pid): str(u["id"]) for u in units for pid in u.get("id_planow", [])}
    own_unit_id = str(me.get("id_jednostki", ""))
    direct_units = direct_child_units(own_unit_id, units)
    direct_ids = {str(u["id"]) for u in direct_units}
    is_national = person_id == "demo-premier"
    # Reset the previous user's scope before the keyed scope widget is created.
    # This prevents a stale Police/other-unit view from carrying over to Premier.
    previous_scope_person = st.session_state.get("_scope_person_id")
    if previous_scope_person != person_id:
        st.session_state["selected_scope_id"] = own_unit_id
        st.session_state["_scope_person_id"] = person_id
    # The scope selector can navigate the visible organizational tree. The tree itself
    # is rendered to two levels at a time; selecting a node makes it the new root.
    descendant_units = unit_descendants(own_unit_id, units)
    if is_national:
        navigable_units = sorted(units, key=lambda x: x.get("nazwa", ""))
    else:
        navigable_units = [u for u in descendant_units if str(u.get("id")) in units_by_id]
    scope_options = ([NATIONAL_SCOPE] if is_national else []) + [own_unit_id] + [str(u["id"]) for u in navigable_units if str(u["id"]) != own_unit_id]
    if st.session_state.get("selected_scope_id") not in scope_options:
        st.session_state["selected_scope_id"] = own_unit_id
    with st.sidebar:
        selected_scope = st.selectbox(
            "Zakres analizy", scope_options,
            format_func=lambda x: (
                "Przegląd krajowy · jednostki bezpośrednio podległe" if x == NATIONAL_SCOPE
                else f"Moja jednostka · {units_by_id.get(x, {}).get('nazwa', 'Jednostka')}" if x == own_unit_id
                else units_by_id.get(x, {}).get("nazwa", "Jednostka")
            ),
            key="selected_scope_id",
        )
        st.caption("Zakres prezentacji nie zmienia tożsamości ani uprawnień konta.")

    scope_unit_id = own_unit_id if selected_scope == NATIONAL_SCOPE else str(selected_scope)
    scope_unit = units_by_id.get(scope_unit_id, {})
    scope_direct_units = direct_child_units(scope_unit_id, units)
    scope_direct_ids = {str(u["id"]) for u in scope_direct_units}
    if is_national and selected_scope == NATIONAL_SCOPE:
        visible_scope_units = scope_direct_units
        visible_scope_ids = scope_direct_ids
        own_plans_for_scope = {str(pid) for pid in units_by_id.get(own_unit_id, {}).get("id_planow", [])}
        visible_scope_plans = own_plans_for_scope | {str(pid) for u in scope_direct_units for pid in u.get("id_planow", [])}
        visible_scope_tasks = [t for t in tasks if task_belongs_to_units(t, visible_scope_ids, visible_scope_plans, owner_by_plan)]
        overview_title = "Obraz sytuacji — poziom krajowy"
    else:
        visible_scope_units = [scope_unit] if scope_unit else []
        visible_scope_ids = {scope_unit_id}
        visible_scope_plans = {str(pid) for u in visible_scope_units for pid in u.get("id_planow", [])}
        visible_scope_tasks = [t for t in tasks if task_belongs_to_unit(t, scope_unit_id, visible_scope_plans)]
        overview_title = scope_unit.get("nazwa", "Obraz sytuacji") if scope_unit else "Obraz sytuacji"
    if is_national and selected_scope == own_unit_id:
        # PRM/RM perspective includes plans owned by direct reports so that the
        # Premier can coordinate and activate plans from this scope as well.
        visible_scope_plans |= {
            str(pid) for unit in scope_direct_units for pid in unit.get("id_planow", [])
        }
    visible_scope_plans_list = [plans_by_id[pid] for pid in visible_scope_plans if pid in plans_by_id]
    active_plans = [p for p in visible_scope_plans_list if p.get("status_operacyjny") == "active"]
    if is_national and selected_scope == NATIONAL_SCOPE:
        scope_label = "Poziom krajowy · przegląd jednostek bezpośrednio podległych"
    else:
        scope_label = f"Poziom widoku: {overview_title}"
    st.markdown(f"**{scope_label}**")
    st.caption(f"Konto: {me.get('stanowisko', 'Użytkownik')} · jednostka konta: {units_by_id.get(own_unit_id, {}).get('nazwa', own_unit_id)}")
    real_tasks = [t for t in visible_scope_tasks if t.get("typ_zadania", "REAL") == "REAL"]
    completion = completion_percent(real_tasks)
    attention_tasks = [t for t in visible_scope_tasks if clamp_progress(t) < 1 and (t.get("status") is False or t.get("status") == 0)]

    tab_overview, tab_tasks, tab_plans, tab_map, tab_operational_analytics, tab_analytics, tab_hierarchy, tab_simulation = st.tabs(
        ["Obraz sytuacji", "Zadania", "Plany", "Mapa", "Analizy operacyjne", "Historia i scenariusze", "Hierarchia", "Symulacja"]
    )

    # Demonstration-only scenario: state is held in this Streamlit session and
    # deliberately does not mutate the operational database or activate real plans.
    with tab_simulation:
        st.markdown('<div class="eyebrow">Centrum symulacji · scenariusz demonstracyjny</div>', unsafe_allow_html=True)
        st.header("🌊 Powódź — przygotowanie i reagowanie")
        st.caption("Scenariusz pokazowy. Stan symulacji jest odzwierciedlany w zakładkach Plany, Zadania i Analizy operacyjne, ale nie zapisuje zmian w operacyjnej bazie danych.")
        sim_key = "flood_demo_elapsed_hours"
        if sim_key not in st.session_state:
            st.session_state[sim_key] = 0
        elapsed = int(st.session_state[sim_key])
        flood_hour = 6
        remaining = max(0, flood_hour - elapsed)
        flood_arrived = elapsed >= flood_hour
        prep_progress = min(100, round(elapsed / flood_hour * 100))
        real_progress = 0 if not flood_arrived else min(100, (elapsed - flood_hour + 1) * 20)
        clock_label = (f"T − {remaining:02d}:00" if not flood_arrived else f"T + {elapsed - flood_hour:02d}:00")

        controls = st.columns([1.25, 1, 1, 1.1])
        with controls[0]:
            if st.button("▶ Uruchom / +1 godz.", type="primary", use_container_width=True, key="flood-sim-next"):
                st.session_state[sim_key] = min(11, elapsed + 1)
                st.rerun()
        with controls[1]:
            if st.button("+3 godz.", use_container_width=True, key="flood-sim-fast"):
                st.session_state[sim_key] = min(11, elapsed + 3)
                st.rerun()
        with controls[2]:
            if st.button("Do nadejścia fali", use_container_width=True, key="flood-sim-arrival"):
                st.session_state[sim_key] = 6
                st.rerun()
        with controls[3]:
            if st.button("↺ Reset", use_container_width=True, key="flood-sim-reset"):
                st.session_state[sim_key] = 0
                st.rerun()

        if flood_arrived:
            st.error("🌊 FALA POWODZIOWA — zagrożenie aktywne. Uruchomiono działania operacyjne REAL.")
        else:
            st.info(f"⏳ Do nadejścia fali powodziowej: {remaining} godz. · trwa faza przygotowań.")

        top = st.columns(3)
        top[0].metric("Czas symulacji", clock_label)
        top[1].metric("Gotowość służb", f"{prep_progress}%", "na podstawie zadań PRZ")
        top[2].metric("Realizacja działań REAL", f"{real_progress}%", "aktywowane po nadejściu fali" if flood_arrived else "plany zaplanowane, jeszcze nieaktywne")

        st.subheader("Oś czasu zagrożenia")
        timeline_cols = st.columns(3)
        timeline_cols[0].markdown(("🟢 **Przygotowania**" if elapsed > 0 else "🔵 **Start przygotowań**") + "\n\n<small>T−06:00 do T−00:00</small>", unsafe_allow_html=True)
        timeline_cols[1].markdown(("🔴 **Powódź — zagrożenie aktywne**" if flood_arrived else "⚪ **Nadejście fali**") + "\n\n<small>T±00:00</small>", unsafe_allow_html=True)
        timeline_cols[2].markdown(("🟢 **Reagowanie operacyjne**" if real_progress > 0 else "⚪ **Działania REAL**") + "\n\n<small>Po aktywacji planów</small>", unsafe_allow_html=True)

        left_sim, right_sim = st.columns(2)
        with left_sim:
            st.subheader("Przygotowanie służb · PRZ")
            st.progress(prep_progress / 100, text=f"Realizacja zadań przygotowawczych: {prep_progress}%")
            prep_items = [
                ("Kontrola sprzętu i zasobów ratowniczych", min(100, max(0, round(elapsed / 3 * 100))),
                 "Komenda Państwowej Straży Pożarnej"),
                ("Przygotowanie punktów ewakuacji", min(100, max(0, round((elapsed - 1) / 3 * 100))),
                 "Administracja wojewódzka"),
                ("Zabezpieczenie wałów i newralgicznych odcinków", min(100, max(0, round((elapsed - 2) / 3 * 100))),
                 "Służby terenowe"),
            ]
            for label, value, owner in prep_items:
                with st.container(border=True):
                    st.markdown(f"**{label}**")
                    st.caption(owner + " · PRZ")
                    st.progress(value / 100, text=f"{value}%")
        with right_sim:
            st.subheader("Działania operacyjne · REAL")
            st.progress(real_progress / 100, text=f"Realizacja zadań REAL: {real_progress}%")
            real_items = [
                ("Ewakuacja mieszkańców z obszarów zagrożonych", max(0, min(100, real_progress)),
                 "Administracja lokalna"),
                ("Uruchomienie punktów pomocy i schronienia", max(0, min(100, real_progress - 10)),
                 "Zespół zarządzania kryzysowego"),
                ("Działania ratownicze i logistyczne", max(0, min(100, real_progress - 20)),
                 "Państwowa Straż Pożarna"),
            ]
            for label, value, owner in real_items:
                with st.container(border=True):
                    st.markdown(f"**{label}**")
                    st.caption(owner + (" · REAL · aktywne" if flood_arrived else " · REAL · zaplanowane"))
                    st.progress(value / 100, text=(f"{value}%" if flood_arrived else "Oczekuje na aktywację"))

        st.subheader("Dziennik zdarzeń symulacji")
        events = [
            (0, "T−06:00", "Rozpoczęcie scenariusza powodziowego", "info"),
            (1, "T−05:00", "Rozpoczęto kontrolę zasobów ratowniczych", "info"),
            (3, "T−03:00", "Przygotowanie punktów ewakuacji i zabezpieczenie infrastruktury", "info"),
            (5, "T−01:00", "Ostatnia faza przygotowań przed nadejściem fali", "warning"),
            (6, "T±00:00", "Nadeszła fala — aktywowano plan krajowy O oraz plany operacyjne PSP (PS/PSS/PSSS)", "critical"),
            (7, "T+01:00", "Rozwinięcie działań ewakuacyjnych i punktów pomocy", "info"),
            (9, "T+03:00", "Kontynuacja działań ratowniczych i logistycznych", "info"),
        ]
        visible_events = [event for event in events if event[0] <= elapsed]
        for _, event_time, event_text, severity in reversed(visible_events):
            icon = "🔴" if severity == "critical" else "🟠" if severity == "warning" else "🟢"
            st.markdown(f"{icon} **{event_time}** — {event_text}")

        if flood_arrived:
            st.success("Aktywne w tej sesji: plan krajowy O oraz plany PSP PS, PSS i PSSS. Przełącz konto na komendanta PSP, aby zobaczyć własne plany i zadania REAL po aktywacji.")
        st.caption("Tryb demonstracyjny: statusy i postęp są nakładką sesji. Reset przywraca stan początkowy; baza operacyjna nie jest modyfikowana.")

    with tab_overview:
        st.markdown('<div class="eyebrow">Sytuacja operacyjna</div>', unsafe_allow_html=True)
        st.header(overview_title)
        if is_national and selected_scope == NATIONAL_SCOPE:
            st.caption("Przegląd obejmuje wyłącznie jednostki bezpośrednio podległe. Szczegóły jednostek niższego szczebla nie są agregowane ani wyświetlane.")
        k1,k2,k3 = st.columns(3)
        k1.metric("Aktywne plany", len(active_plans))
        k2.metric("Wymagające uwagi", len(attention_tasks))
        k3.metric("Budżet jednostek", format_money(sum(float(u.get("budzet", 0) or 0) for u in visible_scope_units)))
        st.divider()
        left,right = st.columns([1.25,1])
        with left:
            st.subheader("Aktywne plany")
            if not active_plans: st.info("Brak aktywnych planów w wybranym zakresie.")
            for p in sorted(active_plans, key=lambda x: display_plan_name(x).casefold()):
                p_tasks = [t for t in visible_scope_tasks if str(t.get("id_planu")) == str(p.get("id_planu"))]
                p_pct = completion_percent([t for t in p_tasks if t.get("typ_zadania") == "REAL"])
                with st.container(border=True):
                    st.markdown(f"**{display_plan_name(p)}**")
                    st.caption(f"{plan_status(p)} · {op_status(p)} · {p.get('klauzula_tajnosci','—')}")
                    st.progress((p_pct or 0)/100, text=f"Realizacja własnych zadań REAL: {p_pct:.0f}%" if p_pct is not None else "Brak zadań REAL")
        with right:
            st.subheader("Zadania wymagające uwagi")
            if not attention_tasks: st.success("Brak niezakończonych zadań w wybranym zakresie.")
            for t in attention_tasks[:8]:
                p = plans_by_id.get(str(t.get("id_planu")), {})
                with st.container(border=True):
                    st.markdown(f"**{t.get('nazwa_zadania','Zadanie')}**")
                    st.caption(f"Plan: {display_plan_name(p)} · {task_status(t)} · {clamp_progress(t)*100:.0f}%")
        st.divider()
        st.subheader("Jednostki w zakresie")
        rows=[]
        # Show only the current user's direct reports as clickable drill-down targets.
        # The row statistics are calculated per unit and never aggregate deeper descendants.
        if selected_scope == NATIONAL_SCOPE:
            unit_cards = scope_direct_units
        else:
            unit_cards = scope_direct_units if scope_direct_units else visible_scope_units
        for u in unit_cards:
            uid_value = str(u.get("id"))
            unit_plan_ids = {str(pid) for pid in u.get("id_planow", [])}
            u_tasks = [t for t in tasks if task_belongs_to_unit(t, uid_value, unit_plan_ids)]
            val=completion_percent([t for t in u_tasks if t.get("typ_zadania")=="REAL"])
            rows.append({"ID": uid_value, "Jednostka":u.get("nazwa"),"Plany":sum(1 for pid in unit_plan_ids if pid in plans_by_id),"Zadania REAL":sum(1 for t in u_tasks if t.get("typ_zadania")=="REAL"),"Realizacja":f"{val:.0f}%" if val is not None else "—"})
        if rows:
            unit_cols = st.columns(min(3, len(rows)))
            for index, row in enumerate(rows):
                uid = row["ID"]
                with unit_cols[index % len(unit_cols)]:
                    with st.container(border=True):
                        st.markdown(f"**{row['Jednostka']}**")
                        st.caption(f"Plany: {row['Plany']} · zadania REAL: {row['Zadania REAL']} · realizacja: {row['Realizacja']}")
                        if uid:
                            st.button(
                                "Otwórz obraz sytuacji", key=f"open-unit-{uid}",
                                use_container_width=True, on_click=_select_scope, args=(uid,),
                            )
        else:
            st.info("Brak jednostek do pokazania.")

    with tab_tasks:
        task_views = st.tabs(["Rejestr zadań", "Dodaj zadanie"])
        with task_views[0]:
            st.header("Rejestr zadań")
            st.caption("Jedna tabela dla zadań widocznych w bieżącej perspektywie. Szczegóły i raportowanie są ograniczone uprawnieniami oraz własnością zadania.")
            all_scope_tasks = visible_scope_tasks
            f1, f2, f3 = st.columns([2, 1, 1])
            plan_filter_options = {"Wszystkie plany": "__all__"}
            for pid in sorted({str(t.get("id_planu")) for t in all_scope_tasks}):
                plan_obj = plans_by_id.get(pid, {})
                plan_filter_options[f"{display_plan_name(plan_obj)} · {pid}"] = pid
            selected_plan_filter_label = f1.selectbox("Filtruj według planu", list(plan_filter_options), key="task-plan-filter")
            selected_plan_filter = plan_filter_options[selected_plan_filter_label]
            search = f2.text_input("Szukaj zadania", placeholder="Nazwa zadania…", key="task-name-search")
            type_filter = f3.selectbox("Rodzaj", ["Wszystkie", "PRZ", "REAL"], key="task-type-filter")
            status_filter = st.selectbox("Status", ["Wszystkie", "Zaplanowane", "W toku", "Zakończone"], key="task-status-filter")
            filtered=[]
            for t in all_scope_tasks:
                p=plans_by_id.get(str(t.get("id_planu")), {})
                if selected_plan_filter != "__all__" and str(t.get("id_planu")) != selected_plan_filter: continue
                if type_filter != "Wszystkie" and t.get("typ_zadania") != type_filter: continue
                if status_filter != "Wszystkie" and task_status(t) != status_filter: continue
                if search and search.casefold() not in str(t.get("nazwa_zadania", "")).casefold(): continue
                filtered.append(t)
            filtered.sort(key=lambda t: (0 if t.get("typ_zadania", "REAL") == "REAL" else 1, display_plan_name(plans_by_id.get(str(t.get("id_planu")), {})).casefold(), str(t.get("nazwa_zadania", "")).casefold()))
            rows=[]
            for t in filtered:
                p=plans_by_id.get(str(t.get("id_planu")), {})
                owner=units_by_id.get(owner_by_plan.get(str(t.get("id_planu")), ""), {})
                rows.append({"Zadanie":t.get("nazwa_zadania"),"Plan":display_plan_name(p),"Jednostka":owner.get("nazwa","—"),"Typ":t.get("typ_zadania","REAL"),"Status":task_status(t),"Postęp":f"{clamp_progress(t)*100:.0f}%"})
            if rows:
                task_df = pd.DataFrame(rows)
                task_styler = task_df.style.apply(
                    lambda row: ["background-color: #fff2b3; color: #242424" if row.get("Typ") == "REAL" else "" for _ in row], axis=1
                )
                st.dataframe(task_styler, use_container_width=True, hide_index=True)
                st.caption("Zadania REAL są wyróżnione kolorem żółtym i sortowane przed zadaniami PRZ.")
            else:
                st.info("Brak zadań spełniających kryteria.")
            if filtered:
                detail_plan_options = {f"{display_plan_name(plans_by_id.get(pid, {}))} · {pid}": pid for pid in sorted({str(t.get("id_planu")) for t in filtered})}
                detail_plan_label = st.selectbox("Szczegóły zadania — wybierz plan", list(detail_plan_options), key="task-detail-plan")
                detail_plan_id = detail_plan_options[detail_plan_label]
                tasks_for_detail_plan = [t for t in filtered if str(t.get("id_planu")) == detail_plan_id]
                detail_task_options = {f"{t.get('nazwa_zadania','Zadanie')} · {t.get('id_zadania','')}": t for t in tasks_for_detail_plan}
                chosen_label = st.selectbox("Wybierz konkretne zadanie", list(detail_task_options), key=f"task-detail-item-{detail_plan_id}")
                task=detail_task_options[chosen_label]; p=plans_by_id.get(str(task.get("id_planu")), {})
                with st.container(border=True):
                    st.subheader(task.get("nazwa_zadania", "Zadanie"))
                    st.caption(f"Plan: {display_plan_name(p)} · jednostka odpowiedzialna: {units_by_id.get(owner_by_plan.get(str(task.get('id_planu')),''),{}).get('nazwa','—')}")
                    a,b,c=st.columns(3); a.metric("Rodzaj",task.get("typ_zadania","REAL")); b.metric("Status",task_status(task)); c.metric("Postęp",f"{clamp_progress(task)*100:.0f}%")
                    st.progress(clamp_progress(task))
                    if str(owner_by_plan.get(str(task.get("id_planu")),""))==own_unit_id and ((task.get("typ_zadania")=="REAL" and p.get("status_operacyjny")=="active") or (task.get("typ_zadania")=="PRZ" and p.get("status_planu")=="approved")) :
                        new_progress=st.slider("Zaktualizuj rzeczywisty postęp",0,100,int(clamp_progress(task)*100),key=f"task-progress-{task.get('id_planu')}-{task.get('id_zadania')}")
                        if st.button("Zapisz postęp",key=f"save-progress-{task.get('id_planu')}-{task.get('id_zadania')}"):
                            try: patch(f"/api/tasks/{task.get('id_planu')}/{task.get('id_zadania')}/progress",person_id,{"poziom_realizacji":new_progress/100}); st.success("Zapisano postęp."); st.rerun()
                            except Exception as exc: st.error(f"Nie udało się zapisać postępu: {exc}")
                    elif task.get("typ_zadania")=="REAL" and p.get("status_operacyjny")!="active": st.info("Zadanie REAL jest zaplanowane. Raportowanie postępu będzie dostępne po aktywacji planu.")
                    elif task.get("typ_zadania")=="PRZ" and p.get("status_planu")!="approved": st.info("Zadanie przygotowawcze można raportować po zatwierdzeniu planu.")
                    else: st.caption("Podgląd zadania. Edycja jest dostępna wyłącznie dla własnych zadań REAL w aktywnym planie.")

                    # Actual execution reporting: immutable report history + atomic progress update.
                    can_report = (
                        str(owner_by_plan.get(str(task.get("id_planu")), "")) == own_unit_id
                        and ((task.get("typ_zadania") == "REAL" and p.get("status_operacyjny") == "active")
                             or (task.get("typ_zadania") == "PRZ" and p.get("status_planu") == "approved"))
                    )
                    if can_report:
                        with st.expander("Złóż raport rzeczywistego wykonania", expanded=False):
                            with st.form(f"task-report-form-{task.get('id_planu')}-{task.get('id_zadania')}"):
                                report_progress = st.slider(
                                    "Stopień realizacji po raporcie", 0, 100,
                                    int(clamp_progress(task) * 100),
                                    key=f"report-progress-{task.get('id_planu')}-{task.get('id_zadania')}"
                                )
                                report_summary = st.text_area(
                                    "Wykonane czynności i uzyskane rezultaty *",
                                    placeholder="Opisz, co wykonano i jaki jest rezultat…", max_chars=5000
                                )
                                report_blockers = st.text_area(
                                    "Przeszkody / ryzyka", placeholder="Opcjonalnie", max_chars=3000
                                )
                                report_needs = st.text_area(
                                    "Potrzebne wsparcie / zasoby", placeholder="Opcjonalnie", max_chars=3000
                                )
                                report_eta = st.text_input(
                                    "Przewidywany termin zakończenia (RRRR-MM-DD)",
                                    placeholder="2026-10-20", max_chars=32
                                )
                                report_submitted = st.form_submit_button("Zapisz raport i zaktualizuj postęp", type="primary")
                            if report_submitted:
                                if len(report_summary.strip()) < 3:
                                    st.error("Opisz wykonane czynności (co najmniej 3 znaki).")
                                else:
                                    try:
                                        post(f"/api/tasks/{task.get('id_planu')}/{task.get('id_zadania')}/reports", person_id, {
                                            "poziom_realizacji": report_progress / 100,
                                            "wykonane_czynnosci": report_summary.strip(),
                                            "przeszkody": report_blockers.strip(),
                                            "potrzeby": report_needs.strip(),
                                            "przewidywany_termin": report_eta.strip() or None,
                                        })
                                        st.success("Raport zapisany. Postęp zadania został zaktualizowany.")
                                        st.rerun()
                                    except Exception as exc:
                                        st.error(f"Nie udało się zapisać raportu: {exc}")
                    try:
                        reports = get(f"/api/tasks/{task.get('id_planu')}/{task.get('id_zadania')}/reports", person_id)
                    except Exception as exc:
                        reports = []
                        st.warning(f"Nie udało się pobrać historii raportów: {exc}")
                    with st.expander(f"Historia raportów ({len(reports)})", expanded=bool(reports)):
                        if not reports:
                            st.caption("Brak zapisanych raportów wykonania.")
                        for report in reports:
                            st.markdown(f"**{report.get('created_at', '—')} · {report.get('author_name', 'Użytkownik')} · {float(report.get('poziom_realizacji', 0))*100:.0f}%**")
                            st.write(report.get("wykonane_czynnosci", "—"))
                            if report.get("przeszkody"):
                                st.caption(f"Przeszkody / ryzyka: {report['przeszkody']}")
                            if report.get("potrzeby"):
                                st.caption(f"Potrzebne wsparcie: {report['potrzeby']}")
                            if report.get("przewidywany_termin"):
                                st.caption(f"Przewidywany termin zakończenia: {report['przewidywany_termin']}")
                            st.divider()
                    st.write(f"**Ostatnia aktualizacja:** {task.get('data_aktualizacji','—')}")

        with task_views[1]:
            st.subheader("Dodaj zadanie do planu")
            st.caption("Zadanie jest przypisane do wybranego planu i automatycznie do jednostki będącej właścicielem planu. Nie edytujemy ani nie odtwarzamy istniejących zadań.")
            own_plans_for_tasks = [p for p in plans if owner_by_plan.get(str(p.get("id_planu"))) == own_unit_id]
            eligible_plans = [p for p in own_plans_for_tasks if p.get("status_planu") not in ("in_review",) and p.get("status_operacyjny") in ("prepared", None, "active")]
            if not eligible_plans:
                st.info("Brak własnych planów, do których można dodać zadanie.")
            else:
                plan_labels = {f"{display_plan_name(p)} · {p.get('id_planu')} · {plan_status(p)} · {op_status(p)}": p for p in eligible_plans}
                chosen_plan_label = st.selectbox("Plan, do którego przypisać zadanie", list(plan_labels), key="new-task-plan")
                chosen_plan = plan_labels[chosen_plan_label]
                is_plan_active = chosen_plan.get("status_operacyjny") == "active"
                task_type_options = ["REAL"] if is_plan_active else ["PRZ"]
                with st.form("create-task-form", clear_on_submit=True):
                    new_task_name = st.text_input("Nazwa zadania", placeholder="Np. Weryfikacja gotowości zasobów")
                    new_task_type = st.selectbox("Rodzaj zadania", task_type_options, format_func=lambda x: "Zadanie operacyjne (REAL)" if x == "REAL" else "Zadanie przygotowawcze (PRZ)")
                    create_task_submit = st.form_submit_button("Dodaj zadanie", type="primary")
                if is_plan_active:
                    st.caption("Plan jest aktywny — można dodać zadanie operacyjne REAL.")
                else:
                    st.caption("Plan nie jest aktywny operacyjnie — można dodać zadanie przygotowawcze PRZ. W zatwierdzonym planie postęp PRZ można raportować; zadania REAL są przeznaczone dla planu aktywnego.")
                if create_task_submit:
                    if len(new_task_name.strip()) < 3:
                        st.error("Nazwa zadania musi mieć co najmniej 3 znaki.")
                    else:
                        try:
                            created = post(f"/api/plans/{chosen_plan.get('id_planu')}/tasks", person_id, {"nazwa_zadania": new_task_name.strip(), "typ_zadania": new_task_type})
                            st.success(f"Dodano zadanie „{created.get('nazwa_zadania', new_task_name.strip())}” do planu {display_plan_name(chosen_plan)}.")
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Nie udało się dodać zadania: {exc}")

    with tab_plans:
        st.header("Plany i cykl planistyczny")
        st.caption("Od przygotowania planu i wymogów dla podległych jednostek po zatwierdzenie i aktywację operacyjną.")
        plan_tabs = st.tabs(["Plany i cykl planistyczny", "Utwórz / edytuj plan", "Wymogi i akceptacja"])

        # 1. Plan overview and lifecycle. REAL progress is deliberately hidden until activation.
        with plan_tabs[0]:
            if not visible_scope_plans_list:
                st.info("Brak planów w bieżącym zakresie.")
            for p in sorted(visible_scope_plans_list, key=lambda x: display_plan_name(x).casefold()):
                pid = str(p.get("id_planu"))
                p_tasks = [t for t in tasks if str(t.get("id_planu")) == pid]
                prep_tasks = [t for t in p_tasks if t.get("typ_zadania") == "PRZ"]
                real_tasks_for_plan = [t for t in p_tasks if t.get("typ_zadania") == "REAL"]
                prep = completion_percent(prep_tasks)
                is_active = p.get("status_operacyjny") == "active"
                with st.container(border=True):
                    if is_active:
                        st.markdown('<span class="active-plan-marker">active</span><span class="active-plan-badge">PLAN AKTYWNY OPERACYJNIE</span>', unsafe_allow_html=True)
                    left, right = st.columns([3, 1])
                    left.subheader(display_plan_name(p))
                    right.caption(plan_status(p))
                    left.caption(f"{op_status(p)} · klauzula: {p.get('klauzula_tajnosci', '—')}")
                    if is_active:
                        real = completion_percent(real_tasks_for_plan)
                        st.metric("Zadania zrealizowane REAL", f"{real:.0f}%" if real is not None else "Brak zadań REAL")
                        if real is not None:
                            st.progress(real / 100, text=f"Realizacja operacyjna: {real:.0f}%")
                    else:
                        c1, c2 = st.columns([1, 2])
                        c1.metric("Zadania przygotowawcze", len(prep_tasks))
                        c2.metric("Przygotowanie PRZ", f"{prep:.0f}%" if prep is not None else "Brak zadań PRZ")
                        if prep is not None:
                            if prep >= 100:
                                st.success(f"Przygotowanie zakończone · {prep:.0f}%")
                            elif prep >= 50:
                                st.warning(f"Przygotowanie w toku · {prep:.0f}%")
                            else:
                                st.error(f"Niski stopień przygotowania · {prep:.0f}%")
                            with st.expander("Postęp poszczególnych zadań przygotowawczych"):
                                for prep_task in prep_tasks:
                                    task_pct = clamp_progress(prep_task) * 100
                                    task_left, task_right = st.columns([4, 1])
                                    task_left.write(prep_task.get("nazwa_zadania", "Zadanie przygotowawcze"))
                                    if task_pct >= 100:
                                        task_right.success(f"{task_pct:.0f}%")
                                    elif task_pct >= 50:
                                        task_right.warning(f"{task_pct:.0f}%")
                                    else:
                                        task_right.error(f"{task_pct:.0f}%")
                        else:
                            st.caption("Plan nie zawiera zadań przygotowawczych.")
                    # Expand one level only: plans owned by the user's direct reports.
                    subordinate_plan_rows = [
                        child for child in plans
                        if str(child.get("id_planu_nadrzednego") or "") == pid
                        and owner_by_plan.get(str(child.get("id_planu"))) in scope_direct_ids
                    ]
                    if subordinate_plan_rows:
                        with st.expander("Realizacja planu przez jednostki bezpośrednio podległe"):
                            for child_plan in sorted(subordinate_plan_rows, key=lambda x: display_plan_name(x).casefold()):
                                child_pid = str(child_plan.get("id_planu"))
                                child_owner_id = owner_by_plan.get(child_pid, "")
                                child_owner_name = units_by_id.get(child_owner_id, {}).get("nazwa", "Jednostka")
                                child_tasks = [t for t in tasks if str(t.get("id_planu")) == child_pid and str(child_owner_id) in {str(x) for x in t.get("id_jednostek", [])}]
                                child_real_tasks = [t for t in child_tasks if t.get("typ_zadania") == "REAL"]
                                child_pct = completion_percent(child_real_tasks) if child_plan.get("status_operacyjny") == "active" else None
                                st.markdown(f"**{child_owner_name}** — {display_plan_name(child_plan)}")
                                approval_date = child_plan.get("data_zatwierdzeina") or child_plan.get("data_zatwierdzenia")
                                approval_label = str(approval_date)[:10] if approval_date else "data nieznana"
                                st.caption(f"{plan_status(child_plan)} · {approval_label}")
                                child_active = child_plan.get("status_operacyjny") == "active"
                                st.write(f"Stan: plan {'aktywny' if child_active else 'nieaktywny'}")
                                if child_active:
                                    completed = (sum(1 for task in child_real_tasks if clamp_progress(task) >= 1.0) / len(child_real_tasks) * 100) if child_real_tasks else None
                                    if completed is None:
                                        st.caption("Zadań zrealizowanych: brak zadań REAL")
                                    else:
                                        st.progress(completed / 100, text=f"Zadań zrealizowanych: {completed:.0f}%")
                                else:
                                    child_prep_tasks = [task for task in child_tasks if task.get("typ_zadania") == "PRZ"]
                                    prepared = (sum(1 for task in child_prep_tasks if clamp_progress(task) >= 1.0) / len(child_prep_tasks) * 100) if child_prep_tasks else None
                                    if prepared is None:
                                        st.caption("Wykonanych zadań przygotowawczych: brak zadań PRZ")
                                    else:
                                        st.progress(prepared / 100, text=f"Wykonanych zadań przygotowawczych: {prepared:.0f}%")
                    # Before activation REAL tasks are not shown as an operational progress metric.
                    if p.get("data_przegladu"):
                        try:
                            review_date = date.fromisoformat(str(p["data_przegladu"])[:10])
                            days = (review_date - date.today()).days
                            if days < 0:
                                st.warning(f"Termin przeglądu minął {abs(days)} dni temu — wymagany przegląd/aktualizacja.")
                            elif days <= 90:
                                st.warning(f"Zbliża się termin przeglądu: {review_date.isoformat()} ({days} dni).")
                            else:
                                st.caption(f"Kolejny przegląd: {review_date.isoformat()}")
                        except ValueError:
                            st.caption(f"Termin przeglądu: {p.get('data_przegladu')}")
                    else:
                        st.caption("Nie określono terminu kolejnego przeglądu w danych.")
                    if p.get("wymogi"):
                        with st.expander("Wymogi dla jednostek podrzędnych"):
                            for req in p["wymogi"]:
                                target = units_by_id.get(str(req.get("id_jednostki")), {}).get("nazwa", str(req.get("id_jednostki", "Jednostka")))
                                st.write(f"**{target}** — {req.get('opis', 'Wymóg planistyczny')} · termin: {req.get('termin', '—')} · status: {req.get('status', 'Oczekuje na plan')}")
                    if p.get("status_planu") in ("editing", "draft", "rejected") and owner_by_plan.get(pid) == own_unit_id:
                        if st.button("Edytuj projekt", key=f"edit-plan-{pid}"):
                            st.session_state["plan_editor_selection"] = pid
                            st.session_state["_force_plan_editor_selection"] = True
                            st.rerun()
                    if p.get("status_planu") in ("draft", "rejected") and owner_by_plan.get(pid) == own_unit_id:
                        if st.button("Przekaż do zatwierdzenia", key=f"submit-{pid}"):
                            try:
                                post(f"/api/plans/{pid}/submit", person_id)
                                st.success("Plan przekazano do zatwierdzenia.")
                                st.rerun()
                            except Exception as exc:
                                st.error(f"Nie udało się przekazać planu: {exc}")
                    directly_subordinate_unit_ids = {
                        str(unit.get("id")) for unit in units
                        if str(unit.get("id_jednostki_nadrzednej") or "") == own_unit_id
                    }
                    can_activate_from_scope = (
                        owner_by_plan.get(pid) == own_unit_id
                        or owner_by_plan.get(pid) in directly_subordinate_unit_ids
                    )
                    if p.get("status_planu") == "approved" and not is_active and can_activate_from_scope:
                        if st.button("Aktywuj plan i podplany", key=f"activate-{pid}", type="primary"):
                            try:
                                post(f"/api/plans/{pid}/activate", person_id)
                                st.success("Plan i dostępne podplany aktywowano.")
                                st.rerun()
                            except Exception as exc:
                                st.error(f"Nie udało się aktywować planu: {exc}")

        # 2. One editor for plan metadata, tasks, and subordinate requirements.
        with plan_tabs[1]:
            st.subheader("Opracowanie planu")
            st.caption("Opracowanie oznacza utworzenie nowego planu — również wtedy, gdy odpowiadasz na wymóg otrzymany od jednostki nadrzędnej. W takim przypadku wybierz właściwy plan nadrzędny; istniejący projekt wybierz z listy tylko wtedy, gdy chcesz kontynuować jego edycję. Wymogi dla jednostek podrzędnych definiujesz w tym samym formularzu.")
            editable_plans = [p for p in plans if owner_by_plan.get(str(p.get("id_planu"))) == own_unit_id and p.get("status_planu") in ("editing", "draft", "rejected")]
            edit_options = {"Nowy plan": None}
            edit_options.update({f"{display_plan_name(p)} · {p.get('id_planu')} · {plan_status(p)}": str(p.get("id_planu")) for p in editable_plans})
            wanted = st.session_state.get("plan_editor_selection")
            edit_labels = list(edit_options)
            default_label = next((label for label, pid in edit_options.items() if pid == wanted), "Nowy plan")
            force_editor_selection = st.session_state.pop("_force_plan_editor_selection", False)
            if "plan-editor-select" not in st.session_state or force_editor_selection:
                st.session_state["plan-editor-select"] = default_label
            selected_label = st.selectbox("Plan do opracowania", edit_labels, key="plan-editor-select")
            selected_plan_id = edit_options[selected_label]
            selected_plan = plans_by_id.get(str(selected_plan_id), {}) if selected_plan_id else {}
            is_edit = bool(selected_plan_id)
            editor_key = str(selected_plan_id or "new")
            editor_selection_changed = st.session_state.get("_last_plan_editor_key") != editor_key

            default_parent_options = {"— bez planu nadrzędnego —": None}
            own_parent_unit_id = str(units_by_id.get(own_unit_id, {}).get("id_jednostki_nadrzednej") or "")
            for plan in plans:
                plan_id_value = str(plan.get("id_planu"))
                plan_owner = owner_by_plan.get(plan_id_value)
                # Own plans, plans in the selected display scope, and plans owned by
                # the direct superior are eligible parent codes. No sibling unit's plans.
                if plan_owner == own_unit_id or plan_owner == own_parent_unit_id or plan_id_value in visible_scope_plans:
                    default_parent_options[f"{display_plan_name(plan)} · {plan_id_value}"] = plan_id_value
            for requirement_item in received_requirements:
                parent_id = str(requirement_item.get("id_planu_nadrzednego"))
                default_parent_options[f"{requirement_item.get('nazwa_planu_nadrzednego', 'Plan nadrzędny')} · wymóg"] = parent_id
            parent_labels = list(default_parent_options)
            desired_parent = st.session_state.get("child_parent_plan", selected_plan.get("id_planu_nadrzednego"))
            parent_index = next((i for i, label in enumerate(parent_labels) if default_parent_options[label] == desired_parent), 0)
            parent_widget_key = f"parent-plan-{editor_key}"
            force_parent_prefill = st.session_state.pop("_force_parent_prefill", False)
            if parent_widget_key not in st.session_state or editor_selection_changed or force_parent_prefill:
                st.session_state[parent_widget_key] = parent_labels[parent_index]
            st.session_state["_last_plan_editor_key"] = editor_key
            name_widget_key = f"plan-name-{editor_key}"
            force_child_prefill = st.session_state.pop("_force_child_prefill", False)
            if not is_edit and st.session_state.get("child_plan_title") and (name_widget_key not in st.session_state or force_child_prefill):
                st.session_state[name_widget_key] = st.session_state["child_plan_title"]

            child_units = direct_child_units(own_unit_id, units)
            child_by_id = {str(u.get("id")): u for u in child_units}
            existing_requirements = list(selected_plan.get("wymogi", []) or [])
            existing_target_ids = [str(r.get("id_jednostki")) for r in existing_requirements if str(r.get("id_jednostki")) in child_by_id]
            default_task_rows = [
                {"Nazwa zadania": t.get("nazwa_zadania", ""), "Typ": t.get("typ_zadania", "PRZ")}
                for t in tasks if is_edit and str(t.get("id_planu")) == str(selected_plan_id)
            ]
            if not default_task_rows:
                default_task_rows = [{"Nazwa zadania": "", "Typ": "PRZ"}]
            parent_label = st.selectbox("Plan nadrzędny", parent_labels, key=parent_widget_key, disabled=is_edit)
            parent_code = str(default_parent_options[parent_label] or "")
            if is_edit:
                plan_id_value = str(selected_plan.get("id_planu", ""))
                st.text_input("Kod planu", value=plan_id_value, disabled=True, key=f"plan-code-{editor_key}")
            else:
                suffix_key = f"plan-code-suffix-{editor_key}"
                suffix = st.text_input(
                    "Oznaczenie poziomu (jedna litera)", value=st.session_state.get(suffix_key, ""),
                    max_chars=1, placeholder="np. R, K lub E", key=suffix_key,
                    help="Kod zostanie utworzony automatycznie jako kod planu nadrzędnego + jedna wielka litera. Dla planu głównego wpisz jedną literę.",
                ).strip().upper()
                plan_id_value = f"{parent_code}{suffix}" if parent_code else suffix
                st.caption(f"Kod planu: **{plan_id_value or 'uzupełnij oznaczenie'}**")
            # Requirement fields are separate for each selected subordinate unit.
            st.markdown("**Wymogi dla jednostek podrzędnych**")
            if child_units:
                selected_children = st.multiselect(
                    "Jednostki zobowiązane do przygotowania planów",
                    options=[str(u["id"]) for u in child_units],
                    default=existing_target_ids if is_edit else [],
                    format_func=lambda uid: child_by_id.get(str(uid), {}).get("nazwa", str(uid)),
                    key=f"requirement-units-{editor_key}",
                )
                requirement_values = {}
                for child_id in selected_children:
                    existing_req = next((r for r in existing_requirements if str(r.get("id_jednostki")) == str(child_id)), {})
                    with st.container(border=True):
                        child_name = child_by_id.get(str(child_id), {}).get("nazwa", str(child_id))
                        req_desc = st.text_area(
                            f"Wymogi dla: {child_name}", value=str(existing_req.get("opis", "")),
                            placeholder="Wymagany zakres, elementy planu i procedury…",
                            key=f"requirement-description-{editor_key}-{child_id}",
                        )
                        req_default = date.today() + timedelta(days=30)
                        try:
                            if existing_req.get("termin"):
                                req_default = date.fromisoformat(str(existing_req["termin"])[:10])
                        except ValueError:
                            pass
                        req_deadline = st.date_input(
                            "Termin przygotowania planu", value=req_default,
                            key=f"requirement-deadline-{editor_key}-{child_id}",
                        )
                        requirement_values[str(child_id)] = {"opis": req_desc, "termin": req_deadline}
            else:
                selected_children, requirement_values = [], {}
                st.info("Ta jednostka nie ma bezpośrednio podległych jednostek w dostępnych danych.")

            with st.form(f"plan-editor-form-{editor_key}", clear_on_submit=False):
                st.markdown("**Informacje dodatkowe**")
                plan_name_value = st.text_input("Nazwa planu", value=str(selected_plan.get("nazwa_dokumentu", st.session_state.get("child_plan_title", ""))), placeholder="Np. Plan ochrony i reagowania na powódź…", key=name_widget_key)
                classification = st.selectbox("Klauzula tajności", CLASSIFICATIONS, index=CLASSIFICATIONS.index(selected_plan.get("klauzula_tajnosci", "jawne")) if selected_plan.get("klauzula_tajnosci", "jawne") in CLASSIFICATIONS else 0, key=f"classification-{editor_key}")
                review_default = date.today() + timedelta(days=730)
                try:
                    if selected_plan.get("data_przegladu"):
                        review_default = date.fromisoformat(str(selected_plan["data_przegladu"])[:10])
                except ValueError:
                    pass
                review_date = st.date_input("Termin kolejnego przeglądu", value=review_default, key=f"review-date-{editor_key}")
                comment_value = st.text_area("Cel / uwagi do planu", value=str(selected_plan.get("komentarz", "")), key=f"plan-comment-{editor_key}")
                st.markdown("**Zadania planu**")
                task_editor = st.data_editor(
                    pd.DataFrame(default_task_rows, columns=["Nazwa zadania", "Typ"]),
                    num_rows="dynamic", use_container_width=True, hide_index=True,
                    column_config={"Nazwa zadania": st.column_config.TextColumn("Nazwa zadania", required=False),
                                   "Typ": st.column_config.SelectboxColumn("Typ", options=["PRZ", "REAL"], required=True)},
                    key=f"task-editor-{editor_key}")
                st.divider()
                if is_edit and selected_plan.get("status_planu") == "editing":
                    save_draft = st.form_submit_button("Zapisz zmiany", type="secondary")
                    create_project = st.form_submit_button("Utwórz projekt planu", type="primary")
                elif is_edit:
                    save_draft = st.form_submit_button("Zapisz zmiany", type="secondary")
                    create_project = False
                else:
                    save_draft = st.form_submit_button("Zapisz wersję roboczą", type="secondary")
                    create_project = st.form_submit_button("Utwórz projekt planu", type="primary")

            if save_draft or create_project:
                clean_id = str(plan_id_value).strip()
                clean_name = str(plan_name_value).strip()
                task_records = []
                for i, row in task_editor.fillna("").iterrows():
                    task_name = str(row.get("Nazwa zadania", "")).strip()
                    if task_name:
                        task_records.append({"id_zadania": f"TASK-{i+1:03d}", "nazwa_zadania": task_name, "typ_zadania": "REAL" if row.get("Typ") == "REAL" else "PRZ"})
                requirements_payload = []
                requirements_error = False
                for child_id in selected_children:
                    req_values = requirement_values.get(str(child_id), {})
                    description = str(req_values.get("opis", "")).strip()
                    if not description:
                        requirements_error = True
                        continue
                    old = next((r for r in existing_requirements if str(r.get("id_jednostki")) == str(child_id)), {})
                    requirements_payload.append({
                        "id_jednostki": str(child_id), "opis": description,
                        "termin": req_values["termin"].isoformat(), "status": old.get("status", "Oczekuje na plan"),
                        **({"id_planu_podrzednego": old["id_planu_podrzednego"]} if old.get("id_planu_podrzednego") else {})
                    })
                payload = {
                    "id_planu": clean_id, "nazwa_dokumentu": clean_name,
                    "sporzadzil": f"{me.get('imie','')} {me.get('nazwisko','')}".strip(),
                    "id_jednostki_wlasciciela": own_unit_id,
                    "id_planu_nadrzednego": default_parent_options[parent_label],
                    "klauzula_tajnosci": classification, "data_przegladu": review_date.isoformat(),
                    "komentarz": comment_value, "zadania": task_records, "wymogi": requirements_payload,
                    "zapis_roboczy": bool(save_draft),
                }
                if requirements_error:
                    st.error("Uzupełnij opis wymogów dla wybranych jednostek albo usuń ich zaznaczenie.")
                elif len(clean_name) < 3:
                    st.error("Podaj nazwę planu.")
                elif not clean_id or len(clean_id) > 64 or not clean_id.isalpha() or not clean_id.isupper() or (parent_code and (not clean_id.startswith(parent_code) or len(clean_id) != len(parent_code) + 1)) or (not parent_code and len(clean_id) != 1):
                    st.error("Kod musi być tworzony hierarchicznie: kod planu nadrzędnego + dokładnie jedna wielka litera. Plan główny ma jednoliterowy kod.")
                else:
                    try:
                        if is_edit:
                            put(f"/api/plans/{clean_id}", person_id, payload)
                            st.session_state["plan_editor_selection"] = clean_id
                            st.session_state["_force_plan_editor_selection"] = True
                            st.success("Zapisano zmiany w projekcie planu." if not create_project else "Utworzono projekt planu. Możesz go przekazać do zatwierdzenia, gdy będzie gotowy.")
                        else:
                            post("/api/plans", person_id, payload)
                            st.session_state["plan_editor_selection"] = clean_id
                            st.session_state["_force_plan_editor_selection"] = True
                            st.success("Zapisano wersję roboczą planu w źródle danych. Wybierz ją ponownie, aby kontynuować edycję i później utworzyć projekt planu." if save_draft else "Utworzono projekt planu wraz z zadaniami i wymogami dla wybranych jednostek.")
                        st.session_state.pop("child_parent_plan", None)
                        st.session_state.pop("child_plan_title", None)
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Nie udało się zapisać planu: {exc}")

        # 3. Requirements for the current unit and all directly subordinate plans for review.
        with plan_tabs[2]:
            st.subheader("Wymogi otrzymane przez tę jednostkę")
            if received_requirements:
                for item in received_requirements:
                    req = item.get("wymog", {})
                    with st.container(border=True):
                        st.markdown(f"**{item.get('nazwa_planu_nadrzednego', 'Plan nadrzędny')}**")
                        st.write(req.get("opis", "Wymóg planistyczny"))
                        st.caption(f"Termin: {req.get('termin', '—')} · status: {req.get('status', 'Oczekuje na plan')}")
                        if st.button("Przygotuj plan podrzędny", key=f"child-create-{item.get('id_planu_nadrzednego')}-{req.get('id_jednostki')}"):
                            st.session_state["child_parent_plan"] = str(item.get("id_planu_nadrzednego"))
                            st.session_state["child_plan_title"] = f"Plan podrzędny — {item.get('nazwa_planu_nadrzednego', '')}"
                            st.session_state["plan_editor_selection"] = None
                            st.session_state["_force_plan_editor_selection"] = True
                            st.session_state["_force_parent_prefill"] = True
                            st.session_state["_force_child_prefill"] = True
                            st.success("Ustawiono plan nadrzędny. Przejdź do „Utwórz / edytuj plan”, aby uzupełnić plan i zapisać go wraz z wymogami.")
            else:
                st.info("Brak wymogów planistycznych skierowanych bezpośrednio do tej jednostki.")

            st.divider()
            st.subheader("Plany jednostek bezpośrednio podległych")
            direct_ids_for_review = {str(u["id"]) for u in direct_units}
            child_plans = [p for p in plans if owner_by_plan.get(str(p.get("id_planu"))) in direct_ids_for_review]
            child_plans.sort(key=lambda p: (plan_status(p), display_plan_name(p).casefold()))
            if not child_plans:
                st.info("Brak planów jednostek bezpośrednio podległych w dostępnym zakresie.")
            for p in child_plans:
                pid = str(p.get("id_planu"))
                owner_name = units_by_id.get(owner_by_plan.get(pid, ""), {}).get("nazwa", "Jednostka")
                with st.container(border=True):
                    st.markdown(f"**{display_plan_name(p)}**")
                    st.caption(f"Jednostka: {owner_name} · {plan_status(p)} · {op_status(p)} · klauzula: {p.get('klauzula_tajnosci', '—')}")
                    if p.get("status_planu") == "in_review":
                        if st.button("Zatwierdź plan", key=f"approve-{pid}", type="primary"):
                            try:
                                post(f"/api/plans/{pid}/approve", person_id)
                                st.success("Plan zatwierdzono. Zadania przygotowawcze mogą być realizowane zgodnie z cyklem planistycznym.")
                                st.rerun()
                            except Exception as exc:
                                st.error(f"Nie udało się zatwierdzić planu: {exc}")
                    elif p.get("status_planu") == "draft":
                        st.caption("Projekt planu — nie został jeszcze przekazany do zatwierdzenia.")
                    elif p.get("status_planu") == "approved":
                        st.caption("Plan zatwierdzony. Aktywacja operacyjna pozostaje odrębnym etapem.")

    with tab_map:
        st.header("Mapa administracyjna")
        st.caption("Mapa wykorzystuje współrzędne tylko wtedy, gdy są dostępne w danych. Nie generujemy fikcyjnych lokalizacji zadań.")
        map_obj=folium.Map(location=RADOM_CENTER,zoom_start=6,tiles="CartoDB positron")
        plotted=0
        for u in visible_scope_units:
            lat=u.get("latitude",u.get("lat")); lon=u.get("longitude",u.get("lon",u.get("lng")))
            try:
                if lat is None or lon is None: continue
                folium.Marker([float(lat),float(lon)],tooltip=u.get("nazwa","Jednostka"),popup=u.get("nazwa","Jednostka")).add_to(map_obj); plotted+=1
            except (TypeError,ValueError): continue
        st_folium(map_obj,use_container_width=True,height=520,key="pro-rp-map")
        if not plotted: st.info("W aktualnym modelu danych nie ma współrzędnych geograficznych jednostek ani zadań. Mapa pokazuje podkład orientacyjny; nie przedstawia fikcyjnych markerów. Integrację z granicami administracyjnymi i geolokalizacją można włączyć po udostępnieniu tych danych przez warstwę Data.")
        else: st.caption(f"Liczba jednostek z dostępną lokalizacją: {plotted}")

    with tab_operational_analytics:
        from app.analytics_ui import (
            leaf_tasks, top_level_tasks, task_status_band, estimate_task_duration, days_until,
            unit_metrics, build_unit_task_rows,
        )
        st.header("Analizy realizacji zadań")
        st.caption("Zakres danych jest ograniczony przez Access do planów, jednostek i zadań widocznych dla wybranego konta. Analiza nie rozszerza uprawnień użytkownika.")

        # The national account can inspect the full hierarchy returned by Access.
        # Unit accounts see only their own authorized subtree and tasks returned by Access.
        all_visible_units = list(units)
        all_visible_plans = list(plans)
        all_visible_tasks = list(tasks)
        unit_map = {str(u.get("id")): u for u in all_visible_units}
        plan_map = {str(p.get("id_planu")): p for p in all_visible_plans}
        plan_owner = {str(pid): str(u.get("id")) for u in all_visible_units for pid in (u.get("id_planow") or [])}

        def descendants_in_scope(root_id):
            root_id = str(root_id)
            found, seen = [], {root_id}
            changed = True
            while changed:
                changed = False
                for candidate in all_visible_units:
                    cid = str(candidate.get("id"))
                    parent = str(candidate.get("id_jednostki_nadrzednej") or "")
                    if cid not in seen and parent in seen:
                        seen.add(cid); found.append(candidate); changed = True
            return found

        if is_national and selected_scope == NATIONAL_SCOPE:
            scope_units = all_visible_units
            scope_label = "Zakres krajowy — wszystkie jednostki dostępne dla konta"
        else:
            root_id = str(selected_scope if is_national else own_unit_id)
            root_unit = unit_map.get(root_id)
            scope_units = ([root_unit] if root_unit else []) + descendants_in_scope(root_id)
            scope_label = root_unit.get("nazwa", "Zakres jednostki") if root_unit else "Zakres jednostki"
        scope_ids = {str(u.get("id")) for u in scope_units}
        scope_plan_ids = {str(pid) for u in scope_units for pid in (u.get("id_planow") or [])}
        scope_tasks = []
        for task in all_visible_tasks:
            pid = str(task.get("id_planu", ""))
            if pid not in plan_map:
                continue
            assigned_ids = {str(x) for x in (task.get("id_jednostek") or [])}
            owner_id = plan_owner.get(pid, "")
            if (assigned_ids & scope_ids) or (not assigned_ids and owner_id in scope_ids):
                scope_tasks.append(task)
        # Count only terminal tasks in a hierarchy, so parent tasks with children do not double-count.
        analyzed_tasks = leaf_tasks(scope_tasks)
        st.markdown(f"**Zakres:** {scope_label} · **Zadań na najniższym poziomie:** {len(analyzed_tasks)} · **Jednostek:** {len(scope_units)}")
        if sim_elapsed > 0:
            if is_national:
                if sim_flood_arrived:
                    st.info("**Wniosek dla premiera:** plan krajowy i plany operacyjne zostały aktywowane. Warto monitorować nierozpoczęte zadania REAL w jednostkach podległych i kierować wsparcie tam, gdzie postęp jest najniższy.")
                else:
                    st.info("**Wniosek dla premiera:** przed nadejściem fali należy dopilnować terminowego zakończenia przygotowań PRZ oraz wskazać jednostki, które wymagają dodatkowych zasobów.")
            elif person_id == "demo-kgpsp":
                if sim_flood_arrived:
                    st.info("**Wniosek dla komendanta PSP:** plany PSP są aktywne. Priorytetem jest raportowanie postępu zadań REAL, identyfikacja braków zasobowych i przesuwanie sił do zadań o najwyższym ryzyku opóźnienia.")
                else:
                    st.info("**Wniosek dla komendanta PSP:** skoncentruj przygotowania na zadaniach PRZ z najniższym postępem i sprawdź gotowość zasobów przed aktywacją działań REAL.")
        if not analyzed_tasks:
            st.info("W zakresie widocznym dla tego konta nie ma zadań do analizy.")
        else:
            import json as _json
            # 1. Task status distribution, exclusive bands: each leaf task counts once.
            st.subheader("1. Struktura realizacji zadań")
            bands = ["Nierozpoczęte", "Rozpoczęte: 0–25%", "Realizacja: 25–50%", "Realizacja: 50–75%", "Realizacja: 75–99,9%", "Zakończone"]
            colors = ["#F59E0B", "#A7F3D0", "#6EE7B7", "#34D399", "#059669", "#2563EB"]
            counts = {band: 0 for band in bands}
            for task in analyzed_tasks:
                counts[task_status_band(task)] += 1
            chart_data = [{"status": band, "liczba": counts[band]} for band in bands if counts[band] > 0]
            c1, c2 = st.columns([1.2, 1])
            with c1:
                st.vega_lite_chart(chart_data, {
                    "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                    "description": "Udział zadań na najniższym poziomie hierarchii według postępu.",
                    "mark": {"type": "arc", "innerRadius": 48, "stroke": "#ffffff", "strokeWidth": 1},
                    "encoding": {
                        "theta": {"field": "liczba", "type": "quantitative"},
                        "color": {"field": "status", "type": "nominal", "scale": {"domain": bands, "range": colors}, "legend": {"title": "Status realizacji", "orient": "right"}},
                        "tooltip": [{"field": "status", "type": "nominal", "title": "Status"}, {"field": "liczba", "type": "quantitative", "title": "Liczba zadań"}]
                    }
                }, use_container_width=True)
            with c2:
                st.dataframe(pd.DataFrame([{"Status": b, "Liczba zadań": counts[b], "Udział (%)": round(100*counts[b]/len(analyzed_tasks), 2)} for b in bands]), use_container_width=True, hide_index=True)
                st.caption("Zadanie nadrzędne jest pomijane w podsumowaniu, jeśli ma podzadania. Każde zadanie końcowe liczy się tylko raz.")

            # 2. Time, due date, duration prediction and delay risk.
            st.subheader("2. Czas realizacji i ryzyko terminu")
            st.caption("Tabela pokazuje najwyższy widoczny poziom zadania, żeby nie dublować zadania nadrzędnego i podzadań. Prognoza wykorzystuje tempo postępu od utworzenia zadania. Jeśli w danych brakuje daty lub terminu, UI nie zgaduje wartości.")
            unit_names = {str(u.get("id")): u.get("nazwa", str(u.get("id"))) for u in scope_units}
            # For the time table show the highest visible level; leaf-only tasks are used for all aggregates.
            duration_tasks = top_level_tasks(scope_tasks)
            task_rows = build_unit_task_rows(duration_tasks, plan_map, unit_names, owner_by_plan=plan_owner)
            task_df = pd.DataFrame(task_rows)
            def highlight_delay(row):
                status = row.get("Opóźnienie")
                color = "background-color: #fee2e2; color: #991b1b" if status == "Opóźnione" else ("background-color: #ffedd5; color: #9a3412" if status == "Potencjalne" else "")
                return [color if col == "Opóźnienie" else "" for col in row.index]
            st.dataframe(task_df.style.apply(highlight_delay, axis=1).format(precision=2, na_rep="—"), use_container_width=True, hide_index=True, column_config={
                "Opóźnienie": st.column_config.TextColumn("Opóźnienie", help="Brak / Potencjalne / Opóźnione. Ocena terminowości wymaga terminu końcowego w danych."),
                "Termin realizacji": st.column_config.TextColumn("Termin realizacji"),
                "Prognoza: pozostało (dni)": st.column_config.NumberColumn("Prognoza: pozostało (dni)", format="%.1f"),
            })

            # 3. Unit capacity and efficiency, only for units in this user's authorized scope.
            st.subheader("3. Możliwości jednostek i obciążenie")
            unit_rows = unit_metrics(scope_units, analyzed_tasks, plan_owner)
            if unit_rows:
                unit_df = pd.DataFrame(unit_rows).drop(columns=[c for c in ["_unit_id", "_risk_score", "_per_person"] if c in pd.DataFrame(unit_rows).columns])
                def highlight_unit_risk(row):
                    styles = [""] * len(row)
                    if row.get("Ryzyko przeciążenia") == "Wysokie":
                        styles = ["background-color: #fee2e2; color: #991b1b"] * len(row)
                    elif row.get("Ryzyko przeciążenia") == "Podwyższone":
                        styles = ["background-color: #ffedd5; color: #9a3412"] * len(row)
                    elif row.get("Wydajność (0–100)") is not None and row.get("Wydajność (0–100)") < 30:
                        styles = ["background-color: #fee2e2; color: #991b1b"] * len(row)
                    return styles
                st.dataframe(unit_df.style.apply(highlight_unit_risk, axis=1).format(precision=2, na_rep="—"), use_container_width=True, hide_index=True, column_config={
                    "Wydajność (0–100)": st.column_config.ProgressColumn("Wydajność (0–100)", min_value=0, max_value=100, format="%.2f", help="Wynik porównawczy łączący tempo, postęp i obciążenie zadaniami na osobę."),
                    "Ryzyko przeciążenia": st.column_config.TextColumn("Ryzyko przeciążenia"),
                })
                chart_cols = st.columns([1.4, 1])
                with chart_cols[0]:
                    st.markdown("**Postęp i wydajność jednostek**")
                    st.bar_chart(pd.DataFrame(unit_rows).set_index("Jednostka")[["Średni postęp (%)", "Wydajność (0–100)"]], use_container_width=True)
                with chart_cols[1]:
                    st.markdown("**Zadania na pracownika**")
                    st.bar_chart(pd.DataFrame(unit_rows).set_index("Jednostka")[["Zadania / osoba"]].fillna(0), use_container_width=True)
                valid_corr = pd.DataFrame(unit_rows)[["Personel", "Średni postęp (%)", "Zadania / osoba"]].dropna()
                if len(valid_corr) >= 3:
                    corr = valid_corr.corr(numeric_only=True).loc["Personel", "Średni postęp (%)"]
                    st.metric("Korelacja: personel ↔ postęp", f"{corr:.2f}", help="Korelacja Pearsona na poziomie jednostek widocznych w wybranym zakresie; nie oznacza przyczynowości.")
                st.caption("Wydajność jest względnym wskaźnikiem porównawczym w obrębie aktualnie widocznego zakresu. Niski wynik oznaczono na czerwono, a wysokie ryzyko przeciążenia na czerwono lub pomarańczowo. To heurystyka, nie miara jakości pracy.")

            with st.expander("Ograniczenia i jakość danych"):
                st.write("- Terminy realizacji w danych demonstracyjnych zostały wygenerowane sztucznie. Nie są to oficjalne terminy operacyjne.")
                st.write("- Prognoza czasu pozostałego jest ekstrapolacją dotychczasowego tempa, a nie gwarancją daty ukończenia.")
                st.write("- Wskaźniki kadrowe i efektywnościowe są heurystykami, a nie oceną jakości pracy jednostek.")
                st.write("- Wszystkie agregacje wykorzystują tylko dane zwrócone przez API po kontroli dostępu.")


    with tab_analytics:
        st.header("Analityk — historia i scenariusze postępu")
        st.caption(
            "Oddzielny moduł analityczny. Żądania przechodzą przez Presentation API i Access; "
            "dane historyczne pochodzą z demonstracyjnego arkusza Excel, a nie z bieżących zadań operacyjnych."
        )
        if not is_national:
            st.info(
                "Ten demonstrator analityki historycznej nie zawiera mapowania zadań na jednostki. "
                "Z tego powodu zagregowane wyniki globalne są dostępne wyłącznie w perspektywie krajowej "
                "(Premier), aby nie ujawniać danych spoza zakresu jednostki."
            )
        else:
            try:
                snapshots_payload = get("/api/analytics/history/snapshots", person_id)
                snapshots = snapshots_payload.get("snapshots", [])
                if not snapshots:
                    st.warning("Brak snapshotów historycznych. Sprawdź inicjalizację serwisu analytics-history.")
                else:
                    snapshot_ids = [str(x["snapshot_id"]) for x in snapshots]
                    selected_snapshot = st.selectbox(
                        "Snapshot do podsumowania", snapshot_ids,
                        index=snapshot_ids.index("D+2") if "D+2" in snapshot_ids else len(snapshot_ids)-1,
                        key="analytics_snapshot",
                    )
                    summary = get(
                        f"/api/analytics/history/summary?snapshot_id={quote(selected_snapshot, safe="")}",
                        person_id,
                    )
                    k1, k2, k3, k4 = st.columns(4)
                    k1.metric("Zadania w próbce", summary.get("tasks", 0))
                    k2.metric("Średni postęp", f"{float(summary.get('mean_progress', 0))*100:.1f}%")
                    k3.metric("Zakończone", summary.get("completed_tasks", 0))
                    k4.metric("Niezakończone", summary.get("incomplete_tasks", 0))
                    st.caption(summary.get("data_note", "Dane demonstracyjne."))

                    by_type = summary.get("by_type", {})
                    if by_type:
                        st.subheader("Postęp według typu zadania")
                        type_rows = [
                            {"Typ": typ, "Liczba zadań": val.get("tasks", 0),
                             "Średni postęp (%)": round(float(val.get("mean_progress", 0))*100, 1),
                             "Zakończone": val.get("completed_tasks", 0)}
                            for typ, val in sorted(by_type.items())
                        ]
                        st.dataframe(pd.DataFrame(type_rows), use_container_width=True, hide_index=True)
                        st.bar_chart(pd.DataFrame(type_rows).set_index("Typ")[["Średni postęp (%)"]])

                    st.divider()
                    st.subheader("Zmiany między snapshotami")
                    c1, c2 = st.columns(2)
                    from_snapshot = c1.selectbox("Od", snapshot_ids, index=0, key="analytics_from")
                    to_snapshot = c2.selectbox(
                        "Do", snapshot_ids,
                        index=snapshot_ids.index("D+2") if "D+2" in snapshot_ids else len(snapshot_ids)-1,
                        key="analytics_to",
                    )
                    if from_snapshot == to_snapshot:
                        st.info("Wybierz dwa różne snapshoty, aby porównać zmianę.")
                    else:
                        changes = get(
                            f"/api/analytics/history/changes?from_snapshot={quote(from_snapshot, safe="")}&to_snapshot={quote(to_snapshot, safe="")}&limit=5000",
                            person_id,
                        )
                        change_rows = changes.get("changes", [])
                        st.metric("Porównane zadania", changes.get("count", len(change_rows)))
                        if change_rows:
                            change_df = pd.DataFrame([{
                                "ID zadania": x.get("task_id"),
                                "Typ": x.get("task_type"),
                                "Postęp przed (%)": round(float(x.get("progress_before", 0))*100, 1),
                                "Postęp po (%)": round(float(x.get("progress_after", 0))*100, 1),
                                "Zmiana (p.p.)": x.get("change_pp", 0),
                                "Zmiana względna (%)": x.get("relative_change_pct"),
                            } for x in change_rows])
                            st.dataframe(change_df, use_container_width=True, hide_index=True)
                        else:
                            st.info("Brak porównywalnych rekordów.")

                    st.divider()
                    st.subheader("Scenariusz postępu")
                    st.warning(
                        "To ilustracyjna ekstrapolacja liniowa oparta na dwóch snapshotach oddalonych o dwa dni. "
                        "Nie jest zwalidowaną prognozą i nie powinna służyć jako samodzielna podstawa decyzji."
                    )
                    fc1, fc2 = st.columns(2)
                    base_snapshot = fc1.selectbox(
                        "Snapshot bazowy", snapshot_ids,
                        index=snapshot_ids.index("D+2") if "D+2" in snapshot_ids else len(snapshot_ids)-1,
                        key="analytics_forecast_base",
                    )
                    days_ahead = fc2.number_input("Horyzont (dni)", min_value=1, max_value=30, value=2, step=1)
                    if st.button("Uruchom scenariusz", type="primary", key="run_analytics_forecast"):
                        result = post(
                            "/api/analytics/simulations/progress", person_id,
                            {"base_snapshot_id": base_snapshot, "days_ahead": int(days_ahead)},
                        )
                        st.session_state["analytics_last_forecast"] = result
                    forecast = st.session_state.get("analytics_last_forecast")
                    if forecast:
                        st.caption(
                            f"Metoda: {forecast.get('method')} · liczba wyników: {forecast.get('results_count', 0)}"
                        )
                        forecast_rows = [{
                            "ID zadania": x.get("task_id"), "Typ": x.get("task_type"),
                            "Postęp bazowy (%)": round(float(x.get("base_progress", 0))*100, 1),
                            "Postęp scenariusza (%)": round(float(x.get("forecast_progress", 0))*100, 1),
                            "Zmiana (p.p.)": x.get("forecast_change_pp", 0),
                        } for x in forecast.get("results", [])]
                        if forecast_rows:
                            st.dataframe(pd.DataFrame(forecast_rows), use_container_width=True, hide_index=True)
                        st.caption(forecast.get("warning", ""))
            except Exception as exc:
                st.error(f"Nie udało się wykonać analizy przez warstwę dostępową: {exc}")
                st.caption("Sprawdź serwisy presentation, access oraz analytics-history.")

    with tab_hierarchy:
        st.header("Hierarchia jednostek")
        st.caption("Bieżąca jednostka i maksymalnie dwa poziomy podległości. Kliknięcie „Otwórz” przełącza zakres analizy na wybraną jednostkę; tożsamość i uprawnienia konta pozostają bez zmian.")
        root_id = own_unit_id if selected_scope == NATIONAL_SCOPE else str(selected_scope)
        root_unit = units_by_id.get(root_id)
        if root_unit:
            st.markdown(f"### {root_unit.get('nazwa', root_id)}")
            st.caption("Bieżący węzeł hierarchii")
            level_one = sorted(direct_child_units(root_id, units), key=lambda u: u.get("nazwa", ""))
            if not level_one:
                st.info("Brak jednostek bezpośrednio podległych.")
            for child in level_one:
                child_id = str(child.get("id"))
                with st.container(border=True):
                    col_name, col_action = st.columns([4, 1])
                    col_name.markdown(f"**{child.get('nazwa', child_id)}**")
                    col_name.caption("Poziom 1")
                    col_action.button("Otwórz", key=f"hierarchy-tab-{root_id}-{child_id}", use_container_width=True, on_click=_select_scope, args=(child_id,))
                    grandchildren = sorted(direct_child_units(child_id, units), key=lambda u: u.get("nazwa", ""))
                    for grandchild in grandchildren:
                        grandchild_id = str(grandchild.get("id"))
                        subcol, subaction = st.columns([4, 1])
                        subcol.write(f"↳ {grandchild.get('nazwa', grandchild_id)}")
                        subcol.caption("Poziom 2")
                        subaction.button("Otwórz", key=f"hierarchy-tab-{child_id}-{grandchild_id}", use_container_width=True, on_click=_select_scope, args=(grandchild_id,))
        else:
            st.warning("Nie udało się ustalić bieżącego węzła hierarchii.")

if __name__ == "__main__": main()
