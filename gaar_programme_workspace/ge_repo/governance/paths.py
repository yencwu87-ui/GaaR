"""Where runtime state lives (kit v22). One rule: an explicit absolute location, never relative to the folder a
program happens to be started from.

Three defects had one cause: tests writing tracked ledgers, kits shipping ledgers (D19), and workbench tests
overwriting data/assessments.json, all because state was resolved relative to the working directory. Every entry
point now asks here.
"""
from __future__ import annotations

import os
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]


def workbench_data() -> Path:
    """The workbench's data folder: GAAR_WORKBENCH_DATA if set, else the package's own data/ (absolute)."""
    return Path(os.environ.get("GAAR_WORKBENCH_DATA") or PACKAGE / "data").expanduser().resolve()


MARKER = ".gaar_checkout"


def shared_state_warning(data: Path | None = None) -> str | None:
    """The hazard the override creates: two installed copies pointed at one state folder, each writing to it.

    The first copy to use a folder records itself there. A different copy that still exists is reported; a copy that
    no longer exists (an install that was moved, or replaced in place) hands the folder over silently."""
    data = Path(data or workbench_data())
    marker = data / MARKER
    me = str(PACKAGE)
    try:
        owner = marker.read_text(encoding="utf-8").strip()
    except OSError:
        owner = ""
    if owner and owner != me and Path(owner).exists():
        return (f"This workbench's state folder {data} is also used by another installed copy at {owner}. Two copies "
                "writing one ledger can interleave their records. Point one of them elsewhere with GAAR_WORKBENCH_DATA.")
    if owner != me and data.is_dir():
        try:
            marker.write_text(me + "\n", encoding="utf-8")
        except OSError:
            pass
    return None
