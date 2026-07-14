#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed retention/deletion execution preflight; never admits claims."""
import argparse,json,re
from pathlib import Path
SHA=re.compile(r"^[0-9a-f]{64}$")
def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--manifest",required=True,type=Path);p.add_argument("--output",required=True,type=Path);a=p.parse_args();m=json.loads(a.manifest.read_text(encoding="utf-8"));ret=m.get("retention",{});dele=m.get("deletion",{})
 if not isinstance(ret,dict) or not SHA.fullmatch(ret.get("slice_sha256","")) or not SHA.fullmatch(ret.get("scorer_sha256","")):p.error("retention requires pinned slice and scorer hashes")
 checkpoints=ret.get("checkpoints")
 if not isinstance(checkpoints,list) or len(checkpoints)<2 or any(not isinstance(x,str) or not SHA.fullmatch(x) for x in checkpoints) or len(set(checkpoints))!=len(checkpoints):p.error("retention requires two distinct ordered checkpoint hashes")
 if not isinstance(dele,dict) or dele.get("status")!="NOT_APPLICABLE_NO_PROMOTED_MECHANISM":p.error("deletion requires explicit not-applicable status until a promoted mechanism exists")
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps({"result":"PREFLIGHT_ONLY","admission":"NOT_ELIGIBLE","retention_checkpoint_count":len(checkpoints),"deletion_status":dele["status"]},sort_keys=True)+"\n",encoding="utf-8");return 0
if __name__=="__main__":raise SystemExit(main())
