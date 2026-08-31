#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Revalidate land210h's public landing and current tokenizer truth boundary."""

from __future__ import annotations

import argparse
import ast
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
TICKET = "LAND210H-OPS-TOOLS"
LANDING_COMMIT = "ea39d6944155575145c6d17dbe87e8f0f8db153e"
TOKENIZER_REPAIR_COMMIT = "df272db32a106f774a1b30185e142f8e0de3ed2a"
EXPECTED_SUBJECT_COMMIT = "801cd32723734697eab58e19b7a22aef7b28f0a8"
EXPECTED_HISTORICAL_SHA256 = (
    "ab64850305d700af2ba86301bd5249d8a5fbc274ab881598095c773bd5473689"
)
EXPECTED_CURRENT_TOKENIZER_SHA256 = (
    "2c557e7ffe64706112ea947d056be503005d90b16f64c57ec354267c7e9e9c97"
)
EXPECTED_TOKENIZERS_VERSION = "0.22.2"
EXPECTED_RECORDED_VERDICT = (
    "LAND210H_OPS_TOOLS_5_LANDED_0_EXCLUDED_1_PREEXISTING_DEFECT_DISCLOSED"
)
EXECUTION_DENIAL = (
    "historical_only: the sub-3B cbase trainer and every importer are "
    "execution-denied"
)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

EXPECTED_LANDED_PATHS = {
    "src/ember/governance/scripts/convert_nf4_prequant.py",
    "src/ember/governance/scripts/ember_cbase_avir_data.py",
    "scripts/ember_cbase_avir_data_v2.py",
    "scripts/test_ember_cbase_avir_data.py",
    "scripts/test_ember_cbase_avir_data_v2.py",
}
IMPORT_CLOSURE_PATHS = (
    "src/ember/governance/scripts/ember_avir_tasks.py",
    "src/ember/governance/scripts/ember_avir_harness.py",
    "src/ember/governance/scripts/governor.py",
    "scripts/timeshare_pretrain.py",
)


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
    if historical.get("excluded") != []:
        raise ValueError("historical excluded population must be empty")

    files = historical.get("files")
    if not isinstance(files, list) or len(files) != 5:
        raise ValueError("historical landed-file population must contain five rows")
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
    if set(paths) != EXPECTED_LANDED_PATHS:
        raise ValueError("historical candidate path population mismatch")
    if historical.get("candidates_total") != len(paths):
        raise ValueError("historical candidate arithmetic mismatch")
    if modified_count != 1:
        raise ValueError("historical modified-from-stage count mismatch")
    return {
        "paths": paths,
        "candidate_count": len(paths),
        "modified_from_stage_count": modified_count,
        "byte_identical_to_stage_count": len(paths) - modified_count,
    }


def validate_landing_blobs(
    historical: dict[str, Any],
    oid_reader: Callable[[str, str], str],
    subject_blob_reader: Callable[[str, str], bytes],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for row in historical["files"]:
        path = row["path"]
        landing_oid = oid_reader(LANDING_COMMIT, path)
        subject_oid = oid_reader(EXPECTED_SUBJECT_COMMIT, path)
        if landing_oid != subject_oid:
            raise ValueError(f"landing tree/object mismatch for {path}")
        actual = sha256_bytes(subject_blob_reader(EXPECTED_SUBJECT_COMMIT, path))
        if actual != row["landed_sha256"]:
            raise ValueError(
                f"landing blob mismatch for {path}: "
                f"expected {row['landed_sha256']}, got {actual}"
            )
        rows.append(
            {
                "path": path,
                "blob_oid": subject_oid,
                "sha256": actual,
                "modified_from_stage": row["modified_from_stage"],
            }
        )
    return {"matches": len(rows), "rows": sorted(rows, key=lambda item: item["path"])}


def validate_current_tokenizer(raw: bytes) -> dict[str, Any]:
    digest = sha256_bytes(raw)
    if digest != EXPECTED_CURRENT_TOKENIZER_SHA256:
        raise ValueError(
            "current tokenizer SHA-256 mismatch: "
            f"expected {EXPECTED_CURRENT_TOKENIZER_SHA256}, got {digest}"
        )
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"current tokenizer is not strict UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("current tokenizer must contain one JSON object")

    import tokenizers
    from tokenizers import Tokenizer

    if tokenizers.__version__ != EXPECTED_TOKENIZERS_VERSION:
        raise ValueError(
            "tokenizers version mismatch: "
            f"expected {EXPECTED_TOKENIZERS_VERSION}, got {tokenizers.__version__}"
        )
    tokenizer = Tokenizer.from_str(json.dumps(value))
    vocab_size = tokenizer.get_vocab_size(with_added_tokens=True)
    if vocab_size != 32000:
        raise ValueError(f"current tokenizer vocab mismatch: {vocab_size}")
    return {
        "sha256": digest,
        "tokenizers_version": tokenizers.__version__,
        "vocab_size": vocab_size,
        "load_pass": True,
    }


def validate_execution_denial(source: bytes) -> dict[str, Any]:
    try:
        text = source.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError(f"historical trainer source is not UTF-8: {exc}") from exc
    if not text.startswith("# EMBER_ARTIFACT_CLASS=historical_only\n"):
        raise ValueError("historical trainer marker is missing")
    tree = ast.parse(text)
    statements = list(tree.body)
    if statements and isinstance(statements[0], ast.Expr):
        statements = statements[1:]
    if statements and isinstance(statements[0], ast.ImportFrom):
        if statements[0].module == "__future__":
            statements = statements[1:]
    if not statements or not isinstance(statements[0], ast.Raise):
        raise ValueError("historical trainer does not refuse before executable imports")
    refusal = statements[0]
    if (
        not isinstance(refusal.exc, ast.Call)
        or not isinstance(refusal.exc.func, ast.Name)
        or refusal.exc.func.id != "SystemExit"
        or len(refusal.exc.args) != 1
        or not isinstance(refusal.exc.args[0], ast.Constant)
        or refusal.exc.args[0].value != EXECUTION_DENIAL
    ):
        raise ValueError("historical trainer refusal contract mismatch")
    return {
        "path": "scripts/timeshare_pretrain.py",
        "sha256": sha256_bytes(source),
        "artifact_class": "historical_only",
        "denied": True,
        "reason": EXECUTION_DENIAL,
    }


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
    resolved = _git(root, "rev-parse", f"{subject_commit}^{{commit}}")
    if resolved.decode("ascii", errors="strict").strip() != subject_commit:
        raise ValueError("subject commit did not resolve exactly")
    for name, commit in {
        "ops_tools_pr_773_merge": LANDING_COMMIT,
        "tokenizer_repair": TOKENIZER_REPAIR_COMMIT,
    }.items():
        if not _is_ancestor(root, commit, subject_commit):
            raise ValueError(f"required lineage commit is not an ancestor: {name}")

    historical_rel = "receipts/ember-c-scale/land210h-ops-tools-receipt.json"
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

    closure_rows: list[dict[str, Any]] = []
    for path in IMPORT_CLOSURE_PATHS:
        landing_oid = git_blob_oid(root, LANDING_COMMIT, path)
        subject_oid = git_blob_oid(root, subject_commit, path)
        closure_rows.append(
            {
                "path": path,
                "landing_blob_oid": landing_oid,
                "subject_blob_oid": subject_oid,
            }
        )

    tokenizer_path = "domains/model/tokenizer/tokenizer.json"
    tokenizer_raw = git_blob(root, subject_commit, tokenizer_path)
    current_tokenizer = validate_current_tokenizer(tokenizer_raw)
    tokenizer_last_change = _last_change_commit(root, subject_commit, tokenizer_path)
    if tokenizer_last_change != TOKENIZER_REPAIR_COMMIT:
        raise ValueError("current tokenizer repair lineage mismatch")
    current_tokenizer.update(
        {
            "path": tokenizer_path,
            "blob_oid": git_blob_oid(root, subject_commit, tokenizer_path),
            "last_change_commit": tokenizer_last_change,
        }
    )

    execution_policy = validate_execution_denial(
        git_blob(root, subject_commit, "scripts/timeshare_pretrain.py")
    )
    return {
        "historical_candidate_count": structure["candidate_count"],
        "historical_modified_from_stage_count": structure[
            "modified_from_stage_count"
        ],
        "historical_byte_identical_to_stage_count": structure[
            "byte_identical_to_stage_count"
        ],
        "landing_commit": LANDING_COMMIT,
        "direct_landing_blob_matches": landing["matches"],
        "subject_commit": subject_commit,
        "subject_original_bytes_unchanged": landing["matches"],
        "landing_rows": landing["rows"],
        "landing_rows_sha256": _canonical_rows_digest(landing["rows"]),
        "import_closure_path_count": len(closure_rows),
        "import_closure_rows": closure_rows,
        "import_closure_rows_sha256": _canonical_rows_digest(closure_rows),
        "current_tokenizer": current_tokenizer,
        "historical_pipeline_execution_policy": execution_policy,
        "lineage_commits": {
            "ops_tools_pr_773_merge": LANDING_COMMIT,
            "tokenizer_repair": TOKENIZER_REPAIR_COMMIT,
        },
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
    allowed_parent = (root / "receipts" / "ember-c-scale").resolve()
    if historical_path.parent != allowed_parent:
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
        "mode": "PUBLIC_GIT_AND_CURRENT_TOKENIZER_REVALIDATION",
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
            "ops_tools_pr": "https://github.com/wordingone/ember/pull/773",
        },
        "producer": {
            "path": Path(__file__).resolve().relative_to(root).as_posix(),
            "sha256": sha256_file(Path(__file__).resolve()),
        },
        "verdict": (
            "HISTORICAL_5_LANDING_BYTES_VERIFIED_CURRENT_TOKENIZER_LOADS_"
            "HISTORICAL_PIPELINE_EXECUTION_DENIED"
        ),
        "claim_boundary": {
            "five_historical_landing_hashes_revalidated": True,
            "all_five_landing_git_objects_unchanged_at_subject": True,
            "historical_import_closure_paths_present": True,
            "current_tokenizer_load_replayed": True,
            "historical_tokenizer_failure_replayed": False,
            "historical_full_pipeline_replayed": False,
            "historical_test_counts_reasserted": False,
            "historical_stage_source_revalidated": False,
            "historical_default_path_host_equivalence_revalidated": False,
            "current_historical_execution_denial_revalidated": True,
            "preexisting_tokenizer_defect_currently_present": False,
            "issue_210_land210h_tracking_subset_revalidated": True,
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
