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
- The one canonical export command is `python scripts/lane_drift.py export --dst DIR` (its values are in the live-only `lane-export.json`); do not type `export_lane.py` arguments by hand.
- Drift check (#2454): the lane runs the LIVE scripts, so the live copy and this tree must not diverge unnoticed. `python scripts/lane_drift.py check` exports the live scripts and compares every file with this tree at the tree ref by git blob id
  (an edited script, a script the tree lacks, and a tree file the lane lacks are all drift; line endings cannot hide a change). `loops/tick.py` runs the same check FIRST on every tick and refuses (a `blocked` receipt row, no lane work started, `ESCALATE` after 3 in a row)
  while there is drift. It fails closed: if git or the export cannot run, the tick refuses too. When drift is found the gate fetches the tree ref once (at most every 30 minutes), so a merged pull request clears it by itself. The only waiver is
  `python scripts/lane_drift.py ack --ruling ID`, which writes `loops/drift-ack.json` for exactly the current drift (it names the exported blob id of every file, so any later edit trips again) and expires after 48 hours.

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
| `drop_manifest.py`, `drop_execute.py`, `drop_uploaded.py`, `clear_uploaded_shards.py` | Local eviction of packed sets whose bytes are on the Hub. `drop_uploaded.py` and `clear_uploaded_shards.py` carry their own server-copy check outside `verified_remove.py` (`drop_uploaded.py`: per-file server read-back plus local sha256 recompute, receipt row before `os.remove`, skip on any mismatch, hard-linked files in the training catalog never touched; both are open items on #2454, not covered by the shared module). `drop_execute.py` is one of the nine scripts that go through `verified_remove.py` (fresh per-file server read-back, no snapshot index, containment, receipt first); the standing stop on running it stays until the lead lifts it (see Rules). |
| `reserve_manifest.py`, `reserve_evict.py`, `ckpt_*.py`, `dup_ckpt_*.py`, `evict_ckpt_list.py` | Checkpoint custody and eviction. `reserve_evict.py` and `evict_ckpt_list.py` remove on their own checks outside `verified_remove.py` (open items on #2454; `evict_ckpt_list.py` is verified on its own path only for its pinned list); `ckpt_lineage_delete.py` and the remove path of `ckpt_backup.py` are two of the nine scripts that go through `verified_remove.py` as of #2454 (see Rules). |
| `protected_set.py` + `loops/protected-set.json` | The declared protected set (#2450): the ONE keep-list every checkpoint-deleting script reads (`evict_ckpt_list.KEEP_MARKERS`/`kept()`, `reserve_evict`, `reserve_manifest`, `ckpt_backup`, `ckpt_lineage_delete`). `markers` protect everywhere, `reserve_markers` add to the reserve executor. The training seat or lead re-declares each hour by editing the JSON: no code edit, the red tests follow the file. The removal receipts of `reserve_evict.py`, `evict_ckpt_list.py` and `ckpt_lineage_delete.py` record the sha256 and path of the set read immediately before that remove (a marker declared during a run is honoured); `ckpt_backup.py` records no set sha256, and `reserve_manifest.py` uses an import-time snapshot because it only selects. A missing, unreadable, empty, malformed or too-broad file (a marker that is not a string, is padded, is shorter than 8 characters or is a bare root) raises and the deleters remove nothing (fail closed); there is no environment override. |
| `fetch_child_objects.py`, `upload_child_state.py` | Verified restore and upload of checkpoint objects and optimizer/replay state. |
| `heldout_*.py`, `overlap_*.py`, `build_heldout_index*.py` | Held-out custody and overlap sweeps. |
| `kill_with_receipt.py`, `kill_lane.ps1` | The only sanctioned way to stop a lane process: receipt first. |
| `lane_drift.py` | The drift check: exports the live scripts and compares them with this tree by blob id; `loops/tick.py` refuses while there is drift (waiver: `ack --ruling ID`). |
| `tests/` | Red tests: each one fails when the rule it guards is broken. |

## Rules the code enforces

- Fail closed is the design rule, not yet a property of every script. The independent review of this PR (follow-up issue #2454) found gates that fail open, for example a verdict missing a hash, skipped scan types and a missing overlap index. Treat any script not named below as unverified.
- Receipt before action, verified delete. Only these executors read the server copy back and recompute a local hash on the same code path before they remove anything, with the receipt row written first: `drop_uploaded.py`, `pg_verify_delete.py`, `_pack_del.py`, `a_relocate.py`, `remedy_hheldout2.py`, `redact_r1.py`, and `evict_ckpt_list.py` (for its pinned list only).
- Protected checkpoints come from one declaration (#2450): a path containing any marker in `loops/protected-set.json` is never removed, the file is re-read on every check and again immediately before each remove (a long-lived process never keeps a smaller set), and `reserve_evict.py` writes a run-start row before its first removal (the reserve declaration it serves, read once at the start from `loops/reserve.json` with its sha256; the protected-set path and sha256; the free space before), one row per file before its remove, and a run-end row in a `finally` (removed and skipped counts, free space after each removal, an error field), so a run that raised still leaves its declaration and series. A non-dry run with no readable reserve declaration removes nothing.
- Nine named scripts share one delete module (#2454): `verified_remove.py`. It is NOT the one path for every lane delete: six removers (`drop_uploaded.py`, `clear_uploaded_shards.py`, `pg_verify_delete.py`, `_pack_del.py`, `reserve_evict.py`, `evict_ckpt_list.py`) remove on their own server-copy claim outside it and stay open items on #2454. `remove_verified` (a server copy exists) reads the server entry back NOW, requires size AND an LFS sha256 (no size-only fallback; a missing entry, a missing LFS sha256 or an unreadable server keeps the file), recomputes the local sha256 NOW, requires st_nlink == 1 and a path inside the allowed root with no link or junction on the way, and fsyncs the receipt row (both hashes) BEFORE the os.remove. `remove_dup` does the same against a local duplicate. Both of those compare the file with its first stat (size, mtime, inode) once more after the receipt row and just before the remove, and a locked or vanished file while hashing is a named refusal (`hash failed: <ExceptionName>`), not a traceback. `remove_ruled` is the separate, honestly named path for data with NO copy anywhere (regenerable or derived data deleted under a lead ruling); it is a ruling, NOT a verification: a ruling id that is a mail id, a PIN (`--manifest-sha256`: the plan sha256 the dry run printed for the files it found, which the lead rules on; a different plan, for example a file added after the ruling, refuses everything before anything is hashed or written; `ckpt_lineage_delete.py` pins on its `--expect-dirs` file instead), the manifest of every file (path, size, sha256, mtime, inode, pin) fsynced first, a re-check at each remove that the file is still the manifest's file, and the receipt says `ruled-no-copy`, never verified. A row without a pin is refused. The nine: `ckpt_lineage_delete.py` (needs `--ruling` and `--expect-dirs` for the no-copy probe branch; its per-file remove passes the planned link count, so a name hard-linked after the plan refuses), `drop_execute.py` (tier 2 needs `--manifest-sha256 NAME=SHA` per directory), `ckpt_backup.py` (`delete_refuted`), `raw_roll.py` (`roll`, signature unchanged), `free_b.py`, `_pg_obj_del.py`, `delete_approved_dirs.py`, `_wiki_del.py`, `_ws_del.py`. `free_b.py`, `_pg_obj_del.py`, `delete_approved_dirs.py`, `_wiki_del.py`, `_ws_del.py` and `ckpt_backup.py` ran their work at import time before; now importing them does nothing, and the five deleters are a dry run by default (`--go`, plus `--ruling NNNNN` and `--manifest-sha256 <the PLAN_SHA256 the dry run printed>` for the no-copy ones, to delete).
- The standing stop on running these nine stays until the lead lifts it; the migration is code, the decision to run is not ours. Each has a red test on a fake server in a tmp tree (`tests/*_verify_red_test.py`, `tests/oneshot_deleters_red_test.py`): a stale marker, a same-size corrupt upload, a server entry without an LFS sha256, an unreadable server, a hard link, a path outside the root and a failed receipt write all keep the file.
- Not yet reviewed: every other script that can delete a file is listed in `tests/delete_paths_lint_red_test.py` (UNREVIEWED, a frozen baseline that can only shrink). That test fails when a script outside the verified, own-proof and baseline sets gains a delete call, so a new unverified deleter cannot arrive unnoticed.
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

One of them runs in CI today: `python -B src/ember/data/lane/tests/write_gate_lint_red_test.py` is a step of `ci-pr` (the Linux python job; it needs no lane environment). It fails a pull request that adds a bulk writer without an enforced `reserve_plan.write_gate` (`if not ...write_gate(...): sys.exit/raise`, in the write's own function) and is not listed in its `TINY_OK` / `GATE_DEBT`. It also executes dedup, filter_ids, carve_heldout, gh_assemble, redact_r1 and repack_r1 against a stub gate, and prints `unscannable: N files` (write forms a static scan cannot see) under a frozen ceiling. The other lane red tests are still run by hand.
