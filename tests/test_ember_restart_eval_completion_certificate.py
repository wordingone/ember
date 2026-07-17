# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_completion_certificate.py'
def test_validates_honest_checkpoint_bound_completion_certificate():
 with tempfile.TemporaryDirectory()as temporary:
  root=Path(temporary);certificate=root/'certificate';output=root/'validated'
  certificate.write_text(json.dumps({'schema_version':'ember-restart-eval-completion-certificate-v1','goal_id':'EMBER-02','workstream_id':'EMBER-02C','checkpoint_manifest_sha256':'a'*64,'evaluator_commit':'b'*40,'benchmarks':[{ 'family': family, 'benchmark_id': family, 'benchmark_version':'1','split_sha256':'c'*64,'protocol_sha256':'d'*64,'command_sha256':'e'*64,'result':'PREFLIGHT_ONLY'} for family in ('text','image','audio','reasoning','code','mathematics','sql','files','browser_ui','terminal','structured_tools')],'comparators':[{'class':'open_3b','identity':'candidate','command_sha256':'f'*64,'result':'PREFLIGHT_ONLY'}],'resource_receipts':[{'kind':'disk-budget','receipt_sha256':'0'*64}],'honest_unresolved_gaps':['v3 checkpoint unavailable'],'next_checkpoint_evaluation':'consume next corrected v3 checkpoint'}))
  result=subprocess.run([sys.executable,str(SCRIPT),'validate',str(certificate),'--output',str(output)],capture_output=True,text=True)
  assert result.returncode==0,result.stderr
  assert json.loads(output.read_text())['result']=='PREFLIGHT_ONLY'


def test_rejects_malformed_comparator_or_resource_receipt_records():
 with tempfile.TemporaryDirectory() as temporary:
  root=Path(temporary); certificate=root/'certificate'; output=root/'validated'
  base={'schema_version':'ember-restart-eval-completion-certificate-v1','goal_id':'EMBER-02','workstream_id':'EMBER-02C','checkpoint_manifest_sha256':'a'*64,'evaluator_commit':'b'*40,'benchmarks':[{ 'family': family, 'benchmark_id': family, 'benchmark_version':'1','split_sha256':'c'*64,'protocol_sha256':'d'*64,'command_sha256':'e'*64,'result':'PREFLIGHT_ONLY'} for family in ('text','image','audio','reasoning','code','mathematics','sql','files','browser_ui','terminal','structured_tools')],'comparators':[{'class':'open_3b','identity':'candidate','command_sha256':'f'*64,'result':'PREFLIGHT_ONLY'}],'resource_receipts':[{'kind':'disk-budget','receipt_sha256':'0'*64}],'honest_unresolved_gaps':['awaiting comparator execution'],'next_checkpoint_evaluation':'run frozen comparators'}
  for key, invalid in (('comparators',[{'class':'open_3b','identity':'candidate'}]),('resource_receipts',[{'kind':'disk-budget'}])):
   payload=dict(base); payload[key]=invalid; certificate.write_text(json.dumps(payload))
   result=subprocess.run([sys.executable,str(SCRIPT),'validate',str(certificate),'--output',str(output)],capture_output=True,text=True)
   assert result.returncode != 0
   assert not output.exists()


def test_public_certificate_enumerates_current_matrix_and_validates():
    root = Path(__file__).resolve().parents[1]
    certificate = root / "manifests" / "ember-restart-eval-completion-certificate-v1.json"
    with tempfile.TemporaryDirectory() as temporary:
        result = subprocess.run([sys.executable, str(SCRIPT), "validate", str(certificate), "--output", str(Path(temporary) / "validated")], capture_output=True, text=True)
    value = json.loads(certificate.read_text(encoding="utf-8"))
    assert value["checkpoint_manifest_sha256"] == "bf20f05018991eb611b0623edd50a00ec30639da2f8ccae646f6962f152a2a2b"
    assert {row["family"] for row in value["benchmarks"]} == {"text", "image", "audio", "reasoning", "code", "mathematics", "sql", "files", "browser_ui", "terminal", "structured_tools"}
