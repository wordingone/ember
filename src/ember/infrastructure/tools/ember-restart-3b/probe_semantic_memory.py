# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bounded no-step shared-text forward probe for the clean-genesis sparse v2 decoder."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import torch

from batch import decode_owned_batch
from model import RestartDecoderConfig, UnifiedDecoder
# issue2015 exact-local-import:src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py
import importlib.util as _ember_1601eccb5605602b_importlib
import sys as _ember_1601eccb5605602b_sys
from pathlib import Path as _ember_1601eccb5605602b_Path
_ember_1601eccb5605602b_path = _ember_1601eccb5605602b_Path(__file__).resolve().parent.joinpath('parameter_counter.py')
if not _ember_1601eccb5605602b_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py')
_ember_1601eccb5605602b_aliases = ('_ember_issue2015_1601eccb5605602b', 'parameter_counter', 'src.ember.infrastructure.tools.ember-restart-3b.parameter_counter')
_ember_1601eccb5605602b_existing = []
for _ember_1601eccb5605602b_alias in _ember_1601eccb5605602b_aliases:
    _ember_1601eccb5605602b_candidate = _ember_1601eccb5605602b_sys.modules.get(_ember_1601eccb5605602b_alias)
    if _ember_1601eccb5605602b_candidate is not None and all(_ember_1601eccb5605602b_candidate is not item for item in _ember_1601eccb5605602b_existing):
        _ember_1601eccb5605602b_existing.append(_ember_1601eccb5605602b_candidate)
if len(_ember_1601eccb5605602b_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py')
if _ember_1601eccb5605602b_existing:
    _ember_1601eccb5605602b_module = _ember_1601eccb5605602b_existing[0]
    _ember_1601eccb5605602b_observed = getattr(_ember_1601eccb5605602b_module, '__file__', None)
    if _ember_1601eccb5605602b_observed is None or _ember_1601eccb5605602b_Path(_ember_1601eccb5605602b_observed).resolve() != _ember_1601eccb5605602b_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py')
else:
    _ember_1601eccb5605602b_spec = _ember_1601eccb5605602b_importlib.spec_from_file_location('_ember_issue2015_1601eccb5605602b', _ember_1601eccb5605602b_path)
    if _ember_1601eccb5605602b_spec is None or _ember_1601eccb5605602b_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py')
    _ember_1601eccb5605602b_module = _ember_1601eccb5605602b_importlib.module_from_spec(_ember_1601eccb5605602b_spec)
    for _ember_1601eccb5605602b_alias in _ember_1601eccb5605602b_aliases:
        _ember_1601eccb5605602b_prior = _ember_1601eccb5605602b_sys.modules.get(_ember_1601eccb5605602b_alias)
        if _ember_1601eccb5605602b_prior is not None and _ember_1601eccb5605602b_prior is not _ember_1601eccb5605602b_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py')
        _ember_1601eccb5605602b_sys.modules[_ember_1601eccb5605602b_alias] = _ember_1601eccb5605602b_module
    try:
        _ember_1601eccb5605602b_spec.loader.exec_module(_ember_1601eccb5605602b_module)
    except BaseException:
        for _ember_1601eccb5605602b_alias in _ember_1601eccb5605602b_aliases:
            if _ember_1601eccb5605602b_sys.modules.get(_ember_1601eccb5605602b_alias) is _ember_1601eccb5605602b_module:
                _ember_1601eccb5605602b_sys.modules.pop(_ember_1601eccb5605602b_alias, None)
        raise
for _ember_1601eccb5605602b_alias in _ember_1601eccb5605602b_aliases:
    _ember_1601eccb5605602b_prior = _ember_1601eccb5605602b_sys.modules.get(_ember_1601eccb5605602b_alias)
    if _ember_1601eccb5605602b_prior is not None and _ember_1601eccb5605602b_prior is not _ember_1601eccb5605602b_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py')
    _ember_1601eccb5605602b_sys.modules[_ember_1601eccb5605602b_alias] = _ember_1601eccb5605602b_module
measure_parameter_counts = getattr(_ember_1601eccb5605602b_module, 'measure_parameter_counts')
# issue2015 exact-local-import-end:src/ember/infrastructure/tools/ember-restart-3b/parameter_counter.py
# issue2015 exact-local-import:src/ember/infrastructure/tools/ember-restart-3b/semantic_stream.py
import importlib.util as _ember_61c7220b679f890b_importlib
import sys as _ember_61c7220b679f890b_sys
from pathlib import Path as _ember_61c7220b679f890b_Path
_ember_61c7220b679f890b_path = _ember_61c7220b679f890b_Path(__file__).resolve().parent.joinpath('semantic_stream.py')
if not _ember_61c7220b679f890b_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/infrastructure/tools/ember-restart-3b/semantic_stream.py')
_ember_61c7220b679f890b_aliases = ('_ember_issue2015_61c7220b679f890b', 'semantic_stream', 'src.ember.infrastructure.tools.ember-restart-3b.semantic_stream')
_ember_61c7220b679f890b_existing = []
for _ember_61c7220b679f890b_alias in _ember_61c7220b679f890b_aliases:
    _ember_61c7220b679f890b_candidate = _ember_61c7220b679f890b_sys.modules.get(_ember_61c7220b679f890b_alias)
    if _ember_61c7220b679f890b_candidate is not None and all(_ember_61c7220b679f890b_candidate is not item for item in _ember_61c7220b679f890b_existing):
        _ember_61c7220b679f890b_existing.append(_ember_61c7220b679f890b_candidate)
if len(_ember_61c7220b679f890b_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/semantic_stream.py')
if _ember_61c7220b679f890b_existing:
    _ember_61c7220b679f890b_module = _ember_61c7220b679f890b_existing[0]
    _ember_61c7220b679f890b_observed = getattr(_ember_61c7220b679f890b_module, '__file__', None)
    if _ember_61c7220b679f890b_observed is None or _ember_61c7220b679f890b_Path(_ember_61c7220b679f890b_observed).resolve() != _ember_61c7220b679f890b_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/infrastructure/tools/ember-restart-3b/semantic_stream.py')
else:
    _ember_61c7220b679f890b_spec = _ember_61c7220b679f890b_importlib.spec_from_file_location('_ember_issue2015_61c7220b679f890b', _ember_61c7220b679f890b_path)
    if _ember_61c7220b679f890b_spec is None or _ember_61c7220b679f890b_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/infrastructure/tools/ember-restart-3b/semantic_stream.py')
    _ember_61c7220b679f890b_module = _ember_61c7220b679f890b_importlib.module_from_spec(_ember_61c7220b679f890b_spec)
    for _ember_61c7220b679f890b_alias in _ember_61c7220b679f890b_aliases:
        _ember_61c7220b679f890b_prior = _ember_61c7220b679f890b_sys.modules.get(_ember_61c7220b679f890b_alias)
        if _ember_61c7220b679f890b_prior is not None and _ember_61c7220b679f890b_prior is not _ember_61c7220b679f890b_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/semantic_stream.py')
        _ember_61c7220b679f890b_sys.modules[_ember_61c7220b679f890b_alias] = _ember_61c7220b679f890b_module
    try:
        _ember_61c7220b679f890b_spec.loader.exec_module(_ember_61c7220b679f890b_module)
    except BaseException:
        for _ember_61c7220b679f890b_alias in _ember_61c7220b679f890b_aliases:
            if _ember_61c7220b679f890b_sys.modules.get(_ember_61c7220b679f890b_alias) is _ember_61c7220b679f890b_module:
                _ember_61c7220b679f890b_sys.modules.pop(_ember_61c7220b679f890b_alias, None)
        raise
for _ember_61c7220b679f890b_alias in _ember_61c7220b679f890b_aliases:
    _ember_61c7220b679f890b_prior = _ember_61c7220b679f890b_sys.modules.get(_ember_61c7220b679f890b_alias)
    if _ember_61c7220b679f890b_prior is not None and _ember_61c7220b679f890b_prior is not _ember_61c7220b679f890b_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/infrastructure/tools/ember-restart-3b/semantic_stream.py')
    _ember_61c7220b679f890b_sys.modules[_ember_61c7220b679f890b_alias] = _ember_61c7220b679f890b_module
ManifestBoundTokenStream = getattr(_ember_61c7220b679f890b_module, 'ManifestBoundTokenStream')
# issue2015 exact-local-import-end:src/ember/infrastructure/tools/ember-restart-3b/semantic_stream.py

ROOT = Path(__file__).resolve().parents[5]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def probe_receipt(
    *, model_config_sha256: str, stream_receipt_sha256: str, tokenizer_sha256: str,
    selected_expert: str, sequence_length: int, total_parameters: int,
    active_parameters: int, elapsed_seconds: float, peak_memory_bytes: int,
    reserved_memory_bytes: int,
) -> dict[str, Any]:
    return {
        "schema_version": "ember-shared-ffn-memory-probe-v1",
        "result": "MEASURED",
        "operation": "NO_STEP_SEMANTIC_FORWARD",
        "model_config_sha256": model_config_sha256,
        "stream_receipt_sha256": stream_receipt_sha256,
        "tokenizer_sha256": tokenizer_sha256,
        "selected_expert": selected_expert,
        "sequence_length": sequence_length,
        "total_parameters": total_parameters,
        "active_parameters": active_parameters,
        "elapsed_seconds": elapsed_seconds,
        "peak_memory_bytes": peak_memory_bytes,
        "reserved_memory_bytes": reserved_memory_bytes,
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--shards-root", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--sequence-length", type=int, default=1024)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.sequence_length < 1 or args.output.exists():
        parser.error("sequence length must be positive and output must be new")
    stream = ManifestBoundTokenStream.from_receipt(receipt_path=args.receipt, shards_root=args.shards_root, tokenizer_path=args.tokenizer)
    record, _ = stream.next_episode(shard_index=0, token_offset=0, sequence_length=args.sequence_length)
    config_path = ROOT / "configs" / "ember-restart-3b.json"
    config = RestartDecoderConfig.from_contract(config_path)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    previous_dtype = torch.get_default_dtype()
    torch.set_default_dtype(torch.bfloat16)
    try:
        model = UnifiedDecoder(config, device="cuda", allow_production_allocation=True, genesis_seed=args.seed).eval()
    finally:
        torch.set_default_dtype(previous_dtype)
    model._activate_expert("shared")
    counts = measure_parameter_counts(model)
    batch = decode_owned_batch(record, config, device=torch.device("cuda"))
    torch.cuda.reset_peak_memory_stats()
    torch.cuda.synchronize()
    started = time.perf_counter()
    with torch.inference_mode():
        logits = model(batch["input_ids"], active_expert="shared")
        if not torch.isfinite(logits.float()).all():
            raise RuntimeError("no-step semantic forward produced non-finite logits")
    torch.cuda.synchronize()
    receipt = probe_receipt(
        model_config_sha256=_sha256(config_path), stream_receipt_sha256=stream.receipt_sha256,
        tokenizer_sha256=stream.tokenizer_sha256, selected_expert="shared", sequence_length=args.sequence_length,
        total_parameters=counts["unique_parameters"], active_parameters=counts["active_parameters"],
        elapsed_seconds=time.perf_counter() - started, peak_memory_bytes=int(torch.cuda.max_memory_allocated()),
        reserved_memory_bytes=int(torch.cuda.max_memory_reserved()),
    )
    _atomic_json(args.output, receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())