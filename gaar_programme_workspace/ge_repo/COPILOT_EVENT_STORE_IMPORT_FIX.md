# Copilot V1 — Event Store Import-Isolation Fix

## Root cause

The original full-suite failure was not caused by missing Copilot event writes.
`core.cycle.copilot_request()`, `record_read()`, and `decide()` already append the expected events, and `events.state()` projects `read`, `copilot_influence`, and `decision`.

The failure was caused by test-suite module contamination:

- `tests/test_ge109_boundary.py`
- `tests/test_ge110a_contract_integrity.py`
- `tests/test_ge110b2_provenance_repair.py`

were removing `events` and `core.cycle` from `sys.modules` and re-importing them during the same pytest process.

`tests/test_reviewer_copilot.py` had already imported its own `events` module object during collection. After the earlier tests replaced the `sys.modules["events"]` object, `core.cycle` wrote to the new module/log while `test_reviewer_copilot.py` continued reading from the old module/log.

This produced the observed pattern:

- `events.state(cid)` in the reviewer test appeared empty.
- `events.cycle(cid)` contained no Copilot events.
- `copilot_influence` and `decision` appeared missing.

The implementation itself was reachable; the test suite was reading a different event-store module instance.

## Fix

The three helpers now isolate tests by monkeypatching the canonical `events.LOG` path instead of evicting modules from `sys.modules`.

A regression test also asserts:

```python
core.cycle.events is events
```

and statically prevents tests from reintroducing `sys.modules.pop("events")` / `sys.modules.pop("core.cycle")`.

## Verification

Original sequence from the unmodified verification ZIP:

```text
62 passed, 2 skipped, 6 failed
```

The six failures were the six Copilot event/provenance failures reported by the Mac run.

Patched sequence:

```text
72 passed, 2 skipped
```

The standalone Copilot suite remains green as well.

The full repository suite in the sandbox still exceeds the available execution window; no full-suite PASS is claimed from that partial run.
