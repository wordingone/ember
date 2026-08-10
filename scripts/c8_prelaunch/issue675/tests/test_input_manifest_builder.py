# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from q2_event_inputs import admit_event_inputs
import q2_input_manifest_builder as builder
from q2_input_manifest_builder import InputBuildRefusal, stage_event_inputs


def _config():
    return {"model":{"vocab":32,"seq":4},"objective":{"mtp_aux_heads":{"n_heads":1}}}


def _sources(tmp_path):
    names=("config","seed_model","seed_optimizer","grown_model","seed_manifest","b1m_receipt","b2_receipt","pre_momentum","grow_operator")
    result={}
    for name in names:
        path=tmp_path/f"source-{name}.bin"; path.write_bytes((name+"\n").encode()); result[name]=path
    return result


def test_builder_round_trips_closed_inputs_and_historical_batch_identity(tmp_path):
    source="a"*40; run="q2-input-test"; root=tmp_path/"custody"
    cp,bp=stage_event_inputs(root=root,run_id=run,lineage_run_id="historical",source_commit=source,sources=_sources(tmp_path),target_name="target",intermediate_size=8,config=_config())
    result=admit_event_inputs(custody_root=root,checkpoint_manifest_path=cp,batch_manifest_path=bp,expected_source_commit=source,expected_run_id=run)
    assert len(result["microsteps"])==8
    assert result["batch_sha256"]==json.loads(bp.read_text())["batch_sha256"]
    assert result["payload_sha256"]==json.loads(bp.read_text())["payload_sha256"]


def test_builder_refuses_overwrite_and_unknown_source(tmp_path):
    sources=_sources(tmp_path); root=tmp_path/"custody"
    stage_event_inputs(root=root,run_id="r",lineage_run_id="historical",source_commit="a"*40,sources=sources,target_name="target",intermediate_size=8,config=_config())
    with pytest.raises(InputBuildRefusal):
        stage_event_inputs(root=root,run_id="r",lineage_run_id="historical",source_commit="a"*40,sources=sources,target_name="target",intermediate_size=8,config=_config())
    sources["foreign"]=sources["config"]
    with pytest.raises(InputBuildRefusal,match="INPUT_CHECKPOINT_SCHEMA_INVALID"):
        stage_event_inputs(root=tmp_path/"other",run_id="r",lineage_run_id="historical",source_commit="a"*40,sources=sources,target_name="target",intermediate_size=8,config=_config())


def test_large_final_artifact_uses_same_volume_hardlink_without_large_temp(tmp_path,monkeypatch):
    source=tmp_path/"large.bin"; source.write_bytes(b"immutable")
    target=tmp_path/"custody"/"inputs"/"large.bin"
    monkeypatch.setattr(builder,"_MAX_TEMP",1)
    row=builder._atomic_copy(source,target)
    assert row["bytes"]==9 and target.read_bytes()==b"immutable"
    assert target.stat().st_ino==source.stat().st_ino
    target.unlink(); assert source.read_bytes()==b"immutable"
