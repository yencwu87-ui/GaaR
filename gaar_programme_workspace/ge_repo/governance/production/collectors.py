"""Operator-approved, bounded GET collectors; model output cannot choose endpoints."""
import hashlib,json,os,urllib.parse,urllib.request,uuid
from pathlib import Path
from governance.investigation import admit_segments
from governance.investigation.store import canonical
from governance.operations.runtime import collect
from governance.operations.live import NoRedirect
from .journal import atomic_json


def collect_all(config,root,scope,journal,executor):
    evidence=list(collect(config,root,scope))
    if config.get('http_collectors') and not config['trusted_keys'][executor.key_id].get('allow_readonly_collectors'):
        raise ValueError('read-only system collectors need explicit executor policy approval')
    for item in config.get('http_collectors',[]):
        url=urllib.parse.urlparse(item['url'])
        if url.scheme!='https' or url.hostname not in item['allowed_hosts'] or url.username or url.password or url.fragment:
            raise ValueError('collector endpoint outside approved HTTPS scope')
        headers={'Accept':'application/json'}
        if item.get('bearer_token_env'):headers['Authorization']='Bearer '+os.environ[item['bearer_token_env']]
        request=urllib.request.Request(item['url'],headers=headers,method='GET')
        with urllib.request.build_opener(NoRedirect).open(request,timeout=20) as response:
            if 'application/json' not in response.headers.get('Content-Type',''):raise ValueError('collector must return normalized JSON')
            raw=response.read(20_000_001)
        if len(raw)>20_000_000:raise ValueError('collector response budget exceeded')
        package=json.loads(raw)
        if package.get('scope')!=scope.system_id or package.get('as_of')!=scope.period or package.get('model_version',scope.version)!=scope.version:
            raise ValueError('system collector response does not match authorized scope/version/period')
        text=canonical(package);raw=text.encode();digest=hashlib.sha256(raw).hexdigest()
        if item.get('expected_sha256') and item['expected_sha256']!=digest:raise ValueError('collector output differs from expected export hash')
        directory=journal.path.parent/'evidence_blobs';directory.mkdir(mode=0o700,exist_ok=True)
        path=directory/(digest+'.json')
        if path.exists():
            if path.read_bytes()!=raw:raise ValueError('immutable collector blob changed')
        else:
            with path.open('xb') as f:os.chmod(path,0o600);f.write(raw);f.flush();os.fsync(f.fileno())
        receipt={'source_id':item['source_id'],'response_sha256':digest,'request_sha256':hashlib.sha256(item['url'].encode()).hexdigest(),
                 'scope':scope.model_dump(),'transport':'HTTPS_GET','endpoint_origin':url.scheme+'://'+url.netloc,'snapshot':str(path)}
        journal.append('collector:'+item['source_id']+':'+digest,'collection_receipt',receipt,executor,'executor')
        evidence.extend(admit_segments(source_bytes=raw,source_sha256=digest,source_id=item['source_id'],scope=scope,expected_scope=scope,
            segments=[{'start':0,'end':len(text),'evidence_id':item['evidence_id'],'element_ids':item['element_ids'],'purposes':['operating_record'],'finding_status':'neutral'}],
            authority=item.get('authority','internal'),provenance=('approved-readonly-collector','sha256:'+digest)))
    if len({e.evidence_id for e in evidence})!=len(evidence):raise ValueError('duplicate admitted evidence IDs across collectors')
    return tuple(evidence)
