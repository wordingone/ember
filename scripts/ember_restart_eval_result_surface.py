#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Render only a receipt that central admission has independently admitted."""
import argparse,hashlib,json,os,subprocess,sys,tempfile
from pathlib import Path

def _sha256(data):
 return hashlib.sha256(data).hexdigest()

def _admitted(manifest,registry,input_bytes):
 if manifest is None or registry is None:return False
 snapshot=None
 try:
  manifest_bytes=manifest.read_bytes();payload=json.loads(manifest_bytes.decode('utf-8'))
  with tempfile.NamedTemporaryFile('wb',dir=manifest.parent,suffix='.json',delete=False) as handle:
   handle.write(manifest_bytes);snapshot=Path(handle.name)
  contract=Path(__file__).parent/'ember_restart'/'contract.py'
  checked=subprocess.run([sys.executable,str(contract),'validate',str(snapshot),'--trusted-verifier-registry',str(registry)],capture_output=True,text=True,timeout=120,check=False)
  if checked.returncode or payload.get('stage')!='OWNED_ADMITTED':return False
  root=manifest.resolve().parent;wanted=_sha256(input_bytes)
  return any(isinstance(entry,dict) and isinstance(entry.get('receipt_path'),str) and (root/entry['receipt_path']).is_file() and _sha256((root/entry['receipt_path']).read_bytes())==wanted for entry in payload.get('evaluations',[]))
 except (OSError,UnicodeError,json.JSONDecodeError,subprocess.SubprocessError):return False
 finally:
  if snapshot is not None:snapshot.unlink(missing_ok=True)

def main():
 parser=argparse.ArgumentParser()
 parser.add_argument('--input',required=True,type=Path)
 parser.add_argument('--admission-manifest',type=Path)
 parser.add_argument('--trusted-verifier-registry',type=Path)
 parser.add_argument('--output',required=True,type=Path)
 args=parser.parse_args()
 if args.output.exists():parser.error('output must not pre-exist')
 try:
  input_bytes=args.input.read_bytes();result=json.loads(input_bytes.decode('utf-8'))
 except (OSError,UnicodeError,json.JSONDecodeError):parser.error('input must be JSON')
 if not isinstance(result,dict):parser.error('input must be an object')
 measured=result.get('result')=='MEASURED' and _admitted(args.admission_manifest,args.trusted_verifier_registry,input_bytes)
 label='MEASURED CAPABILITY' if measured else 'NOT CLAIM-BEARING'
 args.output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=args.output.parent,delete=False)as handle:
  handle.write(f'# Ember evaluation result\n\nStatus: {label}\n\nCapability: {result.get("capability","unknown")}\n');temporary=Path(handle.name)
 try:
  os.replace(temporary,args.output)
 finally:
  temporary.unlink(missing_ok=True)

if __name__=='__main__':main()
