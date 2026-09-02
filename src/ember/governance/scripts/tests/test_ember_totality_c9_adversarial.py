#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression coverage ported from retired PR #148's C9 shell probe.

The historical probe rewrote production source and executed eight temporary
copies.  These tests exercise the current ``scan`` boundary directly, keep the
fixtures hermetic, and preserve the distinction between a raw C9 finding and
the epoch-aware status rendered by ``main``.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
TARGET = ROOT / "scripts" / "ember_totality" / "test_c9.py"


def _load_target():
    spec = importlib.util.spec_from_file_location("ember_totality_test_c9", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_receipt(root: Path, payload: object, name: str = "r.json") -> None:
    receipt = root / "receipts" / "case" / name
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _metric(
    *,
    verdict: str,
    code: int,
    docs: int,
    include_lifecycle: bool = True,
) -> dict[str, object]:
    metric: dict[str, object] = {
        "verdict": verdict,
        "line_totals": {"code": code, "docs": docs},
        "code_vs_docs": {
            "code_fraction": code / (code + docs) if code + docs else 0.0,
            "docs_fraction": docs / (code + docs) if code + docs else 0.0,
        },
    }
    if include_lifecycle:
        metric["doc_lifecycle_totals"] = {
            "before_project": 0,
            "during_project": docs // 2,
            "after_project": docs - (docs // 2),
        }
    return metric


@pytest.mark.parametrize(
    ("case", "payload", "expected"),
    [
        (
            "docs-only",
            {
                "receipt_type": "code_vs_docs_metric",
                "metric": _metric(
                    verdict="docs_only_no_executable_delta",
                    code=0,
                    docs=500,
                ),
            },
            "RED",
        ),
        (
            "scaffold-marker",
            {
                "receipt_type": "code_vs_docs_metric",
                "note": "invalid_scaffold_before_core",
                "metric": _metric(
                    verdict="mixed_code_and_docs",
                    code=900,
                    docs=100,
                ),
            },
            "RED",
        ),
        ("empty-object", {}, "UNEVALUABLE_ABSENT"),
        (
            "hardcoded-green-note",
            {
                "receipt_type": "note",
                "text": "GREEN C9 CHK satisfied everything passes",
            },
            "UNEVALUABLE_ABSENT",
        ),
        (
            "incomplete-metric",
            {
                "receipt_type": "code_vs_docs_metric",
                "metric": _metric(
                    verdict="code_only_executable_delta",
                    code=900,
                    docs=10,
                    include_lifecycle=False,
                ),
            },
            "RED",
        ),
        (
            "valid-code-only",
            {
                "receipt_type": "code_vs_docs_metric",
                "metric": _metric(
                    verdict="code_only_executable_delta",
                    code=900,
                    docs=10,
                ),
            },
            "GREEN",
        ),
        (
            "zero-code",
            {
                "receipt_type": "code_vs_docs_metric",
                "metric": _metric(
                    verdict="mixed_code_and_docs",
                    code=0,
                    docs=500,
                ),
            },
            "RED",
        ),
    ],
)
def test_historical_adversarial_cases(
    tmp_path: Path,
    case: str,
    payload: object,
    expected: str,
) -> None:
    target = _load_target()
    _write_receipt(tmp_path, payload, name=f"{case}.json")

    status, _reason = target.scan(str(tmp_path), None)

    assert status == expected


def test_empty_scannable_receipts_directory_is_evidence_absent(
    tmp_path: Path,
) -> None:
    target = _load_target()
    (tmp_path / "receipts").mkdir()

    status, reason = target.scan(str(tmp_path), None)

    assert status == "UNEVALUABLE_ABSENT"
    assert "window was scanned successfully and is empty" in reason
