# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib, json, subprocess, sys, tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_text_exact.py'
def test_scores_only_predictions_bound_to_frozen_text_manifest():
 with tempfile.TemporaryDirectory() as temporary:
  root=Path(temporary);references=root/'references';predictions=root/'predictions';manifest=root/'manifest';output=root/'score'
  references.write_text('{"id":"t1","answer":"yes"}\n')
  manifest.write_text(json.dumps({'result':'PREFLIGHT_ONLY','benchmark_id':'local-text','benchmark_version':'1','references_sha256':hashlib.sha256(references.read_bytes()).hexdigest(),'checkpoint_manifest_sha256':'a'*64,'model_config_sha256':'b'*64,'split_sha256':'e'*64,'protocol_sha256':'f'*64}))
  predictions.write_text(json.dumps({'schema_version':'ember-owned-predictions-v1','claim_status':'NON_ADMISSIBLE_RAW_PREDICTIONS','checkpoint_manifest_sha256':'a'*64,'model_config_sha256':'b'*64,'tokenizer_sha256':'c'*64,'inference_implementation_sha256':'d'*64,'benchmark':{'id':'local-text','version':'1','capability':'text','split_sha256':'e'*64,'protocol_sha256':'f'*64},'decoding':{'strategy':'GREEDY_AUTOREGRESSIVE','teacher_forcing':False,'max_new_tokens':1,'temperature':0,'top_p':1,'stop_token_ids':[2]},'rows':[{'id':'t1','input_sha256':'0'*64,'generated_token_ids':[2],'stop_reason':'eos','output':{'kind':'text','text':'yes'}}]}))
  run=subprocess.run([sys.executable,str(SCRIPT),'--frozen-text-manifest',str(manifest),'--references',str(references),'--predictions',str(predictions),'--score-output',str(output)],capture_output=True,text=True)
  assert run.returncode==0,run.stderr

def test_public_raw_forward_wrapper_is_not_a_frozen_local_text_score_input():
    root = Path(__file__).resolve().parents[1]
    wrapper = json.loads((root / "manifests" / "ember-restart-eval-first-shared-raw-forward-v1-predictions.json").read_text(encoding="utf-8"))
    assert wrapper["schema_version"] == "ember-restart-eval-public-predictions-v1"
    assert wrapper["predictions"]["benchmark"]["id"] == "ember-step2-raw-forward"
    assert wrapper["predictions"]["benchmark"]["version"] == "1"
    assert wrapper["predictions"]["benchmark"]["id"] != "local-text"