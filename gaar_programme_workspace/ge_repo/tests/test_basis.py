"""Requirement basis (kit v22): proposed, verbatim, checkable passages behind each control."""
import pytest

from governance import basis


@pytest.fixture(scope="module")
def report():
    return basis.report()


def test_every_control_with_a_held_instrument_gets_a_verbatim_checkable_candidate(report):
    for c in report["controls"]:
        if c["status"] == "INSTRUMENT_UNAVAILABLE":
            assert c["framework"] == "ISO 42001" and c["candidates"] == []
            continue
        assert c["candidates"] and basis.verify_quote(c["candidates"][0], c["framework"])
        assert len(c["instrument_sha256"]) == 64


def test_known_controls_point_at_the_right_passages(report):
    by = {(c["framework"], c["control_id"]): c for c in report["controls"]}
    assert "Board" in by[("MAS", "M1.1")]["candidates"][0]["quote"]
    assert "validation" in by[("MAS", "M3.6")]["candidates"][0]["quote"].lower()
    assert "changes" in by[("MAS", "M3.12")]["candidates"][0]["quote"].lower()


def test_a_basis_is_labelled_a_proposal_not_an_anchor(report):
    assert "not an anchor" in report["meaning"]
    assert report["summary"]["ISO 42001"] == {"INSTRUMENT_UNAVAILABLE": 38}


def test_every_quote_carries_its_instruments_authority(report):
    by = {(c["framework"], c["control_id"]): c for c in report["controls"]}
    assert by[("MAS", "M3.12")]["candidates"][0]["authority"].startswith("CONSULTATION_DRAFT")
    assert all(x["authority"] == basis.AUTHORITY[c["framework"]] for c in report["controls"] for x in c["candidates"])
    assert "not the same as" in basis.__doc__ and "not that no basis exists" in report["meaning"]


def test_the_pilot_controls_are_tier_one_and_the_rest_stay_visible_as_proposals(report):
    tiers = {(c["framework"], c["control_id"]): c["tier"] for c in report["controls"]}
    assert tiers[("MAS", "M3.12")] == 1 and sum(t == 1 for t in tiers.values()) == len(basis.tier1())
    assert report["tier1"] == {"controls": 1, "confirmed": 0, "open": ["MAS M3.12"]}
    assert report["defect"].startswith("D20")


def test_a_basis_is_confirmed_one_control_at_a_time_by_a_named_person():
    before = basis.ledger_path().read_text() if basis.ledger_path().exists() else ""
    record = basis.confirm("MAS", "M3.12", 1, "CONFIRMED", "Test Owner", "read against the paper")
    assert record["rigor"] == "per-control" and record["candidate"]["authority"].startswith("CONSULTATION_DRAFT")
    assert basis.verify_quote(record["candidate"], "MAS") and before == ""
    after = basis.report(["MAS"])
    m312 = next(c for c in after["controls"] if c["control_id"] == "M3.12")
    assert m312["status"] == "CONFIRMED_BASIS" and after["tier1"]["confirmed"] == 1
    basis.confirm("MAS", "M1.1", 0, "NO_BASIS_IN_INSTRUMENT", "Test Owner")
    assert next(c for c in basis.report(["MAS"])["controls"] if c["control_id"] == "M1.1")["status"] == "NO_BASIS_CONFIRMED"


@pytest.mark.parametrize("args, message", [
    (("MAS", "M3.12", 1, "LOOKS_FINE", "A"), "decision must be one of CONFIRMED, REJECTED, NO_BASIS_IN_INSTRUMENT"),
    (("MAS", "M3.12", 1, "CONFIRMED", " "), "a basis decision needs the name of the person making it"),
    (("ISO 42001", "A.2.2", 1, "CONFIRMED", "A"), "ISO 42001: instrument unavailable, so there is no passage to confirm"),
    (("MAS", "M9.99", 1, "CONFIRMED", "A"), "no control MAS M9.99"),
    (("MAS", "M3.12", 7, "CONFIRMED", "A"), "MAS M3.12 has candidates 1 to 2"),
])
def test_a_basis_decision_that_is_not_specific_is_refused(args, message):
    with pytest.raises(ValueError, match="^" + message + "$"):
        basis.confirm(*args)


def test_bulk_confirmation_is_refused():
    with pytest.raises(ValueError, match="^bulk confirmation is refused"):
        basis.confirm_many("MAS", ["M1.1", "M1.2"], "Test Owner")


def test_a_quote_that_no_longer_matches_its_instrument_is_refused(monkeypatch):
    monkeypatch.setattr(basis, "verify_quote", lambda candidate, framework: False)
    with pytest.raises(ValueError, match="^the quote no longer matches the instrument; re-run the report$"):
        basis.confirm("MAS", "M3.12", 1, "CONFIRMED", "Test Owner")
