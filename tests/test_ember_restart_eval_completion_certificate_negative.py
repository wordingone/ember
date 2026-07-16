# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_completion_certificate.py'
def test_rejects_certificate_with_measured_benchmark_or_no_honest_gap():
 with tempfile.TemporaryDirectory()as temporary:
  root=Path(temporary);certificate=root/'certificate';output=root/'output'
  certificate.write_text(json.dumps({'schema_version':'ember-restart-eval-completion-certificate-v1','goal_id':'EMBER-02','workstream_id':'EMBER-02C','checkpoint_manifest_sha256':'a'*64,'evaluator_commit':'b'*40,'benchmarks':[{'benchmark_id':'x','benchmark_version':'1','split_sha256':'c'*64,'protocol_sha256':'d'*64,'command_sha256':'e'*64,'result':'MEASURED'}],'comparators':[],'resource_receipts':[],'honest_unresolved_gaps':[],'next_checkpoint_evaluation':'x'}))
  result=subprocess.run([sys.executable,str(SCRIPT),'validate',str(certificate),'--output',str(output)],capture_output=True,text=True)
  assert result.returncode!=0 and not output.exists()


def test_rejects_certificate_that_omits_required_family():
 with tempfile.TemporaryDirectory() as temporary:
  root=Path(temporary);certificate=root/'certificate';output=root/'output';families=('text','image','audio','reasoning','code','mathematics','sql','files','browser_ui','terminal')
  certificate.write_text(json.dumps({'schema_version':'ember-restart-eval-completion-certificate-v1','goal_id':'EMBER-02','workstream_id':'EMBER-02C','checkpoint_manifest_sha256':'a'*64,'evaluator_commit':'b'*40,'benchmarks':[{'family':family,'benchmark_id':family,'benchmark_version':'1','split_sha256':'c'*64,'protocol_sha256':'d'*64,'command_sha256':'e'*64,'result':'PREFLIGHT_ONLY'} for family in families],'comparators':[],'resource_receipts':[],'honest_unresolved_gaps':['structured tools missing'],'next_checkpoint_evaluation':'x'}))
  result=subprocess.run([sys.executable,str(SCRIPT),'validate',str(certificate),'--output',str(output)],capture_output=True,text=True)
  assert result.returncode!=0 and not output.exists()

def test_rejects_obsolete_no_owned_checkpoint_disposition():
 with tempfile.TemporaryDirectory() as temporary:
  root=Path(temporary);certificate=root/'certificate';output=root/'output';families=('text','image','audio','reasoning','code','mathematics','sql','files','browser_ui','terminal','structured_tools')
  certificate.write_text(json.dumps({'schema_version':'ember-restart-eval-completion-certificate-v1','goal_id':'EMBER-02','workstream_id':'EMBER-02C','checkpoint_manifest_sha256':'a'*64,'evaluator_commit':'b'*40,'benchmarks':[{ 'family':family,'benchmark_id':family,'benchmark_version':'1','split_sha256':'c'*64,'protocol_sha256':'d'*64,'command_sha256':'e'*64,'result':'NOT_EXECUTABLE_NO_OWNED_CHECKPOINT' if family=='text' else 'PREFLIGHT_ONLY'} for family in families],'comparators':[],'resource_receipts':[],'honest_unresolved_gaps':['specialists untrained'],'next_checkpoint_evaluation':'run frozen suite'}))
  result=subprocess.run([sys.executable,str(SCRIPT),'validate',str(certificate),'--output',str(output)],capture_output=True,text=True)
  assert result.returncode!=0 and not output.exists()