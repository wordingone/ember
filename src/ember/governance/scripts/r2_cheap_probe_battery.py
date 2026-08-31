#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""r2_cheap_probe_battery.py -- EMBER-02 R2 (CAPABLE-1k) frozen cheap-probe
battery runner (issue #1435).

============================================================================
CURRENT D-04 AUTHORITY (#1498): the accepted battery is the exact hash-pinned
text manifest in docs/spec/ember02-r1-r2-cheap-probe-suite-v1.json.  R2 must
receive it through --source-suite and deterministically compile token IDs from
the separately hash-bound tokenizer and compiler.  DEFAULT_PROBE_REGISTRY
remains empty deliberately so omission of those bindings refuses rather than
silently substituting an implicit or independently authored token authority.
The D-03 discussion below is retained as historical rationale only.
============================================================================

docs/domains/governance/spec/ember02-preregistration-v1.md refers to "the frozen cheap-probe
battery" four times, in the present tense, as an artifact that already
exists and is already frozen:

  R2-E3 (sec3): "matched-control delta at equal budget (C3/C4/C5) on the
    frozen cheap-probe battery, adjudicated against the signal band (F-03)"
  R2-E4 (sec3): "frozen cheap-probe battery above chance with a one-sided
    lower confidence bound at level T-24 exceeding chance per probe"
  F-03  (sec8): "...on the frozen battery"
  sec6:  "this freeze binds which suites gate which rung (cheap probes at
    R2, modality probes at R3 per D-01, full suite at R4 per D-02)"

Nowhere in that document, in the companion
docs/spec/ember02-preregistration-thresholds-v1.json (whose `entries[]`
array enumerates every T-*/F-*/D-* freeze but contains zero probe rows),
or anywhere else in this repository (exhaustive repo-wide grep for
"cheap-probe", "cheap_probe", "R2-E3", "R2-E4", performed 2026-08-04) is a
single R2 probe actually named: no probe id, no prompt/context, no choice
set, no correct answer, no chance-rate baseline, no metric definition.

Contrast with R3's modality probes and R4's capability-vector thresholds,
which face the EXACT same problem (suites not built yet) but are HONEST
about it -- both are explicitly typed `frozen_form: deferred_amendment` in
the thresholds JSON, both carry a disclosed backstop (E-G) and a stated
reason ("Probe suites do not exist yet; built and frozen by a superseding
version before R3 dispatch" / "Full-suite custody staging incomplete").
D-01 and D-02 rows exist in the JSON precisely so a consumer can see they
are deferred. The R2 cheap-probe battery has no such row, no
deferred_amendment marker, and no backstop -- it is written as if frozen,
but it was never actually specified. This is a strictly worse gap than
D-01/D-02: at least those admit they don't exist yet.

Per the operating instruction for this build ("the spec is the authority;
invention is prohibited... reporting one unimplementable probe accurately
is worth more than five plausible guesses"), this script does NOT invent
probe content. `DEFAULT_PROBE_REGISTRY` below is an empty tuple, on
purpose, forever, until a superseding preregistration version (or an
amendment restoring D-01/D-02-style honesty to R2) defines the battery.

What this script implements instead is everything that IS specified, so
that the day a probe manifest exists, R2-E3/R2-E4 adjudicate in ONE
command with zero further code changes:

  * A versioned, hash-verified, fail-closed probe-manifest format
    (`load_probe_manifest`) a superseding spec's battery can be transcribed
    into directly -- probe id, per-item context/choices/correct answer,
    chance rate, metric id. See PROBE_MANIFEST_SCHEMA.
  * R2-E4 adjudication (`run_r2e4`): per probe, a one-sided lower confidence
    bound at T-24 (0.95) versus the probe's declared chance rate.
  * R2-E3 / F-03 adjudication (`run_r2e3`, `adjudicate_f03`): matched-control
    delta at equal budget between two arms, exactly reproducing F-03's three-
    way split (NO-SIGNAL / F1-pivot / positive-delta), including the R2
    adjudication-asymmetry rule (prereg sec3: "no A3-superiority claim is
    creditable from R2 alone") -- a positive A3 delta over the control is
    classified POSITIVE_DELTA_NO_R2_CREDIT, never PASS/WIN.
  * Checkpoint binding (`verify_checkpoint`): hash-verified identity of the
    real EMBER-02 v3 sparse checkpoint format, by REUSE (import, never
    reimplemented) of `ember_restart_eval_checkpoint_consumer._verify` --
    the same module the EMBER-02C workstream's own checkpoint-consuming
    eval path uses. Every receipt this script writes carries that identity;
    a run that cannot verify a checkpoint never reaches a receipt.
  * Fail-closed refusal throughout (`R2ProbeBatteryRefusal`), one distinct
    machine-readable reason per failure mode -- see the "Refusal reasons"
    list below. In particular: an EMPTY probe registry does not silently
    pass (a vacuous "0/0 probes above chance" verdict) and does not crash
    uninformatively -- it refuses with BATTERY_UNDEFINED, and (when a
    checkpoint DID verify, i.e. the run can still name its subject) that
    refusal is itself written as a receipt, so the record of "checkpoint X
    could not be adjudicated on this date because the battery is
    undefined" is durable and auditable rather than silent.
  * Receipt conventions matched to src/ember/governance/scripts/legb_inprocess_scorer.py (issue
    #757) and scripts/cbase_heldout_eval.py (issue #760): ticket/ts/
    sha_convention/invariant_sha256 envelope, `receipt_write.checked_write`
    atomic quarantine-on-invalid publication, double-run determinism proof
    on every scored item (bit-identical score vectors across two
    independent scoring calls, or DETERMINISM_MISMATCH), api_spend_usd /
    paid_api_surface_used disclosure. NOTE: this script does NOT import
    legb_inprocess_scorer.py -- it imports `timeshare_pretrain`, which
    carries `# EMBER_ARTIFACT_CLASS=historical_only` and is
    execution-denied on import (verified live 2026-08-04: `import
    legb_inprocess_scorer` raises SystemExit
    "historical_only: the sub-3B cbase trainer and every importer are
    execution-denied"). Only its documented CONVENTIONS are reused here;
    its code is retired W1-baseline (sub-3B) tooling and must not be
    imported by anything EMBER-02-scoped.

RATIFIED STATISTICAL METHOD: D-03 binds R2-E4 proportion probes to this
runner's one-sided Wilson lower confidence bound at T-24, without continuity
correction, and requires `lower_bound > chance_rate`.
Unlike F-08/F-09, which explicitly cite `sigma_credit(m)` (sec2), R2-E4 (and
D-01's backstop text, which says it "mirrors R2-E4") names only a
confidence LEVEL, not a method. The previously disclosed implementation, now
ratified by D-03, is the Wilson
score interval (scripts/power.py's `wilson()`, imported not reimplemented
-- the same tool this repo already uses for "single-arm floors" per
docs/domains/governance/archive/pre-restart/r2-prereg.md's "single-arm floors read as Wilson intervals" precedent)
for metric_type="proportion" probes, substituting the ONE-SIDED z for T-24
in place of the two-sided default. A nonparametric bootstrap path is
provided (`one_sided_lower_bootstrap`, sec2's named 10,000-resample
convention) for a future metric_type="graded" probe, but
graded scoring itself is out of scope here (see below) so it is untested
against real items -- disclosed, not silently shipped as if proven.

SCOPE BOUNDARIES (disclosed, not silent gaps):
  * Only metric_type="proportion" (multiple-choice, teacher-forced
    log-likelihood over exact token ids, the ONLY probe-scoring mechanism
    with any precedent in this repo -- score_ids_single's convention in
    the now-retired legb_inprocess_scorer.py) is wired end to end.
    metric_type="graded" is accepted by the manifest schema for forward
    compatibility but refused at scoring time
    (PROBE_METRIC_TYPE_UNSUPPORTED) -- building a generate_until/unit-test
    grading path with zero graded probes to validate it against would be
    exactly the "plausible guess" this build was told not to produce.
  * No live 3B-checkpoint forward pass is wired in this PR. `ProbeScorer`
    is a plain Protocol (`score_choices`); production wiring is "load the
    real checkpoint via verify_checkpoint's identity, build a scorer that
    honors the Protocol, pass it to run_r2e4/run_r2e3" -- deliberately left
    as the next PR's job, because there are zero probes to score against it
    today and the real v3 sparse-MoE forward pass is `ember_restart_eval_
    raw_forward.py`'s own execution-authority-gated system, which is a
    substantial, orthogonal piece of machinery. The CLI refuses
    SCORER_BACKEND_NOT_CONFIGURED if a non-empty registry is ever supplied
    without a wired scorer, rather than silently doing nothing.
  * A1/A2 arm checkpoint formats are not yet defined anywhere in this repo
    (R2 has not dispatched training as of 2026-08-04); `verify_checkpoint`
    takes a pluggable `verify_fn` (default: the v3 sparse-checkpoint
    verifier, which is what the existing A3-shaped candidate uses) so a
    future A1/A2 format is an additive adapter, not a rewrite.
  * R1-E7's sigma_seed receipt schema is not frozen anywhere either (R1-E7
    has not landed: repo-wide grep for "sigma_seed"/"R1-E7" at 2026-08-04
    hits nothing outside c8_prelaunch's unrelated MDE module and the
    preregistration text itself). `load_sigma_seed_receipt` documents and
    enforces THIS script's own minimal input contract
    (`{"sigma_seed": {"<metric_id>": <float>, ...}}`) -- a disclosed
    consumer-side contract, not an invented probe or an invented R1-E7
    schema.

Refusal reasons (R2ProbeBatteryRefusal, always prefixed onto the message):
  CHECKPOINT_MANIFEST_MISSING, CHECKPOINT_MODEL_CONFIG_MISSING,
  CHECKPOINT_VERIFY_FAILED, CHECKPOINT_UNBOUND, PROBE_MANIFEST_UNREADABLE,
  PROBE_MANIFEST_SHA_MISMATCH, PROBE_MANIFEST_SCHEMA_INVALID,
  PROBE_SPEC_INVALID, PROBE_HAS_NO_ITEMS, CHANCE_RATE_INCONSISTENT,
  PROBE_METRIC_TYPE_UNSUPPORTED,
  BATTERY_UNDEFINED, SCORER_RETURNED_WRONG_SHAPE, SCORER_RETURNED_NONFINITE,
  DETERMINISM_MISMATCH, SIGMA_SEED_MISSING, SIGMA_SEED_RECEIPT_UNREADABLE,
  SIGMA_SEED_RECEIPT_INVALID, SIGMA_SEED_INVALID, CI_INPUT_INVALID,
  SCORER_BACKEND_NOT_CONFIGURED, OUTPUT_PATH_REQUIRED.

Usage:
  python src/ember/governance/scripts/r2_cheap_probe_battery.py --selftest
  python src/ember/governance/scripts/r2_cheap_probe_battery.py --run-r2e4 \\
      --checkpoint-manifest <path>/manifest.json \\
      --model-config <path>/model_config.json --arm A3 \\
      --source-suite <path>.json --source-suite-sha256 <sha> \\
      --tokenizer domains/model/tokenizer/tokenizer.json --tokenizer-sha256 <sha> \\
      --compiler-sha256 <sha> \\
      --out receipts/r2-cheap-probe-battery/r2e4-<UTCts>.json
  python src/ember/governance/scripts/r2_cheap_probe_battery.py --run-r2e3 \\
      --checkpoint-manifest-a3 <path>/manifest.json --model-config-a3 <path>/model_config.json \\
      --checkpoint-manifest-control <path>/manifest.json --model-config-control <path>/model_config.json \\
      --control-arm A2 \\
      --source-suite <path>.json --source-suite-sha256 <sha> \\
      --tokenizer domains/model/tokenizer/tokenizer.json --tokenizer-sha256 <sha> \\
      --compiler-sha256 <sha> [--sigma-seed-receipt <path>.json] \\
      --out receipts/r2-cheap-probe-battery/r2e3-<UTCts>.json

Without --source-suite and all three exact hashes, --run-r2e4/--run-r2e3
continue to refuse BATTERY_UNDEFINED.  With D-04 authority admitted, these CLI
paths reach the separately disclosed live-scorer boundary; no capability or
exit claim exists until a named-checkpoint execution receipt is produced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

ISSUE_REF = "#1435"
AUTHORITY_ISSUE_REF = "#1498"
PREREG_DOC = "docs/domains/governance/spec/ember02-preregistration-v1.md"
PREREG_PIN = "3d48d3870919bd04cec735f68d0fad45fcfae0b2"
R2_AUTHORITY_DOC = "docs/domains/governance/spec/ember02-r2-cheap-probe-amendment-v2.json"
R2_AUTHORITY_SCHEMA = "ember02-r2-cheap-probe-amendment/v2"
R2_AUTHORITY_DECISION_ID = "D-04"

# Frozen threshold table, sec8 -- imported as VALUES here (the formula-freeze
# rule, sec2: substituting measured/frozen numbers is mechanical, not an
# amendment). These are numbers, never re-derived, never guessed.
T20_SIGNAL_BAND_MULTIPLIER = 2          # T-20
T21_KILL_BAND_MULTIPLIER = 6            # T-21 (not consumed by R2-E3/E4/F-03; carried for completeness)
T24_CONFIDENCE_LEVEL = 0.95             # T-24

# sec2's named bootstrap resample count (sigma_eval definition) -- the
# closest specified statistical primitive for graded-probe CIs; R2-E4
# itself names no resample count (see module docstring, secondary
# ambiguity).
BOOTSTRAP_RESAMPLES = 10000
DEFAULT_SEED = 83  # matches scripts/cbase_heldout_eval.py's default --seed

RECEIPT_SCHEMA = "r2-cheap-probe-battery/v1"
PROBE_MANIFEST_SCHEMA = "r2-cheap-probe-battery-manifest/v1"
SIGMA_SEED_RECEIPT_SCHEMA_NOTE = (
    "r1-e7-sigma-seed consumer contract/v1 -- R1-E7's own receipt schema is "
    "not frozen anywhere in this repo as of 2026-08-04; this is THIS "
    "script's disclosed input contract, not an invented upstream schema."
)

SHA_CONVENTION = (
    "sha256 over on-disk raw bytes (binary read, no line-ending "
    "normalization) for checkpoint/manifest/probe-manifest files"
)


class R2ProbeBatteryRefusal(Exception):
    """Fail-closed refusal (missing input, unreadable checkpoint, hash
    mismatch, undefined battery, nonfinite/nondeterministic score) -- never
    a silent skip, never a default value, never a trivial pass."""


# ---------------------------------------------------------------------------
# The blocking spec defect, machine-readable (mirrors the module docstring
# so a receipt's `spec_defects` field is self-contained -- a reader should
# never have to go read this file's docstring to understand why a receipt
# says REFUSED/BATTERY_UNDEFINED).
# ---------------------------------------------------------------------------

HISTORICAL_SPEC_DEFECTS = [
    {
        "id": "SPEC-DEFECT-1435-A",
        "severity": "BLOCKING",
        "authority_status": "DEFERRED_BY_D-03",
        "authority_path": "docs/domains/governance/spec/ember02-r2-cheap-probe-amendment-v1.json",
        "exit_criteria_affected": ["R2-E3", "R2-E4", "F-03"],
        "summary": (
            "the frozen cheap-probe battery is referenced as an existing, "
            "already-frozen artifact but its member probes are never "
            "enumerated anywhere in the tree"
        ),
        "spec_quotes": [
            "R2-E3: \"matched-control delta at equal budget (C3/C4/C5) on "
            "the frozen cheap-probe battery, adjudicated against the "
            "signal band (F-03)\"",
            "R2-E4: \"frozen cheap-probe battery above chance with a "
            "one-sided lower confidence bound at level T-24 exceeding "
            "chance per probe\"",
            "F-03: \"...on the frozen battery\"",
            "sec6: \"this freeze binds which suites gate which rung (cheap "
            "probes at R2, modality probes at R3 per D-01, full suite at "
            "R4 per D-02)\"",
        ],
        "contrast": (
            "R3-E3's modality probes (D-01) and R4-E1's capability-vector "
            "thresholds (D-02) face the identical problem (suites not "
            "built yet) but are explicitly typed frozen_form: "
            "deferred_amendment in ember02-preregistration-thresholds-v1.json, "
            "each with a disclosed backstop (E-G) and a stated reason. The "
            "The original v1 files carry no deferred_amendment row for R2. "
            "Append-only D-03 now supplies that missing authority without "
            "rewriting the frozen v1 files."
        ),
        "consequence": (
            "R2-E3 and R2-E4 cannot be adjudicated as written. This "
            "runner refuses with BATTERY_UNDEFINED rather than silently "
            "passing (a vacuous zero-probe accept) or inventing probe "
            "content."
        ),
        "remediation": (
            "D-03 requires a later accepted superseding amendment to define the "
            "battery (probe ids, per-item context/choices/correct answer, "
            "chance rate, metric id per probe) -- the same treatment D-01/"
            "D-02 already anticipate for R3/R4 -- or retype R2-E3/R2-E4 as "
            "battery before R2 dispatch. Until then BATTERY_UNDEFINED blocks "
            "R2 advancement credit and R3 funding."
        ),
    },
    {
        "id": "SPEC-DEFECT-1435-B",
        "severity": "SECONDARY",
        "authority_status": "RATIFIED_BY_D-03",
        "authority_path": "docs/domains/governance/spec/ember02-r2-cheap-probe-amendment-v1.json",
        "exit_criteria_affected": ["R2-E4"],
        "summary": (
            "R2-E4's 'one-sided lower confidence bound at level T-24' "
            "does not bind a computation method"
        ),
        "detail": (
            "Unlike F-08/F-09, which explicitly cite sigma_credit(m) per "
            "sec2, R2-E4 (and D-01's backstop text, which says it "
            "'mirrors R2-E4') names only a confidence LEVEL (T-24=0.95), "
            "never a method. D-03 now ratifies this runner's Wilson one-sided "
            "lower bound for proportion probes, without continuity correction. "
            "sec2 defines sigma_eval (bootstrap, 10,000 "
            "resamples, or exact binomial SE) for a DIFFERENT consumer "
            "(F-08/F-09 suite metrics). This runner's disclosed default: "
            "Wilson score interval (scripts/power.py wilson(), imported) "
            "for metric_type=proportion probes, one-sided by substituting "
            "the one-sided-T-24 z for the two-sided default; nonparametric "
            "bootstrap (sec2's named 10,000-resample count) for a future "
            "metric_type=graded probe. D-03 defines no graded probes and "
            "does not authorize that future path."
        ),
    },
]

# D-04/#1498 settles both D-03 defects.  Receipts created after this source
# carrier must not misreport those historical defects as active.
SPEC_DEFECTS: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# sha256 helpers
# ---------------------------------------------------------------------------

def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Probe schema (empty registry today -- see module docstring)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProbeItem:
    item_id: str
    context_ids: tuple[int, ...]
    choices: tuple[tuple[int, ...], ...]
    correct_choice_index: int

    def __post_init__(self) -> None:
        if not isinstance(self.item_id, str) or not self.item_id:
            raise R2ProbeBatteryRefusal("PROBE_SPEC_INVALID: item_id must be a nonempty string")
        if not self.choices or len(self.choices) < 2:
            raise R2ProbeBatteryRefusal(f"PROBE_SPEC_INVALID: item_id={self.item_id!r} needs >=2 choices")
        if not (0 <= self.correct_choice_index < len(self.choices)):
            raise R2ProbeBatteryRefusal(f"PROBE_SPEC_INVALID: item_id={self.item_id!r} correct_choice_index out of range")
        for choice in self.choices:
            if not choice:
                raise R2ProbeBatteryRefusal(f"PROBE_SPEC_INVALID: item_id={self.item_id!r} has an empty choice")


@dataclass(frozen=True)
class ProbeSpec:
    probe_id: str
    metric_id: str
    metric_type: str  # "proportion" | "graded" (only "proportion" is scored -- see docstring)
    chance_rate: float
    source_note: str
    items: tuple[ProbeItem, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.probe_id, str) or not self.probe_id:
            raise R2ProbeBatteryRefusal("PROBE_SPEC_INVALID: probe_id must be a nonempty string")
        if self.metric_type not in ("proportion", "graded"):
            raise R2ProbeBatteryRefusal(f"PROBE_SPEC_INVALID: probe_id={self.probe_id!r} metric_type={self.metric_type!r}")
        if not isinstance(self.chance_rate, (int, float)) or isinstance(self.chance_rate, bool) or not (0.0 <= float(self.chance_rate) <= 1.0):
            raise R2ProbeBatteryRefusal(f"PROBE_SPEC_INVALID: probe_id={self.probe_id!r} chance_rate={self.chance_rate!r}")
        if not self.items:
            raise R2ProbeBatteryRefusal(f"PROBE_HAS_NO_ITEMS: probe_id={self.probe_id!r}")
        if self.metric_type == "proportion":
            cardinalities = {len(item.choices) for item in self.items}
            if len(cardinalities) != 1:
                raise R2ProbeBatteryRefusal(
                    "CHANCE_RATE_INCONSISTENT: "
                    f"probe_id={self.probe_id!r} proportion probes require uniform "
                    f"choice cardinality; observed={sorted(cardinalities)!r}"
                )
            cardinality = next(iter(cardinalities))
            expected = 1.0 / cardinality
            if abs(float(self.chance_rate) - expected) >= 1e-12:
                raise R2ProbeBatteryRefusal(
                    "CHANCE_RATE_INCONSISTENT: "
                    f"probe_id={self.probe_id!r} chance_rate={self.chance_rate!r} "
                    f"expected=1/{cardinality}={expected!r}"
                )


# No implicit registry: D-04 requires the exact text authority plus tokenizer
# and compiler hashes on every R2 admission.  Keeping this empty makes missing
# bindings refuse BATTERY_UNDEFINED instead of creating a second authority.
DEFAULT_PROBE_REGISTRY: tuple[ProbeSpec, ...] = ()

_PROBE_MANIFEST_TOP_KEYS = {"schema", "issue", "probes"}
_PROBE_MANIFEST_PROBE_KEYS = {
    "probe_id", "metric_id", "metric_type", "chance_rate", "source_note", "items",
}
_PROBE_MANIFEST_ITEM_KEYS = {"item_id", "context_ids", "choices", "correct_choice_index"}


def load_probe_manifest(path: str | Path, expected_sha256: str) -> tuple[list[ProbeSpec], dict]:
    """Hash-verified, closed-schema loader for an external probe manifest.

    No manifest is shipped or defaulted -- see DEFAULT_PROBE_REGISTRY. This
    function exists so the day a superseding preregistration version
    defines the R2 battery, transcribing it into this JSON shape is the
    ONLY step needed before run_r2e4/run_r2e3 can adjudicate it for real.
    """
    manifest_path = Path(path)
    try:
        raw = manifest_path.read_bytes()
    except OSError as exc:
        raise R2ProbeBatteryRefusal(f"PROBE_MANIFEST_UNREADABLE: {manifest_path}: {exc}") from exc
    actual_sha256 = _sha256_bytes(raw)
    if actual_sha256 != expected_sha256:
        raise R2ProbeBatteryRefusal(
            f"PROBE_MANIFEST_SHA_MISMATCH: {manifest_path} "
            f"expected={expected_sha256} actual={actual_sha256}"
        )
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise R2ProbeBatteryRefusal(f"PROBE_MANIFEST_UNREADABLE: {manifest_path}: {exc}") from exc

    if not isinstance(doc, dict) or set(doc) != _PROBE_MANIFEST_TOP_KEYS:
        raise R2ProbeBatteryRefusal(
            f"PROBE_MANIFEST_SCHEMA_INVALID: top-level keys="
            f"{sorted(doc) if isinstance(doc, dict) else type(doc).__name__}"
        )
    if doc.get("schema") != PROBE_MANIFEST_SCHEMA:
        raise R2ProbeBatteryRefusal(
            f"PROBE_MANIFEST_SCHEMA_INVALID: schema={doc.get('schema')!r} "
            f"expected={PROBE_MANIFEST_SCHEMA!r}"
        )
    if not isinstance(doc.get("issue"), str) or not doc["issue"]:
        raise R2ProbeBatteryRefusal("PROBE_MANIFEST_SCHEMA_INVALID: 'issue' must be a nonempty string")
    probes_raw = doc.get("probes")
    if not isinstance(probes_raw, list) or not probes_raw:
        raise R2ProbeBatteryRefusal("PROBE_MANIFEST_SCHEMA_INVALID: 'probes' must be a nonempty list")

    registry: list[ProbeSpec] = []
    seen_probe_ids: set[str] = set()
    for i, row in enumerate(probes_raw):
        if not isinstance(row, dict) or set(row) != _PROBE_MANIFEST_PROBE_KEYS:
            raise R2ProbeBatteryRefusal(
                f"PROBE_MANIFEST_SCHEMA_INVALID: probes[{i}] keys="
                f"{sorted(row) if isinstance(row, dict) else type(row).__name__}"
            )
        items_raw = row.get("items")
        if not isinstance(items_raw, list) or not items_raw:
            raise R2ProbeBatteryRefusal(f"PROBE_MANIFEST_SCHEMA_INVALID: probes[{i}].items must be a nonempty list")
        items = []
        for j, item_row in enumerate(items_raw):
            if not isinstance(item_row, dict) or set(item_row) != _PROBE_MANIFEST_ITEM_KEYS:
                raise R2ProbeBatteryRefusal(
                    f"PROBE_MANIFEST_SCHEMA_INVALID: probes[{i}].items[{j}] keys="
                    f"{sorted(item_row) if isinstance(item_row, dict) else type(item_row).__name__}"
                )
            context_ids = item_row.get("context_ids")
            choices = item_row.get("choices")
            if not isinstance(context_ids, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in context_ids):
                raise R2ProbeBatteryRefusal(f"PROBE_MANIFEST_SCHEMA_INVALID: probes[{i}].items[{j}].context_ids must be a list of int")
            if not isinstance(choices, list) or not all(
                isinstance(c, list) and all(isinstance(x, int) and not isinstance(x, bool) for x in c) for c in choices
            ):
                raise R2ProbeBatteryRefusal(f"PROBE_MANIFEST_SCHEMA_INVALID: probes[{i}].items[{j}].choices must be a list of int lists")
            items.append(ProbeItem(
                item_id=item_row.get("item_id"),
                context_ids=tuple(context_ids),
                choices=tuple(tuple(c) for c in choices),
                correct_choice_index=item_row.get("correct_choice_index"),
            ))
        spec = ProbeSpec(
            probe_id=row.get("probe_id"),
            metric_id=row.get("metric_id"),
            metric_type=row.get("metric_type"),
            chance_rate=row.get("chance_rate"),
            source_note=row.get("source_note"),
            items=tuple(items),
        )
        if spec.probe_id in seen_probe_ids:
            raise R2ProbeBatteryRefusal(f"PROBE_MANIFEST_SCHEMA_INVALID: duplicate probe_id={spec.probe_id!r}")
        seen_probe_ids.add(spec.probe_id)
        registry.append(spec)

    meta = {
        "path": str(manifest_path),
        "sha256": actual_sha256,
        "schema": PROBE_MANIFEST_SCHEMA,
        "issue": doc["issue"],
        "probe_count": len(registry),
    }
    return registry, meta


def load_compiled_source_suite(
    source_path: str | Path,
    expected_source_sha256: str,
    tokenizer_path: str | Path,
    expected_tokenizer_sha256: str,
    expected_compiler_sha256: str,
) -> tuple[list[ProbeSpec], dict]:
    """Compile the sole #1498 text authority into R2 token IDs in memory."""

    from tokenizers import Tokenizer
    from r1_cheap_probe_suite import (
        SuiteRefusal,
        compile_r2_registry,
        load_source_manifest,
    )

    source_path = Path(source_path)
    tokenizer_path = Path(tokenizer_path)
    compiler_path = Path(__file__).with_name("r1_cheap_probe_suite.py")
    try:
        if _sha256_file(tokenizer_path) != expected_tokenizer_sha256:
            raise R2ProbeBatteryRefusal("TOKENIZER_SHA_MISMATCH")
        compiler_sha256 = _sha256_file(compiler_path)
        if compiler_sha256 != expected_compiler_sha256:
            raise R2ProbeBatteryRefusal("COMPILER_SHA_MISMATCH")
        source = load_source_manifest(source_path, expected_source_sha256)
        rows, binding = compile_r2_registry(
            source,
            source_manifest_sha256=expected_source_sha256,
            tokenizer=Tokenizer.from_file(str(tokenizer_path)),
            tokenizer_sha256=expected_tokenizer_sha256,
            compiler_sha256=expected_compiler_sha256,
        )
    except R2ProbeBatteryRefusal:
        raise
    except (OSError, SuiteRefusal, ValueError) as exc:
        raise R2ProbeBatteryRefusal(f"SOURCE_SUITE_COMPILE_FAILED:{exc}") from exc
    registry = [ProbeSpec(
        probe_id=row["probe_id"],
        metric_id=row["metric_id"],
        metric_type=row["metric_type"],
        chance_rate=row["chance_rate"],
        source_note=row["source_note"],
        items=tuple(ProbeItem(
            item_id=item["item_id"],
            context_ids=tuple(item["context_ids"]),
            choices=tuple(tuple(choice) for choice in item["choices"]),
            correct_choice_index=item["correct_choice_index"],
        ) for item in row["items"]),
    ) for row in rows]
    return registry, {
        "path": str(source_path),
        "schema": "ember02-r1-r2-cheap-probe-suite/v1",
        "issue": "#1498",
        "probe_count": len(registry),
        **binding,
    }


# ---------------------------------------------------------------------------
# Checkpoint binding
# ---------------------------------------------------------------------------

def verify_checkpoint(manifest_path: str | Path, model_config_path: str | Path, *, verify_fn=None) -> dict:
    """Hash-verified checkpoint identity, by reuse (never reimplemented) of
    ember_restart_eval_checkpoint_consumer's v3 sparse-checkpoint verifier
    by default. `verify_fn` is pluggable so a future A1/A2 arm checkpoint
    format (not yet defined anywhere in this repo) is an additive adapter.

    Refuses (never returns a partial/unnamed identity) if the checkpoint
    cannot be verified, or if a supplied verify_fn returns something that
    cannot name a subject (no checkpoint_manifest_sha256)."""
    manifest_path = Path(manifest_path)
    model_config_path = Path(model_config_path)
    if not manifest_path.is_file():
        raise R2ProbeBatteryRefusal(f"CHECKPOINT_MANIFEST_MISSING: {manifest_path}")
    if not model_config_path.is_file():
        raise R2ProbeBatteryRefusal(f"CHECKPOINT_MODEL_CONFIG_MISSING: {model_config_path}")

    if verify_fn is None:
        # issue2015 exact-local-import:scripts/ember_restart_eval_checkpoint_consumer.py
        import importlib.util as _ember_347eaa81a3a26359_importlib
        import sys as _ember_347eaa81a3a26359_sys
        from pathlib import Path as _ember_347eaa81a3a26359_Path
        _ember_347eaa81a3a26359_path = _ember_347eaa81a3a26359_Path(__file__).resolve().parents[4].joinpath('scripts', 'ember_restart_eval_checkpoint_consumer.py')
        if not _ember_347eaa81a3a26359_path.is_file():
            raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/ember_restart_eval_checkpoint_consumer.py')
        _ember_347eaa81a3a26359_aliases = ('_ember_issue2015_347eaa81a3a26359', 'ember_restart_eval_checkpoint_consumer', 'scripts.ember_restart_eval_checkpoint_consumer')
        _ember_347eaa81a3a26359_existing = []
        for _ember_347eaa81a3a26359_alias in _ember_347eaa81a3a26359_aliases:
            _ember_347eaa81a3a26359_candidate = _ember_347eaa81a3a26359_sys.modules.get(_ember_347eaa81a3a26359_alias)
            if _ember_347eaa81a3a26359_candidate is not None and all(_ember_347eaa81a3a26359_candidate is not item for item in _ember_347eaa81a3a26359_existing):
                _ember_347eaa81a3a26359_existing.append(_ember_347eaa81a3a26359_candidate)
        if len(_ember_347eaa81a3a26359_existing) > 1:
            raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/ember_restart_eval_checkpoint_consumer.py')
        if _ember_347eaa81a3a26359_existing:
            _ember_347eaa81a3a26359_module = _ember_347eaa81a3a26359_existing[0]
            _ember_347eaa81a3a26359_observed = getattr(_ember_347eaa81a3a26359_module, '__file__', None)
            if _ember_347eaa81a3a26359_observed is None or _ember_347eaa81a3a26359_Path(_ember_347eaa81a3a26359_observed).resolve() != _ember_347eaa81a3a26359_path:
                raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/ember_restart_eval_checkpoint_consumer.py')
        else:
            _ember_347eaa81a3a26359_spec = _ember_347eaa81a3a26359_importlib.spec_from_file_location('_ember_issue2015_347eaa81a3a26359', _ember_347eaa81a3a26359_path)
            if _ember_347eaa81a3a26359_spec is None or _ember_347eaa81a3a26359_spec.loader is None:
                raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/ember_restart_eval_checkpoint_consumer.py')
            _ember_347eaa81a3a26359_module = _ember_347eaa81a3a26359_importlib.module_from_spec(_ember_347eaa81a3a26359_spec)
            for _ember_347eaa81a3a26359_alias in _ember_347eaa81a3a26359_aliases:
                _ember_347eaa81a3a26359_prior = _ember_347eaa81a3a26359_sys.modules.get(_ember_347eaa81a3a26359_alias)
                if _ember_347eaa81a3a26359_prior is not None and _ember_347eaa81a3a26359_prior is not _ember_347eaa81a3a26359_module:
                    raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/ember_restart_eval_checkpoint_consumer.py')
                _ember_347eaa81a3a26359_sys.modules[_ember_347eaa81a3a26359_alias] = _ember_347eaa81a3a26359_module
            try:
                _ember_347eaa81a3a26359_spec.loader.exec_module(_ember_347eaa81a3a26359_module)
            except BaseException:
                for _ember_347eaa81a3a26359_alias in _ember_347eaa81a3a26359_aliases:
                    if _ember_347eaa81a3a26359_sys.modules.get(_ember_347eaa81a3a26359_alias) is _ember_347eaa81a3a26359_module:
                        _ember_347eaa81a3a26359_sys.modules.pop(_ember_347eaa81a3a26359_alias, None)
                raise
        for _ember_347eaa81a3a26359_alias in _ember_347eaa81a3a26359_aliases:
            _ember_347eaa81a3a26359_prior = _ember_347eaa81a3a26359_sys.modules.get(_ember_347eaa81a3a26359_alias)
            if _ember_347eaa81a3a26359_prior is not None and _ember_347eaa81a3a26359_prior is not _ember_347eaa81a3a26359_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/ember_restart_eval_checkpoint_consumer.py')
            _ember_347eaa81a3a26359_sys.modules[_ember_347eaa81a3a26359_alias] = _ember_347eaa81a3a26359_module
        verify_fn = getattr(_ember_347eaa81a3a26359_module, '_verify')
        # issue2015 exact-local-import-end:scripts/ember_restart_eval_checkpoint_consumer.py  # reused, never reimplemented

    try:
        identity = verify_fn(manifest_path, model_config_path)
    except (ValueError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise R2ProbeBatteryRefusal(f"CHECKPOINT_VERIFY_FAILED: {exc}") from exc

    if not isinstance(identity, dict) or not identity.get("checkpoint_manifest_sha256"):
        raise R2ProbeBatteryRefusal(
            "CHECKPOINT_VERIFY_FAILED: verifier returned no checkpoint_manifest_sha256 "
            "-- cannot name the subject"
        )
    return identity


def _require_named_subject(identity: Mapping[str, Any]) -> None:
    if not isinstance(identity, Mapping) or not identity.get("checkpoint_manifest_sha256"):
        raise R2ProbeBatteryRefusal(
            "CHECKPOINT_UNBOUND: checkpoint identity missing checkpoint_manifest_sha256 "
            "-- refusing to adjudicate or emit a receipt that cannot name its subject"
        )


def _iter_checkpoint_subjects(checkpoint: Any) -> list[Mapping[str, Any]]:
    """A receipt's `checkpoint` block comes in exactly two shapes today: a
    single flat identity (R2-E4 -- checkpoint_manifest_sha256 at the top
    level) or an arm-label -> identity mapping (R2-E3 -- e.g. {"A3": {...},
    "control": {...}}). Returns every identity dict that must independently
    name a subject. Anything that is not one of these two recognized shapes
    (wrong type, empty, a value that is not itself a mapping) returns an
    empty list -- this function never partially validates a shape it does
    not recognize; build_receipt treats an empty list as CHECKPOINT_UNBOUND."""
    if not isinstance(checkpoint, Mapping) or not checkpoint:
        return []
    if "checkpoint_manifest_sha256" in checkpoint:
        return [checkpoint]
    if all(isinstance(value, Mapping) for value in checkpoint.values()):
        return list(checkpoint.values())
    return []


# ---------------------------------------------------------------------------
# Scoring interface -- deliberately abstract. See module docstring "SCOPE
# BOUNDARIES": no live 3B forward pass is wired in this PR.
# ---------------------------------------------------------------------------

class ProbeScorer(Protocol):
    def score_choices(self, context_ids: Sequence[int], choice_id_lists: Sequence[Sequence[int]]) -> list[float]:
        """Return one summed teacher-forced log-probability per choice, in
        choice_id_lists order. Exact-token-ID convention (no tokenizer
        parameter here or anywhere downstream -- re-tokenization inside a
        scorer is out of this interface's reach by construction, matching
        the retired legb_inprocess_scorer.score_ids_single's documented
        convention, reused as prose only -- see module docstring)."""
        ...


def _score_item(scorer: ProbeScorer, item: ProbeItem) -> dict:
    context = list(item.context_ids)
    choices = [list(c) for c in item.choices]
    first = scorer.score_choices(context, choices)
    second = scorer.score_choices(context, choices)
    if len(first) != len(choices) or len(second) != len(choices):
        raise R2ProbeBatteryRefusal(
            f"SCORER_RETURNED_WRONG_SHAPE: item_id={item.item_id!r} "
            f"expected={len(choices)} got_run1={len(first)} got_run2={len(second)}"
        )
    if not all(math.isfinite(x) for x in first) or not all(math.isfinite(x) for x in second):
        raise R2ProbeBatteryRefusal(f"SCORER_RETURNED_NONFINITE: item_id={item.item_id!r}")
    if [round(float(x), 12) for x in first] != [round(float(x), 12) for x in second]:
        raise R2ProbeBatteryRefusal(
            f"DETERMINISM_MISMATCH: item_id={item.item_id!r} run1={first!r} run2={second!r}"
        )
    predicted_index = max(range(len(first)), key=lambda i: first[i])
    return {
        "item_id": item.item_id,
        "scores": [float(x) for x in first],
        "predicted_choice_index": predicted_index,
        "correct_choice_index": item.correct_choice_index,
        "correct": predicted_index == item.correct_choice_index,
        "repeat_run_match": True,
    }


def score_probe(scorer: ProbeScorer, probe: ProbeSpec) -> list[dict]:
    if probe.metric_type != "proportion":
        raise R2ProbeBatteryRefusal(
            f"PROBE_METRIC_TYPE_UNSUPPORTED: probe_id={probe.probe_id!r} "
            f"metric_type={probe.metric_type!r} -- only 'proportion' scoring "
            "is wired in this runner (module docstring, scope boundary)"
        )
    if not probe.items:
        raise R2ProbeBatteryRefusal(f"PROBE_HAS_NO_ITEMS: probe_id={probe.probe_id!r}")
    return [_score_item(scorer, item) for item in probe.items]


# ---------------------------------------------------------------------------
# Confidence-bound primitives (secondary spec ambiguity -- see docstring)
# ---------------------------------------------------------------------------

def one_sided_lower_wilson(successes: int, n: int, confidence: float = T24_CONFIDENCE_LEVEL) -> float:
    """One-sided lower Wilson bound at `confidence`, by substituting the
    one-sided z for `confidence` into power.wilson()'s two-sided formula
    (standard technique: a symmetric two-sided (1-2*alpha) interval's lower
    bound IS the one-sided (1-alpha) lower bound) and taking only `lo`.
    Reuses power.wilson() -- never reimplements the score-interval math."""
    if n <= 0 or isinstance(n, bool):
        raise R2ProbeBatteryRefusal(f"CI_INPUT_INVALID: n={n!r} must be a positive integer")
    if not isinstance(successes, int) or isinstance(successes, bool) or not (0 <= successes <= n):
        raise R2ProbeBatteryRefusal(f"CI_INPUT_INVALID: successes={successes!r} n={n!r}")
    if not (0.5 <= confidence < 1.0):
        raise R2ProbeBatteryRefusal(f"CI_INPUT_INVALID: confidence={confidence!r} must be in [0.5, 1.0)")
    # issue2015 exact-local-import:scripts/power.py
    import importlib.util as _ember_41d654a4576ceb0a_importlib
    import sys as _ember_41d654a4576ceb0a_sys
    from pathlib import Path as _ember_41d654a4576ceb0a_Path
    _ember_41d654a4576ceb0a_path = _ember_41d654a4576ceb0a_Path(__file__).resolve().parents[4].joinpath('scripts', 'power.py')
    if not _ember_41d654a4576ceb0a_path.is_file():
        raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/power.py')
    _ember_41d654a4576ceb0a_aliases = ('_ember_issue2015_41d654a4576ceb0a', 'power', 'scripts.power')
    _ember_41d654a4576ceb0a_existing = []
    for _ember_41d654a4576ceb0a_alias in _ember_41d654a4576ceb0a_aliases:
        _ember_41d654a4576ceb0a_candidate = _ember_41d654a4576ceb0a_sys.modules.get(_ember_41d654a4576ceb0a_alias)
        if _ember_41d654a4576ceb0a_candidate is not None and all(_ember_41d654a4576ceb0a_candidate is not item for item in _ember_41d654a4576ceb0a_existing):
            _ember_41d654a4576ceb0a_existing.append(_ember_41d654a4576ceb0a_candidate)
    if len(_ember_41d654a4576ceb0a_existing) > 1:
        raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/power.py')
    if _ember_41d654a4576ceb0a_existing:
        _ember_41d654a4576ceb0a_module = _ember_41d654a4576ceb0a_existing[0]
        _ember_41d654a4576ceb0a_observed = getattr(_ember_41d654a4576ceb0a_module, '__file__', None)
        if _ember_41d654a4576ceb0a_observed is None or _ember_41d654a4576ceb0a_Path(_ember_41d654a4576ceb0a_observed).resolve() != _ember_41d654a4576ceb0a_path:
            raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/power.py')
    else:
        _ember_41d654a4576ceb0a_spec = _ember_41d654a4576ceb0a_importlib.spec_from_file_location('_ember_issue2015_41d654a4576ceb0a', _ember_41d654a4576ceb0a_path)
        if _ember_41d654a4576ceb0a_spec is None or _ember_41d654a4576ceb0a_spec.loader is None:
            raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/power.py')
        _ember_41d654a4576ceb0a_module = _ember_41d654a4576ceb0a_importlib.module_from_spec(_ember_41d654a4576ceb0a_spec)
        for _ember_41d654a4576ceb0a_alias in _ember_41d654a4576ceb0a_aliases:
            _ember_41d654a4576ceb0a_prior = _ember_41d654a4576ceb0a_sys.modules.get(_ember_41d654a4576ceb0a_alias)
            if _ember_41d654a4576ceb0a_prior is not None and _ember_41d654a4576ceb0a_prior is not _ember_41d654a4576ceb0a_module:
                raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/power.py')
            _ember_41d654a4576ceb0a_sys.modules[_ember_41d654a4576ceb0a_alias] = _ember_41d654a4576ceb0a_module
        try:
            _ember_41d654a4576ceb0a_spec.loader.exec_module(_ember_41d654a4576ceb0a_module)
        except BaseException:
            for _ember_41d654a4576ceb0a_alias in _ember_41d654a4576ceb0a_aliases:
                if _ember_41d654a4576ceb0a_sys.modules.get(_ember_41d654a4576ceb0a_alias) is _ember_41d654a4576ceb0a_module:
                    _ember_41d654a4576ceb0a_sys.modules.pop(_ember_41d654a4576ceb0a_alias, None)
            raise
    for _ember_41d654a4576ceb0a_alias in _ember_41d654a4576ceb0a_aliases:
        _ember_41d654a4576ceb0a_prior = _ember_41d654a4576ceb0a_sys.modules.get(_ember_41d654a4576ceb0a_alias)
        if _ember_41d654a4576ceb0a_prior is not None and _ember_41d654a4576ceb0a_prior is not _ember_41d654a4576ceb0a_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/power.py')
        _ember_41d654a4576ceb0a_sys.modules[_ember_41d654a4576ceb0a_alias] = _ember_41d654a4576ceb0a_module
    wilson = getattr(_ember_41d654a4576ceb0a_module, 'wilson')
    # issue2015 exact-local-import-end:scripts/power.py  # reused, never reimplemented
    z = statistics.NormalDist().inv_cdf(confidence)
    lower, _upper = wilson(successes, n, z=z)
    return float(lower)


def one_sided_lower_bootstrap(
    item_scores: Sequence[float],
    confidence: float = T24_CONFIDENCE_LEVEL,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> float:
    """Nonparametric percentile-bootstrap one-sided lower bound at
    `confidence`, over `resamples` resamples (sec2's named 10,000 default).
    Provided for a future metric_type=graded probe -- not exercised against
    real items today (see module docstring and D-03 scope boundary)."""
    if not item_scores:
        raise R2ProbeBatteryRefusal("CI_INPUT_INVALID: item_scores is empty")
    if resamples < 2:
        raise R2ProbeBatteryRefusal(f"CI_INPUT_INVALID: resamples={resamples!r} must be >= 2")
    if not (0.5 <= confidence < 1.0):
        raise R2ProbeBatteryRefusal(f"CI_INPUT_INVALID: confidence={confidence!r} must be in [0.5, 1.0)")
    values = np.asarray(list(item_scores), dtype=np.float64)
    if not np.all(np.isfinite(values)):
        raise R2ProbeBatteryRefusal("CI_INPUT_INVALID: item_scores contains non-finite values")
    rng = np.random.default_rng(seed)
    draws = np.asarray(
        [float(rng.choice(values, size=len(values), replace=True).mean()) for _ in range(resamples)]
    )
    return float(np.quantile(draws, 1.0 - confidence))


# ---------------------------------------------------------------------------
# R2-E4: frozen cheap-probe battery above chance (per probe)
# ---------------------------------------------------------------------------

def adjudicate_r2e4_probe(probe: ProbeSpec, item_results: Sequence[dict], *, seed: int = DEFAULT_SEED) -> dict:
    n = len(item_results)
    if n == 0:
        raise R2ProbeBatteryRefusal(f"PROBE_HAS_NO_ITEMS: probe_id={probe.probe_id!r}")
    if probe.metric_type == "proportion":
        successes = sum(1 for r in item_results if r["correct"])
        lower = one_sided_lower_wilson(successes, n, T24_CONFIDENCE_LEVEL)
        observed = successes / n
        ci_method = "wilson_one_sided_lower"
    else:  # pragma: no cover -- unreachable while score_probe refuses "graded"; kept for adjudicate_r2e4_probe's own unit tests
        scores = [float(r["score"]) for r in item_results]
        lower = one_sided_lower_bootstrap(scores, T24_CONFIDENCE_LEVEL, BOOTSTRAP_RESAMPLES, seed)
        observed = float(sum(scores) / len(scores))
        ci_method = "nonparametric_bootstrap_one_sided_lower"
    above_chance = lower > probe.chance_rate
    return {
        "probe_id": probe.probe_id,
        "metric_id": probe.metric_id,
        "metric_type": probe.metric_type,
        "n_items": n,
        "observed": observed,
        "chance_rate": probe.chance_rate,
        "confidence_level": T24_CONFIDENCE_LEVEL,
        "ci_method": ci_method,
        "one_sided_lower_bound": lower,
        "above_chance": above_chance,
        "verdict": "R2E4_ABOVE_CHANCE" if above_chance else "R2E4_NOT_ABOVE_CHANCE",
    }


def run_r2e4(*, checkpoint_identity: Mapping[str, Any], registry: Sequence[ProbeSpec], scorer: ProbeScorer, seed: int = DEFAULT_SEED) -> dict:
    _require_named_subject(checkpoint_identity)
    if not registry:
        raise R2ProbeBatteryRefusal(
            "BATTERY_UNDEFINED: the R2 cheap-probe battery has zero probes -- "
            "D-03 explicitly defers R2-E3/R2-E4/F-03 and forbids advancement "
            "until an accepted nonempty battery amendment lands"
        )
    per_probe = []
    for probe in registry:
        items = score_probe(scorer, probe)
        verdict = adjudicate_r2e4_probe(probe, items, seed=seed)
        per_probe.append({**verdict, "items": items})
    return {
        "status": "ADJUDICATED",
        "n_probes": len(per_probe),
        "all_probes_above_chance": all(p["above_chance"] for p in per_probe),
        "per_probe": per_probe,
    }


# ---------------------------------------------------------------------------
# R2-E3 / F-03: matched-control delta at equal budget
# ---------------------------------------------------------------------------

def adjudicate_f03(delta_m: float, sigma_seed_m: float, *, t20: float = T20_SIGNAL_BAND_MULTIPLIER) -> dict:
    """F-03 exactly: NO-SIGNAL iff abs(delta_m) <= T20*sigma_seed(m); F1
    pivot iff delta_m(A3-control) < -T20*sigma_seed(m); otherwise a
    POSITIVE delta for A3 -- which prereg sec3's "Adjudication asymmetry"
    binds as NOT creditable from R2 alone (R3 sustained-regime re-check is
    mandatory before any A3-superiority claim), so it is classified
    POSITIVE_DELTA_NO_R2_CREDIT, never PASS/WIN."""
    if not isinstance(sigma_seed_m, (int, float)) or isinstance(sigma_seed_m, bool) or sigma_seed_m < 0 or not math.isfinite(sigma_seed_m):
        raise R2ProbeBatteryRefusal(f"SIGMA_SEED_INVALID: sigma_seed_m={sigma_seed_m!r}")
    if not isinstance(delta_m, (int, float)) or isinstance(delta_m, bool) or not math.isfinite(delta_m):
        raise R2ProbeBatteryRefusal(f"CI_INPUT_INVALID: delta_m={delta_m!r}")
    band = t20 * sigma_seed_m
    if abs(delta_m) <= band:
        classification = "NO_SIGNAL"
    elif delta_m < -band:
        classification = "F1_PIVOT"
    else:
        classification = "POSITIVE_DELTA_NO_R2_CREDIT"
    return {
        "delta_m": float(delta_m),
        "sigma_seed_m": float(sigma_seed_m),
        "t20": t20,
        "signal_band": band,
        "classification": classification,
    }


def load_sigma_seed_receipt(path: str | Path) -> dict[str, float]:
    """THIS script's disclosed input contract for an R1-E7 sigma_seed
    receipt (schema not frozen upstream -- see module docstring). Expects
    `{"sigma_seed": {"<metric_id>": <float>, ...}}`; extra top-level keys
    are tolerated (this is a consumer-side extraction, not a full-receipt
    schema validator -- receipt_check.validate_receipt is the authority on
    receipt-shape floor, this only extracts what R2-E3 needs)."""
    receipt_path = Path(path)
    try:
        doc = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise R2ProbeBatteryRefusal(f"SIGMA_SEED_RECEIPT_UNREADABLE: {receipt_path}: {exc}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("sigma_seed"), dict) or not doc["sigma_seed"]:
        raise R2ProbeBatteryRefusal(
            f"SIGMA_SEED_RECEIPT_INVALID: {receipt_path} -- expected a nonempty "
            "'sigma_seed' object field"
        )
    values: dict[str, float] = {}
    for key, value in doc["sigma_seed"].items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0 or not math.isfinite(value):
            raise R2ProbeBatteryRefusal(
                f"SIGMA_SEED_RECEIPT_INVALID: {receipt_path} -- sigma_seed[{key!r}]={value!r} "
                "is not a finite non-negative number"
            )
        values[key] = float(value)
    return values


def run_r2e3(
    *,
    checkpoint_identity_a3: Mapping[str, Any],
    checkpoint_identity_control: Mapping[str, Any],
    registry: Sequence[ProbeSpec],
    scorer_a3: ProbeScorer,
    scorer_control: ProbeScorer,
    sigma_seed_lookup: Mapping[str, float],
    seed: int = DEFAULT_SEED,
) -> dict:
    _require_named_subject(checkpoint_identity_a3)
    _require_named_subject(checkpoint_identity_control)
    if not registry:
        raise R2ProbeBatteryRefusal(
            "BATTERY_UNDEFINED: the R2 cheap-probe battery has zero probes -- "
            "D-03 explicitly defers R2-E3/R2-E4/F-03 and forbids advancement "
            "until an accepted nonempty battery amendment lands"
        )
    per_probe = []
    for probe in registry:
        items_a3 = score_probe(scorer_a3, probe)
        items_control = score_probe(scorer_control, probe)
        rate_a3 = sum(1 for r in items_a3 if r["correct"]) / len(items_a3)
        rate_control = sum(1 for r in items_control if r["correct"]) / len(items_control)
        delta = rate_a3 - rate_control
        sigma = sigma_seed_lookup.get(probe.metric_id)
        if sigma is None:
            raise R2ProbeBatteryRefusal(
                f"SIGMA_SEED_MISSING: metric_id={probe.metric_id!r} probe_id={probe.probe_id!r} "
                "-- no R1-E7 sigma_seed supplied for this metric"
            )
        verdict = adjudicate_f03(delta, sigma)
        per_probe.append({
            "probe_id": probe.probe_id,
            "metric_id": probe.metric_id,
            "rate_a3": rate_a3,
            "rate_control": rate_control,
            **verdict,
            "items_a3": items_a3,
            "items_control": items_control,
        })
    return {
        "status": "ADJUDICATED",
        "n_probes": len(per_probe),
        "any_f1_pivot": any(p["classification"] == "F1_PIVOT" for p in per_probe),
        "per_probe": per_probe,
    }


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------

def build_receipt(
    *,
    ticket: str,
    exit_criterion: str,
    checkpoint: dict,
    probe_manifest_meta: dict | None,
    status: str,
    refusal_reason: str | None = None,
    result: dict | None = None,
    extra: dict | None = None,
) -> dict:
    # Do not trust the caller: verify_checkpoint/_require_named_subject were
    # very likely already run upstream (run_r2e4/run_r2e3, both CLI paths
    # today), but that is caller discipline, not this function's own
    # contract -- a future call site (the live-scorer PR's success-path
    # receipt, most obviously) could reach here without repeating that
    # check. Re-verify every subject the checkpoint block claims to name.
    subjects = _iter_checkpoint_subjects(checkpoint)
    if not subjects:
        raise R2ProbeBatteryRefusal(
            "CHECKPOINT_UNBOUND: checkpoint block does not resolve to a recognized "
            "single-identity or arm-label-mapping shape -- refusing to emit a receipt "
            "that cannot name its subject"
        )
    for subject in subjects:
        _require_named_subject(subject)
    import receipt_check  # sole authority for INVARIANT_SHA256 -- never hardcoded here
    receipt: dict[str, Any] = {
        "ticket": ticket,
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "schema": RECEIPT_SCHEMA,
        "issue_refs": [ISSUE_REF, AUTHORITY_ISSUE_REF],
        "sha_convention": SHA_CONVENTION,
        "invariant_sha256": receipt_check.INVARIANT_SHA256,
        "prereg": {"document": PREREG_DOC, "pin": PREREG_PIN},
        "r2_battery_authority": {
            "document": R2_AUTHORITY_DOC,
            "schema": R2_AUTHORITY_SCHEMA,
            "decision_id": R2_AUTHORITY_DECISION_ID,
        },
        "exit_criterion": exit_criterion,
        "checkpoint": checkpoint,
        "probe_manifest": probe_manifest_meta or {"path": None, "sha256": None, "schema": None, "probe_count": 0},
        "status": status,
        "spec_defects": SPEC_DEFECTS,
        "api_spend_usd": 0.0,
        "paid_api_surface_used": False,
    }
    if refusal_reason is not None:
        receipt["refusal_reason"] = refusal_reason
    if result is not None:
        receipt["result"] = result
    if extra:
        receipt.update(extra)
    return receipt


def write_receipt(path: str | Path, receipt: dict) -> None:
    from receipt_write import checked_write  # atomic, quarantine-on-invalid publication
    os.makedirs(os.path.dirname(os.path.abspath(str(path))) or ".", exist_ok=True)
    checked_write(str(path), receipt)


# ---------------------------------------------------------------------------
# Selftest -- pure CPU synthetic fixtures. No GPU, no real checkpoint, no
# real corpus, no real probes (these fixtures are clearly namespaced
# SELFTEST_FIXTURE_* and must never be mistaken for real R2 evidence).
# ---------------------------------------------------------------------------

class _FixtureScorer:
    """Deterministic in-memory ProbeScorer keyed on exact (context, choices).
    Raises if asked to score anything not in its table -- a test fixture
    that silently returned zeros for unknown input would hide bugs."""

    def __init__(self, table: dict[tuple, list[float]], *, flaky: bool = False):
        self._table = table
        self._flaky = flaky
        self._calls = 0

    def score_choices(self, context_ids, choice_id_lists):
        self._calls += 1
        key = (tuple(context_ids), tuple(tuple(c) for c in choice_id_lists))
        if key not in self._table:
            raise KeyError(f"_FixtureScorer: no fixture row for {key!r}")
        values = list(self._table[key])
        if self._flaky and self._calls % 2 == 0:
            values = [v + 1.0 for v in values]  # deliberately break determinism on even calls
        return values


def _fixture_item(item_id: str, index: int, correct_index: int) -> ProbeItem:
    # `index` is folded into context_ids so each item in a probe gets a
    # distinct (context_ids, choices) key in _FixtureScorer's table -- two
    # items sharing a key would silently collapse to one table row.
    return ProbeItem(
        item_id=item_id,
        context_ids=(1, 2, 3, index),
        choices=((10,), (11,), (12,)),
        correct_choice_index=correct_index,
    )


def _fixture_scores_row(item: ProbeItem, correct_wins: bool) -> list[float]:
    # correct choice gets the highest score iff correct_wins
    base = [0.1, 0.2, 0.3]
    if correct_wins:
        base[item.correct_choice_index] = 9.0
    else:
        base[item.correct_choice_index] = -9.0
        base[(item.correct_choice_index + 1) % 3] = 9.0
    return base


def _build_fixture_probe(probe_id: str, *, n_items: int, n_correct: int, chance_rate: float = 1.0 / 3.0) -> tuple[ProbeSpec, _FixtureScorer]:
    items = [_fixture_item(f"{probe_id}-item-{i}", i, correct_index=i % 3) for i in range(n_items)]
    table: dict[tuple, list[float]] = {}
    for i, item in enumerate(items):
        key = (item.context_ids, item.choices)
        table[key] = _fixture_scores_row(item, correct_wins=(i < n_correct))
    probe = ProbeSpec(
        probe_id=probe_id,
        metric_id=f"{probe_id}.accuracy",
        metric_type="proportion",
        chance_rate=chance_rate,
        source_note="SELFTEST_FIXTURE -- synthetic, not a real R2 probe",
        items=tuple(items),
    )
    return probe, _FixtureScorer(table)


def _selftest_manifest_roundtrip(failures: list, tmp_dir: Path) -> None:
    doc = {
        "schema": PROBE_MANIFEST_SCHEMA,
        "issue": "SELFTEST_FIXTURE",
        "probes": [{
            "probe_id": "SELFTEST_FIXTURE_PROBE_1",
            "metric_id": "selftest.accuracy",
            "metric_type": "proportion",
            "chance_rate": 0.5,
            "source_note": "SELFTEST_FIXTURE",
            "items": [{
                "item_id": "SELFTEST_FIXTURE_PROBE_1-item-0",
                "context_ids": [1, 2, 3],
                "choices": [[10], [11]],
                "correct_choice_index": 0,
            }],
        }],
    }
    path = tmp_dir / "manifest.json"
    raw = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    path.write_bytes(raw)
    good_sha = _sha256_bytes(raw)

    registry, meta = load_probe_manifest(path, good_sha)
    if len(registry) != 1 or registry[0].probe_id != "SELFTEST_FIXTURE_PROBE_1" or meta["probe_count"] != 1:
        failures.append(f"manifest_roundtrip FAIL: registry/meta mismatch: {registry!r} {meta!r}")

    try:
        load_probe_manifest(path, "0" * 64)
        failures.append("manifest_roundtrip FAIL: wrong sha256 did not refuse")
    except R2ProbeBatteryRefusal as exc:
        if "PROBE_MANIFEST_SHA_MISMATCH" not in str(exc):
            failures.append(f"manifest_roundtrip FAIL: wrong refusal reason for sha mismatch: {exc}")

    bad_doc = dict(doc)
    bad_doc["extra_key"] = 1
    bad_path = tmp_dir / "manifest_bad.json"
    bad_raw = json.dumps(bad_doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    bad_path.write_bytes(bad_raw)
    try:
        load_probe_manifest(bad_path, _sha256_bytes(bad_raw))
        failures.append("manifest_roundtrip FAIL: extra top-level key did not refuse")
    except R2ProbeBatteryRefusal as exc:
        if "PROBE_MANIFEST_SCHEMA_INVALID" not in str(exc):
            failures.append(f"manifest_roundtrip FAIL: wrong refusal reason for extra key: {exc}")

    dup_doc = json.loads(json.dumps(doc))
    dup_doc["probes"].append(dup_doc["probes"][0])
    dup_path = tmp_dir / "manifest_dup.json"
    dup_raw = json.dumps(dup_doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    dup_path.write_bytes(dup_raw)
    try:
        load_probe_manifest(dup_path, _sha256_bytes(dup_raw))
        failures.append("manifest_roundtrip FAIL: duplicate probe_id did not refuse")
    except R2ProbeBatteryRefusal as exc:
        if "duplicate probe_id" not in str(exc):
            failures.append(f"manifest_roundtrip FAIL: wrong refusal reason for duplicate id: {exc}")

    rate_doc = json.loads(json.dumps(doc))
    rate_doc["probes"][0]["chance_rate"] = 0.25
    rate_path = tmp_dir / "manifest_bad_rate.json"
    rate_raw = json.dumps(rate_doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    rate_path.write_bytes(rate_raw)
    try:
        load_probe_manifest(rate_path, _sha256_bytes(rate_raw))
        failures.append("manifest_roundtrip FAIL: inconsistent chance rate did not refuse")
    except R2ProbeBatteryRefusal as exc:
        if "CHANCE_RATE_INCONSISTENT" not in str(exc):
            failures.append(f"manifest_roundtrip FAIL: wrong refusal reason for chance rate: {exc}")

    mixed_doc = json.loads(json.dumps(doc))
    mixed_doc["probes"][0]["items"][0]["choices"] = [[10], [11], [12]]
    mixed_path = tmp_dir / "manifest_bad_cardinality.json"
    mixed_raw = json.dumps(mixed_doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    mixed_path.write_bytes(mixed_raw)
    try:
        load_probe_manifest(mixed_path, _sha256_bytes(mixed_raw))
        failures.append("manifest_roundtrip FAIL: mixed choice cardinality did not refuse")
    except R2ProbeBatteryRefusal as exc:
        if "CHANCE_RATE_INCONSISTENT" not in str(exc):
            failures.append(f"manifest_roundtrip FAIL: wrong refusal reason for cardinality: {exc}")

    print("SELFTEST battery 1: probe-manifest round trip + sha/schema/duplicate/chance-cardinality refusals PASS")


def _selftest_ci_primitives(failures: list) -> None:
    # Wilson one-sided lower bound: high accuracy, clearly above 1/3 chance
    lower_strong = one_sided_lower_wilson(29, 30, 0.95)
    if not (lower_strong > 1.0 / 3.0):
        failures.append(f"ci_primitives FAIL: strong-accuracy Wilson lower={lower_strong} should exceed chance 1/3")
    # at-chance accuracy with a small sample: lower bound should NOT clear chance
    lower_weak = one_sided_lower_wilson(11, 30, 0.95)  # ~0.367 observed, 1/3 chance
    if lower_weak > 1.0 / 3.0:
        failures.append(f"ci_primitives FAIL: at-chance Wilson lower={lower_weak} unexpectedly exceeds chance 1/3")
    # bootstrap sanity: constant scores collapse the bootstrap distribution to that constant
    lower_boot = one_sided_lower_bootstrap([0.8] * 50, 0.95, resamples=500, seed=1)
    if abs(lower_boot - 0.8) > 1e-9:
        failures.append(f"ci_primitives FAIL: constant-score bootstrap lower={lower_boot} != 0.8")
    # bootstrap on separated values: lower bound must sit strictly below the mean
    mixed = [0.0] * 10 + [1.0] * 10
    lower_mixed = one_sided_lower_bootstrap(mixed, 0.95, resamples=2000, seed=7)
    if not (0.0 <= lower_mixed < 0.5):
        failures.append(f"ci_primitives FAIL: mixed-score bootstrap lower={lower_mixed} not in [0, 0.5)")
    for bad_n in (0, -1):
        try:
            one_sided_lower_wilson(0, bad_n, 0.95)
            failures.append(f"ci_primitives FAIL: n={bad_n} did not refuse")
        except R2ProbeBatteryRefusal:
            pass
    try:
        one_sided_lower_bootstrap([], 0.95)
        failures.append("ci_primitives FAIL: empty item_scores did not refuse")
    except R2ProbeBatteryRefusal:
        pass
    print("SELFTEST battery 2: Wilson + bootstrap one-sided lower bounds PASS")


def _selftest_r2e4(failures: list) -> None:
    checkpoint_identity = {"checkpoint_manifest_sha256": "f" * 64, "arm": "SELFTEST_FIXTURE"}

    two_choice_items = (
        ProbeItem("SELFTEST_FIXTURE_RATE-item-0", (1, 2), ((10,), (11,)), 0),
        ProbeItem("SELFTEST_FIXTURE_RATE-item-1", (1, 3), ((10,), (11,)), 1),
    )
    try:
        ProbeSpec(
            probe_id="SELFTEST_FIXTURE_RATE", metric_id="selftest.rate", metric_type="proportion",
            chance_rate=0.25, source_note="SELFTEST_FIXTURE", items=two_choice_items,
        )
        failures.append("r2e4 FAIL: inconsistent uniform chance rate did not refuse")
    except R2ProbeBatteryRefusal as exc:
        if "CHANCE_RATE_INCONSISTENT" not in str(exc):
            failures.append(f"r2e4 FAIL: wrong refusal reason for inconsistent rate: {exc}")

    mixed_choice_items = (
        ProbeItem("SELFTEST_FIXTURE_MIXED-item-0", (1, 2), ((10,), (11,)), 0),
        ProbeItem("SELFTEST_FIXTURE_MIXED-item-1", (1, 3), ((10,), (11,), (12,), (13,)), 1),
    )
    try:
        ProbeSpec(
            probe_id="SELFTEST_FIXTURE_MIXED", metric_id="selftest.mixed", metric_type="proportion",
            chance_rate=0.5, source_note="SELFTEST_FIXTURE", items=mixed_choice_items,
        )
        failures.append("r2e4 FAIL: mixed choice cardinality did not refuse")
    except R2ProbeBatteryRefusal as exc:
        if "CHANCE_RATE_INCONSISTENT" not in str(exc):
            failures.append(f"r2e4 FAIL: wrong refusal reason for mixed cardinality: {exc}")

    # Empty registry -> BATTERY_UNDEFINED, never a silent pass.
    try:
        run_r2e4(checkpoint_identity=checkpoint_identity, registry=(), scorer=_FixtureScorer({}))
        failures.append("r2e4 FAIL: empty registry did not refuse")
    except R2ProbeBatteryRefusal as exc:
        if "BATTERY_UNDEFINED" not in str(exc):
            failures.append(f"r2e4 FAIL: wrong refusal reason for empty registry: {exc}")

    # Unnamed subject -> CHECKPOINT_UNBOUND, even with a nonempty registry.
    probe, scorer = _build_fixture_probe("SELFTEST_FIXTURE_PROBE_UNBOUND", n_items=10, n_correct=10)
    try:
        run_r2e4(checkpoint_identity={}, registry=(probe,), scorer=scorer)
        failures.append("r2e4 FAIL: unnamed checkpoint identity did not refuse")
    except R2ProbeBatteryRefusal as exc:
        if "CHECKPOINT_UNBOUND" not in str(exc):
            failures.append(f"r2e4 FAIL: wrong refusal reason for unnamed subject: {exc}")

    # All-correct probe, well above chance (1/3): must adjudicate ABOVE_CHANCE.
    probe_hi, scorer_hi = _build_fixture_probe("SELFTEST_FIXTURE_PROBE_HI", n_items=30, n_correct=30)
    result_hi = run_r2e4(checkpoint_identity=checkpoint_identity, registry=(probe_hi,), scorer=scorer_hi)
    if result_hi["status"] != "ADJUDICATED" or not result_hi["all_probes_above_chance"]:
        failures.append(f"r2e4 FAIL: all-correct probe did not adjudicate ABOVE_CHANCE: {result_hi}")
    if result_hi["per_probe"][0]["verdict"] != "R2E4_ABOVE_CHANCE":
        failures.append(f"r2e4 FAIL: wrong verdict for all-correct probe: {result_hi['per_probe'][0]}")

    # At-chance probe (10/30 correct on a 3-choice task): must NOT clear chance.
    probe_lo, scorer_lo = _build_fixture_probe("SELFTEST_FIXTURE_PROBE_LO", n_items=30, n_correct=10)
    result_lo = run_r2e4(checkpoint_identity=checkpoint_identity, registry=(probe_lo,), scorer=scorer_lo)
    if result_lo["all_probes_above_chance"]:
        failures.append(f"r2e4 FAIL: at-chance probe wrongly adjudicated above chance: {result_lo}")

    # Nondeterministic scorer -> DETERMINISM_MISMATCH, never a silently-accepted first score.
    probe_flaky, scorer_flaky = _build_fixture_probe("SELFTEST_FIXTURE_PROBE_FLAKY", n_items=1, n_correct=1)
    flaky_scorer = _FixtureScorer(scorer_flaky._table, flaky=True)
    try:
        run_r2e4(checkpoint_identity=checkpoint_identity, registry=(probe_flaky,), scorer=flaky_scorer)
        failures.append("r2e4 FAIL: nondeterministic scorer did not refuse")
    except R2ProbeBatteryRefusal as exc:
        if "DETERMINISM_MISMATCH" not in str(exc):
            failures.append(f"r2e4 FAIL: wrong refusal reason for nondeterminism: {exc}")

    # Wrong-shape scorer output -> SCORER_RETURNED_WRONG_SHAPE.
    class _WrongShapeScorer:
        def score_choices(self, context_ids, choice_id_lists):
            return [0.0]  # always returns one score regardless of choice count

    probe_shape, _ = _build_fixture_probe("SELFTEST_FIXTURE_PROBE_SHAPE", n_items=1, n_correct=1)
    try:
        run_r2e4(checkpoint_identity=checkpoint_identity, registry=(probe_shape,), scorer=_WrongShapeScorer())
        failures.append("r2e4 FAIL: wrong-shape scorer did not refuse")
    except R2ProbeBatteryRefusal as exc:
        if "SCORER_RETURNED_WRONG_SHAPE" not in str(exc):
            failures.append(f"r2e4 FAIL: wrong refusal reason for wrong shape: {exc}")

    # Nonfinite scorer output -> SCORER_RETURNED_NONFINITE.
    class _NonfiniteScorer:
        def score_choices(self, context_ids, choice_id_lists):
            return [float("nan")] * len(choice_id_lists)

    try:
        run_r2e4(checkpoint_identity=checkpoint_identity, registry=(probe_shape,), scorer=_NonfiniteScorer())
        failures.append("r2e4 FAIL: nonfinite scorer did not refuse")
    except R2ProbeBatteryRefusal as exc:
        if "SCORER_RETURNED_NONFINITE" not in str(exc):
            failures.append(f"r2e4 FAIL: wrong refusal reason for nonfinite: {exc}")

    # Unsupported metric_type -> PROBE_METRIC_TYPE_UNSUPPORTED (never silently scored as proportion).
    graded_item = _fixture_item("SELFTEST_FIXTURE_GRADED-item-0", 0, correct_index=0)
    graded_probe = ProbeSpec(
        probe_id="SELFTEST_FIXTURE_GRADED", metric_id="selftest.graded", metric_type="graded",
        chance_rate=0.0, source_note="SELFTEST_FIXTURE", items=(graded_item,),
    )
    try:
        run_r2e4(checkpoint_identity=checkpoint_identity, registry=(graded_probe,), scorer=_FixtureScorer({}))
        failures.append("r2e4 FAIL: graded metric_type did not refuse")
    except R2ProbeBatteryRefusal as exc:
        if "PROBE_METRIC_TYPE_UNSUPPORTED" not in str(exc):
            failures.append(f"r2e4 FAIL: wrong refusal reason for graded metric_type: {exc}")

    print("SELFTEST battery 3: run_r2e4 (above/at chance, unbound, undefined, "
          "nondeterministic, wrong-shape, nonfinite, unsupported-metric) PASS")


def _selftest_r2e3(failures: list) -> None:
    ck_a3 = {"checkpoint_manifest_sha256": "a" * 64, "arm": "A3"}
    ck_ctrl = {"checkpoint_manifest_sha256": "c" * 64, "arm": "A2"}

    probe_a3, scorer_a3 = _build_fixture_probe("SELFTEST_FIXTURE_PROBE_R2E3", n_items=30, n_correct=27)
    _, scorer_ctrl = _build_fixture_probe("SELFTEST_FIXTURE_PROBE_R2E3", n_items=30, n_correct=10)

    # Missing sigma_seed -> SIGMA_SEED_MISSING.
    try:
        run_r2e3(
            checkpoint_identity_a3=ck_a3, checkpoint_identity_control=ck_ctrl,
            registry=(probe_a3,), scorer_a3=scorer_a3, scorer_control=scorer_ctrl,
            sigma_seed_lookup={},
        )
        failures.append("r2e3 FAIL: missing sigma_seed did not refuse")
    except R2ProbeBatteryRefusal as exc:
        if "SIGMA_SEED_MISSING" not in str(exc):
            failures.append(f"r2e3 FAIL: wrong refusal reason for missing sigma_seed: {exc}")

    # Large A3 advantage vs a tight sigma -> POSITIVE_DELTA_NO_R2_CREDIT (never a WIN/PASS label).
    sigma_lookup = {probe_a3.metric_id: 0.02}
    result = run_r2e3(
        checkpoint_identity_a3=ck_a3, checkpoint_identity_control=ck_ctrl,
        registry=(probe_a3,), scorer_a3=scorer_a3, scorer_control=scorer_ctrl,
        sigma_seed_lookup=sigma_lookup,
    )
    classification = result["per_probe"][0]["classification"]
    if classification != "POSITIVE_DELTA_NO_R2_CREDIT":
        failures.append(f"r2e3 FAIL: large A3 advantage classified {classification!r}, expected POSITIVE_DELTA_NO_R2_CREDIT")
    if result["any_f1_pivot"]:
        failures.append("r2e3 FAIL: any_f1_pivot True for an A3-favoring delta")

    # Reversed roles (control now stronger) -> F1_PIVOT.
    probe_rev, scorer_a3_weak = _build_fixture_probe("SELFTEST_FIXTURE_PROBE_R2E3_REV", n_items=30, n_correct=10)
    _, scorer_ctrl_strong = _build_fixture_probe("SELFTEST_FIXTURE_PROBE_R2E3_REV", n_items=30, n_correct=27)
    result_rev = run_r2e3(
        checkpoint_identity_a3=ck_a3, checkpoint_identity_control=ck_ctrl,
        registry=(probe_rev,), scorer_a3=scorer_a3_weak, scorer_control=scorer_ctrl_strong,
        sigma_seed_lookup={probe_rev.metric_id: 0.02},
    )
    if result_rev["per_probe"][0]["classification"] != "F1_PIVOT" or not result_rev["any_f1_pivot"]:
        failures.append(f"r2e3 FAIL: control-favoring delta did not fire F1_PIVOT: {result_rev['per_probe'][0]}")

    # Tiny delta within a wide sigma band -> NO_SIGNAL.
    probe_tie, scorer_a3_tie = _build_fixture_probe("SELFTEST_FIXTURE_PROBE_R2E3_TIE", n_items=30, n_correct=16)
    _, scorer_ctrl_tie = _build_fixture_probe("SELFTEST_FIXTURE_PROBE_R2E3_TIE", n_items=30, n_correct=15)
    result_tie = run_r2e3(
        checkpoint_identity_a3=ck_a3, checkpoint_identity_control=ck_ctrl,
        registry=(probe_tie,), scorer_a3=scorer_a3_tie, scorer_control=scorer_ctrl_tie,
        sigma_seed_lookup={probe_tie.metric_id: 0.5},
    )
    if result_tie["per_probe"][0]["classification"] != "NO_SIGNAL":
        failures.append(f"r2e3 FAIL: tiny delta under wide band not classified NO_SIGNAL: {result_tie['per_probe'][0]}")

    # Empty registry -> BATTERY_UNDEFINED.
    try:
        run_r2e3(
            checkpoint_identity_a3=ck_a3, checkpoint_identity_control=ck_ctrl,
            registry=(), scorer_a3=scorer_a3, scorer_control=scorer_ctrl, sigma_seed_lookup={},
        )
        failures.append("r2e3 FAIL: empty registry did not refuse")
    except R2ProbeBatteryRefusal as exc:
        if "BATTERY_UNDEFINED" not in str(exc):
            failures.append(f"r2e3 FAIL: wrong refusal reason for empty registry: {exc}")

    print("SELFTEST battery 4: run_r2e3 / F-03 (NO_SIGNAL, F1_PIVOT, "
          "POSITIVE_DELTA_NO_R2_CREDIT, missing sigma, undefined battery) PASS")


def _selftest_f03_direct(failures: list) -> None:
    cases = [
        (0.0, 0.1, "NO_SIGNAL"),
        (0.199, 0.1, "NO_SIGNAL"),   # exactly at the band edge minus epsilon
        (0.2, 0.1, "NO_SIGNAL"),     # exactly on the band (<=), still NO_SIGNAL
        (0.201, 0.1, "POSITIVE_DELTA_NO_R2_CREDIT"),
        (-0.201, 0.1, "F1_PIVOT"),
    ]
    for delta, sigma, expected in cases:
        got = adjudicate_f03(delta, sigma)["classification"]
        if got != expected:
            failures.append(f"f03_direct FAIL: delta={delta} sigma={sigma} got={got} expected={expected}")
    for bad_sigma in (-1.0, float("nan")):
        try:
            adjudicate_f03(0.5, bad_sigma)
            failures.append(f"f03_direct FAIL: sigma={bad_sigma} did not refuse")
        except R2ProbeBatteryRefusal:
            pass
    print("SELFTEST battery 5: adjudicate_f03 boundary cases PASS")


def _selftest_checkpoint_binding(failures: list, tmp_dir: Path) -> None:
    manifest_path = tmp_dir / "ck" / "manifest.json"
    model_config_path = tmp_dir / "ck" / "model_config.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("{}", encoding="utf-8")
    model_config_path.write_text("{}", encoding="utf-8")

    def _fake_verify_ok(m, c):
        return {"checkpoint_manifest_sha256": "e" * 64, "goal_id": "EMBER-02"}

    identity = verify_checkpoint(manifest_path, model_config_path, verify_fn=_fake_verify_ok)
    if identity.get("checkpoint_manifest_sha256") != "e" * 64:
        failures.append(f"checkpoint_binding FAIL: identity not passed through: {identity}")

    def _fake_verify_unnamed(m, c):
        return {"goal_id": "EMBER-02"}  # no checkpoint_manifest_sha256

    try:
        verify_checkpoint(manifest_path, model_config_path, verify_fn=_fake_verify_unnamed)
        failures.append("checkpoint_binding FAIL: unnamed-subject verify_fn did not refuse")
    except R2ProbeBatteryRefusal as exc:
        if "CHECKPOINT_VERIFY_FAILED" not in str(exc):
            failures.append(f"checkpoint_binding FAIL: wrong refusal reason: {exc}")

    def _fake_verify_raises(m, c):
        raise ValueError("synthetic checkpoint corruption")

    try:
        verify_checkpoint(manifest_path, model_config_path, verify_fn=_fake_verify_raises)
        failures.append("checkpoint_binding FAIL: raising verify_fn did not refuse")
    except R2ProbeBatteryRefusal as exc:
        if "CHECKPOINT_VERIFY_FAILED" not in str(exc) or "synthetic checkpoint corruption" not in str(exc):
            failures.append(f"checkpoint_binding FAIL: wrong/incomplete refusal message: {exc}")

    try:
        verify_checkpoint(tmp_dir / "does-not-exist" / "manifest.json", model_config_path, verify_fn=_fake_verify_ok)
        failures.append("checkpoint_binding FAIL: missing manifest did not refuse")
    except R2ProbeBatteryRefusal as exc:
        if "CHECKPOINT_MANIFEST_MISSING" not in str(exc):
            failures.append(f"checkpoint_binding FAIL: wrong refusal reason for missing manifest: {exc}")

    print("SELFTEST battery 6: verify_checkpoint (ok / unnamed subject / raises / missing file) PASS")


def _selftest_sigma_seed_receipt(failures: list, tmp_dir: Path) -> None:
    good_path = tmp_dir / "sigma_seed_good.json"
    good_path.write_text(json.dumps({"sigma_seed": {"m.accuracy": 0.03}}), encoding="utf-8")
    values = load_sigma_seed_receipt(good_path)
    if values != {"m.accuracy": 0.03}:
        failures.append(f"sigma_seed_receipt FAIL: round trip mismatch: {values}")

    bad_path = tmp_dir / "sigma_seed_bad.json"
    bad_path.write_text(json.dumps({"not_sigma_seed": {}}), encoding="utf-8")
    try:
        load_sigma_seed_receipt(bad_path)
        failures.append("sigma_seed_receipt FAIL: missing sigma_seed key did not refuse")
    except R2ProbeBatteryRefusal as exc:
        if "SIGMA_SEED_RECEIPT_INVALID" not in str(exc):
            failures.append(f"sigma_seed_receipt FAIL: wrong refusal reason: {exc}")

    neg_path = tmp_dir / "sigma_seed_neg.json"
    neg_path.write_text(json.dumps({"sigma_seed": {"m.accuracy": -0.1}}), encoding="utf-8")
    try:
        load_sigma_seed_receipt(neg_path)
        failures.append("sigma_seed_receipt FAIL: negative sigma did not refuse")
    except R2ProbeBatteryRefusal as exc:
        if "SIGMA_SEED_RECEIPT_INVALID" not in str(exc):
            failures.append(f"sigma_seed_receipt FAIL: wrong refusal reason for negative sigma: {exc}")

    print("SELFTEST battery 7: load_sigma_seed_receipt (valid / missing key / negative) PASS")


def _selftest_receipt_shape(failures: list, tmp_dir: Path) -> None:
    receipt = build_receipt(
        ticket="R2-1435-SELFTEST",
        exit_criterion="R2-E4",
        checkpoint={"checkpoint_manifest_sha256": "b" * 64, "arm": "SELFTEST_FIXTURE"},
        probe_manifest_meta=None,
        status="REFUSED",
        refusal_reason="BATTERY_UNDEFINED",
    )
    import receipt_check
    findings = receipt_check.validate_receipt(receipt)
    if findings:
        failures.append(f"receipt_shape FAIL: receipt_check.validate_receipt found: {findings}")

    out_path = tmp_dir / "receipt.json"
    write_receipt(out_path, receipt)
    if not out_path.is_file():
        failures.append("receipt_shape FAIL: write_receipt did not create the file")
    else:
        reloaded = json.loads(out_path.read_text(encoding="utf-8"))
        if reloaded != receipt:
            failures.append("receipt_shape FAIL: written bytes do not round-trip to the same object")

    print("SELFTEST battery 8: build_receipt / receipt_check.validate_receipt / write_receipt PASS")


def _selftest() -> int:
    import tempfile
    print("[r2-cheap-probe-battery-selftest] starting CPU-only synthetic-fixture selftest")
    print("[r2-cheap-probe-battery-selftest] NOTE: the canonical #1498 path requires the exact "
          "--source-suite/tokenizer/compiler bindings; omitting authority still refuses "
          "BATTERY_UNDEFINED. This selftest uses synthetic SELFTEST_FIXTURE_* probes only, "
          "never real R2 evidence")
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="r2-cheap-probe-battery-selftest-") as tmp:
        tmp_dir = Path(tmp)
        _selftest_manifest_roundtrip(failures, tmp_dir)
        _selftest_ci_primitives(failures)
        _selftest_r2e4(failures)
        _selftest_r2e3(failures)
        _selftest_f03_direct(failures)
        _selftest_checkpoint_binding(failures, tmp_dir)
        _selftest_sigma_seed_receipt(failures, tmp_dir)
        _selftest_receipt_shape(failures, tmp_dir)

    if failures:
        for f in failures:
            print(f"SELFTEST: {f}")
        print(f"[r2-cheap-probe-battery-selftest] {len(failures)} failure(s)")
        return 1

    print("R2_CHEAP_PROBE_BATTERY_SELFTEST_PASS")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli_load_registry(args) -> tuple[list[ProbeSpec], dict | None]:
    if args.source_suite is not None:
        if args.probe_manifest is not None:
            raise R2ProbeBatteryRefusal("PROBE_AUTHORITY_AMBIGUOUS")
        required = (
            args.source_suite_sha256,
            args.tokenizer,
            args.tokenizer_sha256,
            args.compiler_sha256,
        )
        if not all(required):
            raise R2ProbeBatteryRefusal(
                "SOURCE_SUITE_BINDING_INCOMPLETE: --source-suite requires source, tokenizer, and compiler hashes"
            )
        return load_compiled_source_suite(
            args.source_suite,
            args.source_suite_sha256,
            args.tokenizer,
            args.tokenizer_sha256,
            args.compiler_sha256,
        )
    if args.probe_manifest is not None or args.probe_manifest_sha256 is not None:
        raise R2ProbeBatteryRefusal(
            "PROBE_AUTHORITY_SUPERSEDED: D-04 forbids persisted token-ID manifests; "
            "use the exact --source-suite plus tokenizer and compiler hashes"
        )
    return list(DEFAULT_PROBE_REGISTRY), None


def _cli_run_r2e4(args) -> int:
    try:
        if not args.out:
            raise R2ProbeBatteryRefusal("OUTPUT_PATH_REQUIRED: --out is required for --run-r2e4")
        checkpoint_identity = verify_checkpoint(args.checkpoint_manifest, args.model_config)
    except R2ProbeBatteryRefusal as exc:
        # No output path, or cannot name the subject at all -- no receipt is possible.
        print(f"R2_CHEAP_PROBE_BATTERY_REFUSED: {exc}", file=sys.stderr)
        return 3

    checkpoint_block = {**checkpoint_identity, "arm": args.arm}
    probe_manifest_meta = None
    try:
        registry, probe_manifest_meta = _cli_load_registry(args)
        if not registry:
            raise R2ProbeBatteryRefusal(
                "BATTERY_UNDEFINED: D-04 requires --source-suite plus exact source, "
                "tokenizer, and compiler hashes"
            )
        # A nonempty registry exists but no scorer backend is wired in this PR
        # (see module docstring, scope boundary) -- refuse distinctly rather
        # than crash or silently skip scoring.
        raise R2ProbeBatteryRefusal(
            f"SCORER_BACKEND_NOT_CONFIGURED: {len(registry)} probe(s) loaded from "
            f"{probe_manifest_meta['path'] if probe_manifest_meta else '<none>'} but no live "
            "scorer backend is wired to this CLI yet (module docstring, scope boundary)"
        )
    except R2ProbeBatteryRefusal as exc:
        reason = str(exc).split(":", 1)[0]
        receipt = build_receipt(
            ticket=f"R2-1435-CHEAP-PROBE-BATTERY-R2E4-{args.arm}",
            exit_criterion="R2-E4",
            checkpoint=checkpoint_block,
            probe_manifest_meta=probe_manifest_meta,
            status="REFUSED",
            refusal_reason=str(exc),
        )
        write_receipt(args.out, receipt)
        print(f"R2_CHEAP_PROBE_BATTERY_R2E4_REFUSED reason={reason}", file=sys.stderr)
        print(f"R2_CHEAP_PROBE_BATTERY_R2E4_RECEIPT_WRITTEN: {args.out}")
        return 3


def _cli_run_r2e3(args) -> int:
    try:
        if not args.out:
            raise R2ProbeBatteryRefusal("OUTPUT_PATH_REQUIRED: --out is required for --run-r2e3")
        identity_a3 = verify_checkpoint(args.checkpoint_manifest_a3, args.model_config_a3)
        identity_control = verify_checkpoint(args.checkpoint_manifest_control, args.model_config_control)
    except R2ProbeBatteryRefusal as exc:
        # No output path, or cannot name a subject at all -- no receipt is possible.
        print(f"R2_CHEAP_PROBE_BATTERY_REFUSED: {exc}", file=sys.stderr)
        return 3

    checkpoint_block = {
        "A3": {**identity_a3, "arm": "A3"},
        "control": {**identity_control, "arm": args.control_arm},
    }
    probe_manifest_meta = None
    try:
        registry, probe_manifest_meta = _cli_load_registry(args)
        if not registry:
            raise R2ProbeBatteryRefusal(
                "BATTERY_UNDEFINED: D-04 requires --source-suite plus exact source, "
                "tokenizer, and compiler hashes"
            )
        raise R2ProbeBatteryRefusal(
            f"SCORER_BACKEND_NOT_CONFIGURED: {len(registry)} probe(s) loaded from "
            f"{probe_manifest_meta['path'] if probe_manifest_meta else '<none>'} but no live "
            "scorer backend is wired to this CLI yet (module docstring, scope boundary)"
        )
    except R2ProbeBatteryRefusal as exc:
        reason = str(exc).split(":", 1)[0]
        receipt = build_receipt(
            ticket=f"R2-1435-CHEAP-PROBE-BATTERY-R2E3-A3-vs-{args.control_arm}",
            exit_criterion="R2-E3",
            checkpoint=checkpoint_block,
            probe_manifest_meta=probe_manifest_meta,
            status="REFUSED",
            refusal_reason=str(exc),
        )
        write_receipt(args.out, receipt)
        print(f"R2_CHEAP_PROBE_BATTERY_R2E3_REFUSED reason={reason}", file=sys.stderr)
        print(f"R2_CHEAP_PROBE_BATTERY_R2E3_RECEIPT_WRITTEN: {args.out}")
        return 3


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--run-r2e4", action="store_true")
    ap.add_argument("--run-r2e3", action="store_true")
    ap.add_argument("--checkpoint-manifest", help="R2-E4: checkpoint manifest.json path")
    ap.add_argument("--model-config", help="R2-E4: checkpoint model_config.json path")
    ap.add_argument("--arm", default="A3", help="R2-E4: arm label recorded on the receipt (disclosed, unvalidated)")
    ap.add_argument("--checkpoint-manifest-a3", help="R2-E3: A3 checkpoint manifest.json path")
    ap.add_argument("--model-config-a3", help="R2-E3: A3 checkpoint model_config.json path")
    ap.add_argument("--checkpoint-manifest-control", help="R2-E3: control-arm checkpoint manifest.json path")
    ap.add_argument("--model-config-control", help="R2-E3: control-arm checkpoint model_config.json path")
    ap.add_argument("--control-arm", default="A2", help="R2-E3: control-arm label recorded on the receipt (A2 per prereg sec4.4)")
    ap.add_argument("--probe-manifest", default=None, help="legacy persisted token manifest; live CLI refuses under D-04")
    ap.add_argument("--probe-manifest-sha256", default=None, help="legacy companion hash; live CLI refuses under D-04")
    ap.add_argument("--source-suite", default=None, help="#1498 sole canonical text suite; compiled to R2 IDs in memory")
    ap.add_argument("--source-suite-sha256", default=None, help="required whole-file hash for --source-suite")
    ap.add_argument("--tokenizer", default=None, help="tokenizer.json used for deterministic R2 compilation")
    ap.add_argument("--tokenizer-sha256", default=None, help="required raw tokenizer hash")
    ap.add_argument("--compiler-sha256", default=None, help="required raw r1_cheap_probe_suite.py hash")
    ap.add_argument("--sigma-seed-receipt", default=None, help="R2-E3: R1-E7 sigma_seed input (see load_sigma_seed_receipt)")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--out", default=None, help="receipt output path")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if args.run_r2e4:
        if not args.checkpoint_manifest or not args.model_config:
            ap.error("--run-r2e4 requires --checkpoint-manifest and --model-config")
        return _cli_run_r2e4(args)
    if args.run_r2e3:
        if not all((args.checkpoint_manifest_a3, args.model_config_a3, args.checkpoint_manifest_control, args.model_config_control)):
            ap.error("--run-r2e3 requires --checkpoint-manifest-a3, --model-config-a3, "
                      "--checkpoint-manifest-control, and --model-config-control")
        return _cli_run_r2e3(args)

    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
