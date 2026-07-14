#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import argparse,json,re
from pathlib import Path
SHA=re.compile(r'^[0-9a-f]{64}$')
def main():
 p=argparse.ArgumentParser();p.add_argument('--manifest',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args();m=json.loads(a.manifest.read_text());ret=m.get('retention',{});dele=m.get('deletion',{})
 if not isinstance(ret,dict) or not SHA.fullmatch(ret.get('slice_sha256','')) or not SHA.fullmatch(ret.get('scorer_sha256','')):p.error('retention requires pinned slice and scorer hashes')
 checkpoints=ret.get('checkpoints')
 if not isinstance(checkpoints,list) or len(checkpoints)<2: p.error('retention requires two ordered checkpoint records')
 previous=-1;seen=set()
 for record in checkpoints:
  if not isinstance(record,dict) or set(record)!={'sha256','step'} or not isinstance(record.get('sha256'),str) or not SHA.fullmatch(record['sha256']) or not isinstance(record.get('step'),int) or isinstance(record['step'],bool) or record['step']<=previous or record['sha256'] in seen:p.error('retention checkpoints require distinct hashes and strictly increasing integer steps')
  previous=record['step'];seen.add(record['sha256'])
 if not isinstance(dele,dict) or dele.get('status')!='NOT_APPLICABLE_NO_PROMOTED_MECHANISM':p.error('deletion requires explicit not-applicable status until a promoted mechanism exists')
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps({'result':'PREFLIGHT_ONLY','admission':'NOT_ELIGIBLE','retention_checkpoint_count':len(checkpoints),'deletion_status':dele['status']},sort_keys=True)+'\n');return 0
if __name__=='__main__':main()
