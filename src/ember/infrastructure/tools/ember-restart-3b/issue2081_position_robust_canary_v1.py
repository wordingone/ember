#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Measured-slot position-gated successor to the closed issue #2081 canary."""

from __future__ import annotations

import copy
import importlib.util
import json
import math
import re
import statistics
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Mapping, Sequence


_BASE_PATH = Path(__file__).with_name("issue2071_qk_rope_matched_loss_canary_v1.py")
_SPEC = importlib.util.spec_from_file_location("issue2071_base", _BASE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("ISSUE2071_BASE_IMPORT_REFUSED")
BASE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(BASE)
BASE_RUNNER_SHA256 = BASE.sha256_path(_BASE_PATH)
HISTORICAL_BASE_RUNNER_SHA256 = "a76488b723fa86e29f813e319ba07aa4e272e984fb1f8f33f310b2dc50220828"
HISTORICAL_TREATMENT_MODEL_SHA256 = "71cb56da6a7dd3735842a081f58a167713b18685056f7172d7641627f7d0229e"
HISTORICAL_TREATMENT_TEST_SHA256 = "57c488dab9ff9e85e4310d1cc2c9e40bfceacd2aa3a1c06935056975c2842fe3"
PREDECESSOR_TEXT_LAB_CORPUS_SHA256 = (
    "c494b4cd325a0b0c91e4c2075f5b1aad42a413af037590063781384d210261ca"
)
AA_CORPUS_REPO_PATH = "data/ember-restart-3b/owned-text-lab-corpus-v4.json"

SCHEMA_VERSION = "ember-issue2099-measured-slot-position-matched-loss-canary-v1"
AA_SCHEMA_VERSION = "ember-issue2110-aa-position-balanced-warm-stable-canary-v1"
POSITION_RATIO_FLOOR = 1.0 / 1.5
POSITION_RATIO_CEILING = 1.5
AA_PAIRED_RATIO_FLOOR = 0.98
AA_PAIRED_RATIO_CEILING = 1.02
AA_PAIR_ORDERS = (("control", "treatment"), ("treatment", "control")) * 4
AA_WARM_STABILITY_K = 3
AA_WARM_STABILITY_EPSILON = 0.06
# One previous and one current K-wide moving-median window are observable at
# K+1 updates.  A fixed deadline also keeps both A/A arms on the same cursor.
AA_WARM_STABILITY_READINESS_UPDATE_LIMIT = AA_WARM_STABILITY_K + 1
_BASE_RUN_ONE_UPDATE = BASE.run_one_update
_BASE_ADJUDICATE_PAIRS = BASE.adjudicate_pairs

_MEASUREMENT_FIELDS = {
    "arm",
    "pair",
    "loss",
    "processed_tokens",
    "event_seconds",
    "tokens_per_second",
    "start_identity",
    "post_model_identity",
    "post_optimizer_identity",
    "optimizer_structure_census",
    "post_scheduler_identity",
    "post_scaler_identity",
    "post_cursor",
    "post_rng_identity",
    "backend_identity",
    "sampled_parameters",
    "event_ids",
    "warm_loss",
    "warm_processed_tokens",
    "warm_event_seconds",
    "warm_tokens_per_second",
    "warm_event_ids",
    "warm_update",
    "runner_source_sha256",
    "row_sha256",
}
_AA_MEASUREMENT_FIELDS = _MEASUREMENT_FIELDS | {
    "executed_slot",
    "pair_order",
    "warm_updates",
    "warm_updates_to_stability",
}


def _positive_finite(value: object, refusal: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ValueError(refusal)
    return result


def load_measurement_pairs(
    path: Path, *, aa_mode: bool = False
) -> list[list[dict[str, object]]]:
    """Load the successor's hash-bound warm-plus-measured row schema."""
    rows: list[dict[str, object]] = []
    for index, raw in enumerate(path.resolve(strict=True).read_bytes().splitlines()):
        try:
            row = json.loads(raw)
        except (TypeError, ValueError) as error:
            raise ValueError(f"MEASUREMENT_ROW_JSON_REFUSED:{index}") from error
        required = _AA_MEASUREMENT_FIELDS if aa_mode else _MEASUREMENT_FIELDS
        if not isinstance(row, dict) or set(row) != required:
            raise ValueError(f"MEASUREMENT_ROW_SCHEMA_REFUSED:{index}")
        claimed = row.pop("row_sha256")
        if claimed != BASE.sha256_bytes(BASE.canonical(row)):
            raise ValueError(f"MEASUREMENT_ROW_HASH_DRIFT_REFUSED:{index}")
        row["row_sha256"] = claimed
        rows.append(row)
    if len(rows) != 2 * len(BASE.PAIR_ORDERS):
        raise ValueError(f"MEASUREMENT_ROW_COUNT_REFUSED:{len(rows)}")
    source_hashes = {str(row["runner_source_sha256"]) for row in rows}
    if len(source_hashes) != 1 or len(next(iter(source_hashes))) != 64:
        raise ValueError("MEASUREMENT_RUNNER_SOURCE_DRIFT_REFUSED")
    pairs: list[list[dict[str, object]]] = []
    for pair_index in range(len(BASE.PAIR_ORDERS)):
        pair_rows = rows[2 * pair_index : 2 * pair_index + 2]
        if [row["pair"] for row in pair_rows] != [pair_index, pair_index]:
            raise ValueError(f"MEASUREMENT_ROW_ORDER_REFUSED:{pair_index}")
        pairs.append(pair_rows)
    return pairs


def paired_median_ratio(
    pairs: Sequence[Sequence[Mapping[str, object]]],
) -> tuple[list[float], float]:
    """Return the frozen median-of-eight measured treatment/control ratios."""
    if len(pairs) != len(BASE.PAIR_ORDERS):
        raise ValueError("PAIR_COUNT_REFUSED")
    ratios: list[float] = []
    for pair_index, (rows, expected_order) in enumerate(zip(pairs, BASE.PAIR_ORDERS)):
        if tuple(row.get("arm") for row in rows) != expected_order:
            raise ValueError(f"ABBA_ORDER_DRIFT_REFUSED:{pair_index}")
        rates = {
            str(row["arm"]): _positive_finite(
                row.get("tokens_per_second"), "TIMING_SAMPLE_INVALID_REFUSED"
            )
            for row in rows
        }
        ratios.append(rates["treatment"] / rates["control"])
    return ratios, statistics.median(ratios)


def adjudicate_pairs(
    pairs: Sequence[Sequence[Mapping[str, object]]],
    *,
    aa_mode: bool = False,
) -> dict[str, object]:
    """Retain every integrity gate, then gate position from measured rows only."""
    predecessor = _BASE_ADJUDICATE_PAIRS(pairs)
    measured_rates_by_arm_and_slot: dict[str, dict[int, list[float]]] = {
        "control": {0: [], 1: []},
        "treatment": {0: [], 1: []},
    }
    warm_events: list[str] = []
    warm_updates_to_stability_by_arm: dict[str, list[int]] = {
        "control": [],
        "treatment": [],
    }
    cure_fields_present = any(
        "executed_slot" in row for rows in pairs for row in rows
    )
    for pair_index, rows in enumerate(pairs):
        expected_order = AA_PAIR_ORDERS[pair_index]
        for executed_slot, row in enumerate(rows):
            arm = str(row["arm"])
            if aa_mode and cure_fields_present:
                if (
                    int(row.get("executed_slot", -1)) != executed_slot
                    or tuple(row.get("pair_order", ())) != expected_order
                    or tuple(item.get("arm") for item in rows) != expected_order
                ):
                    raise ValueError(f"AA_PAIR_ORDER_DRIFT_REFUSED:{pair_index}")
                warm_updates = row.get("warm_updates")
                warm_count = int(row.get("warm_updates_to_stability", 0))
                if (
                    not isinstance(warm_updates, list)
                    or warm_count != len(warm_updates)
                    or warm_count != AA_WARM_STABILITY_READINESS_UPDATE_LIMIT
                    or not all(isinstance(item, Mapping) for item in warm_updates)
                    or warm_updates[-1] != row.get("warm_update")
                    or not warm_stability_reached(
                        [item.get("tokens_per_second") for item in warm_updates]
                    )
                ):
                    raise ValueError("AA_WARM_STABILITY_RECORD_REFUSED")
                for update in warm_updates:
                    update_tokens = int(update.get("processed_tokens", 0))
                    update_seconds = _positive_finite(
                        update.get("event_seconds"),
                        "AA_WARM_TIMING_SAMPLE_INVALID_REFUSED",
                    )
                    update_rate = _positive_finite(
                        update.get("tokens_per_second"),
                        "AA_WARM_TIMING_SAMPLE_INVALID_REFUSED",
                    )
                    update_events = update.get("event_ids")
                    if (
                        update_tokens <= 0
                        or not math.isclose(
                            update_rate,
                            update_tokens / update_seconds,
                            rel_tol=1e-12,
                            abs_tol=1e-12,
                        )
                        or not isinstance(update_events, list)
                        or len(update_events) != 2
                        or not all(
                            isinstance(item, str) and item for item in update_events
                        )
                    ):
                        raise ValueError("AA_WARM_STABILITY_RECORD_REFUSED")
                    warm_events.extend(update_events)
                warm_updates_to_stability_by_arm[arm].append(warm_count)
            measured_rate = _positive_finite(
                row.get("tokens_per_second"), "TIMING_SAMPLE_INVALID_REFUSED"
            )
            warm_tokens = int(row.get("warm_processed_tokens", 0))
            warm_seconds = _positive_finite(
                row.get("warm_event_seconds"), "WARM_TIMING_SAMPLE_INVALID_REFUSED"
            )
            warm_rate = _positive_finite(
                row.get("warm_tokens_per_second"), "WARM_TIMING_SAMPLE_INVALID_REFUSED"
            )
            warm_loss = _positive_finite(
                row.get("warm_loss"), "WARM_RECORD_DRIFT_REFUSED"
            )
            if warm_tokens <= 0 or not math.isclose(
                warm_rate,
                warm_tokens / warm_seconds,
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise ValueError("WARM_TOKEN_ACCOUNTING_REFUSED")
            event_ids = row.get("warm_event_ids")
            if (
                not isinstance(event_ids, list)
                or len(event_ids) != 2
                or not all(isinstance(item, str) and item for item in event_ids)
            ):
                raise ValueError("WARM_CUDA_EVENT_IDENTITY_REFUSED")
            warm_update = row.get("warm_update")
            try:
                warm_record_matches = (
                    isinstance(warm_update, Mapping)
                    and math.isclose(float(warm_update["loss"]), warm_loss)
                    and int(warm_update["processed_tokens"]) == warm_tokens
                    and math.isclose(float(warm_update["event_seconds"]), warm_seconds)
                    and math.isclose(float(warm_update["tokens_per_second"]), warm_rate)
                    and warm_update["event_ids"] == event_ids
                )
            except (KeyError, TypeError, ValueError):
                warm_record_matches = False
            if not warm_record_matches:
                raise ValueError("WARM_RECORD_DRIFT_REFUSED")
            if not (aa_mode and cure_fields_present):
                warm_events.extend(event_ids)
            measured_rates_by_arm_and_slot[arm][executed_slot].append(measured_rate)
    if len(warm_events) != len(set(warm_events)):
        raise ValueError("WARM_CUDA_EVENT_IDENTITY_REFUSED")
    measured_slot_gate_by_arm = {
        arm: {
            "executed_slot_0_measured_median_tps": statistics.median(values[0]),
            "executed_slot_1_measured_median_tps": statistics.median(values[1]),
        }
        for arm, values in measured_rates_by_arm_and_slot.items()
    }
    for values in measured_slot_gate_by_arm.values():
        values["measured_slot_ratio"] = (
            values["executed_slot_0_measured_median_tps"]
            / values["executed_slot_1_measured_median_tps"]
        )
    position_gate_pass = all(
        POSITION_RATIO_FLOOR
        <= values["measured_slot_ratio"]
        <= POSITION_RATIO_CEILING
        for values in measured_slot_gate_by_arm.values()
    )
    if not aa_mode:
        for arm, values in measured_slot_gate_by_arm.items():
            position_ratio = values["measured_slot_ratio"]
            if POSITION_RATIO_FLOOR <= position_ratio <= POSITION_RATIO_CEILING:
                continue
            raise ValueError(
                f"TIMING_POSITION_EFFECT_REFUSED:{arm}:{position_ratio}"
            )
    paired_ratios, median_ratio = paired_median_ratio(pairs)
    if aa_mode:
        aa_result = (
            "HARNESS_POSITION_INDEPENDENT"
            if position_gate_pass
            and AA_PAIRED_RATIO_FLOOR
            <= median_ratio
            <= AA_PAIRED_RATIO_CEILING
            else "HARNESS_CURE_INSUFFICIENT"
        )
    else:
        aa_result = None
    return {
        **predecessor,
        "disposition": (
            aa_result
            if aa_mode
            else (
                "PASS_POSITIVE"
                if median_ratio >= BASE.SPEEDUP_RATIO_FLOOR
                else "REJECTED"
            )
        ),
        "paired_treatment_control_ratios": paired_ratios,
        "median_paired_treatment_control_ratio": median_ratio,
        "measured_slot_gate_by_arm": measured_slot_gate_by_arm,
        "position_gate_ratio_orientation": "executed-slot-0-over-executed-slot-1",
        "warm_rows_used_for_gating": False,
        "estimator": "median-of-eight-paired-ratios-measured-slot-gate-v2",
        **(
            {
                "aa_paired_median_ratio": median_ratio,
                "aa_position_gate_pass": position_gate_pass,
                "aa_result": aa_result,
                "aa_pair_order_alternated": tuple(
                    tuple(row.get("arm") for row in rows) for rows in pairs
                )
                == AA_PAIR_ORDERS,
                "aa_warm_stability_k": AA_WARM_STABILITY_K,
                "aa_warm_stability_epsilon": AA_WARM_STABILITY_EPSILON,
                **(
                    {
                        "warm_updates_to_stability_by_arm": (
                            warm_updates_to_stability_by_arm
                        )
                    }
                    if cure_fields_present
                    else {}
                ),
            }
            if aa_mode
            else {}
        ),
    }


def warm_stability_reached(
    rates: Sequence[object],
    *,
    k: int = AA_WARM_STABILITY_K,
    epsilon: float = AA_WARM_STABILITY_EPSILON,
) -> bool:
    """Compare consecutive K-update moving medians using a fixed relative bar."""
    values = [
        _positive_finite(value, "AA_WARM_TIMING_SAMPLE_INVALID_REFUSED")
        for value in rates
    ]
    if len(values) < k + 1:
        return False
    previous = statistics.median(values[-k - 1 : -1])
    current = statistics.median(values[-k:])
    return abs(current - previous) / previous < epsilon


def _with_event_prefix(
    update: Mapping[str, object], prefix: str
) -> dict[str, object]:
    rebound = copy.deepcopy(dict(update))
    rebound["event_ids"] = [f"{prefix}-{value}" for value in update["event_ids"]]
    return rebound


def run_warm_then_measure(*, aa_mode: bool = False, **kwargs):
    if int(kwargs.get("pair", 0)) < 0:
        return _BASE_RUN_ONE_UPDATE(**kwargs)
    if aa_mode:
        warm_updates: list[dict[str, object]] = []
        warm_cursor = kwargs["cursor"]
        for warm_index in range(AA_WARM_STABILITY_READINESS_UPDATE_LIMIT):
            warm_kwargs = dict(kwargs)
            warm_kwargs["cursor"] = warm_cursor
            warm, warm_cursor = _BASE_RUN_ONE_UPDATE(**warm_kwargs)
            warm_updates.append(
                _with_event_prefix(warm, f"warm-{warm_index + 1}")
            )
            if warm_stability_reached(
                [item["tokens_per_second"] for item in warm_updates]
            ):
                break
        else:
            raise ValueError("AA_WARM_STABILITY_NOT_REACHED_REFUSED")
    else:
        warm, warm_cursor = _BASE_RUN_ONE_UPDATE(**kwargs)
        warm_updates = [_with_event_prefix(warm, "warm")]
    measured_kwargs = dict(kwargs)
    measured_kwargs["cursor"] = warm_cursor
    measured, measured_cursor = _BASE_RUN_ONE_UPDATE(**measured_kwargs)
    final_warm = warm_updates[-1]
    measured_event_ids = [f"measured-{value}" for value in measured["event_ids"]]
    measured.update({
        "warm_loss": final_warm["loss"],
        "warm_processed_tokens": final_warm["processed_tokens"],
        "warm_event_seconds": final_warm["event_seconds"],
        "warm_tokens_per_second": final_warm["tokens_per_second"],
        "warm_event_ids": final_warm["event_ids"],
        "warm_update": copy.deepcopy(final_warm),
        "event_ids": measured_event_ids,
    })
    if aa_mode:
        pair_index = int(kwargs["pair"])
        pair_order = AA_PAIR_ORDERS[pair_index]
        measured.update({
            "executed_slot": pair_order.index(str(kwargs["arm"])),
            "pair_order": list(pair_order),
            "warm_updates": warm_updates,
            "warm_updates_to_stability": len(warm_updates),
        })
    return measured, measured_cursor


def rebind_receipt(
    value: dict[str, object],
    *,
    control_rebased_head: str,
    treatment_rebased_head: str,
    control_source_model_sha256: str,
    treatment_source_model_sha256: str,
    aa_mode: bool = False,
    aa_text_lab_corpus_sha256: str | None = None,
) -> dict[str, object]:
    for label, digest in (
        ("CONTROL_SOURCE_MODEL", control_source_model_sha256),
        ("TREATMENT_SOURCE_MODEL", treatment_source_model_sha256),
    ):
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError(f"{label}_SHA256_REFUSED:{digest}")
    rebound = copy.deepcopy(value)
    rebound["schema_version"] = AA_SCHEMA_VERSION if aa_mode else SCHEMA_VERSION
    if aa_mode:
        if aa_text_lab_corpus_sha256 is None or re.fullmatch(
            r"[0-9a-f]{64}", aa_text_lab_corpus_sha256
        ) is None:
            raise ValueError("AA_CORPUS_DERIVED_PIN_REFUSED")
        rebound["issue"] = 2110
        rebound["aa_mode"] = True
        rebound["aa_source_head"] = control_rebased_head
        rebound["aa_pair_order_alternated"] = True
        rebound["aa_warm_stability_k"] = AA_WARM_STABILITY_K
        rebound["aa_warm_stability_epsilon"] = AA_WARM_STABILITY_EPSILON
        rebound["text_lab_corpus_sha256"] = aa_text_lab_corpus_sha256
        rebound["predecessor_text_lab_corpus_sha256"] = (
            PREDECESSOR_TEXT_LAB_CORPUS_SHA256
        )
    elif rebound.get("issue") in (2071, 2081):
        rebound["issue"] = 2099
    if aa_mode or "control_source_head" in rebound:
        rebound["control_source_head"] = control_rebased_head
    if aa_mode or "treatment_source_head" in rebound:
        rebound["treatment_source_head"] = treatment_rebased_head
    rebound["control_source_model_sha256"] = control_source_model_sha256
    rebound["treatment_source_model_sha256"] = treatment_source_model_sha256
    rebound["source_lineage"] = {
        "control_predecessor_head": (
            control_rebased_head if aa_mode else BASE.CONTROL_HEAD
        ),
        "treatment_predecessor_head": (
            treatment_rebased_head if aa_mode else BASE.TREATMENT_HEAD
        ),
    }
    rebound["predecessor_runner_source_sha256"] = BASE_RUNNER_SHA256
    rebound["historical_predecessor_runner_source_sha256"] = (
        HISTORICAL_BASE_RUNNER_SHA256
    )
    if "source_model_sha256" in rebound:
        rebound["current_canonical_model_sha256"] = rebound["source_model_sha256"]
    if "source_test_sha256" in rebound:
        rebound["current_canonical_test_sha256"] = rebound["source_test_sha256"]
    rebound["historical_microprofile_model_sha256"] = (
        HISTORICAL_TREATMENT_MODEL_SHA256
    )
    rebound["historical_microprofile_test_sha256"] = (
        HISTORICAL_TREATMENT_TEST_SHA256
    )
    if "claim_boundary" in rebound:
        rebound["claim_boundary"] = (
            "EIGHT-PAIR POSITION-BALANCED, WARM-STABLE A/A HARNESS TEST ONLY; "
            "NO TREATMENT, 20K, CAPABILITY, CAMPAIGN, EMBER-02, OR GOAL CREDIT"
            if aa_mode
            else "EIGHT WARMED-PAIR MEASURED-SLOT POSITION-GATED MATCHED-LOSS CANARY ONLY; "
            "NO 20K, CAPABILITY, SUFFICIENT-PRETRAINING, CAMPAIGN, EMBER-02, OR GOAL CREDIT"
        )
    return rebound


def write_exclusive_refusal(
    output: Path, error: BaseException
) -> tuple[str, str] | None:
    """Write only a nonterminal refusal sidecar; never coexist with terminal."""
    if isinstance(error, SystemExit) and error.code in (None, 0):
        return None
    path = output.with_name(output.stem + ".refusal.json")
    if output.exists() or path.exists():
        return None
    return BASE.write_receipt(path, {
        "schema_version": SCHEMA_VERSION,
        "result": "REFUSED",
        "refusal_class": type(error).__name__,
        "refusal_message": str(error),
        "last_phase": BASE._LAST_PHASE,
        "issue": 2099,
        "predecessor_runner_source_sha256": BASE_RUNNER_SHA256,
        "historical_predecessor_runner_source_sha256": (
            HISTORICAL_BASE_RUNNER_SHA256
        ),
    })


def translate_pre_spine_path(root: Path, path: Path) -> Path:
    old_model = root / "tools" / "ember-restart-3b" / "model.py"
    if path.resolve() == old_model.resolve():
        return root / "src" / "ember" / "model" / "model.py"
    old_test = root / "tests" / "ember_restart_model" / "test_model.py"
    if path.resolve() == old_test.resolve():
        return (
            root
            / "tests"
            / "ember_restart_model"
            / "domain-governance"
            / "test_model.py"
        )
    return path


def validate_source_identity_bindings(
    *,
    microprofile: Mapping[str, object],
    current_model_path: Path,
    current_test_path: Path,
    current_model_sha256: str,
    current_test_sha256: str,
) -> dict[str, str]:
    """Validate current canonical bytes and their historical microprofile ancestor."""

    for path, expected in (
        (current_model_path, current_model_sha256),
        (current_test_path, current_test_sha256),
    ):
        actual = BASE.sha256_path(path)
        if actual != expected:
            raise ValueError(f"INPUT_HASH_DRIFT_REFUSED:{path}:{actual}")
    BASE.validate_microprofile_source_identity(
        microprofile,
        current_model_sha256=current_model_sha256,
        current_test_sha256=current_test_sha256,
        historical_model_sha256=HISTORICAL_TREATMENT_MODEL_SHA256,
        historical_test_sha256=HISTORICAL_TREATMENT_TEST_SHA256,
    )
    return {
        "current_canonical_model_sha256": current_model_sha256,
        "current_canonical_test_sha256": current_test_sha256,
        "historical_microprofile_model_sha256": HISTORICAL_TREATMENT_MODEL_SHA256,
        "historical_microprofile_test_sha256": HISTORICAL_TREATMENT_TEST_SHA256,
    }


def _require_head(value: str, label: str) -> str:
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ValueError(f"{label}_HEAD_REFUSED:{value}")
    return value


def configure_base(
    *,
    root: Path,
    control_rebased_head: str,
    treatment_rebased_head: str,
    aa_mode: bool = False,
) -> None:
    control_rebased_head = _require_head(control_rebased_head, "CONTROL_REBASED")
    treatment_rebased_head = _require_head(treatment_rebased_head, "TREATMENT_REBASED")
    original_sha256_path = BASE.sha256_path
    original_git = BASE.git
    original_write_receipt = BASE.write_receipt
    aa_text_lab_corpus_sha256: str | None = None
    if aa_mode:
        try:
            aa_corpus_bytes = original_git(
                root,
                "show",
                f"{control_rebased_head}:{AA_CORPUS_REPO_PATH}",
            )
        except (OSError, RuntimeError) as error:
            raise ValueError("AA_CORPUS_BLOB_MISSING_REFUSED") from error
        aa_text_lab_corpus_sha256 = BASE.sha256_bytes(aa_corpus_bytes)

    def translated_sha256_path(path: Path) -> str:
        return original_sha256_path(translate_pre_spine_path(root, Path(path)))

    historical_control_spec = (
        f"{BASE.CONTROL_HEAD}:tools/ember-restart-3b/model.py"
    )
    treatment_model_spec = (
        f"{treatment_rebased_head}:src/ember/model/model.py"
    )

    def rebased_git(repo_root: Path, *args: str) -> bytes:
        if args == ("show", historical_control_spec):
            return original_git(
                repo_root,
                "show",
                f"{control_rebased_head}:src/ember/model/model.py",
            )
        return original_git(repo_root, *args)

    def validate_rebased_treatment(
        checkout: Path, head: str, porcelain: bytes
    ) -> None:
        if head != treatment_rebased_head:
            raise ValueError(
                f"TREATMENT_REBASED_HEAD_REFUSED:{head}:{treatment_rebased_head}"
            )
        if porcelain:
            raise ValueError(
                "TREATMENT_CHECKOUT_DIRTY_REFUSED:"
                + porcelain.decode("utf-8", errors="replace")
            )

    def bound_write_receipt(path: Path, value: dict[str, object]):
        control_source_model_sha256 = BASE.sha256_bytes(
            rebased_git(root, "show", historical_control_spec)
        )
        treatment_source_model_sha256 = BASE.sha256_bytes(
            rebased_git(root, "show", treatment_model_spec)
        )
        return original_write_receipt(
            path,
            rebind_receipt(
                value,
                control_rebased_head=control_rebased_head,
                treatment_rebased_head=treatment_rebased_head,
                control_source_model_sha256=control_source_model_sha256,
                treatment_source_model_sha256=treatment_source_model_sha256,
                aa_mode=aa_mode,
                aa_text_lab_corpus_sha256=aa_text_lab_corpus_sha256,
            ),
        )

    for module_path in (
        root / "src" / "ember" / "model",
        root / "src" / "ember" / "training",
        root / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b",
    ):
        sys.path.insert(0, str(module_path))
    BASE.__file__ = str(Path(__file__).resolve(strict=True))
    BASE.SCHEMA_VERSION = AA_SCHEMA_VERSION if aa_mode else SCHEMA_VERSION
    BASE.TEXT_LAB_CORPUS_SHA256 = (
        aa_text_lab_corpus_sha256
        if aa_mode
        else PREDECESSOR_TEXT_LAB_CORPUS_SHA256
    )
    BASE.sha256_path = translated_sha256_path
    BASE.git = rebased_git
    BASE.validate_treatment_checkout = validate_rebased_treatment
    BASE.run_one_update = lambda **kwargs: run_warm_then_measure(
        aa_mode=aa_mode, **kwargs
    )
    BASE.load_measurement_pairs = lambda path: load_measurement_pairs(
        path, aa_mode=aa_mode
    )
    BASE.adjudicate_pairs = lambda pairs: adjudicate_pairs(pairs, aa_mode=aa_mode)
    BASE.write_receipt = bound_write_receipt


def _pop_required_cli_value(name: str) -> str:
    try:
        index = sys.argv.index(name)
        value = sys.argv[index + 1]
    except (ValueError, IndexError) as error:
        raise ValueError(f"{name[2:].upper().replace('-', '_')}_REQUIRED") from error
    del sys.argv[index : index + 2]
    return value


def main() -> int:
    aa_mode = "--aa" in sys.argv
    if aa_mode:
        sys.argv.remove("--aa")
    control_rebased_head = _pop_required_cli_value("--control-rebased-head")
    supplied_treatment_head = _pop_required_cli_value("--treatment-rebased-head")
    treatment_rebased_head = (
        control_rebased_head if aa_mode else supplied_treatment_head
    )
    if "--adjudicate" in sys.argv:
        root = Path(__file__).resolve(strict=True).parents[5]
    else:
        try:
            root = Path(sys.argv[sys.argv.index("--repo-root") + 1]).resolve(strict=True)
        except (ValueError, IndexError, OSError) as error:
            raise ValueError("REPO_ROOT_REQUIRED") from error
    configure_base(
        root=root,
        control_rebased_head=control_rebased_head,
        treatment_rebased_head=treatment_rebased_head,
        aa_mode=aa_mode,
    )
    if aa_mode and supplied_treatment_head != control_rebased_head:
        raise ValueError(
            "AA_TREATMENT_HEAD_MUST_EQUAL_CONTROL_REFUSED:"
            f"{supplied_treatment_head}:{control_rebased_head}"
        )
    if "--adjudicate" not in sys.argv:
        for option in (
            "--historical-microprofile-model-sha256",
            "--historical-microprofile-test-sha256",
        ):
            if option in sys.argv:
                raise ValueError(
                    f"{option[2:].upper().replace('-', '_')}_OVERRIDE_REFUSED"
                )
        sys.argv.extend([
            "--historical-microprofile-model-sha256",
            HISTORICAL_TREATMENT_MODEL_SHA256,
            "--historical-microprofile-test-sha256",
            HISTORICAL_TREATMENT_TEST_SHA256,
        ])
    return BASE.main()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BaseException as error:
        try:
            output = None
            if "--output" in sys.argv:
                output = Path(sys.argv[sys.argv.index("--output") + 1]).resolve()
            elif "--adjudicate" in sys.argv and sys.argv.index("--adjudicate") + 1 < len(sys.argv):
                output = (
                    Path(sys.argv[sys.argv.index("--adjudicate") + 1]).resolve()
                    / "terminal.json"
                )
            if output is not None:
                write_exclusive_refusal(output, error)
        except BaseException:
            traceback.print_exc()
        raise
