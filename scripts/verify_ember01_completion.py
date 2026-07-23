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
import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

# Leg 8 imports the SAME authority function verify_ember00_completion.py uses.
from verify_authority_conservation import (
    ACTIVE_GOAL_ID,
    NEXT_EXECUTED_OUTCOME,
    verify,
)
from ember_01_identity import validate_identity as identity_validator
from ember_01_identity.parameter_identity_binding import (
    ParameterIdentityMismatch,
    measure_live_checkpoint,
    verify_parameter_identity_binding,
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
    "3": "identity round-trip on real checkpoint",
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
def custody_legs(
    root: Path,
    bindings: list[str],
    run_custody: bool,
    issue_census: Path | None = None,
) -> dict[str, Any]:
    manifests = root / "manifests" / "ember-01-custody"
    root_spec = manifests / "root-spec.json"
    bench = manifests / "benchmark-registry.json"
    # The live issue census cannot be content-bound to the commit that contains
    # it: merging a tracked refresh necessarily creates a successor commit.
    # Accept an explicit, externally generated census so census.py can enforce
    # its existing exact-current-master check without a self-referential file.
    issues = issue_census or manifests / "public-issue-census.json"
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

    try:
        issue_census_sha_before = hashlib.sha256(issues.read_bytes()).hexdigest()
    except OSError as error:
        evidence = {
            "tool": CENSUS_REL,
            "error_type": type(error).__name__,
            "error": str(error)[-400:],
        }
        return {
            k: leg(
                RESOLVED_FALSE,
                LEG_TITLES[k],
                "issue census unreadable before custody run",
                evidence,
            )
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
        "--public-master-ref", "refs/remotes/origin/master",
        "--output", str(out),
    ]
    for b in bindings:
        cmd += ["--binding", b]
    result = run(cmd, root=root, name="ember_01_custody")
    try:
        out.unlink(missing_ok=True)  # keep the checkout clean
    except OSError:
        pass
    try:
        issue_census_sha_after = hashlib.sha256(issues.read_bytes()).hexdigest()
    except OSError:
        issue_census_sha_after = None
    if issue_census_sha_after != issue_census_sha_before:
        evidence = {
            "tool": CENSUS_REL,
            "issue_census_sha256_before": issue_census_sha_before,
            "issue_census_sha256_after": issue_census_sha_after,
        }
        return {
            k: leg(
                RESOLVED_FALSE,
                LEG_TITLES[k],
                "issue census changed during custody run",
                evidence,
            )
            for k in ("1", "2", "6", "9")
        }
    rc = result["returncode"]
    if rc == 0:
        state, reason = RESOLVED_TRUE, "census PASS"
    elif rc == 2:
        state, reason = RESOLVED_FALSE, "census INCOMPLETE (benchmark/issue/contradiction errors)"
    else:
        state, reason = RESOLVED_FALSE, f"census FAIL (exit {rc})"
    ev = {
        "tool": CENSUS_REL,
        "returncode": rc,
        "stdout_tail": result["stdout"][-400:],
        "issue_census_sha256": issue_census_sha_before,
    }
    return {k: leg(state, LEG_TITLES[k], reason, ev) for k in ("1", "2", "6", "9")}


# ---- Legs 3/4: identity round-trip / fail-closed (validate_identity.py) ------
def _checkpoint_shard_rows(checkpoint_payload: Any) -> list[dict[str, Any]]:
    if not isinstance(checkpoint_payload, dict):
        raise ValueError("checkpoint manifest must be an object")
    shards = checkpoint_payload.get("shards")
    if not isinstance(shards, list) or not shards:
        raise ValueError("checkpoint manifest must contain shard records")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in shards:
        if not isinstance(record, dict):
            raise ValueError("checkpoint shard record must be an object")
        path = record.get("path")
        size = record.get("bytes")
        digest = record.get("sha256")
        if (
            not isinstance(path, str)
            or not path
            or Path(path).is_absolute()
            or ".." in Path(path).parts
            or path in seen
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("checkpoint shard record is not closed and content-addressed")
        seen.add(path)
        rows.append(
            {
                "name": path,
                "shape": [size],
                "dtype": "ember-checkpoint-shard-v1",
                "sha256": digest,
            }
        )
    return rows


def _flipped_sha256(value: Any) -> str:
    return "1" * 64 if value == "0" * 64 else "0" * 64


def _identity_tamper_mutants(
    payload: dict[str, Any],
) -> list[tuple[str, dict[str, Any], str]]:
    mutants: list[tuple[str, dict[str, Any], str]] = []

    parameter = copy.deepcopy(payload)
    parameter["parameters"]["allocated"] += 1
    mutants.append(
        ("param_count", parameter, "binding.parameters_mismatch")
    )

    tokenizer = copy.deepcopy(payload)
    tokenizer["tokenizer"]["sha256"] = _flipped_sha256(
        tokenizer["tokenizer"].get("sha256")
    )
    mutants.append(
        ("tokenizer", tokenizer, "binding.tokenizer_mismatch")
    )

    learned_signal = copy.deepcopy(payload)
    sources = learned_signal["provenance"]["learned_signal_sources"]
    if "hidden_external_cognition" not in sources:
        sources.append("hidden_external_cognition")
    else:
        sources.append("borrowed_stopping_decision")
    mutants.append(
        (
            "data_learned_signal",
            learned_signal,
            "provenance.forbidden_learned_signal",
        )
    )

    mechanism = copy.deepcopy(payload)
    routers = mechanism["mechanisms"]["router"]
    if not routers or not isinstance(routers[0], dict):
        raise ValueError("real identity manifest has no concrete router to tamper")
    routers[0]["sha256"] = _flipped_sha256(routers[0].get("sha256"))
    mutants.append(
        ("mechanism", mechanism, "binding.mechanisms_mismatch")
    )

    backend = copy.deepcopy(payload)
    backend["backend"]["executable_sha256"] = _flipped_sha256(
        backend["backend"].get("executable_sha256")
    )
    mutants.append(
        ("backend", backend, "binding.backend_mismatch")
    )

    benchmark = copy.deepcopy(payload)
    benchmark["evaluation"]["benchmark_id"] = (
        "ember-cond4-unregistered-benchmark"
    )
    mutants.append(
        (
            "benchmark_id",
            benchmark,
            "binding.evaluation.benchmark_id_mismatch",
        )
    )

    comparator = copy.deepcopy(payload)
    comparator["evaluation"]["comparator_identity"] = (
        "ember-cond4-foreign-comparator"
    )
    mutants.append(
        (
            "comparator",
            comparator,
            "binding.evaluation.comparator_identity_mismatch",
        )
    )
    return mutants


def _run_identity_tamper_battery(
    *,
    root: Path,
    payload: dict[str, Any],
    receipt: dict[str, Any],
    checkpoint_bytes: bytes,
    model_config: Path,
    scratch_root: Path,
) -> dict[str, Any]:
    """Execute cond4's eight isolated fail-closed probes.

    The checkpoint-bytes axis goes through the real parameter-identity verifier.
    The other seven axes go through the shipping validate_identity.py CLI with
    the clean identity as its expected binding. A rejection counts only when
    the process is non-zero, emits ``ok:false``, and includes the axis's bound
    finding code.
    """
    scratch_root.mkdir(parents=True, exist_ok=True)
    evidence: dict[str, Any] = {}
    created: list[Path] = []
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".ember01-cond4-checkpoint-bytes-",
            suffix=".json",
            dir=scratch_root,
            delete=False,
        ) as handle:
            handle.write(checkpoint_bytes + b"\n")
            checkpoint_tamper = Path(handle.name)
            created.append(checkpoint_tamper)
        try:
            verify_parameter_identity_binding(
                payload,
                receipt,
                checkpoint_manifest=checkpoint_tamper,
                model_config=model_config,
            )
        except ParameterIdentityMismatch as error:
            evidence["checkpoint_bytes"] = {
                "rejected": True,
                "finding": "parameter_identity_mismatch",
                "detail": str(error)[-400:],
            }
        else:
            evidence["checkpoint_bytes"] = {
                "rejected": False,
                "finding": None,
                "detail": "tampered checkpoint manifest was accepted",
            }

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=".ember01-cond4-expected-",
            suffix=".json",
            dir=scratch_root,
            delete=False,
        ) as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            expected_path = Path(handle.name)
            created.append(expected_path)

        for axis, mutant, expected_code in _identity_tamper_mutants(payload):
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".ember01-cond4-{axis}-",
                suffix=".json",
                dir=scratch_root,
                delete=False,
            ) as handle:
                json.dump(mutant, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                mutant_path = Path(handle.name)
                created.append(mutant_path)
            result = run(
                [
                    sys.executable,
                    "-B",
                    VALIDATE_IDENTITY_REL,
                    str(mutant_path),
                    "--expected",
                    str(expected_path),
                ],
                root=root,
                name=f"cond4_{axis}",
                timeout=180,
            )
            try:
                parsed = json.loads(result["stdout"])
            except (json.JSONDecodeError, TypeError):
                parsed = {}
            findings = parsed.get("findings")
            finding_codes = sorted(
                {
                    row.get("code")
                    for row in findings
                    if isinstance(row, dict) and isinstance(row.get("code"), str)
                }
            ) if isinstance(findings, list) else []
            rejected = (
                result["returncode"] != 0
                and parsed.get("ok") is False
                and expected_code in finding_codes
            )
            evidence[axis] = {
                "rejected": rejected,
                "expected_finding": expected_code,
                "finding_codes": finding_codes,
                "returncode": result["returncode"],
                "timed_out": result["timed_out"],
            }
    finally:
        for path in reversed(created):
            path.unlink(missing_ok=True)

    failures = [
        axis
        for axis, row in evidence.items()
        if not isinstance(row, dict) or row.get("rejected") is not True
    ]
    return {
        "tool": "scripts/verify_ember01_completion.py::cond4_tamper_battery",
        "axis_count": 8,
        "axes": evidence,
        "failures": failures,
        "all_rejected": not failures and len(evidence) == 8,
    }


def identity_legs(
    root: Path,
    manifest: Path | None,
    checkpoint_manifest: Path | None,
    model_config: Path | None,
    scratch_root: Path,
) -> dict[str, Any]:
    # Requires a real checkpoint manifest on disk. Absent on a bare clone
    # -> UNRESOLVED, never a fake pass.
    if manifest is None:
        why = "no real-checkpoint identity manifest supplied; cannot evaluate on a bare clone"
        return {k: leg(UNRESOLVED, LEG_TITLES[k], why) for k in ("3", "4")}
    if not manifest.is_file():
        return {k: leg(UNRESOLVED, LEG_TITLES[k], f"identity manifest missing: {manifest}") for k in ("3", "4")}
    if checkpoint_manifest is None or not checkpoint_manifest.is_file():
        why = "identity manifest supplied but the checkpoint manifest is not on disk (RUNNER-BLOCKED)"
        return {k: leg(UNRESOLVED, LEG_TITLES[k], why) for k in ("3", "4")}
    if model_config is None or not model_config.is_file():
        why = "identity manifest supplied but the exact model config is not on disk (RUNNER-BLOCKED)"
        return {k: leg(UNRESOLVED, LEG_TITLES[k], why) for k in ("3", "4")}

    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        checkpoint_bytes = checkpoint_manifest.read_bytes()
        checkpoint_payload = json.loads(checkpoint_bytes.decode("utf-8"))
        identity_validator.validate_manifest(payload)
        expected_rows = _checkpoint_shard_rows(checkpoint_payload)
        checkpoint_identity = payload.get("checkpoint")
        if not isinstance(checkpoint_identity, dict):
            raise ValueError("identity manifest lacks checkpoint identity")
        if checkpoint_identity.get("format") != checkpoint_payload.get("schema_version"):
            raise ValueError("identity checkpoint format does not match the real checkpoint manifest")
        if checkpoint_identity.get("tensors") != expected_rows:
            raise ValueError("identity checkpoint shard rows do not match the real checkpoint manifest")
        receipt = measure_live_checkpoint(
            model_config=model_config,
            checkpoint_manifest=checkpoint_manifest,
            active_expert="shared",
        )
        verify_parameter_identity_binding(
            payload,
            receipt,
            checkpoint_manifest=checkpoint_manifest,
            model_config=model_config,
        )
    except Exception as error:  # noqa: BLE001 - completion must fail closed
        evidence = {
            "tool": "scripts/ember_01_identity/parameter_identity_binding.py",
            "error_type": type(error).__name__,
            "error": str(error)[-400:],
        }
        return {
            "3": leg(RESOLVED_FALSE, LEG_TITLES["3"], "real checkpoint identity failed", evidence),
            "4": leg(RESOLVED_FALSE, LEG_TITLES["4"], "tamper proof unavailable because clean round-trip failed", evidence),
        }

    receipt_sha = hashlib.sha256(
        json.dumps(
            receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    clean_evidence = {
        "tool": "scripts/ember_01_identity/parameter_identity_binding.py",
        "checkpoint_sha256": receipt["subject_checkpoint_sha256"],
        "parameter_receipt_sha256": receipt_sha,
        "disposition": payload["identity"]["disposition"],
        "ownership": payload["provenance"]["ownership"],
    }

    try:
        tamper_evidence = _run_identity_tamper_battery(
            root=root,
            payload=payload,
            receipt=receipt,
            checkpoint_bytes=checkpoint_bytes,
            model_config=model_config,
            scratch_root=scratch_root,
        )
    except Exception as error:  # noqa: BLE001 - battery itself fails closed
        tamper_evidence = {
            "tool": "scripts/verify_ember01_completion.py::cond4_tamper_battery",
            "axis_count": 8,
            "axes": {},
            "failures": ["battery_execution"],
            "all_rejected": False,
            "error_type": type(error).__name__,
            "error": str(error)[-400:],
        }
    tamper_rejected = tamper_evidence["all_rejected"] is True
    return {
        "3": leg(RESOLVED_TRUE, LEG_TITLES["3"], "real checkpoint identity re-derived", clean_evidence),
        "4": leg(
            RESOLVED_TRUE if tamper_rejected else RESOLVED_FALSE,
            LEG_TITLES["4"],
            "all eight isolated identity tamper axes rejected"
            if tamper_rejected
            else "one or more isolated identity tamper axes failed open",
            tamper_evidence,
        ),
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
    parser.add_argument(
        "--issue-census",
        default=None,
        help=(
            "live public-issue census generated outside the verified checkout; "
            "defaults to the checked-in historical freeze"
        ),
    )
    parser.add_argument("--identity-manifest", default=None,
                        help="owned-checkpoint identity manifest path")
    parser.add_argument("--checkpoint-manifest", "--checkpoint", dest="checkpoint_manifest", default=None,
                        help="real sharded checkpoint-manifest.json for identity round-trip")
    parser.add_argument("--model-config", default=None,
                        help="exact model config bound by the checkpoint manifest")
    parser.add_argument("--run-seat", action="store_true",
                        help="run bun test on the reference model seat")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    selection = Path(args.selection).resolve()
    ident_manifest = Path(args.identity_manifest).resolve() if args.identity_manifest else None
    checkpoint_manifest = Path(args.checkpoint_manifest).resolve() if args.checkpoint_manifest else None
    model_config = Path(args.model_config).resolve() if args.model_config else None
    issue_census = Path(args.issue_census).resolve() if args.issue_census else None

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
            legs.update(
                custody_legs(
                    root,
                    args.binding,
                    args.run_custody,
                    issue_census=issue_census,
                )
            )
            legs.update(
                identity_legs(
                    root,
                    ident_manifest,
                    checkpoint_manifest,
                    model_config,
                    receipt.parent,
                )
            )
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
