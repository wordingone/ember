# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""fp38b_l9_completion.py — L9 completion: b16 + b8 no-ckpt flash cells.

fp38_l9_flash_ab covered B=39/33/26 (all OOM from MLP activations).
This bench extends to B=16 and B=8 to fully price the activation model:
  - Flash eliminates S² attention scores (~640MB at B=16)
  - But MLP activations + residuals at hidden=1024 may still OOM
  - B=16-nockpt-flash would need to fit where B=16-nockpt-eager failed
  - B=8-nockpt-flash is the minimum useful batch for this architecture

Both cells: flash/SDPA + no-ckpt + compiled + QAT + governed.
Same anchor as fp38: b4-ckpt-eager = 18,472 tok/s.

The result refits the activation OOM model for c04 design:
KILL-at-all-batches → c04 must solve activation budget via architecture
REVIVE-at-b8 → c04 can use flash+no-ckpt if hidden/batch tuned below OOM
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)
# issue2015 exact-local-import:src/ember/governance/scripts/fp19_bench.py
import importlib.util as _ember_f0fbd2c9d8066617_importlib
import sys as _ember_f0fbd2c9d8066617_sys
from pathlib import Path as _ember_f0fbd2c9d8066617_Path
_ember_f0fbd2c9d8066617_path = _ember_f0fbd2c9d8066617_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'fp19_bench.py')
if not _ember_f0fbd2c9d8066617_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/fp19_bench.py')
_ember_f0fbd2c9d8066617_aliases = ('_ember_issue2015_f0fbd2c9d8066617', 'fp19_bench', 'scripts.fp19_bench')
_ember_f0fbd2c9d8066617_existing = []
for _ember_f0fbd2c9d8066617_alias in _ember_f0fbd2c9d8066617_aliases:
    _ember_f0fbd2c9d8066617_candidate = _ember_f0fbd2c9d8066617_sys.modules.get(_ember_f0fbd2c9d8066617_alias)
    if _ember_f0fbd2c9d8066617_candidate is not None and all(_ember_f0fbd2c9d8066617_candidate is not item for item in _ember_f0fbd2c9d8066617_existing):
        _ember_f0fbd2c9d8066617_existing.append(_ember_f0fbd2c9d8066617_candidate)
if len(_ember_f0fbd2c9d8066617_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/fp19_bench.py')
if _ember_f0fbd2c9d8066617_existing:
    _ember_f0fbd2c9d8066617_module = _ember_f0fbd2c9d8066617_existing[0]
    _ember_f0fbd2c9d8066617_observed = getattr(_ember_f0fbd2c9d8066617_module, '__file__', None)
    if _ember_f0fbd2c9d8066617_observed is None or _ember_f0fbd2c9d8066617_Path(_ember_f0fbd2c9d8066617_observed).resolve() != _ember_f0fbd2c9d8066617_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/fp19_bench.py')
else:
    _ember_f0fbd2c9d8066617_spec = _ember_f0fbd2c9d8066617_importlib.spec_from_file_location('_ember_issue2015_f0fbd2c9d8066617', _ember_f0fbd2c9d8066617_path)
    if _ember_f0fbd2c9d8066617_spec is None or _ember_f0fbd2c9d8066617_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/fp19_bench.py')
    _ember_f0fbd2c9d8066617_module = _ember_f0fbd2c9d8066617_importlib.module_from_spec(_ember_f0fbd2c9d8066617_spec)
    for _ember_f0fbd2c9d8066617_alias in _ember_f0fbd2c9d8066617_aliases:
        _ember_f0fbd2c9d8066617_prior = _ember_f0fbd2c9d8066617_sys.modules.get(_ember_f0fbd2c9d8066617_alias)
        if _ember_f0fbd2c9d8066617_prior is not None and _ember_f0fbd2c9d8066617_prior is not _ember_f0fbd2c9d8066617_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/fp19_bench.py')
        _ember_f0fbd2c9d8066617_sys.modules[_ember_f0fbd2c9d8066617_alias] = _ember_f0fbd2c9d8066617_module
    try:
        _ember_f0fbd2c9d8066617_spec.loader.exec_module(_ember_f0fbd2c9d8066617_module)
    except BaseException:
        for _ember_f0fbd2c9d8066617_alias in _ember_f0fbd2c9d8066617_aliases:
            if _ember_f0fbd2c9d8066617_sys.modules.get(_ember_f0fbd2c9d8066617_alias) is _ember_f0fbd2c9d8066617_module:
                _ember_f0fbd2c9d8066617_sys.modules.pop(_ember_f0fbd2c9d8066617_alias, None)
        raise
for _ember_f0fbd2c9d8066617_alias in _ember_f0fbd2c9d8066617_aliases:
    _ember_f0fbd2c9d8066617_prior = _ember_f0fbd2c9d8066617_sys.modules.get(_ember_f0fbd2c9d8066617_alias)
    if _ember_f0fbd2c9d8066617_prior is not None and _ember_f0fbd2c9d8066617_prior is not _ember_f0fbd2c9d8066617_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/fp19_bench.py')
    _ember_f0fbd2c9d8066617_sys.modules[_ember_f0fbd2c9d8066617_alias] = _ember_f0fbd2c9d8066617_module
fp19 = _ember_f0fbd2c9d8066617_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/fp19_bench.py                              # noqa: E402
# issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
import importlib.util as _ember_66ee9e91637922dc_importlib
import sys as _ember_66ee9e91637922dc_sys
from pathlib import Path as _ember_66ee9e91637922dc_Path
_ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
if not _ember_66ee9e91637922dc_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_write.py')
_ember_66ee9e91637922dc_aliases = ('_ember_issue2015_66ee9e91637922dc', 'receipt_write', 'scripts.receipt_write')
_ember_66ee9e91637922dc_existing = []
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_candidate = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_candidate is not None and all(_ember_66ee9e91637922dc_candidate is not item for item in _ember_66ee9e91637922dc_existing):
        _ember_66ee9e91637922dc_existing.append(_ember_66ee9e91637922dc_candidate)
if len(_ember_66ee9e91637922dc_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_write.py')
if _ember_66ee9e91637922dc_existing:
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_existing[0]
    _ember_66ee9e91637922dc_observed = getattr(_ember_66ee9e91637922dc_module, '__file__', None)
    if _ember_66ee9e91637922dc_observed is None or _ember_66ee9e91637922dc_Path(_ember_66ee9e91637922dc_observed).resolve() != _ember_66ee9e91637922dc_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_write.py')
else:
    _ember_66ee9e91637922dc_spec = _ember_66ee9e91637922dc_importlib.spec_from_file_location('_ember_issue2015_66ee9e91637922dc', _ember_66ee9e91637922dc_path)
    if _ember_66ee9e91637922dc_spec is None or _ember_66ee9e91637922dc_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_importlib.module_from_spec(_ember_66ee9e91637922dc_spec)
    for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
        _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
        if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
        _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
    try:
        _ember_66ee9e91637922dc_spec.loader.exec_module(_ember_66ee9e91637922dc_module)
    except BaseException:
        for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
            if _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias) is _ember_66ee9e91637922dc_module:
                _ember_66ee9e91637922dc_sys.modules.pop(_ember_66ee9e91637922dc_alias, None)
        raise
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
checked_write = getattr(_ember_66ee9e91637922dc_module, 'checked_write')
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py               # noqa: E402

RECEIPTS = f"{NC}/receipts"
SEQ = fp19.SEQ
VOCAB = fp19.VOCAB
PACE_S = fp19.PACE_S
VRAM_FRACTION = 0.80
MARGIN_GIB = fp19.MARGIN_GIB
WARMUP_COMPILE = 8
TIMED = 10
VARIANT = "qat"

ANCHOR_TOK_S = 18472.2
COMPILED_TOK_S = 31377.4
PRIOR_RECEIPT_L9 = "fp38-l9-flash-ab-20260612T223639Z.json"
PRIOR_RECEIPT_L6 = "fp32-l6-compile-ab-20260612T215844Z.json"
BATCH_LADDER = (16, 8)


def _enable_flash_global():
    """Set flash SDPA backend globally — no context manager needed."""
    import torch
    try:
        from torch.nn.attention import SDPBackend, sdpa_kernel as _sk
        # Can't hold open a context manager across steps; set globally via flags
        torch.backends.cuda.enable_flash_sdp(True)
        torch.backends.cuda.enable_mem_efficient_sdp(True)
        torch.backends.cuda.enable_math_sdp(False)
    except Exception:
        torch.backends.cuda.enable_flash_sdp(True)
        torch.backends.cuda.enable_mem_efficient_sdp(True)
        torch.backends.cuda.enable_math_sdp(False)


def bench_cell(batch):
    import torch
    from transformers import LlamaConfig, LlamaForCausalLM

    c = fp19.CONFIGS["c03"]
    cell_name = f"b{batch}-nockpt-flash-compile"
    out = {
        "cell": cell_name, "batch": batch, "seq": SEQ,
        "grad_checkpointing": False, "compiled": True,
        "flash_sdpa": True, "variant": VARIANT,
        "timed_steps": TIMED, "warmup_reps": WARMUP_COMPILE,
    }
    try:
        conf = LlamaConfig(
            vocab_size=VOCAB, hidden_size=c["hidden"],
            intermediate_size=4 * c["hidden"],
            num_hidden_layers=c["layers"], num_attention_heads=c["heads"],
            num_key_value_heads=c["heads"], max_position_embeddings=SEQ,
            tie_word_embeddings=True,
        )
        model = LlamaForCausalLM(conf).cuda().to(torch.bfloat16)
        model.train()
        opt = torch.optim.AdamW(model.parameters(), lr=1e-4)
        # Set flash backend globally — avoids graph break from sdpa_kernel CM
        # inside the compiled call, which triggers the output_capturing NameError.
        _enable_flash_global()

        print(f"[fp38b] torch.compile(model) ...", flush=True)
        fwd = torch.compile(model)

        def step():
            saved = fp19._apply_fake_quant(model, VARIANT)
            ids = torch.randint(0, VOCAB, (batch, SEQ), device="cuda")
            o = fwd(input_ids=ids, labels=ids)
            o.loss.backward()
            fp19._restore(saved)
            opt.step()
            opt.zero_grad(set_to_none=True)

        print(f"[fp38b] warmup {WARMUP_COMPILE} steps ...", flush=True)
        for i in range(WARMUP_COMPILE):
            step()
            print(f"[fp38b]   warmup {i+1}/{WARMUP_COMPILE}", flush=True)
        torch.cuda.synchronize()
        free_b, _ = torch.cuda.mem_get_info()
        free_gib = free_b / (1 << 30)
        out["free_vram_gib_post_warmup"] = round(free_gib, 2)
        if free_gib < MARGIN_GIB:
            out["status"] = "SKIPPED-MARGIN"
            del model, opt, fwd
            torch.cuda.empty_cache()
            return out

        print(f"[fp38b] bench {TIMED} steps ...", flush=True)
        t0 = time.perf_counter()
        for _ in range(TIMED):
            step()
            torch.cuda.synchronize()
            time.sleep(PACE_S)
        dt = time.perf_counter() - t0
        toks = TIMED * batch * SEQ
        paced = toks / dt
        raw = toks / (dt - TIMED * PACE_S)
        out.update(status="OK", tok_s_paced=round(paced, 1),
                   tok_s_raw=round(raw, 1),
                   pacing_tax=round(1.0 - paced / raw, 4))
        del model, opt, fwd
        torch.cuda.empty_cache()
        return out
    except torch.cuda.OutOfMemoryError:
        out["status"] = "SKIPPED-OOM"
        torch.cuda.empty_cache()
        return out
    except Exception as e:
        out["status"] = "CELL-ERROR"
        out["error"] = f"{type(e).__name__}: {e}"[:400]
        torch.cuda.empty_cache()
        return out


def main():
    import torch
    torch.cuda.set_per_process_memory_fraction(VRAM_FRACTION)

    print(f"[fp38b] device: {torch.cuda.get_device_name(0)}", flush=True)
    print(f"[fp38b] torch: {torch.__version__}", flush=True)
    print(f"[fp38b] L9 completion: batch ladder {BATCH_LADDER} (B=39/33/26 OOM in fp38)", flush=True)

    cells = []
    best = None
    for batch in BATCH_LADDER:
        print(f"\n[fp38b] cell b{batch}-nockpt-flash-compile ...", flush=True)
        r = bench_cell(batch)
        print(f"[fp38b]   -> {json.dumps(r)}", flush=True)
        cells.append(r)
        if r.get("status") == "OK" and best is None:
            best = r

    ts_now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    all_oom = all(c.get("status") == "SKIPPED-OOM" for c in cells)
    any_error = any(c.get("status") == "CELL-ERROR" for c in cells)
    if best:
        mm_vs_anchor = round(best["tok_s_paced"] / ANCHOR_TOK_S, 4)
        mm_vs_compiled = round(best["tok_s_paced"] / COMPILED_TOK_S, 4)
        verdict = f"L9_COMPLETE_VIABLE_B{best['batch']}" if mm_vs_anchor >= 1.02 else f"L9_COMPLETE_MARGINAL_B{best['batch']}"
    else:
        mm_vs_anchor = mm_vs_compiled = None
        verdict = "L9_KILLED_ALL_BATCHES"

    if all_oom:
        arch_note = (
            "ALL-OOM: flash/SDPA does not save enough activation memory at c03 "
            "hidden=1024 even at B=8. MLP activations + residuals are the binding "
            "constraint. L9 ARCH-KILL confirmed across full batch range (B=8..39). "
            "c04 must solve via smaller hidden or FSDP offload."
        )
    elif best:
        arch_note = (
            f"REVIVE at B={best['batch']}: flash enables no-ckpt at reduced batch. "
            "c04 design: hidden/batch tuning within this constraint is viable."
        )
    else:
        arch_note = (
            "ALL-CELL-ERROR: compiled cells failed (likely transformers NameError). "
            "Re-run with corrected compile wrapper to get OOM/viable verdict."
        )

    receipt = {
        "ticket": "FP38B-L9-COMPLETION",
        "ts": ts_now,
        "lever": "L9",
        "issue": 225,
        "verdict": verdict,
        "arch_note": arch_note,
        "prior_receipts": {
            "fp38_l9": PRIOR_RECEIPT_L9,
            "fp32_l6": PRIOR_RECEIPT_L6,
        },
        "baseline": {
            "anchor_cell": "b4-ckpt-eager",
            "anchor_tok_s_paced": ANCHOR_TOK_S,
            "compiled_l6_tok_s_paced": COMPILED_TOK_S,
            "fp38_oom_batches": [39, 33, 26],
        },
        "cells": cells,
        "best_cell": best,
        "multipliers": {
            "vs_anchor": mm_vs_anchor,
            "vs_l6_compiled": mm_vs_compiled,
        },
        "runtime": {
            "device": torch.cuda.get_device_name(0),
            "torch": torch.__version__,
        },
        "governor": {
            "vram_fraction": VRAM_FRACTION,
            "margin_gib_floor": MARGIN_GIB,
            "pace_s_per_step": PACE_S,
        },
        "flags": [
            "c03 shapes (hidden=1024, layers=20, heads=16, ffn=4096, seq=1024)",
            "flash/SDPA: torch.nn.attention.sdpa_kernel flash+efficient backends",
            "no gradient checkpointing",
            f"batch ladder: {BATCH_LADDER} (extending fp38 which covered 39/33/26)",
            "compile: torch.compile(model) default backend",
            f"warmup_compile={WARMUP_COMPILE}",
            "governor rails HOLD — never loosened",
        ],
    }

    out = f"{RECEIPTS}/fp38b-l9-completion-{ts_now}.json"
    checked_write(out, receipt)
    print(json.dumps({
        "verdict": verdict,
        "arch_note": arch_note,
        "cells": [{"cell": c["cell"], "status": c.get("status"),
                   "tok_s_paced": c.get("tok_s_paced")} for c in cells],
    }, indent=2))
    print(f"FP38B_L9_COMPLETION_DONE {os.path.relpath(out, NC)}")


if __name__ == "__main__":
    main()
