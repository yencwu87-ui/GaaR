#!/usr/bin/env python3
"""Convert a quarantined PDF/HTML receipt into versioned TXT in instruments/regulatory.

Official live:
 python tools/regulator_fetch.py --regulator MAS --url https://www.mas.gov.sg/...pdf --output /private/intake
 python tools/instrument_convert.py --receipt /private/intake/<sha>.receipt.json --id MAS-PSN05
Offline (operator-supplied original, NOT live proof):
 python tools/instrument_convert.py --local-pdf /path/archive.pdf --regulator MAS --official-url https://www.mas.gov.sg/...pdf --id MAS-P012-2026
"""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from governance.watcher.instrument_conversion import convert_receipt,import_local_pdf,ConversionError

def main():
 ap=argparse.ArgumentParser(description=__doc__)
 grp=ap.add_mutually_exclusive_group(required=True)
 grp.add_argument('--receipt',type=Path)
 grp.add_argument('--local-pdf',type=Path,help='operator-supplied original; cannot certify live retrieval')
 ap.add_argument('--regulator',choices=('MAS','FCA','HKMA','NFRA'))
 ap.add_argument('--official-url',help='official URL used as OPERATOR ATTESTATION on --local-pdf')
 ap.add_argument('--id',required=True,help='version-stable instrument identifier e.g. MAS-PSN05')
 ap.add_argument('--title',default='')
 ap.add_argument('--instruments',type=Path,default=ROOT/'instruments')
 ap.add_argument('--intake',type=Path,default=ROOT/'governance'/'regulator_intake')
 a=ap.parse_args()
 try:
  if a.local_pdf:
   if not a.regulator or not a.official_url: ap.error('--local-pdf requires --regulator and --official-url')
   receipt=import_local_pdf(a.local_pdf,a.intake,regulator=a.regulator,url=a.official_url)
  else:receipt=a.receipt
  info=convert_receipt(receipt,a.instruments,instrument_id=a.id,title=a.title,regulator=a.regulator)
  print(json.dumps(info,indent=2));return 0
 except (ConversionError,OSError,ValueError,KeyError) as exc:
  print(json.dumps({'status':'BLOCKED','reason':str(exc)}),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
