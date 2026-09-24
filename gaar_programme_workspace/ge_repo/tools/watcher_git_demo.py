#!/usr/bin/env python3
"""Run an entirely isolated DEMO ADD/DIFF/COMMIT/PUSH using the real CLI.

No user data, real regulator sites, or durable GaaR ledgers are accessed.
"""
from __future__ import annotations

import base64
import json
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="gaar-watcher-git-DEMO-") as dir_name:
        path=Path(dir_name)
        source=path/"DEMO_policy.txt"
        source.write_text("DEMO ONLY: fictional AI oversight rule.\n",encoding="utf-8")
        config=path/"sources.yaml"
        config.write_text("""sources:
  - source_id: demo-regulator
    source_type: regulation
    authority: binding
    jurisdiction: DEMO
    enabled: true
    connector: {type: static, items: []}
    filters:
      framework: DEMO
      approved_domains: [regulator.example.test]
""",encoding="utf-8")
        env={**os.environ,
             "WB_GAAR_WATCHER_BLOBS":str(path/"cas"),
             "WB_GAAR_WATCHER_SNAPSHOTS":str(path/"snapshots.jsonl"),
             "WB_GAAR_WATCHER_GIT_STORE":str(path/"git.jsonl"),
             "WB_GAAR_AUTOPILOT_TRIGGER_STORE":str(path/"triggers.jsonl"),
             "WB_GAAR_AUTOPILOT_JOB_STORE":str(path/"jobs.jsonl"),
             "WB_GAAR_RESULT_SIGNING_KEY_B64":base64.b64encode(secrets.token_bytes(32)).decode(),
             "WB_GAAR_RESULT_KEY_ID":"DEMO-ephemeral-not-authority"}
        runner=[sys.executable,str(ROOT/"tools"/"watcher_git.py"),"--config",str(config)]
        def cli(*args):
            result=subprocess.run([*runner,*args],cwd=ROOT,env=env,capture_output=True,text=True)
            if result.returncode:
                raise RuntimeError(result.stderr)
            return json.loads(result.stdout)
        staged=cli("add","--file",str(source),"--source-id","demo-regulator",
                   "--document-id","fictional-1","--source-url","https://regulator.example.test/fictional-1",
                   "--landing-url","https://regulator.example.test/catalogue","--title","DEMO fictional rule",
                   "--issuer","DEMO Regulator","--published-at","2026-09-19",
                   "--document-class","binding_rule","--lifecycle","effective",
                   "--assessment","ASM-DEMO","--framework","DEMO","--control","DEMO-C1",
                   "--actor","DEMO OPERATOR","--reason","Lab scenario only",
                   "--attestation","DEMO fictional domain is not a real regulator")
        difference=cli("diff",staged["stage_id"])
        committed=cli("commit",staged["stage_id"],"--reviewer","DEMO OPERATOR",
                      "--note","Approved for lab simulation only")
        verified=cli("verify",committed["commit_id"])
        pushed=cli("push",committed["commit_id"])
        pushed_again=cli("push",committed["commit_id"])
        assert pushed["push_id"]==pushed_again["push_id"]
        assert len(json.loads((path/"triggers.jsonl").read_text().splitlines()[0])["trigger"])>0
        assert len((path/"jobs.jsonl").read_text().splitlines())==1
        print(json.dumps({"mode":"ISOLATED_SYNTHETIC_DEMO", "stage_id":staged["stage_id"],
            "diff_from":difference["previous_version_hash"],"commit_id":committed["commit_id"],
            "signed_commit":verified["signature"],"blob_verified":verified["CAS_hash"],
            "push_id":pushed["push_id"],"relationship":pushed["relationship_status"],
            "typed_triggers":len(pushed["trigger_ids"]),"autopilot_jobs":1,
            "idempotent_push":True,"no_real_regulator_accessed":True,
            "no_live_governance_results_created":True},indent=2))


if __name__=="__main__": main()
