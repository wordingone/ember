#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Validate and install Ember's measured direct Python environment."""

from __future__ import annotations

import argparse
import ast
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "ember-python-environment-v1"
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
    "platform",
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
_VERSION_RE = re.compile(r"^[0-9][A-Za-z0-9.+_-]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_DIST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_IMPORT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_EXCLUDED_PARTS = {"data", "receipts", "scratch", "state", "tests", "test"}


class EnvironmentContractError(ValueError):
    """Raised when the environment authority fails closed."""


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
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise EnvironmentContractError(f"manifest is malformed JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise EnvironmentContractError("manifest root must be an object")
    return payload


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
    if not isinstance(observed, dict):
        raise EnvironmentContractError("observed_environment must be an object")
    _require_exact_keys(observed, _ENVIRONMENT_KEYS, "observed_environment")
    for key in sorted(_ENVIRONMENT_KEYS):
        _require_text(observed.get(key), f"observed_environment.{key}")

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
        if path in seen_paths or Path(path).is_absolute() or ".." in Path(path).parts:
            raise EnvironmentContractError(f"{label}.path is unsafe or duplicate")
        seen_paths.add(path)

    linked = manifest.get("linked_manifests")
    if not isinstance(linked, dict):
        raise EnvironmentContractError("linked_manifests must be an object")
    _require_exact_keys(linked, _LINKED_KEYS, "linked_manifests")
    for key in sorted(_LINKED_KEYS):
        path = _require_text(linked.get(key), f"linked_manifests.{key}")
        if Path(path).is_absolute() or ".." in Path(path).parts:
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


def validate_installed_versions(
    manifest: Mapping[str, Any],
    installed_versions: Mapping[str, str],
) -> None:
    normalized = {
        _normalized_distribution(name): version
        for name, version in installed_versions.items()
    }
    for row in manifest["packages"]:
        key = _normalized_distribution(row["distribution"])
        actual = normalized.get(key)
        if actual is None and not row["install_by_default"]:
            continue
        if actual != row["version"]:
            raise EnvironmentContractError(
                "installed version mismatch for "
                f"{row['distribution']}: expected {row['version']}, got {actual}"
            )


def current_installed_versions(manifest: Mapping[str, Any]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for row in manifest["packages"]:
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


def current_installed_sources(
    manifest: Mapping[str, Any],
) -> dict[str, dict[str, Any] | None]:
    sources: dict[str, dict[str, Any] | None] = {}
    for row in manifest["packages"]:
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
            parsed = json.loads(raw)
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
) -> None:
    normalized = {
        _normalized_distribution(name): value
        for name, value in installed_sources.items()
    }
    for row in manifest["packages"]:
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


def validate_observed_environment(manifest: Mapping[str, Any]) -> None:
    observed = manifest["observed_environment"]
    actual = {
        "implementation": platform.python_implementation(),
        "python_version": platform.python_version(),
        "python_executable_basename": Path(sys.executable).name,
        "platform": platform.platform(),
        "pip_version": importlib.metadata.version("pip"),
    }
    if actual != observed:
        mismatches = [
            f"{key}: expected {observed[key]!r}, got {actual[key]!r}"
            for key in sorted(actual)
            if actual[key] != observed[key]
        ]
        raise EnvironmentContractError(
            "observed environment mismatch: " + "; ".join(mismatches)
        )


def validate_repository_contract(
    *,
    root: Path,
    manifest: Mapping[str, Any],
    installed_versions: Mapping[str, str] | None = None,
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
        validate_installed_versions(manifest, installed_versions)
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
            for row in manifest["packages"]
            if row["install_by_default"]
        ),
    ]


def _default_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=_default_root(),
        help="Ember repository root (default: script parent repository)",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("manifests/python-environment-v1.json"),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify", help="validate repository/import authority")
    verify.add_argument("--check-installed", action="store_true")
    sub.add_parser("install", help="install the exact measured direct environment")
    sub.add_parser("print-install-command", help="print the exact pip argv")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.root.resolve()
    manifest_path = args.manifest
    if not manifest_path.is_absolute():
        manifest_path = root / manifest_path
    manifest = load_manifest(manifest_path.resolve())
    if args.command == "verify":
        versions = (
            current_installed_versions(manifest)
            if args.check_installed
            else None
        )
        result = validate_repository_contract(
            root=root,
            manifest=manifest,
            installed_versions=versions,
        )
        if versions is not None:
            validate_observed_environment(manifest)
            validate_installed_sources(
                manifest,
                current_installed_sources(manifest),
            )
        result["installed_versions_checked"] = versions is not None
        result["installed_sources_checked"] = versions is not None
        print(json.dumps(result, sort_keys=True))
        return 0
    validate_repository_contract(root=root, manifest=manifest)
    install_argv = build_install_argv(
        manifest,
        python_executable=sys.executable,
    )
    if args.command == "print-install-command":
        print(subprocess.list2cmdline(install_argv))
        return 0
    validate_observed_environment(manifest)
    completed = subprocess.run(install_argv, cwd=root, check=False)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
