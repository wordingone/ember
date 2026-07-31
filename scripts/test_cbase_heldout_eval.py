# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations
import hashlib, importlib.util, json
from pathlib import Path
import numpy as np
import pytest
import torch

SCRIPT = Path(__file__).with_name("cbase_heldout_eval.py")

def load_module():
    spec = importlib.util.spec_from_file_location("cbase_heldout_eval", SCRIPT)
    assert SCRIPT.is_file() and spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write_json(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, separators=(",", ":"))+"\n", encoding="utf-8", newline="\n")
    return sha(path)

def manifest(shard_sha):
    return {"schema":"cbase-heldout-slice/v1","issue":"#760","captured_public_master":"e"*40,"source_corpus":{"combined_sha256":"a"*64,"receipt_path":"receipts/source.json","receipt_sha256":"b"*64,"shards":[{"name":"v0-00000.bin","sha256":shard_sha,"n_tokens":40}]},"selection_evidence":{"path":"receipts/selection.json","sha256":"c"*64,"batch_sha256":"d"*64,"verdict":"CLEAN"},"sequence":{"dtype":"<u2","seq":4,"n_mtp":0,"separator_id":0,"packed_bytes_per_token":2.0,"scoring":"primary_next_token_only"},"training_consumption":[{"source":"fixture","global_token_start":0,"global_token_end_exclusive":8}],"windows":[{"window_index":2,"shard_name":"v0-00000.bin","shard_token_start":8,"shard_token_end_exclusive":13,"global_token_start":8,"global_token_end_exclusive":13},{"window_index":4,"shard_name":"v0-00000.bin","shard_token_start":16,"shard_token_end_exclusive":21,"global_token_start":16,"global_token_end_exclusive":21}],"expected_scored_token_count":8,"scale":"W1_FROM_SCRATCH_PILOT_BASELINE","availability":{"status":"AVAILABLE","missing":[],"note":"fixture"},"claim_boundary":"fixture"}

class TinyTiedModel(torch.nn.Module):
    def __init__(self):
        super().__init__(); self.backbone_model=torch.nn.Module(); self.backbone_model.embed_tokens=torch.nn.Embedding(11,4)
        layer=torch.nn.Module(); layer.mlp=torch.nn.Module(); layer.mlp.gate_proj=torch.nn.Linear(4,8,bias=False); self.backbone_model.layers=torch.nn.ModuleList([layer])
        self.head=torch.nn.Linear(4,11,bias=False); self.head.weight=self.backbone_model.embed_tokens.weight
    def forward(self, ids): return self.head(self.backbone_model.embed_tokens(ids))

def test_public_contract():
    m=load_module(); assert {"HeldoutEvalRefusal","derive_checkpoint_identity","verify_checkpoint_files","load_frozen_slice_manifest","read_eval_windows","evaluate_teacher_forced","build_receipt"}.issubset(vars(m))

def test_identity_derived_from_storage_and_shapes():
    m=load_module(); assert m.derive_checkpoint_identity(TinyTiedModel().state_dict()) == {"unique_parameter_count":76,"state_dict_parameter_count":120,"duplicate_parameter_count":44,"vocab_size":11,"hidden_size":4,"feed_forward_width":8,"layer_count":1,"primary_head_tied":True}
    state=TinyTiedModel().state_dict(); state["head.weight"]=state["head.weight"].clone(); assert m.derive_checkpoint_identity(state)["primary_head_tied"] is False

def test_wrong_checkpoint_hash_refused(tmp_path):
    m=load_module(); ck=tmp_path/"ck"; ck.mkdir(); (ck/"model.pt").write_bytes(b"v1"); (ck/"optimizer.pt").write_bytes(b"o1")
    write_json(ck/"manifest.json", {"step":50,"files":{"model.pt":sha(ck/"model.pt"),"optimizer.pt":sha(ck/"optimizer.pt")}}); (ck/"model.pt").write_bytes(b"v2")
    with pytest.raises(m.HeldoutEvalRefusal, match="CHECKPOINT_SHA_MISMATCH"): m.verify_checkpoint_files(ck)

def test_manifest_hash_truncation_and_overlap_refused(tmp_path):
    m=load_module(); shard=tmp_path/"v0-00000.bin"; np.arange(40,dtype="<u2").tofile(shard); p=tmp_path/"slice.json"; doc=manifest(sha(shard)); good=write_json(p,doc)
    assert m.load_frozen_slice_manifest(p,good)["expected_scored_token_count"]==8
    with pytest.raises(m.HeldoutEvalRefusal,match="MANIFEST_SHA_MISMATCH"): m.load_frozen_slice_manifest(p,"0"*64)
    doc["windows"][0]["shard_token_end_exclusive"]=12; doc["windows"][0]["global_token_end_exclusive"]=12; bad=write_json(p,doc)
    with pytest.raises(m.HeldoutEvalRefusal,match="TRUNCATED_SLICE"): m.load_frozen_slice_manifest(p,bad)
    doc=manifest(sha(shard)); doc["training_consumption"][0]["global_token_end_exclusive"]=9; overlap=write_json(p,doc)
    with pytest.raises(m.HeldoutEvalRefusal,match="TRAINING_OVERLAP"): m.load_frozen_slice_manifest(p,overlap)

def test_window_reader_verifies_bytes_and_counts_fragments(tmp_path):
    m=load_module(); tokens=np.arange(40,dtype="<u2"); tokens[9]=0; tokens[18]=0; shard=tmp_path/"v0-00000.bin"; tokens.tofile(shard); p=tmp_path/"slice.json"; doc=manifest(sha(shard)); loaded=m.load_frozen_slice_manifest(p,write_json(p,doc)); rows=m.read_eval_windows(tmp_path,loaded)
    assert len(rows)==2 and sum(len(x["target_ids"]) for x in rows)==8
    assert len({d for row in rows for d in row["document_ids"]})==4
    shard.write_bytes(b"\0"*shard.stat().st_size)
    with pytest.raises(m.HeldoutEvalRefusal,match="SHARD_SHA_MISMATCH"): m.read_eval_windows(tmp_path,loaded)

def test_teacher_forced_is_deterministic_and_receipted():
    m=load_module(); torch.manual_seed(7); model=TinyTiedModel(); rows=[{"shard_name":"s","window_index":2,"input_ids":[1,2,3,4],"target_ids":[2,3,4,5],"document_ids":["a","a","b","b"]},{"shard_name":"s","window_index":4,"input_ids":[5,6,7,8],"target_ids":[6,7,8,9],"document_ids":["c","c","d","d"]}]
    kw={"device":"cpu","dtype":"float32","seed":83,"packed_bytes_per_token":2.0,"bootstrap_samples":200}; first=m.evaluate_teacher_forced(model,rows,**kw); second=m.evaluate_teacher_forced(model,rows,**kw)
    assert first==second and first["token_count"]==8 and first["document_fragment_count"]==4 and first["repeat_run_match"] is True and len(first["per_batch_loss_vector_sha256"])==64
    assert first["bits_per_packed_byte"]==pytest.approx(first["mean_nll"]/np.log(2)/2.0)
    receipt=m.build_receipt(checkpoint={"files_sha256":{"model.pt":"c"*64},"manifest_sha256":"d"*64,"manifest_step":50},checkpoint_identity=m.derive_checkpoint_identity(model.state_dict()),slice_manifest_sha256="e"*64,slice_manifest={"scale":"W1_FROM_SCRATCH_PILOT_BASELINE"},evaluation=first)
    assert receipt["api_spend_usd"]==0.0 and receipt["markers"]==["HELDOUT_EVAL_DETERMINISM_PASS","HELDOUT_EVAL_NEGATIVE_FIXTURES_PASS","HELDOUT_SLICE_DISJOINT_PASS"]

def test_nonfinite_loss_refused():
    m=load_module()
    class Bad(torch.nn.Module):
        def forward(self,ids): return torch.full((ids.shape[0],ids.shape[1],11),float("nan"))
    rows=[{"shard_name":"s","window_index":2,"input_ids":[1,2,3,4],"target_ids":[2,3,4,5],"document_ids":["a"]*4}]
    with pytest.raises(m.HeldoutEvalRefusal,match="NONFINITE_LOSS"): m.evaluate_teacher_forced(Bad(),rows,device="cpu",dtype="float32",seed=83,packed_bytes_per_token=2.0,bootstrap_samples=20)


def test_cli_validate_only_checks_real_slice_bytes(tmp_path):
    import subprocess, sys
    shard=tmp_path/"v0-00000.bin"; np.arange(40,dtype="<u2").tofile(shard); p=tmp_path/"slice.json"; expected=write_json(p,manifest(sha(shard)))
    cmd=[sys.executable,"-B",str(SCRIPT),"--validate-only","--slice-manifest",str(p),"--expected-slice-sha256",expected,"--shard-dir",str(tmp_path)]
    good=subprocess.run(cmd,text=True,capture_output=True,check=False)
    assert good.returncode==0 and "HELDOUT_SLICE_DISJOINT_PASS" in good.stdout
    shard.unlink(); missing=subprocess.run(cmd,text=True,capture_output=True,check=False)
    assert missing.returncode==2 and "SHARD_MISSING" in missing.stderr

def test_manifest_provenance_and_closed_shape_fail_closed(tmp_path):
    m=load_module(); shard=tmp_path/"v0-00000.bin"; np.arange(40,dtype="<u2").tofile(shard); p=tmp_path/"slice.json"; doc=manifest(sha(shard))
    doc["source_corpus"].update({"receipt_path":"receipts/source.json","receipt_sha256":"b"*64}); doc["selection_evidence"]={"path":"receipts/selection.json","sha256":"c"*64,"batch_sha256":"d"*64,"verdict":"CLEAN"}
    doc["captured_public_master"]="e"*40; doc["availability"]={"status":"AVAILABLE","missing":[],"note":"fixture"}; doc["claim_boundary"]="fixture"
    write_json(p,doc)
    assert m.load_frozen_slice_manifest(p,sha(p))["selection_evidence"]["verdict"]=="CLEAN"
    for mutate in (
        lambda value: value["source_corpus"].update(receipt_sha256="short"),
        lambda value: value["selection_evidence"].update(verdict="UNKNOWN"),
        lambda value: value["windows"][0].update(unexpected=True),
        lambda value: value.update(unexpected=True),
    ):
        bad=json.loads(json.dumps(doc)); mutate(bad); write_json(p,bad)
        with pytest.raises(m.HeldoutEvalRefusal,match="SLICE_"): m.load_frozen_slice_manifest(p,sha(p))
def test_evaluator_does_not_import_execution_denied_historical_trainer():
    source=SCRIPT.read_text(encoding="utf-8")
    assert "from timeshare_pretrain" not in source
    assert "from w1_collapse_control_run" not in source
    m=load_module()
    assert m.HISTORICAL_EVAL_MODEL_CONTRACT == {"public_master":"db571b310b0ad20f8b257760cdc7c7ee69714929","w1_model_source_blob":"3dc627d49c5e48ceb8ab0c028eab68acb74e4f61","timeshare_source_blob":"ea367b382b975afd7afecbe86b6efa1148bd76ad","attention_heads":16,"max_sequence_length":1024}