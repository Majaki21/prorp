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

from app.view_helpers import direct_child_units, task_belongs_to_unit, task_belongs_to_units, task_status, display_plan_name, completion_percent, format_money

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


def main():
    st.set_page_config(page_title="PRO RP | Obraz sytuacji", page_icon="🛡️", layout="wide")
    st.markdown("""<style>
    .block-container{padding-top:1.15rem;padding-bottom:2rem;max-width:1600px}
    div[data-testid="stMetric"]{background:rgba(120,130,150,.07);padding:.75rem 1rem;border-radius:.8rem;border:1px solid rgba(120,130,150,.17)}
    .eyebrow{text-transform:uppercase;letter-spacing:.09em;font-size:.72rem;font-weight:700;opacity:.68}
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

    plans_by_id = {str(p.get("id_planu")): p for p in plans}
    units_by_id = {str(u.get("id")): u for u in units}
    owner_by_plan = {str(pid): str(u["id"]) for u in units for pid in u.get("id_planow", [])}
    own_unit_id = str(me.get("id_jednostki", ""))
    direct_units = direct_child_units(own_unit_id, units)
    direct_ids = {str(u["id"]) for u in direct_units}
    is_national = person_id == "demo-premier"
    with st.sidebar:
        if is_national:
            scope_options = [NATIONAL_SCOPE] + [str(u["id"]) for u in sorted(direct_units, key=lambda x: x.get("nazwa", ""))]
            selected_scope = st.selectbox("Zakres analizy", scope_options, format_func=lambda x: "Przegląd krajowy · jednostki bezpośrednio podległe" if x == NATIONAL_SCOPE else units_by_id.get(x, {}).get("nazwa", "Jednostka"))
        else:
            selected_scope = own_unit_id
            st.caption("Zakres szczegółowy ograniczony do jednostki użytkownika.")

    if is_national and selected_scope == NATIONAL_SCOPE:
        visible_scope_units = direct_units
        visible_scope_ids = direct_ids
        # Include the national-level user's own plans in the plan lifecycle UI,
        # while task aggregates remain restricted to directly subordinate units.
        own_plans_for_scope = {str(pid) for pid in units_by_id.get(own_unit_id, {}).get("id_planow", [])}
        visible_scope_plans = own_plans_for_scope | {str(pid) for u in direct_units for pid in u.get("id_planow", [])}
        visible_scope_tasks = [t for t in tasks if task_belongs_to_units(t, visible_scope_ids, visible_scope_plans, owner_by_plan)]
        overview_title = "Obraz sytuacji — poziom krajowy"
    else:
        target_unit_id = selected_scope if is_national else own_unit_id
        visible_scope_units = [units_by_id[target_unit_id]] if target_unit_id in units_by_id else []
        visible_scope_ids = {target_unit_id}
        visible_scope_plans = {str(pid) for u in visible_scope_units for pid in u.get("id_planow", [])}
        visible_scope_tasks = [t for t in tasks if task_belongs_to_unit(t, target_unit_id, visible_scope_plans)]
        overview_title = visible_scope_units[0].get("nazwa", "Obraz sytuacji") if visible_scope_units else "Obraz sytuacji"
    visible_scope_plans_list = [plans_by_id[pid] for pid in visible_scope_plans if pid in plans_by_id]
    active_plans = [p for p in visible_scope_plans_list if p.get("status_operacyjny") == "active"]
    real_tasks = [t for t in visible_scope_tasks if t.get("typ_zadania", "REAL") == "REAL"]
    completion = completion_percent(real_tasks)
    attention_tasks = [t for t in visible_scope_tasks if clamp_progress(t) < 1 and (t.get("status") is False or t.get("status") == 0)]

    tab_overview, tab_tasks, tab_plans, tab_map, tab_analytics = st.tabs(
        ["Obraz sytuacji", "Zadania", "Plany", "Mapa", "Analityk"]
    )

    with tab_overview:
        st.markdown('<div class="eyebrow">Sytuacja operacyjna</div>', unsafe_allow_html=True)
        st.header(overview_title)
        if is_national and selected_scope == NATIONAL_SCOPE:
            st.caption("Przegląd obejmuje wyłącznie jednostki bezpośrednio podległe. Szczegóły jednostek niższego szczebla nie są agregowane ani wyświetlane.")
        k1,k2,k3,k4,k5 = st.columns(5)
        k1.metric("Aktywne plany", len(active_plans))
        k2.metric("Zadania REAL", len(real_tasks))
        k3.metric("Średnia realizacja REAL", f"{completion:.0f}%" if completion is not None else "—")
        k4.metric("Wymagające uwagi", len(attention_tasks))
        k5.metric("Budżet jednostek", format_money(sum(float(u.get("budzet", 0) or 0) for u in visible_scope_units)))
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
                st.markdown(f"**{t.get('nazwa_zadania','Zadanie')}**")
                st.caption(f"Plan: {display_plan_name(p)} · {task_status(t)} · {clamp_progress(t)*100:.0f}%")
        st.divider()
        st.subheader("Jednostki w zakresie")
        rows=[]
        for u in visible_scope_units:
            u_tasks=[t for t in visible_scope_tasks if str(u.get("id")) in {str(x) for x in t.get("id_jednostek", [])} or (not t.get("id_jednostek") and str(t.get("id_planu")) in {str(x) for x in u.get("id_planow", [])})]
            val=completion_percent([t for t in u_tasks if t.get("typ_zadania")=="REAL"])
            rows.append({"Jednostka":u.get("nazwa"),"Plany":sum(1 for p in visible_scope_plans_list if owner_by_plan.get(str(p.get("id_planu")))==str(u.get("id"))),"Zadania REAL":sum(1 for t in u_tasks if t.get("typ_zadania")=="REAL"),"Realizacja":f"{val:.0f}%" if val is not None else "—"})
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("Brak jednostek do pokazania.")

    with tab_tasks:
        st.header("Rejestr zadań")
        st.caption("Jedna tabela dla zadań widocznych w bieżącej perspektywie. Szczegóły i raportowanie są ograniczone uprawnieniami oraz własnością zadania.")
        all_scope_tasks = visible_scope_tasks
        f1,f2,f3 = st.columns([2,1,1])
        search = f1.text_input("Szukaj zadania lub planu", placeholder="Nazwa zadania…")
        type_filter = f2.selectbox("Rodzaj", ["Wszystkie", "PRZ", "REAL"])
        status_filter = f3.selectbox("Status", ["Wszystkie", "Zaplanowane", "W toku", "Zakończone"])
        filtered=[]
        for t in all_scope_tasks:
            p=plans_by_id.get(str(t.get("id_planu")), {})
            if type_filter != "Wszystkie" and t.get("typ_zadania") != type_filter: continue
            if status_filter != "Wszystkie" and task_status(t) != status_filter: continue
            if search and search.casefold() not in (str(t.get("nazwa_zadania",""))+" "+display_plan_name(p)).casefold(): continue
            filtered.append(t)
        rows=[]
        for t in filtered:
            p=plans_by_id.get(str(t.get("id_planu")), {})
            owner=units_by_id.get(owner_by_plan.get(str(t.get("id_planu")), ""), {})
            rows.append({"Zadanie":t.get("nazwa_zadania"),"Plan":display_plan_name(p),"Jednostka":owner.get("nazwa","—"),"Typ":t.get("typ_zadania","REAL"),"Status":task_status(t),"Postęp":f"{clamp_progress(t)*100:.0f}%"})
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("Brak zadań spełniających kryteria.")
        if filtered:
            options={f"{t.get('nazwa_zadania','Zadanie')} · {display_plan_name(plans_by_id.get(str(t.get('id_planu')),{}))}":t for t in filtered}
            chosen_label=st.selectbox("Szczegóły zadania", list(options))
            task=options[chosen_label]; p=plans_by_id.get(str(task.get("id_planu")), {})
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
                st.write(f"**Ostatnia aktualizacja:** {task.get('data_aktualizacji','—')}")

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
                    left, right = st.columns([3, 1])
                    left.subheader(display_plan_name(p))
                    right.caption(plan_status(p))
                    left.caption(f"{op_status(p)} · klauzula: {p.get('klauzula_tajnosci', '—')}")
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
                    if is_active:
                        real = completion_percent(real_tasks_for_plan)
                        st.metric("Realizacja zadań REAL", f"{real:.0f}%" if real is not None else "Brak zadań REAL")
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
                    if p.get("status_planu") == "approved" and not is_active and owner_by_plan.get(pid) == own_unit_id:
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
            st.caption("Wymogi dla jednostek podrzędnych definiujesz w tym samym formularzu. Najpierw możesz zachować wersję roboczą formularza, a dopiero po uzupełnieniu utworzyć projekt planu.")
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
            for plan in plans:
                plan_id_value = str(plan.get("id_planu"))
                plan_owner = owner_by_plan.get(plan_id_value)
                if plan_owner == own_unit_id or plan_id_value in visible_scope_plans:
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
            with st.form(f"plan-editor-form-{editor_key}", clear_on_submit=False):
                plan_id_value = st.text_input("Kod planu", value=str(selected_plan.get("id_planu", "")), placeholder="np. PLAN-2026-01", disabled=is_edit, key=f"plan-code-{editor_key}")
                plan_name_value = st.text_input("Nazwa planu", value=str(selected_plan.get("nazwa_dokumentu", st.session_state.get("child_plan_title", ""))), placeholder="Plan przygotowania do działania…", key=name_widget_key)
                parent_label = st.selectbox("Plan nadrzędny", parent_labels, key=parent_widget_key)
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
                st.markdown("**Wymogi dla jednostek podrzędnych**")
                if child_units:
                    selected_children = st.multiselect(
                        "Jednostki zobowiązane do przygotowania planów",
                        options=[str(u["id"]) for u in child_units],
                        default=existing_target_ids if is_edit else [],
                        format_func=lambda uid: child_by_id.get(str(uid), {}).get("nazwa", str(uid)),
                        key=f"requirement-units-{editor_key}")
                    requirement_description = st.text_area(
                        "Wymagania dla planów podrzędnych",
                        value=str(existing_requirements[0].get("opis", "")) if existing_requirements else "",
                        placeholder="Opisz wymagany zakres, elementy planu i procedury…",
                        key=f"requirement-description-{editor_key}")
                    req_default = date.today() + timedelta(days=30)
                    try:
                        if existing_requirements and existing_requirements[0].get("termin"):
                            req_default = date.fromisoformat(str(existing_requirements[0]["termin"])[:10])
                    except ValueError:
                        pass
                    requirement_deadline = st.date_input("Termin przygotowania planów podrzędnych", value=req_default, key=f"requirement-deadline-{editor_key}")
                    st.caption("Opis i termin zostaną przypisane każdej wybranej jednostce. Wymogi można później zmienić, dopóki plan pozostaje projektem.")
                else:
                    selected_children, requirement_description, requirement_deadline = [], "", date.today() + timedelta(days=30)
                    st.info("Ta jednostka nie ma bezpośrednio podległych jednostek w dostępnych danych.")
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
                requirements_error = bool(selected_children and not str(requirement_description).strip())
                if selected_children and str(requirement_description).strip():
                    for child_id in selected_children:
                        old = next((r for r in existing_requirements if str(r.get("id_jednostki")) == str(child_id)), {})
                        requirements_payload.append({
                            "id_jednostki": str(child_id), "opis": str(requirement_description).strip(),
                            "termin": requirement_deadline.isoformat(), "status": old.get("status", "Oczekuje na plan"),
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
                elif len(clean_id) < 2 or len(clean_name) < 3:
                    st.error("Podaj kod i nazwę planu.")
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

if __name__ == "__main__": main()
