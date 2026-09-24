"""Precise machine-readable next-action contracts."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field

class Request(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    kind:Literal['EvidenceRequest','AuthorizationRequest','ServiceRequest','IntegrityRequest']
    investigation_id:str
    stage:str
    reason:str
    required_items:list[str]=Field(min_length=1)
    scope:dict={}
    retry_safe:bool=True
    deployment_authorized:bool=False


def blocked(kind,iid,stage,reason,items,scope=None):
    return {'checkpoint':'ACTION_REQUIRED','request':Request(kind=kind,investigation_id=iid,stage=stage,reason=reason,required_items=items,scope=scope or {},retry_safe=kind not in {'IntegrityRequest','AuthorizationRequest'}).model_dump(),
            'assessment_finalizable':False,'deployment_authorized':False}
