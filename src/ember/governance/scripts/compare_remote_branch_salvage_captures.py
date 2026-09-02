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
# issue2015 exact-local-import:src/ember/governance/scripts/remote_branch_salvage.py
import importlib.util as _ember_ea37ccce90bbd51b_importlib
import sys as _ember_ea37ccce90bbd51b_sys
from pathlib import Path as _ember_ea37ccce90bbd51b_Path
_ember_ea37ccce90bbd51b_path = _ember_ea37ccce90bbd51b_Path(__file__).resolve().parents[4].joinpath('scripts', 'remote_branch_salvage.py')
if not _ember_ea37ccce90bbd51b_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/remote_branch_salvage.py')
_ember_ea37ccce90bbd51b_aliases = ('_ember_issue2015_ea37ccce90bbd51b', 'remote_branch_salvage', 'src.ember.governance.scripts.remote_branch_salvage')
_ember_ea37ccce90bbd51b_existing = []
for _ember_ea37ccce90bbd51b_alias in _ember_ea37ccce90bbd51b_aliases:
    _ember_ea37ccce90bbd51b_candidate = _ember_ea37ccce90bbd51b_sys.modules.get(_ember_ea37ccce90bbd51b_alias)
    if _ember_ea37ccce90bbd51b_candidate is not None and all(_ember_ea37ccce90bbd51b_candidate is not item for item in _ember_ea37ccce90bbd51b_existing):
        _ember_ea37ccce90bbd51b_existing.append(_ember_ea37ccce90bbd51b_candidate)
if len(_ember_ea37ccce90bbd51b_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/remote_branch_salvage.py')
if _ember_ea37ccce90bbd51b_existing:
    _ember_ea37ccce90bbd51b_module = _ember_ea37ccce90bbd51b_existing[0]
    _ember_ea37ccce90bbd51b_observed = getattr(_ember_ea37ccce90bbd51b_module, '__file__', None)
    if _ember_ea37ccce90bbd51b_observed is None or _ember_ea37ccce90bbd51b_Path(_ember_ea37ccce90bbd51b_observed).resolve() != _ember_ea37ccce90bbd51b_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/remote_branch_salvage.py')
else:
    _ember_ea37ccce90bbd51b_spec = _ember_ea37ccce90bbd51b_importlib.spec_from_file_location('_ember_issue2015_ea37ccce90bbd51b', _ember_ea37ccce90bbd51b_path)
    if _ember_ea37ccce90bbd51b_spec is None or _ember_ea37ccce90bbd51b_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/remote_branch_salvage.py')
    _ember_ea37ccce90bbd51b_module = _ember_ea37ccce90bbd51b_importlib.module_from_spec(_ember_ea37ccce90bbd51b_spec)
    for _ember_ea37ccce90bbd51b_alias in _ember_ea37ccce90bbd51b_aliases:
        _ember_ea37ccce90bbd51b_prior = _ember_ea37ccce90bbd51b_sys.modules.get(_ember_ea37ccce90bbd51b_alias)
        if _ember_ea37ccce90bbd51b_prior is not None and _ember_ea37ccce90bbd51b_prior is not _ember_ea37ccce90bbd51b_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/remote_branch_salvage.py')
        _ember_ea37ccce90bbd51b_sys.modules[_ember_ea37ccce90bbd51b_alias] = _ember_ea37ccce90bbd51b_module
    try:
        _ember_ea37ccce90bbd51b_spec.loader.exec_module(_ember_ea37ccce90bbd51b_module)
    except BaseException:
        for _ember_ea37ccce90bbd51b_alias in _ember_ea37ccce90bbd51b_aliases:
            if _ember_ea37ccce90bbd51b_sys.modules.get(_ember_ea37ccce90bbd51b_alias) is _ember_ea37ccce90bbd51b_module:
                _ember_ea37ccce90bbd51b_sys.modules.pop(_ember_ea37ccce90bbd51b_alias, None)
        raise
for _ember_ea37ccce90bbd51b_alias in _ember_ea37ccce90bbd51b_aliases:
    _ember_ea37ccce90bbd51b_prior = _ember_ea37ccce90bbd51b_sys.modules.get(_ember_ea37ccce90bbd51b_alias)
    if _ember_ea37ccce90bbd51b_prior is not None and _ember_ea37ccce90bbd51b_prior is not _ember_ea37ccce90bbd51b_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/remote_branch_salvage.py')
    _ember_ea37ccce90bbd51b_sys.modules[_ember_ea37ccce90bbd51b_alias] = _ember_ea37ccce90bbd51b_module
PacketError = getattr(_ember_ea37ccce90bbd51b_module, 'PacketError')
_canonical = getattr(_ember_ea37ccce90bbd51b_module, '_canonical')
# issue2015 exact-local-import-end:src/ember/governance/scripts/remote_branch_salvage.py


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
