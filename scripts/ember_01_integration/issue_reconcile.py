# goal_id: EMBER-01
# workstream_id: EMBER-01A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Plan fail-closed, issue-by-issue public tracker reconciliation."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping


ALLOWED_DISPOSITIONS = {
    "current executable obligation",
    "preserved research direction",
    "implemented and independently verified",
    "superseded by an exact named successor",
    "exact duplicate of one canonical issue",
    "historical sub-3B or borrowed-lineage non-executable evidence",
    "expired operational incident",
    "unresolved",
}

LABEL_BY_DISPOSITION = {
    "current executable obligation": "ember:current",
    "preserved research direction": "ember:research",
    "implemented and independently verified": "ember:verified",
    "superseded by an exact named successor": "ember:superseded",
    "exact duplicate of one canonical issue": "ember:duplicate",
    "historical sub-3B or borrowed-lineage non-executable evidence": "ember:historical",
    "expired operational incident": "ember:expired",
    "unresolved": "ember:unresolved",
}


def _git(repository_root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository_root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ValueError(f"git_failed:{' '.join(arguments)}:{detail}")
    return result.stdout.strip()


def _closure_proof_verified(
    repository_root: Path,
    public_master_sha: str,
    issue_number: int,
    disposition: str,
    source_body_sha256: str,
    obligation_sha256: str,
    proof: Mapping[str, Any],
) -> bool:
    commit = str(proof.get("commit", ""))
    artifact_path = str(proof.get("artifact_path", ""))
    if (
        not re.fullmatch(r"[0-9a-f]{40}", commit)
        or not artifact_path
        or "\\" in artifact_path
        or artifact_path.startswith("/")
        or re.match(r"^[A-Za-z]:", artifact_path)
        or ".." in Path(artifact_path).parts
    ):
        return False
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, public_master_sha],
        cwd=repository_root,
        capture_output=True,
        check=False,
    )
    if ancestor.returncode != 0:
        return False
    artifact = subprocess.run(
        ["git", "show", f"{commit}:{artifact_path}"],
        cwd=repository_root,
        capture_output=True,
        check=False,
    )
    if artifact.returncode != 0:
        return False
    if hashlib.sha256(artifact.stdout).hexdigest() != proof.get("artifact_sha256"):
        return False
    try:
        receipt = json.loads(artifact.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    subject_public_master_sha = str(receipt.get("subject_public_master_sha", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", subject_public_master_sha):
        return False
    for descendant in (commit, public_master_sha):
        binding = subprocess.run(
            ["git", "merge-base", "--is-ancestor", subject_public_master_sha, descendant],
            cwd=repository_root,
            capture_output=True,
            check=False,
        )
        if binding.returncode != 0:
            return False
    return (
        isinstance(receipt, Mapping)
        and receipt.get("schema") == "ember-01-issue-closure-proof-v1"
        and receipt.get("issue") == issue_number
        and receipt.get("disposition") == disposition
        and receipt.get("source_body_sha256") == source_body_sha256
        and receipt.get("obligation_sha256") == obligation_sha256
        and receipt.get("criterion") == proof.get("criterion")
        and receipt.get("result") == "PASSED"
        and receipt.get("independent_verification") is True
        and isinstance(receipt.get("evidence"), list)
        and bool(receipt["evidence"])
    )


def validate_inputs(
    census: Mapping[str, Any],
    live_issues: list[Mapping[str, Any]],
    repository_root: Path,
    public_master_sha: str,
) -> list[str]:
    errors: list[str] = []
    rows = census.get("issues")
    if not isinstance(rows, list):
        return ["issues_not_list"]
    live_numbers = [
        row.get("number") for row in live_issues if isinstance(row.get("number"), int)
    ]
    census_numbers = [
        row.get("number")
        for row in rows
        if isinstance(row, Mapping) and isinstance(row.get("number"), int)
    ]
    for number in sorted(set(census_numbers)):
        if census_numbers.count(number) > 1:
            errors.append(f"census_issue_duplicate:{number}")
    for number in sorted(set(live_numbers)):
        if live_numbers.count(number) > 1:
            errors.append(f"live_issue_duplicate:{number}")
    live_by_number = {
        row.get("number"): row
        for row in live_issues
        if isinstance(row.get("number"), int)
    }
    census_by_number = {
        row.get("number"): row
        for row in rows
        if isinstance(row, Mapping) and isinstance(row.get("number"), int)
    }
    for number, row in sorted(live_by_number.items()):
        if not re.fullmatch(r"[0-9a-f]{64}", str(row.get("body_sha256") or "")):
            errors.append(f"live_issue_body_sha256_invalid:{number}")
    for number, row in sorted(census_by_number.items()):
        if not re.fullmatch(r"[0-9a-f]{64}", str(row.get("body_sha256") or "")):
            errors.append(f"issue_body_sha256_invalid:{number}")
        if not re.fullmatch(
            r"[0-9a-f]{64}",
            str(row.get("obligation_sha256") or ""),
        ):
            errors.append(f"issue_obligation_sha256_invalid:{number}")
    for number in sorted(set(live_by_number) - set(census_by_number)):
        errors.append(f"live_issue_unclassified:{number}")
    canonical_dispositions = {
        "superseded by an exact named successor",
        "exact duplicate of one canonical issue",
    }
    rows_by_obligation: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        obligation_sha256 = row.get("obligation_sha256")
        if re.fullmatch(r"[0-9a-f]{64}", str(obligation_sha256 or "")):
            rows_by_obligation.setdefault(str(obligation_sha256), []).append(row)
    for obligation_sha256, obligation_rows in sorted(rows_by_obligation.items()):
        if len(obligation_rows) < 2:
            continue
        roots = [
            row
            for row in obligation_rows
            if row.get("disposition") not in canonical_dispositions
        ]
        root_number = roots[0].get("number") if len(roots) == 1 else None
        linked = (
            isinstance(root_number, int)
            and all(
                row is roots[0]
                or (
                    row.get("disposition") in canonical_dispositions
                    and row.get("canonical_issue") == root_number
                )
                for row in obligation_rows
            )
        )
        if not linked:
            issue_numbers = ",".join(
                str(row.get("number"))
                for row in sorted(
                    obligation_rows,
                    key=lambda item: str(item.get("number")),
                )
            )
            errors.append(
                f"obligation_multiple_unlinked:{obligation_sha256}:{issue_numbers}"
            )
    for row in rows:
        if not isinstance(row, Mapping):
            errors.append("issue_row_not_object")
            continue
        number = row.get("number", "<missing>")
        if row.get("disposition") not in ALLOWED_DISPOSITIONS:
            errors.append(f"issue_disposition_invalid:{number}")
        live = live_by_number.get(number)
        if live is None:
            errors.append(f"issue_missing_live:{number}")
        elif live.get("body_sha256") != row.get("body_sha256"):
            errors.append(f"issue_body_changed:{number}")
        closure = row.get("closure_proposed") is True
        if closure:
            if not isinstance(live, Mapping) or live.get("state") != "OPEN":
                errors.append(f"closure_source_not_open:{number}")
            if str(row.get("unresolved_remainder") or "").strip():
                errors.append(f"closure_has_unresolved_remainder:{number}")
            allowed_closure_dispositions = {
                "implemented and independently verified",
                "superseded by an exact named successor",
                "exact duplicate of one canonical issue",
                "expired operational incident",
            }
            if row.get("disposition") not in allowed_closure_dispositions:
                errors.append(f"closure_disposition_lacks_allowed_basis:{number}")
            proof_dispositions = {
                "implemented and independently verified",
                "expired operational incident",
            }
            if row.get("disposition") in proof_dispositions:
                proof = row.get("completion_proof")
                if not isinstance(proof, list) or not proof:
                    errors.append(f"closure_completion_proof_missing:{number}")
                elif not all(
                    isinstance(item, Mapping)
                    and re.fullmatch(r"[0-9a-f]{40}", str(item.get("commit", "")))
                    and isinstance(item.get("artifact_path"), str)
                    and bool(item["artifact_path"].strip())
                    and re.fullmatch(
                        r"[0-9a-f]{64}",
                        str(item.get("artifact_sha256", "")),
                    )
                    and isinstance(item.get("criterion"), str)
                    and bool(item["criterion"].strip())
                    for item in proof
                ):
                    errors.append(f"closure_completion_proof_invalid:{number}")
                elif not all(
                    _closure_proof_verified(
                        repository_root,
                        public_master_sha,
                        int(number),
                        str(row.get("disposition")),
                        str(row.get("body_sha256")),
                        str(row.get("obligation_sha256")),
                        item,
                    )
                    for item in proof
                ):
                    errors.append(f"closure_completion_proof_unverified:{number}")
            if row.get("disposition") in canonical_dispositions:
                canonical_issue = row.get("canonical_issue")
                target = census_by_number.get(canonical_issue)
                if (
                    not isinstance(canonical_issue, int)
                    or canonical_issue == number
                    or not isinstance(target, Mapping)
                ):
                    errors.append(f"closure_canonical_issue_invalid:{number}")
                elif (
                    row.get("canonical_obligation_sha256")
                    != target.get("body_sha256")
                ):
                    errors.append(
                        f"closure_canonical_obligation_mismatch:{number}"
                    )
                else:
                    target_live = live_by_number.get(canonical_issue, {})
                    target_body = str(target_live.get("body", ""))
                    issue_binding = f"preserves_issue: #{number}"
                    source_hash_binding = (
                        f"source_body_sha256: {row.get('body_sha256')}"
                    )
                    if (
                        issue_binding not in target_body
                        or source_hash_binding not in target_body
                    ):
                        errors.append(
                            f"closure_canonical_source_not_preserved:{number}"
                        )
                    if (
                        target.get("closure_proposed") is True
                        or target_live.get("state") != "OPEN"
                    ):
                        errors.append(
                            f"closure_canonical_target_not_surviving:{number}"
                        )
    return errors


def build_plan(
    census: Mapping[str, Any], live_issues: list[Mapping[str, Any]]
) -> dict[str, Any]:
    live_by_number = {row["number"]: row for row in live_issues}
    issue_plans: list[dict[str, Any]] = []
    for row in sorted(census["issues"], key=lambda item: item["number"]):
        number = int(row["number"])
        disposition = str(row["disposition"])
        obligation_sha256 = str(row["obligation_sha256"])
        classification_binding = {
            "body_sha256": row["body_sha256"],
            "closure_proposed": row.get("closure_proposed") is True,
            "completion_proof": row.get("completion_proof", []),
            "canonical_issue": row.get("canonical_issue"),
            "canonical_obligation_sha256": row.get(
                "canonical_obligation_sha256"
            ),
            "disposition": disposition,
            "issue": number,
            "obligation_sha256": obligation_sha256,
            "public_master_sha": census["public_master_sha"],
            "unresolved_remainder": row.get("unresolved_remainder"),
        }
        classification_sha256 = hashlib.sha256(
            json.dumps(
                classification_binding,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        marker = (
            "<!-- ember-01-reconcile:v1 "
            f"issue={number} classification_sha256={classification_sha256} -->"
        )
        remainder = str(row.get("unresolved_remainder") or "none")
        canonical_lines: list[str] = []
        if isinstance(row.get("canonical_issue"), int):
            canonical_lines = [
                f"Canonical issue: #{row['canonical_issue']}.",
                "Canonical obligation SHA-256: "
                f"{row['canonical_obligation_sha256']}.",
            ]
        proof_lines: list[str] = []
        for proof in row.get("completion_proof", []):
            proof_lines.extend(
                [
                    f"Proof commit: {proof['commit']}.",
                    f"Proof artifact SHA-256: {proof['artifact_sha256']}.",
                    f"Proof criterion: {proof['criterion']}.",
                ]
            )
        body = "\n".join(
            [
                "EMBER-01A issue-by-issue reconciliation.",
                "",
                f"Disposition: {disposition}.",
                f"Unresolved remainder: {remainder}.",
                f"Public master binding: {census['public_master_sha']}.",
                f"Obligation SHA-256: {obligation_sha256}.",
                *canonical_lines,
                *proof_lines,
                "",
                "This classification makes no model, capability, benchmark, "
                "or research claim.",
                "",
                marker,
            ]
        )
        live = live_by_number[number]
        existing_labels = {
            str(label.get("name", "")) if isinstance(label, Mapping) else str(label)
            for label in live.get("labels", [])
        }
        existing_comments = [
            str(comment.get("body", ""))
            if isinstance(comment, Mapping)
            else str(comment)
            for comment in live.get("comments", [])
        ]
        operations: list[dict[str, Any]] = []
        desired_label = LABEL_BY_DISPOSITION[disposition]
        conflicting_labels = (
            existing_labels & set(LABEL_BY_DISPOSITION.values()) - {desired_label}
        )
        for conflicting_label in sorted(conflicting_labels):
            operations.append(
                {"type": "propose_remove_label", "label": conflicting_label}
            )
        if desired_label not in existing_labels:
            operations.append({"type": "propose_ensure_label", "label": desired_label})
        if not any(marker in comment for comment in existing_comments):
            operations.append(
                {"type": "propose_ensure_comment", "marker": marker, "body": body}
            )
        if row.get("closure_proposed") is True:
            reason = (
                "completed"
                if disposition == "implemented and independently verified"
                else "not_planned"
            )
            close_operation: dict[str, Any] = {"type": "propose_close", "reason": reason}
            if isinstance(row.get("canonical_issue"), int):
                close_operation["canonical_issue"] = row["canonical_issue"]
            operations.append(close_operation)
        issue_plans.append(
            {
                "number": number,
                "expected_state": live_by_number[number]["state"],
                "expected_body_sha256": row["body_sha256"],
                "disposition": disposition,
                "operations": operations,
            }
        )
    return {
        "schema": "ember-01-issue-reconciliation-plan-v1",
        "public_master_sha": census["public_master_sha"],
        "mutation_performed": False,
        "live_snapshot_authoritative": False,
        "requires_live_reverification": True,
        "issues": issue_plans,
    }


def _load_object(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _load_list(path: Path) -> list[Mapping[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(
        isinstance(row, Mapping) for row in payload
    ):
        raise ValueError(f"JSON object list required: {path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan")
    plan.add_argument("--census", required=True, type=Path)
    plan.add_argument("--live", required=True, type=Path)
    plan.add_argument("--output", required=True, type=Path)
    plan.add_argument("--repo-root", type=Path, default=Path.cwd())
    plan.add_argument("--public-ref", required=True)
    args = parser.parse_args()

    try:
        census = _load_object(args.census)
        public_master_sha = _git(args.repo_root, "rev-parse", args.public_ref)
        if census.get("public_master_sha") != public_master_sha:
            raise ValueError(
                "public_master_mismatch:"
                f"declared={census.get('public_master_sha')}:"
                f"actual={public_master_sha}"
            )
        live = _load_list(args.live)
        errors = validate_inputs(
            census,
            live,
            args.repo_root,
            public_master_sha,
        )
        if errors:
            print("EMBER_01_ISSUE_RECONCILE FAIL: " + "; ".join(errors))
            return 1
        reconciliation_plan = build_plan(census, live)
        args.output.write_text(
            json.dumps(reconciliation_plan, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except Exception as exc:
        print(f"EMBER_01_ISSUE_RECONCILE FAIL: {exc}")
        return 1
    print("EMBER_01_ISSUE_RECONCILE PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
