# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_audio_wer.py'
def test_rejects_audio_reference_substitution_before_output():
 with tempfile.TemporaryDirectory()as temporary:
  root=Path(temporary);bound=root/'bound';references=root/'references';predictions=root/'predictions';manifest=root/'manifest';output=root/'score'
  bound.write_text('{"id":"a","transcript":"one"}\n');references.write_text('{"id":"a","transcript":"two"}\n');predictions.write_text('{"id":"a","transcript":"two"}\n')
  manifest.write_text(json.dumps({'result':'PREFLIGHT_ONLY','benchmark_id':'local-audio-wer','benchmark_version':'1','references_sha256':hashlib.sha256(bound.read_bytes()).hexdigest()}))
  result=subprocess.run([sys.executable,str(SCRIPT),'--frozen-audio-manifest',str(manifest),'--references',str(references),'--predictions',str(predictions),'--score-output',str(output)],capture_output=True,text=True)
  assert result.returncode!=0 and not output.exists()
