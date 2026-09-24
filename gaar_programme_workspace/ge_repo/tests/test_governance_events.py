"""Policy approval, independent mapping review, and truthful display of what was signed.

Every test here writes approvals and reviews to temporary folders; none touches docs/ in the repository.
"""
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_recurring import ROOT, _cli, _load, _signed_mapping_with_demo_keys, _attest


@pytest.fixture
def policy_copy(tmp_path, monkeypatch):
    """A private copy of the governing policy, and a private approvals folder."""
    from governance.production import policy_approval as pa
    copy = tmp_path / "policy/quality_policy.md"
    copy.parent.mkdir()
    shutil.copyfile(pa.POLICY, copy)
    monkeypatch.setattr(pa, "POLICY", copy)
    monkeypatch.setattr(pa, "APPROVALS", tmp_path / "policy/approvals")
    return copy


def _keys(home):
    import subprocess, sys, os
    keys = home / ".gaar-test-keys"
    env = {**os.environ, "HOME": str(home)}
    for name in ("owner", "reviewer", "outsider"):
        if not (keys / f"{name}.key").exists():
            subprocess.run([sys.executable, str(ROOT / "tools/gaar_pilot.py"), "keygen", "--out",
                            str(keys / f"{name}.key")], check=True, env=env, capture_output=True)
    return keys


def _approve(keys, name="Test Owner", key="owner.key", confirm=None):
    import importlib
    sys_path_tool = importlib.import_module("tools.gaar_policy")
    from governance.production import policy_approval as pa
    confirm = confirm or pa.policy_identity(pa.POLICY)["policy_sha256"][:12]
    return sys_path_tool.approve(SimpleNamespace(key=str(keys / key), name=name, confirm=confirm))


def _authorise(home, **extra):
    import importlib
    tool = importlib.import_module("tools.gaar_recurring")
    args = SimpleNamespace(constructed_demo=True, workspace=str(home / "demo"), periods=None, reviewer_token_env="GAAR_REVIEWER_TOKEN",
                           mapping=None, mapping_review=None, policy_approval=None, grace_days=2, slack_minutes=10,
                           cadence_days=7, layout=None, element=None, reconcile=None)
    for key, value in extra.items():
        setattr(args, key, value)
    import os
    old = os.environ.get("HOME")
    os.environ["HOME"] = str(home)
    try:
        return tool.authorise(args)
    finally:
        os.environ["HOME"] = old


# ----- policy approval --------------------------------------------------------------------------------

def test_an_approval_must_name_the_exact_text_it_approves(tmp_path, policy_copy):
    keys = _keys(tmp_path)
    with pytest.raises(ValueError, match="must repeat the first 12 characters of the policy hash"):
        _approve(keys, confirm="000000000000")


def test_an_approval_stops_covering_the_policy_once_the_text_changes(tmp_path, policy_copy):
    from governance.production import policy_approval as pa
    keys = _keys(tmp_path)
    outcome = _approve(keys)
    document = pa.load(outcome["approval"])
    assert pa.verify(document)["approver"] == "Test Owner"
    assert document["payload"]["policy_version"] == pa.policy_identity(pa.POLICY)["policy_version"]
    policy_copy.write_text(policy_copy.read_text() + "\nA quiet edit after approval.\n")
    with pytest.raises(ValueError, match="has changed since it was approved"):
        pa.verify(document)


def test_a_real_evidence_series_cannot_be_authorised_without_an_approved_policy(tmp_path, policy_copy, monkeypatch):
    import importlib
    tool = importlib.import_module("tools.gaar_recurring")
    home = tmp_path / "home"
    home.mkdir()
    _keys(home)
    args = SimpleNamespace(constructed_demo=False, workspace=str(home / "demo"), periods=None, policy_approval=None,
                           mapping=None, mapping_review=None, reviewer_token_env="GAAR_REVIEWER_TOKEN", grace_days=2, slack_minutes=10)
    monkeypatch.setenv("HOME", str(home))
    tool._demo_defaults(args)                            # every other input a real series would have
    args.constructed_demo = False
    with pytest.raises(ValueError, match="needs an approved governing policy"):
        tool.authorise(args)
    assert not (home / "demo").exists(), "nothing may be provisioned before the policy check"


def test_an_approved_policy_is_pinned_and_a_later_edit_stops_the_series(tmp_path, policy_copy):
    from governance.production import recurring
    home = tmp_path / "home"
    home.mkdir()
    keys = _keys(home)
    approval = _approve(keys)
    result = _authorise(home, policy_approval=approval["approval"])
    config, root = _load(Path(result["config"]))
    payload = recurring.verify(config, root)
    from governance.production import policy_approval as pa
    assert payload["governing_policy_status"] == "APPROVED"
    assert payload["governing_policy_version"] == pa.policy_identity(pa.POLICY)["policy_version"]
    assert payload["authorisation_id_inputs"]["governing_policy_sha256"] == approval["policy_sha256"]
    policy_copy.write_text(policy_copy.read_text().replace("DRAFT", "draft"))
    with pytest.raises(ValueError, match="governing policy text has changed since this series was authorised"):
        recurring.verify(config, root)


def test_a_policy_approved_by_someone_outside_the_series_governance_is_refused(tmp_path, policy_copy):
    home = tmp_path / "home"
    home.mkdir()
    keys = _keys(home)
    approval = _approve(keys, name="Someone Else", key="outsider.key")
    with pytest.raises(ValueError, match="not a governance owner of this series"):
        _authorise(home, policy_approval=approval["approval"])


# ----- mapping review ---------------------------------------------------------------------------------

def _review(keys, document, key, name, outcome="AGREED"):
    import importlib
    tool = importlib.import_module("tools.gaar_mapping")
    return tool.review(SimpleNamespace(mapping=str(document), reviewer_key=str(keys / key), reviewer_name=name,
                                       outcome=outcome, notes="Checked every obligation's codes against its text."))


def test_the_mapping_signer_cannot_review_their_own_mapping(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    document = _signed_mapping_with_demo_keys(home, tmp_path)
    keys = _keys(home)
    with pytest.raises(ValueError, match="not independent"):
        _review(keys, document, "owner.key", "Independent Person")           # same key as the signer
    with pytest.raises(ValueError, match="not independent"):
        _review(keys, document, "outsider.key", "Test Owner")                # same name as the signer


def test_an_independent_review_is_pinned_recorded_by_d8_and_shown(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from governance.production import recurring
    home = tmp_path / "home"
    home.mkdir()
    document = _signed_mapping_with_demo_keys(home, tmp_path)
    keys = _keys(home)
    review = _review(keys, document, "outsider.key", "Independent Reviewer")
    result = _authorise(home, mapping=str(document), mapping_review=review["review"])
    config_path = Path(result["config"])
    config, root = _load(config_path)
    assert recurring.verify(config, root)["mapping_review_sha256"]
    _cli(home, "demo-inbox", "--config", config_path, "--week", 1)
    recurring.tick(config, root)
    rec = recurring._journal(config, root, "CHG-WEEKLY-2026-09-15").latest("obligation_reconciliation")["payload"]
    assert (rec["mapping_reviewed_by"], rec["mapping_review_outcome"]) == ("Independent Reviewer", "AGREED")
    monkeypatch.setenv("WB_INVESTIGATION_CONFIG", str(config_path))
    monkeypatch.setenv("GAAR_REVIEWER_TOKEN", "t")
    app = AppTest.from_file(str(ROOT / "app_gaar.py"), default_timeout=60).run()
    app.text_input[0].input("t").run()
    assert any("Mapping independently reviewed by **Independent Reviewer**: AGREED" in c.value for c in app.caption)
    assert any("authorised without an approved governing policy" in c.value for c in app.caption)

    review_file = Path(review["review"])
    tampered = json.loads(review_file.read_text())
    tampered["payload"]["outcome"] = "CHANGES_REQUESTED"
    review_file.write_text(json.dumps(tampered))
    with pytest.raises(ValueError, match="differs from the one the standing authorisation pins"):
        recurring.verify(config, root)


def test_changes_requested_is_recorded_and_warned_not_hidden(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    from governance.production import recurring
    home = tmp_path / "home"
    home.mkdir()
    document = _signed_mapping_with_demo_keys(home, tmp_path)
    keys = _keys(home)
    review = _review(keys, document, "outsider.key", "Independent Reviewer", outcome="CHANGES_REQUESTED")
    result = _authorise(home, mapping=str(document), mapping_review=review["review"])
    config, root = _load(Path(result["config"]))
    _cli(home, "demo-inbox", "--config", result["config"], "--week", 1)
    recurring.tick(config, root)
    monkeypatch.setenv("WB_INVESTIGATION_CONFIG", result["config"])
    monkeypatch.setenv("GAAR_REVIEWER_TOKEN", "t")
    app = AppTest.from_file(str(ROOT / "app_gaar.py"), default_timeout=60).run()
    app.text_input[0].input("t").run()
    assert any("CHANGES_REQUESTED" in w.value and "do not rely on this series" in w.value for w in app.warning)


# ----- display ----------------------------------------------------------------------------------------

def test_the_chip_and_attested_line_say_what_was_signed(tmp_path, monkeypatch):
    from datetime import datetime, timezone, timedelta
    from streamlit.testing.v1 import AppTest
    from governance.production import recurring
    home = tmp_path / "home"
    home.mkdir()
    result = _authorise(home)
    config_path = Path(result["config"])
    config, root = _load(config_path)
    _cli(home, "demo-inbox", "--config", config_path, "--week", 3)
    recurring.tick(config, root, now=datetime(2026, 10, 1, 9, tzinfo=timezone(timedelta(hours=8))))
    _attest(config, root, "CHG-WEEKLY-2026-09-29", "NO_EXCEPTIONS_NOTED", True,
            "Week 3 checked with corroborated coverage; nothing raised.")
    monkeypatch.setenv("WB_INVESTIGATION_CONFIG", str(config_path))
    monkeypatch.setenv("GAAR_REVIEWER_TOKEN", "t")
    app = AppTest.from_file(str(ROOT / "app_gaar.py"), default_timeout=60).run()
    app.text_input[0].input("t").run()
    app.sidebar.radio[0].set_value("CHG-WEEKLY-2026-09-29").run()
    assert not app.exception
    assert any("attested — No exceptions noted for this period (assurance only) · simulated clock" in m.value
               for m in app.markdown)
    assert any("Assessed under a simulated clock" in s.value and "recorded in this attestation" in s.value
               for s in app.success)
    assert not any("deterministic record — attest" in m.value for m in app.markdown)


# ----- every new refusal, triggered and expecting its exact message (D15: re-sign so the named guard fires) ----

def _signer(keys, key, name, role):
    import importlib
    gaar_pilot = importlib.import_module("tools.gaar_pilot")
    return gaar_pilot.load_human(str(keys / key), name, role, Path("/nonexistent-workspace"))[1]


def _resign(document, signer, **changes):
    from governance.investigation.store import canonical
    payload = {**document["payload"], **changes}
    return {**document, "payload": payload, "signature": signer.sign(canonical(payload).encode())}


def _reviewed(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    document = _signed_mapping_with_demo_keys(home, tmp_path)
    keys = _keys(home)
    review = json.loads(Path(_review(keys, document, "outsider.key", "Independent Reviewer")["review"]).read_text())
    return home, keys, document, review


def test_a_tampered_review_fails_its_signature(tmp_path):
    from governance.production.reconciliation import verify_mapping_review
    home, keys, document, review = _reviewed(tmp_path)
    review["payload"]["notes"] = "Edited after signing."
    with pytest.raises(ValueError, match="the mapping review signature is invalid"):
        verify_mapping_review(review, json.loads(document.read_text()))


def test_a_review_of_another_mapping_document_is_refused(tmp_path):
    from governance.production.reconciliation import verify_mapping_review
    home, keys, document, review = _reviewed(tmp_path)
    other = json.loads(document.read_text())
    other["payload"]["signed_at"] = "2026-01-01T00:00:00+0800"
    with pytest.raises(ValueError, match="the mapping review is about a different mapping document"):
        verify_mapping_review(review, other)


def test_a_review_outcome_outside_the_two_allowed_is_refused(tmp_path):
    from governance.production.reconciliation import verify_mapping_review
    home, keys, document, review = _reviewed(tmp_path)
    forged = _resign(review, _signer(keys, "outsider.key", "Independent Reviewer", "reviewer"), outcome="MOSTLY_FINE")
    with pytest.raises(ValueError, match="the mapping review outcome must be AGREED or CHANGES_REQUESTED"):
        verify_mapping_review(forged, json.loads(document.read_text()))


def test_a_tampered_policy_approval_fails_its_signature(tmp_path, policy_copy):
    from governance.production import policy_approval as pa
    document = pa.load(_approve(_keys(tmp_path))["approval"])
    document["payload"]["approver"] = "Someone More Senior"
    with pytest.raises(ValueError, match="the policy approval signature is invalid"):
        pa.verify(document)


def test_an_approval_without_the_required_statement_is_refused(tmp_path, policy_copy):
    from governance.production import policy_approval as pa
    keys = _keys(tmp_path)
    document = pa.load(_approve(keys)["approval"])
    forged = _resign(document, _signer(keys, "owner.key", "Test Owner", "governance"), statement="Looks fine.")
    with pytest.raises(ValueError, match="the policy approval does not carry the required statement"):
        pa.verify(forged)


def _approved_series(tmp_path, policy_copy, with_review=False):
    home = tmp_path / "home"
    home.mkdir()
    keys = _keys(home)
    approval = _approve(keys)
    extra = {"policy_approval": approval["approval"]}
    if with_review:
        document = _signed_mapping_with_demo_keys(home, tmp_path)
        review = _review(keys, document, "outsider.key", "Independent Reviewer")
        extra.update(mapping=str(document), mapping_review=review["review"])
    result = _authorise(home, **extra)
    config, root = _load(Path(result["config"]))
    return keys, approval, extra, config, root


def test_a_missing_pinned_approval_stops_the_series(tmp_path, policy_copy):
    from governance.production import recurring
    keys, approval, extra, config, root = _approved_series(tmp_path, policy_copy)
    Path(approval["approval"]).unlink()
    with pytest.raises(ValueError, match="the policy approval pinned by the standing authorisation is missing"):
        recurring.verify(config, root)


def test_a_substituted_approval_stops_the_series(tmp_path, policy_copy):
    from governance.production import recurring, policy_approval as pa
    keys, approval, extra, config, root = _approved_series(tmp_path, policy_copy)
    path = Path(approval["approval"])
    substitute = _resign(pa.load(path), _signer(keys, "owner.key", "Test Owner", "governance"),
                         approved_at="2026-01-01T00:00:00+0800")          # genuine, but not the one pinned
    path.write_text(json.dumps(substitute))
    with pytest.raises(ValueError, match="the policy approval differs from the one the standing authorisation pins"):
        recurring.verify(config, root)


def test_a_missing_pinned_review_stops_the_series(tmp_path, policy_copy):
    from governance.production import recurring
    keys, approval, extra, config, root = _approved_series(tmp_path, policy_copy, with_review=True)
    Path(extra["mapping_review"]).unlink()
    with pytest.raises(ValueError, match="the mapping review pinned by the standing authorisation is missing"):
        recurring.verify(config, root)



def test_two_people_can_each_approve_the_same_text(tmp_path, policy_copy):
    from governance.production import policy_approval as pa
    keys = _keys(tmp_path)
    first = _approve(keys)
    second = _approve(keys, name="Someone Else", key="outsider.key")
    assert first["approval"] != second["approval"]
    assert {pa.verify(pa.load(a["approval"]))["approver"] for a in (first, second)} == {"Test Owner", "Someone Else"}
    with pytest.raises(ValueError, match="this approver has already approved this text"):
        _approve(keys)
