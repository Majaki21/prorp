import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

from fastapi.testclient import TestClient
from services.access.app import main as access


async def fake_data_get(path, params=None):
    if path == "/people/demo-premier":
        return {"id_osoby": "demo-premier", "id_jednostki": "U-PRM",
                "aktywna": True, "klauzula_tajnosci": "tajne"}
    if path == "/people/demo-unit":
        return {"id_osoby": "demo-unit", "id_jednostki": "U-POL",
                "aktywna": True, "klauzula_tajnosci": "tajne"}
    raise AssertionError(f"Unexpected request: {path}")


def setup(monkeypatch):
    monkeypatch.setattr(access, "data_get", fake_data_get)
    monkeypatch.setattr(access, "DEFAULT_PERSON_ID", "")
    return TestClient(access.app)


def test_analytics_requires_explicit_identity(monkeypatch):
    client = setup(monkeypatch)
    assert client.get("/analytics/history/snapshots").status_code == 401


def test_analytics_global_snapshot_is_premier_only(monkeypatch):
    client = setup(monkeypatch)
    assert client.get("/analytics/history/snapshots",
                      headers={"X-Person-Id": "demo-unit"}).status_code == 403


def test_analytics_premier_is_authorized_and_proxy_is_called(monkeypatch):
    client = setup(monkeypatch)

    async def fake_analytics_request(method, path, params=None, payload=None):
        assert method == "GET"
        assert path == "/history/snapshots"
        return {"snapshots": []}

    monkeypatch.setattr(access, "analytics_request", fake_analytics_request)
    response = client.get("/analytics/history/snapshots",
                          headers={"X-Person-Id": "demo-premier"})
    assert response.status_code == 200
    assert response.json() == {"snapshots": []}
