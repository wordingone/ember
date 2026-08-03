# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Build a non-mutating public issue census bound to exact Git evidence."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


ISSUE_REF_RE = re.compile(r"(?<![A-Za-z0-9_])#([1-9][0-9]*)")
ISO_INSTANT_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
ALLOWED_DISPOSITIONS = (
    "current executable obligation",
    "preserved research direction",
    "implemented and independently verified",
    "superseded by an exact named successor",
    "exact duplicate of one canonical issue",
    "historical sub-3B or borrowed-lineage non-executable evidence",
    "expired operational incident",
    "unresolved",
)
HISTORICAL_MARKERS = (
    "2.2b", "2.2 b", "sub-3b", "sub 3b", "qwen", "borrowed",
)
RESEARCH_MARKERS = (
    "research", "hypothesis", "architecture", "mechanism", "world model",
    "memory", "optimizer", "kernel", "attention", "benchmark", "reasoning",
    "multimodal", "modality", "expert", "routing", "rope", "bitnet", "qat",
    "subq", "igrpo", "rlm",
)


def _git(root: Path, *arguments: str, allow_no_match: bool = False) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    accepted = {0, 1} if allow_no_match else {0}
    if result.returncode not in accepted:
        raise ValueError(
            "git command failed: "
            + " ".join(arguments)
            + ": "
            + (result.stderr.strip() or result.stdout.strip())
        )
    return result.stdout.replace("\r\n", "\n")


def _encode_text(value: Any) -> str:
    return base64.b64encode(str(value).encode("utf-8")).decode("ascii")


def _decode_text(value: Any) -> str:
    try:
        return base64.b64decode(str(value), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("invalid canonical base64 text") from exc


def _sha256_json(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _blob_map(root: Path, commit: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    output = _git(root, "ls-tree", "-r", commit)
    for line in output.splitlines():
        metadata, separator, path = line.partition("\t")
        if not separator:
            continue
        fields = metadata.split()
        if len(fields) >= 3 and fields[1] == "blob":
            rows[path.replace("\\", "/")] = fields[2]
    return rows


def _master_evidence(root: Path, commit: str) -> dict[int, list[dict[str, Any]]]:
    blobs = _blob_map(root, commit)
    matches: dict[int, set[tuple[str, int, str]]] = defaultdict(set)
    output = _git(
        root,
        "grep",
        "-n",
        "-I",
        "-E",
        r"#[0-9]+",
        commit,
        "--",
        ".",
        allow_no_match=True,
    )
    for line in output.splitlines():
        _, separator, remainder = line.partition(":")
        if not separator:
            continue
        path, separator, numbered_text = remainder.partition(":")
        if not separator:
            continue
        line_number, separator, text = numbered_text.partition(":")
        if not separator or not line_number.isdigit():
            continue
        normalized_path = path.replace("\\", "/")
        blob = blobs.get(normalized_path)
        if blob is None:
            continue
        for match in ISSUE_REF_RE.finditer(text):
            matches[int(match.group(1))].add(
                (normalized_path, int(line_number), blob)
            )
    return {
        number: [
            {"path": path, "line": line, "blob_sha1": blob}
            for path, line, blob in sorted(rows)
        ]
        for number, rows in matches.items()
    }


def _history_evidence(root: Path, commit: str) -> dict[int, list[dict[str, str]]]:
    matches: dict[int, set[str]] = defaultdict(set)
    output = _git(root, "log", commit, "--format=%H%x00%B%x00%x1e")
    for record in output.split("\x1e"):
        fields = record.strip().split("\x00", 2)
        if len(fields) < 2:
            continue
        commit_sha = fields[0].strip()
        message = fields[1]
        if not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
            continue
        for match in ISSUE_REF_RE.finditer(message):
            matches[int(match.group(1))].add(commit_sha)
    return {
        number: [{"commit": sha} for sha in sorted(commits)]
        for number, commits in matches.items()
    }


def _normalized_issue(issue: Mapping[str, Any]) -> dict[str, Any]:
    labels = issue.get("labels")
    label_names = sorted(
        row.get("name")
        for row in labels or []
        if isinstance(row, Mapping) and isinstance(row.get("name"), str)
    )
    author = issue.get("author")
    return {
        "number": int(issue["number"]),
        "title": str(issue.get("title", "")),
        "body_sha256": hashlib.sha256(
            str(issue.get("body", "")).encode("utf-8")
        ).hexdigest(),
        "url": str(issue.get("url", "")),
        "created_at": str(issue.get("createdAt", "")),
        "updated_at": str(issue.get("updatedAt", "")),
        "labels": label_names,
        "author": (
            str(author.get("login", "")) if isinstance(author, Mapping) else ""
        ),
    }


def _source_issue(issue: Mapping[str, Any]) -> dict[str, Any]:
    labels = issue.get("labels")
    author = issue.get("author")
    comments = issue.get("comments")
    return {
        "number": int(issue["number"]),
        "title": str(issue.get("title", "")),
        "body_base64": _encode_text(issue.get("body", "")),
        "url": str(issue.get("url", "")),
        "created_at": str(issue.get("createdAt", "")),
        "updated_at": str(issue.get("updatedAt", "")),
        "labels": sorted(
            row.get("name") for row in labels or []
            if isinstance(row, Mapping) and isinstance(row.get("name"), str)
        ),
        "author": str(author.get("login", "")) if isinstance(author, Mapping) else "",
        "state": str(issue.get("state", "")),
        "state_reason": str(issue.get("stateReason", "")),
        "closed_at": str(issue.get("closedAt", "")),
        "comments": sorted(
            (
                {
                    "url": str(comment.get("url", "")),
                    "body_base64": _encode_text(comment.get("body", "")),
                    "author": str((comment.get("author") or {}).get("login", "")),
                    "created_at": str(comment.get("createdAt", "")),
                    "updated_at": str(comment.get("updatedAt", "")),
                }
                for comment in comments or []
                if isinstance(comment, Mapping)
            ),
            key=lambda row: (row["created_at"], row["url"]),
        ),
    }


def canonical_open_issue_source_snapshot(
    issues: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return the one canonical source projection used by build and live audit."""
    return sorted(
        (_source_issue(issue) for issue in issues),
        key=lambda row: row["number"],
    )


def _normalized_source_issue(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "number": int(source["number"]),
        "title": str(source.get("title", "")),
        "body_sha256": hashlib.sha256(_decode_text(source.get("body_base64", "")).encode("utf-8")).hexdigest(),
        "url": str(source.get("url", "")),
        "created_at": str(source.get("created_at", "")),
        "updated_at": str(source.get("updated_at", "")),
        "labels": sorted(str(label) for label in source.get("labels", [])),
        "author": str(source.get("author", "")),
        "state": str(source.get("state", "")),
        "evidence_comments": [
            {
                "url": str(comment.get("url", "")),
                "body_sha256": hashlib.sha256(
                    _decode_text(comment.get("body_base64", "")).encode("utf-8")
                ).hexdigest(),
                "author": str(comment.get("author", "")),
                "created_at": str(comment.get("created_at", "")),
                "updated_at": str(comment.get("updated_at", "")),
            }
            for comment in source.get("comments", [])
            if isinstance(comment, Mapping)
        ],
    }


def _conservative_disposition(
    source: Mapping[str, Any],
    master_rows: list[dict[str, Any]],
    history_rows: list[dict[str, str]],
) -> tuple[str, str, str, str]:
    title = str(source.get("title", ""))
    lowered = title.casefold()
    if any(marker in lowered for marker in HISTORICAL_MARKERS):
        return (
            "historical sub-3B or borrowed-lineage non-executable evidence",
            "explicit_historical_or_borrowed_marker_in_issue_title",
            "medium",
            "historical_evidence_only_surviving_obligation_requires_mapping",
        )
    if not master_rows and not history_rows:
        return (
            "unresolved",
            "no_public_master_or_history_reference_found",
            "low",
            "no_public_master_or_history_binding_found",
        )
    if any(marker in lowered for marker in RESEARCH_MARKERS):
        return (
            "preserved research direction",
            "research_marker_plus_git_evidence",
            "medium",
            "research_direction_preserved_no_completion_claim",
        )
    return (
        "current executable obligation",
        "git_evidence_without_completion_proof",
        "medium",
        "requested_outcome_not_independently_verified",
    )




def _normalized_closed_source(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **_normalized_source_issue(source),
        "state": str(source.get("state", "")),
        "state_reason": str(source.get("state_reason", "")),
        "closed_at": str(source.get("closed_at", "")),
        "evidence_comments": [
            {
                "url": str(comment.get("url", "")),
                "body_sha256": hashlib.sha256(
                    _decode_text(comment.get("body_base64", "")).encode("utf-8")
                ).hexdigest(),
                "author": str(comment.get("author", "")),
                "created_at": str(comment.get("created_at", "")),
                "updated_at": str(comment.get("updated_at", "")),
            }
            for comment in source.get("comments", [])
            if isinstance(comment, Mapping)
        ],
    }
def build_issue_census(
    repository_root: Path,
    public_ref: str,
    issues: Iterable[Mapping[str, Any]],
    closed_issues: Iterable[Mapping[str, Any]] = (),
    completion_evidence: Iterable[Mapping[str, Any]] = (),
    captured_at: str | None = None,
) -> dict[str, Any]:
    root = repository_root.resolve()
    public_master_sha = _git(root, "rev-parse", public_ref).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", public_master_sha):
        raise ValueError("public ref did not resolve to one commit")
    source_snapshot = canonical_open_issue_source_snapshot(issues)
    normalized = [_normalized_source_issue(source) for source in source_snapshot]
    source_by_number = {row["number"]: row for row in source_snapshot}
    master = _master_evidence(root, public_master_sha)
    history = _history_evidence(root, public_master_sha)
    rows: list[dict[str, Any]] = []
    for source in normalized:
        number = source["number"]
        obligation = {
            "title": source["title"],
            "body_sha256": source["body_sha256"],
            "labels": source["labels"],
        }
        master_rows = master.get(number, [])
        history_rows = history.get(number, [])
        (
            disposition,
            classification_basis,
            confidence,
            unresolved_remainder,
        ) = _conservative_disposition(source, master_rows, history_rows)
        rows.append(
            {
                **source,
                "issue_record_sha256": _sha256_json(source),
                "obligation_sha256": _sha256_json(obligation),
                "surviving_obligation": source["title"],
                "public_master_sha": public_master_sha,
                "master_evidence": master_rows,
                "compound_obligations": [source["title"], f"body_sha256:{source['body_sha256']}"],
                "history_evidence": history_rows,
                "disposition": disposition,
                "classification_basis": classification_basis,
                "confidence": confidence,
                "unresolved_remainder": unresolved_remainder,
                "closure_proposed": False,
                "completion_proof": [],
                "canonical_issue": None,
                "canonical_obligation_sha256": None,
            }
        )
    evidence_rows = []
    for evidence in completion_evidence:
        sanitized = dict(evidence)
        excerpt = sanitized.pop("verification_evidence_excerpt", None)
        evidence_rows.append(sanitized)
    evidence_by_number: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for evidence in evidence_rows:
        evidence_by_number[int(evidence["number"])].append(evidence)
    for row in rows:
        audit_rows = evidence_by_number.get(row["number"], [])
        if not audit_rows:
            continue
        override = next((item for item in audit_rows if isinstance(item.get("disposition"), str)), None)
        if override is not None:
            disposition = str(override["disposition"])
            if disposition not in ALLOWED_DISPOSITIONS:
                raise ValueError(f"audit disposition invalid: {row['number']}")
            row.update({"disposition": disposition, "classification_basis": "audited_disposition_override", "confidence": "high", "canonical_issue": override.get("canonical_issue"), "canonical_issue_url": override.get("canonical_issue_url"), "canonical_obligation_sha256": override.get("canonical_obligation_sha256"), "preserved_issue_body_sha256": override.get("preserved_issue_body_sha256"), "completion_proof": []})
        else:
            row.update({"disposition": "implemented and independently verified", "classification_basis": "audited_completion_evidence", "confidence": "high", "unresolved_remainder": None, "completion_proof": audit_rows})
    closed_items = list(closed_issues)
    closed_snapshot = sorted((_source_issue(issue) for issue in closed_items), key=lambda row: row["number"])
    normalized_closed = [_normalized_closed_source(source) for source in closed_snapshot]
    raw_closed = {int(issue["number"]): issue for issue in closed_items}
    closed_outcomes = []
    for source in normalized_closed:
        raw = raw_closed[source["number"]]
        obligation = {"title": source["title"], "body_sha256": source["body_sha256"], "labels": source["labels"]}
        proof_rows = evidence_by_number.get(source["number"], [])
        limitation = next(
            (row for row in proof_rows if row.get("closed_disposition") == "unresolved"),
            None,
        )
        disposition = "unresolved" if limitation is not None else "implemented and independently verified"
        unresolved_remainder = limitation.get("unresolved_remainder") if limitation is not None else None
        closed_outcomes.append({**source, "issue_record_sha256": _sha256_json(source), "obligation_sha256": _sha256_json(obligation), "disposition": disposition, "closure_proposed": False, "completion_proof": proof_rows, "unresolved_remainder": unresolved_remainder})
    return {
        "authority": {
            "goal_id": "EMBER-01",
            "workstream_id": "EMBER-01B",
            "next_executed_outcome": (
                "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
            ),
        },
        "schema": "ember-01-public-issue-census-v1",
        "repository": "wordingone/ember",
        # The instant this snapshot was taken. Downstream certification binds to
        # it so the claim reads "issues as of <captured_at>" instead of implying
        # the live list still matches at end-of-run (#1331).
        "captured_at": captured_at,
        "public_master_sha": public_master_sha,
        "open_issue_count": len(rows),
        "issue_snapshot_sha256": _sha256_json(normalized),
        "snapshot_max_issue_updated_at": max(
            (row["updated_at"] for row in rows), default=None
        ),
        "allowed_dispositions": list(ALLOWED_DISPOSITIONS),
        "issue_source_snapshot": source_snapshot,
        "closed_issue_source_snapshot": closed_snapshot,
        "closed_issue_snapshot_sha256": _sha256_json(normalized_closed),
        "closed_outcome_count": len(closed_outcomes),
        "closed_outcomes": closed_outcomes,
        "immutable_custody_evidence": evidence_rows,
        "mutation_performed": False,
        "issues": rows,
    }


def _content_proof_errors(
    proof: Any, repository_root: Path | None, master_sha: Any, number: Any,
) -> list[str]:
    errors: list[str] = []
    if not isinstance(proof, list) or not proof:
        return [f"completion_proof_missing:{number}"]
    if repository_root is None:
        return [f"completion_repository_unresolved:{number}"]
    for item in proof:
        if not isinstance(item, Mapping):
            errors.append(f"completion_proof_invalid:{number}")
            continue
        if item.get("number") != number:
            errors.append(f"completion_proof_issue_mismatch:{number}")
        commit = str(item.get("commit", ""))
        implementation_commit = str(item.get("implementation_commit", ""))
        criterion = item.get("criterion")
        criterion_sha = str(item.get("criterion_sha256", ""))
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            errors.append(f"completion_commit_invalid:{number}")
            continue
        ancestry = subprocess.run(["git", "merge-base", "--is-ancestor", commit, str(master_sha)], cwd=repository_root, capture_output=True, check=False)
        if ancestry.returncode != 0:
            errors.append(f"completion_commit_not_ancestor:{number}")
        if not re.fullmatch(r"[0-9a-f]{40}", implementation_commit):
            errors.append(f"implementation_commit_invalid:{number}")
        else:
            implemented = subprocess.run(
                ["git", "merge-base", "--is-ancestor", implementation_commit, str(master_sha)],
                cwd=repository_root,
                capture_output=True,
                check=False,
            )
            if implemented.returncode != 0:
                errors.append(f"implementation_commit_not_ancestor:{number}")
            changed = subprocess.run(
                ["git", "diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "-m", implementation_commit],
                cwd=repository_root,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                check=False,
            )
            changed_paths = sorted(set(changed.stdout.splitlines())) if changed.returncode == 0 else []
            implementation_paths = item.get("implementation_paths")
            if not isinstance(implementation_paths, list) or not implementation_paths:
                errors.append(f"implementation_paths_missing:{number}")
            elif not all(isinstance(path, str) and path in changed_paths for path in implementation_paths):
                errors.append(f"implementation_paths_not_changed:{number}")
            expected_diff_hash = hashlib.sha256(
                ("\n".join(changed_paths) + "\n").encode("utf-8")
            ).hexdigest()
            if item.get("implementation_diff_sha256") != expected_diff_hash:
                errors.append(f"implementation_diff_hash_mismatch:{number}")
        if not isinstance(criterion, str) or hashlib.sha256(criterion.encode("utf-8")).hexdigest() != criterion_sha:
            errors.append(f"completion_criterion_hash_mismatch:{number}")
        for kind in ("artifact", "verifier"):
            path = item.get(f"{kind}_path")
            expected = str(item.get(f"{kind}_sha256", ""))
            if not isinstance(path, str) or not path or path.startswith("/") or ".." in Path(path).parts:
                errors.append(f"completion_{kind}_path_invalid:{number}")
                continue
            shown = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=repository_root, capture_output=True, check=False)
            if shown.returncode != 0:
                errors.append(f"completion_{kind}_path_unresolved:{number}")
            elif hashlib.sha256(shown.stdout).hexdigest() != expected:
                errors.append(f"completion_{kind}_hash_mismatch:{number}")
        absent_paths = item.get("absent_paths", [])
        if not isinstance(absent_paths, list):
            errors.append(f"completion_absent_paths_invalid:{number}")
        else:
            for absent in absent_paths:
                if (
                    not isinstance(absent, str)
                    or not absent
                    or Path(absent).is_absolute()
                    or ".." in Path(absent).parts
                ):
                    errors.append(f"completion_absent_path_invalid:{number}")
                    continue
                probe = subprocess.run(
                    ["git", "cat-file", "-e", f"{commit}:{Path(absent).as_posix()}"],
                    cwd=repository_root,
                    capture_output=True,
                    check=False,
                )
                if probe.returncode == 0:
                    errors.append(f"completion_absent_path_present:{number}")
    return errors

def validate_issue_census(
    payload: Mapping[str, Any], repository_root: Path | None = None
) -> list[str]:
    errors: list[str] = []
    rows = payload.get("issues")
    if not isinstance(rows, list):
        return ["issues_not_list"]
    numbers = [row.get("number") for row in rows if isinstance(row, Mapping)]
    for number in sorted(set(numbers), key=lambda value: str(value)):
        if numbers.count(number) > 1:
            errors.append(f"issue_number_duplicate:{number}")
    if payload.get("open_issue_count") != len(rows):
        errors.append("open_issue_count_mismatch")
    if payload.get("allowed_dispositions") != list(ALLOWED_DISPOSITIONS):
        errors.append("allowed_dispositions_mismatch")
    captured_at = payload.get("captured_at")
    if captured_at is not None and not (
        isinstance(captured_at, str) and ISO_INSTANT_RE.fullmatch(captured_at)
    ):
        errors.append("captured_at_invalid")
    master_sha = payload.get("public_master_sha")
    source_snapshot = payload.get("issue_source_snapshot")
    if not isinstance(source_snapshot, list):
        errors.append("issue_source_snapshot_missing")
        source_snapshot = []
    source_numbers = [
        row.get("number") for row in source_snapshot if isinstance(row, Mapping)
    ]
    for source in source_snapshot:
        if isinstance(source, Mapping) and source.get("state") != "OPEN":
            errors.append(f"open_issue_state_invalid:{source.get('number')}")
    if sorted(source_numbers, key=str) != sorted(numbers, key=str):
        errors.append("issue_source_number_set_mismatch")
    normalized_snapshot = sorted(
        (_normalized_source_issue(row) for row in source_snapshot if isinstance(row, Mapping)),
        key=lambda row: row["number"],
    )
    if source_snapshot and payload.get("issue_snapshot_sha256") != _sha256_json(normalized_snapshot):
        errors.append("issue_snapshot_hash_mismatch")
    source_by_number = {row["number"]: row for row in normalized_snapshot}
    raw_by_number = {row.get("number"): row for row in source_snapshot if isinstance(row, Mapping)}
    closed_source = payload.get("closed_issue_source_snapshot", [])
    closed_outcomes = payload.get("closed_outcomes", [])
    closed_raw_by_number = (
        {row.get("number"): row for row in closed_source if isinstance(row, Mapping)}
        if isinstance(closed_source, list)
        else {}
    )
    if closed_source or closed_outcomes:
        if not isinstance(closed_source, list) or not isinstance(closed_outcomes, list):
            errors.append("closed_outcome_snapshot_invalid")
        else:
            closed_source_numbers = [
                row.get("number")
                for row in closed_source
                if isinstance(row, Mapping)
            ]
            closed_outcome_numbers = [
                row.get("number")
                for row in closed_outcomes
                if isinstance(row, Mapping)
            ]
            for number in sorted(set(closed_source_numbers), key=str):
                if closed_source_numbers.count(number) > 1:
                    errors.append(f"closed_issue_number_duplicate:{number}")
            for number in sorted(set(closed_outcome_numbers), key=str):
                if closed_outcome_numbers.count(number) > 1:
                    errors.append(f"closed_outcome_number_duplicate:{number}")
            for number in sorted(set(source_numbers) & set(closed_source_numbers), key=str):
                errors.append(f"open_closed_issue_overlap:{number}")
            normalized_closed = sorted(
                (
                    _normalized_closed_source(row)
                    for row in closed_source
                    if isinstance(row, Mapping)
                ),
                key=lambda row: row["number"],
            )
            if payload.get("closed_issue_snapshot_sha256") != _sha256_json(
                normalized_closed
            ):
                errors.append("closed_issue_snapshot_hash_mismatch")
            if payload.get("closed_outcome_count") != len(closed_outcomes):
                errors.append("closed_outcome_count_mismatch")
            closed_by_number = {
                row.get("number"): row
                for row in closed_outcomes
                if isinstance(row, Mapping)
            }
            if set(closed_by_number) != {
                row["number"] for row in normalized_closed
            }:
                errors.append("closed_outcome_number_set_mismatch")
            for source in normalized_closed:
                number = source["number"]
                outcome = closed_by_number.get(number)
                if not isinstance(outcome, Mapping):
                    continue
                obligation = {
                    "title": source["title"],
                    "body_sha256": source["body_sha256"],
                    "labels": source["labels"],
                }
                for field in ("number", "title", "body_sha256", "url", "created_at", "updated_at", "labels", "author", "state", "state_reason", "closed_at"):
                    if outcome.get(field) != source.get(field):
                        errors.append(f"closed_outcome_source_mismatch:{number}:{field}")
                errors.extend(_content_proof_errors(outcome.get("completion_proof"), repository_root, master_sha, number))
                raw_closed = closed_raw_by_number.get(number, {})
                raw_comments = raw_closed.get("comments", []) if isinstance(raw_closed, Mapping) else []
                for proof in outcome.get("completion_proof", []):
                    if not isinstance(proof, Mapping):
                        continue
                    evidence_url = proof.get("evidence_comment_url")
                    evidence_hash = proof.get("evidence_comment_body_sha256")
                    matching = next(
                        (
                            comment for comment in raw_comments
                            if isinstance(comment, Mapping) and comment.get("url") == evidence_url
                        ),
                        None,
                    )
                    if not isinstance(matching, Mapping):
                        errors.append(f"completion_evidence_comment_unresolved:{number}")
                        continue
                    body = _decode_text(matching.get("body_base64", ""))
                    if hashlib.sha256(body.encode("utf-8")).hexdigest() != evidence_hash:
                        errors.append(f"completion_evidence_comment_hash_mismatch:{number}")
                    if str(proof.get("implementation_commit", ""))[:8] not in body:
                        errors.append(f"implementation_commit_comment_unbound:{number}")
                    if proof.get("verification_exit_code") != 0:
                        errors.append(f"completion_verification_exit_nonzero:{number}")
                    if proof.get("verification_outcome") != "independently_verified" or not any(marker in body.casefold() for marker in ("verif", "pass", "exit 0", "exited 0", "zero")):
                        errors.append(f"completion_verification_outcome_unbound:{number}")
                    if proof.get("verification_executed_at") != matching.get("created_at"):
                        errors.append(f"completion_verification_time_unbound:{number}")
                if outcome.get("issue_record_sha256") != _sha256_json(source):
                    errors.append(f"closed_issue_record_hash_mismatch:{number}")
                if outcome.get("obligation_sha256") != _sha256_json(obligation):
                    errors.append(f"closed_issue_obligation_hash_mismatch:{number}")
                disposition = outcome.get("disposition")
                if (
                    outcome.get("state") != "CLOSED"
                    or outcome.get("state_reason") != "COMPLETED"
                    or disposition not in ALLOWED_DISPOSITIONS
                ):
                    errors.append(f"closed_outcome_state_invalid:{number}")
                if disposition == "implemented and independently verified" and outcome.get("unresolved_remainder") is not None:
                    errors.append(f"closed_verified_remainder_present:{number}")
                if disposition == "unresolved" and not (
                    isinstance(outcome.get("unresolved_remainder"), str)
                    and outcome["unresolved_remainder"].strip()
                ):
                    errors.append(f"closed_unresolved_remainder_missing:{number}")
    by_number = {row.get("number"): row for row in rows if isinstance(row, Mapping)}
    custody_evidence = {
        (item.get("artifact_sha256"), item.get("criterion"), item.get("verifier_sha256"))
        for item in payload.get("immutable_custody_evidence", []) if isinstance(item, Mapping)
    }
    canonical_dispositions = {
        "superseded by an exact named successor",
        "exact duplicate of one canonical issue",
    }
    for row in rows:
        if not isinstance(row, Mapping):
            errors.append("issue_row_not_object")
            continue
        number = row.get("number", "<missing>")
        disposition = row.get("disposition")
        if disposition not in ALLOWED_DISPOSITIONS:
            errors.append(f"issue_disposition_invalid:{number}")
        if row.get("public_master_sha") != master_sha:
            errors.append(f"issue_master_binding_mismatch:{number}")
        source = source_by_number.get(number)
        raw_source = raw_by_number.get(number)
        if isinstance(source, Mapping) and isinstance(raw_source, Mapping):
            if row.get("issue_record_sha256") != _sha256_json(source):
                errors.append(f"issue_record_hash_mismatch:{number}")
            obligation = {"title": source["title"], "body_sha256": source["body_sha256"], "labels": source["labels"]}
            if row.get("obligation_sha256") != _sha256_json(obligation):
                errors.append(f"issue_obligation_hash_mismatch:{number}")
            if row.get("compound_obligations") != [source["title"], f"body_sha256:{source['body_sha256']}"]:
                errors.append(f"issue_compound_obligations_mismatch:{number}")
        if disposition == "implemented and independently verified":
            errors.extend(_content_proof_errors(row.get("completion_proof"), repository_root, master_sha, number))
            raw_comments = raw_source.get("comments", []) if isinstance(raw_source, Mapping) else []
            for proof in row.get("completion_proof", []):
                if not isinstance(proof, Mapping):
                    continue
                matching = next(
                    (
                        comment for comment in raw_comments
                        if isinstance(comment, Mapping)
                        and comment.get("url") == proof.get("evidence_comment_url")
                    ),
                    None,
                )
                if not isinstance(matching, Mapping):
                    errors.append(f"completion_evidence_comment_unresolved:{number}")
                    continue
                body = _decode_text(matching.get("body_base64", ""))
                if hashlib.sha256(body.encode("utf-8")).hexdigest() != proof.get("evidence_comment_body_sha256"):
                    errors.append(f"completion_evidence_comment_hash_mismatch:{number}")
                if str(proof.get("implementation_commit", ""))[:8] not in body:
                    errors.append(f"implementation_commit_comment_unbound:{number}")
                if proof.get("verification_exit_code") != 0 or proof.get("verification_outcome") != "independently_verified":
                    errors.append(f"completion_verification_outcome_unbound:{number}")
                if proof.get("verification_executed_at") != matching.get("created_at"):
                    errors.append(f"completion_verification_time_unbound:{number}")
        closure = row.get("closure_proposed") is True
        proof = row.get("completion_proof")
        proof_shape_valid = (
            isinstance(proof, list) and bool(proof) and all(
                isinstance(item, Mapping)
                and re.fullmatch(r"[0-9a-f]{40}", str(item.get("commit", "")))
                and re.fullmatch(r"[0-9a-f]{64}", str(item.get("artifact_sha256", "")))
                and isinstance(item.get("criterion"), str) and bool(item["criterion"].strip())
                and re.fullmatch(r"[0-9a-f]{64}", str(item.get("verifier_sha256", "")))
                for item in proof
            )
        )
        proof_custody_valid = proof_shape_valid and all(
            (item["artifact_sha256"], item["criterion"], item["verifier_sha256"]) in custody_evidence
            for item in proof
        )
        if (
            disposition
            == "historical sub-3B or borrowed-lineage non-executable evidence"
            and row.get("canonical_issue") is not None
        ):
            historical_target = source_by_number.get(row.get("canonical_issue"))
            expected_url = (
                historical_target.get("url")
                if isinstance(historical_target, Mapping)
                else None
            )
            expected_body_hash = (
                historical_target.get("body_sha256")
                if isinstance(historical_target, Mapping)
                else None
            )
            if (
                row.get("canonical_issue") == number
                or not isinstance(historical_target, Mapping)
                or row.get("canonical_issue_url") != expected_url
                or row.get("canonical_obligation_sha256")
                != expected_body_hash
                or row.get("preserved_issue_body_sha256")
                != source.get("body_sha256")
            ):
                errors.append(f"historical_canonical_mapping_invalid:{number}")
        canonical = row.get("canonical_issue")
        target = by_number.get(canonical)
        canonical_valid = (
            disposition in canonical_dispositions and isinstance(canonical, int)
            and canonical != number and isinstance(target, Mapping)
            and target.get("obligation_sha256") == row.get("obligation_sha256")
            and row.get("canonical_obligation_sha256") == row.get("obligation_sha256")
        )
        if closure and disposition == "implemented and independently verified":
            if not isinstance(proof, list) or not proof:
                errors.append(f"closure_completion_proof_missing:{number}")
            elif not proof_shape_valid:
                errors.append(f"closure_completion_proof_invalid:{number}")
        if closure and disposition in canonical_dispositions and not canonical_valid:
            errors.append(f"closure_canonical_obligation_not_exact:{number}")
        if closure and disposition not in canonical_dispositions | {
            "implemented and independently verified",
            "historical sub-3B or borrowed-lineage non-executable evidence",
            "expired operational incident",
        }:
            errors.append(f"closure_disposition_lacks_allowed_basis:{number}")
        if closure and not proof_custody_valid and not canonical_valid:
            errors.append(f"closure_proof_or_canonical_missing:{number}")
            if proof_shape_valid:
                errors.append(f"closure_custody_evidence_unresolved:{number}")
        if closure and proof_custody_valid:
            if repository_root is None:
                errors.append(f"closure_repository_unresolved:{number}")
            else:
                for item in proof:
                    ancestry = subprocess.run(
                        ["git", "merge-base", "--is-ancestor", str(item["commit"]), str(master_sha)],
                        cwd=repository_root, capture_output=True, check=False,
                    )
                    if ancestry.returncode != 0:
                        errors.append(f"closure_commit_not_ancestor:{number}")
                        break
    return errors


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--public-ref", required=True)
    parser.add_argument("--issues-json")
    parser.add_argument("--closed-issues-json")
    parser.add_argument("--completion-evidence-json")
    parser.add_argument(
        "--captured-at",
        help=(
            "ISO8601 Z instant the issue snapshot was acquired; defaults to the "
            "build instant, which bounds acquisition from above"
        ),
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        raw = (
            Path(args.issues_json).read_text(encoding="utf-8")
            if args.issues_json
            else sys.stdin.read()
        )
        issues = json.loads(raw)
        if not isinstance(issues, list):
            raise ValueError("issue snapshot must be a JSON list")
        captured_at = args.captured_at or datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        if not ISO_INSTANT_RE.fullmatch(captured_at):
            raise ValueError("captured-at must be ISO8601 YYYY-MM-DDTHH:MM:SSZ")
        payload = build_issue_census(
            Path(args.repo_root), args.public_ref, issues,
            captured_at=captured_at,
            closed_issues=(json.loads(Path(args.closed_issues_json).read_text(encoding="utf-8")) if args.closed_issues_json else []),
            completion_evidence=(json.loads(Path(args.completion_evidence_json).read_text(encoding="utf-8")) if args.completion_evidence_json else []),
        )
        errors = validate_issue_census(payload, repository_root=Path(args.repo_root))
        if errors:
            raise ValueError("; ".join(errors))
        _write_json_atomic(Path(args.output), payload)
    except Exception as exc:
        print(f"EMBER_01_ISSUE_CENSUS FAIL: {exc}")
        return 1
    print(
        "EMBER_01_ISSUE_CENSUS PASS: "
        f"open_issues={payload['open_issue_count']} "
        f"public_master={payload['public_master_sha']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
