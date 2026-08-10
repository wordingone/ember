# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Stage immutable #675 checkpoint and frozen-batch inputs manifest-last."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Mapping

import numpy as np
import torch


_MAX_TEMP = 4 * 1024**3


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


def _atomic_torch(value: torch.Tensor, target: Path) -> dict[str, object]:
    if target.exists(): _refuse("INPUT_OUTPUT_ALREADY_EXISTS")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent); os.close(fd)
    try:
        torch.save(value, temporary)
        if os.path.getsize(temporary) > _MAX_TEMP: _refuse("INPUT_TEMP_EXCEEDS_4GIB")
        with open(temporary, "rb+") as handle: os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        try: os.unlink(temporary)
        except OSError: pass
        raise
    return {"logical_path": target.relative_to(target.parents[1]).as_posix(), "sha256": _sha(target), "bytes": target.stat().st_size}


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
    expected={"config","seed_model","seed_optimizer","grown_model","seed_manifest","b1m_receipt","b2_receipt","pre_momentum","grow_operator"}
    if set(sources)!=expected or not target_name or not lineage_run_id or intermediate_size<=0: _refuse("INPUT_CHECKPOINT_SCHEMA_INVALID")
    rows={name:_atomic_copy(Path(path),root/"inputs"/f"{name}{Path(path).suffix or '.bin'}") for name,path in sources.items()}
    checkpoint={"schema":"q2-event-checkpoint-input-v1","source_commit":source_commit,"run_id":run_id,"lineage_run_id":lineage_run_id,"target_name":target_name,"intermediate_size":intermediate_size,"files":rows}
    checkpoint_path=_write_manifest(root/"checkpoint-manifest.json",checkpoint)
    batch_path=build_frozen_batch(root=root,run_id=run_id,source_commit=source_commit,config=config)
    return checkpoint_path,batch_path
