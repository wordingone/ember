# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "ember-restart-3b" / "python_environment.py"
SPEC = importlib.util.spec_from_file_location("issue1953_python_environment", SCRIPT)
assert SPEC and SPEC.loader
python_environment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(python_environment)

BUILD_MANIFEST = ROOT / "tools" / "ember-restart-3b" / "python-environment-build-v1.json"
SETUPTOOLS_SHA256 = "51a52592b3b99e102b609654876bd65f19f999935166d1352678931132b0c670"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
OUTPUT_EVIDENCE = {
    "stdout_filename": "stage.stdout.log", "stdout_sha256": EMPTY_SHA256,
    "stdout_bytes": 0, "stderr_filename": "stage.stderr.log",
    "stderr_sha256": EMPTY_SHA256, "stderr_bytes": 0,
}


def command_evidence(command_id: str, *, exit_code: int = 0) -> dict[str, object]:
    return {
        "id": command_id, "exit_code": exit_code, "duration_seconds": 1.0,
        "executed_argv": ["python", "-m", "pip"],
        "executed_argv_sha256": "4" * 64,
        **OUTPUT_EVIDENCE,
        "stdout_filename": f"{command_id}.stdout.log",
        "stderr_filename": f"{command_id}.stderr.log",
        "environment_conditioning": {
            "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.longpaths",
            "GIT_CONFIG_VALUE_0": "true", "GIT_TERMINAL_PROMPT": "0",
        },
        "temporary_directory_custody": {
            "path": "B:\\tmp\\ember-pip-1234abcd",
            "deleted_in_finally": True,
            "leak_count": 0,
        },
    }


BYPASS_ROWS = python_environment.build_environment_install_plan(
    python_environment.load_manifest(ROOT / "manifests" / "python-environment-v1.json"),
    python_executable="python.exe",
)["resolver_bypass_rows"]


def write_receipt_logs(parent: Path, stages: list[dict[str, object]]) -> None:
    for stage in stages:
        for command in stage["commands"]:
            for stream_name in ("stdout", "stderr"):
                (parent / command[f"{stream_name}_filename"]).write_bytes(b"")


def use_writable_short_temp(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, accept_receipt: bool = False,
) -> None:
    parent = tmp_path / "short-pip-temp"
    monkeypatch.setattr(python_environment, "_PIP_SHORT_TEMP_PARENT", parent)
    if accept_receipt:
        monkeypatch.setattr(
            python_environment,
            "_PIP_SHORT_TEMP_RE",
            re.compile(rf"^{re.escape(str(parent))}\\ember-pip-[0-9a-f]{{8}}$", re.IGNORECASE),
        )


def load_build_manifest() -> dict[str, object]:
    value = python_environment.load_build_manifest(BUILD_MANIFEST)
    python_environment.validate_build_manifest_shape(value)
    return value


def test_build_manifest_is_closed_to_the_one_exact_backend_wheel() -> None:
    manifest = load_build_manifest()
    assert manifest == {
        "schema_version": "ember-python-environment-build-v1",
        "goal_id": "EMBER-02",
        "workstream_id": "EMBER-02B",
        "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
        "environment": {"implementation": "CPython", "python_version": "3.10.11"},
        "backend": {
            "distribution": "setuptools",
            "version": "84.0.0",
            "requirement": "setuptools==84.0.0",
            "artifact": {
                "filename": "setuptools-84.0.0-py3-none-any.whl",
                "sha256": SETUPTOOLS_SHA256,
                "requires_python": ">=3.10",
            },
        },
    }
    substituted = json.loads(json.dumps(manifest))
    substituted["backend"]["artifact"]["sha256"] = "0" * 64
    with pytest.raises(python_environment.EnvironmentContractError, match="fixed setuptools wheel"):
        python_environment.validate_build_manifest_shape(substituted)


def test_backend_requirement_and_pip_argv_are_hash_enforced_and_report_bound(tmp_path: Path) -> None:
    manifest = load_build_manifest()
    requirements = tmp_path / "build-requirements.txt"
    report = tmp_path / "backend-report.json"
    assert python_environment.build_backend_requirement_bytes(manifest) == (
        f"setuptools==84.0.0 --hash=sha256:{SETUPTOOLS_SHA256}\n".encode()
    )
    argv = python_environment.build_backend_install_argv(
        manifest,
        python_executable="python",
        requirements_path=requirements,
        report_path=report,
    )
    assert argv[:4] == ["python", "-m", "pip", "install"]
    assert "--require-hashes" in argv
    assert "--only-binary=:all:" in argv
    assert "--force-reinstall" in argv
    assert "--no-deps" in argv
    assert argv[argv.index("--report") + 1] == str(report)
    assert argv[argv.index("-r") + 1] == str(requirements)
    assert python_environment.build_local_install_argv("python") == [
        "python", "-m", "pip", "install", "--no-deps", "--no-build-isolation", "-e", ".",
    ]


def test_environment_stage_splits_resolvable_core_and_disclosed_exact_pin_tail() -> None:
    manifest = python_environment.load_manifest(ROOT / "manifests" / "python-environment-v1.json")
    plan = python_environment.build_environment_install_plan(
        manifest, python_executable="python.exe", cache_dir=Path("B:/custody/pip-cache"),
    )
    tail = plan["resolver_bypass_rows"]
    assert [row["distribution"] for row in tail] == ["peft", "transformers", "trl", "unsloth"]
    assert all("unsloth 2026.2.1 caps transformers" in row["reason"] for row in tail)
    assert "--no-deps" in plan["exact_pin_no_deps_argv"]
    assert plan["resolved_core_argv"][plan["resolved_core_argv"].index("--cache-dir") + 1] == "B:\\custody\\pip-cache"
    for row in tail:
        assert row["requirement"] in plan["exact_pin_no_deps_argv"]
        assert row["requirement"] not in plan["resolved_core_argv"]
    assert plan["pip_check_argv"] == ["python.exe", "-m", "pip", "check"]


def test_pip_check_accepts_only_the_one_disclosed_metadata_conflict() -> None:
    expected = (
        b"unsloth 2026.2.1 has requirement transformers>=4.51.3,<=4.57.6, "
        b"but you have transformers 5.8.0.dev0.\n"
    )
    result = python_environment.validate_disclosed_pip_check(
        exit_code=1, stdout=expected, stderr=b"",
    )
    assert result["pip_check_disposition"] == "DISCLOSED_EXPECTED_UNSLOTH_TRANSFORMERS_METADATA_CONFLICT"
    assert result["pip_check_disclosed_conflict_lines"] == [expected.decode().strip()]
    with pytest.raises(python_environment.EnvironmentContractError):
        python_environment.validate_disclosed_pip_check(
            exit_code=1, stdout=expected + b"another 1.0 has requirement missing>=2\n", stderr=b"",
        )


def test_explicit_receipt_is_no_overwrite_self_hashed_and_binds_report(tmp_path: Path) -> None:
    report = tmp_path / "backend-report.json"
    report.write_text('{"install":[]}', encoding="utf-8")
    receipt_path = tmp_path / "install-receipt.json"
    stages = [
        {"id": "environment_packages", "result": "PASS_WITH_DISCLOSED_METADATA_CONFLICT", "exit_code": 0, "duration_seconds": 3.0, "commands": [command_evidence("resolved_core"), command_evidence("exact_pin_no_deps_tail"), command_evidence("post_install_pip_check", exit_code=1)], "resolver_bypass_rows": BYPASS_ROWS, "pip_check_disposition": "DISCLOSED_EXPECTED_UNSLOTH_TRANSFORMERS_METADATA_CONFLICT", "pip_check_disclosed_conflict_lines": ["unsloth 2026.2.1 has requirement transformers>=4.51.3,<=4.57.6, but you have transformers 5.8.0.dev0."]},
        {"id": "build_backend", "result": "PASS", "exit_code": 0, "duration_seconds": 1.0, "commands": [command_evidence("build_backend")], "requirements_sha256": "6" * 64, "report_sha256": hashlib.sha256(report.read_bytes()).hexdigest(), "artifact_filename": "setuptools-84.0.0-py3-none-any.whl", "artifact_sha256": SETUPTOOLS_SHA256, "artifact_requires_python": ">=3.10", "manifest_artifact_sha256": SETUPTOOLS_SHA256, "artifact_matches_manifest": True, "host_conditioned_local_wheel": False},
        {"id": "local_editable", "result": "PASS", "exit_code": 0, "duration_seconds": 1.0, "commands": [command_evidence("local_editable")]},
    ]
    receipt = python_environment.build_install_receipt(
        legacy_manifest_sha256="1" * 64,
        build_manifest_sha256="2" * 64,
        pyproject_sha256="3" * 64,
        stages=stages,
    )
    write_receipt_logs(tmp_path, stages)
    python_environment.write_install_receipt_no_replace(receipt_path, receipt)
    reopened = python_environment.load_install_receipt(receipt_path)
    assert reopened["result"] == "PASS"
    assert reopened["stages"][1]["artifact_matches_manifest"] is True
    with pytest.raises(FileExistsError, match="no-overwrite"):
        python_environment.write_install_receipt_no_replace(receipt_path, receipt)


def test_installed_backend_and_editable_src_package_are_named_verification_legs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = load_build_manifest()

    class FakeDistribution:
        def read_text(self, name: str) -> str:
            assert name == "direct_url.json"
            return json.dumps({"url": ROOT.as_uri(), "dir_info": {"editable": True}})

    monkeypatch.setattr(python_environment.importlib.metadata, "version", lambda name: "84.0.0" if name == "setuptools" else "0.0.0")
    monkeypatch.setattr(python_environment.importlib.metadata, "distribution", lambda name: FakeDistribution())
    monkeypatch.setattr(
        python_environment.importlib.util,
        "find_spec",
        lambda name: SimpleNamespace(origin=str(ROOT / "src" / "ember" / "__init__.py")),
    )
    result = python_environment.verify_packaging_installation(ROOT, manifest)
    assert result == {
        "backend_exact_version": "PASS",
        "local_direct_url_editable": "PASS",
        "local_module_src_resolution": "PASS",
    }


@pytest.mark.parametrize(
    ("negative_id", "failure_class"),
    [
        ("SUBSTITUTED_BACKEND_ARTIFACT", "HASH_MISMATCH_REFUSED"),
        ("SDIST_SUBSTITUTION", "ONLY_BINARY_REFUSED"),
        ("LOCAL_PACKAGE_ABSENT", "LOCAL_EDITABLE_MISSING"),
    ],
)
def test_three_named_negative_receipts_are_closed_and_self_hashed(
    negative_id: str, failure_class: str,
) -> None:
    receipt = python_environment.build_negative_receipt(
        negative_id=negative_id,
        failure_class=failure_class,
        exit_code=1,
        restored=True,
    )
    assert receipt["result"] == "EXPECTED_REFUSAL"
    assert receipt["restored"] is True
    python_environment.validate_negative_receipt(receipt)


def test_cli_help_requires_explicit_install_and_verify_receipt_paths() -> None:
    assert "install" in python_environment._parser().format_help()
    assert "three-stage" in python_environment.__doc__
    with pytest.raises(SystemExit):
        python_environment.main(["--root", str(ROOT), "install"])
    with pytest.raises(SystemExit):
        python_environment.main(["--root", str(ROOT), "verify", "--check-installed"])
    with pytest.raises(SystemExit):
        python_environment.main([
            "--root", str(ROOT), "verify", "--install-receipt", "unused.json",
        ])


def test_pip_stage_captures_exact_stdout_and_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    observed: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs: object) -> SimpleNamespace:
        observed.update(kwargs)
        return SimpleNamespace(returncode=7, stdout=b"resolver-out\n", stderr=b"resolver-error\n")

    monkeypatch.setattr(python_environment.subprocess, "run", fake_run)
    use_writable_short_temp(monkeypatch, tmp_path)
    exit_code, _duration, stdout, stderr, temp_custody = python_environment._run_pip(
        ["python.exe", "-m", "pip"], root=ROOT,
    )
    assert exit_code == 7
    assert stdout == b"resolver-out\n"
    assert stderr == b"resolver-error\n"
    assert observed["capture_output"] is True
    environment = observed["env"]
    assert isinstance(environment, dict)
    assert environment["GIT_CONFIG_KEY_0"] == "core.longpaths"
    assert environment["GIT_CONFIG_VALUE_0"] == "true"
    assert environment["TMP"] == temp_custody["path"]
    assert environment["TEMP"] == temp_custody["path"]
    assert environment["TMPDIR"] == temp_custody["path"]
    assert temp_custody["deleted_in_finally"] is True
    assert temp_custody["leak_count"] == 0
    assert not Path(temp_custody["path"]).exists()


def test_install_command_runs_three_stages_and_hashes_named_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(list(argv))
        if "--report" in argv:
            report_path = Path(argv[argv.index("--report") + 1])
            report_path.write_text(json.dumps({
                "install": [{
                    "metadata": {"name": "setuptools", "version": "84.0.0", "requires_python": ">=3.10"},
                    "download_info": {
                        "url": "https://files.pythonhosted.org/packages/setuptools-84.0.0-py3-none-any.whl",
                        "archive_info": {"hashes": {"sha256": SETUPTOOLS_SHA256}},
                    },
                }],
            }), encoding="utf-8")
        if argv[-2:] == ["pip", "check"]:
            return SimpleNamespace(
                returncode=1,
                stdout=(b"unsloth 2026.2.1 has requirement transformers>=4.51.3,<=4.57.6, "
                        b"but you have transformers 5.8.0.dev0.\n"),
                stderr=b"",
            )
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(python_environment, "validate_repository_contract", lambda **_kwargs: {"status": "PASS"})
    monkeypatch.setattr(python_environment, "validate_observed_environment", lambda _manifest: None)
    monkeypatch.setattr(python_environment.subprocess, "run", fake_run)
    use_writable_short_temp(monkeypatch, tmp_path, accept_receipt=True)
    receipt_path = tmp_path / "install.json"
    assert python_environment.main([
        "--root", str(ROOT), "install", "--receipt", str(receipt_path),
    ]) == 0
    assert len(calls) == 5
    receipt = python_environment.load_install_receipt(receipt_path)
    report_path = tmp_path / "install-backend-report.json"
    assert receipt["stages"][1]["report_sha256"] == hashlib.sha256(report_path.read_bytes()).hexdigest()
    assert receipt["stages"][1]["artifact_matches_manifest"] is True
    serialized = receipt_path.read_text(encoding="utf-8")
    assert str(tmp_path) not in serialized
    assert str(ROOT) not in serialized


def test_install_failure_still_writes_explicit_self_hashed_custody(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(python_environment, "validate_repository_contract", lambda **_kwargs: {"status": "PASS"})
    monkeypatch.setattr(python_environment, "validate_observed_environment", lambda _manifest: None)
    use_writable_short_temp(monkeypatch, tmp_path)
    monkeypatch.setattr(
        python_environment.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=7, stdout=b"", stderr=b"resolver failure\n",
        ),
    )
    receipt_path = tmp_path / "failed.json"
    assert python_environment.main([
        "--root", str(ROOT), "install", "--receipt", str(receipt_path),
    ]) == 7
    value = json.loads(receipt_path.read_text(encoding="utf-8"))
    claimed = value.pop("self_sha256")
    assert claimed == hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert value["result"] == "FAIL"
    assert value["failed_stage"] == "environment_packages"
    stderr_path = tmp_path / "failed-resolved-core.stderr.log"
    assert stderr_path.read_bytes() == b"resolver failure\n"
    command = value["stages"][0]["commands"][0]
    assert command["stderr_filename"] == stderr_path.name
    assert command["stderr_sha256"] == hashlib.sha256(
        stderr_path.read_bytes()
    ).hexdigest()
    assert command["stderr_bytes"] == len(b"resolver failure\n")


def test_verify_check_installed_consumes_only_the_explicit_bound_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    report = tmp_path / "report.json"
    report.write_text("{}", encoding="utf-8")
    stages = [
        {"id": "environment_packages", "result": "PASS_WITH_DISCLOSED_METADATA_CONFLICT", "exit_code": 0, "duration_seconds": 0.3, "commands": [command_evidence("resolved_core"), command_evidence("exact_pin_no_deps_tail"), command_evidence("post_install_pip_check", exit_code=1)], "resolver_bypass_rows": BYPASS_ROWS, "pip_check_disposition": "DISCLOSED_EXPECTED_UNSLOTH_TRANSFORMERS_METADATA_CONFLICT", "pip_check_disclosed_conflict_lines": ["unsloth 2026.2.1 has requirement transformers>=4.51.3,<=4.57.6, but you have transformers 5.8.0.dev0."]},
        {"id": "build_backend", "result": "PASS", "exit_code": 0, "duration_seconds": 0.1, "commands": [command_evidence("build_backend")], "requirements_sha256": "9" * 64, "report_sha256": hashlib.sha256(report.read_bytes()).hexdigest(), "artifact_filename": "setuptools-84.0.0-py3-none-any.whl", "artifact_sha256": SETUPTOOLS_SHA256, "artifact_requires_python": ">=3.10", "manifest_artifact_sha256": SETUPTOOLS_SHA256, "artifact_matches_manifest": True, "host_conditioned_local_wheel": False},
        {"id": "local_editable", "result": "PASS", "exit_code": 0, "duration_seconds": 0.1, "commands": [command_evidence("local_editable")]},
    ]
    receipt = python_environment.build_install_receipt(
        legacy_manifest_sha256=hashlib.sha256((ROOT / "manifests" / "python-environment-v1.json").read_bytes()).hexdigest(),
        build_manifest_sha256=hashlib.sha256(BUILD_MANIFEST.read_bytes()).hexdigest(),
        pyproject_sha256=hashlib.sha256((ROOT / "pyproject.toml").read_bytes()).hexdigest(),
        stages=stages,
    )
    receipt_path = tmp_path / "install.json"
    write_receipt_logs(tmp_path, stages)
    python_environment.write_install_receipt_no_replace(receipt_path, receipt)
    monkeypatch.setattr(python_environment, "current_installed_versions", lambda _manifest: {})
    monkeypatch.setattr(python_environment, "current_installed_sources", lambda _manifest: {})
    monkeypatch.setattr(python_environment, "validate_repository_contract", lambda **_kwargs: {"status": "PASS"})
    monkeypatch.setattr(python_environment, "validate_observed_environment", lambda _manifest: None)
    monkeypatch.setattr(python_environment, "validate_installed_sources", lambda *_args: None)
    monkeypatch.setattr(
        python_environment,
        "verify_packaging_installation",
        lambda *_args: {"backend_exact_version": "PASS", "local_direct_url_editable": "PASS", "local_module_src_resolution": "PASS"},
    )
    assert python_environment.main([
        "--root", str(ROOT), "verify", "--check-installed",
        "--install-receipt", str(receipt_path),
    ]) == 0

    tampered = json.loads(receipt_path.read_text(encoding="utf-8"))
    tampered["identity"]["pyproject_sha256"] = "0" * 64
    tampered.pop("self_sha256")
    tampered["self_sha256"] = hashlib.sha256(
        json.dumps(tampered, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    tampered_path = tmp_path / "tampered.json"
    tampered_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(python_environment.EnvironmentContractError, match="identity differs"):
        python_environment.main([
            "--root", str(ROOT), "verify", "--check-installed",
            "--install-receipt", str(tampered_path),
        ])
