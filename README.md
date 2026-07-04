# ember

A substrate that runs, trains, and improves on one local machine — and has to
prove every improvement with receipts.

ember improves by **verified experience only**: it acts in worlds it can
inspect, verifies its own outputs against ground truth the world itself
provides, and burns only verified episodes into its weights. Every claimed
gain must

1. survive **held-out evaluation** on a split it never trained on,
2. beat a **matched control** (an identically-budgeted adapter trained on
   confirmed-failing programs), and
3. **disappear when the artifact is deleted** (standing D-gate) and
   **persist across process boundaries** (standing P-gate).

Claims are gated exclusively by receipts from executed local jobs — JSON
artifacts under `receipts/` — never by prose.

## Current status

<!-- state-as-of: 2026-07-04 | board-receipt: ember-totality-20260704T175932Z | counts: 28-GREEN / 3-AUDIT-OK / 6-RED -->

Position ledger: `STATE.md`. Standing goal: `GOAL.md`.

**State as of 2026-07-04 (evening).** The program is now governed by a receipt-gated
**totality board**: a registry of 37 conditions (35 primary + 2 roll-ups)
covering base capability, resident training, growth, efficiency, observability,
independence, process integrity, enforcement, disconfirmation, and ledger
admission. Every row's verdict traces to executed-job receipts; an adversarial
board-integrity audit (issue #89) re-attacks the GREEN rows on a cadence — its
first fire produced 7 findings, maintainer spot-verification confirmed 5, and
all 7 probe-hardening cures have now LANDED (issue #97). Current board:
**27 of 34 state conditions GREEN, 3 of 3 process-invariant audits OK**. Two of
today's REDs are the hardened probes doing their job — verdicts that were
previously accepted on weaker evidence are now honestly open. The RED set:

- **C-SCALE** — foundation-model-scale training on the one-GPU budget is not
  yet receipted. This week's named finding (issue #82): the pre-registered W1
  token-collapse control landed **L3** — a width-matched from-scratch control
  matched the grown model's capability point with **≤13% of the grow path's
  tokens**, refuting the growth ladder's token-economics at rung-1 scale and
  redirecting the scale program to from-scratch-at-width (W2 pre-registration
  frozen, issue #29).
- **C-E2B** — the paired measured-distance protocol against the frozen
  reference model (issues #23/#48): GATE-1 passed; the GATE-0 paired run is
  live at this writing (instrumented re-fire after two silent launch failures).
- **C11** — re-opened BY the hardening: the probe now demands execution-bound
  active-time tiers, and two banked tiers inherited a counter instead of
  earning it (re-earn protocol: issue #98). The 24h tier's spend was genuine.
- **C3** — re-opened BY the hardening: the probe now reads the receipt's own
  `equal_within_tolerance` measurement, which contradicts the banked reason.
  Honest re-measurement queued.
- **C-SURFACE2** — re-opened BY the hardening: replay-of-completed-run
  provenance no longer counts as a live surface; needs a genuinely live run.
- **C-TALLY** — the roll-up; RED by construction until the above clear.
The field-level contribution proof (`GOAL.md`) therefore remains **not
cleared** — C-SCALE and C-E2B are its preconditions, and no receipt on file
constitutes a field-level claim.

Beyond the board, the standing program surfaces are public as issues on this
repository: the succession/self-hosting codex (#90), the
autonomy-relinquishment ladder — the invariant-gated transfer of the
maintainer's levers to ember itself, currently at rung NONE with rung R0 in
build (#92), enforcement-layer execution integrity (#38), and the export/CI
hygiene chain that is bringing the full contract tree, board machinery, and
receipts into this public repo via PRs (#33, #91).

**Freshness contract:** this section carries a machine-readable
`state-as-of` marker (above). A stale README is a defect of the same class as
a stale `STATE.md` (`GOVERNANCE.md`), and the publication-visibility clause
(issue #42) makes public-surface currency a board-gated property, not a
courtesy.

## How to reproduce the public checks

See `docs/REPRODUCIBILITY.md` for the full list with exact commands. Short
form:

```
# Schema-floor validator — fail-closed per receipt file
python scripts/receipt_check.py --selftest     # pure-logic self-test; no deps
python scripts/receipt_check.py --all          # report over every receipts/*.json

# Component selftests (no live model, no GPU required)
python scripts/corpus_acquire_selftest.py
python scripts/corpus_mix_selftest.py
python scripts/ember_gate_cleanroom_inventory_selftest.py
python scripts/ember_gate_cleanroom_legal_boundary_selftest.py
python scripts/ember_gate_full_parity_harness_selftest.py
python scripts/ember_gate_receipt_store_selftest.py
```

Each selftest prints a `*_SELFTEST_PASS` sentinel on success and exits
non-zero on failure. They require only Python 3.11+ and the packages in
`requirements.txt`; no model weights, no credentials, no GPU.

## What is NOT reproducible from this repo

The following are explicitly **out-of-tree** and cannot be reproduced from
this repository alone:

- **Model weights** — not committed; must be produced by running the training
  scripts against a local corpus.
- **Token shards and corpus bytes** — not committed; source manifests are
  under `manifests/corpus/`; hydrating them requires running
  `scripts/corpus_acquire.py` with local disk space (several hundred GB).
- **Hydrated third-party benchmark data** — licenses prohibit redistribution;
  `scripts/corpus_acquire.py` downloads from canonical sources.
- **Full training run** — requires one NVIDIA RTX 4090 or equivalent (24 GB
  VRAM). The governor rails (`VRAM_FRACTION=0.80`, `MARGIN_GIB=1.5`) are
  enforced mechanically; no cloud path exists.
- **Third-party `vendor/` clones** — their provenance must be pinned in
  receipts before any claim depends on them.

## Exact limits of current claims

1. **Receipt scope = claim scope.** No claim extends beyond the exact
   receipted job. A receipt for D3 task_65/task_66 is not evidence on
   ScienceAgentBench; a ScienceAgentBench admission receipt is not a
   performance claim.

2. **No goal-clear.** The Goal Clear Condition (`GOAL.md §Goal Clear
   Condition`) is not yet met. Existing receipts are engineering evidence;
   they do not constitute a field-level ML/AI breakthrough claim.

3. **D3 loop receipts are pre-condition evidence only.** The broader-D3 loop
   receipts (`d3-broader-multifamily-loop-*`) are `invalid_precondition_bypass_for_goal_clear`
   until the clean-room predecessor-CLI, RLM, and iGRPO resident-training
   preconditions are receipted. They inform regression/transfer tests; they
   cannot clear the goal or any readiness gate.

4. **Symbolic proxy passes are revoked as gate passes.** Any prior
   resident-training receipt that contains no trainable neural parameter
   update is `SYMBOLIC_PROXY_PASS` — runner evidence only, not a gate
   clearance.

5. **Zero paid-service dependency.** The canonical proof path requires no
   money-costing API key, hosted model, metered visual judge, or paid
   leaderboard. Any receipt that depends on paid access is
   `invalid_paid_api_exit_ramp` and is not authoritative evidence.

## Repository layout

| path | what |
|---|---|
| `GOAL.md` | the standing goal, verbatim, with binding reading notes |
| `STATE.md` | the single bounded position ledger |
| `GOVERNANCE.md` | repository structure, branch lifecycle, and commit policy |
| `scripts/` | the harness: cycle spine, readiness gate, benchmark harness, A/B/C wheel, governor binding, state substrate, training/eval surfaces |
| `receipts/` | one JSON per executed job — the only admissible evidence |
| `receipts/ledger/` | verified-episode ledger + matched-control pool + committed views |
| `scripts/probes/` | canonical frozen probe sets (sha-stamped) |
| `config/` | frozen v0 pretrain + multimodal configs and validator contract |
| `tokenizer/` | the frozen 32k tokenizer (byte-pinned; reserved band ids 0–7) |
| `manifests/corpus/` | per-source manifests of the license-clean v0 corpus |
| `docs/` | specs and contracts |
| `docs/research/` | internal working notes: decision artifacts, preregs' prose halves, surveys |
| `tools/` | repository-guard kernel and hook installer (see `GOVERNANCE.md`) |

## Operating constraints

The machine stays usable while ember works. Every job passes mechanical launch
preconditions: a hard per-process VRAM-fraction cap, a free-VRAM margin
assert, and a decode pacer inside every generation loop. Evals are chunked,
resumable, and early-stopping — sized to this machine, not to datacenter
habits. The registered destination core is from-scratch, quantization-native,
and owned; any borrowed core is instrumentation for proving the loop, not the
destination.

## Contributing

This repository is single-owner and source-available (see `LICENSE`). Structure
and lifecycle invariants are enforced mechanically by `tools/repo-guard.sh`,
which runs as a local git hook, a required CI status check, and a scheduled
freshness monitor. Run `bash tools/install-hooks.sh` once after cloning. See
`GOVERNANCE.md` for the rules the guard enforces.

## Consolidation note

The repository was reset to a single clean-history root on 2026-06-24 (commit
`8e9e6b6`). Prior development history was collapsed to remove operator names,
local filesystem paths, and personal contact details from published history.
The working tree at that commit is the consolidated content. Branch protection
and `tools/repo-guard.sh` enforce structure going forward. If you cloned or
forked before 2026-06-24, re-clone from the current origin to avoid working
from a superseded history.
