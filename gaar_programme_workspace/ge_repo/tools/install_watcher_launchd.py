#!/usr/bin/env python3
"""Print/install a local launchd agent for opt-in hourly source-due polling.
No sudo, no privileged daemon, no silent install. Only on actual macOS.
"""
import argparse, os, plistlib, subprocess, sys
from pathlib import Path

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--install',action='store_true',help='write user LaunchAgent (disabled until explicit launchctl bootstrap)')
    ap.add_argument('--print',dest='show',action='store_true')
    a=ap.parse_args()
    root=Path(__file__).resolve().parents[1]
    python=Path(sys.executable).resolve()
    log=Path.home()/'.gaar'/'logs'
    plist={ 'Label':'org.gaar.regulatory-watcher', 'ProgramArguments':[str(python),str(root/'tools'/'watcher_updates.py'),'scan'],
        'WorkingDirectory':str(root),'StartInterval':3600,'RunAtLoad':True,
        'EnvironmentVariables':{'WB_GAAR_WATCHER_SCHEDULER_ENABLED':'1'},
        'StandardOutPath':str(log/'watcher_scheduler.log'),'StandardErrorPath':str(log/'watcher_scheduler.error.log')}
    data=plistlib.dumps(plist)
    if a.install:
        if sys.platform!='darwin': raise SystemExit('launchd installation requires macOS; use --print for an inspection only')
        dest=Path.home()/'Library'/'LaunchAgents'/'org.gaar.regulatory-watcher.plist'
        dest.parent.mkdir(parents=True,exist_ok=True);log.mkdir(parents=True,exist_ok=True)
        if dest.exists(): raise SystemExit(f'{dest} exists; inspect/backup it before replacement')
        dest.write_bytes(data)
        print(f'Installed (not bootstrapped): {dest}')
        print(f'Enable explicitly: launchctl bootstrap gui/$(id -u) {dest}')
        print(f'Disable: launchctl bootout gui/$(id -u) {dest}')
    else:print(data.decode())
if __name__=='__main__':main()
