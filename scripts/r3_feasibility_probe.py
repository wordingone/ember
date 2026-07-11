#!/usr/bin/env python3
"""R3 feasibility probe (issue #47) -- co-residence of a frozen 4-bit
~27B-class base + trainable LoRA-class slice, ONE train step + ONE
inference pass, single process, on the 4090.

Phase A (CPU prep, THIS harness's --dry-run mode): exercises every assert
and every leg's control flow against a TINY already-cached CPU substitute
model (Qwen2.5-0.5B-Instruct, Llama-style module naming -- the same
target_modules list applies unchanged to the real ~27B-class candidates
named in the phase-A report). No CUDA calls, no bitsandbytes 4-bit path
(that op requires a real GPU and is out of scope for phase A by the
issue's own text: "NO CUDA calls in phase A"). Proves the harness's control
flow, assert scaffolding, and receipt-writing are correct BEFORE any GPU
touch.

Phase B (maintainer-launched, post-keystone-crossing): --dry-run omitted,
requires --model pointed at an approved, already-downloaded checkpoint and
EMBER_GATE_AUTHORIZED=1 (checked by governor.preflight() conventions
elsewhere in this repo); loads the base 4-bit via bitsandbytes, runs the
five legs for real on CUDA.

Five receipt legs (issue #47 Deliverable, verbatim):
  1. ~27B-class base loaded 4-bit frozen (NF4/bitsandbytes-class; the slice
     must backprop -- never a GGUF inference-only path).
  2. Trainable LoRA-class slice attached (target ~100-300M trainable
     params, exact count recorded).
  3. ONE verified training step (loss, backward, optimizer step; grad-norm
     > 0 recorded; frozen-base assert: zero base params with grad).
  4. ONE inference pass (greedy, >=64 new tokens) WITHOUT unloading
     anything.
  5. VRAM peak (torch.cuda.max_memory_allocated + nvidia-smi sample) under
     the governor's fraction cap with the margin assert; tokens/s for both
     legs; wall-clock.

Fail-closed rails (issue #47 A3, verbatim):
  - governor fraction read from scripts/governor.py's standard config
    (env_limits() / preflight()) -- never re-derived or hardcoded here.
  - margin assert BEFORE and AFTER load.
  - frozen-base grad assert (zero base params with requires_grad=True).
  - receipt written ONLY if every assert passed -- a raised AssertionError
    halts execution before the receipt-write step is ever reached; this
    script does not catch/suppress assertion failures.

Rails: CPU-only until phase B; zero CUDA calls before the keystone
crossing; no edits outside scripts/ + receipts/r3-feasibility/ + a scratch
subdir (per issue #47's own rails section).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Issue #87 round 4 item 3 (live-fire finding): set BEFORE any torch import
# (torch is imported lazily inside main(), governor.py imports no torch at
# module level either -- this is early enough). PYTORCH_CUDA_ALLOC_CONF is
# this repo's OWN established convention (matches every other *_live.py
# script under scripts/); the round-4 issue comment names the newer
# torch>=2.4-generic alias PYTORCH_ALLOC_CONF -- both are set (harmless if
# either is unrecognized by the installed torch build) rather than silently
# picking one over the issue's literal wording.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import governor  # noqa: E402  (env_limits/preflight/device_capability -- never reimplemented)

REAL_RECEIPT_DIR = REPO / "receipts" / "r3-feasibility"
DRYRUN_RECEIPT_DIR = REPO / "scratch" / "r3-feasibility-dryrun"

# Llama-style module naming shared by all named phase-A candidates (Qwen2.5,
# Mistral-Small-24B, Yi-1.5, Gemma-2) AND by the dry-run substitute
# (Qwen2.5-0.5B-Instruct) -- one target list, unchanged between dry-run and
# the real GPU leg.
LORA_TARGET_MODULES = [
    "q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj",
]
DRYRUN_SUBSTITUTE_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"  # already HF-cached locally

TARGET_TRAINABLE_MIN = 100_000_000
TARGET_TRAINABLE_MAX = 300_000_000
MIN_NEW_TOKENS = 64
TRAIN_SEQ_LEN = 32  # Leg 3's training-step sequence length (named here, used at both the leg-3 call site and the round-4 activation-budget estimate -- one number, never a diverging duplicate literal)
INFER_PROMPT_LEN = 8  # Leg 4's inference-prompt length (same sharing rationale)

# Issue #87 round 4 item 2 (live-fire finding): rank=64 produced 318.7M
# trainable params, over TARGET_TRAINABLE_MAX. rank=24 is the new default
# (estimate_lora_trainable_params below cross-checks the real checkpoint at
# ~119.5M, comfortably inside [TARGET_TRAINABLE_MIN, TARGET_TRAINABLE_MAX]).
LORA_RANK_DEFAULT = 24

# Issue #87 round 5.4: the standing rank sweep for derive_max_fitting_rank's
# graceful-degradation fallback. Descending ONLY from LORA_RANK_DEFAULT --
# round 4 already established that ranks ABOVE 24 make both problems worse
# (rank=64 -> 318.7M trainable params, over TARGET_TRAINABLE_MAX; a bigger
# rank also means more VRAM, never less), so degradation only ever searches
# downward. The real checkpoint's ~119.5M trainable params at rank=24 scales
# ~linearly with rank, putting the TARGET_TRAINABLE_MIN=100M floor near
# rank~20 -- this sweep covers that entire live window plus margin below it,
# so derive_max_fitting_rank can correctly return None rather than silently
# stopping short of a rank that would have been band-legal.
LORA_RANK_SWEEP_CANDIDATES = [24, 23, 22, 21, 20, 19, 18, 17, 16, 15, 14, 13, 12]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="R3 feasibility probe (issue #47)")
    p.add_argument(
        "--model", default=None,
        help="HF repo id or local path of the ~27B-class base (required unless --dry-run)",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Exercise every assert/leg against a tiny CPU substitute model; no CUDA calls",
    )
    p.add_argument("--lora-rank", type=int, default=LORA_RANK_DEFAULT)
    p.add_argument("--seed", type=int, default=20260704)
    p.add_argument("--max-new-tokens", type=int, default=MIN_NEW_TOKENS)
    p.add_argument(
        "--neutralize-embed-offload", action="store_true",
        help="Issue #87 round 5 item (b): remove accelerate's offload hook from "
             "model.embed_tokens and replace it with a CPU-compute + activation-only-"
             "transfer hook (see neutralize_embed_tokens_offload_hook). Off by default -- "
             "when unset, round 3/4's tested behavior is byte-identical (embed_tokens "
             "streams via accelerate's normal hook, governed_fit_v2 gates as before). "
             "Only meaningful under a real (non-dry-run) prequantized load.",
    )
    p.add_argument(
        "--fragmentation-regime", choices=("static", "streaming"), default="static",
        help="Issue #87 round 5 item (d): governed_fit_v2.1's fragmentation-cost regime "
             "-- 'static' (0.75GiB) if --neutralize-embed-offload eliminates all streaming, "
             "'streaming' (1.5GiB) as the conservative fallback. Only used when "
             "--neutralize-embed-offload is set (v2.1 is only valid once streaming is "
             "actually eliminated).",
    )
    args = p.parse_args()
    if not args.dry_run and not args.model:
        p.error("--model is required unless --dry-run is set")
    return args


def log(msg: str) -> None:
    print(f"[{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}] {msg}", flush=True)


def nvidia_smi_sample() -> dict | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=True,
        )
        used_mib, total_mib = (int(x.strip()) for x in out.stdout.strip().split(","))
        return {"memory_used_mib": used_mib, "memory_total_mib": total_mib}
    except Exception as exc:  # pragma: no cover -- environment dependent
        return {"error": f"{type(exc).__name__}: {exc}"}


def detect_prequantized_config(model_path: str) -> dict | None:
    """Issue #86: read config.json directly (no from_pretrained, no torch/
    transformers import) and return its quantization_config block if present,
    else None. Local, already-materialized checkpoint dirs only -- a bare HF
    hub repo id (no local config.json to inspect without a network call) is
    treated as NOT prequantized, so from_pretrained still gets a fresh
    bnb_config for that case, byte-identical to today's behavior. Kept
    import-light (json/pathlib only) so unit tests can exercise this in
    isolation without pulling in torch/transformers (both stay imported
    lazily inside main(), never at module level)."""
    p = Path(model_path)
    config_path = p / "config.json"
    if not p.is_dir() or not config_path.is_file():
        return None
    try:
        cfg = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return cfg.get("quantization_config")


# Issue #87 round 5.2 (team-lead finding, flagged out-of-scope in round 5.1):
# the ONE shared byte->GiB helper, needed here FIRST (derive_governed_fit_max_memory,
# below) and again later by derive_governed_fit_v2_1 (round 5.1) -- defined
# once, this early, so both consumers share it rather than duplicating.
# governor.py is read-only shared infra (never edited here) -- its own
# total_gb/free_gb/margin_gb are DECIMAL-GB (torch.cuda.mem_get_info()'s raw
# bytes / 1e9; see governor.preflight()'s own body). BYTES_PER_GIB/bytes_to_gib
# convert a genuine byte count to TRUE binary GiB; converting governor's
# decimal-GB inputs requires round-tripping them through bytes first
# (value * 1e9, the standard GB->bytes factor) before this helper -- see
# derive_governed_fit_max_memory's docstring immediately below for exactly
# where that round-trip happens and why.
BYTES_PER_GIB = 2 ** 30  # 1,073,741,824 -- true binary gibibyte, never 1e9 (decimal GB)


def bytes_to_gib(n_bytes) -> float:
    """Issue #87 round 5.1/5.2: the ONE shared byte->GiB conversion helper,
    used by derive_governed_fit_max_memory (round 5.2) and
    derive_governed_fit_v2_1 (round 5.1). True binary GiB (n_bytes / 2**30),
    never decimal GB (n_bytes / 1e9)."""
    return n_bytes / BYTES_PER_GIB


def derive_governed_fit_max_memory(
    frac: float, total_gb: float, margin_gb: float, expected_mapped_bytes: int,
) -> dict:
    """Issue #87: pure arithmetic, no CUDA/torch/transformers import -- derives
    the device_map="auto" max_memory dict from the SAME governor config
    env_limits()/preflight() already produced, never a hardcoded GPU budget.

      allowed_gb    = frac * total_gb        (the governor VRAM ceiling the
                       leg5 peak-assert already enforces against total_gb)
      gpu_budget_gb = allowed_gb - margin_gb (reserve the SAME headroom
                       margin governor.env_limits() already carries for the
                       post-load VRAM-margin assert -- activation/KV-cache/
                       optimizer headroom, not a new number invented here)
      cpu_budget_gb = expected_mapped_bytes / 1e9 (the checkpoint's own
                       total on-disk size -- a natural sufficient upper bound
                       for whatever accelerate offloads to host RAM; never
                       unbounded, or this reopens the #81/#84 host-commit
                       class this probe exists to guard against)

    Round 5.2 fix (team-lead finding; the units bug round 5.1 flagged but
    deliberately left untouched, since it touched already-gated code outside
    that round's scope -- now in scope): total_gb and margin_gb are
    DECIMAL-GB (governor.py's own convention: preflight()'s total_gb/free_gb
    are torch.cuda.mem_get_info()'s raw bytes divided by 1e9; env_limits()'s
    EMBER_VRAM_MARGIN_GB is compared against raw bytes via `margin_gb * 1e9`
    inside preflight() -- both confirmed by direct read of governor.py, never
    touched here, read-only shared infra). The OLD max_memory string took
    gpu_budget_gb (itself decimal-GB, since it's linearly derived from
    decimal-GB total_gb/margin_gb) and f-string-labeled it "GiB" --
    accelerate's from_pretrained(max_memory=...) then parses that number as
    TRUE GiB, so every launch was actually authorized
    gpu_budget_gb * (1e9/2**30) =~ 1.0737x its governed intent -- a ~7.37%
    over-authorization of the ACTUAL VRAM ceiling the governor's fraction cap
    was meant to enforce, every single launch (the same units-bug CLASS as
    round 5.1's governed_fit_v2_1 defect, just one layer upstream of it).

    Fix: total_gb and margin_gb are round-tripped back through bytes (their
    own governor-documented unit -- value * 1e9) and then through
    bytes_to_gib (the ONE shared helper, same one round 5.1's
    derive_governed_fit_v2_1 uses) to get max_memory_authorized_gib -- the
    TRUE GiB value the max_memory string now actually encodes.
    expected_mapped_bytes is ALREADY a genuine raw byte count
    (governor.estimate_checkpoint_mapped_bytes: sum of os.path.getsize) --
    straight through bytes_to_gib, no *1e9 round-trip needed for that one.

    arithmetic's PRE-EXISTING fields (gpu_budget_gb, allowed_gb, total_gb,
    margin_gb, cpu_budget_gb, expected_mapped_bytes, vram_fraction) are LEFT
    COMPLETELY UNCHANGED -- they still feed derive_governed_fit_v1/v2/v2.1's
    own already-gated, internally-consistent decimal-GB budget comparisons
    (the disclosed residual documented in derive_governed_fit_v2_1's own
    docstring); renaming/re-deriving those would ripple into gated code this
    round was never asked to touch. Only the max_memory DICT VALUES (what
    accelerate actually consumes -- the real over-authorization surface for
    fire #7) and the two NEW additive fields (max_memory_authorized_gib,
    cpu_max_memory_authorized_gib) change.

    Returns {"max_memory": {0: "<max_memory_authorized_gib>GiB", "cpu":
    "<cpu_max_memory_authorized_gib>GiB"}, "arithmetic": {...}} so callers
    can log/receipt the derivation next to the dict accelerate actually
    consumes. Caller owns clamping/failure semantics if the budget is
    negative -- this function only computes, never asserts."""
    allowed_gb = frac * total_gb
    gpu_budget_gb = allowed_gb - margin_gb
    cpu_budget_gb = expected_mapped_bytes / 1e9

    total_gib = bytes_to_gib(total_gb * 1e9)
    margin_gib = bytes_to_gib(margin_gb * 1e9)
    max_memory_authorized_gib = round(frac * total_gib - margin_gib, 4)
    cpu_max_memory_authorized_gib = round(bytes_to_gib(expected_mapped_bytes), 4)

    max_memory = {0: f"{max_memory_authorized_gib:.2f}GiB", "cpu": f"{cpu_max_memory_authorized_gib:.2f}GiB"}
    arithmetic = {
        "vram_fraction": frac,
        "total_gb": total_gb,
        "allowed_gb": round(allowed_gb, 4),
        "margin_gb": margin_gb,
        "gpu_budget_gb": round(gpu_budget_gb, 4),
        "expected_mapped_bytes": expected_mapped_bytes,
        "cpu_budget_gb": round(cpu_budget_gb, 4),
        "max_memory_authorized_gib": max_memory_authorized_gib,
        "cpu_max_memory_authorized_gib": cpu_max_memory_authorized_gib,
    }
    return {"max_memory": max_memory, "arithmetic": arithmetic}


# Issue #87 round 4 (live-fire finding #2): round 3's deterministic device_map
# got the FIRST successful 27B load (496 quantized modules GPU-resident,
# post-load margin assert passed), but the run died one leg later --
# accelerate's offload hook STREAMS a cpu-placed module's weights to the GPU
# for every forward call that touches it (cpu-placed != cpu-computed: the
# module's PARAMETERS live in host RAM, but the matmul itself still runs on
# the execution device, so accelerate copies the weights over just-in-time,
# on TOP of whatever else is GPU-resident at that moment). Round 3's
# vram_sanity only budgeted the resident quantized trunk; it never accounted
# for this streamed cost, nor for the LoRA adapter's own weight+grad+optimizer
# mass, nor for forward/backward activation memory. governed_fit_v2 below
# closes all three gaps with a single pre-leg, fail-closed budget check.

NF4_BLOCKSIZE = 64  # this repo's OWN conversion script's Params4bit(...,
# blocksize=64, ...) call (scripts/convert_nf4_prequant.py, verified by direct
# grep -- never bitsandbytes' library default assumed blind). Cross-checked
# against the real checkpoint: model.layers.0.mlp.gate_proj.weight.absmax has
# 1,392,640 entries; 1,392,640*64 == 89,128,960 == hidden_size(5120) *
# intermediate_size(17408) exactly.

# LoRA-mass sizing assumption (disclosed, not hidden -- same posture as v1's
# cpu_budget_gb "natural sufficient upper bound"): peft's LoRA adapter
# parameters default to fp32 regardless of the frozen base's compute dtype,
# and Leg 3's own torch.optim.Adam (see main()) allocates FOUR fp32-sized
# slots per trainable param once .step() first runs: the weight itself, its
# gradient (loss.backward() populates p.grad), and Adam's two running-moment
# buffers (exp_avg, exp_avg_sq). This is an upper-bound estimate, not an
# exact reproduction of peft/torch internals.
LORA_PARAM_DTYPE_BYTES = 4
LORA_STATE_MULTIPLIER = 4  # weight + grad + adam.exp_avg + adam.exp_avg_sq

# Activation-budget sizing assumption (disclosed): round-4 item 1 enables
# gradient checkpointing UNCONDITIONALLY before LoRA attach (see main()),
# which bounds resident forward activations to roughly one checkpoint
# segment's worth (the current layer's forward output plus one in-flight
# recompute buffer during backward) rather than one-per-layer across the
# whole 64-layer stack. bf16 matches the checkpoint's own
# bnb_4bit_compute_dtype (read from quantization_config, not a separate
# invented dtype).
ACTIVATION_DTYPE_BYTES = 2
ACTIVATION_RESIDENT_LAYERS_WITH_CHECKPOINTING = 2


def read_model_config_dims(model_path: str) -> dict:
    """Reads the checkpoint's own config.json for the architecture dims
    round-4's LoRA-mass/activation arithmetic needs (hidden_size,
    intermediate_size) -- never hardcoded/assumed. Returns {} (never raises)
    if absent/malformed -- same hermetic-reader convention as
    read_safetensors_index_weight_map/read_convert_receipt_skip_set above."""
    p = Path(model_path) / "config.json"
    if not p.is_file():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return {"hidden_size": d.get("hidden_size"), "intermediate_size": d.get("intermediate_size")}


def derive_lora_target_module_dims(model_path: str, weight_map: dict, hidden_size, intermediate_size) -> dict:
    """Issue #87 round 4: derives the (in_features, out_features) PAIR for
    each LoRA target-module TYPE straight from the checkpoint's own quant
    metadata -- never an assumed num_heads*head_dim formula (this Qwen3.6
    hybrid architecture's q_proj output width does NOT equal
    num_attention_heads*head_dim; verified by direct inspection against the
    real checkpoint -- q_proj resolves to 2x the naive expectation, an
    architecture-specific fact this function discovers rather than assumes).

    For a bnb-NF4-quantized weight the base '.weight' tensor's on-disk
    'shape' is a PACKED byte count, not the logical shape -- the true
    element count is absmax_length * NF4_BLOCKSIZE (the absmax sidecar's own
    length IS the number of quantization blocks). One of the two logical
    dimensions is always hidden_size or intermediate_size (the residual
    stream / MLP intermediate width, both read from config.json); this
    function tries both and keeps whichever divides the element count
    evenly (both do, harmlessly, for a square-ish MLP tensor -- direction
    doesn't matter since only the SUM in+out feeds the LoRA-mass formula).
    Returns {module_type: {"known_dim", "other_dim", "numel"}} for every
    target-module type actually present in weight_map (via its .absmax
    sidecar); a type with no divisible match gets None dims."""
    example_by_type: dict = {}
    for tensor_key, shard_file in weight_map.items():
        if not tensor_key.endswith(".weight.absmax"):
            continue
        base = tensor_key[: -len(".absmax")]
        module_name = _owning_module_name(base)
        module_type = module_name.rsplit(".", 1)[-1]
        example_by_type.setdefault(module_type, (tensor_key, shard_file))

    known_dims = {"hidden_size": hidden_size, "intermediate_size": intermediate_size}
    header_cache: dict = {}
    dims = {}
    for module_type, (tensor_key, shard_file) in example_by_type.items():
        if shard_file not in header_cache:
            header_cache[shard_file] = read_safetensors_header(Path(model_path) / shard_file)
        info = header_cache[shard_file].get(tensor_key)
        if info is None or "shape" not in info:
            dims[module_type] = {"known_dim": None, "other_dim": None, "numel": None}
            continue
        numel = info["shape"][0] * NF4_BLOCKSIZE
        resolved = None
        for dim_val in (known_dims.get("hidden_size"), known_dims.get("intermediate_size")):
            if dim_val and numel % dim_val == 0:
                resolved = {"known_dim": dim_val, "other_dim": numel // dim_val, "numel": numel}
                break
        dims[module_type] = resolved if resolved is not None else {"known_dim": None, "other_dim": None, "numel": numel}
    return dims


def estimate_lora_trainable_params(weight_map: dict, target_module_dims: dict, target_modules: list, lora_rank: int) -> dict:
    """Issue #87 round 4: counts how many LAYER INSTANCES of each target
    module type actually exist in the checkpoint -- never assumed uniform
    across all layers (this hybrid architecture only puts self_attn's
    q/k/v/o_proj on a SUBSET of layers; mlp's gate/up/down_proj are on every
    layer -- both facts discovered from weight_map, not hardcoded 16/64).
    Trainable params = lora_rank*(in_features+out_features) per instance,
    summed. Pure dict/string operations on weight_map, no torch/peft import
    -- the CPU-computable cross-check for what peft's get_peft_model() will
    produce on the real GPU, verifiable entirely before touching one."""
    instance_counts: dict = {}
    for tensor_key in weight_map:
        if not tensor_key.endswith(".weight"):
            continue
        module_type = _owning_module_name(tensor_key).rsplit(".", 1)[-1]
        if module_type in target_modules:
            instance_counts[module_type] = instance_counts.get(module_type, 0) + 1

    total_params = 0
    per_module_type = {}
    for module_type in target_modules:
        n_instances = instance_counts.get(module_type, 0)
        dims = target_module_dims.get(module_type)
        if n_instances == 0 or dims is None or dims.get("other_dim") is None:
            per_module_type[module_type] = {"n_instances": n_instances, "params": 0}
            continue
        params_per_instance = lora_rank * (dims["known_dim"] + dims["other_dim"])
        module_total = params_per_instance * n_instances
        per_module_type[module_type] = {
            "n_instances": n_instances, "params_per_instance": params_per_instance, "params": module_total,
        }
        total_params += module_total
    return {"total_trainable_params": total_params, "per_module_type": per_module_type}


def estimate_lora_mass_bytes(total_trainable_params: int) -> dict:
    """Issue #87 round 4: LoRA weight + grad + Adam(exp_avg, exp_avg_sq) --
    see LORA_PARAM_DTYPE_BYTES/LORA_STATE_MULTIPLIER's docstring above for
    the disclosed dtype assumption. Pure arithmetic."""
    total_bytes = total_trainable_params * LORA_PARAM_DTYPE_BYTES * LORA_STATE_MULTIPLIER
    return {
        "total_trainable_params": total_trainable_params,
        "dtype_bytes_assumed": LORA_PARAM_DTYPE_BYTES,
        "state_multiplier": LORA_STATE_MULTIPLIER,
        "lora_mass_bytes": total_bytes,
        "lora_mass_gb": round(total_bytes / 1e9, 4),
    }


def estimate_streamed_offload_bytes(model_path: str, weight_map: dict, cpu_modules: list) -> dict:
    """Issue #87 round 4 (the live-fire finding itself): every module round
    3's device_map places on 'cpu' is NOT compute-resident there --
    accelerate's offload hook streams a cpu-placed module's weights to the
    execution device just-in-time for its forward call (cpu-placed !=
    cpu-computed), so its bytes must be counted as a TEMPORARY GPU-resident
    cost during Leg 3/4, on top of whatever else is already resident. The
    live receipt named lm_head specifically (2.37GiB observed); this
    function deliberately covers EVERY module in cpu_modules uniformly (the
    streaming mechanism is identical for each cpu-placed module) -- for this
    checkpoint that is lm_head AND model.embed_tokens, a disclosed widening
    beyond the single module named in the live receipt."""
    streamed_bytes = compute_module_group_bytes(model_path, weight_map, set(cpu_modules))
    return {
        "streamed_modules": sorted(cpu_modules),
        "streamed_bytes": streamed_bytes,
        "streamed_gb": round(streamed_bytes / 1e9, 4),
    }


def estimate_activation_bytes(hidden_size: int, intermediate_size: int, seq_len: int, batch_size: int = 1) -> dict:
    """Issue #87 round 4: rough, DISCLOSED-ASSUMPTION upper bound for
    forward+backward activation memory with gradient checkpointing enabled
    (round-4 item 1, applied unconditionally before LoRA attach -- see
    main()). This is an ESTIMATE, not an exact reproduction of PyTorch's
    allocator behavior (same posture as v1's cpu_budget_gb) -- it accounts
    for the per-token hidden-stream activation (hidden_size) PLUS the MLP's
    wider intermediate activation (intermediate_size, the gate_proj/up_proj
    output before down_proj contracts it back down), times
    ACTIVATION_RESIDENT_LAYERS_WITH_CHECKPOINTING (current + recompute
    buffer) times ACTIVATION_DTYPE_BYTES (bf16, matching the checkpoint's own
    bnb_4bit_compute_dtype)."""
    per_token_elems = hidden_size + intermediate_size
    total_elems = batch_size * seq_len * per_token_elems * ACTIVATION_RESIDENT_LAYERS_WITH_CHECKPOINTING
    total_bytes = total_elems * ACTIVATION_DTYPE_BYTES
    return {
        "seq_len": seq_len,
        "batch_size": batch_size,
        "resident_layers": ACTIVATION_RESIDENT_LAYERS_WITH_CHECKPOINTING,
        "dtype_bytes_assumed": ACTIVATION_DTYPE_BYTES,
        "activation_bytes": total_bytes,
        "activation_gb": round(total_bytes / 1e9, 6),
    }


def derive_governed_fit_v2(
    model_path: str, weight_map: dict, config_dims: dict, device_map_derivation: dict,
    lora_rank: int, target_modules: list, gpu_budget_gb: float, seq_len: int, batch_size: int = 1,
) -> dict:
    """Issue #87 round 4: the governed-fit budget check, EXTENDED with the
    three terms round 3's vram_sanity never accounted for (trunk-only
    budgeting is what let the live-fire streaming + LoRA-mass overflow slip
    through undetected until Leg 3/4's actual forward call): streamed_head
    (cpu-placed modules temporarily copied to GPU per forward), lora_mass
    (weight+grad+Adam state for the trainable slice), and activation
    (forward/backward intermediate tensors, reduced by gradient
    checkpointing). trunk_gb is round 3's own resident-quantized-modules
    figure, UNCHANGED and still counted -- v2 completes v1/round-3's
    arithmetic, it does not replace it. gpu_budget_gb is v1's own
    derive_governed_fit_max_memory arithmetic, reused rather than
    re-derived. Returns a dict with every term broken out plus a
    fail-closed 'fits' bool the caller asserts on BEFORE from_pretrained --
    a pre-leg gate, not a post-hoc one, so a bad launch is refused before
    any GPU cycle is spent."""
    hidden_size = config_dims.get("hidden_size")
    intermediate_size = config_dims.get("intermediate_size")

    trunk_bytes = compute_module_group_bytes(
        model_path, weight_map, set(device_map_derivation["classified"]["quantized_modules"]),
    )
    trunk_gb = round(trunk_bytes / 1e9, 4)

    streamed = estimate_streamed_offload_bytes(model_path, weight_map, device_map_derivation["cpu_modules"])

    target_dims = derive_lora_target_module_dims(model_path, weight_map, hidden_size, intermediate_size)
    lora_params = estimate_lora_trainable_params(weight_map, target_dims, target_modules, lora_rank)
    lora_mass = estimate_lora_mass_bytes(lora_params["total_trainable_params"])

    activation = estimate_activation_bytes(hidden_size, intermediate_size, seq_len, batch_size)

    total_required_gb = round(
        trunk_gb + streamed["streamed_gb"] + lora_mass["lora_mass_gb"] + activation["activation_gb"], 4,
    )
    headroom_gb = round(gpu_budget_gb - total_required_gb, 4)

    return {
        "gpu_budget_gb": gpu_budget_gb,
        "trunk_gb": trunk_gb,
        "streamed_head": streamed,
        "lora_target_dims": target_dims,
        "lora_trainable_params": lora_params,
        "lora_mass": lora_mass,
        "activation": activation,
        "total_required_gb": total_required_gb,
        "headroom_gb": headroom_gb,
        "fits": headroom_gb > 0,
    }


# Issue #87 round 5 (structural cure): round 4's fail-closed assert correctly
# refused every rank in the [100M,300M] band because the STREAMING itself
# was the problem, not the rank. Round 5 removes streaming at the source --
# item (a) makes lm_head NF4-resident on GPU (no longer cpu-placed-bf16),
# item (b) neutralizes model.embed_tokens' accelerate offload hook so its
# weight table NEVER moves (only the tiny per-forward output activation
# does). v2.1 hard-asserts streamed_bytes==0 under this architecture rather
# than merely computing it, and adds the two new resident-cost terms plus a
# CUDA-allocator fragmentation term.

# Real-checkpoint-calibrated NF4 sidecar byte constants (issue #87 round 5):
# verified EXACTLY against this checkpoint's own already-quantized tensors
# (e.g. model.layers.0.mlp.gate_proj: packed=44,564,480 + absmax=5,570,560 +
# quant_map=64 + quant_state=83 == 50,135,187 bytes, matching the real
# measured total byte-for-byte) -- never guessed round numbers.
NF4_QUANT_MAP_BYTES = 64  # bnb's fixed 16-entry fp32 NF4 lookup table, constant regardless of tensor size
NF4_QUANT_STATE_OVERHEAD_BYTES = 83  # the fixed-size quant_state.bitsandbytes__nf4 sidecar, constant per tensor

# Fragmentation constants (issue #87 round-5 comment, team-lead's own
# live-fire-informed figures) -- NOT independently re-derived here, cited as
# sourced from the frozen spec rather than invented by this arithmetic. These
# are literal GiB constants (never byte-computed), so the round-5.1 units fix
# below does not change their VALUES, only their names (GiB, not GB).
FRAGMENTATION_GIB_STREAMING_REGIME = 1.5
FRAGMENTATION_GIB_STATIC_REGIME = 0.75

# Issue #87 round 5.1 (units-audit cure, team-lead finding): governed_fit
# v2's fields (trunk_gb, lora_mass_gb, streamed_gb, activation_gb) and
# round 5's initial v2.1 draft were ALL computed via `/ 1e9` -- decimal GB,
# NOT true binary GiB -- while the real, physical GPU accounting team-lead
# reads (nvidia-smi, torch.cuda memory stats, the accelerate max_memory
# ceiling this whole budget check exists to respect) is GiB-denominated.
# Reproduced case: lm_head's real bf16 size is 248320*5120*2 =
# 2,542,796,800 bytes = 2.5428 decimal-GB (what an `/1e9` computation
# reports, and exactly the figure the round-5 report quoted) but 2.3682
# TRUE GiB (matching team-lead's live-fire receipt's 2.37GiB almost
# exactly) -- the "2.5428GiB" figure quoted in the round-5 report was a
# decimal-GB number mislabeled GiB, not a real discrepancy. BYTES_PER_GIB
# and bytes_to_gib() are defined once, near derive_governed_fit_max_memory
# above (round 5.2 needed the same helper one layer upstream) -- every
# governed_fit_v2_1 byte->size conversion below goes through that ONE
# shared helper, no inline `/ 1e9` or `/ 1073741824` literals scattered
# across this module's v2.1 code. (v2's own already-gated fields are left
# untouched -- see derive_governed_fit_v2_1's docstring for why that scope
# line was drawn there.)


# bitsandbytes.optim.optimizer.Optimizer2State's OWN state layout (the base
# class AdamW8bit inherits from) -- read directly from
# bitsandbytes/optim/optimizer.py's init_state this round, never guessed:
# state1/state2 are uint8 (1 byte/element) when optim_bits==8 AND
# p.numel() >= min_8bit_size (else it silently falls back to fp32 state);
# block_wise=True (AdamW8bit's own default) additionally allocates
# absmax1/absmax2, one fp32 value per `blocksize=256` elements (a HARDCODED
# literal in bnb's own init_state -- 256, NOT this repo's NF4_BLOCKSIZE=64,
# a different quantity for a different quantizer); qmap1/qmap2 are a fixed
# 256-entry fp32 lookup table SHARED across the whole optimizer instance
# (F.create_dynamic_map()), a one-time global cost, never per-parameter.
BNB_8BIT_MIN_SIZE = 4096  # bnb's own min_8bit_size default (Optimizer2State.__init__)
BNB_8BIT_BLOCKSIZE = 256  # bnb's own hardcoded blockwise-state block size (init_state literal)
BNB_8BIT_QMAP_ENTRIES = 256  # F.create_dynamic_map()'s fixed table size
BNB_8BIT_QMAP_BYTES_TOTAL = 2 * BNB_8BIT_QMAP_ENTRIES * 4  # qmap1+qmap2, fp32, GLOBAL (one-time, not per-param)


def estimate_nf4_quantized_bytes(numel: int, blocksize: int = NF4_BLOCKSIZE) -> dict:
    """Issue #87 round 5 items (a)/(d): analytically estimates the on-disk/
    GPU-resident byte size an nn.Linear weight of `numel` elements would
    occupy AFTER bnb NF4 quantization -- packed 4-bit data (numel//2 bytes,
    2 values packed per byte) + one fp32 absmax per quantization block
    (ceil(numel/blocksize)*4 bytes) + the fixed quant_map/quant_state sidecar
    sizes above. double_quant is NOT modeled (this checkpoint's own
    bnb_4bit_use_double_quant is False, matching its quantization_config).
    This is the ANALYTICAL counterpart to compute_module_group_bytes -- used
    for a tensor NOT YET quantized on disk (lm_head today, pre-round-5),
    whose post-quantization size can only be estimated, never read from a
    header that doesn't exist yet. VERIFIED to reproduce this checkpoint's
    own already-quantized tensors' real measured byte totals EXACTLY (see
    module comment above) before being trusted for this extrapolation.
    total_gib is TRUE GiB (round 5.1 units-audit cure, bytes_to_gib)."""
    packed_bytes = numel // 2
    n_blocks = -(-numel // blocksize)  # ceil division -- a partial final block still needs its own absmax
    absmax_bytes = n_blocks * 4
    total_bytes = packed_bytes + absmax_bytes + NF4_QUANT_MAP_BYTES + NF4_QUANT_STATE_OVERHEAD_BYTES
    return {
        "numel": numel, "packed_bytes": packed_bytes, "absmax_bytes": absmax_bytes,
        "quant_map_bytes": NF4_QUANT_MAP_BYTES, "quant_state_overhead_bytes": NF4_QUANT_STATE_OVERHEAD_BYTES,
        "total_bytes": total_bytes, "total_gib": round(bytes_to_gib(total_bytes), 4),
    }


def estimate_embed_transfer_bytes(hidden_size: int, seq_len: int, batch_size: int = 1, dtype_bytes: int = 2) -> dict:
    """Issue #87 round 5 item (b): after model.embed_tokens' offload hook is
    neutralized, its weight table NEVER moves to GPU -- the ONLY thing that
    still crosses CPU->GPU every forward is the (batch, seq_len, hidden_size)
    output activation of the CPU-side embedding lookup itself (bf16,
    matching the checkpoint's own bnb_4bit_compute_dtype). This is the exact
    'ship only the batch*seq*hidden_size activation' cost named in the round-5
    spec -- orders of magnitude smaller than streaming the full weight table.
    total_gib is TRUE GiB (round 5.1 units-audit cure, bytes_to_gib)."""
    total_bytes = batch_size * seq_len * hidden_size * dtype_bytes
    return {"batch_size": batch_size, "seq_len": seq_len, "hidden_size": hidden_size,
            "dtype_bytes": dtype_bytes, "total_bytes": total_bytes,
            "total_gib": round(bytes_to_gib(total_bytes), 6)}


def estimate_lora_mass_bytes_by_optimizer(
    total_trainable_params: int, optimizer_pricing_mode: str,
    lora_target_dims: dict, lora_rank: int,
) -> dict:
    """Issue #87 round 5.1 (defect #1 cure, team-lead finding): v2's
    estimate_lora_mass_bytes prices ONLY fp32 Adam (weight+grad+2 fp32
    moments = 16 bytes/param) -- correct for dry_run (build_lora_optimizer's
    torch.optim.Adam branch) but WRONG for the live path, which item (c)
    makes bitsandbytes.optim.AdamW8bit. This function prices whichever
    optimizer the run ACTUALLY constructs:

    'fp32_adam' (matches v2's estimate_lora_mass_bytes exactly, used for
    dry_run/control-flow-parity comparisons): weight(4B)+grad(4B)+
    exp_avg(4B)+exp_avg_sq(4B) = 16 bytes/param, no block overhead.

    'bnb_adamw8bit' (the LIVE path since item (c)): weight(4B fp32,
    the LoRA adapter tensor itself stays fp32)+grad(4B fp32)+state1(1B
    uint8)+state2(1B uint8), PLUS the blockwise absmax overhead
    (BNB_8BIT_BLOCKSIZE=256, TWO fp32 absmax tensors, read directly from
    bitsandbytes' own init_state -- never guessed) PLUS the one-time global
    qmap overhead (BNB_8BIT_QMAP_BYTES_TOTAL, shared across the whole
    optimizer instance, disclosed rather than silently dropped).

    Assumes every priced LoRA tensor is >= BNB_8BIT_MIN_SIZE (bnb's own
    threshold below which it silently falls back to fp32 state) --
    ACTUALLY VERIFIED here (not just assumed) against lora_target_dims'
    smallest A/B matrix at this lora_rank; min_8bit_size_assumption_holds
    is a real computed boolean, not a decorative stub."""
    assert optimizer_pricing_mode in ("fp32_adam", "bnb_adamw8bit"), (
        f"optimizer_pricing_mode must be 'fp32_adam' or 'bnb_adamw8bit', got {optimizer_pricing_mode!r}"
    )

    smallest_tensor_numel = None
    for dims in lora_target_dims.values():
        known_dim, other_dim = dims.get("known_dim"), dims.get("other_dim")
        if known_dim is None or other_dim is None:
            continue
        for n in (lora_rank * known_dim, other_dim * lora_rank):
            if smallest_tensor_numel is None or n < smallest_tensor_numel:
                smallest_tensor_numel = n
    min_8bit_size_assumption_holds = (
        smallest_tensor_numel is None or smallest_tensor_numel >= BNB_8BIT_MIN_SIZE
    )

    weight_bytes = total_trainable_params * 4
    grad_bytes = total_trainable_params * 4
    if optimizer_pricing_mode == "fp32_adam":
        state_bytes = total_trainable_params * 4 * 2  # exp_avg + exp_avg_sq, both fp32
        blockwise_overhead_bytes = 0
        qmap_overhead_bytes = 0
    else:
        state_bytes = total_trainable_params * 1 * 2  # state1 + state2, both uint8
        n_blocks = -(-total_trainable_params // BNB_8BIT_BLOCKSIZE)  # ceil division
        blockwise_overhead_bytes = n_blocks * 4 * 2  # absmax1 + absmax2, fp32, per block
        qmap_overhead_bytes = BNB_8BIT_QMAP_BYTES_TOTAL  # global, one-time

    total_bytes = weight_bytes + grad_bytes + state_bytes + blockwise_overhead_bytes + qmap_overhead_bytes
    return {
        "optimizer_pricing_mode": optimizer_pricing_mode,
        "total_trainable_params": total_trainable_params,
        "weight_bytes": weight_bytes,
        "grad_bytes": grad_bytes,
        "state_bytes": state_bytes,
        "blockwise_overhead_bytes": blockwise_overhead_bytes,
        "qmap_overhead_bytes": qmap_overhead_bytes,
        "total_bytes": total_bytes,
        "lora_mass_gib": round(bytes_to_gib(total_bytes), 4),
        "smallest_lora_tensor_numel": smallest_tensor_numel,
        "min_8bit_size_assumption_holds": min_8bit_size_assumption_holds,
    }


def derive_governed_fit_v2_1(
    model_path: str, weight_map: dict, config_dims: dict, device_map_derivation: dict,
    lora_rank: int, target_modules: list, gpu_budget_gb: float, seq_len: int,
    streamed_bytes_actual: int, fragmentation_regime: str, optimizer_pricing_mode: str,
    batch_size: int = 1, max_memory_authorized_gib: float | None = None,
) -> dict:
    """Issue #87 round 5 (round 5.1 units + optimizer-pricing cure; round 5.2
    max_memory units cure; round 5.3 closes the loop between them, all
    team-lead findings): governed-fit v2.1 -- the structural successor to v2
    once items (a)/(b) remove streaming at the source. Differs from v2 in
    FOUR ways: (1) streamed_bytes_actual is HARD-ASSERTED to be exactly 0
    (the caller passes the REAL measured value -- e.g. from the round-5
    sentinel counter -- never an assumption; a nonzero value here means item
    (b)'s hook neutralization did NOT actually take effect, and this
    function refuses rather than silently accepting a nonzero stream), (2)
    lm_head is now counted as a GPU-resident NF4 term
    (estimate_nf4_quantized_bytes) instead of a streamed term, (3) an
    embed_transfer term (the small per-forward CPU->GPU activation) and a
    fragmentation_gib term (regime-dependent, team-lead's own sourced
    constants) are added, (4) lora_mass is priced by the ACTUAL optimizer the
    run constructs (estimate_lora_mass_bytes_by_optimizer,
    optimizer_pricing_mode) rather than v2's fixed fp32-Adam assumption --
    item (c) makes the live path bnb AdamW8bit, and pricing it as fp32 Adam
    was wrong-optimizer-conservative.

    UNITS (round 5.1 requirement terms + round 5.3 budget term -- NO
    residual after this round): every byte->size conversion in THIS function
    goes through bytes_to_gib (TRUE GiB, /2**30) -- trunk_gib, lm_head_nf4,
    embed_transfer, lora_mass, activation, fragmentation, total_required_gib
    are all TRUE GiB. Round 5.1 shipped with those terms true-GiB but the
    BUDGET they were compared against (gpu_budget_gb, fed straight from
    derive_governed_fit_max_memory's decimal-GB-flavored arithmetic field)
    was NOT -- a disclosed-but-unfixed residual at the time (out of that
    round's scope). Round 5.2 fixed max_memory's OWN accelerate-facing
    string/receipt fields to true GiB (max_memory_authorized_gib) but
    deliberately left this function's gpu_budget_gb consumption untouched
    (also out of that round's scope). Round 5.3 closes the gap: the fits
    verdict is now computed EXCLUSIVELY against max_memory_authorized_gib
    (true GiB, matching every requirement term's unit) -- if the caller
    supplies it directly (the real value from derive_governed_fit_max_memory's
    OWN live computation -- this is what main()'s call site does), it is used
    as-is; if omitted (older call sites, existing tests), it is DERIVED from
    gpu_budget_gb via the identical bytes_to_gib(gpu_budget_gb * 1e9)
    round-trip round 5.2 uses, so a caller who only has the legacy
    decimal-GB value still gets a unit-correct fits verdict, never a silent
    fallback to the old (wrong) comparison. gpu_budget_gb itself is returned
    verbatim as gpu_budget_gb_legacy_residual -- kept ONLY for cross-run
    comparability against pre-5.3 reports (e.g. round 5.1's own reported
    figures), NEVER consulted for the fits computation itself.

    Rank is NEVER self-tuned down here if fits=False -- the caller reports
    the exact gap (same discipline as round 4)."""
    assert streamed_bytes_actual == 0, (
        f"CLASS RULE VIOLATED (round 5): streamed_bytes_actual={streamed_bytes_actual} is nonzero -- "
        "item (b)'s embed_tokens offload-hook neutralization did not take effect (or another module is "
        "still streaming). governed_fit_v2.1 refuses to compute a budget that assumes zero streaming "
        "while a live nonzero stream was actually measured."
    )
    assert fragmentation_regime in ("streaming", "static"), (
        f"fragmentation_regime must be 'streaming' or 'static', got {fragmentation_regime!r}"
    )
    fragmentation_gib = (
        FRAGMENTATION_GIB_STREAMING_REGIME if fragmentation_regime == "streaming" else FRAGMENTATION_GIB_STATIC_REGIME
    )

    hidden_size = config_dims.get("hidden_size")
    intermediate_size = config_dims.get("intermediate_size")

    trunk_bytes = compute_module_group_bytes(
        model_path, weight_map, set(device_map_derivation["classified"]["quantized_modules"]),
    )
    trunk_gib = round(bytes_to_gib(trunk_bytes), 4)

    lm_head_numel = None
    for tensor_key, shard_file in weight_map.items():
        if tensor_key == "lm_head.weight":
            hdr = read_safetensors_header(Path(model_path) / shard_file)
            info = hdr.get(tensor_key)
            if info and "shape" in info:
                shape = info["shape"]
                lm_head_numel = shape[0] * shape[1] if len(shape) == 2 else shape[0]
            break
    lm_head_nf4 = estimate_nf4_quantized_bytes(lm_head_numel) if lm_head_numel else None

    embed_transfer = estimate_embed_transfer_bytes(hidden_size, seq_len, batch_size)

    target_dims = derive_lora_target_module_dims(model_path, weight_map, hidden_size, intermediate_size)
    lora_params = estimate_lora_trainable_params(weight_map, target_dims, target_modules, lora_rank)
    lora_mass = estimate_lora_mass_bytes_by_optimizer(
        lora_params["total_trainable_params"], optimizer_pricing_mode, target_dims, lora_rank,
    )

    activation = estimate_activation_bytes(hidden_size, intermediate_size, seq_len, batch_size)
    activation_gib = round(bytes_to_gib(activation["activation_bytes"]), 6)

    lm_head_nf4_gib = lm_head_nf4["total_gib"] if lm_head_nf4 else 0.0
    total_required_gib = round(
        trunk_gib + lm_head_nf4_gib + embed_transfer["total_gib"] + lora_mass["lora_mass_gib"]
        + activation_gib + fragmentation_gib,
        4,
    )

    # Round 5.3: the fits verdict is computed EXCLUSIVELY against
    # max_memory_authorized_gib (TRUE GiB, unit-consistent with every
    # requirement term above) -- never against gpu_budget_gb directly (that
    # was round 5.1's disclosed residual, now closed). If the caller didn't
    # supply the real value (from derive_governed_fit_max_memory's own live
    # computation), derive it via the SAME round-trip round 5.2 uses.
    if max_memory_authorized_gib is None:
        max_memory_authorized_gib = round(bytes_to_gib(gpu_budget_gb * 1e9), 4)
        max_memory_authorized_gib_source = "derived_from_gpu_budget_gb"
    else:
        max_memory_authorized_gib_source = "caller_supplied"
    headroom_gib = round(max_memory_authorized_gib - total_required_gib, 4)

    return {
        "max_memory_authorized_gib": max_memory_authorized_gib,
        "max_memory_authorized_gib_source": max_memory_authorized_gib_source,
        "gpu_budget_gb_legacy_residual": gpu_budget_gb,
        "streamed_bytes_actual": streamed_bytes_actual,
        "trunk_gib": trunk_gib,
        "lm_head_nf4": lm_head_nf4,
        "embed_transfer": embed_transfer,
        "lora_target_dims": target_dims,
        "lora_trainable_params": lora_params,
        "lora_mass": lora_mass,
        "activation": {**activation, "activation_gib": activation_gib},
        "fragmentation_regime": fragmentation_regime,
        "fragmentation_gib": fragmentation_gib,
        "total_required_gib": total_required_gib,
        "headroom_gib": headroom_gib,
        "fits": headroom_gib > 0,
    }


# ---------------------------------------------------------------------------
# Issue #87 round 5.3 items (4)/(5): the launch-gate boundary. NO live GPU
# reads and NO governor.preflight() calls happen in this module -- the real
# preflight reading only exists at fire #7 launch time, in the runner
# process. Both functions below take a preflight_reading DICT (the exact
# shape governor.preflight() returns: {"vram_fraction", "free_gb", "total_gb",
# "margin_gb"}) as a plain argument, so they stay pure/CPU-testable here and
# the runner supplies the live dict at the actual launch call site.
# ---------------------------------------------------------------------------

def assert_governed_fit(
    preflight_reading: dict, model_path: str, weight_map: dict, config_dims: dict,
    device_map_derivation: dict, lora_rank: int, target_modules: list, seq_len: int,
    fragmentation_regime: str, optimizer_pricing_mode: str, expected_mapped_bytes: int,
    batch_size: int = 1,
) -> dict:
    """Issue #87 round 5.3 item (4): the launch-gate assertion. Recomputes
    the FULL governed-fit chain (derive_governed_fit_max_memory ->
    derive_governed_fit_v2_1, round 5.3's unit-consistent budget) from a
    LIVE preflight_reading the caller supplies -- this function itself never
    calls governor.preflight() or touches CUDA, so it is exercised here with
    a synthetic preflight_reading dict exactly like every other CPU-only
    case in this module; the runner passes the REAL dict at fire #7.

    Fail-closed, same posture as this repo's other interlock checks
    (d_gate.py's _check_interlock: refuse unless every condition verifiably
    holds) -- but returned as DATA rather than raised, so the runner can act
    on the refusal (e.g. fall back to derive_max_fitting_rank below) instead
    of the process dying outright. Returns {"authorized": bool,
    "refusal_reason": str|None, "rank", "regime", "fit": <the full
    derive_governed_fit_v2_1 dict>, "max_memory": <the max_memory dict
    accelerate would receive>}. authorized=False whenever fit["fits"] is
    False -- the runner MUST NOT proceed with the launch in that case."""
    max_mem_result = derive_governed_fit_max_memory(
        preflight_reading["vram_fraction"], preflight_reading["total_gb"],
        preflight_reading["margin_gb"], expected_mapped_bytes,
    )
    fit = derive_governed_fit_v2_1(
        model_path, weight_map, config_dims, device_map_derivation,
        lora_rank, target_modules, max_mem_result["arithmetic"]["gpu_budget_gb"],
        seq_len, streamed_bytes_actual=0, fragmentation_regime=fragmentation_regime,
        optimizer_pricing_mode=optimizer_pricing_mode, batch_size=batch_size,
        max_memory_authorized_gib=max_mem_result["arithmetic"]["max_memory_authorized_gib"],
    )
    authorized = bool(fit["fits"])
    refusal_reason = None if authorized else (
        f"governed-fit refused: total_required_gib={fit['total_required_gib']}GiB > "
        f"max_memory_authorized_gib={fit['max_memory_authorized_gib']}GiB "
        f"(headroom={fit['headroom_gib']}GiB, rank={lora_rank}, regime={fragmentation_regime})"
    )
    return {
        "authorized": authorized,
        "refusal_reason": refusal_reason,
        "rank": lora_rank,
        "regime": fragmentation_regime,
        "fit": fit,
        "max_memory": max_mem_result["max_memory"],
    }


def derive_max_fitting_rank(
    preflight_reading: dict, fragmentation_regime: str, ranks: list,
    model_path: str, weight_map: dict, config_dims: dict, device_map_derivation: dict,
    target_modules: list, seq_len: int, optimizer_pricing_mode: str,
    expected_mapped_bytes: int, batch_size: int = 1,
) -> dict:
    """Issue #87 round 5.3 item (5): the launch-gate's graceful-degradation
    fallback. When assert_governed_fit refuses the requested rank, this
    sweeps `ranks` (any order -- sorted here, descending) and returns the
    LARGEST rank that is BOTH authorized (assert_governed_fit's fit["fits"])
    AND trainable-param-band-legal ([TARGET_TRAINABLE_MIN,
    TARGET_TRAINABLE_MAX]) -- a rank that fits memory-wise but falls outside
    the band is NOT a legal launch target (round 5.1's own finding: ranks
    <=18 fit trivially but were never band-legal). NEVER widens governor
    caps/margin to force a fit -- those are constitution (team-lead
    directive) -- this only searches the ALREADY-governed, ALREADY-band-
    scoped rank space for the best available answer.

    Returns {"max_fitting_rank": int|None, "candidates": [{"rank",
    "authorized", "band_ok", "headroom_gib", "n_trainable"}, ...]} --
    max_fitting_rank is None if no candidate rank is both authorized and
    band-legal (the runner must refuse the launch entirely, never invent a
    below-band rank to force a pass)."""
    candidates = []
    for rank in sorted(set(ranks), reverse=True):
        result = assert_governed_fit(
            preflight_reading, model_path, weight_map, config_dims, device_map_derivation,
            rank, target_modules, seq_len, fragmentation_regime, optimizer_pricing_mode,
            expected_mapped_bytes, batch_size,
        )
        n_trainable = result["fit"]["lora_trainable_params"]["total_trainable_params"]
        band_ok = TARGET_TRAINABLE_MIN <= n_trainable <= TARGET_TRAINABLE_MAX
        candidates.append({
            "rank": rank,
            "authorized": result["authorized"],
            "band_ok": band_ok,
            "headroom_gib": result["fit"]["headroom_gib"],
            "n_trainable": n_trainable,
        })
    legal_ranks = [c["rank"] for c in candidates if c["authorized"] and c["band_ok"]]
    max_fitting_rank = max(legal_ranks) if legal_ranks else None
    return {"max_fitting_rank": max_fitting_rank, "candidates": candidates}


def resolve_governed_launch_rank(
    preflight_reading: dict, model_path: str, weight_map: dict, config_dims: dict,
    device_map_derivation: dict, requested_rank: int, target_modules: list, seq_len: int,
    fragmentation_regime: str, optimizer_pricing_mode: str, expected_mapped_bytes: int,
    rank_sweep_candidates: list, batch_size: int = 1,
) -> dict:
    """Issue #87 round 5.4: the exact launch-gate resolution main() drives,
    extracted as a pure function so it is CPU-testable in isolation (main()
    itself does live CUDA loads and cannot be unit-tested directly). Gates
    at requested_rank via assert_governed_fit; if authorized, returns
    immediately with no degradation. If refused, sweeps
    rank_sweep_candidates via derive_max_fitting_rank; if a band-legal,
    authorized candidate exists, RE-GATES at that exact granted rank (a
    second assert_governed_fit call -- never trusts the sweep's own
    per-candidate authorized flag as a substitute for a real re-check) and
    returns the granted result with a populated degradation record. If no
    candidate qualifies, returns the ORIGINAL refusal at requested_rank with
    granted_rank=None and rank_degradation=None -- the CALLER (main()) is
    responsible for asserting on granted_rank is None and never proceeding;
    this function itself never raises on a legitimate hard refusal (only on
    the internal-inconsistency case below, which is a genuine bug signal,
    not a refusal).

    Governor caps/margin are NEVER widened here to force a fit -- this only
    ever searches DOWNWARD within rank_sweep_candidates (derive_max_fitting_rank's
    own contract), returning None rather than inventing a rank when nothing
    qualifies.

    Returns {"gate_result": <assert_governed_fit's dict, from the FINAL
    (possibly re-gated) rank -- authorized reflects whether the caller may
    proceed>, "rank_degradation": dict|None (requested_rank,
    requested_rank_refusal_reason, granted_rank, candidates), "granted_rank":
    int|None, "sweep_candidates": list|None (the full derive_max_fitting_rank
    candidates table when a sweep ran, None if the requested rank was
    authorized outright and no sweep was needed)}."""
    gate_result = assert_governed_fit(
        preflight_reading, model_path, weight_map, config_dims, device_map_derivation,
        requested_rank, target_modules, seq_len, fragmentation_regime, optimizer_pricing_mode,
        expected_mapped_bytes, batch_size,
    )
    if gate_result["authorized"]:
        return {
            "gate_result": gate_result, "rank_degradation": None,
            "granted_rank": requested_rank, "sweep_candidates": None,
        }

    sweep = derive_max_fitting_rank(
        preflight_reading, fragmentation_regime, rank_sweep_candidates,
        model_path, weight_map, config_dims, device_map_derivation,
        target_modules, seq_len, optimizer_pricing_mode, expected_mapped_bytes, batch_size,
    )
    granted_rank = sweep["max_fitting_rank"]
    if granted_rank is None:
        # Hard refusal -- propagate the ORIGINAL refusal at requested_rank;
        # the caller must refuse the launch, never invent a fallback rank.
        return {
            "gate_result": gate_result, "rank_degradation": None,
            "granted_rank": None, "sweep_candidates": sweep["candidates"],
        }

    regated = assert_governed_fit(
        preflight_reading, model_path, weight_map, config_dims, device_map_derivation,
        granted_rank, target_modules, seq_len, fragmentation_regime, optimizer_pricing_mode,
        expected_mapped_bytes, batch_size,
    )
    assert regated["authorized"], (
        "INTERNAL INCONSISTENCY (round 5.4): derive_max_fitting_rank granted "
        f"rank={granted_rank} as authorized+band-legal, but re-gating at that exact rank "
        f"refused ({regated['refusal_reason']}) -- the two computations disagree; "
        "the caller must refuse launch rather than trust a contradictory verdict."
    )
    rank_degradation = {
        "requested_rank": requested_rank,
        "requested_rank_refusal_reason": gate_result["refusal_reason"],
        "granted_rank": granted_rank,
        "candidates": sweep["candidates"],
    }
    return {
        "gate_result": regated, "rank_degradation": rank_degradation,
        "granted_rank": granted_rank, "sweep_candidates": sweep["candidates"],
    }


# Issue #87 reopened: the checkpoint's own serialized quantization_config core
# fields that fully determine its quantization arithmetic -- these are the
# ONLY fields the cure below is permitted to replicate (read verbatim from
# config.json, never invented, never widened to other quantization_config
# keys such as llm_int8_threshold/llm_int8_skip_modules that the cure spec
# does not name).
BNB_CORE_FIELDS = (
    "load_in_4bit",
    "bnb_4bit_quant_type",
    "bnb_4bit_use_double_quant",
    "bnb_4bit_compute_dtype",
    "bnb_4bit_quant_storage",
)


def derive_cpu_offload_bnb_override(serialized_quant_config: dict) -> dict:
    """Issue #87 reopened (live-fire finding): transformers' Bnb4BitHfQuantizer
    .validate_environment refuses ANY cpu-dispatched module unless the quant
    config it receives carries llm_int8_enable_fp32_cpu_offload=True -- and
    the #86 prequantized load path passes NO quantization_config at all (by
    design, to avoid double-configuring an already-quantized checkpoint), so
    the flag never reaches the quantizer and a governed-fit CPU-dispatched
    load CUDA-OOMs/refuses at the quantizer's own environment check.

    Cure: build override kwargs by REPLICATING the checkpoint's own serialized
    quantization_config core fields (BNB_CORE_FIELDS) field-for-field -- never
    inventing a value the checkpoint doesn't already state -- and adding ONLY
    the one new permission flag. This is not a re-quantization and does not
    alter any quant arithmetic; it grants CPU-offload permission for the exact
    quantization the checkpoint was already saved with (transformers'
    BitsAndBytesConfig accepts the serialized string values -- e.g.
    bnb_4bit_compute_dtype="bfloat16" -- directly and converts them internally,
    so no dtype-object conversion happens here).

    Returns {"bnb_config_kwargs": <dict ready for BitsAndBytesConfig(**kwargs)>,
    "quant_config_replicated_fields": <dict of only the BNB_CORE_FIELDS present
    in serialized_quant_config, for the receipt's field-by-field equality
    assertion>, "offload_flag_added": "llm_int8_enable_fp32_cpu_offload"}.
    Pure dict operations -- no BitsAndBytesConfig/torch/transformers import,
    so this stays unit-testable in isolation, same as detect_prequantized_config
    and derive_governed_fit_max_memory above."""
    replicated = {
        field: serialized_quant_config[field]
        for field in BNB_CORE_FIELDS
        if field in serialized_quant_config
    }
    bnb_config_kwargs = dict(replicated)
    bnb_config_kwargs["llm_int8_enable_fp32_cpu_offload"] = True
    return {
        "bnb_config_kwargs": bnb_config_kwargs,
        "quant_config_replicated_fields": replicated,
        "offload_flag_added": "llm_int8_enable_fp32_cpu_offload",
    }


# Issue #87 round 3 (live-fire finding): a bnb-quantized tensor's on-disk
# storage always carries sidecar keys alongside its base '<name>.weight' key
# -- confirmed against this repo's OWN prequant artifact's
# model.safetensors.index.json (e.g. 'model.layers.0.mlp.down_proj.weight'
# has siblings '...weight.absmax', '...weight.quant_map',
# '...weight.quant_state.bitsandbytes__nf4'; 'lm_head.weight' and
# 'model.embed_tokens.weight' have none). This is the checkpoint's own,
# unambiguous, index-native signal for "was this tensor actually quantized"
# -- never a name-guess (e.g. never assuming embed_tokens is unquantized by
# convention; the index is asked directly).
BNB_SIDECAR_SUFFIXES = (
    ".absmax",
    ".quant_map",
    ".quant_state.bitsandbytes__nf4",
    ".quant_state.bitsandbytes__fp4",
    ".nested_absmax",
    ".nested_quant_map",
)


def _base_tensor_name(tensor_key: str) -> str:
    """Strips a bnb sidecar suffix (if any) back to the base parameter name
    a checkpoint would carry pre-quantization (e.g.
    '...down_proj.weight.quant_state.bitsandbytes__nf4' -> '...down_proj.weight').
    Non-sidecar keys pass through unchanged."""
    for suffix in BNB_SIDECAR_SUFFIXES:
        if tensor_key.endswith(suffix):
            return tensor_key[: -len(suffix)]
    return tensor_key


def _owning_module_name(base_tensor_name: str) -> str:
    """Strips the final '.weight'/'.bias'/parameter-attribute segment to get
    the fully-qualified nn.Module name that OWNS this parameter/buffer (e.g.
    'model.layers.3.mlp.down_proj.weight' -> 'model.layers.3.mlp.down_proj';
    'model.layers.3.linear_attn.A_log' -> 'model.layers.3.linear_attn'). This
    is what HF's device_map is keyed on, not individual tensor names."""
    parts = base_tensor_name.rsplit(".", 1)
    return parts[0] if len(parts) == 2 else base_tensor_name


def classify_checkpoint_tensors(weight_map: dict) -> dict:
    """Issue #87 round 3: derive, PURELY from the checkpoint's own weight
    index keys (model.safetensors.index.json's weight_map -- never from
    architecture assumptions or name-guessing), which base tensors/modules
    are bnb-4bit-quantized (identified by the presence of their own
    quant-state sidecar keys) vs kept in original dtype. Pure dict/string
    operations, no torch/transformers/CUDA."""
    base_names = {_base_tensor_name(k) for k in weight_map}
    sidecar_bases = {
        _base_tensor_name(k) for k in weight_map
        if any(k.endswith(sfx) for sfx in BNB_SIDECAR_SUFFIXES)
    }
    quantized_base_tensors = sorted(sidecar_bases)
    unquantized_base_tensors = sorted(base_names - sidecar_bases)
    return {
        "quantized_base_tensors": quantized_base_tensors,
        "unquantized_base_tensors": unquantized_base_tensors,
        "quantized_modules": sorted({_owning_module_name(n) for n in quantized_base_tensors}),
        "unquantized_modules": sorted({_owning_module_name(n) for n in unquantized_base_tensors}),
    }


def derive_deterministic_device_map(weight_map: dict, skip_set: list) -> dict:
    """Issue #87 round 3 (live-fire finding): device_map='auto' let
    accelerate's greedy bin-packer place a QUANTIZED module on CPU, and this
    bnb/accelerate version pairing cannot construct an offloaded Params4bit
    (TypeError: Params4bit.__new__ got an unexpected keyword argument
    '_is_hf_initialized', from accelerate's set_module_tensor_to_device
    forwarding param attrs into the constructor). Class rule: under this
    environment, a 4-bit-quantized module must NEVER be placed off-GPU; only
    genuinely unquantized (bf16/fp32) modules may offload.

    Deterministic cure: derive a COARSE, EXPLICIT device_map straight from the
    checkpoint's own weight index (never accelerate's heuristic) --
    'model' (the catch-all covering every quantized decoder-layer module) ->
    GPU index 0; every module named in the convert receipt's skip_set (e.g.
    lm_head) -> cpu; 'model.embed_tokens' -> cpu ONLY IF the index itself
    shows it carries no bnb sidecar tensors (nn.Embedding is never
    Linear4bit-quantized regardless of skip_set -- this is checked against
    the index, never assumed). accelerate resolves the most-specific matching
    prefix per module (see resolve_device_for_module below), so this coarse
    map is unambiguous: any module under 'model.*' other than the explicit
    cpu overrides inherits 'model' -> 0."""
    classified = classify_checkpoint_tensors(weight_map)
    device_map = {"model": 0}
    cpu_modules = []
    for name in skip_set:
        device_map[name] = "cpu"
        cpu_modules.append(name)
    embed_module = "model.embed_tokens"
    if embed_module in classified["unquantized_modules"] and embed_module not in device_map:
        device_map[embed_module] = "cpu"
        cpu_modules.append(embed_module)
    return {
        "device_map": device_map,
        "cpu_modules": sorted(cpu_modules),
        "gpu_module_count": len(classified["quantized_modules"]),
        "source_index": "model.safetensors.index.json",
        "classified": classified,
    }


def resolve_device_for_module(module_name: str, device_map: dict):
    """accelerate's own module-prefix matching semantics: the device_map
    entry with the LONGEST matching prefix (module_name == key, or
    module_name starting with '<key>.') wins. Returns None if nothing
    matches (uncovered by the derived map)."""
    best_key = None
    for key in device_map:
        if module_name == key or module_name.startswith(key + "."):
            if best_key is None or len(key) > len(best_key):
                best_key = key
    return device_map[best_key] if best_key is not None else None


def assert_no_quantized_module_offloaded(device_map: dict, classified: dict) -> dict:
    """Issue #87 round 3 fail-closed rail (the class rule, checked
    mechanically): for EVERY module the index shows carries a quantized
    (bnb sidecar) tensor, its resolved placement under the derived
    device_map must be GPU, never 'cpu'/'disk'/unresolved. Returns a dict
    the caller asserts on and receipts verbatim -- never silently passes an
    offloaded quantized module."""
    offending = []
    uncovered = []
    for module_name in classified["quantized_modules"]:
        placement = resolve_device_for_module(module_name, device_map)
        if placement is None:
            uncovered.append(module_name)
        elif str(placement) in ("cpu", "disk"):
            offending.append({"module": module_name, "placement": placement})
    return {
        "passed": (not offending) and (not uncovered),
        "offending_quantized_modules_offloaded": offending,
        "uncovered_quantized_modules": uncovered,
        "n_quantized_modules_checked": len(classified["quantized_modules"]),
    }


def read_safetensors_index_weight_map(model_path: str) -> dict:
    """Reads the checkpoint's own model.safetensors.index.json weight_map --
    the source of truth for which tensors this specific on-disk checkpoint
    actually carries. Returns {} (never raises) if absent/malformed/no
    weight_map key -- json/pathlib only, no torch/transformers, CPU-testable
    in isolation like detect_prequantized_config above."""
    p = Path(model_path) / "model.safetensors.index.json"
    if not p.is_file():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    wm = d.get("weight_map")
    return dict(wm) if isinstance(wm, dict) else {}


def read_convert_receipt_skip_set(model_path: str) -> list:
    """Reads the checkpoint's own convert_receipt.json (written at NF4-export
    time, issue #97/#98's convert_nf4_prequant.py) for its skip_set list --
    module names deliberately left unquantized. Returns [] (never raises) if
    the receipt is absent or malformed; derive_deterministic_device_map still
    correctly classifies embed_tokens as unquantized directly from the weight
    index regardless, so an absent convert receipt degrades gracefully."""
    p = Path(model_path) / "convert_receipt.json"
    if not p.is_file():
        return []
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    skip_set = d.get("skip_set")
    return list(skip_set) if isinstance(skip_set, list) else []


def read_safetensors_header(shard_path) -> dict:
    """Reads a safetensors file's JSON header ONLY (a few KB) -- never the
    multi-GB tensor payload. Returns {tensor_name: {"dtype", "shape",
    "data_offsets": [start, end]}, ..., "__metadata__": {...}}. A tensor's
    on-disk byte size is (data_offsets[1] - data_offsets[0]) directly from
    this header -- safetensors already accounts for dtype/shape, so no
    dtype-size table is reimplemented here."""
    with open(shard_path, "rb") as f:
        header_len = int.from_bytes(f.read(8), "little")
        header_bytes = f.read(header_len)
    return json.loads(header_bytes)


def compute_module_group_bytes(model_path: str, weight_map: dict, module_names: set) -> int:
    """Issue #87 round 3 item 5 (VRAM arithmetic sanity): sums the REAL
    on-disk byte size (from each shard's safetensors header data_offsets,
    never a hardcoded '~13.7GiB'/'~4.74GiB' figure) of EVERY tensor key --
    base weight AND its bnb sidecars (.absmax/.quant_map/.quant_state...) --
    whose owning module is in module_names. The sidecars are NOT a duplicate
    representation of the base tensor's bytes: the base '.weight' key holds
    the packed 4-bit values, and the sidecars hold the additional scale
    factors/lookup table/metadata bnb needs to dequantize -- ALL of them
    physically reside on whatever device the module is assigned to, so all
    must be counted for a true device-residency byte total (an earlier draft
    of this function excluded sidecars as 'double-counting' and undercounted
    the real quantized-trunk size by ~1.5GiB against this repo's own
    convert_receipt-cited ~13.7GiB figure -- verified by including them).
    Reads each referenced shard's header once, never the tensor payload
    itself -- CPU-only, no GPU, no multi-GB read."""
    needed_shards: dict = {}
    for tensor_key, shard_file in weight_map.items():
        base = _base_tensor_name(tensor_key)
        if _owning_module_name(base) in module_names:
            needed_shards.setdefault(shard_file, []).append(tensor_key)
    total = 0
    for shard_file, tensor_keys in needed_shards.items():
        header = read_safetensors_header(Path(model_path) / shard_file)
        for tensor_key in tensor_keys:
            info = header.get(tensor_key)
            if info and "data_offsets" in info:
                start, end = info["data_offsets"]
                total += (end - start)
    return total


def _embed_tokens_pre_forward_pin_cpu(sentinel: dict, module, args: tuple, kwargs: dict):
    """Issue #87 round 5 item (b): pre-forward hook for the neutralized
    embed_tokens module. Ensures the module's weight parameter is on CPU
    (incrementing sentinel['weight_device_moves'] only if a move was
    ACTUALLY needed -- this must stay 0 forever once device_map placed the
    module on CPU at load time; a nonzero count here means something
    upstream moved the weight off CPU behind this hook's back) and moves
    the (tiny) input ids tensor to CPU so the lookup executes there. Pure
    function taking sentinel/module/args explicitly (not closed over) so it
    is directly unit-testable against a plain CPU nn.Embedding + mock args,
    with zero accelerate/CUDA dependency -- verified this round against a
    real nn.Embedding forward call (zero device-moves, correct output).
    Imports torch locally (this module's established convention -- torch is
    never imported at module level, only inside the functions that use it,
    so the module stays hermetically CPU-testable without CUDA/torch even
    present at import time)."""
    import torch

    if module.weight.device.type != "cpu":
        sentinel["weight_device_moves"] += 1
        module.weight.data = module.weight.data.to("cpu")
    new_args = tuple(a.to("cpu") if torch.is_tensor(a) else a for a in args)
    new_kwargs = {k: (v.to("cpu") if torch.is_tensor(v) else v) for k, v in kwargs.items()}
    return new_args, new_kwargs


def _embed_tokens_post_forward_ship_activation(execution_device, module, input, output):
    """Issue #87 round 5 item (b): post-forward hook -- ships ONLY the
    resulting (batch, seq_len, hidden_size) output activation to
    execution_device. The weight table itself never moves through this
    hook -- that elimination is the entire point (see
    estimate_embed_transfer_bytes / governed_fit_v2_1's embed_transfer
    term, which prices exactly this tensor and nothing more)."""
    return output.to(execution_device)


def neutralize_embed_tokens_offload_hook(base_model, execution_device, sentinel: dict = None) -> dict:
    """Issue #87 round 5 item (b), curing round 4's live-fire finding
    ('cpu-placed != cpu-computed' -- accelerate's default AlignDevicesHook
    streams a cpu-placed module's FULL weight table to the execution device
    for every forward call). For model.embed_tokens specifically this is
    wasteful: an embedding lookup is a cheap CPU-side index_select, and
    streaming a multi-GiB weight table every forward is exactly the
    'streamed_head' cost governed_fit_v2 had to budget for.

    Removes accelerate's AlignDevicesHook from embed_tokens entirely
    (accelerate.hooks.remove_hook_from_module -- confirmed this round to be
    a safe no-op when no hook is attached, so this function is also safe to
    call defensively) and replaces it with the two lightweight custom hooks
    above: a pre-forward hook that pins the weight to CPU (asserted never to
    actually need moving, since device_map already placed it there) and
    moves the input ids to CPU, and a post-forward hook that ships ONLY the
    resulting small activation to execution_device.

    Returns the sentinel dict (weight_device_moves counter) for the
    caller's fail-closed assert -- governed_fit_v2_1's streamed_bytes_actual
    must be fed this counter's value, hard-asserted to 0.

    CPU-VERIFIED THIS ROUND: the two callback functions' full cycle (pin,
    lookup, ship) against a real plain nn.Embedding.forward() call --
    zero weight device-moves, correct output shape/device. NOT YET
    verified against a REAL accelerate-attached AlignDevicesHook on a
    live-GPU-dispatched model (that hook only exists after a real
    device_map from_pretrained call) -- proving the ACTUAL removal of a
    live hook and zero streaming across a real forward pass on the 27B-class
    trunk is team-lead's GPU leg, not reproducible CPU-side."""
    from accelerate.hooks import remove_hook_from_module

    if sentinel is None:
        sentinel = {"weight_device_moves": 0}

    embed = base_model.get_input_embeddings()
    remove_hook_from_module(embed)

    embed.register_forward_pre_hook(
        lambda module, args, kwargs: _embed_tokens_pre_forward_pin_cpu(sentinel, module, args, kwargs),
        with_kwargs=True,
    )
    embed.register_forward_hook(
        lambda module, inp, out: _embed_tokens_post_forward_ship_activation(execution_device, module, inp, out)
    )
    return sentinel


def build_lora_optimizer(trainable_params: list, dry_run: bool, lr: float = 1e-4):
    """Issue #87 round 5 item (c): LoRA optimizer -> bitsandbytes AdamW8bit
    (disclosed feasibility-recipe delta: int8-quantized optimizer moments
    vs fp32 Adam, roughly 4x smaller optimizer-state memory, with disclosed
    numerical rounding noise). Empirically verified THIS round, CPU-side:
    bnb.optim.AdamW8bit.step() raises AttributeError on plain CPU tensors
    (its 8-bit state-quantization update path needs a CUDA kernel) -- so
    dry_run=True (CPU substrate, no CUDA) MUST keep the original
    torch.optim.Adam for control-flow parity with the rest of this harness's
    CPU-only dry-run discipline; only dry_run=False (the real GPU path,
    team-lead's leg) switches to AdamW8bit. Returns
    (optimizer, optimizer_class_name, is_8bit) so the caller can disclose
    which optimizer actually ran in the receipt, never silently. Imports
    torch/bitsandbytes locally (this module's established convention --
    neither is imported at module level, keeping the module hermetically
    CPU-testable at import time)."""
    if dry_run:
        import torch
        return torch.optim.Adam(trainable_params, lr=lr), "torch.optim.Adam", False
    import bitsandbytes as bnb
    return bnb.optim.AdamW8bit(trainable_params, lr=lr), "bitsandbytes.optim.AdamW8bit", True


def main() -> None:
    args = parse_args()
    t_start = time.time()
    log(f"=== R3 feasibility probe (issue #47) -- dry_run={args.dry_run} ===")

    import torch
    torch.manual_seed(args.seed)

    # --- Governor config: read from the standard config, never re-derived ---
    frac, margin_gb, throttle_s = governor.env_limits()
    log(f"governor config (standard, from env_limits()): vram_fraction={frac} margin_gb={margin_gb} throttle_s={throttle_s}")

    preflight_before = None
    commit_preflight = None
    if args.dry_run:
        log("SKIPPED (dry-run, no CUDA): governor.preflight() margin assert BEFORE load")
        log("SKIPPED (dry-run, no CUDA): governor.commit_margin_preflight() host commit-charge assert")
    else:
        preflight_before = governor.preflight()  # raises SystemExit if insufficient free VRAM
        log(f"margin assert BEFORE load PASSED: {preflight_before}")

        # Host commit-charge preflight (issue #84) -- VRAM margin above guards
        # the GPU; this guards the HOST, the #81 incident's own gap (a 27B
        # from_pretrained() mmap load charged commit the VRAM assert never
        # sees). expected_mapped_bytes = every safetensors shard this
        # from_pretrained() call is about to open simultaneously.
        shard_paths = sorted(str(p) for p in Path(args.model).glob("*.safetensors")) \
            if Path(args.model).is_dir() else []
        expected_mapped_bytes = governor.estimate_checkpoint_mapped_bytes(shard_paths)
        commit_preflight = governor.commit_margin_preflight(expected_mapped_bytes)
        log(f"commit-margin preflight ({len(shard_paths)} shard(s), "
            f"{commit_preflight.get('expected_mapped_gib', 'n/a')}GiB): {commit_preflight}")

    # --- Leg 1: base model, 4-bit frozen (real) / tiny fp32 substitute (dry-run) ---
    from transformers import AutoModelForCausalLM, AutoTokenizer

    if args.dry_run:
        model_id = DRYRUN_SUBSTITUTE_MODEL
        log(f"loading DRY-RUN substitute (fp32, CPU, no 4-bit quant): {model_id}")
        t0 = time.time()
        tokenizer = AutoTokenizer.from_pretrained(model_id)
        base_model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype=torch.float32)
        base_model.to("cpu")
        load_s = time.time() - t0
        quant_config_used = None
        load_path = None  # not applicable -- dry-run never touches a real checkpoint dir
        detected_prequant_config = None
        governed_fit = None
        rank_degradation = None  # Issue #87 round 5.4: the launch gate never runs under dry-run (no CUDA)
    else:
        model_id = args.model
        # Issue #87: governed-fit placement, derived ONCE, shared by both load
        # paths below (device_map={"":0} OOM'd -- the two deliberately-
        # unquantized bf16 modules, embed_tokens/lm_head, overflow the GPU
        # once stacked on the quantized trunk; device_map="auto" + a max_memory
        # DERIVED from the SAME governor config lets accelerate place the
        # trunk on GPU and offload whatever doesn't fit to CPU).
        governed_fit = derive_governed_fit_max_memory(
            frac, preflight_before["total_gb"], margin_gb, expected_mapped_bytes,
        )
        max_memory = governed_fit["max_memory"]
        log(f"governed-fit placement: max_memory={max_memory} (arithmetic: {governed_fit['arithmetic']})")

        # Issue #86: auto-detect an already-prequantized checkpoint from its
        # own config.json BEFORE deciding whether to construct a fresh
        # BitsAndBytesConfig -- passing a second, fresh quant config against
        # a checkpoint that already carries one double-configures the load
        # and invalidates load_s as a clean baseline. No new CLI flag; the
        # artifact self-describes.
        detected_prequant_config = detect_prequantized_config(model_id)
        cpu_offload_override = None
        device_map_derivation = None
        vram_sanity = None
        governed_fit_v2 = None
        governed_fit_v2_1 = None
        embed_tokens_sentinel = None
        rank_degradation = None  # Issue #87 round 5.4: populated only if the launch gate degrades the rank
        if detected_prequant_config is not None:
            load_path = "prequantized"
            # Issue #87 reopened: governed-fit's max_memory ALWAYS advertises a
            # nonzero CPU budget (derive_governed_fit_max_memory's cpu_budget_gb
            # is the checkpoint's own on-disk size, never zero for a real
            # checkpoint) -- accelerate's actual placement decision inside
            # from_pretrained is not knowable in advance, so every prequantized
            # governed-fit load must carry the CPU-offload permission flag; the
            # flag is inert if accelerate ends up placing nothing on CPU. The
            # override REPLICATES the checkpoint's own serialized quant config
            # (never a fresh/invented one) -- #86's "never re-quantize" intent
            # is preserved, only the offload permission is added.
            from transformers import BitsAndBytesConfig
            cpu_offload_override = derive_cpu_offload_bnb_override(detected_prequant_config)
            # Fail-closed rail: the override must replicate the checkpoint's OWN
            # serialized values field-for-field -- never silently diverge (a
            # mismatch would mean re-quantizing under different arithmetic than
            # the checkpoint was saved with, which this cure must never do).
            for _field, _value in cpu_offload_override["quant_config_replicated_fields"].items():
                assert detected_prequant_config.get(_field) == _value, (
                    f"quant-config-replication assert FAILED: override.{_field}={_value!r} != "
                    f"checkpoint.{_field}={detected_prequant_config.get(_field)!r}"
                )
            log(f"detected prequantized checkpoint (config.json quantization_config present) at {model_id}: "
                f"quant_method={detected_prequant_config.get('quant_method')} "
                f"load_in_4bit={detected_prequant_config.get('load_in_4bit')} -- "
                f"replicating serialized quant config + adding "
                f"{cpu_offload_override['offload_flag_added']}=True "
                f"(replicated fields verified equal: {cpu_offload_override['quant_config_replicated_fields']})")
            bnb_config = BitsAndBytesConfig(**cpu_offload_override["bnb_config_kwargs"])

            # Issue #87 round 3 (live-fire finding): device_map="auto" let
            # accelerate place a QUANTIZED module on CPU, and this bnb/accelerate
            # pairing cannot construct an offloaded Params4bit (TypeError:
            # unexpected kwarg '_is_hf_initialized'). Cure: a DETERMINISTIC
            # module-level map derived straight from the checkpoint's own weight
            # index + convert-receipt skip_set -- never accelerate's heuristic.
            # max_memory is KEPT as a belt (still governs headroom); device_map
            # now pins placement explicitly, so accelerate has no discretion
            # left to place a quantized module off-GPU.
            weight_map = read_safetensors_index_weight_map(model_id)
            skip_set = read_convert_receipt_skip_set(model_id)
            device_map_derivation = derive_deterministic_device_map(weight_map, skip_set)
            deterministic_device_map = device_map_derivation["device_map"]
            no_quantized_offload_check = assert_no_quantized_module_offloaded(
                deterministic_device_map, device_map_derivation["classified"],
            )
            # Fail-closed rail (the class rule, mechanically enforced): under
            # this environment a 4-bit-quantized module must NEVER be placed
            # off-GPU. This assert fires BEFORE from_pretrained is ever called.
            assert no_quantized_offload_check["passed"], (
                "CLASS RULE VIOLATED: a 4-bit-quantized module must never be placed "
                f"off-GPU under this environment. offending={no_quantized_offload_check['offending_quantized_modules_offloaded']} "
                f"uncovered={no_quantized_offload_check['uncovered_quantized_modules']}"
            )
            log(f"deterministic device_map derived from {device_map_derivation['source_index']}: "
                f"{deterministic_device_map} (cpu_modules={device_map_derivation['cpu_modules']}, "
                f"{no_quantized_offload_check['n_quantized_modules_checked']} quantized modules verified GPU-resident)")

            # Issue #87 round 4 (live-fire finding #2): round 3's own
            # vram_sanity only budgeted the resident trunk and missed the
            # streamed-lm_head + LoRA-mass + activation costs that killed the
            # run one leg later. governed_fit_v2 is the PRE-LEG, fail-closed
            # replacement -- computed and asserted BEFORE from_pretrained,
            # using the SAME gpu_budget_gb v1/round-3 already derived (never
            # re-derived independently).
            config_dims = read_model_config_dims(model_id)
            seq_len_for_activation = max(TRAIN_SEQ_LEN, INFER_PROMPT_LEN + args.max_new_tokens)

            if args.neutralize_embed_offload:
                # Issue #87 round 5: v2.1 supersedes v2 ONLY when the
                # structural fix is actually engaged (item (b) flag set).
                # streamed_bytes_actual=0 here is the STRUCTURAL, pre-leg
                # declaration (no forward pass has happened yet -- nothing
                # CAN have streamed) -- the SAME pre-leg-gate discipline v2
                # used (an analytical estimate asserted before any GPU cycle
                # is spent), never a live measurement at this point. The
                # sentinel counter (wired after from_pretrained, asserted
                # after Leg 3 below) is the SEPARATE, later, POST-hoc proof
                # that the mechanism actually behaved as this pre-leg gate
                # assumed -- never conflated with this budget check.
                # Issue #87 round 5.4: the launch gate is now
                # resolve_governed_launch_rank (round 5.3's assert_governed_fit
                # + derive_max_fitting_rank, composed) fed a preflight_reading
                # dict built from the SAME preflight_before/governed_fit values
                # already derived above -- never a fresh governor.preflight()
                # call, never re-derived arithmetic. On refusal at the
                # requested rank it sweeps LORA_RANK_SWEEP_CANDIDATES
                # (descending-only) and, if a band-legal+authorized rank
                # exists, re-gates at that rank -- LOUDLY logged here, never
                # silent, never widening governor caps/margin to force the
                # original rank. If no candidate rank qualifies, refuses
                # exactly as before (fail-closed, before any GPU cycle spent).
                preflight_reading_for_gate = {
                    "vram_fraction": governed_fit["arithmetic"]["vram_fraction"],
                    "free_gb": preflight_before["free_gb"],
                    "total_gb": preflight_before["total_gb"],
                    "margin_gb": governed_fit["arithmetic"]["margin_gb"],
                }
                requested_rank = args.lora_rank
                resolution = resolve_governed_launch_rank(
                    preflight_reading_for_gate, model_id, weight_map, config_dims, device_map_derivation,
                    requested_rank, LORA_TARGET_MODULES, seq_len_for_activation,
                    args.fragmentation_regime, "bnb_adamw8bit", expected_mapped_bytes,
                    LORA_RANK_SWEEP_CANDIDATES,
                )
                gate_result = resolution["gate_result"]
                assert gate_result["authorized"], (
                    "CLASS RULE VIOLATED (round 5.4): governed-fit refused at the requested rank "
                    f"({requested_rank}): {gate_result['refusal_reason']} -- AND no band-legal, "
                    f"memory-authorized rank exists in the standing sweep {LORA_RANK_SWEEP_CANDIDATES} "
                    f"(candidates={resolution['sweep_candidates']}). Refusing launch before any GPU "
                    "cycle is spent -- governor caps/margin are constitution, never widened to force a fit."
                )
                rank_degradation = resolution["rank_degradation"]
                if rank_degradation:
                    args.lora_rank = rank_degradation["granted_rank"]
                    log(f"governed-fit RANK DEGRADED (round 5.4): requested rank={rank_degradation['requested_rank']} "
                        f"refused ({rank_degradation['requested_rank_refusal_reason']}) -- stepping DOWN to "
                        f"granted_rank={rank_degradation['granted_rank']} per the standing sweep "
                        f"{LORA_RANK_SWEEP_CANDIDATES}. Proceeding at the granted rank; this degradation is "
                        "recorded in the receipt (requested_rank/granted_rank/candidates), never silent.")
                governed_fit_v2_1 = gate_result["fit"]
                log(f"governed-fit v2.1 PASSED (lora_rank={args.lora_rank}"
                    f"{', DEGRADED from ' + str(requested_rank) if rank_degradation else ''}): "
                    f"trunk={governed_fit_v2_1['trunk_gib']}GiB "
                    f"lm_head_nf4={governed_fit_v2_1['lm_head_nf4']['total_gib'] if governed_fit_v2_1['lm_head_nf4'] else 0}GiB "
                    f"embed_transfer={governed_fit_v2_1['embed_transfer']['total_gib']}GiB "
                    f"lora_mass={governed_fit_v2_1['lora_mass']['lora_mass_gib']}GiB "
                    f"({governed_fit_v2_1['lora_trainable_params']['total_trainable_params']} trainable params, "
                    f"optimizer_pricing_mode={governed_fit_v2_1['lora_mass']['optimizer_pricing_mode']}) "
                    f"activation={governed_fit_v2_1['activation']['activation_gib']}GiB "
                    f"fragmentation={governed_fit_v2_1['fragmentation_gib']}GiB "
                    f"total={governed_fit_v2_1['total_required_gib']}GiB vs "
                    f"max_memory_authorized={governed_fit_v2_1['max_memory_authorized_gib']}GiB "
                    f"(source={governed_fit_v2_1['max_memory_authorized_gib_source']}, "
                    f"legacy_decimal_gb_residual={governed_fit_v2_1['gpu_budget_gb_legacy_residual']}) "
                    f"(headroom={governed_fit_v2_1['headroom_gib']}GiB)")
                vram_sanity = {
                    "gpu_trunk_gib": governed_fit_v2_1["trunk_gib"],
                    "max_memory_authorized_gib": governed_fit_v2_1["max_memory_authorized_gib"],
                    "trunk_fits_budget": governed_fit_v2_1["trunk_gib"] <= governed_fit_v2_1["max_memory_authorized_gib"],
                }
            else:
                # Round 3/4 tested path, UNCHANGED -- byte-identical to
                # before this round's edits when the new flag is not set.
                governed_fit_v2 = derive_governed_fit_v2(
                    model_id, weight_map, config_dims, device_map_derivation,
                    args.lora_rank, LORA_TARGET_MODULES, governed_fit["arithmetic"]["gpu_budget_gb"],
                    seq_len_for_activation,
                )
                assert governed_fit_v2["fits"], (
                    "CLASS RULE VIOLATED (round 4): governed-fit v2 budget exceeded -- "
                    f"trunk={governed_fit_v2['trunk_gb']}GiB + "
                    f"streamed_head={governed_fit_v2['streamed_head']['streamed_gb']}GiB + "
                    f"lora_mass={governed_fit_v2['lora_mass']['lora_mass_gb']}GiB "
                    f"({governed_fit_v2['lora_trainable_params']['total_trainable_params']} trainable params) + "
                    f"activation={governed_fit_v2['activation']['activation_gb']}GiB "
                    f"= {governed_fit_v2['total_required_gb']}GiB > "
                    f"gpu_budget={governed_fit_v2['gpu_budget_gb']}GiB "
                    f"(headroom={governed_fit_v2['headroom_gb']}GiB). Refusing launch before any GPU cycle is "
                    "spent -- lower --lora-rank or increase GPU budget and re-fire; never fix-forward on a "
                    "headroom violation."
                )
                log(f"governed-fit v2 PASSED: trunk={governed_fit_v2['trunk_gb']}GiB "
                    f"streamed_head={governed_fit_v2['streamed_head']['streamed_gb']}GiB "
                    f"lora_mass={governed_fit_v2['lora_mass']['lora_mass_gb']}GiB "
                    f"({governed_fit_v2['lora_trainable_params']['total_trainable_params']} trainable params) "
                    f"activation={governed_fit_v2['activation']['activation_gb']}GiB "
                    f"total={governed_fit_v2['total_required_gb']}GiB vs "
                    f"budget={governed_fit_v2['gpu_budget_gb']}GiB "
                    f"(headroom={governed_fit_v2['headroom_gb']}GiB)")

                # vram_sanity (round 3, kept for receipt-schema stability): now
                # DERIVED from governed_fit_v2's own trunk_gb rather than
                # recomputing the same safetensors-header scan a second time.
                vram_sanity = {
                    "gpu_trunk_gb": governed_fit_v2["trunk_gb"],
                    "gpu_budget_gb": governed_fit_v2["gpu_budget_gb"],
                    "trunk_fits_budget": governed_fit_v2["trunk_gb"] <= governed_fit_v2["gpu_budget_gb"],
                }

            t0 = time.time()
            tokenizer = AutoTokenizer.from_pretrained(model_id)
            base_model = AutoModelForCausalLM.from_pretrained(
                model_id, quantization_config=bnb_config,
                device_map=deterministic_device_map, max_memory=max_memory,
            )
            load_s = time.time() - t0
            quant_config_used = {
                "load_in_4bit": detected_prequant_config.get("load_in_4bit"),
                "bnb_4bit_quant_type": detected_prequant_config.get("bnb_4bit_quant_type"),
                "bnb_4bit_compute_dtype": detected_prequant_config.get("bnb_4bit_compute_dtype"),
            }

            if args.neutralize_embed_offload:
                embed_tokens_sentinel = neutralize_embed_tokens_offload_hook(
                    base_model, execution_device=0,
                )
                log(f"embed_tokens offload hook neutralized (round 5 item (b)); "
                    f"sentinel={embed_tokens_sentinel}")
        else:
            from transformers import BitsAndBytesConfig
            load_path = "quantize_on_load"
            log(f"loading REAL base 4-bit frozen (NF4, bitsandbytes): {model_id}")
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
            )
            t0 = time.time()
            tokenizer = AutoTokenizer.from_pretrained(model_id)
            base_model = AutoModelForCausalLM.from_pretrained(
                model_id, quantization_config=bnb_config, device_map="auto", max_memory=max_memory,
            )
            load_s = time.time() - t0
            quant_config_used = {
                "load_in_4bit": True, "bnb_4bit_quant_type": "nf4", "bnb_4bit_compute_dtype": "bfloat16",
            }
    log(f"base model loaded in {load_s:.1f}s (load_path={load_path})")

    # Issue #87: placement provenance -- final hf_device_map echo + which
    # modules landed on CPU. Disclosed, never hidden: a nonempty
    # cpu_offloaded_modules list means leg4's inference wall-time includes
    # CPU-resident matmuls for those modules (embed_tokens/lm_head expected).
    if args.dry_run:
        hf_device_map = None
        cpu_offloaded_modules = None
    else:
        hf_device_map = getattr(base_model, "hf_device_map", None)
        cpu_offloaded_modules = sorted(
            k for k, v in (hf_device_map or {}).items() if str(v) in ("cpu", "disk")
        )
        log(f"hf_device_map cpu/disk modules: {cpu_offloaded_modules}")

    if args.dry_run:
        log("SKIPPED (dry-run, no CUDA): margin assert AFTER load, VRAM peak, nvidia-smi sample")
        preflight_after = None
        vram_peak_bytes = None
        nvidia_smi_after_load = None
    else:
        free_after, total_after = torch.cuda.mem_get_info()
        assert free_after >= margin_gb * 1e9, (
            f"margin assert AFTER load FAILED: {free_after/1e9:.1f}GB free < {margin_gb}GB required"
        )
        preflight_after = {"free_gb": round(free_after / 1e9, 2), "total_gb": round(total_after / 1e9, 2)}
        log(f"margin assert AFTER load PASSED: {preflight_after}")
        nvidia_smi_after_load = nvidia_smi_sample()

    # Issue #87 round 4 item 1 (live-fire finding): gradient checkpointing
    # BEFORE LoRA attach -- trades recompute time for not holding every
    # layer's forward activations resident through backward (this is the
    # lever governed_fit_v2's activation-budget term above assumes is
    # active). Applies identically on CPU (dry-run) or GPU (real), so
    # enabled unconditionally for the same dry-run/real control-flow parity
    # this harness maintains everywhere else. enable_input_require_grads()
    # is required alongside it for a model whose embedding/base is entirely
    # frozen until LoRA is attached -- without it, checkpointing's recompute
    # graph has no requires_grad=True tensor to hang the backward graph on
    # and the whole checkpointed segment would silently produce zero
    # gradient (a correctness bug the frozen-base assert below would NOT
    # catch, since it only checks base params, not the recompute path).
    base_model.gradient_checkpointing_enable()
    base_model.enable_input_require_grads()
    log("gradient checkpointing ENABLED on base model (before LoRA attach)")

    # --- Leg 2: trainable LoRA-class slice attached (frozen base) ---
    from peft import LoraConfig, get_peft_model

    lora_config = LoraConfig(
        r=args.lora_rank, lora_alpha=args.lora_rank * 2, target_modules=LORA_TARGET_MODULES,
        lora_dropout=0.0, bias="none", task_type="CAUSAL_LM",
    )
    peft_model = get_peft_model(base_model, lora_config)

    n_trainable = sum(p.numel() for p in peft_model.parameters() if p.requires_grad)
    n_total = sum(p.numel() for p in peft_model.parameters())
    log(f"LoRA slice attached: rank={args.lora_rank} trainable_params={n_trainable} total_params={n_total}")

    # Frozen-base grad assert: every param OUTSIDE the LoRA adapter must be
    # requires_grad=False. Checked explicitly (never trust peft's default
    # silently) -- this IS the "frozen-base assert" the issue names.
    n_base_with_grad = 0
    for pname, p in peft_model.named_parameters():
        if "lora_" not in pname and p.requires_grad:
            n_base_with_grad += 1
    assert n_base_with_grad == 0, (
        f"frozen-base assert FAILED: {n_base_with_grad} non-LoRA params have requires_grad=True"
    )
    log(f"frozen-base assert PASSED: 0 non-LoRA params have requires_grad=True")

    trainable_in_target_range = TARGET_TRAINABLE_MIN <= n_trainable <= TARGET_TRAINABLE_MAX
    if args.dry_run:
        log(
            f"trainable-param target range check ({TARGET_TRAINABLE_MIN}-{TARGET_TRAINABLE_MAX}) "
            f"SKIPPED (dry-run substrate is a tiny 0.5B model, not the real ~27B-class base) -- "
            f"got {n_trainable}, only meaningful under phase B"
        )
    else:
        log(
            f"trainable-param target range check ({TARGET_TRAINABLE_MIN}-{TARGET_TRAINABLE_MAX}): "
            f"{n_trainable} -- in_range={trainable_in_target_range}"
        )

    # --- Leg 3: ONE verified training step ---
    optimizer, optimizer_class_name, optimizer_is_8bit = build_lora_optimizer(
        [p for p in peft_model.parameters() if p.requires_grad], args.dry_run, lr=1e-4,
    )
    log(f"LoRA optimizer: {optimizer_class_name} (8bit={optimizer_is_8bit})")
    vocab_size = base_model.config.vocab_size
    seq_len = TRAIN_SEQ_LEN
    input_ids = torch.randint(0, vocab_size, (1, seq_len))
    labels = input_ids.clone()

    peft_model.train()
    t_train0 = time.time()
    outputs = peft_model(input_ids=input_ids, labels=labels)
    loss = outputs.loss
    optimizer.zero_grad()
    loss.backward()

    grad_sq_sum = 0.0
    for p in peft_model.parameters():
        if p.requires_grad and p.grad is not None:
            grad_sq_sum += float((p.grad.detach() ** 2).sum().item())
    grad_norm = grad_sq_sum ** 0.5
    assert grad_norm > 0.0, "training-step assert FAILED: grad_norm is 0.0 (vacuous step)"

    optimizer.step()
    train_step_s = time.time() - t_train0
    train_tokens_per_s = seq_len / train_step_s if train_step_s > 0 else None
    log(
        f"ONE training step VERIFIED: loss={float(loss.item()):.4f} grad_norm={grad_norm:.6f} "
        f"wall_s={train_step_s:.3f} tokens/s={train_tokens_per_s}"
    )

    # Issue #87 round 5 item (b): POST-hoc sentinel assert -- this is the
    # "zero hook device-moves" proof team-lead's spec names, separate from
    # (and later than) the pre-leg governed_fit_v2.1 budget gate above. The
    # pre-leg gate declared streamed_bytes_actual=0 as a structural
    # assumption BEFORE any forward pass; THIS assert checks whether that
    # assumption actually held after a REAL forward call (Leg 3) exercised
    # embed_tokens. A nonzero count here means the neutralization mechanism
    # did not behave as budgeted -- fail closed rather than proceed on an
    # unproven assumption.
    if args.neutralize_embed_offload and embed_tokens_sentinel is not None:
        assert embed_tokens_sentinel["weight_device_moves"] == 0, (
            "CLASS RULE VIOLATED (round 5): embed_tokens_sentinel.weight_device_moves="
            f"{embed_tokens_sentinel['weight_device_moves']} after Leg 3's real forward call -- "
            "the offload-hook neutralization did NOT hold across an actual forward pass. The "
            "pre-leg governed_fit_v2.1 budget assumed zero streaming; that assumption is now "
            "disproven and this run refuses to report a fits=True verdict it cannot back."
        )
        log(f"embed_tokens sentinel assert PASSED: weight_device_moves=0 across the real Leg 3 forward call")

    # --- Leg 4: ONE inference pass, greedy, >=MIN_NEW_TOKENS, no unload ---
    peft_model.eval()
    prompt_ids = torch.randint(0, vocab_size, (1, INFER_PROMPT_LEN))
    t_infer0 = time.time()
    with torch.no_grad():
        generated = peft_model.generate(
            input_ids=prompt_ids, max_new_tokens=args.max_new_tokens, do_sample=False,
        )
    infer_s = time.time() - t_infer0
    n_new_tokens = generated.shape[1] - prompt_ids.shape[1]
    assert n_new_tokens >= MIN_NEW_TOKENS, (
        f"inference-pass assert FAILED: only {n_new_tokens} new tokens generated, "
        f"need >= {MIN_NEW_TOKENS}"
    )
    infer_tokens_per_s = n_new_tokens / infer_s if infer_s > 0 else None
    log(
        f"ONE inference pass VERIFIED: new_tokens={n_new_tokens} wall_s={infer_s:.3f} "
        f"tokens/s={infer_tokens_per_s}"
    )

    # --- Leg 5: VRAM peak + tokens/s (both legs) + wall-clock ---
    if args.dry_run:
        vram_peak_bytes = None
        nvidia_smi_final = None
        log("SKIPPED (dry-run, no CUDA): VRAM peak (torch.cuda.max_memory_allocated), final nvidia-smi sample")
    else:
        vram_peak_bytes = torch.cuda.max_memory_allocated()
        vram_peak_fraction_of_total = vram_peak_bytes / (total_after * 1e9) if 'total_after' in dir() else None
        nvidia_smi_final = nvidia_smi_sample()
        assert vram_peak_bytes / 1e9 <= frac * (preflight_before["total_gb"] if preflight_before else 1e18), (
            "VRAM peak assert FAILED: peak usage exceeds the governor fraction cap"
        )
        log(f"VRAM peak: {vram_peak_bytes/1e9:.2f}GB (fraction cap={frac}); nvidia-smi={nvidia_smi_final}")

    total_elapsed_s = time.time() - t_start
    all_assertions_passed = True  # reaching this line means no AssertionError fired above

    receipt = {
        "ticket": "R3-FEASIBILITY-PROBE",
        "issue": "wordingone/ember#47",
        "mode": "dry_run" if args.dry_run else "real",
        "model_id": model_id,
        "quant_config": quant_config_used,
        "lora_rank": args.lora_rank,
        # Issue #87 round 5.4: None on every run where the requested rank was
        # authorized outright. When the launch gate degraded the rank, this
        # carries requested_rank/granted_rank/requested_rank_refusal_reason/
        # the full per-candidate sweep table -- the degradation decision must
        # be fully auditable from the receipt alone, never inferred.
        "rank_degradation": rank_degradation,
        "lora_target_modules": LORA_TARGET_MODULES,
        "seed": args.seed,
        "governor_config": {"vram_fraction": frac, "margin_gb": margin_gb, "throttle_s": throttle_s},
        # Issue #87 round 4 items 1+3: unconditional -- these apply on every
        # run (dry-run or real), matching where the code that sets them runs.
        "gradient_checkpointing_enabled": True,
        "pytorch_cuda_alloc_conf": os.environ.get("PYTORCH_CUDA_ALLOC_CONF"),
        "pytorch_alloc_conf": os.environ.get("PYTORCH_ALLOC_CONF"),
        # Issue #87 round 5 item (c): disclosed feasibility-recipe delta --
        # dry_run always uses torch.optim.Adam (bnb.optim.AdamW8bit cannot
        # step on CPU tensors, confirmed empirically), only the real run
        # uses AdamW8bit.
        "optimizer_class": optimizer_class_name,
        "optimizer_is_8bit": optimizer_is_8bit,
        "preflight_before_load": preflight_before,
        "commit_margin_preflight": commit_preflight,
        "preflight_after_load": preflight_after,
        "nvidia_smi_after_load": nvidia_smi_after_load,
        "nvidia_smi_final": nvidia_smi_final,
        "base_model_load_wall_s": load_s,
        # Issue #86: provenance stamp for base_model_load_wall_s / load_s --
        # 'prequantized' | 'quantize_on_load' | None (dry_run, not applicable).
        # W2's naive-reload baseline cites load_s; this says which load path
        # actually produced that number.
        "load_path": load_path,
        "detected_prequant_config": (
            {
                "quant_method": detected_prequant_config.get("quant_method"),
                "load_in_4bit": detected_prequant_config.get("load_in_4bit"),
            }
            if (not args.dry_run and detected_prequant_config is not None) else None
        ),
        # Issue #87: governed-fit placement provenance -- max_memory arithmetic,
        # final hf_device_map, which modules landed on CPU/disk, and a plain
        # disclosure note tying that to leg4's inference wall-time (never a
        # hidden slowdown).
        "governed_fit_placement": governed_fit["arithmetic"] if governed_fit is not None else None,
        "hf_device_map": hf_device_map,
        "cpu_offloaded_modules": cpu_offloaded_modules,
        # Issue #87 reopened: the CPU-offload permission cure -- only present
        # on the prequantized real-load path. quant_config_replicated_fields
        # is the exact core-field dict passed to BitsAndBytesConfig (verified,
        # not merely asserted-and-dropped: quant_config_replication_verified
        # re-checks field-by-field equality against detected_prequant_config
        # at receipt-build time, same rail the load-time assert already
        # enforced). offload_flag_added names the one new permission key.
        "quant_config_replicated_fields": (
            cpu_offload_override["quant_config_replicated_fields"]
            if (not args.dry_run and cpu_offload_override is not None) else None
        ),
        "quant_config_replication_verified": (
            all(
                detected_prequant_config.get(_f) == _v
                for _f, _v in cpu_offload_override["quant_config_replicated_fields"].items()
            )
            if (not args.dry_run and cpu_offload_override is not None) else None
        ),
        "offload_flag_added": (
            cpu_offload_override["offload_flag_added"]
            if (not args.dry_run and cpu_offload_override is not None) else None
        ),
        # Issue #87 round 3: the deterministic device-map cure -- only present
        # on the prequantized real-load path. device_map_derivation names the
        # source index, the resulting cpu/gpu module split, and the derived
        # device_map itself; no_quantized_module_offloaded is the class-rule
        # verdict (mirrors the load-time assert, re-stated for the receipt);
        # vram_sanity is the real (safetensors-header-derived, never
        # hardcoded) GPU-trunk-bytes vs governed-fit-budget comparison.
        "device_map_derivation": (
            {
                "source_index": device_map_derivation["source_index"],
                "cpu_modules": device_map_derivation["cpu_modules"],
                "gpu_module_count": device_map_derivation["gpu_module_count"],
                "device_map": device_map_derivation["device_map"],
            }
            if (not args.dry_run and device_map_derivation is not None) else None
        ),
        "no_quantized_module_offloaded": (
            no_quantized_offload_check["passed"]
            if (not args.dry_run and device_map_derivation is not None) else None
        ),
        "vram_sanity": (
            vram_sanity if (not args.dry_run and vram_sanity is not None) else None
        ),
        # Issue #87 round 4: the pre-leg, fail-closed governed-fit v2 budget
        # check (trunk + streamed_head + lora_mass + activation vs
        # gpu_budget) -- see derive_governed_fit_v2's docstring. Supersedes
        # vram_sanity's narrower trunk-only accounting; vram_sanity above is
        # kept for receipt-schema stability, now derived from this same data.
        "governed_fit_v2": (
            governed_fit_v2 if (not args.dry_run and governed_fit_v2 is not None) else None
        ),
        # Issue #87 round 5: the structural successor, present ONLY when
        # --neutralize-embed-offload is set (items (a)/(b) engaged). Adds
        # lm_head_nf4 + embed_transfer + fragmentation_gb terms and
        # hard-asserts zero streaming rather than budgeting for it. See
        # derive_governed_fit_v2_1's docstring.
        "governed_fit_v2_1": (
            governed_fit_v2_1 if (not args.dry_run and governed_fit_v2_1 is not None) else None
        ),
        "neutralize_embed_offload_enabled": args.neutralize_embed_offload,
        "fragmentation_regime": (args.fragmentation_regime if args.neutralize_embed_offload else None),
        # Issue #87 round 5 item (b): the post-hoc proof (asserted after
        # Leg 3's real forward call, separate from the pre-leg budget
        # gate above) that embed_tokens' weight table never moved off CPU.
        "embed_tokens_sentinel": (
            embed_tokens_sentinel if (not args.dry_run and embed_tokens_sentinel is not None) else None
        ),
        "cpu_offload_disclosure": (
            "non-empty cpu_offloaded_modules means leg4_inference_pass.wall_s includes "
            "CPU-resident matmuls for those modules (embed_tokens/lm_head expected here) -- "
            "correct but slower than an all-GPU forward; see governed_fit_placement for the "
            "max_memory arithmetic that produced this placement."
            if (not args.dry_run and cpu_offloaded_modules) else None
        ),
        "leg1_base_loaded_4bit_frozen": (not args.dry_run),
        "leg2_lora_slice": {
            "n_trainable_params": n_trainable,
            "n_total_params": n_total,
            "target_range": [TARGET_TRAINABLE_MIN, TARGET_TRAINABLE_MAX],
            "in_target_range": trainable_in_target_range if not args.dry_run else None,
            "target_range_check_skipped_dry_run": args.dry_run,
        },
        "frozen_base_assert": {
            "n_base_params_with_grad": n_base_with_grad,
            "passed": n_base_with_grad == 0,
        },
        "leg3_training_step": {
            "loss": float(loss.item()),
            "grad_norm": grad_norm,
            "wall_s": train_step_s,
            "tokens_per_s": train_tokens_per_s,
            "grad_norm_nonzero_assert_passed": grad_norm > 0.0,
        },
        "leg4_inference_pass": {
            "n_new_tokens": n_new_tokens,
            "min_required": MIN_NEW_TOKENS,
            "wall_s": infer_s,
            "tokens_per_s": infer_tokens_per_s,
            "min_tokens_assert_passed": n_new_tokens >= MIN_NEW_TOKENS,
        },
        "leg5_vram_peak": {
            "vram_peak_bytes": vram_peak_bytes,
            "vram_peak_gb": (vram_peak_bytes / 1e9) if vram_peak_bytes is not None else None,
            "skipped_dry_run": args.dry_run,
        },
        "all_assertions_passed": all_assertions_passed,
        "total_elapsed_s": total_elapsed_s,
        "api_spend_usd": 0.0,
        "paid_api_surface_used": False,
    }

    out_dir = DRYRUN_RECEIPT_DIR if args.dry_run else REAL_RECEIPT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    prefix = "r3-feasibility-dryrun" if args.dry_run else "r3-feasibility"
    out_path = out_dir / f"{prefix}-{ts}.json"
    out_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    log(f"wrote {out_path}")
    log("=== R3 FEASIBILITY PROBE COMPLETE (all assertions passed; receipt written) ===")


if __name__ == "__main__":
    main()
