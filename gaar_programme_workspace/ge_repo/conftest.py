"""Keep the shipped governance ledgers byte-identical across a test run.

Several legacy modules default their append-only ledgers to paths inside
`governance/`, and some legacy tests exercise those defaults. Without this
guard, running the suite rewrites files that are listed in the package content
manifest, so a package built after testing would silently differ from the one
that was verified.

This restores the original bytes at the end of the session and removes files
the run created there. It does not hide the behaviour: the terminal summary
names every ledger a test touched. The proper fix is for those tests to pass
temporary paths; until then, this keeps the shipped artefacts honest.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
GUARDED = (ROOT / "governance", ROOT / ".cache")
_touched: list[str] = []


def _snapshot():
    files = {}
    for folder in GUARDED:
        if folder.is_dir():
            for path in folder.iterdir():
                if path.is_file() and (path.suffix in {".jsonl", ".lock"} or path.name.endswith(".jsonl.lock")):
                    files[path] = path.read_bytes()
    return files


@pytest.fixture(scope="session", autouse=True)
def _preserve_shipped_ledgers():
    before = _snapshot()
    existed = {folder: folder.exists() for folder in GUARDED}
    yield
    after = _snapshot()
    for path, raw in before.items():
        if not path.exists() or path.read_bytes() != raw:
            path.write_bytes(raw)
            _touched.append(str(path.relative_to(ROOT)))
    for path in after:
        if path not in before and path.exists():
            path.unlink()
            _touched.append(str(path.relative_to(ROOT)) + " (created, removed)")
    for folder, was_there in existed.items():
        if not was_there and folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()


def pytest_terminal_summary(terminalreporter):
    if _touched:
        terminalreporter.write_sep("-", "shipped ledgers written by tests and restored")
        for name in sorted(set(_touched)):
            terminalreporter.write_line(name)
