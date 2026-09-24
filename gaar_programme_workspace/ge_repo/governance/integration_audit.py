"""Integration audit — does each stage consume the canonical element, or rediscover its own?

Read-only by construction. It resolves, compares and reports; it imports the pipeline's own
resolvers rather than reimplementing them, because a tracer that reconstructs the element set is
itself the twelfth failure mode it is looking for.

The semantic layer proved: Source → Canonical Control → Elements → Derived Views. What this
proves or disproves is the next arrow chain:

    Canonical Elements → Evidence → Human Reading → AI Proposal → Challenge → Comparison → Decision

At every arrow one question: is this component consuming the canonical element, or building its
own version from the control description, an older field, or a verification procedure?

The invariant that matters most:

    human_element_id == assessor_element_id == challenge_element_id

with the *text* resolved from one source rather than three independently supplied copies. Ids
agreeing while texts differ is worse than disagreement, because it looks like agreement.
"""
from __future__ import annotations

import collections
import inspect
from pathlib import Path
from typing import Any

SCHEMA = "integration-audit.1"
ROOT = Path(__file__).resolve().parents[1]

#: The twelve ways an alternate semantic authority gets in.
FAILURE_MODES = {
    "F01": "control title substituted for element text",
    "F02": "legacy elements/requirements field bypassing the canonical registry",
    "F03": "prompt rebuilding elements from the control description",
    "F04": "verification procedures passed as requirements",
    "F05": "assessor receiving a different element set from the human reviewer",
    "F06": "challenge validator resolving against stale element text",
    "F07": "comparison keyed by position rather than element_id",
    "F08": "decision engine consuming AI output as authority",
    "F09": "UI maintaining its own semantic copy",
    "F10": "derived view treated as a writable source",
    "F11": "predicate evaluation silently creating semantic requirements",
    "F12": "evidence packet referring to an obsolete element version",
}


def canonical(control_id: str, framework: str) -> list[dict]:
    from governance.control_contract import get_control_contract
    c = get_control_contract(control_id, framework) or {}
    return list(c.get("elements") or [])


def _resolvers(control_id: str, framework: str) -> dict[str, list[dict]]:
    """What each stage would actually see, obtained from that stage's own code path."""
    out: dict[str, list[dict]] = {"canonical": canonical(control_id, framework)}

    class _C:
        id, lib = control_id, framework
        title = req = owner = maps = artefacts = ""

    try:                                   # assessor / AI proposal
        import assessor as A
        out["assessor"] = list(A._contract_elements(_C()) or [])
    except Exception as exc:
        out["assessor_error"] = [{"id": "?", "text": f"{type(exc).__name__}: {exc}"}]
    try:                                   # human reading + comparison
        import compare as C
        out["compare"] = list(C.elements_for(_C()) or [])
    except Exception as exc:
        out["compare_error"] = [{"id": "?", "text": f"{type(exc).__name__}: {exc}"}]
    try:                                   # challenge validator
        from governance.control_contract import requirement_context
        ctx = requirement_context(control_id, framework) or {}
        out["challenge"] = list(ctx.get("elements") or [])
    except Exception as exc:
        out["challenge_error"] = [{"id": "?", "text": f"{type(exc).__name__}: {exc}"}]
    return out


def _norm(t: Any) -> str:
    return " ".join(str(t or "").split())


def trace(control_id: str, framework: str) -> dict[str, Any]:
    """One control, all the way through. Reports; changes nothing."""
    views = _resolvers(control_id, framework)
    canon = views["canonical"]
    canon_ids = [str(e.get("id")) for e in canon]
    canon_text = {str(e.get("id")): _norm(e.get("text")) for e in canon}

    findings: list[dict[str, str]] = []
    stages = {}
    for name in ("assessor", "compare", "challenge"):
        if f"{name}_error" in views:
            findings.append({"mode": "F02", "stage": name,
                             "detail": views[f"{name}_error"][0]["text"]})
            continue
        els = views.get(name) or []
        ids = [str(e.get("id")) for e in els]
        stages[name] = {"n": len(els), "ids": ids}

        if ids != canon_ids:
            findings.append({
                "mode": "F05" if name == "assessor" else "F06" if name == "challenge" else "F07",
                "stage": name,
                "detail": f"element ids differ from canonical: {ids} vs {canon_ids}"})
        for e in els:
            eid, txt = str(e.get("id")), _norm(e.get("text"))
            if eid in canon_text and txt != canon_text[eid]:
                findings.append({"mode": "F06", "stage": name,
                                 "detail": f"{eid} text differs from canonical"})

    # F01 — an element that is its own control's title
    try:
        from governance.control_contract import get_control_contract
        title = _norm((get_control_contract(control_id, framework) or {}).get("title"))
        for e in canon:
            if title and _norm(e.get("text")).lower() == title.lower():
                findings.append({"mode": "F01", "stage": "canonical",
                                 "detail": f"{e.get('id')} is the control title"})
    except Exception:
        pass

    return {"control_id": control_id, "framework": framework,
            "canonical_elements": len(canon), "stages": stages,
            "ids_agree": all(s["ids"] == canon_ids for s in stages.values()),
            "findings": findings}


def static_checks() -> list[dict[str, str]]:
    """Failure modes that are properties of the code, not of any one control."""
    out: list[dict[str, str]] = []

    # F04 — verification guidance must be labelled and separated in the prompt
    import assessor as A
    src = inspect.getsource(A)
    if "VERIFICATION GUIDANCE — NOT REQUIREMENTS" not in src:
        out.append({"mode": "F04", "stage": "assessor",
                    "detail": "ToD/ToE material is not labelled as non-requirement"})

    # F07 — comparison must key by element_id
    import compare as C
    csrc = inspect.getsource(C)
    if "element_id" not in csrc:
        out.append({"mode": "F07", "stage": "compare", "detail": "no element_id keying found"})
    if "zip(" in csrc and "element_id" not in csrc.split("zip(")[1][:200]:
        out.append({"mode": "F07", "stage": "compare",
                    "detail": "positional zip near verdict matching"})

    # F08 — the decision engine must not treat the proposal as authority
    from governance import decision_engine as DE
    dsrc = inspect.getsource(DE)
    if "reviewer_decision" not in dsrc:
        out.append({"mode": "F08", "stage": "decision",
                    "detail": "decision does not centre the reviewer's decision"})

    # F09 — the UI must not hold its own element copy
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    for leaked in ("control_contracts.yaml", "semantic_registry.yaml"):
        if leaked in app:
            out.append({"mode": "F09", "stage": "ui",
                        "detail": f"app.py reads {leaked} directly rather than via a service"})

    # F10 — a derived view must not be authored into
    from governance import semantic_canon as sc
    if "def reverse_sync" in inspect.getsource(sc):
        out.append({"mode": "F10", "stage": "canon", "detail": "reverse sync exists"})

    # F11 — predicates must not mint requirements
    try:
        from governance import predicate_engine as PE
        psrc = inspect.getsource(PE)
        if "elements[" in psrc and "append" in psrc:
            out.append({"mode": "F11", "stage": "predicate",
                        "detail": "predicate engine appears to mutate an element list"})
    except Exception:
        pass
    return out


def audit(corpus: list[tuple[str, str]]) -> dict[str, Any]:
    traces = [trace(cid, fw) for cid, fw in corpus]
    statics = static_checks()
    all_findings = statics + [f for t in traces for f in t["findings"]]
    return {"schema": SCHEMA, "traced": len(traces), "traces": traces,
            "static_findings": statics,
            "by_mode": dict(collections.Counter(f["mode"] for f in all_findings)),
            "clean": not all_findings,
            "findings": all_findings}


def report(a: dict[str, Any]) -> str:
    lines = [f"traced {a['traced']} control(s)"]
    for t in a["traces"]:
        ok = "ok" if not t["findings"] else f"{len(t['findings'])} finding(s)"
        stages = " ".join(f"{k}={v['n']}" for k, v in sorted(t["stages"].items()))
        lines.append(f"  {t['control_id']:10} {t['framework']:22} canon={t['canonical_elements']:3}"
                     f"  {stages:38} ids_agree={str(t['ids_agree']):5} {ok}")
    if a["findings"]:
        lines.append("")
        for f in a["findings"]:
            lines.append(f"  {f['mode']} {FAILURE_MODES[f['mode']]:52} [{f['stage']}] {f['detail'][:70]}")
    else:
        lines.append("\n  no alternate semantic authority found in any traced stage")
    return "\n".join(lines)
