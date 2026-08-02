# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""The committed EMBER-02 admission registry must load through the contract's own loader.

Loading it through `_load_trusted_verifiers` rather than a local re-implementation is
the point: the registry is only correct if the code that gates admission accepts it.
"""

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT = REPO_ROOT / "scripts" / "ember_restart" / "contract.py"
REGISTRY = REPO_ROOT / "manifests" / "ember-02-admission" / "trusted-verifiers-v1.json"

CONSUMED_EVIDENCE_CLASSES = {
    "parameter_realization",
    "tokenizer_freeze",
    "training_data",
    "sufficient_pretraining",
    "evaluation",
}
CAPABILITY_CRITERIA = {
    f"ember-3b-{capability}-capability-v1"
    for capability in ("text", "image", "audio", "reasoning", "tool")
}


def _load_contract():
    spec = importlib.util.spec_from_file_location("_ember_restart_contract", CONTRACT)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(CONTRACT.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(CONTRACT.parent))
    return module


@pytest.fixture(scope="module")
def contract():
    return _load_contract()


@pytest.fixture(scope="module")
def registry(contract):
    errors: list[str] = []
    trusted = contract._load_trusted_verifiers(REGISTRY, errors)
    assert errors == [], errors
    return trusted


def test_registry_loads_without_errors(registry):
    assert registry, "registry resolved to zero trusted verifiers"


def test_every_consumed_evidence_class_is_covered(registry):
    covered = {
        evidence_class
        for entry in registry.values()
        for evidence_class in entry["evidence_classes"]
    }
    assert CONSUMED_EVIDENCE_CLASSES <= covered


def test_sufficiency_and_capability_criteria_are_trusted(registry):
    sufficiency = [
        entry for entry in registry.values() if "sufficient_pretraining" in entry["evidence_classes"]
    ]
    assert len(sufficiency) == 1
    assert "ember-sufficient-pretraining-v2" in sufficiency[0]["criterion_ids"]

    evaluation = [entry for entry in registry.values() if "evaluation" in entry["evidence_classes"]]
    assert len(evaluation) == 1
    assert CAPABILITY_CRITERIA <= set(evaluation[0]["criterion_ids"])


def test_recorded_hashes_match_the_verifier_bytes_on_disk():
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    for entry in payload["verifiers"]:
        path = REGISTRY.parent / entry["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], entry["path"]


def test_verifiers_are_self_contained_and_runnable():
    """Each verifier must import under -I isolation, which forbids repo-relative imports."""
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    for entry in payload["verifiers"]:
        path = REGISTRY.parent / entry["path"]
        completed = subprocess.run(
            [sys.executable, "-I", str(path), "--help"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert completed.returncode == 0, (entry["path"], completed.stderr)


def test_registry_clears_the_missing_registry_error():
    """A checkpoint claim validated with this registry must not report a registry fault."""
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            str(CONTRACT),
            "validate",
            str(REPO_ROOT / "configs" / "ember-restart-3b.json"),
            "--trusted-verifier-registry",
            str(REGISTRY),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    errors = json.loads(completed.stdout)["errors"]
    assert not [error for error in errors if error.startswith("trusted_verifier_registry")], errors
