"""One constructed quarter, end to end, through all four modules. Every input is constructed and labelled so.

    python -m governance.raas.demo            (prints the result packs)

Every run writes to its own fresh folder, never to the real RaaS ledgers (GAAR_RAAS_HOME / ~/gaar-raas): constructed
records must not sit beside real ones, and a second run must not collide with the first (its proposal id is the
publication's hash, so the same items would already be decided).

Two vendor agents are verified on the same sealed cases: a careful one (the pilot's own deterministic checks, reading
only the prompt) and a hasty one (it approves any change that has a ticket). The careful one earns a warranty; the
hasty one shows why a warranty must read a measured rate.
"""
from __future__ import annotations

import json
import re
import tempfile

from governance.arena.contestants import _rules

from . import closure, reg_to_control, verifier, warranty
from .result import result_pack

SAMPLE_PUBLICATION = """CONSTRUCTED SAMPLE CIRCULAR - NOT A MAS PUBLICATION. Written for the RaaS demonstration only.

Circular on AI change and third-party oversight (sample)

1. Scope. This sample circular applies to financial institutions that deploy AI systems in production.

2. Change management. Financial institutions must ensure that every change to an AI model or its configuration is \
supported by a documented impact assessment, tested before deployment, approved by an authorised person and traceable \
from request to release.

3. Monitoring. Financial institutions should monitor deployed AI systems for performance drift and incidents, with \
defined thresholds that trigger revalidation and escalation.

4. Third parties. Financial institutions are expected to perform risk-based due diligence on third-party AI providers, \
with contractual rights to audit and to receive notice of material model changes.

5. Agent kill switch drills. Institutions shall rehearse, at least twice a year, the halting of every autonomous agent \
in production, and keep a dated log of each rehearsal.
"""


def _records(prompt: str) -> dict:
    return json.loads(prompt.split("RECORDS:\n", 1)[1])


def careful_agent(prompt: str) -> str:
    """Reads only the prompt, and applies the pilot's deterministic checks to the records in it."""
    return json.dumps(_rules({"records": _records(prompt)}))


def hasty_agent(prompt: str) -> str:
    """Approves anything with a ticket. The kind of agent a warranty must not be issued on."""
    ok = isinstance(_records(prompt)["ticket"], dict)
    return json.dumps({"answer": "SUPPORTED" if ok else "CONTRADICTED", "confidence": 0.9})


def run(path=None, as_of: str = "2026-12-24") -> dict:
    path = path or tempfile.mkdtemp(prefix="gaar-raas-demo-")
    controls = [f"CHG-{i:02d}" for i in range(1, 41)]            # one change-management family of 40 controls

    # M1: the circular becomes proposed amendments and additions; one person decides each item.
    prop = reg_to_control.propose(SAMPLE_PUBLICATION, "MAS", "Sample circular on AI change and third-party oversight",
                                  "CONSTRUCTED/2026/01", path=path)
    for item in prop["items"]:
        reg_to_control.decide(prop["proposal_id"], item["item_id"], "ACCEPT", "Tan Wei Ling", SAMPLE_PUBLICATION,
                              note="read against the quoted passage", path=path)
    signed = reg_to_control.control_set(prop["proposal_id"], path=path)

    # M2: both vendor agents answer the same 100 sealed cases.
    careful = verifier.verify(careful_agent, "vendor-a:careful", 100, seed=11, sponsor="AI vendor A", path=path)
    hasty = verifier.verify(hasty_agent, "vendor-b:hasty", 100, seed=11, sponsor="AI vendor B", path=path)

    # M3: six exceptions from the careful agent's flags go through the desk.
    flagged = careful["flagged_cases"][:6]
    ids = [f"EXC-{i + 1:02d}" for i in range(len(flagged))]
    for eid, case_id, ctl in zip(ids, flagged, controls):
        closure.open_exception(eid, ctl, f"unauthorised production change ({case_id})", careful["verification_id"],
                               path=path)
        closure.assign(eid, "Rajesh Kumar", "Tan Wei Ling", path=path)
    for eid in ids[:4]:
        closure.evidence_fix(eid, f"CR-{eid}-fix", "Rajesh Kumar", path=path)
        closure.retest(eid, "PASS", "Siti Rahman", path=path)
    closure.evidence_fix(ids[4], f"CR-{ids[4]}-fix", "Rajesh Kumar", path=path)
    closure.retest(ids[4], "FAIL", "Siti Rahman", note="rollback evidence missing", path=path)
    closure.evidence_fix(ids[4], f"CR-{ids[4]}-fix2", "Rajesh Kumar", path=path)
    closure.retest(ids[4], "PASS", "Siti Rahman", path=path)
    closure.accept_risk(ids[5], "Lim Mei Hua", "legacy batch job retired in Q1; compensating daily review",
                        "2027-03-31", as_of=as_of, path=path)
    desk = closure.summary(as_of=as_of, path=path)

    # M4: a warranty only where the measured rate qualifies.
    fee = warranty.price(controls=len(controls), exceptions_closed=desk["billable"], reg_changes=1)["total"]
    packs = []
    for v in (careful, hasty):
        try:
            cert, why = warranty.issue(f"ORD-{v['agent']}", controls, v, fee, "Tan Wei Ling", "2026-12-31", path=path), ""
        except ValueError as refusal:
            cert, why = None, str(refusal)
        packs.append(result_pack(f"ORD-{v['agent']}", "Change management", "2026-Q4", controls, [signed], v, desk,
                                 cert, why))
    return {"ledger_folder": str(path), "provenance": "Constructed end to end: sample circular, twin cases, named people are fictional.",
            "proposal": prop, "signed_control_set": signed, "verifications": [careful, hasty], "closure": desk,
            "packs": packs}


if __name__ == "__main__":
    out = run()
    print(json.dumps({"ledger_folder": out["ledger_folder"], "packs": [{k: p[k] for k in ("order_id", "status", "verification", "invoice")} for p in out["packs"]],
                      "reg_change": out["proposal"]["counts"], "closure": {k: v for k, v in out["closure"].items()
                                                                           if k != "exceptions"}}, indent=1))
