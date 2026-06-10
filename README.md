# ember

A substrate that runs, trains, and improves on one local machine — and has to
prove every improvement with receipts.

ember improves by **verified experience only**: it acts in worlds it can
inspect (currently ARC-AGI-1 program synthesis), verifies its own outputs
against ground truth the world itself provides (a candidate program must
reproduce the task's own train pairs in a sandbox), and burns only verified
episodes into its weights. Every claimed gain must

1. survive **held-out transfer** (tasks never trained on, plus ARC-AGI-2 as a
   second transfer surface),
2. beat a **matched control** (an identically-budgeted adapter trained on
   confirmed-failing programs), and
3. **disappear when the artifact is deleted**.

Claims are gated exclusively by receipts from executed local jobs — JSON
artifacts in `receipts/` — never by prose. `STATE.md` is the single position
ledger; `GOAL.md` is the standing goal and its binding reading notes.

## Layout

| path | what |
|---|---|
| `GOAL.md` | the goal, verbatim, with binding reading notes |
| `STATE.md` | position ledger: running jobs, gated receipts, pending layers, transition log |
| `scripts/` | the harness: sampling/verification (`t1_*`), round training (`t2_*`), seed ledger (`t3_*`), four-arm heldout eval (`t4_*`), harm suite (`t5_*`) |
| `receipts/` | one JSON per executed job — the only admissible evidence |
| `ledger/` | verified-episode ledger + matched-control pool |
| `research/` | technique surveys for the owned-core destination |

Not in the repo: model weights (adapters' sizes and hashes are pinned in their
training receipts; weights publish separately) and third-party `vendor/`
clones (arc-dsl, re-arc, ARC-AGI — provenance recorded in `STATE.md`).

## Operating constraints

The machine stays usable while ember works. Every job passes mechanical launch
preconditions: a hard per-process VRAM fraction cap, a free-VRAM margin
assert, and a decode pacer inside every generation loop. Evals are chunked,
resumable, and early-stopping — sized to this machine, not to datacenter
habits. The current borrowed core (smallest Qwen2.5-Coder that clears the
verify floor) is instrumentation for proving the accumulation loop; the
registered destination is a from-scratch, quantization-native, owned core
(`nc2-own-technique-contract.md`).
