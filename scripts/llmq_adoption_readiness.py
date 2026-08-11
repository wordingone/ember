# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""Scratch-only #1413 launch-readiness gate; not product authority."""

import hashlib
import json
import math
import os
import re
import sqlite3
import subprocess
from pathlib import Path


_SHA = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_SOURCE_RECEIPT_SCHEMA = "llmq-governed-source-receipt-v1"
_SOURCE_MANIFEST_SCHEMA = "llmq-source-manifest-v1"
_BUILD_RECEIPT_SCHEMA = "ember-lab-build-receipt-v1"
_BENCHMARK_RECEIPT_SCHEMA = "ember-lab-benchmark-receipt-v1"
_DAEMON_RECEIPT_SCHEMA = "ember-lab-operational-receipt-v1"
_SCHEDULE_ALARM_SCHEMA = "ember-lab-schedule-alarm-state-v1"
_GOVERNED_ORIGIN = "https://github.com/IST-DASLab/llmq.git"
_EMBER_LAB_SOURCE_PATH = "runtime/ember-lab/src/lib.rs"
_APPROVED_DAEMON_STATE_ROOT = (
    Path(os.environ["EMBER_STATE_ROOT"])
    if os.environ.get("EMBER_STATE_ROOT", "").strip()
    else None
)


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


def _authority_file(root: Path | None, path_value: object) -> Path | None:
    """Reopen a daemon-owned file under the approved external EMBER_STATE_ROOT."""
    if root is None or not isinstance(path_value, str) or not path_value:
        return None
    try:
        authority_root = root.resolve(strict=True)
        candidate = Path(path_value)
        if candidate.is_absolute():
            if ".." in candidate.parts or not candidate.is_relative_to(authority_root):
                return None
            if _has_reparse_component(candidate, authority_root):
                return None
            candidate = candidate.resolve(strict=True)
            if not candidate.is_relative_to(authority_root):
                return None
        else:
            candidate = _safe_file(authority_root, path_value)
            if candidate is None:
                return None
        return candidate if candidate.is_file() else None
    except OSError:
        return None


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
    path = _authority_file(root, path_value)
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
    path = _authority_file(root, path_value)
    if path is None:
        return False
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest() == digest
    except OSError:
        return False


def _read_sqlite_row(path: Path, query: str, params: tuple[object, ...]) -> tuple | None:
    """Reopen a daemon database read-only; never create or mutate an authority DB."""
    try:
        uri = f"{path.resolve(strict=True).as_uri()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            return connection.execute(query, params).fetchone()
    except (OSError, sqlite3.Error):
        return None


def _approved_daemon_state_root(source_root: Path) -> Path | None:
    """Resolve the existing Ember state root, never a caller-selected checkout path."""
    if _APPROVED_DAEMON_STATE_ROOT is None:
        return None
    try:
        authority_root = _APPROVED_DAEMON_STATE_ROOT.resolve(strict=True)
        checkout_root = source_root.resolve(strict=True)
        if authority_root == checkout_root or authority_root.is_relative_to(checkout_root):
            return None
        return authority_root
    except OSError:
        return None


def _ember_lab_daemon_authority_missing(
    root: Path, build_receipt: object, benchmark_receipt: object
) -> list[str]:
    """Require daemon-owned job/run state, not a self-consistent receipt bundle."""
    authority_root = _approved_daemon_state_root(root)
    missing: list[str] = []
    if authority_root is None:
        return ["ember_lab_build_receipt.daemon_authority.locator"]
    if not isinstance(build_receipt, dict):
        return ["ember_lab_build_receipt.daemon_authority"]
    has_benchmark = isinstance(benchmark_receipt, dict)
    if not has_benchmark:
        benchmark_receipt = {}
    operational_path = build_receipt.get("operational_receipt_path")
    operational_sha = build_receipt.get("operational_receipt_sha256")
    state_db_path = build_receipt.get("daemon_state_db_path")
    state_db_sha = build_receipt.get("daemon_state_db_sha256")
    alarm_path = benchmark_receipt.get("schedule_alarm_state_path")
    alarm_sha = benchmark_receipt.get("schedule_alarm_state_sha256")
    measurement_sha = benchmark_receipt.get("measurement_receipt_sha256")
    required_paths = [
        ("operational_receipt_path", operational_path),
        ("daemon_state_db_path", state_db_path),
    ]
    if has_benchmark:
        required_paths.append(("schedule_alarm_state_path", alarm_path))
    for field, value in required_paths:
        if not isinstance(value, str) or not value:
            missing.append(f"ember_lab_build_receipt.daemon_authority.{field}")
    required_hashes = [
        ("operational_receipt_sha256", operational_sha),
        ("daemon_state_db_sha256", state_db_sha),
    ]
    if has_benchmark:
        required_hashes.extend(
            [
                ("schedule_alarm_state_sha256", alarm_sha),
                ("measurement_receipt_sha256", measurement_sha),
            ]
        )
    for field, value in required_hashes:
        if not isinstance(value, str) or not _DIGEST.fullmatch(value):
            missing.append(f"ember_lab_build_receipt.daemon_authority.{field}")
    if missing:
        return missing
    operational_file = _authority_file(authority_root, operational_path)
    state_db_file = _authority_file(authority_root, state_db_path)
    alarm_file = _authority_file(authority_root, alarm_path)
    if operational_file is None or not _digest_file(authority_root, operational_path, operational_sha):
        missing.append("ember_lab_build_receipt.daemon_authority.operational_receipt")
    if state_db_file is None or not _digest_file(authority_root, state_db_path, state_db_sha):
        missing.append("ember_lab_build_receipt.daemon_authority.state_db")
    if has_benchmark and (alarm_file is None or not _digest_file(authority_root, alarm_path, alarm_sha)):
        missing.append("ember_lab_build_receipt.daemon_authority.schedule_alarm_state")
    if operational_file is not None and operational_file.name != f"{operational_sha}.json":
        missing.append("ember_lab_build_receipt.daemon_authority.content_addressed_receipt")
    if operational_file is not None and operational_file.parent.name != "content-addressed-receipts":
        missing.append("ember_lab_build_receipt.daemon_authority.receipt_root")
    operational = _json_file(authority_root, operational_path)
    if not isinstance(operational, dict) or operational.get("schema") != _DAEMON_RECEIPT_SCHEMA:
        missing.append("ember_lab_build_receipt.daemon_authority.operational_schema")
        operational = None
    if operational is None or operational.get("test_only") is True:
        missing.append("ember_lab_build_receipt.daemon_authority.test_only")
    if operational is not None:
        if operational.get("job_id") != build_receipt.get("job_id"):
            missing.append("ember_lab_build_receipt.daemon_authority.job_id")
        if operational.get("state") not in {"stopped", "exited", "failed"}:
            missing.append("ember_lab_build_receipt.daemon_authority.terminal_state")
        if operational.get("exit_code") not in {0, None}:
            missing.append("ember_lab_build_receipt.daemon_authority.exit_code")
        identity = operational.get("ember_lab_identity")
        if (
            not isinstance(identity, dict)
            or identity.get("source_sha256") != build_receipt.get("producer_source_sha256")
            or identity.get("binary_sha256") != build_receipt.get("producer_binary_sha256")
        ):
            missing.append("ember_lab_build_receipt.daemon_authority.identity")
    job_id = build_receipt.get("job_id")
    job = _read_sqlite_row(
        state_db_file,
        "SELECT state,exit_code,pid,resource,executable_identity,stdout_log_path,stderr_log_path,stdout_log_sha256,stderr_log_sha256 FROM jobs WHERE job_id=?",
        (job_id,),
    ) if state_db_file is not None else None
    if job is None:
        missing.append("ember_lab_build_receipt.daemon_authority.job_row")
    elif operational is not None:
        if job[0] != operational.get("state"):
            missing.append("ember_lab_build_receipt.daemon_authority.job_state")
        if job[1] != operational.get("exit_code"):
            missing.append("ember_lab_build_receipt.daemon_authority.job_exit_code")
        if job[2] != operational.get("pid"):
            missing.append("ember_lab_build_receipt.daemon_authority.job_pid")
        if job[3] != operational.get("resource_lease"):
            missing.append("ember_lab_build_receipt.daemon_authority.job_lease")
        if job[4] != operational.get("executable_identity"):
            missing.append("ember_lab_build_receipt.daemon_authority.job_executable")
        receipt_logs = operational.get("logs")
        for label, path_index, sha_index in (("stdout", 5, 7), ("stderr", 6, 8)):
            declared = receipt_logs.get(label) if isinstance(receipt_logs, dict) else None
            log_path = _authority_file(authority_root, job[path_index])
            try:
                log_sha = hashlib.sha256(log_path.read_bytes()).hexdigest() if log_path is not None else None
            except OSError:
                log_sha = None
            if (
                not isinstance(declared, dict)
                or declared.get("sealed") is not True
                or log_path is None
                or declared.get("file_name") != log_path.name
                or declared.get("sha256") != job[sha_index]
                or log_sha != job[sha_index]
            ):
                missing.append(f"ember_lab_build_receipt.daemon_authority.job_{label}_log")
    schedule = _json_file(authority_root, alarm_path) if has_benchmark else None
    if has_benchmark and (not isinstance(schedule, dict) or schedule.get("schema_version") != _SCHEDULE_ALARM_SCHEMA):
        missing.append("ember_lab_build_receipt.daemon_authority.schedule_schema")
        schedule = None
    if has_benchmark and schedule is not None and operational is not None:
        if schedule.get("ember_lab_identity") != operational.get("ember_lab_identity"):
            missing.append("ember_lab_build_receipt.daemon_authority.schedule_identity")
    measurement = _read_sqlite_row(
        state_db_file,
        "SELECT measured_at_ms,measured_duration_ms,measured_tokens,measurement_outcome,measurement_receipt_sha256,measurement_daemon_binary_sha256,measurement_daemon_source_sha256 FROM schedule_runs WHERE job_id=?",
        (job_id,),
    ) if has_benchmark and state_db_file is not None else None
    if has_benchmark and (measurement is None or measurement[0] is None):
        missing.append("ember_lab_build_receipt.daemon_authority.measurement_row")
    elif has_benchmark and measurement[4] != measurement_sha:
        missing.append("ember_lab_build_receipt.daemon_authority.measurement_receipt")
    if has_benchmark and measurement is not None and operational is not None:
        identity = operational.get("ember_lab_identity")
        if (
            not isinstance(identity, dict)
            or measurement[5] != identity.get("binary_sha256")
            or measurement[6] != identity.get("source_sha256")
        ):
            missing.append("ember_lab_build_receipt.daemon_authority.measurement_identity")
    if has_benchmark and schedule is not None:
        runs = schedule.get("runs")
        run = next((row for row in runs if isinstance(row, dict) and row.get("job_id") == job_id), None) if isinstance(runs, list) else None
        if run is None:
            missing.append("ember_lab_build_receipt.daemon_authority.schedule_run")
        elif measurement is not None:
            for index, field in ((0, "measured_at_ms"), (1, "measured_duration_ms"), (2, "measured_tokens"), (3, "measurement_outcome"), (4, "measurement_receipt_sha256")):
                if run.get(field) != measurement[index]:
                    missing.append(f"ember_lab_build_receipt.daemon_authority.schedule_{field}")
            prediction_identity = run.get("prediction_daemon_identity")
            measurement_identity = run.get("measurement_daemon_identity")
            if (
                not isinstance(prediction_identity, dict)
                or prediction_identity.get("binary_sha256") != measurement[5]
                or prediction_identity.get("source_sha256") != measurement[6]
                or not isinstance(measurement_identity, dict)
                or measurement_identity.get("binary_sha256") != measurement[5]
                or measurement_identity.get("source_sha256") != measurement[6]
            ):
                missing.append("ember_lab_build_receipt.daemon_authority.schedule_identity")
    if has_benchmark and benchmark_receipt.get("raw_log_sha256") != measurement_sha:
        missing.append("ember_lab_build_receipt.daemon_authority.measurement_raw_log")
    return missing


def _content_addressed_json(root: Path, path_value: object, digest: object) -> dict | None:
    """Open an immutable daemon export whose file name is its exact raw SHA-256."""
    if not isinstance(digest, str) or not _DIGEST.fullmatch(digest):
        return None
    path = _authority_file(root, path_value)
    if path is None or path.name != f"{digest}.json":
        return None
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, ValueError):
        return None
    return value if hashlib.sha256(raw).hexdigest() == digest and isinstance(value, dict) else None


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
    authority_root = _approved_daemon_state_root(root)
    authority_files_root = authority_root or root
    if authority_root is None:
        missing.append("ember_lab_build_receipt.daemon_authority.locator")
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
    if not _digest_file(authority_files_root, receipt.get("dispatch_receipt_path"), receipt.get("dispatch_receipt_sha256")):
        missing.append("ember_lab_build_receipt.dispatch_receipt")
    if not _digest_file(authority_files_root, receipt.get("binary_manifest_path"), receipt.get("binary_manifest_sha256")):
        missing.append("ember_lab_build_receipt.binary_manifest")
    if not isinstance(build, dict) or build.get("binary_sha256") != receipt.get("binary_sha256"):
        missing.append("ember_lab_build_receipt.binary_sha256")
    producer_source_path = receipt.get("producer_source_path")
    producer_source_sha = receipt.get("producer_source_sha256")
    if producer_source_path != _EMBER_LAB_SOURCE_PATH:
        missing.append("ember_lab_build_receipt.producer_source_identity")
    if not isinstance(producer_source_sha, str) or not _DIGEST.fullmatch(producer_source_sha):
        missing.append("ember_lab_build_receipt.producer_source_sha256")
    elif not _digest_file(authority_files_root, producer_source_path, producer_source_sha):
        missing.append("ember_lab_build_receipt.producer_source_sha256")
    producer_binary_path = receipt.get("producer_binary_path")
    producer_binary_sha = receipt.get("producer_binary_sha256")
    if not isinstance(producer_binary_sha, str) or not _DIGEST.fullmatch(producer_binary_sha):
        missing.append("ember_lab_build_receipt.producer_binary_sha256")
    elif not _digest_file(authority_files_root, producer_binary_path, producer_binary_sha):
        missing.append("ember_lab_build_receipt.producer_binary_sha256")
    operational_path = receipt.get("operational_receipt_path")
    operational_sha = receipt.get("operational_receipt_sha256")
    operational = _content_addressed_json(authority_files_root, operational_path, operational_sha)
    if not isinstance(operational, dict):
        missing.append("ember_lab_build_receipt.daemon_authority")
    else:
        expected_keys = {
            "schema", "ember_lab_identity", "job_id", "identity_sha256",
            "resource_lease", "state", "pid", "executable_identity",
            "restart_policy", "exit_code", "logs", "events", "outage_events",
            "scientific_capability_evidence",
        }
        identity = operational.get("ember_lab_identity")
        logs = operational.get("logs")
        streams = logs if isinstance(logs, dict) else {}
        sealed_logs = all(
            isinstance(streams.get(name), dict)
            and streams[name].get("sealed") is True
            and isinstance(streams[name].get("file_name"), str)
            and Path(streams[name]["file_name"]).name == streams[name]["file_name"]
            and isinstance(streams[name].get("sha256"), str)
            and _DIGEST.fullmatch(streams[name]["sha256"])
            for name in ("stdout", "stderr")
        )
        if (
            set(operational) != expected_keys
            or operational.get("schema") != "ember-lab-operational-receipt-v1"
            or operational.get("job_id") != receipt.get("job_id")
            or not isinstance(operational.get("identity_sha256"), str)
            or not _DIGEST.fullmatch(operational["identity_sha256"])
            or not isinstance(operational.get("resource_lease"), str)
            or not operational["resource_lease"]
            or operational.get("state") != "exited"
            or not isinstance(operational.get("pid"), int)
            or operational["pid"] <= 0
            or not isinstance(operational.get("executable_identity"), str)
            or not operational["executable_identity"]
            or operational.get("restart_policy") != "never"
            or operational.get("exit_code") != 0
            or not isinstance(operational.get("events"), list)
            or not any(isinstance(event, dict) and event.get("kind") == "job_started" for event in operational["events"])
            or not any(isinstance(event, dict) and event.get("kind") == "job_exited" for event in operational["events"])
            or not isinstance(operational.get("outage_events"), list)
            or operational.get("scientific_capability_evidence") is not False
            or not sealed_logs
            or not isinstance(identity, dict)
            or set(identity) != {"source_sha256", "binary_sha256"}
            or identity.get("source_sha256") != producer_source_sha
            or identity.get("binary_sha256") != producer_binary_sha
        ):
            missing.append("ember_lab_build_receipt.daemon_authority")
    dispatch = _json_file(authority_files_root, receipt.get("dispatch_receipt_path"))
    if not isinstance(dispatch, dict) or dispatch.get("schema") != "ember-lab-dispatch-terminal-receipt-v1":
        missing.append("ember_lab_build_receipt.dispatch_schema")
    else:
        if dispatch.get("status") != "PASS" or dispatch.get("test_only") is True:
            missing.append("ember_lab_build_receipt.dispatch_status")
        if dispatch.get("job_id") != receipt.get("job_id"):
            missing.append("ember_lab_build_receipt.dispatch_job_id")
        if dispatch.get("source_manifest_sha256") != receipt.get("source_manifest_sha256"):
            missing.append("ember_lab_build_receipt.dispatch_source_manifest_sha256")
    binary = _json_file(authority_files_root, receipt.get("binary_manifest_path"))
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
    authority_root = _approved_daemon_state_root(root)
    authority_files_root = authority_root or root
    if authority_root is None:
        missing.append("ember_lab_benchmark_receipt.daemon_authority.locator")
    if receipt.get("test_only") is True or receipt.get("status") != "PASS":
        missing.append("ember_lab_benchmark_receipt.status")
    if receipt.get("authority") != "ember-cli->ember-lab":
        missing.append("ember_lab_benchmark_receipt.authority")
    if receipt.get("job_id") != build_receipt.get("job_id"):
        missing.append("ember_lab_benchmark_receipt.job_id")
    for field in (
        "hardware_uuid", "command", "config_sha256", "raw_log_path", "raw_log_sha256",
        "operational_receipt_path", "operational_receipt_sha256",
        "schedule_alarm_state_path", "schedule_alarm_state_sha256", "measurement_receipt_sha256",
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
    operational = _content_addressed_json(
        authority_files_root,
        receipt.get("operational_receipt_path"),
        receipt.get("operational_receipt_sha256"),
    )
    if not isinstance(operational, dict):
        missing.append("ember_lab_benchmark_receipt.daemon_authority")
    elif (
        receipt.get("job_id") != operational.get("job_id")
        or receipt.get("hardware_uuid") != operational.get("resource_lease")
    ):
        missing.append("ember_lab_benchmark_receipt.hardware_run_authority")
    if not _digest_file(authority_files_root, receipt.get("raw_log_path"), receipt.get("raw_log_sha256")):
        missing.append("ember_lab_benchmark_receipt.raw_log")
    raw_path = _authority_file(authority_root, receipt.get("raw_log_path"))
    if isinstance(operational, dict):
        stdout = operational.get("logs", {}).get("stdout") if isinstance(operational.get("logs"), dict) else None
        if (
            not isinstance(stdout, dict)
            or stdout.get("sealed") is not True
            or stdout.get("file_name") != (raw_path.name if raw_path is not None else None)
            or stdout.get("sha256") != receipt.get("raw_log_sha256")
        ):
            missing.append("ember_lab_benchmark_receipt.sample_log_authority")
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
    schedule = _json_file(authority_files_root, receipt.get("schedule_alarm_state_path"))
    if not _digest_file(
        authority_files_root,
        receipt.get("schedule_alarm_state_path"),
        receipt.get("schedule_alarm_state_sha256"),
    ) or not isinstance(schedule, dict):
        missing.append("ember_lab_benchmark_receipt.schedule_authority")
    else:
        identity = operational.get("ember_lab_identity") if isinstance(operational, dict) else None
        runs = schedule.get("runs")
        matching = [
            run for run in runs
            if isinstance(run, dict) and run.get("job_id") == receipt.get("job_id")
        ] if isinstance(runs, list) else []
        total_tokens = sum(row.get("tokens", 0) for row in raw_rows if isinstance(row, dict))
        total_duration = sum(row.get("elapsed_ms", 0) for row in raw_rows if isinstance(row, dict))
        run = matching[0] if len(matching) == 1 else None
        if (
            schedule.get("schema_version") != "ember-lab-schedule-alarm-state-v1"
            or schedule.get("ember_lab_identity") != identity
            or not isinstance(run, dict)
            or run.get("artifact_class") != "llmq-4090x1-3b-benchmark"
            or run.get("measured_tokens") != total_tokens
            or run.get("measured_duration_ms") != total_duration
            or run.get("measurement_outcome") != "COMPLETED"
            or run.get("measurement_receipt_sha256") != receipt.get("measurement_receipt_sha256")
            or run.get("prediction_daemon_identity") != identity
            or run.get("measurement_daemon_identity") != identity
        ):
            missing.append("ember_lab_benchmark_receipt.hardware_run_sample_authority")
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
    daemon_authority_missing = _ember_lab_daemon_authority_missing(
        Path(source_root),
        payload.get("ember_lab_build_receipt"),
        payload.get("ember_lab_benchmark_receipt"),
    )
    missing.extend(daemon_authority_missing)
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
        or any(field.startswith("ember_lab_build_receipt.daemon_authority") for field in missing)
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
