"""Control impact graph: when one control lapses, what else loses reliance, and where the cause probably sits (kit v21).

Built on the dependency catalogue (governance/investigation/dependency_knowledge.json) and the MAS/MGF crosswalk.
It works the way an auditor treats a general IT-control deficiency: dependent controls lose *reliance*, they are not
assumed broken. So a lapse raises flags, never verdicts:

- ``RELIANCE_IMPAIRED``  complete weakness flag: the dependent control cannot be relied on until corroborated;
- ``RELIANCE_REDUCED``   partial weakness flag: rely on it only with added testing;
- ``WATCH``              a further step away, or a peer control in another framework sharing a capability.

Flag strength = the lapse's severity, capped by the edge's reliance and its review status, minus one level per hop.
Every catalogue edge is still PROPOSED (a hypothesis), and a proposed edge can raise at most RELIANCE_REDUCED:
only an approved edge declaring complete reliance can carry RELIANCE_IMPAIRED. Every flag names the corroboration
rule that must be met, and nothing here changes a control's recorded status (``changes_control_verdict`` is False).

Root cause runs the other way: from a lapsed control up its dependencies. A lapsed ancestor with no lapsed ancestor of
its own is a likely root cause; an unassessed ancestor is "unverified, test next"; an effective one is ruled out on
that path. An ancestor shared by several lapses is a likely common cause.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import yaml

from governance.investigation.dependencies import DEFAULT_PATH, load

LEVELS = {3: "RELIANCE_IMPAIRED", 2: "RELIANCE_REDUCED", 1: "WATCH"}
LAPSED, WEAK, EFFECTIVE, UNKNOWN = "LAPSED", "WEAK", "EFFECTIVE", "UNASSESSED"
SEVERITY = {LAPSED: 3, WEAK: 2, EFFECTIVE: 0, UNKNOWN: 0}
CROSSWALK = Path(__file__).with_name("crosswalk_mas_mgf.yaml")
NON_INFERENCE = ("A flag is a lead, not a finding: it says reliance on a dependent control is in question until the "
                 "edge's corroboration rule is met. No control's recorded status is changed.")


# Deterministic finding codes point at the control whose failure they evidence. Proposed internal mapping, reviewable
# like the edges: a finding on CHANGE.MGMT that says "self-approved" is evidence about change approval upstream.
FINDING_LINKS = {
    "APPROVAL_AFTER_EXECUTION": "INTERNAL:CHANGE.APPROVAL", "APPROVAL_NOT_ESTABLISHED": "INTERNAL:CHANGE.APPROVAL",
    "SELF_APPROVAL": "INTERNAL:CHANGE.APPROVAL", "NO_MATCHING_APPROVED_TICKET": "INTERNAL:CHANGE.APPROVAL",
    "IMPLEMENTER_NOT_APPROVED": "INTERNAL:CHANGE.APPROVAL", "OUTSIDE_APPROVED_WINDOW": "INTERNAL:CHANGE.APPROVAL",
    "DEVIATES_FROM_APPROVED_SCOPE": "INTERNAL:CHANGE.APPROVAL", "IMPLEMENTATION_CONTENT_MISMATCH": "INTERNAL:CHANGE.APPROVAL",
    "FREEZE_WITHOUT_PRIOR_EXCEPTION": "INTERNAL:CHANGE.FREEZE",
    "COLLECTION_POPULATION_DISAGREEMENT": "INTERNAL:LOGGING.COVERAGE",
    "CREDENTIAL_NOT_APPROVED_FOR_CHANGE": "INTERNAL:ACCESS.PRIVILEGED", "PRIVILEGE_NOT_ESTABLISHED": "INTERNAL:ACCESS.PRIVILEGED",
    "RECOVERY_NOT_ESTABLISHED": "INTERNAL:SERVICE.RECOVERY",
}


def status_of(value) -> str:
    """Normalise the many ways a result is written (sufficiency, verdicts, decisions) into four states."""
    v = str(value or "").strip().upper()
    if v in {"NONE", "FAIL", "FAILED", "ADVERSE", "CONTRADICTED", "LAPSED", "INEFFECTIVE"}:
        return LAPSED
    if v in {"PARTIAL", "INCONCLUSIVE", "NOT_EVIDENCED", "WEAK", "DEFICIENT"}:
        return WEAK
    if v in {"FULL", "PASS", "EFFECTIVE", "NO_EXCEPTIONS_FOUND", "NO_EXCEPTIONS_NOTED", "SUPPORTED"}:
        return EFFECTIVE
    return UNKNOWN


def _key(framework: str, control_id: str) -> str:
    f = (framework or "").removeprefix("Control Library - ")
    return f"{f}:{control_id}"


class ImpactGraph:
    def __init__(self, path=DEFAULT_PATH, crosswalk=CROSSWALK):
        book, self.knowledge_sha256 = load(path)
        self.version = book["version"]
        self.down, self.up = defaultdict(list), defaultdict(list)
        for edge in book["edges"]:
            u, d = _key(edge["framework"], edge["upstream"]), _key(edge["framework"], edge["downstream"])
            self.down[u].append((d, edge))
            self.up[d].append((u, edge))
        self.capabilities = defaultdict(set)
        if crosswalk and Path(crosswalk).exists():
            for m in (yaml.safe_load(Path(crosswalk).read_text(encoding="utf-8")) or {}).get("mappings") or []:
                for cap in (m.get("maps_to") or {}).get("capabilities") or []:
                    self.capabilities[cap].add(_key(m["framework"], m["control_id"]))

    @staticmethod
    def edge_cap(edge: dict) -> int:
        """How strong a flag this edge may carry. A proposed hypothesis never carries a complete weakness flag."""
        reliance = 3 if edge.get("reliance") == "complete" else 2
        return min(reliance, 3 if edge.get("review_status") == "APPROVED" else 2)

    def downstream(self, control: str, status: str, max_depth: int = 3, findings: list[str] | tuple = ()) -> list[dict]:
        linked = defaultdict(list)
        for code in findings:
            if code in FINDING_LINKS:
                linked[FINDING_LINKS[code]].append(code)
        severity = SEVERITY[status_of(status)]
        if severity == 0:
            return []
        flags, frontier = {}, [(control, severity, [control], [])]
        for depth in range(1, max_depth + 1):
            nxt = []
            for node, level, path, edges in frontier:
                for child, edge in self.down.get(node, []):
                    strength = min(level, self.edge_cap(edge)) - (1 if depth > 1 else 0)
                    if strength <= 0 or child in path:
                        continue
                    if child not in flags or strength > flags[child]["_strength"]:
                        flags[child] = {"control": child, "flag": LEVELS[strength], "_strength": strength, "depth": depth,
                                        "path": path + [child], "because": [e["relation"] for e in edges + [edge]],
                                        "edges": [e["edge_id"] for e in edges + [edge]],
                                        "edge_status": sorted({e["review_status"] for e in edges + [edge]}),
                                        "evidenced_by": sorted(linked.get(child, [])),
                                        "corroborate": edge["corroboration_rule"],
                                        "evidence_required": edge["evidence_required"]}
                        nxt.append((child, strength, path + [child], edges + [edge]))
            frontier = nxt
        rank = {"RELIANCE_IMPAIRED": 0, "RELIANCE_REDUCED": 1, "WATCH": 2}
        return sorted(({k: v for k, v in f.items() if k != "_strength"} for f in flags.values()),
                      key=lambda f: (rank[f["flag"]], f["depth"], f["control"]))

    def peers(self, control: str) -> list[dict]:
        """Controls in any framework mapped to the same capability: a lapse here puts them on watch."""
        found = defaultdict(list)
        for cap, members in self.capabilities.items():
            if control in members:
                for other in members - {control}:
                    found[other].append(cap)
        return [{"control": c, "flag": "WATCH", "shared_capabilities": sorted(caps),
                 "because": ["Mapped to the same capability in the crosswalk (not a claim of regulatory equivalence)."]}
                for c, caps in sorted(found.items())]

    def ancestors(self, control: str, max_depth: int = 3) -> list[dict]:
        out, frontier, seen = [], [(control, [control], [])], {control}
        for depth in range(1, max_depth + 1):
            nxt = []
            for node, path, edges in frontier:
                for parent, edge in self.up.get(node, []):
                    if parent in seen:
                        continue
                    seen.add(parent)
                    out.append({"control": parent, "depth": depth, "path": [parent] + path, "edges": edges + [edge]})
                    nxt.append((parent, [parent] + path, edges + [edge]))
            frontier = nxt
        return out

    def root_cause(self, control: str, statuses: dict[str, str], findings: list[str] | tuple = ()) -> list[dict]:
        state = {k: status_of(v) for k, v in statuses.items()}
        evidenced = defaultdict(list)
        for code in findings:
            if code in FINDING_LINKS:
                evidenced[FINDING_LINKS[code]].append(code)
        candidates = []
        for a in self.ancestors(control):
            s = state.get(a["control"], UNKNOWN)
            lapsed_above = any(state.get(x["control"]) in (LAPSED, WEAK) or x["control"] in evidenced
                               for x in self.ancestors(a["control"]))
            if a["control"] in evidenced and not lapsed_above:
                verdict = "LIKELY_ROOT_CAUSE"
            elif a["control"] in evidenced:
                verdict = "CONTRIBUTING"
            elif s in (LAPSED, WEAK):
                verdict = "CONTRIBUTING" if lapsed_above else "LIKELY_ROOT_CAUSE"
            elif s == EFFECTIVE:
                verdict = "RULED_OUT_ON_THIS_PATH"
            else:
                verdict = "UNVERIFIED_TEST_NEXT"
            first = a["edges"][-1]
            candidates.append({"control": a["control"], "status": s, "assessment": verdict, "depth": a["depth"],
                               "evidenced_by": sorted(evidenced.get(a["control"], [])),
                               "path": a["path"], "because": [e["relation"] for e in reversed(a["edges"])],
                               "test": first["corroboration_rule"], "evidence_required": first["evidence_required"],
                               "alternatives": first["alternatives"]})
        order = {"LIKELY_ROOT_CAUSE": 0, "CONTRIBUTING": 1, "UNVERIFIED_TEST_NEXT": 2, "RULED_OUT_ON_THIS_PATH": 3}
        return sorted(candidates, key=lambda c: (order[c["assessment"]], c["depth"], c["control"]))

    def analyse(self, statuses: dict[str, str], findings: dict[str, list[str]] | None = None) -> dict:
        """Everything at once: each lapse's downstream flags and root-cause candidates, and shared (common) causes.
        `findings` maps a lapsed control to the deterministic finding codes on its record."""
        findings = findings or {}
        state = {k: status_of(v) for k, v in statuses.items()}
        lapses = sorted(k for k, s in state.items() if s in (LAPSED, WEAK))
        per = {}
        reached = defaultdict(set)
        for control in lapses:
            causes = self.root_cause(control, statuses, findings.get(control, ()))
            for c in causes:
                if c["assessment"] in ("LIKELY_ROOT_CAUSE", "CONTRIBUTING", "UNVERIFIED_TEST_NEXT"):
                    reached[c["control"]].add(control)
            per[control] = {"status": state[control], "findings": sorted(findings.get(control, ())),
                            "downstream": self.downstream(control, state[control], findings=findings.get(control, ())),
                            "peers": self.peers(control), "root_cause": causes,
                            "root_cause_local": not any(c["assessment"] in ("LIKELY_ROOT_CAUSE", "CONTRIBUTING")
                                                        for c in causes)}
        common = [{"control": c, "explains": sorted(ls), "status": state.get(c, UNKNOWN)}
                  for c, ls in reached.items() if len(ls) >= 2]
        flagged = defaultdict(list)
        for control, result in per.items():
            for f in result["downstream"]:
                if f["control"] not in lapses:
                    flagged[f["control"]].append({"from": control, "flag": f["flag"]})
        return {"lapses": per, "common_causes": sorted(common, key=lambda c: (-len(c["explains"]), c["control"])),
                "flagged_controls": {k: sorted(v, key=lambda x: x["flag"]) for k, v in sorted(flagged.items())},
                "knowledge_version": self.version, "knowledge_sha256": self.knowledge_sha256,
                "changes_control_verdict": False, "non_inference": NON_INFERENCE,
                "coverage_statement": "Bounded to the proposed dependency catalogue and the crosswalk; a control with "
                                      "no edges has no modelled dependencies, which is not the same as none."}

    def dot(self, statuses: dict[str, str], focus: str | None = None) -> str:
        """Graphviz source for the app: lapses red, flagged amber, effective green, unknown grey."""
        state = {k: status_of(v) for k, v in statuses.items()}
        result = self.analyse(statuses)
        flagged = result["flagged_controls"]
        nodes = set(state) | set(flagged) | {focus} if focus else set(state) | set(flagged)
        for control in list(result["lapses"]):
            nodes |= {c["control"] for c in result["lapses"][control]["root_cause"]}
        colours = {LAPSED: "#F87171", WEAK: "#FDBA74", EFFECTIVE: "#86EFAC", UNKNOWN: "#E5E7EB"}
        lines = ['digraph impact {', '  rankdir=LR; node [shape=box, style="rounded,filled", fontname="Helvetica", fontsize=10];']
        for n in sorted(x for x in nodes if x):
            fill = colours[state.get(n, UNKNOWN)]
            if n in flagged and state.get(n, UNKNOWN) == UNKNOWN:
                fill = "#FDE68A"
            label = n.replace(":", "\\n") + (f"\\n{flagged[n][0]['flag']}" if n in flagged else "")
            lines.append(f'  "{n}" [label="{label}", fillcolor="{fill}"{", penwidth=2" if n == focus else ""}];')
        for u in sorted(nodes):
            for d, edge in self.down.get(u, []):
                if d in nodes:
                    lines.append(f'  "{u}" -> "{d}" [tooltip="{edge["relation"][:80]}"];')
        return "\n".join(lines + ["}"])


def statuses_from_ledger() -> dict[str, str]:
    """The latest human decision per control in the workbench ledger (sufficiency: none / partial / full)."""
    import events
    latest = {}
    for s in events.iter_states():
        decision = s.get("decision") or {}
        value = decision.get("sufficiency") or (decision.get("reviewer_decision") or {}).get("sufficiency")
        if value and s.get("control_id"):
            latest[_key(s.get("framework", ""), s["control_id"])] = value
    return latest


def statuses_from_pilot(config: dict, root) -> tuple[dict[str, str], dict[str, list[str]]]:
    """The pilot series: each period's deterministic verdict for its control, with its finding codes (latest period
    with a record wins)."""
    from governance.production import recurring
    statuses, findings = {}, {}
    for period in recurring.load(config, root)["payload"]["periods"]:
        journal = recurring._journal(config, root, period["investigation_id"])
        record = recurring._record(journal)
        if not record:
            continue
        rec = journal.latest("obligation_reconciliation")["payload"]
        key = _key("INTERNAL", config.get("pilot_control_id") or rec.get("control_id") or "CHANGE.MGMT")
        statuses[key] = record.get("deterministic_verdict")
        findings[key] = sorted({i["code"] for i in rec.get("issues", [])})
    return statuses, findings
