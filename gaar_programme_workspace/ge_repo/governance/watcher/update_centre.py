"""WB-134: factual scan receipts and plain-language publication-domain grouping.

Domain tags are discovery/review suggestions, never legal classifications or impact approvals.
The feed adapter is explicitly a publication-index/summary adapter: a successful index
poll is not proof that every PDF on the site was downloaded or inspected.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from .store import HashChainStore
from .models import utcnow

DOMAINS = {
    'AI and model governance': ('artificial intelligence','machine learning','ai model','model governance','model risk','ai governance','generative ai','algorithm'),
    'Cybersecurity and resilience': ('cyber','technology risk','vulnerab','ransomware','incident','resilience','operational risk'),
    'Data protection and privacy': ('personal data','privacy','data protection','data breach'),
    'Financial crime and AML': ('money laundering','aml','terrorist financing','sanction','financial crime'),
    'Third-party and outsourcing': ('outsourc','third party','third-party','vendor','supply chain'),
    'Consumer protection': ('consumer','fair dealing','customer','conduct'),
    'Financial reporting and capital': ('capital adequacy','liquidity','financial report','disclosure','securitisation'),
    'Digital assets and payments': ('digital payment','stablecoin','tokenis','crypto','payments'),
    'Governance and accountability': ('board','governance','accountability','fit and proper','risk management'),
}

def domain_suggestions(title: str, summary: str = '') -> list[str]:
    value=(title+' '+summary).lower()
    return [name for name, terms in DOMAINS.items() if any(term in value for term in terms)] or ['Unclassified — review required']

class ScanReceipts:
    def __init__(self,path: str|Path|None=None):
        self.store=HashChainStore(path or os.environ.get('WB_GAAR_WATCHER_SCAN_STORE') or Path(__file__).resolve().parents[1]/'watcher_scan_receipts.jsonl', 'gaar.watcher-scan.v1')
    def record(self,*,source_id:str,status:str,run_id:str|None=None,discovered:int=0,error:str|None=None,checked_at:str|None=None,interval_minutes:int=360):
        if status not in ('UP_TO_DATE','UPDATES_AVAILABLE','UNABLE_TO_CHECK'):
            raise ValueError('invalid source scan status')
        return self.store.append('SourceScan',dict(source_id=source_id,status=status,run_id=run_id,discovered=discovered,error=error,checked_at=checked_at or utcnow(),interval_minutes=interval_minutes))
    def latest(self,source_id:str):
        rows=[r['payload'] for r in self.store.read() if r['payload']['source_id']==source_id]
        return rows[-1] if rows else None
    def status(self,source_id:str,*,enabled:bool,now:datetime|None=None):
        if not enabled: return {'source_id':source_id,'status':'NOT_CONFIGURED','message':'Monitoring not enabled'}
        row=self.latest(source_id)
        if not row: return {'source_id':source_id,'status':'NEVER_CHECKED','message':'No successful or failed scan recorded'}
        if row['status']=='UNABLE_TO_CHECK': return dict(row)
        now=now or datetime.now(timezone.utc)
        try: checked=datetime.fromisoformat(row['checked_at'].replace('Z','+00:00'))
        except ValueError: return dict(row,status='UNABLE_TO_CHECK',error='Invalid scan timestamp')
        if checked.tzinfo is None: return dict(row,status='UNABLE_TO_CHECK',error='Missing timezone in scan timestamp')
        if now-checked > timedelta(minutes=int(row['interval_minutes'])*2):
            return dict(row,status='CHECK_OVERDUE',message='Last successful scan is stale')
        return dict(row)
