# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json, subprocess, sys, tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_execution_preflight.py'
def test_rejects_unbound_bare_prediction_list_after_canonical_contract_lands():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);files=[root/x for x in ('checkpoint','split','harness','protocol')]
  for x in files:x.write_text(x.name)
  raw=root/'raw';score=root/'score';out=root/'out';raw.write_text('[{"id":"x"}]');score.write_text(json.dumps({'criterion_id':'ember-3b-text-capability-v1','criterion_result':'FAILED','sample_count':1,'metrics':{'accuracy':0.0}}))
  r=subprocess.run([sys.executable,str(SCRIPT),'--capability','text','--checkpoint-manifest',str(files[0]),'--benchmark-id','x','--benchmark-version','v1','--split-artifact',str(files[1]),'--harness-artifact',str(files[2]),'--protocol-artifact',str(files[3]),'--raw-predictions',str(raw),'--result-artifact',str(score),'--output',str(out)],capture_output=True,text=True);assert r.returncode!=0 and not out.exists()
