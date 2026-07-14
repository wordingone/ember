#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Validate central-schema evaluator inputs without emitting a claim-bearing receipt."""
import argparse,hashlib,json,math,os,tempfile
from pathlib import Path
CAPABILITIES=("text","image","audio","reasoning","tool")
def sha256(path:Path)->str:return hashlib.sha256(path.read_bytes()).hexdigest()
def main()->int:
 p=argparse.ArgumentParser();p.add_argument("--capability",required=True,choices=CAPABILITIES);p.add_argument("--checkpoint-manifest",required=True,type=Path);p.add_argument("--benchmark-id",required=True);p.add_argument("--benchmark-version",required=True);p.add_argument("--split-artifact",required=True,type=Path);p.add_argument("--harness-artifact",required=True,type=Path);p.add_argument("--protocol-artifact",required=True,type=Path);p.add_argument("--raw-predictions",required=True,type=Path);p.add_argument("--result-artifact",required=True,type=Path);p.add_argument("--output",required=True,type=Path);a=p.parse_args()
 if not a.benchmark_id.strip() or not a.benchmark_version.strip():p.error("benchmark id and version must be non-empty")
 predictions=json.loads(a.raw_predictions.read_text(encoding="utf-8"));score=json.loads(a.result_artifact.read_text(encoding="utf-8"));expected=f"ember-3b-{a.capability}-capability-v1"
 if not isinstance(predictions,list) or not predictions:p.error("raw predictions must be a non-empty list")
 if not isinstance(score,dict) or score.get("criterion_id")!=expected or score.get("criterion_result") not in("PASSED","FAILED"):p.error("evaluator score artifact must explicitly provide the pinned criterion")
 count=score.get("sample_count")
 if not isinstance(count,int) or isinstance(count,bool) or count!=len(predictions):p.error("evaluator sample_count must be an exact integer match for raw predictions")
 metrics=score.get("metrics")
 if not isinstance(metrics,dict) or not metrics or any(isinstance(v,bool)or not isinstance(v,(int,float))or not math.isfinite(v)for v in metrics.values()):p.error("score artifact must contain non-empty finite numeric metrics")
 payload={"result":"PREFLIGHT_ONLY","admission":"NOT_ELIGIBLE","capability":a.capability,"subject_checkpoint_sha256":sha256(a.checkpoint_manifest),"benchmark_id":a.benchmark_id,"benchmark_version":a.benchmark_version,"split_sha256":sha256(a.split_artifact),"harness_sha256":sha256(a.harness_artifact),"protocol_sha256":sha256(a.protocol_artifact),"predictions_sha256":sha256(a.raw_predictions),"score_artifact_sha256":sha256(a.result_artifact),"sample_count":count,"metrics":metrics,"criterion_id":expected,"criterion_result":score["criterion_result"]}
 a.output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=a.output.parent,prefix=a.output.name+".",suffix=".tmp",delete=False)as h:h.write(json.dumps(payload,sort_keys=True)+"\n");temp=Path(h.name)
 os.replace(temp,a.output);return 0
if __name__=="__main__":raise SystemExit(main())
