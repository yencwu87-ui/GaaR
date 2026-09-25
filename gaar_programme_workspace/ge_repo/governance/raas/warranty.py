"""M4 Assurance Warranty: a capped refund per falsely assured control, issued only on a measured, qualifying rate.

- Eligibility reads the 95% upper bound on M2's false-assurance rate, never the point estimate (decided 25 Sep 2026:
  a point estimate of 0.3% on 300 cases cannot support a warranty). Three bands, by the bound: at or below
  warranty.max_far (1%) WARRANTED; up to warranty.monitored_max_far (3%) MONITORED_ONLY, sold at a lower price without
  a warranty; above that NOT_ASSURED, where only M1 and M2 are offered, as tools.
- A claim needs evidence, a control inside the certificate's scope, a discovery date inside the claim window, and an
  assessor who is not the claimant. Refunds stop at the cap.
- The expected-claim figure is an estimate on an assumed defect prevalence, stated as such, until four quarters of
  observed rates replace it. The upper-bound figure is what the reserve is checked against.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone

from governance.names import require_person

from . import params, params_sha256, store


def tier(verification: dict | None) -> dict:
    """Which band a measured rate falls in, read from its 95% upper bound."""
    w = params()["warranty"]
    upper = (verification or {}).get("far_upper")
    if upper is None:
        return {"tier": "NOT_ASSURED", "reason": "no measured false-assurance rate"}
    planted = verification.get("planted")
    stated = f"the 95% upper bound on the false-assurance rate, {upper:.2%} on {planted} planted,"
    if upper <= w["max_far"]:
        return {"tier": "WARRANTED", "reason": f"{stated} is at or below {w['max_far']:.2%}"}
    if upper <= w["monitored_max_far"]:
        return {"tier": "MONITORED_ONLY", "reason": f"{stated} is above {w['max_far']:.2%} and at or below "
                                                     f"{w['monitored_max_far']:.2%}"}
    return {"tier": "NOT_ASSURED", "reason": f"{stated} is above {w['monitored_max_far']:.2%}"}


def price(controls: int, exceptions_closed: int = 0, reg_changes: int = 0, vendor_agents: int = 0,
          monitored_controls: int = 0) -> dict:
    """The period fee by outcome unit. Nothing is priced per seat or per hour."""
    p = params()["prices"]
    if monitored_controls and p.get("control_monitored") is None:
        raise ValueError("the monitored-only price is not set: the owner sets prices.control_monitored in "
                         "config/raas.yaml")
    lines = [("control_assured", controls), ("control_monitored", monitored_controls),
             ("exception_closed", exceptions_closed),
             ("regulatory_change", reg_changes), ("vendor_agent_verified", vendor_agents)]
    rows = [{"unit": u, "quantity": q, "unit_price": p[u], "amount": q * p[u]} for u, q in lines if q]
    return {"currency": params()["currency"], "lines": rows, "total": sum(r["amount"] for r in rows)}


def issue(order_id: str, controls: list[str], verification: dict, fee_total: float, issued_by: str,
          period_end: str, path=None) -> dict:
    w = params()["warranty"]
    issued_by = require_person(issued_by, "a warranty needs the name of the person issuing it")
    if not controls:
        raise ValueError("a warranty covers named controls: the scope is empty")
    if not verification or verification.get("far_upper") is None:
        raise ValueError("no measured false-assurance rate: the warranty cannot be issued")
    band = tier(verification)
    if band["tier"] != "WARRANTED":
        raise ValueError(f"{band['reason']}: {band['tier']}, no warranty")
    per_control = params()["prices"]["control_assured"] * w["refund_multiple"]
    cap = round(fee_total * w["cap_share_of_fee"], 2)
    prevalence = w["assumed_defect_prevalence"]
    cert = {"certificate_id": "WAR-" + hashlib.sha256(f"{order_id}|{period_end}|{sorted(controls)}".encode()).hexdigest()[:12],
            "order_id": order_id, "controls": sorted(controls), "period_end": period_end,
            "verification_id": verification.get("verification_id"), "far": verification["far"],
            "far_upper": verification.get("far_upper"),
            "tier": band["tier"], "eligibility_basis": band["reason"] + " (read from the upper bound, "
                                                                        + verification.get("bound_method", "exact") + ")",
            "refund_per_control": per_control, "cap": cap,
            "claims_until": (date.fromisoformat(period_end) + timedelta(days=w["claim_window_days"])).isoformat(),
            "reserve": round(fee_total * w["reserve_share"], 2),
            "expected_claims": round(len(controls) * prevalence * verification["far"] * per_control, 2),
            "expected_claims_at_upper_bound": round(min(cap, len(controls) * prevalence *
                                                        (verification.get("far_upper") or 1) * per_control), 2),
            "estimate_basis": f"assumed defect prevalence {prevalence}; replaced by observed rates after 4 quarters",
            "issued_by": issued_by, "params_sha256": params_sha256(), "at": datetime.now(timezone.utc).isoformat()}
    store("warranty", path).append("RaaSWarrantyIssued", cert)
    return cert


def _certificate(certificate_id: str, path=None) -> tuple[dict, list[dict]]:
    rows = [r["payload"] for r in store("warranty", path).read() if r["payload"]["certificate_id"] == certificate_id]
    cert = next((r for r in rows if "cap" in r), None)
    if cert is None:
        raise ValueError(f"no warranty {certificate_id}")
    return cert, [r for r in rows if "payout" in r]


def claim(certificate_id: str, control_id: str, evidence_ref: str, discovered_on: str, claimed_by: str,
          assessed_by: str, path=None) -> dict:
    """A falsely assured control, shown by evidence, assessed by someone other than the claimant."""
    cert, paid = _certificate(certificate_id, path)
    claimed_by = require_person(claimed_by, "a claim needs the name of the person making it")
    assessed_by = require_person(assessed_by, "a claim needs the name of the person assessing it")
    if assessed_by == claimed_by:
        raise ValueError("a claim must be assessed by someone other than the claimant")
    if control_id not in cert["controls"]:
        raise ValueError(f"{control_id} is not in this warranty's scope")
    if not (evidence_ref or "").strip():
        raise ValueError("a claim needs evidence that the control was not effective in the period")
    if not cert["period_end"] <= discovered_on <= cert["claims_until"]:
        raise ValueError(f"a claim must be discovered between {cert['period_end']} and {cert['claims_until']}")
    if any(p["control_id"] == control_id for p in paid):
        raise ValueError(f"{control_id} has already been refunded under this warranty")
    remaining = round(cert["cap"] - sum(p["payout"] for p in paid), 2)
    if remaining <= 0:
        raise ValueError("the warranty cap is exhausted")
    record = {"certificate_id": certificate_id, "control_id": control_id, "evidence_ref": evidence_ref.strip(),
              "discovered_on": discovered_on, "claimed_by": claimed_by, "assessed_by": assessed_by,
              "payout": min(cert["refund_per_control"], remaining), "cap_remaining_before": remaining,
              "at": datetime.now(timezone.utc).isoformat()}
    store("warranty", path).append("RaaSWarrantyClaimPaid", record)
    return record
