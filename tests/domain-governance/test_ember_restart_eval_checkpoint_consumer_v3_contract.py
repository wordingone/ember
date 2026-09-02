# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import torch

SCRIPT = Path(__file__).parents[1] / "scripts" / "ember_restart_eval_checkpoint_consumer.py"
EXPERTS = ("vision", "audio", "reasoning", "tool")

def _sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def write_v3(root: Path, *, mutate=None) -> Path:
    contract={"name":"paged_8bit_adamw","implementation":"bitsandbytes.optim.PagedAdamW8bit","hyperparameters":{"learning_rate":1e-5},"state_format":"bitsandbytes-paged-8bit-adamw-state-dict-v1"}
    realization={"implementation":contract["implementation"],"implementation_source_sha256":"f"*64,"state_format":contract["state_format"],"optimizer_contract_sha256":hashlib.sha256(json.dumps(contract,sort_keys=True,separators=(",",":")).encode()).hexdigest()}
    cursor={"shard":"owned.json","record_index":1,"global_step":1,"tokens_seen":3};cpu=torch.tensor([1,2],dtype=torch.uint8);cuda=torch.tensor([3,4],dtype=torch.uint8)
    config=root/"config.json";config.write_text(json.dumps({"training":{"optimizer":contract}}),encoding="utf-8")
    shared=root/"shared.pt";torch.save({"model":{},"optimizer":{},"optimizer_contract":contract,"optimizer_realization":realization},shared)
    replay=root/"replay-state.pt";torch.save({"rng_state":{"cpu":cpu,"cuda":cuda},"data_cursor":cursor},replay)
    records=[]
    for shard,role in [(shared,"shared_model_and_optimizer"),(replay,"replay_state")]:records.append({"path":shard.name,"role":role,"bytes":shard.stat().st_size,"sha256":_sha(shard)})
    genesis=root/"genesis";genesis.mkdir();genesis_hashes={}
    for expert in EXPERTS:
        artifact=genesis/f"{expert}.json";artifact.write_text(json.dumps({"schema_version":"ember-expert-genesis-v1","expert":expert}),encoding="utf-8");genesis_hashes[expert]=_sha(artifact)
        shard=root/f"expert-{expert}.pt";torch.save({"expert":expert,"genesis_sha256":genesis_hashes[expert],"model":{}},shard);records.append({"path":shard.name,"role":f"expert_{expert}","bytes":shard.stat().st_size,"sha256":_sha(shard)})
    manifest={"schema_version":"ember-sparse-checkpoint-v3","launch_seed":82,"rng_state_sha256":{"cpu":hashlib.sha256(cpu.numpy().tobytes()).hexdigest(),"cuda":hashlib.sha256(cuda.numpy().tobytes()).hexdigest()},"data_cursor":cursor,"model_config_sha256":_sha(config),"contract_sha256":"d"*64,"active_expert_ids":["tool"],"expert_genesis_sha256":genesis_hashes,"expert_checkpoint_sha256":{name:next(x["sha256"] for x in records if x["path"]==f"expert-{name}.pt") for name in EXPERTS},"shared_optimizer_shard_sha256":records[0]["sha256"],"optimizer_contract":contract,"optimizer_realization":realization,"shards":records}
    manifest["contract_version"]=3
    manifest["architecture_revision"]="ember-sparse-3b-v2"
    manifest["architecture"]={"revision":"ember-sparse-3b-v2","allocated_parameters":3839161856,"unique_parameters":3839161856,"trainable_parameters":3839161856,"served_parameters":3839161856,"active_parameters":1725232640,"episode_trainable_parameters":1725232640,"shared_text_ffn":"always_active_SwiGLU_4H"}
    if mutate: mutate(manifest)
    path=root/"checkpoint-manifest.json";path.write_text(json.dumps(manifest),encoding="utf-8");return path
def invoke(manifest:Path,output:Path): return subprocess.run([sys.executable,str(SCRIPT),"verify",str(manifest),"--model-config",str(manifest.parent/"config.json"),"--output",str(output)],capture_output=True,text=True)
def test_accepts_closed_v3_checkpoint_manifest():
 with tempfile.TemporaryDirectory()as temporary:
  root=Path(temporary);output=root/"receipt.json";completed=invoke(write_v3(root),output);assert completed.returncode==0,completed.stderr;assert json.loads(output.read_text())["shard_count"]==6
def test_rejects_missing_optimizer_contract_before_output():
 with tempfile.TemporaryDirectory()as temporary:
  root=Path(temporary);output=root/"receipt.json";completed=invoke(write_v3(root,mutate=lambda x:x.pop("optimizer_contract")),output);assert completed.returncode!=0 and not output.exists()
def test_rejects_wrong_expert_checkpoint_mapping_before_output():
 with tempfile.TemporaryDirectory()as temporary:
  root=Path(temporary);output=root/"receipt.json";completed=invoke(write_v3(root,mutate=lambda x:x["expert_checkpoint_sha256"].__setitem__("tool","0"*64)),output);assert completed.returncode!=0 and not output.exists()
def test_rejects_missing_central_contract_version_before_output():
 with tempfile.TemporaryDirectory()as temporary:
  root=Path(temporary);output=root/"receipt.json";completed=invoke(write_v3(root,mutate=lambda x:x.pop("contract_version",None)),output);assert completed.returncode!=0 and not output.exists()
def test_rejects_missing_central_architecture_declaration_before_output():
 with tempfile.TemporaryDirectory()as temporary:
  root=Path(temporary);output=root/"receipt.json";completed=invoke(write_v3(root,mutate=lambda x:x.pop("architecture",None)),output);assert completed.returncode!=0 and not output.exists()
