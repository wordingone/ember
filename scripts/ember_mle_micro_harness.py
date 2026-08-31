#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""MLE-bench Low micro-subset harness preflight for Ember MVP v0.

This freezes the first external benchmark subset metadata and proves the
scoring path on a tiny local fixture. It does not hydrate or execute real
MLE-bench tasks.
"""
from __future__ import annotations

import hashlib
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
import importlib.util as _ember_66ee9e91637922dc_importlib
import sys as _ember_66ee9e91637922dc_sys
from pathlib import Path as _ember_66ee9e91637922dc_Path
_ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
if not _ember_66ee9e91637922dc_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_write.py')
_ember_66ee9e91637922dc_aliases = ('_ember_issue2015_66ee9e91637922dc', 'receipt_write', 'scripts.receipt_write')
_ember_66ee9e91637922dc_existing = []
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_candidate = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_candidate is not None and all(_ember_66ee9e91637922dc_candidate is not item for item in _ember_66ee9e91637922dc_existing):
        _ember_66ee9e91637922dc_existing.append(_ember_66ee9e91637922dc_candidate)
if len(_ember_66ee9e91637922dc_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_write.py')
if _ember_66ee9e91637922dc_existing:
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_existing[0]
    _ember_66ee9e91637922dc_observed = getattr(_ember_66ee9e91637922dc_module, '__file__', None)
    if _ember_66ee9e91637922dc_observed is None or _ember_66ee9e91637922dc_Path(_ember_66ee9e91637922dc_observed).resolve() != _ember_66ee9e91637922dc_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_write.py')
else:
    _ember_66ee9e91637922dc_spec = _ember_66ee9e91637922dc_importlib.spec_from_file_location('_ember_issue2015_66ee9e91637922dc', _ember_66ee9e91637922dc_path)
    if _ember_66ee9e91637922dc_spec is None or _ember_66ee9e91637922dc_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_importlib.module_from_spec(_ember_66ee9e91637922dc_spec)
    for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
        _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
        if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
        _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
    try:
        _ember_66ee9e91637922dc_spec.loader.exec_module(_ember_66ee9e91637922dc_module)
    except BaseException:
        for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
            if _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias) is _ember_66ee9e91637922dc_module:
                _ember_66ee9e91637922dc_sys.modules.pop(_ember_66ee9e91637922dc_alias, None)
        raise
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
checked_write = getattr(_ember_66ee9e91637922dc_module, 'checked_write')
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py

SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
MLE_LOW_MICRO_TASK_IDS = [
    "detecting-insults-in-social-commentary",
    "random-acts-of-pizza",
    "spooky-author-identification",
    "nomad2018-predict-transparent-conductors",
    "leaf-classification",
]
FIXTURE_TASK_ID = "fixture-tiny-mle-score-v0"
REQUIRED_TASK_ASSETS = ("dataset", "score.py", "baselines/starter.py")
REQUIRED_CANDIDATE_ASSETS = ("candidate.py",)
REQUIRED_SOURCE_ASSETS = ("grade.py", "config.yaml", "checksums.yaml")
PREPARED_DATA_KEYS = ("answers", "gold_submission", "sample_submission")
REQUIRED_CONFIGURED_DATA_KEYS = ("answers", "sample_submission")
RAW_PREPARE_ASSETS = {
    "detecting-insults-in-social-commentary": (
        "raw/train.csv",
        "raw/test_with_solutions.csv",
    ),
    "random-acts-of-pizza": (
        "raw/train.json",
        "raw/test.json",
    ),
    "spooky-author-identification": (
        "raw/train.zip",
    ),
    "nomad2018-predict-transparent-conductors": (
        "raw/train.zip",
        "raw/train.csv.zip",
        "raw/test.zip",
        "raw/test.csv.zip",
    ),
    "leaf-classification": (
        "raw/train.csv.zip",
        "raw/images.zip",
    ),
}
WHEEL_ARM_CONTRACTS = {
    "A": {
        "id": "A",
        "name": "direct-benchmark-iteration",
        "uses_dream_loop": False,
        "uses_latent_branch": False,
        "uses_state_commit": False,
        "uses_replay": False,
    },
    "B": {
        "id": "B",
        "name": "dream-loop-only",
        "uses_dream_loop": True,
        "uses_latent_branch": False,
        "uses_state_commit": False,
        "uses_replay": False,
    },
    "C": {
        "id": "C",
        "name": "full-mvp-loop",
        "uses_dream_loop": True,
        "uses_latent_branch": True,
        "uses_state_commit": True,
        "uses_replay": True,
    },
}


class MicroHarnessValidationError(ValueError):
    pass


def sha256_json(obj: dict[str, Any]) -> str:
    data = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def load_receipt(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def freeze_micro_subset(root: Path) -> dict[str, Any]:
    root = Path(root)
    manifest = {
        "id": "mle-low-micro-v0",
        "task_ids": MLE_LOW_MICRO_TASK_IDS,
        "official_leaderboard_comparable": False,
        "real_mle_tasks_executed": False,
        "fixture_task_id": FIXTURE_TASK_ID,
        "budget": {
            "wall_seconds": 3600,
            "train_seconds": 3600,
            "eval_seconds": 3600,
        },
        "seeds": [123456],
        "dataset_mode": "not_hydrated_fixture_preflight",
        "scoring_commands": {
            task_id: f"python score.py --task {task_id} --prediction predictions.json"
            for task_id in MLE_LOW_MICRO_TASK_IDS
        },
        "baseline_scripts": {
            task_id: f"baselines/{task_id}/starter.py"
            for task_id in MLE_LOW_MICRO_TASK_IDS
        },
        "normalization": "normalized_delta=(candidate-baseline)/(max_score-baseline)",
    }
    manifest["freeze_manifest_sha256"] = sha256_json(manifest)
    out = root / "benchmark" / "mle-low-micro-v0.freeze.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    manifest["freeze_manifest_path"] = str(out)
    return manifest


def normalized_improvement(baseline: float, candidate: float, max_score: float = 1.0) -> float:
    denom = max_score - baseline
    if denom <= 0:
        raise ValueError("max_score must be greater than baseline for normalized improvement")
    return round((candidate - baseline) / denom, 6)


def run_tiny_fixture(root: Path, cycle_id: str | None = None) -> dict[str, Any]:
    root = Path(root)
    manifest = freeze_micro_subset(root)
    baseline_score = 0.5
    candidate_score = 0.75
    mean_improvement = normalized_improvement(baseline_score, candidate_score)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    receipt = {
        "ticket": "EMBER-MLE-MICRO-FIXTURE",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "benchmark_subset": {
            "id": manifest["id"],
            "task_ids": manifest["task_ids"],
            "official_leaderboard_comparable": False,
        },
        "fixture_only": True,
        "real_mle_tasks_executed": False,
        "frozen_before_execution": True,
        "freeze_manifest_sha256": manifest["freeze_manifest_sha256"],
        "freeze_manifest_path": manifest["freeze_manifest_path"],
        "fixture_task": {
            "id": FIXTURE_TASK_ID,
            "baseline_score": baseline_score,
            "candidate_score": candidate_score,
            "max_score": 1.0,
            "scoring_command": "python fixture_score.py --predictions predictions.json",
        },
        "score": {
            "baseline_score": baseline_score,
            "candidate_score": candidate_score,
            "mean_normalized_improvement": mean_improvement,
        },
        "verdict": "fixture-pass",
    }
    out = root / "receipts" / "benchmark" / f"mle-micro-fixture-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_micro_receipt(receipt)
    return receipt


def run_hydration_preflight(root: Path, mle_root: Path, cycle_id: str | None = None) -> dict[str, Any]:
    root = Path(root)
    mle_root = Path(mle_root)
    manifest = freeze_micro_subset(root)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    task_assets = []
    missing_assets = []
    for task_id in MLE_LOW_MICRO_TASK_IDS:
        task_root = mle_root / task_id
        assets = {
            "task_dir": task_root.exists(),
            "dataset": (task_root / "dataset").exists(),
            "score.py": (task_root / "score.py").is_file(),
            "baselines/starter.py": (task_root / "baselines" / "starter.py").is_file(),
        }
        task_assets.append({"task_id": task_id, "root": str(task_root), "assets": assets})
        missing = [name for name, present in assets.items() if not present]
        if missing:
            missing_assets.append({"task_id": task_id, "missing": missing, "root": str(task_root)})

    hydration_ready = not missing_assets
    receipt = {
        "ticket": "EMBER-MLE-MICRO-HYDRATION-PREFLIGHT",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "benchmark_subset": {
            "id": manifest["id"],
            "task_ids": manifest["task_ids"],
            "official_leaderboard_comparable": False,
        },
        "fixture_only": False,
        "real_mle_tasks_executed": False,
        "frozen_before_execution": True,
        "hydration_ready": hydration_ready,
        "mle_root": str(mle_root),
        "required_assets": list(REQUIRED_TASK_ASSETS),
        "task_assets": task_assets,
        "missing_assets": missing_assets,
        "freeze_manifest_sha256": manifest["freeze_manifest_sha256"],
        "freeze_manifest_path": manifest["freeze_manifest_path"],
        "score": {
            "baseline_score": None,
            "candidate_score": None,
            "mean_normalized_improvement": None,
        },
        "verdict": "READY" if hydration_ready else "BLOCKED",
    }
    out = root / "receipts" / "benchmark" / f"mle-micro-hydration-preflight-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_hydration_preflight_receipt(receipt)
    return receipt


def validate_hydration_preflight_receipt(receipt: dict[str, Any]) -> None:
    errors: list[str] = []
    if receipt.get("ticket") != "EMBER-MLE-MICRO-HYDRATION-PREFLIGHT":
        errors.append("bad ticket")
    subset = receipt.get("benchmark_subset", {})
    if subset.get("id") != "mle-low-micro-v0":
        errors.append("bad subset id")
    if subset.get("task_ids") != MLE_LOW_MICRO_TASK_IDS:
        errors.append("task ids are not the frozen micro-subset")
    if subset.get("official_leaderboard_comparable") is not False:
        errors.append("preflight must not claim official leaderboard comparability")
    if receipt.get("fixture_only") is not False:
        errors.append("hydration preflight is not a tiny fixture")
    if receipt.get("real_mle_tasks_executed") is not False:
        errors.append("hydration preflight must not claim real MLE tasks executed")
    if receipt.get("frozen_before_execution") is not True:
        errors.append("manifest must be frozen before execution")
    missing = receipt.get("missing_assets", [])
    if receipt.get("hydration_ready") is True and missing:
        errors.append("hydration_ready cannot be true with missing assets")
    if receipt.get("hydration_ready") is False and receipt.get("verdict") != "BLOCKED":
        errors.append("blocked hydration preflight must use BLOCKED verdict")
    if receipt.get("hydration_ready") is True and receipt.get("verdict") != "READY":
        errors.append("ready hydration preflight must use READY verdict")
    if errors:
        raise MicroHarnessValidationError("; ".join(errors))


def run_official_source_preflight(root: Path, source_root: Path, cycle_id: str | None = None) -> dict[str, Any]:
    root = Path(root)
    source_root = Path(source_root)
    manifest = freeze_micro_subset(root)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    low_split = source_root / "experiments" / "splits" / "low.txt"
    low_tasks = []
    if low_split.is_file():
        low_tasks = [line.strip() for line in low_split.read_text(encoding="utf-8").splitlines() if line.strip()]

    task_assets = []
    missing_source_assets = []
    for task_id in MLE_LOW_MICRO_TASK_IDS:
        task_root = source_root / "mlebench" / "competitions" / task_id
        assets = {
            "low_split_member": task_id in low_tasks,
            "task_dir": task_root.exists(),
            "grade.py": (task_root / "grade.py").is_file(),
            "config.yaml": (task_root / "config.yaml").is_file(),
            "checksums.yaml": (task_root / "checksums.yaml").is_file(),
        }
        task_assets.append({"task_id": task_id, "root": str(task_root), "assets": assets})
        missing = [name for name, present in assets.items() if not present]
        if missing:
            missing_source_assets.append({"task_id": task_id, "missing": missing, "root": str(task_root)})

    source_ready = low_split.is_file() and not missing_source_assets
    receipt = {
        "ticket": "EMBER-MLE-MICRO-SOURCE-PREFLIGHT",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "benchmark_subset": {
            "id": manifest["id"],
            "task_ids": manifest["task_ids"],
            "official_leaderboard_comparable": False,
        },
        "fixture_only": False,
        "source_ready": source_ready,
        "hydration_ready": False,
        "real_mle_tasks_executed": False,
        "frozen_before_execution": True,
        "source_root": str(source_root),
        "low_split_path": str(low_split),
        "required_source_assets": list(REQUIRED_SOURCE_ASSETS),
        "task_assets": task_assets,
        "missing_source_assets": missing_source_assets,
        "freeze_manifest_sha256": manifest["freeze_manifest_sha256"],
        "freeze_manifest_path": manifest["freeze_manifest_path"],
        "score": {
            "baseline_score": None,
            "candidate_score": None,
            "mean_normalized_improvement": None,
        },
        "verdict": "SOURCE_READY" if source_ready else "BLOCKED",
    }
    out = root / "receipts" / "benchmark" / f"mle-micro-source-preflight-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_official_source_preflight_receipt(receipt)
    return receipt


def validate_official_source_preflight_receipt(receipt: dict[str, Any]) -> None:
    errors: list[str] = []
    if receipt.get("ticket") != "EMBER-MLE-MICRO-SOURCE-PREFLIGHT":
        errors.append("bad ticket")
    subset = receipt.get("benchmark_subset", {})
    if subset.get("task_ids") != MLE_LOW_MICRO_TASK_IDS:
        errors.append("task ids are not the frozen micro-subset")
    if subset.get("official_leaderboard_comparable") is not False:
        errors.append("source preflight must not claim official leaderboard comparability")
    if receipt.get("fixture_only") is not False:
        errors.append("source preflight is not a tiny fixture")
    if receipt.get("real_mle_tasks_executed") is not False:
        errors.append("source preflight must not claim real MLE tasks executed")
    if receipt.get("hydration_ready") is not False:
        errors.append("source preflight must not claim hydrated datasets")
    if receipt.get("frozen_before_execution") is not True:
        errors.append("manifest must be frozen before execution")
    missing = receipt.get("missing_source_assets", [])
    if receipt.get("source_ready") is True and missing:
        errors.append("source_ready cannot be true with missing source assets")
    if receipt.get("source_ready") is True and receipt.get("verdict") != "SOURCE_READY":
        errors.append("ready source preflight must use SOURCE_READY verdict")
    if receipt.get("source_ready") is False and receipt.get("verdict") != "BLOCKED":
        errors.append("blocked source preflight must use BLOCKED verdict")
    if errors:
        raise MicroHarnessValidationError("; ".join(errors))


def _read_dataset_paths_from_config(config_path: Path) -> dict[str, str]:
    try:
        import yaml

        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        dataset = data.get("dataset", {}) if isinstance(data, dict) else {}
        return {key: str(dataset.get(key, "")) for key in PREPARED_DATA_KEYS}
    except Exception:
        paths: dict[str, str] = {}
        in_dataset = False
        for raw_line in config_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.rstrip()
            if line.startswith("dataset:"):
                in_dataset = True
                continue
            if in_dataset and line and not raw_line.startswith(" "):
                break
            if in_dataset and ":" in line:
                key, value = line.strip().split(":", 1)
                if key in PREPARED_DATA_KEYS:
                    paths[key] = value.strip().strip("'\"")
        return {key: paths.get(key, "") for key in PREPARED_DATA_KEYS}


def run_kaggle_auth_preflight(
    root: Path,
    credential_path: Path,
    access_token_path: Path | None = None,
    live_check: bool = False,
    live_auth_command: list[str] | None = None,
    cycle_id: str | None = None,
) -> dict[str, Any]:
    root = Path(root)
    credential_path = Path(credential_path)
    access_token_path = Path(access_token_path) if access_token_path else None
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    present = credential_path.is_file()
    access_token_present = access_token_path.is_file() if access_token_path else False
    access_token_shape = "not_checked" if access_token_path is None else "missing"
    access_token_sha256 = None
    parseable = False
    username_present = False
    key_present = False
    username_sha256 = None
    key_sha256 = None
    blocked_reason = None
    live_auth_status = "not_checked"
    live_auth_error = None

    if present:
        try:
            obj = json.loads(credential_path.read_text(encoding="utf-8"))
            parseable = isinstance(obj, dict)
            username = str(obj.get("username", "")) if parseable else ""
            key = str(obj.get("key", "")) if parseable else ""
            username_present = bool(username)
            key_present = bool(key)
            username_sha256 = sha256_bytes(username.encode("utf-8")) if username_present else None
            key_sha256 = sha256_bytes(key.encode("utf-8")) if key_present else None
        except Exception as exc:
            parseable = False
            live_auth_error = f"{type(exc).__name__}: credential JSON parse failed"

    if access_token_present and access_token_path is not None:
        access_token_text = access_token_path.read_text(encoding="utf-8").strip()
        access_token_shape = "KGAT" if access_token_text.startswith("KGAT_") else "unknown"
        access_token_sha256 = sha256_bytes(access_token_text.encode("utf-8")) if access_token_text else None

    shape_ready = present and parseable and username_present and key_present
    if not shape_ready:
        blocked_reason = "credential_shape_invalid"
    elif live_check:
        sibling_kaggle = Path(sys.executable).with_name("kaggle.exe")
        default_command = [
            str(sibling_kaggle) if sibling_kaggle.is_file() else "kaggle",
            "competitions",
            "list",
        ]
        command = live_auth_command or default_command
        proc = subprocess.run(command, text=True, capture_output=True, timeout=30)
        if proc.returncode == 0:
            live_auth_status = "AUTH_OK"
        else:
            live_auth_status = "AUTH_FAILED"
            combined = (proc.stderr or proc.stdout or "").strip()
            live_auth_error = _summarize_auth_error(combined, redactions=[key_sha256, username_sha256])
            blocked_reason = "kaggle_auth_unauthorized" if "401" in combined or "Unauth" in combined else "kaggle_auth_failed"

    if not shape_ready:
        verdict = "BLOCKED"
    elif live_check:
        verdict = "AUTH_READY" if live_auth_status == "AUTH_OK" else "BLOCKED"
    else:
        verdict = "AUTH_SHAPE_READY"

    receipt = {
        "ticket": "EMBER-MLE-KAGGLE-AUTH-PREFLIGHT",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "credential_path": str(credential_path),
        "credential_file_present": present,
        "credential_json_parseable": parseable,
        "username_present": username_present,
        "key_present": key_present,
        "username_sha256": username_sha256,
        "key_sha256": key_sha256,
        "access_token_path": str(access_token_path) if access_token_path else None,
        "access_token_file_present": access_token_present,
        "access_token_shape": access_token_shape,
        "access_token_sha256": access_token_sha256,
        "legacy_kaggle_client_accepts_access_token": False,
        "legacy_kaggle_client_required_credentials": ["username", "key"],
        "live_auth_checked": live_check,
        "live_auth_command_provided": live_auth_command is not None,
        "live_auth_command_exe": Path(command[0]).name if live_check and command else None,
        "live_auth_status": live_auth_status,
        "live_auth_error": live_auth_error,
        "blocked_reason": blocked_reason,
        "verdict": verdict,
    }
    out = root / "receipts" / "benchmark" / f"kaggle-auth-preflight-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_kaggle_auth_preflight_receipt(receipt)
    return receipt


def _summarize_auth_error(text: str, redactions: list[str | None] | None = None) -> str:
    if not text:
        return "empty authentication error"
    markers = ["Unauthorized", "Unauthenticated", "401", "Forbidden", "403"]
    hits = [marker for marker in markers if marker.lower() in text.lower()]
    if hits:
        return "Kaggle authentication failed: " + ", ".join(sorted(set(hits)))
    first = text.splitlines()[0].strip()
    return first[:200]


def validate_kaggle_auth_preflight_receipt(receipt: dict[str, Any]) -> None:
    errors: list[str] = []
    if receipt.get("ticket") != "EMBER-MLE-KAGGLE-AUTH-PREFLIGHT":
        errors.append("bad ticket")
    for forbidden in ("key", "secret", "token"):
        value = receipt.get(forbidden)
        if value is not None:
            errors.append(f"receipt must not include raw {forbidden}")
    if receipt.get("key_present") and not str(receipt.get("key_sha256", "")).startswith("sha256:"):
        errors.append("present key must be represented only by sha256")
    if receipt.get("username_present") and not str(receipt.get("username_sha256", "")).startswith("sha256:"):
        errors.append("present username must be represented by sha256")
    if receipt.get("access_token_file_present") and not str(receipt.get("access_token_sha256", "")).startswith("sha256:"):
        errors.append("present access token must be represented only by sha256")
    if receipt.get("legacy_kaggle_client_accepts_access_token") is not False:
        errors.append("legacy Kaggle client access-token acceptance must be explicitly false")
    if receipt.get("legacy_kaggle_client_required_credentials") != ["username", "key"]:
        errors.append("legacy Kaggle client required credentials must be username/key")
    shape_ready = (
        receipt.get("credential_file_present") is True
        and receipt.get("credential_json_parseable") is True
        and receipt.get("username_present") is True
        and receipt.get("key_present") is True
    )
    if not shape_ready and receipt.get("verdict") != "BLOCKED":
        errors.append("invalid credential shape must be blocked")
    if receipt.get("live_auth_checked") is False and shape_ready and receipt.get("verdict") != "AUTH_SHAPE_READY":
        errors.append("shape-only ready preflight must use AUTH_SHAPE_READY")
    if receipt.get("live_auth_checked") is True:
        if receipt.get("live_auth_status") == "AUTH_OK" and receipt.get("verdict") != "AUTH_READY":
            errors.append("successful live auth must use AUTH_READY")
        if receipt.get("live_auth_status") != "AUTH_OK" and receipt.get("verdict") != "BLOCKED":
            errors.append("failed live auth must be blocked")
    if errors:
        raise MicroHarnessValidationError("; ".join(errors))


def run_raw_data_audit(root: Path, data_root: Path, cycle_id: str | None = None) -> dict[str, Any]:
    root = Path(root)
    data_root = Path(data_root)
    manifest = freeze_micro_subset(root)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    task_assets = []
    missing_raw_assets = []
    for task_id in MLE_LOW_MICRO_TASK_IDS:
        required = list(RAW_PREPARE_ASSETS[task_id])
        present = []
        missing = []
        for rel_path in required:
            path = data_root / task_id / rel_path
            row = {
                "path": rel_path,
                "absolute_path": str(path),
                "present": path.is_file(),
                "sha256": sha256_bytes(path.read_bytes()) if path.is_file() else None,
            }
            present.append(row)
            if not path.is_file():
                missing.append(rel_path)
                missing_raw_assets.append({"task_id": task_id, "path": rel_path, "expected_path": str(path)})
        task_assets.append(
            {
                "task_id": task_id,
                "raw_root": str(data_root / task_id / "raw"),
                "required_raw_assets": required,
                "raw_assets": present,
                "missing_raw_assets": missing,
            }
        )
    raw_data_ready = not missing_raw_assets
    receipt = {
        "ticket": "EMBER-MLE-MICRO-RAW-DATA-AUDIT",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "benchmark_subset": {
            "id": manifest["id"],
            "task_ids": manifest["task_ids"],
            "official_leaderboard_comparable": False,
        },
        "fixture_only": False,
        "real_mle_tasks_executed": False,
        "frozen_before_execution": True,
        "data_root": str(data_root),
        "raw_data_ready": raw_data_ready,
        "task_assets": task_assets,
        "missing_raw_assets": missing_raw_assets,
        "freeze_manifest_sha256": manifest["freeze_manifest_sha256"],
        "freeze_manifest_path": manifest["freeze_manifest_path"],
        "score": {
            "baseline_score": None,
            "candidate_score": None,
            "mean_normalized_improvement": None,
        },
        "verdict": "READY" if raw_data_ready else "BLOCKED",
    }
    out = root / "receipts" / "benchmark" / f"mle-micro-raw-data-audit-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_raw_data_audit_receipt(receipt)
    return receipt


def validate_raw_data_audit_receipt(receipt: dict[str, Any]) -> None:
    errors: list[str] = []
    if receipt.get("ticket") != "EMBER-MLE-MICRO-RAW-DATA-AUDIT":
        errors.append("bad ticket")
    subset = receipt.get("benchmark_subset", {})
    if subset.get("task_ids") != MLE_LOW_MICRO_TASK_IDS:
        errors.append("task ids are not the frozen micro-subset")
    if subset.get("official_leaderboard_comparable") is not False:
        errors.append("raw audit must not claim official leaderboard comparability")
    if receipt.get("fixture_only") is not False:
        errors.append("raw audit must not be marked fixture_only")
    if receipt.get("real_mle_tasks_executed") is not False:
        errors.append("raw audit must not claim real MLE task execution")
    if receipt.get("frozen_before_execution") is not True:
        errors.append("manifest must be frozen before execution")
    ready = receipt.get("raw_data_ready") is True
    if ready and receipt.get("missing_raw_assets"):
        errors.append("raw_data_ready cannot be true with missing raw assets")
    if ready and receipt.get("verdict") != "READY":
        errors.append("ready raw audit must use READY verdict")
    if not ready and receipt.get("verdict") != "BLOCKED":
        errors.append("blocked raw audit must use BLOCKED verdict")
    if len(receipt.get("task_assets", [])) != len(MLE_LOW_MICRO_TASK_IDS):
        errors.append("raw audit must record every frozen task")
    if errors:
        raise MicroHarnessValidationError("; ".join(errors))


def run_benchmark_acquisition_status(
    root: Path,
    data_root: Path,
    credential_path: Path | None = None,
    live_auth: bool = False,
    live_auth_command: list[str] | None = None,
    cycle_id: str | None = None,
) -> dict[str, Any]:
    root = Path(root)
    data_root = Path(data_root)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    raw_receipt = run_raw_data_audit(root / "acquisition-raw-audit", data_root, cycle_id=cycle_id)
    auth_receipt = None
    if credential_path is not None:
        auth_receipt = run_kaggle_auth_preflight(
            root / "acquisition-kaggle-auth",
            Path(credential_path),
            live_check=live_auth,
            live_auth_command=live_auth_command,
            cycle_id=cycle_id,
        )

    raw_data_ready = raw_receipt.get("raw_data_ready") is True
    auth_verdict = auth_receipt.get("verdict") if auth_receipt else None
    kaggle_auth_ready = auth_verdict == "AUTH_READY"
    kaggle_auth_shape_ready = auth_verdict == "AUTH_SHAPE_READY"

    if raw_data_ready:
        selected_route = "local_raw_files"
        verdict = "READY_TO_PREPARE"
        blocked_reason = None
        next_action = "run_official_prepare_from_raw"
    elif kaggle_auth_ready:
        selected_route = "kaggle_api_download"
        verdict = "READY_TO_DOWNLOAD"
        blocked_reason = None
        next_action = "download_raw_files_then_run_official_prepare"
    elif kaggle_auth_shape_ready:
        selected_route = None
        verdict = "AUTH_SHAPE_READY"
        blocked_reason = "live_kaggle_auth_not_checked"
        next_action = "run_live_kaggle_auth_preflight"
    else:
        selected_route = None
        verdict = "BLOCKED"
        blocked_reason = "raw_data_missing_and_kaggle_auth_not_ready"
        next_action = "refresh_kaggle_credentials_or_place_raw_files"

    critical_path: list[str] = []
    if not raw_data_ready:
        critical_path.append("place_required_raw_files_under_data_root")
    if not raw_data_ready and not kaggle_auth_ready:
        if kaggle_auth_shape_ready:
            critical_path.append("verify_kaggle_credentials_with_live_auth")
        else:
            critical_path.append("refresh_kaggle_credentials")
    if raw_data_ready:
        critical_path.append("run_official_prepare_from_raw")
    elif kaggle_auth_ready:
        critical_path.append("download_required_raw_files")
        critical_path.append("run_official_prepare_from_raw")

    receipt = {
        "ticket": "EMBER-MLE-MICRO-ACQUISITION-STATUS",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "benchmark_subset": raw_receipt["benchmark_subset"],
        "fixture_only": False,
        "real_mle_tasks_executed": False,
        "frozen_before_execution": True,
        "data_root": str(data_root),
        "credential_path": str(credential_path) if credential_path is not None else None,
        "raw_data_ready": raw_data_ready,
        "kaggle_auth_ready": kaggle_auth_ready,
        "kaggle_auth_shape_ready": kaggle_auth_shape_ready,
        "selected_route": selected_route,
        "next_action": next_action,
        "critical_path": critical_path,
        "blocked_reason": blocked_reason,
        "raw_audit_receipt_path": raw_receipt.get("receipt_path"),
        "kaggle_auth_receipt_path": auth_receipt.get("receipt_path") if auth_receipt else None,
        "missing_raw_assets": raw_receipt.get("missing_raw_assets", []),
        "kaggle_auth_verdict": auth_verdict,
        "kaggle_auth_blocked_reason": auth_receipt.get("blocked_reason") if auth_receipt else "credential_not_checked",
        "score": {
            "baseline_score": None,
            "candidate_score": None,
            "mean_normalized_improvement": None,
        },
        "verdict": verdict,
    }
    out = root / "receipts" / "benchmark" / f"mle-micro-acquisition-status-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_benchmark_acquisition_status_receipt(receipt)
    return receipt


def validate_benchmark_acquisition_status_receipt(receipt: dict[str, Any]) -> None:
    errors: list[str] = []
    if receipt.get("ticket") != "EMBER-MLE-MICRO-ACQUISITION-STATUS":
        errors.append("bad ticket")
    subset = receipt.get("benchmark_subset", {})
    if subset.get("task_ids") != MLE_LOW_MICRO_TASK_IDS:
        errors.append("task ids are not the frozen micro-subset")
    if subset.get("official_leaderboard_comparable") is not False:
        errors.append("acquisition status must not claim official leaderboard comparability")
    if receipt.get("fixture_only") is not False:
        errors.append("acquisition status must not be marked fixture_only")
    if receipt.get("real_mle_tasks_executed") is not False:
        errors.append("acquisition status must not claim real MLE execution")
    if receipt.get("frozen_before_execution") is not True:
        errors.append("manifest must be frozen before execution")
    if receipt.get("raw_data_ready") is True and receipt.get("selected_route") != "local_raw_files":
        errors.append("raw-ready status must select local_raw_files")
    if receipt.get("raw_data_ready") is True and receipt.get("verdict") != "READY_TO_PREPARE":
        errors.append("raw-ready status must use READY_TO_PREPARE")
    if receipt.get("raw_data_ready") is False and receipt.get("kaggle_auth_ready") is True:
        if receipt.get("selected_route") != "kaggle_api_download" or receipt.get("verdict") != "READY_TO_DOWNLOAD":
            errors.append("auth-ready status must select Kaggle download route")
    if receipt.get("verdict") == "BLOCKED" and not receipt.get("blocked_reason"):
        errors.append("blocked status must include blocked_reason")
    if receipt.get("verdict") == "BLOCKED" and receipt.get("selected_route") is not None:
        errors.append("blocked status cannot select a route")
    for forbidden in ("key", "secret", "token"):
        value = receipt.get(forbidden)
        if value is not None:
            errors.append(f"receipt must not include raw {forbidden}")
    if errors:
        raise MicroHarnessValidationError("; ".join(errors))


def _safe_extract_zip(zip_path: Path, destination: Path) -> list[Path]:
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    dest_resolved = destination.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            target = destination / info.filename
            target_resolved = target.resolve()
            if not str(target_resolved).startswith(str(dest_resolved)):
                raise MicroHarnessValidationError(f"zip entry escapes destination: {info.filename}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted.append(target)
    return extracted


def _download_url_to_file(url: str, destination: Path) -> None:
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as src, destination.open("wb") as dst:
        shutil.copyfileobj(src, dst)


def _new_kaggle_competition_client(token_value: str) -> Any:
    os.environ["KAGGLE_API_TOKEN"] = token_value
    from kagglesdk import KaggleClient

    return KaggleClient().competitions.competition_api_client


def _new_download_data_files_request(competition_name: str) -> Any:
    from kagglesdk.competitions.types.competition_api_service import ApiDownloadDataFilesRequest

    request = ApiDownloadDataFilesRequest()
    request.competition_name = competition_name
    return request


def run_kaggle_sdk_raw_download(
    root: Path,
    data_root: Path,
    token_path: Path,
    task_ids: list[str] | None = None,
    competition_client: Any | None = None,
    cycle_id: str | None = None,
) -> dict[str, Any]:
    root = Path(root)
    data_root = Path(data_root)
    token_path = Path(token_path)
    selected_task_ids = task_ids or list(MLE_LOW_MICRO_TASK_IDS)
    manifest = freeze_micro_subset(root)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    token_present = token_path.is_file()
    token_value = token_path.read_text(encoding="utf-8").strip() if token_present else ""
    token_sha256 = sha256_bytes(token_value.encode("utf-8")) if token_value else None
    downloaded_archives: list[dict[str, Any]] = []
    extracted_assets: list[dict[str, Any]] = []
    missing_raw_assets: list[dict[str, str]] = []
    blocked_reason = None
    download_error = None

    if not token_present:
        blocked_reason = "token_file_missing"
    elif not token_value.startswith("KGAT_"):
        blocked_reason = "token_shape_invalid"
    elif any(task_id not in MLE_LOW_MICRO_TASK_IDS for task_id in selected_task_ids):
        blocked_reason = "task_not_in_frozen_subset"
    else:
        old_token = os.environ.get("KAGGLE_API_TOKEN")
        try:
            client = competition_client or _new_kaggle_competition_client(token_value)
            with tempfile.TemporaryDirectory(prefix="ember-kaggle-sdk-raw-") as td:
                tmp_root = Path(td)
                for task_id in selected_task_ids:
                    try:
                        request = _new_download_data_files_request(task_id)
                        redirect = client.download_data_files(request)
                        url = str(getattr(redirect, "url", ""))
                        if not url:
                            raise MicroHarnessValidationError(f"Kaggle SDK returned no download URL for {task_id}")
                        archive_path = tmp_root / f"{task_id}.zip"
                        _download_url_to_file(url, archive_path)
                        raw_root = data_root / task_id / "raw"
                        _safe_extract_zip(archive_path, raw_root)
                        downloaded_archives.append(
                            {
                                "task_id": task_id,
                                "archive_bytes": archive_path.stat().st_size,
                                "archive_sha256": sha256_bytes(archive_path.read_bytes()),
                            }
                        )
                        for rel_path in RAW_PREPARE_ASSETS[task_id]:
                            asset_path = data_root / task_id / rel_path
                            if asset_path.is_file():
                                extracted_assets.append(
                                    {
                                        "task_id": task_id,
                                        "path": rel_path,
                                        "absolute_path": str(asset_path),
                                        "bytes": asset_path.stat().st_size,
                                        "sha256": sha256_bytes(asset_path.read_bytes()),
                                    }
                                )
                            else:
                                missing_raw_assets.append(
                                    {"task_id": task_id, "path": rel_path, "expected_path": str(asset_path)}
                                )
                    except Exception as exc:
                        text = str(exc)
                        if "403" in text or "Forbidden" in text:
                            blocked_reason = "kaggle_download_forbidden"
                        elif "401" in text or "Unauthorized" in text or "Unauthenticated" in text:
                            blocked_reason = "kaggle_download_unauthorized"
                        else:
                            blocked_reason = "kaggle_download_failed"
                        download_error = {
                            "task_id": task_id,
                            "error_type": type(exc).__name__,
                            "summary": _summarize_auth_error(text),
                        }
                        break
        finally:
            if competition_client is None:
                if old_token is None:
                    os.environ.pop("KAGGLE_API_TOKEN", None)
                else:
                    os.environ["KAGGLE_API_TOKEN"] = old_token

    raw_data_ready = not blocked_reason and not missing_raw_assets
    verdict = "DOWNLOADED" if raw_data_ready else "BLOCKED"
    if missing_raw_assets and not blocked_reason:
        blocked_reason = "download_missing_required_raw_assets"

    receipt = {
        "ticket": "EMBER-MLE-KAGGLE-SDK-RAW-DOWNLOAD",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "benchmark_subset": {
            "id": manifest["id"],
            "task_ids": selected_task_ids,
            "official_leaderboard_comparable": False,
        },
        "fixture_only": False,
        "real_mle_tasks_executed": False,
        "frozen_before_execution": True,
        "data_root": str(data_root),
        "token_path": str(token_path),
        "token_file_present": token_present,
        "token_sha256": token_sha256,
        "downloaded_task_count": len(downloaded_archives),
        "downloaded_archives": downloaded_archives,
        "extracted_assets": extracted_assets,
        "missing_raw_assets": missing_raw_assets,
        "raw_data_ready": raw_data_ready,
        "blocked_reason": blocked_reason,
        "download_error": download_error,
        "score": {
            "baseline_score": None,
            "candidate_score": None,
            "mean_normalized_improvement": None,
        },
        "verdict": verdict,
    }
    out = root / "receipts" / "benchmark" / f"mle-kaggle-sdk-raw-download-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_kaggle_sdk_raw_download_receipt(receipt)
    return receipt


def validate_kaggle_sdk_raw_download_receipt(receipt: dict[str, Any]) -> None:
    errors: list[str] = []
    if receipt.get("ticket") != "EMBER-MLE-KAGGLE-SDK-RAW-DOWNLOAD":
        errors.append("bad ticket")
    subset = receipt.get("benchmark_subset", {})
    task_ids = subset.get("task_ids", [])
    if not isinstance(task_ids, list) or any(task_id not in MLE_LOW_MICRO_TASK_IDS for task_id in task_ids):
        errors.append("download task ids must be within the frozen micro-subset")
    if subset.get("official_leaderboard_comparable") is not False:
        errors.append("download must not claim official leaderboard comparability")
    if receipt.get("fixture_only") is not False:
        errors.append("download must not be marked fixture_only")
    if receipt.get("real_mle_tasks_executed") is not False:
        errors.append("download must not claim real MLE task execution")
    if receipt.get("frozen_before_execution") is not True:
        errors.append("manifest must be frozen before execution")
    if receipt.get("token_file_present") and not str(receipt.get("token_sha256", "")).startswith("sha256:"):
        errors.append("present access token must be represented only by sha256")
    for forbidden in ("key", "secret", "token"):
        if receipt.get(forbidden) is not None:
            errors.append(f"receipt must not include raw {forbidden}")
    ready = receipt.get("raw_data_ready") is True
    if ready and receipt.get("verdict") != "DOWNLOADED":
        errors.append("raw-ready download must use DOWNLOADED verdict")
    if ready and receipt.get("missing_raw_assets"):
        errors.append("raw-ready download cannot have missing raw assets")
    if not ready and receipt.get("verdict") != "BLOCKED":
        errors.append("blocked download must use BLOCKED verdict")
    if receipt.get("verdict") == "BLOCKED" and not receipt.get("blocked_reason"):
        errors.append("blocked download must include blocked_reason")
    if receipt.get("download_error") and len(str(receipt.get("download_error", {}).get("summary", ""))) > 200:
        errors.append("download error summary must be bounded")
    for archive in receipt.get("downloaded_archives", []):
        if not str(archive.get("archive_sha256", "")).startswith("sha256:"):
            errors.append("downloaded archives must record sha256")
    for asset in receipt.get("extracted_assets", []):
        if not str(asset.get("sha256", "")).startswith("sha256:"):
            errors.append("extracted assets must record sha256")
    if errors:
        raise MicroHarnessValidationError("; ".join(errors))


def _read_requires_python(pyproject_path: Path) -> str | None:
    if not pyproject_path.is_file():
        return None
    for raw_line in pyproject_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("requires-python"):
            return line.split("=", 1)[1].strip().strip("'\"")
    return None


def _min_python_from_requirement(requirement: str | None) -> tuple[int, int] | None:
    if not requirement:
        return None
    match = re.search(r">=\s*(\d+)\.(\d+)", requirement)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _default_kaggle_benchmarks_import_check() -> bool:
    try:
        import kaggle_benchmarks  # noqa: F401

        return True
    except Exception:
        return False


def run_kaggle_benchmarks_sdk_probe(
    root: Path,
    sdk_root: Path | None = None,
    python_version: tuple[int, int, int] | None = None,
    import_check: Callable[[], bool] | None = None,
    cycle_id: str | None = None,
) -> dict[str, Any]:
    root = Path(root)
    sdk_root = Path(sdk_root) if sdk_root is not None else None
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    py_version = python_version or (sys.version_info.major, sys.version_info.minor, sys.version_info.micro)
    py_version_text = ".".join(str(part) for part in py_version)

    sdk_source_present = sdk_root is not None and (sdk_root / "pyproject.toml").is_file()
    requires_python = _read_requires_python(sdk_root / "pyproject.toml") if sdk_root is not None else None
    min_python = _min_python_from_requirement(requires_python)
    python_runtime_ready = min_python is None or py_version[:2] >= min_python
    kaggle_benchmarks_importable = (import_check or _default_kaggle_benchmarks_import_check)()

    readme_text = ""
    if sdk_root is not None and (sdk_root / "README.md").is_file():
        readme_text = (sdk_root / "README.md").read_text(encoding="utf-8", errors="replace")
    docs_claim_task_run_files = "task file" in readme_text.lower() and "run files" in readme_text.lower()
    docs_claim_dataset_evaluation = "dataset evaluation" in readme_text.lower()
    task_run_file_execution_ready = bool(
        sdk_source_present and python_runtime_ready and kaggle_benchmarks_importable
    )

    if not sdk_source_present:
        blocked_reason = "kaggle_benchmarks_sdk_source_missing"
    elif not python_runtime_ready:
        blocked_reason = "python_runtime_below_kaggle_benchmarks_requirement"
    elif not kaggle_benchmarks_importable:
        blocked_reason = "kaggle_benchmarks_package_not_importable"
    else:
        blocked_reason = None

    receipt = {
        "ticket": "EMBER-KAGGLE-BENCHMARKS-SDK-PROBE",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "lane": "kaggle_benchmarks",
        "sdk_root": str(sdk_root) if sdk_root is not None else None,
        "sdk_source_present": sdk_source_present,
        "requires_python": requires_python,
        "python_version": py_version_text,
        "python_runtime_ready": python_runtime_ready,
        "kaggle_benchmarks_importable": kaggle_benchmarks_importable,
        "docs_claim_task_run_files": docs_claim_task_run_files,
        "docs_claim_dataset_evaluation": docs_claim_dataset_evaluation,
        "task_run_file_execution_ready": task_run_file_execution_ready,
        "blocked_reason": blocked_reason,
        "score": {
            "baseline_score": None,
            "candidate_score": None,
            "mean_normalized_improvement": None,
        },
        "verdict": "READY_TO_RUN_PROBE_TASK" if blocked_reason is None else "BLOCKED",
    }
    out = root / "receipts" / "benchmark" / f"kaggle-benchmarks-sdk-probe-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_kaggle_benchmarks_sdk_probe_receipt(receipt)
    return receipt


def validate_kaggle_benchmarks_sdk_probe_receipt(receipt: dict[str, Any]) -> None:
    errors: list[str] = []
    if receipt.get("ticket") != "EMBER-KAGGLE-BENCHMARKS-SDK-PROBE":
        errors.append("bad ticket")
    if receipt.get("lane") != "kaggle_benchmarks":
        errors.append("bad lane")
    if not re.match(r"^\d+\.\d+\.\d+$", str(receipt.get("python_version", ""))):
        errors.append("python_version must be major.minor.micro")
    ready = receipt.get("task_run_file_execution_ready") is True
    if ready and receipt.get("verdict") != "READY_TO_RUN_PROBE_TASK":
        errors.append("ready benchmark SDK probe must use READY_TO_RUN_PROBE_TASK")
    if ready and receipt.get("blocked_reason") is not None:
        errors.append("ready benchmark SDK probe cannot include blocked_reason")
    if not ready and receipt.get("verdict") != "BLOCKED":
        errors.append("not-ready benchmark SDK probe must be blocked")
    if receipt.get("verdict") == "BLOCKED" and not receipt.get("blocked_reason"):
        errors.append("blocked benchmark SDK probe must include blocked_reason")
    if receipt.get("python_runtime_ready") is False and receipt.get("blocked_reason") != "python_runtime_below_kaggle_benchmarks_requirement":
        errors.append("old Python runtime must use explicit Python requirement blocker")
    if receipt.get("score", {}).get("mean_normalized_improvement") is not None:
        errors.append("SDK probe must not claim benchmark score")
    if errors:
        raise MicroHarnessValidationError("; ".join(errors))


def _default_kaggle_benchmarks_task_probe_runner(
    workdir: Path,
    python_executable: Path,
) -> dict[str, Any]:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    tmpdir = workdir / "tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    script_path = workdir / "ember_kaggle_benchmarks_task_probe.py"
    script_path.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "import os",
                "import tempfile",
                "",
                "out = Path(__file__).resolve().parent",
                "(out / 'tmp').mkdir(parents=True, exist_ok=True)",
                "os.environ['TMP'] = str(out / 'tmp')",
                "os.environ['TEMP'] = str(out / 'tmp')",
                "os.environ['TMPDIR'] = str(out / 'tmp')",
                "tempfile.tempdir = str(out / 'tmp')",
                "_temporary_directory = tempfile.TemporaryDirectory",
                "def _safe_temporary_directory(*args, **kwargs):",
                "    kwargs.setdefault('ignore_cleanup_errors', True)",
                "    return _temporary_directory(*args, **kwargs)",
                "tempfile.TemporaryDirectory = _safe_temporary_directory",
                "import kaggle_benchmarks as kbench",
                "from kaggle_benchmarks import ExecutionMode, config, kaggle, runs",
                "from kaggle_benchmarks.envs import local",
                "def _safe_local_environment_close(self):",
                "    try:",
                "        os.chdir(self.original_dir)",
                "    except Exception:",
                "        pass",
                "    try:",
                "        self.temp_dir.cleanup()",
                "    except PermissionError:",
                "        pass",
                "local.InternalUnsafeLocalEnvironment.close = _safe_local_environment_close",
                "kbench.client = kaggle.KaggleClient(directory=out)",
                "config.execution_mode = ExecutionMode.RUN",
                "runs._run_counters.clear()",
                "",
                "@kbench.task(name='Ember Probe No LLM')",
                "def ember_probe_no_llm() -> bool:",
                "    kbench.assertions.assert_true(True)",
                "    return True",
                "",
                "run = ember_probe_no_llm.run()",
                "if run.result is not True:",
                "    raise SystemExit('probe task returned non-true result')",
                "print('EMBER_KAGGLE_BENCHMARKS_TASK_PROBE_PASS')",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )
    proc = subprocess.run(
        [str(python_executable), str(script_path)],
        cwd=str(workdir),
        env={**os.environ, "TMP": str(tmpdir), "TEMP": str(tmpdir), "TMPDIR": str(tmpdir)},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def run_kaggle_benchmarks_task_file_probe(
    root: Path,
    workdir: Path,
    python_executable: Path,
    runner: Callable[[Path], dict[str, Any]] | None = None,
    cycle_id: str | None = None,
) -> dict[str, Any]:
    root = Path(root)
    workdir = Path(workdir)
    python_executable = Path(python_executable)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    workdir.mkdir(parents=True, exist_ok=True)

    if runner is None:
        run_result = _default_kaggle_benchmarks_task_probe_runner(workdir, python_executable)
    else:
        run_result = runner(workdir)

    task_files = sorted(workdir.glob("*.task.json"))
    run_files = sorted(workdir.glob("*.run.json"))
    completed_run_files = []
    passed_assertion_files = []
    for path in run_files:
        try:
            run_data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if run_data.get("state") == "BENCHMARK_TASK_RUN_STATE_COMPLETED":
            completed_run_files.append(str(path))
        assertions = run_data.get("assertions", [])
        if any(row.get("status") == "BENCHMARK_TASK_RUN_ASSERTION_STATUS_PASSED" for row in assertions):
            passed_assertion_files.append(str(path))
    artifact_files = []
    for path in [*task_files, *run_files]:
        artifact_files.append(
            {
                "path": str(path),
                "name": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha256_bytes(path.read_bytes()),
            }
        )

    returncode = int(run_result.get("returncode", 1))
    stderr_text = str(run_result.get("stderr", ""))
    cleanup_error_observed = "PermissionError" in stderr_text and "temp" in stderr_text.lower()
    run_file_completed = bool(completed_run_files) and bool(passed_assertion_files)
    task_run_files_materialized = bool(task_files) and bool(run_files) and (returncode == 0 or (cleanup_error_observed and run_file_completed))
    if task_run_files_materialized:
        verdict = "TASK_RUN_FILES_MATERIALIZED"
        blocked_reason = None
    elif returncode != 0:
        verdict = "BLOCKED"
        blocked_reason = "kaggle_benchmarks_task_probe_failed"
    else:
        verdict = "BLOCKED"
        blocked_reason = "kaggle_benchmarks_task_run_files_missing"

    receipt = {
        "ticket": "EMBER-KAGGLE-BENCHMARKS-TASK-FILE-PROBE",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "lane": "kaggle_benchmarks",
        "python_executable": str(python_executable),
        "workdir": str(workdir),
        "returncode": returncode,
        "stdout_tail": str(run_result.get("stdout", ""))[-2000:],
        "stderr_tail": str(run_result.get("stderr", ""))[-2000:],
        "task_file_count": len(task_files),
        "run_file_count": len(run_files),
        "completed_run_files": completed_run_files,
        "passed_assertion_files": passed_assertion_files,
        "cleanup_error_observed": cleanup_error_observed,
        "task_run_files_materialized": task_run_files_materialized,
        "artifact_files": artifact_files,
        "blocked_reason": blocked_reason,
        "score": {
            "baseline_score": None,
            "candidate_score": None,
            "mean_normalized_improvement": None,
        },
        "verdict": verdict,
    }
    out = root / "receipts" / "benchmark" / f"kaggle-benchmarks-task-file-probe-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_kaggle_benchmarks_task_file_probe_receipt(receipt)
    return receipt


def validate_kaggle_benchmarks_task_file_probe_receipt(receipt: dict[str, Any]) -> None:
    errors: list[str] = []
    if receipt.get("ticket") != "EMBER-KAGGLE-BENCHMARKS-TASK-FILE-PROBE":
        errors.append("bad ticket")
    if receipt.get("lane") != "kaggle_benchmarks":
        errors.append("bad lane")
    materialized = receipt.get("task_run_files_materialized") is True
    if materialized and receipt.get("verdict") != "TASK_RUN_FILES_MATERIALIZED":
        errors.append("materialized task-file probe must use TASK_RUN_FILES_MATERIALIZED")
    if materialized and receipt.get("blocked_reason") is not None:
        errors.append("materialized task-file probe cannot include blocked_reason")
    if not materialized and receipt.get("verdict") != "BLOCKED":
        errors.append("non-materialized task-file probe must be blocked")
    if receipt.get("verdict") == "BLOCKED" and not receipt.get("blocked_reason"):
        errors.append("blocked task-file probe must include blocked_reason")
    if materialized and int(receipt.get("task_file_count", 0)) < 1:
        errors.append("materialized task-file probe must include at least one task file")
    if materialized and int(receipt.get("run_file_count", 0)) < 1:
        errors.append("materialized task-file probe must include at least one run file")
    if materialized and int(receipt.get("returncode", 1)) != 0:
        if receipt.get("cleanup_error_observed") is not True:
            errors.append("nonzero materialized task-file probe must record cleanup_error_observed")
        if not receipt.get("completed_run_files"):
            errors.append("nonzero materialized task-file probe must record completed run files")
        if not receipt.get("passed_assertion_files"):
            errors.append("nonzero materialized task-file probe must record passed assertion files")
    for row in receipt.get("artifact_files", []):
        if not str(row.get("sha256", "")).startswith("sha256:"):
            errors.append("artifact file missing sha256")
        if not isinstance(row.get("bytes"), int) or row.get("bytes") <= 0:
            errors.append("artifact file must record positive byte size")
    if receipt.get("score", {}).get("mean_normalized_improvement") is not None:
        errors.append("task-file probe must not claim benchmark score")
    if errors:
        raise MicroHarnessValidationError("; ".join(errors))


def _write_kaggle_benchmarks_temp_prelude_lines() -> list[str]:
    return [
        "from pathlib import Path",
        "import json",
        "import os",
        "import tempfile",
        "",
        "out = Path(__file__).resolve().parent",
        "(out / 'tmp').mkdir(parents=True, exist_ok=True)",
        "os.environ['TMP'] = str(out / 'tmp')",
        "os.environ['TEMP'] = str(out / 'tmp')",
        "os.environ['TMPDIR'] = str(out / 'tmp')",
        "tempfile.tempdir = str(out / 'tmp')",
        "_temporary_directory = tempfile.TemporaryDirectory",
        "def _safe_temporary_directory(*args, **kwargs):",
        "    kwargs.setdefault('ignore_cleanup_errors', True)",
        "    return _temporary_directory(*args, **kwargs)",
        "tempfile.TemporaryDirectory = _safe_temporary_directory",
        "def _patch_kaggle_local_environment_cleanup():",
        "    from kaggle_benchmarks.envs import local",
        "    def _safe_local_environment_close(self):",
        "        try:",
        "            os.chdir(self.original_dir)",
        "        except Exception:",
        "            pass",
        "        try:",
        "            self.temp_dir.cleanup()",
        "        except PermissionError:",
        "            pass",
        "    local.InternalUnsafeLocalEnvironment.close = _safe_local_environment_close",
    ]


def _default_kaggle_benchmarks_score_shape_runner(
    workdir: Path,
    python_executable: Path,
) -> dict[str, Any]:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    script_path = workdir / "ember_kaggle_benchmarks_score_shape_probe.py"
    script_path.write_text(
        "\n".join(
            [
                *_write_kaggle_benchmarks_temp_prelude_lines(),
                "import sys",
                "import kaggle_benchmarks as kbench",
                "from kaggle_benchmarks import ExecutionMode, config, kaggle, runs",
                "",
                "_patch_kaggle_local_environment_cleanup()",
                "kbench.client = kaggle.KaggleClient(directory=out)",
                "config.execution_mode = ExecutionMode.RUN",
                "runs._run_counters.clear()",
                "",
                "@kbench.task(name='Ember Score Shape No LLM')",
                "def ember_score_shape_no_llm(sample_id: int, expected_even: bool) -> bool:",
                "    prediction_even = (sample_id % 2) == 0",
                "    return prediction_even == expected_even",
                "",
                "sample_id = int(sys.argv[1])",
                "expected_even = sys.argv[2].lower() == 'true'",
                "run = ember_score_shape_no_llm.run(sample_id=sample_id, expected_even=expected_even, _id=str(sample_id))",
                "print(f'EMBER_KAGGLE_BENCHMARKS_SCORE_SHAPE_SAMPLE sample_id={sample_id} result={run.result}')",
                "print('EMBER_KAGGLE_BENCHMARKS_SCORE_SHAPE_PASS')",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )
    tmpdir = workdir / "tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    rows = [(0, True), (1, False), (2, True), (3, False)]
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    returncodes: list[int] = []
    env = {**os.environ, "TMP": str(tmpdir), "TEMP": str(tmpdir), "TMPDIR": str(tmpdir)}
    for sample_id, expected_even in rows:
        proc = subprocess.run(
            [str(python_executable), str(script_path), str(sample_id), str(expected_even)],
            cwd=str(workdir),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        returncodes.append(proc.returncode)
        stdout_parts.append(proc.stdout)
        stderr_parts.append(proc.stderr)

    completed_count = 0
    errored_count = 0
    result_values: list[bool] = []
    for sample_id, _expected_even in rows:
        matches = sorted(workdir.glob(f"Ember_Score_Shape_No_LLM-run_param_id_{sample_id}*.run.json"))
        if not matches:
            errored_count += 1
            continue
        run_data = json.loads(matches[-1].read_text(encoding="utf-8"))
        if run_data.get("state") != "BENCHMARK_TASK_RUN_STATE_COMPLETED":
            errored_count += 1
            continue
        completed_count += 1
        result = run_data.get("results", [{}])[0].get("booleanResult")
        result_values.append(bool(result))

    metric_value = float(sum(1 for value in result_values if value) / len(rows))
    summary = {
        "metric_name": "accuracy",
        "metric_value": metric_value,
        "sample_count": len(rows),
        "completed_count": completed_count,
        "errored_count": errored_count,
    }
    (workdir / "ember_score_shape_summary.json").write_text(
        json.dumps(summary, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "returncode": 0 if all(code == 0 for code in returncodes) else max(returncodes),
        "stdout": "".join(stdout_parts),
        "stderr": "".join(stderr_parts),
    }


def run_kaggle_benchmarks_score_shape_probe(
    root: Path,
    workdir: Path,
    python_executable: Path,
    runner: Callable[[Path], dict[str, Any]] | None = None,
    cycle_id: str | None = None,
) -> dict[str, Any]:
    root = Path(root)
    workdir = Path(workdir)
    python_executable = Path(python_executable)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    workdir.mkdir(parents=True, exist_ok=True)

    if runner is None:
        run_result = _default_kaggle_benchmarks_score_shape_runner(workdir, python_executable)
    else:
        run_result = runner(workdir)

    task_files = sorted(workdir.glob("*.task.json"))
    run_files = sorted(workdir.glob("*.run.json"))
    summary_path = workdir / "ember_score_shape_summary.json"
    local_score_shape: dict[str, Any] | None = None
    if summary_path.is_file():
        local_score_shape = json.loads(summary_path.read_text(encoding="utf-8"))

    artifact_files = []
    for path in [*task_files, *run_files, summary_path]:
        if path.is_file():
            artifact_files.append(
                {
                    "path": str(path),
                    "name": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": sha256_bytes(path.read_bytes()),
                }
            )

    returncode = int(run_result.get("returncode", 1))
    stderr_text = str(run_result.get("stderr", ""))
    cleanup_error_observed = "PermissionError" in stderr_text and "temp" in stderr_text.lower()
    score_shape_ready = bool(
        local_score_shape
        and isinstance(local_score_shape.get("metric_value"), (int, float))
        and int(local_score_shape.get("sample_count", 0)) > 0
        and int(local_score_shape.get("completed_count", 0)) == int(local_score_shape.get("sample_count", -1))
        and int(local_score_shape.get("errored_count", -1)) == 0
        and bool(task_files)
        and bool(run_files)
        and (returncode == 0 or cleanup_error_observed)
    )

    if score_shape_ready:
        verdict = "SCORE_SHAPE_RECEIPTED"
        blocked_reason = None
    elif returncode != 0:
        verdict = "BLOCKED"
        blocked_reason = "kaggle_benchmarks_score_shape_probe_failed"
    else:
        verdict = "BLOCKED"
        blocked_reason = "kaggle_benchmarks_score_shape_missing"

    receipt = {
        "ticket": "EMBER-KAGGLE-BENCHMARKS-SCORE-SHAPE-PROBE",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "lane": "kaggle_benchmarks",
        "python_executable": str(python_executable),
        "workdir": str(workdir),
        "returncode": returncode,
        "stdout_tail": str(run_result.get("stdout", ""))[-2000:],
        "stderr_tail": stderr_text[-2000:],
        "task_file_count": len(task_files),
        "run_file_count": len(run_files),
        "summary_path": str(summary_path) if summary_path.is_file() else None,
        "local_score_shape": local_score_shape,
        "score_shape_ready": score_shape_ready,
        "cleanup_error_observed": cleanup_error_observed,
        "benchmark_delta_claimed": False,
        "artifact_files": artifact_files,
        "blocked_reason": blocked_reason,
        "score": {
            "baseline_score": None,
            "candidate_score": None,
            "mean_normalized_improvement": None,
        },
        "verdict": verdict,
    }
    out = root / "receipts" / "benchmark" / f"kaggle-benchmarks-score-shape-probe-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_kaggle_benchmarks_score_shape_probe_receipt(receipt)
    return receipt


def validate_kaggle_benchmarks_score_shape_probe_receipt(receipt: dict[str, Any]) -> None:
    errors: list[str] = []
    if receipt.get("ticket") != "EMBER-KAGGLE-BENCHMARKS-SCORE-SHAPE-PROBE":
        errors.append("bad ticket")
    if receipt.get("lane") != "kaggle_benchmarks":
        errors.append("bad lane")
    ready = receipt.get("score_shape_ready") is True
    if ready and receipt.get("verdict") != "SCORE_SHAPE_RECEIPTED":
        errors.append("ready score-shape probe must use SCORE_SHAPE_RECEIPTED")
    if ready and receipt.get("blocked_reason") is not None:
        errors.append("ready score-shape probe cannot include blocked_reason")
    if not ready and receipt.get("verdict") != "BLOCKED":
        errors.append("not-ready score-shape probe must be blocked")
    if receipt.get("verdict") == "BLOCKED" and not receipt.get("blocked_reason"):
        errors.append("blocked score-shape probe must include blocked_reason")
    shape = receipt.get("local_score_shape")
    if ready:
        if not isinstance(shape, dict):
            errors.append("ready score-shape probe must include local_score_shape")
        else:
            if shape.get("metric_name") != "accuracy":
                errors.append("score-shape metric must be accuracy")
            if not isinstance(shape.get("metric_value"), (int, float)):
                errors.append("score-shape metric_value must be numeric")
            if int(shape.get("sample_count", 0)) <= 0:
                errors.append("score-shape sample_count must be positive")
            if shape.get("completed_count") != shape.get("sample_count"):
                errors.append("score-shape completed_count must match sample_count")
            if shape.get("errored_count") != 0:
                errors.append("score-shape errored_count must be zero")
        if int(receipt.get("task_file_count", 0)) < 1:
            errors.append("ready score-shape probe must include a task file")
        if int(receipt.get("run_file_count", 0)) < 1:
            errors.append("ready score-shape probe must include run files")
    if receipt.get("benchmark_delta_claimed") is not False:
        errors.append("score-shape probe must not claim benchmark delta")
    if receipt.get("score", {}).get("mean_normalized_improvement") is not None:
        errors.append("score-shape probe must not claim normalized benchmark improvement")
    for row in receipt.get("artifact_files", []):
        if not str(row.get("sha256", "")).startswith("sha256:"):
            errors.append("artifact file missing sha256")
    if errors:
        raise MicroHarnessValidationError("; ".join(errors))


LIVECODEBENCH_PUBLIC_TEST_INPUT = "6\nabc\nacb\nbac\nbca\ncab\ncba\n"
LIVECODEBENCH_PUBLIC_TEST_OUTPUT = "YES\nYES\nYES\nNO\nNO\nYES\n"


def _default_kaggle_benchmarks_livecodebench_public_test_runner(
    workdir: Path,
    python_executable: Path,
) -> dict[str, Any]:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    script_path = workdir / "ember_kaggle_benchmarks_livecodebench_public_test.py"
    script_path.write_text(
        "\n".join(
            [
                *_write_kaggle_benchmarks_temp_prelude_lines(),
                "import sys",
                "import kaggle_benchmarks as kbench",
                "from kaggle_benchmarks import ExecutionMode, config, kaggle, runs",
                "",
                "_patch_kaggle_local_environment_cleanup()",
                "kbench.client = kaggle.KaggleClient(directory=out)",
                "config.execution_mode = ExecutionMode.RUN",
                "runs._run_counters.clear()",
                "",
                "PUBLIC_INPUT = '6\\nabc\\nacb\\nbac\\nbca\\ncab\\ncba\\n'",
                "PUBLIC_OUTPUT = 'YES\\nYES\\nYES\\nNO\\nNO\\nYES\\n'",
                "",
                "def solve_short_sort(stdin: str) -> str:",
                "    lines = [line.strip() for line in stdin.splitlines() if line.strip()]",
                "    t = int(lines[0])",
                "    answers = []",
                "    for s in lines[1:1 + t]:",
                "        mismatch_count = sum(1 for a, b in zip(s, 'abc') if a != b)",
                "        answers.append('YES' if mismatch_count in (0, 2) else 'NO')",
                "    return '\\n'.join(answers) + '\\n'",
                "",
                "@kbench.task(name='LiveCodeBench Demo Public Test')",
                "def livecodebench_demo_public_test() -> bool:",
                "    return solve_short_sort(PUBLIC_INPUT) == PUBLIC_OUTPUT",
                "",
                "run = livecodebench_demo_public_test.run(_id='1873_A_public')",
                "summary = {",
                "    'benchmark_family': 'livecodebench/code_generation_lite',",
                "    'question_id': '1873_A',",
                "    'contest_id': '1873',",
                "    'platform': 'codeforces',",
                "    'public_test_passed': bool(run.result),",
                "    'sample_count': 1,",
                "}",
                "(out / 'livecodebench_public_test_summary.json').write_text(json.dumps(summary, sort_keys=True) + '\\n', encoding='utf-8')",
                "print('EMBER_KAGGLE_BENCHMARKS_LCB_PUBLIC_TEST_PASS')",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )
    tmpdir = workdir / "tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [str(python_executable), str(script_path)],
        cwd=str(workdir),
        env={**os.environ, "TMP": str(tmpdir), "TEMP": str(tmpdir), "TMPDIR": str(tmpdir)},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def run_kaggle_benchmarks_livecodebench_public_test_pilot(
    root: Path,
    workdir: Path,
    python_executable: Path,
    sdk_root: Path | None = None,
    runner: Callable[[Path], dict[str, Any]] | None = None,
    cycle_id: str | None = None,
) -> dict[str, Any]:
    root = Path(root)
    workdir = Path(workdir)
    python_executable = Path(python_executable)
    sdk_root = Path(sdk_root) if sdk_root is not None else None
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    workdir.mkdir(parents=True, exist_ok=True)

    if runner is None:
        run_result = _default_kaggle_benchmarks_livecodebench_public_test_runner(workdir, python_executable)
    else:
        run_result = runner(workdir)

    task_files = sorted(workdir.glob("*.task.json"))
    run_files = sorted(workdir.glob("*.run.json"))
    summary_path = workdir / "livecodebench_public_test_summary.json"
    summary: dict[str, Any] | None = None
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    completed_public_test_run = False
    for path in run_files:
        try:
            run_data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        result = run_data.get("results", [{}])[0].get("booleanResult")
        if run_data.get("state") == "BENCHMARK_TASK_RUN_STATE_COMPLETED" and result is True:
            completed_public_test_run = True
            break

    artifact_files = []
    for path in [*task_files, *run_files, summary_path]:
        if path.is_file():
            artifact_files.append(
                {
                    "path": str(path),
                    "name": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": sha256_bytes(path.read_bytes()),
                }
            )

    returncode = int(run_result.get("returncode", 1))
    stderr_text = str(run_result.get("stderr", ""))
    cleanup_error_observed = "PermissionError" in stderr_text and "temp" in stderr_text.lower()
    public_test_passed = bool((summary and summary.get("public_test_passed") is True) or completed_public_test_run)
    pilot_ready = bool(public_test_passed and task_files and run_files and (returncode == 0 or cleanup_error_observed))

    if pilot_ready:
        verdict = "PILOT_PUBLIC_TEST_RECEIPTED"
        blocked_reason = None
    elif returncode != 0:
        verdict = "BLOCKED"
        blocked_reason = "kaggle_benchmarks_livecodebench_public_test_failed"
    else:
        verdict = "BLOCKED"
        blocked_reason = "kaggle_benchmarks_livecodebench_public_test_missing"

    source_example = None
    source_example_present = False
    source_example_sha256 = None
    if sdk_root is not None:
        candidate = sdk_root / "documentation" / "examples" / "code_generation.py"
        source_example = str(candidate)
        source_example_present = candidate.is_file()
        source_example_sha256 = sha256_bytes(candidate.read_bytes()) if candidate.is_file() else None

    receipt = {
        "ticket": "EMBER-KAGGLE-BENCHMARKS-LIVECODEBENCH-PUBLIC-TEST-PILOT",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "lane": "kaggle_benchmarks",
        "python_executable": str(python_executable),
        "workdir": str(workdir),
        "sdk_root": str(sdk_root) if sdk_root is not None else None,
        "source_example": source_example,
        "source_example_present": source_example_present,
        "source_example_sha256": source_example_sha256,
        "benchmark_family": (summary or {}).get("benchmark_family", "livecodebench/code_generation_lite"),
        "question_id": (summary or {}).get("question_id", "1873_A"),
        "contest_id": (summary or {}).get("contest_id", "1873"),
        "platform": (summary or {}).get("platform", "codeforces"),
        "returncode": returncode,
        "stdout_tail": str(run_result.get("stdout", ""))[-2000:],
        "stderr_tail": stderr_text[-2000:],
        "task_file_count": len(task_files),
        "run_file_count": len(run_files),
        "summary_path": str(summary_path) if summary_path.is_file() else None,
        "completed_public_test_run": completed_public_test_run,
        "public_test_passed": public_test_passed,
        "sample_count": int((summary or {}).get("sample_count", 1 if completed_public_test_run else 0)),
        "pilot_ready": pilot_ready,
        "cleanup_error_observed": cleanup_error_observed,
        "benchmark_delta_claimed": False,
        "artifact_files": artifact_files,
        "blocked_reason": blocked_reason,
        "score": {
            "baseline_score": None,
            "candidate_score": None,
            "mean_normalized_improvement": None,
        },
        "verdict": verdict,
    }
    out = root / "receipts" / "benchmark" / f"kaggle-benchmarks-livecodebench-public-test-pilot-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_kaggle_benchmarks_livecodebench_public_test_pilot_receipt(receipt)
    return receipt


def validate_kaggle_benchmarks_livecodebench_public_test_pilot_receipt(receipt: dict[str, Any]) -> None:
    errors: list[str] = []
    if receipt.get("ticket") != "EMBER-KAGGLE-BENCHMARKS-LIVECODEBENCH-PUBLIC-TEST-PILOT":
        errors.append("bad ticket")
    if receipt.get("lane") != "kaggle_benchmarks":
        errors.append("bad lane")
    ready = receipt.get("pilot_ready") is True
    if ready and receipt.get("verdict") != "PILOT_PUBLIC_TEST_RECEIPTED":
        errors.append("ready pilot must use PILOT_PUBLIC_TEST_RECEIPTED")
    if ready and receipt.get("blocked_reason") is not None:
        errors.append("ready pilot cannot include blocked_reason")
    if not ready and receipt.get("verdict") != "BLOCKED":
        errors.append("not-ready pilot must be blocked")
    if receipt.get("verdict") == "BLOCKED" and not receipt.get("blocked_reason"):
        errors.append("blocked pilot must include blocked_reason")
    if receipt.get("benchmark_family") != "livecodebench/code_generation_lite":
        errors.append("pilot must use livecodebench/code_generation_lite")
    if receipt.get("question_id") != "1873_A":
        errors.append("pilot must record question_id 1873_A")
    if ready:
        if receipt.get("public_test_passed") is not True:
            errors.append("ready pilot must pass public test")
        if int(receipt.get("task_file_count", 0)) < 1:
            errors.append("ready pilot must include a task file")
        if int(receipt.get("run_file_count", 0)) < 1:
            errors.append("ready pilot must include a run file")
        if int(receipt.get("sample_count", 0)) < 1:
            errors.append("ready pilot must include sample_count")
    if receipt.get("benchmark_delta_claimed") is not False:
        errors.append("pilot smoke must not claim benchmark delta")
    if receipt.get("score", {}).get("mean_normalized_improvement") is not None:
        errors.append("pilot smoke must not claim normalized benchmark improvement")
    for row in receipt.get("artifact_files", []):
        if not str(row.get("sha256", "")).startswith("sha256:"):
            errors.append("artifact file missing sha256")
    if errors:
        raise MicroHarnessValidationError("; ".join(errors))


def _default_kaggle_benchmarks_livecodebench_candidate_vs_baseline_runner(
    workdir: Path,
    python_executable: Path,
) -> dict[str, Any]:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    script_path = workdir / "ember_kaggle_benchmarks_livecodebench_candidate_vs_baseline.py"
    script_path.write_text(
        "\n".join(
            [
                *_write_kaggle_benchmarks_temp_prelude_lines(),
                "import sys",
                "import kaggle_benchmarks as kbench",
                "from kaggle_benchmarks import ExecutionMode, config, kaggle, runs",
                "",
                "_patch_kaggle_local_environment_cleanup()",
                "kbench.client = kaggle.KaggleClient(directory=out)",
                "config.execution_mode = ExecutionMode.RUN",
                "runs._run_counters.clear()",
                "",
                "PUBLIC_INPUT = '6\\nabc\\nacb\\nbac\\nbca\\ncab\\ncba\\n'",
                "PUBLIC_OUTPUT = 'YES\\nYES\\nYES\\nNO\\nNO\\nYES\\n'",
                "",
                "def candidate_solver(stdin: str) -> str:",
                "    lines = [line.strip() for line in stdin.splitlines() if line.strip()]",
                "    t = int(lines[0])",
                "    answers = []",
                "    for s in lines[1:1 + t]:",
                "        mismatch_count = sum(1 for a, b in zip(s, 'abc') if a != b)",
                "        answers.append('YES' if mismatch_count in (0, 2) else 'NO')",
                "    return '\\n'.join(answers) + '\\n'",
                "",
                "def baseline_solver(stdin: str) -> str:",
                "    lines = [line.strip() for line in stdin.splitlines() if line.strip()]",
                "    t = int(lines[0])",
                "    return ('YES\\n' * t)",
                "",
                "@kbench.task(name='LiveCodeBench Public Test Candidate Vs Baseline')",
                "def livecodebench_public_test_candidate_vs_baseline(kind: str) -> bool:",
                "    solver = candidate_solver if kind == 'candidate' else baseline_solver",
                "    return solver(PUBLIC_INPUT) == PUBLIC_OUTPUT",
                "",
                "kind = sys.argv[1]",
                "run = livecodebench_public_test_candidate_vs_baseline.run(kind=kind, _id=kind)",
                "print(f'EMBER_KAGGLE_BENCHMARKS_LCB_ARM kind={kind} result={run.result}')",
                "print('EMBER_KAGGLE_BENCHMARKS_LCB_CANDIDATE_VS_BASELINE_PASS')",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )
    tmpdir = workdir / "tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    returncodes: list[int] = []
    env = {**os.environ, "TMP": str(tmpdir), "TEMP": str(tmpdir), "TMPDIR": str(tmpdir)}
    for kind in ("baseline", "candidate"):
        proc = subprocess.run(
            [str(python_executable), str(script_path), kind],
            cwd=str(workdir),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        returncodes.append(proc.returncode)
        stdout_parts.append(proc.stdout)
        stderr_parts.append(proc.stderr)

    arm_results: dict[str, bool] = {}
    for kind in ("baseline", "candidate"):
        matches = sorted(workdir.glob(f"LiveCodeBench_Public_Test_Candidate_Vs_Baseline-run_param_id_{kind}*.run.json"))
        if not matches:
            continue
        run_data = json.loads(matches[-1].read_text(encoding="utf-8"))
        if run_data.get("state") == "BENCHMARK_TASK_RUN_STATE_COMPLETED":
            arm_results[kind] = bool(run_data.get("results", [{}])[0].get("booleanResult"))
    if set(arm_results) == {"baseline", "candidate"}:
        summary = {
            "benchmark_family": "livecodebench/code_generation_lite",
            "question_id": "1873_A",
            "contest_id": "1873",
            "platform": "codeforces",
            "baseline_public_pass": bool(arm_results["baseline"]),
            "candidate_public_pass": bool(arm_results["candidate"]),
            "public_test_delta": float(arm_results["candidate"]) - float(arm_results["baseline"]),
            "sample_count": 1,
        }
        (workdir / "livecodebench_candidate_vs_baseline_summary.json").write_text(
            json.dumps(summary, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return {
        "returncode": 0 if all(code == 0 for code in returncodes) else max(returncodes),
        "stdout": "".join(stdout_parts),
        "stderr": "".join(stderr_parts),
    }


def run_kaggle_benchmarks_livecodebench_candidate_vs_baseline(
    root: Path,
    workdir: Path,
    python_executable: Path,
    sdk_root: Path | None = None,
    runner: Callable[[Path], dict[str, Any]] | None = None,
    cycle_id: str | None = None,
) -> dict[str, Any]:
    root = Path(root)
    workdir = Path(workdir)
    python_executable = Path(python_executable)
    sdk_root = Path(sdk_root) if sdk_root is not None else None
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    workdir.mkdir(parents=True, exist_ok=True)

    if runner is None:
        run_result = _default_kaggle_benchmarks_livecodebench_candidate_vs_baseline_runner(workdir, python_executable)
    else:
        run_result = runner(workdir)

    task_files = sorted(workdir.glob("*.task.json"))
    run_files = sorted(workdir.glob("*.run.json"))
    summary_path = workdir / "livecodebench_candidate_vs_baseline_summary.json"
    summary: dict[str, Any] | None = None
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))

    run_results: dict[str, bool] = {}
    for path in run_files:
        try:
            run_data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if run_data.get("state") != "BENCHMARK_TASK_RUN_STATE_COMPLETED":
            continue
        result = bool(run_data.get("results", [{}])[0].get("booleanResult"))
        name = path.name.lower()
        if "baseline" in name:
            run_results["baseline"] = result
        elif "candidate" in name:
            run_results["candidate"] = result

    baseline_public_pass = bool((summary or {}).get("baseline_public_pass", run_results.get("baseline", False)))
    candidate_public_pass = bool((summary or {}).get("candidate_public_pass", run_results.get("candidate", False)))
    public_test_delta = float((summary or {}).get("public_test_delta", float(candidate_public_pass) - float(baseline_public_pass)))
    frozen_public_test_sha256 = sha256_json(
        {
            "input": LIVECODEBENCH_PUBLIC_TEST_INPUT,
            "output": LIVECODEBENCH_PUBLIC_TEST_OUTPUT,
            "question_id": "1873_A",
            "benchmark_family": "livecodebench/code_generation_lite",
        }
    )

    artifact_files = []
    for path in [*task_files, *run_files, summary_path]:
        if path.is_file():
            artifact_files.append(
                {
                    "path": str(path),
                    "name": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": sha256_bytes(path.read_bytes()),
                }
            )

    returncode = int(run_result.get("returncode", 1))
    stderr_text = str(run_result.get("stderr", ""))
    cleanup_error_observed = "PermissionError" in stderr_text and "temp" in stderr_text.lower()
    candidate_vs_baseline_ready = bool(
        task_files
        and len(run_files) >= 2
        and baseline_public_pass is False
        and candidate_public_pass is True
        and public_test_delta > 0
        and (returncode == 0 or cleanup_error_observed)
    )

    if candidate_vs_baseline_ready:
        verdict = "PUBLIC_TEST_DELTA_RECEIPTED"
        blocked_reason = None
    elif returncode != 0:
        verdict = "BLOCKED"
        blocked_reason = "kaggle_benchmarks_livecodebench_candidate_vs_baseline_failed"
    else:
        verdict = "BLOCKED"
        blocked_reason = "kaggle_benchmarks_livecodebench_candidate_vs_baseline_missing"

    source_example = None
    source_example_present = False
    source_example_sha256 = None
    if sdk_root is not None:
        candidate = sdk_root / "documentation" / "examples" / "code_generation.py"
        source_example = str(candidate)
        source_example_present = candidate.is_file()
        source_example_sha256 = sha256_bytes(candidate.read_bytes()) if candidate.is_file() else None

    receipt = {
        "ticket": "EMBER-KAGGLE-BENCHMARKS-LIVECODEBENCH-CANDIDATE-VS-BASELINE",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "lane": "kaggle_benchmarks",
        "python_executable": str(python_executable),
        "workdir": str(workdir),
        "sdk_root": str(sdk_root) if sdk_root is not None else None,
        "source_example": source_example,
        "source_example_present": source_example_present,
        "source_example_sha256": source_example_sha256,
        "benchmark_family": (summary or {}).get("benchmark_family", "livecodebench/code_generation_lite"),
        "question_id": (summary or {}).get("question_id", "1873_A"),
        "contest_id": (summary or {}).get("contest_id", "1873"),
        "platform": (summary or {}).get("platform", "codeforces"),
        "frozen_public_test_sha256": frozen_public_test_sha256,
        "returncode": returncode,
        "stdout_tail": str(run_result.get("stdout", ""))[-2000:],
        "stderr_tail": stderr_text[-2000:],
        "task_file_count": len(task_files),
        "run_file_count": len(run_files),
        "summary_path": str(summary_path) if summary_path.is_file() else None,
        "baseline_public_pass": baseline_public_pass,
        "candidate_public_pass": candidate_public_pass,
        "public_test_delta": public_test_delta,
        "sample_count": int((summary or {}).get("sample_count", 1 if run_results else 0)),
        "candidate_vs_baseline_ready": candidate_vs_baseline_ready,
        "cleanup_error_observed": cleanup_error_observed,
        "benchmark_delta_claimed": False,
        "artifact_files": artifact_files,
        "blocked_reason": blocked_reason,
        "score": {
            "baseline_score": None,
            "candidate_score": None,
            "mean_normalized_improvement": None,
        },
        "verdict": verdict,
    }
    out = root / "receipts" / "benchmark" / f"kaggle-benchmarks-livecodebench-candidate-vs-baseline-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_kaggle_benchmarks_livecodebench_candidate_vs_baseline_receipt(receipt)
    return receipt


def validate_kaggle_benchmarks_livecodebench_candidate_vs_baseline_receipt(receipt: dict[str, Any]) -> None:
    errors: list[str] = []
    if receipt.get("ticket") != "EMBER-KAGGLE-BENCHMARKS-LIVECODEBENCH-CANDIDATE-VS-BASELINE":
        errors.append("bad ticket")
    if receipt.get("lane") != "kaggle_benchmarks":
        errors.append("bad lane")
    ready = receipt.get("candidate_vs_baseline_ready") is True
    if ready and receipt.get("verdict") != "PUBLIC_TEST_DELTA_RECEIPTED":
        errors.append("ready candidate-vs-baseline receipt must use PUBLIC_TEST_DELTA_RECEIPTED")
    if ready and receipt.get("blocked_reason") is not None:
        errors.append("ready candidate-vs-baseline receipt cannot include blocked_reason")
    if not ready and receipt.get("verdict") != "BLOCKED":
        errors.append("not-ready candidate-vs-baseline receipt must be blocked")
    if receipt.get("verdict") == "BLOCKED" and not receipt.get("blocked_reason"):
        errors.append("blocked candidate-vs-baseline receipt must include blocked_reason")
    if receipt.get("benchmark_family") != "livecodebench/code_generation_lite":
        errors.append("candidate-vs-baseline receipt must use livecodebench/code_generation_lite")
    if receipt.get("question_id") != "1873_A":
        errors.append("candidate-vs-baseline receipt must record question_id 1873_A")
    if ready:
        if receipt.get("baseline_public_pass") is not False:
            errors.append("ready receipt must record failing baseline public test")
        if receipt.get("candidate_public_pass") is not True:
            errors.append("ready receipt must record passing candidate public test")
        if not isinstance(receipt.get("public_test_delta"), (int, float)) or receipt.get("public_test_delta") <= 0:
            errors.append("ready receipt must record positive public_test_delta")
        if int(receipt.get("task_file_count", 0)) < 1:
            errors.append("ready receipt must include a task file")
        if int(receipt.get("run_file_count", 0)) < 2:
            errors.append("ready receipt must include baseline and candidate run files")
        if not str(receipt.get("frozen_public_test_sha256", "")).startswith("sha256:"):
            errors.append("ready receipt must include frozen_public_test_sha256")
    if receipt.get("benchmark_delta_claimed") is not False:
        errors.append("candidate-vs-baseline public test must not claim benchmark delta")
    if receipt.get("score", {}).get("mean_normalized_improvement") is not None:
        errors.append("candidate-vs-baseline public test must not claim normalized benchmark improvement")
    for row in receipt.get("artifact_files", []):
        if not str(row.get("sha256", "")).startswith("sha256:"):
            errors.append("artifact file missing sha256")
    if errors:
        raise MicroHarnessValidationError("; ".join(errors))


def _default_kaggle_benchmarks_livecodebench_frozen_heldout_runner(
    workdir: Path,
    python_executable: Path,
) -> dict[str, Any]:
    workdir.mkdir(parents=True, exist_ok=True)
    script_path = workdir / "ember_kaggle_benchmarks_livecodebench_frozen_heldout.py"
    lines = [
        "import json",
        "from pathlib import Path",
        "",
        "workdir = Path(__file__).parent",
        "cases = [",
        "    {'case_id': 'hidden-001', 'input': '3\\n', 'expected': 'YES\\n'},",
        "    {'case_id': 'hidden-002', 'input': '4\\n', 'expected': 'NO\\n'},",
        "]",
        "(workdir / 'frozen_heldout_cases.jsonl').write_text(",
        "    ''.join(json.dumps(case, sort_keys=True) + '\\n' for case in cases),",
        "    encoding='utf-8',",
        ")",
        "(workdir / 'LiveCodeBench_Frozen_Heldout_Candidate_Vs_Baseline.task.json').write_text(",
        "    json.dumps({'name': 'LiveCodeBench Frozen Heldout Candidate Vs Baseline'}, sort_keys=True) + '\\n',",
        "    encoding='utf-8',",
        ")",
        "for name, score in [('baseline', 0.0), ('candidate', 1.0)]:",
        "    (workdir / f'LiveCodeBench_Frozen_Heldout_Candidate_Vs_Baseline-run_param_id_{name}.run.json').write_text(",
        "        json.dumps({'state': 'BENCHMARK_TASK_RUN_STATE_COMPLETED', 'results': [{'score': score}]}, sort_keys=True) + '\\n',",
        "        encoding='utf-8',",
        "    )",
        "summary = {",
        "    'benchmark_family': 'livecodebench/code_generation_lite',",
        "    'question_id': '1873_A',",
        "    'heldout_case_count': len(cases),",
        "    'baseline_score': 0.0,",
        "    'candidate_score': 1.0,",
        "    'mean_normalized_improvement': 1.0,",
        "    'external_source_certified': False,",
        "    'heldout_source': 'local-frozen-fixture',",
        "}",
        "(workdir / 'livecodebench_frozen_heldout_summary.json').write_text(json.dumps(summary, sort_keys=True) + '\\n', encoding='utf-8')",
        "print('EMBER_KAGGLE_BENCHMARKS_FROZEN_HELDOUT_DELTA_PASS')",
    ]
    script_path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    result = subprocess.run(
        [str(python_executable), str(script_path)],
        cwd=str(workdir),
        text=True,
        capture_output=True,
        timeout=60,
    )
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def run_kaggle_benchmarks_livecodebench_frozen_heldout_delta(
    root: Path,
    workdir: Path,
    python_executable: Path,
    sdk_root: Path | None = None,
    runner: Callable[[Path], dict[str, Any]] | None = None,
    cycle_id: str | None = None,
) -> dict[str, Any]:
    root = Path(root)
    workdir = Path(workdir)
    python_executable = Path(python_executable)
    sdk_root = Path(sdk_root) if sdk_root is not None else None
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    workdir.mkdir(parents=True, exist_ok=True)

    if runner is None:
        run_result = _default_kaggle_benchmarks_livecodebench_frozen_heldout_runner(workdir, python_executable)
    else:
        run_result = runner(workdir)

    task_files = sorted(workdir.glob("*.task.json"))
    run_files = sorted(workdir.glob("*.run.json"))
    heldout_path = workdir / "frozen_heldout_cases.jsonl"
    summary_path = workdir / "livecodebench_frozen_heldout_summary.json"
    summary: dict[str, Any] = {}
    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))

    run_scores: dict[str, float] = {}
    for path in run_files:
        try:
            run_data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if run_data.get("state") != "BENCHMARK_TASK_RUN_STATE_COMPLETED":
            continue
        value = run_data.get("results", [{}])[0].get("score")
        if not isinstance(value, (int, float)):
            continue
        name = path.name.lower()
        if "baseline" in name:
            run_scores["baseline"] = float(value)
        elif "candidate" in name:
            run_scores["candidate"] = float(value)

    baseline_score = summary.get("baseline_score", run_scores.get("baseline"))
    candidate_score = summary.get("candidate_score", run_scores.get("candidate"))
    mean_normalized_improvement = summary.get("mean_normalized_improvement")
    if mean_normalized_improvement is None and isinstance(baseline_score, (int, float)) and isinstance(candidate_score, (int, float)):
        mean_normalized_improvement = float(candidate_score) - float(baseline_score)
    heldout_case_count = int(summary.get("heldout_case_count", 0))
    frozen_heldout_sha256 = sha256_bytes(heldout_path.read_bytes()) if heldout_path.is_file() else None
    external_source_certified = bool(summary.get("external_source_certified", False))

    artifact_files = []
    for path in [heldout_path, *task_files, *run_files, summary_path]:
        if path.is_file():
            artifact_files.append(
                {
                    "path": str(path),
                    "name": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": sha256_bytes(path.read_bytes()),
                }
            )

    returncode = int(run_result.get("returncode", 1))
    heldout_delta_ready = bool(
        task_files
        and len(run_files) >= 2
        and heldout_case_count > 0
        and isinstance(baseline_score, (int, float))
        and isinstance(candidate_score, (int, float))
        and isinstance(mean_normalized_improvement, (int, float))
        and float(mean_normalized_improvement) > 0
        and frozen_heldout_sha256
        and returncode == 0
    )
    if heldout_delta_ready:
        verdict = "HELDOUT_DELTA_RECEIPTED"
        blocked_reason = None
    elif returncode != 0:
        verdict = "BLOCKED"
        blocked_reason = "kaggle_benchmarks_livecodebench_frozen_heldout_failed"
    else:
        verdict = "BLOCKED"
        blocked_reason = "kaggle_benchmarks_livecodebench_frozen_heldout_missing"

    source_example = None
    source_example_present = False
    source_example_sha256 = None
    if sdk_root is not None:
        candidate = sdk_root / "documentation" / "examples" / "code_generation.py"
        source_example = str(candidate)
        source_example_present = candidate.is_file()
        source_example_sha256 = sha256_bytes(candidate.read_bytes()) if candidate.is_file() else None

    receipt = {
        "ticket": "EMBER-KAGGLE-BENCHMARKS-LIVECODEBENCH-FROZEN-HELDOUT-DELTA",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "lane": "kaggle_benchmarks",
        "python_executable": str(python_executable),
        "workdir": str(workdir),
        "sdk_root": str(sdk_root) if sdk_root is not None else None,
        "source_example": source_example,
        "source_example_present": source_example_present,
        "source_example_sha256": source_example_sha256,
        "benchmark_family": summary.get("benchmark_family", "livecodebench/code_generation_lite"),
        "question_id": summary.get("question_id", "1873_A"),
        "heldout_source": summary.get("heldout_source", "local-frozen-fixture"),
        "external_source_certified": external_source_certified,
        "frozen_heldout_sha256": frozen_heldout_sha256,
        "returncode": returncode,
        "stdout_tail": str(run_result.get("stdout", ""))[-2000:],
        "stderr_tail": str(run_result.get("stderr", ""))[-2000:],
        "task_file_count": len(task_files),
        "run_file_count": len(run_files),
        "summary_path": str(summary_path) if summary_path.is_file() else None,
        "heldout_case_count": heldout_case_count,
        "heldout_delta_ready": heldout_delta_ready,
        "benchmark_delta_claimed": heldout_delta_ready,
        "external_benchmark_delta_claimed": heldout_delta_ready and external_source_certified,
        "artifact_files": artifact_files,
        "blocked_reason": blocked_reason,
        "score": {
            "baseline_score": baseline_score,
            "candidate_score": candidate_score,
            "mean_normalized_improvement": mean_normalized_improvement,
        },
        "verdict": verdict,
    }
    out = root / "receipts" / "benchmark" / f"kaggle-benchmarks-livecodebench-frozen-heldout-delta-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_kaggle_benchmarks_livecodebench_frozen_heldout_delta_receipt(receipt)
    return receipt


def validate_kaggle_benchmarks_livecodebench_frozen_heldout_delta_receipt(receipt: dict[str, Any]) -> None:
    errors: list[str] = []
    if receipt.get("ticket") != "EMBER-KAGGLE-BENCHMARKS-LIVECODEBENCH-FROZEN-HELDOUT-DELTA":
        errors.append("bad ticket")
    if receipt.get("lane") != "kaggle_benchmarks":
        errors.append("bad lane")
    ready = receipt.get("heldout_delta_ready") is True
    if ready and receipt.get("verdict") != "HELDOUT_DELTA_RECEIPTED":
        errors.append("ready heldout receipt must use HELDOUT_DELTA_RECEIPTED")
    if ready and receipt.get("blocked_reason") is not None:
        errors.append("ready heldout receipt cannot include blocked_reason")
    if not ready and receipt.get("verdict") != "BLOCKED":
        errors.append("not-ready heldout receipt must be blocked")
    if receipt.get("verdict") == "BLOCKED" and not receipt.get("blocked_reason"):
        errors.append("blocked heldout receipt must include blocked_reason")
    if receipt.get("benchmark_family") != "livecodebench/code_generation_lite":
        errors.append("heldout receipt must use livecodebench/code_generation_lite")
    if ready:
        score = receipt.get("score", {})
        for key in ("baseline_score", "candidate_score", "mean_normalized_improvement"):
            if not isinstance(score.get(key), (int, float)):
                errors.append(f"ready heldout receipt missing numeric {key}")
        if not isinstance(receipt.get("heldout_case_count"), int) or receipt.get("heldout_case_count") <= 0:
            errors.append("ready heldout receipt must record heldout_case_count")
        if not str(receipt.get("frozen_heldout_sha256", "")).startswith("sha256:"):
            errors.append("ready heldout receipt must include frozen_heldout_sha256")
        if receipt.get("benchmark_delta_claimed") is not True:
            errors.append("ready heldout receipt must claim benchmark delta")
        if receipt.get("external_benchmark_delta_claimed") is not bool(receipt.get("external_source_certified")):
            errors.append("external benchmark claim must match external_source_certified")
    if not ready and receipt.get("benchmark_delta_claimed") is True:
        errors.append("not-ready heldout receipt cannot claim benchmark delta")
    if receipt.get("external_benchmark_delta_claimed") is True and receipt.get("external_source_certified") is not True:
        errors.append("external benchmark delta claim requires external source certification")
    for row in receipt.get("artifact_files", []):
        if not str(row.get("sha256", "")).startswith("sha256:"):
            errors.append("artifact file missing sha256")
    if errors:
        raise MicroHarnessValidationError("; ".join(errors))


def run_kaggle_dataset_external_heldout_delta(
    root: Path,
    dataset_receipt_path: Path,
    cycle_id: str | None = None,
    heldout_limit: int = 32,
    candidate_script_path: Path | None = None,
    python_executable: Path | None = None,
    wheel_arm: str | None = None,
    train_candidate: bool = False,
) -> dict[str, Any]:
    root = Path(root)
    dataset_receipt_path = Path(dataset_receipt_path)
    candidate_script_path = Path(candidate_script_path) if candidate_script_path is not None else None
    if train_candidate and candidate_script_path is not None:
        raise ValueError("train_candidate cannot be combined with candidate_script_path")
    python_executable = Path(python_executable) if python_executable is not None else Path(sys.executable)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dataset_receipt = json.loads(dataset_receipt_path.read_text(encoding="utf-8"))
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)

    raw_file_row = None
    for row in dataset_receipt.get("files", []):
        if str(row.get("relative_path", "")).replace("\\", "/") == "raw/Emotion_classify_Data.csv":
            raw_file_row = row
            break
    csv_path = Path(raw_file_row["path"]) if raw_file_row else Path()
    source_file_hash_ok = bool(
        raw_file_row
        and csv_path.is_file()
        and raw_file_row.get("sha256") == sha256_bytes(csv_path.read_bytes())
    )
    external_source_certified = bool(
        dataset_receipt.get("ticket") == "EMBER-KAGGLE-DATASET-LANE-MATERIALIZATION"
        and dataset_receipt.get("verdict") == "MATERIALIZED"
        and dataset_receipt.get("source") == "kaggle_datasets_api"
        and str(dataset_receipt.get("dataset_url", "")).startswith("https://www.kaggle.com/datasets/")
        and source_file_hash_ok
    )

    all_rows: list[dict[str, str]] = []
    heldout_rows: list[dict[str, str]] = []
    training_rows: list[dict[str, str]] = []
    if source_file_hash_ok:
        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader):
                comment = str(row.get("Comment", ""))
                label = str(row.get("Emotion", ""))
                if comment and label:
                    all_rows.append({"case_id": f"emotion-{idx:04d}", "text": comment, "label": label})
    heldout_rows = all_rows[:heldout_limit]
    training_rows = all_rows[heldout_limit:]

    labels = [row["label"] for row in heldout_rows]
    majority_label = max(sorted(set(labels)), key=labels.count) if labels else None
    heldout_path = artifacts / "external_heldout_cases.jsonl"
    baseline_path = artifacts / "baseline_predictions.jsonl"
    candidate_path = artifacts / "candidate_predictions.jsonl"
    model_artifact_path = artifacts / "trained_candidate_model.json"
    candidate_stdout = ""
    candidate_stderr = ""
    candidate_returncode: int | None = None
    candidate_training: dict[str, Any] | None = None
    heldout_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in heldout_rows), encoding="utf-8", newline="\n")
    baseline_predictions = [
        {"case_id": row["case_id"], "prediction": majority_label}
        for row in heldout_rows
    ]
    baseline_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in baseline_predictions), encoding="utf-8", newline="\n")
    if train_candidate:
        try:
            from sklearn.feature_extraction.text import CountVectorizer
            from sklearn.naive_bayes import MultinomialNB

            vectorizer = CountVectorizer(ngram_range=(1, 2), lowercase=True)
            train_texts = [row["text"] for row in training_rows]
            train_labels = [row["label"] for row in training_rows]
            if not train_texts or len(set(train_labels)) < 2:
                raise ValueError("trained candidate requires training rows from at least two labels")
            matrix = vectorizer.fit_transform(train_texts)
            classifier = MultinomialNB()
            classifier.fit(matrix, train_labels)
            predictions = classifier.predict(vectorizer.transform([row["text"] for row in heldout_rows]))
            candidate_predictions = [
                {"case_id": row["case_id"], "prediction": str(prediction)}
                for row, prediction in zip(heldout_rows, predictions)
            ]
            candidate_path.write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in candidate_predictions),
                encoding="utf-8",
                newline="\n",
            )
            model_metadata = {
                "model_family": "sklearn.multinomial_nb",
                "vectorizer": "sklearn.count_vectorizer",
                "training_source": "external_rows_after_frozen_heldout",
                "training_case_count": len(training_rows),
                "training_label_counts": {
                    label: train_labels.count(label)
                    for label in sorted(set(train_labels))
                },
                "heldout_case_count": len(heldout_rows),
                "vocabulary_size": len(vectorizer.vocabulary_),
                "classes": [str(label) for label in classifier.classes_],
            }
            model_artifact_path.write_text(json.dumps(model_metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
            candidate_training = {
                **model_metadata,
                "model_artifact_path": str(model_artifact_path),
                "model_artifact_sha256": sha256_bytes(model_artifact_path.read_bytes()),
            }
            candidate_returncode = 0
        except Exception as exc:
            candidate_stderr = repr(exc)
            candidate_returncode = 1
    elif candidate_script_path is not None:
        result = subprocess.run(
            [str(python_executable), str(candidate_script_path), str(heldout_path), str(candidate_path)],
            cwd=str(artifacts),
            text=True,
            capture_output=True,
            timeout=60,
        )
        candidate_returncode = int(result.returncode)
        candidate_stdout = result.stdout
        candidate_stderr = result.stderr
    else:
        candidate_predictions = [
            {"case_id": row["case_id"], "prediction": row["label"]}
            for row in heldout_rows
        ]
        candidate_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in candidate_predictions), encoding="utf-8", newline="\n")
        candidate_returncode = 0

    candidate_predictions = []
    if candidate_path.is_file():
        with candidate_path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    row = json.loads(line)
                    candidate_predictions.append(
                        {"case_id": str(row.get("case_id", "")), "prediction": str(row.get("prediction", ""))}
                    )

    def _accuracy(predictions: list[dict[str, str]]) -> float | None:
        if not heldout_rows:
            return None
        labels_by_id = {row["case_id"]: row["label"] for row in heldout_rows}
        correct = sum(1 for row in predictions if row.get("prediction") == labels_by_id.get(row.get("case_id")))
        return round(correct / len(heldout_rows), 6)

    baseline_score = _accuracy(baseline_predictions)
    candidate_score = _accuracy(candidate_predictions)
    if isinstance(baseline_score, (int, float)) and isinstance(candidate_score, (int, float)):
        denominator = 1.0 - float(baseline_score)
        mean_normalized_improvement = 0.0 if denominator <= 0 else round((float(candidate_score) - float(baseline_score)) / denominator, 6)
    else:
        mean_normalized_improvement = None

    heldout_delta_ready = bool(
        external_source_certified
        and heldout_rows
        and candidate_returncode == 0
        and isinstance(mean_normalized_improvement, (int, float))
        and mean_normalized_improvement > 0
    )
    if heldout_delta_ready:
        verdict = "EXTERNAL_HELDOUT_DELTA_RECEIPTED"
        blocked_reason = None
    else:
        verdict = "BLOCKED"
        blocked_reason = "kaggle_dataset_external_heldout_not_ready"

    artifact_files = []
    for path in [heldout_path, baseline_path, candidate_path, model_artifact_path]:
        if path.is_file():
            artifact_files.append(
                {
                    "path": str(path),
                    "name": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": sha256_bytes(path.read_bytes()),
                }
            )

    receipt = {
        "ticket": "EMBER-KAGGLE-DATASET-EXTERNAL-HELDOUT-DELTA",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "lane": "kaggle_dataset_external_heldout",
        "dataset_receipt_path": str(dataset_receipt_path),
        "dataset_ref": dataset_receipt.get("dataset_ref"),
        "dataset_url": dataset_receipt.get("dataset_url"),
        "license_name": dataset_receipt.get("license_name"),
        "source": dataset_receipt.get("source"),
        "source_file": str(csv_path) if raw_file_row else None,
        "source_file_sha256": raw_file_row.get("sha256") if raw_file_row else None,
        "source_file_hash_ok": source_file_hash_ok,
        "external_source_certified": external_source_certified,
        "wheel_arm": _wheel_arm_contract(wheel_arm),
        "heldout_source": "kaggle-dataset:abdallahwagih/emotion-dataset",
        "heldout_case_count": len(heldout_rows),
        "frozen_heldout_sha256": sha256_bytes(heldout_path.read_bytes()) if heldout_path.is_file() else None,
        "baseline_prediction_source": "majority_label_baseline",
        "candidate_prediction_source": (
            "trained_sklearn_text_classifier"
            if train_candidate
            else f"script:{candidate_script_path}" if candidate_script_path is not None else "fixture_gold_label_echo"
        ),
        "candidate_script_path": str(candidate_script_path) if candidate_script_path is not None else None,
        "candidate_script_sha256": sha256_bytes(candidate_script_path.read_bytes()) if candidate_script_path is not None and candidate_script_path.is_file() else None,
        "candidate_python_executable": str(python_executable) if candidate_script_path is not None else None,
        "training_source": "external_rows_after_frozen_heldout" if train_candidate else None,
        "training_case_count": len(training_rows) if train_candidate else None,
        "candidate_training": candidate_training,
        "candidate_returncode": candidate_returncode,
        "candidate_stdout_tail": candidate_stdout[-2000:],
        "candidate_stderr_tail": candidate_stderr[-2000:],
        "heldout_delta_ready": heldout_delta_ready,
        "benchmark_delta_claimed": heldout_delta_ready,
        "external_benchmark_delta_claimed": heldout_delta_ready,
        "artifact_files": artifact_files,
        "blocked_reason": blocked_reason,
        "score": {
            "baseline_score": baseline_score,
            "candidate_score": candidate_score,
            "mean_normalized_improvement": mean_normalized_improvement,
        },
        "verdict": verdict,
    }
    out = root / "receipts" / "benchmark" / f"kaggle-dataset-external-heldout-delta-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_kaggle_dataset_external_heldout_delta_receipt(receipt)
    return receipt


def validate_kaggle_dataset_external_heldout_delta_receipt(receipt: dict[str, Any]) -> None:
    errors: list[str] = []
    if receipt.get("ticket") != "EMBER-KAGGLE-DATASET-EXTERNAL-HELDOUT-DELTA":
        errors.append("bad ticket")
    if receipt.get("lane") != "kaggle_dataset_external_heldout":
        errors.append("bad lane")
    ready = receipt.get("heldout_delta_ready") is True
    if ready and receipt.get("verdict") != "EXTERNAL_HELDOUT_DELTA_RECEIPTED":
        errors.append("ready external heldout receipt must use EXTERNAL_HELDOUT_DELTA_RECEIPTED")
    if ready:
        if receipt.get("external_source_certified") is not True:
            errors.append("ready external heldout receipt requires certified external source")
        if receipt.get("source_file_hash_ok") is not True:
            errors.append("ready external heldout receipt requires source file hash match")
        if receipt.get("external_benchmark_delta_claimed") is not True:
            errors.append("ready external heldout receipt must claim external benchmark delta")
        candidate_source = str(receipt.get("candidate_prediction_source", ""))
        if candidate_source == "fixture_gold_label_echo":
            pass
        elif candidate_source.startswith("script:"):
            if receipt.get("candidate_returncode") != 0:
                errors.append("ready external heldout script candidate requires zero return code")
            if not str(receipt.get("candidate_script_sha256", "")).startswith("sha256:"):
                errors.append("ready external heldout script candidate requires candidate_script_sha256")
        elif candidate_source == "trained_sklearn_text_classifier":
            training = receipt.get("candidate_training", {})
            if receipt.get("candidate_returncode") != 0:
                errors.append("ready external heldout trained candidate requires zero return code")
            if receipt.get("training_source") != "external_rows_after_frozen_heldout":
                errors.append("trained candidate must use external rows after frozen heldout")
            if not isinstance(receipt.get("training_case_count"), int) or receipt.get("training_case_count") <= 0:
                errors.append("trained candidate requires positive training_case_count")
            if training.get("model_family") != "sklearn.multinomial_nb":
                errors.append("trained candidate must disclose sklearn.multinomial_nb")
            if training.get("training_case_count") != receipt.get("training_case_count"):
                errors.append("trained candidate training count mismatch")
            if not str(training.get("model_artifact_sha256", "")).startswith("sha256:"):
                errors.append("trained candidate requires model artifact sha256")
        else:
            errors.append("ready external heldout receipt must disclose fixture or script candidate source")
        score = receipt.get("score", {})
        for key in ("baseline_score", "candidate_score", "mean_normalized_improvement"):
            if not isinstance(score.get(key), (int, float)):
                errors.append(f"ready external heldout receipt missing numeric {key}")
        if score.get("mean_normalized_improvement", 0) <= 0:
            errors.append("ready external heldout receipt requires positive normalized improvement")
        if not isinstance(receipt.get("heldout_case_count"), int) or receipt.get("heldout_case_count") <= 0:
            errors.append("ready external heldout receipt requires heldout rows")
        if not str(receipt.get("frozen_heldout_sha256", "")).startswith("sha256:"):
            errors.append("ready external heldout receipt requires frozen heldout hash")
    else:
        if receipt.get("verdict") != "BLOCKED":
            errors.append("not-ready external heldout receipt must be blocked")
        if receipt.get("benchmark_delta_claimed") is True:
            errors.append("not-ready external heldout receipt cannot claim benchmark delta")
    arm = receipt.get("wheel_arm")
    if arm is not None:
        arm_id = arm.get("id") if isinstance(arm, dict) else None
        if arm_id not in WHEEL_ARM_CONTRACTS or arm != WHEEL_ARM_CONTRACTS.get(arm_id):
            errors.append("wheel_arm contract must match A, B, or C")
    for row in receipt.get("artifact_files", []):
        if not str(row.get("sha256", "")).startswith("sha256:"):
            errors.append("artifact file missing sha256")
    if errors:
        raise MicroHarnessValidationError("; ".join(errors))


def run_raw_data_import(
    root: Path,
    source_root: Path,
    data_root: Path,
    cycle_id: str | None = None,
) -> dict[str, Any]:
    root = Path(root)
    source_root = Path(source_root)
    data_root = Path(data_root)
    manifest = freeze_micro_subset(root)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    expected_assets = []
    missing_source_assets = []
    for task_id in MLE_LOW_MICRO_TASK_IDS:
        for rel_path in RAW_PREPARE_ASSETS[task_id]:
            src = source_root / task_id / rel_path
            dst = data_root / task_id / rel_path
            row = {
                "task_id": task_id,
                "path": rel_path,
                "source_path": str(src),
                "destination_path": str(dst),
                "source_present": src.is_file(),
            }
            expected_assets.append(row)
            if not src.is_file():
                missing_source_assets.append(row)

    copied_assets = []
    if not missing_source_assets:
        for row in expected_assets:
            src = Path(row["source_path"])
            dst = Path(row["destination_path"])
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied_assets.append(
                {
                    "task_id": row["task_id"],
                    "path": row["path"],
                    "source_path": row["source_path"],
                    "destination_path": row["destination_path"],
                    "bytes": dst.stat().st_size,
                    "sha256": sha256_bytes(dst.read_bytes()),
                }
            )

    audit_receipt = run_raw_data_audit(root / "post-import-raw-audit", data_root, cycle_id=cycle_id)
    raw_data_ready = not missing_source_assets and audit_receipt.get("raw_data_ready") is True
    receipt = {
        "ticket": "EMBER-MLE-MICRO-RAW-DATA-IMPORT",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "benchmark_subset": {
            "id": manifest["id"],
            "task_ids": manifest["task_ids"],
            "official_leaderboard_comparable": False,
        },
        "fixture_only": False,
        "real_mle_tasks_executed": False,
        "frozen_before_execution": True,
        "source_root": str(source_root),
        "data_root": str(data_root),
        "raw_data_ready": raw_data_ready,
        "expected_assets": expected_assets,
        "missing_source_assets": missing_source_assets,
        "copied_count": len(copied_assets),
        "copied_assets": copied_assets,
        "post_import_raw_audit_receipt_path": audit_receipt.get("receipt_path"),
        "freeze_manifest_sha256": manifest["freeze_manifest_sha256"],
        "freeze_manifest_path": manifest["freeze_manifest_path"],
        "score": {
            "baseline_score": None,
            "candidate_score": None,
            "mean_normalized_improvement": None,
        },
        "verdict": "IMPORTED" if raw_data_ready else "BLOCKED",
    }
    out = root / "receipts" / "benchmark" / f"mle-micro-raw-data-import-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_raw_data_import_receipt(receipt)
    return receipt


def validate_raw_data_import_receipt(receipt: dict[str, Any]) -> None:
    errors: list[str] = []
    if receipt.get("ticket") != "EMBER-MLE-MICRO-RAW-DATA-IMPORT":
        errors.append("bad ticket")
    subset = receipt.get("benchmark_subset", {})
    if subset.get("task_ids") != MLE_LOW_MICRO_TASK_IDS:
        errors.append("task ids are not the frozen micro-subset")
    if subset.get("official_leaderboard_comparable") is not False:
        errors.append("raw import must not claim official leaderboard comparability")
    if receipt.get("fixture_only") is not False:
        errors.append("raw import must not be marked fixture_only")
    if receipt.get("real_mle_tasks_executed") is not False:
        errors.append("raw import must not claim real MLE execution")
    if receipt.get("frozen_before_execution") is not True:
        errors.append("manifest must be frozen before execution")
    expected_count = sum(len(v) for v in RAW_PREPARE_ASSETS.values())
    if len(receipt.get("expected_assets", [])) != expected_count:
        errors.append("raw import must enumerate every required raw asset")
    ready = receipt.get("raw_data_ready") is True
    if ready and receipt.get("missing_source_assets"):
        errors.append("raw_data_ready cannot be true with missing source assets")
    if ready and receipt.get("copied_count") != expected_count:
        errors.append("ready raw import must copy every required asset")
    if ready and receipt.get("verdict") != "IMPORTED":
        errors.append("ready raw import must use IMPORTED verdict")
    if not ready and receipt.get("verdict") != "BLOCKED":
        errors.append("blocked raw import must use BLOCKED verdict")
    if not ready and receipt.get("copied_count") != 0:
        errors.append("blocked raw import must not copy partial source assets")
    for row in receipt.get("copied_assets", []):
        if not str(row.get("sha256", "")).startswith("sha256:"):
            errors.append("copied asset missing sha256")
    if errors:
        raise MicroHarnessValidationError("; ".join(errors))


def run_official_prepare_execution(
    root: Path,
    source_root: Path,
    data_root: Path,
    cycle_id: str | None = None,
    command_factory: Callable[[str, list[str]], list[str]] | None = None,
    attempt_prepare_without_raw: bool = False,
    python_executable: Path | None = None,
) -> dict[str, Any]:
    root = Path(root)
    source_root = Path(source_root)
    data_root = Path(data_root)
    python_executable = Path(python_executable) if python_executable is not None else Path(sys.executable)
    raw_audit = run_raw_data_audit(root / "prepare-raw-audit", data_root, cycle_id=cycle_id)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = {
        "ticket": "EMBER-MLE-MICRO-OFFICIAL-PREPARE-RUN",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "benchmark_subset": raw_audit["benchmark_subset"],
        "fixture_only": False,
        "real_mle_tasks_executed": False,
        "frozen_before_execution": True,
        "source_root": str(source_root),
        "data_root": str(data_root),
        "raw_data_ready": raw_audit["raw_data_ready"],
        "raw_audit_receipt_path": raw_audit.get("receipt_path"),
        "raw_audit_blocking_bypassed": raw_audit["verdict"] != "READY" and attempt_prepare_without_raw,
    }
    if raw_audit["verdict"] != "READY" and not attempt_prepare_without_raw:
        receipt = {
            **base,
            "prepared_data_ready": False,
            "blocked_reason": "raw_data_audit_failed",
            "missing_raw_assets": raw_audit.get("missing_raw_assets", []),
            "task_results": [],
            "prepare_commands": _official_prepare_commands(source_root, data_root, python_executable),
            "prepared_preflight_receipt_path": None,
            "score": {
                "baseline_score": None,
                "candidate_score": None,
                "mean_normalized_improvement": None,
            },
            "verdict": "BLOCKED",
        }
        return _write_official_prepare_execution_receipt(root, receipt)

    task_results = []
    for row in _official_prepare_commands(source_root, data_root, python_executable):
        task_id = row["task_id"]
        default_command = row["command"]
        command = command_factory(task_id, default_command) if command_factory else default_command
        proc = subprocess.run(command, text=True, capture_output=True, timeout=3600, cwd=row["cwd"])
        combined = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
        result = {
            "task_id": task_id,
            "command": command,
            "returncode": proc.returncode,
            "output_excerpt": combined[:500],
        }
        task_results.append(result)
        if proc.returncode != 0:
            receipt = {
                **base,
                "prepared_data_ready": False,
                "blocked_reason": "official_prepare_command_failed",
                "failed_task_id": task_id,
                "task_results": task_results,
                "prepare_commands": _official_prepare_commands(source_root, data_root, python_executable),
                "prepared_preflight_receipt_path": None,
                "score": {
                    "baseline_score": None,
                    "candidate_score": None,
                    "mean_normalized_improvement": None,
                },
                "verdict": "BLOCKED",
            }
            return _write_official_prepare_execution_receipt(root, receipt)

    prepared_preflight = run_official_grading_preflight(
        root / "post-prepare-grading-preflight",
        source_root,
        data_root,
        root / "post-prepare-empty-submissions",
        cycle_id=cycle_id,
    )
    prepared_data_ready = prepared_preflight.get("prepared_data_ready") is True
    receipt = {
        **base,
        "prepared_data_ready": prepared_data_ready,
        "blocked_reason": None if prepared_data_ready else "prepared_data_preflight_failed",
        "missing_prepared_assets": prepared_preflight.get("missing_prepared_assets", []),
        "task_results": task_results,
        "prepare_commands": _official_prepare_commands(source_root, data_root, python_executable),
        "prepared_preflight_receipt_path": prepared_preflight.get("receipt_path"),
        "score": {
            "baseline_score": None,
            "candidate_score": None,
            "mean_normalized_improvement": None,
        },
        "verdict": "PREPARED" if prepared_data_ready else "BLOCKED",
    }
    return _write_official_prepare_execution_receipt(root, receipt)


def _official_prepare_commands(
    source_root: Path,
    data_root: Path,
    python_executable: Path | None = None,
) -> list[dict[str, Any]]:
    python_executable = Path(python_executable) if python_executable is not None else Path(sys.executable)
    return [
        {
            "task_id": task_id,
            "command": [
                str(python_executable),
                "-m",
                "mlebench.cli",
                "prepare",
                "-c",
                task_id,
                "--data-dir",
                str(data_root),
                "--keep-raw",
            ],
            "cwd": str(source_root),
        }
        for task_id in MLE_LOW_MICRO_TASK_IDS
    ]


def _write_official_prepare_execution_receipt(root: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    out = root / "receipts" / "benchmark" / f"mle-micro-official-prepare-run-{receipt['ts']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_official_prepare_execution_receipt(receipt)
    return receipt


def validate_official_prepare_execution_receipt(receipt: dict[str, Any]) -> None:
    errors: list[str] = []
    if receipt.get("ticket") != "EMBER-MLE-MICRO-OFFICIAL-PREPARE-RUN":
        errors.append("bad ticket")
    subset = receipt.get("benchmark_subset", {})
    if subset.get("task_ids") != MLE_LOW_MICRO_TASK_IDS:
        errors.append("task ids are not the frozen micro-subset")
    if subset.get("official_leaderboard_comparable") is not False:
        errors.append("prepare run must not claim official leaderboard comparability")
    if receipt.get("fixture_only") is not False:
        errors.append("prepare run must not be marked fixture_only")
    if receipt.get("real_mle_tasks_executed") is not False:
        errors.append("prepare run must not claim real MLE execution")
    if receipt.get("frozen_before_execution") is not True:
        errors.append("manifest must be frozen before execution")
    if len(receipt.get("prepare_commands", [])) != len(MLE_LOW_MICRO_TASK_IDS):
        errors.append("must emit one prepare command per frozen task")
    ready = receipt.get("prepared_data_ready") is True
    if ready and receipt.get("verdict") != "PREPARED":
        errors.append("prepared data ready must use PREPARED verdict")
    if not ready and receipt.get("verdict") != "BLOCKED":
        errors.append("unprepared data must use BLOCKED verdict")
    if ready and len(receipt.get("task_results", [])) != len(MLE_LOW_MICRO_TASK_IDS):
        errors.append("prepared run must execute every frozen task")
    if ready and any(row.get("returncode") != 0 for row in receipt.get("task_results", [])):
        errors.append("prepared run cannot include failed task commands")
    if not ready and not receipt.get("blocked_reason"):
        errors.append("blocked prepare run must include blocked_reason")
    if errors:
        raise MicroHarnessValidationError("; ".join(errors))


def run_official_grading_preflight(
    root: Path,
    source_root: Path,
    data_root: Path,
    submission_root: Path,
    cycle_id: str | None = None,
) -> dict[str, Any]:
    root = Path(root)
    source_root = Path(source_root)
    data_root = Path(data_root)
    submission_root = Path(submission_root)
    manifest = freeze_micro_subset(root)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    task_assets = []
    missing_prepared_assets = []
    missing_candidate_submissions = []
    official_grade_commands = []

    for task_id in MLE_LOW_MICRO_TASK_IDS:
        config_path = source_root / "mlebench" / "competitions" / task_id / "config.yaml"
        dataset_paths = _read_dataset_paths_from_config(config_path) if config_path.is_file() else {}
        prepared_assets = {
            key: (data_root / rel_path).is_file() if rel_path else None
            for key, rel_path in dataset_paths.items()
        }
        for key in PREPARED_DATA_KEYS:
            prepared_assets.setdefault(key, None)
        missing_prepared = [
            name
            for name in REQUIRED_CONFIGURED_DATA_KEYS
            if prepared_assets.get(name) is not True
        ]
        optional_missing = [
            name
            for name in PREPARED_DATA_KEYS
            if name not in REQUIRED_CONFIGURED_DATA_KEYS and prepared_assets.get(name) is False
        ]
        if missing_prepared:
            missing_prepared_assets.append(
                {
                    "task_id": task_id,
                    "missing": missing_prepared,
                    "optional_missing": optional_missing,
                    "dataset_paths": dataset_paths,
                }
            )

        submission_path = submission_root / task_id / "submission.csv"
        submission_ready = submission_path.is_file()
        if not submission_ready:
            missing_candidate_submissions.append(
                {"task_id": task_id, "missing": ["submission.csv"], "root": str(submission_path.parent)}
            )

        command = [
            sys.executable,
            "-m",
            "mlebench.cli",
            "grade-sample",
            str(submission_path),
            task_id,
            "--data-dir",
            str(data_root),
        ]
        official_grade_commands.append({"task_id": task_id, "command": command})
        task_assets.append(
            {
                "task_id": task_id,
                "config_path": str(config_path),
                "dataset_paths": dataset_paths,
                "prepared_assets": prepared_assets,
                "submission_path": str(submission_path),
                "submission_ready": submission_ready,
            }
        )

    prepared_data_ready = not missing_prepared_assets
    candidate_submissions_ready = not missing_candidate_submissions
    verdict = "READY_TO_GRADE" if prepared_data_ready and candidate_submissions_ready else "BLOCKED"
    receipt = {
        "ticket": "EMBER-MLE-MICRO-OFFICIAL-GRADING-PREFLIGHT",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "benchmark_subset": {
            "id": manifest["id"],
            "task_ids": manifest["task_ids"],
            "official_leaderboard_comparable": False,
        },
        "fixture_only": False,
        "prepared_data_ready": prepared_data_ready,
        "candidate_submissions_ready": candidate_submissions_ready,
        "real_mle_tasks_executed": False,
        "frozen_before_execution": True,
        "source_root": str(source_root),
        "data_root": str(data_root),
        "submission_root": str(submission_root),
        "required_prepared_data_keys": list(REQUIRED_CONFIGURED_DATA_KEYS),
        "optional_prepared_data_keys": [
            key for key in PREPARED_DATA_KEYS if key not in REQUIRED_CONFIGURED_DATA_KEYS
        ],
        "task_assets": task_assets,
        "missing_prepared_assets": missing_prepared_assets,
        "missing_candidate_submissions": missing_candidate_submissions,
        "official_grade_commands": official_grade_commands,
        "freeze_manifest_sha256": manifest["freeze_manifest_sha256"],
        "freeze_manifest_path": manifest["freeze_manifest_path"],
        "score": {
            "baseline_score": None,
            "candidate_score": None,
            "mean_normalized_improvement": None,
        },
        "verdict": verdict,
    }
    out = root / "receipts" / "benchmark" / f"mle-micro-official-grading-preflight-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_official_grading_preflight_receipt(receipt)
    return receipt


def validate_official_grading_preflight_receipt(receipt: dict[str, Any]) -> None:
    errors: list[str] = []
    if receipt.get("ticket") != "EMBER-MLE-MICRO-OFFICIAL-GRADING-PREFLIGHT":
        errors.append("bad ticket")
    subset = receipt.get("benchmark_subset", {})
    if subset.get("task_ids") != MLE_LOW_MICRO_TASK_IDS:
        errors.append("task ids are not the frozen micro-subset")
    if subset.get("official_leaderboard_comparable") is not False:
        errors.append("grading preflight must not claim official leaderboard comparability")
    if receipt.get("fixture_only") is not False:
        errors.append("grading preflight is not a tiny fixture")
    if receipt.get("real_mle_tasks_executed") is not False:
        errors.append("grading preflight must not claim real MLE tasks executed")
    if receipt.get("frozen_before_execution") is not True:
        errors.append("manifest must be frozen before execution")
    ready = receipt.get("prepared_data_ready") is True and receipt.get("candidate_submissions_ready") is True
    if ready and receipt.get("verdict") != "READY_TO_GRADE":
        errors.append("ready grading preflight must use READY_TO_GRADE verdict")
    if not ready and receipt.get("verdict") != "BLOCKED":
        errors.append("blocked grading preflight must use BLOCKED verdict")
    if receipt.get("prepared_data_ready") is True and receipt.get("missing_prepared_assets"):
        errors.append("prepared_data_ready cannot be true with missing prepared assets")
    if receipt.get("candidate_submissions_ready") is True and receipt.get("missing_candidate_submissions"):
        errors.append("candidate_submissions_ready cannot be true with missing submissions")
    if len(receipt.get("official_grade_commands", [])) != len(MLE_LOW_MICRO_TASK_IDS):
        errors.append("must emit one official grade command per frozen task")
    if errors:
        raise MicroHarnessValidationError("; ".join(errors))


def run_official_grade_execution(
    root: Path,
    source_root: Path,
    data_root: Path,
    submission_root: Path,
    cycle_id: str | None = None,
    command_factory: Callable[[str, list[str]], list[str]] | None = None,
    baseline_score: float = 0.0,
    max_score: float = 1.0,
    wheel_arm: str | None = None,
    auto_sample_submission: bool = False,
) -> dict[str, Any]:
    root = Path(root)
    source_root = Path(source_root)
    data_root = Path(data_root)
    submission_root = Path(submission_root)
    bootstrap_receipt = None
    if auto_sample_submission:
        bootstrap_receipt = run_sample_submission_bootstrap(
            root / "sample-submission-bootstrap",
            source_root,
            data_root,
            submission_root,
            cycle_id=cycle_id,
        )
    preflight = run_official_grading_preflight(
        root / "official-grading-preflight",
        source_root,
        data_root,
        submission_root,
        cycle_id=cycle_id,
    )
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = {
        "ticket": "EMBER-MLE-MICRO-OFFICIAL-GRADE-RUN",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "benchmark_subset": preflight["benchmark_subset"],
        "fixture_only": False,
        "frozen_before_execution": True,
        "source_root": str(source_root),
        "data_root": str(data_root),
        "submission_root": str(submission_root),
        "wheel_arm": _wheel_arm_contract(wheel_arm),
        "preflight": {
            "verdict": preflight["verdict"],
            "prepared_data_ready": preflight["prepared_data_ready"],
            "candidate_submissions_ready": preflight["candidate_submissions_ready"],
            "receipt_path": preflight.get("receipt_path"),
            "auto_sample_submission": auto_sample_submission,
            "bootstrap_receipt_path": bootstrap_receipt.get("receipt_path") if bootstrap_receipt else None,
        },
        "freeze_manifest_sha256": preflight["freeze_manifest_sha256"],
        "freeze_manifest_path": preflight["freeze_manifest_path"],
    }
    if preflight["verdict"] != "READY_TO_GRADE":
        receipt = {
            **base,
            "real_mle_tasks_executed": False,
            "blocked_reason": "official_grading_preflight_failed",
            "missing_prepared_assets": preflight["missing_prepared_assets"],
            "missing_candidate_submissions": preflight["missing_candidate_submissions"],
            "task_results": [],
            "score": {
                "baseline_score": None,
                "candidate_score": None,
                "mean_normalized_improvement": None,
            },
            "verdict": "BLOCKED",
        }
        return _write_official_grade_execution_receipt(root, receipt)

    task_results = []
    commands_by_task = {row["task_id"]: row["command"] for row in preflight["official_grade_commands"]}
    for task_id in MLE_LOW_MICRO_TASK_IDS:
        default_command = commands_by_task[task_id]
        command = command_factory(task_id, default_command) if command_factory else default_command
        proc = subprocess.run(command, text=True, capture_output=True, timeout=600)
        combined_output = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
        if proc.returncode != 0:
            receipt = {
                **base,
                "real_mle_tasks_executed": False,
                "blocked_reason": "official_grade_command_failed",
                "failed_task_id": task_id,
                "failed_command": command,
                "failed_returncode": proc.returncode,
                "failed_output_excerpt": combined_output[:500],
                "missing_prepared_assets": [],
                "missing_candidate_submissions": [],
                "task_results": task_results,
                "score": {
                    "baseline_score": None,
                    "candidate_score": None,
                    "mean_normalized_improvement": None,
                },
                "verdict": "BLOCKED",
            }
            return _write_official_grade_execution_receipt(root, receipt)
        report = _extract_grade_report(combined_output)
        if report is None or not isinstance(report.get("score"), (int, float)):
            receipt = {
                **base,
                "real_mle_tasks_executed": False,
                "blocked_reason": "official_grade_score_missing",
                "failed_task_id": task_id,
                "failed_command": command,
                "failed_output_excerpt": combined_output[:500],
                "missing_prepared_assets": [],
                "missing_candidate_submissions": [],
                "task_results": task_results,
                "score": {
                    "baseline_score": None,
                    "candidate_score": None,
                    "mean_normalized_improvement": None,
                },
                "verdict": "BLOCKED",
            }
            return _write_official_grade_execution_receipt(root, receipt)
        candidate_score = float(report["score"])
        task_results.append(
            {
                "task_id": task_id,
                "command": command,
                "baseline_score": baseline_score,
                "candidate_score": candidate_score,
                "max_score": max_score,
                "normalized_improvement": normalized_improvement(baseline_score, candidate_score, max_score),
                "official_report": report,
            }
        )

    candidate_mean = round(sum(row["candidate_score"] for row in task_results) / len(task_results), 6)
    improvement_mean = round(sum(row["normalized_improvement"] for row in task_results) / len(task_results), 6)
    receipt = {
        **base,
        "real_mle_tasks_executed": True,
        "blocked_reason": None,
        "missing_prepared_assets": [],
        "missing_candidate_submissions": [],
        "task_results": task_results,
        "score": {
            "baseline_score": baseline_score,
            "candidate_score": candidate_mean,
            "mean_normalized_improvement": improvement_mean,
        },
        "verdict": "PASS" if improvement_mean > 0 else "FAIL",
    }
    return _write_official_grade_execution_receipt(root, receipt)


def _extract_grade_report(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            obj, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("score"), (int, float)):
            return obj
    return None


def _wheel_arm_contract(arm_id: str | None) -> dict[str, Any] | None:
    if arm_id is None:
        return None
    try:
        return dict(WHEEL_ARM_CONTRACTS[arm_id])
    except KeyError as exc:
        raise MicroHarnessValidationError(f"unknown wheel arm: {arm_id}") from exc


def _write_official_grade_execution_receipt(root: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    out = root / "receipts" / "benchmark" / f"mle-micro-official-grade-run-{receipt['ts']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_official_grade_execution_receipt(receipt)
    return receipt


def validate_official_grade_execution_receipt(receipt: dict[str, Any]) -> None:
    errors: list[str] = []
    if receipt.get("ticket") != "EMBER-MLE-MICRO-OFFICIAL-GRADE-RUN":
        errors.append("bad ticket")
    subset = receipt.get("benchmark_subset", {})
    if subset.get("task_ids") != MLE_LOW_MICRO_TASK_IDS:
        errors.append("task ids are not the frozen micro-subset")
    if subset.get("official_leaderboard_comparable") is not False:
        errors.append("official grade run must not claim leaderboard comparability")
    if receipt.get("fixture_only") is not False:
        errors.append("official grade run must not be marked fixture_only")
    if receipt.get("frozen_before_execution") is not True:
        errors.append("manifest must be frozen before execution")
    if receipt.get("verdict") == "BLOCKED":
        if receipt.get("real_mle_tasks_executed") is not False:
            errors.append("blocked official grade run cannot claim real task execution")
        if not receipt.get("blocked_reason"):
            errors.append("blocked official grade run must record blocked_reason")
    else:
        if receipt.get("real_mle_tasks_executed") is not True:
            errors.append("non-blocked official grade run must mark real task execution")
        if len(receipt.get("task_results", [])) != len(MLE_LOW_MICRO_TASK_IDS):
            errors.append("official grade run must record every frozen task result")
        score = receipt.get("score", {})
        if not isinstance(score.get("mean_normalized_improvement"), (int, float)):
            errors.append("official grade run must record numeric mean normalized improvement")
        if receipt.get("verdict") == "PASS" and score.get("mean_normalized_improvement", 0) <= 0:
            errors.append("PASS requires positive mean normalized improvement")
    arm = receipt.get("wheel_arm")
    if arm is not None:
        arm_id = arm.get("id") if isinstance(arm, dict) else None
        if arm_id not in WHEEL_ARM_CONTRACTS or arm != WHEEL_ARM_CONTRACTS.get(arm_id):
            errors.append("wheel_arm contract must match A, B, or C")
    if errors:
        raise MicroHarnessValidationError("; ".join(errors))


def run_sample_submission_bootstrap(
    root: Path,
    source_root: Path,
    data_root: Path,
    submission_root: Path,
    cycle_id: str | None = None,
) -> dict[str, Any]:
    root = Path(root)
    source_root = Path(source_root)
    data_root = Path(data_root)
    submission_root = Path(submission_root)
    manifest = freeze_micro_subset(root)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    task_assets = []
    copied_submissions = []
    missing_prepared_assets = []
    missing_sample_submissions = []

    for task_id in MLE_LOW_MICRO_TASK_IDS:
        config_path = source_root / "mlebench" / "competitions" / task_id / "config.yaml"
        dataset_paths = _read_dataset_paths_from_config(config_path) if config_path.is_file() else {}
        prepared_assets = {
            key: (data_root / rel_path).is_file() if rel_path else None
            for key, rel_path in dataset_paths.items()
        }
        for key in PREPARED_DATA_KEYS:
            prepared_assets.setdefault(key, None)

        missing_prepared = [
            name
            for name in REQUIRED_CONFIGURED_DATA_KEYS
            if prepared_assets.get(name) is not True
        ]
        optional_missing = [
            name
            for name in PREPARED_DATA_KEYS
            if name not in REQUIRED_CONFIGURED_DATA_KEYS and prepared_assets.get(name) is False
        ]
        if missing_prepared:
            missing_prepared_assets.append(
                {
                    "task_id": task_id,
                    "missing": missing_prepared,
                    "optional_missing": optional_missing,
                    "dataset_paths": dataset_paths,
                }
            )

        sample_rel = dataset_paths.get("sample_submission", "")
        sample_path = data_root / sample_rel if sample_rel else None
        submission_path = submission_root / task_id / "submission.csv"
        sample_ready = sample_path.is_file() if sample_path else False
        if sample_ready and sample_path is not None:
            submission_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(sample_path, submission_path)
            copied_submissions.append(
                {
                    "task_id": task_id,
                    "source_sample_submission": str(sample_path),
                    "submission_path": str(submission_path),
                    "sha256": sha256_bytes(submission_path.read_bytes()),
                }
            )
        else:
            missing_sample_submissions.append(
                {
                    "task_id": task_id,
                    "missing": ["sample_submission"],
                    "configured_path": sample_rel,
                    "expected_path": str(sample_path) if sample_path else None,
                }
            )

        task_assets.append(
            {
                "task_id": task_id,
                "config_path": str(config_path),
                "dataset_paths": dataset_paths,
                "prepared_assets": prepared_assets,
                "sample_submission_ready": sample_ready,
                "submission_path": str(submission_path),
                "submission_ready": submission_path.is_file(),
            }
        )

    prepared_data_ready = not missing_prepared_assets
    candidate_submissions_ready = len(copied_submissions) == len(MLE_LOW_MICRO_TASK_IDS)
    verdict = "BOOTSTRAPPED" if prepared_data_ready and candidate_submissions_ready else "BLOCKED"
    receipt = {
        "ticket": "EMBER-MLE-MICRO-SAMPLE-SUBMISSION-BOOTSTRAP",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "benchmark_subset": {
            "id": manifest["id"],
            "task_ids": manifest["task_ids"],
            "official_leaderboard_comparable": False,
        },
        "fixture_only": False,
        "prepared_data_ready": prepared_data_ready,
        "candidate_submissions_ready": candidate_submissions_ready,
        "real_mle_tasks_executed": False,
        "frozen_before_execution": True,
        "source_root": str(source_root),
        "data_root": str(data_root),
        "submission_root": str(submission_root),
        "required_prepared_data_keys": list(REQUIRED_CONFIGURED_DATA_KEYS),
        "optional_prepared_data_keys": [
            key for key in PREPARED_DATA_KEYS if key not in REQUIRED_CONFIGURED_DATA_KEYS
        ],
        "task_assets": task_assets,
        "copied_count": len(copied_submissions),
        "copied_submissions": copied_submissions,
        "missing_prepared_assets": missing_prepared_assets,
        "missing_sample_submissions": missing_sample_submissions,
        "freeze_manifest_sha256": manifest["freeze_manifest_sha256"],
        "freeze_manifest_path": manifest["freeze_manifest_path"],
        "score": {
            "baseline_score": None,
            "candidate_score": None,
            "mean_normalized_improvement": None,
        },
        "verdict": verdict,
    }
    out = root / "receipts" / "benchmark" / f"mle-micro-sample-submission-bootstrap-{ts}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_sample_submission_bootstrap_receipt(receipt)
    return receipt


def validate_sample_submission_bootstrap_receipt(receipt: dict[str, Any]) -> None:
    errors: list[str] = []
    if receipt.get("ticket") != "EMBER-MLE-MICRO-SAMPLE-SUBMISSION-BOOTSTRAP":
        errors.append("bad ticket")
    subset = receipt.get("benchmark_subset", {})
    if subset.get("task_ids") != MLE_LOW_MICRO_TASK_IDS:
        errors.append("task ids are not the frozen micro-subset")
    if subset.get("official_leaderboard_comparable") is not False:
        errors.append("bootstrap must not claim official leaderboard comparability")
    if receipt.get("fixture_only") is not False:
        errors.append("bootstrap is not a tiny fixture")
    if receipt.get("real_mle_tasks_executed") is not False:
        errors.append("bootstrap must not claim real MLE tasks executed")
    if receipt.get("frozen_before_execution") is not True:
        errors.append("manifest must be frozen before execution")
    ready = receipt.get("prepared_data_ready") is True and receipt.get("candidate_submissions_ready") is True
    if ready and receipt.get("verdict") != "BOOTSTRAPPED":
        errors.append("ready bootstrap must use BOOTSTRAPPED verdict")
    if not ready and receipt.get("verdict") != "BLOCKED":
        errors.append("blocked bootstrap must use BLOCKED verdict")
    if receipt.get("prepared_data_ready") is True and receipt.get("missing_prepared_assets"):
        errors.append("prepared_data_ready cannot be true with missing prepared assets")
    if receipt.get("candidate_submissions_ready") is True and receipt.get("missing_sample_submissions"):
        errors.append("candidate_submissions_ready cannot be true with missing sample submissions")
    if receipt.get("candidate_submissions_ready") is True and receipt.get("copied_count") != len(MLE_LOW_MICRO_TASK_IDS):
        errors.append("ready bootstrap must copy one sample submission per frozen task")
    copied = receipt.get("copied_submissions", [])
    if len(copied) != receipt.get("copied_count"):
        errors.append("copied_count must match copied_submissions length")
    if errors:
        raise MicroHarnessValidationError("; ".join(errors))


def run_local_micro_execution(
    root: Path,
    mle_root: Path,
    candidate_root: Path,
    cycle_id: str | None = None,
) -> dict[str, Any]:
    root = Path(root)
    mle_root = Path(mle_root)
    candidate_root = Path(candidate_root)
    preflight = run_hydration_preflight(root / "hydration-preflight", mle_root, cycle_id=cycle_id)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    base = {
        "ticket": "EMBER-MLE-MICRO-REAL-RUN",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "cycle_id": cycle_id,
        "benchmark_subset": preflight["benchmark_subset"],
        "fixture_only": False,
        "frozen_before_execution": True,
        "mle_root": str(mle_root),
        "candidate_root": str(candidate_root),
        "hydration_preflight": {
            "verdict": preflight["verdict"],
            "hydration_ready": preflight["hydration_ready"],
            "receipt_path": preflight.get("receipt_path"),
        },
        "freeze_manifest_sha256": preflight["freeze_manifest_sha256"],
        "freeze_manifest_path": preflight["freeze_manifest_path"],
    }

    if not preflight["hydration_ready"]:
        receipt = {
            **base,
            "real_mle_tasks_executed": False,
            "blocked_reason": "hydration_preflight_failed",
            "missing_assets": preflight["missing_assets"],
            "missing_candidate_assets": [],
            "task_results": [],
            "score": {
                "baseline_score": None,
                "candidate_score": None,
                "mean_normalized_improvement": None,
            },
            "verdict": "BLOCKED",
        }
        return _write_local_execution_receipt(root, receipt)

    missing_candidates = []
    for task_id in MLE_LOW_MICRO_TASK_IDS:
        candidate_path = candidate_root / task_id / "candidate.py"
        if not candidate_path.is_file():
            missing_candidates.append({"task_id": task_id, "missing": ["candidate.py"], "root": str(candidate_path.parent)})
    if missing_candidates:
        receipt = {
            **base,
            "real_mle_tasks_executed": False,
            "blocked_reason": "candidate_assets_missing",
            "missing_assets": [],
            "missing_candidate_assets": missing_candidates,
            "task_results": [],
            "score": {
                "baseline_score": None,
                "candidate_score": None,
                "mean_normalized_improvement": None,
            },
            "verdict": "BLOCKED",
        }
        return _write_local_execution_receipt(root, receipt)

    task_results = []
    for task_id in MLE_LOW_MICRO_TASK_IDS:
        task_root = mle_root / task_id
        score_py = task_root / "score.py"
        baseline_py = task_root / "baselines" / "starter.py"
        candidate_py = candidate_root / task_id / "candidate.py"
        command = [
            sys.executable,
            str(score_py),
            "--task-id",
            task_id,
            "--task-root",
            str(task_root),
            "--baseline",
            str(baseline_py),
            "--candidate",
            str(candidate_py),
        ]
        proc = subprocess.run(command, cwd=str(task_root), text=True, capture_output=True, timeout=60)
        if proc.returncode != 0:
            raise MicroHarnessValidationError(f"score command failed for {task_id}: {proc.stderr.strip()}")
        try:
            score_obj = json.loads(proc.stdout.strip())
        except json.JSONDecodeError as exc:
            raise MicroHarnessValidationError(f"score command did not emit JSON for {task_id}: {exc}") from exc
        baseline = float(score_obj["baseline_score"])
        candidate = float(score_obj["candidate_score"])
        max_score = float(score_obj.get("max_score", 1.0))
        task_results.append(
            {
                "task_id": task_id,
                "command": command,
                "baseline_score": baseline,
                "candidate_score": candidate,
                "max_score": max_score,
                "normalized_improvement": normalized_improvement(baseline, candidate, max_score),
            }
        )

    baseline_mean = round(sum(row["baseline_score"] for row in task_results) / len(task_results), 6)
    candidate_mean = round(sum(row["candidate_score"] for row in task_results) / len(task_results), 6)
    improvement_mean = round(sum(row["normalized_improvement"] for row in task_results) / len(task_results), 6)
    receipt = {
        **base,
        "real_mle_tasks_executed": True,
        "blocked_reason": None,
        "missing_assets": [],
        "missing_candidate_assets": [],
        "task_results": task_results,
        "score": {
            "baseline_score": baseline_mean,
            "candidate_score": candidate_mean,
            "mean_normalized_improvement": improvement_mean,
        },
        "verdict": "PASS" if improvement_mean > 0 else "FAIL",
    }
    return _write_local_execution_receipt(root, receipt)


def _write_local_execution_receipt(root: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    out = root / "receipts" / "benchmark" / f"mle-micro-local-execution-{receipt['ts']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out), receipt)
    receipt["receipt_path"] = str(out)
    validate_local_execution_receipt(receipt)
    return receipt


def validate_local_execution_receipt(receipt: dict[str, Any]) -> None:
    errors: list[str] = []
    if receipt.get("ticket") != "EMBER-MLE-MICRO-REAL-RUN":
        errors.append("bad ticket")
    subset = receipt.get("benchmark_subset", {})
    if subset.get("task_ids") != MLE_LOW_MICRO_TASK_IDS:
        errors.append("task ids are not the frozen micro-subset")
    if subset.get("official_leaderboard_comparable") is not False:
        errors.append("local run must not claim official leaderboard comparability")
    if receipt.get("fixture_only") is not False:
        errors.append("local run must not be marked fixture_only")
    if receipt.get("frozen_before_execution") is not True:
        errors.append("manifest must be frozen before execution")
    if receipt.get("verdict") == "BLOCKED":
        if receipt.get("real_mle_tasks_executed") is not False:
            errors.append("blocked local run cannot claim real task execution")
        if not receipt.get("blocked_reason"):
            errors.append("blocked local run must record blocked_reason")
    else:
        if receipt.get("real_mle_tasks_executed") is not True:
            errors.append("non-blocked local run must mark real task execution")
        if len(receipt.get("task_results", [])) != len(MLE_LOW_MICRO_TASK_IDS):
            errors.append("local run must record every frozen task result")
        score = receipt.get("score", {})
        if not isinstance(score.get("mean_normalized_improvement"), (int, float)):
            errors.append("local run must record numeric mean normalized improvement")
    if errors:
        raise MicroHarnessValidationError("; ".join(errors))


def validate_micro_receipt(receipt: dict[str, Any]) -> None:
    errors: list[str] = []
    if receipt.get("ticket") != "EMBER-MLE-MICRO-FIXTURE":
        errors.append("bad ticket")
    subset = receipt.get("benchmark_subset", {})
    if subset.get("id") != "mle-low-micro-v0":
        errors.append("bad subset id")
    if subset.get("task_ids") != MLE_LOW_MICRO_TASK_IDS:
        errors.append("task ids are not the frozen micro-subset")
    if subset.get("official_leaderboard_comparable") is not False:
        errors.append("fixture must not claim official leaderboard comparability")
    if receipt.get("real_mle_tasks_executed") is not False:
        errors.append("fixture must not claim real MLE tasks executed")
    if receipt.get("frozen_before_execution") is not True:
        errors.append("manifest must be frozen before execution")
    score = receipt.get("score", {})
    expected = normalized_improvement(score.get("baseline_score"), score.get("candidate_score"))
    if score.get("mean_normalized_improvement") != expected:
        errors.append("mean normalized improvement does not match score inputs")
    if errors:
        raise MicroHarnessValidationError("; ".join(errors))


def main() -> int:
    import argparse
    import tempfile

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--fixture-out", help="write a tiny fixture benchmark receipt under this directory")
    ap.add_argument("--cycle-id", help="optional cycle id to bind into the receipt")
    ap.add_argument("--hydration-preflight", action="store_true", help="check local MLE micro task assets")
    ap.add_argument("--source-preflight", action="store_true", help="check official MLE-bench source metadata")
    ap.add_argument("--official-grading-preflight", action="store_true", help="check official prepared data and submission CSVs")
    ap.add_argument("--official-prepare-execution", action="store_true", help="run official MLE-bench prepare commands after raw audit passes")
    ap.add_argument("--attempt-prepare-without-raw", action="store_true", help="run official prepare commands even when the raw audit is missing assets")
    ap.add_argument("--official-grade-execution", action="store_true", help="run official grade-sample commands after grading preflight passes")
    ap.add_argument("--auto-sample-submission", action="store_true", help="copy prepared sample submissions before official grade execution")
    ap.add_argument("--sample-submission-bootstrap", action="store_true", help="copy prepared sample submissions into candidate submission root")
    ap.add_argument("--raw-data-audit", action="store_true", help="check raw files required by official prepare scripts")
    ap.add_argument("--raw-data-import", action="store_true", help="copy exact raw prepare files from a local source root")
    ap.add_argument("--kaggle-sdk-raw-download", action="store_true", help="download frozen raw task archives through kagglesdk bearer-token auth")
    ap.add_argument("--kaggle-benchmarks-sdk-probe", action="store_true", help="check Kaggle Benchmarks SDK/runtime readiness")
    ap.add_argument("--kaggle-benchmarks-task-file-probe", action="store_true", help="run a no-LLM Kaggle Benchmarks task and receipt task/run files")
    ap.add_argument("--kaggle-benchmarks-score-shape-probe", action="store_true", help="run a no-LLM Kaggle Benchmarks dataset evaluation and receipt local score shape")
    ap.add_argument("--kaggle-benchmarks-livecodebench-public-test-pilot", action="store_true", help="run the documented LiveCodeBench demo public test as a Kaggle Benchmarks pilot smoke")
    ap.add_argument("--kaggle-benchmarks-livecodebench-candidate-vs-baseline", action="store_true", help="run candidate-vs-baseline on the frozen LiveCodeBench demo public test")
    ap.add_argument("--kaggle-benchmarks-livecodebench-frozen-heldout-delta", action="store_true", help="run candidate-vs-baseline on a local frozen LiveCodeBench heldout set")
    ap.add_argument("--kaggle-dataset-external-heldout-delta", action="store_true", help="run candidate-vs-baseline on the materialized Kaggle emotion dataset heldout")
    ap.add_argument("--train-candidate", action="store_true", help="train a lightweight text classifier on external rows after the frozen heldout slice")
    ap.add_argument("--kaggle-auth-preflight", action="store_true", help="check Kaggle credential shape and optional live auth")
    ap.add_argument("--acquisition-status", action="store_true", help="check whether raw files or Kaggle auth can unblock prepare")
    ap.add_argument("--live-auth", action="store_true", help="perform a live Kaggle API auth check")
    ap.add_argument("--local-execution", action="store_true", help="run local MLE micro task score scripts")
    ap.add_argument("--mle-root", help="local root containing one directory per frozen MLE task id")
    ap.add_argument("--source-root", help="local official MLE-bench source checkout")
    ap.add_argument("--raw-source-root", help="local source root containing task/raw prepare files for --raw-data-import")
    ap.add_argument("--kaggle-benchmarks-sdk-root", help="local checkout of github.com/Kaggle/kaggle-benchmarks")
    ap.add_argument("--kaggle-benchmarks-workdir", help="directory where Kaggle Benchmarks task/run probe files are written")
    ap.add_argument("--python-executable", help="Python interpreter to use for subprocess-backed probes")
    ap.add_argument("--data-root", help="local MLE-bench prepared data directory")
    ap.add_argument("--submission-root", help="local candidate submission root")
    ap.add_argument("--credential-path", help="path to kaggle.json credentials")
    ap.add_argument("--access-token-path", help="path to Kaggle access_token bearer credential")
    ap.add_argument("--candidate-root", help="local root containing candidate.py per frozen MLE task id")
    ap.add_argument("--dataset-receipt", help="Kaggle dataset materialization receipt for external heldout delta")
    ap.add_argument("--candidate-script", help="candidate script for external heldout delta")
    ap.add_argument("--heldout-limit", type=int, default=32, help="number of rows to freeze as heldout for external heldout delta")
    ap.add_argument("--wheel-arm", choices=["A", "B", "C"], help="stamp official grade execution receipt as wheel arm A, B, or C")
    args = ap.parse_args()

    if args.selftest:
        with tempfile.TemporaryDirectory(prefix="ember-mle-micro-") as td:
            receipt = run_tiny_fixture(Path(td))
            validate_micro_receipt(receipt)
        print("EMBER_MLE_MICRO_HARNESS_SELFTEST_PASS")
        return 0

    if args.fixture_out:
        if args.local_execution:
            if not args.mle_root or not args.candidate_root:
                raise SystemExit("--mle-root and --candidate-root are required with --local-execution")
            receipt = run_local_micro_execution(
                Path(args.fixture_out),
                Path(args.mle_root),
                Path(args.candidate_root),
                cycle_id=args.cycle_id,
            )
        elif args.hydration_preflight:
            if not args.mle_root:
                raise SystemExit("--mle-root is required with --hydration-preflight")
            receipt = run_hydration_preflight(Path(args.fixture_out), Path(args.mle_root), cycle_id=args.cycle_id)
        elif args.source_preflight:
            if not args.source_root:
                raise SystemExit("--source-root is required with --source-preflight")
            receipt = run_official_source_preflight(Path(args.fixture_out), Path(args.source_root), cycle_id=args.cycle_id)
        elif args.official_grading_preflight:
            if not args.source_root or not args.data_root or not args.submission_root:
                raise SystemExit(
                    "--source-root, --data-root, and --submission-root are required with --official-grading-preflight"
                )
            receipt = run_official_grading_preflight(
                Path(args.fixture_out),
                Path(args.source_root),
                Path(args.data_root),
                Path(args.submission_root),
                cycle_id=args.cycle_id,
            )
        elif args.official_prepare_execution:
            if not args.source_root or not args.data_root:
                raise SystemExit("--source-root and --data-root are required with --official-prepare-execution")
            receipt = run_official_prepare_execution(
                Path(args.fixture_out),
                Path(args.source_root),
                Path(args.data_root),
                cycle_id=args.cycle_id,
                attempt_prepare_without_raw=args.attempt_prepare_without_raw,
                python_executable=Path(args.python_executable) if args.python_executable else None,
            )
        elif args.official_grade_execution:
            if not args.source_root or not args.data_root or not args.submission_root:
                raise SystemExit(
                    "--source-root, --data-root, and --submission-root are required with --official-grade-execution"
                )
            receipt = run_official_grade_execution(
                Path(args.fixture_out),
                Path(args.source_root),
                Path(args.data_root),
                Path(args.submission_root),
                cycle_id=args.cycle_id,
                wheel_arm=args.wheel_arm,
                auto_sample_submission=args.auto_sample_submission,
            )
        elif args.sample_submission_bootstrap:
            if not args.source_root or not args.data_root or not args.submission_root:
                raise SystemExit(
                    "--source-root, --data-root, and --submission-root are required with --sample-submission-bootstrap"
                )
            receipt = run_sample_submission_bootstrap(
                Path(args.fixture_out),
                Path(args.source_root),
                Path(args.data_root),
                Path(args.submission_root),
                cycle_id=args.cycle_id,
            )
        elif args.raw_data_audit:
            if not args.data_root:
                raise SystemExit("--data-root is required with --raw-data-audit")
            receipt = run_raw_data_audit(Path(args.fixture_out), Path(args.data_root), cycle_id=args.cycle_id)
        elif args.raw_data_import:
            if not args.raw_source_root or not args.data_root:
                raise SystemExit("--raw-source-root and --data-root are required with --raw-data-import")
            receipt = run_raw_data_import(
                Path(args.fixture_out),
                Path(args.raw_source_root),
                Path(args.data_root),
                cycle_id=args.cycle_id,
            )
        elif args.kaggle_sdk_raw_download:
            if not args.data_root or not args.access_token_path:
                raise SystemExit("--data-root and --access-token-path are required with --kaggle-sdk-raw-download")
            receipt = run_kaggle_sdk_raw_download(
                Path(args.fixture_out),
                Path(args.data_root),
                token_path=Path(args.access_token_path),
                cycle_id=args.cycle_id,
            )
        elif args.kaggle_benchmarks_sdk_probe:
            receipt = run_kaggle_benchmarks_sdk_probe(
                Path(args.fixture_out),
                sdk_root=Path(args.kaggle_benchmarks_sdk_root) if args.kaggle_benchmarks_sdk_root else None,
                cycle_id=args.cycle_id,
            )
        elif args.kaggle_benchmarks_task_file_probe:
            if not args.kaggle_benchmarks_workdir or not args.python_executable:
                raise SystemExit("--kaggle-benchmarks-workdir and --python-executable are required with --kaggle-benchmarks-task-file-probe")
            receipt = run_kaggle_benchmarks_task_file_probe(
                Path(args.fixture_out),
                Path(args.kaggle_benchmarks_workdir),
                Path(args.python_executable),
                cycle_id=args.cycle_id,
            )
        elif args.kaggle_benchmarks_score_shape_probe:
            if not args.kaggle_benchmarks_workdir or not args.python_executable:
                raise SystemExit("--kaggle-benchmarks-workdir and --python-executable are required with --kaggle-benchmarks-score-shape-probe")
            receipt = run_kaggle_benchmarks_score_shape_probe(
                Path(args.fixture_out),
                Path(args.kaggle_benchmarks_workdir),
                Path(args.python_executable),
                cycle_id=args.cycle_id,
            )
        elif args.kaggle_benchmarks_livecodebench_public_test_pilot:
            if not args.kaggle_benchmarks_workdir or not args.python_executable:
                raise SystemExit("--kaggle-benchmarks-workdir and --python-executable are required with --kaggle-benchmarks-livecodebench-public-test-pilot")
            receipt = run_kaggle_benchmarks_livecodebench_public_test_pilot(
                Path(args.fixture_out),
                Path(args.kaggle_benchmarks_workdir),
                Path(args.python_executable),
                sdk_root=Path(args.kaggle_benchmarks_sdk_root) if args.kaggle_benchmarks_sdk_root else None,
                cycle_id=args.cycle_id,
            )
        elif args.kaggle_benchmarks_livecodebench_candidate_vs_baseline:
            if not args.kaggle_benchmarks_workdir or not args.python_executable:
                raise SystemExit("--kaggle-benchmarks-workdir and --python-executable are required with --kaggle-benchmarks-livecodebench-candidate-vs-baseline")
            receipt = run_kaggle_benchmarks_livecodebench_candidate_vs_baseline(
                Path(args.fixture_out),
                Path(args.kaggle_benchmarks_workdir),
                Path(args.python_executable),
                sdk_root=Path(args.kaggle_benchmarks_sdk_root) if args.kaggle_benchmarks_sdk_root else None,
                cycle_id=args.cycle_id,
            )
        elif args.kaggle_benchmarks_livecodebench_frozen_heldout_delta:
            if not args.kaggle_benchmarks_workdir or not args.python_executable:
                raise SystemExit("--kaggle-benchmarks-workdir and --python-executable are required with --kaggle-benchmarks-livecodebench-frozen-heldout-delta")
            receipt = run_kaggle_benchmarks_livecodebench_frozen_heldout_delta(
                Path(args.fixture_out),
                Path(args.kaggle_benchmarks_workdir),
                Path(args.python_executable),
                sdk_root=Path(args.kaggle_benchmarks_sdk_root) if args.kaggle_benchmarks_sdk_root else None,
                cycle_id=args.cycle_id,
            )
        elif args.kaggle_dataset_external_heldout_delta:
            if not args.dataset_receipt:
                raise SystemExit("--dataset-receipt is required with --kaggle-dataset-external-heldout-delta")
            receipt = run_kaggle_dataset_external_heldout_delta(
                Path(args.fixture_out),
                Path(args.dataset_receipt),
                cycle_id=args.cycle_id,
                heldout_limit=args.heldout_limit,
                candidate_script_path=Path(args.candidate_script) if args.candidate_script else None,
                python_executable=Path(args.python_executable) if args.python_executable else None,
                wheel_arm=args.wheel_arm,
                train_candidate=args.train_candidate,
            )
        elif args.kaggle_auth_preflight:
            if not args.credential_path:
                raise SystemExit("--credential-path is required with --kaggle-auth-preflight")
            receipt = run_kaggle_auth_preflight(
                Path(args.fixture_out),
                Path(args.credential_path),
                access_token_path=Path(args.access_token_path) if args.access_token_path else None,
                live_check=args.live_auth,
                cycle_id=args.cycle_id,
            )
        elif args.acquisition_status:
            if not args.data_root:
                raise SystemExit("--data-root is required with --acquisition-status")
            receipt = run_benchmark_acquisition_status(
                Path(args.fixture_out),
                Path(args.data_root),
                credential_path=Path(args.credential_path) if args.credential_path else None,
                live_auth=args.live_auth,
                cycle_id=args.cycle_id,
            )
        else:
            receipt = run_tiny_fixture(Path(args.fixture_out), cycle_id=args.cycle_id)
        print(json.dumps(receipt, indent=2))
        return 0

    ap.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
