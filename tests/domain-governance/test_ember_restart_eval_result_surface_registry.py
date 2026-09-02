# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json,subprocess,sys,tempfile
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_result_surface.py'

def test_rejects_self_asserted_measurement_when_registry_and_receipt_binding_do_not_admit_it():
 with tempfile.TemporaryDirectory()as tmp:
  root=Path(tmp);source=root/'self-asserted.json';manifest=root/'admission.json';registry=root/'trusted.json';out=root/'surface.md'
  source.write_text(json.dumps({'result':'MEASURED','admission':'ADMITTED','checkpoint_status':'OWNED_ADMITTED','capability':'audio'}))
  manifest.write_text(json.dumps({'stage':'OWNED_ADMITTED','evaluations':[]}));registry.write_text(json.dumps({'schema_version':'ember-trusted-verifiers-v1','verifiers':[]}))
  result=subprocess.run([sys.executable,str(SCRIPT),'--input',str(source),'--admission-manifest',str(manifest),'--trusted-verifier-registry',str(registry),'--output',str(out)],capture_output=True,text=True)
  assert result.returncode==0,result.stderr
  assert 'NOT CLAIM-BEARING' in out.read_text() and 'MEASURED CAPABILITY' not in out.read_text()
