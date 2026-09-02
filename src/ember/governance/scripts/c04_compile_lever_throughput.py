# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""c04_compile_lever_throughput.py — torch.compile LEVER probe (C-EFF wall-break).

WHY
===
c04_eager_bf16_throughput.py measured the FAITHFUL production recipe at tok_s_paced=16402.2
(effective_days=1.17 > 1.0) — production BF16-eager is BELOW the SHATTER floor (19190.5).
The keystone's 19874.8 came from a faster recipe (qat + torch.compile + batched-muon). The
biggest recoverable lever is torch.compile(fwd): eng56 KILLED it citing a dynamo NameError on
the QAT graph and pinned eager. PRODUCTION HAS NO QAT — so the NameError may be QAT-specific and
compile may work on the pure bf16 graph. This probe tests that, on the EXACT production recipe.

ROUND-2 ROOT CAUSE (run 20260623T113656Z, COMPILE-BREAK -> fixed here): the v1 break was
`Tensor.requires_grad_` reached THROUGH `model.backbone(x)` — the `_V0Real.backbone` Python
WRAPPER METHOD (ts:1127), not the LlamaModel. The anchor (fp45_batched_ns5_ab.py:347,
grad_ckpt=True + .train()) compiled the SAME LlamaModel arch and shattered (19874.8) by compiling
the raw `backbone` directly. So the inner graph compiles; the wrapper frame is what dynamo
choked on. FIX: the compiled fwd calls `model.backbone_model(input_ids=x).last_hidden_state`
(the anchor boundary) instead of the wrapper. This is PROVABLY identical to the wrapper's
text-only path: ts:1150 returns exactly `self.backbone_model(input_ids=ids).last_hidden_state`
when inputs_embeds is None and span_boundaries is falsy — and C-BASE pretrain is text-only. NOT a
recipe change: same computation, compile-traceable boundary. The eager baseline KEEPS the wrapper
(production-faithful), so the correctness gate (compiled-backbone_model vs eager-wrapper) ALSO
proves the boundary equivalence. CE is already dynamo-safe: resolve_ce_impl (ts:974) returns the
module-global chunked_cross_entropy by name, so calling it AFTER apply() yields the patched CE.

This is break-the-wall (make-supported), not escalate. Re-enabling compile reverses the
eng56-eager-pin deviation — legitimate ONLY with this receipt proving: (a) compile_status=PASS on
the no-QAT graph, (b) compiled loss == eager loss within bf16 tolerance (correctness; same
computation), (c) tok_s_compiled >= 19190.5 (clears the floor).

RECIPE (production, reused builders — same as the eager gate):
  governor : ts._apply_governor()
  model    : ts.build_v0_model(cfg, live=True)            # _V0Real .backbone(ids)/.head/.mtp_heads, bf16, grad_ckpt
  opt      : ts.build_split_optimizer(model, cfg)          # per-param _Muon split + AdamW
  ce       : ts.resolve_ce_impl(prefer_liger=True)         # cut_ce_chunked (smoke); dynamo-safe after apply()
  fwd      : model.backbone(x) -> ce(...,chunk=256) primary + per-MTP -> mtp_total_loss
  COMPILE  : c04_dynamo_patch.apply() (dynamo-safe chunked CE) + apply_compile_patch(backbone_model)
             (strip co_varnames decorator) + torch.compile(fwd, fullgraph=True). FWD-ONLY compile;
             backward + optimizer.step stay eager (c04_dynamo_patch contract). Same as the 19874.8
             anchor's compile approach, minus the qat fake-quant.

CELLS (one model build):
  correctness : eager fwd loss vs compiled fwd loss on a FIXED input (untrained weights). GATE.
  A eager     : re-measure the production eager baseline on THIS run (sanity vs 16402-class).
  B compiled  : torch.compile(fwd) timed window. tok_s_compiled -> effective_days. THE LEVER GATE.

FLOOR (frozen SHATTER anchor — identical to the eager gate):
  effective_days(tok_s) = K / tok_s,  K = 0.96557 * 19874.8 = 19190.5
  LEVER RECOVERS SHATTER  <=>  compile_status==PASS AND correctness_ok AND tok_s_compiled >= 19190.5

Receipt : receipts/c04-compile-lever-throughput-{ts}.json
Selftest: python c04_compile_lever_throughput.py --selftest -> COMPILE_LEVER_THROUGHPUT_SELFTEST_PASS
Dispatch: via train MCP (GPU; one model at a time). Production governor applied (fail-closed).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE     = os.path.dirname(os.path.abspath(__file__))
NC       = os.path.dirname(HERE)
RECEIPTS = os.path.join(NC, "receipts")
sys.path.insert(0, HERE)

from receipt_write import checked_write    # noqa: E402  (light; no torch)
# timeshare_pretrain + c04_dynamo_patch imported lazily inside _run_bench (selftest stays torch-free).

WARMUP = 5
TIMED  = 20

BATCH               = 16
CE_CHUNK_TOKENS     = 256
TOTAL_STEPS_NOMINAL = 449651

EFFECTIVE_DAYS_ANCHOR = 0.96557
TOK_S_ANCHOR          = 19874.8
EFFECTIVE_DAYS_FLOOR  = 1.0
K_TOK_S_FLOOR = EFFECTIVE_DAYS_ANCHOR * TOK_S_ANCHOR  # 19190.5

CORRECTNESS_REL_TOL = 0.02   # bf16 + reduction-order; catches a broken unwrap, tolerant of bf16 noise


def effective_days(tok_s_paced: float) -> float:
    if tok_s_paced <= 0:
        return float("inf")
    return K_TOK_S_FLOOR / tok_s_paced


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _harness_sha() -> str:
    h = hashlib.sha256()
    with open(__file__, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_bench() -> dict:
    import torch
    # issue2015 exact-local-import:src/ember/governance/scripts/timeshare_pretrain.py
    import importlib.util as _ember_d9c5c82c124e1dc8_importlib
    import sys as _ember_d9c5c82c124e1dc8_sys
    from pathlib import Path as _ember_d9c5c82c124e1dc8_Path
    _ember_d9c5c82c124e1dc8_path = _ember_d9c5c82c124e1dc8_Path(__file__).resolve().parent.joinpath('timeshare_pretrain.py')
    if not _ember_d9c5c82c124e1dc8_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/timeshare_pretrain.py')
    _ember_d9c5c82c124e1dc8_aliases = ('_ember_issue2015_d9c5c82c124e1dc8', 'src.ember.governance.scripts.timeshare_pretrain', 'timeshare_pretrain')
    _ember_d9c5c82c124e1dc8_existing = []
    for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
        _ember_d9c5c82c124e1dc8_candidate = _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias)
        if _ember_d9c5c82c124e1dc8_candidate is not None and all(_ember_d9c5c82c124e1dc8_candidate is not item for item in _ember_d9c5c82c124e1dc8_existing):
            _ember_d9c5c82c124e1dc8_existing.append(_ember_d9c5c82c124e1dc8_candidate)
    if len(_ember_d9c5c82c124e1dc8_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/timeshare_pretrain.py')
    if _ember_d9c5c82c124e1dc8_existing:
        _ember_d9c5c82c124e1dc8_module = _ember_d9c5c82c124e1dc8_existing[0]
        _ember_d9c5c82c124e1dc8_observed = getattr(_ember_d9c5c82c124e1dc8_module, '__file__', None)
        if _ember_d9c5c82c124e1dc8_observed is None or _ember_d9c5c82c124e1dc8_Path(_ember_d9c5c82c124e1dc8_observed).resolve() != _ember_d9c5c82c124e1dc8_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/timeshare_pretrain.py')
    else:
        _ember_d9c5c82c124e1dc8_spec = _ember_d9c5c82c124e1dc8_importlib.spec_from_file_location('_ember_issue2015_d9c5c82c124e1dc8', _ember_d9c5c82c124e1dc8_path)
        if _ember_d9c5c82c124e1dc8_spec is None or _ember_d9c5c82c124e1dc8_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/timeshare_pretrain.py')
        _ember_d9c5c82c124e1dc8_module = _ember_d9c5c82c124e1dc8_importlib.module_from_spec(_ember_d9c5c82c124e1dc8_spec)
        for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
            _ember_d9c5c82c124e1dc8_prior = _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias)
            if _ember_d9c5c82c124e1dc8_prior is not None and _ember_d9c5c82c124e1dc8_prior is not _ember_d9c5c82c124e1dc8_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/timeshare_pretrain.py')
            _ember_d9c5c82c124e1dc8_sys.modules[_ember_d9c5c82c124e1dc8_alias] = _ember_d9c5c82c124e1dc8_module
        try:
            _ember_d9c5c82c124e1dc8_spec.loader.exec_module(_ember_d9c5c82c124e1dc8_module)
        except BaseException:
            for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
                if _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias) is _ember_d9c5c82c124e1dc8_module:
                    _ember_d9c5c82c124e1dc8_sys.modules.pop(_ember_d9c5c82c124e1dc8_alias, None)
            raise
    for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
        _ember_d9c5c82c124e1dc8_prior = _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias)
        if _ember_d9c5c82c124e1dc8_prior is not None and _ember_d9c5c82c124e1dc8_prior is not _ember_d9c5c82c124e1dc8_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/timeshare_pretrain.py')
        _ember_d9c5c82c124e1dc8_sys.modules[_ember_d9c5c82c124e1dc8_alias] = _ember_d9c5c82c124e1dc8_module
    ts = _ember_d9c5c82c124e1dc8_module
    # issue2015 exact-local-import-end:src/ember/governance/scripts/timeshare_pretrain.py

    gov = ts._apply_governor()
    torch.manual_seed(42)

    cfg = ts.load_contract()
    seq         = cfg["model"]["seq"]
    mtp_cfg     = cfg["objective"]["mtp_aux_heads"]
    mtp_weight  = mtp_cfg["weight"]
    mtp_enabled = bool(mtp_cfg["enabled"])
    pace_s      = ts.FP19_PACE_S

    model, vocab, hidden, n_mtp = ts.build_v0_model(cfg, live=True)
    model_training = bool(model.training)
    bb = getattr(model, "backbone_model", None)
    bb_training = bool(bb.training) if bb is not None else model_training
    if not (model_training and bb_training):
        raise SystemExit(
            f"COMPILE_LEVER_MODE_FAIL: training={model_training}/{bb_training} — expected True "
            f"(grad_ckpt active, matching production + anchor).")
    optimizers, base_lrs, routing = ts.build_split_optimizer(model, cfg)
    print(f"[compile-lever] routing mode={routing.get('mode')} n_muon={routing.get('n_muon')} "
          f"n_adamw={routing.get('n_adamw')}", flush=True)

    def make_batch(gen=None):
        kw = {"device": "cuda"}
        if gen is not None:
            kw["generator"] = gen
        x  = torch.randint(1, vocab, (BATCH, seq), **kw)
        y0 = torch.randint(1, vocab, (BATCH, seq), **kw)
        ym = [torch.randint(1, vocab, (BATCH, seq), **kw) for _ in range(n_mtp)]
        return x, y0, ym

    def build_fwd(ce_fn, *, compiled_boundary=False):
        def fwd(x, y0, y_mtp):
            if compiled_boundary:
                # Anchor boundary (fp45_batched_ns5_ab.py:347 — the 19874.8 existence proof):
                # compile the raw LlamaModel. PROVABLY == the _V0Real.backbone text-path
                # (ts:1150 returns exactly self.backbone_model(input_ids=ids).last_hidden_state
                # when inputs_embeds is None and span_boundaries falsy — the C-BASE text-only path).
                # The wrapper METHOD frame broke dynamo (Tensor.requires_grad_); the inner
                # LlamaModel compiles cleanly, as the anchor proves. Same computation, not a recipe change.
                h = model.backbone_model(input_ids=x).last_hidden_state
            else:
                h = model.backbone(x)  # production-faithful wrapper (text-path == backbone_model call)
            hf = h.reshape(-1, h.shape[-1])
            pce, _ = ce_fn(hf, model.head.weight, y0.reshape(-1), chunk_tokens=CE_CHUNK_TOKENS)
            mces = []
            if mtp_enabled:
                for k in range(n_mtp):
                    ce_k, _ = ce_fn(hf, model.mtp_heads[k].weight, y_mtp[k].reshape(-1),
                                    chunk_tokens=CE_CHUNK_TOKENS)
                    mces.append(ce_k)
            return ts.mtp_total_loss(pce, mces, mtp_weight)
        return fwd

    # ── ORIGINAL (pre-patch) CE + fwd, for the eager baseline + correctness reference ──
    ce_impl_orig, ce_fn_orig = ts.resolve_ce_impl(prefer_liger=True)
    fwd_eager = build_fwd(ce_fn_orig)

    # Correctness reference loss on a FIXED input, on untrained weights (before any opt step).
    gen = torch.Generator(device="cuda"); gen.manual_seed(1234)
    fx = make_batch(gen)
    with torch.no_grad():
        eager_loss_ref = float(fwd_eager(*fx).detach())
    print(f"[compile-lever] ce_impl={ce_impl_orig} eager_loss_ref={eager_loss_ref:.5f}", flush=True)

    def timed_cell(label, fwd_call):
        # warmup
        for i in range(WARMUP):
            loss = fwd_call(*make_batch())
            loss.backward()
            for opt in optimizers.values():
                opt.step()
            for opt in optimizers.values():
                opt.zero_grad(set_to_none=True)
        torch.cuda.empty_cache(); torch.cuda.synchronize()
        free_b, total_b = torch.cuda.mem_get_info()
        free_gib = free_b / (1 << 30)
        if free_gib < ts.FP19_MARGIN_GIB:
            return {"status": "SKIPPED-MARGIN", "free_vram_gib": round(free_gib, 3)}
        step_times = []
        t0 = time.perf_counter()
        for i in range(TIMED):
            t_s = time.perf_counter()
            loss = fwd_call(*make_batch())
            loss.backward()
            for opt in optimizers.values():
                opt.step()
            for opt in optimizers.values():
                opt.zero_grad(set_to_none=True)
            torch.cuda.synchronize()
            t_step = time.perf_counter() - t_s
            time.sleep(pace_s)
            step_times.append(t_step)
        total_dt = time.perf_counter() - t0
        toks = TIMED * BATCH * seq
        tp = toks / total_dt
        return {"status": "OK", "tok_s_paced": round(tp, 1),
                "tok_s_raw": round(toks / (total_dt - TIMED * pace_s), 1),
                "mean_step_ms": round(sum(step_times) / len(step_times) * 1000, 2),
                "effective_days": round(effective_days(tp), 5),
                "free_vram_gib_post_warmup": round(free_gib, 2)}

    # ── Cell A: eager baseline (sanity; should land near the 16402 eager gate) ──
    cell_a = timed_cell("eager", fwd_eager)
    print(f"[compile-lever] CELL-A eager: {cell_a.get('status')} tok_s={cell_a.get('tok_s_paced','?')} "
          f"eff_days={cell_a.get('effective_days','?')}", flush=True)

    # ── Apply dynamo patches + compile (the LEVER) ──
    compile_status = "SKIP"; compiled_loss_ref = None; correctness_ok = False
    grad_ckpt_compiled = "reentrant (default; not reached)"  # set when the non-reentrant re-enable runs
    eager_cmp_loss = None  # eager loss on the SAME weights as the compiled comparison
    cell_b = {"status": "NOT-RUN"}
    try:
        import c04_dynamo_patch
        c04_dynamo_patch.apply()                                   # chunked_ce -> dynamo-safe (global)
        if bb is not None:
            # ROOT CAUSE of the v1/v2/v3 COMPILE-BREAK (Tensor.requires_grad_): the LlamaConfig had
            # use_cache=True — build_v0_model (ts:1114-1118) OMITS use_cache, so HF defaults it True.
            # With grad-ckpt + training, LlamaModel.forward runs a runtime "use_cache incompatible
            # with gradient checkpointing -> set False" branch that, under fullgraph trace, hits
            # Tensor.requires_grad_ (untraceable). The qat DESIGN BENCH compiles the SAME forward graph
            # and PASSES *only because its LlamaConfig sets use_cache=False* (c04_design_bench.py:132) —
            # NOT because of fake_quant (red herring; fake_quant only swaps weight.data). v3's
            # use_reentrant=False did NOT fix it (the break is the use_cache branch, not reentrancy).
            # FIX (make-supported, break-the-wall, NUMERICALLY NEUTRAL — use_cache only affects inference
            # KV-cache, irrelevant in training and force-off under grad-ckpt anyway): set
            # config.use_cache=False before compile, exactly as the design bench. NO qat required — this
            # is the no-qat production graph. The eager baseline already trains with use_cache effectively
            # False (runtime-forced), so this is faithful; the correctness gate proves loss-equivalence.
            bb.config.use_cache = False
            grad_ckpt_compiled = "reentrant (production default, ts:1153); config.use_cache=False set pre-compile (design-bench parity c04_design_bench:132; numerically neutral)"
            c04_dynamo_patch.apply_compile_patch(bb)               # strip co_varnames decorator
        ce_impl_c, ce_fn_c = ts.resolve_ce_impl(prefer_liger=True)  # now returns the patched CE
        fwd_patched = build_fwd(ce_fn_c, compiled_boundary=True)     # anchor boundary (raw LlamaModel)
        try:
            fwd_compiled = torch.compile(fwd_patched, fullgraph=True)
            # trial call triggers the trace/compile (absorbed before timing)
            _l = fwd_compiled(*make_batch())
            _l.backward()
            for opt in optimizers.values():
                opt.zero_grad(set_to_none=True)
            compile_status = "PASS"
            # correctness: compiled vs eager loss on the SAME fixed input (same current weights)
            with torch.no_grad():
                compiled_loss_ref = float(fwd_compiled(*fx).detach())
                eager_now = float(fwd_eager(*fx).detach())
            eager_cmp_loss = eager_now
            rel = abs(compiled_loss_ref - eager_now) / max(abs(eager_now), 1e-6)
            correctness_ok = rel <= CORRECTNESS_REL_TOL
            print(f"[compile-lever] compile PASS | correctness: compiled={compiled_loss_ref:.5f} "
                  f"eager={eager_now:.5f} rel={rel:.4f} ok={correctness_ok}", flush=True)
            cell_b = timed_cell("compiled", fwd_compiled)
            cell_b["correctness_rel_diff"] = round(rel, 5)
            cell_b["correctness_ok"] = bool(correctness_ok)
        except torch._dynamo.exc.Unsupported as e:
            compile_status = "BREAK"
            cell_b = {"status": "COMPILE-BREAK", "error": f"{e!s:.300}"}
        except Exception as e:  # noqa: BLE001
            compile_status = "ERROR"
            cell_b = {"status": "COMPILE-ERROR", "error": f"{type(e).__name__}: {e!s:.300}"}
    except Exception as e:  # noqa: BLE001
        compile_status = "PATCH-UNAVAILABLE"
        cell_b = {"status": "PATCH-UNAVAILABLE", "error": f"{type(e).__name__}: {e!s:.300}"}
    print(f"[compile-lever] CELL-B compiled: status={cell_b.get('status')} "
          f"tok_s={cell_b.get('tok_s_paced','?')} compile_status={compile_status}", flush=True)

    compiled_ok = cell_b.get("status") == "OK"
    tok_s_compiled = cell_b.get("tok_s_paced", 0.0) if compiled_ok else 0.0
    eff_days_compiled = cell_b.get("effective_days") if compiled_ok else None
    lever_recovers = bool(compile_status == "PASS" and correctness_ok and compiled_ok
                          and eff_days_compiled is not None and eff_days_compiled <= EFFECTIVE_DAYS_FLOOR)

    if lever_recovers:
        verdict = "COMPILE-LEVER-RECOVERS-SHATTER"
    elif compile_status != "PASS":
        verdict = "COMPILE-UNAVAILABLE-NEED-OTHER-LEVER"
    elif compiled_ok and not correctness_ok:
        verdict = "COMPILE-FAST-BUT-INCORRECT"
    else:
        verdict = "COMPILE-INSUFFICIENT-STACK-LEVERS"

    return {
        "status": "OK",
        "governor": gov,
        "recipe": {
            "source": "timeshare_pretrain production builders + c04_dynamo_patch compile",
            "optimizer_mode": routing.get("mode"),
            "n_muon": routing.get("n_muon"), "n_adamw": routing.get("n_adamw"),
            "ce_impl_eager": ce_impl_orig,
            "model_training_mode": model_training, "backbone_training_mode": bb_training,
            "batch": BATCH, "seq": seq, "n_mtp": n_mtp, "ce_chunk_tokens": CE_CHUNK_TOKENS,
            "compile": "fwd-only torch.compile(fullgraph=True); backward+opt eager",
            "compile_boundary": "model.backbone_model (raw LlamaModel; anchor boundary fp45:347). "
                                "Eager baseline keeps the _V0Real.backbone wrapper (production text-path "
                                "== backbone_model call, ts:1150). v1 break was the wrapper method frame.",
            "grad_ckpt_compiled": grad_ckpt_compiled,
            "grad_ckpt_eager": "reentrant (production default, ts:1153)",
        },
        "cells": {"eager": cell_a, "compiled": cell_b},
        "correctness": {"eager_loss_untrained_ref": round(eager_loss_ref, 5),
                        "eager_loss_at_compare": round(eager_cmp_loss, 5) if eager_cmp_loss is not None else None,
                        "compiled_loss_at_compare": round(compiled_loss_ref, 5) if compiled_loss_ref is not None else None,
                        "note": "ok compares compiled(backbone_model boundary) vs eager(wrapper) on the "
                                "SAME (post-cell-A) weights — also proves the boundary equivalence (ts:1150)",
                        "rel_tol": CORRECTNESS_REL_TOL, "ok": bool(correctness_ok)},
        "anchor": {"effective_days_anchor": EFFECTIVE_DAYS_ANCHOR, "tok_s_anchor": TOK_S_ANCHOR,
                   "K_tok_s_floor": round(K_TOK_S_FLOOR, 2),
                   "provenance": "shatter-verdict-canonical-20260623.json"},
        "gate": {
            "compile_status": compile_status,
            "tok_s_eager_paced": cell_a.get("tok_s_paced") if cell_a.get("status") == "OK" else None,
            "tok_s_compiled_paced": tok_s_compiled if compiled_ok else None,
            "tok_s_floor": round(K_TOK_S_FLOOR, 2),
            "effective_days_compiled": eff_days_compiled,
            "effective_days_floor": EFFECTIVE_DAYS_FLOOR,
            "correctness_ok": bool(correctness_ok),
            "lever_recovers_shatter": lever_recovers,
            "verdict": verdict,
        },
    }


def run_and_emit() -> Path:
    result = _run_bench()
    receipt = {
        "ticket": "C04-COMPILE-LEVER-THROUGHPUT",
        "ts": _ts(),
        "scope": "C-EFF wall-break: does torch.compile on the no-QAT production graph recover the SHATTER floor",
        "harness_sha": _harness_sha(),
        **result,
    }
    os.makedirs(RECEIPTS, exist_ok=True)
    path = os.path.join(RECEIPTS, f"c04-compile-lever-throughput-{receipt['ts']}.json")
    checked_write(path, receipt)
    print(f"[compile-lever] receipt: {path}", flush=True)
    g = result.get("gate", {})
    print(f"[compile-lever] VERDICT: {g.get('verdict')} | compile={g.get('compile_status')} | "
          f"tok_s_compiled={g.get('tok_s_compiled_paced')} (floor>={g.get('tok_s_floor')}) | "
          f"eff_days={g.get('effective_days_compiled')} | correctness_ok={g.get('correctness_ok')} | "
          f"recovers={g.get('lever_recovers_shatter')}", flush=True)
    print(f"COMPILE_LEVER_THROUGHPUT_DONE verdict={g.get('verdict')} "
          f"recovers={g.get('lever_recovers_shatter')}", flush=True)
    return Path(path)


def _verify_receipt_schema(r: dict) -> None:
    assert r["ticket"] == "C04-COMPILE-LEVER-THROUGHPUT"
    g = r["gate"]
    for key in ("compile_status", "tok_s_floor", "effective_days_floor",
                "correctness_ok", "lever_recovers_shatter", "verdict"):
        assert key in g, f"gate missing '{key}'"
    assert "cells" in r and "eager" in r["cells"] and "compiled" in r["cells"]
    assert "correctness" in r


def selftest() -> None:
    print("[c04_compile_lever_throughput] selftest: math + schema (no GPU)", flush=True)
    assert abs(effective_days(TOK_S_ANCHOR) - EFFECTIVE_DAYS_ANCHOR) < 1e-6
    assert abs(effective_days(K_TOK_S_FLOOR) - 1.0) < 1e-9
    print(f"  floor: tok_s>={K_TOK_S_FLOOR:.1f} <=> effective_days<=1.0  PASS")

    # recovers: compile PASS + correctness + compiled >= floor
    syn_recover = {
        "ticket": "C04-COMPILE-LEVER-THROUGHPUT",
        "cells": {"eager": {"status": "OK", "tok_s_paced": 16402.2},
                  "compiled": {"status": "OK", "tok_s_paced": 21000.0}},
        "correctness": {"ok": True},
        "gate": {"compile_status": "PASS", "tok_s_floor": round(K_TOK_S_FLOOR, 2),
                 "tok_s_compiled_paced": 21000.0, "effective_days_compiled": round(effective_days(21000.0), 5),
                 "effective_days_floor": 1.0, "correctness_ok": True,
                 "lever_recovers_shatter": True, "verdict": "COMPILE-LEVER-RECOVERS-SHATTER"},
    }
    _verify_receipt_schema(syn_recover)
    assert effective_days(21000.0) < 1.0 and syn_recover["gate"]["lever_recovers_shatter"]
    print("  schema (RECOVER synthetic, compiled>=floor + correct): PASS")

    # compile fast but incorrect -> NOT recovers
    assert effective_days(25000.0) < 1.0  # fast
    syn_bad = dict(syn_recover)
    syn_bad = json.loads(json.dumps(syn_recover))
    syn_bad["gate"]["correctness_ok"] = False
    syn_bad["gate"]["lever_recovers_shatter"] = False
    syn_bad["gate"]["verdict"] = "COMPILE-FAST-BUT-INCORRECT"
    _verify_receipt_schema(syn_bad)
    assert not syn_bad["gate"]["lever_recovers_shatter"]
    print("  schema (FAST-BUT-INCORRECT synthetic): PASS")

    # compile break -> need other lever
    syn_break = {
        "ticket": "C04-COMPILE-LEVER-THROUGHPUT",
        "cells": {"eager": {"status": "OK", "tok_s_paced": 16402.2},
                  "compiled": {"status": "COMPILE-BREAK"}},
        "correctness": {"ok": False},
        "gate": {"compile_status": "BREAK", "tok_s_floor": round(K_TOK_S_FLOOR, 2),
                 "tok_s_compiled_paced": None, "effective_days_compiled": None,
                 "effective_days_floor": 1.0, "correctness_ok": False,
                 "lever_recovers_shatter": False, "verdict": "COMPILE-UNAVAILABLE-NEED-OTHER-LEVER"},
    }
    _verify_receipt_schema(syn_break)
    assert not syn_break["gate"]["lever_recovers_shatter"]
    print("  schema (COMPILE-BREAK synthetic): PASS")
    print("COMPILE_LEVER_THROUGHPUT_SELFTEST_PASS")


def main() -> None:
    ap = argparse.ArgumentParser(description="torch.compile lever probe for C-EFF (production graph)")
    ap.add_argument("--selftest", action="store_true")
    args, _ = ap.parse_known_args()
    if args.selftest:
        selftest()
    else:
        run_and_emit()


if __name__ == "__main__":
    main()
