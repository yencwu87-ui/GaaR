#!/usr/bin/env python3
"""One command per round: install, check, run, and pack the results into one file to send back.

    python tools/gaar_round.py --kit ~/Downloads/GaaR_RaaS_Kit_v28.zip      install a new kit, then run the round
    python tools/gaar_round.py                                              run the round on what is installed

It does, in order, and stops with the fix whenever something is not right:
  1. install (only with --kit): copies every ledger to ~/gaar-snapshots/<time>/, refuses a kit that carries runtime
     state (D19), unzips over this install, and proves no ledger changed. Then it continues in the new code.
  2. doctor: the Python environment, the evidence pack, the series, the watch, the mail password variable, Ollama,
     the Anthropic key, git and disk (governance/doctor.py). A secret is reported as set or not set, never shown.
  3. milestone: tests, trace, series, scheduler, attestation, gate report, workpaper, frozen pack.
  4. watch: checks every subscribed source now and records each one's state.
  5. packs everything into ~/Desktop/gaar-round-<time>.zip and prints one summary.

Exit codes: 0 all as expected, 1 something differs, 2 the machine is not ready, 3 waiting on your signature.
"""
import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
DEFAULT_CONFIG = "~/gaar-recurring-demo/operations.json"
LEDGERS = ("governance/*.jsonl", "data/assessments.json", "data/*.jsonl")


def ledgers(root: Path = ROOT) -> dict[str, str]:
    """Every live ledger in this install and its SHA-256."""
    out = {}
    for pattern in LEDGERS:
        for path in sorted(Path(root).glob(pattern)):
            if path.is_file():
                out[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def install(kit_path: Path, root: Path = ROOT, snapshots: Path | None = None, stamp: str = "") -> dict:
    """Snapshot the ledgers, refuse a kit carrying runtime state, unzip, and prove the ledgers are untouched."""
    from build_kit import RUNTIME_STATE, KEEP
    kit_path = Path(kit_path).expanduser()
    if not kit_path.is_file():
        found = sorted(kit_path.parent.glob("GaaR_RaaS_Kit_v*.zip"), key=lambda p: p.stat().st_mtime) \
            if kit_path.parent.is_dir() else []
        raise ValueError(f"no kit at {kit_path}" + (f"; the newest kit in that folder is {found[-1].name}" if found else ""))
    with zipfile.ZipFile(kit_path) as z:
        names = z.namelist()
        if not names or not all(n.startswith("ge_repo/") for n in names):
            raise ValueError("this zip is not a GaaR kit: every entry must sit under ge_repo/")
        carried = [n for n in names if not any(fnmatch.fnmatch(n[8:], k) for k in KEEP)
                   and any(fnmatch.fnmatch(n[8:], p) for p in RUNTIME_STATE)]
        if carried:
            raise ValueError(f"the kit carries runtime state ({carried[0][8:]}{' and more' if len(carried) > 1 else ''}); "
                             "installing it could overwrite your records (D19). Nothing was installed")
        manifest = json.loads(z.read("ge_repo/KIT_MANIFEST.json")) if "ge_repo/KIT_MANIFEST.json" in names else {}
        version, expected = manifest.get("kit"), manifest.get("expected")
        before = ledgers(root)
        snap = Path(snapshots or Path.home() / "gaar-snapshots").expanduser() / stamp
        for rel in before:
            (snap / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(Path(root) / rel, snap / rel)
        (snap).mkdir(parents=True, exist_ok=True)
        (snap / "ledgers.sha256.json").write_text(json.dumps(before, indent=1))
        z.extractall(Path(root).parent)
    after = ledgers(root)
    changed = [rel for rel, digest in before.items() if after.get(rel) != digest]
    if changed:
        raise ValueError(f"{len(changed)} ledger(s) changed during the install ({changed[0]}); restore them from {snap}")
    return {"kit": version, "kit_sha256": hashlib.sha256(kit_path.read_bytes()).hexdigest(),
            "ledgers_checked": len(before), "snapshot": str(snap), "ledgers_before": digest(before),
            "ledgers_after": digest(after), "expected": expected}


def self_contained(installed: dict, root: Path = ROOT) -> dict:
    """v32: an install done by an older installer carries no digest; compute both sides here, before anything runs.

    Before comes from the per-file hashes every installer since v28 writes to the snapshot; after is this install's
    own ledgers, hashed now, before the doctor or the milestone can write to them."""
    if not installed.get("kit_sha256") and (root / "KIT_MANIFEST.json").is_file():
        # The installer that ran predates v32 and did not hash the zip. Record the manifest this install carries;
        # the doctor checks the installed files against it, and release_check checks the zip against it.
        installed = {**installed, "manifest_sha256": hashlib.sha256((root / "KIT_MANIFEST.json").read_bytes()).hexdigest(),
                     "kit_sha256_source": "not recorded: the installer that ran predates v32"}
    if installed.get("ledgers_before"):
        return installed
    snap = Path(installed.get("snapshot", "")) / "ledgers.sha256.json"
    if not snap.is_file():
        return {**installed, "digest_source": "no prior baseline: the installer that ran wrote no ledger hashes"}
    before, after = json.loads(snap.read_text()), ledgers(root)
    changed = [rel for rel, h in before.items() if after.get(rel) != h]
    return {**installed, "ledgers_before": digest(before), "ledgers_after": digest(after),
            "ledgers_changed": changed, "digest_source": "computed by this kit from the snapshot the previous "
                                                          "kit's installer wrote"}


def quarantine(root: Path = ROOT, target: Path | None = None, stamp: str = "") -> dict:
    """D30: code no kit shipped is moved out (never deleted); changed shipped code is copied out as it is. Files that
    are not code are left where they are (D32): they are the owner's drafts and workbooks, and cannot run."""
    from governance import doctor
    found = doctor.install_files(root)
    if found["shipped"] is None:
        raise ValueError("the installed kit carries no file list (kits before v32); nothing can be told apart")
    folder = Path(target or Path.home() / "gaar-quarantine").expanduser() / stamp
    for rel in found["extra"]:
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(Path(root) / rel), str(folder / rel))
    for rel in found["changed"]:
        (folder / "changed" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(root) / rel, folder / "changed" / rel)
    return {"status": "QUARANTINED" if found["extra"] or found["changed"] else "NOTHING_TO_QUARANTINE",
            "moved": found["extra"], "copied_changed": found["changed"], "folder": str(folder),
            "next": "reinstall the kit with --kit to restore changed shipped files" if found["changed"] else
                    "run the round again"}


def skipped(root: Path = ROOT) -> list[str]:
    runs = sorted((Path(root) / ".test_runs").glob("[0-9]*.json"))
    return json.loads(runs[-1].read_text()).get("skipped_with_reasons") or [] if runs else []


def digest(ledger_hashes: dict) -> str:
    """One hash over every ledger's hash, printed before and after an install so the check is visible."""
    return hashlib.sha256(json.dumps(ledger_hashes, sort_keys=True).encode()).hexdigest()


def compare(expected: dict | None, root: Path = ROOT) -> list[str]:
    """v31: the kit states what its tests must count; the Mac checks itself against that. Empty list = met."""
    if not expected:
        return []
    runs = sorted((Path(root) / ".test_runs").glob("[0-9]*.json"))
    traces = sorted((Path(root) / ".test_runs").glob("trace-*.json"))
    run = json.loads(runs[-1].read_text()) if runs else {}
    trace = json.loads(traces[-1].read_text()) if traces else {}
    found = {"tests_collected": run.get("collected"), "trace_modules": len(trace.get("modules") or []) or None,
             "trace_unreached": trace.get("unreached")}
    return [f"{key}: expected {expected[key]}, this machine {found[key]}" for key in found
            if key in expected and found[key] != expected[key]]


def _run(args: list[str], out: Path) -> int:
    result = subprocess.run([sys.executable, *args], cwd=ROOT, text=True, capture_output=True)
    out.write_text(result.stdout + ("\n--- stderr ---\n" + result.stderr if result.stderr.strip() else ""))
    return result.returncode


def summarise(folder: Path, doctor_report: dict, milestone_code, watch_rows, installed, mismatches=None,
              adjudications=None, skips=None) -> str:
    lines = [f"GaaR round {folder.name}", ""]
    if installed:
        digests = (f"digest before {installed['ledgers_before'][:16]}, after {installed['ledgers_after'][:16]}"
                   + (f"; {installed['digest_source']}" if installed.get("digest_source") else "")
                   if installed.get("ledgers_before") else installed.get("digest_source") or "no prior baseline")
        changed = installed.get("ledgers_changed") or []
        lines.append(f"install: {installed['kit']} installed; {installed['ledgers_checked']} ledger(s) "
                     + (f"CHANGED: {', '.join(changed)}" if changed else "unchanged")
                     + f" ({digests}); snapshot {installed['snapshot']}")
    from governance import doctor
    lines += [doctor.render(doctor_report), ""]
    if milestone_code is None:
        lines.append("milestone: not run (the machine is not ready; apply the fixes above and run the round again)")
    else:
        text = (folder / "milestone.txt").read_text() if (folder / "milestone.txt").exists() else ""
        result = next((l for l in text.splitlines() if l.startswith("RESULT")), None)
        if milestone_code == 1 and not result:
            tail = [l for l in text.splitlines() if l.strip()][-15:]
            result = "STOPPED. The last lines of milestone.txt:\n" + "\n".join("  " + l for l in tail)
        lines.append("milestone: " + (result or {3: "WAITING ON YOU: sign in the inbox (command in milestone.txt), "
                                                     "then run the round again without --kit",
                                                  1: "STOPPED: see milestone.txt"}.get(milestone_code, "see milestone.txt")))
    if mismatches is not None:
        lines.append("expected counts: " + ("met" if not mismatches else "DIFFER: " + "; ".join(mismatches)))
    for line in skips or []:
        lines.append(f"  skipped: {line.removeprefix('SKIPPED ')[:200]}")
    if adjudications is not None:
        lines.append("twin adjudications: " + (", ".join(
            f"{a['id']} {a['state']}" + (f" by {', '.join(a['confirmed_by'])}" if a["confirmed_by"] else "")
            for a in adjudications) or "none"))
    if watch_rows is not None:
        ok = [w for w in watch_rows if w["state"] == "OK"]
        lines.append(f"watch: {len(ok)} of {len(watch_rows)} source(s) OK")
        lines += [f"  {w['state']:<8} {w['source_id']:<28} {str(w.get('error') or '')[:110]}"
                  for w in watch_rows if w["state"] != "OK"]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kit", help="a new kit zip to install before the round")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help=f"the series (default {DEFAULT_CONFIG})")
    parser.add_argument("--out", default="~/Desktop/GaaR_Quality_Policy_Workpaper.docx")
    parser.add_argument("--resume", help=argparse.SUPPRESS)          # the new code continuing after an install
    parser.add_argument("--quarantine", action="store_true",
                        help="move files no kit shipped out of the install, then stop")
    args = parser.parse_args()
    if args.quarantine:
        print(json.dumps(quarantine(stamp=datetime.now().strftime("%Y%m%dT%H%M%S")), indent=2))
        return
    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    folder = Path(args.resume) if args.resume else ROOT / "reports" / f"round-{stamp}"
    folder.mkdir(parents=True, exist_ok=True)
    installed = None
    if args.kit:
        print("1. installing", args.kit, flush=True)
        installed = install(Path(args.kit), stamp=stamp)
        (folder / "install.json").write_text(json.dumps(installed, indent=1))
        print(f"   {installed['kit']} installed; {installed['ledgers_checked']} ledger(s) unchanged "
              f"(digest before {installed['ledgers_before'][:16]}, after {installed['ledgers_after'][:16]})", flush=True)
        os.execv(sys.executable, [sys.executable, str(ROOT / "tools/gaar_round.py"), "--config", args.config,
                                  "--out", args.out, "--resume", str(folder)])
    if (folder / "install.json").exists():
        installed = self_contained(json.loads((folder / "install.json").read_text()))
        (folder / "install.json").write_text(json.dumps(installed, indent=1))
    from governance import doctor
    print("2. doctor", flush=True)
    report = doctor.run(args.config)
    (folder / "doctor.json").write_text(json.dumps(report, indent=1))
    print(doctor.render(report), flush=True)
    milestone_code = watch_rows = None
    if report["verdict"] != "NOT READY":
        print("3. milestone (about 7 minutes when the tests run)", flush=True)
        milestone_code = _run(["tools/gaar_milestone.py", "--config", str(Path(args.config).expanduser()),
                               "--out", str(Path(args.out).expanduser())], folder / "milestone.txt")
        from governance.watcher import intel
        if intel.configured():
            print("4. watch", flush=True)
            _run(["tools/gaar_watch.py", "run", "--force"], folder / "watch_run.txt")
            watch_rows = intel.health()
            (folder / "watch_status.json").write_text(json.dumps(watch_rows, indent=1, default=str))
    mismatches = None
    manifest = ROOT / "KIT_MANIFEST.json"
    if milestone_code is not None and manifest.is_file():
        mismatches = compare(json.loads(manifest.read_text()).get("expected"))
        if mismatches and milestone_code == 0:
            milestone_code = 1                                     # a met milestone on the wrong count is not met
    from governance.twin import adjudication
    text = summarise(folder, report, milestone_code, watch_rows, installed, mismatches, adjudication.status(),
                     skipped() if milestone_code is not None else None)
    (folder / "summary.txt").write_text(text)
    target = Path.home() / "Desktop" / f"gaar-round-{folder.name.removeprefix('round-')}.zip"
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(folder.iterdir()):
            z.write(path, path.name)
        latest = sorted((ROOT / "reports").glob("milestone-*.txt"))
        if latest:
            z.write(latest[-1], latest[-1].name)
    print("\n" + text + f"\nsend this one file back: {target}")
    raise SystemExit(2 if milestone_code is None else milestone_code)


def cli():
    try:
        main()
    except ValueError as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    cli()
