"""Result as a Service (kit v31): the four modules, the chain between them, and every refusal they can make.

Each refusal test expects the whole message, anchored, so a guard that stops firing fails its test."""
import json
import re
from pathlib import Path

import pytest

from governance.raas import closure, demo, reg_to_control as m1, verifier, warranty
from governance.raas.result import result_pack
from tests.test_guards_exercised import series  # noqa: F401  (fixture)

PUB = demo.SAMPLE_PUBLICATION
ROOT = Path(__file__).resolve().parents[1]


def refused(exc, message):
    return pytest.raises(exc, match="^" + re.escape(message) + "$")


# ---------- the whole chain ----------

def test_a_constructed_quarter_runs_through_all_four_modules():
    out = demo.run()
    careful, hasty = out["packs"]
    assert careful["status"]["headline"] == "Warranted Control Period"
    assert careful["invoice"]["total"] == 40 * 1500 + 6 * 800 + 2000
    assert hasty["status"]["headline"] == "Complete, not warranted"
    assert hasty["status"]["not_warranted_reason"].startswith("the 95% upper bound on the false-assurance rate, ")
    assert hasty["status"]["not_warranted_reason"].endswith("is above 3.00%: NOT_ASSURED, no warranty")
    assert careful["verification"]["planted"] == 500 and careful["warranty"]["tier"] == "WARRANTED"
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
    assert verifier.far_upper_bound(0, 50) > 0.05
    # D33: the exact thresholds against 1%, with the bound rounded up. Rounding half-up had let 471 and 625 pass.
    for misses, first_passing in ((0, 299), (1, 473), (2, 628)):
        assert verifier.far_upper_bound(misses, first_passing) <= 0.01 < verifier.far_upper_bound(misses, first_passing - 1)
    assert verifier.far_upper_bound(1, 471) == 0.0101 and verifier.far_upper_bound(2, 625) == 0.0101
    # 500 planted cases tolerate exactly one miss.
    assert (verifier.far_upper_bound(1, 500), verifier.far_upper_bound(2, 500)) == (0.0095, 0.0126)
    assert verifier.BOUND_METHOD == "Clopper-Pearson exact, one-sided, rounded up to 4 decimals"


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
    closure.rerun(eid, demo.constructed_retest, {"fixed": True}, "Siti Rahman")
    assert closure.retest(eid, "PASS", "Siti Rahman")["state"] == "CLOSED"
    s = closure.summary()
    assert (s["closed_by_retest"], s["billable"], s["reopened_after_failed_retest"]) == (1, 1, 1)


def test_m3_a_pass_needs_a_passing_rerun_made_by_the_desk_on_new_evidence():
    # B1-4: "closed" is never a person's word alone; the desk runs the control test and keeps the receipt.
    closure.open_exception("EXC-1", "CHG-01", "unapproved change", "VER-x", evidence_sha256=closure.evidence_sha256(
        {"fixed": False}))
    closure.assign("EXC-1", "Rajesh Kumar", "Tan Wei Ling")
    with refused(ValueError, "EXC-1 is ASSIGNED: it cannot be rerun"):
        closure.rerun("EXC-1", demo.constructed_retest, {"fixed": True}, "Siti Rahman")
    closure.evidence_fix("EXC-1", "CR-1", "Rajesh Kumar")
    with refused(ValueError, "a retest cannot pass without a rerun: run the control test on the fixed evidence first"):
        closure.retest("EXC-1", "PASS", "Siti Rahman")
    with refused(ValueError, "a rerun needs new evidence: this is the evidence that raised the exception"):
        closure.rerun("EXC-1", demo.constructed_retest, {"fixed": False}, "Siti Rahman")
    with refused(TypeError, "a rerun needs the control test: a callable that takes the evidence and returns its verdict"):
        closure.rerun("EXC-1", "looks fine", {"fixed": True}, "Siti Rahman")
    with refused(ValueError, "the control test returned 'OK': a rerun verdict is PASS or FAIL"):
        closure.rerun("EXC-1", lambda e: {"verdict": "OK"}, {"fixed": True}, "Siti Rahman")
    with refused(ValueError, "a rerun needs the name of the person who ran it"):
        closure.rerun("EXC-1", demo.constructed_retest, {"fixed": True}, " ")
    s = closure.rerun("EXC-1", demo.constructed_retest, {"fixed": False, "attempt": 2}, "Siti Rahman")
    assert s["rerun"]["verdict"] == "FAIL" and s["rerun"]["test"] == "constructed_retest"
    with refused(ValueError, "the rerun's verdict was FAIL: the retest cannot record PASS"):
        closure.retest("EXC-1", "PASS", "Siti Rahman")
    s = closure.retest("EXC-1", "FAIL", "Siti Rahman")
    assert s["state"] == "ASSIGNED"
    closure.evidence_fix("EXC-1", "CR-2", "Rajesh Kumar")
    assert closure.state("EXC-1")["rerun"] is None                    # a new fix needs its own rerun
    receipt = closure.rerun("EXC-1", demo.constructed_retest, {"fixed": True}, "Siti Rahman")["rerun"]
    assert closure.retest("EXC-1", "PASS", "Siti Rahman")["state"] == "CLOSED"
    retested = [r["payload"] for r in closure._ledger().read() if r["payload"]["event"] == "RETESTED"][-1]
    assert retested["rerun_receipt_sha256"] == receipt["receipt_sha256"]


def test_series_findings_open_exceptions_and_the_retest_reruns_the_series_procedure(series):
    # B1-3 and B1-4 on the constructed series: week 1's findings reach the desk once, and a retest is the series'
    # own change_authorization procedure re-run on the owner's corrected export.
    import copy
    from tests.test_inbox_and_scheduler import _ticked
    from governance.raas import series as feed
    home, config_path, _ = _ticked(series, weeks=(1,))
    [week1] = feed.open_from_series(config_path)
    assert week1["period"] == "2026-09-15" and len(week1["opened"]) == 13 and week1["already_open"] == []
    assert feed.open_from_series(config_path)[0] == {"period": "2026-09-15", "opened": [],
                                                     "already_open": week1["opened"]}
    rows = {(r["detail"]["code"], r["detail"]["event_id"]): r for r in closure.summary()["exceptions"]}
    exc = rows[("IMPLEMENTATION_CONTENT_MISMATCH", "CHG-04")]
    assert exc["control_id"] == "chg.2" and exc["source"].startswith("CHG-WEEKLY-2026-09-15/ISSUE-")
    eid = exc["exception_id"]
    closure.assign(eid, "Rajesh Kumar", "Tan Wei Ling")
    closure.evidence_fix(eid, "CR-104 redeployed", "Rajesh Kumar")
    export = json.loads((ROOT / "tests/fixtures/constructed_change_pack/changes.json").read_text())
    test = feed.retest_for(closure.state(eid))
    with refused(ValueError, "a rerun needs new evidence: this is the evidence that raised the exception"):
        closure.rerun(eid, test, export, "Siti Rahman")
    unfixed = copy.deepcopy(export)
    unfixed["changes"][3]["note"] = "redeployed"                                     # a new export, still wrong
    assert closure.rerun(eid, test, unfixed, "Siti Rahman")["rerun"]["verdict"] == "FAIL"
    malformed = copy.deepcopy(unfixed)
    malformed["changes"][3]["outcome"] = "done"
    assert test(malformed) == {"verdict": "FAIL",
                               "reason": "the export could not be tested: explicit change outcome required"}
    closure.retest(eid, "FAIL", "Siti Rahman")
    closure.evidence_fix(eid, "CR-104 redeployed from the approved build", "Rajesh Kumar")
    fixed = copy.deepcopy(export)
    change = next(c for c in fixed["changes"] if c["event_id"] == "CHG-04")
    change["actual_spec_hash"] = next(t for t in fixed["tickets"] if t["ticket_id"] == "CR-104")["approved_spec_hash"]
    receipt = closure.rerun(eid, test, fixed, "Siti Rahman")["rerun"]
    assert receipt["verdict"] == "PASS" and receipt["test"] == "change_authorization:2 (IMPLEMENTATION_CONTENT_MISMATCH on CHG-04)"
    assert closure.retest(eid, "PASS", "Siti Rahman")["state"] == "CLOSED"
    incomplete = copy.deepcopy(fixed)
    incomplete["collection"]["complete"] = False
    assert test(incomplete)["verdict"] == "FAIL"                           # not comparable is never a pass
    with refused(ValueError, "no re-executable control test for procedure None"):
        feed.retest_for({"detail": {}})


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
    v = verifier.verify(demo.careful_agent, "careful", 1000, seed=11)
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


def test_m4_eligibility_reads_the_upper_bound_in_three_bands():
    # Decided 25 Sep 2026: the 95% upper bound, never the point estimate; 1-3% is monitored-only, above 3% tools only.
    cert = _cert()
    assert cert["far"] == 0 and cert["far_upper"] == 0.006 and cert["tier"] == "WARRANTED"
    assert cert["eligibility_basis"] == ("the 95% upper bound on the false-assurance rate, 0.60% on 500 planted, is at "
                                         "or below 1.00% (read from the upper bound, Clopper-Pearson exact, one-sided, "
                                         "rounded up to 4 decimals)")
    small = {"far": 0.0, "far_upper": verifier.far_upper_bound(0, 50), "planted": 50}      # a 0% point estimate
    assert warranty.tier(small)["tier"] == "NOT_ASSURED"
    assert warranty.tier({"far_upper": 0.0126, "planted": 500})["tier"] == "MONITORED_ONLY"   # two misses in 500
    assert warranty.tier({"far_upper": 0.03, "planted": 500})["tier"] == "MONITORED_ONLY"
    assert warranty.tier({"far_upper": 0.0301, "planted": 500})["tier"] == "NOT_ASSURED"
    assert warranty.tier(None) == {"tier": "NOT_ASSURED", "reason": "no measured false-assurance rate"}


def test_m4_refusals():
    v = verifier.verify(demo.careful_agent, "careful", 1000, seed=11)
    h = verifier.verify(demo.hasty_agent, "hasty", 100, seed=11)
    with refused(ValueError, "a warranty covers named controls: the scope is empty"):
        warranty.issue("ORD-1", [], v, 1000, "Tan Wei Ling", "2026-12-31")
    with refused(ValueError, "no measured false-assurance rate: the warranty cannot be issued"):
        warranty.issue("ORD-1", ["CHG-01"], {}, 1000, "Tan Wei Ling", "2026-12-31")
    with refused(ValueError, f"the 95% upper bound on the false-assurance rate, {h['far_upper']:.2%} on 50 planted, is "
                             "above 3.00%: NOT_ASSURED, no warranty"):
        warranty.issue("ORD-1", ["CHG-01"], h, 1000, "Tan Wei Ling", "2026-12-31")
    small = verifier.verify(demo.careful_agent, "careful-small", 100, seed=11)        # 0 misses, but only 50 planted
    with refused(ValueError, "the 95% upper bound on the false-assurance rate, 5.82% on 50 planted, is above 3.00%: "
                             "NOT_ASSURED, no warranty"):
        warranty.issue("ORD-1", ["CHG-01"], small, 1000, "Tan Wei Ling", "2026-12-31")
    with refused(ValueError, "the 95% upper bound on the false-assurance rate, 1.26% on 500 planted, is above 1.00% and "
                             "at or below 3.00%: MONITORED_ONLY, no warranty"):
        warranty.issue("ORD-1", ["CHG-01"], {**v, "far_upper": 0.0126}, 1000, "Tan Wei Ling", "2026-12-31")
    with refused(ValueError, "the monitored-only price is not set: the owner sets prices.control_monitored in "
                             "config/raas.yaml"):
        warranty.price(controls=0, monitored_controls=10)
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


# ---------- block 1: the watch feeds M1 (B1-2) ----------

def test_a_replayed_mas_watch_item_becomes_an_m1_proposal_and_inbox_work(tmp_path):
    from governance.production.inbox import _raas_items
    from governance.raas import watch_link
    from governance.watcher import intel
    from tests.test_watch_intel import NOW, _alert, _drop, _row
    intel.subscriptions()
    _drop("mas-email-alerts", "a.eml", _alert("alerts@mas.gov.sg", [("https://www.mas.gov.sg/regulation/circulars/c1",
                                                                     "Circular one")]))
    intel.scan_mailbox(_row("mas-email-alerts"), now=NOW)                                   # the baseline
    notice = "https://www.mas.gov.sg/regulation/notices/notice-on-ai-change-and-third-party-oversight"
    _drop("mas-email-alerts", "b.eml", _alert("alerts@mas.gov.sg", [(notice, "Notice on AI change oversight")]))
    intel.scan_mailbox(_row("mas-email-alerts"), now=NOW)
    item = next(i for i in intel.items() if i["url"] == notice)
    assert watch_link.awaiting_text() == [] and _raas_items(NOW) == []       # triage comes first, as for any item
    intel.triage(item["item_id"], "RELEVANT", "Tan Wei Ling")
    assert [i["item_id"] for i in watch_link.awaiting_text()] == [item["item_id"]]
    [todo] = _raas_items(NOW)
    assert todo["kind"] == "m1_text" and todo["title"] == f"Save the text of {item['title']} so M1 can read it"
    saved = tmp_path / "notice.txt"
    saved.write_text(PUB, encoding="utf-8")
    with refused(ValueError, f"no saved publication at {tmp_path / 'missing.txt'}"):
        watch_link.propose_from_watch(item["item_id"], tmp_path / "missing.txt", "Tan Wei Ling")
    with refused(ValueError, "no watch item nope"):
        watch_link.propose_from_watch("nope", saved, "Tan Wei Ling")
    proposal = watch_link.propose_from_watch(item["item_id"], saved, "Tan Wei Ling")
    assert proposal["reference"] == notice and proposal["title"] == item["title"]
    with refused(ValueError, f"watch item {item['item_id']} already has proposal {proposal['proposal_id']}"):
        watch_link.propose_from_watch(item["item_id"], saved, "Tan Wei Ling")
    assert watch_link.awaiting_text() == []
    [decide] = _raas_items(NOW)
    assert decide["kind"] == "m1_decide" and decide["title"].startswith(f"Decide {len(proposal['items'])} of ")
    text = watch_link.publication(proposal["proposal_id"])
    for i in proposal["items"]:
        m1.decide(proposal["proposal_id"], i["item_id"], "ACCEPT", "Tan Wei Ling", text)
    assert _raas_items(NOW) == [] and m1.control_set(proposal["proposal_id"])["status"] == "SIGNED"


def test_the_inbox_never_creates_the_raas_folder(tmp_path, monkeypatch):
    from governance.production.inbox import _raas_items
    from governance import raas
    monkeypatch.setenv("GAAR_RAAS_HOME", str(tmp_path / "never-made"))
    assert _raas_items(None) == [] and not raas.exists()
    assert not (tmp_path / "never-made").exists()


def test_the_watch_link_refuses_what_m1_cannot_read(tmp_path):
    from governance.raas import watch_link
    from governance.watcher import intel
    from tests.test_watch_intel import NOW, _alert, _drop, _row
    intel.subscriptions()
    _drop("mas-email-alerts", "a.eml", _alert("alerts@mas.gov.sg", [("https://www.mas.gov.sg/regulation/circulars/c1",
                                                                     "Circular one")]))
    intel.scan_mailbox(_row("mas-email-alerts"), now=NOW)
    _drop("mas-email-alerts", "b.eml", _alert("alerts@mas.gov.sg", [("https://www.mas.gov.sg/news/media-releases/x",
                                                                     "Media release")]))
    intel.scan_mailbox(_row("mas-email-alerts"), now=NOW)
    item = next(i for i in intel.items() if i["url"].endswith("/x"))
    saved = tmp_path / "x.txt"
    saved.write_text(PUB, encoding="utf-8")
    if item["kind"] not in watch_link.REGULATORY:
        with refused(ValueError, f"watch item {item['item_id']} is not a MAS instrument or consultation: M1 reads "
                                 "MAS publications"):
            watch_link.propose_from_watch(item["item_id"], saved, "Tan Wei Ling")
    with refused(ValueError, "a proposal from the watch needs the name of the person who saved the publication"):
        watch_link.propose_from_watch(item["item_id"], saved, " ")
    with refused(ValueError, "no proposal RCP-missing"):
        watch_link.publication("RCP-missing")


# ---------- block 1: one command runs a period and seals it (B1-1, B1-5, B1-6) ----------

def _order(tmp_path, config_path, controls, name="ORD-T"):
    order = tmp_path / f"{name}.yaml"
    order.write_text(json.dumps({"order_id": name, "customer": "CONSTRUCTED bank", "control_family": "Change management",
                                 "period": "2026-W3", "period_end": "2026-10-01", "series": str(config_path),
                                 "controls": controls, "agent": "governance.raas.demo:careful_agent",
                                 "issued_by": "Tan Wei Ling"}))
    return order


def test_one_command_runs_a_period_through_all_four_modules_and_seals_the_pack(series, tmp_path):
    from tests.test_inbox_and_scheduler import _ticked
    from governance.raas import period, seal
    home, config_path, _ = _ticked(series, weeks=(1,))
    out = period.run(_order(tmp_path, config_path, ["chg.1", "chg.2", "chg.3", "chg.4"]))
    pack = out["pack"]
    assert pack["verification"]["planted"] == 500 and pack["verification"]["cases"] == 1000
    assert pack["closure"]["total"] == 13 and pack["closure"]["still_open"] == 13
    assert pack["status"]["tier"] == "WARRANTED" and not pack["status"]["warranted"]
    assert pack["status"]["headline"] == "Incomplete: exceptions still open"
    assert pack["status"]["not_warranted_reason"] == ("13 exception(s) still open: no warranty until the period is "
                                                      "complete")
    assert pack["lineage"]["series_periods_fed"] == ["2026-09-15"] and len(pack["lineage"]["exceptions"]) == 13
    assert "seed" not in json.dumps(pack["verification"])                    # only a commitment leaves the tenant
    stored = json.loads(Path(out["pack_file"]).read_text())
    passport = json.loads(Path(out["passport_file"]).read_text())
    tenant_key = seal.key_register()[0]["public_key_b64"]
    assert seal.verify(stored, passport, tenant_key)["valid"]
    with refused(ValueError, f"ORD-T 2026-W3 is already sealed as {pack['pack_id']}: a period is sealed once"):
        period.run(_order(tmp_path, config_path, ["chg.1"]))


def test_a_sealed_pack_fails_verification_if_one_byte_changes(series, tmp_path):
    from governance.raas import period, seal
    from tests.test_inbox_and_scheduler import _ticked
    home, config_path, _ = _ticked(series, weeks=(1,))
    out = period.run(_order(tmp_path, config_path, ["OUT-OF-SERIES-1"], name="ORD-CLEAN"))
    pack, passport = out["pack"], out["passport"]
    assert pack["status"]["headline"] == "Warranted Control Period" and pack["warranty"]["tier"] == "WARRANTED"
    raw = Path(out["pack_file"]).read_text()
    tampered = json.loads(raw.replace('"false_assurance": 0', '"false_assurance": 1', 1))
    result = seal.verify(tampered, passport)
    assert not result["valid"] and not result["content_matches"] and result["signature_valid"]
    forged = dict(passport, headline="Warranted Control Period (edited)")
    assert not seal.verify(pack, forged)["passport_digest_valid"]
    other = seal.seal(pack, path=tmp_path / "another-tenant")                 # re-signed with another key
    assert seal.verify(pack, other)["valid"]
    assert not seal.verify(pack, other, seal.key_register()[0]["public_key_b64"])["key_is_the_tenants"]


def test_the_planted_draw_is_sealed_by_the_tenant_key_and_new_each_period(tmp_path):
    from governance.raas import period
    a, b = period.sealed_seed("ORD-1", "2026-Q3"), period.sealed_seed("ORD-1", "2026-Q4")
    assert a != b and a == period.sealed_seed("ORD-1", "2026-Q3")
    assert period.sealed_seed("ORD-1", "2026-Q3", path=tmp_path / "other") != a     # another key, another draw


def test_the_scheduler_seals_due_orders_over_its_series(series, tmp_path):
    from governance import raas
    from governance.production import scheduler
    from governance.raas import period
    from tests.test_inbox_and_scheduler import AFTER_WEEK3, _ticked
    home, config_path, first = _ticked(series, weeks=(1,))
    assert first["jobs"]["raas"]["status"] == "NOT_CONFIGURED" or raas.exists()
    orders = raas.home() / "orders"
    orders.mkdir(parents=True, exist_ok=True)
    _order(orders, config_path, ["OUT-OF-SERIES-1"], name="ORD-DUE")
    _order(orders, tmp_path / "another-series.json", ["X"], name="ORD-ELSEWHERE")
    assert period.due_orders(config_path, "2026-09-30") == []                         # its period has not ended
    ticked = scheduler.tick(config_path, now=AFTER_WEEK3)["jobs"]["raas"]
    assert ticked["status"] == "OK" and ticked["sealed"] == [period.sealed("ORD-DUE", "2026-W3")["pack_id"]]
    assert scheduler.tick(config_path, now=AFTER_WEEK3)["jobs"]["raas"]["detail"] == "nothing due"


def test_period_refusals(tmp_path):
    from governance.raas import period
    with refused(ValueError, f"no order ORD-NONE: put it in {raas_home() / 'orders'}/ORD-NONE.yaml"):
        period.run("ORD-NONE")
    bad = tmp_path / "bad.yaml"
    bad.write_text("order_id: ORD-B\ncustomer: C\n")
    with refused(ValueError, "order bad.yaml is missing control_family, period, period_end, controls, agent, issued_by"):
        period.run(bad)
    with refused(ValueError, "agent 'os:system' must be module:function inside governance/"):
        period.agent_for("os:system")
    assert period.load_order("ORD-DEMO")["order_id"] == "ORD-DEMO"                  # the shipped constructed order


def raas_home():
    from governance import raas
    return raas.home()


# ---------- block 1: read-only API over sealed periods (B1-7) ----------

@pytest.fixture
def api(monkeypatch):
    import threading
    from http.server import ThreadingHTTPServer
    from services.raas_api import RaaSHandler
    monkeypatch.setenv("WB_GAAR_API_QUIET", "1")
    server = ThreadingHTTPServer(("127.0.0.1", 0), RaaSHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _call(url, token=None, body=None):
    import urllib.error
    import urllib.request
    request = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urllib.request.urlopen(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def test_the_period_endpoints_need_a_token_and_never_reveal_the_planted_seed(series, tmp_path, api, monkeypatch):
    from governance import raas
    from governance.raas import period
    from tests.test_inbox_and_scheduler import _ticked
    monkeypatch.delenv("WB_GAAR_API_KEY", raising=False)
    assert _call(f"{api}/v1/periods") == (401, {"error": "unauthorized"})        # never open, even with no key set
    assert _call(f"{api}/health")[0] == 200                                       # the existing public read stays
    monkeypatch.setenv("WB_GAAR_API_KEY", "test-token")
    assert _call(f"{api}/v1/periods", "wrong")[0] == 401
    assert _call(f"{api}/v1/periods", "test-token") == (200, []) and not raas.exists()   # reading creates nothing
    home, config_path, _ = _ticked(series, weeks=(1,))
    out = period.run(_order(tmp_path, config_path, ["OUT-OF-SERIES-1"], name="ORD-API"))
    pid = out["pack"]["pack_id"]
    status, periods = _call(f"{api}/v1/periods", "test-token")
    assert status == 200 and [p["pack_id"] for p in periods] == [pid]
    status, sealed = _call(f"{api}/v1/periods/{pid}", "test-token")
    assert status == 200 and sealed["passport"]["content_hash"] == out["passport"]["content_hash"]
    assert _call(f"{api}/v1/periods/PACK-nope", "test-token")[0] == 404
    status, verifications = _call(f"{api}/v1/verifications", "test-token")
    assert status == 200 and verifications and all("seed" not in v for v in verifications)
    status, warranties = _call(f"{api}/v1/warranties", "test-token")
    assert status == 200 and [w["order_id"] for w in warranties] == ["ORD-API"] and warranties[0]["claims"] == []
    status, checked = _call(f"{api}/v1/packs/verify", "test-token", sealed)
    assert status == 200 and checked["valid"] and checked["key_is_the_tenants"]
    sealed["pack"]["closure"]["still_open"] = 1
    assert _call(f"{api}/v1/packs/verify", "test-token", sealed)[1]["valid"] is False
    assert _call(f"{api}/v1/packs/verify", "test-token", {"pack": {}})[0] == 400


def _cli(*args):
    import subprocess
    import sys
    return subprocess.run([sys.executable, str(ROOT / "tools/gaar_raas.py"), *map(str, args)], text=True,
                          capture_output=True)


def test_the_command_line_runs_a_period_verifies_it_and_refuses_what_it_should(series, tmp_path):
    from tests.test_inbox_and_scheduler import _ticked
    assert _cli("status").stdout.startswith("no RaaS state yet")
    home, config_path, _ = _ticked(series, weeks=(1,))
    ran = _cli("period", _order(tmp_path, config_path, ["OUT-OF-SERIES-1"], name="ORD-CLI"))
    assert ran.returncode == 0, ran.stderr
    assert ran.stdout.splitlines()[0] == "ORD-CLI 2026-W3: Warranted Control Period (WARRANTED)"
    pack_file = ran.stdout.split("pack:")[1].split()[0]
    passport_file = ran.stdout.split("passport:")[1].split()[0]
    assert _cli("verify", "--pack", pack_file, "--passport", passport_file).returncode == 0
    tampered = tmp_path / "tampered.json"
    tampered.write_text(Path(pack_file).read_text().replace('"still_open": 0', '"still_open": 1'))
    assert _cli("verify", "--pack", tampered, "--passport", passport_file).returncode == 1
    again = _cli("period", tmp_path / "ORD-CLI.yaml")
    assert again.returncode == 1 and "refused: ORD-CLI 2026-W3 is already sealed as" in again.stderr
    assert "sealed periods: 1" in _cli("status").stdout
    assert _cli("decide", "--proposal", "RCP-none").stderr.strip() == "refused: no proposal RCP-none"
