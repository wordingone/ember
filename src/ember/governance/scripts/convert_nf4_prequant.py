#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Sequential, commit-safe NF4 pre-quantization export (issue #81 track b).

Root cause of the earlier SIGSEGV (falsified quantization hypothesis, real
cause confirmed by execution receipts): loading the source checkpoint via
`from_pretrained` opens all 15 source shards' safetensors files up front
(mmap, copy-on-write), each charging several GB of Windows commit even
before any bnb call runs. 64GB RAM + a 16GB pagefile gives a ~79.6GB commit
ceiling; ~51GB baseline + 15 concurrent shard mappings overshoots it.

This script never holds more than one source shard's file handle open at a
time (the receipts-proven safe pattern: open, materialize via
`safetensors.torch.load_file` -- which copies bytes into ordinarily
allocated CPU tensors, not a lingering mmap view -- then close before the
next). Eligible tensors are quantized to NF4 one at a time on cuda:0 (a
single ~180MB-class tensor, moved back to CPU and freed immediately
afterward) so VRAM stays a small fraction of a GB, nowhere near the
governor's cap. Output tensors accumulate in ordinary heap RAM (not
file-backed, so none of the commit-multiplication above applies) and are
flushed to a NEW output shard file every ~4.5GB, deliberately fewer/smaller
shards than the source so a later `from_pretrained` load on the OUTPUT
opens far fewer files at once than the 15 that caused the original crash.

Which tensors get quantized: the STANDARD, unmodified bitsandbytes/HF
default -- only `type(module) is nn.Linear` weights, skipping exactly what
`transformers.quantizers.base.get_keys_to_not_convert` would skip for this
checkpoint (lm_head). No custom exclusion list: the earlier hypothesis that
two small linear_attn gating projections needed special-casing was
falsified by direct execution and is not reintroduced here. If a segfault
occurs during THIS run's per-tensor quantize loop (which, unlike the
falsified probe run, actually reaches bitsandbytes' CUDA kernel), the last
logged tensor name pins the true failure point -- unlike the earlier crash,
which died upstream of any bnb call.

Output: an AutoModelForCausalLM-loadable, save_pretrained-style directory
(config.json with a `quantization_config` block, sharded safetensors +
index, tokenizer/generation files copied verbatim) at --dst, plus
convert_receipt.json (sha256 per output file, source-shard lineage per
original tensor, VRAM peak, governor preflight block).

Source model dir is READ-ONLY throughout -- only ever opened for reading.

(Landing provenance, #210 Tier 2: SRC_DIR_DEFAULT/DST_DIR_DEFAULT below are
computed relative to the repo root rather than hardcoded to an operator
machine's absolute path -- same fixed-structural-sibling pattern used for
shards-v0/sandbox-gpu-test elsewhere in this codebase.)
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import shutil
import struct
import sys
import time
from pathlib import Path

import torch
import torch.nn as nn

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "scripts"))

import governor  # noqa: E402  (env_limits/preflight -- never reimplemented)

# The model-weights tree lives at a junction sibling to the repo root (same
# parent directory) -- computed rather than hardcoded so the default is
# portable across deployment trees. See module provenance note.
SRC_DIR_DEFAULT = REPO.parent / "models" / "Qwen3.6-27B"
DST_DIR_DEFAULT = REPO.parent / "models" / "Qwen3.6-27B-nf4"
FLUSH_BYTES_DEFAULT = 4_500_000_000  # target output shard size: fewer/smaller shards than the 15-shard source
VRAM_PEAK_LIMIT_GB = 2.0
AUX_FILES = [
    "tokenizer_config.json", "generation_config.json", "vocab.json",
    "tokenizer.json", "special_tokens_map.json", "merges.txt",
]


def log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}] {msg}", flush=True)


def derive_skip_set_for_run(default_skip: list, quantize_lm_head: bool) -> list:
    """Issue #87 round 5 item (a): the v1 export's skip set is transformers'
    own get_keys_to_not_convert default (['lm_head'] for this checkpoint) --
    kept UNCHANGED and byte-identical when quantize_lm_head is False (v1
    export intact, this is the default). When True, this ADDITIVE leg
    removes 'lm_head' specifically from the skip set so should_convert_module
    treats it like any other eligible nn.Linear -- no new quantization code
    path is needed, the existing quantize_tensor() GPU call already handles
    any Linear weight uniformly. Never touches other skip-set entries (if
    this checkpoint's default skip set ever grows beyond ['lm_head'], only
    'lm_head' is removed here, nothing else). Pure list operation, no
    torch/transformers import needed for this function itself."""
    if not quantize_lm_head:
        return list(default_skip)
    return [k for k in default_skip if k != "lm_head"]


def assert_dst_safe_for_lm_head_variant(dst: Path, default_dst: Path, quantize_lm_head: bool) -> None:
    """Issue #87 round 5 item (a) safety rail: --quantize-lm-head produces a
    DIFFERENT artifact than the v1 export (lm_head becomes NF4 instead of
    bf16) -- it must NEVER land at the v1 default destination, or a later
    r3_feasibility_probe.py run against 'the' prequant checkpoint would
    silently pick up a different quantization shape than what the SAME
    directory's convert_receipt.json (skip_set) claims, and every downstream
    consumer of that path (device_map derivation, governed-fit arithmetic)
    would silently misclassify lm_head. Refuses if quantize_lm_head is set
    and dst was not explicitly overridden away from the v1 default -- pure
    path comparison, no filesystem I/O beyond path resolution."""
    if quantize_lm_head and Path(dst).resolve() == Path(default_dst).resolve():
        raise SystemExit(
            f"--quantize-lm-head requires an explicit --dst different from the v1 default "
            f"({default_dst}) -- refusing to ever overwrite the live v1 export with a "
            f"differently-quantized artifact."
        )


def build_plan(src_dir: Path, quantize_lm_head: bool = False):
    """Meta-device skeleton (zero real weights, zero CUDA) -> exact key sets
    for the causal-LM-only target (matches AutoModelForCausalLM's 851-tensor
    view of this checkpoint, dropping the 333 vision + 15 mtp tensors).

    quantize_lm_head (issue #87 round 5 item (a), additive leg, default
    False = v1 export byte-identical): when True, derive_skip_set_for_run
    removes 'lm_head' from transformers' default skip set BEFORE building
    quantize_set, so lm_head becomes eligible via the SAME
    should_convert_module/quantize_tensor path as every other nn.Linear --
    no new quantization code. The RETURNED skip is always the EFFECTIVE one
    (used for both the receipt's skip_set field and the output
    BitsAndBytesConfig's llm_int8_skip_modules) -- never the stale
    transformers-default, which would misrepresent what's actually on disk
    once lm_head is quantized."""
    from transformers.models.qwen3_5.configuration_qwen3_5 import Qwen3_5TextConfig
    from transformers.models.qwen3_5.modeling_qwen3_5 import Qwen3_5ForCausalLM
    from transformers.quantizers.base import get_keys_to_not_convert
    from transformers.quantizers.quantizers_utils import should_convert_module

    cfg = json.loads((src_dir / "config.json").read_text())
    text_config = Qwen3_5TextConfig(**cfg["text_config"])

    with torch.device("meta"):
        model = Qwen3_5ForCausalLM(text_config)

    default_skip = get_keys_to_not_convert(model)  # expected: ['lm_head']
    skip = derive_skip_set_for_run(default_skip, quantize_lm_head)
    modules_by_name = dict(model.named_modules())
    causal_lm_keys = [n for n, _ in model.named_parameters()]

    quantize_set = set()
    for name in causal_lm_keys:
        module_name = name.rsplit(".", 1)[0]
        mod = modules_by_name[module_name]
        if type(mod) is nn.Linear and name.endswith(".weight") and should_convert_module(module_name, skip):
            quantize_set.add(name)

    def to_checkpoint_key(k: str) -> str:
        if k == "lm_head.weight":
            return k
        assert k.startswith("model."), f"unexpected causal-LM key shape: {k}"
        return "model.language_model." + k[len("model."):]

    key_map = {to_checkpoint_key(k): k for k in causal_lm_keys}  # checkpoint_key -> causal_lm_key
    return text_config, skip, quantize_set, key_map


def quantize_tensor(cpu_tensor: torch.Tensor, double_quant: bool) -> dict[str, torch.Tensor]:
    """Quantize one tensor to NF4 on cuda:0, return CPU tensors keyed by the
    suffix bitsandbytes'/transformers' own Linear4bit._save_to_state_dict
    convention uses ("" for the packed data itself, else "absmax" /
    "quant_map" / "quant_state.bitsandbytes__nf4" [+ nested_* if
    double_quant]) so the output round-trips through
    transformers.integrations.bitsandbytes.Bnb4bitDeserialize unmodified."""
    import bitsandbytes as bnb

    p = bnb.nn.Params4bit(
        cpu_tensor, requires_grad=False, quant_type="nf4",
        compress_statistics=double_quant, blocksize=64, quant_storage=torch.uint8,
    ).cuda()  # bnb_quantized=False at construction -> .cuda() triggers the real quantize_4bit kernel

    out = {"": p.data.detach().to("cpu")}
    for k, v in p.quant_state.as_dict(packed=True).items():
        out[k] = v.detach().to("cpu")

    del p
    torch.cuda.empty_cache()
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Sequential shard-safe NF4 pre-quantization export")
    ap.add_argument("--src", default=str(SRC_DIR_DEFAULT))
    ap.add_argument("--dst", default=str(DST_DIR_DEFAULT))
    ap.add_argument("--double-quant", action="store_true", help="nested double quantization (smaller output, off by default to match the original probe's config)")
    ap.add_argument("--flush-bytes", type=int, default=FLUSH_BYTES_DEFAULT)
    ap.add_argument("--limit-shards", type=int, default=None, help="process only the first N source shards (smoke test)")
    ap.add_argument(
        "--quantize-lm-head", action="store_true",
        help="Issue #87 round 5 item (a): ADDITIVE leg -- ALSO NF4-quantize lm_head "
             "(excluded from the v1 export by transformers' own get_keys_to_not_convert "
             "default; ~0.72GiB NF4-resident vs the current ~2.54GiB bf16). Off by "
             "default (v1 export byte-identical). Requires --dst to differ from the v1 "
             "default -- refuses otherwise, never risks clobbering the live v1 export.",
    )
    args = ap.parse_args()

    src_dir = Path(args.src)
    dst_dir = Path(args.dst)
    assert_dst_safe_for_lm_head_variant(dst_dir, DST_DIR_DEFAULT, args.quantize_lm_head)
    if not src_dir.exists():
        raise SystemExit(f"source dir not found: {src_dir}")
    dst_dir.mkdir(parents=True, exist_ok=True)

    torch.cuda.reset_peak_memory_stats()
    preflight = governor.preflight()
    log(f"governor preflight PASSED: {preflight}")

    log(f"building conversion plan from meta-device skeleton (zero weights, zero CUDA)... "
        f"quantize_lm_head={args.quantize_lm_head}")
    text_config, skip, quantize_set, key_map = build_plan(src_dir, args.quantize_lm_head)
    log(f"skip set: {skip}; quantize-eligible tensors: {len(quantize_set)}; total causal-LM tensors: {len(key_map)}")

    index = json.loads((src_dir / "model.safetensors.index.json").read_text())
    weight_map = index["weight_map"]

    shard_to_keys: dict[str, list[str]] = {}
    for ckpt_key, shard_file in weight_map.items():
        if ckpt_key not in key_map:
            continue  # vision / mtp tensor -- outside the AutoModelForCausalLM target, skipped
        shard_to_keys.setdefault(shard_file, []).append(ckpt_key)

    shard_files_sorted = sorted(shard_to_keys.keys())
    if args.limit_shards:
        shard_files_sorted = shard_files_sorted[: args.limit_shards]
    log(f"processing {len(shard_files_sorted)} source shards sequentially (never more than one file handle open at a time)")

    from safetensors.torch import load_file, save_file

    tmp_dir = dst_dir / "_tmp_parts"
    tmp_dir.mkdir(exist_ok=True)

    buffer: dict[str, torch.Tensor] = {}
    buffer_bytes = 0
    part_paths: list[Path] = []
    tensor_lineage: dict[str, str] = {}  # causal_lm_key -> source shard filename
    tensor_count_done = 0
    quantized_count_done = 0

    def flush() -> None:
        nonlocal buffer, buffer_bytes
        if not buffer:
            return
        part_idx = len(part_paths) + 1
        part_path = tmp_dir / f"part-{part_idx:05d}.safetensors"
        save_file(buffer, str(part_path), metadata={"format": "pt"})
        part_paths.append(part_path)
        log(f"flushed part-{part_idx:05d}.safetensors: {len(buffer)} tensors, {buffer_bytes / 1e9:.2f}GB")
        buffer = {}
        buffer_bytes = 0

    t_start = time.time()
    for shard_file in shard_files_sorted:
        shard_path = src_dir / shard_file
        log(f"opening shard {shard_file} ({len(shard_to_keys[shard_file])} allowlisted tensors)")
        shard_tensors = load_file(str(shard_path))  # materialized, owned CPU tensors -- no lingering mmap
        for ckpt_key in shard_to_keys[shard_file]:
            causal_key = key_map[ckpt_key]
            raw = shard_tensors[ckpt_key]
            if causal_key in quantize_set:
                log(f"  quantizing {causal_key} shape={tuple(raw.shape)}")
                out = quantize_tensor(raw, args.double_quant)
                for suffix, tensor in out.items():
                    key = causal_key if suffix == "" else f"{causal_key}.{suffix}"
                    buffer[key] = tensor
                    buffer_bytes += tensor.numel() * tensor.element_size()
                quantized_count_done += 1
            else:
                buffer[causal_key] = raw.clone()
                buffer_bytes += raw.numel() * raw.element_size()
            tensor_lineage[causal_key] = shard_file
            tensor_count_done += 1
        del shard_tensors
        gc.collect()
        vram_peak_gb = torch.cuda.max_memory_allocated() / 1e9
        log(
            f"closed shard {shard_file}; done {tensor_count_done}/{len(key_map)} tensors "
            f"({quantized_count_done} quantized); buffer={buffer_bytes / 1e9:.2f}GB; vram_peak={vram_peak_gb:.3f}GB"
        )
        if buffer_bytes >= args.flush_bytes:
            flush()

    flush()  # final partial shard

    vram_peak_gb = torch.cuda.max_memory_allocated() / 1e9
    log(f"ALL SHARDS PROCESSED in {time.time() - t_start:.1f}s; vram_peak={vram_peak_gb:.3f}GB")
    if vram_peak_gb >= VRAM_PEAK_LIMIT_GB:
        raise AssertionError(f"VRAM peak {vram_peak_gb:.3f}GB exceeds the {VRAM_PEAK_LIMIT_GB}GB constraint")

    total = len(part_paths)
    final_weight_map: dict[str, str] = {}
    file_sha256: dict[str, str] = {}
    for i, part_path in enumerate(part_paths, start=1):
        final_name = f"model-{i:05d}-of-{total:05d}.safetensors"
        final_path = dst_dir / final_name
        part_path.rename(final_path)

        h = hashlib.sha256()
        with open(final_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        file_sha256[final_name] = h.hexdigest()

        with open(final_path, "rb") as f:
            n = struct.unpack("<Q", f.read(8))[0]
            header = json.loads(f.read(n))
        for k in header:
            if k == "__metadata__":
                continue
            final_weight_map[k] = final_name
    tmp_dir.rmdir()

    total_size = sum((dst_dir / fn).stat().st_size for fn in file_sha256)
    (dst_dir / "model.safetensors.index.json").write_text(
        json.dumps({"metadata": {"total_size": total_size}, "weight_map": final_weight_map}, indent=2)
    )

    from transformers import BitsAndBytesConfig

    bnb_cfg = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype="bfloat16",
        bnb_4bit_use_double_quant=args.double_quant, llm_int8_skip_modules=list(skip),
    )
    out_config = text_config.to_dict()
    out_config["architectures"] = ["Qwen3_5ForCausalLM"]
    out_config["quantization_config"] = bnb_cfg.to_dict()
    (dst_dir / "config.json").write_text(json.dumps(out_config, indent=2, default=str))

    copied_aux = []
    for aux in AUX_FILES:
        src_aux = src_dir / aux
        if src_aux.exists():
            shutil.copy2(src_aux, dst_dir / aux)
            copied_aux.append(aux)

    receipt = {
        "ticket": "NF4-PREQUANT-CONVERT",
        "issue": "wordingone/ember#81",
        "source": str(src_dir),
        "destination": str(dst_dir),
        "governor_preflight": preflight,
        "skip_set": list(skip),
        "quantize_lm_head": args.quantize_lm_head,
        "lm_head_quantized": "lm_head" not in skip,
        "quantize_eligible_tensors": len(quantize_set),
        "kept_tensors": len(key_map) - len(quantize_set),
        "double_quant": args.double_quant,
        "limit_shards": args.limit_shards,
        "vram_peak_gb": round(vram_peak_gb, 4),
        "vram_peak_limit_gb": VRAM_PEAK_LIMIT_GB,
        "output_shard_count": total,
        "output_total_bytes": total_size,
        "output_total_gb": round(total_size / 1e9, 3),
        "sha_convention": "sha256 over final on-disk file bytes, computed after the tmp-part -> model-NNNNN-of-MMMMM rename (rename does not affect content hash)",
        "file_sha256": file_sha256,
        "tensor_lineage": tensor_lineage,
        "aux_files_copied": copied_aux,
        "elapsed_s": round(time.time() - t_start, 1),
    }
    receipt_path = dst_dir / "convert_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2))
    log(f"wrote receipt {receipt_path}")
    log(f"DONE: {total} shards, {total_size / 1e9:.2f}GB total, vram_peak={vram_peak_gb:.3f}GB")


if __name__ == "__main__":
    main()
