#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Certify a post-merge branch capture published without mutating a captured ref."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.remote_branch_salvage import (
    PacketError,
    _canonical,
    validate_packet,
    validate_public_summary,
)


_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_REF = re.compile(r"^refs/heads/(?!/)(?!.*(?:\.\.|\\|\s|//|@\{|[~^:?*\[]))[^/]+(?:/[^/]+)*$")
_CONTEXT_KEYS = {
    "schema_version",
    "repository",
    "mode",
    "workflow_ref",
    "workflow_sha",
    "run_id",
    "run_attempt",
    "excluded_refs",
    "ref_mutations_performed",
}


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PacketError(f"cannot read {path.name}: {exc}") from exc


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strict_object(value: Any, *, field: str, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PacketError(f"{field} must be an object")
    if set(value) != keys:
        raise PacketError(
            f"{field} has invalid keys; "
            f"missing={sorted(keys - set(value))}, extra={sorted(set(value) - keys)}"
        )
    return value


def _refs(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list):
        raise PacketError(f"{field} must be a list")
    if any(not isinstance(ref, str) or _REF.fullmatch(ref) is None for ref in value):
        raise PacketError(f"{field} contains an invalid ref")
    if value != sorted(value) or len(value) != len(set(value)):
        raise PacketError(f"{field} must be uniquely sorted")
    return value


def build_certification_receipt(
    *,
    packet: Mapping[str, Any],
    summary: Mapping[str, Any],
    context: Mapping[str, Any],
    packet_sha256: str,
    summary_sha256: str,
    context_sha256: str,
) -> dict[str, Any]:
    validate_packet(packet)
    validate_public_summary(summary)
    context = _strict_object(context, field="publication_context", keys=_CONTEXT_KEYS)
    if (
        context["schema_version"] != "ember-remote-branch-publication-context-v1"
        or context["repository"] != "wordingone/ember"
        or context["mode"] != "GITHUB_ACTIONS_WORKFLOW_ARTIFACT"
        or context["workflow_ref"] != "refs/heads/master"
    ):
        raise PacketError("publication context identity is invalid")
    workflow_sha = context["workflow_sha"]
    if not isinstance(workflow_sha, str) or _SHA1.fullmatch(workflow_sha) is None:
        raise PacketError("publication_context.workflow_sha is invalid")
    if workflow_sha != packet["master_sha"] or workflow_sha != summary["master_sha"]:
        raise PacketError("workflow SHA, packet master, and summary master must match")
    if (
        not isinstance(context["run_id"], str)
        or not context["run_id"].isdigit()
        or isinstance(context["run_attempt"], bool)
        or not isinstance(context["run_attempt"], int)
        or context["run_attempt"] < 1
    ):
        raise PacketError("publication workflow identity is invalid")

    # These context fields are defense-in-depth declarations, not the primary
    # publication authority. The workflow's read-only permissions prevent ref
    # mutation, while collect_remote_branch_salvage.py requires element-wise
    # equality of every live ref and head before/after capture. Keep both those
    # independently tested gates if these declarations ever change.
    excluded_refs = _refs(context["excluded_refs"], field="publication_context.excluded_refs")
    mutated_refs = _refs(
        context["ref_mutations_performed"],
        field="publication_context.ref_mutations_performed",
    )
    if excluded_refs:
        raise PacketError("certification capture cannot exclude live refs")
    captured_refs = {row["ref"] for row in packet["rows"]}
    if captured_refs.intersection(mutated_refs):
        raise PacketError("publication mutated a ref inside the captured population")
    if mutated_refs:
        raise PacketError("certification publication must not mutate Git refs")

    drifted_refs = [
        row["ref"] for row in packet["rows"]
        if row["ref_stability"]["captured_sha"] != row["ref_stability"]["preexecution_sha"]
    ]
    if drifted_refs:
        raise PacketError("capture window contains ref drift")
    if summary["private_packet_sha256"] != packet["packet_sha256"]:
        raise PacketError("public summary is not bound to the supplied private packet")
    for field in ("branch_count", "selection_sha256"):
        if summary[field] != packet[field]:
            raise PacketError(f"public summary {field} does not match private packet")

    receipt = {
        "schema_version": "ember-remote-branch-salvage-certification-v1",
        "repository": "wordingone/ember",
        "status": "CANDIDATE_NON_AUTHORIZING_CAPTURE",
        "master_sha": packet["master_sha"],
        "captured_at": packet["captured_at"],
        "branch_count": packet["branch_count"],
        "selection_sha256": packet["selection_sha256"],
        "packet_sha256": packet_sha256,
        "packet_canonical_sha256": packet["packet_sha256"],
        "summary_file_sha256": summary_sha256,
        "summary_canonical_sha256": summary["summary_sha256"],
        "publication_context_sha256": context_sha256,
        "workflow": {
            "ref": context["workflow_ref"],
            "sha": context["workflow_sha"],
            "run_id": context["run_id"],
            "run_attempt": context["run_attempt"],
        },
        "excluded_refs": excluded_refs,
        "ref_mutations_performed": mutated_refs,
        "publication_invariant": (
            "stable across the bounded capture window and undisturbed by its own "
            "artifact publication"
        ),
        "deletion_authority": "NOT_GRANTED",
        "public_mutation_performed": False,
    }
    receipt["receipt_sha256"] = hashlib.sha256(_canonical(receipt)).hexdigest()
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--publication-context", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        packet = _read(args.packet)
        summary = _read(args.summary)
        context = _read(args.publication_context)
        receipt = build_certification_receipt(
            packet=packet,
            summary=summary,
            context=context,
            packet_sha256=_sha256_file(args.packet),
            summary_sha256=_sha256_file(args.summary),
            context_sha256=_sha256_file(args.publication_context),
        )
        args.output.write_bytes(_canonical(receipt) + b"\n")
        print(
            json.dumps(
                {
                    "status": receipt["status"],
                    "master_sha": receipt["master_sha"],
                    "branches": receipt["branch_count"],
                    "receipt_sha256": receipt["receipt_sha256"],
                },
                sort_keys=True,
            )
        )
    except PacketError as exc:
        print(f"REMOTE_BRANCH_SALVAGE_CERTIFICATION FAIL: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
