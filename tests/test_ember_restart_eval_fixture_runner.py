# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_fixture_runner.py'
def test_scores_all_five_capabilities_deterministically():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp); fixture=root/'fixture.json'; out=root/'out.json'; fixture.write_text(json.dumps([{'id':c,'capability':c,'expected':'x','actual':'x'} for c in ('text','image','audio','reasoning','tool')]),encoding='utf-8')
  r=subprocess.run([sys.executable,str(SCRIPT),'--fixture',str(fixture),'--output',str(out)],text=True,capture_output=True,check=False); assert r.returncode==0,r.stderr; assert json.loads(out.read_text())=={'correct':5,'rows':[{'id':c,'capability':c,'correct':True} for c in ('text','image','audio','reasoning','tool')],'total':5}
