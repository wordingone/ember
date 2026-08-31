#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Capture and verify Ember's local non-ancestor branch/worktree inventory."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


SCHEMA = "ember-branch-inventory-v1"
BEGIN = "<!-- EMBER_BRANCH_INVENTORY_BEGIN -->"
END = "<!-- EMBER_BRANCH_INVENTORY_END -->"
SHA1 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
DISPOSITIONS = {"LAND", "RETIRE", "PARK"}
DEFAULT_REASON = "Non-ancestor content has not been independently accepted into public master."
DEFAULT_REVISIT = "Review exact files against current master; land only through a provenance-quoted PR or prove supersession."
SELECTION = "every refs/heads tip and detached registered worktree tip not ancestor of master_sha"
MAX_INTRODUCTION_COMMITS = 3
CLAIM_LIMITS = [
    "PARK is the fail-closed default; LAND requires an explicit per-file override.",
    "This inventory grants no branch deletion, merge, issue closure, model, training, or capability authority.",
]
TICKET = "EMBER-BRANCH-INVENTORY"
SHA_CONVENTION = "lowercase hexadecimal SHA-256; receipt_sha256 hashes canonical UTF-8 JSON excluding its own field; identity and path hashes cover their UTF-8 bytes"
INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
TOP_FIELDS = {
    "schema_version", "goal_id", "workstream_id", "next_executed_outcome",
    "repository", "master_sha", "captured_at", "ticket", "ts", "sha_convention", "invariant_sha256", "selection",
    "candidate_count", "path_dictionary", "file_sets", "rows", "ignored_artifacts",
    "mutation_performed", "claim_limits", "receipt_sha256",
}
ROW_FIELDS = {
    "identity_kind", "identity_sha256", "head_sha", "comparison", "unlanded_file_count", "disposition",
    "worktree_path_sha256s", "file_set_sha256", "default_file_disposition",
    "default_file_reason", "default_file_revisit_condition", "file_overrides",
}
INPUT_OVERRIDE_FIELDS = {"disposition", "reason", "revisit_condition"}
OVERRIDE_FIELDS = {"path_sha256", "disposition", "reason", "revisit_condition"}
ARTIFACT_FIELDS = {"path_label", "sha256"}


class InventoryError(ValueError):
    """The branch inventory is incomplete, stale, or malformed."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_sha(value: Any, pattern: re.Pattern[str], field: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise InventoryError(f"{field} must be a lowercase content hash")
    return value


def _safe_identity(value: Any) -> str:
    if not isinstance(value, str) or not value or any(ch in value for ch in ("\r", "\n", "\0")):
        raise InventoryError("inventory identity is invalid")
    return value


def _safe_repo_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value or any(ch in value for ch in ("\r", "\n", "\0")):
        raise InventoryError("inventory file path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise InventoryError("inventory file path must be repository-relative")
    return value


def parse_worktree_porcelain(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for line in [*text.splitlines(), ""]:
        if not line:
            if current:
                path = current.get("path")
                head = current.get("head_sha")
                if not isinstance(path, str) or not SHA1.fullmatch(str(head)):
                    raise InventoryError("malformed git worktree porcelain")
                current.setdefault("branch", None)
                current.setdefault("detached", current["branch"] is None)
                rows.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            current["path"] = value
        elif key == "HEAD":
            current["head_sha"] = value
        elif key == "branch":
            current["branch"] = value
            current["detached"] = False
        elif key == "detached":
            current["detached"] = True
    return rows


def _run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", os.fspath(repo), *args],
        text=True,
        encoding="utf-8",
        errors="strict",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode:
        raise InventoryError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def _local_branches(repo: Path) -> list[tuple[str, str]]:
    result = _run_git(repo, "for-each-ref", "--format=%(refname)%09%(objectname)", "refs/heads")
    rows: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        identity, separator, head = line.partition("\t")
        if not separator or not identity.startswith("refs/heads/") or not SHA1.fullmatch(head):
            raise InventoryError("malformed local branch row")
        rows.append((identity, head))
    return sorted(rows)


def _unique_files(repo: Path, master: str, head: str) -> tuple[list[str], str]:
    triple = _run_git(repo, "diff", "--name-only", "--no-renames", f"{master}...{head}", check=False)
    if triple.returncode == 0:
        files = sorted({_safe_repo_path(line) for line in triple.stdout.splitlines() if line})
        comparison = "tree_equivalent" if not files else "diverged"
        return files, comparison
    merge_base = _run_git(repo, "merge-base", master, head, check=False)
    if merge_base.returncode != 1 and "no merge base" not in (triple.stderr + merge_base.stderr).lower():
        raise InventoryError(f"failed to compare {head} to {master}: {triple.stderr.strip()}")
    tree = _run_git(repo, "ls-tree", "-r", "--name-only", head)
    return sorted({_safe_repo_path(line) for line in tree.stdout.splitlines() if line}), "no_common_ancestor"


def collect_candidates(repo: Path, master: str) -> list[dict[str, Any]]:
    master_sha = _run_git(repo, "rev-parse", "--verify", f"{master}^{{commit}}").stdout.strip()
    _require_sha(master_sha, SHA1, "master_sha")
    worktrees = parse_worktree_porcelain(_run_git(repo, "worktree", "list", "--porcelain").stdout)
    branch_paths: dict[str, list[str]] = {}
    for row in worktrees:
        if row["branch"]:
            branch_paths.setdefault(row["branch"], []).append(sha256_bytes(row["path"].encode("utf-8")))

    by_head: dict[str, tuple[list[str], str]] = {}
    candidates: list[dict[str, Any]] = []
    for identity, head in _local_branches(repo):
        if _run_git(repo, "merge-base", "--is-ancestor", head, master_sha, check=False).returncode == 0:
            continue
        if head not in by_head:
            by_head[head] = _unique_files(repo, master_sha, head)
        files, comparison = by_head[head]
        candidates.append(
            {
                "identity": identity,
                "head_sha": head,
                "unique_files": files,
                "comparison": comparison,
                "worktree_path_sha256s": sorted(branch_paths.get(identity, [])),
            }
        )

    detached_seen: set[tuple[str, str]] = set()
    for row in worktrees:
        head = row["head_sha"]
        if not row["detached"]:
            continue
        if _run_git(repo, "merge-base", "--is-ancestor", head, master_sha, check=False).returncode == 0:
            continue
        path_hash = sha256_bytes(row["path"].encode("utf-8"))
        key = (head, path_hash)
        if key in detached_seen:
            continue
        detached_seen.add(key)
        if head not in by_head:
            by_head[head] = _unique_files(repo, master_sha, head)
        files, comparison = by_head[head]
        candidates.append(
            {
                "identity": f"detached-worktree:{path_hash}",
                "head_sha": head,
                "unique_files": files,
                "comparison": comparison,
                "worktree_path_sha256s": [path_hash],
            }
        )
    return sorted(candidates, key=lambda row: row["identity"])


def classify_candidates(
    candidates: Sequence[Mapping[str, Any]],
    *,
    overrides: Mapping[str, Any],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    known_identities = {_safe_identity(row.get("identity")) for row in candidates}
    unknown = set(overrides) - known_identities
    if unknown:
        raise InventoryError(f"override identities are absent from census: {sorted(unknown)}")
    for candidate in candidates:
        identity = _safe_identity(candidate.get("identity"))
        head = _require_sha(candidate.get("head_sha"), SHA1, f"{identity}.head_sha")
        comparison = candidate.get("comparison")
        if comparison not in {"diverged", "tree_equivalent", "no_common_ancestor"}:
            raise InventoryError(f"{identity}.comparison is invalid")
        unique_files = sorted({_safe_repo_path(path) for path in candidate.get("unique_files", [])})
        identity_overrides = overrides.get(identity, {})
        if not isinstance(identity_overrides, Mapping):
            raise InventoryError(f"{identity} override must be an object")
        if set(identity_overrides) - set(unique_files):
            raise InventoryError(f"{identity} override names a non-census file")
        files: list[dict[str, str]] = []
        for path in unique_files:
            override = identity_overrides.get(path)
            if override is None:
                disposition, reason, revisit = "PARK", DEFAULT_REASON, DEFAULT_REVISIT
            else:
                if not isinstance(override, Mapping):
                    raise InventoryError(f"{identity}:{path} override must be an object")
                if set(override) != INPUT_OVERRIDE_FIELDS:
                    raise InventoryError(f"{identity}:{path} override fields are not closed")
                disposition = override.get("disposition")
                reason = override.get("reason")
                revisit = override.get("revisit_condition")
                if disposition not in DISPOSITIONS or not isinstance(reason, str) or not reason.strip() or not isinstance(revisit, str) or not revisit.strip():
                    raise InventoryError(f"{identity}:{path} override is incomplete")
            files.append(
                {
                    "path": path,
                    "disposition": disposition,
                    "reason": reason,
                    "revisit_condition": revisit,
                }
            )
        if not files:
            disposition = "RETIRE"
            reason = "The non-ancestor tip has no unique files under the required master...tip comparison."
            revisit = "Recreate only if commit-history custody is independently required."
        else:
            dispositions = {row["disposition"] for row in files}
            disposition = next(iter(dispositions)) if len(dispositions) == 1 else "PARK"
            reason = "File-level dispositions are recorded in the content-addressed inventory."
            revisit = DEFAULT_REVISIT
        path_hashes = candidate.get("worktree_path_sha256s", [])
        if not isinstance(path_hashes, list):
            raise InventoryError(f"{identity}.worktree_path_sha256s must be a list")
        path_hashes = sorted({_require_sha(value, SHA256, f"{identity}.worktree_path_sha256") for value in path_hashes})
        result.append(
            {
                "identity": identity,
                "head_sha": head,
                "comparison": comparison,
                "unlanded_file_count": len(files),
                "disposition": disposition,
                "reason": reason,
                "revisit_condition": revisit,
                "worktree_path_sha256s": path_hashes,
                "files": files,
            }
        )
    return sorted(result, key=lambda row: row["identity"])


def hash_ignored_artifacts(specs: Sequence[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for spec in specs:
        label, separator, raw_path = spec.partition("=")
        if not separator or not label.strip() or any(ch in label for ch in "\r\n"):
            raise InventoryError("artifact must use LABEL=PATH")
        path = Path(raw_path)
        if not path.is_file():
            raise InventoryError(f"ignored artifact is not a file: {label}")
        rows.append({"path_label": label, "sha256": sha256_bytes(path.read_bytes())})
    return sorted(rows, key=lambda row: row["path_label"])


def _validate_classified_row(row: Mapping[str, Any]) -> None:
    identity = _safe_identity(row.get("identity"))
    _require_sha(row.get("head_sha"), SHA1, f"{identity}.head_sha")
    if row.get("comparison") not in {"diverged", "tree_equivalent", "no_common_ancestor"}:
        raise InventoryError(f"{identity}.comparison is invalid")
    if row.get("disposition") not in DISPOSITIONS:
        raise InventoryError(f"{identity}.disposition is invalid")
    files = row.get("files")
    if not isinstance(files, list) or row.get("unlanded_file_count") != len(files):
        raise InventoryError(f"{identity}.unlanded_file_count is invalid")
    if [item.get("path") for item in files] != sorted(item.get("path") for item in files):
        raise InventoryError(f"{identity}.files are not sorted")
    for item in files:
        _safe_repo_path(item.get("path"))
        if item.get("disposition") not in DISPOSITIONS:
            raise InventoryError(f"{identity} file disposition is invalid")
        if not isinstance(item.get("reason"), str) or not item["reason"].strip():
            raise InventoryError(f"{identity} file reason is missing")
        if not isinstance(item.get("revisit_condition"), str) or not item["revisit_condition"].strip():
            raise InventoryError(f"{identity} file revisit condition is missing")


def build_receipt(
    *,
    repository: str,
    master_sha: str,
    captured_at: str,
    rows: Sequence[Mapping[str, Any]],
    ignored_artifacts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if repository != "wordingone/ember":
        raise InventoryError("repository must be wordingone/ember")
    _require_sha(master_sha, SHA1, "master_sha")
    try:
        timestamp = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise InventoryError("captured_at must be ISO-8601") from exc
    if timestamp.tzinfo is None:
        raise InventoryError("captured_at must include timezone")
    normalized = [dict(row) for row in rows]
    if [row.get("identity") for row in normalized] != sorted(row.get("identity") for row in normalized):
        raise InventoryError("inventory rows must be identity-sorted")
    if len({row.get("identity") for row in normalized}) != len(normalized):
        raise InventoryError("inventory identities must be unique")
    file_set_paths: dict[str, list[str]] = {}
    compact_rows: list[dict[str, Any]] = []
    for row in normalized:
        _validate_classified_row(row)
        file_paths = [item["path"] for item in row["files"]]
        file_identities = sorted(sha256_bytes(path.encode("utf-8")) for path in file_paths)
        file_set_sha256 = sha256_bytes(canonical_json(file_identities))
        file_set_paths.setdefault(file_set_sha256, file_identities)
        dispositions = {item["disposition"] for item in row["files"]}
        if not row["files"]:
            default_disposition = "RETIRE"
            default_reason = row["reason"]
            default_revisit = row["revisit_condition"]
        elif len(dispositions) == 1:
            default_disposition = next(iter(dispositions))
            first = row["files"][0]
            default_reason = first["reason"]
            default_revisit = first["revisit_condition"]
        else:
            default_disposition = "PARK"
            default_reason = DEFAULT_REASON
            default_revisit = DEFAULT_REVISIT
        overrides = [
            {
                "path_sha256": sha256_bytes(item["path"].encode("utf-8")),
                "disposition": item["disposition"],
                "reason": item["reason"],
                "revisit_condition": item["revisit_condition"],
            }
            for item in row["files"]
            if item["disposition"] != default_disposition
            or item["reason"] != default_reason
            or item["revisit_condition"] != default_revisit
        ]
        identity = row["identity"]
        identity_kind = "branch" if identity.startswith("refs/heads/") else "detached-worktree"
        compact_rows.append(
            {
                key: value
                for key, value in row.items()
                if key not in {"identity", "files", "reason", "revisit_condition"}
            }
            | {
                "identity_kind": identity_kind,
                "identity_sha256": sha256_bytes(identity.encode("utf-8")),
                "file_set_sha256": file_set_sha256,
                "default_file_disposition": default_disposition,
                "default_file_reason": default_reason,
                "default_file_revisit_condition": default_revisit,
                "file_overrides": overrides,
            }
        )
    compact_rows.sort(key=lambda row: (row["identity_kind"], row["identity_sha256"]))
    path_dictionary = sorted({path for paths in file_set_paths.values() for path in paths})
    path_index = {path: index for index, path in enumerate(path_dictionary)}
    file_sets = {
        digest: [path_index[path] for path in paths]
        for digest, paths in sorted(file_set_paths.items())
    }
    artifacts = [dict(row) for row in ignored_artifacts]
    for artifact in artifacts:
        if not isinstance(artifact.get("path_label"), str) or not artifact["path_label"].strip():
            raise InventoryError("ignored artifact label is missing")
        _require_sha(artifact.get("sha256"), SHA256, "ignored artifact sha256")
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA,
        "goal_id": "EMBER-02",
        "workstream_id": "EMBER-02A",
        "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
        "repository": repository,
        "master_sha": master_sha,
        "captured_at": captured_at,
        "ticket": TICKET,
        "ts": captured_at,
        "sha_convention": SHA_CONVENTION,
        "invariant_sha256": INVARIANT_SHA256,
        "selection": SELECTION,
        "candidate_count": len(compact_rows),
        "path_dictionary": path_dictionary,
        "file_sets": file_sets,
        "rows": compact_rows,
        "ignored_artifacts": artifacts,
        "mutation_performed": False,
        "claim_limits": CLAIM_LIMITS,
    }
    receipt["receipt_sha256"] = sha256_bytes(canonical_json(receipt))
    return receipt


def _closed_fields(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise InventoryError(f"{label} fields are not closed")


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise InventoryError("captured_at must be ISO-8601")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InventoryError("captured_at must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise InventoryError("captured_at must include timezone")
    return parsed


def verify_receipt(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise InventoryError("inventory must be an object")
    _closed_fields(payload, TOP_FIELDS, "inventory")
    canonical = dict(payload)
    recorded = canonical.pop("receipt_sha256", None)
    _require_sha(recorded, SHA256, "receipt_sha256")
    if sha256_bytes(canonical_json(canonical)) != recorded:
        raise InventoryError("receipt_sha256 does not match canonical inventory")
    if (
        payload.get("schema_version") != SCHEMA
        or payload.get("goal_id") != "EMBER-02"
        or payload.get("workstream_id") != "EMBER-02A"
        or payload.get("next_executed_outcome")
        != "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
        or payload.get("repository") != "wordingone/ember"
        or payload.get("ticket") != TICKET
        or payload.get("ts") != payload.get("captured_at")
        or payload.get("sha_convention") != SHA_CONVENTION
        or payload.get("invariant_sha256") != INVARIANT_SHA256
    ):
        raise InventoryError("inventory identity is invalid")
    _require_sha(payload.get("master_sha"), SHA1, "master_sha")
    _parse_timestamp(payload.get("captured_at"))
    if payload.get("selection") != SELECTION or payload.get("claim_limits") != CLAIM_LIMITS:
        raise InventoryError("inventory scope or claim limits are invalid")
    rows = payload.get("rows")
    if not isinstance(rows, list) or payload.get("candidate_count") != len(rows):
        raise InventoryError("candidate_count does not match rows")
    row_identities = [(row.get("identity_kind"), row.get("identity_sha256")) for row in rows]
    if row_identities != sorted(row_identities):
        raise InventoryError("inventory rows are not sorted")
    if len(set(row_identities)) != len(rows):
        raise InventoryError("inventory identities are duplicated")
    path_dictionary = payload.get("path_dictionary")
    if (
        not isinstance(path_dictionary, list)
        or path_dictionary != sorted(set(path_dictionary))
    ):
        raise InventoryError("path_dictionary must be a sorted unique list")
    for path_sha256 in path_dictionary:
        _require_sha(path_sha256, SHA256, "path_dictionary entry")
    file_sets = payload.get("file_sets")
    if not isinstance(file_sets, Mapping):
        raise InventoryError("file_sets must be an object")
    reconstructed_file_sets: dict[str, list[str]] = {}
    for digest, indexes in file_sets.items():
        _require_sha(digest, SHA256, "file_set_sha256")
        if (
            not isinstance(indexes, list)
            or any(isinstance(index, bool) or not isinstance(index, int) for index in indexes)
            or indexes != sorted(set(indexes))
            or any(index < 0 or index >= len(path_dictionary) for index in indexes)
        ):
            raise InventoryError(f"{digest}.file_set indexes are invalid")
        paths = [path_dictionary[index] for index in indexes]
        if paths != sorted(paths):
            raise InventoryError(f"{digest}.file_set paths are not sorted")
        if sha256_bytes(canonical_json(paths)) != digest:
            raise InventoryError(f"{digest}.file_set content hash mismatch")
        reconstructed_file_sets[digest] = paths
    referenced_file_sets: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise InventoryError("inventory row must be an object")
        _closed_fields(row, ROW_FIELDS, "inventory row")
        identity_kind = row.get("identity_kind")
        if identity_kind not in {"branch", "detached-worktree"}:
            raise InventoryError("inventory identity kind is invalid")
        identity = _require_sha(row.get("identity_sha256"), SHA256, "identity_sha256")
        _require_sha(row.get("head_sha"), SHA1, f"{identity}.head_sha")
        if row.get("comparison") not in {"diverged", "tree_equivalent", "no_common_ancestor"}:
            raise InventoryError(f"{identity}.comparison is invalid")
        digest = _require_sha(row.get("file_set_sha256"), SHA256, f"{identity}.file_set_sha256")
        referenced_file_sets.add(digest)
        if digest not in file_sets:
            raise InventoryError(f"{identity}.file_set is missing")
        paths = reconstructed_file_sets[digest]
        if row.get("unlanded_file_count") != len(paths):
            raise InventoryError(f"{identity}.unlanded_file_count is invalid")
        if row.get("disposition") not in DISPOSITIONS or row.get("default_file_disposition") not in DISPOSITIONS:
            raise InventoryError(f"{identity}.disposition is invalid")
        path_hashes = row.get("worktree_path_sha256s")
        if not isinstance(path_hashes, list) or path_hashes != sorted(set(path_hashes)):
            raise InventoryError(f"{identity}.worktree_path_sha256s is invalid")
        for path_hash in path_hashes:
            _require_sha(path_hash, SHA256, f"{identity}.worktree_path_sha256")
        for field in ("default_file_reason", "default_file_revisit_condition"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise InventoryError(f"{identity}.{field} is missing")
        overrides = row.get("file_overrides")
        if not isinstance(overrides, list):
            raise InventoryError(f"{identity}.file_overrides must be a list")
        allowed = set(paths)
        seen: set[str] = set()
        override_dispositions: dict[str, str] = {}
        for item in overrides:
            if not isinstance(item, Mapping):
                raise InventoryError(f"{identity}.file_override must be an object")
            _closed_fields(item, OVERRIDE_FIELDS, f"{identity}.file_override")
            path = _require_sha(item.get("path_sha256"), SHA256, f"{identity}.path_sha256")
            if path not in allowed or path in seen:
                raise InventoryError(f"{identity}.file_overrides is invalid")
            seen.add(path)
            if item.get("disposition") not in DISPOSITIONS:
                raise InventoryError(f"{identity} override disposition is invalid")
            for field in ("reason", "revisit_condition"):
                if not isinstance(item.get(field), str) or not item[field].strip():
                    raise InventoryError(f"{identity} override {field} is missing")
            override_dispositions[path] = item["disposition"]
        applied = {override_dispositions.get(path, row["default_file_disposition"]) for path in paths}
        expected_disposition = "RETIRE" if not paths else (next(iter(applied)) if len(applied) == 1 else "PARK")
        if row.get("disposition") != expected_disposition:
            raise InventoryError(f"{identity}.disposition does not match file dispositions")
    if set(file_sets) != referenced_file_sets:
        raise InventoryError("file_sets contains unreferenced entries")
    artifacts = payload.get("ignored_artifacts")
    if not isinstance(artifacts, list):
        raise InventoryError("ignored_artifacts must be a list")
    labels: list[str] = []
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            raise InventoryError("ignored artifact must be an object")
        _closed_fields(artifact, ARTIFACT_FIELDS, "ignored artifact")
        label = artifact.get("path_label")
        if not isinstance(label, str) or not label.strip() or any(ch in label for ch in "\r\n"):
            raise InventoryError("ignored artifact label is invalid")
        labels.append(label)
        _require_sha(artifact.get("sha256"), SHA256, "ignored artifact sha256")
    if labels != sorted(set(labels)):
        raise InventoryError("ignored artifacts must be label-sorted and unique")
    if payload.get("mutation_performed") is not False:
        raise InventoryError("inventory must be read-only")
    return dict(payload)

def render_continuity_block(payload: Mapping[str, Any], manifest_path: str) -> str:
    receipt = verify_receipt(payload)
    _safe_repo_path(manifest_path)
    lines = [
        BEGIN,
        "<!-- GENERATED by src/ember/governance/scripts/branch_inventory.py; do not edit by hand. -->",
        "## Standing branch inventory",
        "",
        f"Manifest: `{manifest_path}`; receipt SHA-256: `{receipt['receipt_sha256']}`; "
        f"master: `{receipt['master_sha']}`; captured: `{receipt['captured_at']}`.",
        "",
        "| Branch/worktree identity | Tip | Unlanded files | Disposition |",
        "|---|---:|---:|---|",
    ]
    for row in receipt["rows"]:
        identity = f"{row['identity_kind']}:{row['identity_sha256']}"
        lines.append(
            f"| `{identity}` | `{row['head_sha']}` | {row['unlanded_file_count']} | `{row['disposition']}` |"
        )
    lines.extend(["", END])
    return "\n".join(lines)


def replace_continuity_block(text: str, block: str) -> str:
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)
    matches = pattern.findall(text)
    if len(matches) > 1:
        raise InventoryError("docs/authority/CONTINUITY.md contains duplicate branch inventory blocks")
    if matches:
        return pattern.sub(lambda _: block, text, count=1)
    suffix = "" if text.endswith("\n") else "\n"
    return f"{text}{suffix}\n{block}\n"


def check_inventory(
    *,
    manifest_path: Path,
    continuity_path: Path,
    repo_path: Path | None = None,
    master_ref: str = "refs/remotes/origin/master",
    now: datetime | None = None,
    max_age_days: int = 7,
) -> dict[str, Any]:
    if isinstance(max_age_days, bool) or not isinstance(max_age_days, int) or max_age_days < 1:
        raise InventoryError("max_age_days must be a positive integer")
    try:
        manifest_bytes = manifest_path.read_bytes()
        if manifest_path.suffix == ".gz":
            manifest_bytes = gzip.decompress(manifest_bytes)
        payload = json.loads(manifest_bytes.decode("utf-8", errors="strict"))
        continuity = continuity_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InventoryError(f"inventory inputs are unreadable: {exc}") from exc
    receipt = verify_receipt(payload)
    if repo_path is not None:
        live_master = _run_git(repo_path, "rev-parse", "--verify", f"{master_ref}^{{commit}}").stdout.strip()
        if live_master != receipt["master_sha"]:
            merge_base = _run_git(repo_path, "merge-base", receipt["master_sha"], live_master).stdout.strip()
            if merge_base != receipt["master_sha"]:
                raise InventoryError("branch inventory master binding is stale")
            distance_text = _run_git(
                repo_path, "rev-list", "--count", f"{receipt['master_sha']}..{live_master}"
            ).stdout.strip()
            try:
                distance = int(distance_text)
            except ValueError as exc:
                raise InventoryError("branch inventory master distance is invalid") from exc
            if distance < 1 or distance > MAX_INTRODUCTION_COMMITS:
                raise InventoryError("branch inventory master binding is stale")
    captured = _parse_timestamp(receipt["captured_at"])
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise InventoryError("current time must include timezone")
    age_seconds = (current - captured).total_seconds()
    if age_seconds < -300:
        raise InventoryError("branch inventory capture time is in the future")
    if age_seconds > max_age_days * 86400:
        raise InventoryError("branch inventory is stale")
    try:
        continuity_parent = continuity_path.resolve().parent
        if (
            continuity_parent.name == "authority"
            and continuity_parent.parent.name == "docs"
        ):
            repository_root = continuity_parent.parent.parent
        else:
            repository_root = continuity_parent
        relative = manifest_path.resolve().relative_to(repository_root).as_posix()
    except ValueError as exc:
        raise InventoryError("manifest must be inside the repository containing docs/authority/CONTINUITY.md") from exc
    expected = render_continuity_block(receipt, relative)
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)
    matches = pattern.findall(continuity)
    if matches != [expected]:
        raise InventoryError("docs/authority/CONTINUITY.md branch inventory block is missing or stale")
    return receipt


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_json(value) + b"\n"
    if path.suffix == ".gz":
        path.write_bytes(gzip.compress(data, compresslevel=9, mtime=0))
    else:
        path.write_bytes(data)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture = subparsers.add_parser("capture")
    capture.add_argument("--repo", type=Path, required=True)
    capture.add_argument("--master", default="refs/remotes/origin/master")
    capture.add_argument("--output", type=Path, required=True)
    capture.add_argument("--continuity", type=Path, required=True)
    capture.add_argument("--overrides", type=Path)
    capture.add_argument("--artifact", action="append", default=[])
    capture.add_argument("--captured-at")
    check = subparsers.add_parser("check")
    check.add_argument("--repo", type=Path, required=True)
    check.add_argument("--master", default="refs/remotes/origin/master")
    check.add_argument("--manifest", type=Path, required=True)
    check.add_argument("--continuity", type=Path, required=True)
    check.add_argument("--max-age-days", type=int, default=7)
    args = parser.parse_args(argv)
    try:
        if args.command == "capture":
            overrides: Mapping[str, Any] = {}
            if args.overrides:
                overrides = json.loads(args.overrides.read_text(encoding="utf-8"))
                if not isinstance(overrides, Mapping):
                    raise InventoryError("overrides must be an object")
            master_sha = _run_git(args.repo, "rev-parse", "--verify", f"{args.master}^{{commit}}").stdout.strip()
            candidates = collect_candidates(args.repo, master_sha)
            rows = classify_candidates(candidates, overrides=overrides)
            captured_at = args.captured_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            receipt = build_receipt(
                repository="wordingone/ember",
                master_sha=master_sha,
                captured_at=captured_at,
                rows=rows,
                ignored_artifacts=hash_ignored_artifacts(args.artifact),
            )
            _write_json(args.output, receipt)
            continuity = args.continuity.read_text(encoding="utf-8")
            relative = args.output.resolve().relative_to(args.continuity.resolve().parent).as_posix()
            args.continuity.write_text(
                replace_continuity_block(continuity, render_continuity_block(receipt, relative)),
                encoding="utf-8",
                newline="\n",
            )
            print(json.dumps({"status": "CAPTURED", "candidate_count": len(rows), "receipt_sha256": receipt["receipt_sha256"]}, sort_keys=True))
        else:
            receipt = check_inventory(
                manifest_path=args.manifest,
                continuity_path=args.continuity,
                repo_path=args.repo,
                master_ref=args.master,
                max_age_days=args.max_age_days,
            )
            print(json.dumps({"status": "PASS", "candidate_count": receipt["candidate_count"], "receipt_sha256": receipt["receipt_sha256"]}, sort_keys=True))
    except (InventoryError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"InventoryError: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
