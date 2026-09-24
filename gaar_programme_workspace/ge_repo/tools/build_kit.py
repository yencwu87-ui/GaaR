#!/usr/bin/env python3
"""Build the installable kit zip, without anything that belongs to the machine it is installed on.

    python tools/build_kit.py --version v21 --out ~/Downloads/GaaR_RaaS_Kit_v21.zip

Defect D19 (found in kit v21): earlier kits shipped the workbench's own runtime stores, including
governance/events.jsonl, the append-only decision ledger. Unzipping a kit with `unzip -o` overwrote the user's ledger,
watcher history and evidence dossiers with the builder's copies. Those files are runtime state: the software creates
them when it first needs them, and a kit must never carry them. The same goes for signed approvals, test and trace
records, reports, packs and caches.
"""
import argparse
import fnmatch
import hashlib
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "ge_repo"
RUNTIME_STATE = [
    "governance/*.jsonl", "governance/*.lock", "governance/*.jsonl.lock",
    "governance/watcher_blobs/*", "governance/evidence_blobs/*", "governance/dossiers/*",
    "data/assessments.json", "data/backups/*",
    "docs/quality/approvals/*",
    ".test_runs/*", "reports/*", "packs/*", ".milestone_state.json", ".coverage*",
    "*/__pycache__/*", "__pycache__/*", ".pytest_cache/*", "*.pyc",
]
KEEP = ["governance/synthetic_demo/*"]          # constructed demonstration data the tests read, not runtime state


def excluded(rel: str) -> bool:
    if any(fnmatch.fnmatch(rel, pattern) for pattern in KEEP):
        return False
    return any(fnmatch.fnmatch(rel, pattern) for pattern in RUNTIME_STATE)


def build(out: Path, version: str) -> dict:
    out = Path(out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    files, skipped = {}, []
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(ROOT.rglob("*")):
            rel = path.relative_to(ROOT).as_posix()
            if path.is_symlink() or not path.is_file():
                continue
            if excluded(rel):
                skipped.append(rel)
                continue
            z.write(path, f"{PREFIX}/{rel}")
            files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest = {"kit": version, "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "files": len(files), "never_shipped": RUNTIME_STATE,
                    "content_sha256": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()}
        z.writestr(f"{PREFIX}/KIT_MANIFEST.json", json.dumps(manifest, indent=2) + "\n")
    return {"status": "KIT_BUILT", "kit": str(out), "files": len(files), "runtime_state_left_out": len(skipped),
            "content_sha256": manifest["content_sha256"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    print(json.dumps(build(Path(args.out), args.version), indent=2))


if __name__ == "__main__":
    main()
