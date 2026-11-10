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
| `EMBER_HF_RAW_REPO`, `EMBER_HF_TRAIN_REPO` | Names of the lane's private raw-sources and training-ready Hub dataset repos. Local configuration only: no private repo name is stored in this tree. |
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
| `drop_manifest.py`, `drop_execute.py`, `drop_uploaded.py`, `clear_uploaded_shards.py` | Local eviction of packed sets whose bytes are on the Hub. `drop_uploaded.py` is the verified path (per-file server read-back plus local sha256 recompute, receipt row before `os.remove`, skip on any mismatch, hard-linked files in the training catalog never touched). `drop_execute.py` does NOT verify on its own path: do not run it (see Rules). |
| `reserve_manifest.py`, `reserve_evict.py`, `ckpt_*.py`, `dup_ckpt_*.py`, `evict_ckpt_list.py` | Checkpoint custody and eviction. Of these only `evict_ckpt_list.py` is verified on its own path (and only for its pinned list); `ckpt_lineage_delete.py` and the remove path of `ckpt_backup.py` are not (see Rules). |
| `protected_set.py` + `loops/protected-set.json` | The declared protected set (#2450): the ONE keep-list every checkpoint-deleting script reads (`evict_ckpt_list.KEEP_MARKERS`/`kept()`, `reserve_evict`, `reserve_manifest`, `ckpt_backup`, `ckpt_lineage_delete`). `markers` protect everywhere, `reserve_markers` add to the reserve executor. The training seat or lead re-declares by editing the JSON: no code edit, the red test follows the file, and every removal receipt records the file's sha256. A missing, unreadable, empty or too-broad file raises and the deleters remove nothing (fail closed). |
| `fetch_child_objects.py`, `upload_child_state.py` | Verified restore and upload of checkpoint objects and optimizer/replay state. |
| `heldout_*.py`, `overlap_*.py`, `build_heldout_index*.py` | Held-out custody and overlap sweeps. |
| `kill_with_receipt.py`, `kill_lane.ps1` | The only sanctioned way to stop a lane process: receipt first. |
| `tests/` | Red tests: each one fails when the rule it guards is broken. |

## Rules the code enforces

- Fail closed is the design rule, not yet a property of every script. The independent review of this PR (follow-up issue #2454) found gates that fail open, for example a verdict missing a hash, skipped scan types and a missing overlap index. Treat any script not named below as unverified.
- Receipt before action, verified delete. Only these executors read the server copy back and recompute a local hash on the same code path before they remove anything, with the receipt row written first: `drop_uploaded.py`, `pg_verify_delete.py`, `_pack_del.py`, `a_relocate.py`, `remedy_hheldout2.py`, `redact_r1.py`, and `evict_ckpt_list.py` (for its pinned list only).
- Protected checkpoints come from one declaration (#2450): a path containing any marker in `loops/protected-set.json` is never removed, the file is re-read on every check (a long-lived process never keeps a smaller set), and `reserve_evict.py` writes one run row per execution holding the reserve declaration it served (`loops/reserve.json` and its sha256), the protected-set sha256, the free space before and after, and the free space measured after each removal (other writers included).
- Unverified executors, not to be run until #2454 fixes them: `ckpt_lineage_delete.py`, `drop_execute.py`, `delete_approved_dirs.py`, `_pg_obj_del.py`, `_wiki_del.py`, `_ws_del.py`, `free_b.py`, and the remove paths of `raw_roll.py` and `ckpt_backup.py`. They are in the tree for review, not as a runbook.
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
