"""Read-only search of a governance-approved precedent snapshot; advisory only."""
import hashlib,json
from .qualification import signed_document
from governance.investigation.store import canonical

def providers(config,root,context):
    if not config.get('precedent_snapshot'):return {}
    def search(question):
        spec=config['precedent_snapshot'];path=root/spec['path']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=spec['sha256']:raise ValueError('precedent snapshot changed')
        fixture=spec.get('evaluation_fixture') is True and config.get('operation_mode')=='evaluation'
        payload,_,_=signed_document(path,config['trusted_keys'],'governance',not fixture)
        expected_status='EVALUATION_FIXTURE' if fixture else 'APPROVED'
        if payload.get('status')!=expected_status or payload.get('framework')!=context.framework or payload.get('control_id')!=context.control_id:
            raise ValueError('precedent corpus is not approved for this framework/control')
        if not isinstance(payload.get('records'),list):raise ValueError('precedent corpus records missing')
        refs=[]
        for record in payload['records']:
            if not all(record.get(k) for k in ('precedent_id','source_ref','system_id','period','lesson','limitations')):raise ValueError('incomplete precedent provenance')
            refs.append('ADVISORY_PRECEDENT:'+canonical(record))
        if len(refs)>100 or sum(map(len,refs))>200000:raise ValueError('precedent corpus exceeds approved read budget')
        return refs
    return {'precedents':search}
