#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Closed-boundary frontier-receipt generator -- R1-E5 (issue #1464).

Prereg authority: docs/spec/ember02-preregistration-v1.md (pin 3d48d387) section 5.4:
"A rung receipt is an admissible closed-boundary frontier point iff: (1) ledger
complete, failed work included; (2) fixed-prior manifest hash-verified +
learned-import attestation; (3) capability leg -- frozen held-out eval bound to
exact checkpoint bytes, no harness/tool substitution; (4) time leg -- whole-run
wall-clock including host-side and serial work; (5) energy leg -- integrated
proxy, coverage >= T-06, boundary flag disclosed; (6) reproducibility -- config,
seeds, data cursor, recipe pinned (reproduces or names its mismatch); (7) any
advantage claim carries the matched-control delta legs ...; (8) INVARIANT stamps
F3 + F4." R1 instance (section 3): "R1-E5: first closed-boundary frontier
receipt per section 5.4 with energy_boundary: DEGRADED_PROXY".

Same fail-closed posture as scripts/forecast_recalibration.py: any leg that
cannot be assembled from evidence refuses with the missing basis NAMED, exit 2,
and NO receipt written -- a partial frontier point must never mint one.
Thresholds (T-01, T-06) are bound at runtime through r1_exit_battery
.load_thresholds, never copied.

Evidence inputs (all under the adjudicated run root unless noted):

  existing producers (bound, not re-invented):
    *energy-proxy*.json            scripts/energy_proxy_logger.py -- the receipt's
                                   "energy" object is embedded VERBATIM (section 5.3
                                   block); path + sha256 recorded beside it.
    disk-budget-runner-receipt.json  certified launch chain (certified_train_launch
                                   .py) -- started_at_ms/finished_at_ms/duration_ms
                                   = process birth to exit, host-side and serial
                                   work inclusive (the section 5.4 time leg; telemetry
                                   ts-span is an undercount and never accepted).
    checkpoint-manifest.json       checkpoint byte hashes, data_cursor, launch_seed,
                                   model_config_sha256, optimizer pins, rng state.
    e4-measurement-receipt.json    optional host-accounting evidence (R1-E4 wiring).
    telemetry *.jsonl              per-run deduped train_step series -> steps_measured,
                                   selected with the battery's own _select_series
                                   (never pooled across run_ids; --run-id names the
                                   run on resumed roots, ambiguity refuses).

  adjudicated inputs this generator DEFINES the consumer contract for
  (their producers are issue-tracked; absence is a named refusal, never a skip):
    frozen-eval-results.json       issue #1498 runner (capability leg): eval_suite_id,
                                   eval_suite_sha256, checkpoint_manifest_sha256,
                                   results {metric: {value, n_items}}, tool_access.
    human-interventions.json       operator-attested list, REQUIRED even when empty
                                   (ledger class 3; an absent file is not a zero).
    walls-checklist.json           exactly 12 rows {wall_id, verdict} against the
                                   twelve-bottleneck protocol table in docs/research/
                                   ember-artificial-physiology-closed-boundary-
                                   addendum-20260801.md (ledger class 8; prereg's
                                   "wall #10" = that table's row 10, Residency).
    reproduction-adjudication.json {status: REPRODUCED|MISMATCH, mismatch,
                                   evidence_ref} -- R1 basis: the R1-E3 round-trip
                                   receipt plus the resume-run comparison (run C).
    receipts/run-attempts.jsonl    repo-level append-only launch-attempt registry
                                   (issue #1497) -- "failed work included" is
                                   unattestable from a single run root without it;
                                   every live running row for this exact run/root
                                   must precede exactly one matching terminal row,
                                   while canonical terminal-only backfills remain
                                   accepted as historical evidence.
                                   The receipt binds the exact non-empty row
                                   prefix it read, so later append-only launches
                                   do not invalidate an already minted receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "ember02-frontier-receipt/v1"
GENERATOR = "scripts/frontier_receipt.py"
RUNG = "R1"
REPO_ROOT = Path(__file__).resolve().parents[1]

GOAL_ID = "EMBER-02"
WORKSTREAM_ID = "EMBER-02A"
NEXT_EXECUTED_OUTCOME = "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"

PREREG_PATH = "docs/spec/ember02-preregistration-v1.md"
INVARIANT_PATH = "INVARIANT.md"
ADMISSION_CONFIG_PATH = "configs/ember-restart-3b.json"
TOKENIZER_RECONSTRUCTION_RECEIPT = "receipts/ember-restart-3b/tokenizer-reconstruction-issue534-v1.json"
RUN_ATTEMPTS_REGISTRY = "receipts/run-attempts.jsonl"
# Prereg line 27 t0: "the candidate's genesis receipt: the already-seen 2,048
# tokens are charged, not orphaned". The seed83 cost-calibration certificate is
# that receipt: it records the run that created the candidate (the two-step /
# 2,048-token anchor) and binds its checkpoint manifest by hash
# (receipt_binding.checkpoint_manifest_sha256 = bf20f050...). The admission-
# contract dry-run validates ENTRY later; it is a gate record, not the genesis.

# Section 5.1 class 1, quoted categories; each must attest false (a true value is a
# stopped program, not a receipt field -- "fail-closed on unknown provenance").
ATTESTATION_CATEGORIES = (
    "imported_learned_weights",
    "imported_embeddings",
    "learned_parameter_tokenizers",
    "teacher_outputs",
    "learned_filters_judges",
    "hidden_accelerator_services",
)

# Section 5.1 class 7, the ten quoted compute components.
COMPUTE_COMPONENTS = (
    "training", "validation", "tools", "environments", "judging",
    "search", "retrieval", "rollouts", "test_time_reasoning", "final_evaluation",
)

# The twelve-bottleneck protocol table (docs/research/ember-artificial-physiology-
# closed-boundary-addendum-20260801.md, section "The twelve bottlenecks become an
# experimental protocol"). NOT the B1-B5 bottleneck-ledger walls (issue #207) --
# that registry has five rows and is a different namespace; prereg line 62's
# "byte-level state inventory, wall #10" matches THIS table's row 10 verbatim.
WALL_IDS = (
    "1-metric", "2-accounting", "3-theory-disclosure", "4-data",
    "5-objective-verifier", "6-transfer-persistence", "7-optimization",
    "8-architecture-capacity", "9-composition", "10-residency",
    "11-roofline-numerics", "12-seriality-iteration",
)
WALL_VERDICTS = ("green", "red", "not_probed")


class FrontierRefusal(RuntimeError):
    """Raised with a named reason whenever a leg cannot be assembled from evidence."""


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_registry_rows_and_prefix(path: Path) -> tuple[list[dict[str, Any]], bytes]:
    """Read registry rows and retain the exact bytes through the last row read.

    Blank lines after the last non-empty row are outside the bound. Bytes before
    and between rows remain part of the prefix, preserving append-only receipt
    semantics without normalizing line endings or JSON whitespace.
    """
    raw = path.read_bytes()
    rows: list[dict[str, Any]] = []
    prefix_end = 0
    cursor = 0
    for line_number, raw_line in enumerate(raw.splitlines(keepends=True), 1):
        cursor += len(raw_line)
        try:
            line = raw_line.decode("utf-8")
        except UnicodeDecodeError as error:
            raise FrontierRefusal(
                f"LEDGER_INCOMPLETE:all_compute_coverage: registry line {line_number} is not UTF-8: {error}"
            ) from error
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as error:
            raise FrontierRefusal(
                f"LEDGER_INCOMPLETE:all_compute_coverage: registry line {line_number} unparseable: {error}"
            ) from error
        if not isinstance(row, dict):
            raise FrontierRefusal(
                f"LEDGER_INCOMPLETE:all_compute_coverage: registry line {line_number} is not a JSON object "
                "-- a scalar line is not an attempt record (rev-1490 item 4)"
            )
        rows.append(row)
        prefix_end = cursor
    return rows, raw[:prefix_end]


def _read_json(path: Path, what: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise FrontierRefusal(f"{what}_UNREADABLE: {path}: {error}") from error


def _repo_file(rel: str, what: str) -> Path:
    path = REPO_ROOT / rel
    if not path.is_file():
        raise FrontierRefusal(f"{what}_MISSING: {path}")
    return path


def _battery():
    """Import the battery module once; thresholds/pins live there, never copied."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import r1_exit_battery
    return r1_exit_battery


def _genesis_receipt_path() -> str:
    """Resolve the validator's pinned predecessor; never duplicate its path."""
    return _battery().E5_GENESIS_RECEIPT_PATH


def _validate_predecessor(predecessor_rel: str) -> str:
    expected = Path(_genesis_receipt_path()).as_posix()
    candidate = Path(predecessor_rel).as_posix()
    if candidate != expected:
        raise FrontierRefusal(
            f"PREDECESSOR_REFUSED: {candidate!r} is not the pinned genesis "
            f"receipt {expected!r}"
        )
    return expected


def _excluded_from_evidence(path: Path, run_root: Path) -> bool:
    """Twin of r1_exit_battery._evidence_excluded, kept in agreement (rev-1490
    E5 item 6: both modules must resolve the retained-failed-attempt shape the
    same way): nothing under .checkpoint-quarantine or a preserved attempt-*/
    dir serves as evidence -- a failed attempt's receipts are history, and a
    run that retained one must stay mintable from its root-level evidence."""
    try:
        relative_parts = path.relative_to(run_root).parts
    except ValueError:
        return True
    return any(
        part == ".checkpoint-quarantine" or part.startswith("attempt-")
        for part in relative_parts
    )


def _find_one(run_root: Path, pattern: str, what: str, needs: str) -> Path:
    candidates = sorted(
        p for p in run_root.rglob(pattern) if not _excluded_from_evidence(p, run_root)
    )
    if not candidates:
        raise FrontierRefusal(f"{what}: no {pattern} under {run_root} ({needs})")
    if len(candidates) > 1:
        raise FrontierRefusal(
            f"{what}_AMBIGUOUS: multiple {pattern} under the run root: "
            + ", ".join(str(p) for p in candidates)
        )
    return candidates[0]


# --- envelope -----------------------------------------------------------------

def bind_document(rel: str, what: str) -> dict[str, str]:
    path = _repo_file(rel, what)
    return {"path": rel, "sha256": _sha256(path)}


def measured_series(battery, run_root: Path, t01: int, run_id: str | None) -> tuple[str, int]:
    """Steps are counted with the battery's own per-run selection
    (_select_series), never pooled across run_ids: on a resumed root a
    pooled count is a step count no single run reached, and the validator
    re-derives against the SELECTED series (rev-1490 items 1+2). Returns
    (selected run_id, deduped series length)."""
    selected_run_id, series, counts = battery._select_series(run_root, run_id=run_id)
    if not series:
        if selected_run_id is None and len(counts) > 1:
            raise FrontierRefusal(
                f"AMBIGUOUS_RUN_ID: multiple telemetry run_ids under {run_root} "
                f"({counts!r}); pass --run-id to name the adjudicated run"
            )
        raise FrontierRefusal(
            f"UNMEASURABLE_STEPS: no train_step telemetry for run_id={run_id!r} "
            f"under {run_root} (run_ids_seen={counts!r})"
        )
    if len(series) < t01:
        raise FrontierRefusal(
            f"STEPS_BELOW_T01: run {selected_run_id!r} series has {len(series)} "
            f"deduped steps, below T-01={t01}"
        )
    return selected_run_id, len(series)


# --- leg 2: fixed prior + learned-import attestation --------------------------

def leg_fixed_prior(battery) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest_path = Path(battery.DEFAULT_FIXED_PRIOR_MANIFEST)
    if not manifest_path.is_file():
        raise FrontierRefusal(f"FIXED_PRIOR_MANIFEST_MISSING: {manifest_path}")
    doc = _read_json(manifest_path, "FIXED_PRIOR_MANIFEST")
    attestation_text = doc.get("learned_import_attestation")
    items = doc.get("items")
    if not isinstance(attestation_text, str) or not attestation_text.strip():
        raise FrontierRefusal(
            "ATTESTATION_UNKNOWN_PROVENANCE: fixed-prior manifest carries no "
            "learned_import_attestation statement"
        )
    if not isinstance(items, list) or not items:
        raise FrontierRefusal("ATTESTATION_UNKNOWN_PROVENANCE: fixed-prior manifest has no items")
    for i, item in enumerate(items):
        if not isinstance(item, dict) or not item.get("provenance"):
            raise FrontierRefusal(
                f"ATTESTATION_UNKNOWN_PROVENANCE: fixed-prior item {i} lacks a provenance line "
                "-- section 5.1 class 1 is fail-closed on unknown provenance"
            )
        # The pin field is per-kind (the manifest's own schema): file bytes are
        # sha-pinned, versions are pinned by their EXECUTED probe output, trees by
        # a combined digest, and external byte sets carry a null sha with the
        # provenance line disclosing where the bytes live.
        kind = item.get("kind")
        probe = item.get("probe") if isinstance(item.get("probe"), dict) else {}
        pinned = (
            (kind == "file" and bool(item.get("sha256")))
            or (kind == "version" and probe.get("ok") is True and bool(probe.get("output")))
            or (kind == "tree" and bool(item.get("combined_sha256")))
            or (kind == "external")
        )
        if not pinned:
            raise FrontierRefusal(
                f"ATTESTATION_UNKNOWN_PROVENANCE: fixed-prior item {i} (kind={kind!r}) carries "
                "no pin for its kind (file:sha256, version:ok probe output, tree:combined_sha256)"
            )
    rel = manifest_path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    fixed_prior = {"manifest_path": rel, "manifest_sha256": _sha256(manifest_path)}
    attestation: dict[str, Any] = {category: False for category in ATTESTATION_CATEGORIES}
    attestation["basis"] = (
        f"fixed-prior manifest ({rel}) learned_import_attestation statement plus "
        f"{len(items)} per-item provenance lines (file/tree items hash-pinned, versions "
        "probe-pinned, external byte sets disclosed by provenance)"
    )
    return fixed_prior, attestation


# --- leg 3: capability --------------------------------------------------------

def leg_capability(run_root: Path, manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    path = _find_one(
        run_root, "frozen-eval-results.json", "UNMEASURABLE_CAPABILITY",
        "the frozen cheap-probe battery has not been run against this checkpoint -- issue #1498",
    )
    doc = _read_json(path, "UNMEASURABLE_CAPABILITY")
    for key in ("eval_suite_id", "eval_suite_sha256", "checkpoint_manifest_sha256", "results"):
        if not doc.get(key):
            raise FrontierRefusal(f"UNMEASURABLE_CAPABILITY: {path} lacks {key}")
    manifest_sha = _sha256(manifest_path)
    if doc["checkpoint_manifest_sha256"] != manifest_sha:
        raise FrontierRefusal(
            "CHECKPOINT_BYTES_UNBOUND: frozen-eval results bind checkpoint manifest "
            f"{doc['checkpoint_manifest_sha256'][:12]}..., this run root's manifest is "
            f"{manifest_sha[:12]}... -- one run's eval must not credit another's checkpoint"
        )
    results = doc["results"]
    if not isinstance(results, dict) or not results:
        raise FrontierRefusal(f"UNMEASURABLE_CAPABILITY: {path} results is not a non-empty mapping")
    for metric, entry in results.items():
        if not isinstance(entry, dict) or not _finite(entry.get("value")):
            raise FrontierRefusal(
                f"UNMEASURABLE_CAPABILITY: results[{metric!r}] lacks a finite value -- "
                "no missing result is converted into completion"
            )
    tool_access = doc.get("tool_access")
    if tool_access != "none":
        raise FrontierRefusal(
            f"UNMEASURABLE_CAPABILITY: tool_access is {tool_access!r}, need 'none' at R1 "
            "(section 5.4 leg 3: no harness/tool substitution)"
        )
    checkpoint_hashes = {
        key: manifest[key]
        for key in ("shared_model_shard_sha256", "expert_checkpoint_sha256",
                    "optimizer_state_shard_sha256", "rng_state_sha256")
        if key in manifest
    }
    if not checkpoint_hashes:
        raise FrontierRefusal("CHECKPOINT_BYTES_UNBOUND: checkpoint manifest carries no shard sha256 fields")
    return {
        "eval_suite_id": doc["eval_suite_id"],
        "eval_suite_sha256": doc["eval_suite_sha256"],
        "results_receipt_path": str(path),
        "results_receipt_sha256": _sha256(path),
        "checkpoint_manifest_sha256": manifest_sha,
        "checkpoint_file_sha256s": checkpoint_hashes,
        "results": results,
        "tool_access": "none",
        # F7's probe column is "R4 + any claim"; with advantage_claims [] and
        # tool_access none there is no claim for the ablation to probe yet.
        "model_only_ablation": None,
    }


# --- leg 4: time --------------------------------------------------------------

def leg_time(run_root: Path) -> dict[str, Any]:
    path = _find_one(
        run_root, "disk-budget-runner-receipt.json", "UNMEASURABLE_WALL_CLOCK",
        "the certified launch chain writes started_at_unix/finished_at_unix; a run "
        "without its runner receipt has no process-level wall clock",
    )
    doc = _read_json(path, "UNMEASURABLE_WALL_CLOCK")
    # The REAL producer contract (read from the canary root's schema_version-7
    # receipt, 2026-08-06): float unix SECONDS in started_at_unix /
    # finished_at_unix. The first transcription invented started_at_ms /
    # finished_at_ms / duration_ms fields no producer writes -- every real
    # root refused (the rev-1490 item-6 unmintability class, caught by
    # probing the canary root after the attempt-dir cure).
    started, finished = doc.get("started_at_unix"), doc.get("finished_at_unix")
    if not (_finite(started) and _finite(finished)):
        raise FrontierRefusal(
            f"UNMEASURABLE_WALL_CLOCK: {path} lacks finite started_at_unix/finished_at_unix"
        )
    if finished < started:
        raise FrontierRefusal(f"UNMEASURABLE_WALL_CLOCK: finished_at_unix precedes started_at_unix in {path}")
    def iso(unix_s: float) -> str:
        return datetime.fromtimestamp(unix_s, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    return {
        "run_start_utc": iso(started),
        "run_end_utc": iso(finished),
        "wall_clock_seconds": finished - started,
        "coverage": "process_birth_to_exit",
        "source": f"{path.name} started_at_unix/finished_at_unix (certified launch chain runner receipt)",
        "runner_receipt_sha256": _sha256(path),
    }


# --- leg 5: energy ------------------------------------------------------------

def leg_energy(run_root: Path, t06: float) -> dict[str, Any]:
    path = _find_one(
        run_root, "*energy-proxy*.json", "UNMEASURABLE_ENERGY",
        "scripts/energy_proxy_logger.py was not invoked for this run",
    )
    doc = _read_json(path, "UNMEASURABLE_ENERGY")
    block = doc.get("energy")
    if not isinstance(block, dict):
        raise FrontierRefusal(f"UNMEASURABLE_ENERGY: {path} has no nested energy block (section 5.3)")
    boundary = block.get("energy_boundary")
    if boundary != "DEGRADED_PROXY":
        raise FrontierRefusal(
            f"ENERGY_BOUNDARY_MISMATCH: {boundary!r}, need 'DEGRADED_PROXY' "
            "(prereg: R1-E5 ships with energy_boundary DEGRADED_PROXY; the boundary is permanent)"
        )
    coverage = block.get("sample_coverage_fraction")
    if not _finite(coverage) or not (0.0 <= coverage <= 1.0):
        raise FrontierRefusal(f"UNMEASURABLE_ENERGY: sample_coverage_fraction {coverage!r} is not in [0,1]")
    if coverage < t06:
        raise FrontierRefusal(
            f"ENERGY_COVERAGE_BELOW_T06: {coverage} < {t06} -- an unmetered run is not a frontier point"
        )
    gpu_j, cpu_j, total_j = block.get("gpu_joules"), block.get("cpu_pkg_joules"), block.get("total_proxy_joules")
    if not _finite(gpu_j) or not _finite(total_j):
        raise FrontierRefusal("UNMEASURABLE_ENERGY: gpu_joules/total_proxy_joules not finite")
    if gpu_j < 0 or total_j < 0 or (_finite(cpu_j) and cpu_j < 0):
        raise FrontierRefusal(
            f"ENERGY_ARITHMETIC_INCONSISTENT: negative joules (gpu={gpu_j!r}, cpu={cpu_j!r}, "
            f"total={total_j!r}) -- integrated energy cannot be below zero"
        )
    expected_total = gpu_j + (cpu_j if _finite(cpu_j) else 0.0)
    if abs(total_j - expected_total) > 1e-9 * max(1.0, abs(expected_total)):
        raise FrontierRefusal(
            f"ENERGY_ARITHMETIC_INCONSISTENT: total_proxy_joules {total_j} != gpu + cpu legs {expected_total}"
        )
    if not _finite(cpu_j):
        # `is None` alone let a STRING-typed cpu leg drop from the total with
        # no disclosure (rev-1490 non-blocking 2): any non-numeric cpu leg
        # must be disclosed as excluded.
        excluded = block.get("excluded_components")
        if not isinstance(excluded, list) or not any(
            isinstance(e, str) and e.lower().startswith("cpu package") for e in excluded
        ):
            raise FrontierRefusal(
                f"ENERGY_ARITHMETIC_INCONSISTENT: cpu_pkg_joules is not a finite number ({cpu_j!r}) "
                "but 'CPU package' is not disclosed in excluded_components (energy_proxy_logger contract)"
            )
    return {
        "energy": block,  # the producer's section-5.3 block, embedded verbatim
        "energy_receipt_path": str(path),
        "energy_receipt_sha256": _sha256(path),
    }


# --- leg 6: reproducibility ---------------------------------------------------

def leg_reproducibility(run_root: Path, manifest: dict[str, Any], fixed_prior: dict[str, Any]) -> dict[str, Any]:
    pins: dict[str, Any] = {}
    for field, key in (
        ("config_sha256", "model_config_sha256"),
        ("optimizer_state_sha256", "optimizer_state_shard_sha256"),
        ("rng_state_sha256", "rng_state_sha256"),
    ):
        value = manifest.get(key)
        if not value:
            raise FrontierRefusal(f"REPRODUCIBILITY_PINS_MISSING: checkpoint manifest lacks {key}")
        pins[field] = value
    optimizer_contract = manifest.get("optimizer_contract")
    if not optimizer_contract:
        raise FrontierRefusal("REPRODUCIBILITY_PINS_MISSING: checkpoint manifest lacks optimizer_contract")
    seed = manifest.get("launch_seed")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise FrontierRefusal("REPRODUCIBILITY_PINS_MISSING: checkpoint manifest lacks integer launch_seed")
    cursor = manifest.get("data_cursor")
    if not isinstance(cursor, dict) or not _finite(cursor.get("tokens_seen")) or not _finite(cursor.get("global_step")):
        raise FrontierRefusal("REPRODUCIBILITY_PINS_MISSING: checkpoint manifest data_cursor incomplete")
    tokenizer_receipt = _repo_file(TOKENIZER_RECONSTRUCTION_RECEIPT, "REPRODUCIBILITY_PINS_MISSING:tokenizer")
    adjudication_path = run_root / "reproduction-adjudication.json"
    if not adjudication_path.is_file():
        raise FrontierRefusal(
            "REPRODUCTION_UNADJUDICATED: no reproduction-adjudication.json under the run root -- "
            "'(reproduces or names its mismatch)' admits exactly REPRODUCED-with-evidence or a "
            "named MISMATCH; the R1 basis is the R1-E3 round-trip receipt plus the resume-run "
            "(run C) comparison"
        )
    adjudication = _read_json(adjudication_path, "REPRODUCTION_UNADJUDICATED")
    status = adjudication.get("status")
    if status not in ("REPRODUCED", "MISMATCH"):
        raise FrontierRefusal(f"REPRODUCTION_UNADJUDICATED: status {status!r} is neither REPRODUCED nor MISMATCH")
    if status == "MISMATCH" and not adjudication.get("mismatch"):
        raise FrontierRefusal("REPRODUCTION_UNADJUDICATED: MISMATCH status without a named mismatch")
    if not adjudication.get("evidence_ref"):
        raise FrontierRefusal("REPRODUCTION_UNADJUDICATED: adjudication carries no evidence_ref")
    return {
        **pins,
        "optimizer_contract": optimizer_contract,
        "tokenizer_reconstruction_receipt": {
            "path": TOKENIZER_RECONSTRUCTION_RECEIPT,
            "sha256": _sha256(tokenizer_receipt),
        },
        "seeds": [seed],
        "data_cursor": {
            "tokens_seen": cursor["tokens_seen"],
            "global_step": cursor["global_step"],
            "resume_authority": cursor.get("resume_authority"),
        },
        "recipe_ref": fixed_prior["manifest_sha256"],
        "reproduction": {
            "status": status,
            "mismatch": adjudication.get("mismatch"),
            "evidence_ref": adjudication["evidence_ref"],
            "adjudication_sha256": _sha256(adjudication_path),
        },
    }


# --- leg 1: the nine-class ledger ---------------------------------------------

def ledger_human_interventions(run_root: Path) -> dict[str, Any]:
    path = run_root / "human-interventions.json"
    if not path.is_file():
        raise FrontierRefusal(
            "LEDGER_INCOMPLETE:human_interventions: no human-interventions.json under the run "
            "root -- an explicit empty list is evidence, an absent file is not a zero"
        )
    rows = _read_json(path, "LEDGER_INCOMPLETE:human_interventions")
    if not isinstance(rows, list):
        raise FrontierRefusal("LEDGER_INCOMPLETE:human_interventions: file is not a list")
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or not all(
            row.get(k) for k in ("action_class", "actor_role", "ts_utc", "description")
        ):
            raise FrontierRefusal(
                f"LEDGER_INCOMPLETE:human_interventions: row {i} lacks "
                "action_class/actor_role/ts_utc/description"
            )
    return {
        "interventions": rows,
        "attestation": "operator-attested record; empty list = zero interventions this rung",
        "source_sha256": _sha256(path),
    }


def ledger_data_accounting(manifest: dict[str, Any], fixed_prior: dict[str, Any]) -> dict[str, Any]:
    cursor = manifest["data_cursor"]
    return {
        "tokens_seen": cursor["tokens_seen"],
        "acquisition_this_rung": "none",
        "attestation": (
            "R1 trains on the frozen preregistered stream only; no acquisition, dedup, or "
            "curation op occurred this rung. Corpora provenance is pinned in the fixed-prior "
            "manifest; the candidate's pre-rung 2,048 tokens are charged at t0 via the genesis "
            "receipt (prereg: 'the already-seen 2,048 tokens are charged, not orphaned')."
        ),
        "corpora_evidence_ref": fixed_prior["manifest_path"],
        "synthetic_ancestry_graph_ref": None,
        "retained_originals": True,
    }


def ledger_host_accounting(run_root: Path) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "offload_bytes": None,
        "not_measured": {},
    }
    e4_candidates = sorted(
        p for p in run_root.rglob("e4-measurement-receipt.json") if not _excluded_from_evidence(p, run_root)
    )
    if len(e4_candidates) == 1:
        e4 = _read_json(e4_candidates[0], "LEDGER_INCOMPLETE:host_accounting")
        host = e4.get("host_utilization") or {}
        vram = e4.get("peak_vram") or {}
        entry["cpu_process_seconds"] = host.get("process_cpu_seconds")
        entry["cpu_process_fraction"] = host.get("process_cpu_fraction")
        entry["gpu_vram_peak_bytes"] = vram.get("allocated_bytes")
        entry["evidence_ref"] = str(e4_candidates[0])
    else:
        entry["not_measured"]["cpu_gpu_utilization"] = (
            "no single e4-measurement-receipt.json under the run root (R1-E4 wiring)"
        )
    for field, reason in (
        ("ram_peak", "no host-RAM producer exists on the certified path yet"),
        ("storage_io", "no storage-IO producer exists on the certified path yet"),
        ("network_io", "no network-IO producer exists on the certified path yet"),
        ("checkpoint_overhead_s", "per-phase overhead split not yet separated from wall clock"),
        ("failure_overhead_s", "charged at registry level (run-attempts), not split per run yet"),
    ):
        entry["not_measured"][field] = reason
    return entry


def ledger_all_compute_coverage(run_root: Path, run_id: str, manifest_sha: str) -> dict[str, Any]:
    registry_path = REPO_ROOT / RUN_ATTEMPTS_REGISTRY
    if not registry_path.is_file():
        raise FrontierRefusal(
            "LEDGER_INCOMPLETE:all_compute_coverage: no run-attempt registry at "
            f"{RUN_ATTEMPTS_REGISTRY} -- 'failed work included' is unattestable from a single "
            "run root; the registry (issue #1497) must enumerate failed/aborted attempts"
        )
    rows, registry_prefix = _read_registry_rows_and_prefix(registry_path)
    if not rows:
        raise FrontierRefusal("LEDGER_INCOMPLETE:all_compute_coverage: run-attempt registry is empty")

    completion_defects = _battery().validate_run_attempt_completion(
        rows,
        selected_run_id=run_id,
        run_root=run_root,
        bound_row_count=len(rows),
    )
    if completion_defects:
        raise FrontierRefusal(
            "LEDGER_INCOMPLETE:all_compute_coverage: " + "; ".join(completion_defects)
        )
    components = {}
    for component in COMPUTE_COMPONENTS:
        included = component in ("training", "validation", "final_evaluation")
        components[component] = {
            "included": included,
            "evidence_ref": RUN_ATTEMPTS_REGISTRY if included else None,
            "note": None if included else "component not exercised at R1 (no tool/search/rollout work on the R1 path)",
        }
    return {
        "components": components,
        "failed_work_included": True,
        "registry_path": RUN_ATTEMPTS_REGISTRY,
        "registry_prefix_sha256": hashlib.sha256(registry_prefix).hexdigest(),
        "registry_rows": len(rows),
    }


def ledger_walls_checklist(run_root: Path) -> dict[str, Any]:
    path = run_root / "walls-checklist.json"
    if not path.is_file():
        raise FrontierRefusal(
            "LEDGER_INCOMPLETE:walls_checklist: no walls-checklist.json under the run root -- "
            "the twelve-bottleneck protocol rows must each carry green/red/not_probed for the rung"
        )
    rows = _read_json(path, "LEDGER_INCOMPLETE:walls_checklist")
    if not isinstance(rows, list) or len(rows) != 12:
        raise FrontierRefusal(
            f"LEDGER_INCOMPLETE:walls_checklist: expected exactly 12 rows, found "
            f"{len(rows) if isinstance(rows, list) else type(rows).__name__}"
        )
    seen = []
    for row in rows:
        wall_id, verdict = (row.get("wall_id"), row.get("verdict")) if isinstance(row, dict) else (None, None)
        if wall_id not in WALL_IDS:
            raise FrontierRefusal(f"LEDGER_INCOMPLETE:walls_checklist: unknown wall_id {wall_id!r}")
        if verdict not in WALL_VERDICTS:
            raise FrontierRefusal(
                f"LEDGER_INCOMPLETE:walls_checklist: wall {wall_id} verdict {verdict!r} "
                f"not in {WALL_VERDICTS}"
            )
        seen.append(wall_id)
    if sorted(seen) != sorted(WALL_IDS):
        raise FrontierRefusal("LEDGER_INCOMPLETE:walls_checklist: rows do not cover the twelve wall ids exactly once")
    return {"rows": rows, "source_sha256": _sha256(path)}


# --- leg 8: invariant stamps --------------------------------------------------

def leg_invariant(predecessor_rel: str) -> tuple[dict[str, str], dict[str, str]]:
    invariant = bind_document(INVARIANT_PATH, "INVARIANT_STAMP")
    predecessor_path = _repo_file(predecessor_rel, "PREDECESSOR_UNRESOLVED")
    stamp = {"invariant_md_sha256": invariant["sha256"]}
    predecessor = {"path": predecessor_rel, "sha256": _sha256(predecessor_path)}
    return stamp, predecessor


# --- assembly -----------------------------------------------------------------

def build_receipt(run_root: Path, predecessor_rel: str, run_id: str | None = None) -> dict[str, Any]:
    predecessor_rel = _validate_predecessor(predecessor_rel)
    battery = _battery()
    thresholds, _ = battery.load_thresholds()
    t01, t06 = int(thresholds["T-01"]), float(thresholds["T-06"])

    # The battery's own finder (artifacts/checkpoints/*/): generator and
    # validator now discover the manifest the same way, so a root where they
    # would disagree cannot exist (rev-1490 item 6's agreement requirement --
    # previously the generator rglob'd via forecast_recalibration and the two
    # modules resolved multi-manifest roots in opposite directions).
    try:
        manifest_path = battery.find_checkpoint_manifest(run_root)
    except battery.R1ExitBatteryRefusal as error:
        raise FrontierRefusal(str(error)) from error
    manifest = _read_json(manifest_path, "CHECKPOINT_MANIFEST")
    if not isinstance(manifest, dict):
        raise FrontierRefusal(f"CHECKPOINT_MANIFEST: {manifest_path} top level is not a JSON object")

    selected_run_id, steps = measured_series(battery, run_root, t01, run_id)
    fixed_prior, attestation = leg_fixed_prior(battery)
    capability = leg_capability(run_root, manifest_path, manifest)
    time_leg = leg_time(run_root)
    energy = leg_energy(run_root, t06)
    reproducibility = leg_reproducibility(run_root, manifest, fixed_prior)
    invariant_stamp, predecessor = leg_invariant(predecessor_rel)

    ledger = {
        "learned_import_attestation_ref": "see learned_import_attestation (leg 2)",
        "fixed_prior_manifest_ref": fixed_prior["manifest_path"],
        "human_interventions": ledger_human_interventions(run_root),
        "data_accounting": ledger_data_accounting(manifest, fixed_prior),
        "host_accounting": ledger_host_accounting(run_root),
        "energy_ref": "see energy (leg 5), embedded verbatim from the producer receipt",
        "all_compute_coverage": ledger_all_compute_coverage(
            run_root, selected_run_id, capability["checkpoint_manifest_sha256"]),
        "walls_checklist": ledger_walls_checklist(run_root),
        "identity_spine_ref": "see identity_spine (envelope)",
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "generator": GENERATOR,
        "rung": RUNG,
        "run_root": str(run_root),
        "run_id": selected_run_id,
        "steps_measured": steps,
        "prereg": bind_document(PREREG_PATH, "PREREG"),
        "admission_config": bind_document(ADMISSION_CONFIG_PATH, "ADMISSION_CONFIG"),
        "identity_spine": {
            "goal_id": GOAL_ID,
            "workstream_id": WORKSTREAM_ID,
            "next_executed_outcome": NEXT_EXECUTED_OUTCOME,
            "checkpoint_manifest_sha256": capability["checkpoint_manifest_sha256"],
            "checkpoint_file_sha256s": capability["checkpoint_file_sha256s"],
        },
        "ledger": ledger,
        "fixed_prior": fixed_prior,
        "learned_import_attestation": attestation,
        "capability": capability,
        "time": time_leg,
        **energy,
        "reproducibility": reproducibility,
        # Section 4.4 freezes R1's receipted comparison at "None (canary + measurement
        # baselines)": presence-of-empty is the attestation, and any claim at R1 has
        # no admissible comparison to bind (ADVANTAGE_CLAIM_INADMISSIBLE_AT_R1).
        "advantage_claims": [],
        "invariant_stamp": invariant_stamp,
        "predecessor_receipt": predecessor,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=None,
                        help="receipt path (default: <run-root>/frontier-receipt.json)")
    parser.add_argument("--predecessor", type=str, default=_genesis_receipt_path(),
                        help="repo-relative predecessor receipt (default: the candidate's genesis receipt; "
                             "the R1 battery validator pins exactly the default -- an override refuses at adjudication)")
    parser.add_argument("--run-id", type=str, default=None,
                        help="explicit telemetry run_id to describe (default: the single run_id present; "
                             "multiple run_ids without this flag refuse -- a pooled step count is minted by no run)")
    args = parser.parse_args()

    out_path = args.out or (args.run_root / "frontier-receipt.json")
    try:
        receipt = build_receipt(args.run_root, args.predecessor, args.run_id)
    except FrontierRefusal as refusal:
        print(f"frontier_receipt: REFUSED: {refusal}", file=sys.stderr)
        print("no receipt written -- a partial frontier point must never mint one", file=sys.stderr)
        return 2
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"frontier receipt written: {out_path}")
    print(f"  rung {receipt['rung']}, run_id {receipt['run_id']}, steps_measured {receipt['steps_measured']}, "
          f"energy_boundary {receipt['energy']['energy_boundary']}, "
          f"wall_clock_s {receipt['time']['wall_clock_seconds']:.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
