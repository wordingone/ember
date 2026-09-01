# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
import os
import sys
from pathlib import Path

import torch

ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
import q2_measured_dry_run as runner
import pytest


class Tiny(torch.nn.Module):
    def __init__(self):
        super().__init__(); self.target=torch.nn.Parameter(torch.ones((2,2))); self.other=torch.nn.Parameter(torch.ones(1)); self.proj=torch.nn.Linear(2,3,bias=False)


class Probe:
    def __init__(self,**kwargs): self.rows=[]; self.bindings=kwargs["bindings"]
    def begin_phase(self,name): self.rows.append(name)
    def sample(self): return 2
    def end_phase(self): pass
    def finish(self,exit_code):
        phases=[]; previous=1
        producers=("checkpoint_writer","checkpoint_writer","training_data_loader","checkpoint_writer","telemetry_buffer")
        for i,(name,producer) in enumerate(zip(self.rows,producers)):
            phases.append({"ordinal":i,"name":name,"producer_kind":producer,"baseline_commit_bytes":previous,"peak_commit_bytes":previous+1,"sample_count":2,"measurement_source":"os_commit_probe"}); previous+=1
        return {"schema_version":"q2-host-commit-measurement-v1","job_id":"r","measurement_mode":"bounded_dry_run","source_commit":"a"*40,"process":{"pid":1,"started_at_ms":1,"ended_at_ms":2,"exit_code":0},"bindings":self.bindings,"phases":phases}


def test_measured_dry_run_executes_exact_five_phases_and_seals_receipt(tmp_path,monkeypatch):
    root=tmp_path/"custody"; root.mkdir(); cp=root/"checkpoint.json"; bp=root/"batch.json"; producer=root/"producer.py"
    config=root/"config.json"; config.write_text(json.dumps({"model":{"seq":2,"hidden":2,"layers":1,"heads":1}}),encoding="utf-8")
    cp.write_text(json.dumps({"files":{"config":{"logical_path":"config.json"}}}),encoding="utf-8"); bp.write_text("batch",encoding="utf-8"); producer.write_text("producer",encoding="utf-8")
    model=Tiny(); grown=root/"grown.pt"; optimizer=root/"optimizer.pt"; momentum=root/"momentum.pt"
    torch.save(model.state_dict(),grown); torch.save({"state":{}},optimizer); torch.save(torch.ones((1,2)),momentum)
    admitted={"files":{"config":config,"grown_model":grown,"seed_optimizer":optimizer,"pre_momentum":momentum},"microsteps":[{"x":torch.ones((1,2),dtype=torch.int64),"y0":torch.ones((1,2),dtype=torch.int64),"y_mtp":[]}],"lineage_run_id":"historical","target_name":"target","intermediate_size":2}
    monkeypatch.setattr(runner,"HostCommitProbe",Probe); monkeypatch.setattr(runner,"admit_event_inputs",lambda **kwargs:admitted)
    monkeypatch.setattr(runner,"build_rung2_model",lambda *a,**k:(model,4,2,0)); monkeypatch.setattr(torch.cuda,"is_available",lambda:True); monkeypatch.setattr(torch.cuda,"synchronize",lambda:None)
    monkeypatch.setattr(model,"to",lambda device:model)
    monkeypatch.setattr(runner,"_touched_cpu_reserve",lambda _bytes:[torch.zeros(1)])
    cuda={"schema":"q2-cuda-allocability-receipt-v1","receipt_sha256":"d"*64}
    monkeypatch.setattr(runner,"_cuda_allocability_probe",lambda **_kwargs:cuda)
    receipt=runner.run_measured_dry_run(run_id="r",source_commit="a"*40,custody_root=root,checkpoint_manifest_path=cp,batch_manifest_path=bp,producer_path=producer,trace_path=root/"trace.json",receipt_path=root/"receipt.json",cuda_receipt_path=root/"cuda.json")
    assert [row["name"] for row in receipt["phases"]]==["model_reconstruction","optimizer_momentum","frozen_batch","capture_staging","python_cuda_host_overhead"]
    assert receipt["event_credit"] is False and (root/"receipt.json").exists()
    assert json.loads((root/"cuda.json").read_text())==cuda


def test_measured_dry_run_refuses_config_path_escape_before_probe(tmp_path,monkeypatch):
    root=tmp_path/"custody"; root.mkdir(); outside=tmp_path/"outside.json"; outside.write_text("{}")
    cp=root/"checkpoint.json"; cp.write_text(json.dumps({"files":{"config":{"logical_path":"../outside.json"}}}))
    bp=root/"batch.json"; bp.write_text("batch"); producer=root/"producer.py"; producer.write_text("producer")
    with pytest.raises(runner.MeasuredDryRunRefusal,match="DRY_RUN_CONFIG_BINDING_INVALID"):
        runner.run_measured_dry_run(run_id="r",source_commit="a"*40,custody_root=root,checkpoint_manifest_path=cp,batch_manifest_path=bp,producer_path=producer,trace_path=root/"trace.json",receipt_path=root/"receipt.json",cuda_receipt_path=root/"cuda.json")


def test_measured_dry_run_prices_cpu_integrity_and_qat_snapshots_together():
    model=Tiny()
    baseline,qat=runner._runtime_host_snapshots(model)
    assert set(baseline)==set(model.state_dict())
    assert len(qat)==1
    assert all(value.device.type=="cpu" and value.is_contiguous() for value in baseline.values())
    assert all(value.device.type=="cpu" and value.is_contiguous() for value in qat)
    assert torch.equal(qat[0],model.proj.weight.detach())


def test_activation_offload_bounds_are_closed_and_monotonic():
    small={"model":{"seq":8,"hidden":4,"layers":2,"heads":1}}
    large={"model":{"seq":16,"hidden":4,"layers":2,"heads":1}}
    small_host,small_scratch=runner._activation_offload_bounds(small,intermediate_size=8,model_bytes=1024)
    large_host,large_scratch=runner._activation_offload_bounds(large,intermediate_size=8,model_bytes=1024)
    assert small_host > 1024 and small_scratch > 0
    assert large_host > small_host and large_scratch > small_scratch


def test_cuda_allocability_probe_refuses_reported_free_but_unallocatable(monkeypatch):
    config={"model":{"seq":8,"hidden":4,"layers":2,"heads":1}}
    monkeypatch.setattr(torch.cuda,"mem_get_info",lambda:(24*1024**3,24*1024**3))
    monkeypatch.setattr(torch.cuda,"synchronize",lambda:None)
    monkeypatch.setattr(torch.cuda,"empty_cache",lambda:None)
    monkeypatch.setattr(torch,"empty",lambda *a,**k: (_ for _ in ()).throw(torch.OutOfMemoryError("WDDM")))
    with pytest.raises(runner.MeasuredDryRunRefusal,match="DRY_RUN_CUDA_NOT_ALLOCATABLE"):
        runner._cuda_allocability_probe(config=config,intermediate_size=8,model_bytes=1024,run_id="r",source_commit="a"*40,config_sha256="b"*64,measurement_tool_sha256="c"*64,checkpoint_manifest_sha256="d"*64)


def test_activation_offload_bound_covers_scaled_saved_tensors():
    class Block(torch.nn.Module):
        def __init__(self):
            super().__init__(); self.up=torch.nn.Linear(4,8,bias=False); self.down=torch.nn.Linear(8,4,bias=False)
        def forward(self,x): return x+self.down(torch.nn.functional.silu(self.up(x)))
    model=torch.nn.Sequential(Block(),Block())
    packed=[]
    def pack(value): packed.append(value.numel()*value.element_size()); return value
    with torch.autograd.graph.saved_tensors_hooks(pack,lambda value:value):
        model(torch.ones((1,8,4),requires_grad=True)).sum().backward()
    model_bytes=runner._unique_model_storage_bytes(model)
    host,_scratch=runner._activation_offload_bounds(
        {"model":{"seq":8,"hidden":4,"layers":2,"heads":1}},
        intermediate_size=8,model_bytes=model_bytes,
    )
    assert sum(packed) <= host


def test_measured_dry_run_refuses_existing_cuda_output_before_other_publication(tmp_path):
    root=tmp_path/"custody"; root.mkdir()
    cuda=root/"cuda.json"; cuda.write_text("preserved")
    with pytest.raises(runner.MeasuredDryRunRefusal,match="DRY_RUN_OUTPUT_ALREADY_EXISTS"):
        runner.run_measured_dry_run(
            run_id="r",source_commit="a"*40,custody_root=root,
            checkpoint_manifest_path=root/"missing-checkpoint.json",
            batch_manifest_path=root/"missing-batch.json",producer_path=root/"missing.py",
            trace_path=root/"trace.json",receipt_path=root/"receipt.json",cuda_receipt_path=cuda,
        )
    assert not (root/"trace.json").exists() and not (root/"receipt.json").exists()
    assert cuda.read_text()=="preserved"


def test_bundle_publication_rolls_back_when_second_link_fails(tmp_path,monkeypatch):
    staged=[]
    for name in ("trace","host","cuda"):
        temporary=runner._stage_json(tmp_path/f"{name}.json",{"name":name})
        staged.append((temporary,tmp_path/f"{name}.json"))
    real_link=os.link; calls=[]
    def fail_second(source,target):
        calls.append(target)
        if len(calls)==2: raise OSError("injected")
        return real_link(source,target)
    monkeypatch.setattr(runner.os,"link",fail_second)
    with pytest.raises(OSError,match="injected"):
        runner._publish_bundle(staged)
    assert not any((tmp_path/f"{name}.json").exists() for name in ("trace","host","cuda"))
