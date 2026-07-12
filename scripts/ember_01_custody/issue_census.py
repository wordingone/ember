# goal_id: EMBER-01
# workstream_id: EMBER-01B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Build a non-mutating public issue census bound to exact Git evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping


ISSUE_REF_RE = re.compile(r"(?<![A-Za-z0-9_])#([1-9][0-9]*)")
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


def build_issue_census(
    repository_root: Path,
    public_ref: str,
    issues: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    root = repository_root.resolve()
    public_master_sha = _git(root, "rev-parse", public_ref).strip()
    if not re.fullmatch(r"[0-9a-f]{40}", public_master_sha):
        raise ValueError("public ref did not resolve to one commit")
    normalized = sorted(
        (_normalized_issue(issue) for issue in issues),
        key=lambda row: row["number"],
    )
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
        "public_master_sha": public_master_sha,
        "open_issue_count": len(rows),
        "issue_snapshot_sha256": _sha256_json(normalized),
        "snapshot_max_issue_updated_at": max(
            (row["updated_at"] for row in rows), default=None
        ),
        "allowed_dispositions": list(ALLOWED_DISPOSITIONS),
        "mutation_performed": False,
        "issues": rows,
    }


def validate_issue_census(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    rows = payload.get("issues")
    if not isinstance(rows, list):
        return ["issues_not_list"]
    numbers = [
        row.get("number") for row in rows if isinstance(row, Mapping)
    ]
    for number in sorted(set(numbers), key=lambda value: str(value)):
        if numbers.count(number) > 1:
            errors.append(f"issue_number_duplicate:{number}")
    if payload.get("open_issue_count") != len(rows):
        errors.append("open_issue_count_mismatch")
    allowed = payload.get("allowed_dispositions")
    if allowed != list(ALLOWED_DISPOSITIONS):
        errors.append("allowed_dispositions_mismatch")
    master_sha = payload.get("public_master_sha")
    by_number = {
        row.get("number"): row for row in rows if isinstance(row, Mapping)
    }
    for row in rows:
        if not isinstance(row, Mapping):
            errors.append("issue_row_not_object")
            continue
        number = row.get("number", "<missing>")
        disposition = row.get("disposition")
        if disposition not in ALLOWED_DISPOSITIONS:
            errors.append(f"issue_disposition_invalid:{number}")
        if "public_master_sha" in row and row.get("public_master_sha") != master_sha:
            errors.append(f"issue_master_binding_mismatch:{number}")
        closure = row.get("closure_proposed") is True
        if closure and disposition == "implemented and independently verified":
            proof = row.get("completion_proof")
            if not isinstance(proof, list) or not proof:
                errors.append(f"closure_completion_proof_missing:{number}")
            elif not all(
                isinstance(item, Mapping)
                and re.fullmatch(r"[0-9a-f]{40}", str(item.get("commit", "")))
                and re.fullmatch(
                    r"[0-9a-f]{64}", str(item.get("artifact_sha256", ""))
                )
                and isinstance(item.get("criterion"), str)
                and bool(item["criterion"].strip())
                for item in proof
            ):
                errors.append(f"closure_completion_proof_invalid:{number}")
        canonical_dispositions = {
            "superseded by an exact named successor",
            "exact duplicate of one canonical issue",
        }
        if closure and disposition in canonical_dispositions:
            canonical = row.get("canonical_issue")
            if not isinstance(canonical, int) or canonical == number:
                errors.append(f"closure_canonical_issue_invalid:{number}")
            else:
                target = by_number.get(canonical)
                obligation = row.get("obligation_sha256")
                if (
                    not isinstance(target, Mapping)
                    or target.get("obligation_sha256") != obligation
                    or row.get("canonical_obligation_sha256") != obligation
                ):
                    errors.append(
                        f"closure_canonical_obligation_not_exact:{number}"
                    )
        if closure and disposition not in canonical_dispositions | {
            "implemented and independently verified",
            "historical sub-3B or borrowed-lineage non-executable evidence",
            "expired operational incident",
        }:
            errors.append(f"closure_disposition_lacks_allowed_basis:{number}")
        if closure:
            proof = row.get("completion_proof")
            proof_valid = (
                isinstance(proof, list)
                and bool(proof)
                and all(
                    isinstance(item, Mapping)
                    and re.fullmatch(
                        r"[0-9a-f]{40}", str(item.get("commit", ""))
                    )
                    and re.fullmatch(
                        r"[0-9a-f]{64}", str(item.get("artifact_sha256", ""))
                    )
                    and isinstance(item.get("criterion"), str)
                    and bool(item["criterion"].strip())
                    for item in proof
                )
            )
            canonical_valid = (
                disposition in canonical_dispositions
                and isinstance(row.get("canonical_issue"), int)
                and row.get("canonical_issue") != number
                and isinstance(by_number.get(row.get("canonical_issue")), Mapping)
                and by_number[row["canonical_issue"]].get("obligation_sha256")
                == row.get("obligation_sha256")
                and row.get("canonical_obligation_sha256")
                == row.get("obligation_sha256")
            )
            if not proof_valid and not canonical_valid:
                errors.append(f"closure_proof_or_canonical_missing:{number}")
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
        payload = build_issue_census(
            Path(args.repo_root), args.public_ref, issues
        )
        errors = validate_issue_census(payload)
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
