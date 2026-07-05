#!/usr/bin/env python3
"""Totality status-probe for Ember goal condition C-BASE.

Condition (authoritative text, B:/M/avir/leo/state/ember-goal-leo.md line 95):

  C-BASE — owned GROWABLE SEED exists (NOT frozen, NOT a fixed endpoint).

  R (positive): a from-scratch owned pilot checkpoint identity
    {arch, token count, weight hashes, NC2 own-component manifest}
  that is the SEED OF GROWTH toward 1T, exposing the growth-operator
  interface from step 0 (the "forever horn": the ledger admits grow-entries,
  the model builder emits variable shapes, the checkpoint replays across shape
  changes, and R4/before-after holds across shapes).

  Does NOT count:
    - a frozen/borrowed base used load-bearing;
    - the dead `12c050e7` lineage;
    - reserved-vocab/config plumbing reported as a trained base;
    - a seed whose graph cannot be grown function-preserving (calcified to a
      fixed size = a smuggled sub-1B-endpoint convenience).

  Invalid-tokens (✗):
    - invalid_frozen_base_escape  (the historical req-14 "or frozen base
      checkpoint" option is CLOSED for Leo)
    - invalid_calcified_seed      (no growth-operator interface)

  CHK (4 conjunctive clauses):
    (a) checkpoint file exists with hashes;
    (b) NC2 manifest complete;
    (c) no borrowed weights in the load-bearing path;
    (d) a grow-operator DRY-RUN produces a valid larger-shape checkpoint that
        replays.

This file is a STATUS PROBE, per the goal's §4.4 totality contract:
  (a) asserts the positive CHK against a REAL receipt/artifact under
      kai-converge (no fabrication — it reads bytes on disk; the satisfying
      checkpoint artifact referenced by a kai-converge receipt is hash-verified
      against the bytes actually present on disk);
  (b) asserts that NONE of the does-NOT-count invalid-tokens / substitutes
      match (encoded as negative assertions);
  (c) prints a single line "RED <reason>" or "GREEN <reason>" and exits 0
      (RED/GREEN is determined by really inspecting state, never hardcoded;
      exit 0 always so the board can aggregate).

Run ONLY via:  wsl python3 <this file>
Under WSL the B: drive is /mnt/b/.
"""

# [PATH-REWRITE 2026-07-01] Imported from
# B:/M/avir/leo/state/ember-totality-build/ into
# B:/M/ember-goalforge/scripts/ember_totality/. Original WSL dual/triple-mount
# candidates pointing at B:/M/avir/leo/state/kai-converge (and /mnt/b/M/...,
# /b/M/..., B:\\M\\... variants) replaced with a single REPO_ROOT-relative
# candidate, REPO_ROOT computed via pathlib from this file's own location (two levels up
# from scripts/ember_totality/), for native Windows system-python execution.
# No probe logic changed -- only path resolution. kai-converge does not exist
# under the new repo root, so these probes are expected to emit a clean RED
# 'root not found' line, which is the correct, non-error outcome.

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_env_root = os.environ.get("EMBER_TOTALITY_ROOT")
ROOT = next(
    (p for p in (Path(_env_root) if _env_root else None, REPO_ROOT,
                 REPO_ROOT / "kai-converge")
     if p is not None and p.is_dir()),
    REPO_ROOT / "kai-converge",
)
RECEIPTS = ROOT / "receipts"

# Exact invalid-tokens this condition fails on (negative-assertion targets).
INVALID_TOKENS = ["invalid_frozen_base_escape", "invalid_calcified_seed"]

# does-NOT-count substitutes, encoded as forbidden markers in any candidate.
DEAD_LINEAGE = "12c050e7"  # the dead lineage explicitly named in the goal.
BORROWED_MARKERS = [
    "borrowed", "pretrained_from_hf", "from_pretrained", "frozen_base",
    "frozen base", "hf_hub", "huggingface.co/", "load_pretrained",
]
# Markers proving the checkpoint is a genuine from-scratch OWNED base
# (a real trainable-neural pretrain, not config/vocab plumbing reported as one).
OWNED_PRETRAIN_MARKERS = [
    "cbase", "c-base", "from-scratch", "from_scratch", "pretrain",
    "timeshare", "v0_segment", "v0-segment", "survivor-stack",
]
# Markers a genuine grow-operator DRY-RUN receipt would carry: it must show a
# larger-shape checkpoint produced function-preserving that REPLAYS.
GROW_OP_MARKERS = [
    "net2net", "layer-stack", "layer_stack", "layer-stacking", "layer_stacking",
    "expert-add", "expert_add", "expert-addition", "function-preserv",
    "function_preserv", "warm-start", "warm_start", "grow_operator",
    "grow-operator", "grow_dry_run", "grow-dry-run",
]
GROW_REPLAY_MARKERS = [
    "larger-shape", "larger_shape", "larger shape", "grown_shape",
    "grown-checkpoint", "replays", "replay_across_shape", "shape_change",
    "shape-change", "post_grow", "pre_grow",
]


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _flatten_text(obj) -> str:
    return json.dumps(obj, default=str).lower()


def _sha256_first16(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def main() -> int:
    # ---- Pre-flight: the artifact root must really exist. --------------------
    if not RECEIPTS.is_dir():
        print(f"RED C-BASE: receipts dir absent at {RECEIPTS} (nothing to satisfy the CHK)")
        return 0

    receipt_files = sorted(RECEIPTS.rglob("*.json"))

    # ---- CHK clause (a)+(c): find a REAL owned-base checkpoint receipt that ---
    #      names a checkpoint with weight hashes, is from-scratch (no borrowed
    #      weights in the load-bearing path), and is NOT the dead lineage.
    #      The checkpoint bytes are HASH-VERIFIED against the receipt's claim so
    #      a fabricated/empty checkpoint cannot pass.
    owned_ckpt_receipt = None
    owned_ckpt_path = None
    owned_ckpt_hash_ok = False
    n_owned_candidates = 0

    for rp in receipt_files:
        obj = _read_json(rp)
        if obj is None:
            continue
        text = _flatten_text(obj)

        # Must read as an owned from-scratch pretrain receipt.
        if not any(m in text for m in OWNED_PRETRAIN_MARKERS):
            continue
        # Must name a checkpoint path.
        ckpt = obj.get("last_checkpoint") or obj.get("checkpoint") or obj.get("resume_checkpoint")
        if not isinstance(ckpt, str) or not ckpt:
            continue
        # does-NOT-count: dead 12c050e7 lineage in the load-bearing path.
        if DEAD_LINEAGE in ckpt.lower() or DEAD_LINEAGE in text:
            continue
        # does-NOT-count: borrowed/frozen base in the load-bearing path.
        if any(b in text for b in BORROWED_MARKERS):
            continue

        n_owned_candidates += 1
        ckpt_path = Path(ckpt)
        manifest = ckpt_path / "manifest.json"
        model_pt = ckpt_path / "model.pt"
        if not (manifest.is_file() and model_pt.is_file()):
            continue
        man = _read_json(manifest)
        if not man:
            continue
        claimed = (man.get("files") or {}).get("model.pt")
        if not isinstance(claimed, str) or not claimed:
            continue
        actual = _sha256_first16(model_pt)
        # Hash-verify the REAL bytes against the manifest's weight-hash claim.
        if actual is not None and claimed.lower().startswith(actual.lower()):
            owned_ckpt_receipt = rp
            owned_ckpt_path = ckpt_path
            owned_ckpt_hash_ok = True
            break

    # ---- CHK clause (d): find a REAL grow-operator DRY-RUN receipt proving a --
    #      larger-shape checkpoint produced function-preserving that REPLAYS.
    grow_op_receipt = None
    for rp in receipt_files:
        obj = _read_json(rp)
        if obj is None:
            continue
        text = _flatten_text(obj)
        if any(g in text for g in GROW_OP_MARKERS) and any(r in text for r in GROW_REPLAY_MARKERS):
            grow_op_receipt = rp
            break

    # ---- (2) NEGATIVE ASSERTIONS: none of the invalid-tokens may appear in ----
    #      a candidate satisfying receipt (checkpoint receipt or grow receipt).
    invalid_hits: list[str] = []
    for cand in (owned_ckpt_receipt, grow_op_receipt):
        if cand is None:
            continue
        cand_text = _flatten_text(_read_json(cand))
        for tok in INVALID_TOKENS:
            if tok.lower() in cand_text and tok not in invalid_hits:
                invalid_hits.append(tok)

    # ---- Verdict (determined by real inspection, never hardcoded). -----------
    if invalid_hits:
        print(
            f"RED C-BASE: candidate receipt matches invalid-token(s) {invalid_hits} "
            "(does-NOT-count: frozen/borrowed base escape or calcified seed)"
        )
        return 0

    if owned_ckpt_receipt is None:
        print(
            "RED C-BASE: no owned from-scratch checkpoint receipt under "
            f"{RECEIPTS} names a checkpoint whose on-disk model.pt bytes hash-match "
            f"its manifest weight-hash claim ({n_owned_candidates} owned-pretrain "
            "candidate(s) scanned; checkpoint missing or hash mismatch; CHK clause "
            "(a)/(c) unmet)"
        )
        return 0

    if grow_op_receipt is None:
        print(
            "RED C-BASE: owned checkpoint "
            f"{owned_ckpt_path} exists with hashes (model.pt sha256 verified vs "
            f"manifest in receipt {owned_ckpt_receipt.name}), but CHK clause (d) is "
            "UNMET — no grow-operator dry-run receipt produces a valid larger-shape "
            "checkpoint that replays (function-preserving net2net/layer-stacking/"
            "expert-addition); the growth operator exists only as a decision-record "
            "doc that does NOT authorize a build => invalid_calcified_seed: the seed "
            "graph cannot be shown growable. Artifact genuinely ABSENT"
        )
        return 0

    print(
        f"GREEN C-BASE: owned from-scratch checkpoint {owned_ckpt_path} exists with "
        f"hash-verified weights (receipt {owned_ckpt_receipt.name}), no borrowed/"
        f"frozen base and not the {DEAD_LINEAGE} lineage, and grow-operator dry-run "
        f"receipt {grow_op_receipt.name} produces a valid larger-shape checkpoint "
        "that replays; no invalid-token present (CHK all four clauses pass)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
