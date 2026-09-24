#!/usr/bin/env python3
"""One-command, offline, explicitly SYNTHETIC eight-stage investigation.

Keys are ephemeral and fixture-only. No human approval, live model, production
attestation or deployment authorization is claimed or manufactured.
"""
from __future__ import annotations
import argparse
import base64
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from governance.result_contract import CanonicalSigner
from governance.investigation import InvestigationEngine, InvestigationStore
from governance.investigation.contracts import *
from governance.investigation.service import sha_bytes, resolve_question
from governance.investigation.agents import challenge, conclude_blocked_by_policy
from governance.investigation import admit_segments


def fixture_environment(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    signers, trust = {}, {}
    for role in ("owner", "governance", "assessor", "test_planner", "executor", "challenger", "decision"):
        signer = CanonicalSigner.from_base64("synthetic-" + role, base64.b64encode(os.urandom(32)).decode())
        signers[role] = signer
        trust[signer.key_id] = {"actor": "SYNTHETIC-" + role, "actor_type": "service",
            "public_key": signer.public_key_b64, "roles": [role], "allow_auto_block": role == "decision"}
    sources = {"INTERNAL-DEMO": {"sha256": sha_bytes(b"synthetic inventory and management policy"), "version": "demo-v1", "authority": "internal"}}
    config = {"store": "investigations.sqlite", "trusted_keys": trust, "sources": sources}
    (directory / "public_config.json").write_text(json.dumps(config, indent=2))
    return InvestigationEngine(InvestigationStore(directory / config["store"], trust), sources), signers


def prepare(engine, signers, iid="SYNTHETIC-WB140", *, missing=False, wrong_purpose=False,
            unavailable=False, not_evaluated=False, unknown_tool=False, stop="plan", scenario="asset"):
    scope = Scope(system_id="credit-platform-v2.3", version="2.3", period="2026-09-20T00:00:00Z")
    control_id = "CHANGE.MGMT" if scenario == "change" else "ASSET.INVENTORY"
    ctx = InvestigationContext(investigation_id=iid, control_id=control_id, framework="INTERNAL-DEMO",
        requirement_version="demo-v1", scope=scope, boundary="Synthetic credit platform exports only",
        owner="SYNTHETIC-owner", criticality="high", synthetic=True)
    engine.append(iid, "understand", ctx, signers["owner"])
    exps = ApplicableExpectations(requirement_version="demo-v1", elements=tuple(
        Expectation(element_id=eid, text=text, source_id="INTERNAL-DEMO",
          source_sha256=engine.source_registry["INTERNAL-DEMO"]["sha256"], source_version="demo-v1",
          authority="internal", purpose=purpose, applies=True, applicability_reason="Synthetic demonstration scope")
        for eid, text, purpose in (("e1", "Reconcile observed changes against approved scope, timing, credentials and recovery" if scenario == "change" else "Reconcile actual discovered asset identities with inventory", "operating"),
                                   ("e2", "Define change authorization policy" if scenario == "change" else "Define asset ownership policy", "design"))))
    engine.append(iid, "expectations", exps, signers["governance"])
    package = {"synthetic": True, "snapshots": {name: {"scope": scope.system_id, "as_of": scope.period,
          "source_id": "SYNTHETIC-" + name, "assets": ids} for name, ids in {
          "inventory": ["a", "b", "retired"], "discovery": ["a", "b", "c"],
          "configuration": ["a", "b"], "vulnerability": ["a", "b"]}.items()}}
    if scenario == "change":
        from tools.wb140_change_fixture import package as change_package
        package = change_package()
    operating = json.dumps(package, sort_keys=True)
    policy = ("SYNTHETIC POLICY: Approve change scope, implementer, credential and implementation window before execution."
              if scenario == "change" else "SYNTHETIC POLICY: Assign a responsible owner to each asset.")
    source = operating + "\n" + policy
    segments = [] if missing else [{"start": 0, "end": len(operating), "evidence_id": "E1",
         "element_ids": ["e1"], "purposes": ["design_statement"] if wrong_purpose else ["operating_record", "gap"],
         "finding_status": "gap_identified"}]
    segments.append({"start": len(operating) + 1, "end": len(source), "evidence_id": "E2",
        "element_ids": ["e2"], "purposes": ["design_statement"], "finding_status": "supports"})
    evidence = admit_segments(source_bytes=source.encode(),
        source_sha256=sha_bytes(source.encode()), source_id="SYNTHETIC-mixed-source", scope=scope,
        expected_scope=scope, segments=segments, authority="internal", provenance=("synthetic-generator", "frozen-export"))
    state = "NOT_EVALUATED" if not_evaluated else "NOT_EVIDENCED" if missing else "CONTRADICTED"
    exam = EvidenceExamination(evidence=evidence, findings=(
        Examination(element_id="e1", status=state, evidence_refs=() if missing else ("E1",), rationale="Missing records or identity discrepancy in supplied scope"),
        Examination(element_id="e2", status="SUPPORTED", evidence_refs=("E2",), rationale="Design policy present")))
    engine.append(iid, "examine", exam, signers["assessor"])
    if stop == "examine":
        return iid
    providers = {name: (lambda q: []) for name in ("expectations", "facts", "dependencies", "counterevidence", "procedures", "precedents")}
    if unavailable:
        def failed(q):
            raise RuntimeError("synthetic collector unavailable")
        providers["counterevidence"] = failed
    lanes = resolve_question({"scope": scope.model_dump()}, providers)
    basis = ("gap:e1",) if missing else ("E1",)
    explanations = ExplanationSet(status="COMPLETED", retrieval=lanes,
        dependencies=(Dependency(dependency_id="D1", upstream=control_id, downstream="SECURITY.LOGGING" if scenario == "change" else "ASSET.PATCH",
            relation="Unauthorized changes can alter security logging and weaken detection" if scenario == "change" else "Incomplete inventory can invalidate management-coverage denominators; no automatic failure propagation",
            basis_refs=basis, status="hypothesis"),),
        hypotheses=(Explanation(hypothesis_id="H1", claim="Observed changes may exceed authorized timing, scope or credentials" if scenario == "change" else "Inventory discrepancies may coincide with management coverage gaps",
            basis_refs=basis, alternatives=("Valid preauthorized emergency procedure", "Clock or identity mapping errors") if scenario == "change" else ("Retired or ephemeral assets", "Export timing or collection failure"),
            compensating_controls_review="Examine just-in-time access, independent deployment records and logging retention" if scenario == "change" else "Check independent discovery and endpoint coverage; no compensating effectiveness established",
            dependencies=("D1",), material=True),),
        limitations=("Synthetic exports; no live asset condition established",))
    engine.append(iid, "explain", explanations, signers["assessor"])
    plan = TestPlan(policy_id="SYNTHETIC-read-only-policy", no_test_rationale="Operating export unavailable" if missing else "",
        tests=() if missing else (TestProposal(test_id="T1", hypothesis_id="H1", tool="unknown" if unknown_tool else "change_reconciliation" if scenario == "change" else "asset_reconciliation",
            version="1", input_ref="E1", decision_impact="Test actual implementation against authorization and recovery records" if scenario == "change" else "Distinguish equal counts from matching identities and management coverage",
            priority=1),))
    engine.append(iid, "plan", plan, signers["test_planner"])
    return iid


def finish(engine, signers, iid, *, conclude=True):
    engine.execute_plan(iid, signers["executor"])
    context = engine.challenge_input(iid)
    record = context["record"]
    refs = tuple(e["evidence_id"] for e in record["examine"]["evidence"]) + tuple(h["hypothesis_id"] for h in record["explain"]["hypotheses"]) + tuple(t["test_id"] for t in record["verify"]["tests"])
    # Scripted independent-role fixture, explicitly not a live model evaluation.
    response = ChallengeRecord(status="COMPLETED", input_head=context["input_head"], reviewed_refs=refs,
        disproof_attempts=("Examined proposed alternate explanations against scoped input records and the test's export-only limitation",),
        missing_explanations=("Real source authenticity and collector-health corroboration unavailable in fixture",),
        findings=(ChallengeFinding(finding_id="C1", material=True,
            claim="Export reconciliation does not establish source authenticity or full collection coverage", basis_refs=("H1",)),))
    challenge(engine, iid, signers["challenger"], lambda prompt: response.model_dump_json())
    if conclude:
        conclude_blocked_by_policy(engine, iid, signers["decision"])
    return engine.gate(iid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("governance/wb140_demo"))
    args = parser.parse_args()
    # Each run gets a fresh journal; never overwrite a previous signed investigation.
    args.output_root.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="run-", dir=args.output_root))
    engine, signers = fixture_environment(run)
    iid = prepare(engine, signers)
    result = finish(engine, signers, iid)
    rows, values = engine.snapshot(iid, result["head"])
    (run / "signed_investigation.json").write_text(json.dumps(rows, indent=2))
    (run / "result.json").write_text(json.dumps(result, indent=2))
    change_id = prepare(engine, signers, iid="SYNTHETIC-WB140-CHANGE", scenario="change")
    change_result = finish(engine, signers, change_id)
    (run / "signed_change_investigation.json").write_text(json.dumps(engine.snapshot(change_id)[0], indent=2))
    (run / "change_result.json").write_text(json.dumps(change_result, indent=2))
    print(json.dumps({"synthetic": True, "model": "SCRIPTED_FIXTURE", "result": result, "change_result": change_result,
                      "artifacts": str(run.resolve())}, indent=2))
    return 0 if result["assessment_finalizable"] and not result["deployment_authorized"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
