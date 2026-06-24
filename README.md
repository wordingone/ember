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

## How to read this repository

Start with these four files, in order:

| read | for |
|---|---|
| `GOAL.md` | the standing goal, verbatim, with its binding reading notes |
| `STATE.md` | the single position ledger — where the work actually is right now (verify its top entry against current receipts before relying on it) |
| `GOVERNANCE.md` | how this repo is kept coherent: one trunk, branch lifecycle, naming, what may and may not be committed |
| `receipts/` | one JSON per executed job — the only admissible evidence (`receipt_check.py` is the floor) |

Status lives in `STATE.md` and the receipts, **not** in commit messages and
**not** in this README. Commit messages record what a change does; they are not
a progress board.

## Layout

| path | what |
|---|---|
| `GOAL.md` | the goal, verbatim, with binding reading notes |
| `STATE.md` | the single bounded position ledger |
| `GOVERNANCE.md` | repository structure, branch lifecycle, and commit policy |
| `scripts/` | the harness: cycle spine, readiness gate, MLE/Kaggle benchmark harness, A/B/C wheel harness, Windows sandbox, governor binding, state substrate, plus training/eval surfaces |
| `receipts/` | one JSON per executed job — the only admissible evidence |
| `receipts/ledger/` | verified-episode ledger + matched-control pool + committed views |
| `scripts/probes/` | canonical frozen probe sets (sha-stamped) |
| `config/` | frozen v0 pretrain + multimodal configs and validator contract |
| `tokenizer/` | the frozen 32k tokenizer (byte-pinned; reserved band ids 0–7) |
| `manifests/corpus/` | per-source manifests of the license-clean v0 corpus (corpus bytes live out-of-tree) |
| `docs/` | specs and contracts |
| `docs/research/` | internal working notes: decision artifacts, preregs' prose halves, surveys |
| `tools/` | repository-guard kernel and hook installer (see GOVERNANCE.md) |

Not in the repo: model weights, token shards, hydrated third-party benchmark
data, and third-party `vendor/` clones. Their provenance must be pinned in
receipts before any claim depends on them.

## Operating constraints

The machine stays usable while ember works. Every job passes mechanical launch
preconditions: a hard per-process VRAM-fraction cap, a free-VRAM margin assert,
and a decode pacer inside every generation loop. Evals are chunked, resumable,
and early-stopping — sized to this machine, not to datacenter habits. The
registered destination core is from-scratch, quantization-native, and owned;
any borrowed core is instrumentation for proving the loop, not the destination.

## Contributing

This repository is single-owner and source-available (see `LICENSE`). Structure
and lifecycle invariants are enforced mechanically by `tools/repo-guard.sh`,
which runs as a local git hook, a required CI status check, and a scheduled
freshness monitor. Run `bash tools/install-hooks.sh` once after cloning. See
`GOVERNANCE.md` for the rules the guard enforces.
