from __future__ import annotations

import hashlib, json, os, fcntl
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .monitor import AutopilotTrigger
from .policy import AutopilotPolicy, load_policy

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_STORE=ROOT/'autopilot_jobs.jsonl'
GENESIS='0'*64

class JobStatus(str, Enum):
    QUEUED='QUEUED'; RUNNING='RUNNING'; WAITING_HUMAN='WAITING_HUMAN'; COMPLETE='COMPLETE'; FAILED='FAILED'; SKIPPED='SKIPPED'

@dataclass(frozen=True)
class AutopilotJob:
    job_id: str
    trigger_id: str
    control_id: str
    framework: str
    status: JobStatus
    created_at: str
    updated_at: str
    cycle_id: str | None = None
    checkpoint: str | None = None
    outcome: str | None = None
    error: str | None = None

    def to_dict(self):
        raw=asdict(self); raw['status']=self.status.value; return raw


def _now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
def _canon(v): return json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'),default=str)
def _sha(v): return hashlib.sha256(_canon(v).encode()).hexdigest()

@contextmanager
def _lock(path:Path):
    path.parent.mkdir(parents=True,exist_ok=True); lp=path.with_name(path.name+'.lock')
    with lp.open('a+') as fh:
        fcntl.flock(fh.fileno(),fcntl.LOCK_EX)
        try: yield
        finally: fcntl.flock(fh.fileno(),fcntl.LOCK_UN)

class AutopilotScheduler:
    def __init__(self, path: str|Path|None=None, policy: AutopilotPolicy|None=None):
        self.path=Path(path or os.environ.get('WB_GAAR_AUTOPILOT_JOB_STORE',DEFAULT_STORE)); self.policy=policy or load_policy()

    def _records(self):
        if not self.path.exists(): return []
        out=[]; prev=GENESIS
        for line in self.path.read_text(encoding='utf-8').splitlines():
            if not line.strip(): continue
            row=json.loads(line)
            if row.get('prev_hash')!=prev: raise ValueError('autopilot job chain is broken')
            if row.get('record_hash')!=_sha({k:v for k,v in row.items() if k!='record_hash'}): raise ValueError('autopilot job record hash is invalid')
            out.append(row); prev=row['record_hash']
        return out

    def _append(self, job:AutopilotJob):
        with _lock(self.path):
            rows=self._records(); prev=rows[-1]['record_hash'] if rows else GENESIS
            row={'schema_version':'gaar.autopilot-job.v1','prev_hash':prev,'job':job.to_dict()}; row['record_hash']=_sha(row)
            with self.path.open('a',encoding='utf-8') as fh: fh.write(_canon(row)+'\n'); fh.flush(); os.fsync(fh.fileno())
        return job

    def latest_jobs(self) -> list[AutopilotJob]:
        latest={}
        for r in self._records():
            j=AutopilotJob(**{**r['job'],'status':JobStatus(r['job']['status'])}); latest[j.job_id]=j
        return list(latest.values())

    def enqueue(self, trigger:AutopilotTrigger) -> AutopilotJob:
        for j in self.latest_jobs():
            if j.trigger_id==trigger.trigger_id: return j
        now=_now(); jid='AJ-'+_sha({'trigger_id':trigger.trigger_id})[:24]
        return self._append(AutopilotJob(jid,trigger.trigger_id,trigger.control_id,trigger.framework,JobStatus.QUEUED,now,now))

    def active(self): return [j for j in self.latest_jobs() if j.status==JobStatus.RUNNING]
    def queued(self): return [j for j in self.latest_jobs() if j.status==JobStatus.QUEUED]

    def claim(self) -> list[AutopilotJob]:
        capacity=max(0,self.policy.max_concurrent_reassessments-len(self.active()))
        claimed=[]
        for j in sorted(self.queued(), key=lambda x:(x.created_at,x.job_id))[:capacity]:
            n=AutopilotJob(**{**j.__dict__,'status':JobStatus.RUNNING,'updated_at':_now()}); self._append(n); claimed.append(n)
        return claimed

    def update(self, job:AutopilotJob, *, status:JobStatus, cycle_id:str|None=None, checkpoint:str|None=None,
               outcome:str|None=None, error:str|None=None) -> AutopilotJob:
        n=AutopilotJob(job.job_id,job.trigger_id,job.control_id,job.framework,status,job.created_at,_now(),
                       cycle_id if cycle_id is not None else job.cycle_id,
                       checkpoint if checkpoint is not None else job.checkpoint,
                       outcome if outcome is not None else job.outcome,
                       error if error is not None else job.error)
        return self._append(n)

    def status(self) -> dict[str,Any]:
        jobs=self.latest_jobs(); counts={s.value:sum(j.status==s for j in jobs) for s in JobStatus}
        return {'enabled':self.policy.enabled,'max_concurrent':self.policy.max_concurrent_reassessments,
                'queue_depth':counts['QUEUED'],'in_flight':counts['RUNNING'],'counts':counts,'jobs':jobs}
