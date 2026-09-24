"""The governing policy is the source of truth; the software must enforce exactly what it says.

Hash-pinning the policy and the configuration separately cannot detect divergence between them. This test
can: it fails if the prose table, the policy's machine block, the enforced decision matrix, or the tools'
named defaults disagree.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = (ROOT / "docs/quality/quality_policy.md").read_text()


def _block():
    return json.loads(re.search(r"```policy\n(.*?)```", POLICY, re.S).group(1))


def _label(decision, assurance_only):
    from governance.decisions import DECISION_LABEL
    return DECISION_LABEL.get((decision, assurance_only),
                              decision + (" (assurance only)" if assurance_only else ""))


def test_the_enforced_decision_matrix_is_exactly_the_policy():
    from governance.decisions import DETERMINISTIC_DECISIONS
    block = {v: [tuple(d) for d in ds] for v, ds in _block()["decision_matrix"].items()}
    assert block == {v: [tuple(d) for d in ds] for v, ds in DETERMINISTIC_DECISIONS.items()}


def test_the_prose_table_says_what_the_policy_block_says():
    section = POLICY[POLICY.index("## 3."):POLICY.index("```policy")]
    rows = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0] in _block()["decision_matrix"]:
            rows[cells[0]] = cells[1]
    for verdict, decisions in _block()["decision_matrix"].items():
        assert rows.get(verdict) == " · ".join(_label(d, a) for d, a in decisions), verdict
    assert set(rows) == set(_block()["decision_matrix"]), "every verdict must appear in the prose table"


def test_no_verdict_on_the_deterministic_path_permits_pass():
    assert not any(d == "PASS" for ds in _block()["decision_matrix"].values() for d, _ in ds)


def test_the_signed_defaults_are_the_ones_the_tools_use():
    defaults = _block()["defaults"]
    tool = (ROOT / "tools/gaar_recurring.py").read_text()
    assert re.search(r'"--grace-days", type=int, default=(\d+)', tool).group(1) == str(defaults["grace_days"])
    assert re.search(r'"--slack-minutes", type=int, default=(\d+)', tool).group(1) == str(defaults["slack_minutes"])
    recurring = (ROOT / "governance/production/recurring.py").read_text()
    runtime = (ROOT / "governance/operations/runtime.py").read_text()
    assert f'.get("grace_days", {defaults["grace_days"]})' in recurring
    assert f".get('slack_minutes', {defaults['slack_minutes']})" in runtime
