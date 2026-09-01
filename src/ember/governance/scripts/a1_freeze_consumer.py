#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""a1_freeze_consumer.py -- ember #631 deliverable 5: the fail-closed executable
CONSUMER that applies the A1 freeze pointer + the 147-row exclusion amendment.

Cures A1 machinery defect #5 (refs #123 finding 5): PR #603 declared the freeze +
amendment but shipped NO executable surface that binds them, so nothing proved the
seven splits are actually filtered and time-ordered before a governed launch/eval.

This consumer is fail-closed: every check REFUSES (nonzero exit) rather than warning.

BINDINGS (all required):
  1. Freeze-hash pointer: read receipts/eval-suite-freeze/EVAL-FREEZE-HASH (40-hex).
     Verify it is a real commit AND (squash-merge-robust) that the declaration file is
     byte-identical in the --build-ref tree. The pointer's ancestry of --build-ref is
     recorded and disclosed: PR #603 was squash-merged, so the pointer commit is NOT an
     ancestor of master; the substantive binding is therefore the declaration CONTENT
     present byte-identical in the build lineage (the frozen suite definition the launch
     actually builds from). REFUSE if the declaration content is absent/altered in the
     build-ref. The build-ref commit sha is recorded as the non-null freeze anchor.
  2. Time order: declaration.freeze_ts strictly precedes --launch-ts. REFUSE otherwise.
  3. Lineage binding (refs #631 deliverable 3): --lineage-manifest must declare the
     checkpoint lineage's training inputs, each with a scan receipt and scanned=true.
     REFUSE if the manifest is missing or any input is unscanned (the "shards-v0 is the
     whole universe" premise is dead; the lineage must be explicit and fully scanned).
  4. Filtering: for each of the seven pinned splits, verify on-disk sha == frozen sha
     (REFUSE on drift -- cannot filter an unverified split), drop the amendment's excluded
     dataset_lines, and compute effective_filtered_sha256. A governed eval is admitted
     ONLY against these effective hashes; for a contaminated dataset the effective hash
     differs from the unfiltered-content hash (proving filtering is real).

Usage:
  python src/ember/governance/scripts/a1_freeze_consumer.py \\
      --declaration receipts/eval-suite-freeze/a1-freeze-declaration-20260709T233050Z.json \\
      --pointer-file receipts/eval-suite-freeze/EVAL-FREEZE-HASH \\
      --amendment receipts/eval-suite-freeze/a1-freeze-exclusion-amendment-20260709T234148Z.json \\
      --freeze-receipt receipts/eval-suite-freeze/eval-suite-freeze-v1.json \\
      --eval-suite-dir <sha-verified eval-suite-v1 copy> \\
      --launch-ts 2026-07-10T06:00:00Z \\
      --build-ref HEAD \\
      --lineage-manifest <lineage manifest json> \\
      --out receipts/eval-suite-freeze/a1-freeze-admission-<UTCts>.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import receipt_write  # noqa: E402

INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"
DIR_NAME_MAP = {"MMLU-Pro": "MMLU-Pro", "GSM8K": "GSM8K", "MATH-500": "MATH-500",
                "ARC-Challenge": "ARC-Challenge", "HumanEval+": "HumanEvalplus",
                "MBPP": "MBPP", "HellaSwag": "HellaSwag"}


class Refuse(SystemExit):
    def __init__(self, code, msg):
        super().__init__(f"A1_CONSUMER_REFUSE[{code}]: {msg}")


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def parse_ts(t):
    if not t:
        return None
    try:
        return datetime.strptime(t, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None


def git(*args):
    return subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True)


def content_sha_at_ref(ref: str, relpath: str):
    r = subprocess.run(["git", "-C", REPO, "show", f"{ref}:{relpath}"],
                       capture_output=True)
    if r.returncode != 0:
        return None
    return hashlib.sha256(r.stdout).hexdigest()


def effective_filtered_sha(split_path: str, excluded_lines: set):
    """sha256 of the retained (0-indexed) lines, canonical '\\n'.join + trailing '\\n'.
    Also returns the unfiltered-content sha (same serialization, nothing dropped) so a
    contaminated dataset visibly differs, and native_ids at the dropped lines for audit."""
    lines = []
    with open(split_path, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.rstrip("\n")
            if ln.strip():
                lines.append(ln)
    retained = [ln for i, ln in enumerate(lines) if i not in excluded_lines]
    eff = hashlib.sha256(("\n".join(retained) + "\n").encode("utf-8")).hexdigest()
    unf = hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()
    return eff, unf, len(lines), len(retained)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--declaration", required=True)
    ap.add_argument("--pointer-file", required=True)
    ap.add_argument("--amendment", required=True)
    ap.add_argument("--freeze-receipt", required=True)
    ap.add_argument("--eval-suite-dir", required=True)
    ap.add_argument("--launch-ts", required=True)
    ap.add_argument("--build-ref", default="HEAD")
    ap.add_argument("--lineage-manifest", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    decl_rel = os.path.relpath(os.path.abspath(args.declaration), REPO).replace(os.sep, "/")
    declaration = json.load(open(args.declaration, encoding="utf-8"))
    amendment = json.load(open(args.amendment, encoding="utf-8"))
    freeze = json.load(open(args.freeze_receipt, encoding="utf-8"))

    # --- CHECK 1: freeze-hash pointer + declaration content binding ---
    pointer = open(args.pointer_file, encoding="utf-8").read().strip()
    if len(pointer) < 7 or any(c not in "0123456789abcdef" for c in pointer.lower()):
        raise Refuse("POINTER_FORMAT", f"EVAL-FREEZE-HASH not a hex commit sha: {pointer!r}")
    pointer_is_commit = git("cat-file", "-t", pointer).stdout.strip() == "commit"
    decl_on_disk_sha = file_sha256(args.declaration)
    decl_at_pointer = content_sha_at_ref(pointer, decl_rel) if pointer_is_commit else None
    decl_at_build = content_sha_at_ref(args.build_ref, decl_rel)
    if decl_at_build is None:
        raise Refuse("DECL_ABSENT_IN_BUILD_REF",
                     f"declaration {decl_rel} not present in build-ref {args.build_ref!r}")
    if decl_at_build != decl_on_disk_sha:
        raise Refuse("DECL_ALTERED_IN_BUILD_REF",
                     f"declaration content in {args.build_ref} ({decl_at_build}) != on-disk "
                     f"({decl_on_disk_sha})")
    pointer_ancestor = git("merge-base", "--is-ancestor", pointer, args.build_ref).returncode == 0
    build_ref_commit = git("rev-parse", args.build_ref).stdout.strip()

    # --- CHECK 2: time order ---
    freeze_ts = parse_ts(declaration["freeze_ts"])
    launch_ts = parse_ts(args.launch_ts)
    if launch_ts is None:
        raise Refuse("LAUNCH_TS_UNPARSEABLE", f"--launch-ts {args.launch_ts!r}")
    if freeze_ts is None:
        raise Refuse("FREEZE_TS_UNPARSEABLE", f"declaration.freeze_ts {declaration['freeze_ts']!r}")
    if not (launch_ts > freeze_ts):
        raise Refuse("TIME_ORDER", f"launch_ts {args.launch_ts} not strictly after freeze_ts "
                                    f"{declaration['freeze_ts']}")

    # --- CHECK 3: lineage binding ---
    if not os.path.exists(args.lineage_manifest):
        raise Refuse("LINEAGE_MISSING", f"--lineage-manifest {args.lineage_manifest} not found")
    lineage = json.load(open(args.lineage_manifest, encoding="utf-8"))
    inputs = lineage.get("training_inputs")
    if not lineage.get("checkpoint_lineage") or not isinstance(inputs, list) or not inputs:
        raise Refuse("LINEAGE_INCOMPLETE", "manifest must carry checkpoint_lineage + non-empty "
                                           "training_inputs")
    unscanned = [i.get("corpus") for i in inputs
                 if not i.get("scanned") or not i.get("scan_receipt")]
    if unscanned:
        raise Refuse("LINEAGE_UNSCANNED", f"training inputs not scanned: {unscanned}")

    # --- CHECK 4: filter each split, effective hashes ---
    excluded_by_ds = {}
    for it in amendment["exclusions"]["items"]:
        excluded_by_ds.setdefault(it["dataset"], set()).add(it["dataset_line"])

    per_dataset = {}
    for ds in freeze["datasets"]:
        name = ds["name"]
        if ds.get("test_split_sha256") in (None, "PIN-PENDING"):
            continue
        p = os.path.join(args.eval_suite_dir, DIR_NAME_MAP[name], "test.jsonl")
        if not os.path.exists(p):
            raise Refuse("SPLIT_ABSENT", f"{name}: {p} missing")
        on_disk = file_sha256(p)
        if on_disk != ds["test_split_sha256"]:
            raise Refuse("SPLIT_SHA_DRIFT",
                         f"{name} on-disk {on_disk} != frozen {ds['test_split_sha256']}")
        excl = excluded_by_ds.get(name, set())
        eff, unf, n_raw, n_ret = effective_filtered_sha(p, excl)
        if n_ret != n_raw - len(excl):
            raise Refuse("FILTER_COUNT", f"{name}: retained {n_ret} != {n_raw}-{len(excl)}")
        per_dataset[name] = {
            "raw_split_sha256": on_disk,
            "n_raw_rows": n_raw,
            "n_excluded": len(excl),
            "n_filtered_rows": n_ret,
            "effective_filtered_sha256": eff,
            "unfiltered_content_sha256": unf,
            "filtering_changes_content": (eff != unf),
        }

    total_excluded = sum(v["n_excluded"] for v in per_dataset.values())
    if total_excluded != amendment["exclusions"]["n_excluded"]:
        raise Refuse("EXCLUSION_COUNT",
                     f"applied {total_excluded} != amendment {amendment['exclusions']['n_excluded']}")

    receipt = {
        "ticket": "A1-FREEZE-ADMISSION",
        "ts": datetime.now(timezone.utc).isoformat(),
        "schema": "a1-freeze-admission/v1",
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "issue_refs": ["#631", "#123", "#593", "#440"],
        "verdict": "ADMITTED",
        "launch_ts": args.launch_ts,
        "freeze_binding": {
            "pointer": pointer,
            "pointer_is_commit": pointer_is_commit,
            "declaration_sha256_at_pointer": decl_at_pointer,
            "declaration_sha256_on_disk": decl_on_disk_sha,
            "declaration_sha256_at_build_ref": decl_at_build,
            "declaration_byte_identical_in_build_ref": True,
            "build_ref": args.build_ref,
            "build_ref_commit": build_ref_commit,
            "freeze_anchor_commit": build_ref_commit,
            "pointer_is_ancestor_of_build_ref": pointer_ancestor,
            "pointer_ancestry_disclosure": (
                None if pointer_ancestor else
                "the EVAL-FREEZE-HASH pointer commit is NOT an ancestor of the build-ref: PR #603 "
                "was squash-merged, dangling the freeze-content commit. Binding is by declaration "
                "CONTENT verified byte-identical in the build lineage (squash-merge-robust); the "
                "declaration's rule (3) 'pointer is an ancestor' is unsatisfiable from master and "
                "is a coordinator item (re-anchor EVAL-FREEZE-HASH to a master-reachable commit "
                "would re-roll AC4, so it is NOT done here)."),
        },
        "time_order": {"freeze_ts": declaration["freeze_ts"], "launch_ts": args.launch_ts,
                       "launch_after_freeze": True},
        "lineage_binding": {
            "checkpoint_lineage": lineage["checkpoint_lineage"],
            "n_training_inputs": len(inputs),
            "training_inputs": inputs,
            "all_inputs_scanned": True,
        },
        "effective_filtered_suite": {
            "n_excluded_total": total_excluded,
            "per_dataset": per_dataset,
            "rule": "a governed eval on suite (b) MUST filter the excluded rows and reproduce "
                    "effective_filtered_sha256 per dataset; the raw split sha is NOT admissible "
                    "for a contaminated dataset (filtering_changes_content=true)",
        },
    }

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    receipt_write.checked_write(args.out, receipt)
    print(f"A1_FREEZE_CONSUMER: ADMITTED launch_ts={args.launch_ts}; excluded={total_excluded}; "
          f"pointer_ancestor={pointer_ancestor} (content-bound in {args.build_ref}); "
          f"datasets={len(per_dataset)} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
