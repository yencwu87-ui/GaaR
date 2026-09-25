"""Result as a Service (kit v31): the four modules, the chain between them, and every refusal they can make.

Each refusal test expects the whole message, anchored, so a guard that stops firing fails its test."""
import json
import re

import pytest

from governance.raas import closure, demo, reg_to_control as m1, verifier, warranty
from governance.raas.result import result_pack

PUB = demo.SAMPLE_PUBLICATION


def refused(exc, message):
    return pytest.raises(exc, match="^" + re.escape(message) + "$")


# ---------- the whole chain ----------

def test_a_constructed_quarter_runs_through_all_four_modules():
    out = demo.run()
    careful, hasty = out["packs"]
    assert careful["status"]["headline"] == "Warranted Control Period"
    assert careful["invoice"]["total"] == 40 * 1500 + 6 * 800 + 2000
    assert hasty["status"]["headline"] == "Complete, not warranted"
    assert hasty["status"]["not_warranted_reason"].startswith("false-assurance rate 0.940 is above")
    assert all(line["unit"] != "control_assured" for line in hasty["invoice"]["lines"])   # no warranty, no control fee
    assert out["closure"]["closed_by_retest"] == 5 and out["closure"]["risk_accepted"] == 1
    assert out["closure"]["reopened_after_failed_retest"] == 1
    assert careful["verification"]["provenance"].startswith("Ground truth: constructed digital-twin cases")


def test_the_demo_runs_twice_and_never_writes_the_real_ledgers(tmp_path, monkeypatch):
    real = tmp_path / "real-raas"
    monkeypatch.setenv("GAAR_RAAS_HOME", str(real))
    first, second = demo.run(), demo.run()
    assert first["ledger_folder"] != second["ledger_folder"]
    assert second["packs"][0]["status"]["headline"] == "Warranted Control Period"
    assert not real.exists()


# ---------- M1 Reg-to-Control ----------

def test_m1_reads_obligations_amends_the_right_controls_and_proposes_what_is_new():
    p = m1.propose(PUB, "MAS", "Sample", "CONSTRUCTED/1")
    by = {i["control_id"]: i for i in p["items"]}
    assert {"M3.12", "M3.10", "M3.14", "MAS-NEW-1"} == set(by)
    assert by["M3.12"]["action"] == "AMEND" and by["MAS-NEW-1"]["action"] == "ADD"
    assert p["retirements_proposed"] == 0
    for i in p["items"]:                                       # every quote is the publication at its offsets
        assert " ".join(PUB[i["start"]:i["end"]].split()) == i["quote"]


def test_m1_control_set_is_signed_only_when_every_item_is_decided_by_a_person():
    p = m1.propose(PUB, "MAS", "Sample", "CONSTRUCTED/1")
    first, *rest = p["items"]
    m1.decide(p["proposal_id"], first["item_id"], "REJECT", "Tan Wei Ling", PUB)
    with refused(ValueError, f"the control set is not signed: {len(rest)} item(s) undecided"):
        m1.control_set(p["proposal_id"])
    for i in rest:
        m1.decide(p["proposal_id"], i["item_id"], "ACCEPT", "Tan Wei Ling", PUB)
    signed = m1.control_set(p["proposal_id"])
    assert signed["status"] == "SIGNED" and signed["rejected"] == 1 and len(signed["accepted"]) == len(rest)


def test_m1_refusals():
    with refused(ValueError, "no control contracts for framework NOPE"):
        m1.propose(PUB, "NOPE", "t", "r")
    with refused(ValueError, "there is no publication text to read"):
        m1.propose("  ", "MAS", "t", "r")
    with refused(ValueError, "a proposal needs the publication's title and reference"):
        m1.propose(PUB, "MAS", "", "r")
    with refused(ValueError, "the publication states no obligation this module can read: a person must review it"):
        m1.propose("This note describes the market. It records no requirement.", "MAS", "t", "r")
    p = m1.propose(PUB, "MAS", "Sample", "CONSTRUCTED/1")
    item = p["items"][0]["item_id"]
    with refused(ValueError, "decision must be one of ACCEPT, REJECT"):
        m1.decide(p["proposal_id"], item, "MAYBE", "Tan Wei Ling", PUB)
    with refused(ValueError, "'Your Name' is a placeholder, not a name: record the person's own name"):
        m1.decide(p["proposal_id"], item, "ACCEPT", "Your Name", PUB)
    with refused(ValueError, "no proposal RCP-missing"):
        m1.decide("RCP-missing", item, "ACCEPT", "Tan Wei Ling", PUB)
    with refused(ValueError, f"proposal {p['proposal_id']} has no item Ixxxx"):
        m1.decide(p["proposal_id"], "Ixxxx", "ACCEPT", "Tan Wei Ling", PUB)
    with refused(ValueError, "the publication text differs from the one this proposal was made from"):
        m1.decide(p["proposal_id"], item, "ACCEPT", "Tan Wei Ling", PUB + " ")
    m1.decide(p["proposal_id"], item, "ACCEPT", "Tan Wei Ling", PUB)
    with refused(ValueError, f"item {item} was already decided by Tan Wei Ling"):
        m1.decide(p["proposal_id"], item, "REJECT", "Lim Mei Hua", PUB)
    with refused(ValueError, "bulk sign-off is refused: decide each proposed control change on its own record, "
                             "after reading its passage"):
        m1.decide_all(p["proposal_id"], "ACCEPT", "Tan Wei Ling")


# ---------- M2 Outcome Verifier ----------

def test_m2_the_agent_sees_the_prompt_only_and_the_answer_key_stays_sealed():
    seen = []
    verifier.verify(lambda prompt: seen.append(prompt) or demo.careful_agent(prompt), "probe", 100, seed=3)
    assert len(seen) == 100 and all(isinstance(s, str) for s in seen)
    assert not any("CONTRADICTED\"" in s.split("RECORDS:")[1] or "known_blind" in s or "answer_key" in s for s in seen)


def test_m2_rates_are_published_with_their_sample_and_upper_bound():
    v = verifier.verify(demo.careful_agent, "careful", 100, seed=11)
    assert (v["planted"], v["false_assurance"], v["far"]) == (50, 0, 0.0)
    assert v["far_upper"] == pytest.approx(0.0582, abs=1e-3)             # 0 of 50 still allows up to 5.8%
    h = verifier.verify(demo.hasty_agent, "hasty", 100, seed=11)
    assert h["far"] > 0.9 and h["recall"] < 0.1
    assert [r["agent"] for r in verifier.verifications()] == ["careful", "hasty"]


def test_m2_a_reply_that_is_not_text_or_lacks_a_confidence_is_a_hold_not_an_assurance():
    v = verifier.verify(lambda p: {"answer": "SUPPORTED"}, "dict-replier", 100, seed=5)
    assert v["holds"] == 100 and v["false_assurance"] == 0 and v["recall"] == 0.0
    v = verifier.verify(lambda p: json.dumps({"answer": "SUPPORTED"}), "no-confidence", 100, seed=5)
    assert v["holds"] == 100


def test_m2_upper_bound_behaves_at_the_edges():
    assert verifier.far_upper_bound(5, 5) == 1.0
    assert verifier.far_upper_bound(0, 300) < 0.01                      # ~300 clean planted cases to show below 1%
    assert verifier.far_upper_bound(0, 50) > 0.05


def test_m2_refusals():
    with refused(TypeError, "an agent is a callable that takes a prompt and returns its reply text"):
        verifier.verify("not-an-agent", "x")
    with refused(ValueError, "a verified agent needs a name, so its rate can be traced to it"):
        verifier.verify(demo.careful_agent, " ")
    with refused(ValueError, "too few planted defects to publish a false-assurance rate: 20 planted, 50 needed"):
        verifier.verify(demo.careful_agent, "careful", 40)
    with refused(ValueError, "an upper bound needs at least one planted defect"):
        verifier.far_upper_bound(0, 0)


# ---------- M3 Closure Desk ----------

def _opened(eid="EXC-1"):
    closure.open_exception(eid, "CHG-01", "unapproved change", "VER-x")
    closure.assign(eid, "Rajesh Kumar", "Tan Wei Ling")
    return eid


def test_m3_closed_means_an_independent_retest_passed():
    eid = _opened()
    closure.evidence_fix(eid, "CR-1", "Rajesh Kumar")
    assert closure.retest(eid, "FAIL", "Siti Rahman")["state"] == "ASSIGNED"          # reopened
    closure.evidence_fix(eid, "CR-2", "Rajesh Kumar")
    assert closure.retest(eid, "PASS", "Siti Rahman")["state"] == "CLOSED"
    s = closure.summary()
    assert (s["closed_by_retest"], s["billable"], s["reopened_after_failed_retest"]) == (1, 1, 1)


def test_m3_an_expired_risk_acceptance_is_an_open_exception_again():
    eid = _opened()
    closure.accept_risk(eid, "Lim Mei Hua", "compensating control", "2027-01-31", as_of="2026-12-01")
    assert closure.state(eid, as_of="2027-01-15")["state"] == "RISK_ACCEPTED"
    later = closure.summary(as_of="2027-02-01")
    assert later["still_open"] == 1 and later["billable"] == 0 and later["expired_acceptances"] == 1


def test_m3_refusals():
    with refused(ValueError, "no exception EXC-9 on the closure desk"):
        closure.state("EXC-9")
    with refused(ValueError, "an exception needs the finding and the source that raised it"):
        closure.open_exception("EXC-1", "CHG-01", " ", "VER-x")
    eid = _opened()
    with refused(ValueError, "exception EXC-1 is already on the closure desk"):
        closure.open_exception(eid, "CHG-01", "again", "VER-x")
    with refused(ValueError, "EXC-1 is ASSIGNED: it cannot be retested"):
        closure.retest(eid, "PASS", "Siti Rahman")
    with refused(ValueError, "only the assigned owner (Rajesh Kumar) evidences the fix"):
        closure.evidence_fix(eid, "CR-1", "Siti Rahman")
    with refused(ValueError, "a fix needs a reference to its evidence"):
        closure.evidence_fix(eid, " ", "Rajesh Kumar")
    with refused(ValueError, "a risk acceptance needs an approver other than the control owner"):
        closure.accept_risk(eid, "Rajesh Kumar", "r", "2027-01-31", as_of="2026-12-01")
    with refused(ValueError, "a risk acceptance needs its reason on record"):
        closure.accept_risk(eid, "Lim Mei Hua", " ", "2027-01-31", as_of="2026-12-01")
    with refused(ValueError, "a risk acceptance must expire after 2026-12-01 and no later than 2027-12-01"):
        closure.accept_risk(eid, "Lim Mei Hua", "r", "2028-06-30", as_of="2026-12-01")
    closure.evidence_fix(eid, "CR-1", "Rajesh Kumar")
    with refused(ValueError, "EXC-1 is FIX_EVIDENCED: it cannot be assigned"):
        closure.assign(eid, "Rajesh Kumar", "Tan Wei Ling")
    with refused(ValueError, "a retest result is PASS or FAIL"):
        closure.retest(eid, "LOOKS OK", "Siti Rahman")
    with refused(ValueError, "the retest must be performed by someone other than the owner who fixed it"):
        closure.retest(eid, "PASS", "Rajesh Kumar")
    with refused(ValueError, "'owner' is a placeholder, not a name: record the person's own name"):
        closure.retest(eid, "PASS", "owner")


# ---------- M4 Assurance Warranty ----------

def _cert(fee=66800):
    v = verifier.verify(demo.careful_agent, "careful", 100, seed=11)
    return warranty.issue("ORD-1", ["CHG-01", "CHG-02", "CHG-03", "CHG-04", "CHG-05"], v, fee, "Tan Wei Ling",
                          "2026-12-31")


def test_m4_pricing_is_by_outcome_unit():
    bill = warranty.price(controls=40, exceptions_closed=6, reg_changes=2)
    assert bill["total"] == 68800 and bill["currency"] == "SGD"
    assert [l["unit"] for l in bill["lines"]] == ["control_assured", "exception_closed", "regulatory_change"]


def test_m4_claims_pay_to_the_cap_and_no_further():
    cert = _cert()
    assert (cert["refund_per_control"], cert["cap"], cert["claims_until"]) == (4500, 16700.0, "2027-12-31")
    paid = [warranty.claim(cert["certificate_id"], c, f"IA-{c}", "2027-03-01", "Lim Mei Hua", "Siti Rahman")["payout"]
            for c in ("CHG-01", "CHG-02", "CHG-03", "CHG-04")]
    assert paid == [4500, 4500, 4500, 3200]
    with refused(ValueError, "the warranty cap is exhausted"):
        warranty.claim(cert["certificate_id"], "CHG-05", "IA-5", "2027-03-01", "Lim Mei Hua", "Siti Rahman")


def test_m4_certificate_states_the_basis_of_its_eligibility():
    # Eligibility reads the point rate; the certificate says so and says what the upper bound would have decided.
    cert = _cert()
    assert cert["far"] == 0 and cert["far_upper"] > 0.01
    assert cert["eligibility_basis"] == (f"point estimate 0.000; its 95% upper bound {cert['far_upper']:.3f} is above "
                                         f"the 0.010 threshold")
    tight = warranty._eligibility_basis({"far": 0.0, "far_upper": 0.005}, 0.01)
    assert tight == "point estimate 0.000; its 95% upper bound 0.005 is also within the 0.010 threshold"
    assert warranty._eligibility_basis({"far": 0.0}, 0.01) == "point estimate; no upper bound was published with this rate"


def test_m4_refusals():
    v = verifier.verify(demo.careful_agent, "careful", 100, seed=11)
    h = verifier.verify(demo.hasty_agent, "hasty", 100, seed=11)
    with refused(ValueError, "a warranty covers named controls: the scope is empty"):
        warranty.issue("ORD-1", [], v, 1000, "Tan Wei Ling", "2026-12-31")
    with refused(ValueError, "no measured false-assurance rate: the warranty cannot be issued"):
        warranty.issue("ORD-1", ["CHG-01"], {}, 1000, "Tan Wei Ling", "2026-12-31")
    with refused(ValueError, "false-assurance rate 0.940 is above the 0.010 eligibility threshold: no warranty"):
        warranty.issue("ORD-1", ["CHG-01"], h, 1000, "Tan Wei Ling", "2026-12-31")
    with refused(ValueError, "a warranty needs the name of the person issuing it"):
        warranty.issue("ORD-1", ["CHG-01"], v, 1000, "", "2026-12-31")
    cert = _cert()
    cid = cert["certificate_id"]
    with refused(ValueError, "no warranty WAR-missing"):
        warranty.claim("WAR-missing", "CHG-01", "IA", "2027-03-01", "Lim Mei Hua", "Siti Rahman")
    with refused(ValueError, "a claim must be assessed by someone other than the claimant"):
        warranty.claim(cid, "CHG-01", "IA", "2027-03-01", "Lim Mei Hua", "Lim Mei Hua")
    with refused(ValueError, "CHG-99 is not in this warranty's scope"):
        warranty.claim(cid, "CHG-99", "IA", "2027-03-01", "Lim Mei Hua", "Siti Rahman")
    with refused(ValueError, "a claim needs evidence that the control was not effective in the period"):
        warranty.claim(cid, "CHG-01", " ", "2027-03-01", "Lim Mei Hua", "Siti Rahman")
    with refused(ValueError, "a claim must be discovered between 2026-12-31 and 2027-12-31"):
        warranty.claim(cid, "CHG-01", "IA", "2028-02-01", "Lim Mei Hua", "Siti Rahman")
    warranty.claim(cid, "CHG-01", "IA", "2027-03-01", "Lim Mei Hua", "Siti Rahman")
    with refused(ValueError, "CHG-01 has already been refunded under this warranty"):
        warranty.claim(cid, "CHG-01", "IA-2", "2027-04-01", "Lim Mei Hua", "Siti Rahman")


def test_result_pack_with_open_exceptions_is_incomplete():
    v = verifier.verify(demo.careful_agent, "careful", 100, seed=11)
    _opened()
    pack = result_pack("ORD-1", "Change management", "2026-Q4", ["CHG-01"], [], v, closure.summary(), None, "not issued")
    assert pack["status"]["headline"] == "Incomplete: exceptions still open"
    assert pack["invoice"]["total"] == 0 and len(pack["params_sha256"]) == 64
