# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Execute and seal the exact host-commit dry run for issue #675."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path

import torch

from q2_event_inputs import admit_event_inputs
from q2_host_commit_probe import HostCommitProbe, write_trace_atomic
from q2_host_commit_simulation import validate_host_commit_measurement
from q2_rung2_runtime import build_rung2_model


class MeasuredDryRunRefusal(ValueError):
    """Named refusal before a dispatch host-commit receipt exists."""


def _refuse(code: str) -> None:
    raise MeasuredDryRunRefusal(code)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    if path.exists(): _refuse("DRY_RUN_OUTPUT_ALREADY_EXISTS")
    raw=json.dumps(value,sort_keys=True,separators=(",", ":")).encode("utf-8")
    fd,temporary=tempfile.mkstemp(prefix=f".{path.name}.",suffix=".tmp",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as handle: handle.write(raw); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary,path)
    except Exception:
        try: os.unlink(temporary)
        except OSError: pass
        raise


def _bound_config_path(root: Path, checkpoint_manifest_path: Path) -> Path:
    try:
        manifest=json.loads(checkpoint_manifest_path.read_text(encoding="utf-8"))
        logical=manifest["files"]["config"]["logical_path"]
        if not isinstance(logical,str) or not logical or Path(logical).is_absolute() or ".." in Path(logical).parts:
            _refuse("DRY_RUN_CONFIG_BINDING_INVALID")
        path=(root/logical).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file() or path.is_symlink(): _refuse("DRY_RUN_CONFIG_BINDING_INVALID")
        return path
    except MeasuredDryRunRefusal: raise
    except (OSError,UnicodeError,json.JSONDecodeError,KeyError,TypeError): _refuse("DRY_RUN_CONFIG_BINDING_INVALID")


def run_measured_dry_run(
    *, run_id: str, source_commit: str, custody_root: Path,
    checkpoint_manifest_path: Path, batch_manifest_path: Path,
    producer_path: Path, trace_path: Path, receipt_path: Path,
) -> dict[str, object]:
    """Retain each real phase allocation and measure cumulative commit high-water."""

    root=Path(custody_root).resolve(strict=True)
    checkpoint_manifest_path=Path(checkpoint_manifest_path).resolve(strict=True)
    batch_manifest_path=Path(batch_manifest_path).resolve(strict=True)
    producer_path=Path(producer_path).resolve(strict=True)
    config_path=_bound_config_path(root,checkpoint_manifest_path)
    bindings={
        "measurement_tool_sha256":_sha(Path(__file__).resolve()),
        "config_sha256":_sha(config_path),
        "checkpoint_manifest_sha256":_sha(checkpoint_manifest_path),
        "batch_manifest_sha256":_sha(batch_manifest_path),
        "producer_sha256":_sha(producer_path),
    }
    probe=HostCommitProbe(job_id=run_id,source_commit=source_commit,bindings=bindings)
    held=[]
    try:
        probe.begin_phase("model_reconstruction")
        inputs=admit_event_inputs(custody_root=root,checkpoint_manifest_path=checkpoint_manifest_path,batch_manifest_path=batch_manifest_path,expected_source_commit=source_commit,expected_run_id=run_id)
        files=inputs["files"]
        config=json.loads(files["config"].read_text(encoding="utf-8"))
        model,_vocab,_hidden,_mtp=build_rung2_model(config,intermediate_size=inputs["intermediate_size"],device="cpu")
        grown=torch.load(files["grown_model"],map_location="cpu",weights_only=True)
        model.load_state_dict(grown,strict=True); held.extend([inputs,config,model,grown]); probe.sample(); probe.end_phase()

        probe.begin_phase("optimizer_momentum")
        optimizer=torch.load(files["seed_optimizer"],map_location="cpu",weights_only=True)
        momentum=torch.load(files["pre_momentum"],map_location="cpu",weights_only=True)
        held.extend([optimizer,momentum]); probe.sample(); probe.end_phase()

        probe.begin_phase("frozen_batch")
        frozen=[]
        for row in inputs["microsteps"]:
            frozen.extend([row["x"].clone(),row["y0"].clone(),*[value.clone() for value in row["y_mtp"]]])
        held.append(frozen); probe.sample(); probe.end_phase()

        probe.begin_phase("capture_staging")
        target=model.get_parameter(inputs["target_name"])
        capture_staging=[target.detach().cpu().float().clone() for _ in range(6)]
        non_target={name:value.detach().cpu().clone() for name,value in model.state_dict().items() if name!=inputs["target_name"]}
        held.extend([capture_staging,non_target]); probe.sample(); probe.end_phase()

        probe.begin_phase("python_cuda_host_overhead")
        if not torch.cuda.is_available(): _refuse("DRY_RUN_CUDA_UNAVAILABLE")
        model.to("cuda"); torch.cuda.synchronize(); held.append(torch.empty(1,device="cuda")); probe.sample(); probe.end_phase()
        trace=probe.finish(exit_code=0)
    except MeasuredDryRunRefusal: raise
    except Exception: _refuse("DRY_RUN_PHASE_FAILED")
    write_trace_atomic(trace_path,trace)
    receipt=validate_host_commit_measurement(trace_path)
    _atomic_json(receipt_path,receipt)
    return receipt


def main() -> int:
    parser=argparse.ArgumentParser()
    for name in ("run-id","source-commit","custody-root","checkpoint-manifest","batch-manifest","producer","trace","receipt"):
        parser.add_argument(f"--{name}",required=True)
    args=parser.parse_args()
    receipt=run_measured_dry_run(run_id=args.run_id,source_commit=args.source_commit,custody_root=Path(args.custody_root),checkpoint_manifest_path=Path(args.checkpoint_manifest),batch_manifest_path=Path(args.batch_manifest),producer_path=Path(args.producer),trace_path=Path(args.trace),receipt_path=Path(args.receipt))
    print(json.dumps({"schema":"q2-measured-dry-run-result-v1","receipt_sha256":receipt["receipt_sha256"],"event_credit":False},sort_keys=True))
    return 0


if __name__=="__main__": raise SystemExit(main())
