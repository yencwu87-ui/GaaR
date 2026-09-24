"""TEST ONLY — a control contract deliberately corrupted so the integrity refusal path is always exercised.

The refusal tests used to look for a control in the real library that fails integrity, and skipped when the
library was clean. A guard with nothing to guard against is untested, not proven. This fixture makes the
failure deterministic: it duplicates one element id of a real, valid control's contract, which the
integrity check rejects as DUPLICATE_ELEMENT_ID.

It exists only inside a test: it is installed through pytest's monkeypatch, which reverts it when the test
ends, and it is never written to disk, so nothing outside a test can pick it up.
"""
import copy

MARKER = "TEST_ONLY_DELIBERATELY_FAILING_CONTRACT"


def install_failing_contract(monkeypatch, control):
    from governance import control_contract
    real = control_contract.get_control_contract

    def corrupted(control_id, *args, **kwargs):
        contract = real(control_id, *args, **kwargs)
        if control_id != control.id or not contract:
            return contract
        contract = copy.deepcopy(contract)
        elements = list(contract.get("elements") or [])
        assert elements, "the fixture needs a control whose contract declares elements"
        contract["elements"] = elements + [dict(elements[0])]          # duplicate element id
        contract[MARKER] = True
        return contract

    monkeypatch.setattr(control_contract, "get_control_contract", corrupted)
    from governance.contract_integrity import status_for_control
    status = status_for_control(control)
    assert status["executable"] is False and any(f["code"] == "DUPLICATE_ELEMENT_ID" for f in status["findings"]), \
        "the test-only contract must fail integrity for the reason it was built to fail"
    return status
