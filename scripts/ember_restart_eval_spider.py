#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Execute a pinned local Spider scorer and write a non-admissible score envelope."""
import argparse, importlib.util, json, math, os, sys, tempfile
from pathlib import Path

def rows(path: Path) -> int:
 return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

def sql_lines(path: Path) -> list[str]:
 raw=path.read_text(encoding="utf-8")
 try: value=json.loads(raw)
 except json.JSONDecodeError: return [line for line in raw.splitlines() if line.strip()]
 if not isinstance(value,list) or not value: raise ValueError("Spider predictions must be non-empty SQL lines or a JSON list")
 result=[]
 for index,row in enumerate(value):
  if not isinstance(row,dict) or row.get("index")!=index or not isinstance(row.get("sql"),str): raise ValueError("Spider JSON predictions require contiguous index and sql")
  result.append(row["sql"])
 return result

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
 try: predictions=sql_lines(a.predictions)
 except (OSError,ValueError,json.JSONDecodeError) as exc:p.error(f"invalid Spider predictions: {exc}")
 if len(predictions)!=rows(a.gold): p.error("non-empty predictions must exactly cover the frozen gold rows")
 with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=a.predictions.parent,prefix=a.predictions.name+".",suffix=".spider.tmp",delete=False)as handle:handle.write("\n".join(predictions)+"\n");temporary=Path(handle.name)
 try:
  evaluator=load_evaluator(a.spider_root);foreign_keys=evaluator.build_foreign_key_map_from_json(str(a.tables));captured={};evaluator.print_scores=lambda scores,etype:captured.update(scores);evaluator.evaluate(str(a.gold),str(temporary),str(a.database_dir),"match",foreign_keys);exact=captured["all"]["exact"]
 except Exception as exc: p.error(f"pinned Spider scorer failed: {exc}")
 finally: temporary.unlink(missing_ok=True)
 if isinstance(exact,bool) or not isinstance(exact,(int,float)) or not math.isfinite(exact): p.error("pinned Spider scorer did not return finite exact match")
 payload={"metrics":{"exact_match":float(exact)},"sample_count":len(predictions),"criterion_id":"ember-3b-tool-capability-v1","criterion_result":"FAILED","upstream":"pinned local Spider exact-match scorer"}
 a.score_output.parent.mkdir(parents=True,exist_ok=True)
 with tempfile.NamedTemporaryFile("w",encoding="utf-8",dir=a.score_output.parent,prefix=a.score_output.name+".",suffix=".tmp",delete=False) as handle:handle.write(json.dumps(payload,sort_keys=True)+"\n");temporary=Path(handle.name)
 os.replace(temporary,a.score_output);return 0

if __name__=="__main__": raise SystemExit(main())
