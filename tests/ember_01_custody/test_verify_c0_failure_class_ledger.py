# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_ROOT = REPO_ROOT / "scripts" / "ember_01_custody"
sys.path.insert(0, str(SCRIPT_ROOT))

from verify_c0_failure_class_ledger import (  # noqa: E402
    LAW_LISTED_CLASS_IDS,
    LEDGER_SCHEMA,
    verify,
)

LIVE_LEDGER_PATH = (
    REPO_ROOT / "manifests" / "ember-01-custody" / "c0-failure-class-ledger.json"
)


def _closed_guarded_row(class_id: str) -> dict:
    """A row that resolves against real bytes in this checkout, for building a
    synthetic all-closed ledger in tests."""
    return {
        "class_id": class_id,
        "title": f"{class_id} title",
        "birth_relevance": f"{class_id} birth relevance",
        "state": "CLOSED_GUARDED",
        "guard_ref": "scripts/ember_01_custody/census.py:build_root_census",
        "guard_kind": "test",
        "evidence": "synthetic test row",
    }


def _blocking_row(class_id: str, reason: str = "not yet guarded") -> dict:
    return {
        "class_id": class_id,
        "title": f"{class_id} title",
        "birth_relevance": f"{class_id} birth relevance",
        "state": "BLOCKING",
        "blocking_reason": reason,
    }


def _complete_all_closed_ledger() -> dict:
    """Every law-listed class present and CLOSED_GUARDED with a resolvable guard_ref.
    This is the positive fixture: verify() must return verdict CLOSED, ok True."""
    return {
        "authority": {
            "goal_id": "EMBER-01",
            "workstream_id": "EMBER-01D",
            "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
        },
        "schema": LEDGER_SCHEMA,
        "classes": [_closed_guarded_row(cid) for cid in sorted(LAW_LISTED_CLASS_IDS)],
    }


# ---------------------------------------------------------------------------
# (a) a law-listed class omitted -> RED (completeness cross-check)
# ---------------------------------------------------------------------------


def test_omitted_law_listed_class_is_red_before_fix(tmp_path: Path) -> None:
    ledger = _complete_all_closed_ledger()
    omitted = ledger["classes"].pop()  # drop one law-listed class
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    verdict = verify(ledger_path, REPO_ROOT)

    assert verdict["ok"] is False
    assert verdict["verdict"] == "RED"
    assert any("completeness cross-check FAILED" in e for e in verdict["errors"])
    assert omitted["class_id"] in " ".join(verdict["errors"])


def test_omitted_law_listed_class_fixed_by_adding_row_back(tmp_path: Path) -> None:
    ledger = _complete_all_closed_ledger()
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    verdict = verify(ledger_path, REPO_ROOT)

    assert verdict["ok"] is True
    assert verdict["verdict"] == "CLOSED"


# ---------------------------------------------------------------------------
# (b) a CLOSED_GUARDED row with a dangling guard_ref -> RED
# ---------------------------------------------------------------------------


def test_dangling_guard_ref_is_red_before_fix(tmp_path: Path) -> None:
    ledger = _complete_all_closed_ledger()
    ledger["classes"][0]["guard_ref"] = "scripts/ember_01_custody/does_not_exist.py:nope"
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    verdict = verify(ledger_path, REPO_ROOT)

    assert verdict["ok"] is False
    assert verdict["verdict"] == "RED"
    assert any("dangling guard_ref" in e for e in verdict["errors"])


def test_dangling_guard_ref_fixed_by_pointing_at_real_symbol(tmp_path: Path) -> None:
    ledger = _complete_all_closed_ledger()
    ledger["classes"][0]["guard_ref"] = "scripts/ember_01_custody/census.py:build_root_census"
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    verdict = verify(ledger_path, REPO_ROOT)

    assert verdict["ok"] is True
    assert verdict["verdict"] == "CLOSED"


def test_dangling_guard_ref_missing_symbol_in_real_file_is_red(tmp_path: Path) -> None:
    ledger = _complete_all_closed_ledger()
    ledger["classes"][0]["guard_ref"] = "scripts/ember_01_custody/census.py:this_symbol_does_not_exist"
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    verdict = verify(ledger_path, REPO_ROOT)

    assert verdict["ok"] is False
    assert verdict["verdict"] == "RED"
    assert any("guard_ref symbol not found" in e for e in verdict["errors"])


# ---------------------------------------------------------------------------
# (c) a malformed/truncated ledger line -> terminal RED (not skipped)
# ---------------------------------------------------------------------------


def test_malformed_json_is_terminal_red_not_skipped(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text('{"schema": "' + LEDGER_SCHEMA + '", "classes": [', encoding="utf-8")

    verdict = verify(ledger_path, REPO_ROOT)

    assert verdict["ok"] is False
    assert verdict["verdict"] == "RED"
    assert len(verdict["errors"]) >= 1
    assert "malformed JSON" in verdict["errors"][0]


def test_missing_ledger_file_is_terminal_red(tmp_path: Path) -> None:
    verdict = verify(tmp_path / "does-not-exist.json", REPO_ROOT)

    assert verdict["ok"] is False
    assert verdict["verdict"] == "RED"
    assert any("ledger file missing" in e for e in verdict["errors"])


def test_empty_ledger_file_is_terminal_red(tmp_path: Path) -> None:
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text("", encoding="utf-8")

    verdict = verify(ledger_path, REPO_ROOT)

    assert verdict["ok"] is False
    assert verdict["verdict"] == "RED"


def test_malformed_row_missing_required_key_is_red(tmp_path: Path) -> None:
    ledger = _complete_all_closed_ledger()
    del ledger["classes"][0]["title"]
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    verdict = verify(ledger_path, REPO_ROOT)

    assert verdict["ok"] is False
    assert verdict["verdict"] == "RED"
    assert any("missing required keys" in e for e in verdict["errors"])


def test_unknown_key_rejected_closed_schema(tmp_path: Path) -> None:
    ledger = _complete_all_closed_ledger()
    ledger["classes"][0]["unexpected_field"] = "not allowed"
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    verdict = verify(ledger_path, REPO_ROOT)

    assert verdict["ok"] is False
    assert verdict["verdict"] == "RED"
    assert any("unknown keys" in e for e in verdict["errors"])


# ---------------------------------------------------------------------------
# (d) a BLOCKING row -> verdict BLOCKED, never CLOSED
# ---------------------------------------------------------------------------


def test_blocking_row_yields_blocked_not_closed(tmp_path: Path) -> None:
    ledger = _complete_all_closed_ledger()
    a_class = ledger["classes"][0]["class_id"]
    ledger["classes"][0] = _blocking_row(a_class, "still open, guard not landed")
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    verdict = verify(ledger_path, REPO_ROOT)

    assert verdict["verdict"] == "BLOCKED"
    assert verdict["ok"] is False
    assert a_class in verdict["blocking"]
    assert not verdict["errors"]  # BLOCKED is well-formed, not malformed


def test_blocking_row_missing_blocking_reason_is_red(tmp_path: Path) -> None:
    ledger = _complete_all_closed_ledger()
    a_class = ledger["classes"][0]["class_id"]
    row = _blocking_row(a_class)
    del row["blocking_reason"]
    ledger["classes"][0] = row
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    verdict = verify(ledger_path, REPO_ROOT)

    assert verdict["ok"] is False
    assert verdict["verdict"] == "RED"
    assert any("non-empty blocking_reason" in e for e in verdict["errors"])


def test_blocking_row_with_guard_ref_is_red() -> None:
    ledger = _complete_all_closed_ledger()
    a_class = ledger["classes"][0]["class_id"]
    row = _blocking_row(a_class)
    row["guard_ref"] = "scripts/ember_01_custody/census.py:build_root_census"
    ledger["classes"][0] = row

    verdict_errors, normalized = _validate_row_shim(row)
    assert normalized is None
    assert any("must not carry guard_ref" in e for e in verdict_errors)


def _validate_row_shim(row: dict):
    from verify_c0_failure_class_ledger import validate_row

    return validate_row(row, REPO_ROOT)


# ---------------------------------------------------------------------------
# Positive: complete ledger with all guards resolving -> CLOSED, exit 0
# ---------------------------------------------------------------------------


def test_positive_complete_ledger_closed(tmp_path: Path) -> None:
    ledger = _complete_all_closed_ledger()
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    verdict = verify(ledger_path, REPO_ROOT)

    assert verdict["ok"] is True
    assert verdict["verdict"] == "CLOSED"
    assert set(verdict["closed_guarded"]) == LAW_LISTED_CLASS_IDS
    assert verdict["blocking"] == []
    assert verdict["errors"] == []


def test_positive_complete_ledger_cli_exit_zero() -> None:
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_ROOT / "verify_c0_failure_class_ledger.py"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    payload = json.loads(result.stdout)
    # The live checked-in ledger is honestly BLOCKED pre-birth (9 classes still open)
    # -> exit 1 is correct here. This asserts the CLI wiring works and is honest,
    # not that the repo has secretly reached CLOSED.
    assert payload["schema"] == "ember-01-c0-conjunct3-verdict-v1"
    if payload["verdict"] == "CLOSED":
        assert result.returncode == 0
    else:
        assert result.returncode == 1


# ---------------------------------------------------------------------------
# The live checked-in ledger itself: schema-valid, no dangling guard_refs, no
# duplicate class_ids, completeness holds. This is the real-consumer smoke test -
# it exercises the actual conjunct-3 entrypoint against the actual shipped ledger.
# ---------------------------------------------------------------------------


def test_live_ledger_is_schema_valid_and_complete() -> None:
    verdict = verify(LIVE_LEDGER_PATH, REPO_ROOT)

    # The live ledger must never be RED - RED means the ledger itself is broken
    # (malformed row, dangling guard_ref, or a law-listed class silently dropped).
    assert verdict["verdict"] in ("BLOCKED", "CLOSED"), verdict["errors"]
    assert verdict["errors"] == []
    # Every law-listed class-kill-law class must be present in the checked-in ledger.
    all_ids = set(verdict["closed_guarded"]) | set(verdict["blocking"])
    assert LAW_LISTED_CLASS_IDS <= all_ids


def test_live_ledger_closed_guarded_rows_resolve() -> None:
    verdict = verify(LIVE_LEDGER_PATH, REPO_ROOT)
    assert verdict["errors"] == []
    # Guard resolution happens as part of verify(); errors == [] already proves every
    # CLOSED_GUARDED row's guard_ref resolved to real bytes. This test names that
    # invariant explicitly for anyone reading test output.
    assert isinstance(verdict["closed_guarded"], list)


# ---------------------------------------------------------------------------
# (e) COLLECTABILITY GATE: a CLOSED_GUARDED row whose test-file guard_ref cannot be
# collected must never count as closed, even though its bytes exist and resolve.
# This kills the dead-on-import false-CLOSE class (2026-07-23 coordinator finding).
# ---------------------------------------------------------------------------

# A KNOWN dead-on-import guard: bytes exist, resolve_guard_ref() passes, but
# `pytest --collect-only` on this file INTERNALERRORs because it imports the
# sub-3B trainer chain, which commit 4f758db0 (2026-07-12) locks at module scope
# with a raise SystemExit("historical_only: ...execution-denied") -- a lock that
# POSTDATES this guard's own landing (#792).
_DEAD_GUARD_REL_PATH = "scripts/tests/test_screen792_bf16_momentum.py"

# A KNOWN collectable guard, for the positive control (must NOT be falsely flagged).
_LIVE_GUARD_REL_PATH = "scripts/test_v0_launch_gate_shard_dir_override.py"


def _ledger_with_single_dead_test_guard(rel_path: str) -> dict:
    """A minimal, schema-complete ledger (every law-listed class present and closed
    against a real resolvable non-test guard) except ONE law-listed class is
    CLOSED_GUARDED against `rel_path` -- the guard file under test."""
    ledger = _complete_all_closed_ledger()
    ledger["classes"][0]["guard_ref"] = rel_path
    return ledger


def test_dead_on_import_guard_is_not_collectable_before_fix(tmp_path: Path) -> None:
    """NEGATIVE case for the collectability gate. Uses the REAL verifier entrypoint
    (verify()) against a real dead-on-import guard file already checked into this
    worktree. Must fail closed: the row is NOT accepted as CLOSED_GUARDED."""
    assert (REPO_ROOT / _DEAD_GUARD_REL_PATH).is_file(), (
        f"fixture guard file missing from checkout: {_DEAD_GUARD_REL_PATH}"
    )
    ledger = _ledger_with_single_dead_test_guard(_DEAD_GUARD_REL_PATH)
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    verdict = verify(ledger_path, REPO_ROOT)

    assert verdict["ok"] is False
    assert verdict["verdict"] == "RED"
    assert any("not collectable" in e for e in verdict["errors"]), verdict["errors"]


def test_collectable_guard_still_passes_positive_control(tmp_path: Path) -> None:
    """POSITIVE control: a CLOSED_GUARDED row citing a collectable guard test file
    must NOT be falsely flagged dead by the same gate."""
    assert (REPO_ROOT / _LIVE_GUARD_REL_PATH).is_file(), (
        f"fixture guard file missing from checkout: {_LIVE_GUARD_REL_PATH}"
    )
    ledger = _ledger_with_single_dead_test_guard(_LIVE_GUARD_REL_PATH)
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    verdict = verify(ledger_path, REPO_ROOT)

    assert verdict["ok"] is True
    assert verdict["verdict"] == "CLOSED"
    assert verdict["errors"] == []


def test_non_test_guard_ref_skips_collectability_probe(tmp_path: Path) -> None:
    """A non-test guard_ref (a validator module referenced by symbol, e.g.
    census.py:build_root_census) is out of scope for the collectability probe and
    keeps the prior bytes+symbol-only behavior -- never pytest-collected."""
    ledger = _complete_all_closed_ledger()
    ledger["classes"][0]["guard_ref"] = "scripts/ember_01_custody/census.py:build_root_census"
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    verdict = verify(ledger_path, REPO_ROOT)

    assert verdict["ok"] is True
    assert verdict["verdict"] == "CLOSED"


def test_check_collectability_direct_on_dead_guard() -> None:
    """Direct unit-level exercise of check_collectability() against the real dead
    guard file, independent of the ledger wiring."""
    from verify_c0_failure_class_ledger import check_collectability

    ok, reason = check_collectability(REPO_ROOT, _DEAD_GUARD_REL_PATH)
    assert ok is False
    assert reason


def test_check_collectability_direct_on_live_guard() -> None:
    """Direct unit-level exercise of check_collectability() against the real
    collectable guard file, independent of the ledger wiring."""
    from verify_c0_failure_class_ledger import check_collectability

    ok, reason = check_collectability(REPO_ROOT, _LIVE_GUARD_REL_PATH)
    assert ok is True
    assert reason == ""
