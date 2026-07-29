#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Content-addressed label audit, plan, apply, and verify for Ember."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

import yaml


class MigrationError(RuntimeError):
    pass


def load_data(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8", errors="strict"))
    if not isinstance(value, dict):
        raise MigrationError(f"{path}: expected a mapping")
    return value


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def authority_binding() -> dict[str, str]:
    return {
        "goal_id": "EMBER-02",
        "workstream_id": "EMBER-02A",
        "next_executed_outcome": (
            "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
        ),
    }


SHA_CONVENTION = (
    "sha256 fields use lowercase hexadecimal SHA-256 over canonical UTF-8 JSON "
    "(sort_keys=True,separators=(',',':'),ensure_ascii=False); receipt_sha256 "
    "excludes its own field"
)


def receipt_metadata(ticket: str) -> dict[str, Any]:
    return {
        "authority": authority_binding(),
        "ticket": ticket,
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "sha_convention": SHA_CONVENTION,
    }


def _migration_destination(rule: Mapping[str, Any], item_type: str) -> str | None:
    destination = rule.get("destination")
    if isinstance(destination, dict):
        return destination.get(item_type)
    return destination


def _count_label_uses(snapshot: Mapping[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in snapshot.get("items", []):
        for name in item.get("labels", []):
            counts[name] = counts.get(name, 0) + 1
    return counts


def build_plan(
    snapshot: Mapping[str, Any],
    manifest: Mapping[str, Any],
    migrations: Mapping[str, Any],
) -> dict[str, Any]:
    if snapshot.get("schema_version") != "ember-github-label-snapshot/v1":
        raise MigrationError("unsupported snapshot schema")
    if snapshot.get("repository") != manifest.get("repository"):
        raise MigrationError("repository binding mismatch")
    desired = {row["name"]: row for row in manifest.get("labels", [])}
    rules = {row["source_label"]: row for row in migrations.get("rules", [])}
    live = {row["name"]: row for row in snapshot.get("labels", [])}
    known = set(desired) | set(rules)
    unknown = sorted(set(live) - known)
    if unknown:
        raise MigrationError(f"unknown live labels: {', '.join(unknown)}")
    for item in snapshot.get("items", []):
        unknown_item = sorted(set(item.get("labels", [])) - known)
        if unknown_item:
            raise MigrationError(
                f"{item.get('item_type')} #{item.get('number')}: unknown labels "
                + ", ".join(unknown_item)
            )

    definitions: list[dict[str, Any]] = []
    for name in sorted(desired):
        target = desired[name]
        current = live.get(name)
        action = "create" if current is None else "update"
        if current is not None and (
            current.get("color", "").upper() == target["color"].upper()
            and (current.get("description") or "") == target["description"]
        ):
            continue
        definitions.append(
            {
                "action": action,
                "name": name,
                "color": target["color"].upper(),
                "description": target["description"],
            }
        )

    changes: list[dict[str, Any]] = []
    manual: list[dict[str, Any]] = []
    counts = _count_label_uses(snapshot)
    for item in sorted(
        snapshot.get("items", []),
        key=lambda row: (row["item_type"], int(row["number"])),
    ):
        add: set[str] = set()
        remove: set[str] = set()
        for source in sorted(item.get("labels", [])):
            rule = rules.get(source)
            if rule is None or rule["disposition"] == "KEEP":
                continue
            if rule["human_or_operator_judgment_required"] or not rule["deterministic"]:
                manual.append(
                    {
                        "item_type": item["item_type"],
                        "number": item["number"],
                        "source_label": source,
                        "reason": rule["rationale"],
                    }
                )
                continue
            if rule["disposition"] == "DELETE_IF_UNUSED":
                raise MigrationError(
                    f"refusing to delete label {source}: still used by an item"
                )
            destination = _migration_destination(rule, item["item_type"])
            if destination is None:
                raise MigrationError(
                    f"{source}: deterministic mapping has no destination"
                )
            if destination not in desired:
                raise MigrationError(f"{source}: unknown destination {destination}")
            add.add(destination)
            remove.add(source)
        if add or remove:
            changes.append(
                {
                    "item_type": item["item_type"],
                    "number": int(item["number"]),
                    "add": sorted(add),
                    "remove": sorted(remove),
                }
            )

    deletions: list[str] = []
    for source, rule in sorted(rules.items()):
        if rule["disposition"] == "DELETE_IF_UNUSED":
            if counts.get(source, 0):
                raise MigrationError(f"refusing deletion of in-use label {source}")
            if source in live:
                deletions.append(source)

    plan = {
        "schema_version": "ember-label-migration-plan/v1",
        "repository": snapshot["repository"],
        "label_definition_changes": definitions,
        "item_label_changes": changes,
        "manual_judgment_required": manual,
        "label_deletions": deletions,
        "body_mutations": [],
    }
    before_digest = canonical_sha256(snapshot)
    return {
        "authority": authority_binding(),
        "schema_version": "ember-label-migration-envelope/v1",
        "repository": snapshot["repository"],
        "before_snapshot_sha256": before_digest,
        "plan": plan,
        "plan_sha256": canonical_sha256(plan),
    }


class Client(Protocol):
    def create_or_update_label(
        self, *, action: str, name: str, color: str, description: str
    ) -> None: ...

    def edit_item_labels(
        self, *, item_type: str, number: int, add: list[str], remove: list[str]
    ) -> None: ...

    def delete_label(self, name: str) -> None: ...


@dataclass
class RecordingClient:
    calls: list[dict[str, Any]] = field(default_factory=list)

    def create_or_update_label(self, **kwargs: Any) -> None:
        self.calls.append({"operation": "label", **kwargs})

    def edit_item_labels(self, **kwargs: Any) -> None:
        self.calls.append({"operation": "item", **kwargs})

    def delete_label(self, name: str) -> None:
        self.calls.append({"operation": "delete", "name": name})


def apply_plan(
    envelope: Mapping[str, Any],
    *,
    client: Client,
    apply: bool = False,
    current_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if canonical_sha256(envelope.get("plan")) != envelope.get("plan_sha256"):
        raise MigrationError("plan digest mismatch")
    before_digest = envelope.get("before_snapshot_sha256")
    if (
        not isinstance(before_digest, str)
        or len(before_digest) != 64
        or any(character not in "0123456789abcdef" for character in before_digest)
    ):
        raise MigrationError("before snapshot digest is not canonical SHA-256")
    if apply:
        if current_snapshot is None:
            raise MigrationError("apply requires a fresh current snapshot")
        if canonical_sha256(current_snapshot) != envelope["before_snapshot_sha256"]:
            raise MigrationError("live state drifted after planning")
        for row in envelope["plan"]["label_definition_changes"]:
            client.create_or_update_label(**row)
        for row in envelope["plan"]["item_label_changes"]:
            client.edit_item_labels(**row)
        for name in envelope["plan"]["label_deletions"]:
            client.delete_label(name)
    result = {
        **receipt_metadata("EMBER-GITHUB-LABEL-MIGRATION"),
        "schema_version": "ember-label-migration-receipt/v1",
        "repository": envelope["repository"],
        "before_snapshot_sha256": envelope["before_snapshot_sha256"],
        "plan_sha256": envelope["plan_sha256"],
        "result": {
            "mode": "APPLY" if apply else "DRY_RUN",
            "operation_count": (
                len(envelope["plan"]["label_definition_changes"])
                + len(envelope["plan"]["item_label_changes"])
                + len(envelope["plan"]["label_deletions"])
            ),
            "issue_body_mutation_count": 0,
        },
    }
    result["receipt_sha256"] = canonical_sha256(result)
    return result


def write_canonical(path: Path, value: Mapping[str, Any]) -> None:
    path.write_bytes(canonical_bytes(value) + b"\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("audit", "plan", "apply", "verify"):
        node = sub.add_parser(command)
        node.add_argument("--snapshot", type=Path, required=True)
        node.add_argument("--manifest", type=Path, required=True)
        node.add_argument("--migrations", type=Path, required=True)
        node.add_argument("--output", type=Path)
        if command == "apply":
            node.add_argument("--confirm-apply", action="store_true")
    args = parser.parse_args(argv)
    snapshot = load_data(args.snapshot)
    manifest = load_data(args.manifest)
    migrations = load_data(args.migrations)
    envelope = build_plan(snapshot, manifest, migrations)
    if args.command in {"audit", "plan", "verify"}:
        value: Mapping[str, Any] = envelope
    else:
        # The CLI remains dry-run unless an explicit apply switch is supplied.
        # Live mutation uses the protected wrapper-specific client added by the
        # default-branch labels-sync workflow.
        value = apply_plan(
            envelope,
            client=RecordingClient(),
            apply=False,
            current_snapshot=snapshot if args.confirm_apply else None,
        )
        if args.confirm_apply:
            raise MigrationError(
                "direct CLI mutation is disabled; use the protected labels-sync workflow"
            )
    if args.output:
        write_canonical(args.output, value)
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
