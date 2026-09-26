"""Signed append-only operational events and a separately fsynced local head anchor."""
from contextlib import contextmanager
from datetime import datetime,timezone
import fcntl
import json
import os
from pathlib import Path
import sqlite3
from governance.investigation.store import canonical,digest
from governance.result_contract import verify_signature

ZERO='0'*64


def authorized_kind(kind,payload,role):
    from governance.investigation.contracts import ROLES
    if kind in {'stage_intent','stage_commit'}:
        return role==ROLES.get(payload.get('stage'))
    allowed={'binding':'executor','stage_recovered':'executor','evidence_manifest':'executor','run_report':'executor',
             'dependency_review':'assessor','challenge_dependency_binding':'challenger','result_sealed':'result_sealer',
             'result_current':'result_sealer','reassessment_requested':'executor','remediation_opened':'executor',
             'collection_receipt':'executor','notification_draft':'executor','remediation_closed':'executor','change_intent':'executor',
             'pilot_attestation':'result_approver','obligation_reconciliation':'executor','model_stage_unavailable':'executor','period_delta':'executor','integrity_event':'executor',
             'record_superseded':'executor','scheduler_tick':'executor','job_outcome':'executor'}
    return allowed.get(kind)==role



def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    tmp=path.with_name(path.name+'.'+os.urandom(8).hex()+'.tmp')
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try:
        with os.fdopen(fd,'w') as f:f.write(canonical(value));f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
        directory=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:
        if tmp.exists():tmp.unlink()


@contextmanager
def exclusive(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(path,os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
    with os.fdopen(fd,'a+') as f:
        try:fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError('Another run is active for this investigation')
        try:yield
        finally:fcntl.flock(f.fileno(),fcntl.LOCK_UN)


class Journal:
    def __init__(self,path,trust):
        self.path=Path(path);self.anchor=self.path.with_suffix('.anchor.json');self.trust=trust
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        if self.path.is_symlink() or self.anchor.is_symlink():raise ValueError('journal paths must not be symlinks')
        if self.anchor.exists() and not self.path.exists():raise ValueError('journal missing beneath retained anchor')
        with sqlite3.connect(self.path) as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS entries (sequence INTEGER PRIMARY KEY, event_key TEXT UNIQUE NOT NULL, envelope TEXT NOT NULL);
            CREATE TRIGGER IF NOT EXISTS entries_no_update BEFORE UPDATE ON entries BEGIN SELECT RAISE(ABORT,'append only'); END;
            CREATE TRIGGER IF NOT EXISTS entries_no_delete BEFORE DELETE ON entries BEGIN SELECT RAISE(ABORT,'append only'); END;''')
        os.chmod(self.path,0o600)

    def _verify(self,entries):
        previous=ZERO
        for index,event in enumerate(entries):
            if event['sequence']!=index or event['previous']!=previous or event['policy_sha256']!=digest(self.trust):raise ValueError('operational journal chain/policy mismatch')
            policy=self.trust.get(event['key_id'],{})
            if event['role'] not in policy.get('roles',[]) or event['actor']!=policy.get('actor') or not authorized_kind(event['kind'],event['payload'],event['role']):raise ValueError('unauthorized operational event signer')
            unsigned={k:v for k,v in event.items() if k not in {'signature','event_hash'}}
            if not verify_signature(policy.get('public_key',''),event['signature'],canonical(unsigned).encode()):raise ValueError('invalid operational signature')
            if digest({**unsigned,'signature':event['signature']})!=event['event_hash']:raise ValueError('operational event hash mismatch')
            previous=event['event_hash']
        return entries

    def read(self):
        with sqlite3.connect(self.path) as db:events=[json.loads(row[0]) for row in db.execute('SELECT envelope FROM entries ORDER BY sequence')]
        self._verify(events)
        if self.anchor.exists():
            anchor=json.loads(self.anchor.read_text())
            if anchor['sequence']>=len(events) or events[anchor['sequence']]['event_hash']!=anchor['event_hash']:raise ValueError('operational journal rollback detected')
        elif events:raise ValueError('head anchor missing; explicit integrity recovery required')
        return events

    def append(self,key,kind,payload,signer,role):
        self.read()
        policy=self.trust.get(signer.key_id,{})
        if role not in policy.get('roles',[]) or policy.get('public_key')!=signer.public_key_b64 or not authorized_kind(kind,payload,role):raise ValueError('untrusted operational signer')
        with sqlite3.connect(self.path) as db:
            db.execute('BEGIN IMMEDIATE')
            events=self._verify([json.loads(r[0]) for r in db.execute('SELECT envelope FROM entries ORDER BY sequence')])
            existing=next((e for e in events if e['event_key']==key),None)
            if existing:
                if existing['kind']!=kind or existing['payload']!=payload:raise ValueError('idempotency key reused with different content')
                return existing
            event={'sequence':len(events),'event_key':key,'kind':kind,'payload':payload,'previous':events[-1]['event_hash'] if events else ZERO,
                   'policy_sha256':digest(self.trust),'actor':policy['actor'],'key_id':signer.key_id,'role':role,'at':datetime.now(timezone.utc).isoformat()}
            event['signature']=signer.sign(canonical(event).encode());event['event_hash']=digest(event)
            db.execute('INSERT INTO entries VALUES (?,?,?)',(len(events),key,canonical(event)))
        atomic_json(self.anchor,{'sequence':event['sequence'],'event_hash':event['event_hash']})
        return event

    def latest(self,kind):
        return next((e for e in reversed(self.read()) if e['kind']==kind),None)
