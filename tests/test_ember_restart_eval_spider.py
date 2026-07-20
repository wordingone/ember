# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json, subprocess, sys, tempfile
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ember_restart_eval_spider.py"

def test_executes_local_spider_scorer_and_derives_coverage_from_predictions():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp); spider=root/"spider"; spider.mkdir(); predictions=root/"predictions.sql"; gold=root/"gold.sql"; tables=root/"tables.json"; db=root/"database"; db.mkdir(); score=root/"score.json"
  predictions.write_text("select 1\ndrop table nope\n",encoding="utf-8");gold.write_text("select 1\tdb\nselect 2\tdb\n",encoding="utf-8");tables.write_text("[]",encoding="utf-8")
  (spider/"evaluation.py").write_text("def build_foreign_key_map_from_json(path): return {}\ndef evaluate(gold,pred,db,etype,kmaps):\n print_scores({'all':{'count':2,'exact':0.5}},etype)\n",encoding="utf-8")
  r=subprocess.run([sys.executable,str(SCRIPT),"--spider-root",str(spider),"--gold",str(gold),"--predictions",str(predictions),"--database-dir",str(db),"--tables",str(tables),"--score-output",str(score)],text=True,capture_output=True,check=False)
  assert r.returncode==0,r.stderr
  payload=json.loads(score.read_text(encoding="utf-8"))
  assert payload["metrics"]=={"exact_match":0.5}
  assert payload["sample_count"]==2
  assert payload["criterion_id"]=="ember-3b-tool-capability-v1"
  assert payload["criterion_result"]=="FAILED"

def test_upstream_scorer_exception_fails_closed_without_score_output():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp); spider=root/"spider"; spider.mkdir(); predictions=root/"predictions.sql"; gold=root/"gold.sql"; tables=root/"tables.json"; db=root/"database"; db.mkdir(); score=root/"score.json"
  predictions.write_text("select 1\n",encoding="utf-8");gold.write_text("select 1\tdb\n",encoding="utf-8");tables.write_text("[]",encoding="utf-8")
  (spider/"evaluation.py").write_text("def build_foreign_key_map_from_json(path): return {}\ndef evaluate(*args): raise RuntimeError('bad upstream')\n",encoding="utf-8")
  r=subprocess.run([sys.executable,str(SCRIPT),"--spider-root",str(spider),"--gold",str(gold),"--predictions",str(predictions),"--database-dir",str(db),"--tables",str(tables),"--score-output",str(score)],text=True,capture_output=True,check=False)
  assert r.returncode!=0 and "pinned Spider scorer failed" in r.stderr and not score.exists()
