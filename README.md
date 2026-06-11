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
artifacts in `receipts/` — never by prose. `STATE.md` is the single position
ledger; `GOAL.md` is the standing goal and its binding reading notes.

## Current state (2026-06-11)

The borrowed-core instrument phase is complete: the accumulation recipe is
receipted as **learning in-distribution** (+75.9pp per-sample on trained
tasks, control below base) with a **floor-scoped transfer ceiling** at the
tested episode budget (fp-25 decomposition). The registered round-3 shape is
**(b) owned-core in-dist accumulation** (fp-26 prereg, frozen).

**Staged for the first owned-core v0 training run — currently BLOCKED on
G-shards** (the first shard run was refused by the writer's band guard,
which exposed a count-semantics conflict; the re-derived freeze + shard
rerun are in flight). The live critical path, each step a precondition of
the next:

1. shard emission (`scripts/token_shards_v0.py --emit`) → `TOKEN-SHARDS-V0`
   receipt reproducing the frozen token total (pinned in the
   tokenizer-freeze receipt),
2. the 8-row launch gate (`scripts/v0_pretrain_launch_gate.py`) — all rows
   green, enforced INSIDE the trainer interlock (it cannot dispatch
   otherwise),
3. governed `--live` dispatch of the real-corpus trainer
   (`scripts/timeshare_pretrain.py`) under the resource governor,
4. checkpoint floor probes (frozen fp-23 protocol; fp-24 executes; fp-29
   gates the kill path) → first accumulation round (frozen fp-27 prereg).

`python scripts/sp3_terminal_audit.py --run` prints the terminal-condition
position any day: every row RECEIPTED (path + sha) or GAP-NAMED.

## Layout

| path | what |
|---|---|
| `GOAL.md` | the goal, verbatim, with binding reading notes |
| `STATE.md` | position ledger: running jobs, gated receipts, pending layers, transition log |
| `scripts/` | the harness: sampling/verification (`t1_*`), round training (`t2_*`), seed ledger (`t3_*`), four-arm heldout eval (`t4_*`), harm suite (`t5_*`), v0 pretrain chain (`token_shards_v0`, `v0_pretrain_launch_gate`, `timeshare_pretrain`, `v0_config_check`), frozen preregs + executors (`fp*_*.py`), terminal audit (`sp3_terminal_audit`) |
| `receipts/` | one JSON per executed job — the only admissible evidence (`receipt_check.py` is the floor) |
| `ledger/` | verified-episode ledger + matched-control pool + committed views |
| `configs/` | frozen v0 pretrain config (`v0-pretrain-config.json`) + validator contract |
| `tokenizer/` | the frozen 32k tokenizer (byte-pinned; reserved band ids 0–7) |
| `corpus-manifests/` | per-source manifests of the license-clean ~25.3 GB / 6.97B-token v0 corpus (corpus bytes live out-of-tree) |
| `probes/` | canonical frozen probe sets (L1 floor probe, seed 23, sha-stamped) |
| `docs/` | specs and contracts — see `docs/index.md` |
| `research/` | internal working notes: decision artifacts, preregs' prose halves, surveys |

Not in the repo: model weights and token shards (sizes and hashes pinned in
receipts; ~14 GB shard sets live out-of-tree) and third-party `vendor/`
clones (provenance recorded in `STATE.md`).

## Operating constraints

The machine stays usable while ember works. Every job passes mechanical launch
preconditions: a hard per-process VRAM fraction cap, a free-VRAM margin
assert, and a decode pacer inside every generation loop. Evals are chunked,
resumable, and early-stopping — sized to this machine, not to datacenter
habits. The borrowed core (smallest Qwen2.5-Coder that cleared the verify
floor) was instrumentation for proving the accumulation loop; the registered
destination is a from-scratch, quantization-native, owned core — the v0 run
above is its first instance.
