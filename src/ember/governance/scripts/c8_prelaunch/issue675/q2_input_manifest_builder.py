# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Stage immutable #675 checkpoint and frozen-batch inputs manifest-last."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Mapping

import numpy as np
import torch

import q2_model_lineage as _model_lineage
from q2_model_lineage import replay_b2_widen
from q2_momentum_lineage import resolve_seed_momentum


_MAX_TEMP = 4 * 1024**3
_MAX_GROWN_MODEL_TEMP = 9 * 1024**3 // 2
_CANONICAL_B2_RECEIPT_NAME = "cbase-grow-rung2-event-grow-rung2-20260709-remeasure-b2.json"
_CANONICAL_B2_PATH_SUFFIX = ("receipts", _CANONICAL_B2_RECEIPT_NAME)
_CANONICAL_B2_RECEIPT_PATH = Path(__file__).resolve().parents[6] / "receipts" / _CANONICAL_B2_RECEIPT_NAME
_CANONICAL_B2_RECEIPT_SHA256 = _model_lineage.CANONICAL_B2_RECEIPT_SHA256
_CANONICAL_B2_LINEAGE_RUN_ID = _model_lineage.CANONICAL_B2_LINEAGE_RUN_ID
_CANONICAL_B2_OPERATOR_SHA256 = _model_lineage.CANONICAL_B2_OPERATOR_SHA256
_CANONICAL_B2_EPS_SIGMA = _model_lineage.CANONICAL_B2_EPS_SIGMA
_CANONICAL_B2_EPS_SEED = _model_lineage.CANONICAL_B2_EPS_SEED


class InputBuildRefusal(ValueError):
    """Named refusal before a dispatchable input packet exists."""


def _refuse(code: str) -> None:
    raise InputBuildRefusal(code)


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_copy(source: Path, target: Path) -> dict[str, object]:
    try:
        source = source.resolve(strict=True)
    except OSError:
        _refuse("INPUT_SOURCE_UNAVAILABLE")
    if not source.is_file() or target.exists():
        _refuse("INPUT_SOURCE_INVALID_OR_TOO_LARGE")
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.stat().st_size > _MAX_TEMP:
        try:
            os.link(source, target)
        except OSError:
            _refuse("INPUT_LARGE_SOURCE_HARDLINK_REQUIRED")
        if not target.is_file() or not os.path.samefile(source, target):
            target.unlink(missing_ok=True)
            _refuse("INPUT_LARGE_SOURCE_HARDLINK_INVALID")
        return {"logical_path": target.relative_to(target.parents[1]).as_posix(), "sha256": _sha(target), "bytes": target.stat().st_size}
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    os.close(fd)
    try:
        with source.open("rb") as reader, open(temporary, "wb") as writer:
            shutil.copyfileobj(reader, writer, 1024 * 1024)
            writer.flush(); os.fsync(writer.fileno())
        if os.path.getsize(temporary) != source.stat().st_size: _refuse("INPUT_COPY_SIZE_MISMATCH")
        os.replace(temporary, target)
    except Exception:
        try: os.unlink(temporary)
        except OSError: pass
        raise
    return {"logical_path": target.relative_to(target.parents[1]).as_posix(), "sha256": _sha(target), "bytes": target.stat().st_size}


def _atomic_torch(
    value: torch.Tensor,
    target: Path,
    *,
    max_temp_bytes: int | None = None,
    overflow_code: str = "INPUT_TEMP_EXCEEDS_4GIB",
) -> dict[str, object]:
    if target.exists(): _refuse("INPUT_OUTPUT_ALREADY_EXISTS")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent); os.close(fd)
    try:
        torch.save(value, temporary)
        limit = _MAX_TEMP if max_temp_bytes is None else max_temp_bytes
        if os.path.getsize(temporary) > limit: _refuse(overflow_code)
        with open(temporary, "rb+") as handle: os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        try: os.unlink(temporary)
        except OSError: pass
        raise
    return {"logical_path": target.relative_to(target.parents[1]).as_posix(), "sha256": _sha(target), "bytes": target.stat().st_size}


def _load_json(path: Path, code: str) -> dict[str, object]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        _refuse(code)
    if not isinstance(value, dict):
        _refuse(code)
    return value


def _validate_canonical_b2_source(path: Path, lineage_run_id: str) -> dict[str, object]:
    raw_supplied = os.fspath(path)
    if any(component in {".", ".."} for component in Path(raw_supplied).parts):
        _refuse("INPUT_B2_RECEIPT_PATH_MISMATCH")
    supplied = Path(os.path.abspath(raw_supplied))
    canonical_path = Path(os.path.abspath(os.fspath(_CANONICAL_B2_RECEIPT_PATH)))
    if os.path.normcase(os.fspath(supplied)) != os.path.normcase(os.fspath(canonical_path)):
        _refuse("INPUT_B2_RECEIPT_PATH_MISMATCH")
    try:
        for component in (supplied, *supplied.parents):
            metadata = os.lstat(component)
            if stat.S_ISLNK(metadata.st_mode) or (
                getattr(metadata, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            ):
                _refuse("INPUT_B2_RECEIPT_PATH_MISMATCH")
        resolved = supplied.resolve(strict=True)
        canonical = canonical_path.resolve(strict=True)
    except OSError:
        _refuse("INPUT_B2_RECEIPT_UNAVAILABLE")
    if resolved != canonical:
        _refuse("INPUT_B2_RECEIPT_PATH_MISMATCH")
    if _sha(resolved) != _CANONICAL_B2_RECEIPT_SHA256:
        _refuse("INPUT_B2_RECEIPT_IDENTITY_MISMATCH")
    receipt = _load_json(resolved, "INPUT_B2_RECEIPT_INVALID")
    eps = receipt.get("eps")
    cache = receipt.get("cache")
    proof = receipt.get("realized_proof")
    if (
        lineage_run_id != _CANONICAL_B2_LINEAGE_RUN_ID
        or receipt.get("ticket") != "CBASE-GROW-RUNG2-EVENT-B2"
        or receipt.get("run_id") != _CANONICAL_B2_LINEAGE_RUN_ID
        or receipt.get("verdict") != "B2_REALIZED_PASS"
        or receipt.get("operator_sha256") != _CANONICAL_B2_OPERATOR_SHA256
        or not isinstance(eps, Mapping)
        or eps.get("eps_sigma") != _CANONICAL_B2_EPS_SIGMA
        or eps.get("eps_seed") != _CANONICAL_B2_EPS_SEED
        or eps.get("banned_zero_assertion_passed") is not True
        or not isinstance(cache, Mapping)
        or cache.get("distinct_from_eps0_cache") is not True
        or not isinstance(proof, Mapping)
        or proof.get("eta_band_pass") is not True
        or proof.get("twin_cosine_pass") is not True
    ):
        _refuse("INPUT_B2_FROZEN_LAW_MISMATCH")
    return receipt


def _materialize_replay_inputs(
    *,
    root: Path,
    sources: Mapping[str, Path],
    target_name: str,
    config: Mapping[str, object],
    source_commit: str,
    lineage_run_id: str,
    runtime_config_sha256: str,
) -> dict[str, dict[str, object]]:
    try:
        seed_state = torch.load(sources["seed_model"], map_location="cpu", weights_only=True)
        b2 = _validate_canonical_b2_source(sources["b2_receipt"], lineage_run_id)
        eps = b2["eps"]
        layers = config["model"]["layers"]
        cache = b2["cache"]
        proof = b2["realized_proof"]
        if (
            b2.get("ticket") != "CBASE-GROW-RUNG2-EVENT-B2"
            or b2.get("run_id") != lineage_run_id
            or b2.get("verdict") != "B2_REALIZED_PASS"
            or not isinstance(eps, Mapping)
            or eps.get("banned_zero_assertion_passed") is not True
            or not isinstance(cache, Mapping)
            or cache.get("distinct_from_eps0_cache") is not True
            or not isinstance(proof, Mapping)
            or proof.get("eta_band_pass") is not True
            or proof.get("twin_cosine_pass") is not True
            or not isinstance(b2.get("operator_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", b2["operator_sha256"]) is None
        ):
            raise TypeError
        grown = replay_b2_widen(
            seed_state,
            n_layers=layers,
            eps_sigma=eps["eps_sigma"],
            eps_seed=eps["eps_seed"],
        )
    except InputBuildRefusal:
        raise
    except Exception:
        _refuse("INPUT_B2_REPLAY_INVALID")
    grown_row = _atomic_torch(
        grown,
        root / "inputs" / "grown_model.pt",
        max_temp_bytes=_MAX_GROWN_MODEL_TEMP,
        overflow_code="INPUT_GROWN_MODEL_TEMP_EXCEEDS_4_5GIB",
    )
    momentum = resolve_seed_momentum(
        seed_model_path=sources["seed_model"],
        seed_optimizer_path=sources["seed_optimizer"],
        target_name=target_name,
    )
    momentum_row = _atomic_torch(momentum, root / "inputs" / "pre_momentum.pt")
    operator_row = _atomic_copy(
        Path(_model_lineage.__file__).resolve(), root / "inputs" / "grow_operator.py"
    )
    historical_receipt_sha = _sha(sources["b2_receipt"])
    receipt = {
        "schema": "q2-b2-replay-remint-receipt-v1",
        "source_commit": source_commit,
        "lineage_run_id": lineage_run_id,
        "verdict": "B2_REPLAY_REMINTED",
        "historical": {
            "receipt_sha256": historical_receipt_sha,
            "operator_sha256": b2["operator_sha256"],
            "ticket": b2["ticket"],
            "verdict": b2["verdict"],
        },
        "law": {
            "n_layers": layers,
            "eps_sigma": eps["eps_sigma"],
            "eps_seed": eps["eps_seed"],
            "banned_zero_assertion_passed": True,
            "distinct_from_eps0_cache": True,
            "eta_band_pass": True,
            "twin_cosine_pass": True,
        },
        "inputs": {
            "seed_manifest_sha256": _sha(sources["seed_manifest"]),
            "seed_model_sha256": _sha(sources["seed_model"]),
            "runtime_config_sha256": runtime_config_sha256,
        },
        "operator_sha256": operator_row["sha256"],
        "output": {"grown_model_sha256": grown_row["sha256"]},
    }
    receipt["receipt_sha256"] = hashlib.sha256(_canonical(receipt)).hexdigest()
    receipt_path = root / "inputs" / "b2_receipt.json"
    receipt_row = _atomic_bytes(_canonical(receipt), receipt_path)
    return {
        "grown_model": grown_row,
        "pre_momentum": momentum_row,
        "grow_operator": operator_row,
        "b2_receipt": receipt_row,
    }


def _atomic_bytes(value: bytes, target: Path) -> dict[str, object]:
    if target.exists():
        _refuse("INPUT_OUTPUT_ALREADY_EXISTS")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return {
        "logical_path": target.relative_to(target.parents[1]).as_posix(),
        "sha256": _sha(target),
        "bytes": target.stat().st_size,
    }


def _materialize_runtime_config(
    *, root: Path, historical_config: Mapping[str, object], historical_path: Path, source_commit: str
) -> dict[str, object]:
    try:
        model = historical_config["model"]
        objective = historical_config["objective"]
        mtp = objective["mtp_aux_heads"]
        precision = historical_config["precision"]
        qat = precision["qat"]
        optimizer = historical_config["optimizer"]
        if not all(isinstance(value, Mapping) for value in (model, objective, mtp, precision, qat, optimizer)):
            raise TypeError
        lr_muon = optimizer["lr_muon"]
        if (
            isinstance(lr_muon, bool)
            or not isinstance(lr_muon, (int, float))
            or not math.isfinite(float(lr_muon))
            or lr_muon <= 0
        ):
            raise TypeError
        body = {
            "schema": "q2-event-runtime-config-v1",
            "source_commit": source_commit,
            "historical_config_sha256": _sha(historical_path),
            "scope": "TARGET_TENSOR_COUNTERFACTUAL",
            "execution_authority": "EMBER_LAB_Q2_EVENT_ONLY",
            "model": {
                key: model[key]
                for key in ("vocab", "hidden", "layers", "heads", "seq", "tied_embeddings", "grad_checkpointing")
            },
            "objective": {
                "mtp_aux_heads": {
                    key: mtp[key] for key in ("enabled", "n_heads", "weight")
                }
            },
            "precision": {"qat": {"enabled": qat["enabled"]}},
            "optimizer": {"lr_muon": lr_muon},
            "no_new_parallel_authority": True,
        }
    except (KeyError, TypeError):
        _refuse("INPUT_CONFIG_SOURCE_INVALID")
    body["config_sha256"] = hashlib.sha256(_canonical(body)).hexdigest()
    return _atomic_bytes(_canonical(body), root / "inputs" / "config.json")


def _write_manifest(path: Path, body: dict[str, object]) -> Path:
    if path.exists(): _refuse("INPUT_OUTPUT_ALREADY_EXISTS")
    body["manifest_sha256"] = hashlib.sha256(_canonical(body)).hexdigest()
    raw = _canonical(body)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle: handle.write(raw); handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try: os.unlink(temporary)
        except OSError: pass
        raise
    return path


def build_frozen_batch(*, root: Path, run_id: str, source_commit: str, config: Mapping[str, object], micro_batch: int = 1, grad_accum_steps: int = 8) -> Path:
    try:
        vocab = int(config["model"]["vocab"]); seq = int(config["model"]["seq"])
        n_mtp = int(config["objective"]["mtp_aux_heads"]["n_heads"])
    except (KeyError, TypeError, ValueError): _refuse("INPUT_BATCH_CONFIG_INVALID")
    if min(vocab, seq, micro_batch, grad_accum_steps) <= 0 or n_mtp < 0 or vocab > 65535: _refuse("INPUT_BATCH_CONFIG_INVALID")
    rng = np.random.default_rng(0)
    need = (grad_accum_steps + 4) * micro_batch * seq + seq + n_mtp + 8
    stream = rng.integers(1, vocab, size=int(need), dtype=np.int64); stream[::max(1, seq * 3)] = 0
    rows = []; identities = []; microstep_shas = []
    batch_dir = root / "batch"
    for step in range(grad_accum_steps):
        xs=[]; ys=[]; mtps=[[] for _ in range(n_mtp)]
        for j in range(micro_batch):
            start=(step * micro_batch + j) * seq; window=stream[start:start+seq+1+n_mtp]
            xs.append(window[:seq]); ys.append(window[1:seq+1])
            for k in range(n_mtp): mtps[k].append(window[k+2:seq+k+2])
        x=torch.from_numpy(np.stack(xs)); y0=torch.from_numpy(np.stack(ys)); y_mtp=[torch.from_numpy(np.stack(v)) for v in mtps]
        refs=[]
        for label,tensor in (("x",x),("y0",y0),*[(f"y-mtp-{k}",v) for k,v in enumerate(y_mtp)]):
            refs.append(_atomic_torch(tensor, batch_dir / f"microstep-{step:02d}-{label}.pt"))
        digest=hashlib.sha256(); attention=torch.ones_like(x); positions=torch.arange(seq,dtype=torch.int64).unsqueeze(0).expand(micro_batch,-1)
        for tensor in (x,attention,positions,y0,*y_mtp): digest.update(tensor.contiguous().numpy().tobytes())
        microstep_shas.append(digest.hexdigest()); identities.append([row["sha256"] for row in refs])
        rows.append({"x":refs[0],"y0":refs[1],"y_mtp":refs[2:]})
    body={"schema":"q2-event-batch-input-v1","source_commit":source_commit,"run_id":run_id,"builder_sha256":_sha(Path(__file__).resolve()),"microsteps":rows,"payload_sha256":hashlib.sha256(_canonical(identities)).hexdigest(),"batch_sha256":hashlib.sha256("".join(microstep_shas).encode()).hexdigest()}
    return _write_manifest(root / "batch-manifest.json", body)


def stage_event_inputs(*, root: Path, run_id: str, lineage_run_id: str, source_commit: str, sources: Mapping[str, Path], target_name: str, intermediate_size: int, config: Mapping[str, object]) -> tuple[Path, Path]:
    root = Path(root).resolve(); root.mkdir(parents=True, exist_ok=True)
    expected={"config","seed_model","seed_optimizer","seed_manifest","b1m_receipt","b2_receipt"}
    if set(sources)!=expected or not target_name or not lineage_run_id or intermediate_size<=0: _refuse("INPUT_CHECKPOINT_SCHEMA_INVALID")
    if _load_json(sources["config"], "INPUT_CONFIG_SOURCE_INVALID") != config:
        _refuse("INPUT_CONFIG_ARGUMENT_MISMATCH")
    _validate_canonical_b2_source(sources["b2_receipt"], lineage_run_id)
    rows={name:_atomic_copy(Path(path),root/"inputs"/f"{name}{Path(path).suffix or '.bin'}") for name,path in sources.items() if name not in {"b2_receipt","config"}}
    config_row=_materialize_runtime_config(root=root,historical_config=config,historical_path=sources["config"],source_commit=source_commit)
    rows["config"]=config_row
    rows.update(_materialize_replay_inputs(root=root,sources=sources,target_name=target_name,config=config,source_commit=source_commit,lineage_run_id=lineage_run_id,runtime_config_sha256=config_row["sha256"]))
    checkpoint={"schema":"q2-event-checkpoint-input-v1","source_commit":source_commit,"run_id":run_id,"lineage_run_id":lineage_run_id,"target_name":target_name,"intermediate_size":intermediate_size,"files":rows}
    checkpoint_path=_write_manifest(root/"checkpoint-manifest.json",checkpoint)
    batch_path=build_frozen_batch(root=root,run_id=run_id,source_commit=source_commit,config=config)
    return checkpoint_path,batch_path
