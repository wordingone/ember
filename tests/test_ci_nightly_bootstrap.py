# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Keep every full Python CI surface importable from the checked-out package."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
EDITABLE_INSTALL = "python -m pip install --editable ."


def test_nightly_installs_checkout_once_before_collection_and_suites() -> None:
    nightly = (WORKFLOWS / "ci-nightly.yml").read_text(encoding="utf-8", errors="strict")
    dependency = 'python -m pip install "tokenizers==0.22.2" "huggingface_hub==1.22.0"'
    collection = "python -B src/ember/governance/scripts/check_scripts_tests_collection.py --minimum 380"
    suites = "python -B -m pytest -q --import-mode=importlib scripts/tests"

    assert nightly.count(EDITABLE_INSTALL) == 1
    assert nightly.index(dependency) < nightly.index(EDITABLE_INSTALL)
    assert nightly.index(EDITABLE_INSTALL) < nightly.index(collection) < nightly.index(suites)


def test_nightly_matches_main_and_pr_checkout_bootstrap() -> None:
    for workflow_name in ("ci-main.yml", "ci-pr.yml", "ci-nightly.yml"):
        workflow = (WORKFLOWS / workflow_name).read_text(encoding="utf-8", errors="strict")
        assert workflow.count(EDITABLE_INSTALL) == 1, workflow_name


def _nightly_suite_commands():
    import shlex
    import yaml

    nightly = yaml.safe_load((WORKFLOWS / "ci-nightly.yml").read_text(encoding="utf-8"))
    steps = nightly["jobs"]["extended-audit"]["steps"]
    suites = [step for step in steps if step.get("name") == "Extended CPU-safe suites"]
    assert len(suites) == 1
    return [shlex.split(line) for line in suites[0]["run"].splitlines() if line.strip()]


def test_nightly_executes_all_complete_suites_and_aggregates_failures() -> None:
    expected = [["status=0"]]
    for suite in ("scripts/tests", "src/ember/governance/scripts/tests", "tests"):
        expected.append(["python", "-B", "-m", "pytest", "-q", "--import-mode=importlib",
                         suite, "||", "status=1"])
    expected.append(["exit", "${status}"])
    assert _nightly_suite_commands() == expected


def _collect_fixture_modules(tmp_path, monkeypatch, arguments):
    import sys
    import pytest

    class CollectedModules:
        def __init__(self):
            self.observed = []
            self.names = []

        def pytest_collection_modifyitems(self, items):
            for item in items:
                self.observed.append((Path(item.module.__file__).resolve(),
                                      item.module.COLLECTION_IDENTITY))
                self.names.append(item.module.__name__)

    collected = CollectedModules()
    monkeypatch.setenv("PYTEST_ADDOPTS", "")
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    monkeypatch.setattr(sys, "path", list(sys.path))
    try:
        result = pytest.main([
            "-c", str(ROOT / "pyproject.toml"), "--collect-only", "-q",
            "-p", "no:cacheprovider", "--rootdir", str(tmp_path),
            "--confcutdir", str(tmp_path), *arguments,
        ], plugins=[collected])
    finally:
        for name, module in list(sys.modules.items()):
            source = getattr(module, "__file__", None)
            if source and Path(source).is_relative_to(tmp_path):
                sys.modules.pop(name, None)
    assert result == pytest.ExitCode.OK
    return collected


def test_nightly_mode_collects_distinct_same_basename_modules(tmp_path, monkeypatch) -> None:
    expected = set()
    for directory, marker in (("first-domain", "first"), ("second-domain", "second")):
        module = tmp_path / directory / "test_nightly_collection_identity.py"
        module.parent.mkdir()
        module.write_text(
            f"COLLECTION_IDENTITY = {marker!r}\n"
            "def test_identity():\n"
            f"    assert COLLECTION_IDENTITY == {marker!r}\n",
            encoding="utf-8",
        )
        expected.add((module.resolve(), marker))

    # Consume the actual nightly test command's options with only its suite replaced.
    command = _nightly_suite_commands()[-2]
    assert command[-3:] == ["tests", "||", "status=1"]
    collected = _collect_fixture_modules(tmp_path, monkeypatch,
                                         [*command[4:-3], str(tmp_path)])
    assert len(collected.observed) == 2
    assert set(collected.observed) == expected
    assert len(set(collected.names)) == 2


def test_repository_focused_collection_preserves_sibling_imports(tmp_path, monkeypatch) -> None:
    helper = tmp_path / "nightly_focused_helper.py"
    helper.write_text("COLLECTION_IDENTITY = 'focused'\n", encoding="utf-8")
    module = tmp_path / "test_nightly_focused_identity.py"
    module.write_text(
        "from nightly_focused_helper import COLLECTION_IDENTITY\n"
        "def test_identity():\n"
        "    assert COLLECTION_IDENTITY == 'focused'\n", encoding="utf-8",
    )
    collected = _collect_fixture_modules(tmp_path, monkeypatch, [str(module)])
    assert collected.observed == [(module.resolve(), "focused")]
