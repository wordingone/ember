#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Build and verify issue #35's zero-credit terminal disposition packet."""
from __future__ import annotations

import copy
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


SCHEMA = "ember-issue35-terminal-dispositions-v1"
REPOSITORY = "wordingone/ember"
SOURCE_CROSSWALK = Path(
    "manifests/authority/issue-35-authority-supersession-crosswalk-v1.json"
)
PACKET_PATH = Path(
    "manifests/authority/issue-35-terminal-dispositions-v1.json"
)
SOURCE_VERIFIER = Path("src/ember/governance/scripts/verify_authority_supersession_crosswalk.py")
HISTORICAL_TERMINAL = "HISTORICAL_ORPHANED"
GAP_DISPOSITION = "HISTORICAL_CUSTODY_GAP_CONSERVED"
REOPEN_RULE = "REOPEN_ON_AUTHENTIC_SOURCE_RECOVERY"

TOP_FIELDS = {
    "schema_version", "repository", "issue", "source_crosswalk",
    "denominators", "operator_disposition", "rows", "packet_sha256",
}
SOURCE_FIELDS = {"path", "sha256", "row_count", "custody_gap_count"}
DENOMINATOR_FIELDS = {
    "issue35_mandates", "issue35_defects", "issue35_unwatched",
    "issue35_doc_divergences", "issue265_transfer", "legacy_milestones",
    "legacy_conditions", "total_rows", "custody_gap_rows",
}
OPERATOR_FIELDS = {"authority_kind", "decision", "completion_credit"}
ROW_FIELDS = {
    "source_registry", "source_id", "source_kind",
    "original_statement_sha256", "original_evidence_sha256", "disposition",
    "target", "completion_credit", "reopen_rule",
    "no_new_parallel_authority",
}


class TerminalConservationError(ValueError):
    pass


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _packet_hash(packet: dict[str, Any]) -> str:
    body = copy.deepcopy(packet)
    body.pop("packet_sha256", None)
    return _canonical_hash(body)


def _closed(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise TerminalConservationError(f"{label} must have exact closed fields")
    return value


def _load_source_verifier(root: Path):
    path = root / SOURCE_VERIFIER
    spec = importlib.util.spec_from_file_location("issue35_source_verifier", path)
    if spec is None or spec.loader is None:
        raise TerminalConservationError("source crosswalk verifier is unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source(root: Path) -> tuple[dict[str, Any], dict[str, Any], str]:
    path = root / SOURCE_CROSSWALK
    payload = json.loads(path.read_text(encoding="utf-8"))
    # Bind the crosswalk's canonical, verifier-recomputed identity rather than
    # checkout bytes, whose line endings may differ across Git worktrees.
    source_hash = payload["crosswalk_sha256"]
    result = _load_source_verifier(root).validate_crosswalk(root, payload)
    if result != {
        "status": "PASS_WITH_CUSTODY_GAPS",
        "row_count": 251,
        "custody_gap_count": 126,
        "disposition_counts": {
            "CUSTODY_GAP": 126,
            "HISTORICAL_ORPHANED": 1,
            "SUPERSEDED": 124,
        },
        "crosswalk_sha256": payload["crosswalk_sha256"],
        "source_commit": payload["source_commit"],
    }:
        raise TerminalConservationError("source crosswalk is not the canonical 251/126 packet")
    return payload, result, source_hash


def _denominators(payload: dict[str, Any]) -> dict[str, int]:
    sizes = {
        registry["registry_id"]: len(registry["expected_source_ids"])
        for registry in payload["source_registries"]
    }
    return {
        "issue35_mandates": sizes["ISSUE35-MANDATES"],
        "issue35_defects": sizes["ISSUE35-DEFECTS"],
        "issue35_unwatched": sizes["ISSUE35-UNWATCHED"],
        "issue35_doc_divergences": sizes["ISSUE35-DOC-DIVERGENCES"],
        "issue265_transfer": sizes["ISSUE265-TRANSFER"],
        "legacy_milestones": sizes["LEGACY-MILESTONES"],
        "legacy_conditions": sizes["LEGACY-CONDITIONS"],
        "total_rows": len(payload["rows"]),
        "custody_gap_rows": sum(
            row["disposition"] == "CUSTODY_GAP" for row in payload["rows"]
        ),
    }


def build_packet(root: Path) -> dict[str, Any]:
    payload, _result, source_hash = _source(root)
    rows = []
    for source in payload["rows"]:
        if source["disposition"] != "CUSTODY_GAP":
            continue
        rows.append({
            "source_registry": source["source_registry"],
            "source_id": source["source_id"],
            "source_kind": source["source_kind"],
            "original_statement_sha256": _canonical_hash(source["statement"]),
            "original_evidence_sha256": _canonical_hash(source["evidence"]),
            "disposition": GAP_DISPOSITION,
            "target": HISTORICAL_TERMINAL,
            "completion_credit": False,
            "reopen_rule": REOPEN_RULE,
            "no_new_parallel_authority": True,
        })
    packet: dict[str, Any] = {
        "schema_version": SCHEMA,
        "repository": REPOSITORY,
        "issue": 35,
        "source_crosswalk": {
            "path": SOURCE_CROSSWALK.as_posix(),
            "sha256": source_hash,
            "row_count": 251,
            "custody_gap_count": 126,
        },
        "denominators": _denominators(payload),
        "operator_disposition": {
            "authority_kind": "OPERATOR_DIRECTIVE",
            "decision": (
                "Conserve every irrecoverable historical slot at the closed historical "
                "terminal with zero completion credit; never reconstruct missing wording."
            ),
            "completion_credit": False,
        },
        "rows": rows,
    }
    packet["packet_sha256"] = _packet_hash(packet)
    return packet


def validate_packet(root: Path, packet: dict[str, Any]) -> dict[str, Any]:
    body = _closed(packet, TOP_FIELDS, "packet")
    if body["schema_version"] != SCHEMA or body["repository"] != REPOSITORY:
        raise TerminalConservationError("packet identity mismatch")
    if body["issue"] != 35 or body["packet_sha256"] != _packet_hash(body):
        raise TerminalConservationError("packet issue or self-hash mismatch")
    payload, _result, source_hash = _source(root)
    source = _closed(body["source_crosswalk"], SOURCE_FIELDS, "source_crosswalk")
    if source != {
        "path": SOURCE_CROSSWALK.as_posix(), "sha256": source_hash,
        "row_count": 251, "custody_gap_count": 126,
    }:
        raise TerminalConservationError("source crosswalk binding mismatch")
    denominators = _closed(body["denominators"], DENOMINATOR_FIELDS, "denominators")
    expected_denominators = _denominators(payload)
    if denominators != expected_denominators or expected_denominators != {
        "issue35_mandates": 102, "issue35_defects": 13,
        "issue35_unwatched": 26, "issue35_doc_divergences": 7,
        "issue265_transfer": 7, "legacy_milestones": 55,
        "legacy_conditions": 41, "total_rows": 251, "custody_gap_rows": 126,
    }:
        raise TerminalConservationError("historical denominator mismatch")
    operator = _closed(body["operator_disposition"], OPERATOR_FIELDS, "operator")
    if operator != build_packet(root)["operator_disposition"]:
        raise TerminalConservationError("operator disposition mismatch")

    source_gaps = {
        (row["source_registry"], row["source_id"]): row
        for row in payload["rows"] if row["disposition"] == "CUSTODY_GAP"
    }
    rows = body["rows"]
    if not isinstance(rows, list) or len(rows) != 126:
        raise TerminalConservationError("terminal disposition count must be 126")
    seen: set[tuple[str, str]] = set()
    for index, raw in enumerate(rows):
        row = _closed(raw, ROW_FIELDS, f"row[{index}]")
        key = (row["source_registry"], row["source_id"])
        if key in seen or key not in source_gaps:
            raise TerminalConservationError("duplicate or foreign disposition row")
        seen.add(key)
        original = source_gaps[key]
        if row != {
            "source_registry": original["source_registry"],
            "source_id": original["source_id"],
            "source_kind": original["source_kind"],
            "original_statement_sha256": _canonical_hash(original["statement"]),
            "original_evidence_sha256": _canonical_hash(original["evidence"]),
            "disposition": GAP_DISPOSITION,
            "target": HISTORICAL_TERMINAL,
            "completion_credit": False,
            "reopen_rule": REOPEN_RULE,
            "no_new_parallel_authority": True,
        }:
            raise TerminalConservationError("row disposition is not exact")
    if seen != set(source_gaps):
        raise TerminalConservationError("source custody gaps are not set-equal")

    c_manifest = [
        row for row in payload["rows"]
        if row["source_registry"] == "LEGACY-CONDITIONS"
        and row["source_id"] == "C-MANIFEST"
    ]
    if len(c_manifest) != 1 or c_manifest[0]["disposition"] != "SUPERSEDED":
        raise TerminalConservationError("legacy C-MANIFEST denominator is not transferred")
    if any(row["completion_credit"] is not False for row in payload["rows"]):
        raise TerminalConservationError("source crosswalk grants forbidden completion credit")
    return {
        "status": "PASS_FOR_TERMINAL_ZERO_CREDIT",
        "source_row_count": 251,
        "recoverable_or_transferred_rows": 125,
        "operator_disposition_rows": 126,
        "completion_credit": False,
        "no_new_parallel_authority": True,
        "packet_sha256": body["packet_sha256"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--packet", type=Path)
    parser.add_argument("--write", type=Path)
    args = parser.parse_args()
    packet = (
        json.loads(args.packet.read_text(encoding="utf-8"))
        if args.packet else build_packet(args.repo)
    )
    result = validate_packet(args.repo, packet)
    if args.write:
        args.write.parent.mkdir(parents=True, exist_ok=True)
        args.write.write_text(
            json.dumps(packet, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
