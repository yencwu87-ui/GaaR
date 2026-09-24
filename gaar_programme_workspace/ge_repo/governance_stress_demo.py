#!/usr/bin/env python3
"""Governance stress/demo harness.

Read-only by default. It attacks the governance boundaries rather than scoring model quality.

Usage:
    python governance_stress_demo.py --repo /path/to/repo
    python governance_stress_demo.py --repo /path/to/repo --strict

The harness deliberately distinguishes:
  PASS   = boundary demonstrated by code/runtime assertion
  FAIL   = a bypass or violated invariant was found
  OPEN   = the architecture says the primitive should exist, but the live path is not yet wired
  UNKNOWN= cannot be established from this read-only harness

It never changes the repository and never calls an LLM or writes the event ledger.
"""
from __future__ import annotations

import argparse
import ast
import importlib
import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from types import ModuleType
from typing import Callable, Iterable


@dataclass
class Result:
    id: str
    status: str
    detail: str
    evidence: str = ""


RESULTS: list[Result] = []


def record(test_id: str, status: str, detail: str, evidence: str = "") -> None:
    RESULTS.append(Result(test_id, status, detail, evidence))


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def parse(path: Path) -> ast.AST | None:
    text = read_text(path)
    if not text:
        return None
    try:
        return ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        record(
            f"syntax:{path.name}",
            "FAIL",
            f"Cannot parse {path.name}: {exc}",
        )
        return None


def find_function(tree: ast.AST | None, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    if tree is None:
        return None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def source_segment(path: Path, node: ast.AST) -> str:
    text = read_text(path)
    try:
        return ast.get_source_segment(text, node) or ""
    except Exception:
        return ""


def find_py_files(repo: Path) -> list[Path]:
    return sorted(p for p in repo.rglob("*.py") if ".venv" not in p.parts and "__pycache__" not in p.parts)


def locate(repo: Path, *candidates: str) -> Path | None:
    for rel in candidates:
        p = repo / rel
        if p.exists():
            return p
    return None


def static_checks(repo: Path) -> None:
    app = locate(repo, "app.py")
    cycle = locate(repo, "core/cycle.py", "cycle.py")
    challenge = locate(repo, "challenge.py")

    # 1. Blind review is structural, not just UI order.
    if cycle:
        tree = parse(cycle)
        fn = find_function(tree, "proposal_for_reviewer")
        seg = source_segment(cycle, fn) if fn else ""
        if fn and "if not s.get(\"read\")" in seg and "return None" in seg:
            record("blind_read_gate", "PASS", "proposal_for_reviewer() withholds the proposal before a reviewer read.", f"{cycle}: {fn.lineno}")
        else:
            record("blind_read_gate", "FAIL", "Could not prove proposal withholding before reviewer read.")
    else:
        record("blind_read_gate", "UNKNOWN", "core/cycle.py not found.")

    # 2. Decision boundary.
    if cycle:
        tree = parse(cycle)
        fn = find_function(tree, "decide")
        seg = source_segment(cycle, fn) if fn else ""
        has_reviewer_input = "reviewer_decision" in seg and "sufficiency" in seg and "reason" in seg
        has_eval = "evaluate_governance" in seg
        has_append = 'events.append("decided"' in seg
        if fn and has_reviewer_input and has_eval and has_append:
            record("human_decision_boundary", "PASS", "decide() constructs the governed evaluation from reviewer_decision and writes the decided event.", f"{cycle}: {fn.lineno}")
        else:
            record("human_decision_boundary", "FAIL", "Could not prove reviewer decision is centered at the decision boundary.")
    else:
        record("human_decision_boundary", "UNKNOWN", "cycle module not found.")

    # 3. The governed challenge path exists.
    if cycle:
        tree = parse(cycle)
        fn = find_function(tree, "challenge")
        seg = source_segment(cycle, fn) if fn else ""
        if fn and "challenge_disagreement" in seg and 'events.append("challenged"' in seg:
            record("governed_challenge_path", "PASS", "cycle.challenge() delegates to challenge_disagreement and records the challenged envelope.", f"{cycle}: {fn.lineno}")
        else:
            record("governed_challenge_path", "FAIL", "The cycle-level challenge delegation/recording path could not be proved.")
    else:
        record("governed_challenge_path", "UNKNOWN", "cycle module not found.")

    # 4. The UI must not become a second challenge entry path.
    if app:
        tree = parse(app)
        direct_calls: list[int] = []
        direct_imports: list[int] = []
        for node in ast.walk(tree) if tree else []:
            if isinstance(node, ast.ImportFrom) and node.module == "challenge":
                for alias in node.names:
                    if alias.name == "challenge_disagreement":
                        direct_imports.append(node.lineno)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                # common aliases in the current workbench include run_challenge2
                if node.func.id in {"challenge_disagreement", "run_challenge2"}:
                    direct_calls.append(node.lineno)
        if direct_imports or direct_calls:
            record(
                "no_parallel_ui_challenge_constructor",
                "FAIL",
                "app.py directly imports/calls challenge_disagreement; this is a parallel runtime entry path instead of delegating through cycle.challenge().",
                f"imports={direct_imports}, calls={direct_calls}",
            )
        else:
            record("no_parallel_ui_challenge_constructor", "PASS", "app.py does not directly call challenge_disagreement.")
    else:
        record("no_parallel_ui_challenge_constructor", "UNKNOWN", "app.py not found.")

    # 5. No second challenge constructor elsewhere.
    challenge_call_sites: list[str] = []
    for path in find_py_files(repo):
        if path.name == "challenge.py":
            continue
        tree = parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_text = ""
                if isinstance(node.func, ast.Name):
                    func_text = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_text = node.func.attr
                if func_text == "challenge_disagreement" or func_text == "run_challenge2":
                    challenge_call_sites.append(f"{path}:{node.lineno}")
    # cycle.py is the permitted delegation path; anything else is a bypass.
    production_sites = []
    tests_root = repo / "tests"
    for site in challenge_call_sites:
        site_path = Path(site.split(":", 1)[0])
        is_test_code = tests_root.exists() and (site_path == tests_root or tests_root in site_path.parents)
        is_harness = site_path.name == "governance_stress_demo.py"
        if not is_test_code and not is_harness:
            production_sites.append(site)
    bypass = [x for x in production_sites if not ("/core/cycle.py:" in x or x.endswith("/cycle.py:1"))]
    if bypass:
        record("single_challenge_constructor_boundary", "FAIL", "Found challenge_disagreement call sites outside the cycle delegation boundary.", "; ".join(bypass))
    else:
        record("single_challenge_constructor_boundary", "PASS", "No non-cycle direct calls to challenge_disagreement were found.")

    # 6. Evidence bundle mutation guard exists and is used before proposal.
    if cycle:
        tree = parse(cycle)
        guard = find_function(tree, "check_bundle_unchanged")
        assess = find_function(tree, "assess")
        gseg = source_segment(cycle, guard) if guard else ""
        aseg = source_segment(cycle, assess) if assess else ""
        if guard and "bundle_hash_at_scan" in gseg and "check_bundle_unchanged(cycle_id)" in aseg:
            record("bundle_mutation_guard", "PASS", "Bundle mutation is checked before proposal generation.", f"{cycle}: check_bundle_unchanged + assess")
        else:
            record("bundle_mutation_guard", "FAIL", "Could not prove the proposal-time bundle hash guard is wired.")
    else:
        record("bundle_mutation_guard", "UNKNOWN", "cycle module not found.")

    # 7. Cycle-time freshness is intentionally still open.
    if cycle:
        tree = parse(cycle)
        fn = find_function(tree, "decide")
        seg = source_segment(cycle, fn) if fn else ""
        freshness_terms = ["fresh_until", "is_stale", "freshness", "DEGRADED"]
        if any(t in seg for t in freshness_terms):
            record("decision_time_freshness", "PASS", "decide() contains a freshness decision-time hook.", f"{cycle}: {fn.lineno}")
        else:
            record("decision_time_freshness", "OPEN", "No decision-time freshness evaluation is wired into decide(); fresh_until can exist without affecting a later decision.")
    else:
        record("decision_time_freshness", "UNKNOWN", "cycle module not found.")

    # 8. Baseline gate is intentionally open until the new increment protocol is built.
    baseline = locate(repo, "governance/SEMANTIC_BASELINE.json", "SEMANTIC_BASELINE.json")
    if baseline:
        record("baseline_manifest_exists", "PASS", "Semantic baseline manifest exists.", str(baseline))
    else:
        record("baseline_manifest_exists", "OPEN", "No semantic baseline manifest found in the target checkout.")

    # A manifest existing is not the same as a hard gate.
    gate_hits = []
    for name in ("baseline_gate.py", "governance/baseline_gate.py", "tools/baseline_gate.py"):
        p = repo / name
        if p.exists():
            gate_hits.append(str(p))
    if gate_hits:
        record("baseline_hard_gate", "PASS", "A named baseline gate implementation is present.", "; ".join(gate_hits))
    else:
        record("baseline_hard_gate", "OPEN", "Baseline manifest exists/was expected, but no named hard-fail baseline gate was found by the harness.")

    # 9. Test integrity is deliberately separated from the frozen semantic manifest.
    test_gate_hits = []
    for path in find_py_files(repo):
        text = read_text(path)
        if "SEMANTIC_BASELINE" in text and ("tests" in text or "pytest" in text):
            test_gate_hits.append(str(path))
    if test_gate_hits:
        record("test_integrity_visibility", "PASS", "At least one code path explicitly considers test integrity alongside the semantic baseline.", "; ".join(test_gate_hits[:5]))
    else:
        record("test_integrity_visibility", "UNKNOWN", "The baseline manifest does not visibly govern tests; decide whether tests get a separate integrity signal.")


def runtime_checks(repo: Path) -> None:
    sys.path.insert(0, str(repo))
    try:
        challenge = importlib.import_module("challenge")
    except Exception as exc:
        record("runtime_challenge_import", "UNKNOWN", f"Could not import challenge.py: {type(exc).__name__}: {exc}")
        return

    # A. Agreement must be non-challengeable without touching the model.
    try:
        challenge.challenge_disagreement(
            {"id": "STRESS-001", "title": "Stress", "lib": "TEST"},
            "Evidence source=demo locator=line:1 quote=Control is reviewed.",
            {"sufficiency": "partial", "maturity": 2},
            {"sufficiency": "partial", "proposedMaturity": 2},
            {"comparable": True, "disagreements": [], "rows": []},
        )
    except ValueError as exc:
        if "agree on every compared element" in str(exc):
            record("agreement_not_challengeable", "PASS", "Full agreement is refused before model invocation.")
        else:
            record("agreement_not_challengeable", "FAIL", f"Unexpected refusal: {exc}")
    except Exception as exc:
        record("agreement_not_challengeable", "FAIL", f"Unexpected error: {type(exc).__name__}: {exc}")
    else:
        record("agreement_not_challengeable", "FAIL", "Challenge unexpectedly proceeded despite zero disagreements.")

    # B. Prompt stress: inspect exactly the outgoing disagreement prompt.
    try:
        original_req = challenge._control_requirement_context
        original_testing = challenge.get_testing_context
        challenge._control_requirement_context = lambda control_id, framework="": (
            "A governed requirement.",
            [
                "e1: first governed element.",
                "e2: second governed element.",
                "e3: third governed element.",
            ],
            {},
        )
        challenge.get_testing_context = lambda control_id, framework="": {
            "near_miss_failure_modes": [], "resolutions": [], "test_of_design": [], "test_of_operating_effectiveness": []
        }
        diff = {
            "comparable": True,
            "disagreements": ["e1"],
            "rows": [
                {"element_id": "e1", "text": "first governed element.", "reviewer": "met", "ai": "not_evidenced"},
                {"element_id": "e2", "text": "second governed element.", "reviewer": "met", "ai": "met"},
            ],
        }
        prompt = challenge._prompt_disagreement(
            {"id": "STRESS-001", "title": "Stress", "lib": "TEST"},
            "source=demo\nlocator=line:1\nquote=first governed element is supported.",
            {"sufficiency": "partial", "maturity": 2, "reason": "Reviewer read"},
            {"sufficiency": "partial", "proposedMaturity": 2, "rationale": "Assessor read"},
            diff,
            "(no retrieval)",
            "",
        )
        scoped_marker = "THE DISAGREEMENT — work only on these elements:"
        after = prompt.split(scoped_marker, 1)[1] if scoped_marker in prompt else ""
        evidence_marker = "Overall positions, for context only."
        scoped_block = after.split(evidence_marker, 1)[0] if evidence_marker in after else after
        ok_scope = "e1:" in scoped_block and "e2:" not in scoped_block
        ok_norate = "Do not rate the control." in prompt
        if ok_scope and ok_norate:
            record("outgoing_prompt_scope_no_rating", "PASS", "The outgoing challenge prompt scopes the disagreement to e1 and explicitly says not to rate the control.")
        else:
            record("outgoing_prompt_scope_no_rating", "FAIL", f"Prompt contract mismatch: scope_ok={ok_scope}, no_rating_ok={ok_norate}")
    except Exception as exc:
        record("outgoing_prompt_scope_no_rating", "UNKNOWN", f"Prompt test could not execute: {type(exc).__name__}: {exc}")
    finally:
        try:
            challenge._control_requirement_context = original_req
            challenge.get_testing_context = original_testing
        except Exception:
            pass

    # C. Pure scope filter attack: model tries to smuggle e2 into an e1-only challenge.
    try:
        kept, dropped = challenge.scope_filter(
            [
                {"requirement_pointer": {"element_id": "e1"}},
                {"requirement_pointer": {"element_id": "e2"}},
                {"requirement_pointer": {"element_id": "e999"}},
            ],
            ["e1"],
        )
        if len(kept) == 1 and kept[0]["requirement_pointer"]["element_id"] == "e1" and dropped == 2:
            record("scope_filter_smuggling", "PASS", "Out-of-scope e2/e999 challenges are dropped before admission.")
        else:
            record("scope_filter_smuggling", "FAIL", f"Unexpected filter result: kept={kept}, dropped={dropped}")
    except Exception as exc:
        record("scope_filter_smuggling", "UNKNOWN", f"Scope filter unavailable: {type(exc).__name__}: {exc}")

    # D. Explicitly probe whether an unexpected governance-rating field can survive normalization.
    # This is intentionally a red-team test: the system prompt is not the enforcement boundary.
    try:
        allowed_runtime_keys = {"rating", "sufficiency", "maturity", "verdict", "decision", "posture"}
        original_reqptr = challenge._requirement_pointer_context
        original_resolution = challenge._derive_resolution_pointer
        challenge._requirement_pointer_context = lambda control_id, framework="": (
            "req", [{"id": "e1", "text": "first governed element.", "locator": "controls.STRESS-001.elements[e1]"}], {}, "control_contract"
        )
        challenge._derive_resolution_pointer = lambda raw, control_id, framework: "request_evidence"
        base = {
            "observation": "Observed demo fact",
            "evidence_basis": ["The quoted fact"],
            "requirement_basis": ["first governed element."],
            "inference": "The fact bears on e1.",
            "challenge": "Ask whether the evidence really establishes e1.",
            "factual_pointer": {
                "source": "demo",
                "locator": "line:1",
                "quote": "The quoted fact",
                "fact": "The quoted fact",
                "what_it_supports": "e1",
            },
            "requirement_pointer": {
                "control_id": "STRESS-001",
                "locator": "controls.STRESS-001.elements[e1]",
                "element_id": "e1",
                "text": "first governed element.",
            },
            "risk_to_address": "Overclaiming evidence",
            "resolution_pointer": "request_evidence",
            "recommended_action": "request_evidence",
            "severity": "medium",
            "confidence": "high",
            "claim_test": {"claim": "e1 is met", "fact_meaning": "The quote exists", "rebuttal": "It does not establish e1"},
            "rating": "full",  # hostile extra field
        }
        validated = challenge._validate_structured(
            {"overall_reasoning": "hostile test", "challenges": [base], "rating": "full"},
            [],
            "The quoted fact",
            "STRESS-001",
            reviewer_read={"element_verdicts": [{"element_id": "e1", "status": "met"}]},
            framework="TEST",
        )
        found = []
        if any(k in validated for k in allowed_runtime_keys):
            found.extend(k for k in allowed_runtime_keys if k in validated)
        for row in validated.get("challenges") or []:
            found.extend(k for k in allowed_runtime_keys if k in row)
        if found:
            record("no_rating_enforcement", "FAIL", "Unexpected governance-rating fields survived challenger normalization; the prompt alone is not an enforcement boundary.", ", ".join(sorted(set(found))))
        else:
            record("no_rating_enforcement", "PASS", "Hostile rating fields were absent from the admitted challenge artifact.")
    except Exception as exc:
        record("no_rating_enforcement", "UNKNOWN", f"Could not execute hostile output normalization probe: {type(exc).__name__}: {exc}")
    finally:
        try:
            challenge._requirement_pointer_context = original_reqptr
            challenge._derive_resolution_pointer = original_resolution
        except Exception:
            pass


def demo_sequence() -> list[dict]:
    return [
        {"step": 1, "attack": "Show AI proposal before reviewer read", "expected": "withheld"},
        {"step": 2, "attack": "Run challenge with no disagreement", "expected": "refused before model"},
        {"step": 3, "attack": "Send challenge prompt with e1 disagreement and e2 agreement", "expected": "outgoing prompt scopes the disagreement to e1"},
        {"step": 4, "attack": "Make model return e1 + e2 challenges", "expected": "e2 dropped"},
        {"step": 5, "attack": "Make model return an invented evidence quote", "expected": "challenge rejected"},
        {"step": 6, "attack": "Make model return a governance rating field", "expected": "rating not admitted"},
        {"step": 7, "attack": "Call a second UI challenge constructor", "expected": "hard failure in static scan"},
        {"step": 8, "attack": "Let a cycle age past evidence freshness", "expected": "decide() blocks the decision at the decision-time freshness boundary"},
        {"step": 9, "attack": "Re-pin the baseline silently after a drift", "expected": "hard failure once baseline gate is implemented"},
        {"step": 10, "attack": "Train retrieval/assessor on downstream reviewer determinations", "expected": "cannot be proven preventively; provenance audit required"},
    ]


def print_report(strict: bool = False) -> int:
    print("\nGovernance Stress Demo — red-team boundary report")
    print("=" * 64)
    for r in RESULTS:
        mark = {"PASS": "PASS", "FAIL": "FAIL", "OPEN": "OPEN", "UNKNOWN": "????"}.get(r.status, r.status)
        print(f"[{mark:5}] {r.id}: {r.detail}")
        if r.evidence:
            print(f"        {r.evidence}")
    print("\nAttack sequence")
    for row in demo_sequence():
        print(f"  {row['step']:>2}. {row['attack']} -> {row['expected']}")
    counts = {s: sum(r.status == s for r in RESULTS) for s in ("PASS", "FAIL", "OPEN", "UNKNOWN")}
    print("\nCounts:", json.dumps(counts, sort_keys=True))
    print("\nInterpretation: OPEN/UNKNOWN are not silently converted to PASS.")
    if strict and (counts["FAIL"] or counts["OPEN"] or counts["UNKNOWN"]):
        return 2
    return 1 if counts["FAIL"] else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--strict", action="store_true", help="return non-zero for FAIL, OPEN, or UNKNOWN")
    parser.add_argument("--static-only", action="store_true")
    args = parser.parse_args()
    repo = args.repo.resolve()
    if not repo.exists():
        print(f"Repository not found: {repo}", file=sys.stderr)
        return 2
    static_checks(repo)
    if not args.static_only:
        runtime_checks(repo)
    return print_report(strict=args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
