# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Capability verdict for the local evaluator scorers, from a frozen protocol only.

A scorer never states PASSED or FAILED on its own. With a protocol, the verdict comes from
admission() below. Trusted-verifier recomputation of these fields (pinning this file by
sha256) is a separate follow-up change; until it lands, nothing outside the scorers and
the execution preflight reads them.
Without a protocol the score is DIAGNOSTIC: metrics only, no criterion_result, never
admissible.

Criterion block (every field required, no defaults; ruling 74645):

    {"criterion_id": "ember-3b-<capability>-capability-v1",
     "metric": "<key in score metrics>",
     "direction": "higher_is_better" | "lower_is_better",
     "statistic": {"kind": "point"}
                | {"kind": "lower_confidence_bound" | "upper_confidence_bound",
                   "level": 0.5 < level < 1, "method": "wilson_one_sided"},
     "comparator": {"kind": "min_value" | "max_value", "value": <finite number>}
                 | {"kind": "max_of", "reference_factor": <finite > 0>, "chance_factor": <finite > 0>,
                    "reference": {"path": <relative to protocol>, "sha256": <64 hex>},
                    "chance": {"path": <relative to protocol>, "sha256": <64 hex>}},
     "categories": [] | [{"name": str, "metric": str, "count_metric": str,
                          "reference": {"path": ..., "sha256": ...}, "reference_factor": <finite > 0>}, ...]}

higher_is_better pairs with a point or lower bound and min_value (statistic >= value) or
max_of (statistic >= max(reference_factor x reference, chance_factor x chance), ruling 74784);
lower_is_better pairs with a point or upper
bound and max_value (statistic <= value). Every adjudicated score also carries
admission_margin = statistic - bar (bar - statistic for max_value) and the statistic itself;
PASSED iff admission_margin >= 0. A reference or chance artifact is a JSON object
{"value": <finite number>} whose bytes hash to the pinned sha256. wilson_one_sided applies
only to a metric that is a fraction of sample_count independent items in [0, 1]; a bound
on a NON_BERNOULLI metric (WER, weighted recall/FPR and their derivations) is UNDETERMINED.
The criterion key set is closed: any other field (e.g. a legacy min_value) is refused.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from statistics import NormalDist

DIAGNOSTIC = "diagnostic"
ADJUDICATED = "adjudicated"
DIRECTIONS = ("higher_is_better", "lower_is_better")
METHODS = ("wilson_one_sided",)
HEX64 = re.compile(r"[0-9a-f]{64}")
CRITERION_KEYS = ("metric", "direction", "statistic", "comparator", "categories")
# Metrics that are NOT a fraction of independent Bernoulli items: WER is edits/words over
# transcripts (and 1-WER can be negative); recall and FPR are weighted over mixtures. A
# Wilson bound in these units is unsupported, so a bound on them is UNDETERMINED until a
# pre-declared dependence-aware statistic exists (review 76202 D2).
NON_BERNOULLI = frozenset({"word_error_rate", "quality_one_minus_wer",
                           "weighted_recall", "weighted_fpr", "discrimination_j"})


def _finite(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{where}: expected a finite number")
    return float(value)


def _pinned_value(ref: object, base: Path, where: str) -> float:
    if not isinstance(ref, dict) or set(ref) != {"path", "sha256"}:
        raise ValueError(f"{where}: expected exactly {{path, sha256}}")
    if not isinstance(ref["sha256"], str) or not HEX64.fullmatch(ref["sha256"]):
        raise ValueError(f"{where}.sha256: expected 64 lowercase hex")
    if not isinstance(ref["path"], str) or not ref["path"]:
        raise ValueError(f"{where}.path: expected a relative path")
    raw = (base / ref["path"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
        raise ValueError(f"{where}: artifact bytes do not match the pinned sha256")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{where}: artifact is not a JSON object")
    return _finite(payload.get("value"), f"{where}.value")


def check_criterion(criterion: object, criterion_id: str) -> dict:
    """Validate the criterion block's shape; raise ValueError naming the first defect."""
    if not isinstance(criterion, dict):
        raise ValueError("protocol: pre-registered criterion block missing")
    if criterion.get("criterion_id") != criterion_id:
        raise ValueError("protocol: criterion_id does not match the requested criterion")
    for key in CRITERION_KEYS:
        if key not in criterion:
            raise ValueError(f"protocol criterion.{key}: required")
    # Closed key set: a legacy field such as min_value would let an older reader reach a
    # different verdict on the same protocol (review 76202 D1).
    extra = sorted(set(criterion) - {"criterion_id", *CRITERION_KEYS})
    if extra:
        raise ValueError(f"protocol criterion: unknown field(s) {extra}")
    categories = criterion["categories"]
    if not isinstance(categories, list):
        raise ValueError("protocol criterion.categories: expected a list (empty when the criterion has none)")
    seen = set()
    for index, category in enumerate(categories):
        where = f"protocol criterion.categories[{index}]"
        if not isinstance(category, dict) or set(category) != {"name", "metric", "count_metric", "reference", "reference_factor"}:
            raise ValueError(f"{where}: requires exactly name, metric, count_metric, reference and reference_factor")
        for key in ("name", "metric", "count_metric"):
            if not isinstance(category[key], str) or not category[key]:
                raise ValueError(f"{where}.{key}: expected a non-empty string")
        if category["name"] in seen:
            raise ValueError(f"{where}.name: duplicate category")
        seen.add(category["name"])
        if _finite(category["reference_factor"], f"{where}.reference_factor") <= 0:
            raise ValueError(f"{where}.reference_factor: expected a positive number")
    if not isinstance(criterion["metric"], str) or not criterion["metric"]:
        raise ValueError("protocol criterion.metric: expected a metric name")
    direction = criterion["direction"]
    if direction not in DIRECTIONS:
        raise ValueError("protocol criterion.direction: expected higher_is_better or lower_is_better")
    statistic = criterion["statistic"]
    if not isinstance(statistic, dict) or "kind" not in statistic:
        raise ValueError("protocol criterion.statistic.kind: required")
    kind = statistic["kind"]
    allowed = {"higher_is_better": ("point", "lower_confidence_bound"),
               "lower_is_better": ("point", "upper_confidence_bound")}[direction]
    if kind not in allowed:
        raise ValueError(f"protocol criterion.statistic.kind: {kind!r} is not valid for {direction}")
    if kind == "point":
        if set(statistic) != {"kind"}:
            raise ValueError("protocol criterion.statistic: a point statistic takes no level or method")
    else:
        if set(statistic) != {"kind", "level", "method"}:
            raise ValueError("protocol criterion.statistic: a bound requires exactly kind, level and method")
        level = _finite(statistic["level"], "protocol criterion.statistic.level")
        if not 0.5 < level < 1:
            raise ValueError("protocol criterion.statistic.level: expected 0.5 < level < 1")
        if statistic["method"] not in METHODS:
            raise ValueError("protocol criterion.statistic.method: expected wilson_one_sided")
    comparator = criterion["comparator"]
    if not isinstance(comparator, dict) or "kind" not in comparator:
        raise ValueError("protocol criterion.comparator.kind: required")
    ckind = comparator["kind"]
    allowed = {"higher_is_better": ("min_value", "max_of"), "lower_is_better": ("max_value",)}[direction]
    if ckind not in allowed:
        raise ValueError(f"protocol criterion.comparator.kind: {ckind!r} is not valid for {direction}")
    if ckind == "max_of":
        if set(comparator) != {"kind", "reference", "chance", "reference_factor", "chance_factor"}:
            raise ValueError("protocol criterion.comparator: max_of requires exactly kind, reference, chance, reference_factor and chance_factor")
        for key in ("reference_factor", "chance_factor"):
            if _finite(comparator[key], f"protocol criterion.comparator.{key}") <= 0:
                raise ValueError(f"protocol criterion.comparator.{key}: expected a positive number")
    else:
        if set(comparator) != {"kind", "value"}:
            raise ValueError(f"protocol criterion.comparator: {ckind} requires exactly kind and value")
        _finite(comparator["value"], "protocol criterion.comparator.value")
    return criterion


def statistic_value(observed: float, sample_count: int, statistic: dict) -> float:
    kind = statistic["kind"]
    if kind == "point":
        return observed
    if isinstance(sample_count, bool) or not isinstance(sample_count, int) or sample_count < 1:
        raise ValueError("sample_count: expected a positive integer for a confidence bound")
    if not 0.0 <= observed <= 1.0:
        raise ValueError("wilson_one_sided: metric is not a fraction in [0, 1]")
    n, z = sample_count, NormalDist().inv_cdf(float(statistic["level"]))
    centre = (observed + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(observed * (1 - observed) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return centre - half if kind == "lower_confidence_bound" else centre + half


DERIVED = {  # name -> (inputs, formula); computed here and in the verifier, never emitted by a scorer
    "quality_one_minus_wer": (("word_error_rate",), lambda m: 1 - m["word_error_rate"]),  # unclipped (review 74725)
    "discrimination_j": (("weighted_recall", "weighted_fpr"), lambda m: m["weighted_recall"] - m["weighted_fpr"]),
}


def criterion_metrics(metrics: dict) -> dict:
    """The score metrics plus every DERIVED metric whose inputs are present."""
    out = dict(metrics)
    for name, (inputs, formula) in DERIVED.items():
        if name in metrics:
            raise ValueError(f"score metrics.{name}: a derived metric must not be supplied by the scorer")
        if all(key in metrics for key in inputs):
            out[name] = formula({key: _finite(metrics[key], f"score metrics.{key}") for key in inputs})
    return out


UNDETERMINED = "UNDETERMINED"


def _undetermined(reason: str) -> dict:
    return {"criterion_statistic": None, "admission_margin": None, "criterion_result": UNDETERMINED,
            "undetermined_reason": reason}


def admission(metrics: object, sample_count: int, criterion: dict, protocol_dir: Path) -> dict:
    """{criterion_statistic, admission_margin, criterion_result} under a checked criterion.

    admission_margin = statistic - bar (bar - statistic for max_value), with bar =
    max(reference_factor x reference, chance_factor x chance) for max_of, then the MINIMUM
    of that and every category margin (category statistic - reference_factor x category
    reference; ruling 74883). PASSED iff the minimum >= 0. A metric or count the criterion
    needs but the score lacks gives UNDETERMINED (no margin), never a PASS or a zero.
    """
    if not isinstance(metrics, dict) or not metrics:
        raise ValueError("score metrics: expected a non-empty object")
    metrics = criterion_metrics(metrics)
    name = criterion["metric"]
    if name not in metrics:
        return _undetermined(f"score metrics.{name}: absent")
    bound = criterion["statistic"]["kind"] != "point"
    unsupported = [m for m in (name, *(c["metric"] for c in criterion["categories"])) if m in NON_BERNOULLI]
    if bound and unsupported:
        return _undetermined(f"score metrics.{unsupported[0]}: no dependence-aware confidence statistic "
                             "is declared for this metric's units; a Wilson bound does not apply")
    observed = _finite(metrics[name], f"score metrics.{name}")
    value = statistic_value(observed, sample_count, criterion["statistic"])
    comparator = criterion["comparator"]
    if comparator["kind"] == "min_value":
        margin = value - comparator["value"]
    elif comparator["kind"] == "max_value":
        margin = comparator["value"] - value
    else:
        reference = _pinned_value(comparator["reference"], protocol_dir, "protocol criterion.comparator.reference")
        chance = _pinned_value(comparator["chance"], protocol_dir, "protocol criterion.comparator.chance")
        margin = value - max(comparator["reference_factor"] * reference, comparator["chance_factor"] * chance)
    category_margins = {}
    for category in criterion["categories"]:
        where = f"category {category['name']}"
        if category["metric"] not in metrics or category["count_metric"] not in metrics:
            return _undetermined(f"{where}: score metrics lack {category['metric']} or {category['count_metric']}")
        count = metrics[category["count_metric"]]
        if isinstance(count, bool) or not isinstance(count, (int, float)) or count != int(count) or count < 1:
            raise ValueError(f"score metrics.{category['count_metric']}: expected a positive whole count")
        stat = statistic_value(_finite(metrics[category["metric"]], f"score metrics.{category['metric']}"),
                               int(count), criterion["statistic"])
        reference = _pinned_value(category["reference"], protocol_dir, f"protocol {where}.reference")
        bar = category["reference_factor"] * reference
        # Same orientation as the composite: a lower_is_better category passes only at or under its ceiling.
        category_margins[category["name"]] = (bar - stat if criterion["direction"] == "lower_is_better"
                                              else stat - bar)
    overall = min([margin, *category_margins.values()])
    out = {"criterion_statistic": value, "composite_margin": margin, "admission_margin": overall,
           "criterion_result": "PASSED" if overall >= 0 else "FAILED"}
    if category_margins:
        out["category_margins"] = category_margins
    return out


def verdict_fields(protocol: Path | None, criterion_id: str, metrics: dict, sample_count: int) -> dict:
    """Fields to merge into a score payload; raise ValueError on an unusable protocol."""
    if protocol is None:
        return {"criterion_id": criterion_id, "evaluation_role": DIAGNOSTIC}
    raw = protocol.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"protocol is not JSON: {exc}") from exc
    criterion = check_criterion(payload.get("criterion") if isinstance(payload, dict) else None, criterion_id)
    return {
        "criterion_id": criterion_id,
        "evaluation_role": ADJUDICATED,
        **admission(metrics, sample_count, criterion, protocol.parent),
        "protocol_sha256": hashlib.sha256(raw).hexdigest(),
    }
