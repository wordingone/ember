#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Build and verify a non-authorizing remote-branch salvage packet."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


class PacketError(RuntimeError):
    """An evidence or schema violation that must fail closed."""


_SHA1 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REF = re.compile(r"^refs/heads/(?!/)(?!.*(?:\.\.|\\|\s|//|@\{|[~^:?*\[]))[^/]+(?:/[^/]+)*$")
_AUTHORITY = {
    "goal_id": "EMBER-02",
    "workstream_id": "EMBER-02A",
    "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
}
_CAPTURE_KEYS = {
    "authority",
    "schema_version",
    "repository",
    "master_sha",
    "captured_at",
    "pagination",
    "source_evidence",
    "branches",
    "selection_sha256",
}
_BRANCH_KEYS = {
    "name",
    "ref",
    "head_sha",
    "protected",
    "open_head_prs",
    "all_prs",
    "reachability",
    "patch_blob_equivalence",
    "exact_head_tags",
    "releases",
    "deployments",
    "public_consumers",
    "custody_references",
    "reconstruction",
    "ref_stability",
    "errors",
}
_DISPOSITIONS = {"MERGED", "SUPERSEDED_CITED", "NEGATIVE_KEEP", "DISCARD_EVIDENCED"}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _object(value: Any, *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PacketError(f"{field} must be an object")
    return value


def _list(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise PacketError(f"{field} must be a list")
    return value


def _sha1(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or _SHA1.fullmatch(value) is None:
        raise PacketError(f"{field} must be a lowercase 40-character SHA-1")
    return value


def _sha256(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise PacketError(f"{field} must be a lowercase 64-character SHA-256")
    return value


def _strict_keys(value: Mapping[str, Any], expected: set[str], *, field: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise PacketError(f"{field} has invalid keys; missing={missing}, extra={extra}")


def _citation_group(value: Any, *, field: str) -> Mapping[str, Any]:
    group = _object(value, field=field)
    _strict_keys(group, {"complete", "citations"}, field=field)
    if not isinstance(group["complete"], bool):
        raise PacketError(f"{field}.complete must be boolean")
    citations = _list(group["citations"], field=f"{field}.citations")
    if any(not isinstance(item, str) or not item for item in citations):
        raise PacketError(f"{field}.citations must contain nonempty strings")
    if len(citations) != len(set(citations)):
        raise PacketError(f"{field}.citations contains duplicates")
    return group


def _validate_prs(value: Any, *, field: str, head_sha: str, open_only: bool) -> list[Mapping[str, Any]]:
    rows = _list(value, field=field)
    numbers: set[int] = set()
    result: list[Mapping[str, Any]] = []
    for index, raw in enumerate(rows):
        pr = _object(raw, field=f"{field}[{index}]")
        number = pr.get("number")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1 or number in numbers:
            raise PacketError(f"{field}[{index}].number is invalid or duplicate")
        numbers.add(number)
        pr_head = _sha1(pr.get("head_sha"), field=f"{field}[{index}].head_sha")
        if open_only and pr_head != head_sha:
            raise PacketError(f"{field}[{index}] is not bound to the branch head")
        if open_only and set(pr) != {"number", "head_sha"}:
            raise PacketError(f"{field}[{index}] has an invalid open-PR shape")
        if not open_only:
            expected = {"number", "state", "head_sha", "merged", "merge_sha", "base_sha"}
            _strict_keys(pr, expected, field=f"{field}[{index}]")
            if pr["state"] not in {"open", "closed"} or not isinstance(pr["merged"], bool):
                raise PacketError(f"{field}[{index}] has invalid state")
            if pr["merged"]:
                _sha1(pr["merge_sha"], field=f"{field}[{index}].merge_sha")
            elif pr["merge_sha"] is not None:
                raise PacketError(f"{field}[{index}].merge_sha must be null when unmerged")
            _sha1(pr["base_sha"], field=f"{field}[{index}].base_sha")
        result.append(pr)
    return result


def _validate_branch(raw: Any, *, index: int) -> dict[str, Any]:
    branch = dict(_object(raw, field=f"branches[{index}]"))
    _strict_keys(branch, _BRANCH_KEYS, field=f"branches[{index}]")
    name = branch["name"]
    if not isinstance(name, str) or not name or branch["ref"] != f"refs/heads/{name}" or _REF.fullmatch(branch["ref"]) is None:
        raise PacketError(f"branches[{index}] has an invalid ref")
    head = _sha1(branch["head_sha"], field=f"branches[{index}].head_sha")
    if branch["protected"] not in {True, False, None}:
        raise PacketError(f"branches[{index}].protected is invalid")
    _validate_prs(branch["open_head_prs"], field=f"branches[{index}].open_head_prs", head_sha=head, open_only=True)
    _validate_prs(branch["all_prs"], field=f"branches[{index}].all_prs", head_sha=head, open_only=False)

    reach = _object(branch["reachability"], field=f"branches[{index}].reachability")
    _strict_keys(reach, {"status", "ahead_by", "behind_by", "merge_base"}, field=f"branches[{index}].reachability")
    if reach["status"] not in {"IDENTICAL", "BEHIND", "AHEAD", "DIVERGED", "NO_COMMON_ANCESTOR", "ERROR"}:
        raise PacketError(f"branches[{index}].reachability.status is invalid")
    for key in ("ahead_by", "behind_by"):
        if isinstance(reach[key], bool) or not isinstance(reach[key], int) or reach[key] < 0:
            raise PacketError(f"branches[{index}].reachability.{key} is invalid")
    if reach["merge_base"] is not None:
        _sha1(reach["merge_base"], field=f"branches[{index}].reachability.merge_base")

    status = reach["status"]
    ahead = reach["ahead_by"]
    behind = reach["behind_by"]
    merge_base = reach["merge_base"]
    consistent = {
        "IDENTICAL": ahead == 0 and behind == 0 and merge_base == head,
        "BEHIND": ahead == 0 and behind > 0 and merge_base == head,
        "AHEAD": ahead > 0 and behind == 0 and merge_base is not None,
        "DIVERGED": ahead > 0 and behind > 0 and merge_base is not None,
        "NO_COMMON_ANCESTOR": ahead == 0 and behind == 0 and merge_base is None,
        "ERROR": ahead == 0 and behind == 0 and merge_base is None,
    }
    if not consistent[status]:
        raise PacketError(
            f"branches[{index}].reachability is internally inconsistent for {status}"
        )

    eq = _object(branch["patch_blob_equivalence"], field=f"branches[{index}].patch_blob_equivalence")
    _strict_keys(eq, {"status", "canonical_survivor", "path_count", "path_digest_sha256", "patch_digest_sha256"}, field=f"branches[{index}].patch_blob_equivalence")
    if eq["status"] not in {"PROVEN", "NOT_PROVEN", "NOT_APPLICABLE", "ERROR"}:
        raise PacketError(f"branches[{index}].patch_blob_equivalence.status is invalid")
    if eq["canonical_survivor"] is not None:
        _sha1(eq["canonical_survivor"], field=f"branches[{index}].patch_blob_equivalence.canonical_survivor")
    if isinstance(eq["path_count"], bool) or not isinstance(eq["path_count"], int) or eq["path_count"] < 0:
        raise PacketError(f"branches[{index}].patch_blob_equivalence.path_count is invalid")
    _sha256(eq["path_digest_sha256"], field=f"branches[{index}].patch_blob_equivalence.path_digest_sha256")
    _sha256(eq["patch_digest_sha256"], field=f"branches[{index}].patch_blob_equivalence.patch_digest_sha256")

    for key in ("exact_head_tags", "releases", "deployments", "errors"):
        values = _list(branch[key], field=f"branches[{index}].{key}")
        if any(not isinstance(item, str) or not item for item in values) or len(values) != len(set(values)):
            raise PacketError(f"branches[{index}].{key} must contain unique nonempty strings")
    _citation_group(branch["public_consumers"], field=f"branches[{index}].public_consumers")
    _citation_group(branch["custody_references"], field=f"branches[{index}].custody_references")

    reconstruction = _object(branch["reconstruction"], field=f"branches[{index}].reconstruction")
    _strict_keys(reconstruction, {"command", "expected_sha"}, field=f"branches[{index}].reconstruction")
    if not isinstance(reconstruction["command"], str) or not reconstruction["command"]:
        raise PacketError(f"branches[{index}].reconstruction.command is invalid")
    if _sha1(reconstruction["expected_sha"], field=f"branches[{index}].reconstruction.expected_sha") != head:
        raise PacketError(f"branches[{index}].reconstruction does not bind head")

    stability = _object(branch["ref_stability"], field=f"branches[{index}].ref_stability")
    _strict_keys(stability, {"captured_sha", "preexecution_sha"}, field=f"branches[{index}].ref_stability")
    _sha1(stability["captured_sha"], field=f"branches[{index}].ref_stability.captured_sha")
    _sha1(stability["preexecution_sha"], field=f"branches[{index}].ref_stability.preexecution_sha")
    return branch


def _selection(rows: Sequence[Mapping[str, Any]]) -> str:
    return _digest([[row["ref"], row["head_sha"]] for row in sorted(rows, key=lambda item: str(item["ref"]))])


def _disposition(branch: Mapping[str, Any]) -> tuple[str, bool, str]:
    name = str(branch["name"])
    head = str(branch["head_sha"])
    stability = branch["ref_stability"]
    public = branch["public_consumers"]
    custody = branch["custody_references"]
    reach = branch["reachability"]
    eq = branch["patch_blob_equivalence"]
    gates: list[tuple[bool, str]] = [
        (name == "master", "master is never a deletion candidate"),
        (bool(branch["errors"]), "capture or verifier error remains"),
        (branch["protected"] is not False, "branch protection is true or unknown"),
        (stability["captured_sha"] != head or stability["preexecution_sha"] != head, "ref drift between capture and pre-execution replay"),
        (bool(branch["open_head_prs"]), "an open head PR still consumes the ref"),
        (any(pr["state"] == "open" for pr in branch["all_prs"]), "an open PR still uses the branch name"),
        (bool(branch["exact_head_tags"]), "an exact-head tag still consumes the ref"),
        (bool(branch["releases"]), "a release still consumes the ref"),
        (bool(branch["deployments"]), "a deployment still consumes the ref"),
        (not public["complete"], "public-consumer evidence is incomplete"),
        (bool(public["citations"]), "a public consumer still cites the ref or head"),
        (not custody["complete"], "custody-reference evidence is incomplete"),
        (bool(custody["citations"]), "a custody reference still cites the ref or head"),
        (reach["status"] in {"AHEAD", "DIVERGED", "NO_COMMON_ANCESTOR", "ERROR"} and eq["status"] != "PROVEN", "unique content or patch/blob equivalence remains unproven"),
        (eq["status"] not in {"PROVEN", "NOT_APPLICABLE"}, "canonical-survivor equivalence remains unproven"),
        (eq["canonical_survivor"] is None, "canonical survivor is missing"),
        (True, "independent raw-source and patch/blob replay evidence is not attached to this non-authorizing packet"),
    ]
    for failed, reason in gates:
        if failed:
            return "NEGATIVE_KEEP", False, reason
    return "DISCARD_EVIDENCED", True, "none; all deletion-proposal evidence gates are satisfied"


def build_packet(capture: Mapping[str, Any]) -> dict[str, Any]:
    source = _object(capture, field="capture")
    _strict_keys(source, _CAPTURE_KEYS, field="capture")
    authority = _object(source["authority"], field="capture.authority")
    _strict_keys(authority, set(_AUTHORITY), field="capture.authority")
    if dict(authority) != _AUTHORITY:
        raise PacketError("capture authority binding is invalid")
    if source["schema_version"] != "ember-remote-branch-capture-v1" or source["repository"] != "wordingone/ember":
        raise PacketError("capture identity is invalid")
    master = _sha1(source["master_sha"], field="capture.master_sha")
    pagination = _object(source["pagination"], field="capture.pagination")
    _strict_keys(pagination, {"complete", "page_size", "link_headers_exhausted"}, field="capture.pagination")
    if pagination["complete"] is not True or pagination["link_headers_exhausted"] is not True or pagination["page_size"] != 100:
        raise PacketError("branch pagination is incomplete")
    source_evidence = _object(source["source_evidence"], field="capture.source_evidence")
    expected_sources = {"branches_pre", "branches_post", "pulls", "tags", "releases", "deployments", "public_master"}
    _strict_keys(source_evidence, expected_sources, field="capture.source_evidence")
    for key, digest in source_evidence.items():
        _sha256(digest, field=f"capture.source_evidence.{key}")
    raw_rows = _list(source["branches"], field="capture.branches")
    rows = [_validate_branch(raw, index=index) for index, raw in enumerate(raw_rows)]
    if not rows:
        raise PacketError("capture contains no branches")
    refs = [row["ref"] for row in rows]
    if len(refs) != len(set(refs)):
        raise PacketError("capture contains duplicate refs")
    selection = _selection(rows)
    if _sha256(source["selection_sha256"], field="capture.selection_sha256") != selection:
        raise PacketError("capture selection digest mismatch")
    if not any(row["name"] == "master" and row["head_sha"] == master for row in rows):
        raise PacketError("capture does not bind master branch to master SHA")

    packet_rows: list[dict[str, Any]] = []
    for evidence in sorted(rows, key=lambda item: str(item["ref"])):
        disposition, proposed, falsifier = _disposition(evidence)
        row = copy.deepcopy(evidence)
        row["disposition"] = disposition
        row["deletion_proposed"] = proposed
        row["falsifier"] = falsifier
        row["evidence_sha256"] = _digest({"master_sha": master, "evidence": evidence})
        packet_rows.append(row)

    packet: dict[str, Any] = {
        "authority": dict(authority),
        "schema_version": "ember-remote-branch-salvage-v1",
        "repository": source["repository"],
        "master_sha": master,
        "captured_at": source["captured_at"],
        "branch_count": len(packet_rows),
        "selection_sha256": selection,
        "source_evidence": dict(source_evidence),
        "rows": packet_rows,
        "safe_to_delete_refs": [row["ref"] for row in packet_rows if row["deletion_proposed"]],
        "deletion_authority": "NOT_GRANTED",
        "public_mutation_performed": False,
        "claim_limits": ["No remote ref deletion, issue closure, model, training, checkpoint, benchmark, or capability claim follows."],
    }
    packet["packet_sha256"] = _digest(packet)
    validate_packet(packet)
    return packet


def validate_packet(packet: Mapping[str, Any]) -> None:
    value = _object(packet, field="packet")
    expected = {"authority", "schema_version", "repository", "master_sha", "captured_at", "branch_count", "selection_sha256", "source_evidence", "rows", "safe_to_delete_refs", "deletion_authority", "public_mutation_performed", "claim_limits", "packet_sha256"}
    _strict_keys(value, expected, field="packet")
    authority = _object(value["authority"], field="packet.authority")
    _strict_keys(authority, set(_AUTHORITY), field="packet.authority")
    if dict(authority) != _AUTHORITY:
        raise PacketError("packet authority binding is invalid")
    if value["schema_version"] != "ember-remote-branch-salvage-v1" or value["repository"] != "wordingone/ember":
        raise PacketError("packet identity is invalid")
    master = _sha1(value["master_sha"], field="packet.master_sha")
    if value["deletion_authority"] != "NOT_GRANTED" or value["public_mutation_performed"] is not False:
        raise PacketError("packet cannot grant deletion authority or claim mutation")
    source_evidence = _object(value["source_evidence"], field="packet.source_evidence")
    expected_sources = {"branches_pre", "branches_post", "pulls", "tags", "releases", "deployments", "public_master"}
    _strict_keys(source_evidence, expected_sources, field="packet.source_evidence")
    for key, digest in source_evidence.items():
        _sha256(digest, field=f"packet.source_evidence.{key}")
    rows = _list(value["rows"], field="packet.rows")
    if value["branch_count"] != len(rows):
        raise PacketError("packet branch_count mismatch")
    refs: list[str] = []
    proposals: list[str] = []
    for index, raw in enumerate(rows):
        row = dict(_object(raw, field=f"packet.rows[{index}]"))
        _strict_keys(row, _BRANCH_KEYS | {"disposition", "deletion_proposed", "falsifier", "evidence_sha256"}, field=f"packet.rows[{index}]")
        evidence = {key: row[key] for key in _BRANCH_KEYS if key in row}
        if len(evidence) != len(_BRANCH_KEYS):
            raise PacketError(f"packet.rows[{index}] is missing evidence fields")
        _validate_branch(evidence, index=index)
        if row.get("disposition") not in _DISPOSITIONS or not isinstance(row.get("deletion_proposed"), bool) or not isinstance(row.get("falsifier"), str):
            raise PacketError(f"packet.rows[{index}] has invalid disposition fields")
        expected_disposition, expected_proposed, expected_falsifier = _disposition(evidence)
        if (row["disposition"], row["deletion_proposed"], row["falsifier"]) != (expected_disposition, expected_proposed, expected_falsifier):
            raise PacketError(f"packet.rows[{index}] disposition does not reproduce")
        if _sha256(row.get("evidence_sha256"), field=f"packet.rows[{index}].evidence_sha256") != _digest({"master_sha": master, "evidence": evidence}):
            raise PacketError(f"packet.rows[{index}] evidence digest mismatch")
        refs.append(row["ref"])
        if row["deletion_proposed"]:
            proposals.append(row["ref"])
    if refs != sorted(refs) or len(refs) != len(set(refs)):
        raise PacketError("packet rows must be uniquely ref-sorted")
    if _sha256(value["selection_sha256"], field="packet.selection_sha256") != _selection(rows):
        raise PacketError("packet selection digest mismatch")
    if value["safe_to_delete_refs"] != proposals:
        raise PacketError("packet safe-to-delete projection mismatch")
    supplied = _sha256(value["packet_sha256"], field="packet.packet_sha256")
    body = dict(value)
    body.pop("packet_sha256")
    if supplied != _digest(body):
        raise PacketError("packet digest mismatch")


def _decode_ref_hex(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"(?:[0-9a-f]{2})+", value) is None:
        raise PacketError(f"{field} must be nonempty lowercase UTF-8 hex")
    try:
        ref = bytes.fromhex(value).decode("utf-8", errors="strict")
    except (ValueError, UnicodeError) as exc:
        raise PacketError(f"{field} is not canonical UTF-8 hex") from exc
    if _REF.fullmatch(ref) is None:
        raise PacketError(f"{field} does not decode to a safe branch ref")
    if ref.encode("utf-8").hex() != value:
        raise PacketError(f"{field} is not canonical lowercase UTF-8 hex")
    return ref


def build_public_summary(packet: Mapping[str, Any]) -> dict[str, Any]:
    validate_packet(packet)
    rows = [
        {
            "ref_utf8_hex": str(row["ref"]).encode("utf-8").hex(),
            "head_sha": row["head_sha"],
            "evidence_sha256": row["evidence_sha256"],
            "disposition": row["disposition"],
            "deletion_proposed": row["deletion_proposed"],
        }
        for row in packet["rows"]
    ]
    counts = {disposition: 0 for disposition in sorted(_DISPOSITIONS)}
    for row in rows:
        counts[row["disposition"]] += 1
    summary: dict[str, Any] = {
        "authority": dict(packet["authority"]),
        "schema_version": "ember-remote-branch-salvage-public-summary-v1",
        "repository": packet["repository"],
        "master_sha": packet["master_sha"],
        "captured_at": packet["captured_at"],
        "branch_count": packet["branch_count"],
        "selection_sha256": packet["selection_sha256"],
        "source_evidence": dict(packet["source_evidence"]),
        "disposition_counts": counts,
        "rows": rows,
        "proposal_refs_utf8_hex": [row["ref_utf8_hex"] for row in rows if row["deletion_proposed"]],
        "private_packet_sha256": packet["packet_sha256"],
        "deletion_authority": "NOT_GRANTED",
        "public_mutation_performed": False,
        "claim_limits": list(packet["claim_limits"]),
    }
    summary["summary_sha256"] = _digest(summary)
    validate_public_summary(summary)
    return summary


def validate_public_summary(summary: Mapping[str, Any]) -> None:
    value = _object(summary, field="public_summary")
    expected = {"authority", "schema_version", "repository", "master_sha", "captured_at", "branch_count", "selection_sha256", "source_evidence", "disposition_counts", "rows", "proposal_refs_utf8_hex", "private_packet_sha256", "deletion_authority", "public_mutation_performed", "claim_limits", "summary_sha256"}
    _strict_keys(value, expected, field="public_summary")
    authority = _object(value["authority"], field="public_summary.authority")
    _strict_keys(authority, set(_AUTHORITY), field="public_summary.authority")
    if dict(authority) != _AUTHORITY:
        raise PacketError("public summary authority binding is invalid")
    if value["schema_version"] != "ember-remote-branch-salvage-public-summary-v1" or value["repository"] != "wordingone/ember":
        raise PacketError("public summary identity is invalid")
    _sha1(value["master_sha"], field="public_summary.master_sha")
    _sha256(value["selection_sha256"], field="public_summary.selection_sha256")
    _sha256(value["private_packet_sha256"], field="public_summary.private_packet_sha256")
    if value["deletion_authority"] != "NOT_GRANTED" or value["public_mutation_performed"] is not False:
        raise PacketError("public summary cannot grant deletion authority or claim mutation")
    source_evidence = _object(value["source_evidence"], field="public_summary.source_evidence")
    expected_sources = {"branches_pre", "branches_post", "pulls", "tags", "releases", "deployments", "public_master"}
    _strict_keys(source_evidence, expected_sources, field="public_summary.source_evidence")
    for key, digest in source_evidence.items():
        _sha256(digest, field=f"public_summary.source_evidence.{key}")
    counts = _object(value["disposition_counts"], field="public_summary.disposition_counts")
    _strict_keys(counts, _DISPOSITIONS, field="public_summary.disposition_counts")
    if any(not isinstance(counts[key], int) or isinstance(counts[key], bool) or counts[key] < 0 for key in _DISPOSITIONS):
        raise PacketError("public summary disposition counts must be nonnegative integers")
    rows = _list(value["rows"], field="public_summary.rows")
    if value["branch_count"] != len(rows) or sum(counts.values()) != len(rows):
        raise PacketError("public summary branch or disposition count mismatch")
    refs: list[str] = []
    proposals: list[str] = []
    reproduced_counts = {disposition: 0 for disposition in _DISPOSITIONS}
    for index, raw in enumerate(rows):
        row = _object(raw, field=f"public_summary.rows[{index}]")
        _strict_keys(row, {"ref_utf8_hex", "head_sha", "evidence_sha256", "disposition", "deletion_proposed"}, field=f"public_summary.rows[{index}]")
        ref = _decode_ref_hex(row["ref_utf8_hex"], field=f"public_summary.rows[{index}].ref_utf8_hex")
        _sha1(row["head_sha"], field=f"public_summary.rows[{index}].head_sha")
        _sha256(row["evidence_sha256"], field=f"public_summary.rows[{index}].evidence_sha256")
        if row["disposition"] not in _DISPOSITIONS or not isinstance(row["deletion_proposed"], bool):
            raise PacketError(f"public_summary.rows[{index}] has invalid disposition")
        if row["deletion_proposed"] != (row["disposition"] == "DISCARD_EVIDENCED"):
            raise PacketError(f"public_summary.rows[{index}] proposal does not match disposition")
        refs.append(ref)
        reproduced_counts[row["disposition"]] += 1
        if row["deletion_proposed"]:
            proposals.append(row["ref_utf8_hex"])
    if refs != sorted(refs) or len(refs) != len(set(refs)):
        raise PacketError("public summary rows must be uniquely ref-sorted")
    if dict(counts) != reproduced_counts or value["proposal_refs_utf8_hex"] != proposals:
        raise PacketError("public summary projections do not reproduce")
    supplied = _sha256(value["summary_sha256"], field="public_summary.summary_sha256")
    body = dict(value)
    body.pop("summary_sha256")
    if supplied != _digest(body):
        raise PacketError("public summary digest mismatch")


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PacketError(f"cannot read JSON {path.name}: {exc}") from exc


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("capture", type=Path)
    build.add_argument("output", type=Path)
    verify = sub.add_parser("verify")
    verify.add_argument("packet", type=Path)
    summarize = sub.add_parser("summarize")
    summarize.add_argument("packet", type=Path)
    summarize.add_argument("output", type=Path)
    verify_summary = sub.add_parser("verify-summary")
    verify_summary.add_argument("summary", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            packet = build_packet(_read(args.capture))
            args.output.write_bytes(_canonical(packet) + b"\n")
            print(json.dumps({"status": "PASS_NO_AUTHORITY", "branches": packet["branch_count"], "proposals": len(packet["safe_to_delete_refs"]), "packet_sha256": packet["packet_sha256"]}, sort_keys=True))
        elif args.command == "verify":
            packet = _read(args.packet)
            validate_packet(packet)
            print(json.dumps({"status": "PASS_NO_AUTHORITY", "branches": packet["branch_count"], "proposals": len(packet["safe_to_delete_refs"]), "packet_sha256": packet["packet_sha256"]}, sort_keys=True))
        elif args.command == "summarize":
            summary = build_public_summary(_read(args.packet))
            args.output.write_bytes(_canonical(summary) + b"\n")
            print(json.dumps({"status": "PASS_NO_AUTHORITY", "branches": summary["branch_count"], "proposals": len(summary["proposal_refs_utf8_hex"]), "summary_sha256": summary["summary_sha256"]}, sort_keys=True))
        else:
            summary = _read(args.summary)
            validate_public_summary(summary)
            print(json.dumps({"status": "PASS_NO_AUTHORITY", "branches": summary["branch_count"], "proposals": len(summary["proposal_refs_utf8_hex"]), "summary_sha256": summary["summary_sha256"]}, sort_keys=True))
    except PacketError as exc:
        print(f"REMOTE_BRANCH_SALVAGE FAIL: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
