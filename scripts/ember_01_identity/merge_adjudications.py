#!/usr/bin/env python3
# goal_id: EMBER-01
# workstream_id: EMBER-01C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Merge independent consumer reviews into one exact, source-bound manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path


LANE_SCHEMA = "ember-consumer-adjudication-review-v1"
SET_SCHEMA = "ember-consumer-adjudication-review-set-v1"
SEMANTIC_FIELDS = (
    "current_input", "derived_label", "protocol", "failure_behavior",
    "claim_effect", "conflict", "integration_requirement",
)


def _scope_label(scope: object) -> str:
    if isinstance(scope, str) and scope:
        return scope
    if isinstance(scope, (dict, list)):
        return json.dumps(scope, sort_keys=True, separators=(",", ":"))
    raise ValueError("adjudication lane scope is invalid")


def _digest(row: dict) -> str:
    return str(
        row["line_sha256"] if row.get("evidence_scope") == "LINE"
        else row["content_sha256"]
    )


def _key(row: dict) -> tuple[str, int, str, str]:
    return (str(row["path"]), int(row["line"]), str(row["category"]), _digest(row))


def _review_key(row: dict) -> tuple[str, int, str, str]:
    return (
        str(row["path"]), int(row["line"]), str(row["category"]),
        str(row["evidence_sha256"]),
    )


def _validate_source(source: object) -> tuple[str, dict, dict]:
    if not isinstance(source, dict) or not isinstance(source.get("evidence"), list):
        raise ValueError("source census is invalid")
    public = [
        row for row in source.get("roots", [])
        if isinstance(row, dict) and row.get("root_id") == "public-master"
    ]
    if len(public) != 1 or not re.fullmatch(
        r"[0-9a-f]{40}", str(public[0].get("source_commit"))
    ):
        raise ValueError("source census lacks one exact public source commit")
    exact: dict[tuple[str, int, str, str], dict] = {}
    triples: dict[tuple[str, str, str], list[tuple[str, int, str, str]]] = defaultdict(list)
    for row in source["evidence"]:
        if not isinstance(row, dict) or row.get("source_role") != "EXECUTABLE_CANDIDATE":
            continue
        key = _key(row)
        if key in exact:
            raise ValueError(f"source census repeats an exact executable selector: {key}")
        exact[key] = row
        triples[(key[0], key[2], key[3])].append(key)
    return str(public[0]["source_commit"]), exact, triples


def merge_adjudication_lanes(
    lanes: list[tuple[str, bytes]], source: object
) -> dict:
    source_commit, source_rows, source_triples = _validate_source(source)
    verified = {
        key for key, row in source_rows.items()
        if row.get("record_class") == "VERIFIED_CONSUMER"
    }
    if not lanes:
        raise ValueError("at least one adjudication lane is required")
    consumers: dict[tuple[str, int, str, str], dict] = {}
    nonconsumers: dict[tuple[str, int, str, str], dict] = {}
    nonconsumer_files: dict[tuple[str, str], dict] = {}
    lane_receipts: list[dict[str, str]] = []

    def expanded_keys(item: dict) -> list[tuple[str, int, str, str]]:
        triple = (
            str(item.get("path")), str(item.get("category")),
            str(item.get("evidence_sha256")),
        )
        if "line" in item:
            if not isinstance(item["line"], int) or item["line"] < 0:
                raise ValueError("adjudication line is invalid")
            keys = [(triple[0], item["line"], triple[1], triple[2])]
        else:
            keys = source_triples.get(triple, [])
        if not keys or any(key not in source_rows for key in keys):
            raise ValueError(f"adjudication selector is absent from source: {triple}")
        return sorted(keys)

    for supplied_scope, raw in lanes:
        try:
            lane = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"adjudication lane is not valid JSON: {supplied_scope}") from exc
        required = {
            "schema", "source_commit", "scope", "coverage", "consumer_rows",
            "nonconsumer_rows", "nonconsumer_files",
        }
        if (
            not isinstance(lane, dict) or set(lane) != required
            or lane.get("schema") != LANE_SCHEMA
            or lane.get("source_commit") != source_commit
            or _scope_label(lane.get("scope")) != supplied_scope
            or not isinstance(lane.get("coverage"), dict)
            or any(not isinstance(lane.get(name), list) for name in (
                "consumer_rows", "nonconsumer_rows", "nonconsumer_files"
            ))
        ):
            raise ValueError(f"adjudication lane schema/source mismatch: {supplied_scope}")
        lane_receipts.append({
            "scope": supplied_scope, "sha256": hashlib.sha256(raw).hexdigest()
        })
        for item in lane["consumer_rows"]:
            required_fields = {"path", "category", "evidence_sha256", *SEMANTIC_FIELDS}
            if (
                not isinstance(item, dict)
                or set(item) - {"line"} != required_fields
                or any(not isinstance(item.get(field), str) or not item[field]
                       for field in required_fields)
                or not re.fullmatch(r"[0-9a-f]{64}", item["evidence_sha256"])
            ):
                raise ValueError("consumer adjudication row is invalid")
            for key in expanded_keys(item):
                if key in verified:
                    continue
                if key in consumers or key in nonconsumers:
                    raise ValueError(f"duplicate or conflicting row disposition: {key}")
                consumers[key] = {**item, "line": key[1]}
        for item in lane["nonconsumer_rows"]:
            required_fields = {"path", "category", "evidence_sha256", "review_basis"}
            if (
                not isinstance(item, dict)
                or set(item) - {"line"} != required_fields
                or any(not isinstance(item.get(field), str) or not item[field]
                       for field in required_fields)
                or not re.fullmatch(r"[0-9a-f]{64}", item["evidence_sha256"])
            ):
                raise ValueError("nonconsumer adjudication row is invalid")
            for key in expanded_keys(item):
                if key in verified:
                    continue
                if key in consumers or key in nonconsumers:
                    raise ValueError(f"duplicate or conflicting row disposition: {key}")
                nonconsumers[key] = {**item, "line": key[1]}
        for item in lane["nonconsumer_files"]:
            if (
                not isinstance(item, dict)
                or set(item) != {"path", "content_sha256", "review_basis"}
                or any(not isinstance(item.get(field), str) or not item[field]
                       for field in item)
                or not re.fullmatch(r"[0-9a-f]{64}", item["content_sha256"])
            ):
                raise ValueError("whole-file nonconsumer adjudication is invalid")
            key = (item["path"], item["content_sha256"])
            if key in nonconsumer_files:
                raise ValueError(f"duplicate whole-file disposition: {key}")
            nonconsumer_files[key] = item

    reviewed_consumer = reviewed_nonconsumer = duplicates = 0
    used_files: set[tuple[str, str]] = set()
    unresolved: list[tuple[str, int, str, str]] = []
    for key, source_row in source_rows.items():
        file_key = (key[0], str(source_row["content_sha256"]))
        if file_key in nonconsumer_files:
            used_files.add(file_key)
            if key in verified or key in consumers:
                raise ValueError(
                    f"whole-file nonconsumer conflicts with consumer: {key}"
                )
        dispositions = int(key in consumers) + int(key in nonconsumers)
        if dispositions > 1:
            duplicates += 1
            continue
        if key in verified:
            reviewed_consumer += 1
        elif key in consumers:
            reviewed_consumer += 1
        elif key in nonconsumers:
            reviewed_nonconsumer += 1
        elif file_key in nonconsumer_files:
            reviewed_nonconsumer += 1
        else:
            unresolved.append(key)
    unused_files = sorted(set(nonconsumer_files) - used_files)
    if unresolved or duplicates or unused_files:
        raise ValueError(
            "adjudication lanes do not close the source census: "
            f"unresolved={len(unresolved)} duplicates={duplicates} "
            f"unused_files={unused_files} unresolved_sample={unresolved[:10]}"
        )
    return {
        "schema": SET_SCHEMA,
        "source_commit": source_commit,
        "lanes": sorted(lane_receipts, key=lambda row: row["scope"]),
        "coverage": {
            "source_executable_rows": len(source_rows),
            "reviewed_consumer_rows": reviewed_consumer,
            "reviewed_nonconsumer_rows": reviewed_nonconsumer,
            "unresolved_executable_rows": 0,
            "duplicate_dispositions": 0,
        },
        "consumer_rows": sorted(consumers.values(), key=_review_key),
        "nonconsumer_rows": sorted(nonconsumers.values(), key=_review_key),
        "nonconsumer_files": sorted(
            nonconsumer_files.values(), key=lambda row: (row["path"], row["content_sha256"])
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-census", type=Path, required=True)
    parser.add_argument("--lane", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = json.loads(args.source_census.read_text(encoding="utf-8"))
    lane_inputs = []
    for path in args.lane:
        raw = path.read_bytes()
        payload = json.loads(raw)
        lane_inputs.append((_scope_label(payload.get("scope")), raw))
    merged = merge_adjudication_lanes(lane_inputs, source)
    args.output.write_text(
        json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
