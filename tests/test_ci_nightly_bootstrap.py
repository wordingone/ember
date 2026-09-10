# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Keep every full Python CI surface importable from the checked-out package."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
EDITABLE_INSTALL = "python -m pip install --editable ."
PYTEST_INVOCATION = "python -B -m pytest -q --import-mode=importlib"
# One step per suite, in execution order. The step id is what the aggregate reads, so a
# renamed step silently drops that suite from the failure aggregation unless both move.
SUITE_STEPS = (
    ("suite-scripts-tests", "scripts/tests"),
    ("suite-governance-tests", "src/ember/governance/scripts/tests"),
    ("suite-tests", "tests"),
)


def test_nightly_installs_checkout_once_before_collection_and_suites() -> None:
    nightly = (WORKFLOWS / "ci-nightly.yml").read_text(encoding="utf-8", errors="strict")
    dependency = 'python -m pip install "tokenizers==0.22.2" "huggingface_hub==1.22.0"'
    collection = "python -B src/ember/governance/scripts/check_scripts_tests_collection.py --minimum 380"

    assert nightly.count(EDITABLE_INSTALL) == 1
    assert nightly.index(dependency) < nightly.index(EDITABLE_INSTALL)
    assert nightly.index(EDITABLE_INSTALL) < nightly.index(collection) < nightly.index(PYTEST_INVOCATION)


def test_nightly_matches_main_and_pr_checkout_bootstrap() -> None:
    for workflow_name in ("ci-main.yml", "ci-pr.yml", "ci-nightly.yml"):
        workflow = (WORKFLOWS / workflow_name).read_text(encoding="utf-8", errors="strict")
        assert workflow.count(EDITABLE_INSTALL) == 1, workflow_name


def _extended_audit():
    import yaml

    nightly = yaml.safe_load((WORKFLOWS / "ci-nightly.yml").read_text(encoding="utf-8"))
    return nightly["jobs"]["extended-audit"]


def _suite_steps():
    steps = {step.get("id"): step for step in _extended_audit()["steps"]}
    return [steps[step_id] for step_id, _ in SUITE_STEPS]


def _nightly_suite_commands():
    import shlex

    return [shlex.split(step["run"].strip()) for step in _suite_steps()]


def test_nightly_executes_all_complete_suites() -> None:
    commands = _nightly_suite_commands()
    assert [command[-1] for command in commands] == [suite for _, suite in SUITE_STEPS]
    for command in commands:
        assert command[: len(PYTEST_INVOCATION.split())] == PYTEST_INVOCATION.split()
        # Near-misses are what become the next stall, so they have to be visible before then.
        assert "--durations=25" in command


def test_nightly_gives_each_suite_a_bound_it_can_report_inside() -> None:
    """A stall must name a test, not cancel the job.

    Before this shape the three suites shared one step and one 90-minute job limit, so a suite
    that stopped advancing took the whole job's cancellation with it: no terminal counts for any
    suite, and nothing naming the test that stopped (#2211).
    """
    audit = _extended_audit()
    budget = 0
    for (step_id, suite), step in zip(SUITE_STEPS, _suite_steps()):
        assert step["continue-on-error"] is True, step_id
        limit_minutes = step["timeout-minutes"]
        budget += limit_minutes
        option = next(part for part in step["run"].split()
                      if part.startswith("faulthandler_timeout="))
        # The dump has to fire before the step is cancelled, or the hang stays anonymous.
        assert int(option.split("=", 1)[1]) < limit_minutes * 60, suite
    # ...and every step's own bound has to fit inside the job's, or the last suite is cancelled
    # by the job limit exactly as it was before.
    assert budget < audit["timeout-minutes"]


def test_nightly_aggregates_every_suite_outcome() -> None:
    steps = _extended_audit()["steps"]
    order = [step.get("id") for step in steps]
    aggregate = steps[order.index("aggregate-suites")]

    assert aggregate["if"] == "always()"
    # The aggregate is the job's verdict: it may not excuse itself from failing the run.
    assert "continue-on-error" not in aggregate
    for step_id, _ in SUITE_STEPS:
        assert f"steps.{step_id}.outcome" in aggregate["run"], step_id
        # Outcomes are unset until their step has run.
        assert order.index(step_id) < order.index("aggregate-suites"), step_id
    assert "exit 1" in aggregate["run"]


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
    command = _nightly_suite_commands()[-1]
    assert command[-1] == "tests"
    collected = _collect_fixture_modules(tmp_path, monkeypatch,
                                         [*command[4:-1], str(tmp_path)])
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
