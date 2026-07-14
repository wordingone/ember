# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path
SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'ember_restart_eval_checkpoint_consumer.py'
def _sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def test_verifies_each_declared_checkpoint_shard_and_emits_identity_receipt():
 with tempfile.TemporaryDirectory()as tmp:
  r=Path(tmp);s=r/'shared.pt';s.write_bytes(b'owned-bytes');m=r/'checkpoint-manifest.json';o=r/'receipt.json';m.write_text(json.dumps({'schema_version':'ember-sparse-checkpoint-v2','model_config_sha256':'a'*64,'shards':[{'path':'shared.pt','role':'shared_model_and_optimizer','bytes':11,'sha256':_sha(s)}]}));x=subprocess.run([sys.executable,str(SCRIPT),'verify',str(m),'--output',str(o)],capture_output=True,text=True);assert x.returncode==0,x.stderr;p=json.loads(o.read_text());assert p['result']=='VERIFIED_CHECKPOINT_INPUT' and p['checkpoint_manifest_sha256']==_sha(m) and p['goal_id']=='EMBER-02'
