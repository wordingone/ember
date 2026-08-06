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

And for MODES it is categorical, not incidental: certified_train_launch.py's
_require_scope_subset hard-fails unless the certificate's
authorized["allowed_modes"] == ["governed-vertical"] exactly -- so extending
allowed_modes is NOT a cure (any other list refuses every launch). The
specialist route is instead authorized through the certificate's separate
allowed_training_capabilities key (#1430/#1454, live at this head, with
--telemetry-path wiring) -- but specialist is single-capability continuation
training off an existing checkpoint, not a WARM-100 canary. A real R1-E1
still needs an engineering task (wire telemetry through a 100+-step-capable
canary mode), not a different flag on today's command.

Net effect on this battery: 7 of R1's 8 exits (E1, E2, E4, E5, E6, E7, E8)
are pure EVIDENCE-MISSING against every run this repo has ever produced --
this script proves that with receipts rather than asserting it in prose.
The zero-further-code-changes claim is scoped to E1/E2/E3/E7: the day their
evidence exists (telemetry files, second seed, resume run) they adjudicate
in one command. E4/E5/E6/E8 instead refuse-until-validatable: their MET is
deliberately unreachable until the named validators/computations exist
(tokens-per-s + MFU + host-utilization computation; a section-5.4
frontier-receipt validator; a forecast-recalibration content validator;
the A1 liveness/parity leg computations) -- a filename or marker-word
match never mints MET. Only E3 yields a real, scoped,
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
  THRESHOLDS_UNREADABLE, THRESHOLDS_SCHEMA_INVALID, THRESHOLDS_PIN_MISMATCH,
  THRESHOLDS_MISSING_IDS, CHECKPOINT_MANIFEST_MISSING,
  CHECKPOINT_MANIFEST_UNREADABLE, CHECKPOINT_MANIFEST_SCHEMA_UNRECOGNIZED,
  CHECKPOINT_AMBIGUOUS, UNKNOWN_EXIT_ID.

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
from pathlib import Path, PurePath
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

# F-11 is required alongside T-01..T-09: R1-E8's parity leg quotes its frozen
# band formula from the thresholds document, never from a transcription here.
REQUIRED_THRESHOLD_IDS = {"T-01", "T-02", "T-03", "T-04", "T-05", "T-06", "T-07", "T-08", "T-09", "F-11"}

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
    # "zero NaN/Inf in loss and grad-norm fields" presupposes the fields EXIST:
    # a canary step whose event carries no numeric loss/grad_norm cannot
    # demonstrate the absence of NaN/Inf in it, so absence is NOT_MET, not a
    # silent pass. Audited over the canary steps (1..T-01).
    missing_field_rows = [
        {"step": row["step"], "field": field_name, "present": field_name in row}
        for row in series
        if row["step"] <= t01
        for field_name in ("loss", "grad_norm")
        if not (isinstance(row.get(field_name), (int, float)) and not isinstance(row.get(field_name), bool))
    ]
    met = len(steps_present) >= t01 and contiguous_from_1 and not non_finite_rows and not missing_field_rows
    return {
        "status": "MET" if met else "NOT_MET",
        "run_id": selected_run_id,
        "steps_observed": len(steps_present),
        "steps_required": t01,
        "max_step": max_step,
        "contiguous_from_step_1": contiguous_from_1,
        "non_finite_count": len(non_finite_rows),
        "non_finite_rows": non_finite_rows[:20],
        "missing_field_count": len(missing_field_rows),
        "missing_field_rows": missing_field_rows[:20],
    }


def check_r1_e2(run_root: Path, thresholds: dict[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
    t01, t02, t03 = int(thresholds["T-01"]), int(thresholds["T-02"]), int(thresholds["T-03"])
    selected_run_id, series, counts = _select_series(run_root, run_id=run_id)
    # The spec's windows are the first T-02 / final T-03 steps OF THE T-01-STEP
    # CANARY (steps 1..T-01), not of whatever fragment happens to be present:
    # an unanchored fragment (e.g. steps 41..140) must refuse, never adjudicate
    # with windows the spec never defined. Precondition: the same series that
    # would satisfy R1-E1's completeness bar (every step 1..T-01 present).
    by_step = {row["step"]: row for row in series}
    missing_steps = [step for step in range(1, t01 + 1) if step not in by_step]
    if missing_steps:
        return {
            "status": "EVIDENCE_MISSING",
            "detail": (
                f"R1-E2's comparison windows are anchored to the T-01={t01}-step canary "
                f"(first T-02={t02} and final T-03={t03} steps of steps 1..{t01}); the series "
                f"under {run_root} is missing {len(missing_steps)} of those steps "
                f"(absent step range {missing_steps[0]}..{missing_steps[-1]}; "
                f"steps_present={len(series)}, run_ids_seen={counts!r}) -- an unanchored "
                "fragment must not adjudicate E2"
            ),
            "missing_step_count": len(missing_steps),
            "missing_step_span": [missing_steps[0], missing_steps[-1]],
            "needs": f"the E1-complete series: consecutive steps 1..{t01} with loss telemetry",
        }
    first_window = [by_step[step] for step in range(1, t02 + 1)]
    final_window = [by_step[step] for step in range(t01 - t03 + 1, t01 + 1)]
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
                "resumed_artifact_root": None,  # filled by check_r1_e3 when cursor advancement is verified
            })
    return attempts


def _find_cursor_advance(
    resuming_root: Path,
    *,
    source_manifest_path: Path,
    source_global_step: int | None,
) -> dict[str, Any]:
    """The restore leg's spec bar is "reloaded, cursor advances correctly" --
    a resume exit_code of 0 alone proves neither. Scan the RESUMING run's
    root for successor checkpoint manifests (same v5 schema this battery
    understands; anything else cannot be verified and therefore does not
    count) and report the one whose data_cursor.global_step advanced
    furthest past the source checkpoint's."""
    out: dict[str, Any] = {
        "verified": False,
        "source_global_step": source_global_step,
        "successor_manifest": None,
        "successor_global_step": None,
        "successor_manifests_inspected": 0,
        "reason": None,
    }
    if source_global_step is None:
        out["reason"] = "SOURCE_CURSOR_UNREADABLE: source manifest carries no integer data_cursor.global_step to advance past"
        return out
    ckpt_root = resuming_root / "artifacts" / "checkpoints"
    candidates = sorted(ckpt_root.glob("*/checkpoint-manifest.json")) if ckpt_root.is_dir() else []
    try:
        source_resolved = source_manifest_path.resolve()
    except OSError:
        source_resolved = source_manifest_path
    best: tuple[Path, int] | None = None
    for candidate in candidates:
        try:
            if candidate.resolve() == source_resolved:
                continue  # the source checkpoint itself is never its own successor
        except OSError:
            pass
        out["successor_manifests_inspected"] += 1
        try:
            manifest = json.loads(candidate.read_bytes())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(manifest, dict) or manifest.get("schema_version") != SUPPORTED_CHECKPOINT_SCHEMA:
            continue
        cursor = manifest.get("data_cursor")
        step = cursor.get("global_step") if isinstance(cursor, dict) else None
        if type(step) is int and step > source_global_step and (best is None or step > best[1]):
            best = (candidate, step)
    if best is not None:
        out.update(verified=True, successor_manifest=str(best[0]), successor_global_step=best[1])
    else:
        out["reason"] = (
            f"NO_ADVANCED_SUCCESSOR: no {SUPPORTED_CHECKPOINT_SCHEMA} checkpoint manifest under "
            f"the resuming root advances data_cursor.global_step past {source_global_step}"
        )
    return out


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

    source_cursor = write_integrity.get("data_cursor")
    source_global_step = source_cursor.get("global_step") if isinstance(source_cursor, dict) else None
    if type(source_global_step) is not int:
        source_global_step = None

    # Spec bar: "written, reloaded, cursor advances correctly." A zero exit
    # code is only the "reloaded" half -- SUCCEEDED additionally requires a
    # successor checkpoint under the resuming root whose data_cursor advanced
    # past the source's. A zero-exit resume without that evidence caps at
    # ATTEMPTED_UNVERIFIED, which is NOT_MET.
    verified = False
    attempted_unverified = False
    for attempt in resume_attempts:
        if attempt.get("exit_code") != 0:
            continue
        advance = _find_cursor_advance(
            Path(attempt["run_root"]),
            source_manifest_path=manifest_path,
            source_global_step=source_global_step,
        )
        attempt["cursor_advance"] = advance
        if advance["verified"]:
            attempt["resumed_artifact_root"] = str(Path(advance["successor_manifest"]).parent)
            verified = True
        else:
            attempted_unverified = True
    restore_status = "NOT_ATTEMPTED"
    if verified:
        restore_status = "SUCCEEDED"
    elif attempted_unverified:
        restore_status = "ATTEMPTED_UNVERIFIED"
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
            else (
                "resume exited 0 but cursor advancement is UNVERIFIED: no successor checkpoint "
                "manifest under the resuming root advances data_cursor.global_step past the "
                "source's -- the spec bar is 'reloaded, cursor advances correctly', so a zero "
                "exit code alone never mints the restore leg (see "
                "components.restore_round_trip.attempts[].cursor_advance)"
            ) if restore_status == "ATTEMPTED_UNVERIFIED"
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

    # --- primary evidence: the running e4-measurement-receipt.json the specialist
    # --- path upserts after every step (crash-proof against post-publication
    # --- housekeeping failures by construction -- see run_vertical_slice.py) ---
    receipt_candidates = sorted(
        p for p in run_root.rglob("e4-measurement-receipt.json") if ".checkpoint-quarantine" not in p.parts
    )
    if not receipt_candidates:
        return {
            "status": "EVIDENCE_MISSING",
            "detail": (
                "no e4-measurement-receipt.json under this run root (the specialist path writes one "
                "per step as of the R1-E4 wiring; older runs never produced it), and peak VRAM via "
                f"child.log {'was recovered as disclosed context only' if peak_memory_bytes is not None else 'was not recoverable either'}"
            ),
            "components": {
                "tokens_per_second": None,
                "mfu": None,
                "peak_vram_during_training_bytes": peak_memory_bytes,
                "host_utilization": None,
            },
            "context": context,
            "needs": "a certified specialist run at a head carrying the R1-E4 wiring, so the run root holds a step-current e4-measurement-receipt.json",
        }
    defects: list[str] = []
    receipt: dict[str, Any] = {}
    if len(receipt_candidates) > 1:
        defects.append("ambiguous: multiple e4-measurement-receipt.json files under one run root: " + ", ".join(str(p) for p in receipt_candidates))
    else:
        try:
            receipt = json.loads(receipt_candidates[0].read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            defects.append(f"unreadable receipt: {error}")
        if not isinstance(receipt, dict):
            defects.append("receipt top level is not a JSON object")
            receipt = {}
    if receipt:
        def _finite_pos(value: Any) -> bool:
            return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0
        if receipt.get("schema_version") != "ember02-r1-e4-measurement/v1":
            defects.append(f"schema_version {receipt.get('schema_version')!r}")
        if receipt.get("tokens_missing_steps") != 0:
            defects.append(f"tokens_missing_steps={receipt.get('tokens_missing_steps')!r} -- some steps carried no per-step token count; throughput would be an extrapolation")
        tokens_total, wall_seconds, tps = receipt.get("tokens_total"), receipt.get("wall_seconds"), receipt.get("tokens_per_second")
        for name, value in (("steps", receipt.get("steps")), ("tokens_total", tokens_total), ("wall_seconds", wall_seconds), ("tokens_per_second", tps)):
            if not _finite_pos(value):
                defects.append(f"{name}: not finite-positive ({value!r})")
        if _finite_pos(tokens_total) and _finite_pos(wall_seconds) and _finite_pos(tps) and abs(tps - tokens_total / wall_seconds) > 0.01 * tps:
            defects.append("tokens_per_second inconsistent with its own tokens_total/wall_seconds")
        mfu = receipt.get("mfu") if isinstance(receipt.get("mfu"), dict) else {}
        mfu_value = mfu.get("value")
        if not (isinstance(mfu_value, (int, float)) and not isinstance(mfu_value, bool) and math.isfinite(mfu_value) and 0 < mfu_value < 1):
            defects.append(f"mfu.value: not a finite fraction in (0,1) ({mfu_value!r})")
        elif _finite_pos(mfu.get("active_parameters")) and _finite_pos(mfu.get("assumed_peak_flops")) and _finite_pos(tokens_total) and _finite_pos(wall_seconds):
            expected_mfu = (6.0 * mfu["active_parameters"] * tokens_total / wall_seconds) / mfu["assumed_peak_flops"]
            if abs(mfu_value - expected_mfu) > 0.01 * expected_mfu:
                defects.append("mfu.value inconsistent with its own declared flops model")
        else:
            defects.append("mfu.active_parameters/assumed_peak_flops missing, so the flops model cannot be re-derived")
        vram = receipt.get("peak_vram") if isinstance(receipt.get("peak_vram"), dict) else {}
        if not (_finite_pos(vram.get("allocated_bytes")) and _finite_pos(vram.get("reserved_bytes"))):
            defects.append(f"peak_vram allocated/reserved not finite-positive ({vram.get('allocated_bytes')!r}/{vram.get('reserved_bytes')!r})")
        elif vram["reserved_bytes"] < vram["allocated_bytes"]:
            defects.append("peak_vram.reserved_bytes below allocated_bytes -- allocator invariant violated")
        host = receipt.get("host_utilization") if isinstance(receipt.get("host_utilization"), dict) else {}
        frac = host.get("process_cpu_fraction")
        if not (isinstance(frac, (int, float)) and not isinstance(frac, bool) and math.isfinite(frac) and frac >= 0):
            defects.append(f"host_utilization.process_cpu_fraction: not a finite nonnegative number ({frac!r})")
    if defects:
        return {
            "status": "NOT_MET",
            "detail": "e4-measurement-receipt present but invalid: " + "; ".join(defects),
            "components": {"receipt_path": [str(p) for p in receipt_candidates], "defects": defects},
            "context": context,
            "needs": "a content-valid e4-measurement-receipt.json (every quantity finite and arithmetic-consistent with its own inputs)",
        }
    return {
        "status": "MET",
        "detail": f"validated e4-measurement-receipt: {receipt_candidates[0]} (steps={receipt.get('steps')}, tokens/s={receipt.get('tokens_per_second'):.4g}, mfu={receipt['mfu']['value']:.3e})",
        "components": {
            "tokens_per_second": receipt.get("tokens_per_second"),
            "mfu": receipt["mfu"]["value"],
            "peak_vram_during_training_bytes": receipt["peak_vram"]["allocated_bytes"],
            "peak_vram_reserved_bytes": receipt["peak_vram"]["reserved_bytes"],
            "host_utilization": receipt["host_utilization"]["process_cpu_fraction"],
            "receipt_path": str(receipt_candidates[0]),
        },
        "context": context,
    }


# ---------------------------------------------------------------------------
# R1-E5 -- first closed-boundary frontier receipt, §5.4, energy_boundary
# DEGRADED_PROXY.
# ---------------------------------------------------------------------------

def check_r1_e5(run_root: Path, thresholds: dict[str, Any], *, repo_root: Path = REPO_ROOT, fixed_prior_manifest_path: Path | None = None) -> dict[str, Any]:
    t01 = int(thresholds["T-01"])
    t06 = float(thresholds["T-06"])
    fixed_prior_manifest_path = fixed_prior_manifest_path or DEFAULT_FIXED_PRIOR_MANIFEST
    fixed_prior_present = fixed_prior_manifest_path.is_file()
    fixed_prior_sha256 = _sha256_file(fixed_prior_manifest_path) if fixed_prior_present else None

    frontier_receipt_candidates = sorted(run_root.rglob("*frontier*receipt*.json")) if run_root.is_dir() else []
    energy_receipt_candidates = [
        p for p in (run_root.rglob("*.json") if run_root.is_dir() else [])
        if "energy" in p.name.lower()
    ]

    # A filename match is a CANDIDATE pointer, never §5.4 evidence. The only
    # spec-frozen, checkable-today content is the energy block (§5.3's shape:
    # energy.energy_boundary, energy.sample_coverage_fraction vs T-06) -- run
    # those checks per candidate and record them, but MET stays unreachable
    # until a full §5.4 validator exists (legs: ledger completeness,
    # fixed-prior + learned-import attestation, capability, time,
    # reproducibility, advantage-if-claimed, INVARIANT stamps -- their
    # receipt schema is defined nowhere yet; inventing one here is exactly
    # the invention this battery prohibits).
    candidate_validation: list[dict[str, Any]] = []
    for candidate_path in frontier_receipt_candidates:
        row: dict[str, Any] = {"path": str(candidate_path), "parse_ok": False}
        try:
            doc = json.loads(candidate_path.read_bytes())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            doc = None
        if isinstance(doc, dict):
            row["parse_ok"] = True
            energy = doc.get("energy") if isinstance(doc.get("energy"), dict) else {}
            boundary = energy.get("energy_boundary", doc.get("energy_boundary"))
            coverage = energy.get("sample_coverage_fraction", doc.get("sample_coverage_fraction"))
            row["energy_boundary"] = boundary
            row["energy_boundary_ok"] = boundary == "DEGRADED_PROXY"
            row["sample_coverage_fraction"] = _json_safe_number(coverage)
            row["sample_coverage_ok"] = (
                isinstance(coverage, (int, float)) and not isinstance(coverage, bool)
                and math.isfinite(coverage) and coverage >= t06
            )
        candidate_validation.append(row)

    return {
        "status": "EVIDENCE_MISSING",
        "frontier_receipt_validation": "PARTIAL_UNIMPLEMENTED",
        "detail": (
            (
                f"{len(frontier_receipt_candidates)} frontier-receipt-shaped candidate file(s) found, "
                "recorded with the spec-frozen energy-block checks only (energy_boundary == "
                f"'DEGRADED_PROXY', sample_coverage_fraction >= T-06={t06}) -- a validated §5.4 "
                "frontier receipt is still missing because no validator exists for the remaining "
                "§5.4 legs (ledger, fixed-prior + learned-import attestation, capability, time, "
                "reproducibility, advantage, INVARIANT stamps); a filename match must never mint MET"
            ) if frontier_receipt_candidates else
            "no frontier-receipt-shaped file under this run root, and no frontier-receipt generator "
            "exists anywhere in scripts/ (repo-wide grep, zero hits, 2026-08-05); no energy-proxy "
            "sampling occurred for this run (scripts/energy_proxy_logger.py exists but was not invoked)"
        ),
        "components": {
            "fixed_prior_manifest_present": fixed_prior_present,
            "fixed_prior_manifest_path": str(fixed_prior_manifest_path),
            "fixed_prior_manifest_sha256": fixed_prior_sha256,
            "frontier_receipt_candidates": [str(p) for p in frontier_receipt_candidates],
            "candidate_validation": candidate_validation,
            "energy_receipt_candidates": [str(p) for p in energy_receipt_candidates],
        },
        "needs": (
            f"a §5.4-validated closed-boundary frontier receipt (all 8 legs; energy_boundary "
            f"'DEGRADED_PROXY'; sample_coverage_fraction >= T-06={t06}) from a real >= T-01={t01}-step "
            "canary with energy-proxy sampling -- which first needs BOTH a frontier-receipt assembly "
            "script and a §5.4 validator (neither exists yet): an engineering task, not just an "
            "execution one"
        ),
    }


# ---------------------------------------------------------------------------
# R1-E6 -- forecast-recalibration receipt.
# ---------------------------------------------------------------------------

RECALIBRATION_SCHEMA = "ember02-forecast-recalibration/v1"
E6_FORECAST_SCHEMA = "ember02-r1-forecast/v1"
# The ONE document a recalibration receipt may bind (rev-1490 round-2: without
# this pin, any of the repo's 1,324 quantities-free JSON files was a valid-sha
# decoy that silently disabled the whole value binding).
E6_FORECAST_PATH = "docs/spec/ember02-r1-forecast-v1.json"
E6_SCALAR_QUANTITIES = ("step_time_ms", "tokens_per_second", "proxy_joules_per_token", "peak_vram_gib")


def _validate_recalibration_content(path: Path, *, repo_root: Path, run_root: Path, t01: int) -> list[str]:
    """Return the list of content defects (empty = valid) for one candidate
    recalibration receipt, per §3's closing-receipts clause. Fail-closed: every
    check that cannot be performed is itself a defect. Three bindings must all
    hold or the receipt is decorative (rev-1490 findings 1-3; round-2 finding):
      * document binding -- forecast_path must name THE preregistered document
        (E6_FORECAST_PATH, pinned), resolve INSIDE repo_root (no absolute
        paths, no traversal), hash to forecast_sha256, and validate as a
        forecast (E6_FORECAST_SCHEMA) -- binding any other repo JSON is a
        decoy that would disable the value binding;
      * value binding -- every predicted value in the receipt must EQUAL the
        bound forecast's predicted value (sha alone proves the document is
        unchanged, not that the receipt used its numbers); a quantity or
        anchor the bound forecast supplies NO prediction for is itself a
        defect, never a skipped comparison (round-2: the skip path was the
        door);
      * run binding -- the receipt's run_root must resolve to the adjudicated
        run root, and steps_measured must reach T-01 (a 3-step recalibration
        of someone else's run must not credit this root's exit).
    abs/rel errors are arithmetic-checked against the receipt's own
    predicted/measured values (scalars AND loss anchors) so a hand-assembled
    receipt cannot smuggle inconsistent numbers past the name match."""
    defects: list[str] = []
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return [f"unreadable or non-JSON: {error}"]
    if not isinstance(receipt, dict):
        return ["top level is not a JSON object"]
    if receipt.get("schema_version") != RECALIBRATION_SCHEMA:
        defects.append(f"schema_version is {receipt.get('schema_version')!r}, need {RECALIBRATION_SCHEMA!r}")

    receipt_run_root = receipt.get("run_root")
    if not isinstance(receipt_run_root, str) or not receipt_run_root:
        defects.append("run_root binding field missing")
    else:
        try:
            if Path(receipt_run_root).resolve() != run_root.resolve():
                defects.append(f"run_root mismatch: receipt was generated for {receipt_run_root!r}, adjudicating {str(run_root)!r} -- one run's recalibration must not credit another's exit")
        except OSError as error:
            defects.append(f"run_root unresolvable: {error}")
    steps_measured = receipt.get("steps_measured")
    if not isinstance(steps_measured, int) or isinstance(steps_measured, bool) or steps_measured < t01:
        defects.append(f"steps_measured={steps_measured!r} below T-01={t01} -- recalibration requires the measured baseline the prereg names")

    forecast_predicted: dict[str, Any] = {}
    forecast_bound = False  # True only once THE preregistered forecast is loaded and schema-validated
    forecast_rel = receipt.get("forecast_path")
    forecast_sha = receipt.get("forecast_sha256")
    if not isinstance(forecast_rel, str) or not isinstance(forecast_sha, str):
        defects.append("forecast_path/forecast_sha256 binding fields missing")
    else:
        repo_resolved = repo_root.resolve()
        if Path(forecast_rel).is_absolute():
            defects.append(f"forecast_path is absolute ({forecast_rel!r}) -- the binding must be repo-relative so it names the preregistered document, not an arbitrary file")
        elif PurePath(forecast_rel).as_posix() != E6_FORECAST_PATH:
            defects.append(f"forecast_path {forecast_rel!r} does not name the preregistered forecast document ({E6_FORECAST_PATH}) -- binding any other repo file is refused (rev-1490 round-2: a quantities-free decoy JSON silently disabled the value binding)")
        else:
            forecast_abs = (repo_root / forecast_rel).resolve()
            if repo_resolved not in forecast_abs.parents and forecast_abs != repo_resolved:
                defects.append(f"forecast_path escapes the repository ({forecast_rel!r})")
            elif not forecast_abs.is_file():
                defects.append(f"bound forecast document does not exist: {forecast_rel}")
            elif hashlib.sha256(forecast_abs.read_bytes()).hexdigest() != forecast_sha:
                defects.append(f"forecast_sha256 does not match the bytes of {forecast_rel} -- the receipt binds a different forecast than the one on disk")
            else:
                try:
                    forecast_doc = json.loads(forecast_abs.read_text(encoding="utf-8"))
                except ValueError as error:
                    defects.append(f"bound forecast document is not valid JSON: {error}")
                else:
                    if not isinstance(forecast_doc, dict) or forecast_doc.get("schema_version") != E6_FORECAST_SCHEMA:
                        got = forecast_doc.get("schema_version") if isinstance(forecast_doc, dict) else type(forecast_doc).__name__
                        defects.append(f"bound document is not the preregistered forecast: schema_version={got!r}, need {E6_FORECAST_SCHEMA!r}")
                    elif not isinstance(forecast_doc.get("quantities"), dict) or not forecast_doc["quantities"]:
                        defects.append("bound forecast supplies no quantities mapping -- there is no preregistered comparison basis")
                    else:
                        forecast_predicted = forecast_doc["quantities"]
                        forecast_bound = True

    quantities = receipt.get("quantities")
    if not isinstance(quantities, dict):
        defects.append("quantities mapping missing")
        return defects

    def _num(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

    def _check_pair(label: str, entry: Mapping[str, Any], forecast_value: Any) -> None:
        predicted, measured = entry.get("predicted"), entry.get("measured")
        for field_name, value in (("predicted", predicted), ("measured", measured)):
            if not _num(value):
                defects.append(f"{label}.{field_name}: not a finite number ({value!r})")
        if forecast_bound and _num(predicted):
            if forecast_value is None:
                defects.append(f"{label}: bound forecast supplies no predicted value -- a receipt quantity without a preregistered basis is a defect, never a skipped comparison (rev-1490 round-2)")
            elif not _num(forecast_value):
                defects.append(f"{label}: bound forecast carries no finite predicted value to compare against")
            elif abs(predicted - forecast_value) > 1e-9 * max(1.0, abs(forecast_value)):
                defects.append(f"{label}.predicted={predicted!r} differs from the bound forecast's {forecast_value!r} -- the receipt did not use the preregistered prediction")
        if _num(predicted) and _num(measured):
            abs_error = entry.get("abs_error")
            if not _num(abs_error) or abs(abs_error - abs(measured - predicted)) > 1e-9 * max(1.0, abs(measured), abs(predicted)):
                defects.append(f"{label}.abs_error: absent or inconsistent with |measured - predicted|")

    for name in E6_SCALAR_QUANTITIES:
        entry = quantities.get(name)
        if not isinstance(entry, dict):
            defects.append(f"{name}: entry missing")
            continue
        forecast_entry = forecast_predicted.get(name) if isinstance(forecast_predicted.get(name), dict) else {}
        _check_pair(name, entry, forecast_entry.get("predicted"))

    trajectory = quantities.get("loss_trajectory")
    anchors = trajectory.get("anchors") if isinstance(trajectory, dict) else None
    forecast_lt = forecast_predicted.get("loss_trajectory") if isinstance(forecast_predicted.get("loss_trajectory"), dict) else {}
    forecast_anchors = forecast_lt.get("predicted_anchors") if isinstance(forecast_lt.get("predicted_anchors"), dict) else {}
    if not isinstance(anchors, dict) or not anchors:
        defects.append("loss_trajectory.anchors: missing or empty")
    else:
        if forecast_bound:
            if not forecast_anchors:
                defects.append("loss_trajectory: bound forecast supplies no predicted_anchors -- the anchor set has no preregistered basis (defect, never a skip)")
            elif set(anchors) != set(forecast_anchors):
                defects.append(f"loss_trajectory anchor set {sorted(anchors)} differs from the bound forecast's {sorted(forecast_anchors)}")
        for key, anchor in sorted(anchors.items()):
            if not isinstance(anchor, dict):
                defects.append(f"loss_trajectory.anchors[{key}]: not an object")
                continue
            _check_pair(f"loss_trajectory.anchors[{key}]", anchor, forecast_anchors.get(key))
    return defects


def check_r1_e6(run_root: Path, thresholds: dict[str, Any], *, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    t01 = int(thresholds["T-01"])
    forecast_matches = set(p for p in run_root.rglob("*forecast*.json") if ".checkpoint-quarantine" not in p.parts) if run_root.is_dir() else set()
    recalibration_matches = set(p for p in run_root.rglob("*recalibrat*.json") if ".checkpoint-quarantine" not in p.parts) if run_root.is_dir() else set()
    # Deduped union: one file named e.g. forecast-recalibration.json matches
    # BOTH name patterns -- it is one candidate document, not two satisfied
    # requirements. Name matches are candidate pointers only; §3's closing-
    # receipts clause defines the required CONTENT (predicted vs measured
    # step time, tokens/s, proxy-joules/token, peak VRAM, loss trajectory),
    # validated per-candidate by _validate_recalibration_content -- a filename
    # match must never mint MET.
    candidate_documents = [
        {
            "path": str(p),
            "name_matches": [
                name for name, hit in (("forecast", p in forecast_matches), ("recalibration", p in recalibration_matches)) if hit
            ],
        }
        for p in sorted(forecast_matches | recalibration_matches)
    ]
    required = ["step_time_ms", "tokens_per_second", "proxy_joules_per_token", "peak_vram_gib", "loss_trajectory"]
    if not candidate_documents:
        return {
            "status": "EVIDENCE_MISSING",
            "forecast_recalibration_validation": "IMPLEMENTED",
            "detail": (
                "no forecast document and no recalibration receipt found under this run root; "
                "generate one with scripts/forecast_recalibration.py --forecast "
                "docs/spec/ember02-r1-forecast-v1.json --run-root <this root> (it refuses, with the "
                "quantity named, until the run root carries the evidence each quantity needs -- "
                f"including a measured >= T-01={t01}-step baseline)"
            ),
            "components": {"candidate_documents": [], "required_predicted_vs_measured": required},
            "needs": (
                "a forecast-recalibration receipt whose CONTENT carries predicted vs measured step time, "
                "tokens/s, proxy-joules/token, peak VRAM, and loss trajectory (prereg §3 closing-receipts "
                f"clause), generated against a real measured >= T-01={t01}-step run"
            ),
        }
    validations = [
        {**doc, "defects": _validate_recalibration_content(Path(doc["path"]), repo_root=repo_root, run_root=run_root, t01=t01)}
        for doc in candidate_documents
    ]
    # The dispositive population is the candidates that CLAIM to be the
    # recalibration receipt (name-match "recalibration"); *forecast*-named
    # companions -- a copied-in forecast doc, a disk-forecast.json -- are
    # recorded but never counted toward ambiguity (rev-1490 finding 6: gating
    # on total candidate count produced a false NOT_MET with a false reason).
    claimants = [v for v in validations if "recalibration" in v["name_matches"]]
    valid_claimants = [v for v in claimants if not v["defects"]]
    if len(claimants) == 1 and len(valid_claimants) == 1:
        return {
            "status": "MET",
            "forecast_recalibration_validation": "IMPLEMENTED",
            "detail": f"validated forecast-recalibration receipt: {valid_claimants[0]['path']}",
            "components": {"candidate_validation": validations, "required_predicted_vs_measured": required},
        }
    if not claimants:
        return {
            "status": "EVIDENCE_MISSING",
            "forecast_recalibration_validation": "IMPLEMENTED",
            "detail": (
                f"{len(validations)} name-matched candidate(s) but none claims to be a recalibration "
                "receipt; generate one with scripts/forecast_recalibration.py"
            ),
            "components": {"candidate_validation": validations, "required_predicted_vs_measured": required},
            "needs": "a content-valid recalibration receipt under the run root",
        }
    return {
        "status": "NOT_MET",
        "forecast_recalibration_validation": "IMPLEMENTED",
        "detail": (
            f"{len(claimants)} recalibration claimant(s), {len(valid_claimants)} content-valid: "
            + ("ambiguous -- more than one candidate claims to be the recalibration receipt" if len(claimants) > 1 else
               "; ".join(f"{v['path']}: {'; '.join(v['defects'])}" for v in claimants if v["defects"]))
        ),
        "components": {"candidate_validation": validations, "required_predicted_vs_measured": required},
        "needs": "exactly one content-valid recalibration receipt (plus optionally the bound forecast document) under the run root",
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
    t01 = int(thresholds["T-01"])
    t07 = int(thresholds["T-07"])
    # The thresholds document's own sigma_definition: "pooled standard
    # deviation ... at matched step counts, measured at R1 scale with >= T-07
    # seeds". R1 scale IS T-01 steps (the "R1 step count" entry) -- a seed
    # counts only with >= T-01 steps of telemetry, and the pooled sigma
    # itself only qualifies over >= T-01 matched steps. Two 4-step roots are
    # not a seed-noise measurement.
    seed_series: dict[str, list[dict[str, Any]]] = {}
    seeds_usable_at_r1_scale = 0
    per_root: list[dict[str, Any]] = []
    for root in seed_roots:
        run_id, series, counts = _select_series(root, run_id=None)
        usable = len(series) >= t01
        seeds_usable_at_r1_scale += int(usable)
        per_root.append({
            "run_root": str(root),
            "run_id": run_id,
            "steps": len(series),
            "usable_at_r1_scale": usable,
            "run_ids_seen": counts,
        })
        if usable:
            seed_series[str(root)] = series
    if seeds_usable_at_r1_scale < t07:
        return {
            "status": "EVIDENCE_MISSING",
            "detail": (
                f"T-07={t07} seed replicas each with >= T-01={t01} steps of telemetry (R1 scale) "
                f"required; {len(seed_roots)} seed root(s) supplied, {seeds_usable_at_r1_scale} "
                "usable at R1 scale (per-seed step counts in components.per_seed_root)"
            ),
            "components": {"per_seed_root": per_root},
            "needs": f">= {t07} independent-seed runs each with >= T-01={t01} steps of train_step telemetry (none of this repo's CLI paths currently wire telemetry through a >=T-01-step run -- see module docstring)",
        }
    sigma_loss = pooled_sigma_seed(seed_series, metric="loss")
    sigma_grad_norm = pooled_sigma_seed(seed_series, metric="grad_norm")
    matched_ok = (
        sigma_loss["matched_step_count"] >= t01 and sigma_grad_norm["matched_step_count"] >= t01
    )
    if not matched_ok:
        # Sub-scale sigma values are deliberately NOT disclosed here -- a
        # number computed below the frozen scale must not exist to be quoted.
        return {
            "status": "EVIDENCE_MISSING",
            "detail": (
                f"sigma_seed must be pooled over >= T-01={t01} matched steps across all counted "
                "seeds (thresholds sigma_definition: 'at matched step counts, measured at R1 "
                f"scale'); matched_step_count: loss={sigma_loss['matched_step_count']}, "
                f"grad_norm={sigma_grad_norm['matched_step_count']}"
            ),
            "components": {"per_seed_root": per_root},
            "needs": f">= {t07} independent-seed runs sharing >= T-01={t01} matched telemetry steps",
        }
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


def check_r1_e8(search_roots: list[Path], thresholds: dict[str, Any]) -> dict[str, Any]:
    t08 = float(thresholds["T-08"])
    t09 = int(thresholds["T-09"])
    f11_formula = str(thresholds["F-11"])
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
    # The marker scan only LOCATES candidate A1 evidence -- it is never the
    # exit itself. R1-E8 adjudicates two computed legs (§4-A1): liveness
    # (equal-budget token ratio vs A3, floor T-08) and, iff the fallback tier
    # is invoked, parity (per-step loss/grad-norm trajectories vs the
    # CPU-offloaded full-state AdamW reference over T-09 matched steps,
    # inside the F-11 band, which itself consumes sigma_seed from a green
    # R1-E7). None of those inputs exists in any receiptable form, so MET is
    # deliberately unreachable: status stays EVIDENCE_MISSING until the leg
    # computations are implemented AND their evidence exists.
    liveness_leg = {
        "status": "EVIDENCE_MISSING",
        "bar": {"threshold_id": "T-08", "floor_fraction": t08, "meaning": "A1 equal-budget tokens vs A3 (leg 1)"},
        "missing": [
            "an A1 tier-1 (CPU-offloaded full-state AdamW) run with measured tokens/s and proxy-joules/token",
            "the matched A3 equal-budget token count to ratio against",
        ],
    }
    parity_leg = {
        "status": "EVIDENCE_MISSING",
        "required_when": "the fallback tier 2 mechanism is invoked (Tier 1 below the T-08 liveness floor)",
        "bar": {"threshold_ids": ["T-09", "F-11"], "matched_steps_required": t09, "band_formula": f11_formula},
        "missing": [
            "candidate-mechanism per-step loss/grad-norm trajectory over T-09 matched steps",
            "CPU-offloaded full-state AdamW reference trajectory (same model/data/seed)",
            "sigma_seed(loss) and sigma_seed(grad_norm_ratio) from a green R1-E7",
        ],
    }
    return {
        "status": "EVIDENCE_MISSING",
        "detail": (
            (
                f"{len(candidates)} manifest(s) carry A1 marker words -- recorded as candidate "
                f"pointers ONLY; R1-E8 adjudicates the computed liveness leg (floor T-08={t08}) "
                f"and conditional parity leg (T-09={t09} matched steps inside the F-11 band), and "
                "neither is computable from any evidence on disk (a marker word in a manifest is "
                "not a leg receipt)"
            ) if candidates else
            "no A1 (dense) arm run found under any given search root -- every checkpoint inspected is "
            "architecture_revision ember-sparse-3b-v2 (A3's role-prior sparse architecture); repo-wide "
            "grep for tier1/offload/Q-GaLore mechanisms in tools/ember-restart-3b finds zero hits "
            "beyond the preregistration text itself (2026-08-05)"
        ),
        "components": {
            "candidate_manifests": candidates,
            "liveness_leg": liveness_leg,
            "parity_leg": parity_leg,
        },
        "needs": (
            f"an A1 tier-1 (CPU-offloaded full-state AdamW) run, its liveness leg computed against "
            f"T-08={t08} (equal-budget tokens vs A3), and -- if the fallback tier is invoked -- the "
            f"parity leg over T-09={t09} matched steps inside the F-11 band (formula in "
            "components.parity_leg.bar.band_formula, consuming sigma_seed from a green R1-E7) -- "
            "no A1 execution path exists anywhere in this repo yet; this is an engineering task "
            "before it is an execution one"
        ),
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
    run_id: str | None = None,
) -> dict[str, Any]:
    seed_roots_effective = list(seed_roots) or [run_root]
    if exit_id == "e1":
        result = check_r1_e1(run_root, thresholds, run_id=run_id)
    elif exit_id == "e2":
        result = check_r1_e2(run_root, thresholds, run_id=run_id)
    elif exit_id == "e3":
        result = check_r1_e3(run_root, sibling_roots=sibling_roots, explicit_manifest=explicit_manifest)
    elif exit_id == "e4":
        result = check_r1_e4(run_root)
    elif exit_id == "e5":
        result = check_r1_e5(run_root, thresholds)
    elif exit_id == "e6":
        result = check_r1_e6(run_root, thresholds)
    elif exit_id == "e7":
        result = check_r1_e7(seed_roots_effective, thresholds)
    elif exit_id == "e8":
        result = check_r1_e8(sibling_roots + [run_root], thresholds)
    else:
        raise R1ExitBatteryRefusal(f"UNKNOWN_EXIT_ID: {exit_id!r}")
    subject: dict[str, Any] = {
        "run_root": str(run_root),
        "sibling_roots": [str(p) for p in sibling_roots],
        # R1-E7 adjudicates the EFFECTIVE seed set (defaulting to the run root
        # when no --seed-root is supplied) -- the receipt records what was
        # adjudicated, never an empty list the check did not use.
        "seed_roots": [str(p) for p in (seed_roots_effective if exit_id == "e7" else seed_roots)],
    }
    if run_id is not None:
        subject["run_id"] = run_id
    return build_receipt(
        ticket=f"r1-exit-battery-{exit_id}",
        exit_criterion=f"R1-{exit_id.upper()}",
        subject=subject,
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
    ap.add_argument("--run-id", type=str, default=None, help="explicit telemetry run_id to adjudicate for R1-E1/E2 (default: the single run_id present under --run-root; multiple run_ids without this flag refuse)")
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
                run_id=args.run_id,
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


def _synthetic_checkpoint(tmp_dir: Path, *, seed: int = 830001, corrupt_shard: bool = False, corrupt_cross_ref: bool = False, global_step: int = 4) -> Path:
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
        "data_cursor": {"global_step": global_step, "record_index": global_step, "tokens_seen": 36, "shard": "SELFTEST_FIXTURE_shard"},
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

        # --- E1 (R-13): 100 events with NO loss field cannot demonstrate "zero NaN/Inf in loss" -> NOT_MET ---
        fieldless_root = tmp_path / "fieldless_run"
        fieldless_events = []
        for step in range(1, 101):
            ts = datetime.fromtimestamp(1785900000 + step, tz=timezone.utc).isoformat().replace("+00:00", "Z")
            fieldless_events.append({"ts": ts, "kind": "train_step", "source": "ember-restart-3b", "payload": {"run_id": "SELFTEST_FIXTURE_run", "step": step, "grad_norm": 1.0}})
        _write_jsonl(fieldless_root / "telemetry.jsonl", fieldless_events)
        r4 = check_r1_e1(fieldless_root, thresholds)
        assert r4["status"] == "NOT_MET" and r4["missing_field_count"] == 100, r4
        assert r4["missing_field_rows"][0] == {"step": 1, "field": "loss", "present": False}, r4

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

        # --- E2 (R-5): an unanchored mid-run fragment (steps 41..140, decreasing) must refuse, not adjudicate ---
        fragment_root = tmp_path / "fragment_run"
        fragment_events = []
        for step in range(41, 141):
            ts = datetime.fromtimestamp(1785900000 + step, tz=timezone.utc).isoformat().replace("+00:00", "Z")
            fragment_events.append({"ts": ts, "kind": "train_step", "source": "ember-restart-3b", "payload": {"run_id": "SELFTEST_FIXTURE_run", "step": step, "loss": 2.0 - 0.01 * step, "grad_norm": 1.0}})
        _write_jsonl(fragment_root / "telemetry.jsonl", fragment_events)
        e2_fragment = check_r1_e2(fragment_root, thresholds)
        assert e2_fragment["status"] == "EVIDENCE_MISSING", e2_fragment
        assert e2_fragment["missing_step_span"] == [1, 40], e2_fragment

        # --- E2 (R-5): a 20-step run fills both windows but is not the T-01 canary -> refuse ---
        twenty_root = tmp_path / "twenty_run"
        _write_jsonl(twenty_root / "telemetry.jsonl", _synthetic_train_step_events(run_id="SELFTEST_FIXTURE_run", n_steps=20))
        e2_twenty = check_r1_e2(twenty_root, thresholds)
        assert e2_twenty["status"] == "EVIDENCE_MISSING", e2_twenty
        assert e2_twenty["missing_step_span"] == [21, 100], e2_twenty

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

        # --- E3 (R-1): a zero-exit resume with NO successor checkpoint -> ATTEMPTED_UNVERIFIED, NOT_MET ---
        resume_sibling_ok = tmp_path / "e3_resume_sibling_ok"
        resume_sibling_ok.mkdir()
        launch_receipt_ok = {
            "argv": ["python", "run_vertical_slice.py", "governed-vertical", "--resume-checkpoint", str(ckpt_dir)],
            "exit_code": 0,
            "child_log": None,
        }
        (resume_sibling_ok / "disk-budget-runner-receipt-certified-launch.json").write_bytes(json.dumps(launch_receipt_ok).encode("utf-8"))
        e3_unverified = check_r1_e3(ok_ckpt_root, sibling_roots=[resume_sibling_ok])
        assert e3_unverified["components"]["restore_round_trip"]["status"] == "ATTEMPTED_UNVERIFIED", e3_unverified
        assert e3_unverified["status"] == "NOT_MET", e3_unverified
        assert e3_unverified["components"]["restore_round_trip"]["attempts"][0]["cursor_advance"]["verified"] is False, e3_unverified

        # --- E3 (R-1): successor checkpoint present but cursor NOT advanced (global_step equal) -> still unverified ---
        _synthetic_checkpoint(resume_sibling_ok, seed=830002, global_step=4)
        e3_stale = check_r1_e3(ok_ckpt_root, sibling_roots=[resume_sibling_ok])
        assert e3_stale["components"]["restore_round_trip"]["status"] == "ATTEMPTED_UNVERIFIED", e3_stale
        assert e3_stale["status"] == "NOT_MET", e3_stale

        # --- E3 (R-1): successor checkpoint with an ADVANCED cursor -> SUCCEEDED, overall MET ---
        _synthetic_checkpoint(resume_sibling_ok, seed=830003, global_step=5)
        e3_ok_resume = check_r1_e3(ok_ckpt_root, sibling_roots=[resume_sibling_ok])
        assert e3_ok_resume["components"]["restore_round_trip"]["status"] == "SUCCEEDED", e3_ok_resume
        assert e3_ok_resume["status"] == "MET", e3_ok_resume
        advance = e3_ok_resume["components"]["restore_round_trip"]["attempts"][0]["cursor_advance"]
        assert advance["verified"] is True and advance["source_global_step"] == 4 and advance["successor_global_step"] == 5, e3_ok_resume
        resumed_root = e3_ok_resume["components"]["restore_round_trip"]["attempts"][0]["resumed_artifact_root"]
        assert str(resumed_root).endswith("checkpoint-vertical-slice-seed-830003"), e3_ok_resume

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
        assert e4_result["status"] == "EVIDENCE_MISSING", e4_result  # child.log alone is disclosed context, not the measurement receipt
        assert e4_result["components"]["peak_vram_during_training_bytes"] == 12345678, e4_result
        assert e4_result["context"]["pre_run_vram_preflight"]["total_gb"] == 25.76, e4_result

        # --- E4: content-valid measurement receipt -> MET, components arithmetic-verified ---
        def _e4_receipt(steps: int = 100, tokens_total: int = 773, wall_seconds: float = 17.4) -> dict[str, Any]:
            active, peak = 1_725_232_640, 165.2e12
            return {
                "schema_version": "ember02-r1-e4-measurement/v1",
                "run_id": "SELFTEST_FIXTURE_run",
                "steps": steps, "tokens_total": tokens_total, "tokens_missing_steps": 0,
                "wall_seconds": wall_seconds, "step_ms_sum": wall_seconds * 1000.0,
                "tokens_per_second": tokens_total / wall_seconds,
                "tokens_per_second_step_basis": tokens_total / wall_seconds,
                "mfu": {"value": (6.0 * active * tokens_total / wall_seconds) / peak,
                        "flops_model": "6 * active_parameters * tokens_total / wall_seconds",
                        "active_parameters": active, "assumed_peak_flops": peak},
                "peak_vram": {"allocated_bytes": 21_700_000_000, "reserved_bytes": 22_100_000_000},
                "host_utilization": {"process_cpu_seconds": 8.7, "wall_seconds": wall_seconds, "process_cpu_fraction": 0.5},
            }
        e4_met_root = tmp_path / "e4_met_run"
        e4_met_root.mkdir()
        (e4_met_root / "e4-measurement-receipt.json").write_text(json.dumps(_e4_receipt()), encoding="utf-8")
        e4_met = check_r1_e4(e4_met_root)
        assert e4_met["status"] == "MET", e4_met
        assert abs(e4_met["components"]["tokens_per_second"] - 773 / 17.4) < 1e-9, e4_met

        # --- E4: tokens_per_second inconsistent with its own inputs -> NOT_MET ---
        e4_bad = _e4_receipt()
        e4_bad["tokens_per_second"] = e4_bad["tokens_per_second"] * 3.0
        e4_bad_root = tmp_path / "e4_bad_run"
        e4_bad_root.mkdir()
        (e4_bad_root / "e4-measurement-receipt.json").write_text(json.dumps(e4_bad), encoding="utf-8")
        e4_bad_result = check_r1_e4(e4_bad_root)
        assert e4_bad_result["status"] == "NOT_MET", e4_bad_result
        assert any("inconsistent" in d for d in e4_bad_result["components"]["defects"]), e4_bad_result

        # --- E4: a partial run with missing per-step tokens (nulls) -> NOT_MET, never extrapolated ---
        e4_null = _e4_receipt()
        e4_null["tokens_missing_steps"] = 7
        e4_null["tokens_total"] = None
        e4_null["tokens_per_second"] = None
        e4_null["mfu"]["value"] = None
        e4_null_root = tmp_path / "e4_null_run"
        e4_null_root.mkdir()
        (e4_null_root / "e4-measurement-receipt.json").write_text(json.dumps(e4_null), encoding="utf-8")
        e4_null_result = check_r1_e4(e4_null_root)
        assert e4_null_result["status"] == "NOT_MET", e4_null_result
        assert any("tokens_missing_steps" in d for d in e4_null_result["components"]["defects"]), e4_null_result

        # --- E5/E6: EVIDENCE_MISSING against an empty root; fixed-prior manifest presence is reported ---
        e5 = check_r1_e5(empty_root, thresholds)
        assert e5["status"] == "EVIDENCE_MISSING", e5
        assert e5["components"]["fixed_prior_manifest_present"] is True, e5  # real repo file, checked via REPO_ROOT default

        # --- E5 (R-2): a name-matched JUNK file must NOT mint MET; partial validation is recorded ---
        e5_junk_root = tmp_path / "e5_junk_run"
        e5_junk_root.mkdir()
        (e5_junk_root / "SELFTEST_FIXTURE-frontier-receipt.json").write_bytes(json.dumps({"note": "SELFTEST_FIXTURE junk"}).encode("utf-8"))
        e5_junk = check_r1_e5(e5_junk_root, thresholds)
        assert e5_junk["status"] == "EVIDENCE_MISSING", e5_junk
        assert e5_junk["frontier_receipt_validation"] == "PARTIAL_UNIMPLEMENTED", e5_junk
        junk_row = e5_junk["components"]["candidate_validation"][0]
        assert junk_row["parse_ok"] is True and junk_row["energy_boundary_ok"] is False and junk_row["sample_coverage_ok"] is False, e5_junk

        # --- E5 (R-2): even a candidate passing every IMPLEMENTED energy check refuses MET (no full §5.4 validator) ---
        e5_energy_root = tmp_path / "e5_energy_run"
        e5_energy_root.mkdir()
        (e5_energy_root / "SELFTEST_FIXTURE-frontier-receipt.json").write_bytes(json.dumps({
            "energy": {"energy_boundary": "DEGRADED_PROXY", "sample_coverage_fraction": float(thresholds["T-06"])},
        }).encode("utf-8"))
        e5_energy = check_r1_e5(e5_energy_root, thresholds)
        assert e5_energy["status"] == "EVIDENCE_MISSING", e5_energy
        energy_row = e5_energy["components"]["candidate_validation"][0]
        assert energy_row["energy_boundary_ok"] is True and energy_row["sample_coverage_ok"] is True, e5_energy

        e6 = check_r1_e6(empty_root, thresholds)
        assert e6["status"] == "EVIDENCE_MISSING", e6
        assert e6["forecast_recalibration_validation"] == "IMPLEMENTED", e6

        # --- E6 (R-3): ONE file matching BOTH name patterns is deduped to one candidate;
        # --- garbage content now fails VALIDATION (NOT_MET), never mints MET on the name ---
        e6_dual_root = tmp_path / "e6_dual_run"
        e6_dual_root.mkdir()
        (e6_dual_root / "forecast-recalibration.json").write_bytes(json.dumps({"SELFTEST_FIXTURE": True}).encode("utf-8"))
        e6_dual = check_r1_e6(e6_dual_root, thresholds)
        assert e6_dual["status"] == "NOT_MET", e6_dual
        assert e6_dual["forecast_recalibration_validation"] == "IMPLEMENTED", e6_dual
        dual_rows = e6_dual["components"]["candidate_validation"]
        assert len(dual_rows) == 1 and sorted(dual_rows[0]["name_matches"]) == ["forecast", "recalibration"], e6_dual
        assert dual_rows[0]["defects"], e6_dual

        # --- E6: a content-valid receipt -- sha-bound, value-bound, run-bound -> MET ---
        e6_repo = tmp_path / "e6_repo"
        (e6_repo / "docs" / "spec").mkdir(parents=True)
        e6_forecast_bytes = json.dumps({
            "schema_version": "ember02-r1-forecast/v1",
            "SELFTEST_FIXTURE": True,
            "quantities": {
                "step_time_ms": {"predicted": 174.0},
                "tokens_per_second": {"predicted": 44.4},
                "proxy_joules_per_token": {"predicted": 10.1},
                "peak_vram_gib": {"predicted": 20.2},
                "loss_trajectory": {"predicted_anchors": {"step_100": 0.39}},
            },
        }).encode("utf-8")
        (e6_repo / "docs" / "spec" / "ember02-r1-forecast-v1.json").write_bytes(e6_forecast_bytes)
        e6_met_root = tmp_path / "e6_met_run"
        e6_met_root.mkdir()
        def _e6_scalar(predicted: float, measured: float) -> dict[str, Any]:
            return {"predicted": predicted, "measured": measured, "abs_error": abs(measured - predicted), "rel_error": abs(measured - predicted) / abs(predicted)}
        e6_receipt = {
            "schema_version": "ember02-forecast-recalibration/v1",
            "generator": "scripts/forecast_recalibration.py",
            "forecast_path": "docs/spec/ember02-r1-forecast-v1.json",
            "forecast_sha256": hashlib.sha256(e6_forecast_bytes).hexdigest(),
            "run_root": str(e6_met_root),
            "steps_measured": 100,
            "quantities": {
                "step_time_ms": _e6_scalar(174.0, 181.5),
                "tokens_per_second": _e6_scalar(44.4, 42.6),
                "proxy_joules_per_token": _e6_scalar(10.1, 6.8),
                "peak_vram_gib": _e6_scalar(20.2, 20.4),
                "loss_trajectory": {"anchors": {"step_100": {"predicted": 0.39, "measured": 0.41, "abs_error": 0.02}}},
            },
        }
        (e6_met_root / "forecast-recalibration.json").write_text(json.dumps(e6_receipt), encoding="utf-8")
        e6_met = check_r1_e6(e6_met_root, thresholds, repo_root=e6_repo)
        assert e6_met["status"] == "MET", e6_met

        # --- E6 (rev-1490 f6): the valid receipt plus TWO forecast-named companions stays MET ---
        (e6_met_root / "disk-forecast.json").write_text(json.dumps({"noise": 1}), encoding="utf-8")
        (e6_met_root / "old-forecast.json").write_text(json.dumps({"noise": 2}), encoding="utf-8")
        e6_companions = check_r1_e6(e6_met_root, thresholds, repo_root=e6_repo)
        assert e6_companions["status"] == "MET", e6_companions

        # --- E6 (rev-1490 f1): predicted values differing from the bound forecast -> NOT_MET ---
        e6_invent = json.loads(json.dumps(e6_receipt))
        e6_invent["quantities"]["step_time_ms"] = _e6_scalar(999.0, 999.0)
        e6_invent_root = tmp_path / "e6_invent_run"
        e6_invent_root.mkdir()
        e6_invent["run_root"] = str(e6_invent_root)
        (e6_invent_root / "forecast-recalibration.json").write_text(json.dumps(e6_invent), encoding="utf-8")
        e6_invent_res = check_r1_e6(e6_invent_root, thresholds, repo_root=e6_repo)
        assert e6_invent_res["status"] == "NOT_MET", e6_invent_res
        assert any("did not use the preregistered prediction" in d for row in e6_invent_res["components"]["candidate_validation"] for d in row["defects"]), e6_invent_res

        # --- E6 (rev-1490 f2): absolute forecast_path -> NOT_MET; traversal -> NOT_MET ---
        for bad_path in (str((e6_repo / "docs" / "spec" / "ember02-r1-forecast-v1.json").resolve()), "../outside-forecast.json"):
            e6_abs = json.loads(json.dumps(e6_receipt))
            e6_abs["forecast_path"] = bad_path
            e6_abs_root = tmp_path / ("e6_path_run_" + hashlib.sha256(bad_path.encode()).hexdigest()[:8])
            e6_abs_root.mkdir()
            e6_abs["run_root"] = str(e6_abs_root)
            (e6_abs_root / "forecast-recalibration.json").write_text(json.dumps(e6_abs), encoding="utf-8")
            e6_abs_res = check_r1_e6(e6_abs_root, thresholds, repo_root=e6_repo)
            assert e6_abs_res["status"] == "NOT_MET", (bad_path, e6_abs_res)

        # --- E6 (rev-1490 f3): run_root naming a different run -> NOT_MET; steps below T-01 -> NOT_MET ---
        e6_foreign = json.loads(json.dumps(e6_receipt))
        e6_foreign_root = tmp_path / "e6_foreign_run"
        e6_foreign_root.mkdir()
        (e6_foreign_root / "forecast-recalibration.json").write_text(json.dumps(e6_foreign), encoding="utf-8")  # run_root still points at e6_met_root
        e6_foreign_res = check_r1_e6(e6_foreign_root, thresholds, repo_root=e6_repo)
        assert e6_foreign_res["status"] == "NOT_MET", e6_foreign_res
        assert any("run_root mismatch" in d for row in e6_foreign_res["components"]["candidate_validation"] for d in row["defects"]), e6_foreign_res
        e6_short = json.loads(json.dumps(e6_receipt))
        e6_short["steps_measured"] = 3
        e6_short_root = tmp_path / "e6_short_run"
        e6_short_root.mkdir()
        e6_short["run_root"] = str(e6_short_root)
        (e6_short_root / "forecast-recalibration.json").write_text(json.dumps(e6_short), encoding="utf-8")
        e6_short_res = check_r1_e6(e6_short_root, thresholds, repo_root=e6_repo)
        assert e6_short_res["status"] == "NOT_MET", e6_short_res
        assert any("T-01" in d for row in e6_short_res["components"]["candidate_validation"] for d in row["defects"]), e6_short_res

        # --- E6 (rev-1490 f4): quarantined receipts are invisible, both directions ---
        e6_quar_root = tmp_path / "e6_quar_run"
        (e6_quar_root / ".checkpoint-quarantine").mkdir(parents=True)
        e6_quar = json.loads(json.dumps(e6_receipt))
        e6_quar["run_root"] = str(e6_quar_root)
        (e6_quar_root / ".checkpoint-quarantine" / "forecast-recalibration.json").write_text(json.dumps(e6_quar), encoding="utf-8")
        e6_quar_res = check_r1_e6(e6_quar_root, thresholds, repo_root=e6_repo)
        assert e6_quar_res["status"] == "EVIDENCE_MISSING", e6_quar_res  # a valid receipt ONLY in quarantine never mints MET

        # --- E6 (rev-1490 informational): anchor abs_error tamper -> NOT_MET, same check as scalars ---
        e6_anchor = json.loads(json.dumps(e6_receipt))
        e6_anchor["quantities"]["loss_trajectory"]["anchors"]["step_100"]["abs_error"] = 123.0
        e6_anchor_root = tmp_path / "e6_anchor_run"
        e6_anchor_root.mkdir()
        e6_anchor["run_root"] = str(e6_anchor_root)
        (e6_anchor_root / "forecast-recalibration.json").write_text(json.dumps(e6_anchor), encoding="utf-8")
        e6_anchor_res = check_r1_e6(e6_anchor_root, thresholds, repo_root=e6_repo)
        assert e6_anchor_res["status"] == "NOT_MET", e6_anchor_res
        assert any("abs_error" in d for row in e6_anchor_res["components"]["candidate_validation"] for d in row["defects"]), e6_anchor_res

        # --- E6: tampered scalar abs_error -> NOT_MET ---
        e6_tamper = json.loads(json.dumps(e6_receipt))
        e6_tamper["quantities"]["step_time_ms"]["abs_error"] = 0.0
        e6_tamper_root = tmp_path / "e6_tamper_run"
        e6_tamper_root.mkdir()
        e6_tamper["run_root"] = str(e6_tamper_root)
        (e6_tamper_root / "forecast-recalibration.json").write_text(json.dumps(e6_tamper), encoding="utf-8")
        e6_bad = check_r1_e6(e6_tamper_root, thresholds, repo_root=e6_repo)
        assert e6_bad["status"] == "NOT_MET", e6_bad
        assert any("abs_error" in d for row in e6_bad["components"]["candidate_validation"] for d in row["defects"]), e6_bad

        # --- E6: receipt bound to a forecast whose bytes changed since -> NOT_MET (sha mismatch) ---
        e6_stale_repo = tmp_path / "e6_stale_repo"
        (e6_stale_repo / "docs" / "spec").mkdir(parents=True)
        (e6_stale_repo / "docs" / "spec" / "ember02-r1-forecast-v1.json").write_bytes(e6_forecast_bytes + b"\n")
        e6_stale = check_r1_e6(e6_met_root, thresholds, repo_root=e6_stale_repo)
        assert e6_stale["status"] == "NOT_MET", e6_stale
        assert any("forecast_sha256" in d for row in e6_stale["components"]["candidate_validation"] for d in row["defects"]), e6_stale

        # --- E6 (rev-1490 round-2, blocking finding): a fully fabricated receipt sha-bound to a
        # --- real repo JSON that is NOT the forecast must refuse on the path pin, never mint MET ---
        decoy_bytes = json.dumps({"schema_version": "ember02-preregistration-thresholds-v1", "SELFTEST_FIXTURE": True, "frozen": True}).encode("utf-8")
        (e6_repo / "docs" / "spec" / "decoy-thresholds.json").write_bytes(decoy_bytes)
        e6_decoy = json.loads(json.dumps(e6_receipt))
        e6_decoy["forecast_path"] = "docs/spec/decoy-thresholds.json"
        e6_decoy["forecast_sha256"] = hashlib.sha256(decoy_bytes).hexdigest()
        for name in E6_SCALAR_QUANTITIES:
            e6_decoy["quantities"][name] = _e6_scalar(999.0, 999.0)
        e6_decoy["quantities"]["loss_trajectory"] = {"anchors": {"step_1": {"predicted": 0.0, "measured": 0.0, "abs_error": 0.0}}}
        e6_decoy_root = tmp_path / "e6_decoy_run"
        e6_decoy_root.mkdir()
        e6_decoy["run_root"] = str(e6_decoy_root)
        (e6_decoy_root / "forecast-recalibration.json").write_text(json.dumps(e6_decoy), encoding="utf-8")
        e6_decoy_res = check_r1_e6(e6_decoy_root, thresholds, repo_root=e6_repo)
        assert e6_decoy_res["status"] == "NOT_MET", e6_decoy_res
        assert any("does not name the preregistered forecast document" in d for row in e6_decoy_res["components"]["candidate_validation"] for d in row["defects"]), e6_decoy_res

        # --- E6 (round-2): the canonical path occupied by a NON-forecast document -> schema defect ---
        e6_swap_repo = tmp_path / "e6_swap_repo"
        (e6_swap_repo / "docs" / "spec").mkdir(parents=True)
        swap_bytes = json.dumps({"schema_version": "ember02-preregistration-thresholds-v1", "SELFTEST_FIXTURE": True}).encode("utf-8")
        (e6_swap_repo / "docs" / "spec" / "ember02-r1-forecast-v1.json").write_bytes(swap_bytes)
        e6_swap = json.loads(json.dumps(e6_receipt))
        e6_swap["forecast_sha256"] = hashlib.sha256(swap_bytes).hexdigest()
        e6_swap_root = tmp_path / "e6_swap_run"
        e6_swap_root.mkdir()
        e6_swap["run_root"] = str(e6_swap_root)
        (e6_swap_root / "forecast-recalibration.json").write_text(json.dumps(e6_swap), encoding="utf-8")
        e6_swap_res = check_r1_e6(e6_swap_root, thresholds, repo_root=e6_swap_repo)
        assert e6_swap_res["status"] == "NOT_MET", e6_swap_res
        assert any("is not the preregistered forecast" in d for row in e6_swap_res["components"]["candidate_validation"] for d in row["defects"]), e6_swap_res

        # --- E6 (round-2): forecast valid but supplying NO prediction for one required quantity
        # --- -> named defect, never a skipped comparison ---
        e6_gap_repo = tmp_path / "e6_gap_repo"
        (e6_gap_repo / "docs" / "spec").mkdir(parents=True)
        gap_doc = json.loads(e6_forecast_bytes)
        del gap_doc["quantities"]["proxy_joules_per_token"]
        gap_bytes = json.dumps(gap_doc).encode("utf-8")
        (e6_gap_repo / "docs" / "spec" / "ember02-r1-forecast-v1.json").write_bytes(gap_bytes)
        e6_gap = json.loads(json.dumps(e6_receipt))
        e6_gap["forecast_sha256"] = hashlib.sha256(gap_bytes).hexdigest()
        e6_gap_root = tmp_path / "e6_gap_run"
        e6_gap_root.mkdir()
        e6_gap["run_root"] = str(e6_gap_root)
        (e6_gap_root / "forecast-recalibration.json").write_text(json.dumps(e6_gap), encoding="utf-8")
        e6_gap_res = check_r1_e6(e6_gap_root, thresholds, repo_root=e6_gap_repo)
        assert e6_gap_res["status"] == "NOT_MET", e6_gap_res
        assert any("supplies no predicted value" in d for row in e6_gap_res["components"]["candidate_validation"] for d in row["defects"]), e6_gap_res

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

        # --- E7 (R-6): two 4-step seed roots are NOT an R1-scale seed-noise measurement -> refuse ---
        seed_short_a = tmp_path / "seed_short_a"
        seed_short_b = tmp_path / "seed_short_b"
        _write_jsonl(seed_short_a / "telemetry.jsonl", _synthetic_train_step_events(run_id="SELFTEST_FIXTURE_ssa", n_steps=4))
        _write_jsonl(seed_short_b / "telemetry.jsonl", _synthetic_train_step_events(run_id="SELFTEST_FIXTURE_ssb", n_steps=4))
        e7_short = check_r1_e7([seed_short_a, seed_short_b], thresholds)
        assert e7_short["status"] == "EVIDENCE_MISSING", e7_short
        assert "T-01=100" in e7_short["detail"], e7_short
        assert all(row["usable_at_r1_scale"] is False for row in e7_short["components"]["per_seed_root"]), e7_short

        # --- E7 (R-6): two 100-step seeds whose MATCHED overlap is below T-01 -> refuse, no sub-scale sigma ---
        seed_offset = tmp_path / "seed_offset"
        offset_events = []
        for step in range(51, 151):
            ts = datetime.fromtimestamp(1785900000 + step, tz=timezone.utc).isoformat().replace("+00:00", "Z")
            offset_events.append({"ts": ts, "kind": "train_step", "source": "ember-restart-3b", "payload": {"run_id": "SELFTEST_FIXTURE_offset", "step": step, "loss": 1.0, "grad_norm": 1.0}})
        _write_jsonl(seed_offset / "telemetry.jsonl", offset_events)
        e7_offset = check_r1_e7([seed_a, seed_offset], thresholds)
        assert e7_offset["status"] == "EVIDENCE_MISSING", e7_offset
        assert "matched_step_count: loss=50" in e7_offset["detail"], e7_offset
        assert "sigma_seed" not in e7_offset, e7_offset

        # --- E8 (R-4): no A1 evidence anywhere -> EVIDENCE_MISSING, frozen bars quoted from the thresholds dict ---
        e8_missing = check_r1_e8([ok_ckpt_root, empty_root], thresholds)
        assert e8_missing["status"] == "EVIDENCE_MISSING", e8_missing
        assert e8_missing["components"]["candidate_manifests"] == [], e8_missing
        assert e8_missing["components"]["liveness_leg"]["bar"]["floor_fraction"] == thresholds["T-08"], e8_missing
        assert e8_missing["components"]["parity_leg"]["bar"]["matched_steps_required"] == thresholds["T-09"], e8_missing
        assert e8_missing["components"]["parity_leg"]["bar"]["band_formula"] == thresholds["F-11"], e8_missing

        # --- E8 (R-4): a manifest carrying A1 marker words is a CANDIDATE pointer only -- never MET ---
        a1_root = tmp_path / "a1_run"
        a1_ckpt_dir = a1_root / "artifacts" / "checkpoints" / "checkpoint-a1"
        a1_ckpt_dir.mkdir(parents=True)
        (a1_ckpt_dir / "checkpoint-manifest.json").write_bytes(json.dumps({"schema_version": "SELFTEST_FIXTURE", "arm": "A1_dense_tier1_offload"}).encode("utf-8"))
        e8_found = check_r1_e8([a1_root], thresholds)
        assert e8_found["status"] == "EVIDENCE_MISSING", e8_found
        assert len(e8_found["components"]["candidate_manifests"]) == 1, e8_found

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
