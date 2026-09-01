# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "docs_information_system.py"
PYTHON_ENVIRONMENT_SCRIPT = (
    REPO_ROOT / "tools" / "ember-restart-3b" / "python_environment.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("docs_information_system", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_python_environment_module():
    spec = importlib.util.spec_from_file_location(
        "issue1967_python_environment", PYTHON_ENVIRONMENT_SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def install_governed_launcher(root: Path, module) -> Path:
    source = REPO_ROOT / module.PUBLIC_PYTHON_LAUNCHER_PATH
    target = root / module.PUBLIC_PYTHON_LAUNCHER_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
    assert module.sha256_file(target) == module.PUBLIC_PYTHON_LAUNCHER_SHA256
    return target


def metadata_fixture() -> dict:
    return {
        "schema_version": "ember-doc-metadata-v1",
        "documents": [
            {
                "path": "README.md",
                "title": "Ember",
                "summary": "Project entry",
                "domain": "Governance",
                "document_type": "entry",
                "status": "normative",
                "authority_class": "GOVERNED_NORMATIVE",
                "audience": ["new-user"],
                "canonical_id": "ember.entry.root",
                "owner": "Governance",
                "supersedes": [],
            },
            {
                "path": "docs/start.md",
                "title": "Start",
                "summary": "Safe start",
                "domain": "Lab",
                "document_type": "guide",
                "status": "current",
                "authority_class": "CURRENT_GUIDANCE",
                "audience": ["operator"],
                "canonical_id": "ember.guide.start",
                "owner": "Lab",
                "supersedes": [],
            },
        ],
    }


def test_metadata_refuses_missing_path_and_duplicate_id(tmp_path: Path) -> None:
    module = load_module()
    write(tmp_path / "README.md", "# Ember\n")
    manifest = metadata_fixture()
    manifest["documents"][1]["canonical_id"] = "ember.entry.root"

    with pytest.raises(module.DocsInfoError, match="DUPLICATE_CANONICAL_ID"):
        module.validate_metadata(tmp_path, manifest)

    manifest["documents"][1]["canonical_id"] = "ember.guide.start"
    with pytest.raises(module.DocsInfoError, match="DOCUMENT_PATH_MISSING"):
        module.validate_metadata(tmp_path, manifest)

    del manifest["documents"][1]["authority_class"]
    with pytest.raises(module.DocsInfoError, match="METADATA_ROW_SCHEMA_INVALID"):
        module.validate_metadata(tmp_path, manifest)


def test_generated_index_is_deterministic_and_detects_drift(tmp_path: Path) -> None:
    module = load_module()
    write(tmp_path / "README.md", "# Ember\n")
    write(tmp_path / "docs/start.md", "# Start\n")
    manifest = metadata_fixture()

    first = module.render_index(manifest)
    second = module.render_index(json.loads(json.dumps(manifest)))

    assert first == second
    assert "ember.entry.root" in first
    assert "ember.guide.start" in first


def test_claim_map_rehashes_sources_and_refuses_stale(tmp_path: Path) -> None:
    module = load_module()
    source = tmp_path / "docs/source.md"
    write(source, "authority bytes\n")
    write(tmp_path / "README.md", "# Test document\n")
    digest = module.sha256_file(source)
    claim_map = {
        "schema_version": "ember-doc-claim-source-map-v1",
        "anchors": {"ember.claim.identity": "ember.claim.identity"},
        "claims": [
            {
                "claim_id": "ember.claim.identity",
                "document": "README.md",
                "source_class": "AUTHORITY_DERIVED",
                "status": "current",
                "sources": [{"path": "docs/source.md", "sha256": digest}],
            }
        ],
    }

    write(tmp_path / "README.md", '<a id="ember.claim.identity"></a>\n# Test document\n')

    module.validate_claim_map(tmp_path, claim_map)
    write(tmp_path / "README.md", "# Anchor removed\n")
    with pytest.raises(module.DocsInfoError, match="CLAIM_ANCHOR_MISSING"):
        module.validate_claim_map(tmp_path, claim_map)
    write(tmp_path / "README.md", '<a id="ember.claim.identity"></a>\n# Test document\n')
    write(source, "changed bytes\n")
    with pytest.raises(module.DocsInfoError, match="STALE_CLAIM_SOURCE"):
        module.validate_claim_map(tmp_path, claim_map)


def test_readme_guard_requires_conservation_and_bounded_intro(tmp_path: Path) -> None:
    module = load_module()
    readme = tmp_path / "README.md"
    write(readme, "# Ember\nplain language\n")
    with pytest.raises(module.DocsInfoError, match="CONSERVATION_BLOCK_MISSING"):
        module.validate_readme(readme)

    write(
        readme,
        "<!-- EMBER_CONSERVATION_V1\nmechanism_erasure=forbidden\n-->\n"
        "# Ember\nA bounded project introduction.\n",
    )
    module.validate_readme(readme)


def test_prose_path_scanner_keeps_full_nested_path(tmp_path: Path) -> None:
    module = load_module()
    write(tmp_path / "docs/domains/runtime/README.md", "# Runtime\n")
    write(tmp_path / "docs/map.md", "Read docs/domains/runtime/README.md.\n")
    rows = [{"path": "docs/map.md", "status": "current"}]
    counts = module.validate_references(tmp_path, rows, [])
    assert counts["prose_paths"] == 1


def test_bad_public_command_is_terminal_red(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_module()
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: module.subprocess.CompletedProcess(args[0], 7, "", "boom"),
    )
    commands = {
        "schema_version": "ember-public-command-replay-v1",
        "commands": [
            {
                "id": "bad",
                "argv": ["ember-test-command", "--fail"],
                "cwd": ".",
                "requirements": {"cpu": True, "gpu": False, "network": False},
            }
        ],
    }
    with pytest.raises(module.DocsInfoError, match="PUBLIC_COMMAND_FAILED"):
        module.run_public_commands(tmp_path, commands)


def test_windows_python_command_refuses_without_headless_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.delenv("EMBER_PUBLIC_PYTHON_LAUNCHER_JSON", raising=False)
    commands = {"commands": [{"id": "bootstrap-python", "argv": ["python", "tool.py"], "cwd": "."}]}

    with pytest.raises(module.DocsInfoError, match="PUBLIC_COMMAND_DIRECT_PYTHON_REFUSED"):
        module.run_public_commands(tmp_path, commands)


def test_headless_command_replay_custodies_actual_argv_and_no_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    monkeypatch.setattr(module.sys, "platform", "win32")
    launcher_path = install_governed_launcher(tmp_path, module)
    launcher = [
        "powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-File",
        str(launcher_path), "--",
    ]
    monkeypatch.setenv("EMBER_PUBLIC_PYTHON_LAUNCHER_JSON", json.dumps(launcher))
    observed = {}

    def fake_run(argv, **kwargs):
        observed["argv"] = argv
        observed["kwargs"] = kwargs
        _write_bound_interpreter_receipt(
            tmp_path, module,
            relative="state/python-environments/python-environment-install-v1/Scripts/python.exe",
        )
        return module.subprocess.CompletedProcess(argv, 0, "ok\n", "")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    commands = {"commands": [{"id": "bootstrap-python", "argv": ["python", "tool.py"], "cwd": "."}]}

    results = module.run_public_commands(tmp_path, commands)

    assert observed["argv"] == launcher + ["tool.py"]
    assert observed["kwargs"]["creationflags"] == module.NO_WINDOW
    assert observed["kwargs"]["stdin"] is module.subprocess.DEVNULL
    assert results[0]["manifest_argv"] == ["python", "tool.py"]
    assert results[0]["host_argv"] == launcher + ["tool.py"]
    assert results[0]["host_argv_sha256"] == module.sha256_bytes(
        module.canonical_json(launcher + ["tool.py"])
    )
    assert results[0]["stdout_sha256"] == module.sha256_bytes(b"ok\n")


def _write_bound_interpreter_receipt(
    root: Path, module, *, relative: str, materialize: bool = True,
) -> Path:
    interpreter = root / relative
    if materialize:
        interpreter.parent.mkdir(parents=True, exist_ok=True)
        interpreter.write_bytes(b"isolated-interpreter")
    else:
        assert interpreter.is_file()
    receipt = {
        "schema_version": "ember-python-environment-install-receipt-v1",
        "result": "PASS",
        "identity": {
            "legacy_manifest_sha256": "1" * 64,
            "build_manifest_sha256": "2" * 64,
            "pyproject_sha256": "3" * 64,
            "isolated_interpreter": {
                "path": relative.replace("/", "\\"),
                "python_version": "3.10.11",
                "package_set_sha256": "4" * 64,
            },
        },
        "stages": [],
    }
    receipt["self_sha256"] = module.sha256_bytes(module.canonical_compact(receipt))
    path = root / "state/receipts/python-environment-install-v1.json"
    write(path, json.dumps(receipt))
    return interpreter


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (
            r"state\python-environments\python-environment-install-v1\Scripts\python.exe",
            Path("state/python-environments/python-environment-install-v1/Scripts/python.exe"),
        ),
        (
            "state/python-environments/python-environment-install-v1/bin/python",
            Path("state/python-environments/python-environment-install-v1/bin/python"),
        ),
    ],
)
def test_portable_interpreter_path_accepts_windows_and_posix_venv_layouts(
    stored: str, expected: Path
) -> None:
    module = load_module()

    assert module.portable_interpreter_relative_path(stored) == expected


@pytest.mark.parametrize(
    "stored",
    [r"C:\outside\python.exe", r"\\server\share\python.exe", "/outside/python"],
)
def test_portable_interpreter_path_refuses_absolute_paths_on_every_host(stored: str) -> None:
    module = load_module()

    with pytest.raises(
        module.DocsInfoError,
        match="PUBLIC_COMMAND_INTERPRETER_OUTSIDE_CHECKOUT_REFUSED",
    ):
        module.portable_interpreter_relative_path(stored)


def test_nonbootstrap_python_refuses_missing_bound_interpreter_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    monkeypatch.setattr(module.sys, "platform", "win32")
    launcher_path = install_governed_launcher(tmp_path, module)
    monkeypatch.setenv(
        "EMBER_PUBLIC_PYTHON_LAUNCHER_JSON",
        json.dumps(["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(launcher_path), "--"]),
    )
    commands = {"commands": [{"id": "verify-authority", "argv": ["python", "tool.py"], "cwd": "."}]}

    with pytest.raises(module.DocsInfoError, match="PUBLIC_COMMAND_INTERPRETER_RECEIPT_MISSING"):
        module.run_public_commands(tmp_path, commands)


def test_nonbootstrap_python_refuses_receipt_interpreter_outside_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    outside = tmp_path.parent / "outside-python.exe"
    outside.write_bytes(b"outside")
    receipt = {
        "schema_version": "ember-python-environment-install-receipt-v1",
        "result": "PASS",
        "identity": {
            "legacy_manifest_sha256": "1" * 64,
            "build_manifest_sha256": "2" * 64,
            "pyproject_sha256": "3" * 64,
            "isolated_interpreter": {
                "path": str(outside),
                "python_version": "3.10.11",
                "package_set_sha256": "4" * 64,
            },
        },
        "stages": [],
    }
    receipt["self_sha256"] = module.sha256_bytes(module.canonical_compact(receipt))
    write(tmp_path / "state/receipts/python-environment-install-v1.json", json.dumps(receipt))

    with pytest.raises(module.DocsInfoError, match="PUBLIC_COMMAND_INTERPRETER_OUTSIDE_CHECKOUT_REFUSED"):
        module.load_public_interpreter_binding(tmp_path)


def test_replay_uses_receipt_bound_interpreter_after_bootstrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load_module()
    monkeypatch.setattr(module.sys, "platform", "win32")
    launcher_path = install_governed_launcher(tmp_path, module)
    launcher = ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(launcher_path), "--"]
    monkeypatch.setenv("EMBER_PUBLIC_PYTHON_LAUNCHER_JSON", json.dumps(launcher))
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((list(argv), kwargs))
        if len(calls) == 1:
            _write_bound_interpreter_receipt(
                tmp_path, module,
                relative="state/python-environments/python-environment-install-v1/Scripts/python.exe",
            )
        return module.subprocess.CompletedProcess(argv, 0, "ok\n", "")

    monkeypatch.setattr(module.subprocess, "run", fake_run)
    commands = {"commands": [
        {"id": "bootstrap-python", "argv": ["python", "bootstrap.py"], "cwd": "."},
        {"id": "verify-authority", "argv": ["python", "verify.py"], "cwd": "."},
    ]}
    results = module.run_public_commands(tmp_path, commands)

    assert "CODEX_PYTHON" not in calls[0][1].get("env", {})
    bound = calls[1][1]["env"]["CODEX_PYTHON"]
    assert Path(bound).resolve() == (
        tmp_path / "state/python-environments/python-environment-install-v1/Scripts/python.exe"
    ).resolve()
    assert results[1]["interpreter_binding"]["package_set_sha256"] == "4" * 64


def test_nonwindows_replay_executes_receipt_bound_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    venv = tmp_path / "bound-interpreter"
    created = module.subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(venv)],
        stdin=module.subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        creationflags=module.NO_WINDOW,
    )
    assert created.returncode == 0, created.stderr
    relative = (
        "bound-interpreter/Scripts/python.exe"
        if sys.platform == "win32"
        else "bound-interpreter/bin/python"
    )
    bound = _write_bound_interpreter_receipt(
        tmp_path, module, relative=relative, materialize=False,
    )
    observed = tmp_path / "child-executable.txt"
    monkeypatch.setattr(module.sys, "platform", "linux")
    commands = {"commands": [{
        "id": "verify-authority",
        "argv": [
            "python", "-c",
            f"import pathlib,sys;pathlib.Path({str(observed)!r}).write_text(sys.executable)",
        ],
        "cwd": ".",
    }]}
    results = module.run_public_commands(tmp_path, commands)

    reported_raw = Path(observed.read_text(encoding="utf-8"))
    assert reported_raw.resolve() == bound.resolve()
    assert reported_raw != Path(sys.executable)
    assert Path(results[0]["host_argv"][0]).resolve() == bound.resolve()
    assert module.portable_interpreter_relative_path(
        results[0]["interpreter_binding"]["path"]
    ) == Path(relative)


def _run_repo_launcher_identity(module, monkeypatch, bound_interpreter: Path) -> Path:
    launcher_path = REPO_ROOT / "scripts" / "headless-python.ps1"
    launcher = [
        "powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive",
        "-File", str(launcher_path), "--",
    ]
    monkeypatch.setenv("EMBER_PUBLIC_PYTHON_LAUNCHER_JSON", json.dumps(launcher))
    monkeypatch.setenv("CODEX_PYTHON", str(bound_interpreter))
    host_argv = module.public_command_host_argv(
        REPO_ROOT,
        ["python", "-c", "import json,sys;print(json.dumps({'executable':sys.executable}))"],
    )
    completed = module.subprocess.run(
        host_argv,
        stdin=module.subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        creationflags=module.NO_WINDOW,
        env=module.os.environ.copy(),
    )
    assert completed.returncode == 0, completed.stderr
    return Path(json.loads(completed.stdout.strip())["executable"]).resolve()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows headless launcher contract")
def test_repo_launcher_executes_exact_bound_interpreter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    reported = _run_repo_launcher_identity(module, monkeypatch, Path(sys.executable))
    assert reported == Path(sys.executable).resolve()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows headless launcher contract")
def test_repo_launcher_identity_probe_detects_different_interpreter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_module()
    venv = tmp_path / "planted-other-interpreter"
    created = module.subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(venv)],
        stdin=module.subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        creationflags=module.NO_WINDOW,
    )
    assert created.returncode == 0, created.stderr
    planted = venv / "Scripts" / "python.exe"
    reported = _run_repo_launcher_identity(module, monkeypatch, planted)
    assert reported == planted.resolve()
    assert reported != Path(sys.executable).resolve()


def test_repository_receipt_retains_per_command_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_module()
    command_results = [{"id": "one", "returncode": 0, "stdout_sha256": "a", "stderr_sha256": "b"}]
    monkeypatch.setattr(module, "run_public_commands", lambda root, commands: command_results)

    receipt = module.check_repository(REPO_ROOT, run_commands=True)

    assert receipt["commands_executed"] == 1
    assert receipt["command_results"] == command_results


def test_command_manifest_binds_276_row_census_to_four_command_subset() -> None:
    module = load_module()
    commands = {
        "schema_version": "ember-public-command-replay-v1",
        "filing_time_census": {"command_rows": 275},
        "governed_subset": {
            "authority_artifact_sha256": "c2eee97ca0ea1f24ef80f5a0a128ac48b88a0632c5a9b774f735648eb8c4fe54",
            "authority_artifact_lines": [242, 249],
            "selection": "FOUR_FINAL_PUBLIC_ENTRY_COMMANDS",
        },
        "commands": [],
    }
    with pytest.raises(module.DocsInfoError, match="PUBLIC_COMMAND_CENSUS_DENOMINATOR_INVALID"):
        module.validate_commands_manifest(commands)


def test_bootstrap_public_command_requires_explicit_no_overwrite_receipt() -> None:
    module = load_module()
    commands = json.loads(
        (REPO_ROOT / "manifests/documentation/public-commands-v1.json").read_text(
            encoding="utf-8"
        )
    )
    bootstrap = next(row for row in commands["commands"] if row["id"] == "bootstrap-python")
    bootstrap["argv"] = [
        "python",
        "tools/ember-restart-3b/python_environment.py",
        "install",
    ]
    with pytest.raises(module.DocsInfoError, match="PUBLIC_COMMAND_REQUIRED_RECEIPT_MISSING"):
        module.validate_commands_manifest(commands)


def test_readme_preserves_python_environment_authority_contract() -> None:
    environment = load_python_environment_module()
    manifest = environment.load_manifest(
        REPO_ROOT / "manifests/python-environment-v1.json"
    )
    environment.validate_prose_authority(REPO_ROOT, manifest)


def test_question_destination_refuses_unknown_canonical_id(tmp_path: Path) -> None:
    module = load_module()
    rows = metadata_fixture()["documents"]
    instrument = {
        "instrument_sha256": "frozen",
        "questions": [
            {"question_id": f"Q{i}", "question": f"Question {i}"} for i in range(1, 9)
        ],
    }
    routes = {
        "schema_version": "ember-reader-question-destinations-v2",
        "instrument_sha256": "frozen",
        "routes": [
            {
                "question_id": f"Q{i}",
                "question": f"Question {i}",
                "canonical_destination_id": "ember.entry.root",
            }
            for i in range(1, 9)
        ],
    }
    routes["routes"][7]["canonical_destination_id"] = "ember.missing"
    with pytest.raises(module.DocsInfoError, match="QUESTION_DESTINATION_UNKNOWN:Q8"):
        module.validate_question_destinations(tmp_path, routes, rows, instrument)


def test_frozen_reader_source_requires_canonical_disposition(tmp_path: Path) -> None:
    module = load_module()
    write(tmp_path / "README.md", "# Root\n")
    write(tmp_path / "docs/start.md", "# Start\n")
    write(tmp_path / "docs/canonical.md", "# Canonical\n")
    rows = metadata_fixture()["documents"]
    instrument = {
        "instrument_sha256": "frozen",
        "questions": [
            {
                "question_id": f"Q{i}",
                "question": f"Question {i}",
                "answer_key": {"public_sources": ["docs/retired.md"]},
            }
            for i in range(1, 9)
        ],
    }
    mapping = {
        "schema_version": "ember-reader-question-destinations-v2",
        "instrument_sha256": "frozen",
        "source_dispositions": [],
        "routes": [
            {
                "question_id": f"Q{i}",
                "question": f"Question {i}",
                "canonical_destination_id": "ember.entry.root",
            }
            for i in range(1, 9)
        ],
    }
    with pytest.raises(module.DocsInfoError, match="READER_PUBLIC_SOURCE_UNRESOLVED"):
        module.validate_question_destinations(tmp_path, mapping, rows, instrument)
    mapping["source_dispositions"] = [
        {
            "source": "docs/retired.md",
            "canonical_source": "docs/canonical.md",
            "disposition": "RETIRED_WITH_CANONICAL_DISPOSITION",
        }
    ]
    module.validate_question_destinations(tmp_path, mapping, rows, instrument)


def test_terminal_receipt_is_self_hashed_and_no_overwrite(tmp_path: Path) -> None:
    module = load_module()
    output = tmp_path / "receipt.json"
    finalized = module.write_final_receipt(output, {"result": "PASS", "count": 2})
    assert finalized["self_sha256"] == module.sha256_bytes(
        module.canonical_json({"result": "PASS", "count": 2})
    )
    with pytest.raises(module.DocsInfoError, match="OUTPUT_EXISTS_REFUSED"):
        module.write_final_receipt(output, {"result": "PASS", "count": 2})


def test_reader_study_requires_exactly_two_eligible_complete_passes() -> None:
    module = load_module()
    questions = [f"Q{i}" for i in range(1, 9)]
    study = {
        "schema_version": "ember-doc-reader-study-v2",
        "instrument_sha256": module.READER_INSTRUMENT_SHA256,
        "questions": questions,
        "readers": [
            {
                "reader_id": "reader-v2-a",
                "eligible": True,
                "authored_prose": False,
                "answers": {question: {"materially_correct": True} for question in questions},
                "unexplained_blocking_terms": [],
                "elapsed_seconds": 120,
            },
            {
                "reader_id": "reader-v2-b",
                "eligible": True,
                "authored_prose": False,
                "answers": {question: {"materially_correct": True} for question in questions},
                "unexplained_blocking_terms": [],
                "elapsed_seconds": 150,
            },
        ],
    }

    receipt = module.score_reader_study(study)
    assert receipt["result"] == "PASS"
    assert receipt["correct_answers"] == 16
    study["readers"][1]["answers"]["Q8"]["materially_correct"] = False
    with pytest.raises(module.DocsInfoError, match="READER_STUDY_INCOMPLETE"):
        module.score_reader_study(study)


def test_v2_reader_study_refuses_v1_schema_hash_and_reader_id_reuse(monkeypatch) -> None:
    module = load_module()
    questions = [f"Q{i}" for i in range(1, 9)]
    study = {
        "schema_version": "ember-doc-reader-study-v2",
        "instrument_sha256": module.READER_INSTRUMENT_SHA256,
        "questions": questions,
        "readers": [
            {
                "reader_id": "reader-v2-a",
                "eligible": True,
                "authored_prose": False,
                "answers": {question: {"materially_correct": True} for question in questions},
                "unexplained_blocking_terms": [],
                "elapsed_seconds": 1,
            },
            {
                "reader_id": "reader-v2-b",
                "eligible": True,
                "authored_prose": False,
                "answers": {question: {"materially_correct": True} for question in questions},
                "unexplained_blocking_terms": [],
                "elapsed_seconds": 1,
            },
        ],
    }
    for field, stale in (
        ("schema_version", "ember-doc-reader-study-v1"),
        ("instrument_sha256", "f6d851c10dcc7a19dcc6f5c8bdca72344933764aedb244fb92bfc2c48d5d288b"),
    ):
        candidate = json.loads(json.dumps(study))
        candidate[field] = stale
        with pytest.raises(module.DocsInfoError):
            module.score_reader_study(candidate)
    assert module.PREDECESSOR_READER_ID_SHA256S == {
        "c66bd342cb4e5e1432c2eb601d2f2ce784aff6da5b15f14e10e3c0e0f4facfd7",
        "58e1156648c53a55ce490437ee7a1cec562ad37b8cf3bf343faa2db81ab840d4",
    }
    predecessor_id = "predecessor-reader-a"
    monkeypatch.setattr(
        module,
        "PREDECESSOR_READER_ID_SHA256S",
        {module.sha256_bytes(predecessor_id.encode("utf-8"))},
    )
    study["readers"][0]["reader_id"] = predecessor_id
    with pytest.raises(module.DocsInfoError, match="READER_ID_REUSE_REFUSED"):
        module.score_reader_study(study)


def test_v2_reader_instrument_hashes_rederive_and_q3_is_atomic() -> None:
    module = load_module()
    instrument = json.loads(
        (REPO_ROOT / "manifests/documentation/reader-study-instrument-v2.json").read_bytes()
    )
    module.validate_reader_instrument(REPO_ROOT, instrument)
    questions = {row["question_id"]: row["question"] for row in instrument["questions"]}
    assert questions["Q3"] == (
        "State Ember's certified current model/training status, then state the full EMBER-02 "
        "target including approximate parameter range, modalities, reasoning, and structured-tool role."
    )


def test_checked_in_information_system_is_terminal_green() -> None:
    module = load_module()
    receipt = module.check_repository(REPO_ROOT, run_commands=False)
    assert receipt["result"] == "PASS"
    assert receipt["current_reference_reconciliation_count"] == 453
    assert receipt["metadata_document_count"] >= 12
    assert receipt["claim_count"] >= 8


def test_current_reference_reconciliation_replays_live_rows_and_refuses_drift(
    tmp_path: Path,
) -> None:
    module = load_module()
    reconciliation = json.loads(
        (REPO_ROOT / module.CURRENT_REFERENCE_RECONCILIATION_PATH).read_text(
            encoding="utf-8"
        )
    )
    frozen = json.loads(
        (REPO_ROOT / module.REFERENCE_DISPOSITIONS_PATH).read_text(encoding="utf-8")
    )
    assert len(
        module.validate_current_reference_reconciliation(
            REPO_ROOT, reconciliation, frozen
        )
    ) == 453

    drifted = json.loads(json.dumps(reconciliation))
    drifted["rows"].pop()
    with pytest.raises(
        module.DocsInfoError,
        match="CURRENT_REFERENCE_RECONCILIATION_CURRENT_ROWS_STALE",
    ):
        module.validate_current_reference_reconciliation(REPO_ROOT, drifted, frozen)

    write(tmp_path / "domains/data/README.md", "# canonical\n")
    write(tmp_path / "README.md", "# root\n")
    document = tmp_path / "docs/example.md"
    write(document, "See domains/data/README.md.\n")
    filing = module.current_unresolved_reference_rows(
        tmp_path, module.FILING_REFERENCE_RE
    )
    corrected = module.current_unresolved_reference_rows(
        tmp_path, module.CORRECTED_REFERENCE_RE
    )
    assert [row["target"] for row in filing] == ["data/README.md"]
    assert corrected == []


def test_reference_dispositions_refuse_an_absent_document() -> None:
    module = load_module()
    dispositions = json.loads(
        (REPO_ROOT / module.REFERENCE_DISPOSITIONS_PATH).read_text(encoding="utf-8")
    )
    dispositions["rows"][0]["document"] = "docs/planted-absent-document.md"
    dispositions["row_set_sha256"] = module.sha256_bytes(
        module.canonical_json(dispositions["rows"])
    )
    with pytest.raises(
        module.DocsInfoError,
        match="REFERENCE_DISPOSITION_DOCUMENT_MISSING",
    ):
        module.validate_reference_dispositions(REPO_ROOT, dispositions)


def test_reference_reconciliation_generator_matches_checked_in_bytes() -> None:
    module = load_module()
    dispositions = json.loads(
        (REPO_ROOT / module.REFERENCE_DISPOSITIONS_PATH).read_text(encoding="utf-8")
    )
    checked = json.loads(
        (REPO_ROOT / module.CURRENT_REFERENCE_RECONCILIATION_PATH).read_text(
            encoding="utf-8"
        )
    )
    assert module.build_current_reference_reconciliation(
        REPO_ROOT, dispositions, checked
    ) == checked
