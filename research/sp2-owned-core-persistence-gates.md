# sp-2 — D/P-gate owned-core instances across the multi-day governed pretrain (#201)

Owner: Leo. Status: SPEC FROZEN. The standing persistence gates (D-gate
quarantine, P-gate session-boundary — task #36 lineage, first receipts
green 2026-06-11 ~07:08) were instanced on borrowed-core adapters. The
owned-core track changes both surfaces. This spec pins the instances
BEFORE they must fire; the eng instance harness lands separately (eng
track), bound to these shapes.

## 1. Where the old instances do and do not transfer

- **D-gate is ADAPTER-SCOPED and transfers.** Quarantine-the-weights →
  gain collapses to base at fixed seed. On the owned core every
  accumulation round still produces an adapter on a fixed base
  (fp-27: retrain-from-base on the full ledger), so `d_gate.py`
  semantics carry unchanged — only the base swaps from the borrowed 3B
  to the owned checkpoint.
- **D-gate does NOT transfer to the pretrained base itself.** There is
  no "base below the base" for the quarantine counterfactual. The
  base's deletion-test ANALOGUE is provenance, not quarantine: the
  checkpoint sha lineage + resume-continuity chain (P-own-resume below)
  is what makes the base's identity receipted rather than assumed.
- **P-gate transfers with a new, cheaper instance during pretrain.**
  The borrowed-core P-gate (#114) proved gain reproduction across a
  REAL daemon restart (bit-identical at fixed seed). The multi-day
  governed pretrain WILL cross daemon restarts; each one is a
  P-gate-shaped event, receipted per-event (not once per phase).

## 2. P-own-resume — the per-restart continuity receipt (pretrain phase)

Grounded in the trainer's existing primitives (eng-33:
`verify_resume`, `restore_rng` — both already selftested):

Required fields (receipt_check-compatible; sha fields ⇒ `sha_convention`):

```
ticket                      P-OWN-RESUME
ts
run_dir
verify_resume_verdict       must be "SAFE_RESUME" (fail-closed:
                            RESTART_FROM_SCRATCH is its own receipt and
                            a STATE event, never silent)
resume_ckpt_dir / resume_step
ckpt_sha_chain_assert       true: resumed checkpoint's per-file sha256
                            == manifest of the last emitted checkpoint
rng_restored_assert         true: restore_rng applied from checkpoint state
pid_before / pid_after      process discontinuity evidence (#114 pattern)
last_pre_loss / first_post_loss   logged continuity pair (evidence of a
                            recorded boundary; determinism comes from
                            restore_rng, no numeric band is invented)
governor                    governor block of the resumed segment
sha_convention / no_gpu:false
```

Emitter: the trainer's resume path (eng). Audit: gate-time re-derivation
of the sha chain from the checkpoint manifest (eng-53 pattern — the
asserts are the emitter's claim, never the verdict's evidence).

## 3. Round-phase instances (accumulation rounds, per fp-27)

| Event | Gate | Shape |
|---|---|---|
| every daemon restart during pretrain | **P-own-resume** | §2 (per-event) |
| round gate (every round) | **D-round** | `d_gate.py` shape: quarantine `adapters/own-r{N}-{arm}`, base = owned checkpoint (by sha); gain_without must collapse to base pass-vector at fixed seed on the round-gate split (buckets 90–99) |
| round gate (every round) | round verdict | fp-27 frozen vocabulary (GAIN/FLAT/NEGATIVE by paired CI) — not this spec |
| promotion (artifact adopted into lineage) | **D-promotion** | same quarantine shape on the promoted artifact; promotion receipt additionally pins base sha + adapter sha + ledger sha at promotion time |
| once per round | **P-round** | `p_gate.py` shape unchanged: boundary pair across a real restart, gain reproduction at fixed seed (the #114 precedent), adapter shas unchanged across the boundary |

## 4. Bindings

- **fp-27 (#198, frozen):** `ROUND_GATE.d_gate` / `ROUND_GATE.p_gate`
  reference these instances; the dispatch receipt records which
  cadence rows fired.
- **fp-24 probe receipts:** `adapter_none_assert` already isolates the
  base from adapter lift at probe time — unchanged by this spec.
- **eng harness:** emits P-own-resume from the resume path and runs the
  D-round/D-promotion quarantine legs; shapes above are the contract.

## 5. What this spec refuses to invent

No numeric loss-continuity band (determinism is restore_rng's job; a
band would be a tunable goalpost). No D-gate-on-the-base fiction (the
honest analogue is the provenance chain). No new verdict words.
