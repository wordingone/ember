#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Compare two downloaded branch-capture artifacts before certifying stability."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.finalize_remote_branch_salvage import build_certification_receipt
from scripts.remote_branch_salvage import PacketError, _canonical


_SOURCE_NAMES = {
    "branches_pre",
    "branches_post",
    "pulls",
    "tags",
    "releases",
    "deployments",
    "public_master",
}


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PacketError(f"cannot read {path}: {exc}") from exc


def _file_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise PacketError(f"cannot hash {path}: {exc}") from exc


def _mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PacketError(f"{field} must be an object")
    return value


def _load_artifact(root: Path) -> dict[str, Any]:
    packet_path = root / "packet.json"
    summary_path = root / "public-summary.json"
    context_path = root / "publication-context.json"
    candidate_path = root / "candidate-receipt.json"
    packet = _mapping(_read(packet_path), field=f"{root.name}.packet")
    summary = _mapping(_read(summary_path), field=f"{root.name}.summary")
    context = _mapping(_read(context_path), field=f"{root.name}.context")
    candidate = _mapping(_read(candidate_path), field=f"{root.name}.candidate")
    regenerated = build_certification_receipt(
        packet=packet,
        summary=summary,
        context=context,
        packet_sha256=_file_sha256(packet_path),
        summary_sha256=_file_sha256(summary_path),
        context_sha256=_file_sha256(context_path),
    )
    if dict(candidate) != regenerated:
        raise PacketError(f"{root.name} candidate receipt does not reproduce from artifact bytes")

    source_evidence = _mapping(
        packet.get("source_evidence"), field=f"{root.name}.packet.source_evidence"
    )
    if set(source_evidence) != _SOURCE_NAMES:
        raise PacketError(f"{root.name} source-evidence set is incomplete")
    for name in sorted(_SOURCE_NAMES):
        if _file_sha256(root / f"{name}.json") != source_evidence[name]:
            raise PacketError(f"{root.name} raw source {name} does not match packet")
    return {
        "packet": packet,
        "summary": summary,
        "context": context,
        "candidate": candidate,
        "candidate_file_sha256": _file_sha256(candidate_path),
    }


def _packet_projection(packet: Mapping[str, Any]) -> dict[str, Any]:
    projection = dict(packet)
    projection.pop("captured_at")
    projection.pop("packet_sha256")
    return projection


def _summary_projection(summary: Mapping[str, Any]) -> dict[str, Any]:
    projection = dict(summary)
    projection.pop("captured_at")
    projection.pop("private_packet_sha256")
    projection.pop("summary_sha256")
    return projection


def compare_artifacts(
    first_root: Path,
    second_root: Path,
    *,
    expected_first_run_id: str,
    expected_second_run_id: str,
) -> dict[str, Any]:
    first = _load_artifact(first_root)
    second = _load_artifact(second_root)
    first_context = first["context"]
    second_context = second["context"]
    if (
        first_context["run_id"] != expected_first_run_id
        or second_context["run_id"] != expected_second_run_id
    ):
        raise PacketError(
            "downloaded artifact run ID does not match expected workflow run"
        )
    if first_context["run_id"] == second_context["run_id"]:
        raise PacketError("two distinct workflow runs are required")
    if first_context["workflow_sha"] != second_context["workflow_sha"]:
        raise PacketError("workflow runs must bind the same exact master")

    first_packet_projection = _packet_projection(first["packet"])
    second_packet_projection = _packet_projection(second["packet"])
    first_summary_projection = _summary_projection(first["summary"])
    second_summary_projection = _summary_projection(second["summary"])
    if (
        first_packet_projection != second_packet_projection
        or first_summary_projection != second_summary_projection
    ):
        raise PacketError("capture evidence differs across workflow runs")

    stable_projection = {
        "packet": first_packet_projection,
        "public_summary": first_summary_projection,
    }
    receipt = {
        "schema_version": "ember-remote-branch-two-run-certification-v1",
        "repository": "wordingone/ember",
        "status": "CERTIFIED_TWO_RUN_NON_AUTHORIZING_CAPTURE",
        "master_sha": first["packet"]["master_sha"],
        "branch_count": first["packet"]["branch_count"],
        "selection_sha256": first["packet"]["selection_sha256"],
        "captured_at": [
            first["packet"]["captured_at"],
            second["packet"]["captured_at"],
        ],
        "run_ids": [first_context["run_id"], second_context["run_id"]],
        "candidate_receipt_file_sha256": [
            first["candidate_file_sha256"],
            second["candidate_file_sha256"],
        ],
        "stable_projection_sha256": hashlib.sha256(
            _canonical(stable_projection)
        ).hexdigest(),
        "publication_invariant": (
            "two downloaded artifact byte sets agree after removing only capture time "
            "and run-specific digest fields"
        ),
        "excluded_refs": [],
        "ref_mutations_performed": [],
        "deletion_authority": "NOT_GRANTED",
        "public_mutation_performed": False,
    }
    receipt["receipt_sha256"] = hashlib.sha256(_canonical(receipt)).hexdigest()
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first-artifact", type=Path, required=True)
    parser.add_argument("--second-artifact", type=Path, required=True)
    parser.add_argument("--expected-first-run-id", required=True)
    parser.add_argument("--expected-second-run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = compare_artifacts(
            args.first_artifact,
            args.second_artifact,
            expected_first_run_id=args.expected_first_run_id,
            expected_second_run_id=args.expected_second_run_id,
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
        print(f"REMOTE_BRANCH_TWO_RUN_CERTIFICATION FAIL: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
