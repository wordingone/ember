#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Revalidate land210g's public Git lineage and correct its exclusion count."""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from scripts.lib.invariant import stamp


GOAL_ID = "EMBER-02"
WORKSTREAM_ID = "EMBER-02A"
NEXT_EXECUTED_OUTCOME = "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
TICKET = "LAND210G-EXPERIMENT-RUNNERS"
LANDING_COMMIT = "617f071e36b2af20efccd9af4a574ea488ed3088"
EXPECTED_SUBJECT_COMMIT = "e8ca7191fd5ac29594868894ced6e5b5efafa9f8"
EXPECTED_HISTORICAL_SHA256 = (
    "ca77488917d85467f021c4d939e8a061aa0880ffa9ed99b10de5496cd6ccb703"
)
EXPECTED_RECORDED_VERDICT = "LAND210G_EXPERIMENT_RUNNERS_26_LANDED_7_EXCLUDED"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

LINEAGE_COMMITS = {
    "experiment_runners_pr_766": LANDING_COMMIT,
    "spend_field_repair_pr_775": "0bfa3a46a3dcf7c1693a6c92025442386b2c21d6",
    "family_3_stragglers_pr_777": "70aefaa0a92fdebd376c068133749cc87760d074",
    "e2b_pair_pr_780": "560f93c3ceb9a86e67f663f9f8bfc5c8389ccaa7",
    "authority_lock_pr_807_head": "4f758db0ec11b5089698d80215a1145d48ef7537",
    "mixture_retirement_pr_1132": "7ea8b38b3ea727495e392884ee53c49a3697113e",
}

EXPECTED_LATER_CHANGES = {
    "scripts/conv_c03_muon_ns3_live.py": {
        "sha256": "d45f8ac529a3d4febf3ae7253093e4d357dcc6708f032b1d6fd6f7fc2c324204",
        "last_change_commit": "4f758db0ec11b5089698d80215a1145d48ef7537",
        "public_pr": "https://github.com/wordingone/ember/pull/807",
        "disposition": "later authority-and-totality lock",
    },
    "scripts/ember_cbase_mixture.py": {
        "sha256": "2b74e18b585d50c4b092a21c3bbeb18694bcabd37b1d20a580dd3742221fda36",
        "last_change_commit": "7ea8b38b3ea727495e392884ee53c49a3697113e",
        "public_pr": "https://github.com/wordingone/ember/pull/1132",
        "disposition": "later historical assembler retirement",
    },
}


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{path.name} is not strict UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain one JSON object")
    return value


def _git(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"git {' '.join(args)} failed: {message}")
    return result.stdout


def git_blob(root: Path, commit: str, path: str) -> bytes:
    return _git(root, "show", f"{commit}:{path}")


def git_blob_oid(root: Path, commit: str, path: str) -> str:
    raw = _git(root, "ls-tree", commit, "--", path)
    line = raw.decode("utf-8", errors="strict").strip()
    match = re.fullmatch(r"100644 blob ([0-9a-f]{40})\t(.+)", line)
    if match is None or match.group(2) != path:
        raise ValueError(f"no exact Git blob object for {commit}:{path}")
    return match.group(1)


def _is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", ancestor, descendant],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def _last_change_commit(root: Path, commit: str, path: str) -> str:
    value = _git(root, "log", "-1", "--format=%H", commit, "--", path)
    commit_sha = value.decode("ascii", errors="strict").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
        raise ValueError(f"no exact last-change commit for {path}")
    return commit_sha


def _validate_path(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("scripts/"):
        raise ValueError("candidate path must be a scripts/ path")
    if "\\" in value or ".." in Path(value).parts or Path(value).is_absolute():
        raise ValueError("candidate path is not confined")
    return value


def _validate_sha(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be lowercase SHA-256")
    return value


def validate_historical_structure(historical: dict[str, Any]) -> dict[str, Any]:
    if historical.get("ticket") != TICKET:
        raise ValueError("historical ticket mismatch")
    if historical.get("issue") != "ember#210":
        raise ValueError("historical issue binding mismatch")
    if historical.get("verdict") != EXPECTED_RECORDED_VERDICT:
        raise ValueError("historical recorded verdict mismatch")
    if historical.get("pass") is not True:
        raise ValueError("historical pass field is not true")
    if historical.get("api_spend_usd") != 0.0:
        raise ValueError("historical api_spend_usd mismatch")

    files = historical.get("files")
    governor = historical.get("excluded_governor_cport")
    forward = historical.get("excluded_forward_dependency_on_later_families")
    if not isinstance(files, list) or len(files) != 26:
        raise ValueError("historical landed-file population must contain 26 rows")
    if not isinstance(governor, list) or len(governor) != 1:
        raise ValueError("historical governor-exclusion population must contain one row")
    if not isinstance(forward, list) or len(forward) != 7:
        raise ValueError("historical forward-exclusion population must contain seven rows")

    landed_paths: list[str] = []
    for row in files:
        if not isinstance(row, dict):
            raise ValueError("historical file row must be an object")
        landed_paths.append(_validate_path(row.get("path")))
        _validate_sha(row.get("stage_sha256"), field="stage_sha256")
        _validate_sha(row.get("landed_sha256"), field="landed_sha256")

    excluded_paths: list[str] = []
    for row in [*governor, *forward]:
        if not isinstance(row, dict):
            raise ValueError("historical exclusion row must be an object")
        excluded_paths.append(_validate_path(row.get("path")))

    all_paths = [*landed_paths, *excluded_paths]
    if len(set(all_paths)) != len(all_paths):
        raise ValueError("candidate paths must be unique")
    candidate_count = historical.get("candidates_total")
    if (
        candidate_count != 34
        or len(landed_paths) + len(excluded_paths) != candidate_count
    ):
        raise ValueError("historical candidate arithmetic mismatch")

    return {
        "landed_paths": landed_paths,
        "excluded_paths": excluded_paths,
        "landed_count": len(landed_paths),
        "excluded_count": len(excluded_paths),
        "candidate_count": candidate_count,
        "recorded_verdict_exclusion_count_incorrect": (
            len(excluded_paths) == 8 and "_7_EXCLUDED" in EXPECTED_RECORDED_VERDICT
        ),
    }


def validate_landing_blobs(
    historical: dict[str, Any],
    oid_reader: Callable[[str, str], str],
    subject_blob_reader: Callable[[str, str], bytes],
) -> dict[str, Any]:
    matches = 0
    not_rehashed: list[dict[str, Any]] = []
    for row in historical["files"]:
        path = row["path"]
        landing_oid = oid_reader(LANDING_COMMIT, path)
        subject_oid = oid_reader(EXPECTED_SUBJECT_COMMIT, path)
        if path in EXPECTED_LATER_CHANGES:
            if landing_oid == subject_oid:
                raise ValueError(f"expected a later Git object for {path}")
            not_rehashed.append(
                {
                    "path": path,
                    "landing_blob_oid": landing_oid,
                    "recorded_landing_sha256": row["landed_sha256"],
                    "reason": (
                        "the subject path has a later Git object; this pass does not "
                        "reassert the unavailable historical blob bytes"
                    ),
                }
            )
            continue
        if landing_oid != subject_oid:
            raise ValueError(f"landing tree/object mismatch for {path}")
        actual = sha256_bytes(subject_blob_reader(EXPECTED_SUBJECT_COMMIT, path))
        expected = row["landed_sha256"]
        if actual != expected:
            raise ValueError(
                f"landing blob mismatch for {path}: expected {expected}, got {actual}"
            )
        matches += 1
    return {"matches": matches, "not_rehashed": not_rehashed}


def _canonical_rows_digest(rows: list[dict[str, Any]]) -> str:
    raw = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(raw)


def validate_public_lineage(
    root: Path,
    historical: dict[str, Any],
    *,
    subject_commit: str,
) -> dict[str, Any]:
    if subject_commit != EXPECTED_SUBJECT_COMMIT:
        raise ValueError("subject commit is not the reviewed public base")
    resolved_subject = _git(root, "rev-parse", f"{subject_commit}^{{commit}}")
    if resolved_subject.decode("ascii").strip() != subject_commit:
        raise ValueError("subject commit did not resolve exactly")
    for name, commit in LINEAGE_COMMITS.items():
        if not _is_ancestor(root, commit, subject_commit):
            raise ValueError(f"required lineage commit is not an ancestor: {name}")

    historical_rel = (
        "receipts/ember-c-scale/land210g-experiment-runners-receipt.json"
    )
    subject_historical_sha = sha256_bytes(
        git_blob(root, subject_commit, historical_rel)
    )
    if subject_historical_sha != EXPECTED_HISTORICAL_SHA256:
        raise ValueError("subject historical receipt bytes do not match")

    landing_validation = validate_landing_blobs(
        historical,
        lambda commit, path: git_blob_oid(root, commit, path),
        lambda commit, path: git_blob(root, commit, path),
    )
    structure = validate_historical_structure(historical)

    original_rows: list[dict[str, Any]] = []
    changed_rows: list[dict[str, Any]] = []
    for row in historical["files"]:
        path = row["path"]
        current_sha = sha256_bytes(git_blob(root, subject_commit, path))
        current = {"path": path, "sha256": current_sha}
        original_rows.append(current)
        if current_sha != row["landed_sha256"]:
            expected = EXPECTED_LATER_CHANGES.get(path)
            if expected is None or current_sha != expected["sha256"]:
                raise ValueError(f"unrecognized post-landing bytes for {path}")
            last_change = _last_change_commit(root, subject_commit, path)
            if last_change != expected["last_change_commit"]:
                raise ValueError(f"post-landing provenance mismatch for {path}")
            changed_rows.append(
                {
                    "path": path,
                    "landing_sha256": row["landed_sha256"],
                    "subject_sha256": current_sha,
                    "last_change_commit": last_change,
                    "public_pr": expected["public_pr"],
                    "disposition": expected["disposition"],
                }
            )

    if set(EXPECTED_LATER_CHANGES) != {row["path"] for row in changed_rows}:
        raise ValueError("post-landing change population mismatch")

    excluded_rows = [
        {"path": path, "sha256": sha256_bytes(git_blob(root, subject_commit, path))}
        for path in structure["excluded_paths"]
    ]
    all_rows = sorted([*original_rows, *excluded_rows], key=lambda row: row["path"])
    if len(all_rows) != 34 or len({row["path"] for row in all_rows}) != 34:
        raise ValueError("subject tracked-candidate population mismatch")

    return {
        "historical_candidate_count": structure["candidate_count"],
        "historical_landed_file_count": structure["landed_count"],
        "historical_exclusion_count": structure["excluded_count"],
        "recorded_verdict": EXPECTED_RECORDED_VERDICT,
        "recorded_verdict_exclusion_count_incorrect": structure[
            "recorded_verdict_exclusion_count_incorrect"
        ],
        "landing_commit": LANDING_COMMIT,
        "direct_landing_blob_matches": landing_validation["matches"],
        "historical_landing_hashes_not_rehashed": len(
            landing_validation["not_rehashed"]
        ),
        "historical_landing_hash_gaps": landing_validation["not_rehashed"],
        "subject_commit": subject_commit,
        "subject_tracked_candidate_count": len(all_rows),
        "subject_original_bytes_unchanged": len(original_rows) - len(changed_rows),
        "traceable_later_changes": changed_rows,
        "historically_excluded_paths_now_tracked": excluded_rows,
        "all_subject_candidate_rows_sha256": _canonical_rows_digest(all_rows),
        "lineage_commits": LINEAGE_COMMITS,
    }


def build_receipt(
    root: Path,
    historical_path: Path,
    *,
    subject_commit: str,
    timestamp: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    historical_path = historical_path.resolve()
    digest = sha256_file(historical_path)
    if digest != EXPECTED_HISTORICAL_SHA256:
        raise ValueError(
            "historical receipt SHA-256 mismatch: "
            f"expected {EXPECTED_HISTORICAL_SHA256}, got {digest}"
        )
    expected_parent = (root / "receipts" / "ember-c-scale").resolve()
    if historical_path.parent != expected_parent:
        raise ValueError("historical receipt must be under receipts/ember-c-scale")
    historical = load_json(historical_path)
    validate_historical_structure(historical)
    lineage = validate_public_lineage(
        root,
        historical,
        subject_commit=subject_commit,
    )

    ts = timestamp or datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    receipt = {
        "ticket": TICKET,
        "ts": ts,
        "issue": "ember#210",
        "drain_issue": 700,
        "goal_id": GOAL_ID,
        "workstream_id": WORKSTREAM_ID,
        "next_executed_outcome": NEXT_EXECUTED_OUTCOME,
        "mode": "PUBLIC_GIT_LINEAGE_REVALIDATION",
        "sha_convention": "bytes on disk as-is (binary read, no normalization)",
        "supersedes": historical_path.relative_to(root).as_posix(),
        "historical_receipt_sha256": digest,
        "public_lineage_revalidation": lineage,
        "public_evidence": {
            "triage_ruling": (
                "https://github.com/wordingone/ember/issues/210"
                "#issuecomment-4890625466"
            ),
            "tier_2_landing_ladder": (
                "https://github.com/wordingone/ember/issues/210"
                "#issuecomment-4944319195"
            ),
            "tracking_hazard_closure": (
                "https://github.com/wordingone/ember/issues/210"
                "#issuecomment-5030468387"
            ),
            "experiment_runners_pr": "https://github.com/wordingone/ember/pull/766",
            "family_3_stragglers_pr": "https://github.com/wordingone/ember/pull/777",
            "e2b_pair_pr": "https://github.com/wordingone/ember/pull/780",
        },
        "producer": {
            "path": Path(__file__).resolve().relative_to(root).as_posix(),
            "sha256": sha256_file(Path(__file__).resolve()),
        },
        "verdict": (
            "HISTORICAL_24_BYTES_DIRECTLY_VERIFIED_8_EXCLUSIONS_CORRECTED_"
            "ALL_34_TRACKED"
        ),
        "claim_boundary": {
            "historical_landing_bytes_directly_revalidated": 24,
            "all_26_historical_landing_hashes_revalidated": False,
            "historical_exclusion_count_corrected": True,
            "all_34_candidates_tracked_at_subject": True,
            "issue_210_land210g_tracking_subset_revalidated": True,
            "issue_210_whole_closure_revalidated": False,
            "historical_runtime_checks_replayed": False,
            "historical_argparse_findings_replayed": False,
            "preexisting_runtime_defects_cured": False,
            "historical_paid_api_surface_usage_revalidated": False,
            "tier_3_private_archive_revalidated": False,
            "gpu_experiment_replayed": False,
            "training_claim": False,
            "model_capability_claim": False,
            "issue_700_completion_claim": False,
        },
        "paid_api_surface_used": False,
    }
    return stamp(receipt, str(root))


def publish(receipt: dict[str, Any], target: Path, root: Path) -> None:
    target = target.resolve()
    allowed = (root.resolve() / "receipts" / "ember-c-scale").resolve()
    if target.parent != allowed:
        raise ValueError("output must be under receipts/ember-c-scale")
    raw = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with target.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO)
    parser.add_argument("--historical-receipt", type=Path, required=True)
    parser.add_argument(
        "--subject-commit",
        default=EXPECTED_SUBJECT_COMMIT,
        help="exact reviewed public commit whose Git tree is revalidated",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = build_receipt(
        args.root,
        args.historical_receipt,
        subject_commit=args.subject_commit,
    )
    publish(receipt, args.output, args.root)
    print(json.dumps({"status": "PASS", "ticket": receipt["ticket"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
