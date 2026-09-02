#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Retire deprecated label definitions after preserving closed-history events."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.ember.governance.scripts.github.labels import GhClient, capture_label_snapshot  # noqa: E402
from src.ember.governance.src.ember.governance.scripts.github.labels_engine import (  # noqa: E402
    authority_binding,
    load_data,
    receipt_metadata,
)
from src.ember.governance.scripts.github.snapshot import Gh  # noqa: E402


class RetirementError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def build_plan(
    snapshot: dict[str, Any],
    manifest: dict[str, Any],
    migrations: dict[str, Any],
) -> dict[str, Any]:
    canonical = {row["name"] for row in manifest["labels"]}
    legacy = {row["source_label"] for row in migrations["rules"]}
    live = {row["name"] for row in snapshot["labels"]}
    deprecated = sorted(live - canonical)
    unknown = sorted(set(deprecated) - legacy)
    if unknown:
        raise RetirementError(f"unknown noncanonical labels: {', '.join(unknown)}")
    changes = []
    uses = {name: 0 for name in deprecated}
    for item in snapshot["items"]:
        attached = sorted(set(item["labels"]) & set(deprecated))
        if not attached:
            continue
        if item["state"] == "OPEN":
            raise RetirementError(
                f"{item['item_type']} #{item['number']}: deprecated labels still open"
            )
        for name in attached:
            uses[name] += 1
        changes.append(
            {
                "item_type": item["item_type"],
                "number": item["number"],
                "remove": attached,
            }
        )
    result = {
        "authority": authority_binding(),
        "schema_version": "ember-deprecated-label-retirement-plan/v1",
        "repository": snapshot["repository"],
        "before_snapshot_sha256": _sha(snapshot),
        "deprecated_labels": deprecated,
        "closed_item_changes": changes,
        "use_counts": uses,
        "body_mutation_count": 0,
        "claim_boundary": (
            "label associations and definitions only; GitHub history events, "
            "issue bodies, acceptance clauses, and closure states are preserved"
        ),
    }
    result["plan_sha256"] = _sha({k: v for k, v in result.items() if k != "authority"})
    return result


def apply(
    plan: dict[str, Any],
    snapshot: dict[str, Any],
    client: Any,
    *,
    confirm: bool,
) -> dict[str, Any]:
    if not confirm:
        raise RetirementError("apply requires --confirm-apply")
    expected = _sha(
        {
            key: value
            for key, value in plan.items()
            if key not in {"authority", "plan_sha256"}
        }
    )
    if expected != plan.get("plan_sha256"):
        raise RetirementError("plan digest mismatch")
    if _sha(snapshot) != plan["before_snapshot_sha256"]:
        raise RetirementError("live label state drift")
    for row in plan["closed_item_changes"]:
        client.edit_item_labels(
            item_type=row["item_type"],
            number=row["number"],
            add=[],
            remove=row["remove"],
        )
    for name in plan["deprecated_labels"]:
        client.delete_label(name)
    receipt = {
        **receipt_metadata("EMBER-GITHUB-DEPRECATED-LABEL-RETIREMENT"),
        "schema_version": "ember-deprecated-label-retirement-receipt/v1",
        "repository": plan["repository"],
        "plan_sha256": plan["plan_sha256"],
        "retired_definition_count": len(plan["deprecated_labels"]),
        "closed_item_change_count": len(plan["closed_item_changes"]),
        "body_mutation_count": 0,
        "status": "APPLIED",
    }
    receipt["receipt_sha256"] = _sha(receipt)
    return receipt


def _prefix(wrapper: Path) -> list[str]:
    return [
        "powershell.exe",
        "-NoProfile",
        "-File",
        str(wrapper.resolve()),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("plan", "apply"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--migrations", type=Path, required=True)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", default="wordingone/ember")
    parser.add_argument("--gh-wrapper", type=Path, required=True)
    parser.add_argument("--confirm-apply", action="store_true")
    args = parser.parse_args(argv)
    gh = Gh(_prefix(args.gh_wrapper), args.repository)
    snapshot = capture_label_snapshot(gh)
    if args.command == "plan":
        value = build_plan(
            snapshot, load_data(args.manifest), load_data(args.migrations)
        )
    else:
        if args.plan is None:
            raise RetirementError("apply requires --plan")
        value = apply(
            load_data(args.plan),
            snapshot,
            GhClient(gh),
            confirm=args.confirm_apply,
        )
    args.output.write_bytes(_canonical(value) + b"\n")
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
