import json
from pathlib import Path

ROOT = Path(__file__).parent
seed = json.loads((ROOT / "seed_data.json").read_text(encoding="utf-8"))
plans = {p["id_planu"]: p for p in seed["plans"]}
units = {u["id"]: u for u in seed["units"]}
errors = []
for p in seed["plans"]:
    parent = p.get("id_planu_nadrzednego")
    if parent and parent not in plans: errors.append(f"Plan {p['id_planu']}: brak rodzica {parent}")
    if parent and not p["id_planu"].startswith(parent): errors.append(f"Plan {p['id_planu']}: kod nie zaczyna się od kodu rodzica {parent}")
for u in seed["units"]:
    parent = u.get("id_jednostki_nadrzednej")
    if parent and parent not in units: errors.append(f"Jednostka {u['id']}: brak rodzica {parent}")
    for pid in u.get("id_planow", []):
        if pid not in plans: errors.append(f"Jednostka {u['id']}: brak planu {pid}")
for t in seed["tasks"]:
    if t["id_planu"] not in plans: errors.append(f"Zadanie {t['id_zadania']}: brak planu {t['id_planu']}")
    if t.get("id_jednostek"): errors.append(f"Zadanie {t['id_zadania']}: pole id_jednostek powinno być puste")
for p in seed["plans"]:
    expected = next((u["id"] for u in seed["units"] if p["id_planu"] in u["id_planow"]), None)
    if not expected: errors.append(f"Plan {p['id_planu']}: brak jednostki-właściciela")
if errors:
    print("BŁĘDY:"); print("\n".join(errors)); raise SystemExit(1)
print(f"OK: {len(plans)} planów, {len(units)} jednostek, {len(seed['tasks'])} zadań")
