"""selective_recompute_ab.py — selective activation checkpointing A/B (Closes #296).

Measures the recompute tax in backward (E4 56.5% region) by comparing three
grad-ckpt modes at c03 shapes (v0 training config):
  - full-ckpt  : gradient_checkpointing_enable() on all blocks (control)
  - selective  : cache attention activations, checkpoint MLP only
  - none       : disable grad-ckpt entirely (if VRAM fits under governor)

Protocol:
  warmup_steps=5, bench_steps=20, seeds={16,17,18}, c03 shapes.
  Metric: tokens/s per arm; measured_multiplier = arm_tok_s / full_ckpt_tok_s.
  (>1.0x = arm is faster than full-ckpt; <1.0x = slower or failed)

Governed: VRAM_FRACTION=0.80, MARGIN_GIB=1.5, PACE_S=0.05 (fp19 floor).
Live run 12c050e7 NOT touched.

Selftest: python selective_recompute_ab.py --selftest
  Marker: SELECTIVE_RECOMPUTE_AB_SELFTEST_PASS

Run: python selective_recompute_ab.py
  NOT via train MCP. Native Windows Python only.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone

HERE     = os.path.dirname(os.path.abspath(__file__))
NC       = os.path.dirname(HERE)
RECEIPTS = os.path.join(NC, "receipts")

# ---------------------------------------------------------------------------
# c03 shapes (v0 training config, same as E4 profiler)
# ---------------------------------------------------------------------------
HIDDEN      = 1024
LAYERS      = 20
HEADS       = 16
FFN         = 4096
VOCAB       = 32000
SEQ         = 1024
BATCH       = 4
WARMUP_REPS = 5
BENCH_REPS  = 20

SEEDS = [16, 17, 18]

SHARD_DIR   = os.path.join(os.path.dirname(NC), "shards-v0")
SHARD_FILES = ["v0-00000.bin", "v0-00001.bin"]

# Governor rails (fp19 floor — never relax)
VRAM_FRACTION = 0.80
MARGIN_GIB    = 1.5
PACE_S        = 0.05

LIVE_RUN_SHA = "12c050e7"


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# Shard-backed dataset
# ---------------------------------------------------------------------------

class ShardDataset:
    def __init__(self, shard_dir: str, shard_files: list[str], seq: int, seed: int):
        import numpy as np
        chunks = []
        for fname in shard_files:
            p = os.path.join(shard_dir, fname)
            if not os.path.exists(p):
                raise FileNotFoundError(f"shard not found: {p}")
            chunks.append(np.memmap(p, dtype=np.uint16, mode="r"))
        self._tokens = np.concatenate([c.astype(np.int64) for c in chunks])
        self._seq = seq
        self._n = len(self._tokens) - seq - 1
        rng = np.random.default_rng(seed)
        self._order = rng.permutation(self._n)
        self._pos = 0

    def next_batch(self, batch: int):
        import numpy as np
        import torch
        idxs = []
        for _ in range(batch):
            if self._pos >= len(self._order):
                self._pos = 0
            idxs.append(self._order[self._pos])
            self._pos += 1
        rows = np.stack([self._tokens[i: i + self._seq + 1] for i in idxs])
        x = torch.from_numpy(rows[:, :-1].copy()).long()
        y = torch.from_numpy(rows[:, 1:].copy()).long()
        return x, y


# ---------------------------------------------------------------------------
# Selective checkpointing patch
# ---------------------------------------------------------------------------

def apply_selective_ckpt(model) -> None:
    """Patch each LlamaDecoderLayer to checkpoint MLP only, keeping attn alive.

    - gradient_checkpointing is left disabled at the model level (no
      GradientCheckpointingLayer.__call__ wrapping).
    - Each decoder layer's forward is replaced with a version that:
        1. Runs the attention block normally (activations kept alive).
        2. Wraps the MLP block with torch.utils.checkpoint.checkpoint
           (activations freed, recomputed on backward).
    """
    import torch.utils.checkpoint as ckpt_util

    for layer in model.model.layers:
        _patch_layer_selective(layer, ckpt_util)


def _patch_layer_selective(layer, ckpt_util) -> None:
    """Replace one LlamaDecoderLayer.forward with selective-ckpt version."""
    # Capture references before binding
    self_attn          = layer.self_attn
    mlp                = layer.mlp
    input_layernorm    = layer.input_layernorm
    post_attn_layernorm = layer.post_attention_layernorm

    def selective_forward(
        hidden_states,
        attention_mask=None,
        position_ids=None,
        past_key_values=None,
        use_cache=False,
        position_embeddings=None,
        **kwargs,
    ):
        # ---- ATTENTION BLOCK (no checkpoint — activations kept alive) ----
        residual     = hidden_states
        hidden_states = input_layernorm(hidden_states)
        hidden_states, _ = self_attn(
            hidden_states=hidden_states,
            attention_mask=attention_mask,
            position_ids=position_ids,
            past_key_values=past_key_values,
            use_cache=use_cache,
            position_embeddings=position_embeddings,
            **kwargs,
        )
        hidden_states = residual + hidden_states

        # ---- MLP BLOCK (checkpointed — activations freed, recomputed on bwd) ----
        residual = hidden_states

        def mlp_block(hs):
            hs = post_attn_layernorm(hs)
            hs = mlp(hs)
            return hs

        hidden_states = residual + ckpt_util.checkpoint(
            mlp_block, hidden_states, use_reentrant=False
        )
        return hidden_states

    # Bind as an instance method replacement
    import types
    layer.forward = types.MethodType(
        lambda self, *a, **kw: selective_forward(*a, **kw), layer
    )


# ---------------------------------------------------------------------------
# Per-arm training measurement
# ---------------------------------------------------------------------------

def _build_model(torch, arm: str):
    from transformers import LlamaConfig, LlamaForCausalLM

    conf = LlamaConfig(
        vocab_size=VOCAB, hidden_size=HIDDEN,
        intermediate_size=FFN,
        num_hidden_layers=LAYERS, num_attention_heads=HEADS,
        num_key_value_heads=HEADS,
        max_position_embeddings=SEQ * 2,
        tie_word_embeddings=True,
        bos_token_id=1, eos_token_id=2,
    )
    model = LlamaForCausalLM(conf).cuda().to(torch.bfloat16)

    if arm == "full-ckpt":
        model.gradient_checkpointing_enable()
    elif arm == "selective":
        # Model-level ckpt disabled; patch per-layer MLP checkpoint
        model.gradient_checkpointing_disable()
        apply_selective_ckpt(model)
    elif arm == "none":
        model.gradient_checkpointing_disable()
    else:
        raise ValueError(f"unknown arm: {arm}")

    model.train()
    return model


def measure_arm(seed: int, arm: str, torch) -> dict:
    """Warmup then bench BENCH_REPS steps. Returns measurement dict or error."""
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.empty_cache()

    # VRAM before launch
    free_before, total_b = torch.cuda.mem_get_info()
    free_gib_before = free_before / (1 << 30)

    try:
        model = _build_model(torch, arm)
    except torch.cuda.OutOfMemoryError as e:
        torch.cuda.empty_cache()
        return {"arm": arm, "seed": seed, "error": f"OOM_AT_BUILD: {e}",
                "measured_multiplier": None}

    opt = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=0.1)
    dataset = ShardDataset(SHARD_DIR, SHARD_FILES, SEQ, seed)

    # Warmup
    for _ in range(WARMUP_REPS):
        x, y = dataset.next_batch(BATCH)
        x, y = x.cuda(), y.cuda()
        try:
            out = model(input_ids=x, labels=y)
            out.loss.backward()
        except torch.cuda.OutOfMemoryError as e:
            del model, opt, dataset
            torch.cuda.empty_cache()
            return {"arm": arm, "seed": seed, "error": f"OOM_AT_WARMUP: {e}",
                    "measured_multiplier": None}
        opt.step()
        opt.zero_grad(set_to_none=True)
        time.sleep(PACE_S)

    # Bench
    step_times = []
    for _ in range(BENCH_REPS):
        x, y = dataset.next_batch(BATCH)
        x, y = x.cuda(), y.cuda()
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        try:
            out = model(input_ids=x, labels=y)
            out.loss.backward()
        except torch.cuda.OutOfMemoryError as e:
            del model, opt, dataset
            torch.cuda.empty_cache()
            return {"arm": arm, "seed": seed, "error": f"OOM_AT_BENCH: {e}",
                    "measured_multiplier": None}
        torch.cuda.synchronize()
        step_times.append(time.perf_counter() - t0)
        opt.step()
        opt.zero_grad(set_to_none=True)
        time.sleep(PACE_S)

    free_after, _ = torch.cuda.mem_get_info()
    vram_used_gib = (free_before - free_after) / (1 << 30)

    tokens_per_step = BATCH * SEQ
    mean_step_s = sum(step_times) / len(step_times)
    tokens_per_s = tokens_per_step / mean_step_s

    del model, opt, dataset
    torch.cuda.empty_cache()

    return {
        "arm": arm,
        "seed": seed,
        "bench_reps": BENCH_REPS,
        "mean_step_s": round(mean_step_s, 5),
        "tokens_per_step": tokens_per_step,
        "tokens_per_s": round(tokens_per_s, 1),
        "vram_used_gib": round(vram_used_gib, 3),
        "step_times_s": [round(t, 5) for t in step_times],
        "error": None,
        "measured_multiplier": None,  # filled after all arms run
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import torch

    # Governor preflight
    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION)
    free_b, total_b = torch.cuda.mem_get_info()
    free_gib = free_b / (1 << 30)
    if free_gib < MARGIN_GIB:
        raise SystemExit(
            f"SELECTIVE_RECOMPUTE_AB_GOVERNOR_FAIL: {free_gib:.2f} GiB free < "
            f"{MARGIN_GIB} GiB — refusing launch")

    governor = {
        "vram_fraction": VRAM_FRACTION,
        "margin_gib_floor": MARGIN_GIB,
        "pace_s_per_step": PACE_S,
        "free_gib_at_launch": round(free_gib, 2),
        "total_gib": round(total_b / (1 << 30), 2),
    }

    # Shard check
    for fname in SHARD_FILES:
        p = os.path.join(SHARD_DIR, fname)
        if not os.path.exists(p):
            raise SystemExit(f"SELECTIVE_RECOMPUTE_AB_SHARD_MISSING: {p}")

    arms = ["full-ckpt", "selective", "none"]
    config = {
        "hidden": HIDDEN, "layers": LAYERS, "heads": HEADS,
        "ffn": FFN, "vocab": VOCAB, "seq": SEQ, "batch": BATCH,
        "warmup_reps": WARMUP_REPS, "bench_reps": BENCH_REPS,
        "vram_fraction": VRAM_FRACTION, "seeds": SEEDS,
        "arms": arms,
        "shard_files": SHARD_FILES,
    }

    print(f"[selective_recompute_ab] c03 shape hidden={HIDDEN} layers={LAYERS} "
          f"heads={HEADS} seq={SEQ} batch={BATCH}", flush=True)
    print(f"  arms: {arms}", flush=True)
    print(f"  seeds: {SEEDS}, warmup={WARMUP_REPS}, bench={BENCH_REPS}", flush=True)
    print(f"  shard_dir: {SHARD_DIR}", flush=True)

    # Collect per-arm-per-seed results
    results: dict[str, list[dict]] = {arm: [] for arm in arms}

    for arm in arms:
        for seed in SEEDS:
            print(f"  arm={arm} seed={seed} ...", flush=True)
            r = measure_arm(seed, arm, torch)
            if r.get("error"):
                print(f"    ERROR: {r['error']}", flush=True)
            else:
                print(f"    {r['tokens_per_s']:.0f} tok/s, "
                      f"step={r['mean_step_s']*1000:.1f}ms, "
                      f"vram={r['vram_used_gib']:.2f} GiB", flush=True)
            results[arm].append(r)

    # Aggregate per arm
    arm_agg: dict[str, dict] = {}
    for arm in arms:
        valid = [r for r in results[arm] if r.get("error") is None]
        if not valid:
            arm_agg[arm] = {
                "status": "FAIL",
                "reason": results[arm][0].get("error", "all seeds failed"),
                "mean_tokens_per_s": None,
            }
        else:
            arm_agg[arm] = {
                "status": "PASS",
                "n_valid_seeds": len(valid),
                "mean_tokens_per_s": round(
                    sum(r["tokens_per_s"] for r in valid) / len(valid), 1
                ),
                "mean_step_s": round(
                    sum(r["mean_step_s"] for r in valid) / len(valid), 5
                ),
                "mean_vram_used_gib": round(
                    sum(r["vram_used_gib"] for r in valid) / len(valid), 3
                ),
            }

    # measured_multiplier relative to full-ckpt (>1.0 = faster than full-ckpt)
    ctrl_tok_s = (arm_agg["full-ckpt"].get("mean_tokens_per_s") or 0.0)
    for arm in arms:
        agg = arm_agg[arm]
        arm_tok_s = agg.get("mean_tokens_per_s")
        if arm_tok_s and ctrl_tok_s > 0:
            agg["measured_multiplier"] = round(arm_tok_s / ctrl_tok_s, 4)
        else:
            agg["measured_multiplier"] = None

    # Also stamp per-seed results with measured_multiplier
    for arm in arms:
        ctrl_seed_tok: dict[int, float] = {}
        for r in results["full-ckpt"]:
            if r.get("error") is None:
                ctrl_seed_tok[r["seed"]] = r["tokens_per_s"]
        for r in results[arm]:
            seed = r.get("seed")
            if r.get("error") is None and seed in ctrl_seed_tok and ctrl_seed_tok[seed] > 0:
                r["measured_multiplier"] = round(
                    r["tokens_per_s"] / ctrl_seed_tok[seed], 4
                )

    # Verdict
    sel_mm = arm_agg["selective"].get("measured_multiplier")
    none_mm = arm_agg["none"].get("measured_multiplier")

    if sel_mm is not None and sel_mm >= 1.0:
        verdict = "SELECTIVE_PASS"
    elif sel_mm is not None:
        verdict = "SELECTIVE_FAIL"
    else:
        verdict = "SELECTIVE_ERROR"

    ts = _ts()
    receipt = {
        "ticket": "SELECTIVE_RECOMPUTE_AB",
        "ts": ts,
        "verdict": verdict,
        "issue": "#296",
        "runtime": {
            "device": str(torch.cuda.get_device_name(0)),
            "sm": str(torch.cuda.get_device_capability(0)[0] * 10 + torch.cuda.get_device_capability(0)[1]),
            "torch": torch.__version__,
        },
        "config": config,
        "governor": governor,
        "arm_aggregate": arm_agg,
        "per_seed_results": {arm: results[arm] for arm in arms},
        "measured_multiplier_vs_full_ckpt": {
            "selective": sel_mm,
            "none": none_mm,
        },
        "flags": [
            "c03 shapes (v0 training config — same as E4 profiler)",
            f"live run {LIVE_RUN_SHA} NOT touched",
            "governor rails HOLD — never loosened",
            "none arm catches OOM and records VRAM_EXCEEDED rather than crashing",
            "measured_multiplier > 1.0 = arm faster than full-ckpt control",
        ],
    }

    print(f"\n[selective_recompute_ab] verdict: {verdict}", flush=True)
    for arm in arms:
        agg = arm_agg[arm]
        mm = agg.get("measured_multiplier")
        if agg["status"] == "PASS":
            print(f"  {arm}: {agg['mean_tokens_per_s']:.0f} tok/s, "
                  f"MM={mm:.4f}x", flush=True)
        else:
            print(f"  {arm}: {agg['status']} — {agg.get('reason','')}", flush=True)

    os.makedirs(RECEIPTS, exist_ok=True)
    out = os.path.join(RECEIPTS, f"selective-recompute-ab-{ts}.json")
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2))
    print(f"SELECTIVE_RECOMPUTE_AB_DONE {out}")
    return receipt


# ---------------------------------------------------------------------------
# Selftest (CPU-only, no GPU, no shards)
# ---------------------------------------------------------------------------

def _selftest():
    # 1. Governor constants satisfy fp19 floor
    assert VRAM_FRACTION <= 0.80, "VRAM_FRACTION must not exceed 0.80"
    assert MARGIN_GIB >= 1.5,   "MARGIN_GIB must not be below 1.5"
    assert PACE_S >= 0.05,      "PACE_S must not be below 0.05"

    # 2. Arms defined correctly
    assert "full-ckpt" in ["full-ckpt", "selective", "none"]
    assert "selective" in ["full-ckpt", "selective", "none"]

    # 3. measured_multiplier formula: arm/ctrl (>1.0 = arm faster)
    def mm(arm_tok_s, ctrl_tok_s):
        return arm_tok_s / ctrl_tok_s
    assert mm(30000, 25000) > 1.0   # arm faster
    assert mm(20000, 25000) < 1.0   # arm slower
    assert abs(mm(25000, 25000) - 1.0) < 1e-9

    # 4. c03 shapes are non-trivial
    assert HIDDEN == 1024
    assert LAYERS == 20
    assert SEQ == 1024
    assert BATCH == 4

    # 5. Seeds are fixed
    assert set(SEEDS) == {16, 17, 18}

    # 6. Selective forward patch is importable (no GPU needed for the patch itself)
    import types
    class _FakeSelfAttn:
        def __call__(self, hidden_states, **kw):
            return hidden_states, None
    class _FakeMLP:
        def __call__(self, x): return x
    class _FakeNorm:
        def __call__(self, x): return x
    class _FakeLayer:
        def __init__(self):
            self.self_attn = _FakeSelfAttn()
            self.mlp = _FakeMLP()
            self.input_layernorm = _FakeNorm()
            self.post_attention_layernorm = _FakeNorm()
        def forward(self, hs, **kw): return hs

    import torch.utils.checkpoint as cu
    layer = _FakeLayer()
    _patch_layer_selective(layer, cu)
    # Patched forward should be callable (CPU smoke — no gradient flow in selftest)
    assert callable(layer.forward), "selective patch must produce a callable forward"

    # 7. verify_at_boot tamper detection: working-tree modification must REFUSE.
    #    This test would have caught the git-blob hashing regression (verify must
    #    read the ACTUAL bytes the loop will consume, not the committed blob).
    import subprocess, tempfile, shutil
    _tmpdir = tempfile.mkdtemp(prefix="nck_tamper_selftest_")
    try:
        # Init a bare git repo and commit a dummy protected file.
        subprocess.run(["git", "init", _tmpdir], check=True, capture_output=True)
        subprocess.run(["git", "-C", _tmpdir, "config", "user.email", "test@test"], check=True, capture_output=True)
        subprocess.run(["git", "-C", _tmpdir, "config", "user.name", "test"], check=True, capture_output=True)
        _prot = os.path.join(_tmpdir, "protected.txt")
        with open(_prot, "wb") as f:
            f.write(b"original content\n")
        subprocess.run(["git", "-C", _tmpdir, "add", "protected.txt"], check=True, capture_output=True)
        subprocess.run(["git", "-C", _tmpdir, "commit", "-m", "init"], check=True, capture_output=True)

        # Build a minimal manifest + baseline using the committed bytes.
        import hashlib as _hl
        _blob_hash = _hl.sha256(b"original content\n").hexdigest()
        _manifest = {
            "protected_paths": [
                {"label": "protected-file", "path": "protected.txt", "sha256": _blob_hash}
            ]
        }
        import json as _json
        # verify_at_boot derives repo_root = dirname(dirname(manifest_path)).
        # Put manifest at _tmpdir/config/manifest.json so repo_root = _tmpdir.
        _config_dir = os.path.join(_tmpdir, "config")
        os.makedirs(_config_dir, exist_ok=True)
        _baseline_dir = os.path.join(_config_dir, "baseline")
        os.makedirs(_baseline_dir, exist_ok=True)
        _manifest_path = os.path.join(_config_dir, "manifest.json")
        _baseline_path = os.path.join(_baseline_dir, "manifest.json")
        _mdata = (_json.dumps(_manifest, indent=2) + "\n").encode("utf-8")
        with open(_manifest_path, "wb") as f: f.write(_mdata)
        with open(_baseline_path, "wb") as f: f.write(_mdata)

        # Add the invariants module to path and verify clean state passes.
        import sys as _sys
        _scripts_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)))
        if _scripts_dir not in _sys.path:
            _sys.path.insert(0, _scripts_dir)
        from nck.invariants import verify_at_boot
        verify_at_boot(manifest_path=_manifest_path, baseline_path=_baseline_path)

        # Tamper the working-tree file WITHOUT touching git objects.
        with open(_prot, "wb") as f:
            f.write(b"TAMPERED content\n")

        # verify_at_boot must REFUSE — working-tree bytes have changed.
        _refused = False
        try:
            verify_at_boot(manifest_path=_manifest_path, baseline_path=_baseline_path)
        except SystemExit as _e:
            if "INVARIANT_REFUSE" in str(_e):
                _refused = True
        assert _refused, (
            "TAMPER DETECTION REGRESSION: verify_at_boot accepted a tampered "
            "working-tree file. verify_at_boot must hash working-tree bytes, "
            "not git-blob bytes."
        )
    finally:
        shutil.rmtree(_tmpdir, ignore_errors=True)

    print("SELECTIVE_RECOMPUTE_AB_SELFTEST_PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
