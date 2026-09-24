"""Reference rules for model prompts (Phase 0 defects D11 and D12).

Every rejection of a small model's answer in Phase 0 after the examine fix had
the same cause: the model referred to identifiers outside the set the validator
accepts, because the prompt never listed that set. Explain cited dependency-
catalogue entries where evidence was required (D11). Dependency review referred
to hypothesis, test or evidence ids that did not exist (D12).

These helpers state, for each stage, exactly which identifiers exist in this
investigation and which kinds may be used where. They mirror the validators in
service.py and dependencies.py; they do not relax them, and they never hint at
an answer: no status, finding or expected conclusion is named.
"""
from __future__ import annotations

import json

from governance.investigation.service import LANES, TOOLS

CHANGE_TOOLS = ("change_authorization", "change_segregation", "change_reconciliation")
POPULATION_TOOLS = ("change_population",)


def _ids(items, attr):
    return sorted(getattr(i, attr) for i in items)


def _basis(values):
    evidence = _ids(values["examine"].evidence, "evidence_id")
    gaps = sorted("gap:" + f.element_id for f in values["examine"].findings
                  if f.status in {"NOT_EVIDENCED", "NOT_EVALUATED"})
    return evidence, gaps


def _shape(record):
    try:
        package = json.loads(record.text)
    except ValueError:
        return None
    if isinstance(package, dict) and isinstance(package.get("changes"), list):
        return "change export"
    if isinstance(package, dict) and "primary" in package and "independent" in package:
        return "population export"
    return None


def explain_rules(values):
    evidence, gaps = _basis(values)
    allowed = ", ".join(evidence + gaps)
    rules = [
        f"basis_refs of every dependency and every hypothesis may use only these ids: {allowed}.",
        "Dependency-catalogue candidates and knowledge hashes are NOT valid basis_refs. "
        "They may appear only in the refs of the 'dependencies' retrieval lane.",
        "A hypothesis's dependencies field may name only dependency_ids defined in this same answer.",
        f"Give every one of these retrieval lanes an explicit status: {', '.join(LANES)}.",
        "Every dependency_id and hypothesis_id must be unique.",
    ]
    if not gaps:
        rules.append("No obligation is currently NOT_EVIDENCED or NOT_EVALUATED, so no gap: reference is available.")
    return rules


def plan_rules(values, trust, control_id):
    hypotheses = _ids(values["explain"].hypotheses, "hypothesis_id")
    by_shape = {}
    for record in values["examine"].evidence:
        by_shape.setdefault(_shape(record), []).append(record.evidence_id)
    required = sorted({tuple(x) for policy in trust.values() if "test_planner" in policy.get("roles", [])
                       for x in (policy.get("required_tools_by_control") or {}).get(control_id, [])})
    registered = sorted(TOOLS)
    rules = [
        f"hypothesis_id must be one of: {', '.join(hypotheses)}.",
        f"input_ref must be one admitted evidence id: {', '.join(_ids(values['examine'].evidence, 'evidence_id'))}.",
        "Registered tools and versions: " + ", ".join(f"{t}:{v}" for t, v in registered) + ". Use no other.",
    ]
    if by_shape.get("change export"):
        rules.append(f"{', '.join(t for t in CHANGE_TOOLS if any(t == r[0] for r in registered))} read the change "
                     f"export: {', '.join(by_shape['change export'])}.")
    if by_shape.get("population export"):
        rules.append(f"change_population reads the population export: {', '.join(by_shape['population export'])}. "
                     "It cannot read the change export.")
    if required:
        rules.append("These procedures are mandatory and must appear with required=true: "
                     + ", ".join(f"{t}:{v}" for t, v in required) + ".")
    rules += ["Every test_id must be unique.",
              "Do not plan the same tool on the same input more than once."]
    return rules


def dependency_rules(values, knowledge):
    evidence = _ids(values["examine"].evidence, "evidence_id")
    executed = sorted(t.test_id for t in values["verify"].tests if t.status == "EXECUTED")
    unavailable = sorted(t.test_id for t in values["verify"].tests if t.status != "EXECUTED")
    material = sorted(h.hypothesis_id for h in values["explain"].hypotheses if h.material)
    other = sorted(h.hypothesis_id for h in values["explain"].hypotheses if not h.material)
    rules = [
        "Give exactly one treatment for each edge_id: " + ", ".join(e["edge_id"] for e in knowledge["edges"]) + ".",
        f"knowledge_sha256 must be exactly {knowledge['knowledge_sha256']}.",
        f"evidence_refs may use only: {', '.join(evidence)}.",
        f"test_refs may use only these executed tests: {', '.join(executed) or 'none executed'}."
        + (f" These did not execute and must not be cited: {', '.join(unavailable)}." if unavailable else ""),
        f"risk_refs may use only hypothesis ids: {', '.join(material + other)}"
        + (f" (material: {', '.join(material)})." if material else "."),
        "INVESTIGATED requires at least one evidence_ref and at least one executed test_ref.",
        "NOT_APPLICABLE cannot also be material.",
        "material=true requires at least one risk_ref that is a material hypothesis.",
    ]
    return rules


def challenge_rules(values):
    evidence, gaps = _basis(values)
    hypotheses = _ids(values["explain"].hypotheses, "hypothesis_id")
    tests = _ids(values["verify"].tests, "test_id")
    elements = [e.element_id for e in values["expectations"].elements]
    dependencies = _ids(values["explain"].dependencies, "dependency_id")
    must = evidence + hypotheses + tests
    allowed = must + gaps + elements + dependencies
    return [
        f"reviewed_refs must include every one of: {', '.join(must)}.",
        f"reviewed_refs and every finding's basis_refs may use only: {', '.join(allowed)}.",
        "Every finding_id must be unique.",
    ]
