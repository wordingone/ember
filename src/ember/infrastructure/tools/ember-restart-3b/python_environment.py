#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Run Ember's three-stage install from composed v1 + 02B-completion authority."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
import platform
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlparse

SCHEMA_VERSION = "ember-python-environment-v1"
BUILD_SCHEMA_VERSION = "ember-python-environment-build-v1"
INSTALL_RECEIPT_SCHEMA_VERSION = "ember-python-environment-install-receipt-v1"
NEGATIVE_RECEIPT_SCHEMA_VERSION = "ember-python-environment-negative-receipt-v1"
_SETUPTOOLS_VERSION = "84.0.0"
_SETUPTOOLS_REQUIREMENT = "setuptools==84.0.0"
_SETUPTOOLS_WHEEL = "setuptools-84.0.0-py3-none-any.whl"
_SETUPTOOLS_SHA256 = "51a52592b3b99e102b609654876bd65f19f999935166d1352678931132b0c670"
_SETUPTOOLS_REQUIRES_PYTHON = ">=3.10"
AUTHORITY_MARKER = (
    "Python dependency authority: manifests/python-environment-v1.json"
)
_MANIFEST_KEYS = {
    "schema_version",
    "goal_id",
    "workstream_id",
    "observed_environment",
    "pip_options",
    "packages",
    "optional_unavailable",
    "prose_authority",
    "linked_manifests",
}
_ENVIRONMENT_KEYS = {
    "implementation",
    "python_version",
    "python_executable_basename",
    "platform_pattern",
    "pip_version",
}
_PACKAGE_KEYS = {
    "distribution",
    "version",
    "requirement",
    "imports",
    "group",
    "source",
    "install_by_default",
    "compatibility",
    "platform_profiles",
    "platform_versions",
}
_SOURCE_KEYS = {"kind", "locator", "commit", "artifact_sha256"}
_OPTIONAL_KEYS = {"imports", "feature", "reason"}
_PROSE_KEYS = {"path", "required_marker"}
_LINKED_KEYS = {"rust", "typescript"}
_PRIMARY_INDEX_LOCATOR = "https://pypi.org/simple"
_EXPECTED_INDEX_LOCATOR = "https://download.pytorch.org/whl/cu126"
_EXPECTED_PIP_OPTIONS = [
    "--isolated",
    "--index-url",
    _PRIMARY_INDEX_LOCATOR,
    "--extra-index-url",
    _EXPECTED_INDEX_LOCATOR,
]
_RESOLVER_BYPASS_DISTRIBUTIONS = ("peft", "transformers", "trl", "unsloth", "unsloth-zoo")
_RESOLVER_BYPASS_REQUIREMENTS = (
    "peft==0.18.1",
    "transformers @ git+https://github.com/huggingface/transformers.git@5d9bce2548fc6fa70d0e38e7999a29bedaa4feeb",
    "trl==0.24.0",
    "unsloth==2026.2.1",
    "unsloth-zoo==2026.2.1",
)
_RESOLVER_BYPASS_REASON = (
    "manifest-preserved metadata conflict: exact tail metadata excludes the fixed "
    "transformers 5.8.0.dev0 VCS pin"
)
_PIP_CHECK_DISPOSITION = "DISCLOSED_EXPECTED_UNSLOTH_TRANSFORMERS_METADATA_CONFLICT"
_PIP_CHECK_AUTHORITY = {
    "source_issue": 1953,
    "terminal_report_sha256": "93f461eebe4f3f311a86c7257a3bf2a6af9a11b1aeb050366bd5520bd3be3141",
    "install_receipt_sha256": "f284689888470822974a87959c26f3707cc2de16a4fd2f20327cdcdd57fe3a61",
    "install_receipt_self_sha256": "e40911b1c41553c4ae2c4ff5cb402fdc4ac3da7036d50710bf246ae9e2ff72d6",
    "conflict_lines_sha256": "c5ac4c38584b8840f98c90f0fada2494085df0e7fbe64f63c5a2ce30918a8f32",
}
_PIP_ENVIRONMENT_CONDITIONING = {
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "core.longpaths",
    "GIT_CONFIG_VALUE_0": "true",
    "GIT_TERMINAL_PROMPT": "0",
}
if os.name == "nt":
    _PIP_SHORT_TEMP_PARENT = Path("B:/tmp")
    _PIP_SHORT_TEMP_RE = re.compile(
        r"^B:\\tmp\\ember-pip-[0-9a-f]{8}$", re.IGNORECASE
    )
else:
    _PIP_SHORT_TEMP_PARENT = Path("/tmp")
    _PIP_SHORT_TEMP_RE = re.compile(r"^/tmp/ember-pip-[0-9a-f]{8}$")
_COMPLETION_REQUIREMENTS = (
    "typer==0.24.0", "diffusers==0.35.2", "hf-transfer==0.1.9",
    "torchvision==0.25.0+cu126", "tyro==1.0.8", "unsloth-zoo==2026.2.1",
    "wheel==0.45.1", "xformers==0.0.35", "cut-cross-entropy==25.1.1",
    "msgspec==0.20.0",
)
_UNSLOTH_ZOO_TRANSFORMERS_REQUIREMENT = (
    "transformers!=4.52.0,!=4.52.1,!=4.52.2,!=4.52.3,!=4.53.0,!=4.54.0,"
    "!=4.55.0,!=4.55.1,!=4.57.4,!=4.57.5,<=4.57.6,>=4.51.3"
)
_VERSION_RE = re.compile(r"^[0-9][A-Za-z0-9.+_-]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_DIST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_IMPORT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_EXCLUDED_PARTS = {"data", "receipts", "scratch", "state", "tests", "test"}


class EnvironmentContractError(ValueError):
    """Raised when the environment authority fails closed."""


def _reject_duplicate_object_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EnvironmentContractError(
                f"duplicate JSON object key: {key!r}"
            )
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise EnvironmentContractError(f"non-finite JSON constant is forbidden: {value}")


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: set[str],
    label: str,
) -> None:
    if set(value) != expected:
        raise EnvironmentContractError(
            f"{label} keys must be exactly {sorted(expected)}; got {sorted(value)}"
        )


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise EnvironmentContractError(f"{label} must be a non-empty trimmed string")
    return value


def _require_string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise EnvironmentContractError(f"{label} must be a non-empty list")
    result: list[str] = []
    for index, item in enumerate(value):
        text = _require_text(item, f"{label}[{index}]")
        if text in result:
            raise EnvironmentContractError(f"{label} contains duplicate {text!r}")
        result.append(text)
    return result


def _normalized_distribution(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise EnvironmentContractError(
            f"manifest must be strict UTF-8: {exc}"
        ) from exc
    except OSError as exc:
        raise EnvironmentContractError(f"cannot read manifest: {exc}") from exc
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_object_keys,
            parse_constant=_reject_json_constant,
        )
    except json.JSONDecodeError as exc:
        raise EnvironmentContractError(f"manifest is malformed JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise EnvironmentContractError("manifest root must be an object")
    return payload


def load_build_manifest(path: Path) -> dict[str, Any]:
    return load_manifest(path)


def validate_build_manifest_shape(manifest: Mapping[str, Any]) -> None:
    expected = {
        "schema_version": BUILD_SCHEMA_VERSION,
        "goal_id": "EMBER-02",
        "workstream_id": "EMBER-02B",
        "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
        "environment": {"implementation": "CPython", "python_version": "3.10.11"},
        "backend": {
            "distribution": "setuptools",
            "version": _SETUPTOOLS_VERSION,
            "requirement": _SETUPTOOLS_REQUIREMENT,
            "artifact": {
                "filename": _SETUPTOOLS_WHEEL,
                "sha256": _SETUPTOOLS_SHA256,
                "requires_python": _SETUPTOOLS_REQUIRES_PYTHON,
            },
        },
        "pip_check_authority": _PIP_CHECK_AUTHORITY,
        "runtime_dependency_completion": [
            {
                "distribution": requirement.split("==", 1)[0],
                "version": requirement.split("==", 1)[1],
                "requirement": requirement,
                "resolver_mode": (
                    "exact_pin_no_deps_tail"
                    if requirement.startswith("unsloth-zoo==") else "resolver_core"
                ),
                "transformers_requirement": (
                    _UNSLOTH_ZOO_TRANSFORMERS_REQUIREMENT
                    if requirement.startswith("unsloth-zoo==") else None
                ),
            }
            for requirement in _COMPLETION_REQUIREMENTS
        ],
    }
    if dict(manifest) != expected:
        raise EnvironmentContractError("build manifest must bind the fixed setuptools wheel")


def _resolver_bypass_reason(distribution: str) -> str:
    if _normalized_distribution(distribution) == "unsloth-zoo":
        return "host dist-info transformers requirement: " + _UNSLOTH_ZOO_TRANSFORMERS_REQUIREMENT
    return _RESOLVER_BYPASS_REASON


def build_backend_requirement_bytes(
    manifest: Mapping[str, Any], *, artifact_uri: str | None = None,
) -> bytes:
    validate_build_manifest_shape(manifest)
    requirement = artifact_uri or str(manifest["backend"]["requirement"])
    return f"{requirement} --hash=sha256:{_SETUPTOOLS_SHA256}\n".encode()


def build_backend_install_argv(
    manifest: Mapping[str, Any], *, python_executable: str,
    requirements_path: Path, report_path: Path,
) -> list[str]:
    validate_build_manifest_shape(manifest)
    return [
        python_executable, "-m", "pip", "install", "--isolated", "--no-cache-dir",
        "--index-url", _PRIMARY_INDEX_LOCATOR, "--force-reinstall", "--no-deps",
        "--only-binary=:all:", "--require-hashes", "--report", str(report_path),
        "-r", str(requirements_path),
    ]


def build_local_install_argv(python_executable: str) -> list[str]:
    return [
        python_executable, "-m", "pip", "install", "--no-deps",
        "--no-build-isolation", "-e", ".",
    ]


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _self_hashed(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    result["self_sha256"] = hashlib.sha256(_canonical(result)).hexdigest()
    return result


def _verify_self_hash(value: Mapping[str, Any], label: str) -> dict[str, Any]:
    result = dict(value)
    claimed = result.pop("self_sha256", None)
    if not isinstance(claimed, str) or not _SHA256_RE.fullmatch(claimed):
        raise EnvironmentContractError(f"{label} self hash is malformed")
    if hashlib.sha256(_canonical(result)).hexdigest() != claimed:
        raise EnvironmentContractError(f"{label} self hash differs")
    result["self_sha256"] = claimed
    return result


def build_install_receipt(
    *, legacy_manifest_sha256: str, build_manifest_sha256: str,
    pyproject_sha256: str, isolated_interpreter: Mapping[str, Any],
    platform_profile: str, stages: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if platform_profile not in {"windows", "linux"}:
        raise EnvironmentContractError("install receipt platform profile is invalid")
    for label, value in (
        ("legacy manifest", legacy_manifest_sha256),
        ("build manifest", build_manifest_sha256),
        ("pyproject", pyproject_sha256),
    ):
        if not _SHA256_RE.fullmatch(value):
            raise EnvironmentContractError(f"{label} hash must be lowercase 64hex")
    interpreter_binding = dict(isolated_interpreter)
    if (
        set(interpreter_binding) != {"path", "python_version", "package_set_sha256"}
        or not isinstance(interpreter_binding.get("path"), str)
        or not interpreter_binding["path"]
        or Path(interpreter_binding["path"]).is_absolute()
        or not isinstance(interpreter_binding.get("python_version"), str)
        or not interpreter_binding["python_version"]
        or not _SHA256_RE.fullmatch(str(interpreter_binding.get("package_set_sha256", "")))
    ):
        raise EnvironmentContractError("isolated interpreter binding is malformed")
    rows = [dict(stage) for stage in stages]
    if [row.get("id") for row in rows] != ["environment_packages", "build_backend", "local_editable"]:
        raise EnvironmentContractError("install receipt must contain the three frozen stages")
    if any(type(row.get("exit_code")) is not int for row in rows):
        raise EnvironmentContractError("install receipt stage exit code is malformed")
    common_keys = {"id", "result", "exit_code", "duration_seconds", "commands"}
    environment_keys = common_keys | {
        "resolver_bypass_rows", "pip_check_disposition",
        "pip_check_disclosed_conflict_lines", "completion_report_filename",
        "completion_report_sha256", "resolver_governed_subdependencies",
        "pip_check_authority",
    }
    backend_keys = common_keys | {
        "requirements_sha256", "report_sha256", "artifact_filename", "artifact_sha256",
        "artifact_requires_python", "manifest_artifact_sha256", "artifact_matches_manifest",
        "host_conditioned_local_wheel",
    }
    if set(rows[0]) != environment_keys or set(rows[1]) != backend_keys or set(rows[2]) != common_keys:
        raise EnvironmentContractError("install receipt stage keys are not closed")
    expected_command_ids = {
        "environment_packages": [
            "resolved_core", "completion_resolver", "exact_pin_no_deps_tail",
            "post_install_pip_check",
        ],
        "build_backend": ["build_backend"],
        "local_editable": ["local_editable"],
    }
    command_keys = {
        "id", "exit_code", "duration_seconds", "executed_argv", "executed_argv_sha256",
        "stdout_filename", "stdout_sha256", "stdout_bytes",
        "stderr_filename", "stderr_sha256", "stderr_bytes",
        "environment_conditioning",
        "temporary_directory_custody",
    }
    for row in rows:
        if (
            not isinstance(row.get("duration_seconds"), (int, float))
            or not math.isfinite(float(row["duration_seconds"]))
            or float(row["duration_seconds"]) < 0
            or not isinstance(row.get("commands"), list)
            or [command.get("id") for command in row["commands"]]
            != expected_command_ids[row["id"]]
        ):
            raise EnvironmentContractError("install receipt stage evidence is malformed")
        for command in row["commands"]:
            if (
                not isinstance(command, dict)
                or set(command) != command_keys
                or type(command.get("exit_code")) is not int
                or not isinstance(command.get("duration_seconds"), (int, float))
                or not math.isfinite(float(command["duration_seconds"]))
                or float(command["duration_seconds"]) < 0
                or not isinstance(command.get("executed_argv"), list)
                or not _SHA256_RE.fullmatch(str(command.get("executed_argv_sha256", "")))
                or not isinstance(command.get("stdout_filename"), str)
                or not _SHA256_RE.fullmatch(str(command.get("stdout_sha256", "")))
                or type(command.get("stdout_bytes")) is not int
                or int(command["stdout_bytes"]) < 0
                or not isinstance(command.get("stderr_filename"), str)
                or not _SHA256_RE.fullmatch(str(command.get("stderr_sha256", "")))
                or type(command.get("stderr_bytes")) is not int
                or int(command["stderr_bytes"]) < 0
                or command.get("environment_conditioning") != _PIP_ENVIRONMENT_CONDITIONING
                or not isinstance(command.get("temporary_directory_custody"), dict)
                or set(command["temporary_directory_custody"]) != {
                    "path", "deleted_in_finally", "leak_count",
                }
                or not _PIP_SHORT_TEMP_RE.fullmatch(
                    str(command["temporary_directory_custody"].get("path", ""))
                )
                or command["temporary_directory_custody"].get("deleted_in_finally") is not True
                or command["temporary_directory_custody"].get("leak_count") != 0
            ):
                raise EnvironmentContractError("install command evidence is malformed")
    environment = rows[0]
    if (
        environment.get("result") != "PASS_WITH_DISCLOSED_METADATA_CONFLICT"
        or environment.get("exit_code") != 0
        or environment.get("pip_check_disposition") != _PIP_CHECK_DISPOSITION
        or not isinstance(environment.get("resolver_bypass_rows"), list)
        or not isinstance(environment.get("pip_check_disclosed_conflict_lines"), list)
        or [command["exit_code"] for command in environment["commands"]] != [0, 0, 0, 1]
        or not isinstance(environment.get("completion_report_filename"), str)
        or not _SHA256_RE.fullmatch(str(environment.get("completion_report_sha256", "")))
    ):
        raise EnvironmentContractError("environment package stage disclosure is malformed")
    expected_bypass_rows = [
        {
            "distribution": distribution,
            "requirement": requirement,
            "reason": _resolver_bypass_reason(distribution),
        }
        for distribution, requirement in zip(
            _RESOLVER_BYPASS_DISTRIBUTIONS, _RESOLVER_BYPASS_REQUIREMENTS, strict=True,
        )
    ]
    if environment["resolver_bypass_rows"] != expected_bypass_rows:
        raise EnvironmentContractError("resolver bypass disclosure differs from frozen tail")
    _validate_completion_census(environment.get("resolver_governed_subdependencies"))
    pip_check_lines = environment["pip_check_disclosed_conflict_lines"]
    validate_disclosed_pip_check(
        exit_code=1,
        stdout=("\n".join(pip_check_lines) + "\n").encode("utf-8"),
        stderr=b"",
        authority=environment["pip_check_authority"],
    )
    backend = rows[1]
    if (
        backend.get("result") != "PASS"
        or backend.get("exit_code") != 0
        or backend.get("artifact_filename") != _SETUPTOOLS_WHEEL
        or backend.get("artifact_sha256") != _SETUPTOOLS_SHA256
        or backend.get("artifact_requires_python") != _SETUPTOOLS_REQUIRES_PYTHON
        or backend.get("manifest_artifact_sha256") != _SETUPTOOLS_SHA256
        or backend.get("artifact_matches_manifest") is not True
        or not _SHA256_RE.fullmatch(str(backend.get("report_sha256", "")))
    ):
        raise EnvironmentContractError("install receipt backend artifact differs from manifest")
    if rows[2].get("result") != "PASS" or rows[2].get("exit_code") != 0:
        raise EnvironmentContractError("local editable stage is not PASS")
    return _self_hashed({
        "schema_version": INSTALL_RECEIPT_SCHEMA_VERSION,
        "result": "PASS" if all(row["exit_code"] == 0 for row in rows) else "FAIL",
        "identity": {
            "legacy_manifest_sha256": legacy_manifest_sha256,
            "build_manifest_sha256": build_manifest_sha256,
            "pyproject_sha256": pyproject_sha256,
            "platform_profile": platform_profile,
            "isolated_interpreter": interpreter_binding,
        },
        "stages": rows,
    })


def write_install_receipt_no_replace(path: Path, receipt: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(dict(receipt), sort_keys=True, indent=2, allow_nan=False).encode("utf-8") + b"\n"
    try:
        with path.open("xb") as stream:
            stream.write(raw)
    except FileExistsError as error:
        raise FileExistsError("install receipt custody is no-overwrite") from error


def load_install_receipt(path: Path) -> dict[str, Any]:
    value = load_manifest(path)
    value = _verify_self_hash(value, "install receipt")
    if set(value) != {"schema_version", "result", "identity", "stages", "self_sha256"}:
        raise EnvironmentContractError("install receipt keys are not closed")
    if value.get("schema_version") != INSTALL_RECEIPT_SCHEMA_VERSION or value.get("result") != "PASS":
        raise EnvironmentContractError("install receipt is not a terminal PASS")
    stages = value.get("stages")
    identity = value.get("identity")
    if not isinstance(identity, dict) or set(identity) != {
        "legacy_manifest_sha256", "build_manifest_sha256", "pyproject_sha256",
        "platform_profile", "isolated_interpreter",
    }:
        raise EnvironmentContractError("install receipt identity keys are not closed")
    if not isinstance(stages, list):
        raise EnvironmentContractError("install receipt stages are malformed")
    build_install_receipt(
        legacy_manifest_sha256=str(value.get("identity", {}).get("legacy_manifest_sha256", "")),
        build_manifest_sha256=str(value.get("identity", {}).get("build_manifest_sha256", "")),
        pyproject_sha256=str(value.get("identity", {}).get("pyproject_sha256", "")),
        platform_profile=str(value.get("identity", {}).get("platform_profile", "")),
        isolated_interpreter=value.get("identity", {}).get("isolated_interpreter", {}),
        stages=stages,
    )
    for stage in stages:
        for command in stage["commands"]:
            for stream_name in ("stdout", "stderr"):
                filename = command[f"{stream_name}_filename"]
                if Path(filename).name != filename:
                    raise EnvironmentContractError("install stage log filename is not local")
                log_path = path.parent / filename
                if (
                    not log_path.is_file()
                    or log_path.stat().st_size != command[f"{stream_name}_bytes"]
                    or _sha256_path(log_path) != command[f"{stream_name}_sha256"]
                ):
                    raise EnvironmentContractError("install stage log differs from receipt")
    environment = stages[0]
    completion_filename = environment["completion_report_filename"]
    if Path(completion_filename).name != completion_filename:
        raise EnvironmentContractError("completion report filename is not local")
    completion_path = path.parent / completion_filename
    if (
        not completion_path.is_file()
        or _sha256_path(completion_path) != environment["completion_report_sha256"]
        or _completion_census_from_report(completion_path)
        != environment["resolver_governed_subdependencies"]
    ):
        raise EnvironmentContractError("completion report differs from receipt")
    return value


def build_install_failure_receipt(
    *, legacy_manifest_sha256: str, build_manifest_sha256: str,
    pyproject_sha256: str, isolated_interpreter: Mapping[str, Any],
    platform_profile: str, stages: Sequence[Mapping[str, Any]], failed_stage: str,
) -> dict[str, Any]:
    if failed_stage not in {"environment_packages", "build_backend", "local_editable"}:
        raise EnvironmentContractError("install failure stage is invalid")
    identity = {
        "legacy_manifest_sha256": legacy_manifest_sha256,
        "build_manifest_sha256": build_manifest_sha256,
        "pyproject_sha256": pyproject_sha256,
        "platform_profile": platform_profile,
        "isolated_interpreter": dict(isolated_interpreter),
    }
    if any(
        not _SHA256_RE.fullmatch(str(identity[key]))
        for key in ("legacy_manifest_sha256", "build_manifest_sha256", "pyproject_sha256")
    ):
        raise EnvironmentContractError("install failure identity is malformed")
    if platform_profile not in {"windows", "linux"}:
        raise EnvironmentContractError("install failure platform profile is invalid")
    binding = identity["isolated_interpreter"]
    if (
        set(binding) != {"path", "python_version", "package_set_sha256"}
        or not isinstance(binding.get("path"), str)
        or not binding["path"]
        or Path(binding["path"]).is_absolute()
        or not isinstance(binding.get("python_version"), str)
        or not binding["python_version"]
        or not _SHA256_RE.fullmatch(str(binding.get("package_set_sha256", "")))
    ):
        raise EnvironmentContractError("install failure identity is malformed")
    rows = [dict(row) for row in stages]
    if not rows or rows[-1].get("id") != failed_stage or rows[-1].get("exit_code") in {None, 0}:
        raise EnvironmentContractError("install failure receipt does not bind the failed stage")
    return _self_hashed({
        "schema_version": INSTALL_RECEIPT_SCHEMA_VERSION,
        "result": "FAIL",
        "identity": identity,
        "failed_stage": failed_stage,
        "stages": rows,
    })


def build_negative_receipt(
    *, negative_id: str, failure_class: str, exit_code: int, restored: bool,
) -> dict[str, Any]:
    allowed = {
        "SUBSTITUTED_BACKEND_ARTIFACT": "HASH_MISMATCH_REFUSED",
        "SDIST_SUBSTITUTION": "ONLY_BINARY_REFUSED",
        "LOCAL_PACKAGE_ABSENT": "LOCAL_EDITABLE_MISSING",
    }
    if allowed.get(negative_id) != failure_class or type(exit_code) is not int or exit_code == 0 or restored is not True:
        raise EnvironmentContractError("negative receipt does not prove one restored expected refusal")
    return _self_hashed({
        "schema_version": NEGATIVE_RECEIPT_SCHEMA_VERSION,
        "result": "EXPECTED_REFUSAL",
        "negative_id": negative_id,
        "failure_class": failure_class,
        "exit_code": exit_code,
        "restored": restored,
    })


def validate_negative_receipt(receipt: Mapping[str, Any]) -> None:
    value = _verify_self_hash(receipt, "negative receipt")
    expected = build_negative_receipt(
        negative_id=str(value.get("negative_id")),
        failure_class=str(value.get("failure_class")),
        exit_code=int(value.get("exit_code", 0)),
        restored=value.get("restored") is True,
    )
    if expected != value:
        raise EnvironmentContractError("negative receipt fields differ")


def verify_packaging_installation(root: Path, build_manifest: Mapping[str, Any]) -> dict[str, str]:
    validate_build_manifest_shape(build_manifest)
    if importlib.metadata.version("setuptools") != _SETUPTOOLS_VERSION:
        raise EnvironmentContractError("backend_exact_version leg failed")
    distribution = importlib.metadata.distribution("ember")
    direct_text = distribution.read_text("direct_url.json")
    if not isinstance(direct_text, str):
        raise EnvironmentContractError("local_direct_url_editable leg failed")
    direct = json.loads(direct_text, object_pairs_hook=_reject_duplicate_object_keys)
    parsed = urlparse(str(direct.get("url", "")))
    path_text = unquote(parsed.path)
    if re.fullmatch(r"/[A-Za-z]:/.*", path_text):
        path_text = path_text[1:]
    direct_root = Path(path_text).resolve()
    if parsed.scheme != "file" or direct_root != root.resolve() or direct.get("dir_info", {}).get("editable") is not True:
        raise EnvironmentContractError("local_direct_url_editable leg failed")
    spec = importlib.util.find_spec("ember")
    expected_module = (root / "src" / "ember" / "__init__.py").resolve()
    if spec is None or not isinstance(spec.origin, str) or Path(spec.origin).resolve() != expected_module:
        raise EnvironmentContractError("local_module_src_resolution leg failed")
    return {
        "backend_exact_version": "PASS",
        "local_direct_url_editable": "PASS",
        "local_module_src_resolution": "PASS",
    }


def validate_manifest_shape(manifest: Mapping[str, Any]) -> None:
    _require_exact_keys(manifest, _MANIFEST_KEYS, "manifest")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise EnvironmentContractError(
            f"schema_version must be {SCHEMA_VERSION!r}"
        )
    if manifest.get("goal_id") != "EMBER-02":
        raise EnvironmentContractError("goal_id must be EMBER-02")
    if manifest.get("workstream_id") != "EMBER-02B":
        raise EnvironmentContractError("workstream_id must be EMBER-02B")

    observed = manifest.get("observed_environment")
    if not isinstance(observed, dict) or set(observed) != {"windows", "linux"}:
        raise EnvironmentContractError("observed_environment platform profiles must be exactly windows and linux")
    for profile in ("windows", "linux"):
        value = observed.get(profile)
        if not isinstance(value, dict):
            raise EnvironmentContractError(f"observed_environment.{profile} must be an object")
        _require_exact_keys(value, _ENVIRONMENT_KEYS, f"observed_environment.{profile}")
        for key in sorted(_ENVIRONMENT_KEYS):
            _require_text(value.get(key), f"observed_environment.{profile}.{key}")
        pattern_text = value["platform_pattern"]
        try:
            re.compile(pattern_text)
        except re.error as error:
            raise EnvironmentContractError(
                f"observed_environment.{profile}.platform_pattern is malformed"
            ) from error
        if not pattern_text.startswith("^") or not pattern_text.endswith("$"):
            raise EnvironmentContractError(
                f"observed_environment.{profile}.platform_pattern must be anchored"
            )

    pip_options = manifest.get("pip_options")
    if not isinstance(pip_options, list):
        raise EnvironmentContractError("pip_options must be a list")
    if pip_options != _EXPECTED_PIP_OPTIONS:
        raise EnvironmentContractError(
            f"pip_options must be exactly {_EXPECTED_PIP_OPTIONS!r}"
        )

    packages = manifest.get("packages")
    if not isinstance(packages, list) or not packages:
        raise EnvironmentContractError("packages must be a non-empty list")
    seen_distributions: dict[str, int] = {}
    seen_imports: dict[str, str] = {}
    for index, row in enumerate(packages):
        label = f"packages[{index}]"
        if not isinstance(row, dict):
            raise EnvironmentContractError(f"{label} must be an object")
        _require_exact_keys(row, _PACKAGE_KEYS, label)
        distribution = _require_text(row.get("distribution"), f"{label}.distribution")
        if not _DIST_RE.fullmatch(distribution):
            raise EnvironmentContractError(f"{label}.distribution is malformed")
        normalized = _normalized_distribution(distribution)
        if normalized in seen_distributions:
            raise EnvironmentContractError(
                f"duplicate distribution {distribution!r} at {label}"
            )
        seen_distributions[normalized] = index
        version = _require_text(row.get("version"), f"{label}.version")
        if not _VERSION_RE.fullmatch(version):
            raise EnvironmentContractError(f"{label}.version is malformed")
        requirement = _require_text(row.get("requirement"), f"{label}.requirement")
        imports = _require_string_list(row.get("imports"), f"{label}.imports")
        for import_name in imports:
            if not _IMPORT_RE.fullmatch(import_name):
                raise EnvironmentContractError(
                    f"{label}.imports contains malformed import {import_name!r}"
                )
            if import_name in seen_imports:
                raise EnvironmentContractError(
                    f"duplicate import {import_name!r} in "
                    f"{seen_imports[import_name]} and {label}"
                )
            seen_imports[import_name] = label
        if row.get("group") not in {"runtime", "optional"}:
            raise EnvironmentContractError(
                f"{label}.group must be runtime or optional"
            )
        install_by_default = row.get("install_by_default")
        if not isinstance(install_by_default, bool):
            raise EnvironmentContractError(
                f"{label}.install_by_default must be boolean"
            )
        compatibility = row.get("compatibility")
        if row["group"] == "runtime":
            if not install_by_default or compatibility is not None:
                raise EnvironmentContractError(
                    f"{label} runtime package must install by default without a compatibility note"
                )
        elif install_by_default or not isinstance(compatibility, str) or not compatibility.strip():
            raise EnvironmentContractError(
                f"{label} optional package must be excluded by default with a compatibility note"
            )
        platform_profiles = row.get("platform_profiles")
        if platform_profiles not in (
            ["windows"],
            ["linux"],
            ["windows", "linux"],
        ):
            raise EnvironmentContractError(
                f"{label}.platform_profiles must be a non-empty ordered subset "
                "of windows and linux"
            )
        platform_versions = row.get("platform_versions")
        if platform_versions is not None:
            if (
                not isinstance(platform_versions, dict)
                or list(platform_versions) != platform_profiles
            ):
                raise EnvironmentContractError(
                    f"{label}.platform_versions must bind every selected profile"
                )
            for profile, profile_version in platform_versions.items():
                if (
                    not isinstance(profile_version, str)
                    or not _VERSION_RE.fullmatch(profile_version)
                    or profile_version.split("+", 1)[0] != version.split("+", 1)[0]
                ):
                    raise EnvironmentContractError(
                        f"{label}.platform_versions.{profile} is malformed"
                    )
        source = row.get("source")
        if not isinstance(source, dict):
            raise EnvironmentContractError(f"{label}.source must be an object")
        _require_exact_keys(source, _SOURCE_KEYS, f"{label}.source")
        kind = source.get("kind")
        if kind not in {"pypi", "index", "vcs"}:
            raise EnvironmentContractError(f"{label}.source.kind is invalid")
        locator = source.get("locator")
        commit = source.get("commit")
        artifact_sha256 = source.get("artifact_sha256")
        for key, value in (
            ("locator", locator),
            ("commit", commit),
            ("artifact_sha256", artifact_sha256),
        ):
            if value is not None:
                _require_text(value, f"{label}.source.{key}")
        if artifact_sha256 is not None and not _SHA256_RE.fullmatch(
            artifact_sha256
        ):
            raise EnvironmentContractError(
                f"{label}.source.artifact_sha256 is malformed"
            )
        if kind == "pypi":
            expected = f"{distribution}=={version}"
            if requirement != expected or locator is not None or commit is not None:
                raise EnvironmentContractError(
                    f"{label} PyPI requirement must be exactly {expected!r}"
                )
        elif kind == "index":
            expected = f"{distribution}=={version}"
            if (
                requirement != expected
                or not isinstance(locator, str)
                or not locator.startswith("https://")
                or commit is not None
            ):
                raise EnvironmentContractError(
                    f"{label} index source/requirement is malformed"
                )
            if locator != _EXPECTED_INDEX_LOCATOR:
                raise EnvironmentContractError(
                    f"{label} index source must equal the executed pip index "
                    f"{_EXPECTED_INDEX_LOCATOR!r}"
                )
        else:
            if (
                not isinstance(locator, str)
                or not locator.startswith("https://")
                or not isinstance(commit, str)
                or not _COMMIT_RE.fullmatch(commit)
                or artifact_sha256 is not None
                or requirement
                != f"{distribution} @ git+{locator}@{commit}"
            ):
                raise EnvironmentContractError(
                    f"{label} VCS source/requirement is malformed"
                )

    optionals = manifest.get("optional_unavailable")
    if not isinstance(optionals, list):
        raise EnvironmentContractError("optional_unavailable must be a list")
    for index, row in enumerate(optionals):
        label = f"optional_unavailable[{index}]"
        if not isinstance(row, dict):
            raise EnvironmentContractError(f"{label} must be an object")
        _require_exact_keys(row, _OPTIONAL_KEYS, label)
        imports = _require_string_list(row.get("imports"), f"{label}.imports")
        _require_text(row.get("feature"), f"{label}.feature")
        _require_text(row.get("reason"), f"{label}.reason")
        for import_name in imports:
            if not _IMPORT_RE.fullmatch(import_name):
                raise EnvironmentContractError(
                    f"{label} contains malformed import {import_name!r}"
                )
            if import_name in seen_imports:
                raise EnvironmentContractError(
                    f"duplicate import {import_name!r} across package/optional rows"
                )
            seen_imports[import_name] = label

    prose = manifest.get("prose_authority")
    if not isinstance(prose, list) or not prose:
        raise EnvironmentContractError("prose_authority must be a non-empty list")
    seen_paths: set[str] = set()
    for index, row in enumerate(prose):
        label = f"prose_authority[{index}]"
        if not isinstance(row, dict):
            raise EnvironmentContractError(f"{label} must be an object")
        _require_exact_keys(row, _PROSE_KEYS, label)
        path = _require_text(row.get("path"), f"{label}.path")
        marker = _require_text(
            row.get("required_marker"), f"{label}.required_marker"
        )
        if marker != AUTHORITY_MARKER:
            raise EnvironmentContractError(
                f"{label}.required_marker must equal the authority marker"
            )
        relative_path = Path(path)
        if (
            path in seen_paths
            or relative_path.anchor
            or ".." in relative_path.parts
        ):
            raise EnvironmentContractError(f"{label}.path is unsafe or duplicate")
        seen_paths.add(path)

    linked = manifest.get("linked_manifests")
    if not isinstance(linked, dict):
        raise EnvironmentContractError("linked_manifests must be an object")
    _require_exact_keys(linked, _LINKED_KEYS, "linked_manifests")
    for key in sorted(_LINKED_KEYS):
        path = _require_text(linked.get(key), f"linked_manifests.{key}")
        relative_path = Path(path)
        if relative_path.anchor or ".." in relative_path.parts:
            raise EnvironmentContractError(
                f"linked_manifests.{key} must be repo-relative"
            )


def _tracked_python_paths(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="strict",
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise EnvironmentContractError(
            f"git ls-files failed: {result.stderr.strip()}"
        )
    paths = [Path(line) for line in result.stdout.splitlines() if line.strip()]
    if not paths:
        raise EnvironmentContractError("git ls-files returned no Python files")
    return paths


def production_import_roots(root: Path) -> list[str]:
    tracked = _tracked_python_paths(root)
    local_roots: set[str] = set()
    for relative in tracked:
        local_roots.add(relative.stem)
        local_roots.update(relative.parts[:-1])
    stdlib = set(sys.stdlib_module_names)
    stdlib.add("tomllib")
    imports: set[str] = set()
    for relative in tracked:
        lowered_parts = {part.lower() for part in relative.parts}
        name = relative.name.lower()
        if (
            lowered_parts & _EXCLUDED_PARTS
            or name.startswith("test_")
            or name.endswith(("_test.py", "_selftest.py"))
        ):
            continue
        path = root / relative
        try:
            source = path.read_text(encoding="utf-8-sig", errors="strict")
            tree = ast.parse(source, filename=relative.as_posix())
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            raise EnvironmentContractError(
                f"cannot scan production Python file {relative.as_posix()}: {exc}"
            ) from exc
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif (
                isinstance(node, ast.ImportFrom)
                and node.level == 0
                and node.module
            ):
                imports.add(node.module.split(".", 1)[0])
    return sorted(
        name
        for name in imports
        if name not in stdlib and name not in local_roots and not name.startswith("_")
    )


def validate_prose_authority(root: Path, manifest: Mapping[str, Any]) -> None:
    for row in manifest["prose_authority"]:
        path = root / row["path"]
        try:
            text = path.read_bytes().decode("utf-8", errors="strict")
        except (OSError, UnicodeDecodeError) as exc:
            raise EnvironmentContractError(
                f"cannot read prose authority {row['path']}: {exc}"
            ) from exc
        if row["required_marker"] not in text:
            raise EnvironmentContractError(
                f"dependency authority marker missing from {row['path']}"
            )


def _package_rows_for_profile(
    manifest: Mapping[str, Any], platform_profile: str | None,
) -> list[Mapping[str, Any]]:
    if platform_profile is None:
        return list(manifest["packages"])
    profile = platform_profile
    if profile not in {"windows", "linux"}:
        raise EnvironmentContractError(f"platform profile is unavailable: {profile!r}")
    return [
        row for row in manifest["packages"]
        if profile in row.get("platform_profiles", ("windows", "linux"))
    ]


def _expected_package_version(
    row: Mapping[str, Any], platform_profile: str,
) -> str:
    versions = row["platform_versions"]
    if isinstance(versions, Mapping):
        return str(versions[platform_profile])
    return str(row["version"])


def validate_installed_versions(
    manifest: Mapping[str, Any],
    installed_versions: Mapping[str, str],
    platform_profile: str | None = None,
) -> None:
    profile = platform_profile or inferred_platform_profile()
    normalized = {
        _normalized_distribution(name): version
        for name, version in installed_versions.items()
    }
    for row in _package_rows_for_profile(manifest, profile):
        key = _normalized_distribution(row["distribution"])
        actual = normalized.get(key)
        if actual is None and not row["install_by_default"]:
            continue
        expected = _expected_package_version(row, profile)
        if actual != expected:
            raise EnvironmentContractError(
                "installed version mismatch for "
                f"{row['distribution']}: expected {expected}, got {actual}"
            )


def current_installed_versions(
    manifest: Mapping[str, Any], platform_profile: str | None = None,
) -> dict[str, str]:
    versions: dict[str, str] = {}
    for row in _package_rows_for_profile(manifest, platform_profile):
        distribution = row["distribution"]
        try:
            versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError as exc:
            if not row["install_by_default"]:
                continue
            raise EnvironmentContractError(
                f"required distribution is not installed: {distribution}"
            ) from exc
    return versions


def validate_completion_versions(
    build_manifest: Mapping[str, Any], installed_versions: Mapping[str, str],
) -> None:
    validate_build_manifest_shape(build_manifest)
    normalized = {
        _normalized_distribution(name): version
        for name, version in installed_versions.items()
    }
    for row in build_manifest["runtime_dependency_completion"]:
        actual = normalized.get(_normalized_distribution(row["distribution"]))
        if actual != row["version"]:
            raise EnvironmentContractError(
                "completion version mismatch for "
                f"{row['distribution']}: expected {row['version']}, got {actual}"
            )


def current_completion_versions(build_manifest: Mapping[str, Any]) -> dict[str, str]:
    validate_build_manifest_shape(build_manifest)
    versions: dict[str, str] = {}
    for row in build_manifest["runtime_dependency_completion"]:
        distribution = row["distribution"]
        try:
            versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            continue
    return versions


def current_installed_sources(
    manifest: Mapping[str, Any],
    platform_profile: str | None = None,
) -> dict[str, dict[str, Any] | None]:
    sources: dict[str, dict[str, Any] | None] = {}
    for row in _package_rows_for_profile(manifest, platform_profile):
        distribution = row["distribution"]
        try:
            metadata = importlib.metadata.distribution(distribution)
        except importlib.metadata.PackageNotFoundError as exc:
            if not row["install_by_default"]:
                sources[distribution] = None
                continue
            raise EnvironmentContractError(
                f"required distribution is not installed: {distribution}"
            ) from exc
        raw = metadata.read_text("direct_url.json")
        if raw is None:
            sources[distribution] = None
            continue
        try:
            parsed = json.loads(
                raw,
                object_pairs_hook=_reject_duplicate_object_keys,
            )
        except json.JSONDecodeError as exc:
            raise EnvironmentContractError(
                f"installed direct_url.json is malformed for {distribution}: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise EnvironmentContractError(
                f"installed direct_url.json is not an object for {distribution}"
            )
        sources[distribution] = parsed
    return sources


def validate_installed_sources(
    manifest: Mapping[str, Any],
    installed_sources: Mapping[str, dict[str, Any] | None],
    platform_profile: str | None = None,
) -> None:
    normalized = {
        _normalized_distribution(name): value
        for name, value in installed_sources.items()
    }
    for row in _package_rows_for_profile(manifest, platform_profile):
        distribution = row["distribution"]
        direct = normalized.get(_normalized_distribution(distribution))
        if direct is None and not row["install_by_default"]:
            continue
        source = row["source"]
        if source["kind"] == "vcs":
            if not isinstance(direct, dict):
                raise EnvironmentContractError(
                    f"installed VCS source identity missing for {distribution}"
                )
            vcs = direct.get("vcs_info")
            if (
                direct.get("url") != source["locator"]
                or not isinstance(vcs, dict)
                or vcs.get("vcs") != "git"
                or vcs.get("commit_id") != source["commit"]
            ):
                raise EnvironmentContractError(
                    f"installed VCS source mismatch for {distribution}"
                )
            continue
        expected_hash = source["artifact_sha256"]
        if expected_hash is not None:
            archive = direct.get("archive_info") if isinstance(direct, dict) else None
            hashes = archive.get("hashes") if isinstance(archive, dict) else None
            if not isinstance(hashes, dict) or hashes.get("sha256") != expected_hash:
                raise EnvironmentContractError(
                    f"installed artifact source mismatch for {distribution}"
                )
        elif direct is not None:
            raise EnvironmentContractError(
                f"unrepresented direct URL source for {distribution}"
            )


def inferred_platform_profile() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    raise EnvironmentContractError(f"platform profile is unavailable for {sys.platform!r}")


def select_platform_profile(
    manifest: Mapping[str, Any], requested: str | None = None,
) -> Mapping[str, Any]:
    profile = requested or inferred_platform_profile()
    observed = manifest.get("observed_environment")
    if not isinstance(observed, Mapping) or profile not in {"windows", "linux"} or profile not in observed:
        raise EnvironmentContractError(f"platform profile is unavailable: {profile!r}")
    value = observed[profile]
    if not isinstance(value, Mapping):
        raise EnvironmentContractError(f"platform profile is unavailable: {profile!r}")
    return value


def validate_observed_environment(
    manifest: Mapping[str, Any], platform_profile: str | None = None,
) -> None:
    observed = select_platform_profile(manifest, platform_profile)
    actual = {
        "implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "python_executable_basename": Path(sys.executable).name,
        "pip_version": importlib.metadata.version("pip"),
    }
    mismatches = [
        f"{key}: expected {observed[key]!r}, got {actual[key]!r}"
        for key in sorted(actual)
        if actual[key] != observed[key]
    ]
    actual_platform = platform.platform()
    if re.fullmatch(str(observed["platform_pattern"]), actual_platform) is None:
        mismatches.append(
            "platform: expected fullmatch "
            f"{observed['platform_pattern']!r}, got {actual_platform!r}"
        )
    if mismatches:
        raise EnvironmentContractError(
            "observed environment mismatch: " + "; ".join(mismatches)
        )


def validate_repository_contract(
    *,
    root: Path,
    manifest: Mapping[str, Any],
    installed_versions: Mapping[str, str] | None = None,
    platform_profile: str | None = None,
) -> dict[str, Any]:
    validate_manifest_shape(manifest)
    mapped: dict[str, list[str]] = {}
    for row in [*manifest["packages"], *manifest["optional_unavailable"]]:
        for import_name in row["imports"]:
            mapped.setdefault(import_name, []).append(
                row.get("distribution", row.get("feature", "optional"))
            )
    actual = production_import_roots(root)
    unmapped = sorted(set(actual) - set(mapped))
    duplicate_imports = sorted(
        name for name, owners in mapped.items() if len(owners) != 1
    )
    stale = sorted(set(mapped) - set(actual))
    if unmapped:
        raise EnvironmentContractError(
            f"unmapped production imports: {', '.join(unmapped)}"
        )
    if duplicate_imports:
        raise EnvironmentContractError(
            f"duplicate import mappings: {', '.join(duplicate_imports)}"
        )
    if stale:
        raise EnvironmentContractError(
            f"manifest import mappings are stale: {', '.join(stale)}"
        )
    for path in manifest["linked_manifests"].values():
        if not (root / path).is_file():
            raise EnvironmentContractError(f"linked manifest is missing: {path}")
    validate_prose_authority(root, manifest)
    if installed_versions is not None:
        validate_installed_versions(
            manifest, installed_versions, platform_profile=platform_profile
        )
    return {
        "status": "PASS",
        "production_import_count": len(actual),
        "package_count": len(manifest["packages"]),
        "optional_unavailable_count": len(manifest["optional_unavailable"]),
        "unmapped_imports": unmapped,
        "duplicate_imports": duplicate_imports,
    }


def build_install_argv(
    manifest: Mapping[str, Any],
    *,
    python_executable: str,
    platform_profile: str | None = None,
) -> list[str]:
    validate_manifest_shape(manifest)
    return [
        python_executable,
        "-m",
        "pip",
        "install",
        *manifest["pip_options"],
        *(
            row["requirement"]
            for row in _package_rows_for_profile(manifest, platform_profile)
            if row["install_by_default"]
        ),
    ]


def build_environment_install_plan(
    manifest: Mapping[str, Any], *, build_manifest: Mapping[str, Any], python_executable: str,
    cache_dir: Path | None = None, completion_report_path: Path | None = None,
    platform_profile: str | None = None,
) -> dict[str, Any]:
    validate_manifest_shape(manifest)
    validate_build_manifest_shape(build_manifest)
    default_rows = [
        row for row in _package_rows_for_profile(manifest, platform_profile)
        if row["install_by_default"]
    ]
    completion_rows = list(build_manifest["runtime_dependency_completion"])
    completion_core_rows = [
        row for row in completion_rows if row["resolver_mode"] == "resolver_core"
    ]
    completion_tail_rows = [
        row for row in completion_rows if row["resolver_mode"] == "exact_pin_no_deps_tail"
    ]
    combined_rows = [*default_rows, *completion_tail_rows]
    bypass_rows = [
        row for row in combined_rows
        if _normalized_distribution(row["distribution"]) in _RESOLVER_BYPASS_DISTRIBUTIONS
    ]
    if tuple(_normalized_distribution(row["distribution"]) for row in bypass_rows) != _RESOLVER_BYPASS_DISTRIBUTIONS:
        raise EnvironmentContractError("resolver bypass rows differ from frozen manifest order")
    if tuple(row["requirement"] for row in bypass_rows) != _RESOLVER_BYPASS_REQUIREMENTS:
        raise EnvironmentContractError("resolver bypass requirements differ from frozen pins")
    core_rows = [row for row in default_rows if row not in bypass_rows]
    cache_options = ["--cache-dir", str(cache_dir)] if cache_dir is not None else []
    base = [
        python_executable, "-m", "pip", "install",
        *manifest["pip_options"], *cache_options,
    ]
    return {
        "resolved_core_argv": [*base, *(row["requirement"] for row in core_rows)],
        "completion_resolver_argv": [
            *base,
            *(["--report", str(completion_report_path)] if completion_report_path else []),
            *(row["requirement"] for row in completion_core_rows),
        ],
        "exact_pin_no_deps_argv": [
            *base, "--no-deps", *(row["requirement"] for row in bypass_rows),
        ],
        "pip_check_argv": [python_executable, "-m", "pip", "check"],
        "resolver_bypass_rows": [
            {
                "distribution": row["distribution"],
                "requirement": row["requirement"],
                "reason": _resolver_bypass_reason(row["distribution"]),
            }
            for row in bypass_rows
        ],
    }


def _validate_completion_census(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise EnvironmentContractError("completion resolver census is malformed")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != {"distribution", "version"}:
            raise EnvironmentContractError("completion resolver census row is malformed")
        distribution = _normalized_distribution(str(raw.get("distribution", "")))
        version = str(raw.get("version", ""))
        if distribution in seen or not _DIST_RE.fullmatch(distribution) or not _VERSION_RE.fullmatch(version):
            raise EnvironmentContractError("completion resolver census row is invalid")
        seen.add(distribution)
        rows.append({"distribution": distribution, "version": version})
    if rows != sorted(rows, key=lambda row: row["distribution"]):
        raise EnvironmentContractError("completion resolver census is not sorted")
    return rows


def _completion_census_from_report(path: Path) -> list[dict[str, str]]:
    report = load_manifest(path)
    installs = report.get("install")
    if not isinstance(installs, list):
        raise EnvironmentContractError("completion pip report install rows are malformed")
    rows = []
    for install in installs:
        metadata = install.get("metadata") if isinstance(install, dict) else None
        if not isinstance(metadata, dict):
            raise EnvironmentContractError("completion pip report metadata is malformed")
        rows.append({
            "distribution": _normalized_distribution(str(metadata.get("name", ""))),
            "version": str(metadata.get("version", "")),
        })
    rows.sort(key=lambda row: row["distribution"])
    return _validate_completion_census(rows)


def validate_disclosed_pip_check(
    *, exit_code: int, stdout: bytes, stderr: bytes,
    authority: Mapping[str, Any],
) -> dict[str, Any]:
    text = (stdout + stderr).decode("utf-8", errors="strict")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if (
        dict(authority) != _PIP_CHECK_AUTHORITY
        or exit_code != 1
        or bool(stderr)
        or hashlib.sha256(_canonical(lines)).hexdigest()
        != authority.get("conflict_lines_sha256")
    ):
        raise EnvironmentContractError(
            "pip check differs from authority-bound disclosed conflict set"
        )
    return {
        "pip_check_disposition": _PIP_CHECK_DISPOSITION,
        "pip_check_disclosed_conflict_lines": lines,
        "pip_check_authority": dict(authority),
    }


def _default_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=_default_root(),
        help="Ember repository root (default: script parent repository)",
    )
    parser.add_argument("--platform-profile", choices=("windows", "linux"))
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser(
        "verify", help="validate repository/import authority",
        description=(
            "Validate repository authority. With --check-installed, an explicit "
            "--install-receipt is required and backend, hash receipt, editable direct_url, "
            "and src/ember resolution are checked."
        ),
    )
    verify.add_argument("--check-installed", action="store_true")
    verify.add_argument("--install-receipt", type=Path)
    install = sub.add_parser(
        "install", help="run all three hash-governed install stages",
        description=(
            "One command composes read-only v1 authority, exact 02B completion rows, and a "
            "receipted census of resolver-governed completion subdependencies; then runs the "
            "resolvable core, completion resolver, disclosed exact-pin no-deps tail, and closed "
            "pip-check classification; the exact setuptools wheel follows via "
            "pip --require-hashes and a named --report; then the local editable src package "
            "with --no-deps --no-build-isolation. An explicit no-overwrite --receipt is required."
        ),
    )
    install.add_argument("--receipt", type=Path, required=True)
    install.add_argument(
        "--backend-wheel", type=Path,
        help="optional host-conditioned wheel; exact manifest filename and sha256 are mandatory",
    )
    sub.add_parser("print-install-command", help="print the exact staged pip plan")
    return parser


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def isolated_interpreter_path(root: Path, receipt_path: Path) -> Path:
    """Return the deterministic, run-scoped interpreter inside one checkout."""
    environment_root = root.resolve() / "state" / "python-environments" / receipt_path.stem
    return environment_root / ("Scripts/python.exe" if os.name == "nt" else "bin/python3")


def _lexical_relative_to_root(root: Path, interpreter: Path) -> Path:
    """Containment by lexical absolute paths: a POSIX venv interpreter is a symlink to
    its provisioner, so resolving it would escape the checkout on every Linux host."""
    root_lexical = Path(os.path.abspath(root))
    interpreter_lexical = Path(os.path.abspath(interpreter))
    try:
        Path(os.path.normcase(str(interpreter_lexical))).relative_to(
            Path(os.path.normcase(str(root_lexical)))
        )
        return Path(*interpreter_lexical.parts[len(root_lexical.parts):])
    except ValueError as error:
        raise EnvironmentContractError("isolated interpreter must be inside repository root") from error


def isolated_pip_pin_argv(interpreter: Path, pip_version: str) -> list[str]:
    """Pin the isolated interpreter's pip to the declared platform-profile version; the
    venv's bundled pip is whatever the provisioner shipped, never the declared one."""
    if not isinstance(pip_version, str) or not re.fullmatch(r"[0-9][0-9A-Za-z.]*", pip_version):
        raise EnvironmentContractError("platform profile pip_version is malformed")
    return [
        str(interpreter), "-I", "-m", "pip", "install", "--isolated", "--no-cache-dir",
        "--disable-pip-version-check", "--index-url", _PRIMARY_INDEX_LOCATOR, "--no-deps",
        f"pip=={pip_version}",
    ]


def create_isolated_interpreter(root: Path, interpreter: Path, pip_version: str | None = None) -> Path:
    """Create one no-overwrite venv; the host interpreter is only its provisioner."""
    root = Path(os.path.abspath(root))
    interpreter = Path(os.path.abspath(interpreter))
    _lexical_relative_to_root(root, interpreter)
    environment_root = interpreter.parents[1]
    if environment_root.exists():
        raise FileExistsError("isolated interpreter custody is no-overwrite")
    environment_root.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [sys.executable, "-m", "venv", str(environment_root)],
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        shell=False,
        creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
    )
    if completed.returncode != 0:
        raise EnvironmentContractError(
            "isolated interpreter bootstrap failed: "
            + bytes(completed.stderr).decode("utf-8", errors="replace").strip()
        )
    if not interpreter.is_file():
        raise EnvironmentContractError("isolated interpreter bootstrap produced no interpreter")
    if pip_version is not None:
        pinned = subprocess.run(
            isolated_pip_pin_argv(interpreter, pip_version),
            cwd=root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            shell=False,
            creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
        )
        if pinned.returncode != 0:
            raise EnvironmentContractError(
                "isolated interpreter pip pin failed: "
                + bytes(pinned.stderr).decode("utf-8", errors="replace").strip()
            )
    return interpreter


def build_isolated_interpreter_binding(root: Path, interpreter: Path) -> dict[str, str]:
    """Bind the interpreter identity and its normalized installed package set."""
    root = Path(os.path.abspath(root))
    interpreter = Path(os.path.abspath(interpreter))
    if not interpreter.is_file():
        raise EnvironmentContractError("isolated interpreter is absent")
    relative = _lexical_relative_to_root(root, interpreter)
    probe = (
        "import importlib.metadata,json,platform;"
        "print(json.dumps({'python_version':platform.python_version(),"
        "'packages':[{'name':d.metadata['Name'],'version':d.version} "
        "for d in importlib.metadata.distributions()]}))"
    )
    completed = subprocess.run(
        [str(interpreter), "-I", "-c", probe],
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        shell=False,
        creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
    )
    if completed.returncode != 0:
        raise EnvironmentContractError("isolated interpreter identity probe failed")
    try:
        observed = json.loads(bytes(completed.stdout).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise EnvironmentContractError("isolated interpreter identity probe is malformed") from error
    version = observed.get("python_version") if isinstance(observed, dict) else None
    packages = observed.get("packages") if isinstance(observed, dict) else None
    if not isinstance(version, str) or not version or not isinstance(packages, list):
        raise EnvironmentContractError("isolated interpreter identity probe is malformed")
    normalized = []
    for row in packages:
        if not isinstance(row, dict) or set(row) != {"name", "version"}:
            raise EnvironmentContractError("isolated interpreter package row is malformed")
        name = row.get("name")
        package_version = row.get("version")
        if not isinstance(name, str) or not name or not isinstance(package_version, str) or not package_version:
            raise EnvironmentContractError("isolated interpreter package row is malformed")
        normalized.append({
            "name": re.sub(r"[-_.]+", "-", name).lower(),
            "version": package_version,
        })
    normalized.sort(key=lambda row: (row["name"], row["version"]))
    if len({row["name"] for row in normalized}) != len(normalized):
        raise EnvironmentContractError("isolated interpreter package set has duplicate distributions")
    return {
        "path": relative.as_posix(),
        "python_version": version,
        "package_set_sha256": hashlib.sha256(_canonical(normalized)).hexdigest(),
    }


def validate_running_interpreter_binding(root: Path, binding: Mapping[str, Any]) -> None:
    """Refuse verification unless this process is the still-matching bound interpreter."""
    relative = binding.get("path")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise EnvironmentContractError("isolated interpreter binding path is malformed")
    root = Path(os.path.abspath(root))
    interpreter = Path(os.path.abspath(root / PurePosixPath(relative)))
    try:
        _lexical_relative_to_root(root, interpreter)
    except EnvironmentContractError as error:
        raise EnvironmentContractError("isolated interpreter binding escapes repository root") from error
    if os.path.normcase(str(interpreter)) != os.path.normcase(os.path.abspath(sys.executable)):
        raise EnvironmentContractError("verification is not running under receipt-bound interpreter")
    if build_isolated_interpreter_binding(root, interpreter) != dict(binding):
        raise EnvironmentContractError("receipt-bound interpreter package set differs")


def _sanitized_argv(
    argv: Sequence[str], *, root: Path, requirements_path: Path | None = None,
    report_path: Path | None = None, wheel_path: Path | None = None,
    cache_path: Path | None = None,
) -> list[str]:
    substitutions = {
        str(root): "<repo>",
        str(Path(sys.executable)): Path(sys.executable).name,
    }
    if requirements_path is not None:
        substitutions[str(requirements_path)] = "<generated-build-requirements>"
    if report_path is not None:
        substitutions[str(report_path)] = "<backend-report>"
    if wheel_path is not None:
        substitutions[str(wheel_path)] = "<manifest-bound-wheel>"
        substitutions[wheel_path.as_uri()] = "<manifest-bound-wheel>"
    if cache_path is not None:
        substitutions[str(cache_path)] = "<receipt-pip-cache>"
    return [substitutions.get(str(token), str(token)) for token in argv]


def _run_pip(
    argv: Sequence[str], *, root: Path,
) -> tuple[int, float, bytes, bytes, dict[str, Any]]:
    started = time.perf_counter()
    environment = os.environ.copy()
    environment.update(_PIP_ENVIRONMENT_CONDITIONING)
    _PIP_SHORT_TEMP_PARENT.mkdir(parents=True, exist_ok=True)
    short_temp = _PIP_SHORT_TEMP_PARENT / f"ember-pip-{secrets.token_hex(4)}"
    short_temp.mkdir(exist_ok=False)
    environment.update({
        "TMP": str(short_temp), "TEMP": str(short_temp), "TMPDIR": str(short_temp),
    })
    cleanup_error = ""
    completed: subprocess.CompletedProcess[bytes]
    try:
        completed = subprocess.run(
            list(argv), cwd=root, check=False, shell=False,
            capture_output=True, env=environment,
            creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
        )
    finally:
        try:
            shutil.rmtree(short_temp)
        except OSError as error:
            cleanup_error = f"short pip temp cleanup failed: {type(error).__name__}: {error}\n"
    deleted = not short_temp.exists()
    leak_count = 0 if deleted else 1 + sum(1 for _ in short_temp.rglob("*"))
    exit_code = int(completed.returncode)
    stderr = bytes(completed.stderr)
    if not deleted:
        exit_code = exit_code or 74
        stderr += cleanup_error.encode("utf-8", errors="replace")
    return (
        exit_code, time.perf_counter() - started,
        bytes(completed.stdout), stderr,
        {
            "path": str(short_temp),
            "deleted_in_finally": deleted,
            "leak_count": leak_count,
        },
    )


def _stage_log_paths(receipt_path: Path, stage_id: str) -> tuple[Path, Path]:
    stem = receipt_path.stem + "-" + stage_id.replace("_", "-")
    return (
        receipt_path.with_name(stem + ".stdout.log"),
        receipt_path.with_name(stem + ".stderr.log"),
    )


def _write_stage_logs_no_replace(
    receipt_path: Path, stage_id: str, stdout: bytes, stderr: bytes,
) -> dict[str, Any]:
    stdout_path, stderr_path = _stage_log_paths(receipt_path, stage_id)
    try:
        with stdout_path.open("xb") as stream:
            stream.write(stdout)
        with stderr_path.open("xb") as stream:
            stream.write(stderr)
    except FileExistsError as error:
        raise FileExistsError("install stage log custody is no-overwrite") from error
    return {
        "stdout_filename": stdout_path.name,
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
        "stdout_bytes": len(stdout),
        "stderr_filename": stderr_path.name,
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "stderr_bytes": len(stderr),
    }


def _run_pip_command(
    *, receipt_path: Path, command_id: str, argv: Sequence[str], root: Path,
    requirements_path: Path | None = None, report_path: Path | None = None,
    wheel_path: Path | None = None,
    cache_path: Path | None = None,
) -> tuple[dict[str, Any], bytes, bytes]:
    exit_code, duration, stdout, stderr, temp_custody = _run_pip(argv, root=root)
    evidence = {
        "id": command_id,
        "exit_code": exit_code,
        "duration_seconds": duration,
        "executed_argv": _sanitized_argv(
            argv, root=root, requirements_path=requirements_path,
            report_path=report_path, wheel_path=wheel_path, cache_path=cache_path,
        ),
        "executed_argv_sha256": hashlib.sha256(_canonical(list(argv))).hexdigest(),
        "environment_conditioning": dict(_PIP_ENVIRONMENT_CONDITIONING),
        "temporary_directory_custody": temp_custody,
        **_write_stage_logs_no_replace(receipt_path, command_id, stdout, stderr),
    }
    return evidence, stdout, stderr


def _validate_backend_report(path: Path, manifest: Mapping[str, Any]) -> dict[str, str]:
    if not path.is_file():
        raise EnvironmentContractError("build backend pip report is absent")
    report = load_manifest(path)
    installs = report.get("install")
    if not isinstance(installs, list) or len(installs) != 1 or not isinstance(installs[0], dict):
        raise EnvironmentContractError("build backend pip report must contain exactly one install row")
    row = installs[0]
    metadata = row.get("metadata")
    download = row.get("download_info")
    if not isinstance(metadata, dict) or not isinstance(download, dict):
        raise EnvironmentContractError("build backend pip report row is malformed")
    archive = download.get("archive_info")
    hashes = archive.get("hashes") if isinstance(archive, dict) else None
    observed_sha = hashes.get("sha256") if isinstance(hashes, dict) else None
    if observed_sha is None and isinstance(archive, dict):
        raw_hash = archive.get("hash")
        observed_sha = raw_hash.removeprefix("sha256=") if isinstance(raw_hash, str) else None
    url_name = Path(urlparse(str(download.get("url", ""))).path).name
    if (
        _normalized_distribution(str(metadata.get("name", ""))) != "setuptools"
        or str(metadata.get("version", "")) != _SETUPTOOLS_VERSION
        or str(metadata.get("requires_python", "")) != _SETUPTOOLS_REQUIRES_PYTHON
        or url_name != _SETUPTOOLS_WHEEL
        or observed_sha != _SETUPTOOLS_SHA256
    ):
        raise EnvironmentContractError("build backend pip report differs from fixed manifest artifact")
    return {
        "artifact_filename": url_name,
        "artifact_sha256": str(observed_sha),
        "artifact_requires_python": str(metadata["requires_python"]),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    root = args.root.resolve()
    manifest_path = root / "manifests" / "python-environment-v1.json"
    build_manifest_path = (
        root
        / "src"
        / "ember"
        / "infrastructure"
        / "tools"
        / "ember-restart-3b"
        / "python-environment-build-v1.json"
    )
    pyproject_path = root / "pyproject.toml"
    manifest = load_manifest(manifest_path)
    selected_platform_profile = args.platform_profile or inferred_platform_profile()
    build_manifest = load_build_manifest(build_manifest_path)
    validate_build_manifest_shape(build_manifest)
    if args.command == "verify":
        if args.check_installed and args.install_receipt is None:
            parser.error("verify --check-installed requires --install-receipt PATH")
        if not args.check_installed and args.install_receipt is not None:
            parser.error("verify --install-receipt requires --check-installed")
        versions = (
            current_installed_versions(
                manifest, platform_profile=selected_platform_profile
            )
            if args.check_installed
            else None
        )
        completion_versions = (
            current_completion_versions(build_manifest)
            if args.check_installed
            else None
        )
        result = validate_repository_contract(
            root=root,
            manifest=manifest,
            installed_versions=versions,
            platform_profile=selected_platform_profile,
        )
        if versions is not None:
            assert completion_versions is not None
            validate_completion_versions(build_manifest, completion_versions)
            validate_observed_environment(manifest, selected_platform_profile)
            validate_installed_sources(
                manifest,
                current_installed_sources(
                    manifest, platform_profile=selected_platform_profile
                ),
                platform_profile=selected_platform_profile,
            )
            receipt = load_install_receipt(args.install_receipt.resolve(strict=True))
            validate_running_interpreter_binding(root, receipt["identity"]["isolated_interpreter"])
            expected_identity = {
                "legacy_manifest_sha256": _sha256_path(manifest_path),
                "build_manifest_sha256": _sha256_path(build_manifest_path),
                "pyproject_sha256": _sha256_path(pyproject_path),
                "platform_profile": selected_platform_profile,
                "isolated_interpreter": receipt["identity"]["isolated_interpreter"],
            }
            if receipt.get("identity") != expected_identity:
                raise EnvironmentContractError("install receipt identity differs from repository authority")
            result["packaging_installation"] = verify_packaging_installation(root, build_manifest)
            result["install_receipt_self_sha256"] = receipt["self_sha256"]
        result["installed_versions_checked"] = versions is not None
        result["completion_versions_checked"] = completion_versions is not None
        result["installed_sources_checked"] = versions is not None
        print(json.dumps(result, sort_keys=True))
        return 0
    validate_repository_contract(root=root, manifest=manifest)
    if args.command == "print-install-command":
        print(json.dumps(
            build_environment_install_plan(
                manifest, build_manifest=build_manifest, python_executable=sys.executable,
                platform_profile=selected_platform_profile,
            ),
            sort_keys=True,
        ))
        return 0
    validate_observed_environment(manifest, selected_platform_profile)
    receipt_path = args.receipt.resolve()
    report_path = receipt_path.with_name(receipt_path.stem + "-backend-report.json")
    completion_report_path = receipt_path.with_name(
        receipt_path.stem + "-completion-report.json"
    )
    if receipt_path.exists():
        raise FileExistsError("install receipt custody is no-overwrite")
    if report_path.exists():
        raise FileExistsError("build backend report custody is no-overwrite")
    if completion_report_path.exists():
        raise FileExistsError("completion report custody is no-overwrite")
    for command_id in (
        "resolved_core", "completion_resolver", "exact_pin_no_deps_tail",
        "post_install_pip_check",
        "build_backend", "local_editable",
    ):
        if any(path.exists() for path in _stage_log_paths(receipt_path, command_id)):
            raise FileExistsError("install stage log custody is no-overwrite")
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    interpreter_path = isolated_interpreter_path(root, receipt_path)
    create_isolated_interpreter(
        root, interpreter_path,
        pip_version=str(select_platform_profile(manifest, selected_platform_profile)["pip_version"]),
    )
    # Fail fast on a binding defect here, so it can never mask a later stage failure.
    build_isolated_interpreter_binding(root, interpreter_path)
    wheel_path = args.backend_wheel.resolve(strict=True) if args.backend_wheel is not None else None
    if wheel_path is not None and (
        wheel_path.name != _SETUPTOOLS_WHEEL or _sha256_path(wheel_path) != _SETUPTOOLS_SHA256
    ):
        raise EnvironmentContractError("host-conditioned wheel differs from fixed manifest artifact")

    authority_hashes = {
        "legacy_manifest_sha256": _sha256_path(manifest_path),
        "build_manifest_sha256": _sha256_path(build_manifest_path),
        "pyproject_sha256": _sha256_path(pyproject_path),
    }
    def receipt_identity() -> dict[str, Any]:
        return {
            **authority_hashes,
            "platform_profile": selected_platform_profile,
            "isolated_interpreter": build_isolated_interpreter_binding(root, interpreter_path),
        }
    stages: list[dict[str, Any]] = []
    environment_plan = build_environment_install_plan(
        manifest, build_manifest=build_manifest, python_executable=str(interpreter_path),
        cache_dir=receipt_path.parent / "pip-cache",
        completion_report_path=completion_report_path,
        platform_profile=selected_platform_profile,
    )
    environment_commands: list[dict[str, Any]] = []
    core_command, _stdout, _stderr = _run_pip_command(
        receipt_path=receipt_path, command_id="resolved_core",
        argv=environment_plan["resolved_core_argv"], root=root,
        cache_path=receipt_path.parent / "pip-cache",
    )
    environment_commands.append(core_command)
    if core_command["exit_code"] != 0:
        stages.append({
            "id": "environment_packages", "result": "FAIL",
            "exit_code": core_command["exit_code"],
            "duration_seconds": sum(row["duration_seconds"] for row in environment_commands),
            "commands": environment_commands,
            "resolver_bypass_rows": environment_plan["resolver_bypass_rows"],
        })
        write_install_receipt_no_replace(
            receipt_path,
            build_install_failure_receipt(**receipt_identity(), stages=stages, failed_stage="environment_packages"),
        )
        return int(core_command["exit_code"])
    completion_command, _stdout, _stderr = _run_pip_command(
        receipt_path=receipt_path, command_id="completion_resolver",
        argv=environment_plan["completion_resolver_argv"], root=root,
        report_path=completion_report_path,
        cache_path=receipt_path.parent / "pip-cache",
    )
    environment_commands.append(completion_command)
    if completion_command["exit_code"] != 0:
        stages.append({
            "id": "environment_packages", "result": "FAIL",
            "exit_code": completion_command["exit_code"],
            "duration_seconds": sum(row["duration_seconds"] for row in environment_commands),
            "commands": environment_commands,
            "resolver_bypass_rows": environment_plan["resolver_bypass_rows"],
        })
        write_install_receipt_no_replace(
            receipt_path,
            build_install_failure_receipt(**receipt_identity(), stages=stages, failed_stage="environment_packages"),
        )
        return int(completion_command["exit_code"])
    completion_census = _completion_census_from_report(completion_report_path)
    tail_command, _stdout, _stderr = _run_pip_command(
        receipt_path=receipt_path, command_id="exact_pin_no_deps_tail",
        argv=environment_plan["exact_pin_no_deps_argv"], root=root,
        cache_path=receipt_path.parent / "pip-cache",
    )
    environment_commands.append(tail_command)
    if tail_command["exit_code"] != 0:
        stages.append({
            "id": "environment_packages", "result": "FAIL",
            "exit_code": tail_command["exit_code"],
            "duration_seconds": sum(row["duration_seconds"] for row in environment_commands),
            "commands": environment_commands,
            "resolver_bypass_rows": environment_plan["resolver_bypass_rows"],
            "completion_report_filename": completion_report_path.name,
            "completion_report_sha256": _sha256_path(completion_report_path),
            "resolver_governed_subdependencies": completion_census,
        })
        write_install_receipt_no_replace(
            receipt_path,
            build_install_failure_receipt(**receipt_identity(), stages=stages, failed_stage="environment_packages"),
        )
        return int(tail_command["exit_code"])
    pip_check_command, pip_check_stdout, pip_check_stderr = _run_pip_command(
        receipt_path=receipt_path, command_id="post_install_pip_check",
        argv=environment_plan["pip_check_argv"], root=root,
    )
    environment_commands.append(pip_check_command)
    try:
        pip_check_disclosure = validate_disclosed_pip_check(
            exit_code=int(pip_check_command["exit_code"]),
            stdout=pip_check_stdout, stderr=pip_check_stderr,
            authority=build_manifest["pip_check_authority"],
        )
    except EnvironmentContractError as error:
        stages.append({
            "id": "environment_packages", "result": "FAIL", "exit_code": 1,
            "duration_seconds": sum(row["duration_seconds"] for row in environment_commands),
            "commands": environment_commands,
            "resolver_bypass_rows": environment_plan["resolver_bypass_rows"],
            "completion_report_filename": completion_report_path.name,
            "completion_report_sha256": _sha256_path(completion_report_path),
            "resolver_governed_subdependencies": completion_census,
            "pip_check_classification_error": str(error),
        })
        write_install_receipt_no_replace(
            receipt_path,
            build_install_failure_receipt(**receipt_identity(), stages=stages, failed_stage="environment_packages"),
        )
        return 1
    stages.append({
        "id": "environment_packages",
        "result": "PASS_WITH_DISCLOSED_METADATA_CONFLICT",
        "exit_code": 0,
        "duration_seconds": sum(row["duration_seconds"] for row in environment_commands),
        "commands": environment_commands,
        "resolver_bypass_rows": environment_plan["resolver_bypass_rows"],
        "completion_report_filename": completion_report_path.name,
        "completion_report_sha256": _sha256_path(completion_report_path),
        "resolver_governed_subdependencies": completion_census,
        **pip_check_disclosure,
    })

    with tempfile.TemporaryDirectory(prefix="ember-build-authority-", dir=receipt_path.parent) as directory:
        requirements_path = Path(directory) / "build-requirements.txt"
        artifact_uri = wheel_path.as_uri() if wheel_path is not None else None
        requirements_path.write_bytes(
            build_backend_requirement_bytes(build_manifest, artifact_uri=artifact_uri)
        )
        backend_argv = build_backend_install_argv(
            build_manifest,
            python_executable=str(interpreter_path),
            requirements_path=requirements_path,
            report_path=report_path,
        )
        backend_command, _stdout, _stderr = _run_pip_command(
            receipt_path=receipt_path, command_id="build_backend",
            argv=backend_argv, root=root, requirements_path=requirements_path,
            report_path=report_path, wheel_path=wheel_path,
        )
        if backend_command["exit_code"] != 0:
            stages.append({
                "id": "build_backend", "result": "FAIL",
                "exit_code": backend_command["exit_code"],
                "duration_seconds": backend_command["duration_seconds"],
                "commands": [backend_command],
                "requirements_sha256": _sha256_path(requirements_path),
                "report_sha256": _sha256_path(report_path) if report_path.is_file() else None,
            })
            write_install_receipt_no_replace(
                receipt_path,
                build_install_failure_receipt(**receipt_identity(), stages=stages, failed_stage="build_backend"),
            )
            return int(backend_command["exit_code"])
        observed_artifact = _validate_backend_report(report_path, build_manifest)
        stages.append({
            "id": "build_backend", "result": "PASS", "exit_code": 0,
            "duration_seconds": backend_command["duration_seconds"],
            "commands": [backend_command],
            "requirements_sha256": _sha256_path(requirements_path),
            "report_sha256": _sha256_path(report_path),
            **observed_artifact,
            "manifest_artifact_sha256": _SETUPTOOLS_SHA256,
            "artifact_matches_manifest": observed_artifact["artifact_sha256"] == _SETUPTOOLS_SHA256,
            "host_conditioned_local_wheel": wheel_path is not None,
        })

    local_argv = build_local_install_argv(str(interpreter_path))
    local_command, _stdout, _stderr = _run_pip_command(
        receipt_path=receipt_path, command_id="local_editable",
        argv=local_argv, root=root,
    )
    stages.append({
        "id": "local_editable", "result": "PASS" if local_command["exit_code"] == 0 else "FAIL",
        "exit_code": local_command["exit_code"],
        "duration_seconds": local_command["duration_seconds"],
        "commands": [local_command],
    })
    if local_command["exit_code"] != 0:
        write_install_receipt_no_replace(
            receipt_path,
            build_install_failure_receipt(**receipt_identity(), stages=stages, failed_stage="local_editable"),
        )
        return int(local_command["exit_code"])
    receipt = build_install_receipt(
        **receipt_identity(),
        stages=stages,
    )
    write_install_receipt_no_replace(receipt_path, receipt)
    print(json.dumps({
        "status": "PASS", "receipt": str(args.receipt),
        "receipt_self_sha256": receipt["self_sha256"],
        "backend_report_sha256": stages[1]["report_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
