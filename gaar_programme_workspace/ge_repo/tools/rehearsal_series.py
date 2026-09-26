#!/usr/bin/env python3
"""A practice series for upgrade rehearsals (kit v32): the constructed demo, plus a signed mapping and its review.

    python tools/rehearsal_series.py --workspace ~/gaar-recurring-demo

A plain constructed demo has no mapping, so its "Independent mapping review" gate is OPEN and every rehearsal reported
DIFFERS on it while the Mac, whose series has a review, expected HELD. This builds the series the way the Mac's was
built: a mapping signed with the demo's governance key and reviewed with a different key (the demo's outsider key), so
a rehearsal's gate table can match the Mac's. Constructed keys and constructed data only; never for a real series.
"""
import argparse
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def build(workspace: Path, home: Path | None = None) -> dict:
    from tests.test_governance_events import _keys, _review
    from tests.test_recurring import _signed_mapping_with_demo_keys
    import importlib
    home = Path(home or Path.home())
    workspace = Path(workspace).expanduser()
    if (workspace / "operations.json").exists():
        raise ValueError(f"{workspace} already holds a series; a rehearsal series is built fresh, never over one")
    scratch = workspace.parent / f".{workspace.name}-mapping"
    scratch.mkdir(parents=True, exist_ok=True)
    old = os.environ.get("HOME")
    os.environ["HOME"] = str(home)
    try:
        document = _signed_mapping_with_demo_keys(home, scratch)
        review = _review(_keys(home), document, "outsider.key", "Independent Reviewer")["review"]
        tool = importlib.import_module("tools.gaar_recurring")
        result = tool.authorise(SimpleNamespace(
            constructed_demo=True, workspace=str(workspace), periods=None, reviewer_token_env="GAAR_REVIEWER_TOKEN",
            mapping=str(document), mapping_review=str(review), policy_approval=None, grace_days=2, slack_minutes=10,
            cadence_days=7, layout=None, element=None, reconcile=None))
    finally:
        if old is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = old
    return {"status": "REHEARSAL_SERIES_BUILT", "config": str(workspace / "operations.json"),
            "mapping": str(document), "mapping_review": str(review), "authorisation": result.get("status")}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workspace", required=True)
    args = parser.parse_args()
    print(json.dumps(build(Path(args.workspace)), indent=2))


if __name__ == "__main__":
    main()
