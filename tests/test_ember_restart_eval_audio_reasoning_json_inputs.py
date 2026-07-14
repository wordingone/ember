# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json, subprocess, sys, tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_audio_and_reasoning_scorers_accept_central_json_list_predictions():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp)
  for name,field in (("audio_wer","transcript"),("reasoning_exact","answer")):
   references=root/f"{name}-references.json";predictions=root/f"{name}-predictions.json";score=root/f"{name}-score.json";references.write_text(json.dumps([{"id":"x",field:"ok"}]),encoding="utf-8");predictions.write_text(json.dumps([{"id":"x",field:"ok"}]),encoding="utf-8")
   r=subprocess.run([sys.executable,str(ROOT/"scripts"/f"ember_restart_eval_{name}.py"),"--references",str(references),"--predictions",str(predictions),"--score-output",str(score)],text=True,capture_output=True,check=False)
   assert r.returncode==0,r.stderr
