"""Test bootstrap: make repository modules importable from both root and tests invocations."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_watch_home(tmp_path, monkeypatch):
    """No test may read or write the real regulatory watch home (~/gaar-watch)."""
    monkeypatch.setenv("GAAR_WATCH_HOME", str(tmp_path / "gaar-watch"))


@pytest.fixture(autouse=True)
def _isolated_arena_home(tmp_path, monkeypatch):
    """No test may read or write the real model arena results (~/gaar-arena)."""
    monkeypatch.setenv("GAAR_ARENA_HOME", str(tmp_path / "gaar-arena"))


@pytest.fixture(autouse=True)
def _isolated_twin_home(tmp_path, monkeypatch):
    """No test may read or write the real twin adjudication confirmations (~/gaar-twin)."""
    monkeypatch.setenv("GAAR_TWIN_HOME", str(tmp_path / "gaar-twin"))


@pytest.fixture(autouse=True)
def _isolated_basis_ledger(tmp_path, monkeypatch):
    """No test may read or write the real requirement-basis decisions."""
    monkeypatch.setenv("GAAR_BASIS_LEDGER", str(tmp_path / "basis_confirmations.jsonl"))
