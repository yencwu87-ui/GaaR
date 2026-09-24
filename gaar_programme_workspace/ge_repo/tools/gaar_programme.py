#!/usr/bin/env python3
"""Integrated run and local assurance operations. Never sends external messages."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from governance.operations.runtime import load,signers_for
from governance.investigation import InvestigationEngine,InvestigationStore
from governance.production.orchestrator import run,case_directory
from governance.production.journal import Journal,exclusive

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['run','evaluate','check','check-changes','backup','restore-verify','close-action'])
    p.add_argument('--config',type=Path,default=Path(__file__).resolve().parents[1]/'config/programme_operations.json')
    p.add_argument('--action-id');p.add_argument('--investigation-id');p.add_argument('--destination',type=Path);p.add_argument('--archive',type=Path);p.add_argument('--approval',type=Path)
    args=p.parse_args();config,root=load(args.config)
    if args.action=='run':
        if not args.investigation_id:p.error('--investigation-id required')
        result=run(config,root,args.investigation_id)
    elif args.action=='evaluate':
        from governance.production.evaluation import evaluate
        result=evaluate(config,root)
    elif args.action=='check':
        from governance.production.assurance import inspect_environment
        result=inspect_environment(config,root)
    elif args.action=='restore-verify':
        if not args.archive or not args.destination:p.error('--archive and --destination required')
        from governance.production.assurance import restore_verify
        result=restore_verify(args.archive,config['trusted_keys'],args.destination)
    else:
        if not args.investigation_id:p.error('--investigation-id required')
        directory=case_directory(config,root,args.investigation_id)
        with exclusive(directory/'run.lock'):
            signers=signers_for(config,root)
            engine=InvestigationEngine(InvestigationStore(root/config['store'],config['trusted_keys']),config['sources'])
            journal=Journal(directory/'operations.sqlite',config['trusted_keys'])
            if args.action=='backup':
                if not args.destination:p.error('--destination required')
                from governance.production.assurance import backup
                result=backup(config,root,args.investigation_id,engine,journal,signers['executor'],args.destination)
            elif args.action=='check-changes':
                from governance.production.lifecycle import check_changes
                result=check_changes(config,root,args.investigation_id,engine,journal,signers['executor'])
            else:
                if not args.approval or not args.action_id:p.error('--approval and --action-id required')
                from governance.production.actions import close_action
                result=close_action(config,root,journal,args.action_id,args.approval,engine,signers['executor'])
    print(json.dumps(result,indent=2))
    if result.get('checkpoint') in {'ACTION_REQUIRED','QUALITY_GATE_BLOCKED'}:return 2
    return 0
if __name__=='__main__':
    try:sys.exit(main())
    except Exception as exc:print(json.dumps({'status':'BLOCKED','reason':str(exc),'deployment_authorized':False}),file=sys.stderr);sys.exit(2)
