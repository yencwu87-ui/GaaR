#!/usr/bin/env python3
"""Local single-run interface; operate only inside a trusted OS session."""
import json,os,sqlite3,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import streamlit as st
from governance.operations.runtime import load
from governance.investigation import InvestigationEngine,InvestigationStore
from governance.production.orchestrator import run,case_directory

ROOT=Path(__file__).resolve().parents[1]
st.set_page_config(page_title='GaaR — Run investigation',layout='wide')
st.title('Run an investigation')
st.caption('Select a system and an authorized assessment. Completed stages resume automatically.')
try:
    config_path=Path(os.environ.get('WB_INVESTIGATION_CONFIG',ROOT/'config/programme_operations.json'))
    config,root=load(config_path)
    st.info('Mode: '+config.get('operation_mode','evaluation')+'. Deployment authorization remains separate.')
    path=root/config['store']
    if not path.exists():
        st.warning('No authorized assessments are registered. Complete owner and source setup using the operation manual.');st.stop()
    engine=InvestigationEngine(InvestigationStore(path,config['trusted_keys']),config['sources'])
    with sqlite3.connect(path) as db:ids=[r[0] for r in db.execute('SELECT DISTINCT investigation_id FROM stages ORDER BY investigation_id')]
    available=[]
    for iid in ids:
        try:
            rows,values=engine.snapshot(iid)
            if 'understand' in values:available.append((values['understand'].scope.system_id,iid))
        except Exception as exc:st.error('Cannot verify assessment '+iid+': '+str(exc))
    if not available:st.warning('No verified investigation context available.');st.stop()
    system=st.selectbox('System',sorted({s for s,i in available}))
    iid=st.selectbox('Assessment',[i for s,i in available if s==system])
    if st.button('Run / resume',type='primary'):
        with st.spinner('Running approved investigation stages…'):
            st.session_state['programme_result']=(iid,run(config,root,iid))
    result=None
    if st.session_state.get('programme_result',(None,))[0]==iid:result=st.session_state['programme_result'][1]
    else:
        status=case_directory(config,root,iid)/'latest_status.json'
        if status.exists():result=json.loads(status.read_text())
    if result:
        status=result.get('checkpoint','UNKNOWN')
        if status=='COMPLETE':st.success('Investigation complete. Read the verdict and decision request below.')
        elif status=='EVALUATION_COMPLETE':st.info('Evaluation workflow complete. Production qualification remains outstanding.')
        else:st.warning('Action required: '+status)
        request=result.get('request') or result.get('next_request')
        if request:
            st.write(request['reason'])
            for item in request['required_items']:st.write('• '+item)
        for blocker in result.get('gate',{}).get('blockers',[]):st.write('Needs attention: '+blocker)
        st.write('Verdict:',result.get('gate',{}).get('verdict','Not concluded'))
        st.write('Deployment authorized:',False)
        with st.expander('Traceable result and technical detail'):st.json(result)
        st.download_button('Download status report',json.dumps(result,indent=2),file_name='investigation-status.json',mime='application/json')
except Exception as exc:st.error('Unable to check: '+str(exc))
