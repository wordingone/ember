#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Execute a pinned local Spider scorer and write a non-admissible score envelope."""
import argparse, importlib.util, json, math, os, sys, tempfile
from pathlib import Path

def rows(path: Path) -> int:
 return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

def load_evaluator(root: Path):
 source=root/"evaluation.py"
 if not source.is_file(): raise ValueError("pinned Spider evaluation.py is required")
 sys.path.insert(0,str(root))
 try:
  spec=importlib.util.spec_from_file_location("ember_restart_pinned_spider",source)
  if spec is None or spec.loader is None: raise ValueError("could not load pinned Spider evaluation.py")
  module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
 finally: sys.path.pop(0)

def main() -> int:
 p=argparse.ArgumentParser();p.add_argument("--spider-root",required=True,type=Path);p.add_argument("--gold",required=True,type=Path);p.add_argument("--predictions",required=True,type=Path);p.add_argument("--database-dir",required=True,type=Path);p.add_argument("--tables",required=True,type=Path);p.add_argument("--score-output",required=True,type=Path);a=p.parse_args()
 if a.score_output.exists(): p.error("score output must not pre-exist")
 if not all(x.is_file() for x in(a.gold,a.predictions,a.tables)): p.error("gold, predictions, and tables must be files")
 if not a.database_dir.is_dir(): p.error("database directory must exist")
 count=rows(a.predictions)
 if count<=0 or count!=rows(a.gold): p.error("non-empty predictions must exactly cover the frozen gold rows")
 try:
  evaluator=load_evaluator(a.spider_root);foreign_keys=evaluator.build_foreign_key_map_from_json(str(a.tables));captured={};evaluator.print_scores=lambda scores,etype:captured.update(scores);evaluator.evaluate(str(a.gold),str(a.predictions),str(a.database_dir),"match",foreign_keys);exact=captured["all"]["exact"]
 except Exception as exc:
  p.error(f"pinned Spider scorer failed: {exc}")
 if isinstance(exact,bool) or not isinstance(exact,(int,float)) or not math.isfinite(exact): p.error("pinned Spider scorer did not return finite exact match")
 payload={"metrics":{"exact_match":float(exact)},"sample_count":count,"criterion_id":"ember-3b-tool-capability-v1","criterion_result":"FAILED","upstream":"pinned local Spider exact-match scorer"}
 a.score_output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=a.score_output.parent,prefix=a.score_output.name+".",suffix=".tmp",delete=False) as handle:
  handle.write(json.dumps(payload,sort_keys=True)+"\n");temporary=Path(handle.name)
 os.replace(temporary,a.score_output);return 0

if __name__=="__main__": raise SystemExit(main())
