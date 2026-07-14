# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib,json,subprocess,sys,tempfile
from pathlib import Path

SCRIPT=Path(__file__).parents[1]/'scripts'/'ember_restart_eval_historical_v2_input.py'
ROLES={'shared.pt':'shared_model_and_optimizer','replay-state.pt':'replay_state','expert-vision.pt':'expert_vision','expert-audio.pt':'expert_audio','expert-reasoning.pt':'expert_reasoning','expert-tool.pt':'expert_tool'}

def write_v2(root):
 records=[]
 for name,role in ROLES.items():
  path=root/name;path.write_bytes(name.encode());records.append({'path':name,'role':role,'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
 manifest={'schema_version':'ember-sparse-checkpoint-v2','launch_seed':82,'rng_state_sha256':{'cpu':'a'*64,'cuda':'b'*64},'data_cursor':{'global_step':1},'model_config_sha256':'c'*64,'contract_sha256':'d'*64,'active_expert_ids':['tool'],'expert_genesis_sha256':{name:format(index,'x')*64 for index,name in enumerate(('vision','audio','reasoning','tool'),1)},'expert_checkpoint_sha256':{name:next(x['sha256'] for x in records if x['path']==f'expert-{name}.pt') for name in ('vision','audio','reasoning','tool')},'shared_optimizer_shard_sha256':records[0]['sha256'],'shards':records}
 path=root/'checkpoint-manifest.json';path.write_text(json.dumps(manifest));digest=hashlib.sha256(path.read_bytes()).hexdigest();custody={'schema_version':'ember-restart-hardlink-custody-v1','result':'HISTORICAL_ONLY_V2','checkpoint_manifest_sha256':digest,'source_schema_version':'ember-sparse-checkpoint-v2','files':[{'name':path.name,'sha256':digest,'bytes':path.stat().st_size}]+[{'name':x['path'],'sha256':x['sha256'],'bytes':x['bytes']} for x in records]};receipt=root/'custody.json';receipt.write_text(json.dumps(custody));return path,receipt

def test_validates_historical_v2_custody_without_current_rung_credit():
 with tempfile.TemporaryDirectory()as temporary:
  root=Path(temporary);manifest,custody=write_v2(root);output=root/'output.json';completed=subprocess.run([sys.executable,str(SCRIPT),'--manifest',str(manifest),'--custody-receipt',str(custody),'--output',str(output)],capture_output=True,text=True)
  assert completed.returncode==0,completed.stderr
  assert json.loads(output.read_text())['result']=='HISTORICAL_V2_INPUT_ONLY'

def test_rejects_custody_manifest_hash_mismatch_without_output():
 with tempfile.TemporaryDirectory()as temporary:
  root=Path(temporary);manifest,custody=write_v2(root);data=json.loads(custody.read_text());data['checkpoint_manifest_sha256']='0'*64;custody.write_text(json.dumps(data));output=root/'output.json';completed=subprocess.run([sys.executable,str(SCRIPT),'--manifest',str(manifest),'--custody-receipt',str(custody),'--output',str(output)],capture_output=True,text=True)
  assert completed.returncode!=0 and not output.exists()
