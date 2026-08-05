# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""regenerate_cbase_heldout_slice.py -- rebuild the #760 frozen heldout slice
from clean, disjoint, real shard bytes.

WHY THIS EXISTS
----------------
The Wave-011 (PR #1228) frozen slice at manifests/cbase-heldout-slice-v1.json
draws all 16 windows from v0-00016.bin, global token range
[4294967296, 4563402752). The 2026-08-04 L3 fineweb_edu provenance audit
(#1436, scripts/fineweb_exclusion.py) proved the ruled-excluded fineweb_edu
range is [4055121325, 5723508974) -- which CONTAINS v0-00016.bin's entire
span. Every window in the committed frozen slice is 100% fineweb_edu content
now that the exclusion is ruled; scripts/cbase_heldout_eval.py's new
verify_slice_excludes_ruled_sources() correctly REFUSES it (proven: running
`python -B scripts/cbase_heldout_eval.py --validate-only --shard-dir
<real shard bytes>` against the real committed manifest exits 2 with
SLICE_OVERLAPS_EXCLUDED_SOURCE). The slice predates the ruling by 5 days
(PR #1228 merged 2026-07-30; the ruling audit is dated 2026-08-04) -- it was
correct when written and is invalidated by information that did not exist
yet, not by a bug in PR #1228.

This script picks a REPLACEMENT shard entirely outside every ruled-excluded
range, selects windows deterministically (even stride, no cherry-picking),
and verifies every property it can prove from receipts + real bytes: shard
identity (sha256 rehash), exclusion-clean (fineweb_exclusion, same module
the harness now consumes), and training-consumption disjointness (range
arithmetic against the highest window ceiling receipted anywhere in this
repo as of the run).

WHAT THIS SCRIPT DELIBERATELY DOES NOT DO
-------------------------------------------
It does not re-run n-gram contamination_recheck (the Jul-08 decontamination
batch's matcher, reused_matcher: "scripts/w1_collapse_control_run.py:
contamination_recheck"). That function is unreachable from live code:
w1_collapse_control_run.py imports timeshare_pretrain at module scope
(line 76), and timeshare_pretrain.py raises SystemExit at module scope
under the 2026-07-12 historical_only execution-denial lock -- importing
either file to call that function would violate the same lock this whole
codebase (and the #760 build spec) requires respecting. Porting
contamination_recheck into a standalone, non-execution-denied module
(mirroring how cbase_heldout_eval.py's own eval_loss mechanism was ported
out of that same file for Deliverable 1 of #760) is a named follow-up, not
attempted here.

Because of that, this script's output is a CANDIDATE manifest, not a
frozen one: manifests/cbase-heldout-slice-v1.json's schema hard-requires
selection_evidence.verdict == "CLEAN" (scripts/cbase_heldout_eval.py
load_frozen_slice_manifest, SLICE_SELECTION_VERDICT_INVALID), and "CLEAN"
in that field specifically denotes a passed n-gram decontamination check
(see receipts/ember-c-scale/w2-heldout-decontam-20260708T121128Z.json).
Writing "CLEAN" here without having run that check would be exactly the
fabricated-receipt failure mode this codebase's fail-closed culture exists
to prevent -- worse than leaving the slot UNMEASURABLE. This script
therefore writes selection_evidence.verdict = "DECONTAMINATION_NOT_PERFORMED"
and a companion receipt naming the blocker; it never touches the frozen
manifest path or FROZEN_SLICE_SHA256 in cbase_heldout_eval.py. A human (or
a follow-up task with the matcher ported) promotes the candidate once
decontamination is genuinely run.

CLI: --shard-dir (required, real shard bytes) --out (candidate manifest
path) --receipt-out (companion finding receipt) --window-count (default 16,
matching the invalidated slice's count for direct comparability) --dry-run
(compute + print, write nothing). Read-only against receipts/shard bytes
except for its own two output files. No GPU. No model. No checkpoint.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
NC = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import fineweb_exclusion as fx      # noqa: E402
import token_shards_v0 as tsv       # noqa: E402

SHARD_RECEIPT_NAME = "token-shards-v0-20260611T170047Z.json"
ISSUE = "#760"
SCALE = "W1_FROM_SCRATCH_PILOT_BASELINE"

# Highest max_training_window_index_at_ceiling receipted ANYWHERE in this
# repo as of 2026-08-05 (grepped across receipts/ -- the next-highest values
# found were 159 and 2495; every other disjointness receipt in the tree
# reuses this same W1 pilot number). window index is inclusive; the ceiling
# TOKEN is (index+1)*seq. Re-grep before reusing this constant if training
# has advanced since this script was written -- it is a snapshot, not a
# live query, because no single aggregate "all consumption ranges" receipt
# exists yet (a real gap; see the emitted finding receipt's `notes`).
MAX_RECEIPTED_TRAINING_WINDOW_CEILING = 24527
TRAINING_CONSUMPTION_SOURCE = (
    "highest max_training_window_index_at_ceiling receipted anywhere in the "
    "repo as of 2026-08-05 (W1 pilot ceiling; see "
    "receipts/ember-c-scale/w2-heldout-decontam-20260708T121128Z.json and "
    "receipts/ember-c-scale/w1-collapse-control-20260707T*.json). No single "
    "aggregate receipt of every training run's consumed range exists; this "
    "is the maximum found by grep, not a closed-form proof of everything "
    "ever consumed -- disclosed as a limitation in the finding receipt.")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def cumulative_shard_offsets(receipt: dict) -> tuple[dict, int]:
    """{shard_name: (global_start, global_end_exclusive)} in receipt shard
    order (shards are a flat concatenated stream -- PackedShardLoader reads
    them in listed order). Returns (offsets, total_tokens); total_tokens is
    cross-checked against the receipt's own total_stream_tokens by the
    caller, never trusted silently."""
    offsets = {}
    cursor = 0
    for s in receipt["shards"]:
        n = s["n_tokens"]
        offsets[s["name"]] = (cursor, cursor + n)
        cursor += n
    return offsets, cursor


def pick_clean_shard(receipt: dict, excluded_ranges: list[tuple[int, int]]) -> tuple[str, int, int]:
    """The first WHOLLY-clean shard (its entire global range outside every
    excluded range) at or after the excluded region -- not merely a clean
    shard anywhere, so the choice stays maximally far from the low end of
    the stream where training consumption concentrates. Raises if none."""
    offsets, total = cumulative_shard_offsets(receipt)
    if total != receipt["total_stream_tokens"]:
        raise SystemExit(f"REGEN_REFUSED: sum(shard n_tokens) {total} != "
                         f"receipt total_stream_tokens {receipt['total_stream_tokens']}")
    exclusion_end = max((ee for _es, ee in excluded_ranges), default=0)
    candidates = [(name, s, e) for name, (s, e) in offsets.items() if s >= exclusion_end]
    for name, start, end in sorted(candidates, key=lambda row: row[1]):
        if not any(fx._overlaps(start, end, es, ee) for es, ee in excluded_ranges):
            return name, start, end
    raise SystemExit("REGEN_REFUSED: no shard is entirely outside every excluded range")


def select_windows(shard_name: str, shard_start: int, shard_len: int, *,
                   seq: int, n_mtp: int, count: int, training_ceiling_token: int) -> list[dict]:
    """`count` windows, evenly strided across the shard's usable window
    range -- deterministic and reproducible (same inputs always produce the
    same windows), no manual cherry-picking. Every window is asserted past
    the training ceiling before being accepted; this is defense in depth
    (the shard was already chosen far past it), not the primary proof."""
    block_len = seq + 1 + n_mtp
    n_windows_in_shard = (shard_len - block_len) // seq + 1
    if n_windows_in_shard < count:
        raise SystemExit(f"REGEN_REFUSED: shard {shard_name} too small for "
                         f"{count} windows (only {n_windows_in_shard} available)")
    stride = n_windows_in_shard // count
    out = []
    for k in range(count):
        local_index = k * stride
        local_start = local_index * seq
        global_start = shard_start + local_start
        if global_start < training_ceiling_token:
            raise SystemExit(f"REGEN_REFUSED: window at global {global_start} is "
                             f"below the training ceiling {training_ceiling_token}")
        window_index = global_start // seq
        out.append({
            "window_index": window_index,
            "shard_name": shard_name,
            "shard_token_start": local_start,
            "shard_token_end_exclusive": local_start + seq + 1,
            "source_shard_token_end_exclusive": local_start + block_len,
            "global_token_start": global_start,
            "global_token_end_exclusive": global_start + seq + 1,
            "source_global_token_end_exclusive": global_start + block_len,
        })
    return out


def build_candidate(*, shard_dir: Path, window_count: int) -> tuple[dict, dict]:
    receipt_path = NC / "receipts" / SHARD_RECEIPT_NAME
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    violations = tsv.validate_shards_receipt(receipt, str(NC), shard_dir_override=str(shard_dir))
    if violations:
        raise SystemExit(f"REGEN_REFUSED: {SHARD_RECEIPT_NAME} FAILS validation "
                         f"against on-disk shard bytes: {violations}")
    excluded_sources = fx.ruled_excluded_sources(str(NC))
    assembly_name = receipt["premises"]["assembly_receipt"]["name"]
    excluded_ranges, reason = fx.enforcement_for_validated_receipt(
        receipt, nc=str(NC), assembly_name=assembly_name, excluded_sources=excluded_sources)
    if not excluded_ranges:
        raise SystemExit(f"REGEN_REFUSED: derived zero excluded ranges ({reason}) "
                         "-- refusing to proceed on an unproven exclusion set")

    shard_name, shard_start, shard_end = pick_clean_shard(receipt, excluded_ranges)
    shard_meta = next(s for s in receipt["shards"] if s["name"] == shard_name)
    on_disk_sha = _sha256(shard_dir / shard_name)
    if on_disk_sha != shard_meta["sha256"]:
        raise SystemExit(f"REGEN_REFUSED: {shard_name} on-disk sha256 {on_disk_sha[:12]} "
                         f"!= receipted {shard_meta['sha256'][:12]}")

    seq, n_mtp = tsv.SEQ, tsv.N_MTP
    training_ceiling_token = MAX_RECEIPTED_TRAINING_WINDOW_CEILING * seq + tsv.BLOCK_LEN
    windows = select_windows(shard_name, shard_start, shard_meta["n_tokens"], seq=seq, n_mtp=n_mtp,
                             count=window_count, training_ceiling_token=training_ceiling_token)
    for row in windows:
        gs, ge = row["global_token_start"], row["source_global_token_end_exclusive"]
        for es, ee in excluded_ranges:
            if fx._overlaps(gs, ge, es, ee):
                raise SystemExit(f"REGEN_REFUSED: selected window {row['window_index']} "
                                 f"overlaps excluded range [{es},{ee}) -- selection bug")

    combined_sha256 = hashlib.sha256(json.dumps(
        [shard_meta["sha256"]], separators=(",", ":")).encode("ascii")).hexdigest()
    manifest = {
        "schema": "cbase-heldout-slice/v1",
        "issue": ISSUE,
        "captured_public_master": _git_head(NC),
        "source_corpus": {
            "combined_sha256": combined_sha256,
            "receipt_path": f"receipts/{SHARD_RECEIPT_NAME}",
            "receipt_sha256": _sha256(receipt_path),
            "shards": [{"name": shard_name, "sha256": shard_meta["sha256"],
                       "n_tokens": shard_meta["n_tokens"],
                       "global_token_start": shard_start,
                       "global_token_end_exclusive": shard_end}],
        },
        "selection_evidence": {
            "path": "receipts/cbase-heldout-eval/issue-760-slice-regeneration-finding.json",
            "sha256": "0" * 64,   # filled in after the finding receipt is written; see main()
            "batch_sha256": "0" * 64,
            "verdict": "DECONTAMINATION_NOT_PERFORMED",
        },
        "sequence": {"dtype": "<u2", "seq": seq, "n_mtp": n_mtp, "separator_id": tsv.SEPARATOR_ID,
                    "packed_bytes_per_token": 2, "scoring": "primary_next_token_only"},
        "training_consumption": [{
            "source": TRAINING_CONSUMPTION_SOURCE,
            "window_start": 0, "window_end_exclusive": MAX_RECEIPTED_TRAINING_WINDOW_CEILING + 1,
            "global_token_start": 0, "global_token_end_exclusive": training_ceiling_token,
        }],
        "windows": windows,
        "expected_scored_token_count": len(windows) * seq,
        "scale": SCALE,
        "availability": {"status": "AVAILABLE", "missing": [],
                         "note": f"{shard_name} verified present on disk with matching sha256 "
                                 "at regeneration time, rehashed against the pinned "
                                 f"{SHARD_RECEIPT_NAME} entry (no local filesystem path recorded "
                                 "here by design -- shard_dir is a per-machine data-store "
                                 "location, not part of the corpus's identity)."},
        "claim_boundary": ("CANDIDATE slice: exclusion-clean (fineweb_exclusion-verified) and "
                           "training-range-disjoint (arithmetic-verified). NOT decontamination-"
                           "verified (no n-gram contamination_recheck run -- see selection_evidence "
                           "and the companion finding receipt). NOT the frozen production slice. "
                           "No heldout metric, capability, same-quality, or milestone-completion "
                           "claim."),
    }

    finding = {
        "ticket": "ISSUE-760-SLICE-REGENERATION-FINDING",
        "issue": ISSUE,
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "status": "FROZEN_SLICE_INVALIDATED_REPLACEMENT_BLOCKED",
        "invalidated_slice": {
            "path": "manifests/cbase-heldout-slice-v1.json",
            "shard": "v0-00016.bin",
            "shard_global_range": [4294967296, 4563402752],
            "reason": ("entirely inside the ruled-excluded fineweb_edu range "
                      "[4055121325, 5723508974); the exclusion ruling (2026-08-04 L3 audit, "
                      "#1436) postdates this slice's PR (#1228, merged 2026-07-30) by 5 days"),
            "proof": ("python -B scripts/cbase_heldout_eval.py --validate-only --shard-dir "
                     "<real shards> exits 2 with SLICE_OVERLAPS_EXCLUDED_SOURCE against the "
                     "committed manifest, using the verify_slice_excludes_ruled_sources check "
                     "added in this same change"),
        },
        "candidate_slice": {
            "shard": shard_name,
            "shard_global_range": [shard_start, shard_end],
            "window_count": len(windows),
            "exclusion_verified": True,
            "exclusion_ranges_checked": [list(r) for r in excluded_ranges],
            "training_disjointness_verified": True,
            "training_disjointness_method": "range arithmetic only (see training_consumption source)",
            "decontamination_verified": False,
        },
        "blocker": {
            "what": "n-gram contamination_recheck was not re-run for the candidate windows",
            "why_not_run": ("the only implementation is scripts/w1_collapse_control_run.py:"
                           "contamination_recheck; that file imports timeshare_pretrain at "
                           "module scope (line 76), and timeshare_pretrain.py raises SystemExit "
                           "at module scope under the 2026-07-12 historical_only execution-"
                           "denial lock -- importing either to call it would violate that lock"),
            "resolution_paths": [
                "port contamination_recheck into a standalone, non-execution-denied module, "
                "mirroring how cbase_heldout_eval.py's own eval_loss mechanism was ported out "
                "of the same file for #760 Deliverable 1 (named follow-up, not attempted here)",
                "an explicit operator decision to accept range-arithmetic-only disjointness for "
                "this specific replacement slice, promoting the candidate manifest by hand",
            ],
        },
        "limitations": [
            "MAX_RECEIPTED_TRAINING_WINDOW_CEILING (24527 windows / 25,116,675 tokens) is the "
            "highest value found by grepping receipts/ for max_training_window_index_at_ceiling "
            "as of 2026-08-05, not a query against a single aggregate consumption ledger -- no "
            "such ledger exists yet. The candidate shard starts at global token "
            f"{shard_start:,}, ~{shard_start // max(training_ceiling_token, 1):,}x that ceiling, "
            "so this is not a close call, but it is a grep-derived bound, not a closed-form proof.",
        ],
        "api_spend_usd": 0.0,
        "paid_api_surface_used": False,
        "no_gpu": True,
        "goal_id": "EMBER-02",
        "workstream_id": "EMBER-02A",
        "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
    }
    return manifest, finding


def _git_head(nc: Path) -> str:
    import subprocess
    out = subprocess.run(["git", "-C", str(nc), "rev-parse", "origin/master"],
                         capture_output=True, text=True, check=False)
    sha = out.stdout.strip()
    return sha if len(sha) == 40 else "0" * 40


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--shard-dir", required=True)
    parser.add_argument("--window-count", type=int, default=16)
    parser.add_argument("--out", default=str(NC / "manifests" /
                                             "cbase-heldout-slice-v1-CANDIDATE.json"))
    parser.add_argument("--receipt-out", default=str(
        NC / "receipts" / "cbase-heldout-eval" / "issue-760-slice-regeneration-finding.json"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    manifest, finding = build_candidate(shard_dir=Path(args.shard_dir), window_count=args.window_count)

    if args.dry_run:
        print(json.dumps({"candidate_shard": manifest["source_corpus"]["shards"][0]["name"],
                          "window_count": len(manifest["windows"]),
                          "status": finding["status"]}, sort_keys=True))
        return 0

    receipt_out = Path(args.receipt_out)
    receipt_out.parent.mkdir(parents=True, exist_ok=True)
    finding_payload = json.dumps(finding, sort_keys=True, separators=(",", ":")) + "\n"
    receipt_out.write_text(finding_payload, encoding="utf-8", newline="\n")
    manifest["selection_evidence"]["sha256"] = _sha256(receipt_out)
    manifest["selection_evidence"]["batch_sha256"] = manifest["selection_evidence"]["sha256"]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    out_path.write_text(manifest_payload, encoding="utf-8", newline="\n")
    manifest_sha = _sha256(out_path)

    print(f"REGENERATE_CANDIDATE_WRITTEN {out_path} sha256={manifest_sha}")
    print(f"REGENERATE_FINDING_WRITTEN {receipt_out}")
    print(json.dumps({"candidate_shard": manifest["source_corpus"]["shards"][0]["name"],
                      "candidate_manifest_sha256": manifest_sha,
                      "window_count": len(manifest["windows"]),
                      "decontamination_verified": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
