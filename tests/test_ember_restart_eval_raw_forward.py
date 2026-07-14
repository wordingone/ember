# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json,subprocess,sys,tempfile
from pathlib import Path
def test_runner_accepts_valid_tokenizer_probe():
 with tempfile.TemporaryDirectory()as t:
  r=Path(t);tok=r/'t.json';out=r/'o';tok.write_text(json.dumps({'version':'1.0','truncation':None,'padding':None,'added_tokens':[],'normalizer':None,'pre_tokenizer':None,'post_processor':None,'decoder':None,'model':{'type':'WordLevel','vocab':{'x':0},'unk_token':'x'}}));x=subprocess.run([sys.executable,str(Path(__file__).parents[1]/'scripts'/'ember_restart_eval_raw_forward.py'),'--tokenizer',str(tok),'--output',str(out)],capture_output=True);assert x.returncode==0 and out.exists()
