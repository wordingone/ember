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
    collection = "python -B scripts/check_scripts_tests_collection.py --minimum 380"
    suites = "python -B -m pytest -q scripts/tests"

    assert nightly.count(EDITABLE_INSTALL) == 1
    assert nightly.index(dependency) < nightly.index(EDITABLE_INSTALL)
    assert nightly.index(EDITABLE_INSTALL) < nightly.index(collection) < nightly.index(suites)


def test_nightly_matches_main_and_pr_checkout_bootstrap() -> None:
    for workflow_name in ("ci-main.yml", "ci-pr.yml", "ci-nightly.yml"):
        workflow = (WORKFLOWS / workflow_name).read_text(encoding="utf-8", errors="strict")
        assert workflow.count(EDITABLE_INSTALL) == 1, workflow_name

