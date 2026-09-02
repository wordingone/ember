# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
ROOT=next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
def test_audio_and_reasoning_scorers_accept_central_json_list_predictions():
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp)
  for name,field,benchmark,argument in (('audio_wer','transcript','local-audio-wer','--frozen-audio-manifest'),('reasoning_exact','answer','local-reasoning','--frozen-reasoning-manifest')):
   references=root/f'{name}-references.json';predictions=root/f'{name}-predictions.json';manifest=root/f'{name}-manifest.json';score=root/f'{name}-score.json';references.write_text(json.dumps([{'id':'x',field:'ok'}]));predictions.write_text(json.dumps([{'id':'x',field:'ok'}]));manifest.write_text(json.dumps({'result':'PREFLIGHT_ONLY','benchmark_id':benchmark,'benchmark_version':'1','references_sha256':hashlib.sha256(references.read_bytes()).hexdigest()}))
   r=subprocess.run([sys.executable,str(ROOT/'scripts'/f'ember_restart_eval_{name}.py'),argument,str(manifest),'--references',str(references),'--predictions',str(predictions),'--score-output',str(score)],text=True,capture_output=True);assert r.returncode==0,r.stderr
