# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json, subprocess, sys, tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_text_fixture.py'
def test_scores_frozen_text_rows_locally():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp); f=root/'f.json';p=root/'p.json';o=root/'o.json';f.write_text(json.dumps([{'id':'a','answer':'yes'},{'id':'b','answer':'no'}]));p.write_text(json.dumps({'a':'yes','b':'wrong'}))
  r=subprocess.run([sys.executable,str(SCRIPT),'--fixture',str(f),'--predictions',str(p),'--output',str(o)],text=True,capture_output=True,check=False);assert r.returncode==0,r.stderr;assert json.loads(o.read_text())=={'benchmark_id':'frozen-text-fixture-v1','correct':1,'rows':[{'id':'a','correct':True},{'id':'b','correct':False}],'total':2}
