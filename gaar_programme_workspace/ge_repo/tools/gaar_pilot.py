#!/usr/bin/env python3
"""Pilot on-ramp: real evidence, real people, one runnable investigation.

`gaar_provision.py` is the demonstration path. It mints only service keys and
marks everything synthetic, so it can never produce anything a person signs.
This tool is the pilot path. The difference is where the human identities come
from: this tool never creates one. You bring your own.

    # once per person, into a location you control and outside this package
    python3 tools/gaar_pilot.py keygen --out ~/.gaar/yen-ching.key

    python3 tools/gaar_pilot.py provision \\
        --output-config ~/gaar-pilot/operations.json \\
        --investigation-id CHG-2026-09-001 --confirm CHG-2026-09-001 \\
        --system-id credit-platform --version 2.3 --period 2026-09-20T00:00:00Z \\
        --framework INTERNAL --control CHANGE.MGMT \\
        --requirement-version change-policy-v4 --policy change_policy.md --policy-version v4 \\
        --element "chg.1=Every production change is authorised before execution" \\
        --evidence CHANGES=change_export.json --evidence POPULATION=population_export.json \\
        --owner-key ~/.gaar/yen-ching.key --owner-name "Yen-Ching" \\
        --governance-key ~/.gaar/yen-ching.key --governance-name "Yen-Ching" \\
        --approver-key ~/.gaar/reviewer.key --approver-name "Second Reviewer"

    python3 tools/gaar_pilot.py verify --config ~/gaar-pilot/operations.json

What you are signing when you provision
---------------------------------------
* The owner key signs the investigation scope.
* The governance key signs the internal policy as an internal source, the
  obligations you list, and the precedent corpus (empty unless you supply one).
  An empty approved corpus means you attest there are no precedents to consult.

What it will not do
-------------------
* Generate, copy or store a human key. Human key files must already exist,
  be owner-only (chmod 600), and sit outside the pilot workspace and outside
  this package.
* Approve an external regulatory source. The policy becomes `internal`.
* Enter production mode. A pilot runs in evaluation mode, so its outcome is a
  signed pilot attestation, not a sealed governance result.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT.parent
sys.path.insert(0, str(ROOT))

from governance.investigation import InvestigationEngine, InvestigationStore
from governance.investigation.contracts import ApplicableExpectations, Expectation, InvestigationContext, Scope
from governance.investigation.store import canonical
from governance.operations.secrets import private_seed
from governance.result_contract import CanonicalSigner

SERVICE_ROLES = ("assessor", "test_planner", "executor", "challenger", "decision", "result_sealer")
HUMAN_ROLES = ("owner", "governance", "result_approver")
SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
REQUIRED_TOOLS = {
    "CHANGE.MGMT": [["change_authorization", "2"], ["change_population", "1"]],
    "M3.12": [["change_authorization", "2"], ["change_population", "1"]],
    "M3.6": [[n, "1"] for n in ("m36_model_evaluation", "m36_representativeness",
                               "m36_independent_validation", "m36_residual_risk")],
}
PRECEDENT_FIELDS = ("precedent_id", "source_ref", "system_id", "period", "lesson", "limitations")


def safe_id(value: str, what: str) -> str:
    if not value or any(ch not in SAFE for ch in value):
        raise ValueError(f"{what} may contain only letters, digits, dot, dash and underscore")
    return value


def split_pair(value: str, what: str) -> tuple[str, str]:
    if "=" not in value:
        raise ValueError(f"{what} must be written ID=VALUE")
    key, rest = value.split("=", 1)
    return safe_id(key.strip(), what + " id"), rest.strip()


def write_new(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def new_seed() -> str:
    raw = Ed25519PrivateKey.generate().private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    return base64.b64encode(raw).decode()


def fingerprint(public_key_b64: str) -> str:
    return hashlib.sha256(public_key_b64.encode()).hexdigest()[:16]


# --------------------------------------------------------------------------
# keygen
# --------------------------------------------------------------------------

def keygen(args) -> dict:
    """A person creating their own credential, somewhere they control."""
    out = Path(args.out).expanduser().resolve()
    if out.is_relative_to(PACKAGE):
        raise ValueError("keep personal keys outside the GaaR package so they are never shipped with it")
    seed = new_seed()
    write_new(out, (seed + "\n").encode())
    public = CanonicalSigner.from_base64("probe", seed).public_key_b64
    return {"status": "KEY_CREATED", "path": str(out), "public_key": public,
            "fingerprint": fingerprint(public),
            "note": "Owner-only file. Move to an HSM or KMS before any result someone relies on."}


# --------------------------------------------------------------------------
# provision
# --------------------------------------------------------------------------

def load_human(path_text: str, name: str, role: str, workspace: Path) -> tuple[Path, CanonicalSigner]:
    path = Path(path_text).expanduser().resolve(strict=True)
    if path.is_relative_to(workspace):
        raise ValueError(f"the {role} key sits inside the pilot configuration directory; human keys "
                         "must be held apart from the evidence and records they sign")
    if path.is_relative_to(PACKAGE):
        raise ValueError(f"the {role} key sits inside the GaaR package; keep personal keys outside it")
    if not name.strip():
        raise ValueError(f"--{role.replace('_', '-')}-name is required")
    seed = private_seed({"private_key_file": str(path)}, workspace)  # enforces owner-only chmod 600
    public = CanonicalSigner.from_base64("probe", seed).public_key_b64
    return path, CanonicalSigner.from_base64("HUMAN-" + fingerprint(public), seed)


def provision(args) -> dict:
    if args.confirm != args.investigation_id:
        raise ValueError("--confirm must repeat the exact investigation id you are authorising")
    for value, what in ((args.investigation_id, "investigation id"), (args.system_id, "system id"),
                        (args.framework, "framework"), (args.control, "control")):
        safe_id(value, what)

    output = Path(args.output_config).expanduser().resolve()
    if output.exists():
        raise ValueError("output configuration already exists; the pilot tool never overwrites")
    root = output.parent
    workspace = root / "pilot"
    if workspace.exists():
        raise ValueError(f"pilot workspace already exists: {workspace}")
    if root.is_relative_to(PACKAGE):
        raise ValueError("create the pilot workspace outside the GaaR package; it will hold real evidence")

    elements = [(*split_pair(v, "--element"), "operating") for v in args.element or []]
    elements += [(*split_pair(v, "--design-element"), "design") for v in args.design_element or []]
    if not elements:
        raise ValueError("list at least one obligation with --element ID=TEXT")
    if len({e[0] for e in elements}) != len(elements):
        raise ValueError("obligation ids must be unique")

    evidence_specs = []
    for index, value in enumerate(args.evidence or [], start=1):
        eid, path_text = split_pair(value, "--evidence") if "=" in value else (f"E{index}", value)
        path = Path(path_text).expanduser().resolve(strict=True)
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise ValueError(f"{path.name} is not UTF-8. Export it as JSON, CSV or text; "
                             "PDF segmentation needs a reviewed extraction step") from None
        if not text.strip():
            raise ValueError(f"{path.name} is empty")
        evidence_specs.append((eid, path, raw, text))
    if not evidence_specs and not getattr(args, "periodic", False):
        raise ValueError("supply at least one evidence export with --evidence ID=PATH")
    if len({e[0] for e in evidence_specs}) != len(evidence_specs):
        raise ValueError("evidence ids must be unique")

    policy_path = Path(args.policy).expanduser().resolve(strict=True)
    policy_raw = policy_path.read_bytes()
    if not policy_raw.strip():
        raise ValueError("policy document is empty")

    precedents = []
    if args.precedents:
        precedents = json.loads(Path(args.precedents).expanduser().read_text())
        if not isinstance(precedents, list) or any(
                not isinstance(r, dict) or not all(r.get(k) for k in PRECEDENT_FIELDS) for r in precedents):
            raise ValueError("precedents must be a list of records with " + ", ".join(PRECEDENT_FIELDS))

    # --- identities: humans supplied, services minted -----------------------
    humans = {}
    for role, key, name in (("owner", args.owner_key, args.owner_name),
                            ("governance", args.governance_key, args.governance_name),
                            ("result_approver", args.approver_key, args.approver_name)):
        path, signer = load_human(key, name, role, root)
        humans[role] = (path, signer, name.strip())

    trust, signer_config = {}, {}
    for role, (path, signer, name) in humans.items():
        entry = trust.setdefault(signer.key_id, {"actor": name, "actor_type": "human",
                                                  "public_key": signer.public_key_b64, "roles": []})
        if entry["actor"] != name:
            raise ValueError("one key file was given two different names; a key belongs to one person")
        entry["roles"].append(role)
        signer_config[role] = {"key_id": signer.key_id, "private_key_file": str(path)}

    service = {}
    for role in SERVICE_ROLES:
        seed = new_seed()
        key_id = "PILOT-SERVICE-" + role.upper()
        signer = CanonicalSigner.from_base64(key_id, seed)
        key_path = workspace / "service_keys" / f"{role}.key"
        write_new(key_path, (seed + "\n").encode())
        policy = {"actor": "PILOT-SERVICE-" + role, "actor_type": "service",
                  "public_key": signer.public_key_b64, "roles": [role]}
        if role == "assessor":
            policy.update(require_dependency_review=True, require_integrated_gate=True)
        if role == "test_planner":
            policy["required_tools_by_control"] = {k: v for k, v in REQUIRED_TOOLS.items() if k == args.control}
        if role == "decision":
            policy["allow_auto_block"] = True
        if role == "executor":
            policy.update(allow_readonly_collectors=False, allow_action_assignment=False)
        trust[key_id] = policy
        signer_config[role] = {"key_id": key_id, "private_key_file": str(key_path.relative_to(root))}
        service[role] = signer

    human_keys = {s.public_key_b64 for _, s, _ in humans.values()}
    if human_keys & {s.public_key_b64 for s in service.values()}:
        raise ValueError("a human key collides with a service key")

    distinct_people = {name for _, _, name in humans.values()}
    separation = ("SEPARATED" if len(distinct_people) == 3
                  else "APPROVER_SEPARATED" if humans["result_approver"][2] not in
                  {humans["owner"][2], humans["governance"][2]}
                  else "SINGLE_REVIEWER_PILOT")

    governance = humans["governance"][1]
    governance_name = humans["governance"][2]
    owner = humans["owner"][1]
    owner_name = humans["owner"][2]

    # --- internal source, signed by the governance person -------------------
    source_id = "INTERNAL-" + args.control
    snapshot = workspace / "sources" / (source_id + ".snapshot")
    write_new(snapshot, policy_raw)
    source = {"source_id": source_id, "issuer": "INTERNAL", "authority": "internal",
              "version": args.policy_version, "sha256": hashlib.sha256(policy_raw).hexdigest(),
              "snapshot_path": str(snapshot.relative_to(root)), "approved_by": governance_name,
              "authority_decision_ref": str((workspace / "sources" / (source_id + ".decision.json")).relative_to(root))}
    approval = {k: source[k] for k in ("source_id", "sha256", "authority", "version")}
    write_new(root / source["authority_decision_ref"],
              canonical({"payload": approval, "key_id": governance.key_id,
                         "signature": governance.sign(canonical(approval).encode())}).encode())

    corpus = {"status": "APPROVED", "framework": args.framework, "control_id": args.control, "records": precedents}
    corpus_path = workspace / "precedents.json"
    write_new(corpus_path, (canonical({"payload": corpus, "key_id": governance.key_id,
                                       "signature": governance.sign(canonical(corpus).encode())}) + "\n").encode())

    # --- evidence collectors: offsets computed from the file ----------------
    scope = Scope(system_id=args.system_id, version=args.version, period=args.period)
    element_ids = [e[0] for e in elements]
    collectors = []
    for eid, path, raw, text in evidence_specs:
        target = workspace / "evidence" / f"{eid}{path.suffix.lower() or '.txt'}"
        write_new(target, raw)
        collectors.append({
            "root": str(workspace.relative_to(root)), "path": str(target.relative_to(workspace)),
            "source_id": eid, "sha256": hashlib.sha256(raw).hexdigest(), "scope": scope.model_dump(),
            "authority": "internal", "provenance": ["operator-supplied export", "sha256:" + hashlib.sha256(raw).hexdigest()],
            "segments": [{"start": 0, "end": len(text), "evidence_id": eid, "element_ids": element_ids,
                          "purposes": ["operating_record"], "finding_status": "neutral"}]})

    # --- the two signed opening stages --------------------------------------
    context = InvestigationContext(
        investigation_id=args.investigation_id, control_id=args.control, framework=args.framework,
        requirement_version=args.requirement_version, scope=scope, boundary=args.boundary,
        owner=owner_name, criticality=args.criticality, synthetic=False)
    expectations = ApplicableExpectations(requirement_version=args.requirement_version, elements=tuple(
        Expectation(element_id=eid, text=text, source_id=source_id, source_sha256=source["sha256"],
                    source_version=source["version"], authority="internal", purpose=purpose, applies=True,
                    applicability_reason="In scope for this system and period, as authorised at provisioning")
        for eid, text, purpose in elements))
    sources = {source_id: source}
    with tempfile.TemporaryDirectory() as temp:
        trial = InvestigationEngine(InvestigationStore(Path(temp) / "trial.sqlite", trust), sources)
        trial.append(args.investigation_id, "understand", context, owner)
        trial.append(args.investigation_id, "expectations", expectations, governance)
    store = workspace / "investigations.sqlite"
    engine = InvestigationEngine(InvestigationStore(store, trust), sources)
    engine.append(args.investigation_id, "understand", context, owner)
    engine.append(args.investigation_id, "expectations", expectations, governance)
    rows, _ = engine.snapshot(args.investigation_id)
    head = rows[-1]["record_hash"]

    template = json.loads(Path(args.template).resolve(strict=True).read_text())
    models = template.get("models", {})
    for stage in ("examine", "explain", "plan", "challenge"):
        chosen = getattr(args, f"{stage}_model") or args.model
        if chosen:
            models.setdefault(stage, {})["model"] = chosen
    template.update({
        "operation_mode": "evaluation",
        "deployment_profile": "pilot",
        "separation_of_duties": separation,
        "provisioned_by": "tools/gaar_pilot.py",
        "store": str(store.relative_to(root)),
        "programme_dir": str((workspace / "programme").relative_to(root)),
        "receipt_dir": str((workspace / "receipts").relative_to(root)),
        "result_store": str((workspace / "results.jsonl").relative_to(root)),
        "result_state_log": str((workspace / "result_states.jsonl").relative_to(root)),
        "models": models, "trusted_keys": trust, "signers": signer_config, "sources": sources,
        "precedent_snapshot": {"path": str(corpus_path.relative_to(root)),
                               "sha256": hashlib.sha256(corpus_path.read_bytes()).hexdigest()},
        "collectors": collectors, "http_collectors": [],
        "expected_heads": {args.investigation_id: head},
        "qualification_report": "", "result_decisions": {}, "conclusion_decisions": {},
        "reviewer_ui": {"show_sensitive_evidence": False, "show_raw_model_io": False,
                        "allow_trace_download": False, "reveal_on_request": True,
                        "access_token_env": args.reviewer_token_env},
    })
    if args.reconcile:
        from governance.production.reconciliation import validate_map
        mapping = {}
        for item in args.reconcile:
            element, codes = split_pair(item, "--reconcile")
            if element not in {e[0] for e in elements}:
                raise ValueError(f"--reconcile names {element}, which is not one of the obligations")
            mapping[element] = [c.strip() for c in codes.split(",") if c.strip()]
        validate_map(mapping)
        template["reconciliation_map"] = {args.control: mapping}
        template["deterministic_completion"] = not args.no_deterministic_completion
    if args.no_model_stages:
        if not args.reconcile:
            raise ValueError("--no-model-stages needs --reconcile, so the record can be built from the tests")
        template["model_stages"] = "disabled"
        template["deterministic_completion"] = True
    write_new(output, (json.dumps(template, indent=2) + "\n").encode())
    write_new(workspace / "RETAIN_THIS_HEAD.txt",
              (f"investigation_id: {args.investigation_id}\ninitial_head: {head}\n\n"
               "Keep a copy outside this machine. It is how a rollback of the signed record is detected.\n").encode())

    return {"status": "PILOT_PROVISIONED", "config": str(output), "investigation_id": args.investigation_id,
            "initial_head": head, "synthetic": False, "operation_mode": "evaluation",
            "outcome_available": "PILOT_ATTESTATION (not a sealed governance result)",
            "separation_of_duties": separation,
            "signed_by_owner": [f"scope of {args.investigation_id}"],
            "signed_by_governance": [f"internal source {source_id} @ {args.policy_version}",
                                     f"{len(elements)} obligation(s)",
                                     f"precedent corpus with {len(precedents)} record(s)"],
            "service_identities": len(SERVICE_ROLES),
            "reviewer_access": f"set {args.reviewer_token_env} before opening the reviewer app",
            "deployment_authorized": False}


# --------------------------------------------------------------------------
# verify
# --------------------------------------------------------------------------

def verify(args) -> dict:
    from governance.operations.runtime import doctor
    path = Path(args.config).expanduser().resolve(strict=True)
    config, root = json.loads(path.read_text()), path.parent
    findings, warnings = [], []
    if config.get("deployment_profile") != "pilot":
        findings.append("not a pilot configuration")
    if config.get("operation_mode") != "evaluation":
        findings.append("pilot configurations run in evaluation mode")
    workspace = root.resolve()
    for role in HUMAN_ROLES:
        item = config.get("signers", {}).get(role)
        if not item:
            findings.append(f"no {role} identity")
            continue
        key = Path(item["private_key_file"]).expanduser().resolve()
        if key.is_relative_to(workspace) or key.is_relative_to(PACKAGE):
            findings.append(f"{role} key is inside the pilot configuration directory or the package")
        if config["trusted_keys"].get(item["key_id"], {}).get("actor_type") != "human":
            findings.append(f"{role} identity is not marked human")
    for role in SERVICE_ROLES:
        if config["trusted_keys"].get(config["signers"][role]["key_id"], {}).get("actor_type") != "service":
            findings.append(f"{role} identity is not a service identity")
    models = config.get("models", {})
    if models.get("examine", {}).get("model") == models.get("challenge", {}).get("model"):
        warnings.append("examine and challenge use the same model; the challenge is not independent judgment")
    if config.get("separation_of_duties") == "SINGLE_REVIEWER_PILOT":
        warnings.append("one person owns scope, approves sources and attests; acceptable for a pilot, not for reliance")
    token_env = config.get("reviewer_ui", {}).get("access_token_env")
    if token_env and not os.environ.get(token_env):
        warnings.append(f"{token_env} is not set; the reviewer app will stay locked")
    readiness = doctor(config, root)
    return {"status": "PILOT_READY" if not findings and not readiness["blockers"] else "BLOCKED",
            "findings": findings, "warnings": warnings, "readiness_blockers": readiness["blockers"],
            "separation_of_duties": config.get("separation_of_duties")}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    k = sub.add_parser("keygen", help="create your own signing key, outside the package")
    k.add_argument("--out", required=True)
    k.set_defaults(func=keygen)

    p = sub.add_parser("provision", help="create a pilot workspace and one runnable investigation")
    p.add_argument("--output-config", required=True)
    p.add_argument("--template", default=str(ROOT / "config/programme_operations.json"))
    p.add_argument("--investigation-id", required=True)
    p.add_argument("--confirm", required=True, help="repeat the investigation id to authorise it")
    p.add_argument("--system-id", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--period", required=True, help="timezone-aware ISO timestamp")
    p.add_argument("--framework", required=True)
    p.add_argument("--control", required=True)
    p.add_argument("--criticality", choices=["low", "medium", "high"], default="high")
    p.add_argument("--boundary", default="Supplied exports for the stated system, version and period only")
    p.add_argument("--requirement-version", required=True)
    p.add_argument("--policy", required=True, help="internal policy document the obligations come from")
    p.add_argument("--policy-version", required=True)
    p.add_argument("--element", action="append", help="operating obligation ID=TEXT (repeatable)")
    p.add_argument("--design-element", action="append", help="design obligation ID=TEXT (repeatable)")
    p.add_argument("--evidence", action="append", help="UTF-8 export [ID=]PATH (repeatable)")
    p.add_argument("--precedents", help="JSON list of precedent records; default is an empty approved corpus")
    for role in ("owner", "governance", "approver"):
        p.add_argument(f"--{role}-key", required=True)
        p.add_argument(f"--{role}-name", required=True)
    p.add_argument("--model", help="model for all four judgment stages")
    for stage in ("examine", "explain", "plan", "challenge"):
        p.add_argument(f"--{stage}-model")
    p.add_argument("--reviewer-token-env", default="GAAR_REVIEWER_TOKEN")
    p.add_argument("--no-model-stages", action="store_true",
                   help="pilot setting: call no model; build the record from the deterministic tests and D8 (needs --reconcile)")
    p.add_argument("--no-deterministic-completion", action="store_true",
                   help="leave runs at ACTION_REQUIRED when a model stage fails, instead of finishing on tests + D8")
    p.add_argument("--reconcile", action="append",
                   help="D8: OBLIGATION_ID=CODE,CODE — deterministic finding codes that test this obligation (repeatable)")
    p.set_defaults(func=provision)

    v = sub.add_parser("verify", help="check a pilot configuration")
    v.add_argument("--config", required=True)
    v.set_defaults(func=verify)

    args = parser.parse_args()
    result = args.func(args)
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") in {"KEY_CREATED", "PILOT_PROVISIONED", "PILOT_READY"} else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "reason": f"{type(exc).__name__}: {exc}"}), file=sys.stderr)
        raise SystemExit(2)
