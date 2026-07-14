# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json, subprocess, sys, tempfile
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ember_restart_eval_spider.py"

def test_converts_central_json_list_predictions_to_private_spider_sql_lines():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);spider=root/"spider";spider.mkdir();gold=root/"gold.sql";predictions=root/"predictions.json";tables=root/"tables.json";db=root/"database";db.mkdir();score=root/"score.json"
  gold.write_text("select 1\tdb\n",encoding="utf-8");predictions.write_text(json.dumps([{"index":0,"sql":"select 1"}]),encoding="utf-8");tables.write_text("[]",encoding="utf-8")
  (spider/"evaluation.py").write_text("def build_foreign_key_map_from_json(path): return {}\ndef evaluate(gold,pred,db,etype,kmaps):\n assert open(pred).read()=='select 1\\n'\n print_scores({'all':{'count':1,'exact':1.0}},etype)\n",encoding="utf-8")
  r=subprocess.run([sys.executable,str(SCRIPT),"--spider-root",str(spider),"--gold",str(gold),"--predictions",str(predictions),"--database-dir",str(db),"--tables",str(tables),"--score-output",str(score)],text=True,capture_output=True,check=False)
  assert r.returncode==0,r.stderr
  assert json.loads(score.read_text(encoding="utf-8"))["sample_count"]==1
