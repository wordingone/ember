#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""r1_exit_battery.py -- EMBER-02 R1 (WARM-100) exit-criteria derivation battery.

Companion to scripts/r2_cheap_probe_battery.py (#1435): same posture ("the spec is
the authority; invention is prohibited; reporting one unimplementable check
accurately is worth more than five plausible guesses"), same receipt envelope
(ticket/ts/schema/sha_convention/invariant_sha256/prereg block via receipt_check
+ receipt_write.checked_write), same fail-closed refusal discipline. Read that
script's docstring first if this one is confusing -- it explains the shared
conventions in more depth than is repeated here.

============================================================================
HEADLINE FINDING (derived 2026-08-05 while building this battery against the
run at <custody>/r1-warm100-20260804 -- read before trusting
any exit code this script prints):
============================================================================

That run is NOT the R1 WARM-100 100-consecutive-step canary. It is a
`governed-vertical` structural/plumbing check: tools/ember-restart-3b/
run_vertical_slice.py's own docstring says governed-vertical "routes one
record through every specialist" -- exactly 4 records (one per expert:
vision/audio/reasoning/tool) from a fixed `owned-four-domain-production-
rung-v1` shard. The checkpoint's own data_cursor proves it: global_step=4,
record_index=4, tokens_seen=36. Independently confirmed by a same-day resume
attempt (r2-resume-20260804) against this exact checkpoint, which crashed
immediately with "production resume cursor has no remaining authorized
records" -- there is no step 5 under this mode, ever, at any --max-records.

Worse: governed-vertical's CLI parser (run_vertical_slice.py `main()`) has NO
--telemetry-path flag at all. run_governed_vertical() never passes
telemetry_path/telemetry_run_id into run(), so append_training_telemetry is
architecturally unreachable on this path -- zero per-step loss/grad-norm was
ever recorded, for this or any governed-vertical run. The only subcommand
that wires --telemetry-path/--telemetry-run-id as required arguments is
`specialist` (single-capability continuation training off an existing
checkpoint). `semantic` (which does take --steps) ALSO has no telemetry
flags wired in main().

And it is categorical, not incidental: certified_train_launch.py's
_require_scope_subset hard-fails unless the certificate's
authorized["allowed_modes"] == ["governed-vertical"] exactly. The currently
issued launch certificate authorizes governed-vertical ONLY -- semantic /
specialist / plain vertical cannot be launched through the sanctioned path
today at any step count. A real R1-E1 needs an engineering task (wire
telemetry through a 100+-step-capable mode, then extend/reissue the
certificate), not a different flag on today's command.

Net effect on this battery: 7 of R1's 8 exits (E1, E2, E4, E5, E6, E7, E8)
are pure EVIDENCE-MISSING against every run this repo has ever produced --
this script proves that with receipts rather than asserting it in prose,
and is written so the day real evidence exists (telemetry file, second
seed, A1 arm run, frontier receipt, forecast doc) it adjudicates in one
command with zero further code changes. Only E3 yields a real, scoped,
DERIVABLE-NOW sub-receipt today (checkpoint write-side hash integrity) --
it stays NOT-MET overall because the restore leg has never been exercised
(the one attempt crashed on a bookkeeping guard before reaching restore
code, not because restore itself failed or passed).

SCOPE BOUNDARIES (disclosed, not silent gaps):
  * verify_checkpoint_write_integrity does NOT reuse
    scripts/ember_restart_eval_checkpoint_consumer.py's `_verify` -- that
    function is pinned to schema_version "ember-sparse-checkpoint-v3" with a
    single shared_optimizer_shard_sha256 field; the real checkpoint on disk
    is schema "ember-sparse-checkpoint-v5" with a 7-shard list (v3 and v5
    are different, undocumented-diff formats). Reusing a verifier that would
    reject the real artifact by construction is worse than a disclosed,
    narrow, purpose-built v5 byte-hash check. Also deliberately avoids
    importing tools/ember-restart-3b/checkpoint_artifacts.py (torch at
    module scope) for a check that is pure hashlib -- no GPU/CUDA, no torch,
    ever, in this file.
  * R1-E7's sigma_seed computation method is NOT frozen anywhere in this
    repo (same gap #1435 disclosed for R2-E4/D-01's CI method). This
    script's disclosed default: per-step population variance across seed
    replicas at each matched step, pooled by averaging those per-step
    variances, sigma = sqrt(pooled variance). A different superseding
    method is a receipt-schema change, not a code rewrite (see
    `pooled_sigma_seed`).
  * check_r1_e5 confirms the §5.2 fixed-prior manifest exists and is
    hash-checkable (one of §5.4's 8 ledger field classes) but does not
    attempt to assemble a full closed-boundary frontier receipt -- no
    frontier-receipt generator exists anywhere in this repo (verified by
    repo-wide grep 2026-08-05), and inventing one is out of this script's
    scope (a frontier receipt needs a real >=100-step run's energy/time
    legs to exist first; see the inventory doc's needs-execution plan).
  * check_r1_e8 looks for ANY A1-labeled run evidence (dense mechanism,
    tier1/tier2 markers) under the given search roots. It does not invent
    an A1 checkpoint schema (none exists anywhere in this repo as of
    2026-08-05) -- absence is reported as EVIDENCE_MISSING, not guessed at.

Refusal reasons (R1ExitBatteryRefusal, always prefixed onto the message):
  RUN_ROOT_MISSING, THRESHOLDS_UNREADABLE, THRESHOLDS_SCHEMA_INVALID,
  THRESHOLDS_PIN_MISMATCH, THRESHOLDS_MISSING_IDS, CHECKPOINT_MANIFEST_MISSING,
  CHECKPOINT_MANIFEST_UNREADABLE, CHECKPOINT_MANIFEST_SCHEMA_UNRECOGNIZED,
  CHECKPOINT_AMBIGUOUS, OUTPUT_PATH_REQUIRED, UNKNOWN_EXIT_ID.

Usage:
  python scripts/r1_exit_battery.py --selftest
  python scripts/r1_exit_battery.py --run-root <path> --exit e1 --out-dir receipts/ember-02-r1-exits
  python scripts/r1_exit_battery.py --run-root <path> --sibling-root <path> --exit e3 --out-dir ...
  python scripts/r1_exit_battery.py --run-root <path> --seed-root <path> --seed-root <path> --exit e7 --out-dir ...
  python scripts/r1_exit_battery.py --run-root <path> --sibling-root <path> --seed-root <path> --exit all --out-dir ...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import statistics
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ISSUE_REF = "#1463"
PREREG_DOC = "docs/spec/ember02-preregistration-v1.md"
PREREG_PIN = "3d48d3870919bd04cec735f68d0fad45fcfae0b2"
RECEIPT_SCHEMA = "r1-exit-battery/v1"

SHA_CONVENTION = (
    "sha256 over on-disk raw bytes (binary read, no line-ending "
    "normalization) for checkpoint/manifest/telemetry/threshold files"
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_THRESHOLDS_PATH = REPO_ROOT / "docs" / "spec" / "ember02-preregistration-thresholds-v1.json"
DEFAULT_FIXED_PRIOR_MANIFEST = REPO_ROOT / "manifests" / "ember-restart-3b" / "fixed-prior-manifest-v1.json"

REQUIRED_THRESHOLD_IDS = {"T-01", "T-02", "T-03", "T-04", "T-05", "T-06", "T-07", "T-08", "T-09"}

# The checkpoint schema this battery's write-integrity check understands.
# ember-sparse-checkpoint-v3 (a different, undocumented-diff format -- see
# module docstring) is deliberately NOT accepted here.
SUPPORTED_CHECKPOINT_SCHEMA = "ember-sparse-checkpoint-v5"
CHECKPOINT_TOP_LEVEL_SHA_FIELDS = {
    "shared_model": "shared_model_shard_sha256",
    "optimizer_state": "optimizer_state_shard_sha256",
}
CHECKPOINT_EXPERT_ROLE_PREFIX = "expert_"  # role "expert_vision" -> expert_checkpoint_sha256["vision"]


class R1ExitBatteryRefusal(Exception):
    """Fail-closed refusal (missing input, unreadable/unrecognized bytes,
    ambiguous subject) -- never a silent skip, never a default value, never
    a trivial pass."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_safe_number(value: Any) -> Any:
    """Receipts must be strictly valid JSON. A NaN/Inf loss or grad_norm is
    exactly the finding R1-E1 exists to catch -- embed it as a disclosed
    non-finite marker instead of a raw float (json.dumps would otherwise
    emit the literal tokens NaN/Infinity, which most JSON parsers reject)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            return {"non_finite": True, "repr": repr(value)}
        return value
    return value


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ---------------------------------------------------------------------------
# Thresholds (T-01..T-09 etc.) -- loaded at runtime, never hand-transcribed,
# content-hash-bound into every receipt via `prereg.thresholds_sha256`.
# ---------------------------------------------------------------------------

def load_thresholds(path: str | Path | None = None) -> tuple[dict[str, Any], str]:
    path = Path(path) if path is not None else DEFAULT_THRESHOLDS_PATH
    if not path.is_file():
        raise R1ExitBatteryRefusal(f"THRESHOLDS_UNREADABLE: {path} does not exist")
    try:
        raw = path.read_bytes()
        doc = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise R1ExitBatteryRefusal(f"THRESHOLDS_UNREADABLE: {path}: {exc}") from exc
    if (
        not isinstance(doc, dict)
        or doc.get("schema_version") != "ember02-preregistration-thresholds-v1"
        or doc.get("frozen") is not True
    ):
        raise R1ExitBatteryRefusal(f"THRESHOLDS_SCHEMA_INVALID: {path} is not a recognized frozen thresholds document")
    if doc.get("ember_pin") != PREREG_PIN:
        raise R1ExitBatteryRefusal(
            f"THRESHOLDS_PIN_MISMATCH: {path} ember_pin={doc.get('ember_pin')!r} expected={PREREG_PIN!r}"
        )
    values: dict[str, Any] = {}
    for entry in doc.get("entries", []):
        if not isinstance(entry, dict) or "id" not in entry:
            continue
        if entry.get("frozen_form") == "number":
            values[entry["id"]] = entry.get("value")
        elif entry.get("frozen_form") == "formula":
            values[entry["id"]] = entry.get("formula")
    missing = REQUIRED_THRESHOLD_IDS - set(values)
    if missing:
        raise R1ExitBatteryRefusal(f"THRESHOLDS_MISSING_IDS: {path} is missing {sorted(missing)}")
    return values, _sha256_bytes(raw)


# ---------------------------------------------------------------------------
# Telemetry (append_training_telemetry's real emitted shape, run_vertical_
# slice.py lines ~353-378 and pretrain.py's progress payload: {"ts":...,
# "kind":"train_step","source":"ember-restart-3b","payload":{"run_id":...,
# "step":int,"loss":float,"grad_norm":float,...}}). No such file has ever
# been produced by any run inspected on 2026-08-05 (see module docstring) --
# this scanner is written so the day one exists, it is picked up unchanged.
# ---------------------------------------------------------------------------

def _iter_jsonl_events(path: Path):
    """Tolerant line-by-line JSONL reader -- skips oversized or malformed
    lines rather than refusing the whole file (mirrors run_vertical_slice.py
    `_latest_completed_training_step`'s recovery discipline)."""
    try:
        with path.open("rb") as handle:
            for raw_line in handle:
                if len(raw_line) > 4096:
                    continue
                try:
                    event = json.loads(raw_line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if isinstance(event, dict):
                    yield event
    except OSError:
        return


def find_telemetry_files(run_root: Path) -> list[Path]:
    """Every *.jsonl under run_root whose lines look like real
    ember-restart-3b telemetry (append_training_telemetry's exact shape:
    top-level "source"=="ember-restart-3b"). A file with zero matching
    lines is not returned -- an incidental unrelated .jsonl file must not
    be mistaken for a telemetry channel."""
    if not run_root.is_dir():
        return []
    found = []
    for candidate in sorted(run_root.rglob("*.jsonl")):
        for event in _iter_jsonl_events(candidate):
            if event.get("source") == "ember-restart-3b":
                found.append(candidate)
                break
    return found


def load_train_step_series(run_root: Path, *, run_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """Collect every train_step event across every telemetry file under
    run_root, grouped by run_id, deduplicated to the latest-by-ts row per
    (run_id, step) -- a resumed/retried step must not be double-counted.
    Returns {run_id: [ {step, loss, grad_norm, ts, ...} sorted by step ]}."""
    latest: dict[tuple[str, int], tuple[str, dict[str, Any]]] = {}
    for telemetry_path in find_telemetry_files(run_root):
        for event in _iter_jsonl_events(telemetry_path):
            if event.get("kind") != "train_step" or event.get("source") != "ember-restart-3b":
                continue
            payload = event.get("payload")
            ts = event.get("ts")
            if not isinstance(payload, dict) or not isinstance(ts, str):
                continue
            event_run_id = payload.get("run_id")
            step = payload.get("step")
            if not isinstance(event_run_id, str) or not event_run_id or type(step) is not int or step < 0:
                continue
            if run_id is not None and event_run_id != run_id:
                continue
            key = (event_run_id, step)
            existing = latest.get(key)
            if existing is None or ts > existing[0]:
                latest[key] = (ts, payload)
    by_run: dict[str, list[dict[str, Any]]] = {}
    for (event_run_id, _step), (_ts, payload) in latest.items():
        by_run.setdefault(event_run_id, []).append(payload)
    for series in by_run.values():
        series.sort(key=lambda row: row["step"])
    return by_run


def _select_series(run_root: Path, *, run_id: str | None) -> tuple[str | None, list[dict[str, Any]], dict[str, int]]:
    """Pick one run_id's series to adjudicate: the explicit run_id if given,
    else the single run_id present, else (multiple run_ids, none selected)
    -- ambiguous, refuses rather than silently picking one."""
    by_run = load_train_step_series(run_root, run_id=run_id)
    counts = {rid: len(series) for rid, series in by_run.items()}
    if run_id is not None:
        return run_id, by_run.get(run_id, []), counts
    if len(by_run) == 1:
        ((only_run_id, series),) = by_run.items()
        return only_run_id, series, counts
    return None, [], counts


# ---------------------------------------------------------------------------
# R1-E1 / R1-E2 -- step-count/NaN-Inf gate and loss-trend gate. Both need
# the same telemetry series; both structurally require T-01=100 steps
# (E2 additionally needs the first/final T-02/T-03-step windows inside it).
# ---------------------------------------------------------------------------

def check_r1_e1(run_root: Path, thresholds: dict[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
    t01 = int(thresholds["T-01"])
    selected_run_id, series, counts = _select_series(run_root, run_id=run_id)
    if not series:
        return {
            "status": "EVIDENCE_MISSING",
            "detail": (
                f"no train_step telemetry found under {run_root} "
                f"(run_ids_seen={counts!r}; a telemetry file must be a *.jsonl "
                "containing lines with top-level \"source\":\"ember-restart-3b\" "
                "and \"kind\":\"train_step\" -- see append_training_telemetry "
                "in tools/ember-restart-3b/run_vertical_slice.py)"
            ),
            "needs": f"a run producing >= {t01} consecutive train_step telemetry events via an explicit telemetry_path (governed-vertical wires none; see module docstring)",
        }
    steps_present = sorted(row["step"] for row in series)
    step_set = set(steps_present)
    max_step = steps_present[-1]
    contiguous_from_1 = step_set.issuperset(range(1, min(max_step, t01) + 1))
    non_finite_rows = [
        {"step": row["step"], "field": field_name, "value": _json_safe_number(row[field_name])}
        for row in series
        for field_name in ("loss", "grad_norm")
        if field_name in row and isinstance(row[field_name], (int, float)) and not math.isfinite(row[field_name])
    ]
    met = len(steps_present) >= t01 and contiguous_from_1 and not non_finite_rows
    return {
        "status": "MET" if met else "NOT_MET",
        "run_id": selected_run_id,
        "steps_observed": len(steps_present),
        "steps_required": t01,
        "max_step": max_step,
        "contiguous_from_step_1": contiguous_from_1,
        "non_finite_count": len(non_finite_rows),
        "non_finite_rows": non_finite_rows[:20],
    }


def check_r1_e2(run_root: Path, thresholds: dict[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
    t01, t02, t03 = int(thresholds["T-01"]), int(thresholds["T-02"]), int(thresholds["T-03"])
    selected_run_id, series, counts = _select_series(run_root, run_id=run_id)
    if len(series) < t02 + t03:
        return {
            "status": "EVIDENCE_MISSING",
            "detail": (
                f"need >= {t02 + t03} steps of loss telemetry (first {t02} + final {t03} "
                f"windows) under {run_root}; found {len(series)} (run_ids_seen={counts!r})"
            ),
            "needs": f"a run producing >= {t01} consecutive steps with loss telemetry",
        }
    first_window = series[:t02]
    final_window = series[-t03:]
    if not all(isinstance(row.get("loss"), (int, float)) and math.isfinite(row["loss"]) for row in first_window + final_window):
        return {
            "status": "NOT_MET",
            "run_id": selected_run_id,
            "detail": "non-finite loss present inside the R1-E2 comparison windows -- see R1-E1 for the full non-finite audit",
        }
    mean_first = statistics.fmean(row["loss"] for row in first_window)
    mean_final = statistics.fmean(row["loss"] for row in final_window)
    met = mean_final < mean_first
    return {
        "status": "MET" if met else "NOT_MET",
        "run_id": selected_run_id,
        "mean_loss_first_window": mean_first,
        "mean_loss_final_window": mean_final,
        "first_window_steps": [row["step"] for row in first_window],
        "final_window_steps": [row["step"] for row in final_window],
    }


# ---------------------------------------------------------------------------
# R1-E3 -- checkpoint save/restore round trip.
# ---------------------------------------------------------------------------

def find_checkpoint_manifest(run_root: Path, *, explicit: Path | None = None) -> Path:
    if explicit is not None:
        if not explicit.is_file():
            raise R1ExitBatteryRefusal(f"CHECKPOINT_MANIFEST_MISSING: {explicit}")
        return explicit
    candidates = sorted((run_root / "artifacts" / "checkpoints").glob("*/checkpoint-manifest.json")) if (run_root / "artifacts" / "checkpoints").is_dir() else []
    if not candidates:
        raise R1ExitBatteryRefusal(f"CHECKPOINT_MANIFEST_MISSING: no artifacts/checkpoints/*/checkpoint-manifest.json under {run_root}")
    if len(candidates) > 1:
        raise R1ExitBatteryRefusal(
            f"CHECKPOINT_AMBIGUOUS: {len(candidates)} checkpoint manifests under {run_root} -- pass --checkpoint-manifest explicitly: {candidates}"
        )
    return candidates[0]


def verify_checkpoint_write_integrity(manifest_path: Path) -> dict[str, Any]:
    """Pure-hashlib, no-torch verification that every shard byte-matches
    its manifest declaration, and that expert/shared/optimizer shards
    cross-match the manifest's own top-level sha256 mirrors. See module
    docstring for why this does not reuse the v3-schema _verify()."""
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise R1ExitBatteryRefusal(f"CHECKPOINT_MANIFEST_UNREADABLE: {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SUPPORTED_CHECKPOINT_SCHEMA:
        raise R1ExitBatteryRefusal(
            f"CHECKPOINT_MANIFEST_SCHEMA_UNRECOGNIZED: {manifest_path} schema_version="
            f"{manifest.get('schema_version') if isinstance(manifest, dict) else type(manifest).__name__!r} "
            f"(this battery understands {SUPPORTED_CHECKPOINT_SCHEMA!r} only)"
        )
    manifest_dir = manifest_path.parent
    shards = manifest.get("shards")
    if not isinstance(shards, list) or not shards:
        raise R1ExitBatteryRefusal(f"CHECKPOINT_MANIFEST_UNREADABLE: {manifest_path} has no nonempty 'shards' list")

    per_shard: list[dict[str, Any]] = []
    all_ok = True
    for shard in shards:
        row: dict[str, Any] = {"path": shard.get("path"), "role": shard.get("role")}
        shard_path = manifest_dir / str(shard.get("path"))
        if not shard_path.is_file():
            row.update(ok=False, reason="FILE_MISSING")
            all_ok = False
            per_shard.append(row)
            continue
        actual_bytes = shard_path.stat().st_size
        declared_bytes = shard.get("bytes")
        actual_sha256 = _sha256_file(shard_path)
        declared_sha256 = shard.get("sha256")
        size_ok = actual_bytes == declared_bytes
        hash_ok = actual_sha256 == declared_sha256
        cross_ref_ok = True
        cross_ref_field = None
        role = shard.get("role", "")
        if role in CHECKPOINT_TOP_LEVEL_SHA_FIELDS:
            cross_ref_field = CHECKPOINT_TOP_LEVEL_SHA_FIELDS[role]
            cross_ref_ok = manifest.get(cross_ref_field) == declared_sha256
        elif isinstance(role, str) and role.startswith(CHECKPOINT_EXPERT_ROLE_PREFIX):
            expert_name = role[len(CHECKPOINT_EXPERT_ROLE_PREFIX):]
            cross_ref_field = f"expert_checkpoint_sha256[{expert_name!r}]"
            expert_map = manifest.get("expert_checkpoint_sha256")
            cross_ref_ok = isinstance(expert_map, dict) and expert_map.get(expert_name) == declared_sha256
        row.update(
            declared_bytes=declared_bytes,
            actual_bytes=actual_bytes,
            size_ok=size_ok,
            declared_sha256=declared_sha256,
            actual_sha256=actual_sha256,
            hash_ok=hash_ok,
            cross_ref_field=cross_ref_field,
            cross_ref_ok=cross_ref_ok,
            ok=bool(size_ok and hash_ok and cross_ref_ok),
        )
        all_ok = all_ok and row["ok"]
        per_shard.append(row)

    return {
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha256_bytes(manifest_bytes),
        "schema_version": manifest.get("schema_version"),
        "data_cursor": manifest.get("data_cursor"),
        "shard_count": len(shards),
        "all_shards_ok": all_ok,
        "shards": per_shard,
    }


def find_resume_attempts(sibling_roots: list[Path], *, target_checkpoint_dir: Path) -> list[dict[str, Any]]:
    """Scan sibling run roots' *-certified-launch.json receipts for an argv
    containing --resume-checkpoint pointing at target_checkpoint_dir. Path
    comparison is case-insensitive-resolved (Windows) string equality on
    the argv value as authored -- exactly what the real system correlates
    on, not a content hash (the resume argv names a path, not a manifest
    hash)."""
    target = str(target_checkpoint_dir.resolve()).casefold()
    attempts: list[dict[str, Any]] = []
    for sibling in sibling_roots:
        for launch_receipt_path in sorted(sibling.glob("*-certified-launch.json")):
            try:
                launch = json.loads(launch_receipt_path.read_bytes())
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            argv = launch.get("argv")
            if not isinstance(argv, list):
                continue
            resume_idx = None
            for i, token in enumerate(argv):
                if token == "--resume-checkpoint" and i + 1 < len(argv):
                    resume_idx = i + 1
                    break
            if resume_idx is None:
                continue
            try:
                resume_path = Path(str(argv[resume_idx]))
                matches = str(resume_path.resolve()).casefold() == target
            except OSError:
                matches = str(argv[resume_idx]).casefold() == target
            if not matches:
                continue
            exit_code = launch.get("exit_code")
            child_log_field = launch.get("child_log")
            traceback_tail = None
            if child_log_field:
                child_log_path = Path(str(child_log_field))
                if child_log_path.is_file():
                    tail_bytes = child_log_path.read_bytes()[-2000:]
                    traceback_tail = tail_bytes.decode("utf-8", errors="replace")
            attempts.append({
                "launch_receipt": str(launch_receipt_path),
                "run_root": str(sibling),
                "exit_code": exit_code,
                "child_log": child_log_field,
                "traceback_tail": traceback_tail,
                "resumed_artifact_root": None,  # filled by caller if it locates the successor checkpoint
            })
    return attempts


def check_r1_e3(
    run_root: Path,
    *,
    sibling_roots: list[Path] | None = None,
    explicit_manifest: Path | None = None,
) -> dict[str, Any]:
    manifest_path = find_checkpoint_manifest(run_root, explicit=explicit_manifest)
    write_integrity = verify_checkpoint_write_integrity(manifest_path)
    checkpoint_dir = manifest_path.parent
    resume_attempts = find_resume_attempts(sibling_roots or [], target_checkpoint_dir=checkpoint_dir)

    successful_resumes = [a for a in resume_attempts if a.get("exit_code") == 0]
    restore_status = "NOT_ATTEMPTED"
    if successful_resumes:
        restore_status = "SUCCEEDED"
    elif resume_attempts:
        restore_status = "FAILED"

    overall_met = write_integrity["all_shards_ok"] and restore_status == "SUCCEEDED"
    # By the time we reach here, find_checkpoint_manifest + verify_checkpoint_write_integrity
    # have already succeeded, so real evidence always exists for at least the write leg --
    # "no evidence at all" is a R1ExitBatteryRefusal raised earlier (CHECKPOINT_MANIFEST_MISSING
    # etc.), never a status this function returns. A not-fully-met E3 is therefore always
    # NOT_MET, never EVIDENCE_MISSING (fail-closed: partial real evidence is not silence).
    return {
        "status": "MET" if overall_met else "NOT_MET",
        "detail": (
            None if overall_met else
            "write-side hash integrity verified; restore leg never attempted (no sibling-root supplied or none found)" if restore_status == "NOT_ATTEMPTED" and write_integrity["all_shards_ok"]
            else "restore leg attempted and failed before or during reload" if restore_status == "FAILED"
            else "write-side hash integrity check found a mismatch -- see components.write_integrity.shards"
        ),
        "components": {
            "write_integrity": write_integrity,
            "restore_round_trip": {
                "status": restore_status,
                "attempts": resume_attempts,
            },
        },
        "needs": (
            None if overall_met else
            "a fresh governed-vertical launch that leaves >=1 authorized record unconsumed (e.g. --max-records 2 against the 4-record owned-four-domain shard), "
            "then a second governed-vertical launch with --resume-checkpoint/--resume-counter-receipt pointing at that partial checkpoint, expected exit_code 0 "
            "and a successor checkpoint whose data_cursor.global_step advanced past the partial checkpoint's -- see needs-execution plan"
        ),
    }


# ---------------------------------------------------------------------------
# R1-E4 -- measured tokens/s, MFU, peak VRAM, host utilization.
# ---------------------------------------------------------------------------

def check_r1_e4(run_root: Path) -> dict[str, Any]:
    child_logs = sorted(run_root.glob("*-child.log"))
    context: dict[str, Any] = {}
    peak_memory_bytes = None
    for child_log_path in child_logs:
        try:
            lines = child_log_path.read_bytes().splitlines()
        except OSError:
            continue
        for raw_line in reversed(lines):
            try:
                payload = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and "peak_memory_bytes" in payload:
                peak_memory_bytes = payload.get("peak_memory_bytes")
                context["child_log"] = str(child_log_path)
                break
        if peak_memory_bytes is not None:
            break

    manifest_candidates = sorted((run_root / "artifacts" / "checkpoints").glob("*/checkpoint-manifest.json")) if (run_root / "artifacts" / "checkpoints").is_dir() else []
    preflight_vram = None
    if len(manifest_candidates) == 1:
        try:
            manifest = json.loads(manifest_candidates[0].read_bytes())
            preflight_vram = manifest.get("data_cursor", {}).get("governor")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
    if preflight_vram:
        context["pre_run_vram_preflight"] = preflight_vram
        context["pre_run_vram_preflight_caveat"] = "BEFORE-load snapshot (governor.preflight()), not peak-during-training -- not a substitute for peak allocated/reserved VRAM"
    if peak_memory_bytes is not None:
        context["peak_memory_bytes_from_child_log"] = peak_memory_bytes
        context["peak_memory_bytes_caveat"] = "torch.cuda.max_memory_allocated() at end of a 4-record structural run, not a 100-step canary -- disclosed context, not R1-E4 evidence"

    have_tokens_per_second = False  # never computed anywhere on this path (see module docstring)
    have_mfu = False
    have_peak_vram_during_training = peak_memory_bytes is not None
    have_host_utilization = False

    met = have_tokens_per_second and have_mfu and have_peak_vram_during_training and have_host_utilization
    return {
        "status": "MET" if met else "EVIDENCE_MISSING",
        "detail": (
            "none of {tokens/s, MFU, host utilization} exist in any receiptable form under this run root "
            f"(tokens/s and MFU are never computed on the governed-vertical path; peak VRAM "
            f"{'was recovered from a captured child.log' if have_peak_vram_during_training else 'requires a captured *-child.log with the final JSON result line (peak_memory_bytes) -- none found under this run root'})"
        ),
        "components": {
            "tokens_per_second": None,
            "mfu": None,
            "peak_vram_during_training_bytes": peak_memory_bytes,
            "host_utilization": None,
        },
        "context": context,
        "needs": "a run whose stdout is captured to a *-child.log (certified_train_launch.py does this automatically as of the #1408 fix) for peak VRAM, plus a telemetry-wired >=100-step run for tokens/s; MFU and host utilization have no computation path anywhere in this repo yet",
    }


# ---------------------------------------------------------------------------
# R1-E5 -- first closed-boundary frontier receipt, §5.4, energy_boundary
# DEGRADED_PROXY.
# ---------------------------------------------------------------------------

def check_r1_e5(run_root: Path, *, repo_root: Path = REPO_ROOT, fixed_prior_manifest_path: Path | None = None) -> dict[str, Any]:
    fixed_prior_manifest_path = fixed_prior_manifest_path or DEFAULT_FIXED_PRIOR_MANIFEST
    fixed_prior_present = fixed_prior_manifest_path.is_file()
    fixed_prior_sha256 = _sha256_file(fixed_prior_manifest_path) if fixed_prior_present else None

    frontier_receipt_candidates = list(run_root.rglob("*frontier*receipt*.json")) if run_root.is_dir() else []
    energy_receipt_candidates = [
        p for p in (run_root.rglob("*.json") if run_root.is_dir() else [])
        if "energy" in p.name.lower()
    ]

    met = bool(frontier_receipt_candidates)
    return {
        "status": "MET" if met else "EVIDENCE_MISSING",
        "detail": (
            None if met else
            "no frontier-receipt-shaped file under this run root, and no frontier-receipt generator "
            "exists anywhere in scripts/ (repo-wide grep, zero hits, 2026-08-05); no energy-proxy "
            "sampling occurred for this run (scripts/energy_proxy_logger.py exists but was not invoked)"
        ),
        "components": {
            "fixed_prior_manifest_present": fixed_prior_present,
            "fixed_prior_manifest_path": str(fixed_prior_manifest_path),
            "fixed_prior_manifest_sha256": fixed_prior_sha256,
            "frontier_receipt_candidates": [str(p) for p in frontier_receipt_candidates],
            "energy_receipt_candidates": [str(p) for p in energy_receipt_candidates],
        },
        "needs": "a frontier-receipt assembly script (does not exist yet) run against a real >=100-step canary with energy-proxy sampling coverage >= T-06 -- this is an engineering task, not just an execution one",
    }


# ---------------------------------------------------------------------------
# R1-E6 -- forecast-recalibration receipt.
# ---------------------------------------------------------------------------

def check_r1_e6(run_root: Path, *, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    forecast_candidates = list(run_root.rglob("*forecast*.json")) if run_root.is_dir() else []
    recalibration_candidates = list(run_root.rglob("*recalibrat*.json")) if run_root.is_dir() else []
    met = bool(forecast_candidates and recalibration_candidates)
    return {
        "status": "MET" if met else "EVIDENCE_MISSING",
        "detail": (
            None if met else
            "no forecast document and no recalibration receipt found under this run root, and a "
            "repo-wide grep for forecast_recalibration/ForecastRecalibration finds no generator "
            "anywhere in this repo (2026-08-05); recalibration additionally needs a measured "
            ">=100-step baseline (R1-E1/E2/E4), which does not exist yet either"
        ),
        "components": {
            "forecast_candidates": [str(p) for p in forecast_candidates],
            "recalibration_candidates": [str(p) for p in recalibration_candidates],
        },
        "needs": "a predicted-vs-measured forecast document (does not exist) plus a real measured >=100-step run to recalibrate against",
    }


# ---------------------------------------------------------------------------
# R1-E7 -- sigma_seed(m), >= T-07 seed replicas.
# ---------------------------------------------------------------------------

def pooled_sigma_seed(seed_series: dict[str, list[dict[str, Any]]], *, metric: str) -> dict[str, Any]:
    """THIS script's disclosed sigma_seed computation (R1-E7's schema is not
    frozen anywhere upstream -- see module docstring): at each step present
    in every seed's series (matched steps), take the population variance of
    `metric` across seeds; pool by averaging those per-step variances;
    sigma_seed = sqrt(pooled variance)."""
    seeds = sorted(seed_series)
    per_seed_steps = [{row["step"]: row.get(metric) for row in series if metric in row} for series in (seed_series[s] for s in seeds)]
    matched_steps = set.intersection(*(set(d) for d in per_seed_steps)) if per_seed_steps else set()
    matched_steps = {
        step for step in matched_steps
        if all(isinstance(d[step], (int, float)) and math.isfinite(d[step]) for d in per_seed_steps)
    }
    if not matched_steps:
        return {"sigma_seed": None, "matched_step_count": 0, "seeds": seeds}
    per_step_variances = []
    for step in sorted(matched_steps):
        values = [d[step] for d in per_seed_steps]
        per_step_variances.append(statistics.pvariance(values))
    pooled_variance = statistics.fmean(per_step_variances)
    return {
        "sigma_seed": math.sqrt(pooled_variance),
        "matched_step_count": len(matched_steps),
        "seeds": seeds,
    }


def check_r1_e7(seed_roots: list[Path], thresholds: dict[str, Any]) -> dict[str, Any]:
    t07 = int(thresholds["T-07"])
    seed_series: dict[str, list[dict[str, Any]]] = {}
    seeds_with_usable_telemetry = 0
    per_root: list[dict[str, Any]] = []
    for root in seed_roots:
        run_id, series, counts = _select_series(root, run_id=None)
        usable = len(series) > 0
        seeds_with_usable_telemetry += int(usable)
        per_root.append({"run_root": str(root), "run_id": run_id, "steps": len(series), "run_ids_seen": counts})
        if usable:
            seed_series[str(root)] = series
    if seeds_with_usable_telemetry < t07:
        return {
            "status": "EVIDENCE_MISSING",
            "detail": (
                f"T-07={t07} seed replicas with usable R1-scale telemetry required; "
                f"{len(seed_roots)} seed root(s) supplied, {seeds_with_usable_telemetry} with any usable telemetry"
            ),
            "components": {"per_seed_root": per_root},
            "needs": f">= {t07} independent-seed R1-scale runs, each producing train_step telemetry (none of this repo's CLI paths currently wire telemetry through a >=T-01-step run -- see module docstring)",
        }
    sigma_loss = pooled_sigma_seed(seed_series, metric="loss")
    sigma_grad_norm = pooled_sigma_seed(seed_series, metric="grad_norm")
    met = sigma_loss["sigma_seed"] is not None and sigma_grad_norm["sigma_seed"] is not None
    return {
        "status": "MET" if met else "NOT_MET",
        "sigma_seed": {"loss": sigma_loss, "grad_norm": sigma_grad_norm},
        "components": {"per_seed_root": per_root},
        "method_disclosure": "pooled_sigma_seed: population variance across seeds per matched step, pooled by averaging per-step variances (see module docstring) -- not frozen upstream",
    }


# ---------------------------------------------------------------------------
# R1-E8 -- A1 discriminating check (liveness T-08, parity T-09/F-11).
# ---------------------------------------------------------------------------

## Word-boundary regex, not raw substring: a bare "a1" substring check
# false-positives on hex sha256 digests, which contain the two characters
# "a1" somewhere in a 64-hex-char string with high probability by pure
# chance -- every real checkpoint has several such hashes. _HEX_DIGEST_RE
# strips any hex-digest-shaped string value out of the scanned haystack
# before matching, belt-and-suspenders against that class of false
# positive. Separately, \b alone is not enough: this codebase's own
# identifiers are snake_case/kebab-case ("tier_1", "governed-vertical"),
# and `_` is a \w character in regex -- "tier_1" has NO \b between "tier"
# and "_1", so a naive \btier ?1\b would miss it. _normalize_separators
# turns '_'/'-' into spaces before matching so both "tier_1"/"tier-1" and
# "tier1" hit the same word-bounded pattern.
_A1_MARKER_RE = re.compile(r"\b(a1|dense|tier ?1|q ?galore|offload)\b", re.IGNORECASE)
_HEX_DIGEST_RE = re.compile(r"^[0-9a-f]{16,}$", re.IGNORECASE)
_SEPARATOR_RE = re.compile(r"[_\-]+")


def _normalize_separators(text: str) -> str:
    return _SEPARATOR_RE.sub(" ", text)


def _marker_scan_strings(obj: Any) -> list[str]:
    """Collect every dict key and non-hex-digest-shaped string value,
    recursively -- the haystack for A1-marker matching. Numeric/hash/bytes
    fields never contribute (they cannot spell a marker word on purpose,
    only by hex-digest coincidence, which is exactly what this excludes)."""
    out: list[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            out.append(str(key))
            out.extend(_marker_scan_strings(value))
    elif isinstance(obj, list):
        for item in obj:
            out.extend(_marker_scan_strings(item))
    elif isinstance(obj, str):
        if not _HEX_DIGEST_RE.match(obj):
            out.append(obj)
    return out


def check_r1_e8(search_roots: list[Path]) -> dict[str, Any]:
    candidates: list[str] = []
    for root in search_roots:
        if not root.is_dir():
            continue
        for manifest_path in root.rglob("checkpoint-manifest.json"):
            try:
                manifest = json.loads(manifest_path.read_bytes())
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            haystack = _normalize_separators(" ".join(_marker_scan_strings(manifest)))
            if _A1_MARKER_RE.search(haystack):
                candidates.append(str(manifest_path))
    met = bool(candidates)
    return {
        "status": "MET" if met else "EVIDENCE_MISSING",
        "detail": (
            None if met else
            "no A1 (dense) arm run found under any given search root -- every checkpoint inspected is "
            "architecture_revision ember-sparse-3b-v2 (A3's role-prior sparse architecture); repo-wide "
            "grep for tier1/offload/Q-GaLore mechanisms in tools/ember-restart-3b finds zero hits "
            "beyond the preregistration text itself (2026-08-05)"
        ),
        "components": {"candidate_manifests": candidates},
        "needs": "an A1 tier-1 (CPU-offloaded full-state AdamW) run + liveness leg (T-08 tokens ratio vs A3) + parity leg (T-09 matched steps vs offloaded-AdamW reference, F-11 band) -- no A1 execution path exists anywhere in this repo yet; this is an engineering task before it is an execution one",
    }


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------

def build_receipt(
    *,
    ticket: str,
    exit_criterion: str,
    subject: dict[str, Any],
    thresholds_sha256: str | None,
    result: dict[str, Any],
) -> dict[str, Any]:
    import receipt_check  # sole authority for INVARIANT_SHA256 -- never hardcoded here
    receipt: dict[str, Any] = {
        "ticket": ticket,
        "ts": _now_ts(),
        "schema": RECEIPT_SCHEMA,
        # authority block: required by verify_authority_conservation.validate_artifact_binding
        # for every committed receipts/*.json (goal_id + workstream_id + next_executed_outcome)
        "authority": {
            "goal_id": "EMBER-02",
            "workstream_id": "EMBER-02A",
            "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
        },
        "issue_refs": [ISSUE_REF],
        "sha_convention": SHA_CONVENTION,
        "invariant_sha256": receipt_check.INVARIANT_SHA256,
        "prereg": {"document": PREREG_DOC, "pin": PREREG_PIN, "thresholds_sha256": thresholds_sha256},
        "exit_criterion": exit_criterion,
        "subject": subject,
        "status": result.get("status"),
        "result": result,
        "api_spend_usd": 0.0,
        "paid_api_surface_used": False,
    }
    return receipt


# Custody-path redaction: the repo bans absolute local filesystem paths in tracked
# bytes (repo-guard [paths] leg), but this battery adjudicates OFF-TREE run roots.
# The custody parents are registered at runtime from the user-supplied absolute
# arguments -- never hardcoded here -- and every string in a receipt has them
# rewritten to the symbolic "<custody>" before publication. Run identity survives
# (the run-root basename is kept); only the machine-local prefix is stripped.
_REDACT_PARENTS: list[str] = []


def register_redact_parent(p: Path | None) -> None:
    if p is None:
        return
    candidate = Path(p)
    if not candidate.is_absolute():
        return
    s = str(candidate.parent)
    if s and s not in _REDACT_PARENTS:
        _REDACT_PARENTS.append(s)


_ABS_PATH_RE = re.compile(r"[A-Za-z]:[\\/][^\s\"'|<>]*")


def _rewrite_abs_path(match: re.Match[str]) -> str:
    # Leftover absolute paths (quoted tracebacks, resolved in-tree files) that the
    # registered custody parents did not cover: in-tree paths become repo-relative,
    # everything else keeps only its last two components under a symbolic prefix.
    raw = match.group(0).rstrip("\\/.,;:")
    try:
        rel = os.path.relpath(raw, os.getcwd())
    except ValueError:
        rel = None
    if rel is not None and not rel.startswith(".."):
        return rel.replace("\\", "/")
    parts = [p for p in re.split(r"[\\/]+", raw) if p]
    tail = "/".join(parts[-2:]) if len(parts) >= 2 else (parts[-1] if parts else "")
    return "<abs>/" + tail


def _redact_custody(obj: Any) -> Any:
    if isinstance(obj, str):
        out = obj
        for parent in _REDACT_PARENTS:
            for variant in (parent, parent.replace("\\", "/"), parent.replace("/", "\\")):
                out = out.replace(variant, "<custody>")
        return _ABS_PATH_RE.sub(_rewrite_abs_path, out)
    if isinstance(obj, dict):
        return {k: _redact_custody(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_custody(v) for v in obj]
    return obj


def write_receipt(path: str | Path, receipt: dict[str, Any]) -> None:
    from receipt_write import checked_write  # atomic, quarantine-on-invalid publication
    receipt = _redact_custody(receipt)
    os.makedirs(os.path.dirname(os.path.abspath(str(path))) or ".", exist_ok=True)
    checked_write(str(path), receipt)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

EXIT_IDS = ("e1", "e2", "e3", "e4", "e5", "e6", "e7", "e8")


def _run_one_exit(
    exit_id: str,
    *,
    run_root: Path,
    sibling_roots: list[Path],
    seed_roots: list[Path],
    explicit_manifest: Path | None,
    thresholds: dict[str, Any],
    thresholds_sha256: str,
) -> dict[str, Any]:
    if exit_id == "e1":
        result = check_r1_e1(run_root, thresholds)
    elif exit_id == "e2":
        result = check_r1_e2(run_root, thresholds)
    elif exit_id == "e3":
        result = check_r1_e3(run_root, sibling_roots=sibling_roots, explicit_manifest=explicit_manifest)
    elif exit_id == "e4":
        result = check_r1_e4(run_root)
    elif exit_id == "e5":
        result = check_r1_e5(run_root)
    elif exit_id == "e6":
        result = check_r1_e6(run_root)
    elif exit_id == "e7":
        result = check_r1_e7(seed_roots or [run_root], thresholds)
    elif exit_id == "e8":
        result = check_r1_e8(sibling_roots + [run_root])
    else:
        raise R1ExitBatteryRefusal(f"UNKNOWN_EXIT_ID: {exit_id!r}")
    return build_receipt(
        ticket=f"r1-exit-battery-{exit_id}",
        exit_criterion=f"R1-{exit_id.upper()}",
        subject={"run_root": str(run_root), "sibling_roots": [str(p) for p in sibling_roots], "seed_roots": [str(p) for p in seed_roots]},
        thresholds_sha256=thresholds_sha256,
        result=result,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--run-root", type=Path, help="run directory to adjudicate, e.g. <live-receipts-custody>/r1-warm100-20260804")
    ap.add_argument("--sibling-root", type=Path, action="append", default=[], help="another run directory to search for resume/A1 evidence (repeatable)")
    ap.add_argument("--seed-root", type=Path, action="append", default=[], help="a run directory representing one seed replica, for R1-E7 (repeatable; defaults to --run-root alone)")
    ap.add_argument("--checkpoint-manifest", type=Path, default=None, help="explicit checkpoint-manifest.json path for R1-E3 (default: auto-glob under --run-root)")
    ap.add_argument("--thresholds", type=Path, default=None, help="override thresholds JSON path")
    ap.add_argument("--exit", dest="exit_id", choices=(*EXIT_IDS, "all"), default="all")
    ap.add_argument("--out-dir", type=Path, default=Path("receipts") / "ember-02-r1-exits")
    args = ap.parse_args(argv)

    if args.selftest:
        run_selftest()
        print("R1_EXIT_BATTERY_SELFTEST_PASS")
        return 0

    if args.run_root is None:
        print("error: --run-root is required (or --selftest)", file=sys.stderr)
        return 2

    for supplied in (args.run_root, *args.sibling_root, *args.seed_root, args.checkpoint_manifest):
        register_redact_parent(supplied)

    thresholds, thresholds_sha256 = load_thresholds(args.thresholds)
    exit_ids = list(EXIT_IDS) if args.exit_id == "all" else [args.exit_id]
    overall_ok = True
    for exit_id in exit_ids:
        try:
            receipt = _run_one_exit(
                exit_id,
                run_root=args.run_root,
                sibling_roots=list(args.sibling_root),
                seed_roots=list(args.seed_root),
                explicit_manifest=args.checkpoint_manifest,
                thresholds=thresholds,
                thresholds_sha256=thresholds_sha256,
            )
        except R1ExitBatteryRefusal as exc:
            receipt = build_receipt(
                ticket=f"r1-exit-battery-{exit_id}",
                exit_criterion=f"R1-{exit_id.upper()}",
                subject={"run_root": str(args.run_root)},
                thresholds_sha256=thresholds_sha256,
                result={"status": "REFUSED", "refusal_reason": str(exc)},
            )
        out_path = args.out_dir / f"r1-{exit_id}-{_now_ts()}.json"
        write_receipt(out_path, receipt)
        status = receipt["status"]
        print(f"R1-{exit_id.upper()}: {status} -> {out_path}")
        if status not in ("MET",):
            overall_ok = False
    return 0 if overall_ok else 1


# ---------------------------------------------------------------------------
# Selftest -- pure CPU synthetic fixtures. No GPU, no real checkpoint bytes,
# no real telemetry. Fixtures are clearly namespaced SELFTEST_FIXTURE_* and
# must never be mistaken for real R1 evidence.
# ---------------------------------------------------------------------------

def _write_jsonl(path: Path, events: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event) + "\n")


def _synthetic_train_step_events(*, run_id: str, n_steps: int, start_ts: int = 1785900000, inject_nan_at: int | None = None) -> list[dict[str, Any]]:
    events = []
    for step in range(1, n_steps + 1):
        loss = 2.0 - 0.01 * step  # monotonic decreasing synthetic loss
        if inject_nan_at is not None and step == inject_nan_at:
            loss = float("nan")
        events.append({
            "ts": datetime.fromtimestamp(start_ts + step, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
            "kind": "train_step",
            "source": "ember-restart-3b",
            "payload": {"run_id": run_id, "step": step, "loss": loss, "grad_norm": 1.0 + 0.001 * step},
        })
    return events


def _synthetic_checkpoint(tmp_dir: Path, *, seed: int = 830001, corrupt_shard: bool = False, corrupt_cross_ref: bool = False) -> Path:
    ckpt_dir = tmp_dir / "artifacts" / "checkpoints" / f"checkpoint-vertical-slice-seed-{seed}"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    shard_specs = [
        ("shared-model.pt", "shared_model", b"SELFTEST_FIXTURE_shared_model_bytes"),
        ("optimizer-state.pt", "optimizer_state", b"SELFTEST_FIXTURE_optimizer_state_bytes"),
        ("replay-state.pt", "replay_state", b"SELFTEST_FIXTURE_replay_state_bytes"),
        ("expert-vision.pt", "expert_vision", b"SELFTEST_FIXTURE_expert_vision_bytes"),
        ("expert-audio.pt", "expert_audio", b"SELFTEST_FIXTURE_expert_audio_bytes"),
        ("expert-reasoning.pt", "expert_reasoning", b"SELFTEST_FIXTURE_expert_reasoning_bytes"),
        ("expert-tool.pt", "expert_tool", b"SELFTEST_FIXTURE_expert_tool_bytes"),
    ]
    shards = []
    top_level_sha: dict[str, Any] = {"expert_checkpoint_sha256": {}}
    for filename, role, content in shard_specs:
        if corrupt_shard and role == "expert_tool":
            (ckpt_dir / filename).write_bytes(content + b"CORRUPTED")
        else:
            (ckpt_dir / filename).write_bytes(content)
        declared_sha = _sha256_bytes(content)  # declared hash always matches the ORIGINAL content -- corruption is a write-time-vs-manifest mismatch, exactly what E3 must catch
        shards.append({"path": filename, "role": role, "bytes": len(content), "sha256": declared_sha, "publication_mode": "written", "incremental_bytes": len(content)})
        if role == "shared_model":
            top_level_sha["shared_model_shard_sha256"] = declared_sha
        elif role == "optimizer_state":
            top_level_sha["optimizer_state_shard_sha256"] = declared_sha
        elif role.startswith("expert_"):
            top_level_sha["expert_checkpoint_sha256"][role[len("expert_"):]] = declared_sha
    if corrupt_cross_ref:
        top_level_sha["expert_checkpoint_sha256"]["tool"] = "0" * 64
    manifest = {
        "schema_version": SUPPORTED_CHECKPOINT_SCHEMA,
        "shards": shards,
        "data_cursor": {"global_step": 4, "record_index": 4, "tokens_seen": 36, "shard": "SELFTEST_FIXTURE_shard"},
        **top_level_sha,
    }
    (ckpt_dir / "checkpoint-manifest.json").write_bytes(json.dumps(manifest, indent=2).encode("utf-8"))
    return ckpt_dir


def run_selftest() -> None:
    thresholds, thresholds_sha256 = load_thresholds()
    assert thresholds["T-01"] == 100 and thresholds["T-07"] == 2, thresholds

    with tempfile.TemporaryDirectory(prefix="r1_exit_battery_selftest_") as tmp:
        tmp_path = Path(tmp)

        # --- E1/E2: missing telemetry -> EVIDENCE_MISSING ---
        empty_root = tmp_path / "empty_run"
        empty_root.mkdir()
        r = check_r1_e1(empty_root, thresholds)
        assert r["status"] == "EVIDENCE_MISSING", r

        # --- E1: 100 clean steps -> MET ---
        clean_root = tmp_path / "clean_run"
        _write_jsonl(clean_root / "telemetry.jsonl", _synthetic_train_step_events(run_id="SELFTEST_FIXTURE_run", n_steps=100))
        r1 = check_r1_e1(clean_root, thresholds)
        assert r1["status"] == "MET", r1
        assert r1["steps_observed"] == 100 and r1["non_finite_count"] == 0, r1

        # --- E1: NaN at step 50 -> NOT_MET, non_finite_count >= 1 ---
        nan_root = tmp_path / "nan_run"
        _write_jsonl(nan_root / "telemetry.jsonl", _synthetic_train_step_events(run_id="SELFTEST_FIXTURE_run", n_steps=100, inject_nan_at=50))
        r2 = check_r1_e1(nan_root, thresholds)
        assert r2["status"] == "NOT_MET", r2
        assert r2["non_finite_count"] >= 1, r2
        assert r2["non_finite_rows"][0]["value"]["non_finite"] is True, r2  # JSON-safe NaN encoding round-trips

        # --- E1: only 4 steps (the real governed-vertical shape) -> NOT_MET ---
        short_root = tmp_path / "short_run"
        _write_jsonl(short_root / "telemetry.jsonl", _synthetic_train_step_events(run_id="SELFTEST_FIXTURE_run", n_steps=4))
        r3 = check_r1_e1(short_root, thresholds)
        assert r3["status"] == "NOT_MET" and r3["steps_observed"] == 4, r3

        # --- E2: decreasing loss over clean_root -> MET ---
        e2 = check_r1_e2(clean_root, thresholds)
        assert e2["status"] == "MET", e2
        assert e2["mean_loss_final_window"] < e2["mean_loss_first_window"], e2

        # --- E2: flat/increasing loss -> NOT_MET ---
        flat_root = tmp_path / "flat_run"
        flat_events = []
        for step in range(1, 101):
            flat_events.append({
                "ts": datetime.fromtimestamp(1785900000 + step, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
                "kind": "train_step", "source": "ember-restart-3b",
                "payload": {"run_id": "SELFTEST_FIXTURE_run", "step": step, "loss": 1.0, "grad_norm": 1.0},
            })
        _write_jsonl(flat_root / "telemetry.jsonl", flat_events)
        e2_flat = check_r1_e2(flat_root, thresholds)
        assert e2_flat["status"] == "NOT_MET", e2_flat

        # --- E3: intact checkpoint, no resume evidence -> NOT_MET (write ok, restore NOT_ATTEMPTED) ---
        ok_ckpt_root = tmp_path / "e3_ok_run"
        _synthetic_checkpoint(ok_ckpt_root)
        e3_no_resume = check_r1_e3(ok_ckpt_root, sibling_roots=[])
        assert e3_no_resume["status"] == "NOT_MET", e3_no_resume
        assert e3_no_resume["components"]["write_integrity"]["all_shards_ok"] is True, e3_no_resume
        assert e3_no_resume["components"]["restore_round_trip"]["status"] == "NOT_ATTEMPTED", e3_no_resume

        # --- E3: corrupted shard bytes -> write_integrity fails ---
        bad_ckpt_root = tmp_path / "e3_bad_run"
        _synthetic_checkpoint(bad_ckpt_root, corrupt_shard=True)
        e3_bad = check_r1_e3(bad_ckpt_root, sibling_roots=[])
        assert e3_bad["components"]["write_integrity"]["all_shards_ok"] is False, e3_bad
        bad_shard_rows = [s for s in e3_bad["components"]["write_integrity"]["shards"] if not s["ok"]]
        assert bad_shard_rows and bad_shard_rows[0]["role"] == "expert_tool", e3_bad

        # --- E3: corrupted cross-reference (manifest top-level hash disagrees with shard's own declared hash) ---
        xref_root = tmp_path / "e3_xref_run"
        _synthetic_checkpoint(xref_root, corrupt_cross_ref=True)
        e3_xref = check_r1_e3(xref_root, sibling_roots=[])
        assert e3_xref["components"]["write_integrity"]["all_shards_ok"] is False, e3_xref

        # --- E3: a sibling root with a FAILED resume attempt referencing the checkpoint ---
        resume_sibling = tmp_path / "e3_resume_sibling"
        resume_sibling.mkdir()
        ckpt_dir = ok_ckpt_root / "artifacts" / "checkpoints" / "checkpoint-vertical-slice-seed-830001"
        child_log_path = resume_sibling / "disk-budget-runner-receipt-child.log"
        child_log_path.write_text("Traceback (most recent call last):\nRuntimeError: SELFTEST_FIXTURE no remaining authorized records\n", encoding="utf-8")
        launch_receipt = {
            "argv": ["python", "run_vertical_slice.py", "governed-vertical", "--resume-checkpoint", str(ckpt_dir)],
            "exit_code": 1,
            "child_log": str(child_log_path),
        }
        (resume_sibling / "disk-budget-runner-receipt-certified-launch.json").write_bytes(json.dumps(launch_receipt).encode("utf-8"))
        e3_failed_resume = check_r1_e3(ok_ckpt_root, sibling_roots=[resume_sibling])
        assert e3_failed_resume["components"]["restore_round_trip"]["status"] == "FAILED", e3_failed_resume
        assert e3_failed_resume["status"] == "NOT_MET", e3_failed_resume
        assert "no remaining authorized records" in e3_failed_resume["components"]["restore_round_trip"]["attempts"][0]["traceback_tail"], e3_failed_resume

        # --- E3: a sibling root with a SUCCESSFUL resume attempt -> overall MET ---
        resume_sibling_ok = tmp_path / "e3_resume_sibling_ok"
        resume_sibling_ok.mkdir()
        launch_receipt_ok = {
            "argv": ["python", "run_vertical_slice.py", "governed-vertical", "--resume-checkpoint", str(ckpt_dir)],
            "exit_code": 0,
            "child_log": None,
        }
        (resume_sibling_ok / "disk-budget-runner-receipt-certified-launch.json").write_bytes(json.dumps(launch_receipt_ok).encode("utf-8"))
        e3_ok_resume = check_r1_e3(ok_ckpt_root, sibling_roots=[resume_sibling_ok])
        assert e3_ok_resume["components"]["restore_round_trip"]["status"] == "SUCCEEDED", e3_ok_resume
        assert e3_ok_resume["status"] == "MET", e3_ok_resume

        # --- E3: manifest with unrecognized schema (v3) -> refuses cleanly ---
        v3_root = tmp_path / "e3_v3_run"
        v3_ckpt_dir = v3_root / "artifacts" / "checkpoints" / "checkpoint-x"
        v3_ckpt_dir.mkdir(parents=True)
        (v3_ckpt_dir / "checkpoint-manifest.json").write_bytes(json.dumps({"schema_version": "ember-sparse-checkpoint-v3"}).encode("utf-8"))
        try:
            check_r1_e3(v3_root, sibling_roots=[])
            raise AssertionError("expected R1ExitBatteryRefusal for unrecognized schema")
        except R1ExitBatteryRefusal as exc:
            assert "CHECKPOINT_MANIFEST_SCHEMA_UNRECOGNIZED" in str(exc), exc

        # --- E4: no child.log, no manifest -> EVIDENCE_MISSING, all components None ---
        e4_empty = check_r1_e4(empty_root)
        assert e4_empty["status"] == "EVIDENCE_MISSING", e4_empty
        assert e4_empty["components"]["peak_vram_during_training_bytes"] is None, e4_empty

        # --- E4: checkpoint present (pre-run VRAM context) + child.log with peak_memory_bytes ---
        e4_root = tmp_path / "e4_run"
        _synthetic_checkpoint(e4_root)
        e4_manifest_path = e4_root / "artifacts" / "checkpoints" / "checkpoint-vertical-slice-seed-830001" / "checkpoint-manifest.json"
        e4_manifest = json.loads(e4_manifest_path.read_bytes())
        e4_manifest["data_cursor"]["governor"] = {"free_gb": 24.1, "total_gb": 25.76, "margin_gb": 4.0, "vram_fraction": 0.85}
        e4_manifest_path.write_bytes(json.dumps(e4_manifest).encode("utf-8"))
        (e4_root / "disk-budget-runner-receipt-child.log").write_bytes((json.dumps({"peak_memory_bytes": 12345678, "other": "noise"}) + "\n").encode("utf-8"))
        e4_result = check_r1_e4(e4_root)
        assert e4_result["status"] == "EVIDENCE_MISSING", e4_result  # tokens/s + MFU + host util still absent
        assert e4_result["components"]["peak_vram_during_training_bytes"] == 12345678, e4_result
        assert e4_result["context"]["pre_run_vram_preflight"]["total_gb"] == 25.76, e4_result

        # --- E5/E6: EVIDENCE_MISSING against an empty root; fixed-prior manifest presence is reported ---
        e5 = check_r1_e5(empty_root)
        assert e5["status"] == "EVIDENCE_MISSING", e5
        assert e5["components"]["fixed_prior_manifest_present"] is True, e5  # real repo file, checked via REPO_ROOT default

        e6 = check_r1_e6(empty_root)
        assert e6["status"] == "EVIDENCE_MISSING", e6

        # --- E7: single seed root -> EVIDENCE_MISSING naming T-07 ---
        e7_single = check_r1_e7([clean_root], thresholds)
        assert e7_single["status"] == "EVIDENCE_MISSING", e7_single
        assert "T-07=2" in e7_single["detail"], e7_single

        # --- E7: two matched seed roots -> MET, sigma_seed computed and arithmetic-checked ---
        seed_a = tmp_path / "seed_a"
        seed_b = tmp_path / "seed_b"
        # Deterministic synthetic series: loss[step] = base + delta_by_seed, so pooled
        # per-step variance is analytically known (population variance of two points
        # {base-d, base+d} = d^2), letting the test check exact arithmetic, not just "a number came out".
        delta = 0.05
        events_a, events_b = [], []
        for step in range(1, 101):
            ts = datetime.fromtimestamp(1785900000 + step, tz=timezone.utc).isoformat().replace("+00:00", "Z")
            events_a.append({"ts": ts, "kind": "train_step", "source": "ember-restart-3b", "payload": {"run_id": "SELFTEST_FIXTURE_seed_a", "step": step, "loss": 1.0 - delta, "grad_norm": 1.0}})
            events_b.append({"ts": ts, "kind": "train_step", "source": "ember-restart-3b", "payload": {"run_id": "SELFTEST_FIXTURE_seed_b", "step": step, "loss": 1.0 + delta, "grad_norm": 1.0}})
        _write_jsonl(seed_a / "telemetry.jsonl", events_a)
        _write_jsonl(seed_b / "telemetry.jsonl", events_b)
        e7 = check_r1_e7([seed_a, seed_b], thresholds)
        assert e7["status"] == "MET", e7
        expected_sigma_loss = delta  # sqrt(pooled variance) == sqrt(delta^2) == delta, exactly, for every matched step
        assert abs(e7["sigma_seed"]["loss"]["sigma_seed"] - expected_sigma_loss) < 1e-9, e7
        assert e7["sigma_seed"]["loss"]["matched_step_count"] == 100, e7
        assert e7["sigma_seed"]["grad_norm"]["sigma_seed"] == 0.0, e7  # identical grad_norm across seeds -> zero variance

        # --- E8: no A1 evidence anywhere -> EVIDENCE_MISSING ---
        e8_missing = check_r1_e8([ok_ckpt_root, empty_root])
        assert e8_missing["status"] == "EVIDENCE_MISSING", e8_missing

        # --- E8: a manifest mentioning an A1 marker -> MET ---
        a1_root = tmp_path / "a1_run"
        a1_ckpt_dir = a1_root / "artifacts" / "checkpoints" / "checkpoint-a1"
        a1_ckpt_dir.mkdir(parents=True)
        (a1_ckpt_dir / "checkpoint-manifest.json").write_bytes(json.dumps({"schema_version": "SELFTEST_FIXTURE", "arm": "A1_dense_tier1_offload"}).encode("utf-8"))
        e8_found = check_r1_e8([a1_root])
        assert e8_found["status"] == "MET", e8_found

        # --- Receipt envelope + write path: build + write one receipt per exit id, verify schema-floor-clean ---
        import receipt_check
        out_dir = tmp_path / "receipts_out"
        for exit_id, result in (
            ("e1", r1), ("e3", e3_ok_resume), ("e7", e7),
        ):
            receipt = build_receipt(
                ticket=f"selftest-{exit_id}", exit_criterion=f"R1-{exit_id.upper()}",
                subject={"run_root": "SELFTEST_FIXTURE"}, thresholds_sha256=thresholds_sha256, result=result,
            )
            findings = receipt_check.validate_receipt(receipt)
            assert not findings, (exit_id, findings, receipt)
            out_path = out_dir / f"{exit_id}.json"
            write_receipt(out_path, receipt)
            assert out_path.is_file(), out_path
            round_tripped = json.loads(out_path.read_text(encoding="utf-8"))
            assert round_tripped["status"] == result["status"], (exit_id, round_tripped)

        # --- Refusal receipt path (unreadable thresholds) round-trips through validate_receipt too ---
        try:
            load_thresholds(tmp_path / "does-not-exist.json")
            raise AssertionError("expected R1ExitBatteryRefusal")
        except R1ExitBatteryRefusal as exc:
            assert "THRESHOLDS_UNREADABLE" in str(exc), exc


if __name__ == "__main__":
    sys.exit(main())
