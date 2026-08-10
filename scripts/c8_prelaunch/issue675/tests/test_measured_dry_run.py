# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import json
import sys
from pathlib import Path

import torch

ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
import q2_measured_dry_run as runner
import pytest


class Tiny(torch.nn.Module):
    def __init__(self):
        super().__init__(); self.target=torch.nn.Parameter(torch.ones((2,2))); self.other=torch.nn.Parameter(torch.ones(1))


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
    config=root/"config.json"; config.write_text("{}",encoding="utf-8")
    cp.write_text(json.dumps({"files":{"config":{"logical_path":"config.json"}}}),encoding="utf-8"); bp.write_text("batch",encoding="utf-8"); producer.write_text("producer",encoding="utf-8")
    model=Tiny(); grown=root/"grown.pt"; optimizer=root/"optimizer.pt"; momentum=root/"momentum.pt"
    torch.save(model.state_dict(),grown); torch.save({"state":{}},optimizer); torch.save(torch.ones((1,2)),momentum)
    admitted={"files":{"config":config,"grown_model":grown,"seed_optimizer":optimizer,"pre_momentum":momentum},"microsteps":[{"x":torch.ones((1,2),dtype=torch.int64),"y0":torch.ones((1,2),dtype=torch.int64),"y_mtp":[]}],"lineage_run_id":"historical","target_name":"target","intermediate_size":2}
    monkeypatch.setattr(runner,"HostCommitProbe",Probe); monkeypatch.setattr(runner,"admit_event_inputs",lambda **kwargs:admitted)
    monkeypatch.setattr(runner,"build_rung2_model",lambda *a,**k:(model,4,2,0)); monkeypatch.setattr(torch.cuda,"is_available",lambda:True); monkeypatch.setattr(torch.cuda,"synchronize",lambda:None)
    monkeypatch.setattr(model,"to",lambda device:model); monkeypatch.setattr(torch,"empty",lambda *a,**k:torch.zeros(1))
    receipt=runner.run_measured_dry_run(run_id="r",source_commit="a"*40,custody_root=root,checkpoint_manifest_path=cp,batch_manifest_path=bp,producer_path=producer,trace_path=root/"trace.json",receipt_path=root/"receipt.json")
    assert [row["name"] for row in receipt["phases"]]==["model_reconstruction","optimizer_momentum","frozen_batch","capture_staging","python_cuda_host_overhead"]
    assert receipt["event_credit"] is False and (root/"receipt.json").exists()


def test_measured_dry_run_refuses_config_path_escape_before_probe(tmp_path,monkeypatch):
    root=tmp_path/"custody"; root.mkdir(); outside=tmp_path/"outside.json"; outside.write_text("{}")
    cp=root/"checkpoint.json"; cp.write_text(json.dumps({"files":{"config":{"logical_path":"../outside.json"}}}))
    bp=root/"batch.json"; bp.write_text("batch"); producer=root/"producer.py"; producer.write_text("producer")
    with pytest.raises(runner.MeasuredDryRunRefusal,match="DRY_RUN_CONFIG_BINDING_INVALID"):
        runner.run_measured_dry_run(run_id="r",source_commit="a"*40,custody_root=root,checkpoint_manifest_path=cp,batch_manifest_path=bp,producer_path=producer,trace_path=root/"trace.json",receipt_path=root/"receipt.json")
