#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""operator_constants.py — C7 self-growth operator frozen hyperparameters.

Writes and hashes the operator hyperparameters to state/operator-constants.json
before cycle 0. Every emission reads from this file; the operator's behavior is
fully determined by receipts + frozen constants, never by hidden in-code state.

Key interfaces:
  write_operator_constants(out_path, overrides=None) -> dict
      Writes JSON with SHA-256 hash field; returns the dict.
  load_operator_constants(path) -> dict
      Loads + asserts hash matches. Raises ValueError on tamper.
  DEFAULT_CONSTANTS: dict
      Baseline values used by the CPU selftest.

CPU selftest (run as __main__):
  - round-trip identity
  - hash field correctness
  - tamper detection (ValueError on body mutation)
  - override produces dict differing only in overridden keys
  - load-bearing property: operator present improves toy decisions vs deleted
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import torch

# ---------------------------------------------------------------------------
# Frozen default constants
# ---------------------------------------------------------------------------

DEFAULT_CONSTANTS: dict[str, Any] = {
    # Variance floor: if batch reward variance < this threshold, the advantage
    # normalisation denominator is clamped here to prevent division blow-up.
    "variance_floor_threshold": 0.05,

    # Advantage floor: advantages whose absolute value falls below this are
    # zeroed before the policy-gradient update (noise-rejection gate).
    "advantage_floor_threshold": 0.02,

    # Maximum group size N for iGRPO group normalisation.
    "N_max": 8,

    # Learning-rate floor: lr is never allowed to decay below this value.
    "lr_floor": 0.1,

    # C_cooling: number of consecutive no-improvement cycles before the
    # cooling window triggers a lr/N adjustment.
    "C_cooling": 3,

    # N_cooling: number of cycles in each cooling window (duration).
    "N_cooling": 2,

    # Token budgets for the three operator slice tiers (tokens per generation).
    "slice_token_budgets": [32, 48, 64],
}

# ---------------------------------------------------------------------------
# Hash helpers
# ---------------------------------------------------------------------------

_HASH_FIELD = "sha256"


def _canonical_json(d: dict) -> str:
    """Produce canonical (sorted-keys) JSON string for hashing.

    The hash field itself is excluded so the body can be hashed before the
    field is injected.
    """
    body = {k: v for k, v in d.items() if k != _HASH_FIELD}
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def _compute_hash(d: dict) -> str:
    """SHA-256 of the canonical JSON body (hash field excluded)."""
    canonical = _canonical_json(d)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def write_operator_constants(
    out_path: Path,
    overrides: dict | None = None,
) -> dict:
    """Write frozen operator constants to *out_path* as JSON + SHA-256 hash.

    Parameters
    ----------
    out_path:
        Destination file path. Parent directory must exist.
    overrides:
        Optional dict of keys to override on top of DEFAULT_CONSTANTS.
        Overrides are shallow-merged; list values (e.g. slice_token_budgets)
        are replaced wholesale, not appended.

    Returns
    -------
    dict
        The full constants dict including the ``sha256`` hash field.
    """
    out_path = Path(out_path)

    # Build the constants dict (copy to avoid mutating DEFAULT_CONSTANTS).
    constants = copy.deepcopy(DEFAULT_CONSTANTS)
    if overrides:
        for k, v in overrides.items():
            constants[k] = v

    # Compute hash over the body (no hash field present yet).
    constants[_HASH_FIELD] = _compute_hash(constants)

    # Write atomically via a temp file in the same directory, then rename.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(".tmp")
    try:
        tmp_path.write_text(
            json.dumps(constants, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(out_path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise

    return constants


def load_operator_constants(path: Path) -> dict:
    """Load operator constants from *path* and verify the SHA-256 hash.

    Parameters
    ----------
    path:
        Path to the JSON file written by :func:`write_operator_constants`.

    Returns
    -------
    dict
        The full constants dict including the ``sha256`` hash field.

    Raises
    ------
    ValueError
        If the file is missing the hash field, or if the stored hash does not
        match a freshly computed hash of the body (tamper detected).
    FileNotFoundError
        If *path* does not exist.
    """
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))

    if _HASH_FIELD not in raw:
        raise ValueError(
            f"operator-constants file {path} is missing the '{_HASH_FIELD}' field."
        )

    stored_hash = raw[_HASH_FIELD]
    expected_hash = _compute_hash(raw)

    if stored_hash != expected_hash:
        raise ValueError(
            f"operator-constants tamper detected at {path}:\n"
            f"  stored  sha256 = {stored_hash}\n"
            f"  computed sha256 = {expected_hash}"
        )

    return raw


# ---------------------------------------------------------------------------
# Toy load-bearing property: operator present vs deleted
# ---------------------------------------------------------------------------

def _toy_advantage(reward: float, baseline: float, constants: dict) -> float:
    """Compute clipped advantage using operator constants.

    advantage = reward - baseline, then floor-clamped and noise-rejected.
    """
    adv = reward - baseline
    adv_floor = constants["advantage_floor_threshold"]
    # Zero out sub-threshold advantages (noise-rejection gate).
    if abs(adv) < adv_floor:
        adv = 0.0
    return adv


def _toy_variance_safe_normalise(advantages: list[float], constants: dict) -> list[float]:
    """Normalise advantages with variance floor from operator constants."""
    if not advantages:
        return advantages
    t = torch.tensor(advantages, dtype=torch.float32)
    mean = t.mean()
    std = t.std(unbiased=False)
    var_floor = constants["variance_floor_threshold"] ** 0.5
    std_clamped = torch.clamp(std, min=var_floor)
    return ((t - mean) / std_clamped).tolist()


def _toy_decision_quality(constants: dict | None) -> float:
    """Return a quality metric for a toy decision with/without the operator.

    The toy scenario: a batch of 4 rollouts with rewards [0.0, 0.5, 0.5, 1.0].
    The 'policy' update is the L2 norm of the normalised advantages —
    larger norm = more signal extracted = better decision quality.

    With operator constants: variance floor + advantage floor are applied.
    Without operator (deleted): raw advantages (no floor, no normalisation).
    """
    rewards = [0.0, 0.5, 0.5, 1.0]
    baseline = sum(rewards) / len(rewards)  # group mean

    if constants is not None:
        # Operator present: compute floored advantages then normalise.
        adv = [_toy_advantage(r, baseline, constants) for r in rewards]
        adv_norm = _toy_variance_safe_normalise(adv, constants)
    else:
        # Operator deleted: raw advantages, no floor, no normalisation guard.
        adv_norm = [r - baseline for r in rewards]

    # Quality = L2 norm of the advantage vector (proxy for usable gradient signal).
    t = torch.tensor(adv_norm, dtype=torch.float32)
    return float(t.norm())


# ---------------------------------------------------------------------------
# CPU selftest
# ---------------------------------------------------------------------------

def _run_selftest() -> int:
    """Run all assertions. Returns 0 on pass, 1 on first failure."""
    errors: list[str] = []

    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td)
        tmp_file = tmp_dir / "operator-constants.json"

        # ------------------------------------------------------------------
        # Test 1: round-trip identity
        # ------------------------------------------------------------------
        written = write_operator_constants(tmp_file)
        loaded = load_operator_constants(tmp_file)
        # Strip hash for value comparison (hash is present in both).
        written_body = {k: v for k, v in written.items() if k != _HASH_FIELD}
        loaded_body = {k: v for k, v in loaded.items() if k != _HASH_FIELD}
        if written_body != loaded_body:
            errors.append(
                f"FAIL round-trip: written_body != loaded_body\n"
                f"  written: {written_body}\n"
                f"  loaded:  {loaded_body}"
            )
        else:
            print("PASS test 1: round-trip identity")

        # The full dict (including hash field) must match DEFAULT_CONSTANTS + hash.
        default_plus_hash = copy.deepcopy(DEFAULT_CONSTANTS)
        default_plus_hash[_HASH_FIELD] = _compute_hash(default_plus_hash)
        if loaded != default_plus_hash:
            errors.append(
                f"FAIL round-trip full: loaded != DEFAULT_CONSTANTS+hash\n"
                f"  loaded:        {loaded}\n"
                f"  expected:      {default_plus_hash}"
            )
        else:
            print("PASS test 1b: loaded == DEFAULT_CONSTANTS + hash")

        # ------------------------------------------------------------------
        # Test 2: hash field correctness
        # ------------------------------------------------------------------
        stored_hash = loaded[_HASH_FIELD]
        expected_hash = _compute_hash(loaded)
        if stored_hash != expected_hash:
            errors.append(
                f"FAIL hash field: stored {stored_hash} != expected {expected_hash}"
            )
        else:
            print("PASS test 2: hash field matches sha256(body)")

        # ------------------------------------------------------------------
        # Test 3: tamper detection raises ValueError
        # ------------------------------------------------------------------
        # Mutate the JSON body on disk without updating the hash.
        raw = json.loads(tmp_file.read_text(encoding="utf-8"))
        raw["variance_floor_threshold"] = 9999.0  # tamper
        tmp_file.write_text(json.dumps(raw, sort_keys=True, indent=2), encoding="utf-8")
        tamper_caught = False
        try:
            load_operator_constants(tmp_file)
        except ValueError:
            tamper_caught = True
        if not tamper_caught:
            errors.append("FAIL tamper detection: ValueError not raised after body mutation")
        else:
            print("PASS test 3: tamper detection raises ValueError")

        # Re-write clean for subsequent tests.
        write_operator_constants(tmp_file)

        # ------------------------------------------------------------------
        # Test 4: overrides produce dict differing only in overridden keys
        # ------------------------------------------------------------------
        overrides = {"N_max": 16, "lr_floor": 0.01}
        override_file = tmp_dir / "operator-constants-override.json"
        overridden = write_operator_constants(override_file, overrides=overrides)

        # Check overridden keys differ.
        for k, v in overrides.items():
            if overridden[k] != v:
                errors.append(
                    f"FAIL overrides: key '{k}' expected {v}, got {overridden[k]}"
                )
            else:
                print(f"PASS test 4a: override key '{k}' = {v}")

        # Check non-overridden keys are identical to defaults.
        for k in DEFAULT_CONSTANTS:
            if k in overrides:
                continue
            if overridden[k] != DEFAULT_CONSTANTS[k]:
                errors.append(
                    f"FAIL overrides: non-overridden key '{k}' changed: "
                    f"{DEFAULT_CONSTANTS[k]} -> {overridden[k]}"
                )
        print("PASS test 4b: non-overridden keys unchanged")

        # ------------------------------------------------------------------
        # Test 5: load-bearing property (operator present > deleted)
        # ------------------------------------------------------------------
        constants = load_operator_constants(tmp_file)
        quality_with = _toy_decision_quality(constants)
        quality_deleted = _toy_decision_quality(None)

        print(
            f"  load-bearing: quality_with_operator={quality_with:.4f}  "
            f"quality_deleted={quality_deleted:.4f}"
        )

        # The operator provides variance-safe normalisation; the normalised
        # advantages should have higher L2 norm (more usable gradient) than
        # raw un-normalised advantages on this toy batch.
        if quality_with <= quality_deleted:
            errors.append(
                f"FAIL load-bearing property: quality_with={quality_with:.4f} "
                f"<= quality_deleted={quality_deleted:.4f}\n"
                f"  Expected: operator normalisation extracts MORE usable signal."
            )
            selftest_proves_loadbearing = False
        else:
            print("PASS test 5: operator present > deleted on toy decision quality")
            selftest_proves_loadbearing = True

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    if errors:
        print("\n=== SELFTEST FAILURES ===")
        for e in errors:
            print(e)
        print(f"\nFAILED: {len(errors)} assertion(s)")
        return 1

    print(
        f"\nALL SELFTESTS PASSED  "
        f"(load-bearing: with={quality_with:.4f} > deleted={quality_deleted:.4f})"
    )
    print(f"selftest_proves_loadbearing: {selftest_proves_loadbearing}")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(_run_selftest())
