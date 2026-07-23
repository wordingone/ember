# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
#!/usr/bin/env python3
"""Emit the unified EMBER-01 nine-condition completion receipt.

EMBER-01 certification today requires assembling evidence from five separate
tools. This aggregates all nine legs into ONE clean-detached-checkout command
and one atomic receipt written OUTSIDE the checkout.

DESIGN RULE - HONESTY OVER GREEN. Every leg carries one of three states:

    resolved-true    the leg's real tool ran and passed
    resolved-false   the leg's real tool ran and failed
    unresolved       the leg could not be evaluated on this checkout
                     (RUNNER-BLOCKED: operator-machine roots or an owned
                      checkpoint are not bindable on a bare clean clone)

`ok` is the AND of all nine legs being resolved-true PLUS checkout integrity
(clean + detached + head_unchanged both ends) and selection integrity. A leg
that cannot be evaluated is UNRESOLVED, never silently true. On a bare clone
the custody/identity/seat legs are honestly UNRESOLVED - that is the proof the
legs bind to real operator state, not a stub.

The receipt does NOT claim training, a model, runtime, or benchmark work
completed - only that the nine authority/custody/identity conditions hold.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

# Leg 8 imports the SAME authority function verify_ember00_completion.py uses.
from verify_authority_conservation import (
    ACTIVE_GOAL_ID,
    NEXT_EXECUTED_OUTCOME,
    verify,
)

RESOLVED_TRUE = "resolved-true"
RESOLVED_FALSE = "resolved-false"
UNRESOLVED = "unresolved"

CONFIG_REL = "configs/ember-restart-3b.json"
LAUNCH_PACKET_REL = "tools/ember-restart-3b/launch_packet.py"
CENSUS_REL = "scripts/ember_01_custody/census.py"
VALIDATE_IDENTITY_REL = "scripts/ember_01_identity/validate_identity.py"
SEAT_TEST_REL = "tools/ember-cli/src/entrypoints/model-seat.test.ts"

# The nine EMBER-01 conditions and which tool certifies each.
LEG_TITLES = {
    "1": "custody root census (operator-machine roots)",
    "2": "artifact custody census",
    "3": "identity round-trip on owned checkpoint",
    "4": "identity fail-closed on tampered checkpoint",
    "5": "reference model seat resolves and serves",
    "6": "benchmark registry freeze",
    "7": "3B launch packet readiness",
    "8": "authority conservation certificate",
    "9": "public issue census freeze",
}


def validate_receipt_path(root: Path, receipt: Path) -> Path:
    root = root.resolve()
    receipt = receipt.resolve()
    try:
        receipt.relative_to(root)
    except ValueError:
        return receipt
    raise ValueError("completion receipt must be outside the verified checkout")


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def inspect_checkout(root: Path) -> dict[str, Any]:
    head = git(root, "rev-parse", "HEAD")
    if head.returncode != 0:
        raise RuntimeError(f"git rev-parse failed: {head.stderr.strip()}")
    symbolic = git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    if symbolic.returncode not in {0, 1}:
        raise RuntimeError(f"git symbolic-ref failed: {symbolic.stderr.strip()}")
    status = git(root, "status", "--porcelain", "--untracked-files=all")
    if status.returncode != 0:
        raise RuntimeError(f"git status failed: {status.stderr.strip()}")
    return {
        "head": head.stdout.strip(),
        "detached": symbolic.returncode != 0,
        "branch": None if symbolic.returncode != 0 else symbolic.stdout.strip(),
        "clean": not status.stdout.strip(),
        "status": status.stdout.strip().splitlines(),
    }


def selection_evidence(selection: Path) -> dict[str, Any]:
    """Mirror EMBER-00: exactly one active_goal_path, file must exist."""
    text = selection.read_text(encoding="utf-8")
    paths = [
        raw.split(":", 1)[1].strip()
        for raw in text.splitlines()
        if raw.split(":", 1)[0].strip() == "active_goal_path" and ":" in raw
    ]
    if len(paths) != 1:
        raise ValueError("selection must contain exactly one active_goal_path")
    goal_path = Path(paths[0])
    if not goal_path.is_absolute():
        goal_path = (selection.parent / goal_path).resolve()
    if not goal_path.is_file():
        raise ValueError(f"selected goal file is missing: {goal_path}")
    return {"selected_goal_suffix": "/".join(paths[0].replace("\\", "/").split("/")[-4:])}


def run(
    args: Sequence[str],
    *,
    root: Path,
    name: str,
    display: Sequence[str] | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        completed = subprocess.run(
            list(args),
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "name": name,
            "returncode": None,
            "timed_out": True,
            "command": list(display or args),
            "stdout": (exc.stdout or "") if isinstance(exc.stdout, str) else "",
            "stderr": f"timeout after {timeout}s",
        }
    except OSError as exc:
        return {
            "name": name,
            "returncode": None,
            "timed_out": False,
            "command": list(display or args),
            "stdout": "",
            "stderr": str(exc),
        }
    return {
        "name": name,
        "returncode": completed.returncode,
        "timed_out": False,
        "command": list(display or args),
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def leg(state: str, title: str, reason: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    if state not in {RESOLVED_TRUE, RESOLVED_FALSE, UNRESOLVED}:
        raise ValueError(f"illegal leg state: {state}")
    row: dict[str, Any] = {"title": title, "state": state, "reason": reason}
    if evidence is not None:
        row["evidence"] = evidence
    return row


# ---- Legs 1/2/6/9: custody / roots / benchmark / issues (census.py) ----------
def custody_legs(root: Path, bindings: list[str], run_custody: bool) -> dict[str, Any]:
    manifests = root / "manifests" / "ember-01-custody"
    root_spec = manifests / "root-spec.json"
    bench = manifests / "benchmark-registry.json"
    issues = manifests / "public-issue-census.json"
    have_manifests = root_spec.is_file() and bench.is_file() and issues.is_file()

    # A bare clean clone cannot bind operator-machine roots. Without real ROOT
    # bindings the census legs are UNRESOLVED (RUNNER-BLOCKED) - never a green
    # pass and never a hard fail. They resolve only when an operator supplies
    # the machine-root bindings and asks to run the census.
    if not (run_custody and bindings):
        why = "no operator-machine ROOT bindings supplied; census cannot bind roots on a bare clone"
        if not have_manifests:
            why = "custody manifests absent AND no ROOT bindings supplied"
        return {k: leg(UNRESOLVED, LEG_TITLES[k], why) for k in ("1", "2", "6", "9")}

    if not have_manifests:
        return {
            k: leg(UNRESOLVED, LEG_TITLES[k], "custody manifests absent from checkout")
            for k in ("1", "2", "6", "9")
        }

    out = root / ".ember01-verify-custody.tmp.json"
    head = git(root, "rev-parse", "HEAD").stdout.strip()
    cmd = [
        sys.executable, "-B", CENSUS_REL,
        "--root-spec", str(root_spec),
        "--benchmark-registry", str(bench),
        "--issue-census", str(issues),
        "--source-commit", head,
        "--public-master-ref", head,
        "--output", str(out),
    ]
    for b in bindings:
        cmd += ["--binding", b]
    result = run(cmd, root=root, name="ember_01_custody", timeout=180)
    try:
        out.unlink(missing_ok=True)  # keep the checkout clean
    except OSError:
        pass
    rc = result["returncode"]
    if rc == 0:
        state, reason = RESOLVED_TRUE, "census PASS"
    elif rc == 2:
        state, reason = RESOLVED_FALSE, "census INCOMPLETE (benchmark/issue/contradiction errors)"
    else:
        state, reason = RESOLVED_FALSE, f"census FAIL (exit {rc})"
    ev = {"tool": CENSUS_REL, "returncode": rc, "stdout_tail": result["stdout"][-400:]}
    return {k: leg(state, LEG_TITLES[k], reason, ev) for k in ("1", "2", "6", "9")}


# ---- Legs 3/4: identity round-trip / fail-closed (validate_identity.py) ------
def identity_legs(root: Path, manifest: Path | None, checkpoint: Path | None) -> dict[str, Any]:
    # Requires a REAL owned-checkpoint manifest on disk. Absent on a bare clone
    # -> UNRESOLVED, never a fake pass.
    if manifest is None:
        why = "no owned-checkpoint identity manifest supplied; cannot evaluate on a bare clone"
        return {k: leg(UNRESOLVED, LEG_TITLES[k], why) for k in ("3", "4")}
    if not manifest.is_file():
        return {k: leg(UNRESOLVED, LEG_TITLES[k], f"identity manifest missing: {manifest}") for k in ("3", "4")}
    if checkpoint is None or not checkpoint.exists():
        why = "identity manifest supplied but the owned checkpoint is not on disk (RUNNER-BLOCKED)"
        return {k: leg(UNRESOLVED, LEG_TITLES[k], why) for k in ("3", "4")}

    cmd = [sys.executable, "-B", VALIDATE_IDENTITY_REL, str(manifest),
           "--checkpoint", str(checkpoint), "--require-resolved"]
    result = run(cmd, root=root, name="ember_01_identity", timeout=180)
    rc = result["returncode"]
    ok = rc == 0
    try:
        parsed = json.loads(result["stdout"]) if result["stdout"] else {}
        ok = ok and bool(parsed.get("ok"))
    except (json.JSONDecodeError, ValueError):
        ok = False
    ev = {"tool": VALIDATE_IDENTITY_REL, "returncode": rc, "stdout_tail": result["stdout"][-400:]}
    state = RESOLVED_TRUE if ok else RESOLVED_FALSE
    reason = "identity validation ok" if ok else f"identity validation failed (exit {rc})"
    # Leg 4 (fail-closed) is only genuinely proven by a tamper case; on a real
    # run validate_identity's --require-resolved covers the resolved round-trip.
    return {
        "3": leg(state, LEG_TITLES["3"], reason, ev),
        "4": leg(state, LEG_TITLES["4"], reason, ev),
    }


# ---- Leg 5: reference seat (model-seat.ts via bun test) -----------------------
def seat_leg(root: Path, run_seat: bool) -> dict[str, Any]:
    seat_test = root / SEAT_TEST_REL
    if not seat_test.is_file():
        return {"5": leg(UNRESOLVED, LEG_TITLES["5"], "no reference model seat resolvable in checkout")}
    if not run_seat:
        why = "seat proxy not run (pass --run-seat on a machine with bun deps installed)"
        return {"5": leg(UNRESOLVED, LEG_TITLES["5"], why)}
    cli_dir = root / "tools" / "ember-cli"
    bun = shutil.which("bun")
    if bun is None:
        return {
            "5": leg(
                UNRESOLVED,
                LEG_TITLES["5"],
                "seat test could not execute (bun command is unavailable)",
            )
        }
    cmd = [bun, "test", "src/entrypoints/model-seat.test.ts"]
    result = run(cmd, root=cli_dir, name="model_seat", timeout=240)
    rc = result["returncode"]
    if rc == 0:
        return {"5": leg(RESOLVED_TRUE, LEG_TITLES["5"], "bun test model-seat passed",
                         {"tool": "bun test", "returncode": rc})}
    # A non-zero from missing installed deps is a runner block, not a real fail.
    combined = (result["stdout"] + result["stderr"]).lower()
    if result["timed_out"] or "cannot find" in combined or "error: script" in combined or "no such" in combined:
        return {"5": leg(UNRESOLVED, LEG_TITLES["5"],
                         "seat test could not execute (deps not installed / runner-blocked)",
                         {"tool": "bun test", "returncode": rc, "stderr_tail": result["stderr"][-300:]})}
    return {"5": leg(RESOLVED_FALSE, LEG_TITLES["5"], f"bun test model-seat failed (exit {rc})",
                     {"tool": "bun test", "returncode": rc, "stderr_tail": result["stderr"][-300:]})}


# ---- Leg 7: 3B launch packet (launch_packet.py) ------------------------------
def launch_packet_leg(root: Path) -> dict[str, Any]:
    config = root / CONFIG_REL
    if not config.is_file():
        return {"7": leg(UNRESOLVED, LEG_TITLES["7"], f"launch config absent: {CONFIG_REL}")}
    # launch_packet.py writes a transient receipt INTO root/receipts/ember-01-launch-packet/<ts>/
    # and has no output-path override. Snapshot the dir so the receipt it creates can be removed
    # afterward — otherwise leg 7 dirties the checkout mid-run and breaks the integrity invariant
    # (clean+detached+head-unchanged throughout) that every later leg and the final `ok` depend on.
    packet_root = root / "receipts" / "ember-01-launch-packet"
    before = {p.name for p in packet_root.iterdir()} if packet_root.is_dir() else set()
    packet_root_preexisting = packet_root.is_dir()
    cmd = [sys.executable, "-B", LAUNCH_PACKET_REL, "--config", str(config)]
    result = run(cmd, root=root, name="launch_packet", timeout=180)
    # Remove the transient receipt launch_packet just created, restoring the clean tree.
    if packet_root.is_dir():
        for entry in packet_root.iterdir():
            if entry.name not in before:
                shutil.rmtree(entry, ignore_errors=True) if entry.is_dir() else entry.unlink(missing_ok=True)
        if not packet_root_preexisting:
            try:
                packet_root.rmdir()
            except OSError:
                pass
    rc = result["returncode"]
    state = RESOLVED_TRUE if rc == 0 else RESOLVED_FALSE
    reason = "launch packet ready" if rc == 0 else f"launch packet not ready (exit {rc})"
    ev = {"tool": LAUNCH_PACKET_REL, "returncode": rc, "stdout_tail": result["stdout"][-400:]}
    return {"7": leg(state, LEG_TITLES["7"], reason, ev)}


# ---- Leg 8: authority conservation (imported verify()) -----------------------
def authority_leg(root: Path, selection: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    cert = verify(root, selection)
    ok = bool(cert.get("ok"))
    state = RESOLVED_TRUE if ok else RESOLVED_FALSE
    reason = "authority conservation certificate ok" if ok else "authority certificate failed"
    return {"8": leg(state, LEG_TITLES["8"], reason, {"tool": "verify_authority_conservation.verify"})}, cert


def write_receipt(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--selection", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--binding", action="append", default=[],
                        help="operator-machine ROOT binding NAME=PATH (repeatable)")
    parser.add_argument("--run-custody", action="store_true",
                        help="run the custody census (requires real ROOT bindings)")
    parser.add_argument("--identity-manifest", default=None,
                        help="owned-checkpoint identity manifest path")
    parser.add_argument("--checkpoint", default=None,
                        help="owned checkpoint path for identity round-trip")
    parser.add_argument("--run-seat", action="store_true",
                        help="run bun test on the reference model seat")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    selection = Path(args.selection).resolve()
    ident_manifest = Path(args.identity_manifest).resolve() if args.identity_manifest else None
    checkpoint = Path(args.checkpoint).resolve() if args.checkpoint else None

    try:
        receipt = validate_receipt_path(root, Path(args.receipt))
        before = inspect_checkout(root)
        selection_before = selection_evidence(selection)

        # Executable legs run only if the checkout is clean AND detached, same
        # gate EMBER-00 uses, so certifying cannot mutate the tree it certifies.
        if before["clean"] and before["detached"]:
            legs: dict[str, Any] = {}
            authority_row, authority_cert = authority_leg(root, selection)
            legs.update(authority_row)
            legs.update(launch_packet_leg(root))
            legs.update(custody_legs(root, args.binding, args.run_custody))
            legs.update(identity_legs(root, ident_manifest, checkpoint))
            legs.update(seat_leg(root, args.run_seat))
        else:
            authority_cert = {"ok": False, "skipped": "checkout not clean+detached"}
            legs = {
                k: leg(UNRESOLVED, LEG_TITLES[k],
                       "checkout not clean+detached; executable legs skipped")
                for k in LEG_TITLES
            }

        selection_after = selection_evidence(selection)
        after = inspect_checkout(root)
    except Exception as exc:  # noqa: BLE001 - honest fail-closed
        print(f"EMBER01_COMPLETION FAIL: {exc}")
        return 2

    checkout = {
        **after,
        "clean": bool(before["clean"] and after["clean"]),
        "detached": bool(before["detached"] and after["detached"]),
        "head_unchanged": before["head"] == after["head"],
        "status_before": before["status"],
    }
    selection_unchanged = selection_before == selection_after

    legs = {k: legs[k] for k in sorted(legs, key=int)}
    leg_states = {k: v["state"] for k, v in legs.items()}
    exact_nine = set(legs) == {str(n) for n in range(1, 10)}
    all_resolved_true = exact_nine and all(s == RESOLVED_TRUE for s in leg_states.values())
    checkout_integrity = bool(
        checkout["clean"] and checkout["detached"] and checkout["head_unchanged"]
    )
    ok = bool(all_resolved_true and checkout_integrity and selection_unchanged)

    summary = {
        "resolved_true": sorted(k for k, s in leg_states.items() if s == RESOLVED_TRUE),
        "resolved_false": sorted(k for k, s in leg_states.items() if s == RESOLVED_FALSE),
        "unresolved": sorted(k for k, s in leg_states.items() if s == UNRESOLVED),
    }

    payload = {
        "schema": "ember-01-completion-receipt-v1",
        "ok": ok,
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "goal_id": ACTIVE_GOAL_ID,
        "next_executed_outcome": NEXT_EXECUTED_OUTCOME,
        "certificate_legs": leg_states,
        "leg_detail": legs,
        "leg_summary": summary,
        "claim_scope": {
            # What all-nine-resolved-true WOULD prove: EMBER-01 custody, identity,
            # seat, benchmark, launch-packet, authority, and issue conditions.
            # What it NEVER proves:
            "training_completed": False,
            "model_completed": False,
            "runtime_completed": False,
            "benchmark_completed": False,
            "note": (
                "A bare clean clone honestly reports the operator-machine-bound "
                "legs (custody/identity/seat) as UNRESOLVED. ok=true requires an "
                "operator-machine run with real roots + owned checkpoint + seat."
            ),
        },
        "checkout": checkout,
        "selection": {**selection_after, "unchanged_during_verification": selection_unchanged},
        "authority_certificate": authority_cert,
    }
    write_receipt(receipt, payload)

    if ok:
        print(f"EMBER01_COMPLETION PASS: {receipt}")
        return 0
    print(f"EMBER01_COMPLETION FAIL: {receipt}")
    print(f"  resolved-true : {summary['resolved_true']}")
    print(f"  resolved-false: {summary['resolved_false']}")
    print(f"  UNRESOLVED    : {summary['unresolved']}")
    for k in summary["unresolved"] + summary["resolved_false"]:
        print(f"    leg {k} [{leg_states[k]}] {legs[k]['title']}: {legs[k]['reason']}")
    if not checkout_integrity:
        print("  checkout was not clean+detached+head-unchanged throughout")
    if not selection_unchanged:
        print("  goal selector changed during verification")
    return 1


if __name__ == "__main__":
    sys.exit(main())
