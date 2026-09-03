# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
import json
from pathlib import Path


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "ember_totality"
    / "writers_custody_two_run_test.py"
)
SPEC = importlib.util.spec_from_file_location("writers_custody_two_run", MODULE_PATH)
assert SPEC and SPEC.loader
writers = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(writers)


def _install_root(monkeypatch, tmp_path: Path) -> Path:
    (tmp_path / "receipts").mkdir()
    (
        tmp_path
        / "src"
        / "ember"
        / "governance"
        / "scripts"
        / "ember_totality"
        / "receipts-totality"
    ).mkdir(parents=True)
    monkeypatch.setattr(writers, "REPO_ROOT", tmp_path)
    return tmp_path


def _write_designated_receipt(root: Path, family: str, spend: bool) -> None:
    directory = (
        root
        / "src"
        / "ember"
        / "governance"
        / "scripts"
        / "ember_totality"
        / f"receipts-{family}"
    )
    directory.mkdir(parents=True, exist_ok=True)
    payload = {"verdict": "PASS"}
    if spend:
        payload.update({"api_spend_usd": 0.0, "paid_api_surface_used": False})
    (directory / f"{family}-fixture.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_nonzero_writer_exit_is_a_failure(monkeypatch, tmp_path):
    root = _install_root(monkeypatch, tmp_path)

    def failed_milestone(_root, script_path, args=None):
        del args
        family = "milestone" if "milestone" in script_path else "publication"
        _write_designated_receipt(root, family, spend=True)
        return ("expected failure", 1 if family == "milestone" else 0)

    monkeypatch.setattr(writers, "_run_writer_step", failed_milestone)

    assert writers.test_writers_custody_two_run() is False


def test_first_run_canonical_receipt_leak_is_a_failure(monkeypatch, tmp_path):
    root = _install_root(monkeypatch, tmp_path)

    def leaking_writer(_root, script_path, args=None):
        del args
        (root / "receipts" / "leak.json").write_text("{}", encoding="utf-8")
        family = "milestone" if "milestone" in script_path else "publication"
        _write_designated_receipt(root, family, spend=True)
        return ("ok", 0)

    monkeypatch.setattr(writers, "_run_writer_step", leaking_writer)

    assert writers.test_writers_custody_two_run() is False


def test_missing_spend_declarations_are_a_failure(monkeypatch, tmp_path):
    root = _install_root(monkeypatch, tmp_path)

    def undeclared_writer(_root, script_path, args=None):
        del args
        family = "milestone" if "milestone" in script_path else "publication"
        _write_designated_receipt(root, family, spend=False)
        return ("ok", 0)

    monkeypatch.setattr(writers, "_run_writer_step", undeclared_writer)

    assert writers.test_writers_custody_two_run() is False


def test_two_clean_runs_with_declared_designated_receipts_pass(monkeypatch, tmp_path):
    root = _install_root(monkeypatch, tmp_path)

    def clean_writer(_root, script_path, args=None):
        del args
        family = "milestone" if "milestone" in script_path else "publication"
        _write_designated_receipt(root, family, spend=True)
        return ("ok", 1 if family == "publication" else 0)

    monkeypatch.setattr(writers, "_run_writer_step", clean_writer)

    assert writers.test_writers_custody_two_run() is True
