# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Closed, path-safe input admission for the governed #675 GPU event."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Mapping

import torch


class EventInputRefusal(ValueError):
    """Named refusal raised before model construction or GPU allocation."""


def _refuse(code: str) -> None:
    raise EventInputRefusal(code)


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest(root: Path, path: Path, *, schema: str, code: str) -> dict[str, object]:
    try:
        path = Path(path).resolve(strict=True)
        if path.parent != root or not path.is_file() or path.is_symlink():
            _refuse(code + "_OUTSIDE_CUSTODY")
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError):
        _refuse(code + "_MALFORMED")
    if not isinstance(value, dict) or value.get("schema") != schema:
        _refuse(code + "_SCHEMA_INVALID")
    claimed = value.get("manifest_sha256")
    if not isinstance(claimed, str) or re.fullmatch(r"[0-9a-f]{64}", claimed) is None:
        _refuse(code + "_SELF_HASH_INVALID")
    unhashed = dict(value)
    unhashed.pop("manifest_sha256")
    if hashlib.sha256(_canonical(unhashed)).hexdigest() != claimed:
        _refuse(code + "_SELF_HASH_MISMATCH")
    return value


def _bound_file(root: Path, row: object, *, code: str) -> Path:
    if not isinstance(row, dict) or set(row) != {"logical_path", "sha256", "bytes"}:
        _refuse(code + "_FILE_SCHEMA_INVALID")
    logical = row["logical_path"]
    sha = row["sha256"]
    size = row["bytes"]
    if (
        not isinstance(logical, str)
        or not logical
        or Path(logical).is_absolute()
        or ".." in Path(logical).parts
        or not isinstance(sha, str)
        or re.fullmatch(r"[0-9a-f]{64}", sha) is None
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size < 0
    ):
        _refuse(code + "_FILE_SCHEMA_INVALID")
    try:
        path = (root / logical).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file() or path.is_symlink():
            _refuse(code + "_FILE_OUTSIDE_CUSTODY")
        if path.stat().st_size != size or _sha(path) != sha:
            _refuse(code + "_FILE_HASH_MISMATCH")
    except OSError:
        _refuse(code + "_FILE_UNAVAILABLE")
    return path


def validate_runtime_config(path: Path, expected_source_commit: str) -> None:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _refuse("EVENT_RUNTIME_CONFIG_INVALID")
    if not isinstance(config, dict):
        _refuse("EVENT_RUNTIME_CONFIG_INVALID")
    unsigned = {key: value for key, value in config.items() if key != "config_sha256"}
    model = config.get("model")
    objective = config.get("objective")
    precision = config.get("precision")
    optimizer = config.get("optimizer")
    mtp = objective.get("mtp_aux_heads") if isinstance(objective, dict) else None
    qat = precision.get("qat") if isinstance(precision, dict) else None
    if (
        set(config) != {"schema", "source_commit", "historical_config_sha256", "scope", "execution_authority", "model", "objective", "precision", "optimizer", "no_new_parallel_authority", "config_sha256"}
        or config.get("schema") != "q2-event-runtime-config-v1"
        or config.get("source_commit") != expected_source_commit
        or not isinstance(config.get("historical_config_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", config["historical_config_sha256"]) is None
        or config.get("scope") != "TARGET_TENSOR_COUNTERFACTUAL"
        or config.get("execution_authority") != "EMBER_LAB_Q2_EVENT_ONLY"
        or config.get("no_new_parallel_authority") is not True
        or config.get("config_sha256") != hashlib.sha256(_canonical(unsigned)).hexdigest()
        or not isinstance(model, dict)
        or set(model) != {"vocab", "hidden", "layers", "heads", "seq", "tied_embeddings", "grad_checkpointing"}
        or any(not isinstance(model[key], int) or isinstance(model[key], bool) or model[key] <= 0 for key in ("vocab", "hidden", "layers", "heads", "seq"))
        or model.get("tied_embeddings") not in (True, False)
        or model.get("grad_checkpointing") not in (True, False)
        or not isinstance(objective, dict)
        or set(objective) != {"mtp_aux_heads"}
        or not isinstance(mtp, dict)
        or set(mtp) != {"enabled", "n_heads", "weight"}
        or mtp.get("enabled") not in (True, False)
        or not isinstance(mtp.get("n_heads"), int)
        or isinstance(mtp.get("n_heads"), bool)
        or mtp["n_heads"] < 0
        or not isinstance(mtp.get("weight"), (int, float))
        or isinstance(mtp.get("weight"), bool)
        or not math.isfinite(float(mtp["weight"]))
        or mtp["weight"] < 0
        or not isinstance(precision, dict)
        or set(precision) != {"qat"}
        or not isinstance(qat, dict)
        or set(qat) != {"enabled"}
        or qat.get("enabled") not in (True, False)
        or not isinstance(optimizer, dict)
        or set(optimizer) != {"lr_muon"}
        or isinstance(optimizer.get("lr_muon"), bool)
        or not isinstance(optimizer.get("lr_muon"), (int, float))
        or not math.isfinite(float(optimizer["lr_muon"]))
        or optimizer["lr_muon"] <= 0
    ):
        _refuse("EVENT_RUNTIME_CONFIG_INVALID")


def admit_event_inputs(
    *, custody_root: Path, checkpoint_manifest_path: Path,
    batch_manifest_path: Path, expected_source_commit: str, expected_run_id: str,
) -> dict[str, object]:
    """Validate every execution operand and load the frozen CPU tensors."""

    try:
        root = Path(custody_root).resolve(strict=True)
    except OSError:
        _refuse("EVENT_CUSTODY_UNAVAILABLE")
    if not root.is_dir():
        _refuse("EVENT_CUSTODY_UNAVAILABLE")
    checkpoint = _manifest(root, Path(checkpoint_manifest_path), schema="q2-event-checkpoint-input-v1", code="EVENT_CHECKPOINT")
    batch = _manifest(root, Path(batch_manifest_path), schema="q2-event-batch-input-v1", code="EVENT_BATCH")
    checkpoint_keys = {"schema", "source_commit", "run_id", "lineage_run_id", "target_name", "intermediate_size", "files", "manifest_sha256"}
    batch_keys = {"schema", "source_commit", "run_id", "builder_sha256", "microsteps", "payload_sha256", "batch_sha256", "manifest_sha256"}
    if set(checkpoint) != checkpoint_keys or set(batch) != batch_keys:
        _refuse("EVENT_INPUT_UNKNOWN_OR_MISSING_FIELD")
    builder_path = Path(__file__).with_name("q2_input_manifest_builder.py")
    if batch.get("builder_sha256") != _sha(builder_path):
        _refuse("EVENT_BATCH_BUILDER_BINDING_MISMATCH")
    if any(value.get("source_commit") != expected_source_commit or value.get("run_id") != expected_run_id for value in (checkpoint, batch)):
        _refuse("EVENT_INPUT_IDENTITY_MISMATCH")
    if not isinstance(checkpoint["lineage_run_id"], str) or re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", checkpoint["lineage_run_id"]) is None:
        _refuse("EVENT_LINEAGE_RUN_ID_INVALID")
    files = checkpoint["files"]
    required = {
        "config", "seed_model", "seed_optimizer", "grown_model", "seed_manifest",
        "b1m_receipt", "b2_receipt", "pre_momentum", "grow_operator",
    }
    if not isinstance(files, dict) or set(files) != required:
        _refuse("EVENT_CHECKPOINT_FILE_SET_INVALID")
    resolved = {name: _bound_file(root, row, code="EVENT_CHECKPOINT") for name, row in files.items()}
    validate_runtime_config(resolved["config"], expected_source_commit)
    rows = batch["microsteps"]
    if not isinstance(rows, list) or not rows:
        _refuse("EVENT_BATCH_ROWS_INVALID")
    microsteps = []
    identities = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"x", "y0", "y_mtp"} or not isinstance(row["y_mtp"], list):
            _refuse("EVENT_BATCH_ROW_SCHEMA_INVALID")
        paths = [_bound_file(root, row["x"], code="EVENT_BATCH"), _bound_file(root, row["y0"], code="EVENT_BATCH")]
        paths += [_bound_file(root, item, code="EVENT_BATCH") for item in row["y_mtp"]]
        if len(set(paths)) != len(paths):
            _refuse("EVENT_BATCH_FILE_DUPLICATE")
        try:
            tensors = [torch.load(path, map_location="cpu", weights_only=True) for path in paths]
        except Exception:
            _refuse("EVENT_BATCH_TENSOR_MALFORMED")
        if any(not isinstance(value, torch.Tensor) or value.dtype != torch.int64 or value.ndim != 2 for value in tensors) or any(value.shape != tensors[0].shape for value in tensors[1:]):
            _refuse("EVENT_BATCH_TENSOR_INVALID")
        microsteps.append({"x": tensors[0], "y0": tensors[1], "y_mtp": tensors[2:]})
        identities.append([_sha(path) for path in paths])
    actual_payload_sha = hashlib.sha256(_canonical(identities)).hexdigest()
    if batch["payload_sha256"] != actual_payload_sha:
        _refuse("EVENT_BATCH_IDENTITY_MISMATCH")
    microstep_shas = []
    for row in microsteps:
        digest = hashlib.sha256()
        x = row["x"]
        attention = torch.ones_like(x)
        positions = torch.arange(x.shape[1], dtype=torch.int64).unsqueeze(0).expand(x.shape[0], -1)
        for tensor in (x, attention, positions, row["y0"], *row["y_mtp"]):
            digest.update(tensor.contiguous().numpy().tobytes())
        microstep_shas.append(digest.hexdigest())
    actual_batch_sha = hashlib.sha256("".join(microstep_shas).encode("utf-8")).hexdigest()
    if batch["batch_sha256"] != actual_batch_sha:
        _refuse("EVENT_BATCH_CONTENT_IDENTITY_MISMATCH")
    if not isinstance(checkpoint["target_name"], str) or not checkpoint["target_name"] or not isinstance(checkpoint["intermediate_size"], int) or isinstance(checkpoint["intermediate_size"], bool) or checkpoint["intermediate_size"] <= 0:
        _refuse("EVENT_CHECKPOINT_PARAMETERS_INVALID")
    return {"files": resolved, "microsteps": microsteps, "payload_sha256": actual_payload_sha, "batch_sha256": actual_batch_sha, "lineage_run_id": checkpoint["lineage_run_id"], "target_name": checkpoint["target_name"], "intermediate_size": checkpoint["intermediate_size"]}
