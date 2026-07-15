#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Score text predictions only against a hash-bound frozen reference manifest."""
import argparse, hashlib, json, os, re, tempfile
from pathlib import Path

HASH=re.compile(r"[0-9a-f]{64}")
def _sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read_rows(path: Path) -> dict[str,str]:
 raw=path.read_text(encoding="utf-8")
 try: parsed=json.loads(raw); values=parsed if isinstance(parsed,list) else [parsed]
 except json.JSONDecodeError: values=[json.loads(line) for line in raw.splitlines() if line.strip()]
 rows={}
 for value in values:
  if not isinstance(value,dict) or not isinstance(value.get("id"),str) or not value["id"] or not isinstance(value.get("answer"),str) or value["id"] in rows: raise ValueError("each row needs a unique non-empty id and answer")
  rows[value["id"]]=value["answer"]
 if not rows: raise ValueError("rows must be non-empty")
 return rows
def main() -> int:
 p=argparse.ArgumentParser();p.add_argument("--frozen-text-manifest",required=True,type=Path);p.add_argument("--references",required=True,type=Path);p.add_argument("--predictions",required=True,type=Path);p.add_argument("--score-output",required=True,type=Path);a=p.parse_args()
 if a.score_output.exists(): p.error("score output must not pre-exist")
 try:
  manifest=json.loads(a.frozen_text_manifest.read_text(encoding="utf-8"));references=read_rows(a.references);predictions=read_rows(a.predictions)
  if not isinstance(manifest,dict) or manifest.get("result")!="PREFLIGHT_ONLY" or manifest.get("benchmark_id")!="local-text" or manifest.get("benchmark_version")!="1" or manifest.get("references_sha256")!=_sha(a.references) or not HASH.fullmatch(manifest.get("references_sha256","")): raise ValueError("frozen text manifest does not bind the supplied references")
 except (OSError,ValueError,json.JSONDecodeError) as exc:p.error(f"invalid local answer artifacts: {exc}")
 if references.keys()!=predictions.keys(): p.error("predictions must exactly cover the frozen reference ids")
 correct=sum(references[key]==predictions[key] for key in references)
 payload={"criterion_id":"ember-3b-text-capability-v1","criterion_result":"FAILED","metrics":{"exact_match":correct/len(references)},"sample_count":len(references),"references_sha256":_sha(a.references),"frozen_text_manifest_sha256":_sha(a.frozen_text_manifest),"upstream":"deterministic local frozen-answer scorer"}
 a.score_output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=a.score_output.parent,delete=False) as handle: handle.write(json.dumps(payload,sort_keys=True)+"\n");temporary=Path(handle.name)
 os.replace(temporary,a.score_output);return 0
if __name__=="__main__": raise SystemExit(main())
