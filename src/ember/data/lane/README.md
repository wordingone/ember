# ember.data.lane: data-lane tooling

Scripts the data lane runs to source, clean, pack, scan, upload, account for and evict the Ember corpus. They were developed unversioned under a staging directory on the lane's workstation;
this directory is their first versioned home. Advances #1581 (corpus data plane) and #2451 (secret-scan class).

## This directory is generated

The live lane scripts carry machine roots and seat names; the repository forbids both. So this tree is produced by `export_lane.py` from the live copy and is **never hand-edited here**:

    python export_lane.py --src <live scripts dir> --dst src/ember/data/lane --m-root <machine root> --lane-dir <lane dir name> \
        --seat <lead id>=SEAT_LEAD --seat <training id>=SEAT_TRAIN --seat <data id>=SEAT_DATA --word <Name>=<role word> ... --receipt <file>

- A machine root in a code string becomes an expression over `lane_config.M_ROOT` / `lane_config.LANE_ROOT`; a seat id used as a mail recipient or state-directory name becomes `lane_config.SEAT_*`.
- Roots, seat names and mail references in comments, docstrings and message text become neutral role words (`--word OLD=NEW`).
- Equivalence proof: for every `.py` file the rewritten AST is folded back with the real values and compared with the original AST after normalising only documentary text. Any other difference fails the export (exit 1).
  The receipt lists the sha256 of every source and output file; it is attached to the pull request that lands a regeneration.
- To change a script: edit the live copy, rerun the export, commit the diff. A hand edit here is overwritten by the next export.

## Configuration (`lane_config.py`)

Everything machine-specific arrives through the environment; a missing variable raises on first use, so a mis-deployed lane fails loudly instead of writing to a default location.

| Variable | Meaning |
|---|---|
| `EMBER_LANE_ROOT` | Runtime data root of the lane (`logs`, `packed`, `loops`, `scratch`, `upq` ...). This directory is deployed as `<root>/scripts`. |
| `EMBER_M_ROOT` | Parent directory holding the lane root and the sibling trees the lane reads (custody, receipts, seat state trees). |
| `EMBER_SEAT_LEAD`, `EMBER_SEAT_TRAIN`, `EMBER_SEAT_DATA` | Seat ids of the coordinating, training and data roles: mailbox recipient and state-directory name. |
| `EMBER_CENSUS_SKIP_PREFIXES` | `;`-separated lower-case path prefixes the census skips. |

## What is here

| Path | Role |
|---|---|
| `loops/tick.py` | One judgment-free pipeline step per call: `intake`, `fetch`, `prep`, `upload`, `census`. Writes a receipt row per tick. `upload` drops a set locally the moment its private upload is server-verified (`drop_uploaded.py`). |
| `loops/run_loops.py` | Detached singleton runner for the mechanical ticks: exclusive lock, one run per slot, per-tick timeout, heartbeat file, mail relay. |
| `th_gate.py`, `th_pack_scan.py`, `th_rescan_hf.py`, `secret_scan.py`, `redact_pack_hits.py` | Secret-scan class: TruffleHog pre-upload gate (fail closed), pack scan, re-scan of files already on the Hub, redaction and repack. Values are never logged. |
| `pack.py`, `pack_gate.py`, `source_manifest.py`, `text_lane.py`, `pack_prov_fix.py`, `pack_media.py` | Packing and the pack-completeness gate. |
| `reserve_plan.py` | Disk-floor source of truth: `floor_gib()` re-reads the standing floor file on every call (so a floor change reaches already-running lane processes), measured-harm waits, `write_gate()` for scratch writes, `scan_floor_gib()` (a bounded band under the lane floor, never under the press minimum) for the pre-upload scan's transient scratch so scan -> upload -> verified drop is never starved by lanes. |
| `scratch_dir.py` | Owner-stamped scratch directories: removed at exit by their writer; a killed writer's directory is swept with a receipt row. |
| `drop_manifest.py`, `drop_execute.py`, `drop_uploaded.py`, `clear_uploaded_shards.py` | Local eviction of packed sets whose bytes are on the Hub: manifest first, then per-file server read-back plus local sha256 recompute, receipt row before `os.remove`, skip on any mismatch, hard-linked files (in the training catalog) never touched. |
| `reserve_manifest.py`, `reserve_evict.py`, `ckpt_*.py`, `dup_ckpt_*.py`, `evict_ckpt_list.py` | Checkpoint custody and verified eviction. A child of a scored hour is kept until a server-verified copy exists. |
| `fetch_child_objects.py`, `upload_child_state.py` | Verified restore and upload of checkpoint objects and optimizer/replay state. |
| `heldout_*.py`, `overlap_*.py`, `build_heldout_index*.py` | Held-out custody and overlap sweeps. |
| `kill_with_receipt.py`, `kill_lane.ps1` | The only sanctioned way to stop a lane process: receipt first. |
| `tests/` | Red tests: each one fails when the rule it guards is broken. |

## Rules the code enforces

- Fail closed. A scanner crash, a missing receipt, a hash mismatch or a floor breach is a refusal, never a pass.
- Receipt before action. Every delete, kill and upload writes its receipt row first; every delete is preceded by a server read-back and a local hash.
- No secret value in any log, receipt or mail.
- Scratch and pack writes wait on the disk floor (`reserve_plan.write_gate`); they never write below it.
- Evaluation and held-out data are never mixed into training sets; every pack carries a provenance record.

## Running the red tests

Deploy this directory as `<EMBER_LANE_ROOT>/scripts`, set the variables above, and run each test from the lane root, for example:

    python scripts/tests/write_gate_red_test.py
    python scripts/tests/floor_live_process_red_test.py
    python scripts/tests/drop_uploaded_red_test.py

Each prints `ALL PASS` or exits non-zero. Most tests build throwaway directories and inject their own server doubles; they do not touch the lane's live data.
Wiring these tests into the repository's pytest discovery is follow-up work: they are script-style tests that take the lane root from the environment.
