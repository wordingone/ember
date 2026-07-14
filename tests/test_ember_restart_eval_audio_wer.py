# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json, subprocess, sys, tempfile
from pathlib import Path

SCRIPT=Path(__file__).resolve().parents[1]/"scripts"/"ember_restart_eval_audio_wer.py"

def test_scores_checkpoint_transcripts_against_frozen_private_references():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp); references=root/"references.jsonl";predictions=root/"predictions.jsonl";score=root/"score.json"
  references.write_text('{"id":"a","transcript":"one two"}\n{"id":"b","transcript":"three"}\n',encoding="utf-8")
  predictions.write_text('{"id":"a","transcript":"one too"}\n{"id":"b","transcript":"three"}\n',encoding="utf-8")
  r=subprocess.run([sys.executable,str(SCRIPT),"--references",str(references),"--predictions",str(predictions),"--score-output",str(score)],text=True,capture_output=True,check=False)
  assert r.returncode==0,r.stderr
  assert json.loads(score.read_text(encoding="utf-8"))=={"criterion_id":"ember-3b-audio-capability-v1","criterion_result":"FAILED","metrics":{"word_error_rate":1/3},"sample_count":2,"upstream":"deterministic local word-error-rate scorer"}
