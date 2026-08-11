# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""Scratch-only #1413 launch-readiness gate; not product authority."""

import hashlib
import json
import math
import os
import re
import subprocess
from pathlib import Path


_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_SOURCE_RECEIPT_SCHEMA = "llmq-governed-source-receipt-v1"
_SOURCE_MANIFEST_SCHEMA = "llmq-source-manifest-v1"
_BUILD_RECEIPT_SCHEMA = "ember-lab-build-receipt-v1"
_BENCHMARK_RECEIPT_SCHEMA = "ember-lab-benchmark-receipt-v1"
_GOVERNED_ORIGIN = "https://github.com/IST-DASLab/llmq.git"
_EMBER_LAB_SOURCE_PATH = "runtime/ember-lab/src/lib.rs"


def _has_reparse_component(path: Path, root: Path) -> bool:
    """Reject symlink/junction/reparse components before resolving a custody path."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in relative.parts:
        current /= part
        try:
            stat_result = os.lstat(current)
        except OSError:
            return True
        if current.is_symlink() or (getattr(stat_result, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT):
            return True
    return False


def _safe_file(root: Path, relative_value: object) -> Path | None:
    if (
        not isinstance(relative_value, str)
        or not relative_value
        or Path(relative_value).is_absolute()
        or ".." in Path(relative_value).parts
    ):
        return None
    try:
        root = root.resolve(strict=True)
        candidate = root / relative_value
        if _has_reparse_component(candidate, root):
            return None
        candidate = candidate.resolve(strict=True)
    except OSError:
        return None
    return candidate if candidate.is_file() and candidate.is_relative_to(root) else None


def _safe_dir(root: Path, relative_value: object) -> Path | None:
    """Reopen a governed directory without crossing a reparse component."""
    if not isinstance(relative_value, str) or not relative_value or Path(relative_value).is_absolute() or ".." in Path(relative_value).parts:
        return None
    try:
        root = root.resolve(strict=True)
        candidate = root / relative_value
        if _has_reparse_component(candidate, root):
            return None
        candidate = candidate.resolve(strict=True)
    except OSError:
        return None
    return candidate if candidate.is_dir() and candidate.is_relative_to(root) else None


def _git_env() -> dict[str, str]:
    """Drop caller-controlled Git config/object/worktree transport overrides."""
    return {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}


def _run_git(repo: Path, *args: str) -> str | None:
    """Run one read-only Git identity probe without opening a Windows console."""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            check=False,
            creationflags=creationflags,
            env=_git_env(),
        )
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _run_git_bytes(repo: Path, *args: str) -> bytes | None:
    """Read one exact Git object without text decoding or console creation."""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            check=False,
            creationflags=creationflags,
            env=_git_env(),
        )
    except OSError:
        return None
    return result.stdout if result.returncode == 0 else None


def _run_git_ok(repo: Path, *args: str) -> bool:
    """Run a read-only Git predicate without opening a Windows console."""
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            check=False,
            creationflags=creationflags,
            env=_git_env(),
        )
    except OSError:
        return False
    return result.returncode == 0


def _json_file(root: Path, path_value: object) -> dict | None:
    path = _safe_file(root, path_value)
    if path is None:
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _digest_file(root: Path, path_value: object, digest: object) -> bool:
    """Reopen a path under custody and compare its raw bytes to a declared SHA."""
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        return False
    path = _safe_file(root, path_value)
    if path is None:
        return False
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest() == digest
    except OSError:
        return False


def _governed_source_missing(root: Path, payload: dict, commit: object, source_sha: object) -> list[str]:
    """Require an independently replayable source manifest, not caller JSON agreement."""
    receipt = payload.get("governed_source_receipt")
    missing: list[str] = []
    if not isinstance(receipt, dict) or receipt.get("schema") != _SOURCE_RECEIPT_SCHEMA:
        return ["governed_source_receipt"]
    if receipt.get("test_only") is True or receipt.get("status") != "PASS":
        missing.append("governed_source_receipt.status")
    if receipt.get("authority") != "governed-git-source":
        missing.append("governed_source_receipt.authority")
    if receipt.get("repo") != "IST-DASLab/llmq":
        missing.append("governed_source_receipt.repo")
    if receipt.get("commit") != commit or not isinstance(commit, str) or not _SHA.fullmatch(commit):
        missing.append("governed_source_receipt.commit")
    tree = receipt.get("tree_sha256")
    if not isinstance(tree, str) or not _SHA.fullmatch(tree):
        missing.append("governed_source_receipt.tree_sha256")
    if receipt.get("source_sha256") != source_sha:
        missing.append("governed_source_receipt.source_sha256")
    if not _digest_file(root, receipt.get("source_manifest_path"), receipt.get("source_manifest_sha256")):
        missing.append("governed_source_receipt.source_manifest")
    manifest = _json_file(root, receipt.get("source_manifest_path"))
    expected_manifest = {
        "schema": _SOURCE_MANIFEST_SCHEMA,
        "repo": "IST-DASLab/llmq",
        "commit": commit,
        "tree_sha256": tree,
        "remote_ref": receipt.get("remote_ref"),
        "source_path": receipt.get("source_path"),
        "source_sha256": source_sha,
    }
    if not isinstance(manifest, dict) or set(manifest) != set(expected_manifest) or any(
        manifest.get(key) != value for key, value in expected_manifest.items()
    ):
        missing.append("governed_source_receipt.source_manifest_binding")
    if not _digest_file(root, receipt.get("source_path"), source_sha):
        missing.append("governed_source_receipt.source_path")
    if receipt.get("verification") != "git-commit-tree-replayed":
        missing.append("governed_source_receipt.verification")
    repo = _safe_dir(root, receipt.get("git_repo_path"))
    if repo is None:
        missing.append("governed_source_receipt.git_repo_path")
    else:
        origins_raw = _run_git(repo, "config", "--get-all", "remote.origin.url")
        origins = origins_raw.splitlines() if isinstance(origins_raw, str) else []
        origin = origins[0] if len(origins) == 1 else None
        if len(origins) != 1 or origin != _GOVERNED_ORIGIN:
            missing.append("governed_source_receipt.git_origin")
        rewrite_rules = _run_git(repo, "config", "--get-regexp", r"^url\..+\.")
        if isinstance(origin, str) and rewrite_rules and any(
            len(parts := line.split(None, 1)) == 2
            and (
                parts[0].lower().endswith(".insteadof")
                or parts[0].lower().endswith(".pushinsteadof")
            )
            and origin.startswith(parts[1])
            for line in rewrite_rules.splitlines()
        ):
            missing.append("governed_source_receipt.git_url_rewrite")
        resolved_commit = _run_git(repo, "rev-parse", f"{commit}^{{commit}}") if isinstance(commit, str) else None
        resolved_tree = _run_git(repo, "rev-parse", f"{commit}^{{tree}}") if isinstance(commit, str) else None
        if resolved_commit != commit:
            missing.append("governed_source_receipt.git_commit")
        if resolved_tree != receipt.get("tree_sha256"):
            missing.append("governed_source_receipt.git_tree_sha256")
        remote_refs = (
            _run_git(
                repo,
                "for-each-ref",
                "--format=%(refname)",
                "--contains",
                commit,
                "refs/remotes/origin/",
            )
            if isinstance(commit, str)
            else None
        )
        if not remote_refs or not any(
            ref.startswith("refs/remotes/origin/") and ref != "refs/remotes/origin/HEAD"
            for ref in remote_refs.splitlines()
        ):
            missing.append("governed_source_receipt.git_remote_commit")
        remote_ref = receipt.get("remote_ref")
        if not isinstance(remote_ref, str) or not re.fullmatch(r"refs/heads/[A-Za-z0-9._/-]+", remote_ref):
            missing.append("governed_source_receipt.remote_ref")
        else:
            origin_path = Path(origin) if origin is not None else None
            if origin_path is not None and origin_path.is_dir():
                remote_commit = _run_git(origin_path, "show-ref", "--hash", remote_ref)
            else:
                remote_result = _run_git(repo, "ls-remote", "origin", remote_ref)
                remote_commit = remote_result.split()[0] if remote_result else None
            tracking_ref = "refs/remotes/origin/" + remote_ref.removeprefix("refs/heads/")
            fetched_commit = _run_git(repo, "rev-parse", tracking_ref)
            if remote_commit != commit:
                missing.append("governed_source_receipt.git_remote_ref")
            if fetched_commit != remote_commit:
                missing.append("governed_source_receipt.git_remote_fetch")
            if isinstance(commit, str) and not _run_git_ok(repo, "merge-base", "--is-ancestor", commit, tracking_ref):
                missing.append("governed_source_receipt.git_remote_ancestry")
        source_file = _safe_file(root, receipt.get("source_path"))
        if source_file is None or not source_file.is_relative_to(repo):
            missing.append("governed_source_receipt.source_in_repo")
        else:
            source_relative = source_file.relative_to(repo).as_posix()
            committed_source = (
                _run_git_bytes(repo, "cat-file", "blob", f"{commit}:{source_relative}")
                if isinstance(commit, str)
                else None
            )
            try:
                worktree_source = source_file.read_bytes()
            except OSError:
                worktree_source = None
            if (
                committed_source is None
                or worktree_source is None
                or committed_source != worktree_source
                or hashlib.sha256(committed_source).hexdigest() != source_sha
            ):
                missing.append("governed_source_receipt.git_source_blob")
    return missing


def _ember_lab_build_missing(root: Path, payload: dict, source_receipt: dict, build: object) -> list[str]:
    """Require the canonical Ember CLI -> Ember Lab build/dispatch custody chain."""
    receipt = payload.get("ember_lab_build_receipt")
    missing: list[str] = []
    if not isinstance(receipt, dict) or receipt.get("schema") != _BUILD_RECEIPT_SCHEMA:
        return ["ember_lab_build_receipt"]
    if receipt.get("test_only") is True or receipt.get("status") != "PASS":
        missing.append("ember_lab_build_receipt.status")
    if receipt.get("authority") != "ember-cli->ember-lab":
        missing.append("ember_lab_build_receipt.authority")
    for field in (
        "job_id", "host_id", "toolchain", "dispatch_receipt_path", "binary_manifest_path",
        "operational_receipt_path", "producer_source_path", "producer_binary_path",
    ):
        if not isinstance(receipt.get(field), str) or not receipt[field]:
            missing.append(f"ember_lab_build_receipt.{field}")
    if receipt.get("exit_code") != 0:
        missing.append("ember_lab_build_receipt.exit_code")
    if receipt.get("source_manifest_sha256") != source_receipt.get("source_manifest_sha256"):
        missing.append("ember_lab_build_receipt.source_manifest_sha256")
    if not _digest_file(root, receipt.get("dispatch_receipt_path"), receipt.get("dispatch_receipt_sha256")):
        missing.append("ember_lab_build_receipt.dispatch_receipt")
    if not _digest_file(root, receipt.get("binary_manifest_path"), receipt.get("binary_manifest_sha256")):
        missing.append("ember_lab_build_receipt.binary_manifest")
    if not isinstance(build, dict) or build.get("binary_sha256") != receipt.get("binary_sha256"):
        missing.append("ember_lab_build_receipt.binary_sha256")
    producer_source_path = receipt.get("producer_source_path")
    producer_source_sha = receipt.get("producer_source_sha256")
    if producer_source_path != _EMBER_LAB_SOURCE_PATH:
        missing.append("ember_lab_build_receipt.producer_source_identity")
    if not isinstance(producer_source_sha, str) or not _DIGEST.fullmatch(producer_source_sha):
        missing.append("ember_lab_build_receipt.producer_source_sha256")
    elif not _digest_file(root, producer_source_path, producer_source_sha):
        missing.append("ember_lab_build_receipt.producer_source_sha256")
    producer_binary_path = receipt.get("producer_binary_path")
    producer_binary_sha = receipt.get("producer_binary_sha256")
    if not isinstance(producer_binary_sha, str) or not _DIGEST.fullmatch(producer_binary_sha):
        missing.append("ember_lab_build_receipt.producer_binary_sha256")
    elif not _digest_file(root, producer_binary_path, producer_binary_sha):
        missing.append("ember_lab_build_receipt.producer_binary_sha256")
    operational_path = receipt.get("operational_receipt_path")
    operational_sha = receipt.get("operational_receipt_sha256")
    if not _digest_file(root, operational_path, operational_sha):
        missing.append("ember_lab_build_receipt.operational_receipt")
    operational = _json_file(root, operational_path)
    if not isinstance(operational, dict):
        missing.append("ember_lab_build_receipt.operational_receipt_schema")
    else:
        if (
            operational.get("schema") != "ember-lab-operational-receipt-v1"
            or operational.get("producer") != "ember-lab-daemon"
            or operational.get("status") != "PASS"
            or operational.get("test_only") is True
            or operational.get("job_id") != receipt.get("job_id")
            or operational.get("exit_code") != 0
            or operational.get("source_manifest_sha256") != receipt.get("source_manifest_sha256")
            or operational.get("binary_sha256") != receipt.get("binary_sha256")
        ):
            missing.append("ember_lab_build_receipt.operational_receipt_binding")
        identity = operational.get("ember_lab_identity")
        if (
            not isinstance(identity, dict)
            or identity.get("source_sha256") != producer_source_sha
            or identity.get("binary_sha256") != producer_binary_sha
        ):
            missing.append("ember_lab_build_receipt.operational_producer_identity")
    dispatch = _json_file(root, receipt.get("dispatch_receipt_path"))
    if not isinstance(dispatch, dict) or dispatch.get("schema") != "ember-lab-dispatch-terminal-receipt-v1":
        missing.append("ember_lab_build_receipt.dispatch_schema")
    else:
        if dispatch.get("status") != "PASS" or dispatch.get("test_only") is True:
            missing.append("ember_lab_build_receipt.dispatch_status")
        if dispatch.get("job_id") != receipt.get("job_id"):
            missing.append("ember_lab_build_receipt.dispatch_job_id")
        if dispatch.get("source_manifest_sha256") != receipt.get("source_manifest_sha256"):
            missing.append("ember_lab_build_receipt.dispatch_source_manifest_sha256")
    binary = _json_file(root, receipt.get("binary_manifest_path"))
    if not isinstance(binary, dict) or binary.get("schema") != "ember-lab-binary-manifest-v1":
        missing.append("ember_lab_build_receipt.binary_manifest_schema")
    elif binary.get("status") != "PASS" or binary.get("test_only") is True or binary.get("binary_sha256") != receipt.get("binary_sha256"):
        missing.append("ember_lab_build_receipt.binary_manifest_binding")
    return missing


def _ember_lab_benchmark_missing(root: Path, payload: dict, build_receipt: dict) -> list[str]:
    """Require re-openable multi-step benchmark logs and rederived rates."""
    receipt = payload.get("ember_lab_benchmark_receipt")
    missing: list[str] = []
    if not isinstance(receipt, dict) or receipt.get("schema") != _BENCHMARK_RECEIPT_SCHEMA:
        return ["ember_lab_benchmark_receipt"]
    if receipt.get("test_only") is True or receipt.get("status") != "PASS":
        missing.append("ember_lab_benchmark_receipt.status")
    if receipt.get("authority") != "ember-cli->ember-lab":
        missing.append("ember_lab_benchmark_receipt.authority")
    if receipt.get("job_id") != build_receipt.get("job_id"):
        missing.append("ember_lab_benchmark_receipt.job_id")
    for field in (
        "hardware_uuid", "command", "config_sha256", "raw_log_path", "raw_log_sha256",
        "operational_receipt_path", "operational_receipt_sha256",
    ):
        if not isinstance(receipt.get(field), str) or not receipt[field]:
            missing.append(f"ember_lab_benchmark_receipt.{field}")
    if receipt.get("binary_sha256") != build_receipt.get("binary_sha256"):
        missing.append("ember_lab_benchmark_receipt.binary_sha256")
    if (
        receipt.get("operational_receipt_path") != build_receipt.get("operational_receipt_path")
        or receipt.get("operational_receipt_sha256") != build_receipt.get("operational_receipt_sha256")
    ):
        missing.append("ember_lab_benchmark_receipt.operational_receipt_binding")
    if not _digest_file(root, receipt.get("operational_receipt_path"), receipt.get("operational_receipt_sha256")):
        missing.append("ember_lab_benchmark_receipt.operational_receipt")
    if not _digest_file(root, receipt.get("raw_log_path"), receipt.get("raw_log_sha256")):
        missing.append("ember_lab_benchmark_receipt.raw_log")
    raw_path = _safe_file(root, receipt.get("raw_log_path"))
    raw_rows: list[dict] = []
    if raw_path is not None:
        try:
            raw_rows = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, ValueError):
            missing.append("ember_lab_benchmark_receipt.raw_log_schema")
    if not raw_rows or any(not isinstance(row, dict) for row in raw_rows):
        missing.append("ember_lab_benchmark_receipt.raw_log_rows")
    rows = receipt.get("rate_rows")
    if not isinstance(rows, list) or not rows:
        missing.append("ember_lab_benchmark_receipt.rate_rows")
    else:
        modes = set()
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                missing.append(f"ember_lab_benchmark_receipt.rate_rows[{index}]")
                continue
            mode = row.get("mode")
            tokens = row.get("tokens")
            elapsed_ms = row.get("elapsed_ms")
            measured = row.get("tok_s")
            if mode not in {"fp8", "bf16"}:
                missing.append(f"ember_lab_benchmark_receipt.rate_rows[{index}].mode")
            else:
                modes.add(mode)
            if not isinstance(tokens, int) or tokens <= 0 or not isinstance(elapsed_ms, (int, float)) or elapsed_ms <= 0:
                missing.append(f"ember_lab_benchmark_receipt.rate_rows[{index}].measurement")
            elif not isinstance(measured, (int, float)) or not math.isfinite(measured) or abs(measured - tokens * 1000.0 / elapsed_ms) > 1e-6:
                missing.append(f"ember_lab_benchmark_receipt.rate_rows[{index}].tok_s")
        if modes != {"fp8", "bf16"}:
            missing.append("ember_lab_benchmark_receipt.rate_rows.modes")
        if len(raw_rows) != len(rows):
            missing.append("ember_lab_benchmark_receipt.raw_log_cardinality")
        else:
            for index, (raw, declared) in enumerate(zip(raw_rows, rows)):
                if any(raw.get(key) != declared.get(key) for key in ("mode", "tokens", "elapsed_ms")):
                    missing.append(f"ember_lab_benchmark_receipt.raw_log_binding[{index}]")
                if isinstance(raw.get("tokens"), int) and isinstance(raw.get("elapsed_ms"), (int, float)) and raw.get("elapsed_ms", 0) > 0:
                    expected = raw["tokens"] * 1000.0 / raw["elapsed_ms"]
                    if declared.get("tok_s") != expected:
                        missing.append(f"ember_lab_benchmark_receipt.raw_log_rate[{index}]")
    return missing


def assess(source_root: Path, payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {
            "schema": "ember-llmq-adoption-readiness-v1",
            "verdict": "PRELAUNCH_REJECTED",
            "missing": ["payload"],
            "source_root": "SCRATCH_ONLY",
            "execution_claim": False,
            "result_credit": False,
            "external_remainder": ["closed readiness payload"],
            "rollback": "discard scratch-only artifact; no product state changed",
            "next_action": "supply a closed readiness payload before any dispatch",
        }
    missing = []
    commit = payload.get("llmq_dev_commit")
    if not isinstance(commit, str) or not _SHA.fullmatch(commit):
        missing.append("llmq_dev_commit")
    source_path = _safe_file(Path(source_root), payload.get("llmq_source_path"))
    if source_path is None:
        missing.append("llmq_source_path")
    source_sha = payload.get("source_sha256")
    if not isinstance(source_sha, str) or not _DIGEST.fullmatch(source_sha):
        missing.append("source_sha256")
    elif source_path is not None:
        try:
            if hashlib.sha256(source_path.read_bytes()).hexdigest() != source_sha:
                missing.append("source_sha256")
        except OSError:
            missing.append("source_sha256")
    build = payload.get("build_receipt")
    if not isinstance(build, dict) or build.get("schema") != "ember-llmq-build-receipt-v1":
        missing.append("build_receipt")
    else:
        if build.get("status") != "PASS":
            missing.append("build_receipt.status")
        if build.get("source_commit") != commit:
            missing.append("build_receipt.source_commit")
        if build.get("source_sha256") != source_sha:
            missing.append("build_receipt.source_sha256")
        binary_path = _safe_file(Path(source_root), build.get("binary_path"))
        if binary_path is None:
            missing.append("build_receipt.binary_path")
        if not isinstance(build.get("binary_sha256"), str) or not _DIGEST.fullmatch(build["binary_sha256"]):
            missing.append("build_receipt.binary_sha256")
        elif binary_path is not None:
            try:
                if hashlib.sha256(binary_path.read_bytes()).hexdigest() != build["binary_sha256"]:
                    missing.append("build_receipt.binary_sha256")
            except OSError:
                missing.append("build_receipt.binary_sha256")

    source_receipt = payload.get("governed_source_receipt") if isinstance(payload.get("governed_source_receipt"), dict) else {}
    source_authority_missing = _governed_source_missing(Path(source_root), payload, commit, source_sha)
    missing.extend(source_authority_missing)
    build_authority_missing = _ember_lab_build_missing(Path(source_root), payload, source_receipt, build)
    missing.extend(build_authority_missing)
    benchmark_authority_missing = _ember_lab_benchmark_missing(
        Path(source_root), payload, payload.get("ember_lab_build_receipt") if isinstance(payload.get("ember_lab_build_receipt"), dict) else {}
    )
    missing.extend(benchmark_authority_missing)

    for path_field, digest_field in (
        ("adoption_design_path", "adoption_design_sha256"),
        ("mechanism_attribution_path", "mechanism_attribution_sha256"),
    ):
        bound_path = _safe_file(Path(source_root), payload.get(path_field))
        if bound_path is None:
            missing.append(path_field)
        value = payload.get(digest_field)
        if not isinstance(value, str) or not _DIGEST.fullmatch(value):
            missing.append(digest_field)
        elif bound_path is not None:
            try:
                if hashlib.sha256(bound_path.read_bytes()).hexdigest() != value:
                    missing.append(digest_field)
            except OSError:
                missing.append(digest_field)

    benchmark = payload.get("benchmark_receipt")
    if not isinstance(benchmark, dict) or benchmark.get("schema") != "ember-4090-3b-benchmark-receipt-v1":
        missing.append("benchmark_receipt")
    else:
        if benchmark.get("hardware") != "RTX 4090":
            missing.append("benchmark_receipt.hardware")
        if benchmark.get("status") != "PASS":
            missing.append("benchmark_receipt.status")
        if benchmark.get("model") != "Qwen2.5-3B":
            missing.append("benchmark_receipt.model")
        for field in ("fp8_tok_s", "bf16_tok_s"):
            value = benchmark.get(field)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                missing.append(f"benchmark_receipt.{field}")

    source_or_design_missing = any(
        field in missing
        for field in (
            "llmq_dev_commit",
            "llmq_source_path",
            "source_sha256",
            "build_receipt",
            "adoption_design_path",
            "adoption_design_sha256",
            "mechanism_attribution_path",
            "mechanism_attribution_sha256",
        )
    )
    if (
        source_or_design_missing
        or any(field.startswith("build_receipt") for field in missing)
        or any(field.startswith("governed_source_receipt") for field in missing)
        or any(field.startswith("ember_lab_build_receipt") for field in missing)
        or any(field.startswith("benchmark_receipt.") for field in missing)
        or any(field.startswith("ember_lab_benchmark_receipt.") for field in missing)
    ):
        verdict = "PRELAUNCH_REJECTED"
    elif "benchmark_receipt" in missing or "ember_lab_benchmark_receipt" in missing:
        verdict = "READY_FOR_EXTERNAL_EXECUTION"
    else:
        verdict = "READY_FOR_EXTERNAL_EXECUTION"
    external_remainder = []
    if any(field in missing for field in ("llmq_dev_commit", "llmq_source_path", "source_sha256")):
        external_remainder.append("pinned LLMQ source commit and source bytes")
    if any(field.startswith("build_receipt") for field in missing):
        external_remainder.append("governed LLMQ build receipt and binary bytes")
    if any(field in missing for field in ("adoption_design_path", "adoption_design_sha256")):
        external_remainder.append("frozen adoption design bytes")
    if any(field in missing for field in ("mechanism_attribution_path", "mechanism_attribution_sha256")):
        external_remainder.append("mechanism attribution bytes")
    if any(field.startswith("benchmark_receipt") for field in missing):
        external_remainder.append("owned RTX 4090 x1 3B benchmark receipt")
    if any(field.startswith("governed_source_receipt") for field in missing):
        external_remainder.append("independently replayed governed LLMQ source receipt")
    if any(field.startswith("ember_lab_build_receipt") for field in missing):
        external_remainder.append("canonical Ember CLI -> Ember Lab build/dispatch receipt")
    if any(field.startswith("ember_lab_benchmark_receipt") for field in missing):
        external_remainder.append("canonical Ember CLI -> Ember Lab benchmark log receipt")
    return {
        "schema": "ember-llmq-adoption-readiness-v1",
        "verdict": verdict,
        "missing": missing,
        "source_root": "SCRATCH_ONLY",
        "execution_claim": False,
        "result_credit": False,
        "external_remainder": external_remainder,
        "rollback": "discard scratch-only artifact; no product state changed",
        "next_action": (
            "obtain a governed LLMQ build and one-RTX-4090 3B benchmark receipt"
            if "benchmark_receipt" in missing
            else "dispatch only through Ember CLI -> Ember Lab after external evidence"
        ),
    }
