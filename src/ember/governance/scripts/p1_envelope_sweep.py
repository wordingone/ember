# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""p1_envelope_sweep.py -- P1 envelope-sweep point runner (issue #118).

Executes ONE sweep point (--point k in [3..8]) of the frozen run protocol in
docs/domains/governance/spec/p1-envelope-sweep-prereg-v1.md section 2: a from-scratch c03-shape
training run at a token budget derived from E0, scored by held-out val loss
at the FINAL step of the budget (never mid-run / never early-stopped).

REUSE, NEVER REIMPLEMENT (per this lane's frozen build spec): the actual
governed, from-scratch, real-GPU training loop this script drives is
src/ember/governance/scripts/w1_collapse_control_run.py:run_phase2_live -- the SAME matched-recipe
machinery (c03-shape RealW1Model, muon-split+AdamW+MTP-aux optimizer via
build_split_optimizer, cosine-to-10%-of-peak schedule via
apply_cosine_warmup/cosine_warmup_frac, governor preflight via
timeshare_pretrain._apply_governor(), atomic checkpointing, decontam-gated
held-out eval via w2_heldout/launch_gate.py) already used to produce the
REAL, banked W1 control point:
  receipts/ember-c-scale/w1-collapse-control-20260707T110256Z.json
Early-stopping is disabled by passing target_eval_loss=float("-inf") (never
<= any real loss, so run_phase2_live's own early-stop gate never fires) --
this is the one deliberate difference from that script's own CLI use, and it
is what makes "scoring at the FINAL step" (prereg sec.2) hold: the run always
trains the full computed step budget and the receipt reads eval_trace[-1].

This script deliberately does NOT touch EMBER_W1_MAINTAINER_WINDOW_CONFIRMED
-- that is a SEPARATE, W1-comparison-specific ritual gate scoped to
w1_collapse_control_run.py's own protected grow-vs-control CLI entrypoint
(its own comment: "set ONLY by the maintainer's actual GPU-launch runbook,
NEVER by this builder, NEVER in a test"). This script imports only the
constituent, already-governed FUNCTIONS from that module -- never its CLI
main()/main_live() dual-key entrypoint -- and defines its own, narrower
interlock: EMBER_GATE_AUTHORIZED=1 (the general repo-wide real-GPU-launch
key, per timeshare_pretrain.py's own docstring) AND absence of --dry-run.

DISCLOSED DESIGN DECISIONS / CONFLICTS (reported to the coordinator, never
silently resolved -- prereg-vs-spec conflicts are supposed to be reported;
these are prereg-internal gaps/inconsistencies this lane hit while making
section 2 executable). Items 1 and 3 below were RULED on by the coordinator
2026-07-08 and are recorded as docs/domains/governance/ledgers/deviations.md DEV-003 (a pre-first-
-launch, clerical+operational, non-threshold-relaxing amendment to the
frozen prereg); this docstring keeps the original finding for context and
notes each ruling inline.

1. POINT-NUMBERING (prereg section 1 table vs section 4 H-MLI assignment).
   Section 1's inventory table lists six sweep values, in order, for points
   3-8: "0.1x, 0.2x, 0.5x, 1.0x(replicate), 2.0x, 4.0x". Read positionally
   (point3=0.1x ... point8=4.0x) this is CONSISTENT with section 3 ("point 8
   (4.0x) is the HOLDOUT") and with this lane's own frozen spec, which
   restates "points 3-8 at 0.1/0.2/0.5/1.0/2.0/4.0x" in the same order.
   Section 4, however, states "points 4 (1.0x) and 6 (1.0x replicate) ARE
   the two control replicates" for the H-MLI lever-arm design -- which
   requires TWO 1.0x-valued points (4 and 6), impossible under the six-value
   list above (only one 1.0x entry exists for six points).
   RULED (DEV-003): section 4's indices are clerical errors; the
   authoritative intent is the section 1 table's "1.0x(replicate)" label.
   The H-MLI trio is {row 1 W1 control (1.0x), the sweep's own 1.0x
   replicate = point 6 (fresh seed), one lever-arm 1.0x run WITH L1} --
   "points 4 and 6" is void as numbering. POINT_MULTIPLIERS below already
   matched this reading (point6=1.0x replicate); no code change needed.

2. E0-TO-TOKEN-BUDGET CONVERSION. The prereg states E0 in gpu-hours only
   ("the W1 control's measured e_gpu_hours (0.067478 gpu-h)"), with no
   receipt anywhere in this repo carrying a literal e_gpu_hours=0.067478
   field (grepped scripts/docs/receipts repo-wide, excluding worktrees --
   zero hits outside the prereg doc itself) and no operational formula for
   turning "0.1x E0" into a step count for a NEW from-scratch run. This
   script's resolution: REFERENCE_THROUGHPUT_TOK_S is measured from the
   ONLY real receipt on record for this exact matched recipe (muon_split +
   MTP aux, governor pacing 0.80) on this pinned RTX4090 -- the banked W1
   control-arm's own real run (receipts/ember-c-scale/w1-collapse-control-
   20260707T110256Z.json: control_arm.tokens_to_match=819200 tokens /
   control_arm.wall_s=126.484s). tokens(point) = multiplier * E0_GPU_HOURS *
   3600 * REFERENCE_THROUGHPUT_TOK_S; steps = round(tokens / (batch*seq)).
   Sanity check: for point 3 this derivation lands at ~24.3s of intended GPU
   time before overhead -- matching this lane's own frozen spec's stated
   "0.1xE0 ~ 24s GPU" almost exactly, which is the strongest evidence this
   reading is the one the spec author had in mind.

3. WARMUP RULE. Prereg section 2: "warmup = min(2% of budget, the c03
   recipe's absolute warmup)". Grepped the whole repo (scripts/docs/
   receipts, excluding worktrees/fixtures) for "warmup_steps" -- ZERO hits.
   No "c03 recipe's absolute warmup" step-count constant exists anywhere.
   This script computes intended_warmup = min(round(2%*budget), 153) (153 =
   the only concrete number on record -- the banked W1 control's own 10%-
   of-1533-step warmup, expressed as an absolute step count).
   RULED (DEV-003): implement the prereg's rule properly rather than
   disclose-and-diverge. src/ember/governance/scripts/w1_collapse_control_run.py's
   cosine_warmup_frac/apply_cosine_warmup/run_phase2_live now accept an
   OPTIONAL warmup_steps override (default None, byte-identical prior
   behavior for every other caller -- additive reuse, not a fork; see their
   docstrings). This script passes warmup_steps=intended_warmup, so the
   prereg-intended figure and the actually-applied one are now IDENTICAL
   by construction -- both still quoted side by side in the receipt
   (lr_schedule.prereg_intended_warmup_steps vs
   lr_schedule.effective_warmup_steps) so the equality is verifiable from
   the receipt alone, never asserted without evidence.

4. FF WIDTH. w1_collapse_control_run.py's real_arch["ff_grown"] normally
   means the W1 GROW-ARM's widened target FF (16384) -- irrelevant here,
   since points 3-8 are pure from-scratch runs with no grow-arm to match.
   This script uses FF_NATIVE_C03=4096, the c03 recipe's OWN un-grown
   native width (cited directly from RealW1Model's own docstring: "the
   un-grown seed FF width" / run_phase2_live's docstring: "build_v0_model's
   ... intermediate_size is hardcoded to 4096").

Usage:
  CPU mechanics/schema smoke test (no GPU, no corpus, no decontam gate):
    python src/ember/governance/scripts/p1_envelope_sweep.py --point 3 --dry-run

  Real GPU gate probe (requires EMBER_GATE_AUTHORIZED=1 and a real
  --shard-dir; the shard directory is NEVER hardcoded in this file --
  repo-guard scrubs absolute local paths / founder-name path fragments from
  anything committed):
    EMBER_GATE_AUTHORIZED=1 python src/ember/governance/scripts/p1_envelope_sweep.py --point 3 \\
        --shard-dir <local real corpus shard dir>

Receipts: receipts/p1-envelope-sweep/<UTC>-point<k>.json (live),
scratch/p1-envelope-sweep-dryrun/<UTC>-point<k>-dryrun.json (--dry-run).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from receipt_write import checked_write  # reused, not reimplemented
import joules  # reused, not reimplemented
import w1_collapse_control_run as w1c  # reused, not reimplemented
# 2026-07-08: this lane previously swapped in w2_heldout.build_decontam_
# batch_mp's adaptive-chunked contamination_recheck wrapper here, after an
# ArrayMemoryError on the raw serial w1c.contamination_recheck's np.unique
# call. REVERTED (coordinator ruling) now that #451 folded the same
# chunk-halving guard directly into w1c.contamination_recheck itself (issue
# #445), PLUS this lane's own follow-up memmap fix for the per-shard
# np.fromfile read #451 didn't cover -- the wrapper is now a redundant
# extra layer over an already-hardened function; calling w1c's own
# contamination_recheck directly is one fewer indirection for the same
# safety guarantee.

# ---------------------------------------------------------------------------
# Point table (prereg section 1). See module docstring item 1 for the
# disclosed point-numbering conflict this table does NOT resolve.
# ---------------------------------------------------------------------------
POINT_MULTIPLIERS = {3: 0.1, 4: 0.2, 5: 0.5, 6: 1.0, 7: 2.0, 8: 4.0}
HOLDOUT_POINT = 8  # prereg section 3

E0_GPU_HOURS = 0.067478
E0_SOURCE = "docs/domains/governance/spec/p1-envelope-sweep-prereg-v1.md section 5"

REFERENCE_THROUGHPUT_RECEIPT = (
    "receipts/ember-c-scale/w1-collapse-control-20260707T110256Z.json")
REFERENCE_THROUGHPUT_TOKENS = 819200        # control_arm.tokens_to_match
REFERENCE_THROUGHPUT_WALL_S = 126.484       # control_arm.wall_s
REFERENCE_THROUGHPUT_TOK_S = REFERENCE_THROUGHPUT_TOKENS / REFERENCE_THROUGHPUT_WALL_S

BATCH = 16
SEQ = 1024
TOKENS_PER_STEP = BATCH * SEQ
VOCAB = 32000
LAYERS = 20
HEADS = 16
FF_NATIVE_C03 = 4096  # see module docstring item 4

# The W1 control's OWN real receipt's warmup fraction (10% of its 1533-step
# ceiling), expressed as an absolute step count -- see module docstring item 3.
ABSOLUTE_WARMUP_STEPS_CAP = round(0.1 * w1c.REAL_HARD_CEILING_STEPS_ISSUE_STATED)

DECONTAM_RECEIPT_DEFAULT = os.path.join(
    REPO, "receipts", "ember-c-scale", "w2-heldout-decontam-20260708T121128Z.json")
# 2026-07-08: the prior default (...-20260707T055843Z.json) named a receipt
# that was NEVER found in this repo's history (issue #435, the custody
# defect this lane's decontam regen exists to cure) -- pointing the default
# at a file that never existed was itself a latent defect. Updated to the
# regenerated, true-continuity receipt (exact selected_window_indices match
# to the banked W1 control receipt, verified 2026-07-08).

# Corpus memmap cache (issue #118, coordinator ruling 2026-07-08): repo-
# relative default so no absolute path ever lands in source (repo-guard);
# EMBER_CORPUS_CACHE_DIR overrides it at launch time to point every
# consumer (any worktree, any lane) at ONE shared cache instead of each
# worktree building its own 13GB copy -- same env-var-override convention
# as w2_heldout/build_decontam_batch_mp.py's EMBER_SHARD_DIR.
CORPUS_CACHE_DIR = os.environ.get(
    "EMBER_CORPUS_CACHE_DIR", os.path.join(REPO, "scratch", "corpus-cache"))

RAM_FLOOR_GIB = 15.0     # coordinator-narrowed rule-m RAM preflight
VRAM_MARGIN_GIB = 2.0    # frozen spec section "Preflight"

LOCK_DIR = os.path.join(REPO, "scratch", "p1-envelope-sweep-locks")
LOCK_PATH = os.path.join(LOCK_DIR, "sweep.lock")


def steps_for_point(point: int) -> dict:
    if point not in POINT_MULTIPLIERS:
        raise SystemExit(
            f"P1_SWEEP_BAD_POINT: point={point} not in {sorted(POINT_MULTIPLIERS)}")
    mult = POINT_MULTIPLIERS[point]
    target_gpu_hours = mult * E0_GPU_HOURS
    target_tokens = target_gpu_hours * 3600.0 * REFERENCE_THROUGHPUT_TOK_S
    steps = max(1, round(target_tokens / TOKENS_PER_STEP))
    return {
        "point": point,
        "multiplier": mult,
        "e0_gpu_hours": E0_GPU_HOURS,
        "e0_source": E0_SOURCE,
        "target_gpu_hours": target_gpu_hours,
        "target_gpu_hours_note": "intended wall-clock training budget before overhead",
        "reference_throughput_tok_s": REFERENCE_THROUGHPUT_TOK_S,
        "reference_throughput_source": REFERENCE_THROUGHPUT_RECEIPT,
        "target_tokens": target_tokens,
        "tokens_per_step": TOKENS_PER_STEP,
        "steps": steps,
        "derivation": (
            f"steps = round(multiplier({mult}) * E0_GPU_HOURS({E0_GPU_HOURS}) * 3600 * "
            f"REFERENCE_THROUGHPUT_TOK_S({REFERENCE_THROUGHPUT_TOK_S:.4f}) / "
            f"TOKENS_PER_STEP({TOKENS_PER_STEP})); disclosed derivation, see module "
            "docstring item 2 -- the prereg states E0 in gpu-hours only, with no "
            "operational token/step formula on record."),
    }


def intended_warmup_steps(budget_steps: int) -> int:
    """Prereg-intended warmup (section 2); see module docstring item 3 for
    why this is NOT what actually applies in a live run via run_phase2_live."""
    return max(1, min(round(0.02 * budget_steps), ABSOLUTE_WARMUP_STEPS_CAP))


# ---------------------------------------------------------------------------
# Preflight (frozen spec section "Preflight" + coordinator's rule-m note).
# ---------------------------------------------------------------------------

def preflight_ram(floor_gib: float = RAM_FLOOR_GIB) -> dict:
    out = subprocess.run(
        ["wmic", "OS", "get", "FreePhysicalMemory", "/format:list"],
        capture_output=True, text=True, timeout=10)
    free_kb = None
    for line in out.stdout.splitlines():
        line = line.strip()
        if line.startswith("FreePhysicalMemory="):
            free_kb = int(line.split("=", 1)[1])
    if free_kb is None:
        raise SystemExit(
            "P1_SWEEP_RAM_PREFLIGHT_FAIL: could not read FreePhysicalMemory via wmic "
            f"(stdout={out.stdout!r} stderr={out.stderr!r})")
    free_gib = free_kb / (1024.0 * 1024.0)
    result = {"free_ram_gib": round(free_gib, 2), "floor_gib": floor_gib}
    if free_gib < floor_gib:
        raise SystemExit(
            f"P1_SWEEP_RAM_PREFLIGHT_REFUSE: free_ram_gib={free_gib:.2f} < "
            f"floor={floor_gib} -- refusing launch, no fix-forward "
            "(coordinator's rule-m RAM preflight).")
    result["pass"] = True
    return result


def preflight_vram(margin_gib: float = VRAM_MARGIN_GIB) -> dict:
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.free,memory.total",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=10)
    if out.returncode != 0:
        raise SystemExit(
            f"P1_SWEEP_VRAM_PREFLIGHT_FAIL: nvidia-smi rc={out.returncode} "
            f"stderr={out.stderr!r}")
    free_mib, total_mib = (float(x) for x in out.stdout.strip().split(","))
    free_gib = free_mib / 1024.0
    total_gib = total_mib / 1024.0
    result = {"free_vram_gib": round(free_gib, 2), "total_vram_gib": round(total_gib, 2),
              "margin_gib": margin_gib}
    if free_gib < margin_gib:
        raise SystemExit(
            f"P1_SWEEP_VRAM_PREFLIGHT_REFUSE: free_vram_gib={free_gib:.2f} < "
            f"margin={margin_gib} -- refusing launch, no fix-forward.")
    result["pass"] = True
    return result


def acquire_sweep_lock() -> str:
    """One governed GPU job at a time (prereg section 2). Orphan sweep:
    if the lock is held by a PID that is no longer alive, reclaim it rather
    than refusing forever."""
    os.makedirs(LOCK_DIR, exist_ok=True)
    if os.path.exists(LOCK_PATH):
        with open(LOCK_PATH, "r", encoding="utf-8") as f:
            held = f.read().strip()
        held_pid = None
        try:
            held_pid = int(held.split()[0])
        except (ValueError, IndexError):
            pass
        alive = False
        if held_pid is not None:
            check = subprocess.run(
                ["tasklist", "/FI", f"PID eq {held_pid}"],
                capture_output=True, text=True, timeout=10)
            alive = str(held_pid) in check.stdout
        if alive:
            raise SystemExit(
                f"P1_SWEEP_ANOTHER_JOB_LIVE: {LOCK_PATH!r} held by live pid={held_pid} "
                "-- refusing (one governed GPU job at a time, prereg section 2).")
        # else: stale lock (orphan), PID dead -- reclaim below.
    with open(LOCK_PATH, "w", encoding="utf-8") as f:
        f.write(f"{os.getpid()} {datetime.now(timezone.utc).isoformat()}")
    return LOCK_PATH


def release_sweep_lock() -> None:
    try:
        os.remove(LOCK_PATH)
    except FileNotFoundError:
        pass


def adm_fingerprint(real_arch: dict, corpus_manifest: dict, gpu_name: str) -> str:
    payload = {
        "vocab": real_arch["vocab"], "hidden": real_arch["hidden"],
        "layers": real_arch["layers_assumed"], "heads": real_arch["heads_assumed"],
        "ff": real_arch["ff_grown"], "seq": real_arch["seq"], "batch": real_arch["batch"],
        "n_mtp": real_arch["n_mtp"],
        "corpus_manifest_sha256": corpus_manifest.get("combined_sha256"),
        "gpu": gpu_name,
    }
    return w1c.sha256_hex(json.dumps(payload, sort_keys=True).encode("utf-8"))


# ---------------------------------------------------------------------------
# Dry-run path -- CPU-only mechanics/schema smoke test. Never touches CUDA,
# the real corpus, or the decontam gate. Same honesty convention as
# w1_collapse_control_run.py's own --dry-run (toy stand-in, honestly labeled).
# ---------------------------------------------------------------------------

def run_point_dry(args: argparse.Namespace, point_info: dict, ts: str,
                   out_dir: str, intended_warmup: int) -> dict:
    import torch

    budget_steps = point_info["steps"]
    cfg = w1c.arch_config_dict(vocab=64, hidden=8, depth=2, seq=8, batch=2)
    model = w1c.build_model(cfg, seed=args.seed, device="cpu")
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.01)
    corpus = w1c.synthetic_corpus(
        cfg["vocab"], cfg["seq"], n_windows=max(budget_steps * cfg["batch"] * 3, 32), seed=99)
    eval_x, eval_y, eval_sha = w1c.make_eval_batch(cfg["vocab"], cfg["batch"], cfg["seq"], "cpu")

    lr_trace = []
    t0 = time.perf_counter()
    for step in range(budget_steps):
        x, y = w1c.batch_from_corpus(corpus, step, cfg["batch"], "cpu")
        lr = w1c.cosine_warmup_lr(step, budget_steps, base_lr=0.01,
                                   warmup_frac=0.1, min_lr_frac=0.1)
        for g in optimizer.param_groups:
            g["lr"] = lr
        lr_trace.append(round(lr, 8))
        w1c.train_step(model, optimizer, x, y)
    wall_s = time.perf_counter() - t0
    final_el = w1c.eval_loss_fn(model, eval_x, eval_y)

    receipt = {
        "ticket": "P1-ENVELOPE-SWEEP",
        "ts": ts,
        "issue": "#118",
        "schema": "p1-envelope-sweep-point/v1",
        "prereg_ref": "docs/domains/governance/spec/p1-envelope-sweep-prereg-v1.md",
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
        "dry_run": True,
        "point": args.point,
        "multiplier": point_info["multiplier"],
        "budget_derivation": point_info,
        "prereg_intended_warmup_steps": intended_warmup,
        "adm_fingerprint": None,
        "c_functional_id": "neg_val_loss_v1",
        "e_gpu_hours": None,
        "lever_class": "none",
        "claim_type": "envelope-point",
        "power": {"power_qualifier": "unqualified",
                  "note": "dry-run: no GPU, joules.py not sampled"},
        "lr_schedule": {"warmup_frac": 0.1, "min_lr_frac": 0.1,
                        "lr_trace_first": lr_trace[0] if lr_trace else None,
                        "lr_trace_last": lr_trace[-1] if lr_trace else None},
        "steps_run": budget_steps,
        "final_eval_loss": final_el,
        "c_functional_value": -final_el,
        "eval_batch_sha256": eval_sha,
        "wall_s": round(wall_s, 3),
        "note": ("toy CPU stand-in (2-block linear model, synthetic Zipf corpus -- "
                 "same honesty convention as w1_collapse_control_run.py's own "
                 "--dry-run), proves this script's schedule/orchestration/receipt-"
                 "assembly mechanics only; carries no physical meaning; never "
                 "touches the real corpus, GPU, governor, or decontam gate."),
    }
    receipts_dir = os.path.join(REPO, "scratch", "p1-envelope-sweep-dryrun")
    os.makedirs(receipts_dir, exist_ok=True)
    out_path = os.path.join(receipts_dir, f"{ts}-point{args.point}-dryrun.json")
    checked_write(out_path, receipt)
    receipt["_receipt_path"] = out_path
    return receipt


# ---------------------------------------------------------------------------
# Live path -- real GPU, real corpus, real decontam gate, real governor.
# ---------------------------------------------------------------------------

def run_point_live(args: argparse.Namespace, point_info: dict, ts: str,
                    out_dir: str, intended_warmup: int) -> dict:
    if not args.shard_dir:
        raise SystemExit(
            "P1_SWEEP_NO_SHARD_DIR: --shard-dir is required for a live run "
            "(never hardcoded in this file -- repo-guard scrubs absolute "
            "local paths / founder-name fragments from anything committed).")

    ram_receipt = preflight_ram()
    vram_receipt = preflight_vram()
    acquire_sweep_lock()
    try:
        os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")
        import torch
        gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "unknown"

        budget_steps = point_info["steps"]
        eval_every = args.eval_every or budget_steps
        checkpoint_every = args.checkpoint_every or eval_every

        shard_manifest = w1c.verify_shard_corpus(
            args.shard_dir, expected_combined_sha256=args.corpus_manifest_sha256)

        n_mtp = w1c.load_json(w1c.PRETRAIN_CONTRACT_PATH)["objective"]["mtp_aux_heads"]["n_heads"]
        real_arch = {
            "vocab": VOCAB, "seq": SEQ, "batch": BATCH, "hidden": 1024, "n_mtp": n_mtp,
            "ff_grown": FF_NATIVE_C03, "layers_assumed": LAYERS, "heads_assumed": HEADS,
        }

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
        PackedShardLoader = getattr(_ember_d9c5c82c124e1dc8_module, 'PackedShardLoader')
        verify_memmap_stream_equivalence = getattr(_ember_d9c5c82c124e1dc8_module, 'verify_memmap_stream_equivalence')
        # issue2015 exact-local-import-end:src/ember/governance/scripts/timeshare_pretrain.py
        loader = PackedShardLoader(
            args.shard_dir, real_arch["seq"], n_mtp=n_mtp,
            mmap_cache_dir=CORPUS_CACHE_DIR,
            expected_manifest_sha256=w1c.CORPUS_MANIFEST_COMBINED_SHA256_EXPECTED)
        equivalence_report = verify_memmap_stream_equivalence(
            loader.stream, args.shard_dir, loader.shards)

        decontam_receipt = w1c.load_json(args.decontam_receipt)
        candidate_window_indices = decontam_receipt.get("selected_window_indices") or []
        this_run_disjoint_check = w1c.assert_disjoint_from_training(
            min(candidate_window_indices) if candidate_window_indices else 0,
            budget_steps, real_arch["batch"])

        eval_x, eval_y, eval_sha = w1c.rebuild_batch_from_decontam_receipt(
            loader, decontam_receipt, "cuda")
        xs = [eval_x[i].to("cpu").numpy() for i in range(eval_x.shape[0])]
        ys = [eval_y[i].to("cpu").numpy() for i in range(eval_y.shape[0])]
        launch_gate_result = w1c.wire_launch_gate_check(
            xs, ys, seq=real_arch["seq"], receipt_path=args.decontam_receipt,
            out_dir=out_dir, ts=ts)

        eval_rows = [list(x_np) + [int(y_np[-1])] for x_np, y_np in zip(xs, ys)]
        cache_root = os.path.join(REPO, "scratch", "w1-control", "recheck-cache")
        # issue2015 exact-local-import:src/ember/governance/scripts/w1_recheck_cache.py
        import importlib.util as _ember_fabaa435f8739f48_importlib
        import sys as _ember_fabaa435f8739f48_sys
        from pathlib import Path as _ember_fabaa435f8739f48_Path
        _ember_fabaa435f8739f48_path = _ember_fabaa435f8739f48_Path(__file__).resolve().parent.joinpath('w1_recheck_cache.py')
        if not _ember_fabaa435f8739f48_path.is_file():
            raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/w1_recheck_cache.py')
        _ember_fabaa435f8739f48_aliases = ('_ember_issue2015_fabaa435f8739f48', 'src.ember.governance.scripts.w1_recheck_cache', 'w1_recheck_cache')
        _ember_fabaa435f8739f48_existing = []
        for _ember_fabaa435f8739f48_alias in _ember_fabaa435f8739f48_aliases:
            _ember_fabaa435f8739f48_candidate = _ember_fabaa435f8739f48_sys.modules.get(_ember_fabaa435f8739f48_alias)
            if _ember_fabaa435f8739f48_candidate is not None and all(_ember_fabaa435f8739f48_candidate is not item for item in _ember_fabaa435f8739f48_existing):
                _ember_fabaa435f8739f48_existing.append(_ember_fabaa435f8739f48_candidate)
        if len(_ember_fabaa435f8739f48_existing) > 1:
            raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/w1_recheck_cache.py')
        if _ember_fabaa435f8739f48_existing:
            _ember_fabaa435f8739f48_module = _ember_fabaa435f8739f48_existing[0]
            _ember_fabaa435f8739f48_observed = getattr(_ember_fabaa435f8739f48_module, '__file__', None)
            if _ember_fabaa435f8739f48_observed is None or _ember_fabaa435f8739f48_Path(_ember_fabaa435f8739f48_observed).resolve() != _ember_fabaa435f8739f48_path:
                raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/w1_recheck_cache.py')
        else:
            _ember_fabaa435f8739f48_spec = _ember_fabaa435f8739f48_importlib.spec_from_file_location('_ember_issue2015_fabaa435f8739f48', _ember_fabaa435f8739f48_path)
            if _ember_fabaa435f8739f48_spec is None or _ember_fabaa435f8739f48_spec.loader is None:
                raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/w1_recheck_cache.py')
            _ember_fabaa435f8739f48_module = _ember_fabaa435f8739f48_importlib.module_from_spec(_ember_fabaa435f8739f48_spec)
            for _ember_fabaa435f8739f48_alias in _ember_fabaa435f8739f48_aliases:
                _ember_fabaa435f8739f48_prior = _ember_fabaa435f8739f48_sys.modules.get(_ember_fabaa435f8739f48_alias)
                if _ember_fabaa435f8739f48_prior is not None and _ember_fabaa435f8739f48_prior is not _ember_fabaa435f8739f48_module:
                    raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/w1_recheck_cache.py')
                _ember_fabaa435f8739f48_sys.modules[_ember_fabaa435f8739f48_alias] = _ember_fabaa435f8739f48_module
            try:
                _ember_fabaa435f8739f48_spec.loader.exec_module(_ember_fabaa435f8739f48_module)
            except BaseException:
                for _ember_fabaa435f8739f48_alias in _ember_fabaa435f8739f48_aliases:
                    if _ember_fabaa435f8739f48_sys.modules.get(_ember_fabaa435f8739f48_alias) is _ember_fabaa435f8739f48_module:
                        _ember_fabaa435f8739f48_sys.modules.pop(_ember_fabaa435f8739f48_alias, None)
                raise
        for _ember_fabaa435f8739f48_alias in _ember_fabaa435f8739f48_aliases:
            _ember_fabaa435f8739f48_prior = _ember_fabaa435f8739f48_sys.modules.get(_ember_fabaa435f8739f48_alias)
            if _ember_fabaa435f8739f48_prior is not None and _ember_fabaa435f8739f48_prior is not _ember_fabaa435f8739f48_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/w1_recheck_cache.py')
            _ember_fabaa435f8739f48_sys.modules[_ember_fabaa435f8739f48_alias] = _ember_fabaa435f8739f48_module
        check_recheck_cache = getattr(_ember_fabaa435f8739f48_module, 'check_recheck_cache')
        write_recheck_cache = getattr(_ember_fabaa435f8739f48_module, 'write_recheck_cache')
        # issue2015 exact-local-import-end:src/ember/governance/scripts/w1_recheck_cache.py
        contamination = check_recheck_cache(
            eval_rows, args.shard_dir, args.decontam_receipt, cache_root,
            classifier_code_path=os.path.join(HERE, "w1_collapse_control_run.py"))
        if not contamination:
            contamination = w1c.contamination_recheck(
                eval_rows, args.shard_dir,
                window=w1c.CONTAMINATION_WINDOW_TOKENS,
                roll_base=w1c.CONTAMINATION_ROLL_BASE)
            contamination["recheck_implementation"] = (
                "w1_collapse_control_run.contamination_recheck direct call "
                "(reverted from the w2_heldout.build_decontam_batch_mp "
                "adaptive-chunked wrapper this lane used earlier the same "
                "day, 2026-07-08 -- #451 folded the same chunk-halving "
                "MemoryError guard directly into this function [issue #445], "
                "and this lane's own follow-up fix replaced the per-shard "
                "np.fromfile whole-shard read with np.memmap(mode='r') after "
                "a 512MiB ArrayMemoryError at 28.7GB free RAM survived #451 "
                "-- the wrapper is now redundant, direct call kept)")
            write_recheck_cache(
                contamination, eval_rows, args.decontam_receipt, cache_root,
                classifier_code_path=os.path.join(HERE, "w1_collapse_control_run.py"))
        contamination_classified = w1c.classify_contamination_self_matches(
            contamination, candidate_window_indices, seq=real_arch["seq"],
            n_mtp=n_mtp, shard_dir=args.shard_dir)

        # Cross-instrument agreement check (coordinator condition, 2026-07-08
        # chunked-wrapper swap): this run's OWN fresh recheck must agree with
        # the decontam receipt's own recorded verdict on the SAME batch -- a
        # disagreement means the serial and chunked implementations disagree
        # on the same predicate, which is an instrument defect, not a normal
        # refusal, and stops the run immediately rather than proceeding.
        this_run_confirmed_non_self = len(
            contamination_classified.get("confirmed_non_self_matches", []))
        receipt_recorded_non_self = (
            decontam_receipt.get("contamination_recheck", {})
            .get("confirmed_non_self_matches"))
        if (receipt_recorded_non_self is not None
                and this_run_confirmed_non_self != receipt_recorded_non_self):
            raise SystemExit(
                "P1_SWEEP_RECHECK_INSTRUMENT_DISAGREEMENT: this run's fresh "
                f"contamination recheck found confirmed_non_self_matches="
                f"{this_run_confirmed_non_self}, but the decontam receipt "
                f"{args.decontam_receipt} recorded "
                f"confirmed_non_self_matches={receipt_recorded_non_self} for "
                "the SAME batch -- the two instruments disagree on the same "
                "predicate. Refusing to proceed; this is an instrument "
                "defect finding, not a normal contamination refusal.")

        fake_args = argparse.Namespace(
            decontam_receipt=args.decontam_receipt, shard_dir=args.shard_dir,
            live_ceiling_steps=budget_steps, live_eval_every=eval_every,
            live_checkpoint_every=checkpoint_every)
        w1c.refuse_if_non_self_contaminated(
            contamination_classified, contamination=contamination,
            candidate_window_indices=candidate_window_indices, args=fake_args,
            out_dir=out_dir, ts=ts, real_arch=real_arch,
            disjoint_check={"this_run_disjoint_check": this_run_disjoint_check},
            eval_batch_sha=eval_sha)

        cfg_real = w1c.real_config_dict(real_arch)

        power_samples = []
        stop_evt = threading.Event()

        def _sampler():
            try:
                for s in joules.sample_power_nvidia_smi(interval_s=1.0):
                    power_samples.append(s)
                    if stop_evt.is_set():
                        break
            except RuntimeError:
                pass

        sampler_thread = threading.Thread(target=_sampler, daemon=True)
        sampler_thread.start()

        t0 = time.perf_counter()
        phase2 = w1c.run_phase2_live(
            cfg_real, real_arch, ceiling_steps=budget_steps, eval_every=eval_every,
            checkpoint_every=checkpoint_every, target_eval_loss=float("-inf"),
            seed=args.seed, device="cuda", out_dir=os.path.join(out_dir, "phase2-live"),
            shard_dir=args.shard_dir, eval_x=eval_x, eval_y=eval_y, loader=loader,
            rung_receipt=None, progress_path=os.path.join(out_dir, f"progress-{ts}.jsonl"),
            continue_from=None, warmup_steps=intended_warmup)
        wall_s_measured = time.perf_counter() - t0
        stop_evt.set()
        sampler_thread.join(timeout=3.0)

        if len(power_samples) >= 2:
            integration = joules.trapezoidal_integrate(power_samples)
            power_qualifier = "measured"
        else:
            integration = {"joules_total": None, "mean_watts": None, "peak_watts": None,
                           "wall_clock_s": wall_s_measured, "samples_n": len(power_samples),
                           "interval_s": None}
            power_qualifier = "unqualified"  # too short for >=2 samples at 1Hz; never fabricated

        eval_trace = phase2.get("eval_trace") or []
        final_eval = eval_trace[-1] if eval_trace else None
        initial_eval = eval_trace[0] if eval_trace else None
        c_functional = -final_eval["eval_loss"] if final_eval else None
        e_gpu_hours = wall_s_measured / 3600.0
        fp = adm_fingerprint(real_arch, shard_manifest, gpu_name)

        diverged = (final_eval["eval_loss"] > initial_eval["eval_loss"]
                    if (final_eval and initial_eval) else None)

        receipt = {
            "ticket": "P1-ENVELOPE-SWEEP",
            "ts": ts,
            "issue": "#118",
            "schema": "p1-envelope-sweep-point/v1",
            "prereg_ref": "docs/domains/governance/spec/p1-envelope-sweep-prereg-v1.md",
            "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
            "dry_run": False,
            "point": args.point,
            "multiplier": point_info["multiplier"],
            "budget_derivation": point_info,
            "adm_fingerprint": fp,
            "c_functional_id": "neg_val_loss_v1",
            "e_gpu_hours": round(e_gpu_hours, 8),
            "lever_class": "none",
            "claim_type": "envelope-point",
            "power": {**integration, "power_qualifier": power_qualifier},
            "gpu": gpu_name,
            "governor_preflight": {"ram": ram_receipt, "vram": vram_receipt},
            "corpus_manifest_sha256": shard_manifest.get("combined_sha256"),
            "corpus_manifest_ref": "src/ember/governance/scripts/manifest_sha.py",
            "corpus_loader": loader.mmap_cache_report,
            "corpus_loader_equivalence_check": equivalence_report,
            "held_out_batch": {
                "decontam_receipt_path": args.decontam_receipt,
                "selected_window_indices": candidate_window_indices,
                "launch_gate_result": launch_gate_result,
                "this_run_disjoint_check": this_run_disjoint_check,
                "eval_batch_sha256": eval_sha,
            },
            "contamination_recheck": contamination,
            "contamination_recheck_self_exclusion": contamination_classified,
            "contamination_recheck_confirmed_non_self_matches": len(
                contamination_classified.get("confirmed_non_self_matches", [])),
            "lr_schedule": {
                **phase2["lr_schedule"],
                "prereg_intended_warmup_steps": intended_warmup,
                "prereg_intended_warmup_rule": "min(2% of budget, c03 recipe absolute warmup cap)",
                "warmup_resolution": (
                    "RESOLVED (docs/domains/governance/ledgers/deviations.md DEV-003, ruling d): run_phase2_live "
                    "now accepts an additive warmup_steps override (default None, "
                    "unchanged for every other caller); this run passes "
                    "warmup_steps=intended_warmup explicitly, so the prereg-intended "
                    "figure above and phase2.lr_schedule.effective_warmup_steps must "
                    "be IDENTICAL -- no longer a disclosed conflict, previously "
                    "10% of budget_steps before this fix."),
            },
            "optimizer": phase2["optimizer"],
            "steps_run": phase2["steps_run"],
            "ceiling_steps": phase2["ceiling_steps"],
            "eval_trace": eval_trace,
            "final_eval_loss": final_eval["eval_loss"] if final_eval else None,
            "c_functional_value": c_functional,
            "wall_s": round(wall_s_measured, 3),
            "resume_proof": phase2["resume_proof"],
            "governor": phase2["governor"],
            "pacing": phase2["pacing"],
            "divergence_check": {
                "initial_loss": initial_eval["eval_loss"] if initial_eval else None,
                "final_loss": final_eval["eval_loss"] if final_eval else None,
                "diverged": diverged,
                "rule": ("diverged = final_loss > initial_loss (prereg section 2); a "
                         "diverged point is KEPT in the table and excluded from fit "
                         "only, never dropped from the receipt record."),
            },
            "reused_launcher": ("src/ember/governance/scripts/w1_collapse_control_run.py:run_phase2_live "
                                 "(imported, never reimplemented/forked)"),
            "shard_dir_note": ("shard_dir is never embedded in this script or in any "
                               "committed receipt (repo-guard scrubs absolute local "
                               "paths); passed at invocation via --shard-dir only."),
        }

        receipts_dir = os.path.join(REPO, "receipts", "p1-envelope-sweep")
        os.makedirs(receipts_dir, exist_ok=True)
        out_path = os.path.join(receipts_dir, f"{ts}-point{args.point}.json")
        checked_write(out_path, receipt)
        receipt["_receipt_path"] = out_path
        return receipt
    finally:
        release_sweep_lock()


def refuse_unless_authorized(args: argparse.Namespace) -> None:
    authorized = os.environ.get("EMBER_GATE_AUTHORIZED", "") == "1"
    if not args.dry_run and not authorized:
        raise SystemExit(
            "P1_SWEEP_LIVE_REFUSED: a real GPU launch requires EMBER_GATE_AUTHORIZED=1 "
            "(the general repo-wide real-GPU-launch key per timeshare_pretrain.py's own "
            "docstring) AND absence of --dry-run. This script deliberately does NOT "
            "check/require EMBER_W1_MAINTAINER_WINDOW_CONFIRMED -- see module docstring.")


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--point", type=int, required=True, choices=sorted(POINT_MULTIPLIERS))
    ap.add_argument("--shard-dir", default=None,
                    help="real corpus shard dir; never hardcoded in-repo")
    ap.add_argument("--decontam-receipt", default=DECONTAM_RECEIPT_DEFAULT)
    ap.add_argument("--corpus-manifest-sha256",
                    default=w1c.CORPUS_MANIFEST_COMBINED_SHA256_EXPECTED)
    ap.add_argument("--out-dir", default=os.path.join(REPO, "scratch", "p1-envelope-sweep"))
    ap.add_argument("--seed", type=int, default=2002)
    ap.add_argument("--eval-every", type=int, default=None,
                    help="default: evaluate only at step 0 and the final step")
    ap.add_argument("--checkpoint-every", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="CPU-only mechanics/schema check; never touches CUDA/corpus/gate")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    refuse_unless_authorized(args)

    point_info = steps_for_point(args.point)
    budget_steps = point_info["steps"]
    intended_warmup = intended_warmup_steps(budget_steps)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = os.path.join(args.out_dir, f"point{args.point}-{ts}")
    os.makedirs(out_dir, exist_ok=True)

    if args.dry_run:
        receipt = run_point_dry(args, point_info, ts, out_dir, intended_warmup)
    else:
        receipt = run_point_live(args, point_info, ts, out_dir, intended_warmup)

    print(f"[p1-envelope-sweep] point={args.point} steps={budget_steps} "
          f"receipt={receipt.get('_receipt_path')}")
    summary = {k: v for k, v in receipt.items() if k != "eval_trace"}
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
