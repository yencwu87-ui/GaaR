#!/usr/bin/env python3
"""The canonical full test run.

    python tools/run_all_tests.py

"The suite passed" is only true relative to how it was run. This runner makes three things impossible
to miss:

1. A test file that fails to load. Pytest never lists its tests, so they would be absent from both the
   collected and executed counts. The runner counts collection errors and names the files.
2. Failures. The verdict line states them; "complete" never appears on its own.
3. The environment. It prints the Python and key package versions it ran under, because the same code
   in a different environment is a different test run.
"""
import importlib.metadata as md
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("GAAR_TEST_ROOT") or Path(__file__).resolve().parents[1])
BATCHES = int(os.environ.get("GAAR_TEST_BATCHES", "4"))
PACKAGES = ("pytest", "streamlit", "pydantic", "cryptography", "PyMuPDF")


def pytest(*args):
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args], cwd=ROOT,
                          text=True, capture_output=True)


def versions():
    found = []
    for name in PACKAGES:
        try:
            found.append(f"{name} {md.version(name)}")
        except md.PackageNotFoundError:
            found.append(f"{name} (not installed)")
    return ", ".join(found)


def requirement_problems(path=None):
    """Prevention: compare installed packages with requirements.txt before running a single test."""
    path = path or ROOT / "requirements.txt"
    if not path.is_file():
        return [], []
    try:
        from packaging.requirements import Requirement
    except ImportError:
        Requirement = None
    missing, mismatched = [], []
    for raw in path.read_text().splitlines():
        line = raw.split("#")[0].strip()
        if not line:
            continue
        if line.startswith("-r "):
            sub_missing, sub_mismatched = requirement_problems(path.parent / line[3:].strip())
            missing += sub_missing
            mismatched += sub_mismatched
            continue
        name = re.split(r"[<>=!~\[; ]", line, maxsplit=1)[0]
        try:
            installed = md.version(name)
        except md.PackageNotFoundError:
            missing.append(line)
            continue
        if Requirement is not None and not Requirement(line).specifier.contains(installed, prereleases=True):
            mismatched.append(f"{line} (installed {installed})")
    return missing, mismatched


def main():
    print(f"python {sys.executable} ({sys.version.split()[0]})")
    print(f"packages: {versions()}")
    print(f"conda env: {os.environ.get('CONDA_DEFAULT_ENV', '(none)')}")
    # The runner's guarantee covers the runner: the test tooling (requirements-dev.txt) is checked too.
    dev = ROOT / "requirements-dev.txt"
    missing, mismatched = requirement_problems(dev) if dev.is_file() else requirement_problems()
    if missing:
        print("MISSING from this environment (pip install -r requirements.txt):")
        for line in missing:
            print(f"  {line}")
    if mismatched:
        print("Installed at a version outside requirements.txt:")
        for line in mismatched:
            print(f"  {line}")
    if not missing and not mismatched:
        print("environment matches requirements.txt")
    print()

    listing = pytest("--collect-only")
    ids = [line for line in listing.stdout.splitlines() if "::" in line]
    load_errors = sorted({m.group(1) for m in re.finditer(r"^ERROR (\S+)", listing.stdout, re.M)})
    files = sorted({line.split("::")[0] for line in ids})
    collected = len(ids)

    totals = {"passed": 0, "failed": 0, "skipped": 0, "error": 0}
    failing, skipped_lines = [], []
    for index in range(BATCHES):
        batch = files[index::BATCHES]
        if not batch:
            continue
        result = pytest("-rfEs", *batch)
        lines = result.stdout.strip().splitlines()
        summary = lines[-1] if lines else "(no output)"
        for count, word in re.findall(r"(\d+) (passed|failed|skipped|errors?)", summary):
            totals["error" if word.startswith("error") else word] += int(count)
        failing += [line for line in lines if line.startswith(("FAILED ", "ERROR "))]
        skipped_lines += [line for line in lines if line.startswith("SKIPPED ")]
        print(f"batch {index + 1}/{BATCHES}: {summary}")

    executed = sum(totals.values())
    print(f"\nCOLLECTED {collected} · EXECUTED {executed} · passed {totals['passed']} · failed {totals['failed']} "
          f"· skipped {totals['skipped']} · errors {totals['error']} · files that failed to load {len(load_errors)}")
    if load_errors:
        print("\nTest files that failed to load (their tests are not counted anywhere above):")
        for name in load_errors:
            print(f"  {name}")
    if failing:
        print(f"\nFailing tests ({len(failing)}):")
        for line in failing[:80]:
            print(f"  {line[:200]}")
        if len(failing) > 80:
            print(f"  … and {len(failing) - 80} more")

    if skipped_lines:
        print("\nSkipped — not passed — with the reason each gave:")
        for line in skipped_lines:
            print(f"  {line[:220]}")

    complete = executed == collected and not load_errors
    passing = complete and not totals["failed"] and not totals["error"]
    record = {"at": __import__("datetime").datetime.now().astimezone().isoformat(), "python": sys.executable,
              "python_version": sys.version.split()[0], "conda_env": os.environ.get("CONDA_DEFAULT_ENV"),
              "packages": versions(), "requirements_sha256": {
                  name: __import__("hashlib").sha256((ROOT / name).read_bytes()).hexdigest()
                  for name in ("requirements.txt", "requirements-dev.txt") if (ROOT / name).is_file()},
              "environment_missing": missing, "environment_mismatched": mismatched,
              "collected": collected, "executed": executed, **totals, "files_failed_to_load": load_errors,
              "skipped_with_reasons": skipped_lines, "failing": failing}
    if passing and missing:
        print("\nVERDICT: COMPLETE RUN, ALL PASSED — but the environment is missing required packages (listed above)")
    elif passing:
        print(f"\nVERDICT: COMPLETE RUN, ALL PASSED ({totals['skipped']} skipped, listed with reasons above)"
              if totals["skipped"] else "\nVERDICT: COMPLETE RUN, ALL PASSED")
    elif complete:
        print(f"\nVERDICT: COMPLETE RUN, NOT PASSING — {totals['failed']} failed, {totals['error']} errors")
    else:
        print(f"\nVERDICT: INCOMPLETE RUN — {len(load_errors)} file(s) failed to load, "
              f"{collected - executed} collected test(s) did not execute")
    record["verdict"] = ("COMPLETE RUN, ALL PASSED" if passing and not missing else
                         "COMPLETE RUN, NOT PASSING" if complete else "INCOMPLETE RUN")
    runs = ROOT / ".test_runs"
    runs.mkdir(exist_ok=True)
    target = runs / (record["at"].replace(":", "").replace("+", "_") + ".json")
    target.write_text(__import__("json").dumps(record, indent=2) + "\n")
    print(f"run record: {target.relative_to(ROOT)}")
    raise SystemExit(0 if passing and not missing else 1)


if __name__ == "__main__":
    main()
