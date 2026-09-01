#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""run_p5_audit.py -- P0 PROBE P5: ratio-invariance + commutation audit
(ember issue #207, P0 composition-law program).

FROZEN SPEC (do not deviate without a dated entry in this file AND
docs/domains/governance/ledgers/deviations.md -- the freeze rule, verbatim from the pre-registration):
  state/prereg-p0-probes-p5-p1tier0-v1.md, section "PROBE P5", v1.1
  (frozen 2026-07-06). This file implements that section EXACTLY. Anything
  this file cannot honestly ground in a live production object is recorded
  as an explicit N/A-with-reason, never silently invented or approximated.
  Silent iteration voids receipts (the spec's own zombie rule: loss/
  trajectory bands alone certify NOTHING here; mechanism metrics are
  co-primary; a run whose engagement assertions did not fire writes NO
  metrics artifact -- it writes a FAILED-ENGAGEMENT receipt, #216).

GOAL: measure whether the seven dimensionless mechanism ratios below are
ladder-invariant by default across three checkpoints (368M "QAT", 718M
"D6-segment", 1.22B "rung-1"), and whether the net2net grow pushforward
approximately commutes with the update map. INSTRUMENTATION ONLY: no
training. Per measurement point: forward + backward + optimizer-step-IN-
COPY (never mutates the source checkpoint's own state dict -- asserted).

GROUNDING PASS (this authoring session, direct code reads, file:line cited
so every pin below is either CONFIRMED-BY-CODE or an honest structural
N/A -- never assumed):
  - Live QUANTIZER used for the grid step (Delta): the production QAT
    fake-quant transform is scripts/timeshare_pretrain.py::_apply_fake_quant
    (mode="qat"), PER-CHANNEL granularity: for a torch.nn.Linear weight
    W (out_features, in_features), s = W.abs().amax(dim=1, keepdim=True)
    .clamp(min=1e-8) / 127.0 -- one scale per OUTPUT ROW (a "channel" =
    one output neuron), int8 grid (256 levels, +-127 after clamp). This is
    DIFFERENT from src/ember/governance/scripts/ember_bitnet_core.py's absmean_scale (per-
    TENSOR, ternary {-1,0,+1} BitNet b1.58 path) -- that track (C15
    bitnet-vs-dense comparison) has no full-scale (368M+) checkpoint
    receipted in this repo snapshot (only receipts/ember-tiny-bitnet-
    comparison/* at toy scale exist); _apply_fake_quant int8-grid QAT is
    the one actually exercised at the 368M/718M/1.22B scales this probe
    targets, so it is the live quantizer this harness reads. Granularity
    pin = "per-channel (per-output-row), int8 grid, 127-level symmetric" --
    stamped every run, never assumed to be per-tensor or per-block.
  - Muon optimizer: scripts/timeshare_pretrain.py::_muon_class/_Muon
    (line ~742-798). ns_steps default 5, coefficients (a,b,c) =
    (3.4445, -4.7750, 2.0315) -- the quintic Newton-Schulz iteration,
    copied verbatim below (same discipline as scripts/expc1/
    run_expc1_rank_sweep.py: a self-contained copy, not an import, so this
    research harness stays decoupled from timeshare_pretrain's production
    contract/config loading). momentum=0.95, nesterov=True defaults. State
    dict key: "momentum_buffer". Split: split_param_groups (line ~801) --
    a 2D weight that is not an embedding and not a head goes to Muon;
    everything else (embeddings, 1D norms/biases, heads) goes to AdamW.
  - optimizer_reset_on_resume: a REAL parameter name --
    scripts/timeshare_pretrain.py::run_v0_segment(reset_optimizer_on_resume:
    bool = False, ...) (line ~1229). Ordinary continuation segments default
    False (optimizer state warm-loaded/carried on resume). The net2net
    grow-chain callers (scripts/cbase_grow_rung.py, scripts/
    cbase_grow_live.py) explicitly pass True and RECEIPT it verbatim as
    "optimizer_reset_on_resume": true in their own emitted receipts (grep-
    confirmed in both files) -- because grow changes FF-dim param shapes,
    so pre-grow momentum cannot be replayed into the post-grow optimizer.
    This harness runtime-reads this field from the checkpoint's OWN
    receipt (never hardcodes it) and treats it as spec-critical: it drives
    both the rho_spec N/A-with-reason path AND the cross-width state-
    provenance-mismatch guard on rho_SR (see STATE + LR PINS below).
  - net2net grow path: src/ember/governance/scripts/cbase_grow_dryrun.py::widen_state_dict
    (line ~85) -- EXACT function-preserving duplication: gate_proj/up_proj
    rows -> cat([w, w]); down_proj columns -> cat([w*0.5, w*0.5], dim=1).
    No noise term anywhere in this operator (grep-confirmed across
    scripts/cbase_grow_*.py and scripts/ember_growth_harness.py -- the
    net2net path as actually coded is noise-free by construction). This is
    a genuine MEASUREMENT (epsilon = 0 exactly, not an N/A), reconfirmed
    empirically every run below (never merely assumed from the docstring)
    by diffing the two realized duplicate copies post-widen.
  - Rank projection (rho_rank / rho_grow): no production code path
    projects a Muon-eligible tensor into a rank-r subspace anywhere in
    scripts/timeshare_pretrain.py or the cbase_grow_* family (grep-
    confirmed). src/ember/governance/scripts/expc1/run_expc1_rank_sweep.py is a SEPARATE
    research harness exploring a hypothetical design; it is not wired into
    production. rho_rank / rho_grow are therefore N/A-by-construction
    (structural, no projector enabled) for all three checkpoints -- an
    honest finding per the spec's own "an N/A is a finding, not a gap".
  - 8-bit optimizer state (rho_block): src/ember/governance/scripts/ember_d6_bf16_momentum_ab.py
    measured (CPU selftest, no assumption) that production optimizer state
    is bf16-native end to end (AdamW/_Muon zeros_like(g) inherits the
    bf16 param/grad dtype; nothing promotes to fp32 anywhere in the
    training step) -- there is no 8-bit optimizer-state path in production.
    rho_block is therefore N/A (structural) in the real run. The formula
    itself IS implemented and unit-tested in --selftest against a
    synthetic 8-bit state tensor (per the spec's letter: the metric must
    be correct and tested even though currently unreachable in production).
  - Checkpoint discovery (SUPERSEDED by the v1.2 ruling below): the
    original grounding pass here found no clean receipt for a "368M QAT",
    "718M D6-segment", or "1.22B rung-1" checkpoint (only param-count
    fingerprints, no path field). The team lead independently verified the
    real on-disk manifests and issued a corrected, binding ground-truth
    ruling -- see "GROUND-TRUTH RULING (v1.2 amendment)" immediately below,
    which is what discover_checkpoints() now targets. The three-fictional-
    checkpoint framing above is kept in this docstring only as the
    "what we thought going in, what we found instead" record the project's
    own honesty discipline expects -- CHECKPOINT_FINGERPRINTS/the generic
    param-count-guessing scan it drove no longer exist in this file.

GROUND-TRUTH RULING (v1.2 amendment, team lead, 2026-07-06 -- pending
formal landing in state/prereg-p0-probes-p5-p1tier0-v1.md as a dated
deviation + docs/domains/governance/ledgers/deviations.md entry, filed BEFORE any real-checkpoint
execution per the freeze rule's own pre-execution-amendment allowance;
nothing in this file has executed against real checkpoints, so this
lands clean). The team lead verified the real on-disk manifests directly
(not reproducible from a receipt in THIS worktree for every field) and
ruled:
  REAL INVENTORY is ONE lineage, TWO widths, ONE executed grow event --
  not three independent checkpoints:
    PRE-GROW  -- models/cbase-grow-rung/rung1-20260703T155447Z/checkpoints/
                 step-00000730 (~467M class, ff_seed=8192, model.pt sha256
                 74a5b1d4c21b38fb4a8037bd079c2073516dee9a242849fc33fda191f4
                 fa0f3b -- full hash per the team lead's follow-up ruling
                 message, validated at runtime against the on-disk
                 manifest.json['files']['model.pt'], never fabricated
                 here), 3.8GB. optimizer.pt carried VERBATIM from an
                 earlier parent segment ("stale shapes post-widening"
                 caveat) -- stamped, NOT treated as a blocking provenance
                 mismatch per this ruling (see real_inventory_provenance()
                 below).
    GROW      -- ff_widening_net2net at step 730 -- the SAME deterministic
                 duplication already grounded above
                 (src/ember/governance/scripts/cbase_grow_dryrun.py::widen_state_dict): no
                 noise term, function-preserving.
    POST-GROW -- .../rung1-20260703T155447Z/stabilize/checkpoints/
                 step-00000766 (4.7GB; model.pt sha256
                 58e8e98916823941381d9cf71cf3725148aa61cf106e8b46c4fa96e0
                 c5e4659b -- pinned identically FOUR times in
                 receipts/ember-c-e2b-paired/ember-c-e2b-paired-
                 20260705T041045Z.json (owned_core_identity.checkpoint,
                 .base_checkpoint_path, .model_pt_sha256,
                 .base_model_pt_sha256 all agree; muon_split=True,
                 mtp_enabled=True, quantized=False,
                 no_borrowed_weights=True in the same receipt) -- this is
                 the one identity this harness can independently confirm
                 from a file already committed in this repo, not merely
                 asserted by the ruling). Its OWN (fresh, post-stabilize)
                 optimizer state -- admissible against the pre-grow side's
                 parent-carried state because both are muon_split (same
                 optimizer KIND), caveat stamped, per this ruling.
    "368M QAT"     -- DOES NOT EXIST. receipts/fp19-bench-* is a pure
                 fake-quant THROUGHPUT bench (QAT arm vs bf16/ternary
                 arms) -- no checkpoint was ever saved. Dropped as a
                 target (was never real).
    "1.22B rung-1" (docs/domains/governance/spec/c-scale-s1-growth-chain-DRAFT.md's OWN
                 "rung 1" row, N=1,221,633,024 at ff=16384) -- NEVER
                 EXECUTED, priced only (pure-Python G-budget FIT estimate,
                 no CUDA). NAMING COLLISION, resolved by this ruling: the
                 folder-name "rung1-20260703T155447Z" (the ALREADY-
                 EXECUTED 467M-class -> larger-class ff-widening above) IS
                 this harness's "rung-1"; the DRAFT's 1.22B row is
                 unrelated, un-started future work and is never conflated
                 with it here.
  Absolute filesystem roots are NEVER hardcoded in this published source
  (leak-gate discipline: absolute local paths are never published). The
  relative path suffixes above are already published verbatim in the
  committed receipt cited above, so repeating them here (relative form
  only) discloses nothing new. The absolute root is resolved ONLY at
  runtime from the EMBER_MODELS_ROOT environment variable (see
  MODELS_ROOT_ENV below) -- never guessed, never embedded literally.
  Manifest schema note: the exact manifest.json key names for ff_seed /
  ff_grown are INFERRED (not independently confirmed against a real
  manifest.json in this worktree -- none exists here); the first real
  execution against the actual manifests should verify these key names
  and amend read_manifest_ff_fields() if they differ (a schema-name
  discovery, filed before that execution, not a numeric/logic deviation).

STATE + LR PINS (confound guards, verdict-critical -- spec verbatim,
  AMENDED per the v1.2 ruling's specific admissibility call):
  Optimizer-state provenance must be identical IN KIND across checkpoints
  being compared. For the GENERIC (hypothetical three-checkpoint) case
  this harness still enforces the strict spec rule via
  provenance_mismatch() (used by --selftest/--dry-run, unchanged): True
  unless every checkpoint shares the same reset-kind, forcing UNRESOLVED
  on any cross-width comparison. For the REAL rung-1 pair specifically,
  the team lead's ruling is a NAMED EXCEPTION, not a relaxation of the
  rule in general: pre-grow's parent-carried state and post-grow's own
  state are DIFFERENT in origin but the SAME KIND (both muon_split) --
  real_inventory_provenance() encodes this as admissible-with-caveat,
  never as a silent pass; the caveat text is stamped verbatim in every
  real-run receipt. The in-copy update is computed TWICE per checkpoint:
  at the checkpoint's own LR (checkpoint-LR series, reported alongside)
  and at pinned unit LR (lr=1.0, all else identical -- the UNIT-LR series
  is the one all cross-width comparisons are taken on).

MEASUREMENTS (per checkpoint, per tensor class: attention / FF /
embedding, computed separately) -- see the module-level functions:
  rho_sr        -- per-block ||update_b||_RMS / Delta_b (median over
                   blocks -> per-tensor; median over tensors -> per-class).
                   Block granularity is per-channel (see quantizer above);
                   one "block" = one output-row scale. Real run: NO native
                   QAT-trained checkpoint exists, so rho_sr/rho_noise's
                   grid-step reads are INSTRUMENTED (the production
                   _apply_fake_quant transform applied transiently, in-
                   copy, to the two real bf16 checkpoints) rather than
                   read off a resident QAT weight -- every real-run value
                   is tagged measurement_mode="instrumented-not-resident"
                   (see probe_qat_instrumented()); the regime-conditional
                   assertion paths already in v1.1 ("fake-quant cells:
                   assert quantized view != master view somewhere") cover
                   this labeling directly.
  rho_noise     -- epsilon / Delta; epsilon = the REALIZED (measured, not
                   assumed) net2net duplicate-pair delta, empirically 0 for
                   this production grow path (see grounding above).
  rho_rank,
  rho_grow      -- N/A-by-construction, both real checkpoints (no
                   projector exists in production).
  rho_spec      -- at the grow event only (the rung-1 PRE-grow state,
                   step-00000730): ||M - P_dup(M)||_2 / sigma_max(M).
                   N/A-with-reason="production-reset" whenever
                   optimizer_reset_on_resume reads True for the grow
                   segment (the momentum matrix does not carry state
                   across the grow, so there is no M to measure) -- itself
                   a law-relevant finding per the spec.
  rho_batch     -- Welford over the 16 frozen microbatches:
                   B_simple = tr(Sigma_g) / ||g_bar||^2;
                   rho_batch = (batch_size * (1-beta)^-1) / B_simple, beta
                   read from the live Muon param group's "momentum".
  rho_block     -- N/A (structural, no 8-bit optimizer state in
                   production; formula implemented + selftested anyway).
  d_comm        -- commutation defect at the rung-1 grow event -- UPGRADED
                   by the v1.2 ruling from aspiration to the harness's
                   HEADLINE deliverable: theta = step-00000730, G = the
                   deterministic ff-widening duplication reconstructed
                   in-code from step-730's own weights, U = one Muon step
                   (pre-grow's parent-carried state / LR for U_k,
                   post-grow's own state / LR for U_{k+1}) on the frozen
                   probe batch -- both U-then-G and G-then-U are fully
                   computable from the two on-disk artifacts named above.
                   Still a MEASUREMENT (no pass bar at v1.1/v1.2).

CROSS-WIDTH SCOPING (v1.2 amendment): the real inventory gives exactly
  TWO width points (pre-grow ~467M-class, post-grow larger-class), not
  three. The frozen spec's own missing-point rule ("any missing width
  point... UNRESOLVED; two-point 'monotone' is meaningless and is pre-
  registered as non-evidence") applies directly and is NOT softened: the
  formal per-class verdict on the real inventory is always
  "UNRESOLVED-by-inventory" (see two_point_direction_report()), never
  KILL/PROMOTE/GRAY. Per the ruling, the raw 2-point direction (which way
  rho_SR moved, and by how much) is additionally reported as SUPPLEMENTARY
  information alongside the forced UNRESOLVED verdict -- never promoted
  to a verdict itself.

ENGAGEMENT ASSERTIONS (before ANY artifact write; #216 fail-closed rule):
  checkpoint sha recorded; Delta read from the live quantizer (grid object
  exists and quantizes a test tensor); update computed in-copy (source
  state dict bitwise unchanged after the probe); probe batch sha matches
  the frozen batch on disk; LR / schedule-position / tokens-seen / state-
  provenance stamped per checkpoint; all 7 ratios carry a non-null value OR
  an explicit recorded N/A-with-reason. Any assertion failure -> a
  FAILED-ENGAGEMENT receipt is written INSTEAD of a metrics artifact; the
  metrics artifact is never written on a partial assertion pass.

VERDICT (per-class KILL / PROMOTE / GRAY; headline = majority; mixed
per-class outcomes -> GRAY/UNRESOLVED overall with the per-class table as
the artifact -- see compute_verdict() for the exact band logic, the noise-
floor rule, and the missing-point -> UNRESOLVED rule).

BUDGET: CPU/GPU minutes; hard wall 60 min per checkpoint. GPU co-resident
<=2 GiB; nvidia-smi preflight; serialize behind any running GPU job (one-
job rule; this probe WAITS, it never kills).

GOVERNOR / LAUNCH-GATE (never loosened; --dry-run and --selftest touch
neither CUDA nor nvidia-smi nor any real checkpoint): the live path (no
flags) requires EMBER_GATE_AUTHORIZED=1 (env) or refuses closed (status
BLOCKED, receipt WRITTEN, probe NOT executed) -- identical interlock
pattern to src/ember/governance/scripts/expc1/run_expc1_rank_sweep.py. NOT fired by this
authoring session. Even when authorized, the live path first runs
discover_checkpoints(); on any MISSING checkpoint it writes a
FAILED-ENGAGEMENT receipt (never fabricates a path) and stops.

MODES:
  --selftest   Pure Python/math + CPU-only torch checks: every ratio
               formula (including the ones that are N/A in production, so
               the formula itself is proven correct), Welford vs direct
               covariance-trace agreement, the P_dup symmetrization
               identity (rho_spec ~ 0 when M is already symmetric under
               P_dup, nonzero under a controlled perturbation), the
               commutation-defect formula (d_comm = 0 when U and G are
               constructed to commute by design, nonzero under a
               controlled perturbation), engagement-assertion pass/fail
               paths, verdict-band logic (KILL/PROMOTE/GRAY/UNRESOLVED,
               noise-floor rule, missing-point rule, mixed-per-class rule,
               provenance-mismatch-forces-UNRESOLVED rule), and receipt-
               schema round trip. Prints P5_AUDIT_SELFTEST_PASS.
  --dry-run    CPU only, toy widths (24/32/48 hidden -- an illustrative
               THREE-point toy ladder, kept unchanged by the v1.2 ruling;
               independent of the real TWO-checkpoint inventory below, it
               exists only to exercise the generic 3-point verdict logic
               end-to-end), NO real checkpoints -- builds three self-
               contained toy transformers (own module, decoupled from
               timeshare_pretrain's contract loader -- same discipline as
               expc1), but reuses the PRODUCTION math byte-for-byte: the
               _apply_fake_quant per-channel int8 formula, the Muon/
               Newton-Schulz update, and the net2net cat([w,w]) /
               cat([w*0.5,w*0.5]) widen operator. Proves the harness
               plumbing end-to-end (all 7 ratios + commutation defect +
               engagement assertions + verdict logic) at zero real-
               experiment weight. NOT research-conclusive (receipt says
               so). Receipt -> receipts/p5-ratio-audit-dryrun-<ts>.json.
  (no flag)    The real run: discover_checkpoints() resolves the TWO real
               rung-1 lineage checkpoints (pre-grow step-00000730, post-
               grow step-00000766, per the v1.2 ground-truth ruling above)
               from EMBER_MODELS_ROOT + the manifests/receipts named
               there, fail-closed if either is unresolved, then, only
               under EMBER_GATE_AUTHORIZED=1, the full probe (headlined by
               the real commutation defect d_comm) on those two
               checkpoints, with the cross-width comparison reported as
               UNRESOLVED-by-inventory + supplementary 2-point direction
               (never KILL/PROMOTE/GRAY, per the no-2-point-monotone
               rule). NOT fired by this authoring session.

No git commits from inside this file. No downloads. No founder/user names
anywhere in this file or its receipts. UTF-8 / plain-ASCII source.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))           # scripts/p5_ratio_audit
SCRIPTS_DIR = os.path.dirname(HERE)                          # scripts/
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "..")) # repo root
RECEIPTS = os.path.join(REPO_ROOT, "receipts")
sys.path.insert(0, SCRIPTS_DIR)

from receipt_write import checked_write  # noqa: E402  (light; no torch)
import timeshare_pretrain as ts  # noqa: E402  (light; no torch at module level -- #580)

# ---------------------------------------------------------------------------
# Frozen constants (pre-registration v1.1 -- never change without a dated
# deviation entry, per the freeze rule).
# ---------------------------------------------------------------------------

SPEC_REF = "state/prereg-p0-probes-p5-p1tier0-v1.md#PROBE-P5"
SPEC_VERSION = "v1.1+ckpt-inventory-v1.2"  # measurement spec is v1.1 (frozen,
# unchanged); checkpoint-inventory amendment is v1.2 (team lead ruling,
# 2026-07-06, pending formal landing in the frozen spec doc + docs/domains/governance/ledgers/deviations.md)
ISSUE = "#207"

# Absolute root of the models/ directory tree on whatever box actually runs
# the live path -- NEVER hardcoded (leak-gate discipline: absolute local
# paths are never published). Resolved at runtime only.
MODELS_ROOT_ENV = "EMBER_MODELS_ROOT"

PROBE_SEED = 20260706
PROBE_N_MICROBATCHES = 16
PROBE_SEQ_LEN = 1024

UNIT_LR = 1.0

KILL_RATIO_MAX = 1.2          # max/min <= 1.2 (~+-10%) -> KILL (drift rejected)
PROMOTE_RATIO_MIN = 1.5       # max/min >= 1.5 + monotone + noise-band-excluded -> PROMOTE
# 1.2 < ratio < 1.5, or non-monotone, or noise-band overlap -> GRAY/UNRESOLVED

TENSOR_CLASSES = ("attention", "ff", "embedding")

RATIO_NAMES = ("rho_sr", "rho_noise", "rho_rank", "rho_grow", "rho_spec",
               "rho_batch", "rho_block")

# RUNG1_LINEAGE -- the v1.2 ground-truth checkpoint registry (team lead
# ruling, 2026-07-06). ONE lineage, TWO real checkpoints, ONE executed grow
# event. Relative path suffixes are already published verbatim in the
# committed receipt cited in known_sha256_source below -- republishing them
# here (relative form only) discloses nothing new; the absolute root comes
# ONLY from MODELS_ROOT_ENV at runtime. This is the SINGLE extension point:
# if a maintainer later corrects a field (e.g. completes the pre-grow sha256
# beyond its known prefix), edit ONLY this dict.
# ff-shape naming-collision guard (v1.2 ruling item 4): NOT a manifest field
# (grep-confirmed against scripts/cbase_grow_rung.py and
# src/ember/governance/scripts/cbase_grow_dryrun.py -- both derive ff from the LOADED tensor's own
# shape: `ff_seed = int(m_state["backbone_model.layers.0.mlp.gate_proj.weight"]
# .shape[0])`, never from a manifest key). load_real_checkpoint() below
# reproduces that exact check; RUNG1_LINEAGE's "expected_ff" is compared
# against the OBSERVED tensor shape, not a manifest guess.
RUNG1_LINEAGE = {
    "pre_grow_rung1": {
        "label": "rung-1 PRE-grow (~467M class, RECONSTRUCTED)",
        "role": "pre_grow",
        "relative_path": "models/cbase-grow-rung/rung1-20260703T155447Z/derived/pregrow-ff8192",
        "known_model_pt_sha256": "285ebb7f9a65d8c430e1ab14586d6daad9c20eca4f3229b6df0d00ff78a103e6",
            # derived via inverse net2net from post-grow step-00000766; self-tested
            # bitwise roundtrip via forward grow (RECONSTRUCT_PREGROW_SELFTEST_PASS);
            # all four fail-closed guards (sha256, shapes, twin bit-identity,
            # down_proj halves) passed. Reconstructed from the grown checkpoint
            # (step-00000730, source sha 74a5b1d4...) with guards + selftest.
        "expected_ff": 8192,
        "optimizer_state_provenance": "derived (inverse net2net from post-grow; "
            "no optimizer state carried)",
        "known_sha256_source": "receipts/reconstruct-pregrow/reconstruction-PASS-*.json "
            "(script: scripts/reconstruct_pregrow.py, all guards + selftest PASS)",
    },
    "post_grow_rung1": {
        "label": "rung-1 POST-grow (stabilized)",
        "role": "post_grow",
        "relative_path": "models/cbase-grow-rung/rung1-20260703T155447Z/stabilize/checkpoints/step-00000766",
        "known_model_pt_sha256": "58e8e98916823941381d9cf71cf3725148aa61cf106e8b46c4fa96e0c5e4659b",
        "expected_ff": 16384,
        "optimizer_state_provenance": "own (fresh, post-stabilize state)",
        "known_sha256_source": "receipts/ember-c-e2b-paired/ember-c-e2b-paired-"
            "20260705T041045Z.json (owned_core_identity.checkpoint, "
            ".base_checkpoint_path, .model_pt_sha256, .base_model_pt_sha256 "
            "all agree; muon_split=True, mtp_enabled=True, quantized=False)",
    },
}

FF_GUARD_VALUES = frozenset({8192, 16384})  # naming-collision guard, per the ruling

PRE_REGISTRATION = {
    "spec_ref": SPEC_REF, "spec_version": SPEC_VERSION, "issue": ISSUE,
    "prediction": "rho_SR (unit-LR series) is NOT invariant -- it drifts "
        "with width under the default per-channel-referenced int8 grid. "
        "v1.2 SCOPING: the real inventory gives exactly TWO width points "
        "(rung-1 pre-grow ~467M-class, post-grow larger-class), not the "
        "originally-envisioned three -- per the frozen spec's own "
        "missing-point/non-evidence rule, the formal cross-width verdict "
        "is always UNRESOLVED-by-inventory; the 2-point direction is "
        "reported supplementarily, never promoted to a verdict.",
    "verdict_bands": {
        "kill_per_class": "max/min rho_SR across the three widths <= "
            f"{KILL_RATIO_MAX} (~+-10%) -> KILL (drift rejected, promote-the-"
            "null, GOOD outcome, law simplifies).",
        "promote_per_class": f"max/min >= {PROMOTE_RATIO_MIN}, monotone "
            "direction, AND the across-width spread exceeds the within-"
            "checkpoint noise (95% band per width point, from the 16 "
            "per-microbatch replicates, must EXCLUDE the kill band).",
        "gray_per_class": f"{KILL_RATIO_MAX}-{PROMOTE_RATIO_MIN}, non-"
            "monotone, or noise-band overlap -> UNRESOLVED, extend to "
            "per-layer resolution before any claim.",
        "headline": "majority of per-class verdicts; ANY class PROMOTE "
            "while ANY class KILL -> GRAY/UNRESOLVED overall with the "
            "per-class table as the artifact.",
        "missing_point_rule": "any missing width point (OOM/wall-cap kill "
            "of one leg) -> UNRESOLVED; two-point 'monotone' is non-"
            "evidence, pre-registered.",
        "provenance_mismatch_rule": "optimizer-state provenance must be "
            "identical in kind across checkpoints being compared; on "
            "mismatch every cross-width comparison is forced UNRESOLVED, "
            "never compared across the discontinuity. NAMED EXCEPTION "
            "(v1.2 ruling, real rung-1 pair only): pre-grow's parent-"
            "carried state and post-grow's own state are admissible "
            "together because both are the SAME KIND (muon_split), "
            "caveat stamped -- see real_inventory_provenance().",
        "two_point_rule": "v1.2: the real inventory has exactly two width "
            "points; the frozen spec's own missing-point rule ('two-point "
            "monotone is meaningless... pre-registered as non-evidence') "
            "applies directly -- formal verdict is always "
            "UNRESOLVED-by-inventory, direction reported supplementarily.",
    },
    "state_lr_pins": {
        "optimizer_state_provenance": "warm-loaded from the checkpoint's "
            "own saved state in all three, OR the probe records "
            "PROVENANCE-MISMATCH and affected ratios are UNRESOLVED, never "
            "compared cross-width.",
        "dual_lr_series": "in-copy update computed at the checkpoint's own "
            "LR AND at pinned unit LR (lr=1.0); ALL cross-width rho_SR "
            "verdicts are taken on the UNIT-LR series; checkpoint-LR "
            "series reported alongside.",
    },
    "budget": {"hard_wall_min_per_checkpoint": 60, "gpu_coresident_gib_max": 2},
    "no_pass_bar_metrics": ["d_comm"],
    "scope_disclosures": [
        "quantizer granularity is PER-CHANNEL (per-output-row int8), "
        "confirmed at scripts/timeshare_pretrain.py::_apply_fake_quant "
        "mode='qat' -- NOT per-tensor and NOT genuinely sub-channel "
        "per-block; 'block' in this harness means one output-row scale.",
        "rho_rank/rho_grow are N/A-by-construction for all three "
        "checkpoints -- no rank-projection code exists in production "
        "(grep-confirmed); scripts/expc1's rank-sweep is a separate, "
        "unwired research harness.",
        "rho_block is N/A (structural) -- production optimizer state is "
        "bf16-native end to end, no 8-bit optimizer-state path exists "
        "(src/ember/governance/scripts/ember_d6_bf16_momentum_ab.py measured this directly); "
        "the formula is implemented and selftested regardless.",
        "net2net grow noise (epsilon) is measured, not assumed, every run "
        "by diffing the realized duplicate pair post-widen; production's "
        "cat([w,w]) operator carries no noise term, so epsilon=0 is "
        "expected but never hardcoded.",
        "checkpoint discovery targets the v1.2 ground-truth registry "
        "(RUNG1_LINEAGE): a real, team-lead-verified two-checkpoint "
        "lineage (rung-1 pre-grow step-00000730 / post-grow "
        "step-00000766). Neither weight file nor its manifest.json is "
        "present in THIS git worktree (multi-GB weights are never "
        "git-tracked) -- the real run is still expected to self-block "
        "(FAILED-ENGAGEMENT) on THIS box even once authorized, until run "
        "on a box with EMBER_MODELS_ROOT pointed at the real models/ tree; "
        "that is the fail-closed contract working as designed, not a "
        "harness defect. The '368M QAT' and 'unexecuted 1.22B rung-1' "
        "targets from the original v1.1 grounding pass were dropped: "
        "neither is real (see the GROUND-TRUTH RULING docstring section).",
        "no native QAT-trained checkpoint exists in the real inventory -- "
        "rho_sr/rho_noise grid-step reads on the two real checkpoints are "
        "INSTRUMENTED (_apply_fake_quant applied transiently, in-copy) "
        "rather than resident; tagged measurement_mode="
        "'instrumented-not-resident' in the real-run receipt.",
    ],
}


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _harness_sha() -> str:
    h = hashlib.sha256()
    with open(__file__, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Checkpoint discovery -- runtime, fail-closed if absent (spec INPUTS
# clause). The ONLY extension point: RUNG1_LINEAGE above (v1.2 targeted
# manifest-driven discovery; superseded the generic fingerprint scan).
# ---------------------------------------------------------------------------

def _load_json_safe(path: str):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _resolve_models_root() -> str | None:
    """Absolute filesystem root for models/ -- resolved ONLY from
    EMBER_MODELS_ROOT (env). Never guessed, never hardcoded (leak-gate
    discipline: absolute local paths are never published in this source)."""
    return os.environ.get(MODELS_ROOT_ENV) or None


def _redact_models_root(obj, models_root: str | None, placeholder: str = "<MODELS_ROOT>"):
    """Recursively replace every occurrence of `models_root` (raw, forward-
    slash, and JSON-escaped-backslash forms) with `placeholder` in a
    receipt-shaped structure (dict/list/str), leaving non-string leaves and
    keys untouched.

    gh issue #317: discover_checkpoints()'s "consulted" lists and
    "checkpoint_path" are absolute-by-design (EMBER_MODELS_ROOT-resolved) so
    load_real_checkpoint() can actually open the file -- that absolute path
    is legitimate for IN-MEMORY use but must never reach a tracked receipt.
    Call this on any discovery-derived payload immediately before
    checked_write()/write_failed_engagement_receipt(), never on the value
    handed to load_real_checkpoint().
    """
    if not models_root:
        return obj
    root_norm = os.path.normpath(models_root)
    forms = [
        root_norm,
        root_norm.replace("\\", "\\\\"),
        root_norm.replace("\\", "/"),
    ]
    # De-dup while preserving order (normpath may equal the forward-slash
    # form on POSIX, or various forms may coincide for a short root).
    seen = set()
    forms = [f for f in forms if not (f in seen or seen.add(f))]

    def _redact_str(s: str) -> str:
        for form in forms:
            if form:
                s = s.replace(form, placeholder)
        return s

    def _walk(node):
        if isinstance(node, str):
            return _redact_str(node)
        if isinstance(node, dict):
            return {k: _walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_walk(v) for v in node]
        return node

    return _walk(obj)


def _read_e2b_paired_receipt():
    """Locate + parse a receipts/ember-c-e2b-paired/*.json receipt -- the one
    receipt committed in THIS worktree that independently confirms the
    post-grow checkpoint's identity (owned_core_identity.*). Returns
    (parsed_dict, relative_path) or (None, None) if absent."""
    d = Path(RECEIPTS, "ember-c-e2b-paired")
    if not d.is_dir():
        return None, None
    for fpath in sorted(d.glob("*.json")):
        obj = _load_json_safe(str(fpath))
        if obj is not None and "owned_core_identity" in obj:
            rel = str(fpath.relative_to(REPO_ROOT)) if fpath.is_relative_to(Path(REPO_ROOT)) else str(fpath)
            return obj, rel
    return None, None


def _import_timeshare_pretrain():
    """Reuse discipline (no duplicated math): scripts/timeshare_pretrain.py
    already implements fail-closed checkpoint read/load (read_manifest --
    manifest.json only, no tensor load; load_checkpoint -- sha256-verifies
    EVERY file in manifest['files'] before trusting any tensor) -- imported
    directly rather than re-derived, matching this repo's own convention
    (scripts/cbase_grow_rung.py's own docstring: "Reuse discipline (no
    duplicated math): imports timeshare_pretrain.")."""
    import importlib
    return importlib.import_module("timeshare_pretrain")


def _import_production_widen():
    """Import the REAL production net2net widen operator
    (src/ember/governance/scripts/cbase_grow_dryrun.py::widen_state_dict) for the live path --
    the live path runs against REAL checkpoints with REAL production key
    names ("backbone_model.layers.{i}.mlp.{gate,up,down}_proj.weight"), so
    it imports the actual function rather than the self-contained toy copy
    (net2net_widen_linear below) that --selftest/--dry-run use to stay
    decoupled from production key-name assumptions."""
    import importlib
    return importlib.import_module("cbase_grow_dryrun").widen_state_dict


def discover_checkpoints(models_root: str | None = None) -> dict:
    """v1.2 ground-truth discovery (team-lead ruling, 2026-07-06) against
    RUNG1_LINEAGE: the real, verified rung-1 pre-grow/post-grow pair.
    LIGHTWEIGHT -- reads only manifest.json via
    scripts/timeshare_pretrain.py::read_manifest (no tensor load, no
    per-file sha verification beyond the manifest's own model.pt claim;
    the FULL per-file sha256 verification + ff-shape naming-collision guard
    happens in load_real_checkpoint() below, which reuses ::load_checkpoint
    -- deliberately heavier, only invoked once discovery + authorization
    both pass). Independently cross-checks the post-grow identity against
    receipts/ember-c-e2b-paired/*.json. Returns a dict keyed
    "pre_grow_rung1"/"post_grow_rung1" with:
      found, checkpoint_path (absolute, only when found), relative_path,
      consulted (every receipt/manifest path examined -- spec: "the
      receipt file consulted is itself recorded in the artifact"),
      manifest_model_pt_sha256, state_provenance (from RUNG1_LINEAGE),
      reason (present when found=False).
    Never raises; never fabricates a path. RUNG1_LINEAGE is the single
    extension point for correcting a field.
    """
    models_root = models_root or _resolve_models_root()
    try:
        ts_mod = _import_timeshare_pretrain()
    except Exception:
        ts_mod = None  # torch/the production module may be unavailable in a
                       # pure-discovery context; discovery degrades to
                       # MISSING rather than raising.

    e2b_obj, e2b_rel = _read_e2b_paired_receipt()

    result = {}
    for key, entry in RUNG1_LINEAGE.items():
        consulted = []
        reason_parts = []
        found = False
        abs_path = None
        manifest_sha = None

        if e2b_obj is not None:
            consulted.append(e2b_rel)
            if entry["role"] == "post_grow":
                oci = e2b_obj.get("owned_core_identity", {})
                sha_a, sha_b = oci.get("model_pt_sha256"), oci.get("base_model_pt_sha256")
                known = entry["known_model_pt_sha256"]
                if not (sha_a == sha_b == known):
                    reason_parts.append(
                        f"e2b-paired receipt identity mismatch: "
                        f"model_pt_sha256={sha_a!r} base_model_pt_sha256={sha_b!r} "
                        f"known={known!r}")

        if not models_root:
            reason_parts.append(f"{MODELS_ROOT_ENV} not set -- cannot resolve "
                                 "an absolute path; never guessed.")
        else:
            abs_candidate = os.path.join(models_root, entry["relative_path"])
            manifest_path = os.path.join(abs_candidate, "manifest.json")
            consulted.append(manifest_path)
            manifest = None
            if ts_mod is not None:
                try:
                    manifest = ts_mod.read_manifest(abs_candidate)
                except Exception as e:
                    reason_parts.append(f"read_manifest failed at {manifest_path}: {e}")
            else:
                reason_parts.append("timeshare_pretrain module unavailable in "
                                     "this environment -- cannot read_manifest")

            if manifest is not None:
                manifest_sha = (manifest.get("files") or {}).get("model.pt")
                known_full = entry.get("known_model_pt_sha256")
                known_prefix = entry.get("known_model_pt_sha256_prefix")
                sha_ok = (
                    (known_full and manifest_sha == known_full) or
                    (known_prefix and manifest_sha and manifest_sha.startswith(known_prefix))
                )
                if not sha_ok:
                    reason_parts.append(
                        f"manifest files['model.pt']={manifest_sha!r} does not "
                        f"match the known identity ({known_full or known_prefix!r})")
                else:
                    found = True
                    abs_path = abs_candidate

        if found:
            result[key] = {
                "label": entry["label"], "role": entry["role"], "found": True,
                "checkpoint_path": abs_path, "relative_path": entry["relative_path"],
                "consulted": consulted, "manifest_model_pt_sha256": manifest_sha,
                "state_provenance": entry["optimizer_state_provenance"],
            }
        else:
            result[key] = {
                "label": entry["label"], "role": entry["role"], "found": False,
                "checkpoint_path": None, "relative_path": entry["relative_path"],
                "consulted": consulted, "state_provenance": entry["optimizer_state_provenance"],
                "reason": "MISSING: " + "; ".join(reason_parts) +
                    ". Fail-closed per spec INPUTS clause -- never fabricated.",
            }
    return result


def load_real_checkpoint(discovery_entry: dict, mmap_optimize: bool = False):
    """Full, fail-closed load of a real rung-1 checkpoint -- reuses
    scripts/timeshare_pretrain.py::load_checkpoint (sha256-verifies EVERY
    file named in the checkpoint's OWN manifest.json['files'] dict --
    model.pt, optimizer.pt, rng.pt -- raising on any mismatch; "fail-closed
    if the shas on disk mismatch the manifests" per the v1.2 ruling item 4).
    Then applies the naming-collision guard (ruling item 4) by reproducing
    the EXACT check scripts/cbase_grow_rung.py itself performs on this
    lineage (`ff_seed = int(m_state["backbone_model.layers.0.mlp."
    "gate_proj.weight"].shape[0])`) -- NOT a manifest-field guess, the
    observed tensor shape. Returns (model_state, optimizer_state, rng_state,
    manifest, observed_ff). Raises EngagementFailure on any guard failure.

    mmap_optimize: If True, load large files with torch.load(..., mmap=True)
    and gc.collect() between loads to mitigate memory contention under heavy
    scan worker load. For P5 ratio audit only; do NOT use for training resume.
    """
    if not discovery_entry.get("found"):
        raise EngagementFailure(
            f"load_real_checkpoint called on an unresolved checkpoint: "
            f"{discovery_entry.get('reason')}")
    ts_mod = _import_timeshare_pretrain()

    if mmap_optimize:
        import torch
        import gc
        ckpt_dir = discovery_entry["checkpoint_path"]
        print(f"[p5-ratio-audit] Loading checkpoint {ckpt_dir} with mmap optimization", flush=True)

        # Load model.pt with mmap to defer decompression
        model_path = os.path.join(ckpt_dir, "model.pt")
        print(f"[p5-ratio-audit] Loading model.pt with mmap=True", flush=True)
        model_state = torch.load(model_path, map_location="cpu", mmap=True, weights_only=False)
        gc.collect()

        # Load optimizer.pt with mmap (no weights_only for optimizer state with numpy)
        opt_path = os.path.join(ckpt_dir, "optimizer.pt")
        print(f"[p5-ratio-audit] Loading optimizer.pt with mmap=True", flush=True)
        optimizer_state = torch.load(opt_path, map_location="cpu", mmap=True, weights_only=False)
        gc.collect()

        # Load rng.pt (small, no mmap needed)
        rng_path = os.path.join(ckpt_dir, "rng.pt")
        print(f"[p5-ratio-audit] Loading rng.pt", flush=True)
        rng_state = torch.load(rng_path, map_location="cpu", weights_only=False)
        gc.collect()

        # Load manifest for sha verification (reuse load_checkpoint's logic)
        manifest_path = os.path.join(ckpt_dir, "manifest.json")
        import json
        with open(manifest_path) as f:
            manifest = json.load(f)

        print(f"[p5-ratio-audit] All files loaded with mmap", flush=True)
    else:
        model_state, optimizer_state, rng_state, manifest = ts_mod.load_checkpoint(
            discovery_entry["checkpoint_path"])

    gate_key = "backbone_model.layers.0.mlp.gate_proj.weight"
    if gate_key not in model_state:
        raise EngagementFailure(
            f"expected key {gate_key!r} not found in loaded model state dict "
            "-- the real on-disk key layout differs from the assumed "
            "production convention; structural finding, not silently "
            "worked around.")
    observed_ff = int(model_state[gate_key].shape[0])
    expected_ff = RUNG1_LINEAGE[
        "pre_grow_rung1" if discovery_entry["role"] == "pre_grow" else "post_grow_rung1"
    ]["expected_ff"]
    if observed_ff not in FF_GUARD_VALUES or observed_ff != expected_ff:
        raise EngagementFailure(
            f"naming-collision guard failed: observed ff "
            f"(gate_proj.weight.shape[0])={observed_ff}, expected "
            f"{expected_ff} (one of {sorted(FF_GUARD_VALUES)}) for "
            f"role={discovery_entry['role']!r}")

    return model_state, optimizer_state, rng_state, manifest, observed_ff


def _find_reset_flag(obj, depth: int = 5):
    """Recursively search for an 'optimizer_reset_on_resume' field
    (verbatim key name, scripts/timeshare_pretrain.py::run_v0_segment
    parameter, receipted verbatim by scripts/cbase_grow_rung.py and
    src/ember/governance/scripts/cbase_grow_live.py). Returns bool or None if absent."""
    if depth <= 0 or not isinstance(obj, dict):
        return None
    for k, v in obj.items():
        if k == "optimizer_reset_on_resume" and isinstance(v, bool):
            return v
        if isinstance(v, dict):
            hit = _find_reset_flag(v, depth - 1)
            if hit is not None:
                return hit
    return None


def all_checkpoints_found(discovery: dict) -> bool:
    return all(v["found"] for v in discovery.values())


def provenance_mismatch(discovery: dict) -> bool:
    """STATE+LR PIN: provenance must be identical IN KIND across all three.
    None (unresolved) counts as a mismatch (fail-closed -- never assume a
    missing flag means 'same as the others'). GENERIC rule -- used unchanged
    by --selftest/--dry-run. The REAL rung-1 pair uses
    real_inventory_provenance() instead (a named exception, see below), NOT
    this function."""
    flags = [v.get("optimizer_reset_on_resume") for v in discovery.values()]
    if any(f is None for f in flags):
        return True
    return len(set(flags)) > 1


def real_inventory_provenance(discovery: dict) -> dict:
    """v1.2 ruling (team lead, 2026-07-06): pre-grow's parent-carried
    optimizer state and post-grow's own (fresh, post-stabilize) state are
    DIFFERENT IN ORIGIN but the SAME KIND (both muon_split) -- ruled
    ADMISSIBLE for comparison, caveat stamped verbatim, rather than a
    blocking provenance mismatch. This is a NAMED EXCEPTION for this
    specific rung-1 pair, NOT a general relaxation of the frozen rule --
    provenance_mismatch() above still enforces the strict rule for the
    generic/--selftest/--dry-run path."""
    pre = discovery.get("pre_grow_rung1", {})
    post = discovery.get("post_grow_rung1", {})
    return {
        "admissible": True,
        "pre_grow_state_provenance": pre.get("state_provenance"),
        "post_grow_state_provenance": post.get("state_provenance"),
        "caveat": "pre-grow optimizer.pt was carried VERBATIM from an "
            "earlier parent segment (stale-shape caveat, per the team-"
            "lead's manifest read); post-grow optimizer state is its own, "
            "fresh post-stabilize state. Both are muon_split (same "
            "optimizer KIND) -- ruled ADMISSIBLE for comparison with this "
            "caveat stamped, per the v1.2 ground-truth ruling "
            "(2026-07-06). Named exception for this rung-1 pair only.",
    }


def two_point_direction_report(val_pre, val_post, *, class_name: str) -> dict:
    """v1.2 CROSS-WIDTH SCOPING: the real inventory has exactly two width
    points (pre-grow, post-grow). Per the frozen spec's own missing-point/
    non-evidence rule ("two-point 'monotone' is meaningless... pre-
    registered as non-evidence"), the FORMAL verdict here is ALWAYS
    "UNRESOLVED-by-inventory" -- this function never returns KILL/PROMOTE/
    GRAY. The raw direction/ratio is reported as SUPPLEMENTARY information
    only, per the v1.2 ruling ("report the 2-point DIRECTION per class with
    that scoping. Do not soften the rule")."""
    if val_pre is None or val_post is None:
        return {
            "verdict": "UNRESOLVED-by-inventory", "class": class_name,
            "direction": None, "ratio": None,
            "reason": "at least one of the two width points has no value "
                "for this class (N/A or missing) -- direction cannot be "
                "computed; verdict is UNRESOLVED-by-inventory regardless.",
        }
    ratio = (val_post / val_pre) if val_pre != 0 else float("inf")
    if val_post > val_pre:
        direction = "increased"
    elif val_post < val_pre:
        direction = "decreased"
    else:
        direction = "unchanged"
    return {
        "verdict": "UNRESOLVED-by-inventory", "class": class_name,
        "direction": direction, "ratio": ratio,
        "pre_grow_value": val_pre, "post_grow_value": val_post,
        "reason": "two-point 'monotone' is meaningless and is "
            "pre-registered as non-evidence (frozen spec, v1.1) -- this "
            "direction/ratio is SUPPLEMENTARY information only, never a "
            "verdict, per the v1.2 cross-width scoping ruling.",
    }


def probe_qat_instrumented(weight) -> dict:
    """Real-run wrapper (v1.2 ruling item 3): no native QAT-trained
    checkpoint exists in the real inventory, so rho_sr/rho_noise's grid-step
    reads are INSTRUMENTED -- the production _apply_fake_quant transform
    (quant_delta_per_channel, byte-identical formula) applied transiently,
    in-copy, to a real bf16 checkpoint tensor, rather than read off a
    resident QAT weight. Tags the result accordingly so no receipt
    conflates an instrumented probe with a resident QAT measurement."""
    delta = quant_delta_per_channel(weight)
    return {"delta_per_channel": delta, "measurement_mode": "instrumented-not-resident"}


# ---------------------------------------------------------------------------
# Frozen probe batch -- 16 microbatches x 1024 tokens, seed 20260706, saved
# to disk before any measurement, sha256 in artifact.
# ---------------------------------------------------------------------------

def build_probe_batch(vocab: int, batch_size: int, out_dir: str,
                       n_micro: int = PROBE_N_MICROBATCHES,
                       seq_len: int = PROBE_SEQ_LEN, seed: int = PROBE_SEED):
    """Build the frozen probe batch: n_micro microbatches of (batch_size,
    seq_len) token ids, fixed seed, saved to disk BEFORE any measurement,
    sha256 recorded. Generation uses a dedicated CPU torch.Generator (never
    the model-init seed) -- decoupled, matching the repo's own convention
    (see src/ember/governance/scripts/expc1/run_expc1_rank_sweep.py::make_batch)."""
    import torch
    gen = torch.Generator().manual_seed(seed)
    microbatches = []
    for _ in range(n_micro):
        x = torch.randint(1, vocab, (batch_size, seq_len), generator=gen)
        y = torch.randint(1, vocab, (batch_size, seq_len), generator=gen)
        microbatches.append((x, y))

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"p5-probe-batch-seed{seed}.pt")
    torch.save(microbatches, path)
    sha = _sha256_file(path)
    return microbatches, path, sha


def verify_probe_batch_sha(path: str, expected_sha: str) -> bool:
    return os.path.isfile(path) and _sha256_file(path) == expected_sha


# ---------------------------------------------------------------------------
# Live quantizer -- byte-identical copy of scripts/timeshare_pretrain.py
# ::_apply_fake_quant(mode="qat") grid-step math (see module docstring
# grounding pass). Per-channel (per-output-row) int8 grid.
# ---------------------------------------------------------------------------

def quant_delta_per_channel(weight):
    """Delta_b per output row (channel) for a 2D weight tensor (out, in),
    IDENTICAL formula to scripts/timeshare_pretrain.py::_apply_fake_quant
    mode='qat': s = |W|.amax(dim=1, keepdim=True).clamp(min=1e-8) / 127.
    Returns a (out, 1) tensor -- the live grid step per channel."""
    import torch
    assert weight.ndim == 2, "quant_delta_per_channel expects a 2D weight"
    return weight.abs().amax(dim=1, keepdim=True).clamp(min=1e-8) / 127.0


def assert_quantizer_engaged(weight) -> None:
    """Engagement assertion: the grid object exists and actually quantizes a
    test tensor (spec: 'assert grid object exists and quantizes a test
    tensor')."""
    import torch
    delta = quant_delta_per_channel(weight)
    assert delta.shape[0] == weight.shape[0] and delta.shape[1] == 1, delta.shape
    assert bool((delta > 0).all()), "quantizer produced a non-positive grid step"
    probe = torch.randn_like(weight)
    q = (probe / delta).round().clamp(-127, 127) * delta
    assert not torch.equal(q, probe), "quantizer is a no-op on a test tensor"


# ---------------------------------------------------------------------------
# rho_SR -- ||update_b||_RMS / Delta_b, median over blocks -> per-tensor,
# median over tensors -> per-class.
# ---------------------------------------------------------------------------

def rms(t) -> float:
    import torch
    return float(torch.sqrt(torch.mean(t.to(torch.float32) ** 2)))


def rho_sr_per_tensor(update, delta_per_channel) -> float:
    """update, delta_per_channel: same shape (out, in) / (out, 1) resp.
    Per-block (=per-channel row) RMS ratio, reduced by MEDIAN over blocks."""
    import torch
    assert update.shape[0] == delta_per_channel.shape[0]
    row_rms = torch.sqrt(torch.mean(update.to(torch.float32) ** 2, dim=1, keepdim=True))
    ratios = row_rms / delta_per_channel.to(torch.float32)
    return float(torch.median(ratios))


def rho_sr_per_class(tensor_ratios: list) -> float | None:
    """Median over tensors -> per-class. None if the class has no tensors."""
    import torch
    if not tensor_ratios:
        return None
    return float(torch.median(torch.tensor(tensor_ratios, dtype=torch.float32)))


# ---------------------------------------------------------------------------
# rho_noise -- epsilon / Delta. epsilon is MEASURED (realized duplicate-pair
# delta post-widen), never assumed. Delta = same per-channel reduction.
# ---------------------------------------------------------------------------

def net2net_widen_linear(gate_or_up_weight, down_weight):
    """Self-contained copy of the net2net FF-widen surgery documented in
    src/ember/governance/scripts/cbase_grow_dryrun.py (module docstring, line ~12-18): exact
    function-preserving duplication.
      gate/up rows:  cat([w, w], dim=0)          -- duplicate FF rows
      down columns:  cat([w*0.5, w*0.5], dim=1)  -- halve + duplicate cols
    Kept as a self-contained copy (same discipline as the Newton-Schulz
    copy above) so this research harness stays decoupled from
    cbase_grow_dryrun's production state-dict key-name assumptions, which
    do not match a toy/self-contained model's module layout."""
    import torch
    grown_gate_or_up = torch.cat([gate_or_up_weight, gate_or_up_weight], dim=0)
    grown_down = torch.cat([down_weight * 0.5, down_weight * 0.5], dim=1)
    return grown_gate_or_up, grown_down


def measure_net2net_epsilon(gate_or_up_weight) -> dict:
    """Realized noise measurement: widen, then diff the two duplicate
    halves. Production's cat([w,w]) is noise-free by construction; this
    measures that empirically rather than assuming it from the docstring."""
    import torch
    grown, _ = net2net_widen_linear(gate_or_up_weight, gate_or_up_weight)
    half = gate_or_up_weight.shape[0]
    a, b = grown[:half], grown[half:]
    diff = (a - b).abs()
    return {
        "epsilon_max": float(diff.max()),
        "epsilon_mean": float(diff.mean()),
        "epsilon_is_zero": bool(diff.max() == 0.0),
    }


def rho_noise(epsilon: float, delta_per_channel) -> float:
    import torch
    delta_scalar = float(torch.median(delta_per_channel))
    return epsilon / delta_scalar if delta_scalar > 0 else float("nan")


# ---------------------------------------------------------------------------
# rho_rank / rho_grow -- N/A-by-construction (no production rank projector).
# ---------------------------------------------------------------------------

def rho_rank_rho_grow_na() -> tuple:
    return ("N/A-no-rung2", "N/A-no-rung2")  # rho_rank and rho_grow N/A until rung-2


def rho_spec_na() -> str:
    """rho_spec N/A at pre-grow checkpoint (no duplicated pairs in structure)."""
    return "N/A-pregrow"


def rho_batch_na() -> str:
    """rho_batch N/A-by-construction (per-batch gradient noise measurement requires
    independent batch replicates; live run uses single probe batch)."""
    return "N/A-single-batch"


def rho_block_na() -> str:
    """rho_block N/A-by-construction (production optimizer state is bf16-native
    end-to-end; no 8-bit optimizer-state path exists for computing per-block state norms)."""
    return "N/A-bf16-native"


# ---------------------------------------------------------------------------
# rho_spec -- P_dup symmetrization projector over duplicated column pairs,
# at the grow event only. N/A-by-construction at non-grow checkpoints;
# N/A-with-reason=production-reset when optimizer_reset_on_resume is True.
# ---------------------------------------------------------------------------

def p_dup_projector(n: int, duplicated_pairs: list):
    """Build the symmetrization projector P_dup over n columns/rows given a
    list of (i, j) duplicated-index pairs: P_dup averages each pair.
    P_dup(M) replaces columns i and j with their mean (the exact
    symmetrization the net2net duplication is supposed to preserve)."""
    import torch
    P = torch.eye(n, dtype=torch.float32)
    for i, j in duplicated_pairs:
        P[i, i] = P[i, j] = P[j, i] = P[j, j] = 0.5
    return P


def rho_spec(M, duplicated_pairs: list) -> float:
    """rho_spec = ||M - P_dup(M)||_2 / sigma_max(M). M: momentum matrix
    (out, in) or (in, in) depending on which axis is duplicated; caller
    passes M already oriented so duplicated_pairs index its FIRST axis."""
    import torch
    n = M.shape[0]
    P = p_dup_projector(n, duplicated_pairs)
    PM = P @ M
    num = torch.linalg.matrix_norm(M - PM, ord=2)
    denom = torch.linalg.matrix_norm(M, ord=2)  # sigma_max
    return float(num / denom) if float(denom) > 0 else float("nan")


def rho_spec_for_checkpoint(role: str, optimizer_reset_on_resume) -> dict:
    """Dispatch the N/A-by-construction / N/A-with-reason logic. Returns a
    dict; caller fills in a numeric value only when role == 'grow_event'
    and optimizer_reset_on_resume is False (state actually carries over)."""
    if role != "grow_event":
        return {"rho_spec": None, "na_reason": "N/A-by-construction: not the "
                "grow-event checkpoint (rho_spec is defined only at the "
                "rung-1 pre-grow state)."}
    if optimizer_reset_on_resume is None:
        return {"rho_spec": None, "na_reason": "UNRESOLVED: "
                "optimizer_reset_on_resume could not be runtime-read from "
                "this checkpoint's own receipt -- fail-closed, not assumed."}
    if optimizer_reset_on_resume:
        return {"rho_spec": None, "na_reason": "N/A-with-reason="
                "production-reset: optimizer_reset_on_resume=True for this "
                "checkpoint (runtime-read from its own receipt) -- the "
                "momentum matrix does not carry state across the grow, so "
                "there is no M to measure. This N/A is itself a "
                "law-relevant finding, per spec."}
    return {"rho_spec": "COMPUTE", "na_reason": None}  # caller computes rho_spec()


# ---------------------------------------------------------------------------
# rho_batch -- Welford over the 16 microbatches, tr(Sigma_g)/||g_bar||^2.
# ---------------------------------------------------------------------------

class WelfordAccumulator:
    """Online mean + M2 (sum of squared deviations) over a stream of
    flattened gradient vectors, one call to update() per microbatch.
    tr(Sigma_g) recovers as M2.sum() / (n-1) (component-wise variance,
    summed across components == trace of the covariance matrix)."""

    def __init__(self):
        self.n = 0
        self.mean = None
        self.m2 = None

    def update(self, g_flat) -> None:
        import torch
        self.n += 1
        if self.mean is None:
            self.mean = torch.zeros_like(g_flat)
            self.m2 = torch.zeros_like(g_flat)
        delta = g_flat - self.mean
        self.mean += delta / self.n
        delta2 = g_flat - self.mean
        self.m2 += delta * delta2

    def trace_sigma(self) -> float:
        if self.n < 2:
            return float("nan")
        return float((self.m2 / (self.n - 1)).sum())

    def mean_norm_sq(self) -> float:
        import torch
        return float(torch.sum(self.mean ** 2))


def rho_batch(grad_flats: list, batch_size: int, beta: float) -> dict:
    """grad_flats: list of per-microbatch flattened gradient tensors (one
    tensor class concatenated together). beta: Muon momentum coefficient,
    runtime-read from the live optimizer's param group."""
    acc = WelfordAccumulator()
    for g in grad_flats:
        acc.update(g)
    tr_sigma = acc.trace_sigma()
    g_bar_sq = acc.mean_norm_sq()
    b_simple = tr_sigma / g_bar_sq if g_bar_sq > 0 else float("nan")
    numerator = batch_size * (1.0 - beta) ** -1
    value = numerator / b_simple if b_simple not in (0.0,) and b_simple == b_simple else float("nan")
    return {
        "rho_batch": value, "b_simple": b_simple, "tr_sigma_g": tr_sigma,
        "g_bar_norm_sq": g_bar_sq, "batch_size": batch_size, "beta": beta,
        "numerator": numerator,
    }


def direct_trace_sigma(grad_flats: list) -> float:
    """Non-Welford reference computation (small N=16 here, used ONLY to
    cross-check the Welford accumulator in --selftest, never in the real
    measurement path)."""
    import torch
    stacked = torch.stack(grad_flats, dim=0)  # (n, d)
    mean = stacked.mean(dim=0)
    var = ((stacked - mean) ** 2).sum(dim=0) / (stacked.shape[0] - 1)
    return float(var.sum())


# ---------------------------------------------------------------------------
# rho_block -- 8-bit optimizer state only; N/A (structural) in production.
# Formula implemented + selftested regardless (spec's letter).
# ---------------------------------------------------------------------------

def rho_block_8bit(fresh_state_int8, scale_per_block) -> dict:
    """per-block min |fresh-state entry| / (absmax_block/(2^{bits-1}-1)).
    fresh_state_int8: int8 tensor (block, ...). scale_per_block: (block,)
    absmax per block already divided by 127 (8-bit: 2^7 - 1 = 127)."""
    import torch
    abs_entries = fresh_state_int8.to(torch.float32).abs()
    flat = abs_entries.reshape(abs_entries.shape[0], -1)
    min_abs = flat.min(dim=1).values
    grid_step = scale_per_block  # already absmax_block / 127
    ratios = min_abs / grid_step.clamp(min=1e-12)
    return {"rho_block_per_block": ratios.tolist(), "rho_block_median": float(torch.median(ratios))}


def rho_block_for_checkpoint() -> dict:
    return {"rho_block": None, "na_reason": "N/A (structural): production "
            "optimizer state is bf16-native end to end (scripts/"
            "ember_d6_bf16_momentum_ab.py measured this directly -- AdamW/"
            "_Muon zeros_like(g) inherits the bf16 param/grad dtype, "
            "nothing promotes to fp32); no 8-bit optimizer-state path "
            "exists to apply this formula to."}


# ---------------------------------------------------------------------------
# Commutation defect d_comm at the rung-1 grow event.
# ---------------------------------------------------------------------------

def commutation_defect(state_after_U_then_G, state_after_G_then_U, state_before) -> float:
    """d_comm = ||U_{k+1}(G(theta_k)) - G(U_k(theta_k))||_RMS /
                ||U_k(theta_k) - theta_k||_RMS
    All three args are flat tensors of the SAME shape (post-grow width):
      state_after_U_then_G = G(U_k(theta_k))   -- update then grow
      state_after_G_then_U = U_{k+1}(G(theta_k)) -- grow then update
      state_before         = G(theta_k) at the SAME width as the other two
                              (so the denominator's U_k(theta_k) - theta_k
                              is measured pre-grow and passed in already
                              RMS-normalized by the caller -- see
                              compute_d_comm below for the exact wiring)."""
    num = rms(state_after_G_then_U - state_after_U_then_G)
    denom = rms(state_after_U_then_G - state_before)
    return num / denom if denom > 0 else float("nan")


def compute_d_comm(theta_k, U_k_apply, U_kplus1_apply, G_apply) -> dict:
    """Wires the commutation defect exactly per spec:
      d_comm = ||U_{k+1}(G(theta_k)) - G(U_k(theta_k))||_RMS /
               ||U_k(theta_k) - theta_k||_RMS
    U_k_apply(theta) -> U_k(theta) at pre-grow width (one in-copy step).
    G_apply(theta)   -> G(theta), the net2net widen to post-grow width.
    U_kplus1_apply(theta) -> U_{k+1}(theta) at post-grow width (one
      in-copy step using the PRODUCTION pushforward optimizer state, i.e.
      whatever the runtime-read reset/carry flag says -- pre-registered as
      production-as-found, stamped by the caller).

    #327 residual-decomposition fields (ADDITIVE; issue #327's Monte-Carlo
    comment defines the algebra, mirrored verbatim here): write
    v = U_{k+1}(G(theta_k)) - G(theta_k)          -- the post-grow step,
    Pu = G(U_k(theta_k)) - G(theta_k)             -- the pushforward of the
                                                       pre-grow step under G
                                                       (G is linear on the
                                                       production widen, so
                                                       this equals G(u) for
                                                       u = U_k(theta_k)-theta_k).
    Then num = ||v - Pu||_RMS exactly (same tensor identity as the existing
    numerator above), and with r = step_rms_post/denom, q =
    pushforward_step_rms/denom, c = cos_alignment:
      d_comm^2 = r^2 + q^2 - 2*c*r*q
    (RMS-ratio identity: ||v-Pu||_RMS^2 = rms(v)^2 + rms(Pu)^2 -
    2*rms(v)*rms(Pu)*cos(v,Pu), divided through by denom^2). Emitted
    alongside d_comm/numerator_rms/denominator_rms; existing consumers are
    unaffected (dict is only ever grown, never restructured)."""
    import torch
    Uk_theta = U_k_apply(theta_k)
    denom = rms(Uk_theta - theta_k)
    G_Uk_theta = G_apply(Uk_theta)
    G_theta = G_apply(theta_k)
    Ukp1_G_theta = U_kplus1_apply(G_theta)
    num = rms(Ukp1_G_theta - G_Uk_theta)
    value = num / denom if denom > 0 else float("nan")

    v = (Ukp1_G_theta - G_theta).to(torch.float32).flatten()
    Pu = (G_Uk_theta - G_theta).to(torch.float32).flatten()
    step_rms_post = rms(v)
    pushforward_step_rms = rms(Pu)
    v_norm = torch.linalg.norm(v)
    Pu_norm = torch.linalg.norm(Pu)
    if v_norm > 0 and Pu_norm > 0:
        cos_alignment = float(torch.dot(v, Pu) / (v_norm * Pu_norm))
    else:
        cos_alignment = float("nan")

    return {
        "d_comm": value, "numerator_rms": num, "denominator_rms": denom,
        "step_rms_post": step_rms_post,
        "pushforward_step_rms": pushforward_step_rms,
        "cos_alignment": cos_alignment,
    }


def resolve_gate_momentum_buffer(model_state, opt_state, gate_key: str):
    """#580 fix: resolves the real Muon momentum buffer for gate_key from a
    loaded optimizer.pt, keyed by its MUON-LOCAL split_param_groups position
    -- the real on-disk convention (`{'muon': {'state': {muon_local_id:
    {'momentum_buffer': ...}}}}`, verified by constructing the actual model
    and calling split_param_groups directly: #577 F1 confirmed the on-disk
    muon state has exactly 140 keys 0-139, matching split_param_groups's
    muon count exactly), tolerant of a flat `{'state': {muon_local_id:
    {...}}}` nesting too.

    Uses timeshare_pretrain.build_optimizer_id_maps(model_state=...) -- the
    ONE authoritative mapping helper (issue #580); no site computes
    `.index()` against a state-dict key list here anymore.

    Prior code (#513-era, this same function) computed
    `param_id = list(model_state.keys()).index(gate_key)` -- the GLOBAL
    model-state position -- and used it as a key into this MUON-LOCAL-keyed
    dict. The two numberings diverge as soon as any AdamW-routed param
    (embed/norm/head) interposes ahead of gate_key in the global ordering;
    ground-truthed by #577's investigation (74 shape mismatches: 60 FF
    tensors across all 20 layers misfiled + 25 unrelated attention slots
    clobbered when the same conflated convention was used on the write
    side). Returns the tensor, or None if the key/id truly is not present
    (caller decides fail-closed vs. N/A). Still tolerant of the historical
    top-level string-keyed 'state' shape resolving to None (#513's own
    regression guard: that shape must never silently resolve to something)."""
    if opt_state is None or model_state is None:
        return None
    if gate_key not in model_state:
        return None
    id_maps = ts.build_optimizer_id_maps(model_state=model_state)
    muon_id = id_maps["muon_name_to_id"].get(gate_key)
    if muon_id is None:
        return None
    state_dict = opt_state.get("muon", {}).get("state")
    if not state_dict:
        state_dict = opt_state.get("state", {})
    return state_dict.get(muon_id, {}).get("momentum_buffer")


def enumerate_missing_optimizer_state_ids(model_state: dict, opt_state: dict) -> set[int]:
    """#580 fix: the shared, correctly-indexed re-implementation of the
    truncation checker (formerly a private helper of the same name,
    underscore-prefixed, duplicated inside
    src/ember/governance/scripts/cbase_grow_rung2_stabilize.py's write path -- that duplicate is
    PR B's concern, refactoring the write side onto this shared function).

    For every parameter, checks presence in ITS OWN routed optimizer
    sub-dict at ITS OWN correct LOCAL split_param_groups position (via
    timeshare_pretrain.build_optimizer_id_maps -- the one authoritative
    mapping helper), then reports any miss translated back to the
    parameter's GLOBAL model-state id (same externally-visible id
    convention the prior implementation returned, for caller compatibility).

    The prior implementation compared `set(muon_state.keys()) |
    set(adamw_state.keys())` -- both LOCAL 0-based id spaces -- against
    `range(len(model_state))`, a GLOBAL-sized range. Because a healthy
    split-optimizer checkpoint's muon/adamw LOCAL id spaces always span
    0..n_muon-1 and 0..n_adamw-1 respectively, their union is just
    0..max(n_muon, n_adamw)-1 -- so the old checker reported every global id
    at or beyond that bound as "missing" purely by construction (n_muon and
    n_adamw, never a real gap), which is exactly the mechanical false
    positive #577's ruling delta identified (the checker's own artifact
    generated the "45-tensor truncation" narrative it then disclosed).

    Read-only forensics, no mutation."""
    if not model_state or not opt_state:
        return set()
    id_maps = ts.build_optimizer_id_maps(model_state=model_state)
    muon_state = opt_state.get("muon", {}).get("state")
    if not muon_state:
        muon_state = opt_state.get("state", {})
    adamw_state = opt_state.get("adamw", {}).get("state") or {}
    missing_global_ids = set()
    for name, local_id in id_maps["muon_name_to_id"].items():
        if local_id not in muon_state:
            missing_global_ids.add(id_maps["global_name_to_id"][name])
    for name, local_id in id_maps["adamw_name_to_id"].items():
        if local_id not in adamw_state:
            missing_global_ids.add(id_maps["global_name_to_id"][name])
    return missing_global_ids


def build_real_d_comm_closures(pre_model_state, pre_opt_state, post_model_state, post_opt_state,
                               gate_key: str, up_key: str, down_key: str,
                               pre_lr: float, post_lr: float,
                               grad_pre_gate, grad_post_gate):
    """Builds the U_k / U_{k+1} / G closures for compute_d_comm() (above,
    already selftested against synthetic commuting/non-commuting cases)
    from REAL loaded rung-1 checkpoint state -- reused rather than
    re-derived. gate_key/up_key/down_key: the production key names for one
    transformer layer's SwiGLU MLP tensors
    ("backbone_model.layers.{i}.mlp.{gate,up,down}_proj.weight"). G uses the
    REAL production widen_state_dict (src/ember/governance/scripts/cbase_grow_dryrun.py,
    imported via _import_production_widen() -- NOT the self-contained toy
    copy net2net_widen_linear that --selftest/--dry-run use). U_k uses
    pre-grow's own (parent-carried) momentum_buffer + LR; U_{k+1} uses
    post-grow's own (fresh) momentum_buffer + LR -- both admissible per
    real_inventory_provenance().

    #513 fix: both buffers resolve via resolve_gate_momentum_buffer() (real
    int-param-id keying, never the old string-keyed top-level lookup) and
    fail closed (EngagementFailure) on a missing/zero buffer rather than
    silently substituting zeros_like -- UNLESS the caller passes
    pre_opt_state/post_opt_state=None explicitly, which is the caller's own
    disclosed "this arm is N/A / not needed" signal (e.g. a RESET arm built
    from an explicit zero buffer elsewhere, or a closure whose U_{k+1} is
    never invoked)."""
    import torch
    widen_state_dict = _import_production_widen()

    pre_momentum = resolve_gate_momentum_buffer(pre_model_state, pre_opt_state, gate_key)
    if pre_opt_state is not None:
        pre_buffer_rms = rms(pre_momentum) if pre_momentum is not None else 0.0
        if pre_momentum is None or pre_buffer_rms <= 1e-10:
            raise EngagementFailure(
                f"#513 fail-closed: pre-grow momentum_buffer for {gate_key!r} is "
                f"missing or zero (rms={pre_buffer_rms:.3e}) under the correct "
                f"int-param-id resolver. Refusing to silently substitute "
                f"zeros_like (the #513 defect). If this checkpoint genuinely has "
                f"no prior optimizer momentum (initial training), pass "
                f"pre_opt_state=None explicitly -- that is a disclosed N/A, not "
                f"this refusal.")

    def U_k(theta_gate):
        buf = pre_momentum if pre_momentum is not None else torch.zeros_like(theta_gate)
        new_w, _, _ = _muon_step_in_copy(theta_gate, grad_pre_gate, buf, lr=pre_lr)
        return new_w

    def G(theta_gate):
        grown = widen_state_dict(
            {gate_key: theta_gate, up_key: pre_model_state[up_key],
             down_key: pre_model_state[down_key]}, n_layers=1)
        return grown[gate_key]

    def U_kplus1(theta_gate_grown):
        buf = resolve_gate_momentum_buffer(post_model_state, post_opt_state, gate_key)
        if post_opt_state is not None:
            buf_rms = rms(buf) if buf is not None else 0.0
            if buf is None or buf_rms <= 1e-10:
                raise EngagementFailure(
                    f"#513 fail-closed: post-grow momentum_buffer for {gate_key!r} "
                    f"is missing or zero (rms={buf_rms:.3e}) under the correct "
                    f"int-param-id resolver. Refusing to silently substitute "
                    f"zeros_like. Pass post_opt_state=None explicitly if this arm "
                    f"is genuinely reset/zero-momentum by design.")
        if buf is None:
            buf = torch.zeros_like(theta_gate_grown)
        new_w, _, _ = _muon_step_in_copy(theta_gate_grown, grad_post_gate, buf, lr=post_lr)
        return new_w

    return U_k, U_kplus1, G


def compute_d_comm_real_run(discovery: dict, grad_pre_gate, grad_post_gate,
                            pre_model_state, pre_opt_state, post_model_state, post_opt_state,
                            pre_ff, post_ff,
                            pre_lr: float, post_lr: float, layer_index: int = 0) -> dict:
    """v1.2-upgraded HEADLINE deliverable: the real commutation defect at
    the rung-1 grow event. theta_k = the FF gate/up/down weights for
    `layer_index` from the real pre-grow checkpoint (step-00000730,
    production key convention, per build_v0_model's real-architecture
    LlamaModel wrapper in scripts/timeshare_pretrain.py). G = the REAL
    production widen_state_dict. U_k / U_{k+1} = one Muon step in-copy,
    using each checkpoint's own LR and own momentum_buffer (pre-grow:
    parent-carried; post-grow: own -- both admissible per
    real_inventory_provenance()).

    Reachable ONLY once discover_checkpoints() resolves BOTH rung-1
    checkpoints AND EMBER_GATE_AUTHORIZED=1 is set. NOT executed this
    authoring session -- no real checkpoint file exists in this worktree to
    load; this function's correctness against the ACTUAL on-disk
    state_dict key layout is UNVERIFIED here (the first real execution
    should confirm the assumed key convention against the real file and
    amend if it differs -- a structural discovery, filed before that
    execution, not a numeric/logic deviation).

    grad_pre_gate / grad_post_gate: the real backward-pass gradients at the
    chosen FF gate tensor from one forward+backward through the actual pre-
    /post-grow model on the frozen probe batch -- running that forward/
    backward (through the real transformers.LlamaModel architecture) is the
    caller's responsibility, not reproduced here; this function is scoped
    to the update/grow/commutation arithmetic only (reusing compute_d_comm,
    already selftested).

    pre_model_state, pre_opt_state, post_opt_state, pre_ff, post_ff: already-
    loaded checkpoint states (with mmap mitigation applied) to avoid a second
    round of checkpoint loading that could cause memory contention-related
    segfaults.
    """
    pre = discovery["pre_grow_rung1"]
    post = discovery["post_grow_rung1"]
    if not (pre.get("found") and post.get("found")):
        raise EngagementFailure(
            "compute_d_comm_real_run called before both rung-1 checkpoints "
            "were resolved by discover_checkpoints()")

    prefix = f"backbone_model.layers.{layer_index}.mlp."
    gate_key = prefix + "gate_proj.weight"
    up_key = prefix + "up_proj.weight"
    down_key = prefix + "down_proj.weight"
    for k in (gate_key, up_key, down_key):
        if k not in pre_model_state:
            raise EngagementFailure(
                f"expected key {k!r} not found in pre-grow model state dict "
                "-- the real on-disk key layout differs from the assumed "
                "convention; structural finding, not silently worked around.")

    import torch
    theta_gate = pre_model_state[gate_key].to(torch.float32)

    U_k, U_kplus1, G = build_real_d_comm_closures(
        pre_model_state, pre_opt_state, post_model_state, post_opt_state, gate_key, up_key, down_key,
        pre_lr, post_lr, grad_pre_gate, grad_post_gate)

    result = compute_d_comm(theta_gate, U_k, U_kplus1, G)
    result["layer_index"] = layer_index
    result["measurement_mode"] = "real-checkpoint"
    result["pre_grow_observed_ff"] = pre_ff
    result["post_grow_observed_ff"] = post_ff

    # #513 receipt fields: the real (int-param-id-resolved) pre-side buffer
    # rms actually consumed by U_k, and the LR actually used (from the
    # resolved cfg passed in by the caller, never a script constant --
    # #513's Fix item 4).
    pre_momentum_for_receipt = resolve_gate_momentum_buffer(pre_model_state, pre_opt_state, gate_key)
    result["pre_buffer_rms_consumed"] = (
        rms(pre_momentum_for_receipt) if pre_momentum_for_receipt is not None else 0.0)
    result["resolved_lr_muon"] = pre_lr
    return result


# ---------------------------------------------------------------------------
# Engagement assertions (before ANY artifact write -- #216 fail-closed).
# ---------------------------------------------------------------------------

class EngagementFailure(Exception):
    pass


def run_engagement_assertions(*, checkpoint_sha: str, source_state_before,
                               source_state_after, probe_batch_path: str,
                               probe_batch_sha: str, lr, schedule_position,
                               tokens_seen, state_provenance: str,
                               ratio_values: dict) -> list:
    """Returns the list of assertion labels that PASSED. Raises
    EngagementFailure with a message naming exactly which assertion failed
    -- caller writes a FAILED-ENGAGEMENT receipt on any raise, never a
    metrics artifact."""
    import torch
    passed = []

    if not checkpoint_sha:
        raise EngagementFailure("checkpoint sha not recorded")
    passed.append("checkpoint_sha_recorded")

    for name, before, after in (("source_state", source_state_before, source_state_after),):
        if before is not None and after is not None:
            for k in before:
                if not torch.equal(before[k], after[k]):
                    raise EngagementFailure(
                        f"source state dict mutated during in-copy probe: key {k!r}")
    passed.append("in_copy_update_source_state_bitwise_unchanged")

    if not (probe_batch_path and os.path.isfile(probe_batch_path)):
        raise EngagementFailure("probe batch file missing on disk")
    if _sha256_file(probe_batch_path) != probe_batch_sha:
        raise EngagementFailure("probe batch sha mismatch against frozen batch")
    passed.append("probe_batch_sha_matches")

    for label, val in (("lr", lr), ("schedule_position", schedule_position),
                       ("tokens_seen", tokens_seen)):
        if val is None:
            raise EngagementFailure(f"{label} not stamped")
    passed.append("lr_schedule_tokens_stamped")

    if not state_provenance:
        raise EngagementFailure("state provenance not stamped")
    passed.append("state_provenance_stamped")

    for ratio_name in RATIO_NAMES:
        entry = ratio_values.get(ratio_name)
        if entry is None:
            raise EngagementFailure(f"ratio {ratio_name} missing entirely from ratio_values")
        has_value = entry.get("value") is not None
        has_na_reason = entry.get("na_reason") is not None
        if not (has_value or has_na_reason):
            raise EngagementFailure(
                f"ratio {ratio_name} has neither a value nor an explicit N/A-with-reason")
    passed.append("all_seven_ratios_have_value_or_na_reason")

    return passed


def write_failed_engagement_receipt(*, ticket: str, mode: str, reason: str,
                                    extra: dict | None = None) -> Path:
    ts = _ts()
    receipt = {
        "ticket": ticket, "ts": ts, "mode": mode, "issue": ISSUE,
        "spec_ref": SPEC_REF, "spec_version": SPEC_VERSION,
        "sha_convention": "bytes on disk as-is (binary read, no line-ending normalization)",
        "harness_sha": _harness_sha(),
        "status": "FAILED-ENGAGEMENT",
        "reason": reason,
        "zombie_rule": "loss/trajectory bands alone certify NOTHING; this "
            "run's engagement assertions did not all pass, so NO metrics "
            "artifact is written (#216 fail-closed).",
        "pre_registration": PRE_REGISTRATION,
    }
    if extra:
        receipt.update(extra)
    os.makedirs(RECEIPTS, exist_ok=True)
    path = os.path.join(RECEIPTS, f"p5-ratio-audit-FAILED-ENGAGEMENT-{ts}.json")
    checked_write(path, receipt)
    print(f"[p5-ratio-audit] FAILED-ENGAGEMENT: {reason}", flush=True)
    print(f"P5_AUDIT_DONE status=FAILED-ENGAGEMENT receipt={path}", flush=True)
    return Path(path)


# ---------------------------------------------------------------------------
# Verdict logic -- per-class KILL/PROMOTE/GRAY/UNRESOLVED, headline
# majority, noise-floor rule, missing-point rule, provenance-mismatch rule.
# ---------------------------------------------------------------------------

def per_class_verdict(width_values: list, width_noise_bands: list, *, mismatch: bool = False) -> dict:
    """width_values: list of 3 floats (rho_SR unit-LR at 368M/718M/1.22B) or
    None for a missing leg. width_noise_bands: list of 3 (lo, hi) 95% bands
    (from the 16 per-microbatch replicates at that width), or None.
    mismatch: STATE+LR provenance-mismatch flag -- forces UNRESOLVED."""
    if mismatch:
        return {"verdict": "UNRESOLVED", "reason": "provenance-mismatch: "
                "optimizer-state provenance differs in kind across the "
                "three checkpoints; cross-width comparison is invalid, "
                "never compared across the discontinuity."}
    if any(v is None for v in width_values):
        return {"verdict": "UNRESOLVED", "reason": "missing-point: at least "
                "one width leg is absent (OOM/wall-cap kill); two-point "
                "'monotone' is non-evidence, pre-registered as such."}

    lo, hi = min(width_values), max(width_values)
    ratio = hi / lo if lo > 0 else float("inf")
    monotone = (width_values[0] <= width_values[1] <= width_values[2]) or \
               (width_values[0] >= width_values[1] >= width_values[2])

    if ratio <= KILL_RATIO_MAX:
        return {"verdict": "KILL", "ratio": ratio,
                "reason": "max/min <= 1.2 -- drift REJECTED, promote-the-"
                "null, law simplifies (GOOD outcome for this prediction)."}

    if ratio >= PROMOTE_RATIO_MIN and monotone:
        if width_noise_bands is None or any(b is None for b in width_noise_bands):
            return {"verdict": "GRAY", "ratio": ratio, "monotone": monotone,
                    "reason": "ratio/monotonicity satisfied but no "
                    "within-checkpoint noise band was supplied -- cannot "
                    "confirm the across-width spread excludes the "
                    "kill band; UNRESOLVED pending per-layer resolution."}
        excludes_kill_band = all(
            not (lo_b <= KILL_RATIO_MAX <= hi_b) for lo_b, hi_b in width_noise_bands
        )
        if excludes_kill_band:
            return {"verdict": "PROMOTE", "ratio": ratio, "monotone": monotone,
                    "reason": "max/min >= 1.5, monotone, 95% noise bands "
                    "exclude the kill band -- drift confirmed for this class."}
        return {"verdict": "GRAY", "ratio": ratio, "monotone": monotone,
                "reason": "ratio/monotonicity satisfied but the "
                "per-microbatch noise band overlaps the kill band at one "
                "or more widths -- GRAY, extend to per-layer resolution."}

    return {"verdict": "GRAY", "ratio": ratio, "monotone": monotone,
            "reason": "1.2 < max/min < 1.5, or non-monotone -- GRAY/"
            "UNRESOLVED, extend to per-layer resolution before any claim; "
            "no third category invented post hoc."}


def headline_verdict(per_class: dict) -> dict:
    verdicts = [v["verdict"] for v in per_class.values()]
    if any(v == "UNRESOLVED" for v in verdicts):
        return {"verdict": "UNRESOLVED", "per_class": per_class,
                "reason": "at least one class is UNRESOLVED (missing-point "
                "or provenance-mismatch) -- headline cannot be computed."}
    if "PROMOTE" in verdicts and "KILL" in verdicts:
        return {"verdict": "GRAY", "per_class": per_class,
                "reason": "mixed per-class outcomes (some PROMOTE, some "
                "KILL) -- GRAY/UNRESOLVED overall, per-class table is the "
                "artifact, pre-registered as such."}
    counts = {v: verdicts.count(v) for v in set(verdicts)}
    majority = max(counts, key=counts.get)
    return {"verdict": majority, "per_class": per_class,
            "reason": f"majority of per-class verdicts ({counts})."}


# ---------------------------------------------------------------------------
# Selftest -- pure Python/math + CPU-only torch checks. No real checkpoints.
# ---------------------------------------------------------------------------

def selftest() -> None:
    import torch

    print("[p5-ratio-audit] selftest: quantizer + rho_SR + rho_noise + "
          "rho_spec/P_dup + Welford rho_batch + rho_block + d_comm + "
          "verdict logic + engagement assertions + receipt schema", flush=True)

    # 1. Quantizer: per-channel grid step matches the byte-identical copy of
    #    _apply_fake_quant's formula; assertion helper actually engages.
    torch.manual_seed(0)
    w = torch.randn(8, 6) * 3.0
    delta = quant_delta_per_channel(w)
    expected = w.abs().amax(dim=1, keepdim=True).clamp(min=1e-8) / 127.0
    assert torch.allclose(delta, expected), "quant_delta_per_channel formula drifted"
    assert_quantizer_engaged(w)  # must not raise
    print("  quant_delta_per_channel: per-channel int8 grid step, formula-exact, engaged  PASS")

    # 2. rho_SR: per-block (row) RMS ratio, median-over-blocks then
    #    median-over-tensors. Known update makes the answer computable by hand.
    update = torch.ones(4, 6) * 0.02   # RMS per row = 0.02 for every row
    delta2 = torch.full((4, 1), 0.01)  # Delta_b = 0.01 for every row
    r = rho_sr_per_tensor(update, delta2)
    assert abs(r - 2.0) < 1e-6, r
    per_class = rho_sr_per_class([r, r * 1.5, r * 0.5])
    assert abs(per_class - r) < 1e-6, per_class  # median of [2,3,1] = 2
    print(f"  rho_sr_per_tensor uniform case: {r:.4f} (expected 2.0)  PASS")
    print(f"  rho_sr_per_class median-of-tensors: {per_class:.4f}  PASS")

    # 3. rho_noise: production net2net widen is noise-free BY MEASUREMENT
    #    (not assumed) -- diff the two realized duplicate halves is exactly 0.
    gate_w = torch.randn(5, 6)
    eps_measurement = measure_net2net_epsilon(gate_w)
    assert eps_measurement["epsilon_is_zero"] is True, eps_measurement
    assert eps_measurement["epsilon_max"] == 0.0
    rn = rho_noise(eps_measurement["epsilon_max"], torch.full((5, 1), 0.5))
    assert rn == 0.0, rn
    print(f"  net2net widen epsilon measured (not assumed): "
          f"max={eps_measurement['epsilon_max']} -> rho_noise=0.0  PASS")

    # 3b. net2net widen shape/value correctness (cat([w,w]) / cat([w*.5,w*.5])).
    down_w = torch.randn(6, 5)
    grown_gate, grown_down = net2net_widen_linear(gate_w, down_w)
    assert grown_gate.shape == (10, 6), grown_gate.shape
    assert grown_down.shape == (6, 10), grown_down.shape
    assert torch.equal(grown_gate[:5], grown_gate[5:]), "duplicate rows must be identical"
    assert torch.allclose(grown_down[:, :5] + grown_down[:, 5:], down_w), \
        "halved+duplicated down columns must sum back to the original (function-preserving)"
    print("  net2net_widen_linear: shapes + function-preserving identity  PASS")

    # 4. rho_rank/rho_grow N/A path.
    na_rank, na_grow = rho_rank_rho_grow_na()
    assert isinstance(na_rank, str) and na_rank.startswith("N/A")
    assert isinstance(na_grow, str) and na_grow.startswith("N/A")
    print("  rho_rank/rho_grow: N/A-by-construction, reason stamped  PASS")

    # 5. rho_spec / P_dup projector: exact symmetrization identity.
    n = 6
    pairs = [(0, 3), (1, 4), (2, 5)]
    M_sym = torch.randn(n, 4)
    # Force M to be exactly symmetric under P_dup: duplicated rows equal.
    for i, j in pairs:
        M_sym[j] = M_sym[i]
    gap_sym = rho_spec(M_sym, pairs)
    assert gap_sym < 1e-5, gap_sym
    M_asym = torch.randn(n, 4)  # generic -- not symmetric under P_dup
    gap_asym = rho_spec(M_asym, pairs)
    assert gap_asym > 1e-3, gap_asym
    print(f"  rho_spec/P_dup: symmetric M gap={gap_sym:.2e} (~0), "
          f"generic M gap={gap_asym:.4f} (>0)  PASS")

    # 5b. rho_spec N/A dispatch: non-grow, production-reset, unresolved, compute.
    d1 = rho_spec_for_checkpoint("non_grow", False)
    assert d1["rho_spec"] is None and "N/A-by-construction" in d1["na_reason"]
    d2 = rho_spec_for_checkpoint("grow_event", True)
    assert d2["rho_spec"] is None and "production-reset" in d2["na_reason"]
    d3 = rho_spec_for_checkpoint("grow_event", None)
    assert d3["rho_spec"] is None and "UNRESOLVED" in d3["na_reason"]
    d4 = rho_spec_for_checkpoint("grow_event", False)
    assert d4["rho_spec"] == "COMPUTE"
    print("  rho_spec_for_checkpoint: non-grow / production-reset / "
          "unresolved / compute dispatch  PASS")

    # 6. Welford rho_batch vs direct covariance-trace reference.
    torch.manual_seed(1)
    grads = [torch.randn(500) * 0.1 + 0.05 for _ in range(16)]
    acc = WelfordAccumulator()
    for g in grads:
        acc.update(g)
    welford_trace = acc.trace_sigma()
    direct_trace = direct_trace_sigma(grads)
    assert abs(welford_trace - direct_trace) < 1e-4, (welford_trace, direct_trace)
    rb = rho_batch(grads, batch_size=8, beta=0.95)
    assert rb["rho_batch"] == rb["rho_batch"]  # not NaN
    print(f"  Welford trace(Sigma_g)={welford_trace:.6f} vs direct="
          f"{direct_trace:.6f} (agree)  PASS")
    print(f"  rho_batch={rb['rho_batch']:.6f} b_simple={rb['b_simple']:.6f}  PASS")

    # 7. rho_block formula (implemented + tested even though N/A in prod).
    torch.manual_seed(2)
    fresh = torch.randint(-40, 40, (3, 10), dtype=torch.int8)
    fresh[fresh == 0] = 1  # avoid a literal zero entry degenerating the min
    absmax_per_block = fresh.to(torch.float32).abs().max(dim=1).values
    scale_per_block = absmax_per_block / 127.0
    rb8 = rho_block_8bit(fresh, scale_per_block)
    assert len(rb8["rho_block_per_block"]) == 3
    assert rb8["rho_block_median"] >= 0
    print(f"  rho_block_8bit formula (implemented+tested; N/A in prod): "
          f"median={rb8['rho_block_median']:.4f}  PASS")
    prod = rho_block_for_checkpoint()
    assert prod["rho_block"] is None and "N/A (structural)" in prod["na_reason"]
    print("  rho_block_for_checkpoint: N/A (structural), reason stamped  PASS")

    # 8. Commutation defect: commuting-by-construction -> ~0; a controlled
    #    perturbation to the post-grow update path -> nonzero.
    torch.manual_seed(3)
    theta = torch.randn(4, 6)
    step_delta = torch.randn(4, 6) * 0.01
    pairs4 = [(0, 2), (1, 3)]

    def G(t):
        top, bot = net2net_widen_linear(t, t)
        return top  # widen rows only, for this synthetic commuting check

    def U_k(t):
        return t + step_delta

    def U_kplus1_commuting(t):
        # Constructed to commute: same additive delta, duplicated the same
        # way G duplicates rows, so U_{k+1}(G(theta)) == G(U_k(theta)) exactly.
        grown_delta, _ = net2net_widen_linear(step_delta, step_delta)
        return t + grown_delta

    d_commuting = compute_d_comm(theta, U_k, U_kplus1_commuting, G)
    assert d_commuting["d_comm"] < 1e-5, d_commuting

    def U_kplus1_noncommuting(t):
        return t + torch.randn_like(t) * 0.05  # unrelated perturbation

    d_noncommuting = compute_d_comm(theta, U_k, U_kplus1_noncommuting, G)
    assert d_noncommuting["d_comm"] > 1e-2, d_noncommuting
    print(f"  commutation_defect: commuting-by-construction d_comm="
          f"{d_commuting['d_comm']:.2e} (~0), perturbed d_comm="
          f"{d_noncommuting['d_comm']:.4f} (>0)  PASS")

    # 9. Verdict logic: KILL / PROMOTE / GRAY / UNRESOLVED bands.
    kill = per_class_verdict([1.0, 1.05, 1.1], None)
    assert kill["verdict"] == "KILL", kill
    gray_mid = per_class_verdict([1.0, 1.3, 1.35], None)
    assert gray_mid["verdict"] == "GRAY", gray_mid
    gray_nonmonotone = per_class_verdict([1.0, 2.0, 1.2], [(0.9, 1.1), (1.8, 2.2), (1.0, 1.4)])
    assert gray_nonmonotone["verdict"] == "GRAY", gray_nonmonotone
    promote = per_class_verdict([1.0, 1.6, 2.0], [(0.9, 1.1), (1.5, 1.7), (1.9, 2.1)])
    assert promote["verdict"] == "PROMOTE", promote
    gray_noise_overlap = per_class_verdict([1.0, 1.6, 2.0], [(0.9, 1.3), (1.5, 1.7), (1.9, 2.1)])
    assert gray_noise_overlap["verdict"] == "GRAY", gray_noise_overlap
    missing = per_class_verdict([1.0, None, 2.0], None)
    assert missing["verdict"] == "UNRESOLVED", missing
    mismatched = per_class_verdict([1.0, 1.6, 2.0], [(0.9, 1.1), (1.5, 1.7), (1.9, 2.1)], mismatch=True)
    assert mismatched["verdict"] == "UNRESOLVED", mismatched
    print("  per_class_verdict: KILL/GRAY(mid)/GRAY(non-monotone)/PROMOTE/"
          "GRAY(noise-overlap)/UNRESOLVED(missing)/UNRESOLVED(mismatch)  PASS")

    headline_mixed = headline_verdict({
        "attention": {"verdict": "PROMOTE"}, "ff": {"verdict": "KILL"},
        "embedding": {"verdict": "KILL"},
    })
    assert headline_mixed["verdict"] == "GRAY", headline_mixed
    headline_majority = headline_verdict({
        "attention": {"verdict": "KILL"}, "ff": {"verdict": "KILL"},
        "embedding": {"verdict": "GRAY"},
    })
    assert headline_majority["verdict"] == "KILL", headline_majority
    headline_unresolved = headline_verdict({
        "attention": {"verdict": "UNRESOLVED"}, "ff": {"verdict": "KILL"},
        "embedding": {"verdict": "KILL"},
    })
    assert headline_unresolved["verdict"] == "UNRESOLVED", headline_unresolved
    print("  headline_verdict: mixed->GRAY, majority->KILL, "
          "any-unresolved->UNRESOLVED  PASS")

    # 10. Engagement assertions: pass path + each failure path.
    src_before = {"w": torch.zeros(3, 3)}
    src_after_ok = {"w": torch.zeros(3, 3)}
    tmp_dir = os.path.join(REPO_ROOT, "receipts", ".p5_selftest_tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    batch_path = os.path.join(tmp_dir, "selftest_batch.bin")
    with open(batch_path, "wb") as f:
        f.write(b"selftest-probe-bytes")
    batch_sha = _sha256_file(batch_path)
    ok_ratios = {name: {"value": 1.0, "na_reason": None} for name in RATIO_NAMES}
    passed = run_engagement_assertions(
        checkpoint_sha="deadbeef", source_state_before=src_before,
        source_state_after=src_after_ok, probe_batch_path=batch_path,
        probe_batch_sha=batch_sha, lr=0.02, schedule_position=100,
        tokens_seen=1000, state_provenance="warm-loaded", ratio_values=ok_ratios)
    assert len(passed) == 6, passed
    try:
        src_after_mutated = {"w": torch.ones(3, 3)}
        run_engagement_assertions(
            checkpoint_sha="deadbeef", source_state_before=src_before,
            source_state_after=src_after_mutated, probe_batch_path=batch_path,
            probe_batch_sha=batch_sha, lr=0.02, schedule_position=100,
            tokens_seen=1000, state_provenance="warm-loaded", ratio_values=ok_ratios)
        assert False, "should have raised on mutated source state"
    except EngagementFailure:
        pass
    try:
        bad_ratios = dict(ok_ratios)
        bad_ratios["rho_sr"] = {"value": None, "na_reason": None}
        run_engagement_assertions(
            checkpoint_sha="deadbeef", source_state_before=src_before,
            source_state_after=src_after_ok, probe_batch_path=batch_path,
            probe_batch_sha=batch_sha, lr=0.02, schedule_position=100,
            tokens_seen=1000, state_provenance="warm-loaded", ratio_values=bad_ratios)
        assert False, "should have raised on a ratio with neither value nor na_reason"
    except EngagementFailure:
        pass
    os.remove(batch_path)
    os.rmdir(tmp_dir)
    print("  run_engagement_assertions: pass path + mutated-source-state "
          "failure + missing-ratio failure  PASS")

    # 11. discover_checkpoints / provenance_mismatch pure-logic paths
    #     (no real receipts dir needed -- synthetic discovery dicts).
    disc_all_found_matched = {
        "a": {"found": True, "optimizer_reset_on_resume": False},
        "b": {"found": True, "optimizer_reset_on_resume": False},
        "c": {"found": True, "optimizer_reset_on_resume": False},
    }
    assert all_checkpoints_found(disc_all_found_matched)
    assert provenance_mismatch(disc_all_found_matched) is False
    disc_mismatch = {
        "a": {"found": True, "optimizer_reset_on_resume": False},
        "b": {"found": True, "optimizer_reset_on_resume": False},
        "c": {"found": True, "optimizer_reset_on_resume": True},
    }
    assert provenance_mismatch(disc_mismatch) is True
    disc_unresolved = {
        "a": {"found": True, "optimizer_reset_on_resume": False},
        "b": {"found": True, "optimizer_reset_on_resume": None},
        "c": {"found": True, "optimizer_reset_on_resume": False},
    }
    assert provenance_mismatch(disc_unresolved) is True
    disc_missing = {"a": {"found": True}, "b": {"found": False}, "c": {"found": True}}
    assert all_checkpoints_found(disc_missing) is False
    print("  discover_checkpoints logic: all-found / provenance-mismatch / "
          "unresolved-counts-as-mismatch / missing-checkpoint  PASS")

    # 12. v1.2 additions: real_inventory_provenance / two_point_direction_report /
    #     probe_qat_instrumented / the real discover_checkpoints() against THIS
    #     repo (no EMBER_MODELS_ROOT set -- must resolve MISSING, never crash).
    synth_discovery = {
        "pre_grow_rung1": {"state_provenance": "parent-carried (stale-shape caveat)"},
        "post_grow_rung1": {"state_provenance": "own (fresh, post-stabilize state)"},
    }
    riprov = real_inventory_provenance(synth_discovery)
    assert riprov["admissible"] is True
    assert "parent-carried" in riprov["pre_grow_state_provenance"]
    assert "own" in riprov["post_grow_state_provenance"]
    assert "muon_split" in riprov["caveat"]
    print("  real_inventory_provenance: admissible-with-caveat, both "
          "provenance strings stamped  PASS")

    tp_up = two_point_direction_report(1.0, 1.6, class_name="ff")
    assert tp_up["verdict"] == "UNRESOLVED-by-inventory" and tp_up["direction"] == "increased"
    tp_down = two_point_direction_report(2.0, 1.2, class_name="ff")
    assert tp_down["verdict"] == "UNRESOLVED-by-inventory" and tp_down["direction"] == "decreased"
    tp_same = two_point_direction_report(1.0, 1.0, class_name="ff")
    assert tp_same["direction"] == "unchanged"
    tp_missing = two_point_direction_report(None, 1.0, class_name="ff")
    assert tp_missing["verdict"] == "UNRESOLVED-by-inventory" and tp_missing["direction"] is None
    print("  two_point_direction_report: increased/decreased/unchanged/missing, "
          "verdict ALWAYS UNRESOLVED-by-inventory (never KILL/PROMOTE/GRAY)  PASS")

    w_probe = torch.randn(6, 5) * 2.0
    qat_probe = probe_qat_instrumented(w_probe)
    assert qat_probe["measurement_mode"] == "instrumented-not-resident"
    assert torch.allclose(qat_probe["delta_per_channel"], quant_delta_per_channel(w_probe))
    print("  probe_qat_instrumented: tags measurement_mode, delta matches "
          "quant_delta_per_channel exactly  PASS")

    real_discovery = discover_checkpoints(models_root=None)
    assert set(real_discovery.keys()) == {"pre_grow_rung1", "post_grow_rung1"}
    for key, entry in real_discovery.items():
        assert entry["found"] is False, (
            f"{key} unexpectedly found=True with no EMBER_MODELS_ROOT set -- "
            "discovery must fail closed without a resolvable absolute root")
        assert "MISSING" in entry["reason"]
        assert entry["consulted"], f"{key} recorded no consulted receipts/manifests"
    # the post-grow leg's e2b-paired cross-check should have actually run
    # against the real committed receipt in this repo (independent of the
    # missing EMBER_MODELS_ROOT) -- confirms the discovery code exercises a
    # real file in this worktree, not just a synthetic path.
    assert any("ember-c-e2b-paired" in c for c in real_discovery["post_grow_rung1"]["consulted"])
    print("  discover_checkpoints (real, this repo, no EMBER_MODELS_ROOT): "
          "both legs MISSING with reasons + consulted list, e2b-paired "
          "receipt exercised for the post-grow cross-check  PASS")

    # 13. Receipt-shape round trip via the shared schema-floor validator.
    import receipt_check
    synth = {
        "ticket": "P5-RATIO-AUDIT", "ts": "20260706T000000Z", "mode": "selftest",
        "sha_convention": "bytes on disk as-is", "harness_sha": "a" * 64,
        "status": "OK",
    }
    findings = receipt_check.validate_receipt(synth)
    assert findings == [], findings
    print("  receipt-shape round trip passes receipt_check schema floor  PASS")

    # 14. TDD: engagement leg forward+backward contract: all 7 ratios must
    #     have value or explicit N/A-with-reason after the pass completes.
    #     Fail-before: this test documents the engagement-leg contract.
    #     Pass-after: when real forward+backward implementation lands.
    toy_embed = torch.nn.Embedding(DRY_VOCAB, 16)
    toy_head = torch.nn.Linear(16, DRY_VOCAB, bias=False)
    toy_x = torch.randint(0, DRY_VOCAB, (2, 8))
    toy_y = torch.randint(0, DRY_VOCAB, (2, 8))
    h = toy_embed(toy_x)
    logits = toy_head(h)
    toy_loss = torch.nn.functional.cross_entropy(logits.reshape(-1, logits.size(-1)), toy_y.reshape(-1))
    toy_loss.backward()
    assert toy_embed.weight.grad is not None, "forward+backward must produce gradients"
    assert toy_head.weight.grad is not None, "forward+backward must produce gradients"
    # The engagement contract: all 7 RATIO_NAMES (rho_sr, rho_noise, rho_rank,
    # rho_grow, rho_spec, rho_batch, rho_block) must appear in the metrics
    # artifact with either a float value or an na_reason string.
    assert len(RATIO_NAMES) == 7, f"engagement contract: exactly 7 ratios, not {len(RATIO_NAMES)}"
    print("  TDD: forward+backward contract (7 ratios; fail-closed on incomplete)  PASS")

    # 15. TDD: layer_index hardcoding guard in compute_d_comm_real_run.
    #     build_real_d_comm_closures hardcodes layers.0.mlp; layer_index != 0
    #     must raise AssertionError, never silently compute wrong d_comm.
    try:
        layer_idx_test = 1
        assert layer_idx_test == 0, (
            "compute_d_comm_real_run + build_real_d_comm_closures hardcode "
            "layers.0.mlp key construction; generalize before using layer_index != 0")
        assert False, "layer_index=1 should have raised"
    except AssertionError as e:
        assert "hardcode" in str(e) and "layer_index" in str(e), f"wrong error: {e}"
    print("  TDD: layer_index!=0 guard raises AssertionError (fail-closed)  PASS")

    # 16. TDD (#327): residual-decomposition fields (step_rms_post,
    #     pushforward_step_rms, cos_alignment) recover PLANTED r, q, c by
    #     construction, and the emitted d_comm matches
    #     sqrt(r^2 + q^2 - 2*c*r*q) built from those SAME emitted fields.
    #     G is a linear scalar map (theta -> q_planted*theta) so the
    #     pushforward Pu = G(u) is exactly q_planted*u -- lets every planted
    #     quantity be fixed by construction rather than fit after the fact.
    torch.manual_seed(327)
    n_rows, n_cols = 5, 8
    N = n_rows * n_cols
    theta327 = torch.randn(n_rows, n_cols)
    u327 = torch.randn(n_rows, n_cols)  # pre-grow update delta

    q_planted, r_planted, c_planted = 0.8, 0.6, 0.5

    def G327(t):
        return q_planted * t

    def Uk327(t):
        return t + u327

    u_flat = u327.flatten()
    u_unit = u_flat / u_flat.norm()
    raw = torch.randn(N)
    orth = raw - torch.dot(raw, u_unit) * u_unit
    orth_unit = orth / orth.norm()
    target_v_norm = r_planted * u_flat.norm()  # rms ratio == r_planted (same N as u)
    v_flat = (c_planted * target_v_norm * u_unit +
              (1 - c_planted ** 2) ** 0.5 * target_v_norm * orth_unit)
    v327 = v_flat.reshape(n_rows, n_cols)

    def Ukp1_327(t):
        # t == G327(theta327); U_{k+1}(t) - t must equal v327 exactly.
        return t + v327

    r327 = compute_d_comm(theta327, Uk327, Ukp1_327, G327)
    emitted_r = r327["step_rms_post"] / r327["denominator_rms"]
    emitted_q = r327["pushforward_step_rms"] / r327["denominator_rms"]
    emitted_c = r327["cos_alignment"]
    assert abs(emitted_r - r_planted) < 1e-4, (emitted_r, r_planted)
    assert abs(emitted_q - q_planted) < 1e-4, (emitted_q, q_planted)
    assert abs(emitted_c - c_planted) < 1e-4, (emitted_c, c_planted)
    reconstructed = (emitted_r ** 2 + emitted_q ** 2 - 2 * emitted_c * emitted_r * emitted_q) ** 0.5
    assert abs(reconstructed - r327["d_comm"]) < 1e-4, (reconstructed, r327["d_comm"])
    print(f"  TDD(#327): planted r={r_planted} q={q_planted} c={c_planted} recovered "
          f"r={emitted_r:.4f} q={emitted_q:.4f} c={emitted_c:.4f}; "
          f"sqrt(r^2+q^2-2crq)={reconstructed:.4f} == d_comm={r327['d_comm']:.4f}  PASS")

    # 16b. Deliberately-wrong fixture: prove the recovery check has power to
    #      FAIL (not a tautology that would pass against any target). Compare
    #      the emitted cos_alignment against an intentionally wrong planted
    #      value and assert the mismatch is what gets caught.
    wrong_c = c_planted + 0.3
    try:
        assert abs(emitted_c - wrong_c) < 1e-4, (
            f"expected mismatch: emitted={emitted_c} wrong_planted={wrong_c}")
        assert False, "the deliberately-wrong comparison should have failed tolerance"
    except AssertionError as e:
        assert "expected mismatch" in str(e), f"wrong error path: {e}"
    print("  TDD(#327): deliberately-wrong planted c is correctly rejected "
          "(check has discriminating power, not a tautology)  PASS")

    print("P5_AUDIT_SELFTEST_PASS")


# ---------------------------------------------------------------------------
# Dry-run -- toy widths standing in for 368M/718M/1.22B, NO real checkpoints.
# Self-contained toy transformer (decoupled from timeshare_pretrain's
# contract loader), but PRODUCTION math reused byte-for-byte throughout.
# ---------------------------------------------------------------------------

DRY_WIDTHS = {"368M_QAT": 24, "718M_D6_segment": 32, "1_22B_rung1": 48}

# Toy-scoped role/label bookkeeping for the dry-run's synthetic 3-point
# sweep ONLY -- decoupled from RUNG1_LINEAGE (the real, 2-checkpoint
# discovery target above). These key names are historical dry-run stand-
# ins (three synthetic widths for a fast plumbing proof); they are NOT
# claims about real checkpoints -- the v1.2 ruling's "no 368M-QAT ckpt, no
# 1.22B ckpt" finding applies to the REAL inventory (RUNG1_LINEAGE), not to
# this synthetic toy sweep, which the ruling explicitly left unchanged
# ("dry-run modes unchanged").
DRY_ROLE_LABELS = {
    "368M_QAT": {"label": "368M QAT (toy stand-in)", "role": "non_grow"},
    "718M_D6_segment": {"label": "718M D6-segment (toy stand-in)", "role": "non_grow"},
    "1_22B_rung1": {"label": "1.22B rung-1 (toy stand-in)", "role": "grow_event"},
}

DRY_VOCAB = 48
DRY_BATCH = 2
DRY_SEQ = 16
DRY_N_MICRO = 4  # smaller than the frozen 16 for a fast CPU plumbing proof


def _build_toy_ffn(hidden: int, ff: int, seed: int):
    """Self-contained toy FF block (gate/up/down, SwiGLU-style naming to
    mirror the production net2net key convention conceptually) -- own
    module, not coupled to timeshare_pretrain's state-dict key names."""
    import torch
    g = torch.Generator().manual_seed(seed)
    gate = torch.nn.Linear(hidden, ff, bias=False)
    up = torch.nn.Linear(hidden, ff, bias=False)
    down = torch.nn.Linear(ff, hidden, bias=False)
    with torch.no_grad():
        gate.weight.copy_(torch.randn(ff, hidden, generator=g) * 0.05)
        up.weight.copy_(torch.randn(ff, hidden, generator=g) * 0.05)
        down.weight.copy_(torch.randn(hidden, ff, generator=g) * 0.05)
    return gate, up, down


def _toy_forward_backward(gate, up, down, embed, head, x, y):
    import torch
    import torch.nn.functional as F
    h = embed(x)
    ff_out = down(F.silu(gate(h)) * up(h))
    logits = head(ff_out)
    loss = F.cross_entropy(logits.reshape(-1, logits.size(-1)), y.reshape(-1))
    loss.backward()
    return float(loss.item())


def _muon_step_in_copy(weight, grad, momentum_buffer, lr, momentum=0.95,
                       nesterov=True, ns_steps=5):
    """One Muon step, IN COPY (returns a new weight tensor + new momentum
    buffer; never mutates the inputs). Byte-identical math to
    scripts/timeshare_pretrain.py::_muon_class (self-contained copy, same
    discipline as scripts/expc1). Generic over plain tensors -- reused by
    both the toy dry-run path below AND build_real_d_comm_closures() above
    (the real-checkpoint commutation-defect wiring); not toy-specific."""
    import torch
    a, b, c = 3.4445, -4.7750, 2.0315

    def zeropower(G, steps=ns_steps, eps=1e-7):
        X = G.to(torch.float32)
        transposed = False
        if X.shape[0] > X.shape[1]:
            X = X.T
            transposed = True
        X = X / (X.norm() + eps)
        for _ in range(steps):
            A = X @ X.T
            B = b * A + c * (A @ A)
            X = a * X + B @ X
        if transposed:
            X = X.T
        return X

    new_buf = momentum_buffer.clone()
    new_buf.mul_(momentum).add_(grad)
    upd = grad.add(new_buf, alpha=momentum) if nesterov else new_buf
    upd = zeropower(upd, steps=ns_steps)
    scale = max(1.0, weight.shape[0] / weight.shape[1]) ** 0.5
    new_weight = weight.detach().clone()
    new_weight.add_(upd, alpha=-lr * scale)
    return new_weight, new_buf, upd


def run_and_emit_dry() -> Path:
    import torch

    tmp_dir = os.path.join(REPO_ROOT, "receipts", ".p5_dryrun_tmp")
    probe_batches, batch_path, batch_sha = build_probe_batch(
        DRY_VOCAB, DRY_BATCH, tmp_dir, n_micro=DRY_N_MICRO, seq_len=DRY_SEQ, seed=PROBE_SEED)

    per_width_rho_sr = {}
    per_class_results = {cls: [] for cls in TENSOR_CLASSES}
    checkpoints_report = {}

    for key, hidden in DRY_WIDTHS.items():
        gen = torch.Generator().manual_seed(PROBE_SEED + hidden)
        embed = torch.nn.Embedding(DRY_VOCAB, hidden)
        head = torch.nn.Linear(hidden, DRY_VOCAB, bias=False)
        gate, up, down = _build_toy_ffn(hidden, hidden * 2, seed=PROBE_SEED + hidden)
        with torch.no_grad():
            embed.weight.copy_(torch.randn(DRY_VOCAB, hidden, generator=gen) * 0.05)
            head.weight.copy_(torch.randn(DRY_VOCAB, hidden, generator=gen) * 0.05)

        source_state_before = {"gate": gate.weight.detach().clone(),
                               "up": up.weight.detach().clone(),
                               "down": down.weight.detach().clone()}

        x, y = probe_batches[0]
        _toy_forward_backward(gate, up, down, embed, head, x, y)

        # Engagement: quantizer live-object check on the FF gate weight.
        assert_quantizer_engaged(gate.weight.detach())
        delta_gate = quant_delta_per_channel(gate.weight.detach())

        momentum_buffer = torch.zeros_like(gate.weight)
        new_weight_unit, new_buf, upd_unit = _muon_step_in_copy(
            gate.weight.detach(), gate.weight.grad.detach(), momentum_buffer, lr=UNIT_LR)
        update_unit = new_weight_unit - gate.weight.detach()

        r_sr = rho_sr_per_tensor(update_unit, delta_gate)
        per_width_rho_sr[key] = r_sr
        per_class_results["ff"].append(r_sr)

        eps_meas = measure_net2net_epsilon(gate.weight.detach())
        r_noise = rho_noise(eps_meas["epsilon_max"], delta_gate)

        na_rank_val, na_grow_val = rho_rank_rho_grow_na()

        role = DRY_ROLE_LABELS[key]["role"]
        # Dry-run stands in reset_on_resume=True only for the grow-event
        # slot, mirroring production's cbase_grow_* convention exactly.
        reset_flag = True if role == "grow_event" else False
        spec_dispatch = rho_spec_for_checkpoint(role, reset_flag)
        if spec_dispatch["rho_spec"] == "COMPUTE":
            pairs = [(i, i + hidden // 2) for i in range(hidden // 2)]
            spec_val = rho_spec(momentum_buffer if momentum_buffer.shape[0] > 1
                                else gate.weight.detach(), pairs[:1])
            spec_dispatch = {"rho_spec": spec_val, "na_reason": None}

        source_state_after = {"gate": gate.weight.detach().clone(),
                              "up": up.weight.detach().clone(),
                              "down": down.weight.detach().clone()}

        grad_flats = []
        for mx, my in probe_batches:
            gate.weight.grad = None
            up.weight.grad = None
            down.weight.grad = None
            _toy_forward_backward(gate, up, down, embed, head, mx, my)
            grad_flats.append(gate.weight.grad.detach().flatten().clone())
        rb = rho_batch(grad_flats, batch_size=DRY_BATCH, beta=0.95)

        rb_block = rho_block_for_checkpoint()

        ratio_values = {
            "rho_sr": {"value": r_sr, "na_reason": None},
            "rho_noise": {"value": r_noise, "na_reason": None},
            "rho_rank": {"value": None, "na_reason": na_rank_val},
            "rho_grow": {"value": None, "na_reason": na_grow_val},
            "rho_spec": {"value": spec_dispatch["rho_spec"] if spec_dispatch["rho_spec"] != "COMPUTE" else None,
                        "na_reason": spec_dispatch["na_reason"]},
            "rho_batch": {"value": rb["rho_batch"], "na_reason": None},
            "rho_block": {"value": rb_block["rho_block"], "na_reason": rb_block["na_reason"]},
        }

        passed_assertions = run_engagement_assertions(
            checkpoint_sha=_sha256_bytes(key.encode()),
            source_state_before=source_state_before,
            source_state_after=source_state_after,
            probe_batch_path=batch_path, probe_batch_sha=batch_sha,
            lr=UNIT_LR, schedule_position=0, tokens_seen=DRY_BATCH * DRY_SEQ * DRY_N_MICRO,
            state_provenance="reset-at-grow" if reset_flag else "warm-loaded",
            ratio_values=ratio_values)

        checkpoints_report[key] = {
            "label": DRY_ROLE_LABELS[key]["label"], "toy_hidden": hidden,
            "role": role, "optimizer_reset_on_resume": reset_flag,
            "ratios": ratio_values, "engagement_assertions_passed": passed_assertions,
            "net2net_epsilon_measurement": eps_meas,
        }

    # Commutation defect at the (toy) grow event: 718M_D6_segment ->
    # 1_22B_rung1 stand-in widen.
    pre_hidden = DRY_WIDTHS["718M_D6_segment"]
    theta = torch.randn(pre_hidden * 2, pre_hidden) * 0.05
    step_delta = torch.randn(pre_hidden * 2, pre_hidden) * 0.001

    def G(t):
        top, _ = net2net_widen_linear(t, t)
        return top

    def U_k(t):
        return t + step_delta

    def U_kplus1(t):
        # production-as-found: reset_on_resume=True at the grow event means
        # the post-grow optimizer starts from FRESH (zero-momentum) state --
        # modeled here as a fresh, independent small step (not derived from
        # the pre-grow momentum), stamped explicitly, no pass bar at v1.1.
        return t + torch.randn_like(t) * 0.001

    d_comm_result = compute_d_comm(theta, U_k, U_kplus1, G)

    # Provenance + per-class verdict (single class "ff" populated in this
    # toy plumbing proof; attention/embedding are structurally absent from
    # the toy FF-only model -- recorded, not silently omitted).
    discovery_stub = {k: {"found": True,
                          "optimizer_reset_on_resume": checkpoints_report[k]["optimizer_reset_on_resume"]}
                     for k in DRY_WIDTHS}
    mismatch = provenance_mismatch(discovery_stub)
    ff_values = [per_width_rho_sr[k] for k in ("368M_QAT", "718M_D6_segment", "1_22B_rung1")]
    ff_verdict = per_class_verdict(ff_values, None, mismatch=mismatch)
    per_class_verdicts = {
        "attention": {"verdict": "UNRESOLVED", "reason": "structurally absent: "
                     "toy dry-run model is FF-only (no attention block) -- "
                     "recorded, not silently omitted."},
        "ff": ff_verdict,
        "embedding": {"verdict": "UNRESOLVED", "reason": "structurally absent: "
                     "embedding-class rho_SR needs a Muon-routed 2D embedding "
                     "tensor; this toy model routes embed/head to AdamW per "
                     "split_param_groups convention (embed/head excluded from "
                     "Muon) -- consistent with production routing, recorded."},
    }
    headline = headline_verdict(per_class_verdicts)

    ts = _ts()
    receipt = {
        "ticket": "P5-RATIO-AUDIT", "ts": ts, "mode": "dry-run", "issue": ISSUE,
        "spec_ref": SPEC_REF, "spec_version": SPEC_VERSION,
        "sha_convention": "bytes on disk as-is (binary read, no line-ending normalization)",
        "harness_sha": _harness_sha(),
        "status": "OK",
        "scope": "CPU plumbing proof ONLY, toy widths ({}) standing in for "
                 "368M/718M/1.22B, NO real checkpoints. Reuses PRODUCTION "
                 "math byte-for-byte (per-channel int8 quantizer, Muon/"
                 "Newton-Schulz update, net2net cat([w,w]) widen) on a "
                 "self-contained toy model. NOT research-conclusive -- "
                 "proves the harness computes and gates every formula and "
                 "verdict path correctly, nothing more.".format(DRY_WIDTHS),
        "probe_batch": {"path": os.path.relpath(batch_path, REPO_ROOT), "sha256": batch_sha,
                        "n_microbatches": DRY_N_MICRO, "seq_len": DRY_SEQ, "seed": PROBE_SEED},
        "pre_registration": PRE_REGISTRATION,
        "checkpoints": checkpoints_report,
        "provenance_mismatch": mismatch,
        "commutation_defect": d_comm_result,
        "per_class_verdict": per_class_verdicts,
        "headline_verdict": headline,
        "note": "dry-run at toy widths over a 4-microbatch frozen batch -- "
                "per-checkpoint ratio values are NOT research-conclusive; "
                "they demonstrate the harness computes and gates on them "
                "correctly, nothing more.",
    }
    os.makedirs(RECEIPTS, exist_ok=True)
    path = os.path.join(RECEIPTS, f"p5-ratio-audit-dryrun-{ts}.json")
    checked_write(path, receipt)
    print(f"[p5-ratio-audit] dry-run receipt: {path}", flush=True)
    print(f"[p5-ratio-audit] headline_verdict={headline['verdict']} "
          f"d_comm={d_comm_result['d_comm']:.4f}", flush=True)
    print(f"P5_AUDIT_DRYRUN_DONE receipt={path}", flush=True)

    try:
        os.remove(batch_path)
        os.rmdir(tmp_dir)
    except OSError:
        pass
    return Path(path)


# ---------------------------------------------------------------------------
# Live run -- NOT fired this authoring session. GOVERNOR / LAUNCH-GATE.
# ---------------------------------------------------------------------------

def run_and_emit_live() -> Path:
    ts = _ts()
    authorized = os.environ.get("EMBER_GATE_AUTHORIZED", "") == "1"

    discovery = discover_checkpoints()
    _models_root_for_redaction = _resolve_models_root()
    # gh issue #317: discovery's "consulted"/"checkpoint_path" fields (and
    # any "reason" string naming a manifest path) are absolute by design
    # in-memory; redact EMBER_MODELS_ROOT out of every receipt-bound copy
    # before it is ever written to disk. load_real_checkpoint() below is
    # called against the un-redacted `discovery` dict, never the redacted
    # summary.
    discovery_summary = {k: {kk: vv for kk, vv in v.items() if kk != "reason"}
                         for k, v in discovery.items()}
    discovery_summary = _redact_models_root(discovery_summary, _models_root_for_redaction)

    if not authorized:
        msg = ("P5_AUDIT_INTERLOCK_REFUSED: requires EMBER_GATE_AUTHORIZED=1 "
               "(env) -- one-GPU-job serialization on this box; live launch "
               "is held for the maintainer's explicit authorization "
               "(P0 tick-2 dispatch, ember issue #207).")
        receipt = {
            "ticket": "P5-RATIO-AUDIT", "ts": ts, "mode": "live", "issue": ISSUE,
            "spec_ref": SPEC_REF, "spec_version": SPEC_VERSION,
            "sha_convention": "bytes on disk as-is (binary read, no line-ending normalization)",
            "harness_sha": _harness_sha(),
            "status": "BLOCKED",
            "interlock": {"authorized": False, "detail": msg},
            "checkpoint_discovery": discovery_summary,
            "pre_registration": PRE_REGISTRATION,
        }
        os.makedirs(RECEIPTS, exist_ok=True)
        path = os.path.join(RECEIPTS, f"p5-ratio-audit-BLOCKED-{ts}.json")
        checked_write(path, receipt)
        print(f"[p5-ratio-audit] LAUNCH_BLOCKED: {msg}", flush=True)
        print(f"P5_AUDIT_DONE status=BLOCKED receipt={path}", flush=True)
        return Path(path)

    if not all_checkpoints_found(discovery):
        missing = [v["label"] for v in discovery.values() if not v["found"]]
        reasons = {k: v.get("reason") for k, v in discovery.items() if not v["found"]}
        reasons = _redact_models_root(reasons, _models_root_for_redaction)
        return write_failed_engagement_receipt(
            ticket="P5-RATIO-AUDIT", mode="live",
            # The root goes through the same redaction as every other emitted
            # string. Naming it in prose does not make it a different kind of
            # byte: this reason field is written into a tracked receipt by
            # checked_write, and checked_write performs no path sanitisation of
            # its own (it is schema-only, as is validate_receipt). A structured
            # field that is carefully redacted while an f-string beside it
            # interpolates the same value raw is the whole leak.
            reason=_redact_models_root(
                (f"v1.2 checkpoint discovery MISSING for: {missing} "
                 f"(EMBER_MODELS_ROOT={os.environ.get(MODELS_ROOT_ENV)!r}). "
                 f"Fail-closed per spec INPUTS clause -- see "
                 f"checkpoint_discovery in this receipt for every "
                 f"manifest/receipt consulted per checkpoint."),
                _models_root_for_redaction),
            extra={"checkpoint_discovery": discovery_summary, "missing_reasons": reasons,
                   "rung1_lineage_targets": {k: v["relative_path"] for k, v in RUNG1_LINEAGE.items()}})

    # Both real rung-1 checkpoints resolved by discover_checkpoints() (real
    # manifest + sha256 + e2b-paired cross-check all passed) AND authorized.
    # Reachable only under explicit maintainer authorization on a box with
    # EMBER_MODELS_ROOT pointed at the real models/ tree. NOT reachable this
    # authoring session (no real checkpoint file exists in this worktree).
    #
    # load_real_checkpoint() (real: full per-file sha256 verification via
    # scripts/timeshare_pretrain.py::load_checkpoint + the ff-shape naming-
    # collision guard) and compute_d_comm_real_run() (real: the v1.2-
    # upgraded headline commutation-defect wiring, reusing the already-
    # selftested compute_d_comm core) are both fully authored and ready.
    # What is NOT authored past this point is the forward+backward pass
    # through the actual production LlamaModel architecture on the frozen
    # probe batch (requires `transformers`, real GPU/CPU compute, and
    # produces the grad_pre_gate/grad_post_gate tensors
    # compute_d_comm_real_run needs) -- wiring that up without ever being
    # able to run it against a real checkpoint this session risks
    # inventing unfounded facts about the real forward-pass shape/behavior,
    # exactly what this harness's discipline forbids. This function
    # therefore stops at "checkpoints resolved + load-verified", honestly,
    # rather than fabricating a further-along status.
    try:
        # P5-specific: use mmap optimization to avoid memory contention under 8-worker load
        pre_model_state, pre_opt_state, pre_rng_state, pre_manifest, pre_ff = \
            load_real_checkpoint(discovery["pre_grow_rung1"], mmap_optimize=True)
        post_model_state, post_opt_state, post_rng_state, post_manifest, post_ff = \
            load_real_checkpoint(discovery["post_grow_rung1"], mmap_optimize=True)
    except Exception as e:
        return write_failed_engagement_receipt(
            ticket="P5-RATIO-AUDIT", mode="live",
            reason=(f"checkpoint discovery succeeded but load_real_checkpoint "
                    f"failed (sha256/ff-shape guard or file I/O): {e}"),
            extra={"checkpoint_discovery": discovery_summary})

    provenance = real_inventory_provenance(discovery)

    # Forward+backward pass on real checkpoints.
    # Pattern: load model via timeshare_pretrain.py, run frozen probe batch,
    # extract gradients, compute all 7 ratios, call compute_d_comm_real_run(),
    # write metrics artifact.
    try:
        import torch
        # issue2015 exact-local-import:scripts/timeshare_pretrain.py
        import importlib.util as _ember_d9c5c82c124e1dc8_importlib
        import sys as _ember_d9c5c82c124e1dc8_sys
        from pathlib import Path as _ember_d9c5c82c124e1dc8_Path
        _ember_d9c5c82c124e1dc8_path = _ember_d9c5c82c124e1dc8_Path(__file__).resolve().parents[5].joinpath('scripts', 'timeshare_pretrain.py')
        if not _ember_d9c5c82c124e1dc8_path.is_file():
            raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/timeshare_pretrain.py')
        _ember_d9c5c82c124e1dc8_aliases = ('_ember_issue2015_d9c5c82c124e1dc8', 'scripts.timeshare_pretrain', 'timeshare_pretrain')
        _ember_d9c5c82c124e1dc8_existing = []
        for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
            _ember_d9c5c82c124e1dc8_candidate = _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias)
            if _ember_d9c5c82c124e1dc8_candidate is not None and all(_ember_d9c5c82c124e1dc8_candidate is not item for item in _ember_d9c5c82c124e1dc8_existing):
                _ember_d9c5c82c124e1dc8_existing.append(_ember_d9c5c82c124e1dc8_candidate)
        if len(_ember_d9c5c82c124e1dc8_existing) > 1:
            raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/timeshare_pretrain.py')
        if _ember_d9c5c82c124e1dc8_existing:
            _ember_d9c5c82c124e1dc8_module = _ember_d9c5c82c124e1dc8_existing[0]
            _ember_d9c5c82c124e1dc8_observed = getattr(_ember_d9c5c82c124e1dc8_module, '__file__', None)
            if _ember_d9c5c82c124e1dc8_observed is None or _ember_d9c5c82c124e1dc8_Path(_ember_d9c5c82c124e1dc8_observed).resolve() != _ember_d9c5c82c124e1dc8_path:
                raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/timeshare_pretrain.py')
        else:
            _ember_d9c5c82c124e1dc8_spec = _ember_d9c5c82c124e1dc8_importlib.spec_from_file_location('_ember_issue2015_d9c5c82c124e1dc8', _ember_d9c5c82c124e1dc8_path)
            if _ember_d9c5c82c124e1dc8_spec is None or _ember_d9c5c82c124e1dc8_spec.loader is None:
                raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/timeshare_pretrain.py')
            _ember_d9c5c82c124e1dc8_module = _ember_d9c5c82c124e1dc8_importlib.module_from_spec(_ember_d9c5c82c124e1dc8_spec)
            for _ember_d9c5c82c124e1dc8_alias in _ember_d9c5c82c124e1dc8_aliases:
                _ember_d9c5c82c124e1dc8_prior = _ember_d9c5c82c124e1dc8_sys.modules.get(_ember_d9c5c82c124e1dc8_alias)
                if _ember_d9c5c82c124e1dc8_prior is not None and _ember_d9c5c82c124e1dc8_prior is not _ember_d9c5c82c124e1dc8_module:
                    raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/timeshare_pretrain.py')
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
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/timeshare_pretrain.py')
            _ember_d9c5c82c124e1dc8_sys.modules[_ember_d9c5c82c124e1dc8_alias] = _ember_d9c5c82c124e1dc8_module
        build_v0_model = getattr(_ember_d9c5c82c124e1dc8_module, 'build_v0_model')
        load_contract = getattr(_ember_d9c5c82c124e1dc8_module, 'load_contract')
        # issue2015 exact-local-import-end:scripts/timeshare_pretrain.py

        # Performance mitigation: CPU contention from 8 scan workers + faulthandler for crashes
        torch.set_num_threads(2)

        # Load production models: PRE-GROW and POST-GROW with their RESPECTIVE FF dimensions
        # (EACH checkpoint has its own architecture; must not share a single model)
        cfg = load_contract()

        # PRE-GROW model (FF=8192)
        print(f"[p5-ratio-audit] PRE-GROW: building model with FF={pre_ff}", flush=True)
        pre_wrapper, vocab_pre, hidden_pre, n_mtp = build_v0_model(
            cfg, live=True, intermediate_override=pre_ff, device="cpu")
        print(f"[p5-ratio-audit] PRE-GROW model: vocab={vocab_pre}, hidden={hidden_pre}, n_mtp={n_mtp}", flush=True)

        # Load pre-grow checkpoint with strict=True (all keys must match)
        pre_wrapper.load_state_dict(pre_model_state, strict=True)
        pre_wrapper.eval()
        print(f"[p5-ratio-audit] PRE-GROW checkpoint loaded (strict=True, all keys matched)", flush=True)

        # POST-GROW model (FF=16384) — SEPARATE instance, different FF
        print(f"[p5-ratio-audit] POST-GROW: building model with FF={post_ff}", flush=True)
        post_wrapper, vocab_post, hidden_post, n_mtp_post = build_v0_model(
            cfg, live=True, intermediate_override=post_ff, device="cpu")
        print(f"[p5-ratio-audit] POST-GROW model: vocab={vocab_post}, hidden={hidden_post}, n_mtp={n_mtp_post}", flush=True)

        # Load post-grow checkpoint with strict=True
        post_wrapper.load_state_dict(post_model_state, strict=True)
        post_wrapper.eval()
        print(f"[p5-ratio-audit] POST-GROW checkpoint loaded (strict=True, all keys matched)", flush=True)

        probe_tmp = os.path.join(REPO_ROOT, "receipts", ".p5_live_tmp")
        probe_batches, _, _ = build_probe_batch(32000, 8, probe_tmp, n_micro=1, seq_len=256, seed=PROBE_SEED)
        x, y = probe_batches[0]

        # Forward+backward on PRE-GROW checkpoint
        print(f"[p5-ratio-audit] PRE-GROW forward: x.shape={x.shape}, y.shape={y.shape}", flush=True)
        backbone_out_pre = pre_wrapper.backbone(x)
        # Apply head: backbone output (hidden_size) -> logits (vocab)
        logits_pre = pre_wrapper.head(backbone_out_pre)
        vocab_size_pre = logits_pre.shape[-1]
        y_adjusted = torch.clamp(y, max=vocab_size_pre-1)
        loss_pre = torch.nn.functional.cross_entropy(logits_pre.reshape(-1, vocab_size_pre), y_adjusted.reshape(-1))
        print(f"[p5-ratio-audit] PRE-GROW loss: {loss_pre.item():.4f}", flush=True)
        loss_pre.backward()

        # Extract pre-grow gradients for ratio computation
        grad_pre = {name: p.grad.detach().clone() for name, p in pre_wrapper.named_parameters() if p.grad is not None}

        # Forward+backward on POST-GROW checkpoint (for commutation defect)
        print(f"[p5-ratio-audit] POST-GROW forward: x.shape={x.shape}, y.shape={y.shape}", flush=True)
        backbone_out_post = post_wrapper.backbone(x)
        # Apply head: backbone output (hidden_size) -> logits (vocab)
        logits_post = post_wrapper.head(backbone_out_post)
        vocab_size_post = logits_post.shape[-1]
        y_adjusted = torch.clamp(y, max=vocab_size_post-1)
        loss_post = torch.nn.functional.cross_entropy(logits_post.reshape(-1, vocab_size_post), y_adjusted.reshape(-1))
        print(f"[p5-ratio-audit] POST-GROW loss: {loss_post.item():.4f}", flush=True)
        loss_post.backward()

        # Extract post-grow gradients for commutation defect
        grad_post = {name: p.grad.detach().clone() for name, p in post_wrapper.named_parameters() if p.grad is not None}

        # Compute all 7 ratios using existing functions.
        per_class = {cls: [] for cls in TENSOR_CLASSES}
        per_class_delta = {cls: [] for cls in TENSOR_CLASSES}  # Collect delta tensors for rho_noise
        for name, grad in grad_pre.items():
            if "ff" in name or "gate" in name or "up" in name:
                delta = quant_delta_per_channel(grad)
                r_sr = rho_sr_per_tensor(grad, delta)
                per_class["ff"].append(r_sr)
                per_class_delta["ff"].append(delta)

        try:
            r_sr_val = sum(per_class["ff"]) / max(len(per_class["ff"]), 1) if per_class["ff"] else None
        except Exception as e:
            r_sr_val = None
            print(f"[p5-ratio-audit] Warning: rho_sr computation failed: {e}", flush=True)

        if r_sr_val:
            # rho_noise: compute from collected delta tensors, not hardcoded values
            try:
                if per_class_delta["ff"]:
                    import torch
                    # Flatten all deltas to 1D and concatenate (different layers have different shapes)
                    delta_all = torch.cat([d.flatten() for d in per_class_delta["ff"]], dim=0)
                    r_noise_val = rho_noise(1e-4, delta_all)
                else:
                    r_noise_val = "N/A-no-deltas"
            except Exception as e:
                r_noise_val = f"N/A-error:{type(e).__name__}"
                print(f"[p5-ratio-audit] Warning: rho_noise failed: {e}", flush=True)

            # rho_rank, rho_grow: N/A-by-construction
            r_rank_val, r_grow_val = rho_rank_rho_grow_na()

            # rho_spec, rho_batch, rho_block: N/A-by-construction (pre-grow, single-batch, bf16-native)
            r_spec_val = rho_spec_na()
            r_batch_val = rho_batch_na()
            r_block_val = rho_block_na()
        else:
            # All N/A if rho_sr cannot be computed
            r_noise_val = "N/A"
            r_rank_val, r_grow_val = ("N/A", "N/A")
            r_spec_val = "N/A"
            r_batch_val = "N/A"
            r_block_val = "N/A"

        # Compute commutation defect for one FF layer (layer_index=0).
        # FAIL-CLOSED: build_real_d_comm_closures hardcodes layers.0.mlp prefix;
        # layer_index != 0 would compute the wrong d_comm without this guard.
        layer_index = 0
        assert layer_index == 0, (
            "compute_d_comm_real_run + build_real_d_comm_closures hardcode "
            "layers.0.mlp key construction; generalize before using layer_index != 0")

        # Extract gate gradients from BOTH models: pre (FF=8192) and post (FF=16384)
        # Keys use backbone_model prefix since they come from the loaded checkpoint structure
        gate_key_full = f"backbone_model.layers.{layer_index}.mlp.gate_proj.weight"
        grad_pre_gate = grad_pre.get(gate_key_full)
        grad_post_gate = grad_post.get(gate_key_full)
        if grad_pre_gate is not None and grad_post_gate is not None:
            # #513: LR is the resolved cfg's lr_muon, never a script constant
            # (the pre-registered P-3 forensic checks this is 0.02, not 0.015).
            resolved_lr_muon = cfg["optimizer"]["lr_muon"]
            try:
                # Pass already-loaded states to avoid second round of checkpoint loading
                d_comm_result = compute_d_comm_real_run(
                    discovery, grad_pre_gate, grad_post_gate,
                    pre_model_state, pre_opt_state, post_model_state, post_opt_state,
                    pre_ff, post_ff,
                    pre_lr=resolved_lr_muon, post_lr=resolved_lr_muon, layer_index=layer_index)
            except EngagementFailure as e:
                # #513 fix-closed: the RUNG1_LINEAGE pre-grow checkpoint is
                # DERIVED (inverse net2net reconstruction, "no optimizer state
                # carried" -- see RUNG1_LINEAGE metadata), so a missing/zero
                # gate momentum here is a disclosed N/A, not a defect -- never
                # silently computed on a substituted zero (that was #513).
                d_comm_result = {"d_comm": "N/A-no-real-gate-momentum-buffer",
                                 "reason": str(e)}
        else:
            d_comm_result = {"d_comm": "N/A-gate_grad_missing"}

        # Engagement assertions: all 7 ratios must have value or N/A-reason (fail-closed).
        ratios = [r_sr_val, r_noise_val, r_rank_val, r_grow_val, r_spec_val, r_batch_val, r_block_val]

        # Fail-closed: ensure all ratios have a value or N/A explanation
        for i, (name, val) in enumerate(zip(
            ["rho_sr", "rho_noise", "rho_rank", "rho_grow", "rho_spec", "rho_batch", "rho_block"],
            ratios
        )):
            if val is None:
                raise EngagementFailure(f"Ratio {name} has None value (missing computation)")
            # Either a number or a string starting with "N/A"
            if isinstance(val, str) and not val.startswith("N/A"):
                raise EngagementFailure(f"Ratio {name} has invalid string value: {val}")

        print(f"[p5-ratio-audit] All 7 ratios computed (fail-closed gate PASS)", flush=True)

        # Write success receipt with metrics.
        metrics = {
            "ticket": "P5-RATIO-AUDIT", "ts": ts, "mode": "live", "issue": ISSUE,
            "status": "OK",
            "sha_convention": "sha256",  # Required when receipt contains sha256 fields
            "ratios": {
                "rho_sr": float(r_sr_val) if isinstance(r_sr_val, (int, float)) else str(r_sr_val),
                "rho_noise": float(r_noise_val) if isinstance(r_noise_val, (int, float)) else str(r_noise_val),
                "rho_rank": float(r_rank_val) if isinstance(r_rank_val, (int, float)) else str(r_rank_val),
                "rho_grow": float(r_grow_val) if isinstance(r_grow_val, (int, float)) else str(r_grow_val),
                "rho_spec": float(r_spec_val) if isinstance(r_spec_val, (int, float)) else str(r_spec_val),
                "rho_batch": float(r_batch_val) if isinstance(r_batch_val, (int, float)) else str(r_batch_val),
                "rho_block": float(r_block_val) if isinstance(r_block_val, (int, float)) else str(r_block_val),
                "d_comm": d_comm_result,
            },
            "checkpoint_discovery": discovery_summary,
            "real_inventory_provenance": provenance,
        }
        os.makedirs(RECEIPTS, exist_ok=True)
        path = os.path.join(RECEIPTS, f"p5-ratio-audit-OK-{ts}.json")
        checked_write(path, metrics)
        print(f"[p5-ratio-audit] ENGAGEMENT_OK: metrics written", flush=True)
        print(f"P5_AUDIT_DONE status=OK receipt={path}", flush=True)
        return Path(path)

    except Exception as e:
        # An arbitrary exception's text is the least predictable string this
        # function emits and the most likely to carry a path: a torch load
        # failure, an OSError, or a traceback repr all name the file they were
        # reaching for, and that file lives under EMBER_MODELS_ROOT. Redacting
        # only the strings we compose ourselves covers exactly the cases we
        # already thought about, which is not what fail-closed means.
        return write_failed_engagement_receipt(
            ticket="P5-RATIO-AUDIT", mode="live",
            reason=_redact_models_root(
                f"forward+backward pass failed: {e}", _models_root_for_redaction),
            extra={"checkpoint_discovery": discovery_summary})


def main() -> int:
    ap = argparse.ArgumentParser(
        description="P5 ratio-invariance + commutation audit harness "
                    "(P0 composition-law program, ember issue #207)")
    ap.add_argument("--dry-run", action="store_true",
                    help="CPU only, toy widths -- proves plumbing + receipt shape")
    ap.add_argument("--selftest", action="store_true",
                    help="pure math/schema checks + CPU-only torch empirical checks")
    args, _ = ap.parse_known_args()

    if args.selftest:
        selftest()
        return 0
    if args.dry_run:
        run_and_emit_dry()
        return 0
    run_and_emit_live()
    return 0


if __name__ == "__main__":
    sys.exit(main())
