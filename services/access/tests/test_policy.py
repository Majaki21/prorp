import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))

from services.access.app.main import clearance_allows


def test_clearance_ordering():
    assert clearance_allows("tajne", "poufne")
    assert clearance_allows("jawne", "jawne")
    assert not clearance_allows("poufne", "tajne")
    assert not clearance_allows("jawne", "zastrzezone")


def test_unknown_classification_fails_closed():
    assert not clearance_allows("administrator", "jawne")
    assert not clearance_allows("tajne", "unknown")
