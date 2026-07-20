#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed validator for honest evaluator completion-certificate records."""
import argparse,json,re,tempfile,os
from pathlib import Path
SHA=re.compile(r'[0-9a-f]{64}');COMMIT=re.compile(r'[0-9a-f]{40}')
def main():
 p=argparse.ArgumentParser();p.add_argument('validate');p.add_argument('certificate',type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args()
 if a.output.exists():p.error('output must not pre-exist')
 try:v=json.loads(a.certificate.read_text())
 except (OSError,json.JSONDecodeError)as e:p.error(f'invalid certificate: {e}')
 required={'schema_version','goal_id','workstream_id','checkpoint_manifest_sha256','evaluator_commit','benchmarks','comparators','resource_receipts','honest_unresolved_gaps','next_checkpoint_evaluation'}
 if not isinstance(v,dict) or set(v)!=required or v.get('schema_version')!='ember-restart-eval-completion-certificate-v1' or v.get('goal_id')!='EMBER-02' or v.get('workstream_id')!='EMBER-02C' or not SHA.fullmatch(v.get('checkpoint_manifest_sha256','')) or not COMMIT.fullmatch(v.get('evaluator_commit','')) or not isinstance(v['benchmarks'],list) or not v['benchmarks'] or not isinstance(v['comparators'],list) or not isinstance(v['resource_receipts'],list) or not isinstance(v['honest_unresolved_gaps'],list) or not v['honest_unresolved_gaps'] or not isinstance(v['next_checkpoint_evaluation'],str) or not v['next_checkpoint_evaluation']:
  p.error('certificate schema is invalid or lacks honest unresolved gaps')
 for b in v['benchmarks']:
  if not isinstance(b,dict) or set(b)!={'benchmark_id','benchmark_version','split_sha256','protocol_sha256','command_sha256','result'} or not isinstance(b['benchmark_id'],str) or not b['benchmark_id'] or not isinstance(b['benchmark_version'],str) or not b['benchmark_version'] or any(not SHA.fullmatch(b[k]) for k in ('split_sha256','protocol_sha256','command_sha256')) or b['result'] not in ('PREFLIGHT_ONLY','NOT_EXECUTABLE_NO_OWNED_CHECKPOINT','NON_CLAIM_RAW_FORWARD'):
   p.error('certificate benchmark record is invalid')
 a.output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=a.output.parent,delete=False)as h:json.dump({'result':'PREFLIGHT_ONLY','certificate_sha256':__import__('hashlib').sha256(a.certificate.read_bytes()).hexdigest(),'benchmark_count':len(v['benchmarks'])},h,sort_keys=True);h.write('\n');t=h.name
 os.replace(t,a.output)
if __name__=='__main__':main()
