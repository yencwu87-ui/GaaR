from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_tests_do_not_evict_canonical_event_modules_mid_suite():
    offenders = []
    for path in (ROOT / "tests").glob("test_*.py"):
        if path == Path(__file__):
            continue
        text = path.read_text(encoding="utf-8")
        if 'sys.modules.pop("events"' in text or "sys.modules.pop('events'" in text:
            offenders.append(str(path.relative_to(ROOT)))
        if 'sys.modules.pop("core.cycle"' in text or "sys.modules.pop('core.cycle'" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"tests must not evict canonical modules mid-suite: {offenders}"


def test_cycle_and_test_event_modules_resolve_to_one_object():
    import events
    import core.cycle as cycle
    assert cycle.events is events
