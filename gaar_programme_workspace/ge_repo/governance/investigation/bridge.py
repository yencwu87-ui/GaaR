"""Existing-cycle integration. Config is operator-owned, never supplied by evidence."""
import json
import os
from pathlib import Path

from .service import InvestigationEngine
from .store import InvestigationStore


def required(state=None):
    # Bound investigations can never be downgraded by a legacy compatibility flag.
    bound = bool(((state or {}).get("governance_context") or {}).get("investigation_id"))
    return bound or os.environ.get("WB_INVESTIGATION_REQUIRED", "1").lower() not in {"0", "false", "off"}


def configured_engine():
    config_file = os.environ.get("WB_INVESTIGATION_CONFIG")
    if not config_file:
        raise ValueError("WB_INVESTIGATION_CONFIG missing; trusted actor keys and source registry required")
    config_path = Path(config_file).resolve()
    config = json.loads(config_path.read_text())
    store_path = Path(config["store"])
    if not store_path.is_absolute():
        store_path = config_path.parent / store_path
    return InvestigationEngine(InvestigationStore(store_path, config["trusted_keys"]), config["sources"])


def cycle_gate(state):
    try:
        context = state.get("governance_context") or {}
        iid, head = context.get("investigation_id"), context.get("investigation_head")
        if not iid or not head:
            raise ValueError("signed investigation ID and pinned head required")
        engine = configured_engine()
        rows, values = engine.snapshot(iid, head)
        scope = values["understand"]
        if scope.control_id != state.get("control_id") or scope.framework != state.get("framework"):
            raise ValueError("investigation/cycle control scope mismatch")
        if scope.requirement_version != context.get("requirement_version_id"):
            raise ValueError("investigation/cycle requirement version mismatch")
        ev = state.get("evidence") or {}
        # Whole signed evidence slices must survive binding; no different system's
        # otherwise-valid investigation may be used to approve this cycle.
        texts = [str(ev.get("text") or "")] + [str(c.get("text") or "") for c in ev.get("chunks", [])]
        for item in values["examine"].evidence:
            if not any(item.text in text for text in texts):
                raise ValueError("investigation evidence not bound to cycle")
        assessment_scope = context.get("assessment_scope")
        if assessment_scope != scope.scope.model_dump():
            raise ValueError("explicit cycle system/version/period binding missing or mismatched")
        gate = engine.gate(iid, head)
        proposal = state.get("proposal") or {}
        if gate.get("verdict") == "ADVERSE" and proposal.get("sufficiency") == "full":
            gate["assessment_finalizable"] = False
            gate["deployment_authorized"] = False
            gate["blockers"].append("proposal_disagrees_with_adverse_investigation")
        return gate
    except Exception as exc:
        return {"assessment_finalizable": False, "deployment_authorized": False,
                "blockers": [f"investigation_unavailable:{exc}"]}


def agent_context(investigation_id, expected_head=None):
    rows, values = configured_engine().snapshot(investigation_id, expected_head)
    return {"investigation_id": investigation_id, "head": rows[-1]["record_hash"] if rows else None,
            "record": {k: v.model_dump(mode="json") for k, v in values.items()}}
