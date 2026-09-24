"""Local checks and signed backup/restore drills, not production certification."""
import hashlib,json,os,platform,sqlite3,stat,tempfile,zipfile
from pathlib import Path,PurePosixPath
from governance.investigation.store import canonical,digest
from governance.result_contract import verify_signature
from .journal import atomic_json
from .qualification import check as qualification_check


def inspect_environment(config,root):
    from governance.operations.runtime import doctor
    readiness=doctor(config,root);checks=[]
    for field in ('store','programme_dir','receipt_dir'):
        if not config.get(field):checks.append({'check':field,'status':'UNCONFIGURED'});continue
        path=(root/config[field]).resolve()
        if path.exists():
            mode=path.stat().st_mode
            checks.append({'check':field,'status':'PASS' if not mode&0o077 else 'REVIEW_REQUIRED','path':str(path),'mode':oct(stat.S_IMODE(mode))})
        else:checks.append({'check':field,'status':'NOT_CREATED'})
    checks.append({'check':'target_platform','status':'PASS' if platform.system()=='Darwin' else 'NOT_VERIFIED_ON_MACOS','actual':platform.system()})
    checks.append({'check':'external_rollback_anchor','status':'NOT_VERIFIED','reason':'Local sidecar anchor cannot detect coordinated rollback of journal and anchor.'})
    checks.append({'check':'outbound_messages','status':'DISABLED','reason':'Only local notification drafts are implemented.'})
    return {'status':'ASSESSMENT_RECORDED','readiness':readiness,'qualification':qualification_check(config,root),'checks':checks,
            'production_assured':False,'remaining_proof':['independent security review','target-environment acceptance','identity provisioning/revocation drill','external anchor and backup retention verification','approved production release decision']}


def backup(config,root,iid,engine,journal,signer,destination):
    rows,_=engine.snapshot(iid);events=journal.read()
    if not rows or not events:raise ValueError('cannot back up an unbound investigation')
    destination=Path(destination)
    if destination.exists():raise ValueError('backup destination already exists')
    sources={'investigations.sqlite':root/config['store'],'operations.sqlite':journal.path,'operations.anchor.json':journal.anchor}
    for field,name in [('result_store','results.jsonl'),('result_state_log','result_states.jsonl')]:
        path=root/config.get(field, '../var/programme_results.jsonl' if field=='result_store' else '../var/programme_result_states.jsonl')
        if path.exists():sources[name]=path
    # Credentials and arbitrary directories are deliberately outside the backup allowlist.
    with tempfile.TemporaryDirectory() as temp:
        staging=Path(temp);files={}
        for name,path in sources.items():
            if path.suffix=='.sqlite':
                with sqlite3.connect(path) as source,sqlite3.connect(staging/name) as target:source.backup(target)
                raw=(staging/name).read_bytes()
            else:raw=path.read_bytes()
            files[name]=raw
        receipts=journal.path.parent/'inference_receipts'
        if receipts.exists():
            for path in receipts.glob('*.json'):files['inference_receipts/'+path.name]=path.read_bytes()
        blobs=journal.path.parent/'evidence_blobs'
        if blobs.exists():
            for path in blobs.glob('*.json'):files['evidence_blobs/'+path.name]=path.read_bytes()
        report=journal.path.parent/'investigation.json'
        if report.exists():files['investigation.json']=report.read_bytes()
        payload={'schema':'programme-backup.1','investigation_id':iid,'investigation_head':rows[-1]['record_hash'],'operational_head':events[-1]['event_hash'],
                 'trust_sha256':digest(config['trusted_keys']),'files':{name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()},
                 'scope':'Investigation/journal/result/receipt snapshot only. Original source archives, model files, keys and external anchors require separate governed backup.'}
        envelope={'payload':payload,'key_id':signer.key_id,'signature':signer.sign(canonical(payload).encode())}
        destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd=os.open(destination,os.O_RDWR|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w+b') as f,zipfile.ZipFile(f,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json',canonical(envelope))
            for name,raw in files.items():archive.writestr(name,raw)
    return {'path':str(destination),'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'manifest':payload}


def restore_verify(archive,trust,destination):
    destination=Path(destination)
    if destination.exists():raise ValueError('restore requires a new empty destination')
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        if len(names)!=len(set(names)) or any(PurePosixPath(n).is_absolute() or '..' in PurePosixPath(n).parts or '\\' in n for n in names):raise ValueError('unsafe/duplicate backup member')
        if sum(i.file_size for i in z.infolist())>500_000_000:raise ValueError('backup exceeds restore budget')
        envelope=json.loads(z.read('manifest.json'));payload=envelope['payload'];signer=trust.get(envelope['key_id'],{})
        if 'executor' not in signer.get('roles',[]) or not verify_signature(signer.get('public_key',''),envelope['signature'],canonical(payload).encode()) or payload['trust_sha256']!=digest(trust):raise ValueError('backup approval/trust invalid')
        if set(names)!=set(payload['files'])|{'manifest.json'}:raise ValueError('backup contains unlisted files')
        data={name:z.read(name) for name in payload['files']}
        if any(hashlib.sha256(raw).hexdigest()!=payload['files'][name] for name,raw in data.items()):raise ValueError('backup content hash mismatch')
    destination.mkdir(parents=True,mode=0o700)
    for name,raw in data.items():
        path=destination/name;path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with path.open('xb') as f:os.chmod(path,0o600);f.write(raw)
    from governance.investigation import InvestigationStore
    from .journal import Journal
    InvestigationStore(destination/'investigations.sqlite',trust).read(payload['investigation_id'],payload['investigation_head'])
    events=Journal(destination/'operations.sqlite',trust).read()
    if events[-1]['event_hash']!=payload['operational_head']:raise ValueError('restored operational head mismatch')
    return {'status':'VERIFIED_IN_NEW_DIRECTORY','destination':str(destination),'production_restored':False,'scope':'Cryptographic journal/backup integrity only; runtime failover not performed.'}
