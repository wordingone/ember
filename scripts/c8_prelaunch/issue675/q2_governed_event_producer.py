# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Current-authority governed vertical producer for issue #675.

The entry point is admitted only by Ember Lab.  It consumes immutable inputs,
mints the future B3 gradient receipt inside the job, and writes the capture
manifest last.  It is not a general trainer or checkpoint producer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Mapping

import torch

import q2_actual_event_adapter as _adapter
import q2_muon_primitives as _muon
import q2_rung2_runtime as _runtime
from q2_actual_event_adapter import capture_actual_event
from q2_event_inputs import admit_event_inputs
from q2_rung2_runtime import (
    build_rung2_model,
    compute_frozen_batch_gradient,
    replay_target_only_loss,
)


GOVERNED_VERTICAL_MODE = "governed-vertical"
_RUN = re.compile(r"[A-Za-z0-9_.-]{1,128}")


class GovernedEventRefusal(ValueError):
    """Named refusal before a selectable actual-event capture exists."""


def _refuse(code: str) -> None:
    raise GovernedEventRefusal(code)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _muon_learning_rate(config: object) -> float:
    if not isinstance(config, dict):
        _refuse("EVENT_MUON_LEARNING_RATE_INVALID")
    optimizer = config.get("optimizer")
    if not isinstance(optimizer, dict):
        _refuse("EVENT_MUON_LEARNING_RATE_INVALID")
    value = optimizer.get("lr_muon")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _refuse("EVENT_MUON_LEARNING_RATE_INVALID")
    result = float(value)
    if not math.isfinite(result) or result <= 0.0:
        _refuse("EVENT_MUON_LEARNING_RATE_INVALID")
    return result


def _atomic_bytes(path: Path, payload: bytes) -> None:
    if path.exists():
        _refuse("EVENT_OUTPUT_ALREADY_EXISTS")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try: os.unlink(temporary)
        except OSError: pass
        raise


def _atomic_torch(path: Path, tensor: torch.Tensor) -> None:
    if path.exists():
        _refuse("EVENT_OUTPUT_ALREADY_EXISTS")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    try:
        torch.save(tensor, temporary)
        with open(temporary, "rb+") as handle: os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try: os.unlink(temporary)
        except OSError: pass
        raise


def _preflight(path: Path, run_id: str) -> dict[str, object]:
    try: value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError): _refuse("EVENT_PREFLIGHT_MALFORMED")
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "ember-lab-dispatch-preflight-v1"
        or value.get("result") != "PREFLIGHT_PASSED"
        or value.get("job_id") != run_id
        or not isinstance(value.get("source_commit"), str)
        or re.fullmatch(r"[0-9a-f]{40}", value["source_commit"]) is None
    ): _refuse("EVENT_PREFLIGHT_NOT_GREEN")
    return value


def _copy_bindings(
    *, root: Path, config: Path, b2: Path, b1m: Path, b3: Path, batch: Path,
    threshold: Path, verifier: Path,
) -> dict[str, Path]:
    sources = {
        "source_sha256": Path(_adapter.__file__).resolve(),
        "config_sha256": config,
        "checkpoint_sha256": b2,
        "optimizer_sha256": Path(_muon.__file__).resolve(),
        "momentum_sha256": b1m,
        "b3_receipt_sha256": b3,
        "batch_sha256": batch,
        "replay_sha256": Path(_runtime.__file__).resolve(),
        "threshold_sha256": threshold,
        "verifier_sha256": verifier,
    }
    result = {}
    for index, key in enumerate(sorted(sources)):
        source = Path(sources[key]).resolve(strict=True)
        destination = root / f"binding-{index:02d}-{key}.bin"
        _atomic_bytes(destination, source.read_bytes())
        result[key] = destination
    return result


def _mint_b3(
    *, root: Path, run_id: str, batch_sha256: str, target_name: str,
    gradient: torch.Tensor,
) -> tuple[Path, Path]:
    gradient_path = root / f"{run_id}-grad-post-gate.pt"
    receipt_path = root / f"{run_id}-b3.json"
    _atomic_torch(gradient_path, gradient.to(device="cpu", dtype=torch.float32).contiguous())
    receipt = {
        "ticket": "CBASE-GROW-RUNG2-EVENT-B3", "run_id": run_id,
        "batch_pin_check": {"b1m_sha256": batch_sha256, "b3_recomputed_sha256": batch_sha256, "match": True},
        "cache_paths": {"grad_post_gate": gradient_path.name},
        "cache_sha256": {"grad_post_gate": _sha(gradient_path)},
        "gradient_lineage": {
            "target_name": target_name, "dtype": "float32", "shape": list(gradient.shape),
            "source": "pinned-batch-backward", "batch_sha256": batch_sha256,
        },
        "verdict": "B3_CAPTURED",
    }
    _atomic_bytes(receipt_path, _canonical(receipt))
    return gradient_path, receipt_path


def run_governed_vertical(args: argparse.Namespace) -> Path:
    run_id = args.run_id
    if not isinstance(run_id, str) or _RUN.fullmatch(run_id) is None: _refuse("EVENT_RUN_ID_INVALID")
    root = Path(args.custody_root).resolve(strict=True)
    preflight_path = root / "dispatch-preflight.json"
    preflight = _preflight(preflight_path, run_id)
    inputs = admit_event_inputs(
        custody_root=root, checkpoint_manifest_path=Path(args.checkpoint_manifest),
        batch_manifest_path=Path(args.batch_manifest), expected_source_commit=preflight["source_commit"],
        expected_run_id=run_id,
    )
    files: Mapping[str, Path] = inputs["files"]
    try:
        config = json.loads(files["config"].read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _refuse("EVENT_CONFIG_INVALID")
    learning_rate = _muon_learning_rate(config)
    try:
        model, _vocab, _hidden, _mtp = build_rung2_model(config, intermediate_size=inputs["intermediate_size"], device="cuda")
        grown = torch.load(files["grown_model"], map_location="cpu", weights_only=True)
        model.load_state_dict(grown, strict=True)
        model.to("cuda")
    except Exception:
        _refuse("EVENT_MODEL_RECONSTRUCTION_FAILED")
    gradient, _pre_loss, _implementation = compute_frozen_batch_gradient(
        model=model, microsteps=inputs["microsteps"], config=config,
        target_name=inputs["target_name"], device="cuda",
    )
    try:
        b1m = json.loads(files["b1m_receipt"].read_text(encoding="utf-8"))
        b1m_batch = b1m["batch"]["overall_sha256"]
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
        _refuse("EVENT_B1M_BATCH_BINDING_MISSING")
    if b1m_batch != inputs["batch_sha256"]: _refuse("EVENT_B1M_BATCH_BINDING_MISMATCH")
    gradient_path, b3_path = _mint_b3(
        root=root, run_id=run_id, batch_sha256=inputs["batch_sha256"],
        target_name=inputs["target_name"], gradient=gradient,
    )
    try:
        pre_momentum = torch.load(files["pre_momentum"], map_location="cpu", weights_only=True).to(torch.float32)
    except Exception: _refuse("EVENT_PRE_MOMENTUM_LOAD_FAILED")
    reset = torch.zeros_like(gradient)
    transplant = torch.cat([pre_momentum, pre_momentum], dim=0)
    bindings = _copy_bindings(
        root=root, config=files["config"], b2=files["b2_receipt"], b1m=files["b1m_receipt"], b3=b3_path,
        batch=Path(args.batch_manifest), threshold=Path(args.threshold), verifier=Path(args.verifier),
    )
    non_target = {name: value.detach().cpu().clone() for name, value in model.state_dict().items() if name != inputs["target_name"]}
    def replay(target: torch.Tensor, expected_non_target: dict[str, torch.Tensor]) -> float:
        return replay_target_only_loss(
            model=model, microsteps=inputs["microsteps"], config=config,
            target_name=inputs["target_name"], target=target,
            expected_non_target_state=expected_non_target, device="cuda",
        )
    layers = config.get("model", {}).get("layers") if isinstance(config, dict) else None
    if not isinstance(layers, int) or isinstance(layers, bool) or layers <= 0: _refuse("EVENT_LAYER_COUNT_INVALID")
    return capture_actual_event(
        custody_root=root, run_id=run_id, dispatch_receipt_path=preflight_path,
        lineage_run_id=inputs["lineage_run_id"],
        expected_source_commit=preflight["source_commit"],
        binding_files=bindings, model=model, target_name=inputs["target_name"],
        reset_momentum=reset, transplant_momentum=transplant, loss_replay=replay,
        learning_rate=learning_rate, optimizer_scale=1.0,
        seed_manifest_path=files["seed_manifest"], seed_model_path=files["seed_model"],
        seed_optimizer_path=files["seed_optimizer"], grown_model_path=files["grown_model"],
        b2_receipt_path=files["b2_receipt"], b1m_receipt_path=files["b1m_receipt"],
        runtime_config_path=files["config"],
        b3_receipt_path=b3_path, batch_manifest_path=Path(args.batch_manifest),
        persisted_pre_momentum_path=files["pre_momentum"], persisted_gradient_path=gradient_path,
        gradient_data_root=root, expected_batch_sha256=inputs["batch_sha256"],
        grow_operator_path=files["grow_operator"], n_layers=layers,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=[GOVERNED_VERTICAL_MODE])
    for name in ("run-id", "config", "checkpoint-manifest", "batch-manifest", "threshold", "verifier", "custody-root"):
        parser.add_argument(f"--{name}", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    path = run_governed_vertical(args)
    print(json.dumps({"schema": "q2-governed-event-result-v1", "capture_manifest": path.name, "credit": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
