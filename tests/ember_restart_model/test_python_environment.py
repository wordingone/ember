# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "ember-restart-3b" / "python_environment.py"
MANIFEST = ROOT / "manifests" / "python-environment-v1.json"
SPEC = importlib.util.spec_from_file_location("python_environment", SCRIPT)
assert SPEC and SPEC.loader
python_environment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(python_environment)


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_committed_manifest_covers_production_imports_and_prose() -> None:
    result = python_environment.validate_repository_contract(
        root=ROOT,
        manifest=load_manifest(),
    )
    assert result["status"] == "PASS"
    assert result["unmapped_imports"] == []
    assert result["duplicate_imports"] == []


def test_missing_import_mapping_fails_closed() -> None:
    manifest = load_manifest()
    manifest["packages"].pop(0)
    with pytest.raises(
        python_environment.EnvironmentContractError,
        match="unmapped production imports",
    ):
        python_environment.validate_repository_contract(root=ROOT, manifest=manifest)


def test_duplicate_distribution_pin_fails_closed() -> None:
    manifest = load_manifest()
    manifest["packages"].append(copy.deepcopy(manifest["packages"][0]))
    with pytest.raises(
        python_environment.EnvironmentContractError,
        match="duplicate distribution",
    ):
        python_environment.validate_manifest_shape(manifest)


def test_installed_version_mismatch_fails_closed() -> None:
    manifest = load_manifest()
    versions = {
        row["distribution"]: row["version"] for row in manifest["packages"]
    }
    versions[manifest["packages"][0]["distribution"]] = "0.0.0"
    with pytest.raises(
        python_environment.EnvironmentContractError,
        match="installed version mismatch",
    ):
        python_environment.validate_installed_versions(manifest, versions)


def test_missing_default_package_fails_but_missing_optional_package_is_allowed() -> None:
    manifest = load_manifest()
    versions = {
        row["distribution"]: row["version"]
        for row in manifest["packages"]
        if row["install_by_default"]
    }
    python_environment.validate_installed_versions(manifest, versions)

    default = next(row for row in manifest["packages"] if row["install_by_default"])
    versions.pop(default["distribution"])
    with pytest.raises(
        python_environment.EnvironmentContractError,
        match="installed version mismatch",
    ):
        python_environment.validate_installed_versions(manifest, versions)


def test_pip_options_are_closed_and_cannot_inject_installer_flags() -> None:
    manifest = load_manifest()
    manifest["pip_options"] = [
        *manifest["pip_options"],
        "--trusted-host",
        "example.invalid",
    ]
    with pytest.raises(
        python_environment.EnvironmentContractError,
        match="pip_options must be exactly",
    ):
        python_environment.validate_manifest_shape(manifest)


def test_index_source_must_match_the_executed_pip_index() -> None:
    manifest = load_manifest()
    torch = next(
        row for row in manifest["packages"] if row["distribution"] == "torch"
    )
    torch["source"]["locator"] = "https://example.invalid/whl/cu126"
    with pytest.raises(
        python_environment.EnvironmentContractError,
        match="index source must equal the executed pip index",
    ):
        python_environment.validate_manifest_shape(manifest)


def test_vcs_source_mismatch_fails_closed() -> None:
    manifest = load_manifest()
    sources = {row["distribution"]: None for row in manifest["packages"]}
    arc = next(
        row for row in manifest["packages"] if row["distribution"] == "arc-agi"
    )
    sources["arc-agi"] = {
        "archive_info": {
            "hashes": {"sha256": arc["source"]["artifact_sha256"]}
        }
    }
    transformer = next(
        row
        for row in manifest["packages"]
        if row["distribution"] == "transformers"
    )
    sources["transformers"] = {
        "url": transformer["source"]["locator"],
        "vcs_info": {"vcs": "git", "commit_id": "0" * 40},
    }
    with pytest.raises(
        python_environment.EnvironmentContractError,
        match="installed VCS source mismatch",
    ):
        python_environment.validate_installed_sources(manifest, sources)


def test_unknown_manifest_field_fails_closed() -> None:
    manifest = load_manifest()
    manifest["parallel_authority"] = True
    with pytest.raises(
        python_environment.EnvironmentContractError,
        match="manifest keys",
    ):
        python_environment.validate_manifest_shape(manifest)


def test_prose_authority_rejects_windows_rooted_path() -> None:
    manifest = load_manifest()
    manifest["prose_authority"][0]["path"] = r"\Windows\outside.md"
    with pytest.raises(
        python_environment.EnvironmentContractError,
        match="unsafe or duplicate",
    ):
        python_environment.validate_manifest_shape(manifest)


def test_linked_manifest_rejects_windows_rooted_path() -> None:
    manifest = load_manifest()
    manifest["linked_manifests"]["rust"] = r"\Windows\Cargo.toml"
    with pytest.raises(
        python_environment.EnvironmentContractError,
        match="must be repo-relative",
    ):
        python_environment.validate_manifest_shape(manifest)


def test_cli_rejects_an_alternate_manifest_authority(tmp_path: Path) -> None:
    alternative = tmp_path / "parallel-authority.json"
    alternative.write_text(
        json.dumps(load_manifest()),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit):
        python_environment.main([
            "--root", str(ROOT), "--manifest", str(alternative), "verify",
        ])


def test_contradictory_prose_marker_fails_closed(tmp_path: Path) -> None:
    manifest = load_manifest()
    doc = tmp_path / "README.md"
    doc.write_text("independent version prose", encoding="utf-8")
    manifest["prose_authority"] = [
        {
            "path": "README.md",
            "required_marker": python_environment.AUTHORITY_MARKER,
        }
    ]
    with pytest.raises(
        python_environment.EnvironmentContractError,
        match="dependency authority marker",
    ):
        python_environment.validate_prose_authority(tmp_path, manifest)


def test_install_command_is_exact_and_non_mutating_when_not_executed() -> None:
    manifest = load_manifest()
    argv = python_environment.build_install_argv(
        manifest,
        python_executable="python",
    )
    assert argv[:4] == ["python", "-m", "pip", "install"]
    assert argv[4 : 4 + len(manifest["pip_options"])] == manifest["pip_options"]
    expected = [
        row["requirement"]
        for row in manifest["packages"]
        if row["install_by_default"]
    ]
    assert argv[-len(expected) :] == expected
    assert "arc-agi==0.9.4" not in argv


def test_install_command_isolated_from_shell_local_pip_state() -> None:
    manifest = load_manifest()
    argv = python_environment.build_install_argv(
        manifest,
        python_executable="python",
    )
    assert argv[:9] == [
        "python", "-m", "pip", "install", "--isolated",
        "--index-url", "https://pypi.org/simple",
        "--extra-index-url", "https://download.pytorch.org/whl/cu126",
    ]


def test_install_refuses_environment_drift_before_pip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    subprocess_called = False

    def reject_environment(_manifest: dict) -> None:
        raise python_environment.EnvironmentContractError("observed environment mismatch")

    def forbidden_subprocess(*_args: object, **_kwargs: object) -> None:
        nonlocal subprocess_called
        subprocess_called = True
        raise AssertionError("pip must not run after environment refusal")

    monkeypatch.setattr(
        python_environment,
        "validate_repository_contract",
        lambda **_kwargs: {"status": "PASS"},
    )
    monkeypatch.setattr(
        python_environment,
        "validate_observed_environment",
        reject_environment,
    )
    monkeypatch.setattr(python_environment.subprocess, "run", forbidden_subprocess)
    with pytest.raises(
        python_environment.EnvironmentContractError,
        match="observed environment mismatch",
    ):
        python_environment.main([
            "--root", str(ROOT), "install",
            "--receipt", str(tmp_path / "install-receipt.json"),
        ])
    assert subprocess_called is False


def test_strict_utf8_manifest_loader_rejects_invalid_bytes(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_bytes(b'{"schema_version":"bad"}\xff')
    with pytest.raises(
        python_environment.EnvironmentContractError,
        match="strict UTF-8",
    ):
        python_environment.load_manifest(path)


def test_manifest_loader_rejects_duplicate_json_object_keys(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        '{"schema_version":"ember-python-environment-v1",'
        '"schema_version":"shadow-authority"}',
        encoding="utf-8",
    )
    with pytest.raises(
        python_environment.EnvironmentContractError,
        match="duplicate JSON object key",
    ):
        python_environment.load_manifest(path)


def test_installed_direct_url_rejects_duplicate_json_object_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeDistribution:
        def read_text(self, name: str) -> str:
            assert name == "direct_url.json"
            return (
                '{"url":"https://example.invalid/first",'
                '"url":"https://example.invalid/shadow"}'
            )

    monkeypatch.setattr(
        python_environment.importlib.metadata,
        "distribution",
        lambda _name: FakeDistribution(),
    )
    manifest = {
        "packages": [
            {"distribution": "example", "install_by_default": True}
        ]
    }
    with pytest.raises(
        python_environment.EnvironmentContractError,
        match="duplicate JSON object key",
    ):
        python_environment.current_installed_sources(manifest)
