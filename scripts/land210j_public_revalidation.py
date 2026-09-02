#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Revalidate land210j lineage and the owned synthetic R3 CPU proof."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

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


TICKET = "LAND210J-FAMILY3-STRAGGLERS"
LANDING_COMMIT = "70aefaa0a92fdebd376c068133749cc87760d074"
EXPECTED_SUBJECT_COMMIT = "33027681a36ed351478e13ab05418b0698a00e15"
EXPECTED_HISTORICAL_SHA256 = (
    "5ad3f57207f8e3016d8cbabc0a50612db511e92447124c7c88d68851852241bc"
)
EXPECTED_CURRENT_R3_SHA256 = (
    "86e50154acca419a91cc0c0c8d18d2d2773e2518362ac5a5b7abad1554d7cb1e"
)
EXPECTED_RECORDED_VERDICT = (
    "LAND210J_FAMILY3_STRAGGLERS_7_LANDED_0_EXCLUDED_"
    "2_PREEXISTING_DEFECT_CLASSES_DISCLOSED_6_RECEIPTS_BACKFILLED"
)
EXPECTED_PATHS = {
    "src/ember/governance/scripts/r3_feasibility_probe.py",
    "src/ember/governance/scripts/ember_cbase_avir_augment.py",
    "src/ember/governance/scripts/ember_cbase_launch.py",
    "src/ember/governance/scripts/ember_cbase_s6_acceptance.py",
    "src/ember/governance/scripts/test_ember_cbase_avir_augment.py",
    "src/ember/governance/scripts/test_ember_cbase_launch.py",
    "src/ember/governance/scripts/test_ember_cbase_s6_acceptance.py",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


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
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout


def git_blob(root: Path, commit: str, path: str) -> bytes:
    return _git(root, "show", f"{commit}:{path}")


def is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", ancestor, descendant],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def validate_historical(path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    if sha256_file(path) != EXPECTED_HISTORICAL_SHA256:
        raise ValueError("historical receipt SHA-256 mismatch")
    receipt = load_json(path)
    if receipt.get("ticket") != TICKET:
        raise ValueError("historical ticket mismatch")
    if receipt.get("issue") != "ember#210":
        raise ValueError("historical issue mismatch")
    if receipt.get("verdict") != EXPECTED_RECORDED_VERDICT:
        raise ValueError("historical verdict mismatch")
    if receipt.get("pass") is not True or receipt.get("api_spend_usd") != 0.0:
        raise ValueError("historical pass/spend boundary mismatch")
    if receipt.get("candidates_total") != 7 or receipt.get("excluded") != []:
        raise ValueError("historical candidate arithmetic mismatch")
    rows = receipt.get("files")
    if not isinstance(rows, list) or len(rows) != 7:
        raise ValueError("historical file population must contain seven rows")
    expected: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("historical file row must be an object")
        candidate = row.get("path")
        digest = row.get("landed_sha256")
        if candidate not in EXPECTED_PATHS:
            raise ValueError("historical candidate path is outside land210j")
        if not isinstance(digest, str) or SHA256_RE.fullmatch(digest) is None:
            raise ValueError("historical landed_sha256 is invalid")
        if candidate in expected:
            raise ValueError("historical candidate paths must be unique")
        expected[candidate] = digest
    if set(expected) != EXPECTED_PATHS:
        raise ValueError("historical candidate path population mismatch")
    return receipt, expected


def validate_public_lineage(
    root: Path, subject_commit: str, historical_digests: dict[str, str]
) -> list[dict[str, str]]:
    head = _git(root, "rev-parse", "HEAD").decode("ascii").strip()
    if subject_commit != EXPECTED_SUBJECT_COMMIT:
        raise ValueError("subject commit is not the reviewed public base")
    if not is_ancestor(root, subject_commit, head):
        raise ValueError("reviewed public base is not an ancestor of HEAD")
    if not is_ancestor(root, LANDING_COMMIT, subject_commit):
        raise ValueError("historical landing is not an ancestor of subject")
    rows = []
    for candidate in sorted(EXPECTED_PATHS):
        actual = sha256_bytes(git_blob(root, LANDING_COMMIT, candidate))
        if actual != historical_digests[candidate]:
            raise ValueError(f"landing blob mismatch for {candidate}")
        rows.append(
            {
                "path": candidate,
                "landing_sha256": actual,
                "current_sha256": sha256_file(root / candidate),
            }
        )
    return rows


def validate_current_sources(root: Path, historical_digests: dict[str, str]) -> dict[str, Any]:
    repaired = "src/ember/governance/scripts/r3_feasibility_probe.py"
    rows = []
    for candidate in sorted(EXPECTED_PATHS):
        path = root / candidate
        source = path.read_text(encoding="utf-8", errors="strict")
        compile(source, candidate, "exec")
        digest = sha256_file(path)
        if candidate == repaired:
            if digest != EXPECTED_CURRENT_R3_SHA256:
                raise ValueError("current R3 source SHA-256 mismatch")
            if "build_owned_synthetic_dryrun_model" not in source:
                raise ValueError("owned synthetic dry-run constructor is missing")
            if "Qwen/Qwen" in source or "DRYRUN_SUBSTITUTE_MODEL" in source:
                raise ValueError("borrowed dry-run checkpoint seam remains")
            disposition = "CURRENT_REPAIRED_OWNED_RANDOM_INIT"
        else:
            if digest != historical_digests[candidate]:
                raise ValueError(f"unexpected current byte drift for {candidate}")
            disposition = "UNCHANGED_FROM_LANDING"
        rows.append(
            {"path": candidate, "sha256": digest, "disposition": disposition}
        )
    return {
        "compiled_files": len(rows),
        "repaired_files": 1,
        "unchanged_files": 6,
        "rows": rows,
    }


def validate_dryrun_receipt(path: Path) -> dict[str, Any]:
    receipt = load_json(path)
    if receipt.get("ticket") != "R3-FEASIBILITY-PROBE":
        raise ValueError("dry-run ticket mismatch")
    if receipt.get("mode") != "dry_run":
        raise ValueError("dry-run mode mismatch")
    if receipt.get("model_id") != "ember-owned-synthetic-random-init-v1":
        raise ValueError("owned synthetic model id mismatch")
    source = receipt.get("model_source")
    if not isinstance(source, dict):
        raise ValueError("model_source must be an object")
    if source.get("source_kind") != "OWNED_RANDOM_INIT":
        raise ValueError("model_source is not owned random init")
    if source.get("external_checkpoint") is not None:
        raise ValueError("dry-run receipt references an external checkpoint")
    if source.get("external_model_id") is not None:
        raise ValueError("dry-run receipt references an external model id")
    if receipt.get("all_assertions_passed") is not True:
        raise ValueError("dry-run assertions did not all pass")
    if receipt.get("paid_api_surface_used") is not False:
        raise ValueError("paid API boundary mismatch")
    if receipt.get("leg1_base_loaded_4bit_frozen") is not False:
        raise ValueError("dry-run incorrectly claims a real 4-bit base")
    leg3 = receipt.get("leg3_training_step")
    leg4 = receipt.get("leg4_inference_pass")
    if not isinstance(leg3, dict) or leg3.get("grad_norm_nonzero_assert_passed") is not True:
        raise ValueError("one-step training proof is absent")
    if not isinstance(leg4, dict) or leg4.get("min_tokens_assert_passed") is not True:
        raise ValueError("inference proof is absent")
    return {
        "sha256": sha256_file(path),
        "model_source": source,
        "training_grad_norm": leg3.get("grad_norm"),
        "generated_tokens": leg4.get("n_new_tokens"),
        "all_assertions_passed": True,
    }


def build_receipt(
    root: Path,
    historical_path: Path,
    dryrun_path: Path,
    *,
    subject_commit: str,
    timestamp: str,
) -> dict[str, Any]:
    _, digests = validate_historical(historical_path)
    lineage = validate_public_lineage(root, subject_commit, digests)
    sources = validate_current_sources(root, digests)
    dryrun = validate_dryrun_receipt(dryrun_path)
    receipt = {
        "schema_version": "ember-land210j-public-revalidation/v1",
        "goal_id": "EMBER-02",
        "workstream_id": "EMBER-02A",
        "next_executed_outcome": (
            "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
        ),
        "ticket": TICKET,
        "generated_at": timestamp,
        "ts": timestamp,
        "sha_convention": "bytes on disk as-is (binary read, no normalization)",
        "subject_commit": subject_commit,
        "historical_receipt_sha256": EXPECTED_HISTORICAL_SHA256,
        "public_lineage": {
            "landing_commit": LANDING_COMMIT,
            "candidate_count": len(lineage),
            "rows": lineage,
        },
        "current_source_revalidation": sources,
        "owned_synthetic_cpu_replay": dryrun,
        "replay_command": (
            "CUDA_VISIBLE_DEVICES='' python -B src/ember/governance/scripts/r3_feasibility_probe.py "
            "--dry-run --max-new-tokens 64"
        ),
        "claim_boundary": {
            "historical_seven_file_landing_revalidated": True,
            "current_owned_synthetic_cpu_training_and_inference_replayed": True,
            "external_checkpoint_loaded": False,
            "borrowed_model_credit_claim": False,
            "gpu_used": False,
            "real_27b_feasibility_claim": False,
            "issue_47_completion_claim": False,
            "issue_210_whole_closure_claim": False,
            "issue_700_completion_claim": False,
        },
        "verdict": (
            "LAND210J_LINEAGE_REVALIDATED_AND_R3_DRYRUN_REPAIRED_TO_"
            "OWNED_RANDOM_INIT_CPU_PROOF"
        ),
    }
    return stamp(receipt, str(root))


def publish(receipt: dict[str, Any], output: Path, root: Path) -> None:
    allowed = (root / "receipts" / "ember-c-scale").resolve()
    target = output.resolve()
    if target.parent != allowed:
        raise ValueError("output must be under receipts/ember-c-scale")
    if target.exists():
        raise FileExistsError(f"refusing to overwrite {target}")
    raw = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(target, flags, 0o644)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--historical", type=Path, required=True)
    parser.add_argument("--dryrun-receipt", type=Path, required=True)
    parser.add_argument("--subject-commit", required=True)
    parser.add_argument("--timestamp", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = build_receipt(
        args.root.resolve(),
        args.historical.resolve(),
        args.dryrun_receipt.resolve(),
        subject_commit=args.subject_commit,
        timestamp=args.timestamp,
    )
    publish(receipt, args.output.resolve(), args.root.resolve())
    print(json.dumps({"status": "PASS", "output": args.output.name}, sort_keys=True))


if __name__ == "__main__":
    main()
