#!/usr/bin/env python3
"""The release rule, made mechanical (kit v32): the zip that ships is the zip that was rehearsed.

    python tools/release_check.py --kit GaaR_RaaS_Kit_v32.zip --round <rehearsal round folder>

v22 and v31 each shipped a kit changed after its rehearsal (register text in v22; install-path code in v31). The rule:
after the rehearsal, the only permitted step is sending the rehearsed zip itself. Any change means a new build and a
new rehearsal. This check refuses unless:
  - the rehearsal's install recorded this exact zip (SHA-256 of the file, not of its contents list). When the
    installer that ran predates v32 and recorded no zip hash: the install recorded the SHA-256 of the manifest it
    carried, this zip's manifest has that hash, every file in this zip matches the manifest, and the rehearsal's
    doctor found the install to be exactly the manifest's files;
  - no ledger changed during that install;
  - the kit's expected counts were met on the rehearsal machine;
  - the milestone ended ALL GATES AS EXPECTED or WAITING ON YOU, and nothing in the summary says DIFFERS.
"""
import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path


def check(kit: Path, folder: Path) -> dict:
    kit, folder = Path(kit).expanduser(), Path(folder).expanduser()
    problems = []
    install = folder / "install.json"
    summary = folder / "summary.txt"
    if not install.is_file() or not summary.is_file():
        return {"releasable": False, "problems": [f"{folder} is not a rehearsal round with an install"]}
    installed = json.loads(install.read_text())
    digest = hashlib.sha256(kit.read_bytes()).hexdigest() if kit.is_file() else None
    if digest is None:
        problems.append(f"no kit at {kit}")
    elif not installed.get("kit_sha256") and installed.get("manifest_sha256"):
        problems += _by_manifest(kit, installed["manifest_sha256"], folder / "doctor.json")
    elif installed.get("kit_sha256") != digest:
        problems.append(f"this zip ({digest[:16]}) is not the one the rehearsal installed "
                        f"({str(installed.get('kit_sha256'))[:16]}): rebuild means rehearse again")
    text = summary.read_text()
    if "CHANGED:" in text:
        problems.append("a ledger changed during the rehearsal's install")
    if "expected counts: met" not in text:
        problems.append("the kit's expected counts were not met on the rehearsal machine")
    if "DIFFER" in text:
        problems.append("the rehearsal summary reports a difference: " + next(
            line.strip() for line in text.splitlines() if "DIFFER" in line))
    if "milestone: RESULT: ALL GATES AS EXPECTED" not in text and "milestone: WAITING ON YOU" not in text:
        problems.append("the rehearsal's milestone did not end ALL GATES AS EXPECTED or WAITING ON YOU")
    return {"releasable": not problems, "kit_sha256": digest, "problems": problems}


def _by_manifest(kit: Path, manifest_sha256: str, doctor: Path) -> list[str]:
    """The zip is the rehearsed one if its manifest is the installed manifest and its files are the manifest's."""
    with zipfile.ZipFile(kit) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        if "ge_repo/KIT_MANIFEST.json" not in names:
            return ["this zip has no manifest, so it cannot be matched to the rehearsal's install"]
        raw = z.read("ge_repo/KIT_MANIFEST.json")
        if hashlib.sha256(raw).hexdigest() != manifest_sha256:
            return [f"this zip's manifest is not the one the rehearsal installed ({manifest_sha256[:16]}): "
                    "rebuild means rehearse again"]
        listed = json.loads(raw).get("file_sha256") or {}
        shipped = {n[len("ge_repo/"):]: hashlib.sha256(z.read(n)).hexdigest()
                   for n in names if n != "ge_repo/KIT_MANIFEST.json"}
    if shipped != listed:
        odd = sorted(set(shipped) ^ set(listed)) or sorted(k for k in shipped if shipped[k] != listed.get(k))
        return [f"this zip's files do not match its own manifest ({odd[0]})"]
    rows = json.loads(doctor.read_text()).get("checks", []) if doctor.is_file() else []
    row = next((r for r in rows if r.get("check") == "install integrity"), None)
    if not row or row.get("state") != "OK":
        return ["the rehearsal's doctor did not find the install to be exactly the kit's files"]
    return []


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kit", required=True)
    parser.add_argument("--round", required=True)
    args = parser.parse_args()
    result = check(Path(args.kit), Path(args.round))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["releasable"] else 1)


if __name__ == "__main__":
    main()
