#!/usr/bin/env python3
"""Frozen evidence packs: what you hand to a reader outside the team.

    python tools/gaar_pack.py freeze --report reports/gate_status-<time>.json [--workpaper ~/Desktop/…docx]
    python tools/gaar_pack.py verify --pack packs/pack-<time>.zip

A live report is an operating view: regenerated later, it can differ, so "here is what I gave you" would be
unverifiable. `freeze` verifies the report at that moment, copies it with its rendering and the workpaper into a
pack, and writes a manifest of every file's hash. The zip is what is shared. `verify` checks the frozen bytes against
the manifest and the report against its own content hash. It deliberately does not regenerate the report: the pack
records what was true when it was frozen, and says so.
"""
import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance.production import gate_status  # noqa: E402
from governance.investigation.store import digest  # noqa: E402

BODY_KEYS = ("report", "format", "policy", "series", "as_of", "live", "gates", "guard_register")


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def freeze(report_path, workpaper=None, out=None) -> dict:
    report_path = Path(report_path).expanduser()
    report = json.loads(report_path.read_text())
    check = gate_status.verify(report)
    if not check["valid"]:
        raise ValueError(f"the report does not verify ({check['reason']}); a pack is never frozen from it")
    frozen_at = datetime.now().astimezone()
    name = "pack-" + frozen_at.strftime("%Y%m%dT%H%M%S%z")
    folder = Path(out).expanduser() if out else ROOT / "packs"
    target = folder / name
    target.mkdir(parents=True)
    shutil.copyfile(report_path, target / "gate_status.json")
    (target / "gate_status.md").write_text(gate_status.render_markdown(report))
    if workpaper:
        shutil.copyfile(Path(workpaper).expanduser(), target / "workpaper.docx")
    files = {p.name: _sha(p) for p in sorted(target.iterdir())}
    manifest = {"pack": name, "frozen_at": frozen_at.isoformat(), "report_as_of": report["as_of"],
                "report_body_sha256": report["body_sha256"], "policy": report["policy"],
                "verified_at_freeze": check, "files": files,
                "meaning": "Point-in-time. What was true when frozen; regenerating the report later may differ."}
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    archive = folder / f"{name}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(target.iterdir()):
            z.write(path, f"{name}/{path.name}")
    for path in target.iterdir():
        path.chmod(0o444)
    return {"status": "PACK_FROZEN", "pack": str(archive), "folder": str(target),
            "manifest_sha256": _sha(target / "manifest.json"), "files": sorted(files)}


def verify(pack) -> dict:
    pack = Path(pack).expanduser()
    if pack.suffix == ".zip":
        with zipfile.ZipFile(pack) as z:
            names = z.namelist()
            read = {n.split("/", 1)[1]: z.read(n) for n in names if "/" in n}
    else:
        read = {p.name: p.read_bytes() for p in pack.iterdir()}
    if "manifest.json" not in read:
        return {"valid": False, "reason": "no manifest: this is not a frozen pack"}
    manifest = json.loads(read.pop("manifest.json"))
    if set(read) != set(manifest["files"]):
        return {"valid": False, "reason": f"files differ from the manifest: {sorted(set(read) ^ set(manifest['files']))}"}
    for name, content in read.items():
        if hashlib.sha256(content).hexdigest() != manifest["files"][name]:
            return {"valid": False, "reason": f"{name} changed after the pack was frozen"}
    report = json.loads(read["gate_status.json"])
    if digest({k: report.get(k) for k in BODY_KEYS}) != report.get("body_sha256"):
        return {"valid": False, "reason": "the report does not match its own content hash"}
    return {"valid": True, "frozen_at": manifest["frozen_at"], "report_as_of": manifest["report_as_of"],
            "reason": "every file matches the manifest; the report matches its own hash. "
                      "Point-in-time: this is what was true when frozen, not a live regeneration."}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("freeze")
    f.add_argument("--report", required=True)
    f.add_argument("--workpaper")
    f.add_argument("--out")
    v = sub.add_parser("verify")
    v.add_argument("--pack", required=True)
    args = parser.parse_args()
    result = freeze(args.report, args.workpaper, args.out) if args.command == "freeze" else verify(args.pack)
    print(json.dumps(result, indent=2))
    if args.command == "verify" and not result["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        raise SystemExit(2)
