"""Complete treatment of bounded dependency candidates without altering WB140 stages."""
from governance.investigation.prompting import render
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
from governance.investigation.store import canonical
from governance.investigation.dependencies import investigate

class Treatment(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    edge_id:str
    status:Literal['INVESTIGATED','NOT_APPLICABLE','UNRESOLVED','UNAVAILABLE']
    material:bool
    rationale:str=Field(min_length=12)
    evidence_refs:list[str]=[]
    test_refs:list[str]=[]
    risk_refs:list[str]=[]

class Review(BaseModel):
    model_config=ConfigDict(extra='forbid',frozen=True)
    knowledge_sha256:str
    treatments:list[Treatment]


def validate(review,knowledge,values):
    wanted={e['edge_id'] for e in knowledge['edges']};given=[t.edge_id for t in review.treatments]
    if len(given)!=len(set(given)) or set(given)!=wanted:raise ValueError('every retrieved dependency needs exactly one treatment')
    if review.knowledge_sha256!=knowledge['knowledge_sha256']:raise ValueError('dependency treatment knowledge version mismatch')
    evidence={e.evidence_id for e in values['examine'].evidence}
    tests={t.test_id:t for t in values['verify'].tests}
    risks={h.hypothesis_id:h for h in values['explain'].hypotheses}
    for treatment in review.treatments:
        if not set(treatment.evidence_refs)<=evidence or not set(treatment.test_refs)<=set(tests) or not set(treatment.risk_refs)<=set(risks):raise ValueError('dependency treatment references unknown investigation objects')
        if treatment.status=='INVESTIGATED' and (not treatment.evidence_refs or not treatment.test_refs or any(tests[x].status!='EXECUTED' for x in treatment.test_refs)):
            raise ValueError('investigated dependency requires evidence and executed tests')
        if treatment.status=='NOT_APPLICABLE' and treatment.material:raise ValueError('not-applicable dependency cannot simultaneously assert material risk')
        if treatment.material and (not treatment.risk_refs or not any(risks[r].material for r in treatment.risk_refs)):
            raise ValueError('material dependency requires an existing material risk; new explanation revision needed')
    return review


def review_dependencies(engine,iid,invoke):
    _,values=engine.snapshot(iid);ctx=values['understand'];knowledge=investigate(ctx.framework,ctx.control_id)
    prompt={'task':'Treat every proposed dependency. Distinguish investigation with executed tests, justified non-applicability, unresolved and unavailable. Ground claims in the full record. Do not invent references or suppress material risk. A newly discovered material explanation requires a new investigation revision.',
            'rules':__import__('governance.investigation.reference_rules',fromlist=['dependency_rules']).dependency_rules(values,knowledge),
            'schema':Review.model_json_schema(),'knowledge':knowledge,'investigation':{k:v.model_dump(mode='json') for k,v in values.items()}}
    review=Review.model_validate_json(invoke(render(prompt)))
    return validate(review,knowledge,values)
