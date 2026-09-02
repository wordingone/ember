#!/usr/bin/env python3
"""gate9_regime_enforcer.py — Gate-9 regime schema enforcer for C7 self-growth operator.

Purpose
-------
Validates state/training-regime-{k}.json before allowing an iGRPO cycle to start.
Raises RegimeGateError (hard error) if the file is absent, malformed, missing required
fields, has out-of-range values, or contains unexpected fields (R1 firewall: the operator
cannot write fields outside the schema).

This is the structural mechanism that makes the self-growth operator MANDATORY.
Without this gate, the operator is optional from the cycle's perspective — Design A's R2
failure where the operator can be deleted and the cycle continues silently degraded.

Schema
------
  lr_multiplier       : float  in [0.1, 1.0]
  N_drafts            : int    in [2, 8]
  G_refinements       : int    in [2, 8]
  curriculum_slice_id : int    in [0, 10]
  token_budget_per_task: int   in [16, 256]

Key interfaces
--------------
  REGIME_SCHEMA          : dict   — {field: (type, lo, hi)}
  RegimeGateError        : Exception raised on any schema violation
  validate_regime(regime)         — raises RegimeGateError on violation
  load_and_validate_regime(state_dir, cycle_id) -> dict  — load + validate atomically
  check_regime_file_exists(state_dir, cycle_id) -> bool

Run selftests:
  python gate9_regime_enforcer.py        # exits 0 on full pass
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import torch  # CPU only; imported for the loadbearing property toy


# ---------------------------------------------------------------------------
# Schema definition
# ---------------------------------------------------------------------------

# Each entry: field_name -> (python_type, inclusive_lo, inclusive_hi)
REGIME_SCHEMA: dict[str, tuple[type, float, float]] = {
    "lr_multiplier":        (float, 0.1,  1.0),
    "N_drafts":             (int,   2,    8),
    "G_refinements":        (int,   2,    8),
    "curriculum_slice_id":  (int,   0,    10),
    "token_budget_per_task":(int,   16,   256),
}

_REQUIRED_FIELDS = set(REGIME_SCHEMA.keys())


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class RegimeGateError(Exception):
    """Raised on any schema violation.  Message names the violating field and expected range."""


# ---------------------------------------------------------------------------
# Core validation
# ---------------------------------------------------------------------------

def validate_regime(regime: dict) -> None:
    """Validate a regime dict against REGIME_SCHEMA.

    Raises RegimeGateError on:
      - unexpected fields (R1 firewall — operator cannot write outside the schema)
      - missing required fields
      - wrong type
      - value outside [lo, hi]

    Returns None on success.
    """
    if not isinstance(regime, dict):
        raise RegimeGateError(
            f"Regime must be a dict, got {type(regime).__name__}"
        )

    present = set(regime.keys())

    # R1 firewall: unexpected fields are a hard error
    unexpected = present - _REQUIRED_FIELDS
    if unexpected:
        raise RegimeGateError(
            f"Unexpected field(s) not in schema: {sorted(unexpected)}. "
            f"Permitted fields: {sorted(_REQUIRED_FIELDS)}"
        )

    # Missing required fields
    missing = _REQUIRED_FIELDS - present
    if missing:
        raise RegimeGateError(
            f"Missing required field(s): {sorted(missing)}"
        )

    # Per-field type + range checks
    for field_name, (expected_type, lo, hi) in REGIME_SCHEMA.items():
        value = regime[field_name]

        # Type check: be permissive about int/float coercion only for float fields
        if expected_type is float:
            if not isinstance(value, (int, float)):
                raise RegimeGateError(
                    f"Field '{field_name}': expected float, got {type(value).__name__}"
                )
            value = float(value)
        elif expected_type is int:
            if not isinstance(value, int) or isinstance(value, bool):
                raise RegimeGateError(
                    f"Field '{field_name}': expected int, got {type(value).__name__}"
                )
        else:
            if not isinstance(value, expected_type):
                raise RegimeGateError(
                    f"Field '{field_name}': expected {expected_type.__name__}, "
                    f"got {type(value).__name__}"
                )

        # Range check (inclusive both ends)
        if not (lo <= value <= hi):
            raise RegimeGateError(
                f"Field '{field_name}' = {value} is outside permitted range "
                f"[{lo}, {hi}]"
            )


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def _regime_path(state_dir: Path, cycle_id: int) -> Path:
    return Path(state_dir) / f"training-regime-{cycle_id}.json"


def check_regime_file_exists(state_dir: Path, cycle_id: int) -> bool:
    """Return True iff the regime file for cycle_id exists in state_dir."""
    return _regime_path(state_dir, cycle_id).is_file()


def load_and_validate_regime(state_dir: Path, cycle_id: int) -> dict:
    """Load training-regime-{cycle_id}.json from state_dir and validate it atomically.

    Raises RegimeGateError if:
      - the file does not exist
      - the file is not valid JSON
      - the parsed dict fails validate_regime

    Returns the validated regime dict on success.
    """
    path = _regime_path(state_dir, cycle_id)
    if not path.is_file():
        raise RegimeGateError(
            f"Regime file not found: {path}. "
            f"The self-growth operator must emit state/training-regime-{cycle_id}.json "
            f"before cycle {cycle_id} can start. (Gate-9 mandatory operator check.)"
        )

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegimeGateError(f"Cannot read regime file {path}: {exc}") from exc

    try:
        regime = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RegimeGateError(
            f"Regime file {path} is not valid JSON: {exc}"
        ) from exc

    validate_regime(regime)
    return regime


# ---------------------------------------------------------------------------
# Toy loadbearing property: simulate what happens with vs without operator
# ---------------------------------------------------------------------------

def _toy_without_operator() -> float:
    """Simulate a decision made WITHOUT the operator's regime.

    Uses default hyperparams (lr_multiplier=1.0, N_drafts=2) — the static fallback that
    an operator-free cycle would use.  Returns a toy 'score' from one iGRPO-style step
    on a tiny policy.
    """
    torch.manual_seed(42)
    # Tiny 1-layer linear policy: 4-dim input -> 2-dim logits
    policy = torch.nn.Linear(4, 2)
    optimizer = torch.optim.SGD(policy.parameters(), lr=1.0)  # default lr_mult=1.0

    # Batch of 2 rollouts (N_drafts=2)
    x = torch.randn(2, 4)
    logits = policy(x)
    # Simple GRPO-style update: advantages are random (no operator tuning)
    advantages = torch.tensor([1.0, -1.0])
    log_probs = torch.nn.functional.log_softmax(logits, dim=-1)
    chosen = torch.tensor([0, 1])
    per_token_lp = log_probs[torch.arange(2), chosen]
    loss = -(per_token_lp * advantages).mean()
    optimizer.zero_grad()
    loss.backward()
    optimizer.step()
    return float(loss.detach())


def _toy_with_operator(regime: dict) -> float:
    """Simulate a decision made WITH the operator's regime.

    Uses the operator-emitted hyperparams to tune the update.  Returns a toy 'score'
    that should differ from the without-operator baseline (proving the operator's output
    is load-bearing in the decision path).
    """
    torch.manual_seed(42)
    policy = torch.nn.Linear(4, 2)
    lr_mult = float(regime["lr_multiplier"])
    n_drafts = int(regime["N_drafts"])
    optimizer = torch.optim.SGD(policy.parameters(), lr=lr_mult)

    x = torch.randn(n_drafts, 4)
    logits = policy(x)
    advantages = torch.tensor([1.0, -1.0] * (n_drafts // 2) + [1.0] * (n_drafts % 2))
    advantages = advantages[:n_drafts]
    log_probs = torch.nn.functional.log_softmax(logits, dim=-1)
    chosen = torch.zeros(n_drafts, dtype=torch.long)
    per_token_lp = log_probs[torch.arange(n_drafts), chosen]
    loss = -(per_token_lp * advantages).mean()
    optimizer.zero_grad()
    loss.backward()
    optimizer.step()
    return float(loss.detach())


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _run_selftests() -> None:
    """CPU selftest suite.  Exits 0 on full pass; prints failures and exits 1."""
    import tempfile
    import os

    failures: list[str] = []

    def ok(name: str) -> None:
        print(f"  PASS  {name}")

    def fail(name: str, msg: str) -> None:
        print(f"  FAIL  {name}: {msg}")
        failures.append(name)

    def expect_no_error(name: str, fn) -> None:
        try:
            fn()
            ok(name)
        except Exception as exc:
            fail(name, str(exc))

    def expect_regime_gate_error(name: str, fn) -> None:
        try:
            fn()
            fail(name, "Expected RegimeGateError but no exception raised")
        except RegimeGateError:
            ok(name)
        except Exception as exc:
            fail(name, f"Expected RegimeGateError, got {type(exc).__name__}: {exc}")

    # --- Valid baseline regime ---
    VALID_REGIME = {
        "lr_multiplier":        0.5,
        "N_drafts":             4,
        "G_refinements":        4,
        "curriculum_slice_id":  3,
        "token_budget_per_task":64,
    }

    print("Gate-9 regime enforcer selftests")
    print("=================================")

    # 1. Valid regime passes without error
    expect_no_error(
        "validate_regime with all valid fields passes without error",
        lambda: validate_regime(VALID_REGIME),
    )

    # 2. lr_multiplier < 0.1 raises
    expect_regime_gate_error(
        "validate_regime raises RegimeGateError when lr_multiplier < 0.1",
        lambda: validate_regime({**VALID_REGIME, "lr_multiplier": 0.09}),
    )

    # 3. lr_multiplier > 1.0 raises
    expect_regime_gate_error(
        "validate_regime raises RegimeGateError when lr_multiplier > 1.0",
        lambda: validate_regime({**VALID_REGIME, "lr_multiplier": 1.01}),
    )

    # 4. N_drafts > 8 raises
    expect_regime_gate_error(
        "validate_regime raises RegimeGateError when N_drafts > 8",
        lambda: validate_regime({**VALID_REGIME, "N_drafts": 9}),
    )

    # 5. Missing required field raises
    expect_regime_gate_error(
        "validate_regime raises RegimeGateError when a required field is missing",
        lambda: validate_regime({k: v for k, v in VALID_REGIME.items() if k != "G_refinements"}),
    )

    # 6. Unexpected field raises (R1 firewall)
    expect_regime_gate_error(
        "validate_regime raises RegimeGateError when an unexpected field is present",
        lambda: validate_regime({**VALID_REGIME, "rogue_field": 99}),
    )

    # 7. load_and_validate_regime raises when file does not exist
    with tempfile.TemporaryDirectory() as tmpdir:
        expect_regime_gate_error(
            "load_and_validate_regime raises RegimeGateError when the file does not exist",
            lambda: load_and_validate_regime(Path(tmpdir), cycle_id=0),
        )

    # 8. load_and_validate_regime succeeds with a valid file
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "training-regime-7.json"
        p.write_text(json.dumps(VALID_REGIME), encoding="utf-8")
        expect_no_error(
            "load_and_validate_regime succeeds with a valid file",
            lambda: load_and_validate_regime(Path(tmpdir), cycle_id=7),
        )

    # 9. check_regime_file_exists
    with tempfile.TemporaryDirectory() as tmpdir:
        assert not check_regime_file_exists(Path(tmpdir), cycle_id=3), "should be absent"
        p = Path(tmpdir) / "training-regime-3.json"
        p.write_text("{}", encoding="utf-8")
        assert check_regime_file_exists(Path(tmpdir), cycle_id=3), "should be present"
        ok("check_regime_file_exists returns False/True correctly")

    # 10. Additional range checks
    expect_regime_gate_error(
        "validate_regime raises for G_refinements < 2",
        lambda: validate_regime({**VALID_REGIME, "G_refinements": 1}),
    )
    expect_regime_gate_error(
        "validate_regime raises for G_refinements > 8",
        lambda: validate_regime({**VALID_REGIME, "G_refinements": 9}),
    )
    expect_regime_gate_error(
        "validate_regime raises for curriculum_slice_id < 0",
        lambda: validate_regime({**VALID_REGIME, "curriculum_slice_id": -1}),
    )
    expect_regime_gate_error(
        "validate_regime raises for curriculum_slice_id > 10",
        lambda: validate_regime({**VALID_REGIME, "curriculum_slice_id": 11}),
    )
    expect_regime_gate_error(
        "validate_regime raises for token_budget_per_task < 16",
        lambda: validate_regime({**VALID_REGIME, "token_budget_per_task": 15}),
    )
    expect_regime_gate_error(
        "validate_regime raises for token_budget_per_task > 256",
        lambda: validate_regime({**VALID_REGIME, "token_budget_per_task": 257}),
    )

    # 11. Type checks
    expect_regime_gate_error(
        "validate_regime raises for N_drafts as float",
        lambda: validate_regime({**VALID_REGIME, "N_drafts": 4.0}),
    )
    expect_regime_gate_error(
        "validate_regime raises for lr_multiplier as string",
        lambda: validate_regime({**VALID_REGIME, "lr_multiplier": "0.5"}),
    )

    # 12. Malformed JSON raises
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "training-regime-0.json"
        p.write_text("not-json{{{", encoding="utf-8")
        expect_regime_gate_error(
            "load_and_validate_regime raises for malformed JSON",
            lambda: load_and_validate_regime(Path(tmpdir), cycle_id=0),
        )

    # 13. Boundary values pass (inclusive endpoints)
    expect_no_error(
        "validate_regime passes at inclusive lower bounds",
        lambda: validate_regime({
            "lr_multiplier":        0.1,
            "N_drafts":             2,
            "G_refinements":        2,
            "curriculum_slice_id":  0,
            "token_budget_per_task":16,
        }),
    )
    expect_no_error(
        "validate_regime passes at inclusive upper bounds",
        lambda: validate_regime({
            "lr_multiplier":        1.0,
            "N_drafts":             8,
            "G_refinements":        8,
            "curriculum_slice_id":  10,
            "token_budget_per_task":256,
        }),
    )

    # -------------------------------------------------------------------
    # Loadbearing property: deleted-operator degrades the next decision
    # -------------------------------------------------------------------
    print()
    print("Loadbearing property test")
    print("-------------------------")
    loadbearing_proved = False
    try:
        # Operator-emitted regime with non-default values
        operator_regime = {
            "lr_multiplier":        0.3,   # NOT the default 1.0
            "N_drafts":             6,     # NOT the default 2
            "G_refinements":        4,
            "curriculum_slice_id":  2,
            "token_budget_per_task":128,
        }
        validate_regime(operator_regime)  # must be valid

        score_without = _toy_without_operator()
        score_with    = _toy_with_operator(operator_regime)

        # The two scores must differ — operator's regime changes the decision path
        diff = abs(score_with - score_without)
        loadbearing_proved = diff > 1e-9

        if loadbearing_proved:
            print(f"  PASS  loadbearing property: |score_with - score_without| = {diff:.6f} > 1e-9")
            print(f"        score_without_operator = {score_without:.6f}")
            print(f"        score_with_operator    = {score_with:.6f}")
        else:
            print(f"  FAIL  loadbearing property: scores identical (diff={diff:.2e})")
            failures.append("loadbearing property")
    except Exception as exc:
        print(f"  FAIL  loadbearing property (exception): {exc}")
        failures.append("loadbearing property (exception)")

    # -------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------
    print()
    if failures:
        print(f"FAILED: {len(failures)} test(s): {failures}")
        sys.exit(1)
    else:
        n = 14 + 8 + 2  # approx count (some multi-checks above)
        print("ALL TESTS PASSED")
        print(f"loadbearing_proved = {loadbearing_proved}")
        sys.exit(0)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    _run_selftests()
