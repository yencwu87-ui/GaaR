#!/usr/bin/env python3
"""Every refusal must be exercised, not merely present.

Runs the pilot's tests under a coverage tracer and lists each refusal line (`raise`) that no test reaches.
A guard no test reaches is untested, however green the suite looks. Known gaps are allowed only if they are
written in docs/quality/unexercised_guards.md with a reason; anything else fails the check.

    python tools/trace_unreached_guards.py          (needs: pip install coverage)
"""
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULES = ["governance/production/reconciliation.py", "governance/production/completion.py",
           "governance/production/recurring.py", "governance/production/procedures.py", "governance/decisions.py",
           "governance/operations/runtime.py", "governance/production/lifecycle.py",
           "governance/production/policy_approval.py", "governance/production/gate_status.py",
           "governance/production/scheduler.py", "governance/production/inbox.py", "governance/watcher/intel.py",
           "governance/twin/generator.py", "governance/arena/arena.py", "governance/arena/contestants.py",
           "governance/arena/cases.py", "governance/arena/judge.py", "governance/twin/adjudication.py",
           "governance/basis.py", "governance/paths.py", "governance/names.py",
           "governance/watcher/mailbox.py"]
# The command-line tools are exercised by tests through separate processes, which this in-process tracer
# cannot see. They are excluded here and the gap is recorded in the register, rather than reported as passing.
TESTS = ["tests/test_decisions.py", "tests/test_reconciliation.py", "tests/test_completion.py",
         "tests/test_recurring.py", "tests/test_mapping.py", "tests/test_wb143_149_programme.py",
         "tests/test_guards_exercised.py", "tests/test_governance_events.py", "tests/test_policy_consistency.py",
         "tests/test_gate_status.py", "tests/test_core_guards_exercised.py", "tests/test_upgrade_rerun.py",
         "tests/test_inbox_and_scheduler.py", "tests/test_watch_intel.py", "tests/test_twin.py",
         "tests/test_arena.py", "tests/test_basis.py"]
REGISTER = ROOT / "docs/quality/unexercised_guards.md"


def main():
    try:
        import coverage
    except ImportError:
        raise SystemExit("install the tracer first: pip install coverage")
    data = ROOT / ".coverage.guards"
    run = subprocess.run([sys.executable, "-m", "coverage", "run", f"--data-file={data}", f"--include={','.join(MODULES)}",
                          "-m", "pytest", "-q", "-p", "no:cacheprovider", *TESTS], cwd=ROOT, text=True, capture_output=True)
    print((run.stdout.strip().splitlines() or ["(no test output)"])[-1])
    cov = coverage.Coverage(data_file=str(data))
    cov.load()
    unreached = []
    for name in MODULES:
        path = ROOT / name
        _, _, _, missing, _ = cov.analysis2(str(path))
        lines = path.read_text().splitlines()
        for n in missing:
            text = lines[n - 1].strip()
            if text.startswith("raise ") or " raise " in text:
                unreached.append((name, text))
    data.unlink(missing_ok=True)
    registered = REGISTER.read_text() if REGISTER.exists() else ""
    def message(text):
        literal = re.search(r"""['"]([^'"]{8,})""", text)
        return literal.group(1).strip() if literal else text
    unexplained = [(f, t) for f, t in unreached if message(t) not in registered]
    print(f"{len(unreached)} refusal line(s) unreached; {len(unreached) - len(unexplained)} listed in the register")
    for f, t in unexplained:
        print(f"  UNEXPLAINED  {f}: {t[:120]}")
    import datetime, hashlib, json
    record = {"kind": "guard_trace", "at": datetime.datetime.now().astimezone().isoformat(),
              "tests_exit_code": run.returncode, "tests_summary": (run.stdout.strip().splitlines() or [""])[-1],
              "modules": MODULES, "unreached": len(unreached), "registered": len(unreached) - len(unexplained),
              "unexplained": [f"{f}: {t}" for f, t in unexplained],
              "register_sha256": hashlib.sha256(REGISTER.read_bytes()).hexdigest() if REGISTER.exists() else None,
              "verdict": "PASS" if not unexplained and not run.returncode else "FAIL"}
    runs = ROOT / ".test_runs"
    runs.mkdir(exist_ok=True)
    target = runs / ("trace-" + record["at"].replace(":", "").replace("+", "_") + ".json")
    target.write_text(json.dumps(record, indent=2) + "\n")
    print(f"trace record: {target.relative_to(ROOT)}")
    raise SystemExit(1 if unexplained or run.returncode else 0)


if __name__ == "__main__":
    main()
