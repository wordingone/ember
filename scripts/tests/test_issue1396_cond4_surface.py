# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(os.environ.get("EMBER_ISSUE1396_REPO_ROOT", Path(__file__).resolve().parents[2]))
SOURCE_ROOT = Path(os.environ.get("EMBER_ISSUE1396_SOURCE_ROOT", REPO_ROOT))
sys.path.insert(0, str(SOURCE_ROOT / "scripts"))
from ember_01_identity.cond4_battery_surface import (  # noqa: E402
    COMPLETION_VERIFIER_SYMBOLS,
    Cond4SurfaceError,
    EXECUTION_SCHEMA,
    SURFACE_SCHEMA,
    behavior_surface_sha256,
    completion_verifier_binding_valid,
    completion_verifier_surface_sha256,
    cond4_battery_output_sha256,
    cond4_receipt_transition_valid,
)


VERIFIER = REPO_ROOT / "scripts" / "verify_ember01_completion.py"
RECEIPT = (
    Path(os.environ.get("EMBER_ISSUE1396_RECEIPT_ROOT", REPO_ROOT))
    / "receipts"
    / "ember-01-completion"
    / "cond4-tamper-battery-bf20f050-v1.json"
)
WORKFLOW = (
    Path(os.environ.get("EMBER_ISSUE1396_WORKFLOW_ROOT", REPO_ROOT))
    / ".github"
    / "workflows"
    / "ci-pr.yml"
)


def test_unrelated_verifier_edit_preserves_cond4_surface() -> None:
    source = VERIFIER.read_bytes()
    binding = {
        "sha256": hashlib.sha256(source).hexdigest(),
        "battery_surface": {
            "schema": SURFACE_SCHEMA,
            "symbols": list(COMPLETION_VERIFIER_SYMBOLS),
            "sha256": behavior_surface_sha256(source, COMPLETION_VERIFIER_SYMBOLS),
        },
    }
    unrelated = source + b"\n\ndef unrelated_future_verifier_leg():\n    return 'outside-cond4'\n"
    assert hashlib.sha256(unrelated).hexdigest() != binding["sha256"]
    assert completion_verifier_binding_valid(unrelated, binding) is True


def test_edit_inside_battery_surface_invalidates() -> None:
    source = VERIFIER.read_bytes()
    needle = b'"axis_count": 8,'
    assert source.count(needle) >= 1
    tampered = source.replace(needle, b'"axis_count": 9,', 1)
    binding = {
        "sha256": hashlib.sha256(source).hexdigest(),
        "battery_surface": {
            "schema": SURFACE_SCHEMA,
            "symbols": list(COMPLETION_VERIFIER_SYMBOLS),
            "sha256": behavior_surface_sha256(source, COMPLETION_VERIFIER_SYMBOLS),
        },
    }
    assert completion_verifier_binding_valid(tampered, binding) is False


def test_missing_bound_definition_fails_closed() -> None:
    with pytest.raises(Cond4SurfaceError, match="missing cond4 behavior definitions"):
        behavior_surface_sha256(b"def other():\n    pass\n", COMPLETION_VERIFIER_SYMBOLS)


def test_referenced_import_binding_change_invalidates_surface() -> None:
    source = VERIFIER.read_bytes()
    needle = b"import copy\n"
    assert source.count(needle) == 1
    tampered = source.replace(needle, b"import copy as unbound_copy\n", 1)
    binding = {
        "sha256": hashlib.sha256(source).hexdigest(),
        "battery_surface": {
            "schema": SURFACE_SCHEMA,
            "symbols": list(COMPLETION_VERIFIER_SYMBOLS),
            "sha256": behavior_surface_sha256(source, COMPLETION_VERIFIER_SYMBOLS),
        },
    }
    assert completion_verifier_binding_valid(tampered, binding) is False


def test_committed_receipt_binds_current_cond4_surface() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    surface = receipt["implementation"]["completion_verifier"]["battery_surface"]
    assert surface["schema"] == SURFACE_SCHEMA
    assert tuple(surface["symbols"]) == COMPLETION_VERIFIER_SYMBOLS
    assert surface["sha256"] == completion_verifier_surface_sha256(VERIFIER)


@pytest.mark.parametrize(
    ("base", "changed"),
    [
        ("if FLAG:\n    ROOT = 1\n", "if not FLAG:\n    ROOT = 1\n"),
        ("ROOT, OTHER = (1, 2)\n", "ROOT, OTHER = (2, 1)\n"),
        ("ROOT = 1\nROOT += 2\n", "ROOT = 1\nROOT += 3\n"),
        ("ROOT = 1\ndel ROOT\n", "ROOT = 1\nif FLAG:\n    del ROOT\n"),
        (
            "for ROOT in range(1):\n    pass\n",
            "for ROOT in range(2):\n    pass\n",
        ),
        (
            "with context(1) as ROOT:\n    pass\n",
            "with context(2) as ROOT:\n    pass\n",
        ),
        (
            "try:\n    pass\nexcept FirstError as ROOT:\n    pass\n",
            "try:\n    pass\nexcept SecondError as ROOT:\n    pass\n",
        ),
        (
            "match payload:\n    case {'first': ROOT}:\n        pass\n",
            "match payload:\n    case {'second': ROOT}:\n        pass\n",
        ),
    ],
)
def test_compound_or_mutating_bindings_are_in_surface(base: str, changed: str) -> None:
    assert behavior_surface_sha256(base.encode(), ("ROOT",)) != behavior_surface_sha256(
        changed.encode(), ("ROOT",)
    )


def _receipt(source: bytes, *, executed_at: str, result: str = "PASS") -> dict:
    surface_sha = behavior_surface_sha256(source, COMPLETION_VERIFIER_SYMBOLS)
    return {
        "implementation": {
            "completion_verifier": {
                "sha256": hashlib.sha256(source).hexdigest(),
                "battery_surface": {
                    "schema": SURFACE_SCHEMA,
                    "symbols": list(COMPLETION_VERIFIER_SYMBOLS),
                    "sha256": surface_sha,
                },
            }
        },
        "verification": {
            "cond4_battery_execution": {
                "schema": EXECUTION_SCHEMA,
                "completion_verifier_surface_sha256": surface_sha,
                "executed_at": executed_at,
                "command": ["python", "-B", "-m", "pytest", "-q", "cond4"],
                "result": result,
            }
        },
    }


def test_surface_change_requires_new_same_pr_execution_receipt() -> None:
    base = VERIFIER.read_bytes()
    needle = b'"axis_count": 8,'
    assert needle in base
    head = base.replace(needle, b'"axis_count": 9,', 1)
    base_receipt = _receipt(base, executed_at="2026-08-03T21:41:38Z")

    stale = _receipt(head, executed_at="2026-08-03T21:41:38Z")
    stale["verification"]["cond4_battery_execution"] = base_receipt["verification"][
        "cond4_battery_execution"
    ]
    assert cond4_receipt_transition_valid(base, head, base_receipt, stale) is False

    repinned_without_execution = _receipt(head, executed_at="2026-08-03T21:41:38Z")
    assert (
        cond4_receipt_transition_valid(
            base, head, base_receipt, repinned_without_execution
        )
        is False
    )

    self_attested = _receipt(head, executed_at="2026-08-10T12:00:00Z")
    self_attested["verification"]["cond4_battery_execution"][
        "output_sha256"
    ] = "a" * 64
    assert cond4_receipt_transition_valid(
        base, head, base_receipt, self_attested
    ) is False
    assert cond4_receipt_transition_valid(
        base,
        head,
        base_receipt,
        self_attested,
        observed_output_sha256="a" * 64,
    ) is True


def test_battery_output_digest_binds_stable_axis_results() -> None:
    battery = {
        "axis_count": 1,
        "all_rejected": True,
        "failures": [],
        "axes": {
            "checkpoint_bytes": {
                "rejected": True,
                "finding": "parameter_identity_mismatch",
                "detail": "temporary path A",
            }
        },
    }
    same_result = json.loads(json.dumps(battery))
    same_result["axes"]["checkpoint_bytes"]["detail"] = "temporary path B"
    changed_result = json.loads(json.dumps(battery))
    changed_result["axes"]["checkpoint_bytes"]["rejected"] = False

    digest = cond4_battery_output_sha256(battery)
    assert len(digest) == 64
    assert digest == cond4_battery_output_sha256(same_result)
    assert digest != cond4_battery_output_sha256(changed_result)


def test_unrelated_change_does_not_force_battery_reexecution() -> None:
    base = VERIFIER.read_bytes()
    head = base + b"\n\ndef unrelated_future_verifier_leg():\n    return 'outside-cond4'\n"
    base_receipt = _receipt(base, executed_at="2026-08-03T21:41:38Z")
    assert cond4_receipt_transition_valid(base, head, base_receipt, base_receipt) is True


def test_ci_enforces_transition_against_exact_pull_request_base() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "fetch-depth: 0" in workflow
    assert '"jsonschema==4.26.0"' in workflow
    assert '"cryptography==49.0.0"' in workflow
    assert "EMBER_COND4_BASE_SHA: ${{ github.event.pull_request.base.sha }}" in workflow
    assert "scripts/tests/test_issue1396_cond4_surface.py" in workflow
    assert 'scripts/tests/test_verify_ember01_completion.py -k "cond4"' in workflow
