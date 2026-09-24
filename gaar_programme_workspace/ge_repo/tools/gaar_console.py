#!/usr/bin/env python3
"""Local operational console. Saves choices; never creates approval authority."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import webbrowser
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
ROOT=Path(__file__).resolve().parents[1]
SETTINGS=ROOT/'config/programme_console.json'
DEFAULT=ROOT/'config/programme_operations.json'


def settings():
    return json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {'config':str(DEFAULT),'investigation_id':''}


def save_settings(value):
    SETTINGS.parent.mkdir(exist_ok=True)
    SETTINGS.write_text(json.dumps(value,indent=2)+'\n')
    os.chmod(SETTINGS,0o600)


def select_models(config_path,choose=input):
    from governance.operations.live import request_json
    config=json.loads(config_path.read_text())
    endpoints=[('ollama','http://127.0.0.1:11434','/api/tags'),('openai_compatible','http://127.0.0.1:8000/v1','/models')]
    choices=[]
    for provider,base,suffix in endpoints:
        try:
            reply=request_json(base+suffix,{'timeout_seconds':3})
            ids=[m['name'] for m in reply.get('models',[])] if provider=='ollama' else [m['id'] for m in reply.get('data',[])]
            choices.extend({'provider':provider,'base_url':base,'model':m,'timeout_seconds':120,'max_tokens':8192} for m in ids)
        except Exception: print('Service not reachable:',base)
    if not choices:
        print('No local model service found. Start your installed service and try again. No model is downloaded or started automatically.')
        return
    for i,c in enumerate(choices,1):print(f"{i}. {c['provider']} / {c['model']}")
    for stage in ('examine','explain','plan','challenge'):
        answer=choose(f'Model number for {stage} (Enter keeps current): ').strip()
        if answer:
            index=int(answer)-1
            if not 0<=index<len(choices):raise ValueError('model number out of range')
            config.setdefault('models',{})[stage]=choices[index]
    # Operator selections are routing preferences, not trusted-role or authority approvals.
    backup=config_path.with_name(config_path.name+'.before-model-setup')
    if not backup.exists():backup.write_bytes(config_path.read_bytes())
    tmp=config_path.with_suffix('.tmp');tmp.write_text(json.dumps(config,indent=2)+'\n');tmp.replace(config_path)
    print('Saved model choices. Separate challenger signing identity is still required.')


def perform(action,s):
    from governance.operations.runtime import load,doctor
    from governance.production.orchestrator import run
    config_path=Path(s['config']).expanduser().resolve()
    config,root=load(config_path)
    if action=='check':
        report=doctor(config,root)
        print('\nConfiguration:',report['status'])
        for name,check in report['checks'].items():print(f"  {name}: {check['status']}"+(f" — {check['reason']}" if check.get('reason') else ''))
        print('No maturity percentage or production approval is inferred.')
    elif action=='run':
        if not s.get('investigation_id'):
            print('Choose your existing owner-authorized investigation ID in Setup first.');return
        report=run(config,root,s['investigation_id'])
        print('Stopped at:',report['checkpoint'])
        for blocker in report.get('gate',{}).get('blockers',[]):print('  Needs attention:',blocker)
        request=report.get('request') or report.get('next_request')
        if request:
            print(request['kind']+': '+request['reason'])
            for item in request['required_items']:print('  Required:',item)
        print('Deployment authorized:',report.get('deployment_authorized',False))
    elif action=='assurance':
        from governance.production.assurance import inspect_environment
        report=inspect_environment(config,root);print(json.dumps(report,indent=2))
    elif action=='evaluate':
        from governance.production.evaluation import evaluate
        report=evaluate(config,root);print('Evaluation:',report['status']);print(report.get('reason','Independent semantic review still required.'))
    elif action=='knowledge':
        from governance.investigation.dependencies import investigate
        report=investigate('INTERNAL','CHANGE.MGMT')
        print('Change-management investigation relationships (proposed internal knowledge):')
        for edge in report['edges']:
            print('\n'+edge['upstream']+' → '+edge['downstream']+'\n  '+edge['relation'])
            print('  Check:', '; '.join(edge['evidence_required']))
            print('  Alternative:', '; '.join(edge['alternatives']))
        print('\nThese are investigation questions, not proof of a breach.')
    else:raise ValueError('unknown action')
    directory=ROOT/'verification/wb143_149/operator_runs';directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    from datetime import datetime,timezone
    name=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'-'+action+'.json'
    path=directory/name
    with path.open('x') as f:
        os.chmod(path,0o600);json.dump(report,f,indent=2)
    print('Report:',path)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--action',choices=['check','run','evaluate','knowledge','assurance']);args=parser.parse_args()
    s=settings()
    if args.action:
        report=perform(args.action,s)
        if report is None or report.get('status') in {'BLOCKED','UNAVAILABLE','NOT_EVALUATED','PARTIAL'} or report.get('checkpoint') not in (None,'COMPLETE'):sys.exit(2)
        return
    while True:
        print('\nGaaR — Integrated programme candidate\n1 Check readiness\n2 One-time setup / model selection\n3 Run investigation\n4 Explore change-control dependencies\n5 Evaluate four agent stages\n6 Open full operation manual\n7 Start legacy workbench UI\n8 Production assurance status\n9 Open reviewer app (default front door)\nP Pilot on-ramp: bring your own keys (tools/gaar_pilot.py)\n0 Exit')
        try:
            action=input('Choose: ').strip()
            if action=='0':return
            if action=='2':
                path=input('Configuration JSON path (Enter keeps current): ').strip()
                if path:
                    selected=Path(path).expanduser().resolve(strict=True)
                    if not isinstance(json.loads(selected.read_text()),dict):raise ValueError('configuration must be an object')
                    s['config']=str(selected)
                iid=input('Existing investigation ID (Enter keeps current): ').strip()
                if iid:s['investigation_id']=iid
                save_settings(s)
                select_models(Path(s['config']))
            elif action=='6':webbrowser.open((ROOT.parent/'MANUAL.html').as_uri())
            elif action.lower()=='p':
                subprocess.run([sys.executable,str(ROOT/'tools/gaar_pilot.py'),'--help'],check=False)
                print('Start with: keygen --out <a path you control, outside this package>')
            elif action=='9':
                subprocess.run([sys.executable,'-m','pip','install','streamlit>=1.36,<2'],check=True)
                env=os.environ.copy();env['WB_INVESTIGATION_CONFIG']=s['config']
                subprocess.run([sys.executable,'-m','streamlit','run',str(ROOT/'app_gaar.py'),'--server.address','127.0.0.1','--server.port','8502'],cwd=ROOT,env=env,check=True)
            elif action=='7':
                print('Installing the existing workbench requirements if needed...')
                subprocess.run([sys.executable,'-m','pip','install','-r',str(ROOT/'requirements.txt')],check=True)
                env=os.environ.copy();env['WB_INVESTIGATION_REQUIRED']='1'
                env['WB_INVESTIGATION_CONFIG']=s['config']
                print('Opening workbench at http://127.0.0.1:8501; Ctrl-C stops the UI.')
                subprocess.run([sys.executable,'-m','streamlit','run',str(ROOT/'app.py'),'--server.address','127.0.0.1','--server.port','8501'],cwd=ROOT,env=env,check=True)
            elif action in {'1','3','4','5','8'}:perform({'1':'check','3':'run','4':'knowledge','5':'evaluate','8':'assurance'}[action],s)
            else:print('Choose a listed number.')
        except (EOFError,KeyboardInterrupt):return
        except Exception as exc:print('Unable to complete:',type(exc).__name__,str(exc))
if __name__=='__main__':main()
