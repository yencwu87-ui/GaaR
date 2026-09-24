#!/usr/bin/env python3
"""Read-only routine batch eligibility; NEVER publishes results or decides for a human."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from governance.audit_package import batch_eligibility
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('package_json',type=Path,nargs='+')
a=p.parse_args()
packages=[json.loads(f.read_text()) for f in a.package_json]
result=batch_eligibility(packages)
print(json.dumps(result,indent=2))
raise SystemExit(0 if result['eligible'] else 2)
