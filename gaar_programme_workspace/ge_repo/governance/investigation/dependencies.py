"""Bounded bidirectional investigation traversal; edges are not verdicts."""
import hashlib
import json
from pathlib import Path

DEFAULT_PATH=Path(__file__).with_name('dependency_knowledge.json')


def load(path=DEFAULT_PATH):
    raw=Path(path).read_bytes();book=json.loads(raw)
    if book.get('schema')!='dependency-knowledge.2': raise ValueError('unsupported dependency knowledge schema')
    ids=set()
    for edge in book['edges']:
        if edge['edge_id'] in ids: raise ValueError('duplicate dependency identity')
        ids.add(edge['edge_id'])
        for field in ('framework','upstream','downstream','relation','version','authority','review_status','provenance','applicability','evidence_required','alternatives','corroboration_rule','non_inference'):
            if not edge.get(field): raise ValueError('missing dependency field '+field)
        if edge['authority']!='internal_investigation_hypothesis' or edge['review_status']!='PROPOSED':
            raise ValueError('this catalogue cannot self-approve regulatory authority')
    return book,hashlib.sha256(raw).hexdigest()


def investigate(framework,control_id,*,path=DEFAULT_PATH,max_depth=2,max_edges=40):
    if not 1<=max_depth<=3 or not 1<=max_edges<=100: raise ValueError('invalid traversal budget')
    book,digest=load(path)
    framework=framework.removeprefix('Control Library - ')
    pool=[e for e in book['edges'] if e['framework']==framework]
    frontier={control_id};seen_nodes=set(frontier);selected={}
    truncated=False
    for depth in range(1,max_depth+1):
        next_nodes=set()
        for edge in sorted(pool,key=lambda e:e['edge_id']):
            if edge['edge_id'] in selected: continue
            if edge['upstream'] in frontier or edge['downstream'] in frontier:
                if len(selected)>=max_edges: truncated=True;continue
                direction='DOWNSTREAM' if edge['upstream'] in frontier else 'UPSTREAM'
                selected[edge['edge_id']]={**edge,'discovery_depth':depth,'investigation_direction':direction}
                next_nodes.update((edge['upstream'],edge['downstream']))
        frontier=next_nodes-seen_nodes;seen_nodes.update(next_nodes)
        if not frontier: break
    boundary=any(e['edge_id'] not in selected and (e['upstream'] in frontier or e['downstream'] in frontier) for e in pool)
    return {'status':'COMPLETED','framework':framework,'control_id':control_id,'knowledge_version':book['version'],
        'knowledge_sha256':digest,'edges':list(selected.values()),'edge_budget_exhausted':truncated,'depth_boundary_remaining':boundary,
        'max_depth':max_depth,'max_edges':max_edges,'changes_control_verdict':False,
        'coverage_statement':'Bounded proposed catalogue search; no assertion of comprehensive control dependency coverage.'}
