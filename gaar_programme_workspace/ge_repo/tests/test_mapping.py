"""D8 mapping worksheet: draft from real evidence, sign by governance, apply before any run."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_reconciliation import IID, ROOT, _provision
from tools.gaar_phase0 import RECONCILIATION_MAP

TOOL = ROOT / "tools/gaar_mapping.py"


def _cli(*args):
    return subprocess.run([sys.executable, str(TOOL), *map(str, args)], text=True, capture_output=True)


def _tick_like(worksheet, mapping):
    for ob in worksheet["obligations"]:
        for code in ob["codes"]:
            code["include"] = code["code"] in mapping.get(ob["element_id"], [])
    return worksheet


def _drafted(tmp_path):
    config, root = _provision(tmp_path)
    config.pop("reconciliation_map")
    (root / "operations.json").write_text(json.dumps(config, indent=2))
    out = tmp_path / "mapping/worksheet.json"
    result = _cli("draft", "--config", root / "operations.json", "--out", out)
    assert result.returncode == 0, result.stderr
    return root, out


def test_draft_lists_every_real_code_with_where_it_fires_and_ticks_nothing(tmp_path):
    root, out = _drafted(tmp_path)
    worksheet = json.loads(out.read_text())
    assert [o["element_id"] for o in worksheet["obligations"]] == ["chg.1", "chg.2", "chg.3", "chg.4"]
    codes = {c["code"]: c for c in worksheet["obligations"][0]["codes"]}
    assert len(codes) == 13 and "RECORD_DISCREPANCY" not in codes
    assert codes["SELF_APPROVAL"]["fires_on"] == ["CHG-03"]
    assert codes["COLLECTION_POPULATION_DISAGREEMENT"]["fires_on"] == ["CHG-15"]
    assert codes["APPROVAL_AFTER_EXECUTION"]["type"] == "discrepancy"
    assert not any(c["include"] for o in worksheet["obligations"] for c in o["codes"])
    assert "| ☐ | SELF_APPROVAL |" in out.with_suffix(".md").read_text()


def test_sign_refuses_unfinished_or_invented_mappings(tmp_path):
    root, out = _drafted(tmp_path)
    config = root / "operations.json"
    blocked = _cli("sign", "--config", config, "--worksheet", out, "--confirm", "CHANGE.MGMT")
    assert blocked.returncode == 2 and "tick at least one code" in blocked.stderr
    worksheet = _tick_like(json.loads(out.read_text()), RECONCILIATION_MAP)
    worksheet["obligations"][0]["codes"].append({"code": "CHG_AUTH_001", "include": True})
    out.write_text(json.dumps(worksheet))
    invented = _cli("sign", "--config", config, "--worksheet", out, "--confirm", "CHANGE.MGMT")
    assert invented.returncode == 2 and "CHG_AUTH_001" in invented.stderr
    wrong = _cli("sign", "--config", config, "--worksheet", out, "--confirm", "SOMETHING.ELSE")
    assert wrong.returncode == 2 and "--confirm" in wrong.stderr


def test_obligation_may_be_declared_untested_only_with_a_reason(tmp_path):
    root, out = _drafted(tmp_path)
    worksheet = _tick_like(json.loads(out.read_text()), {k: v for k, v in RECONCILIATION_MAP.items() if k != "chg.4"})
    worksheet["obligations"][3].update(no_deterministic_test=True, note="short")
    out.write_text(json.dumps(worksheet))
    assert "at least 20 characters" in _cli("sign", "--config", root / "operations.json", "--worksheet", out,
                                             "--confirm", "CHANGE.MGMT").stderr
    worksheet["obligations"][3]["note"] = "Completeness is assured by the platform team's own reconciliation, out of scope here."
    out.write_text(json.dumps(worksheet))
    signed = _cli("sign", "--config", root / "operations.json", "--worksheet", out, "--confirm", "CHANGE.MGMT")
    assert signed.returncode == 0, signed.stderr
    assert json.loads(signed.stdout)["without_deterministic_test"] == ["chg.4"]


def test_signed_mapping_applies_before_a_run_and_drives_d8(tmp_path, monkeypatch):
    root, out = _drafted(tmp_path)
    config_path = root / "operations.json"
    out.write_text(json.dumps(_tick_like(json.loads(out.read_text()), RECONCILIATION_MAP)))
    signed = json.loads(_cli("sign", "--config", config_path, "--worksheet", out, "--confirm", "CHANGE.MGMT").stdout)
    applied = _cli("apply", "--config", config_path, "--mapping", signed["document"], "--no-model-stages")
    assert applied.returncode == 0, applied.stderr
    config = json.loads(config_path.read_text())
    assert config["model_stages"] == "disabled" and config["deterministic_completion"] is True
    assert {k: sorted(v) for k, v in config["reconciliation_map"]["CHANGE.MGMT"].items()} == {k: sorted(v) for k, v in RECONCILIATION_MAP.items()}
    assert config["reconciliation_mapping_document"]["signed_by"] == "Test Owner"

    import governance.production.orchestrator as orch
    from governance.operations.runtime import load
    config["model_stages"] = "disabled"
    config_path.write_text(json.dumps(config, indent=2))
    config, root = load(config_path)
    monkeypatch.setattr(orch, "doctor", lambda c, r: {"blockers": [], "checks": {}})
    report = orch.run(config, root, IID)
    assert [o["governed_status"] for o in report["obligations"]] == ["CONTRADICTED", "CONTRADICTED",
                                                                     "NOT_EVIDENCED", "NOT_EVIDENCED"]
    again = _cli("apply", "--config", config_path, "--mapping", signed["document"])
    assert again.returncode == 2 and "already run" in again.stderr


def test_a_mapping_edited_after_signing_is_refused_by_d8(tmp_path, monkeypatch):
    root, out = _drafted(tmp_path)
    config_path = root / "operations.json"
    out.write_text(json.dumps(_tick_like(json.loads(out.read_text()), RECONCILIATION_MAP)))
    signed = json.loads(_cli("sign", "--config", config_path, "--worksheet", out, "--confirm", "CHANGE.MGMT").stdout)
    assert _cli("apply", "--config", config_path, "--mapping", signed["document"]).returncode == 0
    config = json.loads(config_path.read_text())
    config["reconciliation_map"]["CHANGE.MGMT"]["chg.1"] = ["APPROVAL_AFTER_EXECUTION"]      # quietly narrowed
    config["model_stages"] = "disabled"
    config_path.write_text(json.dumps(config, indent=2))
    import governance.production.orchestrator as orch
    from governance.operations.runtime import load
    config, root = load(config_path)
    monkeypatch.setattr(orch, "doctor", lambda c, r: {"blockers": [], "checks": {}})
    report = orch.run(config, root, IID)
    assert report["checkpoint"] == "ACTION_REQUIRED" and "signed mapping document" in json.dumps(report)


def _tick_csv(csv_path, mapping, extra_rows=()):
    import csv
    rows = list(csv.DictReader(csv_path.open(newline="")))
    for row in rows:
        row["include"] = "yes" if row["code"] in mapping.get(row["element_id"], []) else ""
    rows += list(extra_rows)
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_spreadsheet_worksheet_signs_like_the_json_one(tmp_path):
    root, out = _drafted(tmp_path)
    sheet = out.with_suffix(".csv")
    import csv
    rows = list(csv.DictReader(sheet.open(newline="")))
    assert len(rows) == 4 * 13 and not any(r["include"] for r in rows)
    assert {r["code"] for r in rows if r["fires_on_in_your_evidence"]} >= {"SELF_APPROVAL", "OUTSIDE_APPROVED_WINDOW"}
    _tick_csv(sheet, RECONCILIATION_MAP)
    result = _cli("sign", "--config", root / "operations.json", "--worksheet", sheet, "--confirm", "CHANGE.MGMT")
    assert result.returncode == 0, result.stderr
    document = json.loads(Path(json.loads(result.stdout)["document"]).read_text())
    assert {k: sorted(v) for k, v in document["payload"]["mapping"].items()} == \
           {k: sorted(v) for k, v in RECONCILIATION_MAP.items()}
    assert document["payload"]["spreadsheet_sha256"]


def test_a_code_typed_into_the_spreadsheet_is_refused(tmp_path):
    root, out = _drafted(tmp_path)
    sheet = out.with_suffix(".csv")
    invented = {"element_id": "chg.1", "obligation": "", "code": "CHG_AUTH_001", "type": "", "meaning": "",
                "fires_on_in_your_evidence": "", "include": "yes", "no_deterministic_test": "", "note": ""}
    _tick_csv(sheet, RECONCILIATION_MAP, [invented])
    result = _cli("sign", "--config", root / "operations.json", "--worksheet", sheet, "--confirm", "CHANGE.MGMT")
    assert result.returncode == 2 and "CHG_AUTH_001" in result.stderr


def test_d8_rejects_a_mapping_and_hash_edited_together(tmp_path, monkeypatch):
    """The old check compared a hash kept in the config; editing both defeated it. The signature cannot be."""
    from governance.investigation.store import digest
    root, out = _drafted(tmp_path)
    config_path = root / "operations.json"
    out.write_text(json.dumps(_tick_like(json.loads(out.read_text()), RECONCILIATION_MAP)))
    signed = json.loads(_cli("sign", "--config", config_path, "--worksheet", out, "--confirm", "CHANGE.MGMT").stdout)
    assert _cli("apply", "--config", config_path, "--mapping", signed["document"], "--no-model-stages").returncode == 0
    config = json.loads(config_path.read_text())
    narrowed = {**config["reconciliation_map"]["CHANGE.MGMT"], "chg.1": ["APPROVAL_AFTER_EXECUTION"]}
    config["reconciliation_map"]["CHANGE.MGMT"] = narrowed
    config["reconciliation_mapping_document"]["mapping_sha256"] = digest(narrowed)       # the consistent edit
    config_path.write_text(json.dumps(config, indent=2))
    import governance.production.orchestrator as orch
    from governance.operations.runtime import load
    config, root = load(config_path)
    monkeypatch.setattr(orch, "doctor", lambda c, r: {"blockers": [], "checks": {}})
    report = orch.run(config, root, IID)
    assert report["checkpoint"] != "DETERMINISTIC_COMPLETE"
    assert "differs from the signed mapping document" in json.dumps(report)


def test_d8_records_who_signed_the_mapping(tmp_path, monkeypatch):
    root, out = _drafted(tmp_path)
    config_path = root / "operations.json"
    out.write_text(json.dumps(_tick_like(json.loads(out.read_text()), RECONCILIATION_MAP)))
    signed = json.loads(_cli("sign", "--config", config_path, "--worksheet", out, "--confirm", "CHANGE.MGMT").stdout)
    _cli("apply", "--config", config_path, "--mapping", signed["document"], "--no-model-stages")
    import governance.production.orchestrator as orch
    from governance.operations.runtime import load
    from governance.production.journal import Journal
    config, root = load(config_path)
    monkeypatch.setattr(orch, "doctor", lambda c, r: {"blockers": [], "checks": {}})
    orch.run(config, root, IID)
    rec = Journal(orch.case_directory(config, root, IID) / "operations.sqlite",
                  config["trusted_keys"]).latest("obligation_reconciliation")["payload"]
    assert rec["mapping_signed_by"] == "Test Owner" and rec["mapping_document_sha256"]


def test_spreadsheet_exported_with_byte_order_mark_and_semicolons_still_signs(tmp_path):
    import csv, io
    root, out = _drafted(tmp_path)
    sheet = out.with_suffix(".csv")
    _tick_csv(sheet, RECONCILIATION_MAP)
    rows = list(csv.DictReader(sheet.open(newline="")))
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), delimiter=";")
    writer.writeheader()
    writer.writerows(rows)
    sheet.write_bytes(b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8"))      # as Numbers / Excel may export
    result = _cli("sign", "--config", root / "operations.json", "--worksheet", sheet, "--confirm", "CHANGE.MGMT")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["mapped"] == {k: len(v) for k, v in RECONCILIATION_MAP.items()}


def test_apply_without_a_path_says_what_is_needed(tmp_path):
    root, out = _drafted(tmp_path)
    result = _cli("apply", "--config", root / "operations.json", "--mapping", "")
    assert result.returncode == 2 and "give the path of a signed mapping document" in result.stderr
    assert "Is a directory" not in result.stderr
