#!/usr/bin/env python3
"""Explicit administrative authorization with existing trusted human keys."""
import argparse,json,os,sys,hashlib,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from governance.operations.runtime import load
from governance.operations.secrets import private_seed
from governance.result_contract import CanonicalSigner
from governance.investigation import InvestigationEngine,InvestigationStore
from governance.investigation.contracts import InvestigationContext,ApplicableExpectations
from governance.investigation.store import canonical
from governance.operations.sources import approved_url,validate_content,validate_source


def signer_for(config,role,root):
    row=config['signers'][role];signer=CanonicalSigner.from_base64(row['key_id'],private_seed(row,root));trusted=config['trusted_keys'][signer.key_id]
    if role not in trusted.get('roles',[]) or trusted.get('public_key')!=signer.public_key_b64 or trusted.get('actor_type')!='human':
        raise ValueError('trusted human role/signing key required')
    return signer,trusted


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',required=True);p.add_argument('--confirm',required=True,help='Exact source or investigation ID being authorized')
    sub=p.add_subparsers(dest='action',required=True);s=sub.add_parser('approve-source');s.add_argument('--source-id',required=True)
    s=sub.add_parser('start');s.add_argument('--bundle',required=True)
    a=p.parse_args();config,root=load(a.config)
    if a.action=='approve-source':
        entry=config['sources'][a.source_id]
        if a.confirm!=a.source_id or entry['source_id']!=a.source_id:raise ValueError('confirmation identity mismatch')
        signer,trust=signer_for(config,'governance',root)
        if entry.get('issuer')=='INTERNAL':
            if entry.get('authority')!='internal' or not entry.get('version'):raise ValueError('internal policy cannot become binding regulation')
            raw=(root/entry['snapshot_path']).read_bytes()
            if not raw or hashlib.sha256(raw).hexdigest()!=entry['sha256'] or entry['approved_by']!=trust['actor']:raise ValueError('internal source/approver mismatch')
            payload={k:entry[k] for k in ('source_id','sha256','authority','version')}
            out=root/entry['authority_decision_ref'];out.parent.mkdir(parents=True,exist_ok=True)
            with out.open('x') as f:json.dump({'payload':payload,'key_id':signer.key_id,'signature':signer.sign(canonical(payload).encode())},f,indent=2)
            validate_source(entry,root,config['trusted_keys']);print('Signed internal source decision:',out);return
        approved_url(entry['issuer'],entry['url'])
        raw=(root/entry['snapshot_path']).read_bytes();receipt=json.loads((root/entry['retrieval_receipt']).read_text())
        if hashlib.sha256(raw).hexdigest()!=entry['sha256'] or receipt.get('sha256')!=entry['sha256'] or receipt.get('url')!=entry['url'] or receipt.get('status')!='QUARANTINED':raise ValueError('snapshot/receipt mismatch')
        validate_content(raw,receipt.get('content_type',''))
        if entry['authority'] not in {'binding','guidance','consultation','internal'} or not entry['version']:raise ValueError('explicit source authority/version required')
        if entry['approved_by']!=trust['actor']:raise ValueError('configured authority approver differs from signer')
        payload={k:entry[k] for k in ('source_id','sha256','authority','version','url')}
        decision={'payload':payload,'key_id':signer.key_id,'signature':signer.sign(canonical(payload).encode())}
        out=root/entry['authority_decision_ref'];out.parent.mkdir(parents=True,exist_ok=True)
        with out.open('x') as f:json.dump(decision,f,indent=2)
        validate_source(entry,root,config['trusted_keys']);print('Signed source decision:',out)
    else:
        bundle=json.loads(Path(a.bundle).read_text());context=InvestigationContext.model_validate(bundle['context']);expectations=ApplicableExpectations.model_validate(bundle['expectations'])
        iid=context.investigation_id
        if a.confirm!=iid or context.synthetic:raise ValueError('exact production investigation confirmation required')
        owner,_=signer_for(config,'owner',root);governance,_=signer_for(config,'governance',root)
        for source_id in {e.source_id for e in expectations.elements}:validate_source(config['sources'][source_id],root,config['trusted_keys'])
        # Validate the complete initial pair before touching the operational journal.
        with tempfile.TemporaryDirectory() as temp:
            trial=InvestigationEngine(InvestigationStore(Path(temp)/'trial.sqlite',config['trusted_keys']),config['sources'])
            trial.append(iid,'understand',context,owner);trial.append(iid,'expectations',expectations,governance)
        engine=InvestigationEngine(InvestigationStore(root/config['store'],config['trusted_keys']),config['sources'])
        rows,values=engine.snapshot(iid)
        if rows:raise ValueError('investigation already exists; no overwriting or implicit migration')
        engine.append(iid,'understand',context,owner);engine.append(iid,'expectations',expectations,governance)
        rows,_=engine.snapshot(iid);config.setdefault('expected_heads',{})[iid]=rows[-1]['record_hash']
        target=Path(a.config).resolve();temp=target.with_suffix('.initialization.tmp');temp.write_text(json.dumps(config,indent=2)+'\n');temp.replace(target)
        print('Owner and expectations signed. Initial expected head saved:',rows[-1]['record_hash'])
        print('Retain an external copy of the trust policy and head before operational use.')
if __name__=='__main__':
    try:main()
    except Exception as e:print('Authorization stopped:',type(e).__name__,str(e));sys.exit(2)
