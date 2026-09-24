#!/usr/bin/env python3
"""Opt-in macOS user LaunchAgent for official publication INDEX scans, never governance writes."""
import argparse,os,plistlib,sys
from pathlib import Path

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--print',action='store_true');ap.add_argument('--install',action='store_true');args=ap.parse_args()
    root=Path(__file__).resolve().parents[1];dest=Path.home()/'Library'/'LaunchAgents'/'org.gaar.official-publication-index.plist'
    log=Path.home()/'.gaar'/'logs'
    plist={'Label':'org.gaar.official-publication-index','ProgramArguments':[str(Path(sys.executable).resolve()),str(root/'tools'/'official_publication_monitor.py'),'scan'],
        'WorkingDirectory':str(root),'StartInterval':3600,'RunAtLoad':True,
        'EnvironmentVariables':{'WB_GAAR_OFFICIAL_INDEX_ENABLED':'1'},
        'StandardOutPath':str(log/'official_publication_index.log'),'StandardErrorPath':str(log/'official_publication_index.error.log')}
    if args.install:
        if sys.platform!='darwin':raise SystemExit('launchd installation requires macOS; --print works here')
        if dest.exists():raise SystemExit(f'{dest} already exists; no overwrite')
        dest.parent.mkdir(parents=True,exist_ok=True);log.mkdir(parents=True,exist_ok=True)
        dest.write_bytes(plistlib.dumps(plist));print('Installed, not started:',dest)
        print('Enable explicitly: launchctl bootstrap gui/$(id -u)',dest)
        print('Disable: launchctl bootout gui/$(id -u)',dest)
    else:print(plistlib.dumps(plist).decode())
if __name__=='__main__':main()
