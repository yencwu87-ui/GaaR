"""GaaR doctor (kit v28): is this machine ready for a round? Every check names its fix.

Each setup failure from the v22-v27 Mac rounds is a check here, so it is caught before a test runs, not diagnosed
afterwards: the wrong Python environment (D25), a kit installed away from its evidence pack, a model server that is
not running, a password variable that is not loaded, a watch setting that will not load. A secret is only ever
reported as set or not set; its value is never read into the report.

States: OK, WARN (the round runs; something optional will not), FAIL (the round stops; the fix is given).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _row(check: str, state: str, detail: str, fix: str = "") -> dict:
    return {"check": check, "state": state, "detail": detail, "fix": fix}


def python_environment(version=None) -> dict:
    version = version or sys.version_info[:2]
    if tuple(version) < (3, 12):
        return _row("python environment", "FAIL", f"Python {version[0]}.{version[1]}: GaaR needs 3.12 or later",
                    "conda activate gaar   (the project environment is Python 3.12)")
    sys.path.insert(0, str(ROOT / "tools"))
    from run_all_tests import requirement_problems
    missing, mismatched = requirement_problems()
    env = os.environ.get("CONDA_DEFAULT_ENV") or "(no conda environment)"
    if missing:
        return _row("python environment", "FAIL", f"{len(missing)} required package(s) missing in {env}: "
                    + ", ".join(missing[:5]), "conda activate gaar   (or: pip install -r requirements.txt)")
    if mismatched:
        return _row("python environment", "WARN", f"{env}: {len(mismatched)} package(s) at another version: "
                    + ", ".join(mismatched[:3]), "pip install -r requirements.txt")
    return _row("python environment", "OK", f"{env}, Python {sys.version.split()[0]}, requirements met")


def evidence_pack(root: Path = ROOT) -> dict:
    pack = Path(root).parent / "synthetic_evidence_v6"
    if not pack.is_dir():
        return _row("evidence pack", "FAIL", f"no synthetic_evidence_v6 next to {Path(root).name}",
                    "install the kit into the folder that holds synthetic_evidence_v6 "
                    "(for you: ~/gaar-test/gaar_programme_workspace)")
    return _row("evidence pack", "OK", f"{pack}")


def kit(root: Path = ROOT) -> dict:
    manifest = Path(root) / "KIT_MANIFEST.json"
    if not manifest.is_file():
        return _row("kit", "WARN", "no KIT_MANIFEST.json (a development checkout, not an installed kit)")
    data = json.loads(manifest.read_text())
    return _row("kit", "OK", f"{data.get('kit')} built {str(data.get('built_at'))[:16]}")


def series(config_path) -> dict:
    path = Path(config_path).expanduser()
    if not path.is_file():
        return _row("series", "FAIL", f"no series configuration at {path}",
                    "python tools/gaar_recurring.py authorise --constructed-demo --workspace ~/gaar-recurring-demo")
    return _row("series", "OK", str(path))


def watch() -> list[dict]:
    from governance.watcher import intel
    if not intel.configured():
        return [_row("watch", "WARN", "not set up", "python tools/gaar_watch.py setup --regions sg,uk,hk,us,cn,global")]
    try:
        subs = intel.subscriptions()
    except ValueError as exc:
        return [_row("watch", "FAIL", f"the watch settings do not load: {exc}", "edit ~/gaar-watch/subscriptions.yaml")]
    rows = [_row("watch", "OK", f"{len(subs['sources'])} source(s) subscribed")]
    mail = subs.get("mail") or {}
    if mail.get("imap_host"):
        name = str(mail.get("password_env") or "")
        rows.append(_row("mail password", "OK", f"{name} is set (value not shown)") if os.environ.get(name) else
                    _row("mail password", "WARN", f"{name or 'password_env'} is not set in this terminal, so alert "
                         "emails will not be read", "source ~/.zshrc; conda activate gaar"))
    return rows


def ollama(get=None) -> dict:
    import requests
    get = get or requests.get
    host = (os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
    try:
        models = [m["name"] for m in get(f"{host}/api/tags", timeout=3).json().get("models", [])]
    except Exception:
        return _row("ollama", "WARN", "not running: local model contestants are unavailable", "open -a Ollama")
    return _row("ollama", "OK", f"{len(models)} model(s): " + ", ".join(models[:6]))


def anthropic_key() -> dict:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return _row("anthropic key", "OK", "set (value not shown)")
    return _row("anthropic key", "WARN", "not set: Claude contestants are unavailable",
                "source ~/.zshrc   (the key is read from the Keychain entry anthropic-api)")


def tools_and_space(home: Path | None = None) -> list[dict]:
    rows = [_row("git", "OK", shutil.which("git")) if shutil.which("git") else
            _row("git", "WARN", "git not found: field agents cannot read a deploy repository", "xcode-select --install")]
    free = shutil.disk_usage(home or Path.home()).free / 2 ** 30
    rows.append(_row("disk", "OK" if free >= 2 else "WARN", f"{free:.1f} GB free",
                     "" if free >= 2 else "free some space: a round writes test records, reports and a pack"))
    return rows


def shared_state() -> dict:
    from governance.paths import shared_state_warning
    warning = shared_state_warning()
    return _row("state folder", "WARN", warning, "point one copy elsewhere with GAAR_WORKBENCH_DATA") if warning else \
        _row("state folder", "OK", "used by this installed copy only")


def run(config_path, root: Path = ROOT, get=None) -> dict:
    rows = [python_environment(), evidence_pack(root), kit(root), series(config_path), *watch(), ollama(get),
            anthropic_key(), *tools_and_space(), shared_state()]
    worst = "FAIL" if any(r["state"] == "FAIL" for r in rows) else "WARN" if any(r["state"] == "WARN" for r in rows) \
        else "OK"
    return {"verdict": {"FAIL": "NOT READY", "WARN": "READY WITH WARNINGS", "OK": "READY"}[worst], "checks": rows}


def render(report: dict) -> str:
    lines = [f"DOCTOR: {report['verdict']}"]
    for r in report["checks"]:
        lines.append(f"  {r['state']:<5} {r['check']:<18} {r['detail']}")
        if r["state"] != "OK" and r["fix"]:
            lines.append(f"        fix: {r['fix']}")
    return "\n".join(lines)
