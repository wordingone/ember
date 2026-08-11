# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import sys
from pathlib import Path

import pytest
import torch

ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from q2_event_inputs import admit_event_inputs
import q2_input_manifest_builder as builder
import q2_model_lineage
import q2_momentum_lineage
from q2_input_manifest_builder import InputBuildRefusal, stage_event_inputs


def _config():
    return {
        "model":{"vocab":32,"hidden":2,"seq":4,"layers":1,"heads":1,"tied_embeddings":True,"grad_checkpointing":False},
        "objective":{"mtp_aux_heads":{"enabled":True,"n_heads":1,"weight":0.3}},
        "precision":{"qat":{"enabled":True}},
        "optimizer":{"lr_muon":0.02,"lr_adamw":0.0003},
    }


def _sources(tmp_path):
    prefix="backbone_model.layers.0.mlp."
    target=prefix+"gate_proj.weight"
    seed={
        target:torch.tensor([[1.,2.],[3.,4.]],dtype=torch.bfloat16),
        prefix+"up_proj.weight":torch.tensor([[.5,1.5],[2.5,3.5]],dtype=torch.bfloat16),
        prefix+"down_proj.weight":torch.tensor([[1.,2.],[4.,8.]],dtype=torch.bfloat16),
        "backbone_model.norm.weight":torch.tensor([1.,2.],dtype=torch.bfloat16),
    }
    result={}
    result["config"]=tmp_path/"config.json"; result["config"].write_text(json.dumps(_config()))
    result["seed_model"]=tmp_path/"model.pt"; torch.save(seed,result["seed_model"])
    result["seed_optimizer"]=tmp_path/"optimizer.pt"
    torch.save({"muon":{"state":{0:{"momentum_buffer":torch.ones((2,2),dtype=torch.float32)}}}},result["seed_optimizer"])
    result["seed_manifest"]=tmp_path/"manifest.json"
    result["seed_manifest"].write_text(json.dumps({"files":{"model.pt":hashlib.sha256(result["seed_model"].read_bytes()).hexdigest(),"optimizer.pt":hashlib.sha256(result["seed_optimizer"].read_bytes()).hexdigest()}}))
    result["b1m_receipt"]=tmp_path/"b1m.json"
    result["b1m_receipt"].write_text(json.dumps({"ticket":"CBASE-GROW-RUNG2-EVENT-B1M","run_id":"historical","verdict":"B1M_CAPTURED","u_pre":{"gate_key":target,"momentum_buffer_source":"B1 snapshot pre-grow momentum_buffer (parent-carried)"},"cache_paths":{"pre_momentum":"lost-pre-momentum.pt"}}))
    (tmp_path/"receipts").mkdir()
    result["b2_receipt"]=tmp_path/"receipts"/"b2.json"
    result["b2_receipt"].write_text(json.dumps({"ticket":"CBASE-GROW-RUNG2-EVENT-B2","run_id":"historical","verdict":"B2_REALIZED_PASS","operator_sha256":"5"*64,"eps":{"eps_sigma":0.1,"eps_seed":17,"banned_zero_assertion_passed":True},"cache":{"cache_path":"lost-grown.pt","distinct_from_eps0_cache":True},"realized_proof":{"eta_band_pass":True,"twin_cosine_pass":True}}))
    builder._CANONICAL_B2_RECEIPT_NAME=result["b2_receipt"].name
    builder._CANONICAL_B2_PATH_SUFFIX=("receipts",result["b2_receipt"].name)
    builder._CANONICAL_B2_RECEIPT_PATH=result["b2_receipt"].resolve()
    builder._CANONICAL_B2_RECEIPT_SHA256=hashlib.sha256(result["b2_receipt"].read_bytes()).hexdigest()
    builder._CANONICAL_B2_LINEAGE_RUN_ID="historical"
    builder._CANONICAL_B2_OPERATOR_SHA256="5"*64
    builder._CANONICAL_B2_EPS_SIGMA=0.1
    builder._CANONICAL_B2_EPS_SEED=17
    q2_model_lineage.CANONICAL_B2_RECEIPT_SHA256=builder._CANONICAL_B2_RECEIPT_SHA256
    q2_model_lineage.CANONICAL_B2_LINEAGE_RUN_ID=builder._CANONICAL_B2_LINEAGE_RUN_ID
    q2_model_lineage.CANONICAL_B2_OPERATOR_SHA256=builder._CANONICAL_B2_OPERATOR_SHA256
    q2_model_lineage.CANONICAL_B2_EPS_SIGMA=builder._CANONICAL_B2_EPS_SIGMA
    q2_model_lineage.CANONICAL_B2_EPS_SEED=builder._CANONICAL_B2_EPS_SEED
    return result,target


def test_builder_round_trips_closed_inputs_and_historical_batch_identity(tmp_path):
    source="a"*40; run="q2-input-test"; root=tmp_path/"custody"
    sources,target=_sources(tmp_path)
    cp,bp=stage_event_inputs(root=root,run_id=run,lineage_run_id="historical",source_commit=source,sources=sources,target_name=target,intermediate_size=8,config=_config())
    result=admit_event_inputs(custody_root=root,checkpoint_manifest_path=cp,batch_manifest_path=bp,expected_source_commit=source,expected_run_id=run)
    assert len(result["microsteps"])==8
    assert result["batch_sha256"]==json.loads(bp.read_text())["batch_sha256"]
    assert result["payload_sha256"]==json.loads(bp.read_text())["payload_sha256"]
    assert set(result["files"])=={"config","seed_model","seed_optimizer","grown_model","seed_manifest","b1m_receipt","b2_receipt","pre_momentum","grow_operator"}
    assert torch.load(result["files"]["pre_momentum"],weights_only=True).equal(torch.ones((2,2)))


def test_builder_accepts_canonical_bfloat16_seed_momentum_without_widening_arm_contract(tmp_path):
    source="a"*40; run="q2-bfloat16-momentum"; root=tmp_path/"custody"
    sources,target=_sources(tmp_path)
    canonical=torch.tensor([[0.5,-0.25],[0.125,0.75]],dtype=torch.bfloat16)
    torch.save({"muon":{"state":{0:{"momentum_buffer":canonical}}}},sources["seed_optimizer"])
    manifest=json.loads(sources["seed_manifest"].read_text(encoding="utf-8"))
    manifest["files"]["optimizer.pt"]=hashlib.sha256(sources["seed_optimizer"].read_bytes()).hexdigest()
    sources["seed_manifest"].write_text(json.dumps(manifest),encoding="utf-8")

    cp,bp=stage_event_inputs(root=root,run_id=run,lineage_run_id="historical",source_commit=source,sources=sources,target_name=target,intermediate_size=8,config=_config())
    admitted=admit_event_inputs(custody_root=root,checkpoint_manifest_path=cp,batch_manifest_path=bp,expected_source_commit=source,expected_run_id=run)
    persisted=torch.load(admitted["files"]["pre_momentum"],map_location="cpu",weights_only=True)

    assert persisted.dtype==torch.bfloat16
    assert torch.equal(persisted,canonical)


def test_builder_remints_missing_b2_and_b1m_cache_bytes_under_current_source(tmp_path):
    source="a"*40; root=tmp_path/"custody"; sources,target=_sources(tmp_path)
    cp,bp=stage_event_inputs(root=root,run_id="future-event",lineage_run_id="historical",source_commit=source,sources=sources,target_name=target,intermediate_size=8,config=_config())
    admitted=admit_event_inputs(custody_root=root,checkpoint_manifest_path=cp,batch_manifest_path=bp,expected_source_commit=source,expected_run_id="future-event")
    files=admitted["files"]
    runtime_config=json.loads(files["config"].read_text(encoding="utf-8"))
    assert runtime_config["schema"]=="q2-event-runtime-config-v1"
    assert runtime_config["source_commit"]==source
    assert runtime_config["execution_authority"]=="EMBER_LAB_Q2_EVENT_ONLY"
    assert runtime_config["scope"]=="TARGET_TENSOR_COUNTERFACTUAL"
    assert runtime_config["optimizer"]=={"lr_muon":0.02}
    assert runtime_config["historical_config_sha256"]==hashlib.sha256(sources["config"].read_bytes()).hexdigest()
    assert runtime_config["no_new_parallel_authority"] is True
    replay_receipt=json.loads(files["b2_receipt"].read_text(encoding="utf-8"))
    assert replay_receipt["schema"]=="q2-b2-replay-remint-receipt-v1"
    assert replay_receipt["source_commit"]==source
    assert replay_receipt["lineage_run_id"]=="historical"
    assert replay_receipt["historical"]["receipt_sha256"]==hashlib.sha256(sources["b2_receipt"].read_bytes()).hexdigest()
    assert replay_receipt["historical"]["operator_sha256"]=="5"*64
    assert replay_receipt["inputs"]["runtime_config_sha256"]==hashlib.sha256(files["config"].read_bytes()).hexdigest()
    assert replay_receipt["operator_sha256"]==hashlib.sha256(files["grow_operator"].read_bytes()).hexdigest()
    assert replay_receipt["output"]["grown_model_sha256"]==hashlib.sha256(files["grown_model"].read_bytes()).hexdigest()
    assert replay_receipt["receipt_sha256"]==hashlib.sha256((json.dumps({key:value for key,value in replay_receipt.items() if key!="receipt_sha256"},sort_keys=True,separators=(",",":"))+"\n").encode()).hexdigest()
    grown=torch.load(files["grown_model"],map_location="cpu",weights_only=True)
    model=q2_model_lineage.validate_model_lineage(
        live_state=grown,
        seed_manifest_path=files["seed_manifest"],
        seed_model_path=files["seed_model"],
        grown_model_path=files["grown_model"],
        b2_receipt_path=files["b2_receipt"],
        grow_operator_path=files["grow_operator"],
        runtime_config_path=files["config"],
        expected_run_id="historical",
        expected_source_commit=source,
        n_layers=1,
    )
    pre=torch.load(files["pre_momentum"],map_location="cpu",weights_only=True)
    momentum=q2_momentum_lineage.validate_momentum_lineage(
        seed_manifest_path=files["seed_manifest"],
        seed_model_path=files["seed_model"],
        seed_optimizer_path=files["seed_optimizer"],
        b1m_receipt_path=files["b1m_receipt"],
        persisted_pre_momentum_path=files["pre_momentum"],
        target_name=target,
        reset_momentum=torch.zeros((4,2),dtype=torch.float32),
        transplant_momentum=torch.cat([pre,pre],dim=0),
        expected_run_id="historical",
    )
    assert model["historical_grow_operator_sha256"]=="5"*64
    assert model["replay_operator_sha256"]==hashlib.sha256(files["grow_operator"].read_bytes()).hexdigest()
    assert momentum["historical_pre_momentum_name"]=="lost-pre-momentum.pt"


def test_builder_refuses_overwrite_and_unknown_source(tmp_path):
    sources,target=_sources(tmp_path); root=tmp_path/"custody"
    stage_event_inputs(root=root,run_id="r",lineage_run_id="historical",source_commit="a"*40,sources=sources,target_name=target,intermediate_size=8,config=_config())
    with pytest.raises(InputBuildRefusal):
        stage_event_inputs(root=root,run_id="r",lineage_run_id="historical",source_commit="a"*40,sources=sources,target_name=target,intermediate_size=8,config=_config())
    sources["foreign"]=sources["config"]
    with pytest.raises(InputBuildRefusal,match="INPUT_CHECKPOINT_SCHEMA_INVALID"):
        stage_event_inputs(root=tmp_path/"other",run_id="r",lineage_run_id="historical",source_commit="a"*40,sources=sources,target_name=target,intermediate_size=8,config=_config())


def test_builder_refuses_nonhex_historical_operator_hash_before_outputs(tmp_path):
    sources,target=_sources(tmp_path)
    receipt=json.loads(sources["b2_receipt"].read_text(encoding="utf-8"))
    receipt["operator_sha256"]="z"*64
    sources["b2_receipt"].write_text(json.dumps(receipt),encoding="utf-8")
    root=tmp_path/"custody"

    with pytest.raises(InputBuildRefusal,match="INPUT_B2_RECEIPT_IDENTITY_MISMATCH"):
        stage_event_inputs(root=root,run_id="r",lineage_run_id="historical",source_commit="a"*40,sources=sources,target_name=target,intermediate_size=8,config=_config())

    assert not (root/"checkpoint-manifest.json").exists()


@pytest.mark.parametrize("mutation", ["zero_sigma", "foreign_seed", "foreign_name", "same_suffix_foreign_root"])
def test_builder_refuses_noncanonical_b2_receipt_or_numeric_law(tmp_path,mutation):
    sources,target=_sources(tmp_path)
    receipt=json.loads(sources["b2_receipt"].read_text(encoding="utf-8"))
    if mutation=="zero_sigma":
        receipt["eps"]["eps_sigma"]=0
    elif mutation=="foreign_seed":
        receipt["eps"]["eps_seed"]=18
    elif mutation=="foreign_name":
        foreign=tmp_path/"foreign-b2.json"
        foreign.write_bytes(sources["b2_receipt"].read_bytes())
        sources["b2_receipt"]=foreign
    else:
        foreign=tmp_path/"foreign-root"/"receipts"/sources["b2_receipt"].name
        foreign.parent.mkdir(parents=True)
        foreign.write_bytes(sources["b2_receipt"].read_bytes())
        sources["b2_receipt"]=foreign
    if mutation not in {"foreign_name", "same_suffix_foreign_root"}:
        sources["b2_receipt"].write_text(json.dumps(receipt),encoding="utf-8")
    code="INPUT_B2_RECEIPT_PATH_MISMATCH" if mutation in {"foreign_name", "same_suffix_foreign_root"} else "INPUT_B2_RECEIPT_IDENTITY_MISMATCH"

    with pytest.raises(InputBuildRefusal,match=code):
        stage_event_inputs(root=tmp_path/"custody",run_id="r",lineage_run_id="historical",source_commit="a"*40,sources=sources,target_name=target,intermediate_size=8,config=_config())


def test_builder_refuses_foreign_symlink_alias_to_canonical_b2_receipt(tmp_path):
    sources,target=_sources(tmp_path)
    canonical=sources["b2_receipt"]
    foreign=tmp_path/"foreign-root"/"receipts"/canonical.name
    foreign.parent.mkdir(parents=True)
    try:
        foreign.symlink_to(canonical)
    except OSError as exc:
        pytest.skip(f"host cannot create file symlink: {exc}")
    sources["b2_receipt"]=foreign
    root=tmp_path/"custody"

    with pytest.raises(InputBuildRefusal,match="INPUT_B2_RECEIPT_PATH_MISMATCH"):
        stage_event_inputs(root=root,run_id="r",lineage_run_id="historical",source_commit="a"*40,sources=sources,target_name=target,intermediate_size=8,config=_config())

    assert not (root/"checkpoint-manifest.json").exists()


def test_builder_refuses_dot_segment_that_hides_foreign_symlink_component(tmp_path):
    sources,target=_sources(tmp_path)
    foreign_target=tmp_path/"foreign-target"
    foreign_target.mkdir()
    foreign_link=tmp_path/"foreign-link"
    try:
        foreign_link.symlink_to(foreign_target,target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"host cannot create directory symlink: {exc}")
    sources["b2_receipt"]=foreign_link/".."/"receipts"/sources["b2_receipt"].name
    root=tmp_path/"custody"

    with pytest.raises(InputBuildRefusal,match="INPUT_B2_RECEIPT_PATH_MISMATCH"):
        stage_event_inputs(root=root,run_id="r",lineage_run_id="historical",source_commit="a"*40,sources=sources,target_name=target,intermediate_size=8,config=_config())

    assert not (root/"checkpoint-manifest.json").exists()


def test_builder_refuses_config_argument_that_differs_from_bound_file(tmp_path):
    sources,target=_sources(tmp_path)
    foreign_config=_config()
    foreign_config["model"]["vocab"]=31
    root=tmp_path/"custody"

    with pytest.raises(InputBuildRefusal,match="INPUT_CONFIG_ARGUMENT_MISMATCH"):
        stage_event_inputs(root=root,run_id="r",lineage_run_id="historical",source_commit="a"*40,sources=sources,target_name=target,intermediate_size=8,config=foreign_config)

    assert not (root/"checkpoint-manifest.json").exists()


def test_large_final_artifact_uses_same_volume_hardlink_without_large_temp(tmp_path,monkeypatch):
    source=tmp_path/"large.bin"; source.write_bytes(b"immutable")
    target=tmp_path/"custody"/"inputs"/"large.bin"
    monkeypatch.setattr(builder,"_MAX_TEMP",1)
    row=builder._atomic_copy(source,target)
    assert row["bytes"]==9 and target.read_bytes()==b"immutable"
    assert target.stat().st_ino==source.stat().st_ino
    target.unlink(); assert source.read_bytes()==b"immutable"


def test_grown_model_can_exceed_generic_tensor_limit_without_weakening_momentum_limit(tmp_path,monkeypatch):
    sources,target=_sources(tmp_path); root=tmp_path/"custody"
    monkeypatch.setattr(builder,"_MAX_TEMP",1)
    monkeypatch.setattr(builder,"_MAX_GROWN_MODEL_TEMP",4096)
    with pytest.raises(InputBuildRefusal,match="INPUT_TEMP_EXCEEDS_4GIB"):
        stage_event_inputs(root=root,run_id="r",lineage_run_id="historical",source_commit="a"*40,sources=sources,target_name=target,intermediate_size=8,config=_config())
    assert (root/"inputs"/"grown_model.pt").is_file()
    assert not (root/"inputs"/"pre_momentum.pt").exists()


def test_grown_model_specific_limit_refuses_and_cleans_oversized_temporary(tmp_path):
    target=tmp_path/"custody"/"inputs"/"grown_model.pt"
    with pytest.raises(InputBuildRefusal,match="INPUT_GROWN_MODEL_TEMP_EXCEEDS_4_5GIB"):
        builder._atomic_torch(torch.tensor([1],dtype=torch.int64),target,max_temp_bytes=1,overflow_code="INPUT_GROWN_MODEL_TEMP_EXCEEDS_4_5GIB")
    assert not target.exists()
    assert list(target.parent.glob(".grown_model.pt.*.tmp"))==[]
