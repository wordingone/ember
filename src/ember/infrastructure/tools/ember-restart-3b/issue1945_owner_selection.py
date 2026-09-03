# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""Consume immutable #2024 receipts and select the next #1945 source owner."""

from __future__ import annotations

import argparse
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable


CLAIM_BOUNDARY = "ATTRIBUTION_AND_SELECTION_ONLY_NO_TREATMENT_SPEEDUP_20K_CREDIT"
ALLOWLIST_SCHEMA = "ember-issue1945-source-owner-allowlist-v1"
RECEIPT_SCHEMA = "ember-issue1945-source-owner-selection-v1"
SITE_RE = re.compile(r"^(?P<path>.+)\((?P<line>[1-9][0-9]*)\): (?P<symbol>.+)$")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_bound_json(path: Path, expected_raw_sha256: str | None = None) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    raw_sha256 = _sha256(raw)
    if expected_raw_sha256 is not None and raw_sha256 != expected_raw_sha256:
        raise ValueError(f"raw sha mismatch for {path}: {raw_sha256} != {expected_raw_sha256}")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    declared_self = value.get("self_sha256")
    if not isinstance(declared_self, str):
        raise ValueError(f"{path} lacks self_sha256")
    without_self = {key: item for key, item in value.items() if key != "self_sha256"}
    computed_self = _sha256(_canonical_bytes(without_self))
    if computed_self != declared_self:
        raise ValueError(f"self sha mismatch for {path}: {computed_self} != {declared_self}")
    return value, raw_sha256


def _decimal(value: object, field: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{field} must be a decimal") from error
    if not number.is_finite() or number < 0:
        raise ValueError(f"{field} must be finite and nonnegative")
    return number


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value, "f")


def _load_allowlist(path: Path) -> tuple[dict[str, Any], str, dict[str, str]]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "source_rules",
        "mapping_rule",
        "selection_rule",
        "minimum_named_attribution_ratio",
    }:
        raise ValueError("allowlist has unknown or missing fields")
    if value["schema_version"] != ALLOWLIST_SCHEMA:
        raise ValueError("allowlist schema mismatch")
    if value["mapping_rule"] != "FIRST_STACK_FRAME_MATCHING_EXACTLY_ONE_DECLARED_BASENAME":
        raise ValueError("mapping rule mismatch")
    if value["selection_rule"] != "MAX_ATTRIBUTED_NON_OVERHEAD_DEVICE_TIME_THEN_LEXICAL_SOURCE_SITE":
        raise ValueError("selection rule mismatch")
    minimum = _decimal(value["minimum_named_attribution_ratio"], "minimum_named_attribution_ratio")
    if minimum != Decimal("0.99"):
        raise ValueError("minimum named attribution ratio must be exactly 0.99")
    rules: dict[str, str] = {}
    source_rules = value["source_rules"]
    if not isinstance(source_rules, list) or not source_rules:
        raise ValueError("source_rules must be a nonempty list")
    for index, rule in enumerate(source_rules):
        if not isinstance(rule, dict) or set(rule) != {"basename", "class"}:
            raise ValueError(f"source_rules[{index}] has unknown or missing fields")
        basename = rule["basename"]
        owner_class = rule["class"]
        if not isinstance(basename, str) or not basename or "/" in basename or "\\" in basename:
            raise ValueError(f"source_rules[{index}].basename is invalid")
        if owner_class not in {"non_overhead", "overhead"}:
            raise ValueError(f"source_rules[{index}].class is invalid")
        if basename in rules:
            raise ValueError(f"ambiguous source basename: {basename}")
        rules[basename] = owner_class
    return value, _sha256(raw), rules


def _map_source_site(stack: object, rules: dict[str, str]) -> tuple[str, str]:
    if not isinstance(stack, list) or not stack or any(not isinstance(frame, str) for frame in stack):
        raise ValueError("source_stack must be a nonempty list of strings")
    for frame in stack:
        match = SITE_RE.fullmatch(frame.replace("\\", "/"))
        if match is None:
            continue
        basename = match.group("path").rsplit("/", 1)[-1]
        if basename in rules:
            site = f"{basename}({match.group('line')}): {match.group('symbol')}"
            return site, rules[basename]
    raise ValueError(f"event has zero declared source-site candidates: {stack!r}")


def _require_input_chain(
    ledger: dict[str, Any],
    ledger_raw_sha256: str,
    offline: dict[str, Any],
    offline_raw_sha256: str,
    comparison: dict[str, Any],
) -> None:
    if ledger.get("mode") != "issue2024-union-one-shot" or ledger.get("result") != "PASS":
        raise ValueError("ledger is not the passing #2024 one-shot measurement")
    if offline.get("mode") != "issue2024-union-one-shot" or offline.get("result") != "PASS":
        raise ValueError("offline link witness is not the passing #2024 one-shot derivation")
    derivation = offline.get("kernel_trace", {}).get("offline_trace_derivation", {})
    if derivation.get("parent_measurement_raw_sha256") != ledger_raw_sha256:
        raise ValueError("offline witness does not bind the ledger raw hash")
    if derivation.get("parent_measurement_self_sha256") != ledger.get("self_sha256"):
        raise ValueError("offline witness does not bind the ledger self hash")
    if comparison.get("result") != "PASS":
        raise ValueError("union comparison is not PASS")
    if comparison.get("one_shot_raw_sha256") != offline_raw_sha256:
        raise ValueError("union comparison does not bind the offline witness raw hash")
    if comparison.get("one_shot_self_sha256") != offline.get("self_sha256"):
        raise ValueError("union comparison does not bind the offline witness self hash")
    if comparison.get("one_shot_only_structural_count") != 0 or comparison.get("sharded_only_structural_count") != 0:
        raise ValueError("union comparison contains structural remainder")
    commits = {
        ledger.get("identity", {}).get("execution_source_commit"),
        offline.get("identity", {}).get("execution_source_commit"),
        comparison.get("execution_source_commit"),
    }
    if len(commits) != 1 or not isinstance(next(iter(commits)), str):
        raise ValueError("input execution source commits disagree")


def build_receipt(
    *,
    ledger_path: Path | str,
    ledger_raw_sha256: str,
    offline_path: Path | str,
    comparison_path: Path | str,
    comparison_raw_sha256: str,
    allowlist_path: Path | str,
    source_master: str,
    expected_event_count: int = 2,
    argv: Iterable[str],
) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{40}", source_master):
        raise ValueError("source_master must be a lowercase 40-hex commit")
    if expected_event_count <= 0:
        raise ValueError("expected_event_count must be positive")
    ledger, observed_ledger_raw = _read_bound_json(Path(ledger_path), ledger_raw_sha256)
    offline, observed_offline_raw = _read_bound_json(Path(offline_path))
    comparison, observed_comparison_raw = _read_bound_json(Path(comparison_path), comparison_raw_sha256)
    _require_input_chain(ledger, observed_ledger_raw, offline, observed_offline_raw, comparison)
    allowlist, allowlist_raw_sha256, rules = _load_allowlist(Path(allowlist_path))

    event_ledger = ledger.get("kernel_trace", {}).get("full_precision_unmapped_event_ledger")
    if not isinstance(event_ledger, dict):
        raise ValueError("ledger lacks full_precision_unmapped_event_ledger")
    events = event_ledger.get("events")
    if not isinstance(events, list) or len(events) != expected_event_count:
        raise ValueError(f"event count mismatch: {len(events) if isinstance(events, list) else 'invalid'} != {expected_event_count}")
    if event_ledger.get("reconciliation_gap_ns") != 0:
        raise ValueError("reconciliation_gap_ns must be zero")
    excluded = _decimal(event_ledger.get("excluded_self_device_time_total_us"), "excluded_self_device_time_total_us")
    if excluded != 0:
        raise ValueError("unmapped/excluded device time must be zero")

    declared_total = _decimal(event_ledger.get("declared_self_device_time_total_us"), "declared_self_device_time_total_us")
    ledger_total = _decimal(event_ledger.get("ledger_self_device_time_total_us"), "ledger_self_device_time_total_us")
    # The predecessor contract publishes its reconciliation in integer ns.  Preserve that
    # authority exactly: a sub-nanosecond Decimal rendering delta is admissible only when the
    # receipt's integer reconciliation gap is zero.
    if abs(declared_total - ledger_total) > Decimal("0.001"):
        raise ValueError("declared and ledger device-time totals disagree by more than one ns")
    if ledger_total <= 0:
        raise ValueError("ledger device-time total must be positive")

    mappings: list[dict[str, Any]] = []
    totals: defaultdict[str, Decimal] = defaultdict(Decimal)
    owner_classes: dict[str, str] = {}
    identities: set[tuple[object, object]] = set()
    mapped_total = Decimal(0)
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f"events[{index}] must be an object")
        identity = (event.get("event_id"), event.get("event_ordinal"))
        if identity in identities:
            raise ValueError(f"duplicate event identity: {identity}")
        identities.add(identity)
        device_time = _decimal(event.get("self_device_time_us"), f"events[{index}].self_device_time_us")
        site, owner_class = _map_source_site(event.get("source_stack"), rules)
        if site in owner_classes and owner_classes[site] != owner_class:
            raise ValueError(f"ambiguous normalized source site: {site}")
        owner_classes[site] = owner_class
        totals[site] += device_time
        mapped_total += device_time
        mappings.append(
            {
                "event_id": event.get("event_id"),
                "event_ordinal": event.get("event_ordinal"),
                "source_site": site,
                "owner_class": owner_class,
                "self_device_time_us": _decimal_text(device_time),
            }
        )
    if mapped_total != ledger_total:
        raise ValueError(f"mapped device time does not reconcile: {mapped_total} != {ledger_total}")
    attribution_ratio = mapped_total / ledger_total
    minimum_ratio = _decimal(allowlist["minimum_named_attribution_ratio"], "minimum_named_attribution_ratio")
    if attribution_ratio < minimum_ratio:
        raise ValueError(f"named attribution ratio below threshold: {attribution_ratio} < {minimum_ratio}")
    candidates = [(site, total) for site, total in totals.items() if owner_classes[site] == "non_overhead"]
    if not candidates:
        raise ValueError("no non-overhead source site is selectable")
    selected_site, selected_total = sorted(candidates, key=lambda item: (-item[1], item[0]))[0]

    payload: dict[str, Any] = {
        "schema_version": RECEIPT_SCHEMA,
        "result": "PASS",
        "claim_boundary": CLAIM_BOUNDARY,
        "source_master": source_master,
        "argv": list(argv),
        "inputs": {
            "ledger_raw_sha256": observed_ledger_raw,
            "ledger_self_sha256": ledger["self_sha256"],
            "offline_link_raw_sha256": observed_offline_raw,
            "offline_link_self_sha256": offline["self_sha256"],
            "union_comparison_raw_sha256": observed_comparison_raw,
            "union_comparison_self_sha256": comparison["self_sha256"],
            "execution_source_commit": comparison["execution_source_commit"],
        },
        "allowlist_raw_sha256": allowlist_raw_sha256,
        "mapping_rule": allowlist["mapping_rule"],
        "selection_rule": allowlist["selection_rule"],
        "minimum_named_attribution_ratio": allowlist["minimum_named_attribution_ratio"],
        "event_count": len(events),
        "mapped_event_count": len(mappings),
        "measured_device_time_total_us": _decimal_text(ledger_total),
        "mapped_device_time_total_us": _decimal_text(mapped_total),
        "unmapped_device_time_us": "0",
        "named_attribution_ratio": _decimal_text(attribution_ratio),
        "source_site_totals": [
            {
                "source_site": site,
                "owner_class": owner_classes[site],
                "self_device_time_us": _decimal_text(totals[site]),
            }
            for site in sorted(totals)
        ],
        "event_mappings": mappings,
        "selected_source_site": selected_site,
        "selected_source_device_time_us": _decimal_text(selected_total),
        "next_successor_entry_predicate": f"TREATMENT_ARM_FOR_{selected_site}_IS_IMPLEMENTED_AND_PREFLIGHT_GREEN",
    }
    payload["self_sha256"] = _sha256(_canonical_bytes(payload))
    return payload


def _write_no_overwrite(path: Path, receipt: dict[str, Any]) -> None:
    raw = _canonical_bytes(receipt)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--ledger-raw-sha256", required=True)
    parser.add_argument("--offline-link", type=Path, required=True)
    parser.add_argument("--union-comparison", type=Path, required=True)
    parser.add_argument("--union-comparison-raw-sha256", required=True)
    parser.add_argument("--allowlist", type=Path, required=True)
    parser.add_argument("--source-master", required=True)
    parser.add_argument("--expected-event-count", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    parsed_argv = list(sys.argv[1:] if argv is None else argv)
    args = _parser().parse_args(parsed_argv)
    receipt = build_receipt(
        ledger_path=args.ledger,
        ledger_raw_sha256=args.ledger_raw_sha256,
        offline_path=args.offline_link,
        comparison_path=args.union_comparison,
        comparison_raw_sha256=args.union_comparison_raw_sha256,
        allowlist_path=args.allowlist,
        source_master=args.source_master,
        expected_event_count=args.expected_event_count,
        argv=[Path(sys.argv[0]).name, *parsed_argv],
    )
    _write_no_overwrite(args.output, receipt)
    print(json.dumps({
        "result": receipt["result"],
        "selected_source_site": receipt["selected_source_site"],
        "self_sha256": receipt["self_sha256"],
        "output": str(args.output),
    }, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
