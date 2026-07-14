#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail closed unless target and pinned open comparator share evaluator pins."""
import argparse,json,re
from pathlib import Path
FIELDS=("capability","benchmark_id","benchmark_version","split_sha256","harness_sha256","protocol_sha256")
def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--target",required=True,type=Path);p.add_argument("--comparator",required=True,type=Path);p.add_argument("--output",required=True,type=Path);a=p.parse_args()
 if a.output.exists():p.error("output must not pre-exist")
 try:
  target=json.loads(a.target.read_text(encoding="utf-8"));comparator=json.loads(a.comparator.read_text(encoding="utf-8"))
 except (OSError,json.JSONDecodeError)as error:
  p.error(f"invalid preflight JSON: {error}")
 for name,payload in (("target",target),("comparator",comparator)):
  if not isinstance(payload,dict) or payload.get("result")!="PREFLIGHT_ONLY" or payload.get("admission")!="NOT_ELIGIBLE":p.error(f"{name} must be a non-admissible evaluator preflight")
  if not isinstance(payload.get("subject_checkpoint_sha256"),str) or not re.fullmatch(r"[0-9a-f]{64}",payload["subject_checkpoint_sha256"]):p.error(f"{name} requires a checkpoint hash")
 if comparator.get("subject_kind")!="open_comparator" or comparator.get("comparator_size_class") not in ("open_3b","open_27b_or_31b") or not isinstance(comparator.get("comparator_revision"),str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}",comparator["comparator_revision"]):p.error("comparator requires pinned open identity and required size class")
 if target["subject_checkpoint_sha256"]==comparator["subject_checkpoint_sha256"]:p.error("comparator must be a different checkpoint")
 for field in FIELDS:
  if target.get(field)!=comparator.get(field) or not target.get(field):p.error(f"target and comparator must share {field}")
 a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps({"result":"COMPARISON_PREFLIGHT","admission":"NOT_ELIGIBLE",**{field:target[field] for field in FIELDS[:3]}},sort_keys=True)+"\n",encoding="utf-8");return 0
if __name__=="__main__":raise SystemExit(main())
