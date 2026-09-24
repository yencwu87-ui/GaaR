#!/usr/bin/env python3
"""Create a clearly synthetic, evaluation-only investigation on-ramp.

This command creates service identities and fixture authority only. Its output
cannot be used in production and cannot authorize deployment or seal a result.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from governance.investigation import InvestigationEngine, InvestigationStore
from governance.investigation.contracts import (ApplicableExpectations, Expectation,
    InvestigationContext, Scope)
from governance.investigation.store import canonical
from governance.result_contract import CanonicalSigner


ROLES=("owner","governance","assessor","test_planner","executor","challenger","decision","result_sealer")


def private_seed() -> str:
    key=Ed25519PrivateKey.generate()
    raw=key.private_bytes(Encoding.Raw,PrivateFormat.Raw,NoEncryption())
    return base64.b64encode(raw).decode()


def safe_id(value: str) -> str:
    if not value or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for ch in value):
        raise ValueError("identifiers may contain only letters, digits, dot, dash and underscore")
    return value


def write_new(path: Path, data: bytes, mode=0o600):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,mode)
    with os.fdopen(fd,"wb") as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template",type=Path,default=Path(__file__).resolve().parents[1]/"config/programme_operations.json")
    parser.add_argument("--output-config",type=Path,required=True)
    parser.add_argument("--evidence",type=Path,required=True,help="UTF-8 text/JSON/CSV export; whole file is admitted")
    parser.add_argument("--investigation-id",required=True);parser.add_argument("--system-id",required=True)
    parser.add_argument("--version",required=True);parser.add_argument("--period",required=True,help="timezone-aware ISO timestamp")
    parser.add_argument("--framework",required=True);parser.add_argument("--control",required=True)
    parser.add_argument("--requirement-version",required=True);parser.add_argument("--requirement",required=True)
    parser.add_argument("--element-id",required=True);parser.add_argument("--element",required=True)
    parser.add_argument("--purpose",choices=["design","operating"],default="operating")
    parser.add_argument("--confirm-evaluation-only",action="store_true",required=True)
    args=parser.parse_args()
    for value in (args.investigation_id,args.system_id,args.framework,args.control,args.element_id):safe_id(value)
    evidence=args.evidence.resolve(strict=True);raw=evidence.read_bytes()
    try:text=raw.decode("utf-8")
    except UnicodeDecodeError:raise ValueError("provisioner accepts UTF-8 text/JSON/CSV only; PDF slicing requires reviewed extraction")
    if not text.strip():raise ValueError("evidence file is empty")
    output=args.output_config.resolve()
    if output.exists():raise ValueError("output config already exists; provisioner never overwrites")
    root=output.parent;workspace=root/"evaluation_fixture";keys=workspace/"keys"
    if workspace.exists():raise ValueError("evaluation fixture directory already exists")
    config=json.loads(args.template.resolve(strict=True).read_text())
    if config.get("operation_mode","evaluation")!="evaluation":raise ValueError("provisioner refuses production mode")
    signers={};trust={};signer_config={}
    for role in ROLES:
        seed=private_seed();key_id="EVAL-"+role.upper();signer=CanonicalSigner.from_base64(key_id,seed)
        key_path=keys/(role+".key");write_new(key_path,(seed+"\n").encode())
        signers[role]=signer;signer_config[role]={"key_id":key_id,"private_key_file":str(key_path.relative_to(root))}
        policy={"actor":"EVALUATION-SERVICE-"+role,"actor_type":"service","public_key":signer.public_key_b64,"roles":[role]}
        if role=="assessor":policy.update(require_dependency_review=True,require_integrated_gate=True)
        if role=="decision":policy["allow_auto_block"]=True
        if role=="executor":policy.update(allow_readonly_collectors=True,allow_action_assignment=False)
        trust[key_id]=policy
    required={}
    if args.control in {"CHANGE.MGMT","M3.12"}:required[args.control]=[["change_authorization","2"],["change_population","1"]]
    if args.control=="M3.6":required[args.control]=[[name,"1"] for name in ("m36_model_evaluation","m36_representativeness","m36_independent_validation","m36_residual_risk")]
    trust[signers["test_planner"].key_id]["required_tools_by_control"]=required
    expectation_bytes=(args.requirement+"\n").encode();expectation_hash=hashlib.sha256(expectation_bytes).hexdigest()
    expectation_path=workspace/"expectation.txt";write_new(expectation_path,expectation_bytes)
    evidence_hash=hashlib.sha256(raw).hexdigest();evidence_path=workspace/("evidence"+evidence.suffix.lower())
    write_new(evidence_path,raw)
    source_id="EVAL-EXPECTATION-"+args.control
    source={"source_id":source_id,"issuer":"INTERNAL","sha256":expectation_hash,"version":args.requirement_version,
            "authority":"internal","snapshot_path":str(expectation_path.relative_to(root)),"evaluation_fixture":True}
    precedent_payload={"status":"EVALUATION_FIXTURE","framework":args.framework,"control_id":args.control,"records":[]}
    governance=signers["governance"]
    precedent={"payload":precedent_payload,"key_id":governance.key_id,"signature":governance.sign(canonical(precedent_payload).encode())}
    precedent_path=workspace/"precedents.json";write_new(precedent_path,(canonical(precedent)+"\n").encode())
    config.update(operation_mode="evaluation",trusted_keys=trust,signers=signer_config,sources={source_id:source},
                  store=str((workspace/"investigations.sqlite").relative_to(root)),programme_dir=str((workspace/"programme").relative_to(root)),
                  receipt_dir=str((workspace/"receipts").relative_to(root)),expected_heads={},result_decisions={},qualification_report="",
                  precedent_snapshot={"path":str(precedent_path.relative_to(root)),"sha256":hashlib.sha256(precedent_path.read_bytes()).hexdigest(),"evaluation_fixture":True},
                  collectors=[{"root":str(workspace.relative_to(root)),"path":evidence_path.name,"source_id":"EVAL-EVIDENCE",
                    "sha256":evidence_hash,"scope":{"system_id":args.system_id,"version":args.version,"period":args.period},
                    "authority":"internal","provenance":["evaluation-only-provisioner","whole-utf8-file"],
                    "segments":[{"start":0,"end":len(text),"evidence_id":"EVAL-E1","element_ids":[args.element_id],
                                 "purposes":["operating_record" if args.purpose=="operating" else "design_statement"]}]}])
    engine=InvestigationEngine(InvestigationStore(root/config["store"],trust),config["sources"])
    scope=Scope(system_id=args.system_id,version=args.version,period=args.period)
    context=InvestigationContext(investigation_id=args.investigation_id,framework=args.framework,control_id=args.control,
        requirement_version=args.requirement_version,scope=scope,boundary="Evaluation fixture provisioned from one explicit UTF-8 export",
        owner=trust[signers["owner"].key_id]["actor"],criticality="high",synthetic=True)
    expectations=ApplicableExpectations(requirement_version=args.requirement_version,elements=(Expectation(element_id=args.element_id,
        text=args.element,source_id=source_id,source_sha256=expectation_hash,source_version=args.requirement_version,
        authority="internal",purpose=args.purpose,applies=True,applicability_reason="Explicit evaluation fixture scope"),))
    engine.append(args.investigation_id,"understand",context,signers["owner"])
    engine.append(args.investigation_id,"expectations",expectations,signers["governance"])
    rows,_=engine.snapshot(args.investigation_id);config["expected_heads"][args.investigation_id]=rows[-1]["record_hash"]
    write_new(output,(json.dumps(config,indent=2)+"\n").encode())
    print(json.dumps({"status":"EVALUATION_FIXTURE_CREATED","config":str(output),"investigation_id":args.investigation_id,
                      "synthetic":True,"production_usable":False,"deployment_authorized":False},indent=2))


if __name__=="__main__":
    try:main()
    except Exception as exc:print(json.dumps({"status":"BLOCKED","reason":f"{type(exc).__name__}: {exc}"}),file=sys.stderr);sys.exit(2)
