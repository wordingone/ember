#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Render only a receipt that central admission has independently admitted."""
import argparse,hashlib,json,os,subprocess,sys,tempfile
from pathlib import Path

def _sha256(path):
 return hashlib.sha256(path.read_bytes()).hexdigest()

def _admitted(manifest,registry,input_path):
 if manifest is None or registry is None:return False
 try:
  payload=json.loads(manifest.read_text(encoding='utf-8'))
  contract=Path(__file__).parent/'ember_restart'/'contract.py'
  checked=subprocess.run([sys.executable,str(contract),'validate',str(manifest),'--trusted-verifier-registry',str(registry)],capture_output=True,text=True,timeout=120,check=False)
  if checked.returncode or payload.get('stage')!='OWNED_ADMITTED':return False
  root=manifest.resolve().parent;wanted=_sha256(input_path)
  return any(isinstance(entry,dict) and isinstance(entry.get('receipt_path'),str) and (root/entry['receipt_path']).is_file() and _sha256(root/entry['receipt_path'])==wanted for entry in payload.get('evaluations',[]))
 except (OSError,UnicodeError,json.JSONDecodeError,subprocess.SubprocessError):return False

def main():
 parser=argparse.ArgumentParser()
 parser.add_argument('--input',required=True,type=Path)
 parser.add_argument('--admission-manifest',type=Path)
 parser.add_argument('--trusted-verifier-registry',type=Path)
 parser.add_argument('--output',required=True,type=Path)
 args=parser.parse_args()
 if args.output.exists():parser.error('output must not pre-exist')
 try: result=json.loads(args.input.read_text(encoding='utf-8'))
 except (OSError,UnicodeError,json.JSONDecodeError):parser.error('input must be JSON')
 if not isinstance(result,dict):parser.error('input must be an object')
 measured=result.get('result')=='MEASURED' and _admitted(args.admission_manifest,args.trusted_verifier_registry,args.input)
 label='MEASURED CAPABILITY' if measured else 'NOT CLAIM-BEARING'
 args.output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=args.output.parent,delete=False)as handle:
  handle.write(f'# Ember evaluation result\n\nStatus: {label}\n\nCapability: {result.get("capability","unknown")}\n');temporary=handle.name
 os.replace(temporary,args.output)

if __name__=='__main__':main()
