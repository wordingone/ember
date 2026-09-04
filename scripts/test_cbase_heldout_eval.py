# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations
import hashlib, importlib.util, json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
import torch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src" / "ember" / "evaluation" / "cbase_heldout_eval.py"

def load_module():
    spec = importlib.util.spec_from_file_location("cbase_heldout_eval", SCRIPT)
    assert SCRIPT.is_file() and spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write_json(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, separators=(",", ":"))+"\n", encoding="utf-8", newline="\n")
    return sha(path)

def manifest(shard_sha, *, receipt_path="receipts/source.json"):
    return {"schema":"cbase-heldout-slice/v1","issue":"#760","captured_public_master":"e"*40,"source_corpus":{"combined_sha256":"a"*64,"receipt_path":receipt_path,"receipt_sha256":"b"*64,"shards":[{"name":"v0-00000.bin","sha256":shard_sha,"n_tokens":40}]},"selection_evidence":{"path":"receipts/selection.json","sha256":"c"*64,"batch_sha256":"d"*64,"verdict":"CLEAN"},"sequence":{"dtype":"<u2","seq":4,"n_mtp":0,"separator_id":0,"packed_bytes_per_token":2.0,"scoring":"primary_next_token_only"},"training_consumption":[{"source":"fixture","global_token_start":0,"global_token_end_exclusive":8}],"windows":[{"window_index":2,"shard_name":"v0-00000.bin","shard_token_start":8,"shard_token_end_exclusive":13,"global_token_start":8,"global_token_end_exclusive":13},{"window_index":4,"shard_name":"v0-00000.bin","shard_token_start":16,"shard_token_end_exclusive":21,"global_token_start":16,"global_token_end_exclusive":21}],"expected_scored_token_count":8,"scale":"W1_FROM_SCRATCH_PILOT_BASELINE","availability":{"status":"AVAILABLE","missing":[],"note":"fixture"},"claim_boundary":"fixture"}

def build_real_corpus_fixture(nc_root, shard_root, *, clean_tokens=2000, fineweb_tokens=1000,
                               shard_name="v0-00000.bin", receipt_name="token-shards-v0-fixture.json"):
    """Build a complete, valid, hermetic TOKEN-SHARDS-V0 + assembly +
    tokenizer-freeze + provenance-ruling fixture tree: `clean_tokens` of
    code_github_clean content followed by `fineweb_tokens` of ruled-excluded
    fineweb_edu content, in one shard. Mirrors fineweb_exclusion.py's own
    _selftest_fail_closed_against_real_schema fixture (same schema, same
    field set -- that fixture is the proof this shape validates cleanly
    against token_shards_v0.validate_shards_receipt).

    nc_root and shard_root may be the same directory (CLI --shard-dir tests,
    which place the .bin flat next to --nc) or different (direct-call tests
    that keep shard bytes under nc_root/shards/, matching the receipt's own
    declared shard_dir for readability). Returns a dict describing what was
    written, including the exact fineweb_edu byte range so callers can place
    windows precisely inside or outside it."""
    import struct, sys
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path: sys.path.insert(0, scripts_dir)
    # issue2015 exact-local-import:src/ember/governance/scripts/token_shards_v0.py
    import importlib.util as _ember_0c6ba95c4d327f51_importlib
    import sys as _ember_0c6ba95c4d327f51_sys
    from pathlib import Path as _ember_0c6ba95c4d327f51_Path
    _ember_0c6ba95c4d327f51_path = _ember_0c6ba95c4d327f51_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'token_shards_v0.py')
    if not _ember_0c6ba95c4d327f51_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/token_shards_v0.py')
    _ember_0c6ba95c4d327f51_aliases = ('_ember_issue2015_0c6ba95c4d327f51', 'scripts.token_shards_v0', 'token_shards_v0')
    _ember_0c6ba95c4d327f51_existing = []
    for _ember_0c6ba95c4d327f51_alias in _ember_0c6ba95c4d327f51_aliases:
        _ember_0c6ba95c4d327f51_candidate = _ember_0c6ba95c4d327f51_sys.modules.get(_ember_0c6ba95c4d327f51_alias)
        if _ember_0c6ba95c4d327f51_candidate is not None and all(_ember_0c6ba95c4d327f51_candidate is not item for item in _ember_0c6ba95c4d327f51_existing):
            _ember_0c6ba95c4d327f51_existing.append(_ember_0c6ba95c4d327f51_candidate)
    if len(_ember_0c6ba95c4d327f51_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/token_shards_v0.py')
    if _ember_0c6ba95c4d327f51_existing:
        _ember_0c6ba95c4d327f51_module = _ember_0c6ba95c4d327f51_existing[0]
        _ember_0c6ba95c4d327f51_observed = getattr(_ember_0c6ba95c4d327f51_module, '__file__', None)
        if _ember_0c6ba95c4d327f51_observed is None or _ember_0c6ba95c4d327f51_Path(_ember_0c6ba95c4d327f51_observed).resolve() != _ember_0c6ba95c4d327f51_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/token_shards_v0.py')
    else:
        _ember_0c6ba95c4d327f51_spec = _ember_0c6ba95c4d327f51_importlib.spec_from_file_location('_ember_issue2015_0c6ba95c4d327f51', _ember_0c6ba95c4d327f51_path)
        if _ember_0c6ba95c4d327f51_spec is None or _ember_0c6ba95c4d327f51_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/token_shards_v0.py')
        _ember_0c6ba95c4d327f51_module = _ember_0c6ba95c4d327f51_importlib.module_from_spec(_ember_0c6ba95c4d327f51_spec)
        for _ember_0c6ba95c4d327f51_alias in _ember_0c6ba95c4d327f51_aliases:
            _ember_0c6ba95c4d327f51_prior = _ember_0c6ba95c4d327f51_sys.modules.get(_ember_0c6ba95c4d327f51_alias)
            if _ember_0c6ba95c4d327f51_prior is not None and _ember_0c6ba95c4d327f51_prior is not _ember_0c6ba95c4d327f51_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/token_shards_v0.py')
            _ember_0c6ba95c4d327f51_sys.modules[_ember_0c6ba95c4d327f51_alias] = _ember_0c6ba95c4d327f51_module
        try:
            _ember_0c6ba95c4d327f51_spec.loader.exec_module(_ember_0c6ba95c4d327f51_module)
        except BaseException:
            for _ember_0c6ba95c4d327f51_alias in _ember_0c6ba95c4d327f51_aliases:
                if _ember_0c6ba95c4d327f51_sys.modules.get(_ember_0c6ba95c4d327f51_alias) is _ember_0c6ba95c4d327f51_module:
                    _ember_0c6ba95c4d327f51_sys.modules.pop(_ember_0c6ba95c4d327f51_alias, None)
            raise
    for _ember_0c6ba95c4d327f51_alias in _ember_0c6ba95c4d327f51_aliases:
        _ember_0c6ba95c4d327f51_prior = _ember_0c6ba95c4d327f51_sys.modules.get(_ember_0c6ba95c4d327f51_alias)
        if _ember_0c6ba95c4d327f51_prior is not None and _ember_0c6ba95c4d327f51_prior is not _ember_0c6ba95c4d327f51_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/token_shards_v0.py')
        _ember_0c6ba95c4d327f51_sys.modules[_ember_0c6ba95c4d327f51_alias] = _ember_0c6ba95c4d327f51_module
    tsv = _ember_0c6ba95c4d327f51_module
    # issue2015 exact-local-import-end:src/ember/governance/scripts/token_shards_v0.py
    nc_root = Path(nc_root); shard_root = Path(shard_root)
    (nc_root/"receipts").mkdir(parents=True, exist_ok=True)
    tokenizer_path = nc_root / "domains" / "model" / "tokenizer" / "tokenizer.json"
    tokenizer_path.parent.mkdir(parents=True, exist_ok=True)
    shard_root.mkdir(parents=True, exist_ok=True)
    prem_names = {"assembly_receipt": "fixture-assembly.json", "tokenizer_freeze_receipt": "fixture-tokfreeze.json"}
    for nm in prem_names.values():
        write_json(nc_root/"receipts"/nm, {"ticket": "FIXTURE", "ts": "20260101T000000Z"})
    write_json(tokenizer_path, {"vocab_size": 32000})
    with open(nc_root/"receipts"/"v1-provenance-manifest-20260706.jsonl", "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"source": "code_github_clean", "provenance_verdict": "CLEAN"}) + "\n")
        fh.write(json.dumps({"source": "fineweb_edu", "action": "DROP",
                             "provenance_verdict": "EXCLUDED (fail-closed per clause 3)"}) + "\n")
    total = clean_tokens + fineweb_tokens
    ids = [8 + (i % 100) for i in range(total)]   # avoid separator(0) and reserved band(1..7)
    shard_path = shard_root / shard_name
    with open(shard_path, "wb") as fh:
        fh.write(b"".join(struct.pack("<H", x) for x in ids))
    shard_sha = sha(shard_path)
    per_source = {s: {"content_tokens": 0, "separator_tokens": 0, "stream_tokens": 0} for s in tsv.EXPECTED_SOURCES}
    per_source["code_github_clean"] = {"content_tokens": clean_tokens, "separator_tokens": 0, "stream_tokens": clean_tokens}
    per_source["fineweb_edu"] = {"content_tokens": fineweb_tokens, "separator_tokens": 0, "stream_tokens": fineweb_tokens}
    receipt = {
        "ticket": tsv.TICKET, "ts": "20260611T000000Z", "shard_dir": "shards",
        "shards": [{"name": shard_name, "sha256": shard_sha, "n_tokens": total}],
        "total_stream_tokens": total, "content_total_tokens": total,
        "per_source": per_source, "separator_id": tsv.SEPARATOR_ID,
        "reserved_band_guard": {"reserved_ids": tsv.RESERVED_IDS, "max_id_lt": tsv.VOCAB_SIZE,
                                "reserved_ids_observed_in_stream": 0},
        "loader_windows": {"seq": tsv.SEQ, "n_mtp": tsv.N_MTP, "block_len": tsv.BLOCK_LEN,
                           "n_windows": max(0, (total - tsv.BLOCK_LEN) // tsv.SEQ + 1)},
        "premises": {
            "assembly_receipt": {"name": prem_names["assembly_receipt"],
                                 "sha256": sha(nc_root/"receipts"/prem_names["assembly_receipt"])},
            "tokenizer_freeze_receipt": {"name": prem_names["tokenizer_freeze_receipt"],
                                         "sha256": sha(nc_root/"receipts"/prem_names["tokenizer_freeze_receipt"])},
            "tokenizer_json": {"path": "domains/model/tokenizer/tokenizer.json", "sha256": sha(tokenizer_path)},
        },
        "sha_convention": tsv.SHA_CONVENTION, "no_gpu": True,
    }
    assembly = {"ticket": "FIXTURE", "ts": "20260101T000000Z", "sources": [
        {"source": "code_github_clean", "fp22_row": 1},
        {"source": "fineweb_edu", "fp22_row": 2},
        {"source": "wikipedia_en", "fp22_row": 3},
        {"source": "gutenberg_en", "fp22_row": 4},
        {"source": "ledger_mit", "fp22_row": 5},
    ]}
    write_json(nc_root/"receipts"/prem_names["assembly_receipt"], assembly)
    receipt["premises"]["assembly_receipt"]["sha256"] = sha(nc_root/"receipts"/prem_names["assembly_receipt"])
    write_json(nc_root/"receipts"/receipt_name, receipt)
    return {"receipt_name": receipt_name, "shard_name": shard_name, "total_tokens": total,
           "shard_sha256": shard_sha, "fineweb_range": (clean_tokens, total)}

class TinyTiedModel(torch.nn.Module):
    def __init__(self):
        super().__init__(); self.backbone_model=torch.nn.Module(); self.backbone_model.embed_tokens=torch.nn.Embedding(11,4)
        layer=torch.nn.Module(); layer.mlp=torch.nn.Module(); layer.mlp.gate_proj=torch.nn.Linear(4,8,bias=False); self.backbone_model.layers=torch.nn.ModuleList([layer])
        self.head=torch.nn.Linear(4,11,bias=False); self.head.weight=self.backbone_model.embed_tokens.weight
    def forward(self, ids): return self.head(self.backbone_model.embed_tokens(ids))

def test_public_contract():
    m=load_module(); assert {"HeldoutEvalRefusal","derive_checkpoint_identity","verify_checkpoint_files","verify_v5_checkpoint_for_heldout","load_v5_live_model","load_frozen_slice_manifest","read_eval_windows","evaluate_teacher_forced","build_receipt"}.issubset(vars(m))

def _v5_binding(*, step=100, tokens_seen=409600, route="tool", declared=None,
                tied=True, measured=None):
    declared = [route] if declared is None else declared
    measured = measured or {
        "shared-model.pt":"1"*64,
        "expert-vision.pt":"2"*64,
        "expert-audio.pt":"3"*64,
        "expert-reasoning.pt":"4"*64,
        "expert-tool.pt":"5"*64,
    }
    return {
        "checkpoint":{
            "schema_version":"ember-sparse-checkpoint-v5",
            "manifest_sha256":"a"*64,
            "measured_shard_sha256":measured,
            "architecture_revision":"ember-sparse-3b-v2",
            "contract_version":5,
            "launch_seed":830013,
            "global_step":step,
            "tokens_seen":tokens_seen,
        },
        "model_config":{
            "path":"configs/ember-restart-3b.json",
            "sha256":"b"*64,
            "hidden_size":4,
            "layers":1,
            "attention_heads":1,
            "vocab_size":11,
        },
        "route":{
            "selected":route,
            "selection_policy":"explicit_required_argument_no_default",
            "config_default_active_expert":"reasoning",
            "manifest_declared_active_expert_ids":declared,
            "selected_matches_manifest_declared":declared == [route],
        },
        "tied_embeddings_reasserted":tied,
        "tokenizer":{"path":"<external>","sha256":"c"*64},
        "requested_device":"cpu",
        "realized_device":"cpu",
        "realized_dtype":"torch.float32",
        "max_position_embeddings":1024,
    }

class FakeV5Module:
    class LiveCandidateRefusal(Exception):
        pass
    MODEL_SHARDS=("shared-model.pt","expert-vision.pt","expert-audio.pt","expert-reasoning.pt","expert-tool.pt")
    __file__=str(ROOT / "src" / "ember" / "governance" / "scripts" / "legb_live_candidate_v5_scorer.py")
    def __init__(self, *, binding=None, verified=None, refusal=None):
        self.binding=binding or _v5_binding(); self.verified=verified or {
            "manifest":{"schema_version":"ember-sparse-checkpoint-v5","active_expert_ids":self.binding["route"]["manifest_declared_active_expert_ids"]},
            "manifest_sha256":"a"*64,
            "measured_shard_sha256":self.binding["checkpoint"]["measured_shard_sha256"],
            "global_step":self.binding["checkpoint"]["global_step"],
            "tokens_seen":self.binding["checkpoint"]["tokens_seen"],
        }; self.refusal=refusal; self.build_calls=0
    def load_verified_v5_checkpoint(self, checkpoint_dir):
        if self.refusal: raise self.LiveCandidateRefusal(self.refusal)
        return self.verified
    def build_live_candidate_scorer(self, **kwargs):
        self.build_calls += 1
        if self.refusal: raise self.LiveCandidateRefusal(self.refusal)
        return SimpleNamespace(model=TinyTiedModel()), self.binding

def test_v5_verify_path_accepts_structural_fixture_but_translates_byte_refusal(monkeypatch):
    m=load_module(); fake=FakeV5Module(binding=_v5_binding(step=4,tokens_seen=36))
    monkeypatch.setattr(m,"_v5_scorer_module",lambda:fake)
    verified=m.verify_v5_checkpoint_for_heldout("seed-830013")
    assert verified["global_step"]==4 and verified["tokens_seen"]==36
    fake.refusal="CHECKPOINT_SHARD_SHA_MISMATCH: expert-tool.pt"
    with pytest.raises(m.HeldoutEvalRefusal,match="CHECKPOINT_SHARD_SHA_MISMATCH"):
        m.verify_v5_checkpoint_for_heldout("seed-830013")

def test_v5_scoring_requires_warm100_exact_route_tied_head_and_closed_model_map(monkeypatch):
    m=load_module(); fake=FakeV5Module(binding=_v5_binding(step=4,tokens_seen=36))
    monkeypatch.setattr(m,"_v5_scorer_module",lambda:fake)
    with pytest.raises(m.HeldoutEvalRefusal,match="WARM100_CHECKPOINT_REQUIRED"):
        m.load_v5_live_model("seed-830013",route="tool",device="cpu",max_position_embeddings=1024)
    assert fake.build_calls==0
    fake=FakeV5Module(binding=_v5_binding(step=100,declared=["reasoning"])); monkeypatch.setattr(m,"_v5_scorer_module",lambda:fake)
    with pytest.raises(m.HeldoutEvalRefusal,match="CHECKPOINT_ROUTE_MISMATCH"):
        m.load_v5_live_model("warm100",route="tool",device="cpu",max_position_embeddings=1024)
    fake=FakeV5Module(binding=_v5_binding(step=100,tied=False)); monkeypatch.setattr(m,"_v5_scorer_module",lambda:fake)
    with pytest.raises(m.HeldoutEvalRefusal,match="PRIMARY_HEAD_NOT_TIED"):
        m.load_v5_live_model("warm100",route="tool",device="cpu",max_position_embeddings=1024)
    fake=FakeV5Module(binding=_v5_binding(step=100,measured={"shared-model.pt":"1"*64})); monkeypatch.setattr(m,"_v5_scorer_module",lambda:fake)
    with pytest.raises(m.HeldoutEvalRefusal,match="CHECKPOINT_MODEL_SHARD_MAP_INVALID"):
        m.load_v5_live_model("warm100",route="tool",device="cpu",max_position_embeddings=1024)
    bad_runtime=_v5_binding(step=100); bad_runtime["requested_device"]="cuda"
    fake=FakeV5Module(binding=bad_runtime); monkeypatch.setattr(m,"_v5_scorer_module",lambda:fake)
    with pytest.raises(m.HeldoutEvalRefusal,match="CHECKPOINT_RUNTIME_BINDING_INVALID"):
        m.load_v5_live_model("warm100",route="tool",device="cpu",max_position_embeddings=1024)
    fake=FakeV5Module(binding=_v5_binding(step=100)); fake.verified["manifest_sha256"]="f"*64
    monkeypatch.setattr(m,"_v5_scorer_module",lambda:fake)
    with pytest.raises(m.HeldoutEvalRefusal,match="CHECKPOINT_CHANGED_DURING_MODEL_LOAD"):
        m.load_v5_live_model("warm100",route="tool",device="cpu",max_position_embeddings=1024)

def test_v5_scoring_adapter_returns_exact_checkpoint_route_and_model_identity(monkeypatch):
    m=load_module(); fake=FakeV5Module(binding=_v5_binding(step=100))
    monkeypatch.setattr(m,"_v5_scorer_module",lambda:fake)
    model,identity,checkpoint=m.load_v5_live_model(
        "warm100",route="tool",device="cpu",max_position_embeddings=1024)
    assert isinstance(model,TinyTiedModel)
    assert checkpoint["manifest_sha256"]=="a"*64
    assert checkpoint["route"]["selected"]=="tool"
    assert identity=={
        "architecture_revision":"ember-sparse-3b-v2",
        "contract_version":5,
        "hidden_size":4,
        "layer_count":1,
        "attention_head_count":1,
        "vocab_size":11,
        "primary_head_tied":True,
        "selected_expert_route":"tool",
    }

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
    assert len({d for row in rows for d in row["document_ids"]})==3
    shard.write_bytes(b"\0"*shard.stat().st_size)
    with pytest.raises(m.HeldoutEvalRefusal,match="SHARD_SHA_MISMATCH"): m.read_eval_windows(tmp_path,loaded)

def test_teacher_forced_is_deterministic_and_receipted():
    m=load_module(); torch.manual_seed(7); model=TinyTiedModel(); rows=[{"shard_name":"s","window_index":2,"input_ids":[1,2,3,4],"target_ids":[2,3,4,5],"document_ids":["a","a","b","b"]},{"shard_name":"s","window_index":4,"input_ids":[5,6,7,8],"target_ids":[6,7,8,9],"document_ids":["c","c","d","d"]}]
    kw={"device":"cpu","dtype":"float32","seed":83,"packed_bytes_per_token":2.0,"bootstrap_samples":200}; first=m.evaluate_teacher_forced(model,rows,**kw); second=m.evaluate_teacher_forced(model,rows,**kw)
    assert first==second and first["token_count"]==8 and first["document_count"]==4 and first["repeat_run_match"] is True and len(first["per_batch_loss_vector_sha256"])==64
    assert first["bits_per_packed_byte"]==pytest.approx(first["mean_nll"]/np.log(2)/2.0)
    receipt=m.build_receipt(checkpoint={"files_sha256":{"model.pt":"c"*64},"manifest_sha256":"d"*64,"manifest_step":50},checkpoint_identity=m.derive_checkpoint_identity(model.state_dict()),slice_manifest_sha256="e"*64,slice_manifest={"scale":"W1_FROM_SCRATCH_PILOT_BASELINE"},evaluation=first)
    assert receipt["issue_refs"]==["#760","#1433"]
    assert receipt["api_spend_usd"]==0.0 and receipt["markers"]==["HELDOUT_EVAL_DETERMINISM_PASS","HELDOUT_EVAL_NEGATIVE_FIXTURES_PASS","HELDOUT_SLICE_DISJOINT_PASS"]

def test_nonfinite_loss_refused():
    m=load_module()
    class Bad(torch.nn.Module):
        def forward(self,ids): return torch.full((ids.shape[0],ids.shape[1],11),float("nan"))
    rows=[{"shard_name":"s","window_index":2,"input_ids":[1,2,3,4],"target_ids":[2,3,4,5],"document_ids":["a"]*4}]
    with pytest.raises(m.HeldoutEvalRefusal,match="NONFINITE_LOSS"): m.evaluate_teacher_forced(Bad(),rows,device="cpu",dtype="float32",seed=83,packed_bytes_per_token=2.0,bootstrap_samples=20)


def _manifest_for_fixture(fixture, **overrides):
    """manifest() pointed at a build_real_corpus_fixture()'s real receipt,
    with source_corpus.shards[0].n_tokens corrected to the fixture's actual
    size (manifest()'s own default of 40 would otherwise mismatch and trip
    SHARD_SIZE_MISMATCH / SLICE_WINDOW_OUT_OF_RANGE against real fixture
    bytes). Any further overrides (e.g. windows/training_consumption) are
    applied on top."""
    doc=manifest(fixture["shard_sha256"],receipt_path=f"receipts/{fixture['receipt_name']}")
    doc["source_corpus"]["shards"][0]["n_tokens"]=fixture["total_tokens"]
    doc.update(overrides)
    return doc

def test_cli_validate_only_checks_real_slice_bytes(tmp_path):
    import subprocess, sys
    # clean_tokens=2000 both keeps manifest()'s windows ([8,13) and [16,21))
    # entirely below the fineweb_edu split and clears validate_shards_receipt's
    # own minimum-size floor (stream must be >= BLOCK_LEN=1027 tokens), so
    # validate-only sees a genuinely clean, genuinely valid slice under the
    # new exclusion check rather than a fixture the check has to be blind to.
    fixture=build_real_corpus_fixture(tmp_path,tmp_path,clean_tokens=2000,fineweb_tokens=1000,shard_name="v0-00000.bin")
    shard=tmp_path/"v0-00000.bin"
    p=tmp_path/"slice.json"; expected=write_json(p,_manifest_for_fixture(fixture))
    cmd=[sys.executable,"-B",str(SCRIPT),"--validate-only","--slice-manifest",str(p),"--expected-slice-sha256",expected,"--shard-dir",str(tmp_path),"--nc",str(tmp_path)]
    good=subprocess.run(cmd,text=True,capture_output=True,check=False)
    assert good.returncode==0 and "HELDOUT_SLICE_DISJOINT_PASS" in good.stdout
    shard.unlink(); missing=subprocess.run(cmd,text=True,capture_output=True,check=False)
    assert missing.returncode==2 and "SHARD_MISSING" in missing.stderr

def test_verify_slice_excludes_ruled_sources_pass_and_refuse(tmp_path):
    """#760 x #1436: a slice window inside the ruled-excluded fineweb_edu
    range is refused; the same corpus's clean region passes and reports the
    exact range it checked. Proves verify_slice_excludes_ruled_sources against
    a real TOKEN-SHARDS-V0 + assembly + ruling fixture tree, not just schema
    shapes -- the fixture is what build_real_corpus_fixture mirrors from
    fineweb_exclusion.py's own proven-valid selftest fixture."""
    m=load_module()
    nc_root=tmp_path/"nc"; shard_root=nc_root/"shards"
    fixture=build_real_corpus_fixture(nc_root,shard_root,clean_tokens=2000,fineweb_tokens=1000)
    fineweb_start,fineweb_end=fixture["fineweb_range"]

    clean=_manifest_for_fixture(fixture)
    loaded_clean=m.load_frozen_slice_manifest(tmp_path/"clean.json",write_json(tmp_path/"clean.json",clean))
    ranges=m.verify_slice_excludes_ruled_sources(loaded_clean,shard_dir=str(shard_root),nc=str(nc_root))
    assert ranges==[(fineweb_start,fineweb_end)]

    tainted_window=[{"window_index":9,"shard_name":"v0-00000.bin","shard_token_start":fineweb_start,"shard_token_end_exclusive":fineweb_start+5,"global_token_start":fineweb_start,"global_token_end_exclusive":fineweb_start+5}]
    tainted=_manifest_for_fixture(fixture,windows=tainted_window,training_consumption=[],expected_scored_token_count=4)
    loaded_tainted=m.load_frozen_slice_manifest(tmp_path/"tainted.json",write_json(tmp_path/"tainted.json",tainted))
    with pytest.raises(m.HeldoutEvalRefusal,match="SLICE_OVERLAPS_EXCLUDED_SOURCE"):
        m.verify_slice_excludes_ruled_sources(loaded_tainted,shard_dir=str(shard_root),nc=str(nc_root))

def test_verify_slice_excludes_ruled_sources_refuses_unproven_receipt(tmp_path):
    """A manifest whose declared source_corpus.receipt_path names no real
    on-disk receipt is a hard refusal, never a silent 'nothing to exclude' --
    the whole point is independently proving the corpus claim, not trusting
    what the manifest says about itself."""
    m=load_module()
    doc=manifest("0"*64)   # default receipt_path -> receipts/source.json, never written
    loaded=m.load_frozen_slice_manifest(tmp_path/"m.json",write_json(tmp_path/"m.json",doc))
    with pytest.raises(m.HeldoutEvalRefusal,match="EXCLUSION_DERIVATION_FAILED"):
        m.verify_slice_excludes_ruled_sources(loaded,shard_dir=str(tmp_path),nc=str(tmp_path))

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

def test_rule_derived_verdict_is_closed_and_legacy_clean_is_unchanged(tmp_path):
    m=load_module(); shard=tmp_path/"v0-00000.bin"; np.arange(40,dtype="<u2").tofile(shard); p=tmp_path/"slice.json"
    legacy=manifest(sha(shard)); write_json(p,legacy)
    assert m.load_frozen_slice_manifest(p,sha(p))["selection_evidence"]["verdict"]=="CLEAN"
    ruled=manifest(sha(shard)); ruled["selection_evidence"]["verdict"]="RULE_DERIVED_EXCLUSION_CLEAN"; write_json(p,ruled)
    assert m.load_frozen_slice_manifest(p,sha(p))["selection_evidence"]["verdict"]=="RULE_DERIVED_EXCLUSION_CLEAN"
    ruled["selection_evidence"]["unexpected"]="x"; write_json(p,ruled)
    with pytest.raises(m.HeldoutEvalRefusal,match="SLICE_SELECTION_INVALID"):
        m.load_frozen_slice_manifest(p,sha(p))

def test_rule_derived_receipt_rederives_exact_windows_and_refuses_later_choice(tmp_path,monkeypatch):
    m=load_module()
    # issue2015 exact-local-import:src/ember/governance/scripts/regenerate_cbase_heldout_slice.py
    import importlib.util as _ember_a2a797319a415ece_importlib
    import sys as _ember_a2a797319a415ece_sys
    from pathlib import Path as _ember_a2a797319a415ece_Path
    _ember_a2a797319a415ece_path = _ember_a2a797319a415ece_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'regenerate_cbase_heldout_slice.py')
    if not _ember_a2a797319a415ece_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/regenerate_cbase_heldout_slice.py')
    _ember_a2a797319a415ece_aliases = ('_ember_issue2015_a2a797319a415ece', 'regenerate_cbase_heldout_slice', 'scripts.regenerate_cbase_heldout_slice')
    _ember_a2a797319a415ece_existing = []
    for _ember_a2a797319a415ece_alias in _ember_a2a797319a415ece_aliases:
        _ember_a2a797319a415ece_candidate = _ember_a2a797319a415ece_sys.modules.get(_ember_a2a797319a415ece_alias)
        if _ember_a2a797319a415ece_candidate is not None and all(_ember_a2a797319a415ece_candidate is not item for item in _ember_a2a797319a415ece_existing):
            _ember_a2a797319a415ece_existing.append(_ember_a2a797319a415ece_candidate)
    if len(_ember_a2a797319a415ece_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/regenerate_cbase_heldout_slice.py')
    if _ember_a2a797319a415ece_existing:
        _ember_a2a797319a415ece_module = _ember_a2a797319a415ece_existing[0]
        _ember_a2a797319a415ece_observed = getattr(_ember_a2a797319a415ece_module, '__file__', None)
        if _ember_a2a797319a415ece_observed is None or _ember_a2a797319a415ece_Path(_ember_a2a797319a415ece_observed).resolve() != _ember_a2a797319a415ece_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/regenerate_cbase_heldout_slice.py')
    else:
        _ember_a2a797319a415ece_spec = _ember_a2a797319a415ece_importlib.spec_from_file_location('_ember_issue2015_a2a797319a415ece', _ember_a2a797319a415ece_path)
        if _ember_a2a797319a415ece_spec is None or _ember_a2a797319a415ece_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/regenerate_cbase_heldout_slice.py')
        _ember_a2a797319a415ece_module = _ember_a2a797319a415ece_importlib.module_from_spec(_ember_a2a797319a415ece_spec)
        for _ember_a2a797319a415ece_alias in _ember_a2a797319a415ece_aliases:
            _ember_a2a797319a415ece_prior = _ember_a2a797319a415ece_sys.modules.get(_ember_a2a797319a415ece_alias)
            if _ember_a2a797319a415ece_prior is not None and _ember_a2a797319a415ece_prior is not _ember_a2a797319a415ece_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/regenerate_cbase_heldout_slice.py')
            _ember_a2a797319a415ece_sys.modules[_ember_a2a797319a415ece_alias] = _ember_a2a797319a415ece_module
        try:
            _ember_a2a797319a415ece_spec.loader.exec_module(_ember_a2a797319a415ece_module)
        except BaseException:
            for _ember_a2a797319a415ece_alias in _ember_a2a797319a415ece_aliases:
                if _ember_a2a797319a415ece_sys.modules.get(_ember_a2a797319a415ece_alias) is _ember_a2a797319a415ece_module:
                    _ember_a2a797319a415ece_sys.modules.pop(_ember_a2a797319a415ece_alias, None)
            raise
    for _ember_a2a797319a415ece_alias in _ember_a2a797319a415ece_aliases:
        _ember_a2a797319a415ece_prior = _ember_a2a797319a415ece_sys.modules.get(_ember_a2a797319a415ece_alias)
        if _ember_a2a797319a415ece_prior is not None and _ember_a2a797319a415ece_prior is not _ember_a2a797319a415ece_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/regenerate_cbase_heldout_slice.py')
        _ember_a2a797319a415ece_sys.modules[_ember_a2a797319a415ece_alias] = _ember_a2a797319a415ece_module
    freezer = _ember_a2a797319a415ece_module
    # issue2015 exact-local-import-end:src/ember/governance/scripts/regenerate_cbase_heldout_slice.py
    (tmp_path/"receipts").mkdir(); write_json(tmp_path/"receipts"/"source.json",{"shards":[]})
    exclusion=tmp_path/"receipts"/"exclusion.json"; write_json(exclusion,{"fixture":True})
    doc=manifest("0"*64); doc["selection_evidence"]["verdict"]="RULE_DERIVED_EXCLUSION_CLEAN"
    expected=list(doc["windows"])
    rule={"ticket":"ISSUE-1433-RULE-DERIVED-HELDOUT-FREEZE","issue":"#1433","ts":"20260820T000000Z",
          "schema":"cbase-heldout-rule-freeze/v1","status":"RULE_DERIVED_EXCLUSION_CLEAN",
          "selection_rule_id":"EARLIEST_ADMISSIBLE_AFTER_EXCLUSION_FRONTIER_V1","selection_rule":"fixture",
          "exclusion_set":{"path":"receipts/exclusion.json","sha256":sha(exclusion),
                           "ranges_sha256":hashlib.sha256(b"[[100,200]]").hexdigest(),
                           "excluded_token_ranges":[[100,200]]},
          "source_receipts":{},"sequence":{"seq":4,"n_mtp":0,"block_len":5},
          "training_ranges":[[0,8]],"windows":expected,"previous_refusal":{},"producer":{},
          "invariant_sha256":"a"*64,"sha_convention":"fixture","authority":{},"claim_boundary":"fixture"}
    selection=tmp_path/"receipts"/"selection.json"; write_json(selection,rule)
    doc["selection_evidence"].update(path="receipts/selection.json",sha256=sha(selection),batch_sha256=sha(selection))
    monkeypatch.setattr(freezer,"_load_exclusion_set",lambda *args,**kwargs:{"excluded_token_ranges":[[100,200]]})
    monkeypatch.setattr(freezer,"select_earliest_admissible_windows",lambda *args,**kwargs:expected)
    m.verify_rule_derived_selection(doc,shard_dir=tmp_path,nc=tmp_path)
    rule["windows"]=list(reversed(expected)); write_json(selection,rule)
    doc["selection_evidence"].update(sha256=sha(selection),batch_sha256=sha(selection))
    with pytest.raises(m.HeldoutEvalRefusal,match="EARLIEST_WINDOW_MISMATCH"):
        m.verify_rule_derived_selection(doc,shard_dir=tmp_path,nc=tmp_path)

def test_evaluate_refuses_intermediate_rule_verdict_before_model_load(tmp_path,monkeypatch,capsys):
    m=load_module(); doc=manifest("0"*64); doc["selection_evidence"]["verdict"]="RULE_DERIVED_EXCLUSION_CLEAN"
    monkeypatch.setattr(m,"load_frozen_slice_manifest",lambda *args:doc)
    monkeypatch.setattr(m,"verify_rule_derived_selection",lambda *args,**kwargs:None)
    monkeypatch.setattr(m,"read_eval_windows",lambda *args,**kwargs:[])
    monkeypatch.setattr(m,"verify_slice_excludes_ruled_sources",lambda *args,**kwargs:[])
    def forbidden(*args,**kwargs): raise AssertionError("checkpoint/model load reached")
    monkeypatch.setattr(m,"load_live_model",forbidden)
    code=m.main(["--evaluate","--shard-dir",str(tmp_path),"--checkpoint-dir",str(tmp_path),
                 "--checkpoint-kind","step25","--out",str(tmp_path/"out.json")])
    assert code==2
    assert "RULE_DERIVED_VERDICT_NOT_SCORABLE" in capsys.readouterr().err

def test_scoped_verdict_refuses_mismatched_run_consumption_before_model_load(tmp_path,monkeypatch,capsys):
    m=load_module(); doc=manifest("0"*64)
    proof={"schema":"issue1433-warm100-trained-range-match-intersection/v1","issue":1433,
           "status":"PASS","answer":"NO","question":"fixture","trained_run":{
             "run_id":"issue1296-warm100-run-20260819T203314Z","source_commit":"b"*40,
             "run_spec_path":"B:/fixture/run-spec.json","run_spec_sha256":"1"*64,
             "checkpoint_manifest_path":"B:/fixture/checkpoint-manifest.json",
             "checkpoint_manifest_sha256":"2"*64,"stream_receipt_path":"A:/fixture/token-shards.json",
             "stream_receipt_sha256":"3"*64,"sequence_length":512,"steps":100,
             "start_cursor":{"shard_index":0,"token_offset":0},
             "terminal_cursor":{"shard_index":0,"token_offset":51200,"record_index":100,
                                "global_step":100,"tokens_seen":51200},
             "consumed_physical_range":{"shard":"v0-00000.bin",
               "input_and_target_token_positions_inclusive":[0,51200],"derivation":"fixture"},
             "producer_source":{}},
           "scan_evidence":{"refusal_packet_sha256":"5ffd38dca7d8cd10b1133a44c703c2468deb0d4f08f31053678eb9dc873d6aa2",
                            "confirmed_non_self_matches":20777},
           "intersection":{"confirmed_non_self_matches_inside_trained_range":0,"any":False,
                           "confidence":"fixture"},"claim_boundary":"fixture"}
    proof_path=tmp_path/"consumption.json"; write_json(proof_path,proof)
    receipt={"ticket":"ISSUE-1433-TRAINED-CONSUMPTION-DECONTAMINATION","ts":"2026-08-19T00:00:00Z","schema":"issue1433-predeclared-trained-consumption-decontamination/v1",
             "status":"CLEAN_VS_TRAINED_CONSUMPTION","verdict":"CLEAN_VS_TRAINED_CONSUMPTION",
             "candidate_manifest_sha256":"4"*64,"candidate_batch_sha256":"5"*64,"training_consumption_set_sha256":sha(proof_path),
             "checkpoint_identity":{"manifest_sha256":"2"*64,"run_id":proof["trained_run"]["run_id"],
                                    "global_step":100,"tokens_seen":51200,
                                    "stream_receipt_sha256":"3"*64},
             "contamination_recheck":{"window_tokens":13,"windows_hashed":51189,
                                      "confirmed_matches":0,"verdict":"CLEAN_VS_TRAINED_CONSUMPTION"},
             "whole_corpus_refusal":{"packet_sha256":"5ffd38dca7d8cd10b1133a44c703c2468deb0d4f08f31053678eb9dc873d6aa2",
                                     "confirmed_non_self_matches":20777},
      "zero_intersection_proof":{"sha256":sha(proof_path),"intersection":0},"sha_convention":"sha256 over exact on-disk bytes",
             "claim_boundary":"fixture"}
    selection=tmp_path/"selection.json"; write_json(selection,receipt)
    doc["selection_evidence"]={"path":"selection.json","sha256":sha(selection),
      "batch_sha256":"5"*64,"verdict":"CLEAN_VS_TRAINED_CONSUMPTION",
      "candidate_manifest_sha256":"4"*64,"training_consumption_set_sha256":sha(proof_path),
      "checkpoint_manifest_sha256":"2"*64}
    wrong=dict(proof); wrong["question"]="different run"; wrong_path=tmp_path/"wrong.json"; write_json(wrong_path,wrong)
    monkeypatch.setattr(m,"load_frozen_slice_manifest",lambda *args:doc)
    monkeypatch.setattr(m,"verify_rule_derived_selection",lambda *args,**kwargs:None)
    monkeypatch.setattr(m,"read_eval_windows",lambda *args,**kwargs:[])
    monkeypatch.setattr(m,"verify_slice_excludes_ruled_sources",lambda *args,**kwargs:[])
    def forbidden(*args,**kwargs): raise AssertionError("checkpoint/model load reached")
    monkeypatch.setattr(m,"load_live_model",forbidden)
    code=m.main(["--evaluate","--shard-dir",str(tmp_path),"--nc",str(tmp_path),
                 "--training-consumption-set",str(wrong_path),"--checkpoint-dir",str(tmp_path),
                 "--checkpoint-kind","v5","--out",str(tmp_path/"out.json")])
    assert code==2
    assert "TRAINING_CONSUMPTION_SET_SHA_MISMATCH" in capsys.readouterr().err
def test_evaluator_does_not_import_execution_denied_historical_trainer():
    source=SCRIPT.read_text(encoding="utf-8")
    assert "from timeshare_pretrain" not in source
    assert "from w1_collapse_control_run" not in source
    m=load_module()
    assert m.HISTORICAL_EVAL_MODEL_CONTRACT == {"public_master":"db571b310b0ad20f8b257760cdc7c7ee69714929","w1_model_source_blob":"3dc627d49c5e48ceb8ab0c028eab68acb74e4f61","timeshare_source_blob":"ea367b382b975afd7afecbe86b6efa1148bd76ad","attention_heads":16,"max_sequence_length":1024}
