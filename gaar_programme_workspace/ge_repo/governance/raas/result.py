"""The Warranted Control Period pack: what the buyer receives, and what they are billed for.

A period is COMPLETE when every accepted regulatory change is signed and no exception is still open. It is WARRANTED
when M4 issued a certificate. Controls are billed only for a warranted period; closed exceptions and signed changes are
billed as delivered. The pack states the parameters it was computed under and the provenance of its truth.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from . import params, params_sha256
from .warranty import price, tier


def result_pack(order_id: str, family: str, period: str, controls: list[str], signed_sets: list[dict],
                verification: dict, closure: dict, certificate: dict | None, not_warranted_reason: str = "") -> dict:
    warranted = certificate is not None
    complete = closure["still_open"] == 0 and all(s["status"] == "SIGNED" for s in signed_sets)
    band = tier(verification)["tier"]
    monitored = len(controls) if band == "MONITORED_ONLY" else 0
    note = None
    if monitored and params()["prices"].get("control_monitored") is None:
        monitored, note = 0, "monitored-only controls are not billed: the owner has not set their price"
    bill = price(controls=len(controls) if warranted else 0, exceptions_closed=closure["billable"],
                 reg_changes=sum(s["status"] == "SIGNED" for s in signed_sets), monitored_controls=monitored)
    if note:
        bill["note"] = note
    return {"pack_id": "PACK-" + hashlib.sha256(f"{order_id}|{period}".encode()).hexdigest()[:12],
            "order_id": order_id, "control_family": family, "period": period,
            "status": {"complete": complete, "warranted": warranted, "tier": band,
                       "headline": ("Warranted Control Period" if warranted and complete else
                                    "Complete, not warranted" if complete else
                                    "Incomplete: exceptions still open" if closure["still_open"] else
                                    "Incomplete: a regulatory change is not yet signed"),
                       "not_warranted_reason": None if warranted else not_warranted_reason},
            "controls_in_scope": len(controls),
            "regulatory_changes": [{"reference": s["reference"], "status": s["status"], "accepted": len(s["accepted"]),
                                    "rejected": s["rejected"], "signed_by": s["signed_by"]} for s in signed_sets],
            "verification": {k: verification.get(k) for k in ("verification_id", "agent", "cases", "planted",
                                                                "false_assurance", "far", "far_upper", "confidence",
                                                                "bound_method",
                                                                "precision", "recall", "holds", "provenance")},
            "closure": {k: closure[k] for k in ("total", "closed_by_retest", "risk_accepted", "still_open",
                                                 "reopened_after_failed_retest", "expired_acceptances")},
            "warranty": certificate, "invoice": bill, "params_sha256": params_sha256(),
            "at": datetime.now(timezone.utc).isoformat()}
