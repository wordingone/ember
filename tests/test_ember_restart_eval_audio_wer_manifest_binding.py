# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_audio_wer.py'
def test_scores_only_transcripts_bound_to_frozen_audio_manifest():
 with tempfile.TemporaryDirectory() as temporary:
  root=Path(temporary);references=root/'references';predictions=root/'predictions';manifest=root/'manifest';output=root/'score'
  references.write_text('{"id":"a","transcript":"one two"}\n');predictions.write_text('{"id":"a","transcript":"one two"}\n')
  manifest.write_text(json.dumps({'result':'PREFLIGHT_ONLY','benchmark_id':'local-audio-wer','benchmark_version':'1','references_sha256':hashlib.sha256(references.read_bytes()).hexdigest()}))
  run=subprocess.run([sys.executable,str(SCRIPT),'--frozen-audio-manifest',str(manifest),'--references',str(references),'--predictions',str(predictions),'--score-output',str(output)],capture_output=True,text=True)
  assert run.returncode==0,run.stderr
