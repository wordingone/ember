# docs index

What ember is, what it claims, and where each binding artifact lives.
(`README.md` at the repo root is the entry point; this maps the docs set.)

## Evidence model (applies to everything below)

- Claims come only from receipts of executed local jobs (`receipts/`,
  floor-checked by `scripts/receipt_check.py`). Prose never carries a claim.
- Preregistration: analyses that judge a run are frozen BEFORE the run
  exists (executable constants + selftests, not prose intent).
- Gates tighten on failure, never relax. Deviations from frozen constants
  are registered, never silent.
- Provenance tags: a receipt's claims are scoped to its pinned world,
  model, seed, and budget — propagating a verdict beyond its scope
  (e.g. a floor-scoped ceiling as an architecture claim) is a violation.

## Specs in this directory

| doc | what it binds |
|---|---|
| `formalization-v0.md` | the v0 formal frame: worlds, episodes, verification, accumulation |
| `ledger-schema-v3.md` | verified-episode ledger schema (the replay buffer) |
| `kernel-v1-freeze-spec.md` | kernel freeze contract |
| `nck-spec-v0.md` / `nck-invariant-contract-v0.md` | owned-core (NC) spec + invariant contract |
| `r2-prereg.md` | round-2 prereg (borrowed-core instrument phase) |
| `arcade-floor-prereg.md` | arcade-world floor prereg |
| `sleep-consolidation-spec-v0.md` | consolidation timescales spec |

## Training pipeline + gates (current: v0 owned-core)

Live chain (each step fail-closed on the previous step's receipt):

1. **Corpus** — license-clean ~25.3 GB assembled, per-source manifests in
   `corpus-manifests/`, totals frozen.
2. **Tokenizer** — frozen 32k, byte-pinned (`tokenizer/`), reserved ids 0–7;
   real token total 6,973,632,296.
3. **Shards** — `scripts/token_shards_v0.py --emit` writes packed uint16
   shards out-of-tree; the receipt must reproduce the frozen total; a
   byte-scan validator re-derives invariants from the bytes.
4. **Launch gate** — `scripts/v0_pretrain_launch_gate.py`, 8 rows
   (corpus / tokenizer / shards / config / governor / world / budget /
   prereg), enforced inside the trainer interlock.
5. **Governed dispatch** — `scripts/timeshare_pretrain.py --live` under the
   resource governor (VRAM fraction cap + margin assert + decode pacer).
6. **Checkpoint floor probes** — frozen protocol in
   `scripts/fp23_probe_prereg.py` (bar: ≥1.0 verified L1 episode per
   governed minute at the 2B checkpoint; one retry at 4B); executed by
   `scripts/fp24_verdict.py`; the kill path additionally requires a
   receipted curriculum-synthesis attempt (`scripts/fp29_kill_synthesis_gate.py`).
7. **Accumulation round 1** — frozen prereg `scripts/fp27_round1_prereg.py`
   (split discipline, sampling pins, frozen verdict vocabulary);
   persistence-gate instances in `research/sp2-owned-core-persistence-gates.md`.
8. **Coverage obligation** — `scripts/fp28_v0_coverage.py` discharges the
   frozen frontier-depth obligation on the first real checkpoint eval.

## Standing audits

- `scripts/sp3_terminal_audit.py --run` — terminal-condition position,
  row-by-row: RECEIPTED (path + sha) or GAP-NAMED. No other verdict words.
- Standing D-gate (deletion) and P-gate (process-boundary persistence)
  receipts gate every round and promotion.

## Non-claims (explicit)

- No transfer claim beyond the preregistered floor and budget it was
  measured at.
- No capability claim for the owned core before its floor receipt exists.
- Internal `research/` notes are working artifacts, not claims.
