from __future__ import annotations
import hashlib,json
from typing import Any
from governance.result_store import ResultStore
from governance.result_contract import ResultStateLog
from governance.quality_gate import QualityGateLog


def _canon(v:Any)->str:
    return json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(",",":"),default=str)

def governance_passport(result_id:str,*,result_store:ResultStore|None=None,state_log:ResultStateLog|None=None)->dict[str,Any]:
    store=result_store or ResultStore(); states=state_log or ResultStateLog(); result=store.get(result_id)
    if not result: raise KeyError(result_id)
    gate=QualityGateLog().latest_for_result(result_id)
    body={
        "passport_schema":"gaar.governance-passport.v1",
        "result_id":result.result_id,
        "result_version":result.result_version,
        "state":(states.current_state(result.result_id).value if states.current_state(result.result_id) else "UNKNOWN"),
        "decision":result.decision.value,
        "requirement_version_id":result.requirement_version_id,
        "evidence_set_id":result.evidence_set_id,
        "assessment_id":result.assessment_id,
        "challenge_set_id":result.challenge_set_id,
        "human_decision_id":result.human_decision_id,
        "content_hash":result.content_hash,
        "merkle_root":result.sealed_record.merkle_root,
        "signature":result.sealed_record.signature,
        "public_key_b64":result.sealed_record.public_key_b64,
        "sealed_at":result.sealed_record.sealed_at,
        "quality_gate":gate.status.value if gate else "NOT_RUN",
        "quality_gate_blockers":list(gate.blockers) if gate else [],
        "parent_result_id":result.parent_result_id,
        "supersedes_result_id":result.supersedes_result_id,
        "provenance":result.provenance.model_dump(mode="json"),
    }
    body["passport_digest"]=hashlib.sha256(_canon(body).encode()).hexdigest()
    return body

def verify_passport(passport:dict[str,Any],*,result_store:ResultStore|None=None)->dict[str,Any]:
    supplied=dict(passport); digest=supplied.pop("passport_digest",None)
    digest_ok=digest==hashlib.sha256(_canon(supplied).encode()).hexdigest()
    result=(result_store or ResultStore()).get(str(passport.get("result_id") or ""))
    result_ok=bool(result and result.content_hash==passport.get("content_hash") and result.sealed_record.merkle_root==passport.get("merkle_root") and result.sealed_record.signature==passport.get("signature"))
    return {"valid":bool(digest_ok and result_ok),"passport_digest_valid":digest_ok,"matches_sealed_result":result_ok}
