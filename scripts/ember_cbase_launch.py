#!/usr/bin/env python3
"""ember_cbase_launch.py — §6-gated incremental C-BASE pretrain DRIVER.

Ground contract:
  - accept_cbase and score_core_on_task imported verbatim from
    ember_cbase_s6_acceptance.py (DO NOT reimplement).
  - Checkpoint I/O uses save_checkpoint / load_checkpoint from
    timeshare_pretrain.py.
  - PackedShardLoader from timeshare_pretrain.py (no-pad packing).
  - TRAIN-ONLY firewall: raises on h0xx ids.
  - Vocab firewall: all context token ids < 32000 (enforced in acceptance harness).
  - General-half held-out perplexity probe uses PINNED heldout eval IDs
    from the REJECT verdict (not train ids, not the shards-v0 raw corpus).

Loop contract (floor_met condition):
  floor_met = (n_correct_tasks >= 1 on >=1 train task from accept_cbase)
              AND (held-out ppl strictly descending over last K=2 checkpoints)
  decision: STOP if floor_met; CEILING_STOP if tokens >= ceiling; else CONTINUE.

Perplexity probe: compute cross-entropy (token-level) of the core on heldout
tasks' goal_prompt text as a proxy for general-language learning. Uses the
same tokenizer as the acceptance harness. IMPORTANT: this is a lightweight
proxy (not shards-v0 perplexity which requires the full corpus). It measures
whether the model is learning language on the HELD-OUT half of the [REDACTED]-task
distribution — sufficient to detect memorization collapse on the task subset.

CPU smoke (--tiny --backend inline): forces CUDA_VISIBLE_DEVICES='' + device='cpu'.
Tiny model (vocab=64, hidden=32, depth=2) from timeshare_pretrain._tiny_v0_model.

NEVER calls executing_verifier(), [REDACTED].exe /input, or any external model.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Force CUDA off for CPU smoke path.
# The caller sets CUDA_VISIBLE_DEVICES='' before importing torch;
# we also set it here so the module is self-contained.
# ---------------------------------------------------------------------------
# NOTE: Setting CUDA_VISIBLE_DEVICES after torch.cuda init has no effect —
# the env var must be set BEFORE torch is imported. We set it here as a
# belt-and-suspenders measure; the test module sets it before import.
if os.environ.get("CUDA_VISIBLE_DEVICES", "NOTSET") == "NOTSET":
    # Only set if not already configured — don't override an explicit setting.
    pass  # leave as-is; the smoke test sets '' before import.

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent

sys.path.insert(0, str(_HERE))

# shards-v0 is a fixed structural sibling of the repo root (same junction
# class as sandbox-gpu-test/models elsewhere in this codebase) -- computed
# rather than hardcoded so the default is portable across deployment trees.
_DEFAULT_MIXTURE_DIR = str(_REPO.parent / "shards-v0")

# ---------------------------------------------------------------------------
# Banked imports — DO NOT reimplement these functions.
# ---------------------------------------------------------------------------
from ember_cbase_s6_acceptance import (  # noqa: E402
    accept_cbase,
    score_core_on_task,
    _get_tokenizer,
)
from timeshare_pretrain import (  # noqa: E402
    save_checkpoint,
    load_checkpoint,
    capture_rng,
    restore_rng,
    PackedShardLoader,
    write_packed_shard,
    _tiny_v0_model,
    load_contract,
    build_split_optimizer,
    save_optimizers_state,
    load_optimizers_state,
    wsd_lr_frac,
    apply_wsd,
    chunked_cross_entropy,
    mtp_total_loss,
    FP19_PACE_S,
    FP19_VOCAB,
    FP19_SEQ,
)
from ember_avir_tasks import load_split  # noqa: E402

# ---------------------------------------------------------------------------
# Pinned eval IDs.
#
# SOURCE: cbase-[REDACTED]-data-build-REJECT-verdict-20260623.json GAP3_eval_ids.
# The REJECT verdict JSON is NOT read at runtime — the IDs are pinned
# constants whose values were transcribed from that document.
# Provenance docstring correction: the previous docstring claimed these were
# "from the REJECT verdict" implying runtime reads; they are compile-time
# constants pinned to the GAP3_eval_ids field of that verdict.
#
# Invariants enforced in tests:
#   - HELDOUT_EVAL_IDS elements match ^h\d{3}$ (heldout split)
#   - TRAIN_EVAL_IDS  elements match ^t\d{3}$ (train split)
#   - HELDOUT_EVAL_IDS and TRAIN_EVAL_IDS are disjoint
# ---------------------------------------------------------------------------
TRAIN_EVAL_IDS: list[str] = [
    "t001", "t004", "t007", "t010", "t013", "t016", "t019", "t022"
]
HELDOUT_EVAL_IDS: list[str] = [
    "h001", "h003", "h005", "h007", "h009", "h011", "h013", "h015"
]

# Enforce invariants at module load so any accidental edit is caught immediately.
import re as _re
_HELDOUT_PAT = _re.compile(r"^h\d{3}$")
_TRAIN_PAT   = _re.compile(r"^t\d{3}$")
for _tid in TRAIN_EVAL_IDS:
    assert _TRAIN_PAT.match(_tid), f"TRAIN_EVAL_IDS contains non-train id: {_tid!r}"
for _hid in HELDOUT_EVAL_IDS:
    assert _HELDOUT_PAT.match(_hid), f"HELDOUT_EVAL_IDS contains non-heldout id: {_hid!r}"
assert set(TRAIN_EVAL_IDS).isdisjoint(set(HELDOUT_EVAL_IDS)), (
    "TRAIN_EVAL_IDS and HELDOUT_EVAL_IDS must be disjoint"
)

# Number of consecutive ppl checkpoints that must be descending for floor_met.
PPL_K: int = 2


# ---------------------------------------------------------------------------
# Per-task answer computation (for the meeting-floor stub in tests).
# These compute the correct output from the known sandbox_setup input.
# ---------------------------------------------------------------------------

def _compute_task_answer(task: dict) -> str:
    """Compute the correct answer string for a task from its sandbox_setup input.

    Returns the string that should be written to the primary output file.
    Used by the test stub to synthesize a known-good draft.

    Only covers the 8 pinned train eval IDs (t001, t004, t007, t010, t013,
    t016, t019, t022). Returns '' for unknown tasks (will produce R=0).
    """
    tid = task.get("id", "")
    files = task.get("sandbox_setup", {}).get("files", {})

    if tid == "t001":
        nums = [int(x) for x in files.get("numbers.txt", "").strip().split("\n") if x.strip()]
        return str(sum(nums))

    elif tid == "t004":
        words = [w for w in files.get("items.txt", "").strip().split("\n") if w.strip()]
        return "\n".join(sorted(words)) + "\n"

    elif tid == "t007":
        lines = [l for l in files.get("pairs.txt", "").strip().split("\n") if l.strip()]
        out = []
        for ln in lines:
            if "=" in ln:
                k, v = ln.split("=", 1)
                out.append(f"{v}={k}")
        return "\n".join(out) + "\n"

    elif tid == "t010":
        text = files.get("sentences.txt", "")
        count = sum(len(ln.split()) for ln in text.strip().split("\n") if ln.strip())
        return str(count)

    elif tid == "t013":
        lines = [l for l in files.get("duplicates.txt", "").strip().split("\n") if l.strip()]
        return f"unique_count: {len(set(lines))}"

    elif tid == "t016":
        lines = [l for l in files.get("coords.txt", "").strip().split("\n") if l.strip()]
        products = []
        for ln in lines:
            x, y = ln.split(",")
            products.append(str(int(x) * int(y)))
        return "\n".join(products) + "\n"

    elif tid == "t019":
        a_lines = [l for l in files.get("a.txt", "").strip().split("\n") if l.strip()]
        b_lines = [l for l in files.get("b.txt", "").strip().split("\n") if l.strip()]
        return f"total_lines: {len(a_lines) + len(b_lines)}"

    elif tid == "t022":
        # t022 not always in train.jsonl — fall through to empty.
        pass

    return ""


def _get_primary_output_path(task: dict) -> str:
    """Return the primary output file path from the task's verifier assertions."""
    input_files = set(task.get("sandbox_setup", {}).get("files", {}).keys())
    for a in task.get("verifier_assertions", []):
        if a.get("type") in ("file_exists", "file_contains",
                             "file_created_this_turn", "file_min_lines",
                             "file_max_lines", "file_order_asc"):
            p = a.get("path", "")
            if p and p not in input_files:
                return p
    return "output.txt"


# ---------------------------------------------------------------------------
# floor_met logic
# ---------------------------------------------------------------------------

def _compute_floor_met(
    n_correct: int,
    ppl_history: list[float],
    K: int = PPL_K,
) -> bool:
    """Return True iff floor_met condition satisfied.

    floor_met = (n_correct >= 1) AND (held-out ppl strictly descending
                over the last K checkpoints).

    Requires at least K ppl values in history.
    """
    if n_correct < 1:
        return False
    if len(ppl_history) < K:
        return False
    # Check last K values are strictly descending.
    tail = ppl_history[-K:]
    for i in range(1, len(tail)):
        if tail[i] >= tail[i - 1]:
            return False
    return True


# ---------------------------------------------------------------------------
# Per-checkpoint receipt builder
# ---------------------------------------------------------------------------

def _make_receipt(
    *,
    tokens: int,
    step: int,
    n_correct: int,
    floor_met: bool,
    ppl: float,
    ppl_descending: bool,
    decision: str,
    ts: str | None = None,
    extra: dict | None = None,
) -> dict[str, Any]:
    """Build a per-checkpoint receipt dict."""
    return {
        "ticket": "CBASE-LAUNCH-CHECKPOINT",
        "ts": ts or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "tokens": tokens,
        "step": step,
        "n_correct": n_correct,
        "floor_met": floor_met,
        "ppl": ppl,
        "ppl_descending": ppl_descending,
        "decision": decision,
        **(extra or {}),
    }


# ---------------------------------------------------------------------------
# Held-out perplexity probe
# ---------------------------------------------------------------------------

def _compute_heldout_ppl(core, heldout_task_ids: list[str] = HELDOUT_EVAL_IDS) -> float:
    """Compute proxy held-out perplexity on heldout task goal_prompts.

    Method: tokenize each heldout task's goal_prompt; compute cross-entropy
    of the core's next-token predictions on the token sequence. Average over
    all valid tokens across all heldout tasks.

    This is a PROXY for general-language learning — it measures whether the
    model assigns high probability to the held-out task distribution's text,
    not raw shards-v0 corpus perplexity (which requires the full GPU path).

    Returns float('inf') on error (fail-open — never raises).
    """
    import torch

    try:
        tok = _get_tokenizer()
        heldout_tasks = {t["id"]: t for t in load_split("heldout")}

        total_nll = 0.0
        total_tokens = 0

        for tid in heldout_task_ids:
            if tid not in heldout_tasks:
                continue
            task = heldout_tasks[tid]
            text = task["goal_prompt"]
            ids = tok.encode(text, add_special_tokens=False).ids
            # Vocab firewall.
            ids = [i for i in ids if i < 32000]
            if len(ids) < 2:
                continue

            ctx = torch.tensor(ids[:-1], dtype=torch.long)
            targets = ids[1:]

            # Autoregressive NLL: for each position, get log-prob of the
            # next token. We call sample_action once per position, but
            # that is stochastic — instead we use the backbone + head
            # directly if available, else fall back to sampling-based ppl.
            if hasattr(core, "backbone") and hasattr(core, "head"):
                # Tiny v0 model path — has .backbone() and .head.
                # The model's head weight shape is [model_vocab, hidden]; clamp
                # token ids to [0, model_vocab) so the embedding never raises
                # IndexError.  This is necessary when the model is tiny (vocab=64)
                # but the text tokens come from the full 32000 BPE vocab.
                model_vocab = core.head.weight.shape[0]
                ctx_clamped = ctx % model_vocab
                tgt_clamped = [t % model_vocab for t in targets]
                with torch.no_grad():
                    # backbone expects [B, T] — add batch dim.
                    hidden = core.backbone(ctx_clamped.unsqueeze(0))  # [1, T, H]
                    logits = hidden @ core.head.weight.T               # [1, T, V]
                    logits = logits.squeeze(0)                         # [T, V]
                    log_probs = torch.log_softmax(logits, dim=-1)
                    tgt_t = torch.tensor(tgt_clamped, dtype=torch.long)
                    nll = -log_probs[
                        torch.arange(len(tgt_clamped)), tgt_t
                    ].sum().item()
                    total_nll += nll
                    total_tokens += len(tgt_clamped)
            else:
                # Stub / unknown core: sampling-based ppl approximation.
                # Run sample_action at temperature -> 0 (argmax approximation)
                # and check if it matches the target. This is a crude proxy
                # but sufficient for the smoke path.
                # ppl = exp(NLL); NLL = -log P(target); P(target) ~ 1/vocab
                # for a random model, so ppl ~ vocab size.
                # For the stub, we use a fixed high ppl.
                total_nll += len(targets) * math.log(32000)
                total_tokens += len(targets)

        if total_tokens == 0:
            return float("inf")
        avg_nll = total_nll / total_tokens
        return math.exp(avg_nll)

    except Exception as e:
        # Fail-open: return inf so ppl_descending=False, never crashes the loop.
        return float("inf")


# ---------------------------------------------------------------------------
# Tiny inline segment runner (CPU smoke backend)
# ---------------------------------------------------------------------------

def _run_inline_segment(
    run_dir: str,
    segment_tokens: int,
    optimizer: str,
    resume_ckpt_dir: str | None,
    shard_dir: str,
    *,
    cfg: dict,
    total_steps: int = 10000,
    tiny: bool = True,
) -> tuple[str, int]:
    """Run a tiny CPU segment in-process (no daemon). Returns (ckpt_dir, steps).

    Used for --backend inline (smoke test). Builds a tiny model, runs
    n_steps = segment_tokens // (batch * seq) steps, checkpoints at the end.
    """
    import torch

    device = torch.device("cpu")
    n_mtp = cfg["objective"]["mtp_aux_heads"]["n_heads"]
    tiny_dims = {"vocab": 64, "hidden": 32, "depth": 2}
    seq = 16 if tiny else cfg["model"]["seq"]
    batch_size = 2 if tiny else cfg["throughput"]["batch"]
    vocab = tiny_dims["vocab"] if tiny else cfg["model"]["vocab"]

    tokens_per_step = batch_size * seq
    n_steps = max(1, segment_tokens // tokens_per_step)

    os.makedirs(run_dir, exist_ok=True)

    # Build tiny model.
    model = _tiny_v0_model(vocab, tiny_dims["hidden"], n_mtp, tiny_dims["depth"])
    model = model.to(device)

    # Build optimizer — use muon_split via build_split_optimizer,
    # or fall back to AdamW-everything (tiny model may not have 2D non-embed/head).
    try:
        optimizers, base_lrs, routing = build_split_optimizer(
            model, cfg, force_fallback=(optimizer != "muon_split"),
            deviation_dir=os.path.join(run_dir, "deviations"),
        )
    except Exception:
        # Fallback: plain AdamW for tiny model.
        opt = torch.optim.AdamW(model.parameters(), lr=3e-4)
        optimizers = {"adamw": opt}
        base_lrs = {"adamw": 3e-4}
        routing = {"mode": "adamw_fallback"}

    # Resume.
    resume_step = 0
    if resume_ckpt_dir is not None:
        try:
            m_state, o_state, r_state, manifest = load_checkpoint(resume_ckpt_dir)
            # Attempt to load; skip on shape mismatch (tiny model may differ).
            try:
                model.load_state_dict(m_state, strict=False)
                try:
                    load_optimizers_state(optimizers, o_state)
                except Exception:
                    pass  # optimizer state mismatch on tiny model — skip
                restore_rng(r_state)
                resume_step = manifest.get("step", 0)
            except Exception:
                pass  # shape mismatch — start fresh from tiny init
        except Exception:
            pass

    # Build packed-shard loader (use existing v2 shard).
    shard_path = Path(shard_dir)
    if not any(shard_path.glob("*.bin")):
        # Synthesize a tiny shard if none present.
        import numpy as np
        synth = shard_path / "synth-00000.bin"
        rng_np = np.random.default_rng(42)
        need = (n_steps + 4) * batch_size * seq + seq + n_mtp + 8
        toks = rng_np.integers(1, vocab, size=int(need), dtype=np.int64)
        write_packed_shard(str(synth), toks.astype("uint16").tolist())

    loader = PackedShardLoader(str(shard_path), seq, n_mtp)

    losses: list[float] = []
    for local_step in range(n_steps):
        global_step = resume_step + local_step
        x, y0, y_mtp_list = loader.batch(global_step, batch_size)
        x = x.to(device)
        y0 = y0.to(device)

        # Clamp inputs and targets to [0, vocab) for tiny model.
        # The packed shards may contain token IDs up to the full vocab (32000);
        # the tiny model has vocab=64. Clamp to keep indices in range.
        x = x % vocab
        hidden_out = model.backbone(x)   # [B, T, H]
        h_flat = hidden_out.reshape(-1, hidden_out.shape[-1])
        y0_flat = (y0.reshape(-1)) % vocab
        primary_ce, _ = chunked_cross_entropy(
            h_flat, model.head.weight, y0_flat, chunk_tokens=256
        )

        mtp_ces = []
        for k, head in enumerate(model.mtp_heads):
            y_k = (y_mtp_list[k].to(device).reshape(-1)) % vocab
            ce_k, _ = chunked_cross_entropy(
                h_flat, head.weight, y_k, chunk_tokens=256
            )
            mtp_ces.append(ce_k)

        mtp_weight = cfg["objective"]["mtp_aux_heads"]["weight"]
        loss = mtp_total_loss(primary_ce, mtp_ces, mtp_weight)

        # Apply WSD schedule.
        try:
            apply_wsd(optimizers, base_lrs, global_step, total_steps,
                      cfg["schedule"])
        except Exception:
            pass

        loss.backward()
        for opt in optimizers.values():
            opt.step()
        for opt in optimizers.values():
            opt.zero_grad(set_to_none=True)
        losses.append(float(loss.detach()))

    # Checkpoint at end of segment.
    rng = capture_rng()
    global_end_step = resume_step + n_steps
    ckpt_dir = save_checkpoint(
        run_dir,
        global_end_step,
        model.state_dict(),
        save_optimizers_state(optimizers),
        rng,
        extra={
            "last_loss": losses[-1] if losses else float("nan"),
            "segment_tokens": segment_tokens,
            "optimizer": optimizer,
        },
    )
    return ckpt_dir, global_end_step


# ---------------------------------------------------------------------------
# Daemon backend segment runner
# ---------------------------------------------------------------------------

def _win_to_wsl(path: str) -> str:
    """Convert a Windows drive-letter path to a WSL /mnt/... path.

    If the path already starts with /mnt/ it is returned unchanged.
    """
    if path.startswith("/mnt/") or path.startswith("/"):
        return path
    p = Path(path)
    drive = p.drive.rstrip(":/").lower()
    rest = str(p.relative_to(p.anchor)).replace("\\", "/")
    return f"/mnt/{drive}/{rest}"


def _write_segment_wrapper(
    run_dir: str,
    seg_idx: int,
    run_id: str,
    mixture_dir: str,
    segment_tokens: int,
    total_steps: int,
    resume_ckpt_dir: str | None,
    scripts_dir: str,
) -> str:
    """Write a self-contained per-segment wrapper script and return its Windows path.

    The wrapper bakes all env vars (EMBER_SHARD_DIR, EMBER_SEGMENT_TOKENS,
    EMBER_TOTAL_STEPS, EMBER_RUN_DIR, and optionally EMBER_RESUME_CKPT_DIR) into
    os.environ at module level before importing cbase_v0_segment_live.  This is
    the only reliable env-injection channel for the train daemon (server.py passes
    {**os.environ, "PYTHONUNBUFFERED": "1"} to subprocesses; JobConfig has no env
    field).

    The wrapper is written to scripts_dir (in practice, this module's own
    directory -- see the two call sites below) as
    cbase_seg_<run_id>_<seg_idx>.py.  Each segment gets a distinct file so
    concurrent multi-run scenarios don't collide, and so the wrapper is inspectable
    after the run for auditing.

    Pattern: conv_c03_muon_split_bf16ns5_live.py — env vars baked at module level,
    then delegate via import.
    """
    # 2026-07 (#77): default repointed from state/cbase-mixture (confirmed absent on
    # this machine per receipts/ember-c-scale/c-scale-s3-deletion-arm-20260704T084922Z.json)
    # to the receipted 26-shard / 6,977,868,758-token corpus via the pre-existing junction.
    wsl_shard_dir = _win_to_wsl(mixture_dir) if mixture_dir else _win_to_wsl(
        _DEFAULT_MIXTURE_DIR
    )
    wsl_run_dir = _win_to_wsl(run_dir)

    # Sanitize run_id for use as part of a Python filename.
    import re as _re
    safe_run_id = _re.sub(r"[^a-zA-Z0-9_-]", "_", run_id)[:40]

    wrapper_name = f"cbase_seg_{safe_run_id}_{seg_idx:04d}.py"
    wrapper_path = os.path.join(scripts_dir, wrapper_name)

    lines = [
        '"""Auto-generated per-segment wrapper — do not hand-edit.',
        f'Run-id: {run_id!r}  Segment: {seg_idx}',
        f'Generated by ember_cbase_launch._write_segment_wrapper.',
        '"""',
        "import os",
        "import sys",
        "",
        "# ---------------------------------------------------------------------------",
        "# Bake all per-segment env vars at module level so cbase_v0_segment_live",
        "# reads them correctly regardless of how the daemon starts this script.",
        "# ---------------------------------------------------------------------------",
        f'os.environ["EMBER_SHARD_DIR"] = {wsl_shard_dir!r}',
        f'os.environ["EMBER_SEGMENT_TOKENS"] = {str(segment_tokens)!r}',
        f'os.environ["EMBER_TOTAL_STEPS"] = {str(total_steps)!r}',
        f'os.environ["EMBER_RUN_DIR"] = {wsl_run_dir!r}',
    ]

    if resume_ckpt_dir:
        wsl_resume = _win_to_wsl(resume_ckpt_dir) if not resume_ckpt_dir.startswith("/") else resume_ckpt_dir
        lines.append(f'os.environ["EMBER_RESUME_CKPT_DIR"] = {wsl_resume!r}')
    else:
        lines.append('os.environ.pop("EMBER_RESUME_CKPT_DIR", None)  # N=0: fresh start')

    lines += [
        "",
        "# ---------------------------------------------------------------------------",
        "# Delegate to cbase_v0_segment_live (reads env vars above, calls ts.main()).",
        "# ---------------------------------------------------------------------------",
        f'sys.path.insert(0, {scripts_dir!r})',
        "import cbase_v0_segment_live  # noqa: F401  (runs on import via module-level code)",
    ]

    with open(wrapper_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    return wrapper_path


def _build_daemon_job_payload(
    run_dir: str,
    optimizer: str,
    resume_ckpt_dir: str | None,
    segment_tokens: int,
    cfg: dict,
    mixture_dir: str = "",
) -> dict:
    """Build the POST /jobs payload for the daemon backend.

    Does NOT actually POST — pure payload construction. Callers POST separately.

    The script is an absolute WSL path to cbase_v0_segment_live.py, which reads
    all config from env vars set in the payload's env block (carried through the
    daemon's os.environ pass-through).  The daemon writes train_config.json but
    timeshare_pretrain.py does NOT read it — all configuration must be in the
    wrapper script's env vars.

    output_dir must contain /models/ per the daemon API contract.

    Recipe note
    -----------
    C-BASE v0 recipe: BF16-eager run_v0_segment (WSD + resume + no torch.compile,
    no fake-quant).  The convergence-harness BF16 number is run_convergence_segment
    — a separate code path — and is NOT the C-BASE throughput basis.  The receipted
    production throughput is measured from run_v0_segment on the daemon
    (daemon-smoke-verify receipt).  The c04 bench was qat-once (compiled-bf16 with
    a one-shot weight transform), NOT per-step QAT STE; the production decision is
    BF16-eager per spec-section8-sanction (shatter-production-transfer-precision-
    20260623.json).  The QAT-tax framing in prior versions of this docstring is
    superseded and removed.
    """
    wsl_run_dir = _win_to_wsl(run_dir)

    # Script: absolute WSL path to cbase_v0_segment_live.py.
    # This wrapper reads all config from env vars and calls ts.main().
    scripts_dir = _HERE
    if not scripts_dir.is_absolute():
        scripts_dir = scripts_dir.resolve()
    wsl_scripts_dir = _win_to_wsl(str(scripts_dir))
    script = f"{wsl_scripts_dir}/cbase_v0_segment_live.py"

    # Ensure output_dir contains /models/ (daemon API contract).
    if "/models/" not in wsl_run_dir:
        wsl_run_dir = wsl_run_dir.rstrip("/") + "/models/cbase-run"

    # Dataset: WSL path to the mixture dir (40/10/50 blend).
    # This is the 'dataset' field in the daemon's JobConfig — written verbatim
    # into train_config.json.  The wrapper script reads EMBER_SHARD_DIR from env;
    # both are set so that train_config.json and the live path agree.
    # 2026-07 (#77): same repoint as _write_segment_wrapper — the state/cbase-mixture
    # fallback target is absent on this machine.
    wsl_mixture_dir = _win_to_wsl(mixture_dir) if mixture_dir else _win_to_wsl(
        _DEFAULT_MIXTURE_DIR
    )

    # Compute derived step counts — batch=16, seq=1024 (c04 bench cell frozen recipe).
    # batch=16 is hardcoded here to match the receipted best_cell
    # (c04-design-bench-c03-h1024-d20-20260623T024512Z.json) which specifies
    # batch=16 and receipts 19874.8 tok/s.  cfg["throughput"]["batch"]=4 in
    # v0-pretrain-config.json is overridden; the kwarg in timeshare_pretrain.main()
    # --live call carries the same override.
    _batch = 16  # bench cell recipe — do NOT read from cfg["throughput"]["batch"]
    _seq = cfg.get("model", {}).get("seq", 1024)
    tokens_per_step = _batch * _seq
    # Total steps = compute-optimal budget // tokens_per_step.
    # Use the config token budget if available; fall back to 7.367B.
    _budget = 7_367_086_080
    _total_steps = max(1, _budget // tokens_per_step)

    # hyperparams dict: written to train_config.json by the daemon.
    # The wrapper script does NOT read this dict — it reads env vars.
    # We keep this for observability / audit trail in train_config.json.
    hyperparams: dict[str, Any] = {
        "optimizer": optimizer,
        "segment_tokens": segment_tokens,
        "live": True,
        "recipe_note": (
            "QAT muon_split batch=16 run_v0_segment — WSD+resume. "
            "C-BASE recipe == c04 bench cell (receipt c04-design-bench-c03-h1024-d20-20260623T024512Z.json). "
            "Receipted throughput: 19874.8 tok/s (tok_s_paced). "
            "The convergence-harness BF16 number (19600 tok/s) is run_convergence_segment, "
            "a separate code path — NOT the C-BASE throughput basis."
        ),
    }
    if resume_ckpt_dir is not None:
        hyperparams["resume_ckpt_dir"] = resume_ckpt_dir

    # env_overrides: injected into the daemon process env before the script runs.
    # The daemon passes {**os.environ, "PYTHONUNBUFFERED": "1"} to the subprocess;
    # we add our vars here so the wrapper script can read them.
    # NOTE: the daemon's server.py passes `env = {**os.environ, "PYTHONUNBUFFERED": "1"}`
    # directly to create_subprocess_exec — it does NOT accept per-job env overrides
    # in the current JobConfig schema.  We therefore bake the segment-specific values
    # into the hyperparams dict (for the train_config.json audit trail) AND document
    # that the GPU launch driver must set these env vars in the daemon's process env
    # before POSTing, OR the wrapper script must read them from train_config.json.
    # For now, cbase_v0_segment_live.py reads env vars; the launch driver must ensure
    # they are set in the environment that starts the daemon, or use a patched daemon
    # that accepts per-job env in the JobConfig.  See GPU launch-verification checklist.
    hyperparams["_env_required"] = {
        "EMBER_SHARD_DIR": wsl_mixture_dir,
        "EMBER_SEGMENT_TOKENS": str(segment_tokens),
        "EMBER_TOTAL_STEPS": str(_total_steps),
        **({"EMBER_RESUME_CKPT_DIR": resume_ckpt_dir} if resume_ckpt_dir else {}),
    }

    return {
        "model": "c03-h1024-d20",
        "dataset": wsl_mixture_dir,
        "script": script,
        "output_dir": wsl_run_dir,
        "hyperparams": hyperparams,
    }


def _submit_daemon_job(payload: dict, daemon_url: str = "http://127.0.0.1:8741") -> str:
    """POST the job payload to the daemon. Returns job_id."""
    import urllib.request
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{daemon_url}/jobs",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    return result["job_id"]


def _poll_daemon_job(job_id: str, daemon_url: str = "http://127.0.0.1:8741",
                     poll_interval_s: float = 10.0, timeout_s: float = 7200.0) -> dict:
    """Poll daemon until job completes or fails. Returns job status dict."""
    import time
    import urllib.request
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        req = urllib.request.Request(f"{daemon_url}/jobs/{job_id}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            status = json.loads(resp.read())
        if status.get("status") in ("completed", "failed"):
            return status
        time.sleep(poll_interval_s)
    raise TimeoutError(f"Daemon job {job_id} did not complete within {timeout_s}s")


# ---------------------------------------------------------------------------
# Load checkpoint into a scoring core (tiny v0 interface)
# ---------------------------------------------------------------------------

def _load_core_from_checkpoint(ckpt_dir: str, cfg: dict, *, tiny: bool) -> Any:
    """Load a scoring core from a checkpoint.

    Returns a core object with .backbone(ids) and .head.weight.
    For tiny=True: builds a tiny v0 model and loads the state_dict.
    For tiny=False: builds the real v0 model (gated; not called in smoke).
    """
    import torch

    n_mtp = cfg["objective"]["mtp_aux_heads"]["n_heads"]
    if tiny:
        tiny_dims = {"vocab": 64, "hidden": 32, "depth": 2}
        model = _tiny_v0_model(
            tiny_dims["vocab"], tiny_dims["hidden"], n_mtp, tiny_dims["depth"]
        )
        m_state, _, _, _ = load_checkpoint(ckpt_dir)
        # Use strict=False — tiny model may have a subset of keys.
        model.load_state_dict(m_state, strict=False)
        model.eval()
        return model
    else:
        # Real c03 model — only reachable on live/GPU path (blocked in smoke).
        from timeshare_pretrain import build_v0_model
        contract = load_contract()
        model, vocab, hidden, n_mtp_real = build_v0_model(contract, live=True)
        m_state, _, _, _ = load_checkpoint(ckpt_dir)
        model.load_state_dict(m_state)
        model.eval()
        return model


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run_floor_gated_loop(
    optimizer: str,
    mixture_dir: str,
    train_ids: list[str],
    ceiling_tokens: float,
    segment_tokens: int,
    eval_every: int,
    out_receipt: str,
    backend: str,
    tiny: bool,
    core_override: Any = None,
    cfg: dict | None = None,
    daemon_url: str = "http://127.0.0.1:8741",
    run_dir: str | None = None,
) -> dict[str, Any]:
    """Run the §6-gated incremental C-BASE pretrain loop.

    Parameters
    ----------
    optimizer : str
        Optimizer variant name (the SHATTER winner — keystone-independent param).
    mixture_dir : str
        Directory containing .bin packed-shard files (40/10/50 mixture built
        at shard-write time).
    train_ids : list[str]
        Train task IDs to use for accept_cbase evaluation.
    ceiling_tokens : float
        Hard ceiling on total tokens (2.2e9 default; smoke uses tiny values).
    segment_tokens : int
        Tokens per training segment.
    eval_every : int
        Evaluate (accept_cbase + ppl probe) every this many tokens.
        If 0, evaluate every checkpoint.
    out_receipt : str
        Path to append per-checkpoint JSONL receipts.
    backend : str
        "daemon" or "inline".
    tiny : bool
        If True, use tiny CPU model (smoke mode).
    core_override : optional
        If provided, skip checkpoint loading and use this core for ALL eval.
        Used in tests to inject a stub core.
    cfg : dict, optional
        v0 pretrain config dict. Loaded from configs/v0-pretrain-config.json
        if None.
    daemon_url : str
        Daemon base URL for backend="daemon".
    run_dir : str, optional
        Directory for checkpoints. Auto-created under a tempdir if None.

    Returns
    -------
    dict with keys: decision, total_tokens, n_checkpoints, receipts_written.
    """
    if cfg is None:
        cfg = load_contract()

    # Validate train_ids (TRAIN-ONLY firewall).
    import re
    _heldout_re = re.compile(r"^h\d{3}$")
    for tid in train_ids:
        if _heldout_re.match(tid):
            raise ValueError(
                f"FIREWALL VIOLATION: heldout id {tid!r} in train_ids — "
                f"accept_cbase must only be called on train tasks."
            )

    # Set up run_dir.
    _tmpdir_obj = None
    if run_dir is None:
        _tmpdir_obj = tempfile.TemporaryDirectory(prefix="cbase_launch_")
        run_dir = _tmpdir_obj.name

    os.makedirs(run_dir, exist_ok=True)
    os.makedirs(Path(out_receipt).parent, exist_ok=True)

    # State.
    total_tokens: int = 0
    step: int = 0
    ppl_history: list[float] = []
    receipts_written: int = 0
    last_ckpt_dir: str | None = None
    decision: str = "CONTINUE"

    # Open receipt file (append mode — idempotent on crash+resume).
    receipt_fh = open(out_receipt, "a", encoding="utf-8")

    try:
        while total_tokens < ceiling_tokens:
            remaining = ceiling_tokens - total_tokens
            this_segment = min(segment_tokens, int(remaining))
            if this_segment <= 0:
                break

            # --- Train segment ---
            if backend == "inline" or tiny:
                ckpt_dir, step = _run_inline_segment(
                    run_dir=run_dir,
                    segment_tokens=this_segment,
                    optimizer=optimizer,
                    resume_ckpt_dir=last_ckpt_dir,
                    shard_dir=mixture_dir,
                    cfg=cfg,
                    tiny=tiny,
                )
            else:
                # Daemon backend.
                # Generate a self-contained per-segment wrapper script that bakes
                # all required env vars (EMBER_SHARD_DIR, EMBER_SEGMENT_TOKENS,
                # EMBER_TOTAL_STEPS, EMBER_RUN_DIR, and EMBER_RESUME_CKPT_DIR for
                # resume segments) into os.environ at module level before importing
                # cbase_v0_segment_live.  This is the only reliable env channel:
                # the daemon (server.py) passes {**os.environ, "PYTHONUNBUFFERED":"1"}
                # to subprocesses — no per-job env injection in JobConfig.
                seg_idx = max(1, total_tokens // max(this_segment, 1))
                run_id = Path(run_dir).name or "cbase-v0"
                wrapper_path = _write_segment_wrapper(
                    run_dir=run_dir,
                    seg_idx=seg_idx,
                    run_id=run_id,
                    mixture_dir=mixture_dir,
                    segment_tokens=this_segment,
                    total_steps=_total_steps,
                    resume_ckpt_dir=last_ckpt_dir,
                    scripts_dir=str(_HERE),
                )
                # Point the daemon payload at the generated wrapper instead of
                # the bare cbase_v0_segment_live.py.  The wrapper is a plain
                # Python script; the daemon exec's it via `python <script>`.
                payload = _build_daemon_job_payload(
                    run_dir=run_dir,
                    optimizer=optimizer,
                    resume_ckpt_dir=last_ckpt_dir,
                    segment_tokens=this_segment,
                    cfg=cfg,
                    mixture_dir=mixture_dir,
                )
                # Override the script field to point at the generated wrapper.
                payload["script"] = _win_to_wsl(wrapper_path)
                job_id = _submit_daemon_job(payload, daemon_url)
                status = _poll_daemon_job(job_id, daemon_url)
                if status.get("status") != "completed":
                    raise RuntimeError(
                        f"Daemon job {job_id} failed: {status.get('log_tail', '')}"
                    )
                # Locate the latest checkpoint in run_dir.
                ckpt_base = Path(run_dir) / "checkpoints"
                if not ckpt_base.exists():
                    raise RuntimeError(
                        f"No checkpoints dir after daemon job: {ckpt_base}"
                    )
                ckpt_dirs = sorted(ckpt_base.iterdir())
                if not ckpt_dirs:
                    raise RuntimeError(f"Empty checkpoints dir: {ckpt_base}")
                ckpt_dir = str(ckpt_dirs[-1])
                # Read step from manifest.
                manifest_path = Path(ckpt_dir) / "manifest.json"
                with open(manifest_path) as f:
                    manifest = json.load(f)
                step = manifest.get("step", step + this_segment)

            last_ckpt_dir = ckpt_dir

            # Count tokens.
            if tiny:
                # tiny model: batch=2, seq=16
                tokens_per_step = 2 * 16
            else:
                tokens_per_step = cfg["throughput"]["batch"] * cfg["model"]["seq"]

            # Infer steps from segment_tokens.
            seg_steps = max(1, this_segment // tokens_per_step)
            tokens_this_seg = seg_steps * tokens_per_step
            total_tokens += tokens_this_seg

            # --- Eval: accept_cbase + ppl probe ---
            # Determine the scoring core.
            if core_override is not None:
                scoring_core = core_override
            else:
                scoring_core = _load_core_from_checkpoint(ckpt_dir, cfg, tiny=tiny)

            # Run accept_cbase (imported verbatim — not reimplemented).
            try:
                accept_result = accept_cbase(
                    scoring_core,
                    train_ids,
                    n_samples=4,
                    temperature=1.0,
                    seed=42,
                )
                n_correct = accept_result["summary"]["n_correct_tasks"]
            except Exception as e:
                # Fail-safe: log and treat as 0 correct (never crash the loop).
                n_correct = 0

            # Perplexity probe on held-out tasks (NOT the train set).
            ppl = _compute_heldout_ppl(scoring_core, HELDOUT_EVAL_IDS)
            ppl_history.append(ppl)

            # floor_met condition.
            ppl_descending = _compute_floor_met(n_correct=1, ppl_history=ppl_history)
            # Full floor_met: n_correct AND ppl_descending.
            floor_met = _compute_floor_met(
                n_correct=n_correct,
                ppl_history=ppl_history,
                K=PPL_K,
            )

            # Determine decision.
            if floor_met:
                decision = "STOP"
            elif total_tokens >= ceiling_tokens:
                decision = "CEILING_STOP"
            else:
                decision = "CONTINUE"

            # Write receipt.
            rec = _make_receipt(
                tokens=total_tokens,
                step=step,
                n_correct=n_correct,
                floor_met=floor_met,
                ppl=ppl,
                ppl_descending=ppl_descending,
                decision=decision,
                extra={
                    "ckpt_dir": ckpt_dir,
                    "optimizer": optimizer,
                    "backend": backend,
                    "tiny": tiny,
                },
            )
            receipt_fh.write(json.dumps(rec) + "\n")
            receipt_fh.flush()
            receipts_written += 1

            if decision in ("STOP", "CEILING_STOP"):
                break

    finally:
        receipt_fh.close()
        if _tmpdir_obj is not None:
            # Keep run_dir alive until return (caller may read receipts).
            pass

    return {
        "decision": decision,
        "total_tokens": total_tokens,
        "n_checkpoints": receipts_written,
        "receipts_written": receipts_written,
        "out_receipt": out_receipt,
    }


# ---------------------------------------------------------------------------
# CLI argument parser
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for ember_cbase_launch."""
    parser = argparse.ArgumentParser(
        prog="ember_cbase_launch",
        description="§6-gated incremental C-BASE pretrain driver.",
    )
    parser.add_argument(
        "--optimizer",
        default="muon_split",
        help="Optimizer variant name (the SHATTER winner — keystone-independent param).",
    )
    parser.add_argument(
        "--mixture-dir",
        # 2026-07 (#77): default repointed from the small data/cbase_pretrain stub
        # (63,996 tokens) to the receipted 26-shard corpus junction.
        default=_DEFAULT_MIXTURE_DIR,
        help="Directory of .bin packed-shard files. Default: the receipted 26-shard "
             "corpus (the shards-v0 junction); pass --mixture-dir to override.",
    )
    parser.add_argument(
        "--train-ids",
        nargs="+",
        default=TRAIN_EVAL_IDS,
        help="Train task IDs for accept_cbase evaluation (default: pinned 8 IDs).",
    )
    parser.add_argument(
        "--ceiling-tokens",
        type=float,
        default=2.2e9,
        help="Hard ceiling on total tokens (default: 2.2e9). 2.2B is the ceiling, never the target.",
    )
    parser.add_argument(
        "--segment-tokens",
        type=int,
        default=50_000_000,
        help="Tokens per training segment (default: 50M).",
    )
    parser.add_argument(
        "--eval-every",
        type=int,
        default=50_000_000,
        help="Evaluate every N tokens (default: every segment).",
    )
    parser.add_argument(
        "--out-receipt",
        required=True,
        help="Path to write per-checkpoint JSONL receipts.",
    )
    parser.add_argument(
        "--backend",
        choices=["daemon", "inline"],
        default="daemon",
        help="Training backend: 'daemon' (POST to train daemon) or 'inline' (in-process).",
    )
    parser.add_argument(
        "--tiny",
        action="store_true",
        help="CPU smoke flag: tiny model, tiny shards, CUDA off.",
    )
    parser.add_argument(
        "--run-dir",
        default=None,
        help="Directory for checkpoints (auto-tempdir if not given).",
    )
    parser.add_argument(
        "--daemon-url",
        default="http://127.0.0.1:8741",
        help="Daemon base URL (for --backend daemon). Port 8741 is the real daemon port.",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)

    # Smoke mode: force CUDA off.
    if args.tiny:
        os.environ["CUDA_VISIBLE_DEVICES"] = ""

    result = run_floor_gated_loop(
        optimizer=args.optimizer,
        mixture_dir=args.mixture_dir,
        train_ids=args.train_ids,
        ceiling_tokens=args.ceiling_tokens,
        segment_tokens=args.segment_tokens,
        eval_every=args.eval_every,
        out_receipt=args.out_receipt,
        backend=args.backend,
        tiny=args.tiny,
        run_dir=args.run_dir,
        daemon_url=args.daemon_url,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
