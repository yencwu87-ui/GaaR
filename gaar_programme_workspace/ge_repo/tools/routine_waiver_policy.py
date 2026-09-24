#!/usr/bin/env python3
"""Issue or inspect a signed local routine waiver policy (NOT identity authentication)."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from governance.routine_waiver import policy_approval, verify_policy
from governance.result_integration import signer_from_env

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True,help='New policy file outside the repository; never overwritten')
    p.add_argument('--approve',action='store_true',help='Explicitly issue local signed policy')
    p.add_argument('--actor',help='Named human policy approver (local attribution, NOT RBAC)')
    p.add_argument('--reason',help='Recorded governance reason; min 16 characters')
    a=p.parse_args()
    if a.approve:
        if not a.actor or not a.reason:p.error('--approve requires --actor and --reason')
        approval=policy_approval(approved_by=a.actor,reason=a.reason,signer=signer_from_env())
        a.output.parent.mkdir(parents=True,exist_ok=True)
        with a.output.open('x',encoding='utf-8') as f:
            json.dump(approval,f,indent=2,sort_keys=True)
            f.write('\n')
        a.output.chmod(0o600)
        print(json.dumps({'created':str(a.output),'version':approval['schema'],
            'approved_by':approval['approved_by'],'signature_valid':verify_policy(approval)},indent=2))
    else:
        approval=json.loads(a.output.read_text())
        print(json.dumps({'policy':str(a.output),'signature_valid':verify_policy(approval),
                          'approved_by':approval.get('approved_by'),'schema':approval.get('schema')},indent=2))
        if not verify_policy(approval):return 2
    return 0
if __name__=='__main__':raise SystemExit(main())
