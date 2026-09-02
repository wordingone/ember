# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Closed evidence validation for claimed Ember autonomy rungs."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WINDOW_SCHEMA = "ember-autonomy-window-v2"
CLAIM_SCHEMA = "ember-autonomy-claim-v2"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
WINDOW_KEYS = {
    "schema",
    "rung",
    "window_id",
    "ts",
    "verdict",
    "independent_evidence",
    "provenance",
}
EVIDENCE_KEYS = {"kind", "commit_sha", "commit_ts"}
PROVENANCE_KEYS = {"producer", "window_payload_sha256", "token_sha256"}
CLAIM_KEYS = {"schema", "rung", "claim", "ts", "source_commit", "windows"}
CLAIM_WINDOW_KEYS = {"path", "sha256"}


class ClaimEvidenceError(ValueError):
    pass


def _object_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ClaimEvidenceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        decoded = raw.decode("utf-8", errors="strict")
        value = json.loads(decoded, object_pairs_hook=_object_no_duplicates)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClaimEvidenceError(f"{path.name}: unreadable JSON evidence ({exc})") from exc
    if not isinstance(value, dict):
        raise ClaimEvidenceError(f"{path.name}: evidence must be a JSON object")
    return value


def parse_utc_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ClaimEvidenceError("timestamp must be an ISO-8601 UTC string ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ClaimEvidenceError("timestamp is not valid ISO-8601") from exc
    if parsed.tzinfo != timezone.utc:
        raise ClaimEvidenceError("timestamp must resolve to UTC")
    return parsed


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ClaimEvidenceError(f"{path.name}: cannot hash evidence") from exc


def _require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ClaimEvidenceError(f"{label} schema mismatch missing={missing} extra={extra}")


def _require_safe_receipt_name(value: Any) -> str:
    if not isinstance(value, str) or not value.endswith(".json"):
        raise ClaimEvidenceError("window receipt path must be a JSON filename")
    if Path(value).name != value or "/" in value or "\\" in value or value in {".", ".."}:
        raise ClaimEvidenceError("window receipt path must be a confined filename")
    return value


def _git(repo_root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ClaimEvidenceError("git evidence check unavailable") from exc
    if completed.returncode != 0:
        raise ClaimEvidenceError(f"git evidence check failed: {' '.join(args)}")
    return completed.stdout.strip()


def _verified_commit_timestamp(repo_root: Path, commit_sha: Any) -> datetime:
    if not isinstance(commit_sha, str) or COMMIT_RE.fullmatch(commit_sha) is None:
        raise ClaimEvidenceError("source commit must be lowercase 40-hex")
    _git(repo_root, "cat-file", "-e", f"{commit_sha}^{{commit}}")
    return parse_utc_timestamp(
        datetime.fromisoformat(_git(repo_root, "show", "-s", "--format=%cI", commit_sha).replace("Z", "+00:00"))
        .astimezone(timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _validate_window(
    receipt_path: Path,
    *,
    repo_root: Path,
    expected_rung: str,
) -> tuple[datetime, str]:
    receipt = _read_json_object(receipt_path)
    _require_exact_keys(receipt, WINDOW_KEYS, "window")
    if receipt["schema"] != WINDOW_SCHEMA or receipt["rung"] != expected_rung:
        raise ClaimEvidenceError("window schema or rung mismatch")
    if not isinstance(receipt["window_id"], str) or not receipt["window_id"].strip():
        raise ClaimEvidenceError("window_id must be nonempty")
    if receipt["verdict"] != "PASS":
        raise ClaimEvidenceError("claimed window verdict must be PASS")
    window_ts = parse_utc_timestamp(receipt["ts"])

    evidence = receipt["independent_evidence"]
    if not isinstance(evidence, dict):
        raise ClaimEvidenceError("independent_evidence must be an object")
    _require_exact_keys(evidence, EVIDENCE_KEYS, "independent_evidence")
    if evidence["kind"] != "git_commit":
        raise ClaimEvidenceError("independent evidence kind must be git_commit")
    stated_commit_ts = parse_utc_timestamp(evidence["commit_ts"])
    actual_commit_ts = _verified_commit_timestamp(repo_root, evidence["commit_sha"])
    if stated_commit_ts != actual_commit_ts or window_ts != actual_commit_ts:
        raise ClaimEvidenceError("window timestamp is not bound to the Git commit timestamp")

    provenance = receipt["provenance"]
    if not isinstance(provenance, dict):
        raise ClaimEvidenceError("provenance must be an object")
    _require_exact_keys(provenance, PROVENANCE_KEYS, "provenance")
    if provenance["producer"] != "ember":
        raise ClaimEvidenceError("provenance producer must be exactly ember")
    payload = {key: value for key, value in receipt.items() if key != "provenance"}
    payload_sha = _canonical_sha256(payload)
    if provenance["window_payload_sha256"] != payload_sha:
        raise ClaimEvidenceError("window payload hash mismatch")
    provenance_core = {
        "producer": "ember",
        "window_payload_sha256": payload_sha,
    }
    if provenance["token_sha256"] != _canonical_sha256(provenance_core):
        raise ClaimEvidenceError("structured provenance token mismatch")
    return window_ts, evidence["commit_sha"]


def validate_claimed_rung(
    *,
    root: Path,
    repo_root: Path,
    rung: str,
    window_refs: list[Any],
) -> datetime:
    receipts_dir = root / "receipts" / "autonomy-ladder"
    if not receipts_dir.is_dir():
        raise ClaimEvidenceError("autonomy receipt directory is absent")
    if len(window_refs) < 5:
        raise ClaimEvidenceError("claimed rung requires at least five windows")

    normalized_refs = [_require_safe_receipt_name(ref) for ref in window_refs]
    if len(set(normalized_refs)) != len(normalized_refs):
        raise ClaimEvidenceError("claimed window references must be unique")

    window_times: list[datetime] = []
    window_commits: list[str] = []
    for ref in normalized_refs:
        receipt_path = receipts_dir / ref
        if not receipt_path.is_file():
            raise ClaimEvidenceError(f"window receipt does not resolve: {ref}")
        window_ts, commit_sha = _validate_window(
            receipt_path,
            repo_root=repo_root,
            expected_rung=rung,
        )
        window_times.append(window_ts)
        window_commits.append(commit_sha)
    if any(current <= previous for previous, current in zip(window_times, window_times[1:])):
        raise ClaimEvidenceError("window timestamps must be strictly increasing")
    if len(set(window_commits)) != len(window_commits):
        raise ClaimEvidenceError("each claimed window must bind a distinct Git commit")

    claim_paths = sorted(receipts_dir.glob(f"{rung}-claim-*.json"))
    if len(claim_paths) != 1:
        raise ClaimEvidenceError(f"expected exactly one claim receipt, found {len(claim_paths)}")
    claim = _read_json_object(claim_paths[0])
    _require_exact_keys(claim, CLAIM_KEYS, "claim")
    if (
        claim["schema"] != CLAIM_SCHEMA
        or claim["rung"] != rung
        or claim["claim"] is not True
    ):
        raise ClaimEvidenceError("claim schema, rung, or verdict mismatch")
    claim_ts = parse_utc_timestamp(claim["ts"])
    _verified_commit_timestamp(repo_root, claim["source_commit"])
    if claim["source_commit"] != window_commits[-1]:
        raise ClaimEvidenceError("claim source commit must equal the newest window commit")
    if claim_ts <= window_times[-1]:
        raise ClaimEvidenceError("claim timestamp must postdate the newest window")

    claim_windows = claim["windows"]
    if not isinstance(claim_windows, list) or len(claim_windows) != len(normalized_refs):
        raise ClaimEvidenceError("claim windows must match the state window count")
    for index, (entry, expected_ref) in enumerate(zip(claim_windows, normalized_refs)):
        if not isinstance(entry, dict):
            raise ClaimEvidenceError(f"claim window {index} must be an object")
        _require_exact_keys(entry, CLAIM_WINDOW_KEYS, f"claim window {index}")
        if entry["path"] != expected_ref:
            raise ClaimEvidenceError(f"claim window {index} path mismatch")
        if not isinstance(entry["sha256"], str) or SHA256_RE.fullmatch(entry["sha256"]) is None:
            raise ClaimEvidenceError(f"claim window {index} hash must be lowercase SHA-256")
        if entry["sha256"] != _file_sha256(receipts_dir / expected_ref):
            raise ClaimEvidenceError(f"claim window {index} hash mismatch")
    return claim_ts
