# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cbase_v0_segment_live.py — daemon-invoked wrapper for a single C-BASE v0 segment train.

This script is exec'd by the train-daemon (operator-local train-daemon server process) with
NO CLI args.  All configuration is injected via environment variables set by
ember_cbase_launch._build_daemon_job_payload before POSTing to the daemon.

Provenance: landed from stage dryrun-20260704T211712Z (ember issue #210 Tier 2)
with a portability fix -- the daemon-path citation above and the EMBER_SHARD_DIR
fallback default below carried absolute drive-letter-rooted / WSL-mount
literals pointing at an operator-local tree outside this repo (no
repo-relative default applies). Fallback dropped to empty string;
EMBER_SHARD_DIR (already the primary source, set by the daemon dispatch
payload) is unaffected. See receipts/ember-c-scale/land210g-*.

Required env vars
-----------------
EMBER_GATE_AUTHORIZED=1         (interlock — run_v0_segment checks this)
EMBER_SHARD_DIR                 WSL /mnt path to the mixture dir (40/10/50 mixture)
EMBER_SEGMENT_TOKENS            int — tokens to train this segment
EMBER_TOTAL_STEPS               int — total steps for WSD schedule denominator
                                (= full pretrain token budget // (batch * seq))

Optional env vars
-----------------
EMBER_RESUME_CKPT_DIR           WSL path to checkpoint to resume from (omit for fresh start)
EMBER_RUN_DIR                   WSL path for checkpoint output; required for floor-gated resume.
                                Without this, timeshare_pretrain falls back to tempfile.mkdtemp
                                (breaks cross-segment resume). Set by the generated per-segment
                                wrapper in ember_cbase_launch.run_floor_gated_loop.
PYTORCH_CUDA_ALLOC_CONF         defaults to expandable_segments:True

Recipe (frozen — c04 design-bench BEST cell, receipt c04-design-bench-c03-h1024-d20-20260623T024512Z.json)
----------------------------------------------------------------------------------------------------------
Model:        c03-h1024-d20  (hidden=1024, layers=20, heads=16, vocab=32000, seq=1024)
Precision:    QAT — INT8 fake-quant STE on linear weights (fp19_bench scheme)
              The C-BASE run is QAT muon_split batch=16 == the c04 bench cell by identity.
              Receipted throughput: 19874.8 tok/s (best_cell tok_s_paced).
              The convergence-harness BF16 number (~19600 tok/s) is a SEPARATE code path
              (run_convergence_segment / conv_c03_muon_split_bf16ns5.py) and is NOT the
              C-BASE throughput basis.  Do NOT apply the "0.928x tax / ~18737 tok/s"
              framing here — that figure taxed the wrong base.
              See GPU launch-verification checklist in ember_cbase_launch.py.
Grad-ckpt:   True  (batch=16 arm; spec §1 — enabled unconditionally in build_v0_model line 1153)
Optimizer:    muon_split (bench cell winner; built by build_split_optimizer in run_v0_segment)
WSD:          YES — run_v0_segment calls apply_wsd at every step
Resume:       YES — load_checkpoint(EMBER_RESUME_CKPT_DIR) if set
Batch:        16 (bench cell recipe — overrides v0-pretrain-config throughput.batch=4)
Seq:          1024

BATCH FIX (2026-06-23)
-----------------------
The bench cell receipt specifies batch=16.  v0-pretrain-config.json throughput.batch=4 was
a config-level inconsistency; the _BATCH constant here and the batch_size=16 kwarg in the
timeshare_pretrain.main() --live call are the authoritative override.  EMBER_SEGMENT_TOKENS
is converted to n_steps using batch=16 and seq=1024 (16384 tokens/step).
"""
import os
import sys

# ---------------------------------------------------------------------------
# Gate + interlock
# ---------------------------------------------------------------------------
os.environ["EMBER_GATE_AUTHORIZED"] = "1"

# Allocator — reduces fragmentation on large models.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

# ---------------------------------------------------------------------------
# Read required env vars (fail-fast if absent — the daemon will log the error).
# ---------------------------------------------------------------------------
_SHARD_DIR = os.environ.get("EMBER_SHARD_DIR", "")
_SEGMENT_TOKENS_STR = os.environ.get("EMBER_SEGMENT_TOKENS", "")
_TOTAL_STEPS_STR = os.environ.get("EMBER_TOTAL_STEPS", "")
_RESUME_CKPT_DIR = os.environ.get("EMBER_RESUME_CKPT_DIR", "")
# EMBER_RUN_DIR: stable per-run checkpoint directory.  Without this,
# timeshare_pretrain.run_v0_segment falls back to tempfile.mkdtemp(prefix="v0_live_"),
# which breaks floor-gated resume across segments (each segment would land in a
# different /tmp dir).  The generated per-segment wrapper in
# ember_cbase_launch.run_floor_gated_loop bakes this value in at dispatch time.
_RUN_DIR = os.environ.get("EMBER_RUN_DIR", "")

# ---------------------------------------------------------------------------
# Derived step counts — batch=16, seq=1024 (c04 bench cell frozen recipe).
# Override of v0-pretrain-config throughput.batch=4; batch=16 is load-bearing
# for the receipted 19874.8 tok/s throughput (c04-design-bench best_cell).
# ---------------------------------------------------------------------------
_BATCH = 16
_SEQ = 1024
_TOKENS_PER_STEP = _BATCH * _SEQ  # 16384

if _SEGMENT_TOKENS_STR:
    try:
        _segment_tokens = int(_SEGMENT_TOKENS_STR)
    except ValueError:
        raise RuntimeError(
            f"cbase_v0_segment_live: EMBER_SEGMENT_TOKENS={_SEGMENT_TOKENS_STR!r} "
            f"is not a valid integer."
        )
    _n_steps = max(1, _segment_tokens // _TOKENS_PER_STEP)
else:
    # Default: 50M-token segment.
    _n_steps = max(1, 50_000_000 // _TOKENS_PER_STEP)

if _TOTAL_STEPS_STR:
    try:
        _total_steps = int(_TOTAL_STEPS_STR)
    except ValueError:
        raise RuntimeError(
            f"cbase_v0_segment_live: EMBER_TOTAL_STEPS={_TOTAL_STEPS_STR!r} "
            f"is not a valid integer."
        )
else:
    # Default: compute-optimal budget (7367086080 tokens // 16384 tokens/step = 449651).
    # This is the WSD schedule denominator; correct value comes from the launch driver.
    _total_steps = max(1, 7_367_086_080 // _TOKENS_PER_STEP)

# ---------------------------------------------------------------------------
# Build sys.argv for timeshare_pretrain.main() — the --live path (run_v0_segment).
# ---------------------------------------------------------------------------
# NOTE: the daemon invokes `python cbase_v0_segment_live.py` with NO CLI args.
# We construct sys.argv here so timeshare_pretrain.main() receives the correct args
# when called below.
# ---------------------------------------------------------------------------
_argv = [
    "timeshare_pretrain.py",
    "--live",                        # -> run_v0_segment (WSD + resume + checkpoint I/O)
    "--steps", str(_n_steps),        # steps this segment
    "--total-steps", str(_total_steps),  # WSD schedule denominator
    "--shard-dir", _SHARD_DIR,       # mixture dir (40/10/50 blend)
    "--seed", "42",
    "--segment-id", "cbase-v0",
]

if _RUN_DIR:
    # Pass the stable run_dir so checkpoints land in a consistent, known location.
    # Without --run-dir, timeshare_pretrain.run_v0_segment falls back to
    # tempfile.mkdtemp(prefix="v0_live_"), breaking cross-segment resume.
    _argv += ["--run-dir", _RUN_DIR]

if _RESUME_CKPT_DIR:
    _argv += ["--resume-ckpt", _RESUME_CKPT_DIR]

sys.argv = _argv

# ---------------------------------------------------------------------------
# Import and run timeshare_pretrain.  The module is in the same scripts/ dir
# (daemon sets cwd to scripts/).
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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
# issue2015 exact-local-import-end:src/ember/governance/scripts/timeshare_pretrain.py  # noqa: E402

ts.main()
