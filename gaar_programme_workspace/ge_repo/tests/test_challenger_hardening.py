import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import challenge as CH

CONTROL_ID='M3.12'
EVIDENCE='''Change record CR-17 was approved before deployment.\nDeployment log records release of pricing-model v3 after approval.'''
class _Ctl: id,lib,title,req,maps=CONTROL_ID,'Control Library - MAS','Change management','req',''

def _payload(action='revisit_read',quote='Deployment log records release of pricing-model v3 after approval.'):
    return {'overall_reasoning':'The evidence is limited.','challenges':[{'observation':'A deployment record exists.','evidence_basis':[quote],'requirement_basis':['Change records link approval, implementation and the deployed system/version.'],'knowledge_basis':[],'inference':'The record is relevant.','challenge':'The reviewer should address the timing.','factual_pointer':{'source':'reviewer_supplied','locator':'line:2','quote':quote,'fact':quote,'what_it_supports':'approval precedes deployment'},'requirement_pointer':{'control_id':CONTROL_ID,'locator':'controls.M3.12.elements[1]','element_id':'e2','text':'Change records link approval, implementation and the deployed system/version.'},'risk_to_address':'incorrect timing inference','resolution_pointer':'the change record and timestamps','recommended_action':action,'severity':'medium','confidence':'high','claim_test':{'claim':'e2 is not evidenced','fact_meaning':'approval precedes deployment','rebuttal':'the evidence weakens the claim','rebuttal_strength':'weak','risk_addressed':'incorrect rejection'}}],'sharpest':'address the timing','unaddressed':[]}

def test_action_alias_is_canonicalised(monkeypatch):
    monkeypatch.setattr(CH,'PROVIDER','ollama'); monkeypatch.setattr(CH,'_ollama',lambda s,u:json.dumps(_payload('Revisit_read'))); monkeypatch.setattr(CH,'scan_injection',lambda t:[]); monkeypatch.setenv('WB_CHALLENGE_RETRIES','0'); monkeypatch.setenv('WB_LLM_OBSERVE','0')
    out=CH.challenge(_Ctl(),EVIDENCE,{'sufficiency':'partial','maturity':2,'reason':'unclear'})
    assert out['challenges'][0]['recommended_action']=='revisit_read'

def test_validation_failure_retries(monkeypatch):
    bad=_payload(); bad['challenges'][0]['factual_pointer']['quote']='invented sentence'; good=_payload(); calls=[]
    monkeypatch.setattr(CH,'PROVIDER','ollama'); monkeypatch.setattr(CH,'scan_injection',lambda t:[]); monkeypatch.setenv('WB_CHALLENGE_RETRIES','1'); monkeypatch.setenv('WB_LLM_OBSERVE','0')
    def fake(s,u):
        calls.append(u)
        # First call is the reviewer-claim vetting pass; then exercise the actual challenge
        # validation retry with a bad factual pointer followed by a good payload.
        if len(calls) == 1:
            return json.dumps({'claims': [{'claim_id':'C1','claim':'Reviewer says partial','element_id':'e2','reviewer_position':'sufficiency','evidence_assessment':'unclear','evidence_reason':'insufficient evidence to decide','evidence_quotes':[],'confidence':'low'}]})
        return json.dumps(bad if len(calls)==2 else good)
    monkeypatch.setattr(CH,'_ollama',fake)
    out=CH.challenge(_Ctl(),EVIDENCE,{'sufficiency':'partial','maturity':2,'reason':'unclear'})
    assert len(calls)==3 and 'VALIDATION REPAIR MODE' in calls[2]
    assert out['challenges'][0]['factual_pointer']['quote']==good['challenges'][0]['factual_pointer']['quote']


# ---------------- WB-060: one bad challenge must not discard the good ones ----------------

def _well_formed(element_id="e1", quote="approved by the CIO",
                 text="The organization must prevent agents being deployed in unsuitable / high-impact contexts."):
    return {"observation": "o", "evidence_basis": [quote], "requirement_basis": [text],
            "knowledge_basis": [], "inference": "i", "challenge": "c", "risk_to_address": "r",
            "resolution_pointer": "p", "recommended_action": "request_evidence",
            "severity": "high", "confidence": "high",
            "factual_pointer": {"source": "reviewer_supplied", "locator": "line:1", "quote": quote,
                                "fact": "f", "what_it_supports": "s"},
            "requirement_pointer": {"control_id": "D1.1", "locator": "x",
                                    "element_id": element_id, "text": text},
            "claim_test": {"claim": "a", "fact_meaning": "b", "rebuttal": "c",
                           "rebuttal_strength": "weak", "risk_addressed": "d"}}


def test_a_malformed_challenge_is_dropped_not_fatal():
    """The model failing to format challenge 2 says nothing about challenge 1. Discarding both
    is a batching accident, not strictness.

    The fixture changed, not the invariant. This used to pair a valid challenge with one whose
    `element_id` was `e2` while carrying `e1`'s text, and relied on D1.1 having no e2 for the
    mismatch to be caught. D1.1 now has four source-grounded elements, so e2 is a real element
    and that second challenge is legitimate — the validator returning two was the semantic
    decomposition working, not the challenger loosening. The malformed case is now malformed on
    its own terms: a quote that appears nowhere in the evidence.
    """
    import challenge as C
    out = C._validate_structured(
        {"overall_reasoning": "x",
         "challenges": [_well_formed(),
                        _well_formed(element_id="e2", quote="a sentence not in the evidence")]},
        [], "approved by the CIO", "D1.1", framework="Control Library - MGF Agentic")
    assert len(out["challenges"]) == 1, "the well-formed challenge must survive"
    assert out["rejected_count"] == 1


def test_two_well_formed_challenges_both_survive():
    """The other half of the same invariant, which the old fixture could not express.

    Two challenges anchored to two real elements are two challenges. Dropping one would be the
    mirror failure of dropping both.
    """
    import challenge as C
    out = C._validate_structured(
        {"overall_reasoning": "x", "challenges": [_well_formed(), _well_formed(element_id="e2")]},
        [], "approved by the CIO", "D1.1", framework="Control Library - MGF Agentic")
    assert len(out["challenges"]) == 2
    assert out["rejected_count"] == 0


def test_rejections_are_counted_and_explained():
    """Silent dropping would break the rule applied everywhere else here: a run that mostly
    failed must not look like a run that found little."""
    import challenge as C
    out = C._validate_structured(
        {"overall_reasoning": "x", "challenges": [_well_formed(), _well_formed(element_id="e9")]},
        [], "approved by the CIO", "D1.1", framework="Control Library - MGF Agentic")
    r = out["rejected_challenges"][0]
    assert r["index"] == 2
    assert "not governed" in r["reason"] and "playbook_workbook" in r["reason"]
    assert "mas.yaml" not in r["reason"]          # WB-059: name the source that actually governs


def test_a_run_where_every_challenge_fails_still_raises():
    """Materially different from a clean empty result, and the caller must be told."""
    import challenge as C
    import pytest as _pt
    with _pt.raises(ValueError, match="failed validation"):
        # Same fixture correction: e2 is a real D1.1 element now, so a challenge naming it is
        # valid. The failure has to be in the challenge itself — an unquotable factual pointer.
        C._validate_structured(
            {"overall_reasoning": "x",
             "challenges": [_well_formed(element_id="e2", quote="a sentence not in the evidence")]},
            [], "approved by the CIO", "D1.1", framework="Control Library - MGF Agentic")


def test_no_streamlit_magic_display_leaks_in_app():
    """WB-058: a list comprehension over st.markdown is a bare expression, and Streamlit's magic
    display renders the resulting DeltaGenerator objects into the page."""
    from pathlib import Path
    app = (Path(__file__).parents[1] / "app.py").read_text()
    assert "[st.markdown(" not in app
    assert "[st.write(" not in app


def test_the_envelope_is_built_from_an_allowlist_not_the_model_dict():
    """A red-team probe put {"rating": "full"} beside `challenges` and it survived to the caller.

    The row contract was already enforced — each admitted challenge is rebuilt from validated
    fields. The envelope had none: it was the parsed model JSON, mutated in place and returned.
    """
    import challenge as CH
    src = __import__("inspect").getsource(CH._finalise_structured)
    assert "_MODEL_ENVELOPE_KEYS" in src
    assert "out = {k: out.get(k)" in src


def test_the_validators_own_keys_survive_the_allowlist():
    """`rejected_challenges` and `rejected_count` pass through this function rather than being
    added afterwards, so an allowlist that forgets them erases the record of a refusal."""
    import challenge as CH
    for k in ("rejected_challenges", "rejected_count"):
        assert k in CH._VALIDATOR_ENVELOPE_KEYS


def test_runtime_fields_are_added_after_and_need_no_preservation():
    """validation_status, knowledge, model, dossier and the retrieval receipt are written by the
    caller once this has returned — they cannot be forged by the model and are not stripped."""
    import challenge as CH
    for k in ("validation_status", "knowledge", "model", "dossier"):
        assert k not in CH._MODEL_ENVELOPE_KEYS
