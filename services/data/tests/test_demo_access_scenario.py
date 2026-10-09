import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

from services.data.app import main as data


def test_demo_scenario_seeds_distinct_identities_clauses_and_directional_aggregate(tmp_path, monkeypatch):
    monkeypatch.setattr(data, "DB_PATH", tmp_path / "demo.sqlite3")
    monkeypatch.setattr(data, "SEED_PATH", Path(__file__).resolve().parents[1] / "seed_data.json")

    data.init_db()
    data.apply_demo_access_scenario()

    people = {p["id_osoby"]: p for p in data.get_people()}
    assert set(people) == {"demo-premier", "demo-kgp", "demo-kgpsp"}
    assert people["demo-premier"]["klauzula_tajnosci"] == "scisle_tajne"
    assert people["demo-kgp"]["klauzula_tajnosci"] == "tajne"
    assert people["demo-kgpsp"]["klauzula_tajnosci"] == "zastrzezone"
    assert len({(p["imie"], p["nazwisko"]) for p in people.values()}) == 3

    relations = data.get_cooperation()
    assert relations == [{"unit_id": "U-KGPSP", "partner_unit_id": "U-KGP", "sharing_level": "aggregate"}]

    tasks = data.get_tasks(limit=5000)
    assert any(t["klauzula_tajnosci"] == "tajne" for t in tasks)
    assert any(t["klauzula_tajnosci"] == "zastrzezone" for t in tasks)
