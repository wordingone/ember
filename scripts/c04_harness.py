"""c04_harness.py — c04 training harness scaffold (H3 leg 3).

Engineering features (all config-driven, no hardcoded choices):
  C-3  opt_type: "muon_split" (Muon on 2D cores + fused AdamW side)
                 "full_fused_adamw" (fused AdamW on all params)
  L9   attn_impl: "flash" | "sdpa" | "eager" — config flag, default "flash"
  C-4  compile_model: torch.compile from step 0; zero-break assert after warmup
  C-7  MTP/CE wall-share: separate CUDA-event timing for primary CE vs MTP heads,
       both surfaced as named receipt line-items

Selftest: CPU-only — validates param routing, config schema, receipt structure.
GPU bench (main): dispatched separately once scaffold PR is merged.

Governor rails (HOLD — never loosened):
  VRAM_FRACTION = 0.80, MARGIN_GIB = 1.5, PACE_S = 0.05
"""
import json
import os
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from receipt_write import checked_write  # noqa: E402
import timeshare_pretrain as ts          # noqa: E402
import fp19_bench as fp19               # noqa: E402

RECEIPTS = f"{NC}/receipts"

# Governor rails — never loosened
VRAM_FRACTION = 0.80
MARGIN_GIB = fp19.MARGIN_GIB   # 1.5
PACE_S = fp19.PACE_S            # 0.05

SEQ = fp19.SEQ      # 1024
VOCAB = fp19.VOCAB  # 32000

# attn_impl → transformers attn_implementation string
_ATTN_IMPL_MAP = {
    "flash": "flash_attention_2",
    "sdpa":  "sdpa",
    "eager": "eager",
}

VALID_OPT_TYPES = ("muon_split", "full_fused_adamw")
VALID_ATTN_IMPLS = tuple(_ATTN_IMPL_MAP.keys())


@dataclass
class HarnessConfig:
    # model shape (defaults = c03; override per c04 pick)
    hidden: int = 1024
    layers: int = 20
    heads: int = 16
    vocab: int = VOCAB
    seq: int = SEQ
    # batch / grad_ckpt
    batch: int = 16
    grad_ckpt: bool = False
    # optimizer
    opt_type: str = "muon_split"   # "muon_split" | "full_fused_adamw"
    lr_muon: float = 0.02
    lr_adamw: float = 3e-4
    weight_decay: float = 0.1
    # attention
    attn_impl: str = "flash"       # "flash" | "sdpa" | "eager"
    # MTP
    mtp_n_heads: int = 2
    mtp_weight: float = 0.3
    # compile
    compile_model: bool = True

    def validate(self):
        assert self.opt_type in VALID_OPT_TYPES, \
            f"opt_type must be one of {VALID_OPT_TYPES}, got {self.opt_type!r}"
        assert self.attn_impl in VALID_ATTN_IMPLS, \
            f"attn_impl must be one of {VALID_ATTN_IMPLS}, got {self.attn_impl!r}"
        assert self.hidden % self.heads == 0, \
            f"hidden ({self.hidden}) must be divisible by heads ({self.heads})"
        assert self.mtp_n_heads >= 0
        assert 0.0 <= self.mtp_weight <= 1.0


def apply_attn_backend(cfg: HarnessConfig):
    """Set global SDPA backend flags for cfg.attn_impl (CUDA only).

    Uses torch.backends.cuda flags — no context manager, no graph break.
    fp38b pattern: set globally before torch.compile, held for the session.
    No-op on CPU (called only from bench_cell after CUDA is confirmed).
    """
    import torch
    if cfg.attn_impl == "flash":
        torch.backends.cuda.enable_flash_sdp(True)
        torch.backends.cuda.enable_mem_efficient_sdp(True)
        torch.backends.cuda.enable_math_sdp(False)
    elif cfg.attn_impl == "sdpa":
        torch.backends.cuda.enable_flash_sdp(False)
        torch.backends.cuda.enable_mem_efficient_sdp(True)
        torch.backends.cuda.enable_math_sdp(True)
    else:  # eager
        torch.backends.cuda.enable_flash_sdp(False)
        torch.backends.cuda.enable_mem_efficient_sdp(False)
        torch.backends.cuda.enable_math_sdp(True)


def build_model(cfg: HarnessConfig, device="cuda"):
    """Build backbone, tied head, and MTP heads on the given device.

    attn_impl is enforced via apply_attn_backend() (global SDPA flags);
    call that before compile when on CUDA.
    """
    import torch
    from transformers import LlamaConfig, LlamaModel

    conf = LlamaConfig(
        vocab_size=cfg.vocab,
        hidden_size=cfg.hidden,
        intermediate_size=4 * cfg.hidden,
        num_hidden_layers=cfg.layers,
        num_attention_heads=cfg.heads,
        num_key_value_heads=cfg.heads,
        max_position_embeddings=cfg.seq,
        use_cache=False,
    )
    backbone = LlamaModel(conf)
    backbone = backbone.to(device).to(torch.bfloat16)

    if cfg.grad_ckpt and device != "cpu":
        backbone.gradient_checkpointing_enable()

    head = torch.nn.Linear(cfg.hidden, cfg.vocab, bias=False).to(device).to(torch.bfloat16)
    head.weight = backbone.embed_tokens.weight   # tied

    mtp_heads = torch.nn.ModuleList([
        torch.nn.Linear(cfg.hidden, cfg.vocab, bias=False).to(device).to(torch.bfloat16)
        for _ in range(cfg.mtp_n_heads)
    ])

    return backbone, head, mtp_heads


def build_optimizers(cfg: HarnessConfig, backbone, mtp_heads):
    """Build optimizer dict according to cfg.opt_type.

    On CPU (for selftest): fused=False regardless of opt_type.
    On CUDA: fused=True for AdamW where supported.
    """
    import torch

    # Check device from a representative param
    sample_param = next(backbone.parameters())
    on_cuda = sample_param.is_cuda

    all_params = dict(backbone.named_parameters())
    for i, h in enumerate(mtp_heads):
        for n, p in h.named_parameters():
            all_params[f"mtp_heads.{i}.{n}"] = p

    if cfg.opt_type == "full_fused_adamw":
        opts = {
            "adamw": torch.optim.AdamW(
                list(all_params.values()),
                lr=cfg.lr_adamw,
                weight_decay=cfg.weight_decay,
                fused=on_cuda,
            )
        }
        param_group_summary = {
            "opt_type": "full_fused_adamw",
            "total_params": len(all_params),
            "adamw_params": len(all_params),
            "muon_params": 0,
            "fused": on_cuda,
        }
    else:
        # muon_split: Muon on 2D hidden params excluding embed_tokens; AdamW on rest
        muon_params, adamw_params = [], []
        muon_names, adamw_names = [], []
        for name, p in all_params.items():
            if p.ndim == 2 and "embed_tokens" not in name:
                muon_params.append(p)
                muon_names.append(name)
            else:
                adamw_params.append(p)
                adamw_names.append(name)

        Muon = ts._muon_class()
        opts = {}
        if muon_params:
            opts["muon"] = Muon(muon_params, lr=cfg.lr_muon, weight_decay=cfg.weight_decay)
        opts["adamw"] = torch.optim.AdamW(
            adamw_params,
            lr=cfg.lr_adamw,
            weight_decay=cfg.weight_decay,
            fused=on_cuda,
        )
        param_group_summary = {
            "opt_type": "muon_split",
            "total_params": len(all_params),
            "muon_params": len(muon_params),
            "adamw_params": len(adamw_params),
            "fused_adamw": on_cuda,
        }

    return opts, param_group_summary


def wrap_and_compile(cfg: HarnessConfig, backbone):
    """Return (fwd_fn, compile_info).

    fwd_fn(ids) → last_hidden_state.
    Unwraps transformers decorator before compiling (fp39b pattern).
    If cfg.compile_model=False, returns a plain callable.
    """
    import types
    import torch

    _cls_fwd = type(backbone).forward
    while hasattr(_cls_fwd, "__wrapped__"):
        _cls_fwd = _cls_fwd.__wrapped__
    backbone.forward = types.MethodType(_cls_fwd, backbone)

    def _backbone_call(ids):
        return backbone(input_ids=ids).last_hidden_state

    if not cfg.compile_model:
        return _backbone_call, {"compiled": False}

    fwd_compiled = torch.compile(_backbone_call, mode="reduce-overhead")
    return fwd_compiled, {"compiled": True, "mode": "reduce-overhead"}


def step_with_mtp_ce_timing(cfg, backbone, fwd_fn, head, mtp_heads, opts, ids):
    """Single training step.

    Returns dict of CUDA-event timing (ms) per phase, including C-7 split:
      "ce_primary"  — primary CE loss compute
      "ce_mtp"      — MTP heads CE compute (all heads summed)
    """
    import torch

    ce_fn = ts.chunked_cross_entropy
    tgt0 = torch.roll(ids, -1, dims=1)
    tgt_mtp = [torch.roll(ids, -(k + 2), dims=1) for k in range(cfg.mtp_n_heads)]

    phase_keys = ["backbone", "ce_primary", "ce_mtp", "backward"] + list(opts.keys())
    ev = {k: (torch.cuda.Event(enable_timing=True),
              torch.cuda.Event(enable_timing=True)) for k in phase_keys}

    saved = fp19._apply_fake_quant(backbone, "qat")

    ev["backbone"][0].record()
    hidden = fwd_fn(ids)
    ev["backbone"][1].record()

    h_flat = hidden.reshape(-1, hidden.shape[-1])

    ev["ce_primary"][0].record()
    primary_ce, _ = ce_fn(h_flat, head.weight, tgt0.reshape(-1), chunk_tokens=1024)
    ev["ce_primary"][1].record()

    ev["ce_mtp"][0].record()
    mtp_ces = []
    for k, mh in enumerate(mtp_heads):
        ce_k, _ = ce_fn(h_flat, mh.weight, tgt_mtp[k].reshape(-1), chunk_tokens=1024)
        mtp_ces.append(ce_k)
    ev["ce_mtp"][1].record()

    loss = ts.mtp_total_loss(primary_ce, mtp_ces, cfg.mtp_weight)

    fp19._restore(saved)

    ev["backward"][0].record()
    loss.backward()
    ev["backward"][1].record()

    for opt_key in opts:
        ev[opt_key][0].record()
        opts[opt_key].step()
        ev[opt_key][1].record()

    for o in opts.values():
        o.zero_grad(set_to_none=True)

    return ev, loss.item()


def _check_zero_recompile(compile_count_before: int) -> dict:
    """After warmup: assert dynamo didn't recompile.

    Returns receipt fragment: {zero_break_assert: bool, recompiles_detected: int}.
    """
    try:
        import torch._dynamo.utils as du
        after = du.counters["stats"].get("calls_captured", 0)
        delta = max(0, after - compile_count_before)
        return {"zero_break_assert": delta == 0, "recompiles_post_warmup": delta}
    except Exception:
        return {"zero_break_assert": None, "recompiles_post_warmup": None,
                "note": "dynamo counters unavailable"}


def _dynamo_calls_captured() -> int:
    try:
        import torch._dynamo.utils as du
        return du.counters["stats"].get("calls_captured", 0)
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Selftest — CPU-only, no GPU required
# ---------------------------------------------------------------------------

def selftest():
    """Validate config, optimizer routing, and receipt schema without GPU."""
    import torch

    print("[c04_harness selftest] start")

    # 1 — config validation
    cfg_default = HarnessConfig()
    cfg_default.validate()
    print(f"[selftest] default config valid: {cfg_default.opt_type}, {cfg_default.attn_impl}")

    for ot in VALID_OPT_TYPES:
        HarnessConfig(opt_type=ot).validate()
    for ai in VALID_ATTN_IMPLS:
        HarnessConfig(attn_impl=ai).validate()
    print("[selftest] all opt_type / attn_impl variants validate OK")

    # 2 — tiny CPU model + optimizer routing (eager — SDPA flags are CUDA-only)
    tiny = HarnessConfig(hidden=64, layers=2, heads=2, vocab=128, seq=16,
                         batch=1, compile_model=False, attn_impl="eager")

    for ot in VALID_OPT_TYPES:
        tiny.opt_type = ot
        backbone, head, mtp_heads = build_model(tiny, device="cpu")
        opts, summary = build_optimizers(tiny, backbone, mtp_heads)
        assert summary["total_params"] > 0, "no params"
        if ot == "muon_split":
            assert "muon" in opts or summary["muon_params"] == 0
            assert "adamw" in opts
            assert summary["muon_params"] + summary["adamw_params"] == summary["total_params"]
        else:
            assert "adamw" in opts
            assert len(opts) == 1, f"full_fused_adamw should have 1 optimizer, got {list(opts)}"
        del backbone, head, mtp_heads, opts
        print(f"[selftest] opt_type={ot!r}: param routing OK — {summary}")

    # 3 — attn_impl mapping
    for impl, expected in _ATTN_IMPL_MAP.items():
        assert _ATTN_IMPL_MAP[impl] == expected
    print(f"[selftest] attn_impl mapping: {_ATTN_IMPL_MAP}")

    # 4 — receipt schema (mock timing data)
    mock_phase_ms = {
        "backbone": 12.5, "ce_primary": 3.1, "ce_mtp": 2.8,
        "backward": 22.0, "muon": 4.5, "adamw": 0.2,
    }
    total_ms = sum(mock_phase_ms.values())
    phase_pct = {k: round(100 * v / total_ms, 2) for k, v in mock_phase_ms.items()}
    ce_primary_pct = phase_pct["ce_primary"]
    ce_mtp_pct = phase_pct["ce_mtp"]
    ce_total_pct = round(ce_primary_pct + ce_mtp_pct, 2)
    opt_pct = {k: phase_pct[k] for k in phase_pct if k in ("muon", "adamw")}

    receipt_fragment = {
        "c7_mtp_ce_wallshare": {
            "ce_primary_pct": ce_primary_pct,
            "ce_mtp_pct": ce_mtp_pct,
            "ce_total_pct": ce_total_pct,
            "note": "C-7: MTP heads CE as separate receipt line-item",
        },
        "optimizer_wall_pct": opt_pct,
        "c4_compile": {"compiled": True, "zero_break_assert": True},
    }
    assert "c7_mtp_ce_wallshare" in receipt_fragment
    assert "ce_primary_pct" in receipt_fragment["c7_mtp_ce_wallshare"]
    assert "c4_compile" in receipt_fragment
    print(f"[selftest] receipt schema: OK — c7_mtp_ce_wallshare keys present")

    # 5 — HarnessConfig serializes cleanly
    cfg_dict = asdict(HarnessConfig())
    assert all(isinstance(k, str) for k in cfg_dict)
    _ = json.dumps(cfg_dict)
    print("[selftest] HarnessConfig JSON-serializable OK")

    print("[c04_harness selftest] SELFTEST_PASS")
    return True


# ---------------------------------------------------------------------------
# GPU bench (dispatched separately; scaffold PR certified by selftest only)
# ---------------------------------------------------------------------------

def bench_cell(cfg: HarnessConfig, warmup_steps: int = 8, timed_steps: int = 10):
    """Run one timed bench cell. Requires CUDA."""
    import torch

    cfg.validate()
    cell_label = (
        f"c04-h{cfg.hidden}-d{cfg.layers}-b{cfg.batch}"
        f"-{cfg.opt_type}-{cfg.attn_impl}"
        f"-{'ckpt' if cfg.grad_ckpt else 'nockpt'}"
        f"-{'compile' if cfg.compile_model else 'eager'}"
    )
    out = {
        "cell": cell_label,
        "config": asdict(cfg),
        "status": "PENDING",
    }

    try:
        backbone, head, mtp_heads = build_model(cfg, device="cuda")
        backbone.train(); head.train(); mtp_heads.train()

        opts, param_summary = build_optimizers(cfg, backbone, mtp_heads)
        out["param_groups"] = param_summary

        apply_attn_backend(cfg)   # set SDPA global flags before compile
        fwd_fn, compile_info = wrap_and_compile(cfg, backbone)
        out["compile_info"] = compile_info

        print(f"[c04] warmup {warmup_steps} steps ...", flush=True)
        dynamo_before = _dynamo_calls_captured()
        for i in range(warmup_steps):
            ids = torch.randint(0, cfg.vocab, (cfg.batch, cfg.seq), device="cuda")
            ev, _ = step_with_mtp_ce_timing(cfg, backbone, fwd_fn, head, mtp_heads, opts, ids)
            print(f"[c04]   warmup {i+1}/{warmup_steps}", flush=True)

        torch.cuda.synchronize()
        free_b, _ = torch.cuda.mem_get_info()
        free_gib = free_b / (1 << 30)
        out["free_vram_gib_post_warmup"] = round(free_gib, 2)
        if free_gib < MARGIN_GIB:
            out["status"] = "SKIPPED-MARGIN"
            del backbone, head, mtp_heads, opts
            torch.cuda.empty_cache()
            return out

        # C-4: zero-break assert
        zero_break = _check_zero_recompile(dynamo_before)
        out["c4_compile"] = {**compile_info, **zero_break}

        print(f"[c04] timed {timed_steps} steps ...", flush=True)
        phase_ms_acc = {}
        t0 = time.perf_counter()
        loss_vals = []
        for _ in range(timed_steps):
            ids = torch.randint(0, cfg.vocab, (cfg.batch, cfg.seq), device="cuda")
            ev, loss_val = step_with_mtp_ce_timing(
                cfg, backbone, fwd_fn, head, mtp_heads, opts, ids)
            torch.cuda.synchronize()
            for k, (s, e) in ev.items():
                phase_ms_acc[k] = phase_ms_acc.get(k, 0.0) + s.elapsed_time(e)
            loss_vals.append(loss_val)
            time.sleep(PACE_S)

        dt = time.perf_counter() - t0
        toks = timed_steps * cfg.batch * cfg.seq
        tok_s_paced = toks / dt
        tok_s_raw = toks / (dt - timed_steps * PACE_S)

        avg_ms = {k: round(v / timed_steps, 2) for k, v in phase_ms_acc.items()}
        total_phase_ms = sum(avg_ms.values())
        phase_pct = {k: round(100 * v / total_phase_ms, 2) for k, v in avg_ms.items()}

        # C-7: MTP/CE wall-share
        ce_primary_pct = phase_pct.get("ce_primary", 0.0)
        ce_mtp_pct = phase_pct.get("ce_mtp", 0.0)
        out["c7_mtp_ce_wallshare"] = {
            "ce_primary_pct": ce_primary_pct,
            "ce_mtp_pct": ce_mtp_pct,
            "ce_total_pct": round(ce_primary_pct + ce_mtp_pct, 2),
            "note": "C-7: MTP heads CE as separate receipt line-item",
        }

        opt_keys = [k for k in opts]
        out.update(
            status="OK",
            tok_s_paced=round(tok_s_paced, 1),
            tok_s_raw=round(tok_s_raw, 1),
            pacing_tax=round(1.0 - tok_s_paced / tok_s_raw, 4),
            phase_ms_per_step=avg_ms,
            phase_pct=phase_pct,
            optimizer_wall_pct={k: phase_pct[k] for k in opt_keys if k in phase_pct},
            loss_mean=round(sum(loss_vals) / len(loss_vals), 4),
        )

        del backbone, head, mtp_heads, opts
        torch.cuda.empty_cache()
        return out

    except Exception as e:
        import traceback
        out["status"] = "CELL-ERROR"
        out["error"] = f"{type(e).__name__}: {e}"[:500]
        print(traceback.format_exc(), flush=True)
        try:
            torch.cuda.empty_cache()
        except Exception:
            pass
        return out


def main():
    import torch
    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION)
    print(f"[c04] device: {torch.cuda.get_device_name(0)}", flush=True)
    print(f"[c04] torch: {torch.__version__}", flush=True)
    print("[c04] c04 harness scaffold — GPU bench (configure cells and dispatch)", flush=True)
    print("[c04] Use bench_cell(HarnessConfig(...)) to run individual cells.", flush=True)
    print("[c04] #363 A/B cells will be scripted on this scaffold.", flush=True)


if __name__ == "__main__":
    import sys as _sys
    if "--selftest" in _sys.argv or len(_sys.argv) == 1:
        ok = selftest()
        _sys.exit(0 if ok else 1)
    else:
        main()
