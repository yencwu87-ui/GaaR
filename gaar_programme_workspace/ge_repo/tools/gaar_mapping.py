#!/usr/bin/env python3
"""D8 mapping worksheet: which deterministic finding codes evidence which obligation.

This is a judgment an accountable person makes and signs. The tool removes the
guesswork, not the judgment:

    draft   lists, for every obligation in the signed record, every code the
            procedures can emit, what it means, whether it is a discrepancy or
            an assurance gap, and which records it fires on in your evidence.
            Nothing is pre-ticked unless you ask to review the current mapping.
    sign    checks your ticks (only real codes; every obligation either has at
            least one code or an explicit "no deterministic test" note) and
            signs the mapping with the governance key.
    apply   installs a signed mapping into a workspace that has not run yet.

    python tools/gaar_mapping.py draft --config ~/gaar-pilot/operations.json --out ~/mapping/worksheet.json
    (edit worksheet.json: set "include": true on the codes that belong)
    python tools/gaar_mapping.py sign  --config ~/gaar-pilot/operations.json --worksheet ~/mapping/worksheet.json --confirm CHANGE.MGMT
    python tools/gaar_mapping.py apply --config ~/gaar-pilot/operations.json --mapping ~/mapping/mapping-<id>.signed.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from governance.investigation.store import canonical, digest  # noqa: E402
from governance.production.reconciliation import CODE_CATALOGUE, KNOWN_CODES, validate_map  # noqa: E402
from governance.production.procedures import PROCEDURES  # noqa: E402


def _load(path):
    from governance.operations.runtime import load
    return load(Path(path).expanduser())


def _obligations(config, root, iid=None):
    from governance.investigation import InvestigationEngine, InvestigationStore
    iid = iid or next(iter(config.get("expected_heads") or {}), None)
    if not iid:
        raise ValueError("this workspace has no authorised investigation to read obligations from")
    engine = InvestigationEngine(InvestigationStore(root / config["store"], config["trusted_keys"]), config["sources"])
    values = engine.snapshot(iid)[1]
    return iid, values["understand"], values["expectations"].elements


def _evidence_files(config, root, explicit):
    if explicit:
        return [(k.strip(), Path(v).expanduser()) for k, v in (e.split("=", 1) for e in explicit)]
    layout = config.get("periodic_evidence")
    if layout:
        inbox = root / layout["inbox"]
        for label in sorted(layout["periods"].values(), reverse=True):
            files = [(i["evidence_id"], inbox / label / i["file"]) for i in layout["evidence"]]
            if all(p.is_file() for _, p in files):
                return files
        return []
    return [(c["source_id"], (root / c["root"] / c["path"])) for c in config.get("collectors", [])]


def _fires_on(files):
    fired, used = {}, []
    for evidence_id, path in files:
        raw = path.read_bytes()
        used.append({"evidence_id": evidence_id, "file": str(path), "sha256": hashlib.sha256(raw).hexdigest()})
        try:
            package = json.loads(raw)
        except ValueError:
            continue
        names = (("change_authorization", "2"), ("change_segregation", "1")) if isinstance(package.get("changes"), list) \
            else (("change_population", "1"),) if "primary" in package and "independent" in package else ()
        for name in names:
            result = PROCEDURES[name](package)
            for item in result.get("findings", []) + result.get("assurance_gaps", []):
                where = item.get("event_id") or ",".join(item.get("missing_primary", []) or []) or evidence_id
                fired.setdefault(item["code"], set()).add(where)
    return {k: sorted(v) for k, v in fired.items()}, used


def draft(args):
    config, root = _load(args.config)
    iid, context, elements = _obligations(config, root, args.investigation_id)
    fired, used = _fires_on(_evidence_files(config, root, args.evidence))
    current = (config.get("reconciliation_map") or {}).get(context.control_id, {}) if args.from_current else {}
    worksheet = {
        "worksheet_version": 1, "control_id": context.control_id, "framework": context.framework,
        "system_id": context.scope.system_id, "read_from_investigation": iid, "evidence_used": used,
        "instructions": "For each obligation, set include=true on every code whose finding would show this "
                        "obligation is not met. If no deterministic test covers an obligation, set "
                        "no_deterministic_test=true and explain why in note. Do not add codes: only the listed codes exist.",
        "obligations": [{
            "element_id": e.element_id, "text": e.text, "purpose": e.purpose,
            "no_deterministic_test": False, "note": "",
            "codes": [{"code": code, "meaning": meaning, "type": kind, "procedure": procedure,
                       "fires_on": fired.get(code, []), "include": code in current.get(e.element_id, [])}
                      for code, (procedure, kind, meaning) in sorted(CODE_CATALOGUE.items())]}
            for e in elements],
    }
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(worksheet, indent=2) + "\n")
    lines = [f"# D8 mapping worksheet — {context.control_id} for {context.scope.system_id}", "",
             "Evidence used: " + ", ".join(f"{u['evidence_id']} ({u['sha256'][:12]}…)" for u in used), ""]
    for ob in worksheet["obligations"]:
        lines += [f"## {ob['element_id']}", "", ob["text"], "",
                  "| Include | Code | Type | Meaning | Fires on in this evidence |", "|---|---|---|---|---|"]
        lines += [f"| {'☑' if c['include'] else '☐'} | {c['code']} | {c['type']} | {c['meaning']} | "
                  f"{', '.join(c['fires_on']) or '—'} |" for c in ob["codes"]]
        lines.append("")
    out.with_suffix(".md").write_text("\n".join(lines))
    import csv
    with out.with_suffix(".csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        for ob in worksheet["obligations"]:
            for c in ob["codes"]:
                writer.writerow([ob["element_id"], ob["text"], c["code"], c["type"], c["meaning"],
                                 " ".join(c["fires_on"]), "yes" if c["include"] else "", "", ""])
    return {"status": "WORKSHEET_DRAFTED", "worksheet": str(out), "spreadsheet": str(out.with_suffix(".csv")),
            "readable_view": str(out.with_suffix(".md")),
            "obligations": len(worksheet["obligations"]), "codes_per_obligation": len(CODE_CATALOGUE),
            "codes_firing_in_evidence": len(fired)}


CSV_COLUMNS = ["element_id", "obligation", "code", "type", "meaning", "fires_on_in_your_evidence",
               "include", "no_deterministic_test", "note"]
TRUE = {"yes", "y", "true", "x", "1", "✓", "☑"}


def _worksheet_from(path):
    """Read the JSON worksheet, or the edited spreadsheet laid over the JSON it was drafted with."""
    path = Path(path).expanduser()
    if path.suffix.lower() != ".csv":
        return json.loads(path.read_text()), None
    import csv
    base = path.with_suffix(".json")
    if not base.is_file():
        raise ValueError(f"the spreadsheet must sit next to the {base.name} it was drafted with")
    worksheet = json.loads(base.read_text())
    text = path.read_text(encoding="utf-8-sig")          # Numbers and Excel may add an invisible byte-order mark
    header = text.splitlines()[0] if text else ""
    delimiter = ";" if header.count(";") > header.count(",") else ","   # some regional settings export with semicolons
    rows = list(csv.DictReader(text.splitlines(), delimiter=delimiter))
    if not rows or list(rows[0].keys())[:len(CSV_COLUMNS)] != CSV_COLUMNS:
        raise ValueError("the spreadsheet columns were changed; draft a fresh worksheet")
    by_element = {ob["element_id"]: ob for ob in worksheet["obligations"]}
    for ob in worksheet["obligations"]:
        for c in ob["codes"]:
            c["include"] = False
    for row in rows:
        ob = by_element.get(row["element_id"].strip())
        if ob is None:
            raise ValueError(f"spreadsheet names obligation {row['element_id']!r}, which is not in the signed record")
        code = row["code"].strip()
        entry = next((c for c in ob["codes"] if c["code"] == code), None)
        if entry is None:
            ob["codes"].append({"code": code, "include": row["include"].strip().lower() in TRUE})
            continue
        entry["include"] = row["include"].strip().lower() in TRUE
        if row["no_deterministic_test"].strip().lower() in TRUE:
            ob["no_deterministic_test"] = True
        if row["note"].strip():
            ob["note"] = row["note"].strip()
    return worksheet, hashlib.sha256(path.read_bytes()).hexdigest()


def _signed_document_path(value):
    path = Path(value or "").expanduser()
    if not value or not path.is_file():
        raise ValueError("give the path of a signed mapping document (mapping-….signed.json), as printed by "
                         "'sign'. Nothing was applied.")
    return path


def sign(args):
    config, root = _load(args.config)
    worksheet, spreadsheet_sha256 = _worksheet_from(args.worksheet)
    if args.confirm != worksheet["control_id"]:
        raise ValueError("--confirm must repeat the control id you are signing a mapping for")
    mapping, without_test, problems = {}, [], []
    for ob in worksheet["obligations"]:
        codes = [c["code"] for c in ob["codes"] if c.get("include") is True]
        unknown = [c["code"] for c in ob["codes"] if c["code"] not in KNOWN_CODES]
        if unknown:
            problems.append(f"{ob['element_id']}: codes no procedure emits: {', '.join(unknown)}")
        if codes and ob.get("no_deterministic_test"):
            problems.append(f"{ob['element_id']}: has codes ticked and is also marked no_deterministic_test")
        elif codes:
            mapping[ob["element_id"]] = codes
        elif ob.get("no_deterministic_test") and len((ob.get("note") or "").strip()) >= 20:
            without_test.append({"element_id": ob["element_id"], "note": ob["note"].strip()})
        else:
            problems.append(f"{ob['element_id']}: tick at least one code, or set no_deterministic_test with a note "
                            "of at least 20 characters saying why")
    if problems:
        raise ValueError("worksheet not signable: " + "; ".join(problems))
    validate_map(mapping)
    from governance.operations.secrets import private_seed
    from governance.result_contract import CanonicalSigner
    item = config["signers"]["governance"]
    signer = CanonicalSigner.from_base64(item["key_id"], private_seed(item, root))
    policy = config["trusted_keys"][signer.key_id]
    if policy.get("actor_type") != "human" or "governance" not in policy.get("roles", []):
        raise ValueError("the mapping must be signed by the human governance identity")
    payload = {"control_id": worksheet["control_id"], "framework": worksheet["framework"],
               "system_id": worksheet["system_id"], "mapping": mapping, "mapping_sha256": digest(mapping),
               "obligations_without_deterministic_test": without_test,
               "catalogue_sha256": digest({k: list(v) for k, v in CODE_CATALOGUE.items()}),
               "worksheet_sha256": digest(worksheet), "spreadsheet_sha256": spreadsheet_sha256,
               "evidence_used": worksheet["evidence_used"],
               "signed_by": policy["actor"], "signed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    document = {"payload": payload, "key_id": signer.key_id, "signature": signer.sign(canonical(payload).encode())}
    out = Path(args.worksheet).expanduser().parent / f"mapping-{payload['mapping_sha256'][:12]}.signed.json"
    out.write_text(json.dumps(document, indent=2) + "\n")
    os.chmod(out, 0o600)
    return {"status": "MAPPING_SIGNED", "document": str(out), "signed_by": policy["actor"],
            "mapped": {k: len(v) for k, v in mapping.items()},
            "without_deterministic_test": [w["element_id"] for w in without_test]}


def verify_document(config, document):
    from governance.result_contract import verify_signature
    policy = config["trusted_keys"].get(document["key_id"], {})
    if policy.get("actor_type") != "human" or "governance" not in policy.get("roles", []):
        raise ValueError("mapping document is not signed by a trusted human governance identity")
    if not verify_signature(policy["public_key"], document["signature"], canonical(document["payload"]).encode()):
        raise ValueError("mapping document signature is invalid")
    payload = document["payload"]
    if payload["mapping_sha256"] != digest(payload["mapping"]):
        raise ValueError("mapping document content does not match its own hash")
    validate_map(payload["mapping"])
    return payload


def apply(args):
    config_path = Path(args.config).expanduser().resolve()
    config, root = _load(config_path)
    document = json.loads(_signed_document_path(args.mapping).read_text())
    payload = verify_document(config, document)
    if config.get("standing_authorisation"):
        raise ValueError("this workspace runs under a standing authorisation that already fixes its mapping; "
                         "a new mapping needs a new standing authorisation")
    programme = root / config.get("programme_dir", "")
    if programme.is_dir() and any(programme.iterdir()):
        raise ValueError("this workspace has already run; a mapping applies to investigations that have not run yet")
    config.setdefault("reconciliation_map", {})[payload["control_id"]] = payload["mapping"]
    config["reconciliation_mapping_document"] = {"path": str(Path(args.mapping).expanduser().resolve()),
                                                 "control_id": payload["control_id"],
                                                 "mapping_sha256": payload["mapping_sha256"],
                                                 "signed_by": payload["signed_by"]}
    if getattr(args, "review", None):
        from governance.production.reconciliation import verify_mapping_review
        review_path = _signed_document_path(args.review).resolve()
        reviewed = verify_mapping_review(json.loads(review_path.read_text()), document)
        config["reconciliation_mapping_document"]["review"] = {"path": str(review_path), "reviewer": reviewed["reviewer"],
                                                                "outcome": reviewed["outcome"]}
    if args.no_model_stages:
        config["model_stages"] = "disabled"
        config["deterministic_completion"] = True
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    os.chmod(config_path, 0o600)
    return {"status": "MAPPING_APPLIED", "control_id": payload["control_id"], "signed_by": payload["signed_by"],
            "mapping_sha256": payload["mapping_sha256"],
            "model_stages": config.get("model_stages", "enabled")}


def review(args):
    """An independent reviewer signs their conclusion about one exact, signed mapping document."""
    import time
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import gaar_pilot
    from governance.production.reconciliation import REVIEW_OUTCOMES, verify_mapping_review
    mapping_path = _signed_document_path(args.mapping).resolve()
    document = json.loads(mapping_path.read_text())
    if args.outcome not in REVIEW_OUTCOMES:
        raise ValueError("--outcome must be AGREED or CHANGES_REQUESTED")
    if len(args.notes.strip()) < 20:
        raise ValueError("--notes must say, in at least 20 characters, what was reviewed and concluded")
    _, signer = gaar_pilot.load_human(args.reviewer_key, args.reviewer_name, "reviewer", mapping_path.parent / ".no-workspace")
    payload = {"mapping_document_sha256": digest(document), "mapping_sha256": document["payload"]["mapping_sha256"],
               "control_id": document["payload"]["control_id"], "reviewer": args.reviewer_name.strip(),
               "reviewer_key_id": signer.key_id, "reviewer_public_key": signer.public_key_b64,
               "outcome": args.outcome, "notes": args.notes.strip(),
               "reviewed_at": __import__("datetime").datetime.now().astimezone().isoformat()}
    review_document = {"payload": payload, "signature": signer.sign(canonical(payload).encode())}
    verify_mapping_review(review_document, document)             # refuses a reviewer who is the signer
    target = mapping_path.with_name(mapping_path.name.replace(".signed.json", "") +
                                    f".review-{signer.key_id[-8:]}.json")
    if target.exists():
        raise ValueError(f"{target.name} already exists")
    target.write_text(json.dumps(review_document, indent=2) + "\n")
    return {"status": "MAPPING_REVIEWED", "review": str(target), "reviewer": payload["reviewer"],
            "outcome": payload["outcome"], "mapping_sha256": payload["mapping_sha256"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("draft")
    d.add_argument("--config", required=True)
    d.add_argument("--out", required=True)
    d.add_argument("--investigation-id")
    d.add_argument("--evidence", action="append", help="EVIDENCE_ID=PATH, to show where codes fire")
    d.add_argument("--from-current", action="store_true", help="pre-tick the workspace's current mapping for review")
    d.set_defaults(func=draft)
    s = sub.add_parser("sign")
    s.add_argument("--config", required=True)
    s.add_argument("--worksheet", required=True)
    s.add_argument("--confirm", required=True)
    s.set_defaults(func=sign)
    r = sub.add_parser("review", help="an independent reviewer signs their conclusion about a signed mapping")
    r.add_argument("--mapping", required=True)
    r.add_argument("--reviewer-key", required=True)
    r.add_argument("--reviewer-name", required=True)
    r.add_argument("--outcome", required=True, choices=["AGREED", "CHANGES_REQUESTED"])
    r.add_argument("--notes", required=True)
    r.set_defaults(func=review)
    a = sub.add_parser("apply")
    a.add_argument("--config", required=True)
    a.add_argument("--mapping", required=True)
    a.add_argument("--no-model-stages", action="store_true", help="pilot setting: build every result from tests + D8 only")
    a.add_argument("--review", help="an independent review of this mapping, from 'review'")
    a.set_defaults(func=apply)
    args = parser.parse_args()
    print(json.dumps(args.func(args), indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        raise SystemExit(2)
