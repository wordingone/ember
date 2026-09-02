# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""
ember_phase4_c15/bitnet_blocked_emitter.py

Standalone BITNET_BLOCKED emitter for C15.

Emits a well-formed BITNET_BLOCKED receipt to disk when the C14 gate PASS receipt
is absent (or when called directly from the comparison rig or CLI).

Public API
----------
emit_blocked(out_path, missing_surface, next_command) -> dict
    Write a BITNET_BLOCKED receipt JSON to out_path and return the receipt dict.

main() -> int
    CLI entry point.
    Usage:
        python bitnet_blocked_emitter.py \\
            --out /path/to/receipt.json \\
            --missing-surface "resident-training gate PASS receipt" \\
            --next-command "python ember_resident_training_gate.py --run"

    Exits 0 on BITNET_BLOCKED_EMITTER_SELFTEST_PASS when --selftest is passed.

CPU selftest
------------
Run with --selftest (or via __main__) to emit a receipt to a tempdir and verify
all required fields. No GPU, no C-BASE weights required.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Receipt schema
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = frozenset(
    {
        "ticket",
        "ts",
        "missing_implementation_surface",
        "next_executable_command",
        "verdict",
    }
)

TICKET = "EMBER-C15-BITNET-BLOCKED"
VERDICT = "BITNET_BLOCKED"


# ---------------------------------------------------------------------------
# Core emitter
# ---------------------------------------------------------------------------


def emit_blocked(
    out_path: Path,
    missing_surface: str,
    next_command: str,
    *,
    extra: Optional[dict] = None,
) -> dict:
    """Write a BITNET_BLOCKED receipt to *out_path* and return the receipt dict.

    Parameters
    ----------
    out_path:
        Destination file.  Parent directories are created if absent.
    missing_surface:
        Exact human-readable string naming the absent surface, e.g.
        ``"resident-training gate PASS receipt"``.
    next_command:
        Exact shell command that unblocks the missing surface, e.g.
        ``"python ember_resident_training_gate.py --run"``.
    extra:
        Optional additional fields to merge into the receipt (must not
        shadow any required field).

    Returns
    -------
    dict
        The receipt that was written (identical to what is on disk).

    Raises
    ------
    ValueError
        If *missing_surface* or *next_command* are empty strings, or if
        *extra* contains a key that shadows a required field.
    TypeError
        If *out_path* is not a Path-like object.
    """
    if not missing_surface or not missing_surface.strip():
        raise ValueError("missing_surface must be a non-empty string")
    if not next_command or not next_command.strip():
        raise ValueError("next_command must be a non-empty string")

    out_path = Path(out_path)

    if extra is not None:
        shadow = REQUIRED_FIELDS & set(extra.keys())
        if shadow:
            raise ValueError(
                f"extra dict must not shadow required fields: {sorted(shadow)}"
            )

    ts = datetime.now(tz=timezone.utc).isoformat()

    receipt: dict = {
        "ticket": TICKET,
        "ts": ts,
        "missing_implementation_surface": missing_surface.strip(),
        "next_executable_command": next_command.strip(),
        "verdict": VERDICT,
    }
    if extra:
        receipt.update(extra)

    # Deterministic integrity token (sha256 over stable subset)
    stable = json.dumps(
        {k: receipt[k] for k in sorted(REQUIRED_FIELDS)}, sort_keys=True
    ).encode()
    receipt["_integrity"] = hashlib.sha256(stable).hexdigest()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return receipt


# ---------------------------------------------------------------------------
# Validator (used by comparison rig and verifier)
# ---------------------------------------------------------------------------


def validate_receipt(receipt: dict) -> list[str]:
    """Return a list of validation errors.  Empty list = valid."""
    errors: list[str] = []

    missing = REQUIRED_FIELDS - set(receipt.keys())
    if missing:
        errors.append(f"missing fields: {sorted(missing)}")

    if receipt.get("ticket") != TICKET:
        errors.append(
            f"ticket mismatch: expected {TICKET!r}, got {receipt.get('ticket')!r}"
        )
    if receipt.get("verdict") != VERDICT:
        errors.append(
            f"verdict mismatch: expected {VERDICT!r}, got {receipt.get('verdict')!r}"
        )

    for field in ("missing_implementation_surface", "next_executable_command"):
        val = receipt.get(field, "")
        if not isinstance(val, str) or not val.strip():
            errors.append(f"{field!r} must be a non-empty string")

    # Integrity check (optional — skip if field absent, fail if present + wrong)
    if "_integrity" in receipt:
        stable = json.dumps(
            {k: receipt[k] for k in sorted(REQUIRED_FIELDS)}, sort_keys=True
        ).encode()
        expected = hashlib.sha256(stable).hexdigest()
        if receipt["_integrity"] != expected:
            errors.append(
                f"_integrity mismatch: expected {expected!r}, "
                f"got {receipt['_integrity']!r}"
            )

    return errors


# ---------------------------------------------------------------------------
# CPU selftest
# ---------------------------------------------------------------------------


def _run_selftest() -> int:
    """Full CPU selftest.  Returns 0 on pass, non-zero on failure.

    Tests performed
    ---------------
    T1  emit_blocked writes a file with all required fields.
    T2  validate_receipt accepts the emitted receipt.
    T3  missing_surface empty string raises ValueError.
    T4  next_command empty string raises ValueError.
    T5  extra dict with a shadowed required key raises ValueError.
    T6  Receipt loaded from disk round-trips cleanly through validate_receipt.
    T7  Two calls with different surfaces produce distinct receipts (different ts
        is sufficient; integrity tokens differ too).
    T8  out_path parent auto-created (nested path that does not exist yet).
    T9  CLI smoke: emit via main() argument simulation, verify file on disk.
    """
    import traceback

    failures: list[str] = []

    def _fail(tag: str, msg: str) -> None:
        failures.append(f"[{tag}] {msg}")
        print(f"  FAIL {tag}: {msg}", file=sys.stderr)

    def _pass(tag: str) -> None:
        print(f"  PASS {tag}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        # T1 — basic emit
        receipt_path = tmp_path / "blocked.json"
        surface = "resident-training gate PASS receipt"
        cmd = "python ember_resident_training_gate.py --run"
        try:
            receipt = emit_blocked(receipt_path, surface, cmd)
            assert receipt_path.exists(), "receipt file not written"
            for f in REQUIRED_FIELDS:
                assert f in receipt, f"field {f!r} missing from returned dict"
            _pass("T1")
        except Exception as exc:  # noqa: BLE001
            _fail("T1", str(exc))

        # T2 — validate_receipt accepts the emitted receipt
        try:
            errors = validate_receipt(receipt)
            assert errors == [], f"validation errors: {errors}"
            _pass("T2")
        except Exception as exc:
            _fail("T2", str(exc))

        # T3 — empty missing_surface raises ValueError
        try:
            raised = False
            try:
                emit_blocked(tmp_path / "x.json", "", cmd)
            except ValueError:
                raised = True
            assert raised, "did not raise ValueError for empty missing_surface"
            _pass("T3")
        except Exception as exc:
            _fail("T3", str(exc))

        # T4 — empty next_command raises ValueError
        try:
            raised = False
            try:
                emit_blocked(tmp_path / "x.json", surface, "")
            except ValueError:
                raised = True
            assert raised, "did not raise ValueError for empty next_command"
            _pass("T4")
        except Exception as exc:
            _fail("T4", str(exc))

        # T5 — extra dict shadowing a required field raises ValueError
        try:
            raised = False
            try:
                emit_blocked(
                    tmp_path / "x.json",
                    surface,
                    cmd,
                    extra={"verdict": "OVERRIDE"},
                )
            except ValueError:
                raised = True
            assert raised, "did not raise ValueError for shadowed required field"
            _pass("T5")
        except Exception as exc:
            _fail("T5", str(exc))

        # T6 — disk round-trip
        try:
            loaded = json.loads(receipt_path.read_text(encoding="utf-8"))
            errors = validate_receipt(loaded)
            assert errors == [], f"disk round-trip validation errors: {errors}"
            assert loaded["missing_implementation_surface"] == surface
            assert loaded["next_executable_command"] == cmd
            assert loaded["verdict"] == VERDICT
            assert loaded["ticket"] == TICKET
            _pass("T6")
        except Exception as exc:
            _fail("T6", str(exc))

        # T7 — two receipts differ (integrity tokens must differ because ts differs
        # or at minimum because the stable subset produces different digests)
        try:
            import time
            p1 = tmp_path / "b1.json"
            p2 = tmp_path / "b2.json"
            r1 = emit_blocked(p1, "surface-A", "cmd-A")
            time.sleep(0.001)  # ensure ts differs
            r2 = emit_blocked(p2, "surface-B", "cmd-B")
            assert r1["_integrity"] != r2["_integrity"], (
                "integrity tokens should differ for different surfaces"
            )
            _pass("T7")
        except Exception as exc:
            _fail("T7", str(exc))

        # T8 — nested path auto-created
        try:
            nested = tmp_path / "a" / "b" / "c" / "receipt.json"
            emit_blocked(nested, surface, cmd)
            assert nested.exists(), "nested path not created"
            _pass("T8")
        except Exception as exc:
            _fail("T8", str(exc))

        # T9 — CLI smoke (simulate sys.argv, capture output)
        try:
            cli_out = tmp_path / "cli_receipt.json"
            old_argv = sys.argv
            sys.argv = [
                "bitnet_blocked_emitter.py",
                "--out", str(cli_out),
                "--missing-surface", "test surface via CLI",
                "--next-command", "echo unblocked",
            ]
            try:
                ret = main()
            finally:
                sys.argv = old_argv
            assert ret == 0, f"main() returned {ret}, expected 0"
            assert cli_out.exists(), "CLI did not write receipt file"
            loaded_cli = json.loads(cli_out.read_text(encoding="utf-8"))
            errors = validate_receipt(loaded_cli)
            assert errors == [], f"CLI receipt validation errors: {errors}"
            _pass("T9")
        except Exception as exc:
            traceback.print_exc()
            _fail("T9", str(exc))

    if failures:
        print(
            f"\nBITNET_BLOCKED_EMITTER_SELFTEST_FAIL  ({len(failures)} failure(s))",
            file=sys.stderr,
        )
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        return 1

    print("\nBITNET_BLOCKED_EMITTER_SELFTEST_PASS")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point.

    Usage (normal emit mode):
        python bitnet_blocked_emitter.py \\
            --out /path/to/receipt.json \\
            --missing-surface "resident-training gate PASS receipt" \\
            --next-command "python ember_resident_training_gate.py --run"

    Usage (selftest mode):
        python bitnet_blocked_emitter.py --selftest
    """
    parser = argparse.ArgumentParser(
        description="Emit a BITNET_BLOCKED receipt for C15.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="Run CPU selftest and exit 0 on BITNET_BLOCKED_EMITTER_SELFTEST_PASS.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output path for the receipt JSON.",
    )
    parser.add_argument(
        "--missing-surface",
        dest="missing_surface",
        type=str,
        default=None,
        help="Exact string naming the absent surface.",
    )
    parser.add_argument(
        "--next-command",
        dest="next_command",
        type=str,
        default=None,
        help="Exact shell command to unblock the missing surface.",
    )

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.selftest:
        return _run_selftest()

    # Validate required args for emit mode
    if args.out is None:
        parser.error("--out is required in emit mode")
    if not args.missing_surface:
        parser.error("--missing-surface is required and must be non-empty")
    if not args.next_command:
        parser.error("--next-command is required and must be non-empty")

    receipt = emit_blocked(
        args.out,
        args.missing_surface,
        args.next_command,
    )

    print(json.dumps(receipt, indent=2))
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    # When invoked as a script with no arguments, run the selftest.
    if len(sys.argv) == 1:
        sys.exit(_run_selftest())
    sys.exit(main())
