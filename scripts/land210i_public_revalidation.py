#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Revalidate land210i public lineage and its bounded CPU-only self-tests."""

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

# issue2015 exact-local-import:src/ember/governance/scripts/lib/invariant.py
import importlib.util as _ember_2560a87c017c05b0_importlib
import sys as _ember_2560a87c017c05b0_sys
from pathlib import Path as _ember_2560a87c017c05b0_Path
_ember_2560a87c017c05b0_path = _ember_2560a87c017c05b0_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'lib', 'invariant.py')
if not _ember_2560a87c017c05b0_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/lib/invariant.py')
_ember_2560a87c017c05b0_aliases = ('_ember_issue2015_2560a87c017c05b0', 'invariant', 'scripts.lib.invariant')
_ember_2560a87c017c05b0_existing = []
for _ember_2560a87c017c05b0_alias in _ember_2560a87c017c05b0_aliases:
    _ember_2560a87c017c05b0_candidate = _ember_2560a87c017c05b0_sys.modules.get(_ember_2560a87c017c05b0_alias)
    if _ember_2560a87c017c05b0_candidate is not None and all(_ember_2560a87c017c05b0_candidate is not item for item in _ember_2560a87c017c05b0_existing):
        _ember_2560a87c017c05b0_existing.append(_ember_2560a87c017c05b0_candidate)
if len(_ember_2560a87c017c05b0_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/lib/invariant.py')
if _ember_2560a87c017c05b0_existing:
    _ember_2560a87c017c05b0_module = _ember_2560a87c017c05b0_existing[0]
    _ember_2560a87c017c05b0_observed = getattr(_ember_2560a87c017c05b0_module, '__file__', None)
    if _ember_2560a87c017c05b0_observed is None or _ember_2560a87c017c05b0_Path(_ember_2560a87c017c05b0_observed).resolve() != _ember_2560a87c017c05b0_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/lib/invariant.py')
else:
    _ember_2560a87c017c05b0_spec = _ember_2560a87c017c05b0_importlib.spec_from_file_location('_ember_issue2015_2560a87c017c05b0', _ember_2560a87c017c05b0_path)
    if _ember_2560a87c017c05b0_spec is None or _ember_2560a87c017c05b0_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/lib/invariant.py')
    _ember_2560a87c017c05b0_module = _ember_2560a87c017c05b0_importlib.module_from_spec(_ember_2560a87c017c05b0_spec)
    for _ember_2560a87c017c05b0_alias in _ember_2560a87c017c05b0_aliases:
        _ember_2560a87c017c05b0_prior = _ember_2560a87c017c05b0_sys.modules.get(_ember_2560a87c017c05b0_alias)
        if _ember_2560a87c017c05b0_prior is not None and _ember_2560a87c017c05b0_prior is not _ember_2560a87c017c05b0_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/lib/invariant.py')
        _ember_2560a87c017c05b0_sys.modules[_ember_2560a87c017c05b0_alias] = _ember_2560a87c017c05b0_module
    try:
        _ember_2560a87c017c05b0_spec.loader.exec_module(_ember_2560a87c017c05b0_module)
    except BaseException:
        for _ember_2560a87c017c05b0_alias in _ember_2560a87c017c05b0_aliases:
            if _ember_2560a87c017c05b0_sys.modules.get(_ember_2560a87c017c05b0_alias) is _ember_2560a87c017c05b0_module:
                _ember_2560a87c017c05b0_sys.modules.pop(_ember_2560a87c017c05b0_alias, None)
        raise
for _ember_2560a87c017c05b0_alias in _ember_2560a87c017c05b0_aliases:
    _ember_2560a87c017c05b0_prior = _ember_2560a87c017c05b0_sys.modules.get(_ember_2560a87c017c05b0_alias)
    if _ember_2560a87c017c05b0_prior is not None and _ember_2560a87c017c05b0_prior is not _ember_2560a87c017c05b0_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/lib/invariant.py')
    _ember_2560a87c017c05b0_sys.modules[_ember_2560a87c017c05b0_alias] = _ember_2560a87c017c05b0_module
stamp = getattr(_ember_2560a87c017c05b0_module, 'stamp')
# issue2015 exact-local-import-end:src/ember/governance/scripts/lib/invariant.py


GOAL_ID = "EMBER-02"
WORKSTREAM_ID = "EMBER-02A"
NEXT_EXECUTED_OUTCOME = "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
TICKET = "LAND210I-HARNESS-ENTRY"
LANDING_COMMIT = "93b5b7260ddca9c0fa8344e93924d4ab16190895"
EXPECTED_SUBJECT_COMMIT = "090d92b72e131df65048e62553c253b694f13d00"
EXPECTED_HISTORICAL_SHA256 = (
    "43a5d4ac4749975187ae697a2161e066da82bcd229e7d244a4ab46c7f01fa553"
)
EXPECTED_CURRENT_HARNESS_SHA256 = (
    "838e4f67c338b70c8dc430563076c74b328a384f59448a19a5c1ad7cf99e01dd"
)
EXPECTED_RECORDED_VERDICT = (
    "LAND210I_HARNESS_ENTRY_4_SCRIPTS_2_DATA_LANDED_0_EXCLUDED"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

EXPECTED_SCRIPT_PATHS = {
    "src/ember/governance/scripts/ember_avir_cli_launch_entry.py",
    "src/ember/governance/scripts/ember_avir_harness.py",
    "src/ember/governance/scripts/ember_avir_observe.py",
    "src/ember/governance/scripts/ember_avir_tasks.py",
}
EXPECTED_COMPANION_PATHS = {
    "data/ember_avir_tasks/train.jsonl",
    "data/ember_avir_tasks/heldout.jsonl",
}
EXPECTED_ALL_PATHS = EXPECTED_SCRIPT_PATHS | EXPECTED_COMPANION_PATHS


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


def _validate_sha(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be lowercase SHA-256")
    return value


def _validate_path(value: Any) -> str:
    if not isinstance(value, str) or value not in EXPECTED_ALL_PATHS:
        raise ValueError("candidate path is outside the exact land210i population")
    if "\\" in value or ".." in Path(value).parts or Path(value).is_absolute():
        raise ValueError("candidate path is not confined")
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
    if historical.get("excluded") != []:
        raise ValueError("historical excluded population must be empty")

    files = historical.get("files")
    if not isinstance(files, list) or len(files) != 6:
        raise ValueError("historical file population must contain six rows")
    paths: list[str] = []
    modified_count = 0
    for row in files:
        if not isinstance(row, dict):
            raise ValueError("historical file row must be an object")
        path = _validate_path(row.get("path"))
        stage_sha = _validate_sha(row.get("stage_sha256"), field="stage_sha256")
        landed_sha = _validate_sha(row.get("landed_sha256"), field="landed_sha256")
        modified = row.get("modified_from_stage")
        if not isinstance(modified, bool):
            raise ValueError("modified_from_stage must be boolean")
        if modified != (stage_sha != landed_sha):
            raise ValueError("stage/landing modification classification mismatch")
        modified_count += int(modified)
        paths.append(path)

    if len(set(paths)) != len(paths):
        raise ValueError("candidate paths must be unique")
    if set(paths) != EXPECTED_ALL_PATHS:
        raise ValueError("historical candidate path population mismatch")
    if historical.get("candidates_total") != len(EXPECTED_SCRIPT_PATHS):
        raise ValueError("historical candidate arithmetic mismatch")
    companion = historical.get("companion_data_included")
    if not isinstance(companion, dict) or set(companion.get("files", [])) != (
        EXPECTED_COMPANION_PATHS
    ):
        raise ValueError("historical companion data population mismatch")
    if modified_count != 2:
        raise ValueError("historical modified-from-stage count mismatch")
    return {
        "paths": paths,
        "file_count": len(paths),
        "script_count": len(EXPECTED_SCRIPT_PATHS),
        "companion_count": len(EXPECTED_COMPANION_PATHS),
        "modified_from_stage_count": modified_count,
    }


def validate_landing_blobs(
    historical: dict[str, Any],
    oid_reader: Callable[[str, str], str],
    blob_reader: Callable[[str, str], bytes],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for row in historical["files"]:
        path = row["path"]
        landing_oid = oid_reader(LANDING_COMMIT, path)
        subject_oid = oid_reader(EXPECTED_SUBJECT_COMMIT, path)
        if landing_oid != subject_oid:
            raise ValueError(f"landing tree/object mismatch for {path}")
        actual = sha256_bytes(blob_reader(EXPECTED_SUBJECT_COMMIT, path))
        if actual != row["landed_sha256"]:
            raise ValueError(f"landing blob mismatch for {path}")
        rows.append(
            {
                "path": path,
                "blob_oid": subject_oid,
                "sha256": actual,
                "modified_from_stage": row["modified_from_stage"],
            }
        )
    return {"matches": len(rows), "rows": sorted(rows, key=lambda item: item["path"])}


def validate_current_harness(path: Path) -> dict[str, Any]:
    digest = sha256_file(path)
    if digest != EXPECTED_CURRENT_HARNESS_SHA256:
        raise ValueError(
            "current harness SHA-256 mismatch: "
            f"expected {EXPECTED_CURRENT_HARNESS_SHA256}, got {digest}"
        )
    source = path.read_text(encoding="utf-8", errors="strict")
    compile(source, "src/ember/governance/scripts/ember_avir_harness.py", "exec")
    if "with patch.object(Path, \"home\"" not in source:
        raise ValueError("current harness does not exercise the real home-resolution seam")
    return {
        "path": "src/ember/governance/scripts/ember_avir_harness.py",
        "sha256": digest,
        "session_selection_regression_repaired": True,
    }


def validate_current_files(root: Path, historical: dict[str, Any]) -> dict[str, Any]:
    expected = {row["path"]: row["landed_sha256"] for row in historical["files"]}
    rows: list[dict[str, Any]] = []
    unchanged = 0
    repaired = 0
    for path in sorted(EXPECTED_ALL_PATHS):
        current = sha256_file(root / path)
        if path == "src/ember/governance/scripts/ember_avir_harness.py":
            validate_current_harness(root / path)
            if current == expected[path]:
                raise ValueError("current harness repair is not distinguishable from landing")
            disposition = "CURRENT_REPAIRED"
            repaired += 1
        else:
            if current != expected[path]:
                raise ValueError(f"unexpected current byte drift for {path}")
            disposition = "UNCHANGED_FROM_LANDING"
            unchanged += 1
        rows.append(
            {
                "path": path,
                "sha256": current,
                "historical_landed_sha256": expected[path],
                "disposition": disposition,
            }
        )
    return {
        "unchanged_landing_files": unchanged,
        "repaired_files": repaired,
        "rows": rows,
        "rows_sha256": sha256_bytes(
            json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ),
    }


def _run_cpu(root: Path, argv: list[str], expected: list[str]) -> str:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-B", *argv],
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise ValueError(f"CPU replay failed for {' '.join(argv)}: {result.stdout}")
    for marker in expected:
        if marker not in result.stdout:
            raise ValueError(f"CPU replay marker absent for {' '.join(argv)}: {marker}")
    return sha256_bytes(result.stdout.encode("utf-8"))


def validate_cpu_replay(root: Path) -> dict[str, Any]:
    for path in sorted(EXPECTED_SCRIPT_PATHS):
        source = (root / path).read_text(encoding="utf-8", errors="strict")
        compile(source, path, "exec")
    commands = [
        (
            ["src/ember/governance/scripts/ember_avir_cli_launch_entry.py", "--help"],
            ["usage: ember_avir_cli_launch_entry.py"],
        ),
        (
            ["src/ember/governance/scripts/ember_avir_observe.py", "--help"],
            ["usage: ember_avir_observe.py"],
        ),
        (
            ["src/ember/governance/scripts/ember_avir_harness.py", "--selftest"],
            [
                "T15/find_session_jsonl/session_id pinning",
                "T15/find_session_jsonl/mtime fallback",
                "Result: 38/38 passed",
                "ALL PASS",
            ],
        ),
        (
            ["src/ember/governance/scripts/ember_avir_tasks.py", "--test"],
            [
                "load_split('train'): 24 tasks",
                "load_split('heldout'): 20 tasks",
                "positive selftest: 44 tasks return R=1",
                "ALL PASS",
            ],
        ),
    ]
    rows: list[dict[str, Any]] = []
    for argv, expected in commands:
        rows.append(
            {
                "argv": ["python", "-B", *argv],
                "stdout_sha256": _run_cpu(root, argv, expected),
                "status": "PASS",
            }
        )
    return {
        "compile_count": 4,
        "command_count": 4,
        "harness_selftest": "38/38 PASS",
        "tasks_train": 24,
        "tasks_heldout": 20,
        "tasks_total": 44,
        "external_executable_invoked": False,
        "gpu_used": False,
        "all_pass": True,
        "commands": rows,
    }


def validate_public_lineage(
    root: Path,
    historical: dict[str, Any],
    *,
    subject_commit: str,
) -> dict[str, Any]:
    if subject_commit != EXPECTED_SUBJECT_COMMIT:
        raise ValueError("subject commit is not the reviewed public base")
    resolved = _git(root, "rev-parse", f"{subject_commit}^{{commit}}")
    if resolved.decode("ascii", errors="strict").strip() != subject_commit:
        raise ValueError("subject commit did not resolve exactly")
    if not _is_ancestor(root, LANDING_COMMIT, subject_commit):
        raise ValueError("land210i landing commit is not an ancestor")
    historical_rel = "receipts/ember-c-scale/land210i-harness-entry-receipt.json"
    if sha256_bytes(git_blob(root, subject_commit, historical_rel)) != (
        EXPECTED_HISTORICAL_SHA256
    ):
        raise ValueError("subject historical receipt bytes do not match")
    structure = validate_historical_structure(historical)
    landing = validate_landing_blobs(
        historical,
        lambda commit, path: git_blob_oid(root, commit, path),
        lambda commit, path: git_blob(root, commit, path),
    )
    current = validate_current_files(root, historical)
    return {
        "historical_candidate_count": structure["file_count"],
        "historical_script_count": structure["script_count"],
        "historical_companion_count": structure["companion_count"],
        "historical_modified_from_stage_count": structure[
            "modified_from_stage_count"
        ],
        "landing_commit": LANDING_COMMIT,
        "subject_commit": subject_commit,
        "subject_landing_blob_matches": landing["matches"],
        "subject_landing_rows": landing["rows"],
        "current_unchanged_landing_files": current["unchanged_landing_files"],
        "current_repaired_files": current["repaired_files"],
        "current_rows": current["rows"],
        "current_rows_sha256": current["rows_sha256"],
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
        raise ValueError("historical receipt SHA-256 mismatch")
    if historical_path.parent != (root / "receipts" / "ember-c-scale").resolve():
        raise ValueError("historical receipt must be under receipts/ember-c-scale")
    historical = load_json(historical_path)
    lineage = validate_public_lineage(root, historical, subject_commit=subject_commit)
    replay = validate_cpu_replay(root)
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
        "mode": "PUBLIC_GIT_AND_CPU_ONLY_SELFTEST_REVALIDATION",
        "sha_convention": "bytes on disk as-is (binary read, no normalization)",
        "supersedes": historical_path.relative_to(root).as_posix(),
        "historical_receipt_sha256": digest,
        "public_lineage_revalidation": lineage,
        "current_cpu_replay": replay,
        "public_evidence": {
            "harness_entry_pr": "https://github.com/wordingone/ember/pull/771",
            "tracking_issue": "https://github.com/wordingone/ember/issues/210",
        },
        "producer": {
            "path": Path(__file__).resolve().relative_to(root).as_posix(),
            "sha256": sha256_file(Path(__file__).resolve()),
        },
        "verdict": (
            "HISTORICAL_6_FILE_LANDING_VERIFIED_CURRENT_CPU_SELFTESTS_PASS_"
            "SESSION_SELECTION_REGRESSION_REPAIRED"
        ),
        "claim_boundary": {
            "historical_six_file_landing_revalidated": True,
            "current_cpu_only_selftests_replayed": True,
            "current_session_selection_test_repaired": True,
            "external_executable_invoked": False,
            "external_subscription_or_api_used": False,
            "historical_private_stage_source_revalidated": False,
            "historical_external_executable_behavior_replayed": False,
            "borrowed_model_credit_claim": False,
            "owned_model_credit_claim": False,
            "issue_210_land210i_tracking_subset_revalidated": True,
            "issue_210_whole_closure_revalidated": False,
            "tier_3_private_archive_revalidated": False,
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
    parser.add_argument("--subject-commit", default=EXPECTED_SUBJECT_COMMIT)
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
