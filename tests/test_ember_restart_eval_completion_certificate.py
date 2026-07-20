# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_completion_certificate.py'
def test_validates_honest_checkpoint_bound_completion_certificate():
 with tempfile.TemporaryDirectory()as temporary:
  root=Path(temporary);certificate=root/'certificate';output=root/'validated'
  certificate.write_text(json.dumps({'schema_version':'ember-restart-eval-completion-certificate-v1','goal_id':'EMBER-02','workstream_id':'EMBER-02C','checkpoint_manifest_sha256':'a'*64,'evaluator_commit':'b'*40,'benchmarks':[{'benchmark_id':'local-text','benchmark_version':'1','split_sha256':'c'*64,'protocol_sha256':'d'*64,'command_sha256':'e'*64,'result':'PREFLIGHT_ONLY'}],'comparators':[],'resource_receipts':[],'honest_unresolved_gaps':['v3 checkpoint unavailable'],'next_checkpoint_evaluation':'consume next corrected v3 checkpoint'}))
  result=subprocess.run([sys.executable,str(SCRIPT),'validate',str(certificate),'--output',str(output)],capture_output=True,text=True)
  assert result.returncode==0,result.stderr
  assert json.loads(output.read_text())['result']=='PREFLIGHT_ONLY'
