"""The model arena (kit v22). No test calls a real model: adapters are exercised against recorded replies."""
import json

import pytest

from governance.arena import arena
from governance.arena.cases import draw
from governance.arena.contestants import NotConfigured, Ollama, build, parse


def test_cases_are_constructed_labelled_and_balanced():
    cases = draw(40, 1)
    assert len(cases) == 40 and all(c["provenance"] == "constructed" for c in cases)
    assert sum(c["truth"] == "CONTRADICTED" for c in cases) == 20
    assert all(c["violation"] for c in cases if c["truth"] == "CONTRADICTED")


def test_an_answer_without_a_confidence_is_a_hold_never_a_pass():
    assert parse('{"answer": "SUPPORTED"}')["answer"] == "HOLD"
    assert parse('{"answer": "SUPPORTED", "confidence": 0.8}')["answer"] == "SUPPORTED"
    assert parse("I think it is fine")["answer"] == "HOLD"
    assert parse('{"choice": "CONTRADICTED", "probabilities": {"CONTRADICTED": 0.7}}')["confidence"] == 0.7


def test_baselines_rank_as_they_should_and_nobody_is_seated_on_a_short_run():
    board = arena.run(["baseline:rules", "baseline:always-supported", "baseline:always-contradicted"], n_cases=30, seed=2)
    rows = {r["contestant"]: r for r in board["table"]}
    assert rows["baseline:rules"]["cost_per_case"] == 0 and rows["baseline:rules"]["precision"] == 1.0
    assert rows["baseline:always-supported"]["false_assurance"] == 15
    assert board["table"][-1]["contestant"] == "baseline:always-supported"               # false comfort costs most
    assert board["advisory_seat"] is None                                                   # 30 < min_cases, baselines excluded
    assert board["provenance"].startswith("Ground truth: constructed digital-twin cases")
    assert board["calibration"]["status"] == "SCORER_CALIBRATED"
    assert board["calibration"]["labels"]["baseline:rules"].startswith("Calibration fixture, not a contestant result")
    policy = board["cost_policy"]
    assert (policy["false_assurance"], policy["false_alarm"], policy["hold"]) == (10, 1, 0.5)
    assert policy["false_assurance_to_false_alarm"] == 10 and len(policy["params_sha256"]) == 64
    assert all({"precision", "recall", "false_assurance", "false_alarms", "holds", "weighted_cost"} <= set(r)
               for r in board["table"])


def test_a_scorer_whose_fixtures_misread_seats_nobody(monkeypatch):
    from governance.arena import contestants
    monkeypatch.setattr(contestants, "_rules", lambda case: {"answer": "SUPPORTED", "confidence": 1.0})
    board = arena.run(["baseline:rules", "baseline:always-contradicted"], n_cases=6, seed=2)
    assert board["calibration"]["status"] == "SCORER_SUSPECT" and board["advisory_seat"] is None


def test_the_blind_spot_round_is_where_a_model_can_beat_the_rules():
    board = arena.run(["baseline:rules"], n_cases=200, seed=8, include_known_blind=True)
    assert board["round"] == "blind-spot"
    assert board["table"][0]["false_assurance"] > 0                 # the rules cannot see a namesake's grant
    assert not any(c["fixture"] == "baseline:rules" for c in board["calibration"]["checks"])


def test_scores_come_from_the_attempted_receipts_including_failed_calls(monkeypatch):
    import requests

    def down(url, **k):
        raise requests.ConnectionError("refused")
    monkeypatch.setattr(requests, "post", down)
    board = arena.run(["ollama:qwen2.5:14b", "baseline:rules"], n_cases=12, seed=9)
    rows = {r["contestant"]: r for r in board["table"]}
    row = rows["ollama:qwen2.5:14b"]
    assert row["cases"] == 5 and row["holds"] == 5 and row["errors"] == 5       # every attempt counted, none dropped
    assert row["stopped"] == "after 5 attempts: 5 consecutive failed calls"      # server down: stopped, not asked 12x
    assert rows["baseline:rules"]["cases"] == 12 and "stopped" not in rows["baseline:rules"]
    attempts = [r["payload"] for r in arena.store().read() if r["record_type"] == "ArenaAttempt"
                and r["payload"]["contestant"] == "ollama:qwen2.5:14b"]
    assert len(attempts) == 5
    assert all(a["error"].startswith("ConnectionError") and a["parsed"]["answer"] == "HOLD" for a in attempts)


class _Judge:
    """A stand-in judge model. `mode` decides how it answers."""
    local = True

    def __init__(self, mode, name="ollama:judge-model:7b", family="judge"):
        self.mode, self.name, self.family = mode, name, family

    def raw(self, prompt):
        if self.mode == "position":                              # always prefers whatever is shown first
            return '{"better": "A"}'
        a = prompt.split("ANSWER A:")[1].split("ANSWER B:")[0]
        b = prompt.split("ANSWER B:")[1]
        if self.mode == "substance":                             # prefers the answer that catches the violation
            return '{"better": "A"}' if "CONTRADICTED" in a and "CONTRADICTED" not in b else '{"better": "B"}'
        return "no idea"


def _battle():
    board = arena.run(["baseline:rules", "baseline:always-supported"], n_cases=10, seed=3)
    rows = [r["payload"] for r in arena.store().read() if r["record_type"] == "ArenaAttempt"]
    case = next(r["case_id"] for r in rows if r["truth"] == "CONTRADICTED")
    return board["run_id"], case


def test_a_judge_that_flips_when_the_order_is_swapped_is_discarded():
    from governance.arena.judge import judge_battle, judge_quality
    run_id, case = _battle()
    j = judge_battle(_Judge("position"), run_id, case, "baseline:rules", "baseline:always-supported")
    assert (j["verdict_in_order"], j["verdict_swapped_mapped_back"]) == ("A", "B")
    assert j["status"] == "DISCARDED_INCONSISTENT" and j["verdict"] is None and j["affects_scores"] is False
    good = judge_battle(_Judge("substance"), run_id, case, "baseline:rules", "baseline:always-supported")
    assert good["status"] == "CONSISTENT" and good["verdict"] == "A" and good["agrees_with_truth"] is True
    held = judge_battle(_Judge("mute"), run_id, case, "baseline:rules", "baseline:always-supported")
    assert held["status"] == "HOLD"
    q = judge_quality(run_id)["judges"]["ollama:judge-model:7b"]
    assert (q["judgements"], q["consistent"], q["discarded_inconsistent"], q["holds"], q["agreement_rate"]) == (3, 1, 1, 1, 1.0)


def test_no_model_judges_its_own_battle_or_its_own_family():
    from governance.arena.judge import judge_battle
    run_id, case = _battle()
    with pytest.raises(ValueError, match="^a contestant may not judge its own battle$"):
        judge_battle(_Judge("substance", name="baseline:rules"), run_id, case, "baseline:rules", "baseline:always-supported")
    with pytest.raises(ValueError, match=r"^a judge may not judge a battle involving its own model family \(baseline\)$"):
        judge_battle(_Judge("substance", family="baseline"), run_id, case, "baseline:rules", "baseline:always-supported")
    with pytest.raises(ValueError, match="^baseline:rules and nobody did not both answer"):
        judge_battle(_Judge("substance"), run_id, case, "baseline:rules", "nobody")


def test_a_judge_off_this_machine_sees_only_constructed_cases(monkeypatch):
    from governance.arena import judge as judge_module
    run_id, case = _battle()
    real = judge_module.draw
    monkeypatch.setattr(judge_module, "draw", lambda *a, **k: [dict(c, provenance="own-bank-export") for c in real(*a, **k)])
    remote = _Judge("substance")
    remote.local = False
    with pytest.raises(PermissionError, match="^ollama:judge-model:7b is not on this machine; it may only see constructed cases$"):
        judge_module.judge_battle(remote, run_id, case, "baseline:rules", "baseline:always-supported")


def test_every_attempt_is_a_receipt_and_the_run_records_its_parameters():
    board = arena.run(["baseline:always-contradicted"], n_cases=6, seed=4)
    rows = [r["payload"] for r in arena.store().read()]
    started = next(r for r in rows if r.get("run_id") == board["run_id"] and "params" in r)
    assert started["params"]["costs"]["false_assurance"] == 10 and len(started["params_sha256"]) == 64
    attempts = [r for r in rows if r.get("run_id") == board["run_id"] and "case_id" in r]
    assert len(attempts) == 6 and all(a["raw"] and a["prompt_sha256"] for a in attempts)


def test_an_ollama_model_is_scored_on_what_it_attempted(monkeypatch):
    import requests

    class Reply:
        def __init__(self, text): self.text = text
        def raise_for_status(self): pass
        def json(self): return {"response": self.text}
    monkeypatch.setattr(requests, "post", lambda url, **k: Reply('{"answer": "SUPPORTED", "confidence": 0.95}'))
    board = arena.run(["ollama:qwen2.5:14b"], n_cases=10, seed=5)
    row = board["table"][0]
    assert row["contestant"] == "ollama:qwen2.5:14b" and row["false_assurance"] == 5 and row["local"] if "local" in row else True


def test_a_model_off_this_machine_never_receives_a_non_constructed_case():
    remote = build("openai:https://api.example.com/v1|some-model")
    assert remote.local is False
    case = dict(draw(1, 3)[0], provenance="own-bank-export")
    with pytest.raises(PermissionError, match="may only receive constructed cases"):
        remote.ask(case)


def test_jev_stays_off_until_configured(monkeypatch):
    for var in ("GAAR_JEV_URL", "GAAR_JEV_MODEL", "GAAR_JEV_KEY_ENV"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(NotConfigured, match="Jev is not configured"):
        build("jev")


def test_a_blind_vote_hides_identities_until_cast_and_records_the_voter():
    board = arena.run(["baseline:rules", "baseline:always-supported"], n_cases=4, seed=6)
    pair = arena.blind_pair(board["run_id"], 1)
    visible = json.dumps({k: pair[k] for k in ("A", "B")})
    assert "baseline:" not in visible
    vote = arena.vote(pair, "A", "Test Owner")
    assert vote["voter"] == "Test Owner" and set(vote["revealed_after_vote"].values()) == {"baseline:rules", "baseline:always-supported"}
    with pytest.raises(ValueError, match="^vote A, B, TIE or NEITHER$"):
        arena.vote(pair, "MAYBE", "Test Owner")
    with pytest.raises(ValueError, match="^a vote needs the name of the person casting it$"):
        arena.vote(pair, "A", "  ")
    with pytest.raises(ValueError, match="^'Your Name' is a placeholder, not a name: record the person's own name$"):
        arena.vote(pair, "A", "Your Name")


def test_a_run_refuses_duplicates_and_a_board_refuses_an_unknown_run():
    with pytest.raises(ValueError, match="^each contestant may enter once$"):
        arena.run(["baseline:rules", "baseline:rules"], n_cases=2)
    with pytest.raises(ValueError, match="^no arena run ARENA-missing$"):
        arena.leaderboard("ARENA-missing")


def test_a_contestant_that_cannot_be_asked_is_recorded_as_a_hold():
    from governance.arena.contestants import Contestant
    result = Contestant().ask(draw(1, 3)[0])
    assert result["parsed"]["answer"] == "HOLD"
    assert result["error"] == "NotImplementedError: a contestant must say how it is asked"


def test_unknown_contestants_are_refused():
    with pytest.raises(ValueError, match="^unknown contestant: gpt-99$"):
        build("gpt-99")
    assert isinstance(build("ollama:mistral-nemo:12b"), Ollama)


def test_a_model_server_error_keeps_its_reason_in_the_receipt(monkeypatch):
    """v25 Mac round: muse-glimmer returned HTTP 500 and the reason was lost."""
    import requests

    class Reply:
        status_code, text = 500, '{"error":"model requires more system memory (19 GiB) than is available"}'
    monkeypatch.setattr(requests, "post", lambda url, **k: Reply())
    result = build("ollama:muse-glimmer:30b-mlx").ask(draw(1, 3)[0])
    assert result["error"].startswith("RuntimeError: HTTP 500 from the model server: ")
    assert "more system memory" in result["error"] and result["parsed"]["answer"] == "HOLD"
