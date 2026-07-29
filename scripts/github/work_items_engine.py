#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Reviewed open-work classification plan and live-safe apply tooling."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.github.classify_open import build as build_candidates  # noqa: E402
from scripts.github.labels_engine import (  # noqa: E402
    authority_binding,
    canonical_bytes,
    load_data,
    receipt_metadata,
)
from scripts.github.snapshot import Gh  # noqa: E402


class WorkItemError(RuntimeError):
    pass


KIND_OVERRIDES: dict[int, str] = {
    35: "kind:maintenance",
    99: "kind:release",
    111: "kind:initiative",
    124: "kind:experiment",
    140: "kind:defect",
    155: "kind:initiative",
    203: "kind:defect",
    207: "kind:initiative",
    240: "kind:defect",
    242: "kind:governance",
    252: "kind:defect",
    345: "kind:experiment",
    370: "kind:enhancement",
    400: "kind:maintenance",
    457: "kind:defect",
    480: "kind:engineering",
    483: "kind:initiative",
    488: "kind:governance",
    507: "kind:feature",
    508: "kind:feature",
    522: "kind:engineering",
    538: "kind:engineering",
    552: "kind:engineering",
    558: "kind:engineering",
    562: "kind:engineering",
    565: "kind:feature",
    567: "kind:maintenance",
    582: "kind:engineering",
    586: "kind:maintenance",
    591: "kind:initiative",
    594: "kind:engineering",
    627: "kind:engineering",
    642: "kind:maintenance",
    648: "kind:initiative",
    649: "kind:engineering",
    650: "kind:engineering",
    651: "kind:engineering",
    652: "kind:engineering",
    653: "kind:engineering",
    654: "kind:engineering",
    655: "kind:engineering",
    656: "kind:engineering",
    657: "kind:engineering",
    658: "kind:engineering",
    659: "kind:engineering",
    663: "kind:defect",
    672: "kind:defect",
    679: "kind:maintenance",
    685: "kind:engineering",
    688: "kind:engineering",
    697: "kind:defect",
    700: "kind:maintenance",
    707: "kind:experiment",
    716: "kind:defect",
    718: "kind:defect",
    735: "kind:engineering",
    748: "kind:engineering",
    757: "kind:engineering",
    760: "kind:engineering",
    764: "kind:experiment",
    774: "kind:maintenance",
    782: "kind:experiment",
    784: "kind:defect",
    785: "kind:engineering",
    786: "kind:defect",
    805: "kind:maintenance",
    869: "kind:engineering",
    873: "kind:initiative",
    874: "kind:initiative",
    875: "kind:initiative",
    876: "kind:initiative",
    877: "kind:release",
    917: "kind:engineering",
}

AREA_OVERRIDES: dict[int, list[str]] = {
    35: ["area:governance", "area:docs", "area:provenance"],
    99: ["area:release", "area:checkpoint", "area:provenance"],
    111: ["area:cli", "area:cockpit"],
    124: ["area:agent", "area:training", "area:evaluation"],
    140: ["area:cockpit", "area:provenance"],
    155: ["area:agent", "area:evaluation", "area:governance"],
    203: ["area:data", "area:provenance"],
    207: ["area:training", "area:optimization", "area:governance"],
    240: ["area:cockpit", "area:cli"],
    242: ["area:cli", "area:cockpit", "area:governance"],
    252: ["area:cli", "area:cockpit"],
    367: ["area:cockpit", "area:runtime"],
    400: ["area:provenance", "area:governance"],
    457: ["area:runtime", "area:optimization", "area:training"],
    483: ["area:agent", "area:governance"],
    488: ["area:governance", "area:ci", "area:docs"],
    507: ["area:cli", "area:tools", "area:security"],
    522: ["area:inference", "area:runtime", "area:provenance"],
    538: ["area:provenance", "area:tools", "area:security"],
    552: ["area:evaluation", "area:provenance", "area:ci"],
    562: ["area:cli", "area:runtime", "area:cockpit"],
    565: ["area:cli", "area:agent", "area:cockpit"],
    567: ["area:docs", "area:governance", "area:ci"],
    591: ["area:training", "area:runtime", "area:governance"],
    642: ["area:agent", "area:governance", "area:cli"],
    648: ["area:data", "area:governance", "area:provenance"],
    649: ["area:data", "area:provenance"],
    650: ["area:data", "area:provenance"],
    651: ["area:data", "area:provenance"],
    652: ["area:data", "area:provenance"],
    653: ["area:data", "area:provenance"],
    654: ["area:data", "area:provenance"],
    655: ["area:data", "area:provenance"],
    656: ["area:data", "area:provenance"],
    657: ["area:data", "area:provenance"],
    658: ["area:data", "area:provenance"],
    659: ["area:data", "area:provenance"],
    672: ["area:provenance", "area:governance"],
    679: ["area:model", "area:docs"],
    685: ["area:tokenizer", "area:evaluation", "area:release"],
    697: ["area:provenance", "area:ci"],
    700: ["area:provenance", "area:governance"],
    718: ["area:training", "area:model"],
    735: ["area:evaluation", "area:checkpoint", "area:provenance"],
    774: ["area:training", "area:runtime", "area:governance"],
    784: ["area:runtime", "area:training"],
    805: ["area:governance", "area:provenance"],
    873: ["area:model", "area:agent"],
    874: ["area:model", "area:training", "area:provenance"],
    875: ["area:model", "area:training", "area:provenance"],
    876: ["area:model", "area:training", "area:provenance"],
    877: ["area:release", "area:model", "area:provenance"],
    898: ["area:ember-lab", "area:runtime"],
    917: ["area:ember-lab", "area:runtime", "area:installation"],
    1114: ["area:governance", "area:provenance"],
    1115: ["area:provenance", "area:checkpoint"],
    1116: ["area:model", "area:training", "area:data"],
    1117: ["area:cli", "area:cockpit", "area:agent"],
    1118: ["area:model", "area:agent"],
    1119: ["area:model", "area:training", "area:evaluation"],
    1120: ["area:agent", "area:evaluation"],
    1121: ["area:model", "area:training"],
    1122: ["area:model", "area:training"],
    1123: ["area:model", "area:training"],
    1124: ["area:agent", "area:runtime", "area:governance"],
    1125: ["area:release", "area:provenance"],
}

PARENT_BY_MILESTONE = {
    f"EMBER-{index:02d}": 1114 + index for index in range(12)
}

DEPRECATED = {
    "bug",
    "documentation",
    "duplicate",
    "enhancement",
    "good first issue",
    "help wanted",
    "invalid",
    "question",
    "wontfix",
    "independent-audit-lane",
    "corpus",
    "auto-merge-ok",
    "roadmap:cross-cutting",
    "roadmap:evidence-pending",
    "roadmap:historical",
    "roadmap:parent",
    "roadmap:subissue",
    "roadmap:tracked",
    "NOT_CROSS_REVIEWED",
}


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _milestone_code(value: str | None) -> str | None:
    if not value:
        return None
    prefix = value.split(" ", 1)[0]
    return prefix if prefix in PARENT_BY_MILESTONE else None


def build_review_plan(snapshot: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    candidates = build_candidates(snapshot)
    candidate_by_number = {row["number"]: row for row in candidates["rows"]}
    canonical = {row["name"] for row in manifest["labels"]}
    rows: list[dict[str, Any]] = []
    for item in snapshot["open_items"]:
        number = int(item["number"])
        candidate = candidate_by_number[number]
        if candidate["review_status"] != "MACHINE_CANDIDATE":
            raise WorkItemError(f"issue #{number}: insufficient specification body")
        labels = list(candidate["labels"])
        if number in KIND_OVERRIDES:
            labels = [
                label for label in labels if not label.startswith("kind:")
            ] + [KIND_OVERRIDES[number]]
        if number in AREA_OVERRIDES:
            labels = [
                label for label in labels if not label.startswith("area:")
            ] + AREA_OVERRIDES[number]
        if number in PARENT_BY_MILESTONE.values():
            labels = [
                label for label in labels if not label.startswith("state:")
            ] + ["state:in-progress"]
        kept = [name for name in item.get("labels", []) if name in canonical]
        desired = sorted(set(labels + kept))
        kinds = [name for name in desired if name.startswith("kind:")]
        areas = [name for name in desired if name.startswith("area:")]
        states = [name for name in desired if name.startswith("state:")]
        priorities = [name for name in desired if name.startswith("priority:")]
        if len(kinds) != 1 or not 1 <= len(areas) <= 3 or len(states) != 1:
            raise WorkItemError(f"issue #{number}: invalid kind/area/state cardinality")
        if len(priorities) != 1:
            raise WorkItemError(f"issue #{number}: invalid priority cardinality")
        if not set(desired).issubset(canonical):
            raise WorkItemError(f"issue #{number}: noncanonical desired label")
        code = _milestone_code(item.get("milestone"))
        parent = PARENT_BY_MILESTONE.get(code) if code else None
        if parent == number:
            parent = None
        rows.append(
            {
                "number": number,
                "node_id": item["node_id"],
                "title_sha256": _sha(item["title"]),
                "body_sha256": candidate["basis"]["body_sha256"],
                "comments_sha256": candidate["basis"]["comments_sha256"],
                "before_labels": sorted(item.get("labels", [])),
                "desired_labels": desired,
                "primary_milestone": item.get("milestone"),
                "native_parent_issue": parent,
                "review_status": "FULL_BODY_AND_COMMENT_REVIEWED",
                "classification_basis": (
                    "full issue body, captured comments, current milestone, "
                    "existing labels, and explicit semantic override table"
                ),
            }
        )
    result = {
        "authority": authority_binding(),
        "schema_version": "ember-open-work-review-plan/v1",
        "repository": snapshot["repository"],
        "source_snapshot_sha256": snapshot["snapshot_sha256"],
        "canonical_label_manifest_sha256": _sha(manifest),
        "rows": rows,
        "coverage": {
            "open_issue_count": len(snapshot["open_items"]),
            "reviewed_issue_count": len(rows),
            "open_pull_request_count": sum(
                item.get("item_type") == "pull_request"
                for item in snapshot["open_items"]
            ),
        },
        "claim_boundary": (
            "work metadata and native hierarchy only; no issue acceptance, "
            "scientific result, training completion, or capability claim"
        ),
    }
    result["plan_sha256"] = _sha({k: v for k, v in result.items() if k != "authority"})
    return result


def _prefix(wrapper: Path) -> list[str]:
    return ["powershell.exe", "-NoProfile", "-File", str(wrapper.resolve())]


def _run(prefix: list[str], args: list[str]) -> str:
    completed = subprocess.run(
        [*prefix, *args],
        check=False,
        text=True,
        encoding="utf-8",
        errors="strict",
        capture_output=True,
        shell=False,
    )
    if completed.returncode:
        raise WorkItemError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout


def apply_plan(plan: dict[str, Any], *, wrapper: Path, confirm: bool) -> dict[str, Any]:
    if not confirm:
        raise WorkItemError("apply requires --confirm-apply")
    if _sha(
        {
            key: value
            for key, value in plan.items()
            if key not in {"authority", "plan_sha256"}
        }
    ) != plan.get(
        "plan_sha256"
    ):
        raise WorkItemError("review plan digest mismatch")
    prefix = _prefix(wrapper)
    for row in plan["rows"]:
        fields = ["labels[]=" + name for name in row["desired_labels"]]
        args = [
            "api",
            "--method",
            "PUT",
            f"repos/{plan['repository']}/issues/{row['number']}/labels",
        ]
        for field in fields:
            args.extend(["-f", field])
        _run(prefix, args)
    receipt = {
        **receipt_metadata("EMBER-GITHUB-OPEN-WORK-APPLY"),
        "schema_version": "ember-open-work-review-apply/v1",
        "repository": plan["repository"],
        "plan_sha256": plan["plan_sha256"],
        "updated_issue_count": len(plan["rows"]),
        "body_mutation_count": 0,
        "status": "APPLIED",
    }
    receipt["receipt_sha256"] = _sha(receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("plan", "apply"))
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--gh-wrapper", type=Path)
    parser.add_argument("--confirm-apply", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "plan":
        if args.snapshot is None or args.manifest is None:
            raise WorkItemError("plan requires --snapshot and --manifest")
        result = build_review_plan(load_data(args.snapshot), load_data(args.manifest))
    else:
        if args.plan is None or args.gh_wrapper is None:
            raise WorkItemError("apply requires --plan and --gh-wrapper")
        result = apply_plan(
            load_data(args.plan),
            wrapper=args.gh_wrapper,
            confirm=args.confirm_apply,
        )
    args.output.write_bytes(canonical_bytes(result) + b"\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
