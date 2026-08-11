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
in one command. E4, E5, and E6 carry implemented content validators
(receipt-vs-inputs consistency for the E4 measurement receipt; the
section-5.4 eight-leg frontier-receipt validation for E5; forecast value
binding for E6) -- each still refuses until its run root carries real
evidence, and a filename or marker-word match never mints MET. E8 remains
refuse-until-validatable (the A1 liveness/parity leg computations do not
exist). Only E3 yields a real, scoped,
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
  * check_r1_e5 validates a section-5.4 frontier receipt (schema
    ember02-frontier-receipt/v1, produced by scripts/frontier_receipt.py)
    by independently re-verifying its bindings against the bytes on disk:
    repo-document pins (prereg, admission config, docs/authority/INVARIANT.md, fixed-prior
    manifest, tokenizer receipt, predecessor receipt, run-attempts
    registry), run-root evidence files by sha256 (frozen evals, runner
    receipt, energy producer receipt, reproduction adjudication,
    interventions, walls checklist), the section-5.3 energy block
    re-checked arithmetically AND compared field-for-field with the
    producer's disk copy, and reproducibility pins compared value-for-value
    with the checkpoint manifest. It re-states the spec constants rather
    than importing the generator: validator and generator are deliberately
    two independent transcriptions of the same frozen spec, so a
    transcription error in either surfaces as a refusal at first contact
    instead of validating itself. Telemetry series length is E1's leg (the
    battery composes all exits on one root); E5 checks the receipt's
    steps_measured against T-01 only.
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

import r1_frozen_eval_runner as frozen_eval

ISSUE_REF = "#1463"
PREREG_DOC = "docs/spec/ember02-preregistration-v1.md"
PREREG_PIN = "3d48d3870919bd04cec735f68d0fad45fcfae0b2"
RECEIPT_SCHEMA = "r1-exit-battery/v1"
RUN_ROOT_LAYOUT_SPEC_PATH = "docs/spec/ember-run-root-layout-v1.md"
RUN_ROOT_LAYOUT_SPEC = RUN_ROOT_LAYOUT_SPEC_PATH

SHA_CONVENTION = (
    "sha256 over on-disk raw bytes (binary read, no line-ending "
    "normalization) for checkpoint/manifest/telemetry/threshold files"
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_THRESHOLDS_PATH = REPO_ROOT / "docs" / "spec" / "ember02-preregistration-thresholds-v1.json"
FIXED_PRIOR_MANIFEST_REL = "manifests/ember-restart-3b/fixed-prior-manifest-v1.json"
DEFAULT_FIXED_PRIOR_MANIFEST = REPO_ROOT / FIXED_PRIOR_MANIFEST_REL


def _layout_spec_path(repo_root: Path = REPO_ROOT) -> Path:
    """Return the checked-in run-root layout authority used by discovery."""
    path = Path(repo_root) / RUN_ROOT_LAYOUT_SPEC_PATH
    if not path.is_file():
        raise R1ExitBatteryRefusal(
            f"RUN_ROOT_LAYOUT_SPEC_MISSING: {RUN_ROOT_LAYOUT_SPEC_PATH} is required"
        )
    return path

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


def _validate_frozen_eval_suite_binding(
    run_root: Path,
    capability: Mapping[str, Any],
    eval_doc: Mapping[str, Any],
) -> list[str]:
    """Independently reopen the exact #1498 frozen-suite bytes.

    The frontier producer's receipt is evidence, not a trust root.  R1 must
    therefore rederive the suite identity instead of accepting the producer's
    matching strings.
    """
    defects: list[str] = []
    candidates = sorted(
        path
        for path in run_root.rglob("frozen-eval-suite.json")
        if not _evidence_excluded(path, run_root)
    )
    if len(candidates) != 1:
        return [
            "capability: need exactly one frozen-eval-suite.json under the run root, "
            f"found {len(candidates)}"
        ]
    suite_path = candidates[0]
    named_suite = capability.get("eval_suite_path")
    try:
        named_ok = (
            isinstance(named_suite, str)
            and bool(named_suite.strip())
            and Path(named_suite).resolve() == suite_path.resolve()
        )
    except OSError:
        named_ok = False
    if not named_ok:
        defects.append(
            f"capability.eval_suite_path {named_suite!r} does not name the discovered "
            f"frozen suite {suite_path}"
        )
    suite_sha256 = _sha256_file(suite_path)
    if capability.get("eval_suite_sha256") != suite_sha256:
        defects.append("capability.eval_suite_sha256 does not match frozen suite bytes")
    if eval_doc.get("eval_suite_sha256") != suite_sha256:
        defects.append("capability: frozen-eval results do not bind frozen suite bytes")
    try:
        _suite_raw, suite = frozen_eval._load_suite(suite_path, suite_sha256)
    except frozen_eval.FrozenEvalRefusal as error:
        defects.append(f"capability: {error}")
        return defects
    if (
        suite.get("eval_suite_id") != capability.get("eval_suite_id")
        or suite.get("eval_suite_id") != eval_doc.get("eval_suite_id")
    ):
        defects.append("capability: frozen suite identity is inconsistent")
    return defects


def _registry_rows_and_prefix(
    path: Path, row_limit: int | None = None
) -> tuple[list[tuple[int, str]], bytes]:
    """Return every non-empty registry line plus exact bytes through the bound.

    ``row_limit`` selects the immutable prefix only.  The scan deliberately
    continues through the current tail so appended corruption cannot hide
    behind an otherwise valid historical prefix.
    """
    raw = path.read_bytes()
    lines: list[tuple[int, str]] = []
    prefix_end = 0
    cursor = 0
    for line_number, raw_line in enumerate(raw.splitlines(keepends=True), 1):
        cursor += len(raw_line)
        line = raw_line.decode("utf-8")
        if not line.strip():
            continue
        lines.append((line_number, line.strip()))
        if row_limit is None or len(lines) <= row_limit:
            prefix_end = cursor
    return lines, raw[:prefix_end]


def validate_run_attempt_completion(
    rows: list[dict[str, Any]],
    *,
    selected_run_id: str,
    run_root: Path,
    bound_row_count: int | None = None,
) -> list[str]:
    """Validate issue #1497's terminal-completeness contract.

    Every current row is schema-checked so an appended malformed tail cannot
    hide behind an older receipt prefix.  Attempt pairing is deliberately
    limited to ``bound_row_count``: a valid later append must not invalidate
    an already-minted #1510 prefix receipt.

    Historical ``backfill=true`` terminal rows predate the live spawn/exit
    chain and remain self-contained compatibility evidence.  New live rows
    require exactly one running row followed by exactly one terminal row for
    the same run-root/run/attempt identity.
    """
    import run_attempt_registry as registry

    defects: list[str] = []
    if bound_row_count is None:
        bound_row_count = len(rows)
    elif not isinstance(bound_row_count, int) or isinstance(bound_row_count, bool):
        defects.append("bound_row_count must be an integer")
        return defects
    if bound_row_count < 0 or bound_row_count > len(rows):
        defects.append(
            f"bound_row_count {bound_row_count} is outside the current {len(rows)} rows"
        )
        return defects
    if not isinstance(selected_run_id, str) or not selected_run_id.strip():
        defects.append("selected run identity is missing")
        return defects

    valid_rows: list[tuple[int, dict[str, Any]]] = []
    for index, row in enumerate(rows, start=1):
        row_defects = registry.validate_row(row)
        defects.extend(f"registry row {index}: {defect}" for defect in row_defects)
        if not row_defects:
            valid_rows.append((index, row))

    resolved_root = run_root.resolve()
    expected_root_ref = f"{resolved_root.parent.name}:{resolved_root.name}"
    relevant: list[tuple[int, dict[str, Any]]] = []
    for index, row in valid_rows:
        if index > bound_row_count:
            continue
        same_run = row["run_id"] == selected_run_id
        same_root_name = row["run_root_name"] == resolved_root.name
        if same_root_name and not same_run:
            defects.append(
                f"registry row {index}: foreign run {row['run_id']!r} under selected root "
                f"{resolved_root.name!r}"
            )
            continue
        if same_run and not same_root_name:
            defects.append(
                f"registry row {index}: foreign root {row['run_root_name']!r} for selected "
                f"run {selected_run_id!r}"
            )
            continue
        if not same_run and not same_root_name:
            continue
        if row["run_root_ref"] != expected_root_ref:
            defects.append(
                f"registry row {index}: foreign root reference {row['run_root_ref']!r}; "
                f"expected {expected_root_ref!r}"
            )
            continue
        relevant.append((index, row))

    if not relevant:
        defects.append(
            "no registry row names the selected run/root identity "
            f"({selected_run_id!r}, {resolved_root.name!r})"
        )
        return defects

    def _parse_utc(value: Any, *, index: int, field: str) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
        except ValueError:
            defects.append(
                f"registry row {index}: {field} must be canonical UTC YYYY-MM-DDTHH:MM:SSZ"
            )
            return None

    def _evidence_path(
        value: Any, *, index: int, field: str, require_file: bool
    ) -> Path | None:
        if not isinstance(value, str) or not value.strip():
            return None
        candidate = Path(value)
        try:
            resolved = (resolved_root / candidate).resolve()
            resolved.relative_to(resolved_root)
        except (OSError, ValueError):
            defects.append(
                f"registry row {index}: {field} escapes the selected run root"
            )
            return None
        if not resolved.exists():
            defects.append(
                f"registry row {index}: {field} does not resolve to existing custody evidence"
            )
            return None
        if require_file and not resolved.is_file():
            defects.append(
                f"registry row {index}: {field} must resolve to a regular evidence file"
            )
            return None
        return resolved

    grouped: dict[tuple[str, str, str], list[tuple[int, dict[str, Any]]]] = {}
    for index, row in relevant:
        start = _parse_utc(row.get("start_utc"), index=index, field="start_utc")
        end = None
        if row.get("outcome") != "running":
            end = _parse_utc(row.get("end_utc"), index=index, field="end_utc")
        if start is not None and end is not None and end < start:
            defects.append(f"registry row {index}: end_utc precedes start_utc")

        live = row["backfill"] is False
        launch_path = _evidence_path(
            row.get("launch_receipt_ref"),
            index=index,
            field="launch_receipt_ref",
            require_file=live,
        )
        source_path = _evidence_path(
            row.get("source_receipt"),
            index=index,
            field="source_receipt",
            require_file=live,
        )
        if live and row.get("launch_receipt_ref") != row.get("source_receipt"):
            phase = "running" if row["outcome"] == "running" else "terminal"
            defects.append(
                f"registry row {index}: {phase} receipt references are inconsistent"
            )
        if launch_path is not None and source_path is not None and live:
            if launch_path != source_path:
                phase = "running" if row["outcome"] == "running" else "terminal"
                defects.append(
                    f"registry row {index}: {phase} receipt references resolve to different evidence"
                )

        key = (row["run_root_ref"], row["run_id"], row["attempt_id"])
        grouped.setdefault(key, []).append((index, row))

    for key, attempt_rows in grouped.items():
        running = [(i, row) for i, row in attempt_rows if row["outcome"] == "running"]
        terminal = [(i, row) for i, row in attempt_rows if row["outcome"] != "running"]
        backfill_values = {row["backfill"] for _, row in attempt_rows}
        identity = f"run/root/attempt {key!r}"

        if backfill_values == {True}:
            if running:
                defects.append(f"{identity}: backfill running row is not terminal evidence")
            if len(terminal) == 0:
                defects.append(f"{identity}: historical backfill is missing a terminal row")
            elif len(terminal) > 1:
                defects.append(f"{identity}: duplicate terminal backfill rows")
            continue
        if len(backfill_values) > 1:
            defects.append(f"{identity}: live and backfill rows must not be mixed")

        if len(running) == 0:
            defects.append(f"{identity}: orphan terminal row (foreign attempt)")
            continue
        if len(running) > 1:
            defects.append(f"{identity}: duplicate running rows")
        if len(terminal) == 0:
            defects.append(f"{identity}: missing terminal row")
            continue
        if len(terminal) > 1:
            defects.append(f"{identity}: duplicate terminal rows")
            continue

        running_index, running_row = running[0]
        terminal_index, terminal_row = terminal[0]
        if terminal_index < running_index:
            defects.append(f"{identity}: terminal precedes running row")
        if terminal_row["start_utc"] != running_row["start_utc"]:
            defects.append(f"{identity}: terminal start_utc does not match running start_utc")
        if terminal_row["launch_receipt_ref"] == running_row["launch_receipt_ref"]:
            defects.append(f"{identity}: terminal must not reuse running evidence")

    return defects


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
                except UnicodeDecodeError as error:
                    raise R1ExitBatteryRefusal(f"TELEMETRY_UNREADABLE: {path}: {error}") from error
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict):
                    yield event
    except OSError as error:
        raise R1ExitBatteryRefusal(f"TELEMETRY_UNREADABLE: {path}: {error}") from error


def find_telemetry_files(run_root: Path) -> list[Path]:
    """Every *.jsonl under run_root whose lines look like real
    ember-restart-3b telemetry (append_training_telemetry's exact shape:
    top-level "source"=="ember-restart-3b"). A file with zero matching
    lines is not returned -- an incidental unrelated .jsonl file must not
    be mistaken for a telemetry channel."""
    _layout_spec_path()
    if not run_root.is_dir():
        return []
    found = []
    for candidate in sorted(run_root.rglob("*.jsonl")):
        # This skip is defense-in-depth against copied-in archive material
        # vouching for a run (rev-1494 round-2 item 3), and it is fail-OPEN
        # for content predicates: dedup keeps the latest-by-ts row per
        # (run_id, step), so hiding a quarantined file can PROMOTE an older
        # visible row -- exclusion must never be the mechanism a
        # correctness claim rests on. The load-bearing invariant is
        # upstream (rev-1490 round-3): the trainer never writes telemetry
        # under .checkpoint-quarantine -- only failed checkpoint-WRITE
        # artifacts live there (checkpoint-write-failed-*.json, staged
        # candidate-* dirs); a failed attempt's telemetry lands as a
        # visible sibling (attempt-*/telemetry/) under the same run_id and
        # is still loaded. Any skipped .jsonl that DOES hold real
        # train_step rows is a placement-invariant violation, surfaced by
        # find_quarantined_telemetry_files below.
        if ".checkpoint-quarantine" in candidate.parts:
            continue
        for event in _iter_jsonl_events(candidate):
            if event.get("source") == "ember-restart-3b":
                found.append(candidate)
                break
    return found


def _telemetry_sha256(run_root: Path) -> str:
    paths = find_telemetry_files(run_root)
    if not paths:
        raise R1ExitBatteryRefusal("TELEMETRY_MISSING: no non-quarantined telemetry files")
    digest = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(run_root).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def find_quarantined_telemetry_files(run_root: Path) -> list[Path]:
    """Every *.jsonl under a .checkpoint-quarantine dir that carries real
    ember-restart-3b train_step rows -- OR that cannot be read at all.
    Nothing on the certified path writes telemetry there (see the placement
    invariant in find_telemetry_files), so a non-empty result means
    copied-in archive material or a new producer bug -- surfaced in check
    components, never silently hidden (rev-1490 round-3 suggestion).
    Detection is a raw marker scan, not a JSON parse: a quarantined file is
    already a violation candidate, and an UNREADABLE one is the case where
    something is actively wrong -- a read error counts it and surfaces it
    rather than reporting the quarantine clean (rev-1490 non-blocking 3)."""
    _layout_spec_path()
    if not run_root.is_dir():
        return []
    found = []
    for candidate in sorted(run_root.rglob("*.jsonl")):
        if ".checkpoint-quarantine" not in candidate.parts:
            continue
        try:
            raw = candidate.read_bytes()
        except OSError:
            found.append(candidate)
            continue
        if b'"ember-restart-3b"' in raw and b'"train_step"' in raw:
            found.append(candidate)
    return found


def _evidence_excluded(path: Path, run_root: Path) -> bool:
    """True when a path may not serve as E5 EVIDENCE: anything under
    .checkpoint-quarantine (copied-in archive material must not vouch for a
    run) or under a preserved failed-attempt dir (attempt-*/ -- the
    launcher retains failed attempts as visible siblings; their receipts
    are history, and the run's authoritative evidence lives outside them).
    Telemetry loading deliberately does NOT use this: a failed attempt's
    train_step rows belong to the same run_id and are still counted
    (rev-1490 item 6: both modules must agree, and exclusion mirrors how
    the quarantine dir is already handled)."""
    _layout_spec_path()
    try:
        relative_parts = path.relative_to(run_root).parts
    except ValueError:
        return True
    return any(
        part == ".checkpoint-quarantine" or part.startswith("attempt-")
        for part in relative_parts
    )


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

# Adjudication-pinned MFU basis (rev-1494 finding 3: receipt-supplied constants
# were a tautology -- assumed_peak_flops moved reported MFU 2x with nothing
# binding it). The receipt must carry EXACTLY these values; the battery, not
# the producer, is the authority on the R1 flops model.
E4_ACTIVE_PARAMETERS = 1_725_232_640
E4_ASSUMED_PEAK_FLOPS = 165.2e12


def check_r1_e4(run_root: Path, thresholds: dict[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
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
            except UnicodeDecodeError:
                continue
            except json.JSONDecodeError:
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
    if not defects:
        # Content checks run on the parsed receipt EVEN IF it is an empty
        # object (rev-1494 finding 4: `if receipt:` let `{}` skip every check
        # and then crash the MET formatter) -- every missing section below is
        # its own defect, so `{}` fails closed with the full defect list.
        t01 = int(thresholds["T-01"])

        def _finite_pos(value: Any) -> bool:
            return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0

        def _finite_nonneg(value: Any) -> bool:
            return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0
        if receipt.get("schema_version") != "ember02-r1-e4-measurement/v1":
            defects.append(f"schema_version {receipt.get('schema_version')!r}")
        if receipt.get("tokens_missing_steps") != 0:
            defects.append(f"tokens_missing_steps={receipt.get('tokens_missing_steps')!r} -- some steps carried no per-step token count; throughput would be an extrapolation")
        write_failures = receipt.get("write_failures", 0)
        if not (isinstance(write_failures, int) and not isinstance(write_failures, bool) and write_failures >= 0):
            defects.append(f"write_failures: not a nonnegative integer ({write_failures!r})")
        steps = receipt.get("steps")
        if type(steps) is not int:
            defects.append(f"steps: not an integer ({steps!r})")
        elif steps < t01:
            defects.append(f"steps={steps} below T-01={t01} -- R1-E4 measures the credited >=T-01-step run, not a fragment (threshold via load_thresholds)")
        # Series bind (rev-1494 findings 1+d, and the merge-ordering hazard both
        # review comments name): the receipt's step count must agree with the
        # SAME deduped telemetry series E1 counts, so a hand-written receipt in
        # a telemetry-free root can never mint MET, and an E1/E4 disagreement
        # is a named defect instead of a silent split verdict. The producer
        # emits telemetry before accumulating, so telemetry may lead by at most
        # one step at a crash boundary.
        # run_id threads through from the dispatcher exactly as E1 receives it
        # (rev-1494 round-2 item 2): on a multi-run_id root the operator's
        # --run-id selects the SAME series for both checks, so E1 and E4 can
        # never silently adjudicate different series.
        selected_run_id, series, series_counts = _select_series(run_root, run_id=run_id)
        if not series:
            defects.append(
                "no train_step telemetry series under this run root to bind the receipt against"
                + (f" (run_ids seen: {sorted(series_counts)})" if len(series_counts) > 1 else "")
                + " -- an E4 receipt must describe the same series E1 adjudicates"
            )
        else:
            # The receipt must NAME the series it describes (rev-1494 round-2
            # item 1, same class as the E6 decoy cure): step-count agreement
            # alone would let a receipt describing a different run mint MET.
            receipt_run_id = receipt.get("run_id")
            if not isinstance(receipt_run_id, str) or not receipt_run_id:
                defects.append(
                    f"run_id: missing or not a non-empty string ({receipt_run_id!r}) -- the receipt "
                    "must name the run it describes (the producer writes telemetry's run_id)"
                )
            elif receipt_run_id != selected_run_id:
                defects.append(
                    f"run_id {receipt_run_id!r} does not match the adjudicated series run_id "
                    f"{selected_run_id!r} -- one run's receipt must not credit another's series"
                )
            if type(steps) is int:
                series_steps = len(series)
                if not (0 <= series_steps - steps <= 1):
                    defects.append(
                        f"steps={steps} disagrees with the deduped train_step series ({series_steps} steps, run_id {selected_run_id}) -- "
                        "the receipt must describe the series E1 counts (telemetry may lead by at most 1: emit-before-accumulate)"
                    )
        tokens_total, wall_seconds, tps = receipt.get("tokens_total"), receipt.get("wall_seconds"), receipt.get("tokens_per_second")
        for name, value in (("tokens_total", tokens_total), ("wall_seconds", wall_seconds), ("tokens_per_second", tps)):
            if not _finite_pos(value):
                defects.append(f"{name}: not finite-positive ({value!r})")
        if _finite_pos(tokens_total) and _finite_pos(wall_seconds) and _finite_pos(tps) and abs(tps - tokens_total / wall_seconds) > 0.01 * tps:
            defects.append("tokens_per_second inconsistent with its own tokens_total/wall_seconds")
        mfu = receipt.get("mfu") if isinstance(receipt.get("mfu"), dict) else {}
        mfu_value = mfu.get("value")
        # The flops-model constants are ADJUDICATION-pinned, not receipt-trusted
        # (rev-1494 finding 3): equality against the battery's own values, then
        # the arithmetic re-derivation runs on those pinned values.
        if mfu.get("active_parameters") != E4_ACTIVE_PARAMETERS:
            defects.append(f"mfu.active_parameters={mfu.get('active_parameters')!r} differs from the adjudication pin {E4_ACTIVE_PARAMETERS} -- the battery, not the receipt, is the authority on the R1 flops model")
        if not (isinstance(mfu.get("assumed_peak_flops"), (int, float)) and not isinstance(mfu.get("assumed_peak_flops"), bool) and math.isfinite(mfu.get("assumed_peak_flops")) and abs(mfu.get("assumed_peak_flops") - E4_ASSUMED_PEAK_FLOPS) <= 1e-6 * E4_ASSUMED_PEAK_FLOPS):
            defects.append(f"mfu.assumed_peak_flops={mfu.get('assumed_peak_flops')!r} differs from the adjudication pin {E4_ASSUMED_PEAK_FLOPS:.4g} -- a movable denominator moves reported MFU with nothing binding it")
        if not (isinstance(mfu_value, (int, float)) and not isinstance(mfu_value, bool) and math.isfinite(mfu_value) and 0 < mfu_value < 1):
            defects.append(f"mfu.value: not a finite fraction in (0,1) ({mfu_value!r})")
        elif _finite_pos(tokens_total) and _finite_pos(wall_seconds):
            expected_mfu = (6.0 * E4_ACTIVE_PARAMETERS * tokens_total / wall_seconds) / E4_ASSUMED_PEAK_FLOPS
            if abs(mfu_value - expected_mfu) > 0.01 * expected_mfu:
                defects.append("mfu.value inconsistent with the pinned flops model 6*N*T/(t*peak)")
        vram = receipt.get("peak_vram") if isinstance(receipt.get("peak_vram"), dict) else {}
        if not (_finite_pos(vram.get("allocated_bytes")) and _finite_pos(vram.get("reserved_bytes"))):
            defects.append(f"peak_vram allocated/reserved not finite-positive ({vram.get('allocated_bytes')!r}/{vram.get('reserved_bytes')!r})")
        elif vram["reserved_bytes"] < vram["allocated_bytes"]:
            defects.append("peak_vram.reserved_bytes below allocated_bytes -- allocator invariant violated")
        host = receipt.get("host_utilization") if isinstance(receipt.get("host_utilization"), dict) else {}
        frac, cpu_seconds, host_wall = host.get("process_cpu_fraction"), host.get("process_cpu_seconds"), host.get("wall_seconds")
        if not (isinstance(frac, (int, float)) and not isinstance(frac, bool) and math.isfinite(frac) and frac >= 0):
            defects.append(f"host_utilization.process_cpu_fraction: not a finite nonnegative number ({frac!r})")
        # rev-1494 finding 2: the fraction was declared, never re-derived. Both
        # inputs are now load-bearing and the arithmetic is checked.
        if not _finite_nonneg(cpu_seconds):
            defects.append(f"host_utilization.process_cpu_seconds: not a finite nonnegative number ({cpu_seconds!r})")
        if not _finite_pos(host_wall):
            defects.append(f"host_utilization.wall_seconds: not finite-positive ({host_wall!r})")
        elif _finite_pos(wall_seconds) and abs(host_wall - wall_seconds) > 0.01 * wall_seconds:
            defects.append(f"host_utilization.wall_seconds={host_wall!r} disagrees with the receipt's wall_seconds={wall_seconds!r} -- one clock, one duration")
        if _finite_nonneg(cpu_seconds) and _finite_pos(host_wall) and isinstance(frac, (int, float)) and not isinstance(frac, bool) and math.isfinite(frac):
            expected_frac = cpu_seconds / host_wall
            if abs(frac - expected_frac) > 0.01 * max(1e-9, expected_frac):
                defects.append(f"host_utilization.process_cpu_fraction={frac!r} inconsistent with its own process_cpu_seconds/wall_seconds={expected_frac:.6g}")
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
# DEGRADED_PROXY. Validates receipts produced by scripts/frontier_receipt.py.
# The constants below are INDEPENDENT transcriptions of the frozen spec
# sources (§5.1/§5.4, the physiology-addendum twelve-wall table) -- NOT
# imports from the generator, so a transcription error in either module
# surfaces as a refusal at first contact instead of validating itself.
# ---------------------------------------------------------------------------

FRONTIER_SCHEMA = "ember02-frontier-receipt/v1"
E5_GOAL_ID = "EMBER-02"
E5_WORKSTREAM_ID = "EMBER-02A"
E5_PREREG_PATH = "docs/spec/ember02-preregistration-v1.md"
E5_ADMISSION_CONFIG_PATH = "configs/ember-restart-3b.json"
E5_INVARIANT_PATH = "docs/authority/INVARIANT.md"
E5_TOKENIZER_RECEIPT_PATH = "receipts/ember-restart-3b/tokenizer-reconstruction-issue534-v1.json"
E5_RUN_ATTEMPTS_REGISTRY = "receipts/run-attempts.jsonl"
# Prereg line 27 t0: R1's predecessor is exactly the candidate's genesis
# receipt (the seed83 cost-calibration certificate -- it records the run that
# created the candidate and charges the already-seen 2,048 tokens). This
# battery only ever adjudicates R1, so the pin is closed: an unpinned
# predecessor admits any repo JSON file as the lineage anchor (rev-1490
# item 3 -- the E6 decoy lesson with a different field name).
E5_GENESIS_RECEIPT_PATH = "receipts/ember-restart-3b/native-cost-calibration-seed83-certificate.json"
# §5.1 class 1: each category must attest False -- a True value is a stopped
# program, not a receipt field ("fail-closed on unknown provenance").
E5_ATTESTATION_CATEGORIES = (
    "imported_learned_weights", "imported_embeddings", "learned_parameter_tokenizers",
    "teacher_outputs", "learned_filters_judges", "hidden_accelerator_services",
)
# §5.1 class 7, the ten quoted compute components.
E5_COMPUTE_COMPONENTS = (
    "training", "validation", "tools", "environments", "judging",
    "search", "retrieval", "rollouts", "test_time_reasoning", "final_evaluation",
)
# The twelve-bottleneck protocol table (physiology closed-boundary addendum),
# NOT the five-row B1-B5 bottleneck ledger -- different namespace.
E5_WALL_IDS = (
    "1-metric", "2-accounting", "3-theory-disclosure", "4-data",
    "5-objective-verifier", "6-transfer-persistence", "7-optimization",
    "8-architecture-capacity", "9-composition", "10-residency",
    "11-roofline-numerics", "12-seriality-iteration",
)
E5_WALL_VERDICTS = ("green", "red", "not_probed")
# The manifest keys identity_spine.checkpoint_file_sha256s may mirror.
E5_CHECKPOINT_HASH_KEYS = (
    "shared_model_shard_sha256", "expert_checkpoint_sha256",
    "optimizer_state_shard_sha256", "rng_state_sha256",
)


def _validate_frontier_content(
    path: Path, *, repo_root: Path, run_root: Path, thresholds: dict[str, Any],
    fixed_prior_manifest_path: Path | None, run_id: str | None = None,
) -> list[str]:
    """Return the list of content defects (empty = valid) for one candidate
    frontier receipt. Fail-closed: every check that cannot be performed is
    itself a defect. The three binding families the E6 reviews proved
    load-bearing all apply here:
      * document binding -- every repo-document pin (prereg, admission
        config, fixed-prior manifest, tokenizer receipt, predecessor,
        registry, docs/authority/INVARIANT.md) must name THE pinned path, resolve inside
        repo_root, and hash to the receipt's sha256;
      * value binding -- reproducibility pins must EQUAL the checkpoint
        manifest's values, embedded evidence (energy block, eval results,
        interventions, walls rows) must EQUAL the producer files on disk
        field-for-field, and arithmetic (energy totals, wall clock) must
        recompute from the receipt's own numbers;
      * run binding -- the receipt's run_root must resolve to the
        adjudicated root, every evidence sha must match the file found
        under THAT root, and steps_measured must EQUAL the deduped
        train_step series of the receipt's own run_id, re-selected here
        with the same _select_series the other exits adjudicate through
        (one run's receipt must not credit another's exit, and the
        headline step count is never accepted on the receipt's word --
        rev-1490 items 1+2)."""
    t01 = int(thresholds["T-01"])
    t06 = float(thresholds["T-06"])
    defects: list[str] = []
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return [f"unreadable or non-JSON: {error}"]
    if not isinstance(receipt, dict):
        return ["top level is not a JSON object"]

    def _num(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

    def _nonempty_str(value: Any) -> bool:
        return isinstance(value, str) and bool(value.strip())

    if receipt.get("schema_version") != FRONTIER_SCHEMA:
        defects.append(f"schema_version is {receipt.get('schema_version')!r}, need {FRONTIER_SCHEMA!r}")
    if receipt.get("rung") != "R1":
        defects.append(f"rung is {receipt.get('rung')!r}, need 'R1' (this battery adjudicates R1 exits)")
    if not _nonempty_str(receipt.get("generator")):
        defects.append("generator provenance field missing")
    if not _nonempty_str(receipt.get("generated_utc")):
        defects.append("generated_utc missing")

    receipt_run_root = receipt.get("run_root")
    if not _nonempty_str(receipt_run_root):
        defects.append("run_root binding field missing")
    else:
        try:
            if Path(receipt_run_root).resolve() != run_root.resolve():
                defects.append(
                    f"run_root mismatch: receipt was generated for {receipt_run_root!r}, adjudicating "
                    f"{str(run_root)!r} -- one run's frontier receipt must not credit another's exit"
                )
        except OSError as error:
            defects.append(f"run_root unresolvable: {error}")

    steps_measured = receipt.get("steps_measured")
    if not isinstance(steps_measured, int) or isinstance(steps_measured, bool) or steps_measured < t01:
        defects.append(f"steps_measured={steps_measured!r} below T-01={t01} -- a frontier point needs the measured baseline the prereg names")

    # Re-derive the headline step count from the root's own telemetry with
    # the SAME per-run selection E1/E2/E4 adjudicate through. The receipt's
    # run_id must name the selected run and steps_measured must equal the
    # deduped series length -- a claimed count with no series behind it, or
    # a count pooled across run_ids on a resumed root, never validates
    # (rev-1490 items 1+2: the one asserted-not-re-derived quantity).
    selected_run_id, series, series_counts = _select_series(run_root, run_id=run_id)
    receipt_run_id = receipt.get("run_id")
    if not _nonempty_str(receipt_run_id):
        defects.append("run_id binding field missing -- the receipt must name the telemetry run it describes")
    if not series:
        if selected_run_id is None and len(series_counts) > 1:
            defects.append(
                f"steps_measured cannot be re-derived: multiple telemetry run_ids under the run root "
                f"({series_counts!r}) and no --run-id selects one -- ambiguous adjudication is refused"
            )
        else:
            defects.append(
                f"steps_measured cannot be re-derived: no train_step telemetry for "
                f"run_id={run_id!r} under the run root (run_ids_seen={series_counts!r}) -- "
                "the headline quantity of a frontier point is never accepted on the receipt's own word"
            )
    else:
        if _nonempty_str(receipt_run_id) and receipt_run_id != selected_run_id:
            defects.append(
                f"run_id mismatch: receipt names {receipt_run_id!r}, the adjudicated series is "
                f"{selected_run_id!r} -- one run's frontier receipt must not credit another's telemetry"
            )
        if isinstance(steps_measured, int) and not isinstance(steps_measured, bool) and steps_measured != len(series):
            defects.append(
                f"steps_measured={steps_measured!r} does not equal the re-derived deduped series "
                f"length {len(series)} for run_id={selected_run_id!r}"
            )

    repo_resolved = repo_root.resolve()

    def _bind_repo_doc(label: str, entry: Any, expected_rel: str | None) -> Path | None:
        """Verify a {path, sha256} repo-document pin; return the resolved
        path on success, None (with defects appended) otherwise. When
        expected_rel is given the pin must name exactly that document --
        binding any other repo file is refused (the E6 decoy lesson)."""
        if not isinstance(entry, dict) or not _nonempty_str(entry.get("path")) or not _nonempty_str(entry.get("sha256")):
            defects.append(f"{label}: path/sha256 binding fields missing")
            return None
        rel = entry["path"]
        if Path(rel).is_absolute():
            defects.append(f"{label}: path is absolute ({rel!r}) -- the binding must be repo-relative")
            return None
        if expected_rel is not None and PurePath(rel).as_posix() != expected_rel:
            defects.append(f"{label}: path {rel!r} does not name the pinned document ({expected_rel})")
            return None
        abs_path = (repo_root / rel).resolve()
        if repo_resolved not in abs_path.parents and abs_path != repo_resolved:
            defects.append(f"{label}: path escapes the repository ({rel!r})")
            return None
        if not abs_path.is_file():
            defects.append(f"{label}: bound document does not exist on disk: {rel}")
            return None
        if _sha256_file(abs_path) != entry["sha256"]:
            defects.append(f"{label}: sha256 does not match the bytes of {rel} -- the receipt binds a different document than the one on disk")
            return None
        return abs_path

    _bind_repo_doc("prereg", receipt.get("prereg"), E5_PREREG_PATH)
    _bind_repo_doc("admission_config", receipt.get("admission_config"), E5_ADMISSION_CONFIG_PATH)
    # Pinned to THE R1 predecessor (this battery only adjudicates R1): an
    # unpinned predecessor accepted any repo JSON -- the admission config
    # doubling as its own lineage anchor validated (rev-1490 item 3).
    predecessor_path = _bind_repo_doc("predecessor_receipt", receipt.get("predecessor_receipt"), E5_GENESIS_RECEIPT_PATH)
    if predecessor_path is not None:
        try:
            json.loads(predecessor_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            defects.append(f"predecessor_receipt: bound document is not valid JSON: {error}")

    # --- leg 2: fixed prior + learned-import attestation ----------------------
    expected_manifest = (fixed_prior_manifest_path or (repo_root / FIXED_PRIOR_MANIFEST_REL)).resolve()
    try:
        expected_manifest_rel = expected_manifest.relative_to(repo_resolved).as_posix()
    except ValueError:
        expected_manifest_rel = str(expected_manifest)
    fixed_prior = receipt.get("fixed_prior")
    fixed_prior_sha: str | None = None
    if not isinstance(fixed_prior, dict) or not _nonempty_str(fixed_prior.get("manifest_path")) or not _nonempty_str(fixed_prior.get("manifest_sha256")):
        defects.append("fixed_prior: manifest_path/manifest_sha256 binding fields missing")
        fixed_prior = {}
    elif PurePath(fixed_prior["manifest_path"]).as_posix() != expected_manifest_rel:
        defects.append(
            f"fixed_prior.manifest_path {fixed_prior['manifest_path']!r} does not name the pinned "
            f"§5.2 manifest ({expected_manifest_rel})"
        )
    elif not expected_manifest.is_file():
        defects.append(f"fixed_prior: pinned manifest does not exist on disk: {expected_manifest}")
    elif _sha256_file(expected_manifest) != fixed_prior["manifest_sha256"]:
        defects.append("fixed_prior.manifest_sha256 does not match the manifest bytes on disk")
    else:
        fixed_prior_sha = fixed_prior["manifest_sha256"]
        # Independent re-validation of the manifest CONTENT the attestation
        # rests on (§5.1 class 1 is fail-closed on unknown provenance).
        try:
            manifest_doc = json.loads(expected_manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            defects.append(f"fixed_prior: manifest unreadable: {error}")
            manifest_doc = None
        if isinstance(manifest_doc, dict):
            if not _nonempty_str(manifest_doc.get("learned_import_attestation")):
                defects.append("fixed_prior: manifest carries no learned_import_attestation statement")
            items = manifest_doc.get("items")
            if not isinstance(items, list) or not items:
                defects.append("fixed_prior: manifest has no items")
            else:
                for i, item in enumerate(items):
                    if not isinstance(item, dict) or not item.get("provenance"):
                        defects.append(f"fixed_prior: manifest item {i} lacks a provenance line")
                        continue
                    kind = item.get("kind")
                    probe = item.get("probe") if isinstance(item.get("probe"), dict) else {}
                    pinned = (
                        (kind == "file" and bool(item.get("sha256")))
                        or (kind == "version" and probe.get("ok") is True and bool(probe.get("output")))
                        or (kind == "tree" and bool(item.get("combined_sha256")))
                        or (kind == "external")
                    )
                    if not pinned:
                        defects.append(f"fixed_prior: manifest item {i} (kind={kind!r}) carries no pin for its kind")
        elif manifest_doc is not None:
            defects.append("fixed_prior: manifest top level is not a JSON object")

    attestation = receipt.get("learned_import_attestation")
    if not isinstance(attestation, dict):
        defects.append("learned_import_attestation block missing")
    else:
        for category in E5_ATTESTATION_CATEGORIES:
            if attestation.get(category) is not False:
                defects.append(
                    f"learned_import_attestation.{category} is {attestation.get(category)!r}, need "
                    "False -- a true or absent value is a stopped program, not a receipt field"
                )
        if not _nonempty_str(attestation.get("basis")):
            defects.append("learned_import_attestation.basis missing")

    # --- run-root evidence: checkpoint manifest (identity spine) --------------
    manifest_path: Path | None = None
    disk_manifest: dict[str, Any] | None = None
    disk_manifest_sha: str | None = None
    try:
        manifest_path = find_checkpoint_manifest(run_root)
        disk_manifest_sha = _sha256_file(manifest_path)
        loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            disk_manifest = loaded
        else:
            defects.append(f"checkpoint manifest top level is not a JSON object: {manifest_path}")
    except R1ExitBatteryRefusal as refusal:
        defects.append(f"checkpoint manifest: {refusal}")
    except (OSError, ValueError) as error:
        defects.append(f"checkpoint manifest unreadable: {error}")

    spine = receipt.get("identity_spine")
    if not isinstance(spine, dict):
        defects.append("identity_spine block missing")
        spine = {}
    else:
        if spine.get("goal_id") != E5_GOAL_ID:
            defects.append(f"identity_spine.goal_id is {spine.get('goal_id')!r}, need {E5_GOAL_ID!r}")
        if spine.get("workstream_id") != E5_WORKSTREAM_ID:
            defects.append(f"identity_spine.workstream_id is {spine.get('workstream_id')!r}, need {E5_WORKSTREAM_ID!r}")
        if not _nonempty_str(spine.get("next_executed_outcome")):
            defects.append("identity_spine.next_executed_outcome missing")
        spine_manifest_sha = spine.get("checkpoint_manifest_sha256")
        if not _nonempty_str(spine_manifest_sha):
            defects.append("identity_spine.checkpoint_manifest_sha256 missing")
        elif disk_manifest_sha is not None and spine_manifest_sha != disk_manifest_sha:
            defects.append(
                "identity_spine.checkpoint_manifest_sha256 does not match this run root's checkpoint "
                "manifest bytes -- the receipt describes a different checkpoint"
            )
        file_shas = spine.get("checkpoint_file_sha256s")
        if not isinstance(file_shas, dict) or not file_shas:
            defects.append("identity_spine.checkpoint_file_sha256s missing or empty")
        elif disk_manifest is not None:
            for key, value in file_shas.items():
                if key not in E5_CHECKPOINT_HASH_KEYS:
                    defects.append(f"identity_spine.checkpoint_file_sha256s carries unknown key {key!r}")
                elif disk_manifest.get(key) != value:
                    defects.append(f"identity_spine.checkpoint_file_sha256s[{key!r}] does not equal the checkpoint manifest's value")

    def _bind_run_file(label: str, rel_name: str, expected_sha: Any) -> tuple[Path, Any] | None:
        """Discover exactly one rel_name under the run root (quarantine and
        preserved attempt-*/ dirs excluded -- a retained failed attempt's
        receipts are history, not this run's evidence; rev-1490 item 6),
        require the receipt's sha to match its bytes, and return
        (path, parsed JSON). None (with defects appended) otherwise."""
        candidates = sorted(p for p in run_root.rglob(rel_name) if not _evidence_excluded(p, run_root)) if run_root.is_dir() else []
        if not candidates:
            defects.append(f"{label}: no {rel_name} under the run root")
            return None
        if len(candidates) > 1:
            defects.append(f"{label}: {len(candidates)} {rel_name} files under the run root -- ambiguous evidence")
            return None
        disk_path = candidates[0]
        if not _nonempty_str(expected_sha):
            defects.append(f"{label}: receipt carries no sha256 for {rel_name}")
            return None
        if _sha256_file(disk_path) != expected_sha:
            defects.append(f"{label}: receipt sha256 does not match the bytes of {disk_path} -- the receipt binds different evidence than this run root holds")
            return None
        try:
            return disk_path, json.loads(disk_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            defects.append(f"{label}: {disk_path} unreadable: {error}")
            return None

    # --- leg 3: capability ----------------------------------------------------
    capability = receipt.get("capability")
    if not isinstance(capability, dict):
        defects.append("capability leg missing")
    else:
        bound = _bind_run_file("capability", "frozen-eval-results.json", capability.get("results_receipt_sha256"))
        if bound is not None:
            _eval_path, eval_doc = bound
            # The named path must BE the discovered file, not merely share
            # its sha -- an unbound path field is decorative (rev-1490 nb-4).
            named_eval = capability.get("results_receipt_path")
            try:
                named_eval_ok = _nonempty_str(named_eval) and Path(named_eval).resolve() == _eval_path.resolve()
            except OSError:
                named_eval_ok = False
            if not named_eval_ok:
                defects.append(f"capability.results_receipt_path {named_eval!r} does not name the discovered frozen-eval receipt {_eval_path}")
            if not isinstance(eval_doc, dict):
                defects.append("capability: frozen-eval-results.json top level is not a JSON object")
            else:
                defects.extend(
                    _validate_frozen_eval_suite_binding(run_root, capability, eval_doc)
                )
                try:
                    suite_candidates = sorted(
                        candidate
                        for candidate in run_root.rglob("frozen-eval-suite.json")
                        if not _evidence_excluded(candidate, run_root)
                    )
                    if len(suite_candidates) != 1 or manifest_path is None:
                        raise frozen_eval.FrozenEvalRefusal(
                            "RESULT_RECEIPT_EVIDENCE_UNBOUND"
                        )
                    suite_sha = _sha256_file(suite_candidates[0])
                    _suite_raw, suite = frozen_eval._load_suite(
                        suite_candidates[0], suite_sha
                    )
                    manifest_sha, checkpoint_hashes = frozen_eval._checkpoint_identity(
                        manifest_path.parent
                    )
                    frozen_eval.validate_results_receipt(
                        eval_doc,
                        suite=suite,
                        suite_sha256=suite_sha,
                        checkpoint_manifest_sha256=manifest_sha,
                        checkpoint_file_sha256s=checkpoint_hashes,
                    )
                    if capability.get("checkpoint_file_sha256s") != checkpoint_hashes:
                        defects.append(
                            "capability.checkpoint_file_sha256s does not equal all independently rehashed checkpoint shards"
                        )
                except frozen_eval.FrozenEvalRefusal as error:
                    defects.append(f"capability: {error}")
                for field_name in ("eval_suite_id", "eval_suite_sha256"):
                    if eval_doc.get(field_name) != capability.get(field_name) or not _nonempty_str(capability.get(field_name)):
                        defects.append(f"capability.{field_name} does not equal the frozen-eval receipt's value")
                if eval_doc.get("tool_access") != "none" or capability.get("tool_access") != "none":
                    defects.append(
                        f"capability.tool_access is {capability.get('tool_access')!r} (producer: "
                        f"{eval_doc.get('tool_access')!r}), need 'none' at R1 -- no harness/tool substitution"
                    )
                results = capability.get("results")
                if not isinstance(results, dict) or not results:
                    defects.append("capability.results is not a non-empty mapping")
                else:
                    if results != eval_doc.get("results"):
                        defects.append("capability.results does not equal the frozen-eval receipt's results verbatim")
                    for metric, entry in results.items():
                        if not isinstance(entry, dict) or not _num(entry.get("value")):
                            defects.append(f"capability.results[{metric!r}] lacks a finite value -- no missing result is converted into completion")
                eval_manifest_sha = eval_doc.get("checkpoint_manifest_sha256")
                if disk_manifest_sha is not None and eval_manifest_sha != disk_manifest_sha:
                    defects.append("capability: frozen-eval receipt binds a different checkpoint manifest than this run root's -- one run's eval must not credit another's checkpoint")
        if disk_manifest_sha is not None and capability.get("checkpoint_manifest_sha256") != disk_manifest_sha:
            defects.append("capability.checkpoint_manifest_sha256 does not match this run root's checkpoint manifest bytes")
        if capability.get("model_only_ablation") is not None:
            defects.append("capability.model_only_ablation must be null at R1 (no claim exists for the ablation to probe)")

    # --- leg 4: time ----------------------------------------------------------
    time_leg = receipt.get("time")
    if not isinstance(time_leg, dict):
        defects.append("time leg missing")
    else:
        bound = _bind_run_file("time", "disk-budget-runner-receipt.json", time_leg.get("runner_receipt_sha256"))
        if bound is not None:
            _runner_path, runner_doc = bound
            source = time_leg.get("source")
            if not _nonempty_str(source) or _runner_path.name not in source:
                defects.append(f"time.source {source!r} does not name the discovered runner receipt ({_runner_path.name}) -- an unbound provenance field is decorative")
            # The REAL producer contract: float unix SECONDS in
            # started_at_unix/finished_at_unix (schema_version-7 disk-budget
            # runner receipt, read from the canary root 2026-08-06). The
            # first transcription checked *_ms fields no producer writes.
            started = runner_doc.get("started_at_unix") if isinstance(runner_doc, dict) else None
            finished = runner_doc.get("finished_at_unix") if isinstance(runner_doc, dict) else None
            if not (_num(started) and _num(finished)):
                defects.append("time: runner receipt lacks finite started_at_unix/finished_at_unix")
            elif finished < started:
                defects.append("time: runner receipt finished_at_unix precedes started_at_unix")
            else:
                wall = time_leg.get("wall_clock_seconds")
                expected_wall = finished - started
                if not _num(wall) or abs(wall - expected_wall) > 1e-6:
                    defects.append(f"time.wall_clock_seconds {wall!r} does not equal the runner receipt's span {expected_wall}")

                def _iso(unix_s: float) -> str:
                    return datetime.fromtimestamp(unix_s, tz=timezone.utc).isoformat().replace("+00:00", "Z")

                if time_leg.get("run_start_utc") != _iso(started) or time_leg.get("run_end_utc") != _iso(finished):
                    defects.append("time.run_start_utc/run_end_utc do not re-derive from the runner receipt's unix-seconds fields")
        if time_leg.get("coverage") != "process_birth_to_exit":
            defects.append(f"time.coverage is {time_leg.get('coverage')!r}, need 'process_birth_to_exit'")

    # --- leg 5: energy (§5.3 block re-checked AND compared with producer) -----
    energy_block = receipt.get("energy")
    if not isinstance(energy_block, dict):
        defects.append("energy leg missing (§5.3 block)")
    else:
        boundary = energy_block.get("energy_boundary")
        if boundary != "DEGRADED_PROXY":
            defects.append(f"energy.energy_boundary is {boundary!r}, need 'DEGRADED_PROXY' (prereg: the boundary is permanent)")
        coverage = energy_block.get("sample_coverage_fraction")
        if not _num(coverage) or not (0.0 <= coverage <= 1.0):
            defects.append(f"energy.sample_coverage_fraction {coverage!r} is not in [0,1]")
        elif coverage < t06:
            defects.append(f"energy.sample_coverage_fraction {coverage} below T-06={t06} -- an unmetered run is not a frontier point")
        gpu_j = energy_block.get("gpu_joules")
        cpu_j = energy_block.get("cpu_pkg_joules")
        total_j = energy_block.get("total_proxy_joules")
        if not _num(gpu_j) or not _num(total_j):
            defects.append("energy.gpu_joules/total_proxy_joules not finite")
        else:
            if gpu_j < 0 or total_j < 0:
                defects.append(f"energy joules negative (gpu={gpu_j!r}, total={total_j!r}) -- integrated energy cannot be below zero")
            expected_total = gpu_j + (cpu_j if _num(cpu_j) else 0.0)
            if abs(total_j - expected_total) > 1e-9 * max(1.0, abs(expected_total)):
                defects.append(f"energy.total_proxy_joules {total_j} does not equal gpu + cpu legs {expected_total}")
        if _num(cpu_j) and cpu_j < 0:
            defects.append(f"energy.cpu_pkg_joules negative ({cpu_j!r})")
        if not _num(cpu_j):
            # `is None` alone let a STRING-typed cpu leg drop from the total
            # silently with no disclosure (rev-1490 non-blocking 2): any
            # non-numeric cpu leg must be disclosed as excluded.
            excluded = energy_block.get("excluded_components")
            if not isinstance(excluded, list) or not any(isinstance(e, str) and e.lower().startswith("cpu package") for e in excluded):
                defects.append(f"energy.cpu_pkg_joules is not a finite number ({cpu_j!r}) but 'CPU package' is not disclosed in excluded_components")
        # The producer receipt gets the same discovery discipline as every
        # other evidence file: exactly one under the root, quarantine and
        # attempt-*/ excluded, sha-bound -- a receipt naming a second or
        # quarantined producer while a contradicting one sits on disk never
        # validates (rev-1490 item 5).
        bound = _bind_run_file("energy", "*energy-proxy*.json", receipt.get("energy_receipt_sha256"))
        if bound is not None:
            producer_path, producer_doc = bound
            named_energy = receipt.get("energy_receipt_path")
            try:
                named_energy_ok = _nonempty_str(named_energy) and Path(named_energy).resolve() == producer_path.resolve()
            except OSError:
                named_energy_ok = False
            if not named_energy_ok:
                defects.append(f"energy_receipt_path {named_energy!r} does not name the discovered producer receipt {producer_path}")
            if isinstance(producer_doc, dict) and producer_doc.get("energy") != energy_block:
                defects.append("energy block does not equal the producer receipt's nested energy block verbatim -- the §5.3 embed contract")

    # --- leg 6: reproducibility (value-bound to the checkpoint manifest) ------
    repro = receipt.get("reproducibility")
    if not isinstance(repro, dict):
        defects.append("reproducibility leg missing")
    else:
        if disk_manifest is not None:
            for field_name, manifest_key in (
                ("config_sha256", "model_config_sha256"),
                ("optimizer_state_sha256", "optimizer_state_shard_sha256"),
                ("rng_state_sha256", "rng_state_sha256"),
            ):
                # Present-and-EQUAL, deliberately type-agnostic: v5 manifests
                # pin optimizer/shared/expert shards as per-shard MAPPINGS,
                # not single hex strings (cross-check finding: a string-typed
                # requirement here refused every real generator receipt).
                if not repro.get(field_name) or repro.get(field_name) != disk_manifest.get(manifest_key):
                    defects.append(f"reproducibility.{field_name} does not equal the checkpoint manifest's {manifest_key}")
            if not repro.get("optimizer_contract") or repro.get("optimizer_contract") != disk_manifest.get("optimizer_contract"):
                defects.append("reproducibility.optimizer_contract does not equal the checkpoint manifest's optimizer_contract")
            manifest_seed = disk_manifest.get("launch_seed")
            seeds = repro.get("seeds")
            if not isinstance(seeds, list) or not seeds or not all(isinstance(s, int) and not isinstance(s, bool) for s in seeds):
                defects.append("reproducibility.seeds is not a non-empty list of integers")
            elif seeds != [manifest_seed]:
                defects.append(f"reproducibility.seeds {seeds!r} does not equal the checkpoint manifest's launch_seed [{manifest_seed!r}]")
            cursor = repro.get("data_cursor")
            manifest_cursor = disk_manifest.get("data_cursor") if isinstance(disk_manifest.get("data_cursor"), dict) else {}
            if not isinstance(cursor, dict) or not _num(cursor.get("tokens_seen")) or not _num(cursor.get("global_step")):
                defects.append("reproducibility.data_cursor incomplete (finite tokens_seen/global_step required)")
            elif (cursor.get("tokens_seen") != manifest_cursor.get("tokens_seen")
                  or cursor.get("global_step") != manifest_cursor.get("global_step")):
                defects.append("reproducibility.data_cursor does not equal the checkpoint manifest's data_cursor")
        _bind_repo_doc("reproducibility.tokenizer_reconstruction_receipt", repro.get("tokenizer_reconstruction_receipt"), E5_TOKENIZER_RECEIPT_PATH)
        if fixed_prior_sha is not None and repro.get("recipe_ref") != fixed_prior_sha:
            defects.append("reproducibility.recipe_ref does not equal the fixed-prior manifest sha256 -- the recipe binding is the §5.2 manifest")
        reproduction = repro.get("reproduction")
        if not isinstance(reproduction, dict):
            defects.append("reproducibility.reproduction adjudication block missing")
        else:
            adjudication_disk = run_root / "reproduction-adjudication.json"
            status = reproduction.get("status")
            if status not in ("REPRODUCED", "MISMATCH"):
                defects.append(f"reproduction.status {status!r} is neither REPRODUCED nor MISMATCH -- '(reproduces or names its mismatch)' admits nothing else")
            if status == "MISMATCH" and not reproduction.get("mismatch"):
                defects.append("reproduction: MISMATCH status without a named mismatch")
            if not _nonempty_str(reproduction.get("evidence_ref")):
                defects.append("reproduction.evidence_ref missing")
            if not adjudication_disk.is_file():
                defects.append("reproduction: no reproduction-adjudication.json under the run root")
            elif not _nonempty_str(reproduction.get("adjudication_sha256")) or _sha256_file(adjudication_disk) != reproduction.get("adjudication_sha256"):
                defects.append("reproduction.adjudication_sha256 does not match reproduction-adjudication.json bytes")
            else:
                try:
                    adjudication_doc = json.loads(adjudication_disk.read_text(encoding="utf-8"))
                except (OSError, ValueError) as error:
                    adjudication_doc = None
                    defects.append(f"reproduction adjudication unreadable: {error}")
                if isinstance(adjudication_doc, dict) and adjudication_doc.get("status") != status:
                    defects.append("reproduction.status does not equal the adjudication file's status")

    # --- leg 1: the nine-class ledger -----------------------------------------
    ledger = receipt.get("ledger")
    if not isinstance(ledger, dict):
        defects.append("ledger block missing (§5.1)")
    else:
        for ref_field in ("learned_import_attestation_ref", "energy_ref", "identity_spine_ref"):
            if not _nonempty_str(ledger.get(ref_field)):
                defects.append(f"ledger.{ref_field} missing")
        if isinstance(fixed_prior, dict) and fixed_prior.get("manifest_path") and ledger.get("fixed_prior_manifest_ref") != fixed_prior.get("manifest_path"):
            defects.append("ledger.fixed_prior_manifest_ref does not name the bound fixed-prior manifest")

        interventions = ledger.get("human_interventions")
        if not isinstance(interventions, dict):
            defects.append("ledger.human_interventions missing")
        else:
            interventions_disk = run_root / "human-interventions.json"
            if not interventions_disk.is_file():
                defects.append("ledger.human_interventions: no human-interventions.json under the run root -- an explicit empty list is evidence, an absent file is not a zero")
            elif not _nonempty_str(interventions.get("source_sha256")) or _sha256_file(interventions_disk) != interventions.get("source_sha256"):
                defects.append("ledger.human_interventions.source_sha256 does not match human-interventions.json bytes")
            else:
                try:
                    disk_rows = json.loads(interventions_disk.read_text(encoding="utf-8"))
                except (OSError, ValueError) as error:
                    disk_rows = None
                    defects.append(f"ledger.human_interventions: source file unreadable: {error}")
                rows = interventions.get("interventions")
                if disk_rows is not None and rows != disk_rows:
                    defects.append("ledger.human_interventions.interventions does not equal the source file's rows verbatim")
                if isinstance(rows, list):
                    for i, row in enumerate(rows):
                        if not isinstance(row, dict) or not all(row.get(k) for k in ("action_class", "actor_role", "ts_utc", "description")):
                            defects.append(f"ledger.human_interventions row {i} lacks action_class/actor_role/ts_utc/description")
                else:
                    defects.append("ledger.human_interventions.interventions is not a list")

        data_accounting = ledger.get("data_accounting")
        if not isinstance(data_accounting, dict):
            defects.append("ledger.data_accounting missing")
        else:
            if disk_manifest is not None:
                manifest_cursor = disk_manifest.get("data_cursor") if isinstance(disk_manifest.get("data_cursor"), dict) else {}
                if not _num(data_accounting.get("tokens_seen")) or data_accounting.get("tokens_seen") != manifest_cursor.get("tokens_seen"):
                    defects.append("ledger.data_accounting.tokens_seen does not equal the checkpoint manifest's data_cursor.tokens_seen")
            if not _nonempty_str(data_accounting.get("attestation")):
                defects.append("ledger.data_accounting.attestation missing")
            if data_accounting.get("retained_originals") is not True:
                defects.append("ledger.data_accounting.retained_originals must be true")
            if isinstance(fixed_prior, dict) and fixed_prior.get("manifest_path") and data_accounting.get("corpora_evidence_ref") != fixed_prior.get("manifest_path"):
                defects.append("ledger.data_accounting.corpora_evidence_ref does not name the fixed-prior manifest")

        host = ledger.get("host_accounting")
        if not isinstance(host, dict):
            defects.append("ledger.host_accounting missing")
        else:
            not_measured = host.get("not_measured")
            if not isinstance(not_measured, dict) or not all(_nonempty_str(v) for v in not_measured.values()):
                defects.append("ledger.host_accounting.not_measured must map each unmeasured field to a named reason (§5.1 class 4: an absent measurement without a reason is a hole, not a disclosure)")
            evidence_ref = host.get("evidence_ref")
            if _nonempty_str(evidence_ref):
                if not Path(evidence_ref).is_file():
                    defects.append(f"ledger.host_accounting.evidence_ref does not exist: {evidence_ref}")
            elif isinstance(not_measured, dict) and "cpu_gpu_utilization" not in not_measured:
                defects.append("ledger.host_accounting carries neither an evidence_ref (R1-E4 receipt) nor a not_measured reason for cpu_gpu_utilization")

        coverage_block = ledger.get("all_compute_coverage")
        if not isinstance(coverage_block, dict):
            defects.append("ledger.all_compute_coverage missing")
        else:
            registry_disk = repo_root / E5_RUN_ATTEMPTS_REGISTRY
            if coverage_block.get("registry_path") != E5_RUN_ATTEMPTS_REGISTRY:
                defects.append(f"ledger.all_compute_coverage.registry_path does not name {E5_RUN_ATTEMPTS_REGISTRY}")
            if not registry_disk.is_file():
                defects.append(f"ledger.all_compute_coverage: no run-attempt registry at {E5_RUN_ATTEMPTS_REGISTRY} -- 'failed work included' is unattestable without it (issue #1497)")
            else:
                declared_rows = coverage_block.get("registry_rows")
                if not isinstance(declared_rows, int) or isinstance(declared_rows, bool) or declared_rows < 1:
                    defects.append("ledger.all_compute_coverage.registry_rows must be a positive integer")
                    declared_rows = 0
                try:
                    line_entries, registry_prefix = _registry_rows_and_prefix(registry_disk, declared_rows)
                except (OSError, UnicodeDecodeError) as error:
                    line_entries, registry_prefix = [], b""
                    defects.append(f"ledger.all_compute_coverage: registry unreadable: {error}")
                bound_entries = line_entries[:declared_rows]
                if len(bound_entries) != declared_rows:
                    defects.append(
                        f"ledger.all_compute_coverage.registry_rows {coverage_block.get('registry_rows')!r} "
                        f"cannot be re-read from the registry prefix (found {len(bound_entries)} rows)"
                    )
                has_prefix_sha = "registry_prefix_sha256" in coverage_block
                has_legacy_sha = "registry_sha256" in coverage_block
                prefix_sha = coverage_block.get("registry_prefix_sha256")
                legacy_sha = coverage_block.get("registry_sha256")
                if has_prefix_sha and has_legacy_sha:
                    defects.append(
                        "ledger.all_compute_coverage must not mix registry_prefix_sha256 "
                        "with legacy registry_sha256"
                    )
                elif has_prefix_sha:
                    if not _nonempty_str(prefix_sha) or _sha256_bytes(registry_prefix) != prefix_sha:
                        defects.append("ledger.all_compute_coverage.registry prefix sha256 does not match the bound rows on disk")
                elif has_legacy_sha:
                    if not _nonempty_str(legacy_sha) or _sha256_file(registry_disk) != legacy_sha:
                        defects.append("ledger.all_compute_coverage.registry_sha256 does not match the registry bytes on disk")
                    if len(line_entries) != declared_rows:
                        defects.append(
                            f"legacy ledger.all_compute_coverage.registry_rows {coverage_block.get('registry_rows')!r} "
                            f"does not equal the registry's {len(line_entries)} rows"
                        )
                else:
                    defects.append(
                        "ledger.all_compute_coverage requires registry_prefix_sha256 "
                        "or legacy registry_sha256"
                    )
                lines = [line for _, line in bound_entries]
                parse_failures = []
                non_object_rows = []
                all_rows = []
                for line_number, line in line_entries:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        parse_failures.append(line_number)
                        continue
                    if not isinstance(row, dict):
                        non_object_rows.append(line_number)
                        continue
                    all_rows.append(row)
                if parse_failures:
                    defects.append(f"ledger.all_compute_coverage: registry lines unparseable: {parse_failures}")
                if non_object_rows:
                    defects.append(
                        f"ledger.all_compute_coverage: registry lines are not JSON objects: {non_object_rows} "
                        "-- a scalar line is not an attempt record (rev-1490 item 4)"
                    )
                if not lines:
                    defects.append("ledger.all_compute_coverage: run-attempt registry is empty")
                if (
                    all_rows
                    and not parse_failures
                    and not non_object_rows
                    and _nonempty_str(selected_run_id)
                ):
                    completion_defects = validate_run_attempt_completion(
                        all_rows,
                        selected_run_id=selected_run_id,
                        run_root=run_root,
                        bound_row_count=declared_rows,
                    )
                    defects.extend(
                        f"ledger.all_compute_coverage: {defect}"
                        for defect in completion_defects
                    )
            if coverage_block.get("failed_work_included") is not True:
                defects.append("ledger.all_compute_coverage.failed_work_included must be true")
            components_map = coverage_block.get("components")
            if not isinstance(components_map, dict):
                defects.append("ledger.all_compute_coverage.components missing")
            else:
                for component in E5_COMPUTE_COMPONENTS:
                    entry = components_map.get(component)
                    if not isinstance(entry, dict) or not isinstance(entry.get("included"), bool):
                        defects.append(f"ledger.all_compute_coverage.components[{component!r}] missing or lacks an included bool")
                    elif entry["included"] and not _nonempty_str(entry.get("evidence_ref")):
                        defects.append(f"ledger.all_compute_coverage.components[{component!r}] included without an evidence_ref")
                    elif not entry["included"] and not _nonempty_str(entry.get("note")):
                        defects.append(f"ledger.all_compute_coverage.components[{component!r}] excluded without a note naming why")

        walls = ledger.get("walls_checklist")
        if not isinstance(walls, dict):
            defects.append("ledger.walls_checklist missing")
        else:
            walls_disk = run_root / "walls-checklist.json"
            rows = walls.get("rows")
            if not walls_disk.is_file():
                defects.append("ledger.walls_checklist: no walls-checklist.json under the run root")
            elif not _nonempty_str(walls.get("source_sha256")) or _sha256_file(walls_disk) != walls.get("source_sha256"):
                defects.append("ledger.walls_checklist.source_sha256 does not match walls-checklist.json bytes")
            else:
                try:
                    disk_rows = json.loads(walls_disk.read_text(encoding="utf-8"))
                except (OSError, ValueError) as error:
                    disk_rows = None
                    defects.append(f"ledger.walls_checklist: source file unreadable: {error}")
                if disk_rows is not None and rows != disk_rows:
                    defects.append("ledger.walls_checklist.rows does not equal walls-checklist.json verbatim")
            if not isinstance(rows, list) or len(rows) != 12:
                defects.append(f"ledger.walls_checklist.rows must be exactly the twelve protocol rows, found {len(rows) if isinstance(rows, list) else type(rows).__name__}")
            else:
                seen_ids = []
                for row in rows:
                    wall_id, verdict = (row.get("wall_id"), row.get("verdict")) if isinstance(row, dict) else (None, None)
                    if wall_id not in E5_WALL_IDS:
                        defects.append(f"ledger.walls_checklist: unknown wall_id {wall_id!r}")
                    if verdict not in E5_WALL_VERDICTS:
                        defects.append(f"ledger.walls_checklist: wall {wall_id!r} verdict {verdict!r} not in {E5_WALL_VERDICTS}")
                    seen_ids.append(wall_id)
                if sorted(str(s) for s in seen_ids) != sorted(E5_WALL_IDS):
                    defects.append("ledger.walls_checklist: rows do not cover the twelve wall ids exactly once")

    # --- advantage + invariant stamps -----------------------------------------
    if receipt.get("advantage_claims") != []:
        defects.append(
            f"advantage_claims is {receipt.get('advantage_claims')!r}, need [] -- §4.4 freezes R1's "
            "receipted comparison at 'None (canary + measurement baselines)'"
        )
    stamp = receipt.get("invariant_stamp")
    invariant_disk = repo_root / E5_INVARIANT_PATH
    if not isinstance(stamp, dict) or not _nonempty_str(stamp.get("invariant_md_sha256")):
        defects.append("invariant_stamp.invariant_md_sha256 missing")
    elif not invariant_disk.is_file():
        defects.append(f"invariant stamp: no {E5_INVARIANT_PATH} at the repository root")
    elif _sha256_file(invariant_disk) != stamp.get("invariant_md_sha256"):
        defects.append(
            "invariant_stamp.invariant_md_sha256 does not match the docs/authority/INVARIANT.md in force -- a "
            "receipt stamped under a different invariant is not this rung's receipt"
        )
    return defects


def check_r1_e5(run_root: Path, thresholds: dict[str, Any], *, repo_root: Path = REPO_ROOT, fixed_prior_manifest_path: Path | None = None, run_id: str | None = None) -> dict[str, Any]:
    layout_spec_path = _layout_spec_path()
    t01 = int(thresholds["T-01"])
    t06 = float(thresholds["T-06"])
    manifest_cfg = fixed_prior_manifest_path or (repo_root / FIXED_PRIOR_MANIFEST_REL)
    fixed_prior_present = manifest_cfg.is_file()
    frontier_receipt_candidates = sorted(
        p for p in (run_root.rglob("*frontier*receipt*.json") if run_root.is_dir() else [])
        if not _evidence_excluded(p, run_root)
    )
    # Placement-invariant disclosure (rev-1490 round-3): quarantined .jsonl
    # holding real train_step rows never blocks E5, but it is surfaced --
    # nothing legitimate writes telemetry there.
    quarantined_telemetry = [str(p) for p in find_quarantined_telemetry_files(run_root)]
    needs = (
        f"a §5.4-validated closed-boundary frontier receipt (all 8 legs; energy_boundary "
        f"'DEGRADED_PROXY'; sample_coverage_fraction >= T-06={t06}) from a real >= T-01={t01}-step "
        "canary with energy-proxy sampling; generate it with scripts/frontier_receipt.py "
        "--run-root <this root> (it refuses, with the leg named, until every leg's evidence exists)"
    )
    if not frontier_receipt_candidates:
        return {
            "status": "EVIDENCE_MISSING",
            "frontier_receipt_validation": "IMPLEMENTED",
            "detail": (
                "no frontier-receipt-shaped file under this run root; generate one with "
                "scripts/frontier_receipt.py --run-root <this root>"
            ),
            "components": {
                "layout_spec": RUN_ROOT_LAYOUT_SPEC,
                "layout_spec_sha256": _sha256_file(layout_spec_path),
                "fixed_prior_manifest_present": fixed_prior_present,
                "fixed_prior_manifest_path": str(manifest_cfg),
                "fixed_prior_manifest_sha256": _sha256_file(manifest_cfg) if fixed_prior_present else None,
                "candidate_validation": [],
                "quarantined_telemetry_files": quarantined_telemetry,
            },
            "needs": needs,
        }
    validations = [
        {
            "path": str(p),
            "defects": _validate_frontier_content(
                p, repo_root=repo_root, run_root=run_root, thresholds=thresholds,
                fixed_prior_manifest_path=fixed_prior_manifest_path, run_id=run_id,
            ),
        }
        for p in frontier_receipt_candidates
    ]
    valid = [v for v in validations if not v["defects"]]
    components: dict[str, Any] = {
        "layout_spec": RUN_ROOT_LAYOUT_SPEC,
        "layout_spec_sha256": _sha256_file(layout_spec_path),
        "candidate_validation": validations,
        "quarantined_telemetry_files": quarantined_telemetry,
    }
    if len(validations) == 1 and len(valid) == 1:
        receipt_path = Path(valid[0]["path"])
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        components.update({
            "receipt_path": str(receipt_path),
            "receipt_sha256": _sha256_file(receipt_path),
            "run_id": receipt.get("run_id"),
            "steps_measured": receipt.get("steps_measured"),
            "wall_clock_seconds": _json_safe_number(receipt.get("time", {}).get("wall_clock_seconds")),
            "energy_boundary": receipt.get("energy", {}).get("energy_boundary"),
            "sample_coverage_fraction": _json_safe_number(receipt.get("energy", {}).get("sample_coverage_fraction")),
            "total_proxy_joules": _json_safe_number(receipt.get("energy", {}).get("total_proxy_joules")),
        })
        return {
            "status": "MET",
            "frontier_receipt_validation": "IMPLEMENTED",
            "detail": f"validated §5.4 frontier receipt (all legs re-verified against disk): {receipt_path}",
            "components": components,
        }
    return {
        "status": "NOT_MET",
        "frontier_receipt_validation": "IMPLEMENTED",
        "detail": (
            f"{len(validations)} frontier-receipt candidate(s), {len(valid)} content-valid: "
            + ("ambiguous -- more than one file claims to be the frontier receipt" if len(validations) > 1 else
               "; ".join(f"{v['path']}: {'; '.join(v['defects'][:8])}" for v in validations if v["defects"]))
        ),
        "components": components,
        "needs": needs,
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
E6_FORECAST_PATHS = {
    "R1": E6_FORECAST_PATH,
    "R2": "docs/spec/ember02-r2-forecast-v1.json",
}
E6_SCALAR_QUANTITIES = ("step_time_ms", "tokens_per_second", "proxy_joules_per_token", "peak_vram_gib")


def canonical_e6_forecast_path(rung: str) -> str:
    if not isinstance(rung, str) or rung not in E6_FORECAST_PATHS:
        raise R1ExitBatteryRefusal(
            f"UNKNOWN_RUNG: {rung!r}; known E6 forecast rungs are {sorted(E6_FORECAST_PATHS)}"
        )
    paths = tuple(E6_FORECAST_PATHS.values())
    if len(paths) != len(set(paths)):
        raise R1ExitBatteryRefusal("DUPLICATE_FORECAST_PATH: canonical E6 rung mapping is not one-to-one")
    return E6_FORECAST_PATHS[rung]


def _validate_recalibration_content(
    path: Path, *, repo_root: Path, run_root: Path, t01: int,
    run_id: str | None = None, rung: str = "R1",
) -> list[str]:
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

    receipt_rung = receipt.get("rung", "R1")
    try:
        canonical_forecast_path = canonical_e6_forecast_path(rung)
    except R1ExitBatteryRefusal as error:
        defects.append(str(error))
        canonical_forecast_path = None
    if receipt_rung != rung:
        defects.append(f"rung mismatch: receipt names {receipt_rung!r}, adjudicating {rung!r}")

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

    receipt_run_id = receipt.get("run_id")
    if not isinstance(receipt_run_id, str) or not receipt_run_id.strip():
        defects.append("run_id binding field missing -- the receipt must name the telemetry run it describes")
    # The receipt's run_id is the authoritative selector for E6: a root may
    # contain several valid runs, and the receipt must identify which one its
    # measured values describe.  A caller-supplied selector remains an
    # optional cross-check only; it may never silently select a different run.
    selection_run_id = run_id
    if isinstance(receipt_run_id, str) and receipt_run_id.strip():
        if run_id is not None and run_id != receipt_run_id:
            defects.append(
                f"run_id selector mismatch: caller selected {run_id!r}, receipt names {receipt_run_id!r}"
            )
        selection_run_id = receipt_run_id
    try:
        selected_run_id, series, series_counts = _select_series(
            run_root, run_id=selection_run_id
        )
    except R1ExitBatteryRefusal as error:
        defects.append(str(error))
        selected_run_id, series, series_counts = selection_run_id, [], {}
    telemetry_sha = receipt.get("telemetry_sha256")
    if not isinstance(telemetry_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", telemetry_sha):
        defects.append("telemetry_sha256 binding field missing or malformed")
    else:
        try:
            telemetry_paths = find_telemetry_files(run_root)
        except R1ExitBatteryRefusal as error:
            defects.append(str(error))
            telemetry_paths = []
        if not telemetry_paths:
            if not any("TELEMETRY_UNREADABLE" in defect for defect in defects):
                defects.append("telemetry_sha256 cannot be re-derived: no non-quarantined telemetry files")
        else:
            digest = hashlib.sha256()
            for telemetry_path in telemetry_paths:
                try:
                    relative = telemetry_path.relative_to(run_root).as_posix().encode("utf-8")
                    payload = telemetry_path.read_bytes()
                except OSError as error:
                    defects.append(f"telemetry_sha256 cannot be re-derived: {telemetry_path}: {error}")
                    continue
                digest.update(len(relative).to_bytes(8, "big"))
                digest.update(relative)
                digest.update(len(payload).to_bytes(8, "big"))
                digest.update(payload)
            if digest.hexdigest() != telemetry_sha:
                defects.append(
                    f"telemetry_sha256 does not match the bytes of non-quarantined telemetry files "
                    f"(receipt={telemetry_sha}, actual={digest.hexdigest()})"
                )
    if not series:
        if selected_run_id is None and len(series_counts) > 1:
            defects.append(
                "steps_measured cannot be re-derived: multiple telemetry run_ids under the run root "
                f"({series_counts!r}) and no --run-id selects one -- ambiguous adjudication is refused"
            )
        else:
            defects.append(
                "steps_measured cannot be re-derived: no train_step telemetry for the selected run "
                f"(run_id={selection_run_id!r}; run_ids_seen={series_counts!r})"
            )
    else:
        if isinstance(receipt_run_id, str) and receipt_run_id.strip() and receipt_run_id != selected_run_id:
            defects.append(
                f"run_id selector mismatch: receipt names {receipt_run_id!r}, the adjudicated series is "
                f"{selected_run_id!r} -- one run's recalibration must not credit another's telemetry"
            )
        if isinstance(steps_measured, int) and not isinstance(steps_measured, bool) and steps_measured != len(series):
            defects.append(
                f"steps_measured={steps_measured!r} does not equal the re-derived deduped series "
                f"length {len(series)} for run_id={selected_run_id!r}"
            )

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
        elif canonical_forecast_path is None or PurePath(forecast_rel).as_posix() != canonical_forecast_path:
            defects.append(f"forecast_path {forecast_rel!r} does not name the preregistered forecast document for rung {rung!r} ({canonical_forecast_path!r}) -- cross-rung or non-canonical paths are refused")
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


def check_r1_e6(
    run_root: Path, thresholds: dict[str, Any], *, repo_root: Path = REPO_ROOT,
    run_id: str | None = None, rung: str = "R1",
) -> dict[str, Any]:
    canonical_e6_forecast_path(rung)
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
            "components": {"rung": rung, "candidate_documents": [], "required_predicted_vs_measured": required},
            "needs": (
                "a forecast-recalibration receipt whose CONTENT carries predicted vs measured step time, "
                "tokens/s, proxy-joules/token, peak VRAM, and loss trajectory (prereg §3 closing-receipts "
                f"clause), generated against a real measured >= T-01={t01}-step run"
            ),
        }
    validations = [
        {**doc, "defects": _validate_recalibration_content(
            Path(doc["path"]), repo_root=repo_root, run_root=run_root, t01=t01,
            run_id=run_id, rung=rung,
        )}
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
            "components": {"rung": rung, "candidate_validation": validations, "required_predicted_vs_measured": required},
        }
    if not claimants:
        return {
            "status": "EVIDENCE_MISSING",
            "forecast_recalibration_validation": "IMPLEMENTED",
            "detail": (
                f"{len(validations)} name-matched candidate(s) but none claims to be a recalibration "
                "receipt; generate one with scripts/forecast_recalibration.py"
            ),
            "components": {"rung": rung, "candidate_validation": validations, "required_predicted_vs_measured": required},
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
        "components": {"rung": rung, "candidate_validation": validations, "required_predicted_vs_measured": required},
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
    rung: str = "R1",
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    seed_roots_effective = list(seed_roots) or [run_root]
    if exit_id == "e1":
        result = check_r1_e1(run_root, thresholds, run_id=run_id)
    elif exit_id == "e2":
        result = check_r1_e2(run_root, thresholds, run_id=run_id)
    elif exit_id == "e3":
        result = check_r1_e3(run_root, sibling_roots=sibling_roots, explicit_manifest=explicit_manifest)
    elif exit_id == "e4":
        result = check_r1_e4(run_root, thresholds, run_id=run_id)
    elif exit_id == "e5":
        result = check_r1_e5(run_root, thresholds, run_id=run_id)
    elif exit_id == "e6":
        result = check_r1_e6(run_root, thresholds, repo_root=repo_root, run_id=run_id, rung=rung)
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
    if exit_id == "e6":
        subject["rung"] = rung
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
    ap.add_argument("--run-id", type=str, default=None, help="explicit telemetry run_id to adjudicate for R1-E1/E2/E4/E5 (default: the single run_id present under --run-root; multiple run_ids without this flag refuse)")
    ap.add_argument("--rung", choices=tuple(E6_FORECAST_PATHS), default="R1", help="governed rung to adjudicate for E6 (default: R1)")
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
                rung=args.rung,
                repo_root=REPO_ROOT,
            )
        except R1ExitBatteryRefusal as exc:
            subject = {"run_root": str(args.run_root)}
            if exit_id == "e6":
                subject["rung"] = args.rung
            receipt = build_receipt(
                ticket=f"r1-exit-battery-{exit_id}",
                exit_criterion=f"R1-{exit_id.upper()}",
                subject=subject,
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
    layout_spec_path = _layout_spec_path()
    layout_spec_text = layout_spec_path.read_text(encoding="utf-8")
    assert RUN_ROOT_LAYOUT_SPEC == "docs/spec/ember-run-root-layout-v1.md", RUN_ROOT_LAYOUT_SPEC
    assert "attempt-" in layout_spec_text and "telemetry" in layout_spec_text, layout_spec_path

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

        # The launcher-retained attempt layout is excluded from authoritative
        # receipt discovery, while its telemetry remains part of the run's
        # train-step series.  This is the production boundary documented by
        # RUN_ROOT_LAYOUT_SPEC, not a filename-only assertion.
        retained_attempt = clean_root / "attempt-1-CHILD_FAILED-SELFTEST"
        retained_telemetry = retained_attempt / "telemetry" / "events.jsonl"
        _write_jsonl(
            retained_telemetry,
            _synthetic_train_step_events(
                run_id="SELFTEST_FIXTURE_run", n_steps=1
            ),
        )
        retained_receipt = retained_attempt / "frontier-receipt.json"
        retained_receipt.write_text("{}", encoding="utf-8")
        assert retained_telemetry in find_telemetry_files(clean_root), retained_telemetry
        assert _evidence_excluded(retained_receipt, clean_root), retained_receipt

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
        e4_empty = check_r1_e4(empty_root, thresholds)
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
        e4_result = check_r1_e4(e4_root, thresholds)
        assert e4_result["status"] == "EVIDENCE_MISSING", e4_result  # child.log alone is disclosed context, not the measurement receipt
        assert e4_result["components"]["peak_vram_during_training_bytes"] == 12345678, e4_result
        assert e4_result["context"]["pre_run_vram_preflight"]["total_gb"] == 25.76, e4_result

        # --- E4 fixtures: receipt + the telemetry series the receipt must bind to ---
        def _e4_receipt(steps: int = 100, tokens_total: int = 773, wall_seconds: float = 17.4) -> dict[str, Any]:
            active, peak = E4_ACTIVE_PARAMETERS, E4_ASSUMED_PEAK_FLOPS
            return {
                "schema_version": "ember02-r1-e4-measurement/v1",
                "run_id": "SELFTEST_FIXTURE_run",
                "steps": steps, "tokens_total": tokens_total, "tokens_missing_steps": 0,
                "write_failures": 0,
                "wall_seconds": wall_seconds, "step_ms_sum": wall_seconds * 1000.0,
                "tokens_per_second": tokens_total / wall_seconds,
                "tokens_per_second_step_basis": tokens_total / wall_seconds,
                "mfu": {"value": (6.0 * active * tokens_total / wall_seconds) / peak,
                        "flops_model": "6 * active_parameters * tokens_total / wall_seconds",
                        "active_parameters": active, "assumed_peak_flops": peak},
                "peak_vram": {"allocated_bytes": 21_700_000_000, "reserved_bytes": 22_100_000_000},
                "host_utilization": {"process_cpu_seconds": 8.7, "wall_seconds": wall_seconds, "process_cpu_fraction": 8.7 / wall_seconds},
            }

        def _e4_telemetry(root: Path, steps: int, run_id: str = "SELFTEST_FIXTURE_run") -> None:
            (root / "telemetry").mkdir(parents=True, exist_ok=True)
            rows = [json.dumps({"source": "ember-restart-3b", "kind": "train_step", "ts": f"2026-08-06T00:00:{i:02d}Z" if i < 60 else f"2026-08-06T00:{i // 60:02d}:{i % 60:02d}Z",
                                "payload": {"run_id": run_id, "step": i, "loss": 1.0}}) for i in range(1, steps + 1)]
            (root / "telemetry" / "selftest.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")

        def _e4_case(name: str, receipt: dict[str, Any] | str, telemetry_steps: int | None) -> dict[str, Any]:
            root = tmp_path / name
            root.mkdir()
            if telemetry_steps is not None:
                _e4_telemetry(root, telemetry_steps)
            (root / "e4-measurement-receipt.json").write_text(receipt if isinstance(receipt, str) else json.dumps(receipt), encoding="utf-8")
            return check_r1_e4(root, thresholds)

        # --- E4: content-valid receipt bound to a matching >=T-01 series -> MET ---
        e4_met = _e4_case("e4_met_run", _e4_receipt(), telemetry_steps=100)
        assert e4_met["status"] == "MET", e4_met
        assert abs(e4_met["components"]["tokens_per_second"] - 773 / 17.4) < 1e-9, e4_met

        # --- E4 (rev-1494 f1): steps below T-01 -> NOT_MET naming the threshold; non-integer steps -> NOT_MET ---
        e4_short = _e4_case("e4_short_run", _e4_receipt(steps=99), telemetry_steps=99)
        assert e4_short["status"] == "NOT_MET", e4_short
        assert any("T-01" in d for d in e4_short["components"]["defects"]), e4_short
        e4_frac = _e4_receipt()
        e4_frac["steps"] = 100.5
        e4_frac_res = _e4_case("e4_frac_run", e4_frac, telemetry_steps=100)
        assert e4_frac_res["status"] == "NOT_MET", e4_frac_res
        assert any("not an integer" in d for d in e4_frac_res["components"]["defects"]), e4_frac_res

        # --- E4 (rev-1494 f1 + merge-ordering hazard): a hand-written receipt in a
        # --- telemetry-free root -> NOT_MET on the series bind; series mismatch -> NOT_MET ---
        e4_unbound = _e4_case("e4_unbound_run", _e4_receipt(), telemetry_steps=None)
        assert e4_unbound["status"] == "NOT_MET", e4_unbound
        assert any("no train_step telemetry series" in d for d in e4_unbound["components"]["defects"]), e4_unbound
        e4_mismatch = _e4_case("e4_mismatch_run", _e4_receipt(steps=100), telemetry_steps=150)
        assert e4_mismatch["status"] == "NOT_MET", e4_mismatch
        assert any("disagrees with the deduped train_step series" in d for d in e4_mismatch["components"]["defects"]), e4_mismatch
        # telemetry one step AHEAD (emit-before-accumulate crash window) stays MET
        e4_ahead = _e4_case("e4_ahead_run", _e4_receipt(), telemetry_steps=101)
        assert e4_ahead["status"] == "MET", e4_ahead

        # --- E4 (rev-1494 round-2 item 1): the receipt must NAME the adjudicated
        # --- series -- foreign, null, and absent run_id all refuse ---
        e4_foreign = _e4_receipt()
        e4_foreign["run_id"] = "SOME-OTHER-RUN"
        e4_foreign_res = _e4_case("e4_foreign_run", e4_foreign, telemetry_steps=100)
        assert e4_foreign_res["status"] == "NOT_MET", e4_foreign_res
        assert any("must not credit another's series" in d for d in e4_foreign_res["components"]["defects"]), e4_foreign_res
        e4_nullid = _e4_receipt()
        e4_nullid["run_id"] = None
        e4_nullid_res = _e4_case("e4_nullid_run", e4_nullid, telemetry_steps=100)
        assert e4_nullid_res["status"] == "NOT_MET", e4_nullid_res
        e4_noid = _e4_receipt()
        del e4_noid["run_id"]
        e4_noid_res = _e4_case("e4_noid_run", e4_noid, telemetry_steps=100)
        assert e4_noid_res["status"] == "NOT_MET", e4_noid_res
        assert any("must name the run it describes" in d for d in e4_noid_res["components"]["defects"]), e4_noid_res

        # --- E4 (rev-1494 round-2 item 2): on a multi-run_id root the operator's
        # --- run_id selects the SAME series for E4 that E1 adjudicates ---
        e4_multi_root = tmp_path / "e4_multi_run"
        e4_multi_root.mkdir()
        _e4_telemetry(e4_multi_root, 100)
        (e4_multi_root / "telemetry" / "other.jsonl").write_text(
            "\n".join(json.dumps({"source": "ember-restart-3b", "kind": "train_step",
                                  "ts": f"2026-08-06T01:00:{i:02d}Z",
                                  "payload": {"run_id": "an-unrelated-attempt", "step": i, "loss": 9.9}})
                      for i in range(1, 41)) + "\n", encoding="utf-8")
        (e4_multi_root / "e4-measurement-receipt.json").write_text(json.dumps(_e4_receipt()), encoding="utf-8")
        e4_multi = check_r1_e4(e4_multi_root, thresholds, run_id="SELFTEST_FIXTURE_run")
        assert e4_multi["status"] == "MET", e4_multi

        # --- E4 (rev-1494 round-2 item 3): quarantined telemetry is not evidence
        # --- and cannot poison series selection ---
        e4_quar_root = tmp_path / "e4_quar_run"
        e4_quar_root.mkdir()
        _e4_telemetry(e4_quar_root, 100)
        quar_dir = e4_quar_root / ".checkpoint-quarantine" / "telemetry"
        quar_dir.mkdir(parents=True)
        (quar_dir / "poison.jsonl").write_text(
            json.dumps({"source": "ember-restart-3b", "kind": "train_step",
                        "ts": "2026-08-06T02:00:00Z",
                        "payload": {"run_id": "quarantined-run", "step": 1, "loss": 0.0}}) + "\n",
            encoding="utf-8")
        (e4_quar_root / "e4-measurement-receipt.json").write_text(json.dumps(_e4_receipt()), encoding="utf-8")
        e4_quar = check_r1_e4(e4_quar_root, thresholds)
        assert e4_quar["status"] == "MET", e4_quar

        # --- E4 (rev-1494 f2): declared cpu_fraction inconsistent with its own inputs -> NOT_MET ---
        e4_cpu = _e4_receipt()
        e4_cpu["host_utilization"]["process_cpu_fraction"] = 0.999
        e4_cpu_res = _e4_case("e4_cpu_run", e4_cpu, telemetry_steps=100)
        assert e4_cpu_res["status"] == "NOT_MET", e4_cpu_res
        assert any("process_cpu_fraction" in d and "inconsistent" in d for d in e4_cpu_res["components"]["defects"]), e4_cpu_res

        # --- E4 (rev-1494 f3): flops-model constants differing from the adjudication pins -> NOT_MET
        # --- (a self-cohering fabricated MFU basis must not pass) ---
        e4_pins = _e4_receipt()
        e4_pins["mfu"]["active_parameters"] = 1.0
        e4_pins["mfu"]["assumed_peak_flops"] = 1e6
        e4_pins["mfu"]["value"] = (6.0 * 1.0 * e4_pins["tokens_total"] / e4_pins["wall_seconds"]) / 1e6
        e4_pins_res = _e4_case("e4_pins_run", e4_pins, telemetry_steps=100)
        assert e4_pins_res["status"] == "NOT_MET", e4_pins_res
        assert any("adjudication pin" in d for d in e4_pins_res["components"]["defects"]), e4_pins_res

        # --- E4 (rev-1494 f4): a receipt of exactly {} -> NOT_MET with the defect list, no crash ---
        e4_brace = _e4_case("e4_brace_run", "{}", telemetry_steps=100)
        assert e4_brace["status"] == "NOT_MET", e4_brace
        assert len(e4_brace["components"]["defects"]) >= 5, e4_brace

        # --- E4: write_failures disclosure -- negative refuses; positive discloses and stays MET ---
        e4_wf_bad = _e4_receipt()
        e4_wf_bad["write_failures"] = -1
        e4_wf_bad_res = _e4_case("e4_wf_bad_run", e4_wf_bad, telemetry_steps=100)
        assert e4_wf_bad_res["status"] == "NOT_MET", e4_wf_bad_res
        e4_wf_ok = _e4_receipt()
        e4_wf_ok["write_failures"] = 2
        e4_wf_ok_res = _e4_case("e4_wf_ok_run", e4_wf_ok, telemetry_steps=100)
        assert e4_wf_ok_res["status"] == "MET", e4_wf_ok_res

        # --- E4: tokens_per_second inconsistent with its own inputs -> NOT_MET ---
        e4_bad = _e4_receipt()
        e4_bad["tokens_per_second"] = e4_bad["tokens_per_second"] * 3.0
        e4_bad_result = _e4_case("e4_bad_run", e4_bad, telemetry_steps=100)
        assert e4_bad_result["status"] == "NOT_MET", e4_bad_result
        assert any("inconsistent" in d for d in e4_bad_result["components"]["defects"]), e4_bad_result

        # --- E4: a partial run with missing per-step tokens (nulls) -> NOT_MET, never extrapolated ---
        e4_null = _e4_receipt()
        e4_null["tokens_missing_steps"] = 7
        e4_null["tokens_total"] = None
        e4_null["tokens_per_second"] = None
        e4_null["mfu"]["value"] = None
        e4_null_result = _e4_case("e4_null_run", e4_null, telemetry_steps=100)
        assert e4_null_result["status"] == "NOT_MET", e4_null_result
        assert any("tokens_missing_steps" in d for d in e4_null_result["components"]["defects"]), e4_null_result

        # --- E5: EVIDENCE_MISSING against an empty root; fixed-prior manifest presence is reported ---
        e5 = check_r1_e5(empty_root, thresholds)
        assert e5["status"] == "EVIDENCE_MISSING", e5
        assert e5["frontier_receipt_validation"] == "IMPLEMENTED", e5
        assert e5["components"]["fixed_prior_manifest_present"] is True, e5  # real repo file, checked via REPO_ROOT default
        assert e5["components"]["quarantined_telemetry_files"] == [], e5

        # --- E5: a name-matched JUNK file is a defective CLAIMANT (NOT_MET), never EVIDENCE_MISSING, never MET ---
        e5_junk_root = tmp_path / "e5_junk_run"
        e5_junk_root.mkdir()
        (e5_junk_root / "SELFTEST_FIXTURE-frontier-receipt.json").write_bytes(json.dumps({"note": "SELFTEST_FIXTURE junk"}).encode("utf-8"))
        e5_junk = check_r1_e5(e5_junk_root, thresholds)
        assert e5_junk["status"] == "NOT_MET", e5_junk
        assert e5_junk["frontier_receipt_validation"] == "IMPLEMENTED", e5_junk
        assert e5_junk["components"]["candidate_validation"][0]["defects"], e5_junk

        # --- E5: full-fixture MET path + per-leg poison cases against the eight-leg validator ---
        def _e5_repo(name: str) -> Path:
            """A fake repo root carrying every pinned document the validator
            binds, so the MET path is provable hermetically (the real repo
            lacks receipts/run-attempts.jsonl until issue #1497 lands)."""
            repo = tmp_path / name
            (repo / "docs" / "spec").mkdir(parents=True)
            (repo / "configs").mkdir()
            (repo / "manifests" / "ember-restart-3b").mkdir(parents=True)
            (repo / "receipts" / "ember-restart-3b").mkdir(parents=True)
            (repo / "docs" / "spec" / "ember02-preregistration-v1.md").write_bytes(b"SELFTEST_FIXTURE prereg\n")
            (repo / "configs" / "ember-restart-3b.json").write_bytes(json.dumps({"SELFTEST_FIXTURE": True}).encode("utf-8"))
            (repo / "docs/authority/INVARIANT.md").write_bytes(b"SELFTEST_FIXTURE invariant\n")
            (repo / "manifests" / "ember-restart-3b" / "fixed-prior-manifest-v1.json").write_bytes(json.dumps({
                "learned_import_attestation": "SELFTEST_FIXTURE: no learned imports of any category",
                "items": [
                    {"kind": "file", "provenance": "SELFTEST_FIXTURE file", "sha256": "a" * 64},
                    {"kind": "version", "provenance": "SELFTEST_FIXTURE version", "probe": {"ok": True, "output": "1.0"}},
                    {"kind": "tree", "provenance": "SELFTEST_FIXTURE tree", "combined_sha256": "b" * 64},
                    {"kind": "external", "provenance": "SELFTEST_FIXTURE external bytes, sha None by design", "sha256": None},
                ],
            }).encode("utf-8"))
            (repo / "receipts" / "ember-restart-3b" / "tokenizer-reconstruction-issue534-v1.json").write_bytes(
                json.dumps({"SELFTEST_FIXTURE": "tokenizer"}).encode("utf-8"))
            (repo / "receipts" / "ember-restart-3b" / "native-cost-calibration-seed83-certificate.json").write_bytes(
                json.dumps({"SELFTEST_FIXTURE": "genesis", "adjudication": "PASS"}).encode("utf-8"))
            return repo

        def _e5_run(name: str) -> tuple[Path, dict[str, Any]]:
            """A run root with every evidence file; returns (root, checkpoint manifest)."""
            run = tmp_path / name
            ckpt = run / "artifacts" / "checkpoints" / "checkpoint-selftest"
            ckpt.mkdir(parents=True)
            # A real 204-step telemetry series: steps_measured is re-derived
            # from this, never accepted on the receipt's word (rev-1490 item 1).
            _write_jsonl(run / "telemetry" / "train.jsonl",
                         _synthetic_train_step_events(run_id="SELFTEST_E5_run", n_steps=204))
            shared_model = ckpt / "shared-model.pt"
            shared_model.write_bytes(b"SELFTEST_FIXTURE owned checkpoint")
            shared_model_sha = hashlib.sha256(shared_model.read_bytes()).hexdigest()
            manifest = {
                "model_config_sha256": "c" * 64,
                "shared_model_shard_sha256": shared_model_sha,
                # Per-shard MAPPING, the real v5 shape (cross-check finding:
                # these pins are not single hex strings).
                "optimizer_state_shard_sha256": {"shard0": "d" * 64, "shard1": "d" * 63 + "e"},
                "rng_state_sha256": "e" * 64,
                "optimizer_contract": "SELFTEST_FIXTURE-adamw-v1",
                "launch_seed": 830001,
                "data_cursor": {"tokens_seen": 417792, "global_step": 204, "resume_authority": "SELFTEST_FIXTURE"},
                "shards": [
                    {
                        "role": "shared_model",
                        "path": shared_model.name,
                        "sha256": shared_model_sha,
                    }
                ],
            }
            (ckpt / "checkpoint-manifest.json").write_bytes(json.dumps(manifest).encode("utf-8"))
            manifest_sha = hashlib.sha256((ckpt / "checkpoint-manifest.json").read_bytes()).hexdigest()
            suite_path = run / "frozen-eval-suite.json"
            suite_path.write_bytes(
                (REPO_ROOT / "docs/spec/ember02-r1-r2-cheap-probe-suite-v1.json").read_bytes()
            )
            suite_sha = hashlib.sha256(suite_path.read_bytes()).hexdigest()
            _suite_raw, suite = frozen_eval._load_suite(suite_path, suite_sha)
            result_rows = [
                {
                    "row_id": task["row_id"],
                    "judge": task["judge"],
                    "passed": True,
                    "output": task["expected_output"],
                    "output_sha256": hashlib.sha256(
                        task["expected_output"].encode("utf-8")
                    ).hexdigest(),
                }
                for task in suite["tasks"]
            ]
            eval_receipt = {
                "schema": frozen_eval.RESULT_SCHEMA,
                "eval_suite_id": suite["eval_suite_id"],
                "eval_suite_sha256": suite_sha,
                "checkpoint_manifest_sha256": manifest_sha,
                "checkpoint_file_sha256s": {"shared_model": shared_model_sha},
                "owned_identity": {
                    "seat": "OWNED_ADMITTED",
                    "checkpoint_sha256": manifest_sha,
                    "model_name": f"ember-owned:{manifest_sha[:12]}",
                    "model_config_sha256": "b" * 64,
                    "tokenizer_sha256": "c" * 64,
                    "server_source_sha256": "d" * 64,
                },
                "rows": result_rows,
                "results": frozen_eval._probe_results(suite, result_rows),
                "tool_access": "none",
                "retry_count": 0,
                "execution_claim": True,
                "result_credit": False,
                "claim_boundary": frozen_eval._CLAIM_BOUNDARY,
            }
            eval_receipt["receipt_sha256"] = hashlib.sha256(
                frozen_eval._canonical_bytes(eval_receipt, omit="receipt_sha256")
            ).hexdigest()
            (run / "frozen-eval-results.json").write_bytes(
                json.dumps(eval_receipt).encode("utf-8")
            )
            # The real schema_version-7 runner-receipt shape: unix SECONDS.
            (run / "disk-budget-runner-receipt.json").write_bytes(json.dumps({
                "schema_version": 7, "started_at_unix": 1786200000.0, "finished_at_unix": 1786200742.0,
            }).encode("utf-8"))
            (run / "energy-proxy-receipt.json").write_bytes(json.dumps({
                "schema_version": "ember-energy-proxy-run-v1",
                "energy": {
                    "energy_boundary": "DEGRADED_PROXY", "sample_coverage_fraction": 1.0,
                    "gpu_joules": 118.0, "cpu_pkg_joules": 464.5, "total_proxy_joules": 582.5,
                },
            }).encode("utf-8"))
            (run / "reproduction-adjudication.json").write_bytes(json.dumps({
                "status": "REPRODUCED", "mismatch": None, "evidence_ref": "SELFTEST_FIXTURE r1-e3 round trip",
            }).encode("utf-8"))
            (run / "human-interventions.json").write_bytes(b"[]")
            (run / "walls-checklist.json").write_bytes(json.dumps(
                [{"wall_id": wall_id, "verdict": "not_probed"} for wall_id in E5_WALL_IDS]
            ).encode("utf-8"))
            return run, manifest

        def _write_e5_registry(repo: Path, run: Path) -> list[dict[str, Any]]:
            """Write one production-shaped live spawn/terminal pair."""
            import run_attempt_registry as registry_module

            (run / "run-spec.json").write_text(
                '{"schema_version":"SELFTEST_FIXTURE"}\n', encoding="utf-8"
            )
            rows = [
                registry_module.build_row(
                    run_root=run,
                    outcome="running",
                    run_id="SELFTEST_E5_run",
                    attempt_id="attempt-selftest",
                    start_utc="2026-08-06T12:00:00Z",
                    end_utc=None,
                    checkpoint_manifest_sha256=None,
                    launch_receipt_ref="run-spec.json",
                    source_receipt="run-spec.json",
                    outcome_basis="SELFTEST_FIXTURE certified launcher spawn",
                    backfill=False,
                ),
                registry_module.build_row(
                    run_root=run,
                    outcome="completed",
                    run_id="SELFTEST_E5_run",
                    attempt_id="attempt-selftest",
                    start_utc="2026-08-06T12:00:00Z",
                    end_utc="2026-08-06T12:12:22Z",
                    checkpoint_manifest_sha256=None,
                    launch_receipt_ref="disk-budget-runner-receipt.json",
                    source_receipt="disk-budget-runner-receipt.json",
                    outcome_basis="SELFTEST_FIXTURE certified child exit 0",
                    backfill=False,
                ),
            ]
            registry_path = repo / E5_RUN_ATTEMPTS_REGISTRY
            registry_path.write_bytes(
                b"".join(
                    json.dumps(row, sort_keys=True).encode("utf-8") + b"\n"
                    for row in rows
                )
            )
            return rows

        def _e5_receipt(repo: Path, run: Path, manifest: dict[str, Any]) -> dict[str, Any]:
            """Assemble a receipt whose every binding matches the fixture bytes
            -- an independent transcription of the generator's shape."""
            def sha_of(p: Path) -> str:
                return hashlib.sha256(p.read_bytes()).hexdigest()
            manifest_sha = sha_of(run / "artifacts" / "checkpoints" / "checkpoint-selftest" / "checkpoint-manifest.json")
            fixed_prior_rel = "manifests/ember-restart-3b/fixed-prior-manifest-v1.json"
            fixed_prior_sha = sha_of(repo / fixed_prior_rel)
            energy_block = json.loads((run / "energy-proxy-receipt.json").read_text(encoding="utf-8"))["energy"]
            eval_doc = json.loads((run / "frozen-eval-results.json").read_text(encoding="utf-8"))
            return {
                "schema_version": FRONTIER_SCHEMA,
                "generated_utc": "2026-08-06T12:00:00Z",
                "generator": "scripts/frontier_receipt.py",
                "rung": "R1",
                "run_root": str(run),
                "run_id": "SELFTEST_E5_run",
                # Equals the fixture telemetry series length (re-derived).
                "steps_measured": 204,
                "prereg": {"path": E5_PREREG_PATH, "sha256": sha_of(repo / E5_PREREG_PATH)},
                "admission_config": {"path": E5_ADMISSION_CONFIG_PATH, "sha256": sha_of(repo / E5_ADMISSION_CONFIG_PATH)},
                "identity_spine": {
                    "goal_id": "EMBER-02", "workstream_id": "EMBER-02A",
                    "next_executed_outcome": "SELFTEST_FIXTURE outcome",
                    "checkpoint_manifest_sha256": manifest_sha,
                    "checkpoint_file_sha256s": {
                        "optimizer_state_shard_sha256": manifest["optimizer_state_shard_sha256"],
                        "rng_state_sha256": manifest["rng_state_sha256"],
                    },
                },
                "ledger": {
                    "learned_import_attestation_ref": "see learned_import_attestation (leg 2)",
                    "fixed_prior_manifest_ref": fixed_prior_rel,
                    "human_interventions": {
                        "interventions": [], "attestation": "SELFTEST_FIXTURE: zero interventions",
                        "source_sha256": sha_of(run / "human-interventions.json"),
                    },
                    "data_accounting": {
                        "tokens_seen": manifest["data_cursor"]["tokens_seen"],
                        "acquisition_this_rung": "none",
                        "attestation": "SELFTEST_FIXTURE: frozen preregistered stream only",
                        "corpora_evidence_ref": fixed_prior_rel,
                        "synthetic_ancestry_graph_ref": None,
                        "retained_originals": True,
                    },
                    "host_accounting": {
                        "offload_bytes": None,
                        "not_measured": {
                            "cpu_gpu_utilization": "SELFTEST_FIXTURE: no e4 receipt in this fixture",
                            "ram_peak": "SELFTEST_FIXTURE reason", "storage_io": "SELFTEST_FIXTURE reason",
                            "network_io": "SELFTEST_FIXTURE reason", "checkpoint_overhead_s": "SELFTEST_FIXTURE reason",
                            "failure_overhead_s": "SELFTEST_FIXTURE reason",
                        },
                    },
                    "energy_ref": "see energy (leg 5)",
                    "all_compute_coverage": {
                        "components": {
                            component: {
                                "included": component in ("training", "validation", "final_evaluation"),
                                "evidence_ref": E5_RUN_ATTEMPTS_REGISTRY if component in ("training", "validation", "final_evaluation") else None,
                                "note": None if component in ("training", "validation", "final_evaluation") else "SELFTEST_FIXTURE: not exercised at R1",
                            }
                            for component in E5_COMPUTE_COMPONENTS
                        },
                        "failed_work_included": True,
                        "registry_path": E5_RUN_ATTEMPTS_REGISTRY,
                        "registry_prefix_sha256": sha_of(repo / E5_RUN_ATTEMPTS_REGISTRY),
                        "registry_rows": len(
                            _registry_rows_and_prefix(
                                repo / E5_RUN_ATTEMPTS_REGISTRY
                            )[0]
                        ),
                    },
                    "walls_checklist": {
                        "rows": json.loads((run / "walls-checklist.json").read_text(encoding="utf-8")),
                        "source_sha256": sha_of(run / "walls-checklist.json"),
                    },
                    "identity_spine_ref": "see identity_spine (envelope)",
                },
                "fixed_prior": {"manifest_path": fixed_prior_rel, "manifest_sha256": fixed_prior_sha},
                "learned_import_attestation": {
                    **{category: False for category in E5_ATTESTATION_CATEGORIES},
                    "basis": "SELFTEST_FIXTURE basis",
                },
                "capability": {
                    "eval_suite_id": eval_doc["eval_suite_id"],
                    "eval_suite_path": str(run / "frozen-eval-suite.json"),
                    "eval_suite_sha256": eval_doc["eval_suite_sha256"],
                    "results_receipt_path": str(run / "frozen-eval-results.json"),
                    "results_receipt_sha256": sha_of(run / "frozen-eval-results.json"),
                    "checkpoint_manifest_sha256": manifest_sha,
                    "checkpoint_file_sha256s": eval_doc["checkpoint_file_sha256s"],
                    "results": eval_doc["results"],
                    "tool_access": "none",
                    "model_only_ablation": None,
                },
                "time": {
                    "run_start_utc": datetime.fromtimestamp(1786200000.0, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
                    "run_end_utc": datetime.fromtimestamp(1786200742.0, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
                    "wall_clock_seconds": 742.0, "coverage": "process_birth_to_exit",
                    "source": "disk-budget-runner-receipt.json started_at_ms/finished_at_ms (SELFTEST_FIXTURE)",
                    "runner_receipt_sha256": sha_of(run / "disk-budget-runner-receipt.json"),
                },
                "energy": energy_block,
                "energy_receipt_path": str(run / "energy-proxy-receipt.json"),
                "energy_receipt_sha256": sha_of(run / "energy-proxy-receipt.json"),
                "reproducibility": {
                    "config_sha256": manifest["model_config_sha256"],
                    "optimizer_state_sha256": manifest["optimizer_state_shard_sha256"],
                    "rng_state_sha256": manifest["rng_state_sha256"],
                    "optimizer_contract": manifest["optimizer_contract"],
                    "tokenizer_reconstruction_receipt": {
                        "path": E5_TOKENIZER_RECEIPT_PATH,
                        "sha256": sha_of(repo / E5_TOKENIZER_RECEIPT_PATH),
                    },
                    "seeds": [manifest["launch_seed"]],
                    "data_cursor": {
                        "tokens_seen": manifest["data_cursor"]["tokens_seen"],
                        "global_step": manifest["data_cursor"]["global_step"],
                        "resume_authority": "SELFTEST_FIXTURE",
                    },
                    "recipe_ref": fixed_prior_sha,
                    "reproduction": {
                        "status": "REPRODUCED", "mismatch": None,
                        "evidence_ref": "SELFTEST_FIXTURE r1-e3 round trip",
                        "adjudication_sha256": sha_of(run / "reproduction-adjudication.json"),
                    },
                },
                "advantage_claims": [],
                "invariant_stamp": {"invariant_md_sha256": sha_of(repo / "docs/authority/INVARIANT.md")},
                "predecessor_receipt": {
                    "path": "receipts/ember-restart-3b/native-cost-calibration-seed83-certificate.json",
                    "sha256": sha_of(repo / "receipts" / "ember-restart-3b" / "native-cost-calibration-seed83-certificate.json"),
                },
            }

        e5_repo = _e5_repo("e5_repo")
        e5_run, e5_manifest = _e5_run("e5_full_run")
        _write_e5_registry(e5_repo, e5_run)
        e5_pristine = _e5_receipt(e5_repo, e5_run, e5_manifest)

        def _e5_case(mutate=None, run_id=None) -> dict[str, Any]:
            receipt = json.loads(json.dumps(e5_pristine))
            if mutate is not None:
                mutate(receipt)
            (e5_run / "frontier-receipt.json").write_bytes(json.dumps(receipt).encode("utf-8"))
            return check_r1_e5(e5_run, thresholds, repo_root=e5_repo, run_id=run_id)

        def _e5_defect(result: dict[str, Any], fragment: str) -> None:
            assert result["status"] == "NOT_MET", (fragment, result)
            defects = result["components"]["candidate_validation"][0]["defects"]
            assert any(fragment in d for d in defects), (fragment, defects)

        # MET: every leg re-verified against the fixture bytes.
        e5_met = _e5_case()
        assert e5_met["status"] == "MET", e5_met
        assert e5_met["frontier_receipt_validation"] == "IMPLEMENTED", e5_met
        assert e5_met["components"]["steps_measured"] == e5_pristine["steps_measured"], e5_met
        assert e5_met["components"]["energy_boundary"] == "DEGRADED_PROXY", e5_met

        # The producer's independent byte helper must bind exactly the rows it
        # read, not the mutable whole-file hash.
        import frontier_receipt as frontier_receipt_module
        producer_rows, producer_prefix = frontier_receipt_module._read_registry_rows_and_prefix(
            e5_repo / E5_RUN_ATTEMPTS_REGISTRY
        )
        assert len(producer_rows) == 2, producer_rows
        assert hashlib.sha256(producer_prefix).hexdigest() == e5_pristine[
            "ledger"
        ]["all_compute_coverage"]["registry_prefix_sha256"]
        generator_repo_root = frontier_receipt_module.REPO_ROOT
        frontier_receipt_module.REPO_ROOT = e5_repo
        try:
            generated_coverage = frontier_receipt_module.ledger_all_compute_coverage(
                e5_run,
                "SELFTEST_E5_run",
                e5_pristine["identity_spine"]["checkpoint_manifest_sha256"],
            )
        finally:
            frontier_receipt_module.REPO_ROOT = generator_repo_root
        assert generated_coverage["registry_rows"] == 2, generated_coverage
        assert generated_coverage["registry_prefix_sha256"] == e5_pristine[
            "ledger"
        ]["all_compute_coverage"]["registry_prefix_sha256"]

        # #1510: a later append must not invalidate a receipt bound to the
        # first registry row it read; editing that bound prefix must refuse.
        registry_path = e5_repo / E5_RUN_ATTEMPTS_REGISTRY
        registry_before_append = registry_path.read_bytes()

        # Existing v1 receipts used a whole-file registry_sha256.  Preserve
        # that exact behavior for already-minted receipts while new receipts
        # use the append-stable prefix field.
        def _legacy_registry_binding(receipt: dict[str, Any]) -> None:
            coverage = receipt["ledger"]["all_compute_coverage"]
            coverage.pop("registry_prefix_sha256")
            coverage["registry_sha256"] = hashlib.sha256(
                registry_before_append
            ).hexdigest()

        e5_legacy = _e5_case(_legacy_registry_binding)
        assert e5_legacy["status"] == "MET", e5_legacy

        def _legacy_with_null_prefix(receipt: dict[str, Any]) -> None:
            _legacy_registry_binding(receipt)
            receipt["ledger"]["all_compute_coverage"][
                "registry_prefix_sha256"
            ] = None

        def _prefix_with_null_legacy(receipt: dict[str, Any]) -> None:
            receipt["ledger"]["all_compute_coverage"]["registry_sha256"] = None

        _e5_defect(_e5_case(_legacy_with_null_prefix), "must not mix")
        _e5_defect(_e5_case(_prefix_with_null_legacy), "must not mix")

        import run_attempt_registry as registry_module
        (e5_run / "later-run-spec.json").write_text(
            '{"schema_version":"SELFTEST_FIXTURE-later"}\n', encoding="utf-8"
        )
        later_row = registry_module.build_row(
            run_root=e5_run,
            outcome="running",
            run_id="SELFTEST_E5_run",
            attempt_id="attempt-appended-after-mint",
            start_utc="2026-08-06T13:00:00Z",
            end_utc=None,
            checkpoint_manifest_sha256=None,
            launch_receipt_ref="later-run-spec.json",
            source_receipt="later-run-spec.json",
            outcome_basis="SELFTEST_FIXTURE later live append",
            backfill=False,
        )
        registry_path.write_bytes(
            registry_before_append
            + json.dumps(later_row, sort_keys=True).encode("utf-8")
            + b"\n"
        )
        e5_append_after_mint = _e5_case()
        assert e5_append_after_mint["status"] == "MET", e5_append_after_mint
        registry_after_append = registry_path.read_bytes()

        # The prefix hash ignores valid later appends, but the current registry
        # must remain structurally readable end to end.  Corrupt tails never
        # inherit authority from an earlier valid prefix.
        for poison, fragment in (
            (b"\xff\n", "registry unreadable"),
            (b'{"run_id":\n', "unparseable"),
            (b"0\n", "not JSON objects"),
        ):
            registry_path.write_bytes(registry_before_append + poison)
            _e5_defect(_e5_case(), fragment)

        registry_path.write_bytes(registry_after_append)
        registry_path.write_bytes(
            registry_after_append.replace(
                b'"outcome": "completed"', b'"outcome": "tampered"', 1
            )
        )
        e5_edited_prefix = _e5_case()
        _e5_defect(e5_edited_prefix, "registry prefix")
        registry_path.write_bytes(registry_before_append)

        # The run root itself may use the retained-attempt naming convention.
        # Exclusion is scoped below the selected root, so complete evidence in
        # an attempt-* root must still adjudicate normally as MET.
        attempt_root_repo = _e5_repo("e5_attempt_root_repo")
        attempt_root, attempt_root_manifest = _e5_run(
            "attempt-7-CHILD_FAILED-20260808T230500Z"
        )
        _write_e5_registry(attempt_root_repo, attempt_root)
        attempt_root_receipt = _e5_receipt(
            attempt_root_repo, attempt_root, attempt_root_manifest
        )
        (attempt_root / "frontier-receipt.json").write_bytes(
            json.dumps(attempt_root_receipt).encode("utf-8")
        )
        e5_attempt_root = check_r1_e5(
            attempt_root,
            thresholds,
            repo_root=attempt_root_repo,
        )
        assert e5_attempt_root["status"] == "MET", e5_attempt_root

        # Envelope poisons.
        def _set(path_keys, value):
            def mutate(receipt):
                target = receipt
                for key in path_keys[:-1]:
                    target = target[key]
                target[path_keys[-1]] = value
            return mutate
        _e5_defect(_e5_case(_set(["schema_version"], "ember02-frontier-receipt/v0")), "schema_version")
        _e5_defect(_e5_case(_set(["run_root"], str(tmp_path / "some_other_run"))), "run_root mismatch")
        _e5_defect(_e5_case(_set(["steps_measured"], int(thresholds["T-01"]) - 1)), "steps_measured")
        _e5_defect(_e5_case(_set(["prereg", "sha256"], "0" * 64)), "prereg")
        _e5_defect(_e5_case(_set(["advantage_claims"], [{"claim": "SELFTEST_FIXTURE"}])), "advantage_claims")
        _e5_defect(_e5_case(_set(["invariant_stamp", "invariant_md_sha256"], "0" * 64)), "invariant_stamp")

        # Energy poisons: boundary, coverage, arithmetic, and the verbatim-embed contract.
        _e5_defect(_e5_case(_set(["energy", "energy_boundary"], "MEASURED")), "energy_boundary")
        _e5_defect(_e5_case(_set(["energy", "sample_coverage_fraction"], float(thresholds["T-06"]) - 0.01)), "T-06")
        _e5_defect(_e5_case(_set(["energy", "total_proxy_joules"], 9999.0)), "total_proxy_joules")

        def _energy_consistent_but_foreign(receipt):
            receipt["energy"]["gpu_joules"] = 200.0
            receipt["energy"]["total_proxy_joules"] = 200.0 + receipt["energy"]["cpu_pkg_joules"]
        _e5_defect(_e5_case(_energy_consistent_but_foreign), "verbatim")

        # Identity/capability/reproducibility value-binding poisons.
        def _wrong_manifest_sha(receipt):
            receipt["identity_spine"]["checkpoint_manifest_sha256"] = "1" * 64
            receipt["capability"]["checkpoint_manifest_sha256"] = "1" * 64
        _e5_defect(_e5_case(_wrong_manifest_sha), "checkpoint manifest")
        _e5_defect(_e5_case(_set(["reproducibility", "config_sha256"], "2" * 64)), "config_sha256")
        _e5_defect(_e5_case(_set(["reproducibility", "seeds"], [999999])), "seeds")
        _e5_defect(_e5_case(_set(["capability", "tool_access"], "browser")), "tool_access")

        # Ledger poisons: walls row count and interventions verbatim-equality.
        def _drop_wall(receipt):
            receipt["ledger"]["walls_checklist"]["rows"] = receipt["ledger"]["walls_checklist"]["rows"][:11]
        _e5_defect(_e5_case(_drop_wall), "walls_checklist")
        _e5_defect(_e5_case(_set(["ledger", "human_interventions", "interventions"],
                                 [{"note": "SELFTEST_FIXTURE ghost row"}])), "human_interventions")

        # Registry deleted from the fake repo after receipt assembly -> §5.1 class 7 unattestable.
        registry_bytes = (e5_repo / "receipts" / "run-attempts.jsonl").read_bytes()
        (e5_repo / "receipts" / "run-attempts.jsonl").unlink()
        _e5_defect(_e5_case(), "run-attempt registry")
        (e5_repo / "receipts" / "run-attempts.jsonl").write_bytes(registry_bytes)

        # docs/authority/INVARIANT.md drift after receipt assembly -> the stamp no longer names the invariant in force.
        invariant_bytes = (e5_repo / "docs/authority/INVARIANT.md").read_bytes()
        (e5_repo / "docs/authority/INVARIANT.md").write_bytes(b"SELFTEST_FIXTURE invariant CHANGED\n")
        _e5_defect(_e5_case(), "docs/authority/INVARIANT.md in force")
        (e5_repo / "docs/authority/INVARIANT.md").write_bytes(invariant_bytes)

        # Ambiguity: a second frontier-named file -> NOT_MET, never a pick-one.
        (e5_run / "SELFTEST_FIXTURE-copy-frontier-receipt.json").write_bytes(json.dumps(e5_pristine).encode("utf-8"))
        e5_ambiguous = _e5_case()
        assert e5_ambiguous["status"] == "NOT_MET" and "ambiguous" in e5_ambiguous["detail"], e5_ambiguous
        (e5_run / "SELFTEST_FIXTURE-copy-frontier-receipt.json").unlink()

        # Quarantined telemetry with real train_step rows: surfaced, never blocking (rev-1490 round-3).
        quarantine_dir = e5_run / "artifacts" / "checkpoints" / ".checkpoint-quarantine" / "candidate-x" / "telemetry"
        quarantine_dir.mkdir(parents=True)
        (quarantine_dir / "poison.jsonl").write_bytes(json.dumps({
            "source": "ember-restart-3b", "kind": "train_step", "ts": "2026-08-06T00:00:00Z",
            "payload": {"run_id": "SELFTEST_FIXTURE_run", "step": 1},
        }).encode("utf-8") + b"\n")
        e5_quarantine = _e5_case()
        assert e5_quarantine["status"] == "MET", e5_quarantine
        assert len(e5_quarantine["components"]["quarantined_telemetry_files"]) == 1, e5_quarantine

        # An UNREADABLE quarantined .jsonl (a directory wearing the name) is
        # surfaced too -- a read error is the case where something is
        # actively wrong, never reported clean (rev-1490 non-blocking 3).
        (quarantine_dir / "locked.jsonl").mkdir()
        e5_unreadable = _e5_case()
        assert e5_unreadable["status"] == "MET", e5_unreadable
        assert len(e5_unreadable["components"]["quarantined_telemetry_files"]) == 2, e5_unreadable
        (quarantine_dir / "locked.jsonl").rmdir()

        # --- rev-1490 REWORK items 1-6, each cure proven at the bytes ---
        # Item 1: an inflated headline count no series reached never validates.
        _e5_defect(_e5_case(_set(["steps_measured"], 100000)), "does not equal the re-derived")
        # Item 1: a receipt naming a foreign run's telemetry never validates.
        _e5_defect(_e5_case(_set(["run_id"], "SELFTEST_E5_other")), "run_id mismatch")

        # Item 2: a resumed root (second run_id) is ambiguous without --run-id,
        # and adjudicable per-run with it -- steps re-derive from the SELECTED
        # series, never the pool.
        _write_jsonl(e5_run / "telemetry" / "resume.jsonl",
                     _synthetic_train_step_events(run_id="SELFTEST_E5_resume", n_steps=60))
        _e5_defect(_e5_case(), "multiple telemetry run_ids")
        e5_selected = _e5_case(run_id="SELFTEST_E5_run")
        assert e5_selected["status"] == "MET", e5_selected
        (e5_run / "telemetry" / "resume.jsonl").unlink()

        # Item 3: the admission config doubling as its own predecessor (valid
        # sha, wrong document) never validates -- the pin is the genesis receipt.
        def _predecessor_decoy(receipt):
            decoy = e5_repo / "configs" / "ember-restart-3b.json"
            receipt["predecessor_receipt"] = {
                "path": "configs/ember-restart-3b.json",
                "sha256": hashlib.sha256(decoy.read_bytes()).hexdigest(),
            }
        _e5_defect(_e5_case(_predecessor_decoy), "predecessor_receipt")

        # Item 4: a registry whose single line is the scalar `0` attests nothing.
        registry_file = e5_repo / "receipts" / "run-attempts.jsonl"
        original_registry = registry_file.read_bytes()
        registry_file.write_bytes(b"0\n")
        _e5_defect(_e5_case(_set(["ledger", "all_compute_coverage", "registry_prefix_sha256"],
                                 hashlib.sha256(b"0\n").hexdigest())), "not JSON objects")
        # Item 4: canonical object rows that never name the adjudicated
        # run/root still attest nothing.
        foreign_row_doc = registry_module.build_row(
            run_root=tmp_path / "foreign-e5-root",
            outcome="completed",
            run_id="SOMEONE_ELSE",
            attempt_id="evidence-floor",
            start_utc="2026-08-06T14:00:00Z",
            end_utc="2026-08-06T14:00:00Z",
            checkpoint_manifest_sha256=None,
            launch_receipt_ref="historical-receipt.json",
            source_receipt="historical-receipt.json",
            outcome_basis="SELFTEST_FIXTURE foreign history",
            backfill=True,
        )
        foreign_row = json.dumps(foreign_row_doc, sort_keys=True).encode("utf-8") + b"\n"
        registry_file.write_bytes(foreign_row)

        def _bind_foreign_registry(receipt: dict[str, Any]) -> None:
            coverage = receipt["ledger"]["all_compute_coverage"]
            coverage["registry_prefix_sha256"] = hashlib.sha256(foreign_row).hexdigest()
            coverage["registry_rows"] = 1

        _e5_defect(
            _e5_case(_bind_foreign_registry),
            "no registry row names the selected run/root identity",
        )
        registry_file.write_bytes(original_registry)

        # Item 5: a second energy producer receipt on disk is ambiguous evidence,
        # even when the receipt names the "good" one.
        (e5_run / "old-energy-proxy.json").write_bytes((e5_run / "energy-proxy-receipt.json").read_bytes())
        _e5_defect(_e5_case(), "ambiguous evidence")
        (e5_run / "old-energy-proxy.json").unlink()

        # Item 5: a quarantined producer receipt named explicitly (correct sha)
        # never validates -- quarantine is excluded from evidence discovery.
        energy_bytes = (e5_run / "energy-proxy-receipt.json").read_bytes()
        quarantined_energy = e5_run / "artifacts" / "checkpoints" / ".checkpoint-quarantine" / "energy-proxy-receipt.json"
        quarantined_energy.write_bytes(energy_bytes)
        (e5_run / "energy-proxy-receipt.json").unlink()
        _e5_defect(_e5_case(_set(["energy_receipt_path"], str(quarantined_energy))), "no *energy-proxy*.json")
        quarantined_energy.unlink()
        (e5_run / "energy-proxy-receipt.json").write_bytes(energy_bytes)

        # Item 6: a retained failed attempt (attempt-*/ copies of runner +
        # energy receipts) neither blocks nor substitutes -- the root-level
        # evidence stays uniquely discoverable and the receipt stays MET.
        attempt_dir = e5_run / "attempt-1-CHILD_FAILED-0000Z"
        attempt_dir.mkdir()
        (attempt_dir / "disk-budget-runner-receipt.json").write_bytes(json.dumps({
            "schema_version": 7, "started_at_unix": 1786100000.0, "finished_at_unix": 1786100001.0,
        }).encode("utf-8"))
        (attempt_dir / "energy-proxy-receipt.json").write_bytes(energy_bytes)
        e5_attempt = _e5_case()
        assert e5_attempt["status"] == "MET", e5_attempt
        (attempt_dir / "disk-budget-runner-receipt.json").unlink()
        (attempt_dir / "energy-proxy-receipt.json").unlink()
        attempt_dir.rmdir()

        # Non-blocking 1: negative joules never validate (arithmetic-consistent).
        def _negative_joules(receipt):
            receipt["energy"]["gpu_joules"] = -118.0
            receipt["energy"]["total_proxy_joules"] = -118.0 + receipt["energy"]["cpu_pkg_joules"]
        _e5_defect(_e5_case(_negative_joules), "negative")

        # Non-blocking 2: a STRING cpu leg cannot silently drop from the total
        # without an excluded_components disclosure.
        def _string_cpu(receipt):
            receipt["energy"]["cpu_pkg_joules"] = "464.5"
            receipt["energy"]["total_proxy_joules"] = 118.0
        _e5_defect(_e5_case(_string_cpu), "excluded_components")

        # Non-blocking 4: the two formerly-decorative fields are bound.
        _e5_defect(_e5_case(_set(["capability", "results_receipt_path"], str(e5_run / "elsewhere.json"))), "results_receipt_path")
        _e5_defect(_e5_case(_set(["time", "source"], "telemetry ts-span")), "time.source")

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
        _write_jsonl(
            e6_met_root / "telemetry" / "train.jsonl",
            _synthetic_train_step_events(run_id="SELFTEST_E6_run", n_steps=100),
        )
        def _e6_scalar(predicted: float, measured: float) -> dict[str, Any]:
            return {"predicted": predicted, "measured": measured, "abs_error": abs(measured - predicted), "rel_error": abs(measured - predicted) / abs(predicted)}
        e6_receipt = {
            "schema_version": "ember02-forecast-recalibration/v1",
            "generator": "scripts/forecast_recalibration.py",
            "forecast_path": "docs/spec/ember02-r1-forecast-v1.json",
            "forecast_sha256": hashlib.sha256(e6_forecast_bytes).hexdigest(),
            "run_root": str(e6_met_root),
            "run_id": "SELFTEST_E6_run",
            "steps_measured": 100,
            "telemetry_sha256": _telemetry_sha256(e6_met_root),
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

        # --- E6: the headline count must be re-derived from this run's
        # telemetry, not accepted from the receipt's claimed integer ---
        e6_inflated = json.loads(json.dumps(e6_receipt))
        e6_inflated["steps_measured"] = 101
        e6_inflated_root = tmp_path / "e6_inflated_run"
        e6_inflated_root.mkdir()
        _write_jsonl(
            e6_inflated_root / "telemetry" / "train.jsonl",
            _synthetic_train_step_events(run_id="SELFTEST_E6_run", n_steps=100),
        )
        e6_inflated["run_root"] = str(e6_inflated_root)
        (e6_inflated_root / "forecast-recalibration.json").write_text(
            json.dumps(e6_inflated), encoding="utf-8"
        )
        e6_inflated_res = check_r1_e6(e6_inflated_root, thresholds, repo_root=e6_repo)
        assert e6_inflated_res["status"] == "NOT_MET", e6_inflated_res
        assert any(
            "re-derived deduped series" in defect
            for row in e6_inflated_res["components"]["candidate_validation"]
            for defect in row["defects"]
        ), e6_inflated_res

        # --- E6: a receipt naming a foreign telemetry run must refuse ---
        e6_foreign_id = json.loads(json.dumps(e6_receipt))
        e6_foreign_id["run_id"] = "SELFTEST_E6_foreign"
        e6_foreign_id_root = tmp_path / "e6_foreign_id_run"
        e6_foreign_id_root.mkdir()
        _write_jsonl(
            e6_foreign_id_root / "telemetry" / "train.jsonl",
            _synthetic_train_step_events(run_id="SELFTEST_E6_run", n_steps=100),
        )
        e6_foreign_id["run_root"] = str(e6_foreign_id_root)
        (e6_foreign_id_root / "forecast-recalibration.json").write_text(
            json.dumps(e6_foreign_id), encoding="utf-8"
        )
        e6_foreign_id_res = check_r1_e6(e6_foreign_id_root, thresholds, repo_root=e6_repo)
        assert e6_foreign_id_res["status"] == "NOT_MET", e6_foreign_id_res
        assert any(
            "selected run" in defect
            for row in e6_foreign_id_res["components"]["candidate_validation"]
            for defect in row["defects"]
        ), e6_foreign_id_res

        # --- E6: a receipt's run_id is the selector when a root contains
        # multiple valid telemetry runs; an explicit caller selector must
        # agree with that receipt identity (Niko #1604 P1). ---
        e6_multi_root = tmp_path / "e6_multi_run"
        e6_multi_root.mkdir()
        _write_jsonl(
            e6_multi_root / "telemetry" / "train.jsonl",
            _synthetic_train_step_events(run_id="SELFTEST_E6_run", n_steps=100)
            + _synthetic_train_step_events(run_id="SELFTEST_E6_other", n_steps=100),
        )
        e6_multi = json.loads(json.dumps(e6_receipt))
        e6_multi["run_root"] = str(e6_multi_root)
        e6_multi["telemetry_sha256"] = _telemetry_sha256(e6_multi_root)
        (e6_multi_root / "forecast-recalibration.json").write_text(
            json.dumps(e6_multi), encoding="utf-8"
        )
        e6_multi_valid = check_r1_e6(e6_multi_root, thresholds, repo_root=e6_repo)
        assert e6_multi_valid["status"] == "MET", e6_multi_valid
        e6_multi_mismatch = check_r1_e6(
            e6_multi_root, thresholds, repo_root=e6_repo, run_id="SELFTEST_E6_other"
        )
        assert e6_multi_mismatch["status"] == "NOT_MET", e6_multi_mismatch
        assert any(
            "run_id selector mismatch" in defect
            for row in e6_multi_mismatch["components"]["candidate_validation"]
            for defect in row["defects"]
        ), e6_multi_mismatch

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
