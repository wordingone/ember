#!/usr/bin/env python
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Run-attempt registry producer (issue #1497).

Writes the repo-level append-only registry `receipts/run-attempts.jsonl`
that R1-E5 "failed work included" adjudication binds (prereg 5.4 leg 1,
5.1 class 7). Consumer contract (PR #1500, scripts/r1_exit_battery.py
E5 leg + scripts/frontier_receipt.py ledger_all_compute_coverage):

- path: receipts/run-attempts.jsonl, resolved against the REPO ROOT
  (not the run root; run-root evidence discovery excludes attempt-*/
  and .checkpoint-quarantine/ and never finds a registry there);
- every non-empty line MUST parse as a JSON OBJECT (a scalar line is
  not an attempt record -- rev-1490 item 4);
- at least one row must NAME the adjudicated run: the consumer does a
  field-name-agnostic recursive scan of each row's string values for
  the telemetry run_id, the run-root directory name, or the
  checkpoint-manifest sha256. Every row here therefore carries
  run_root_name explicitly, plus a non-empty stable run_id and attempt_id.

Two repo laws are enforced AT WRITE TIME (a limit is real only when it
is always enforced where the bytes are made, not in a later gate):

- authority binding: every row carries goal_id / workstream_id /
  next_executed_outcome exactly as GOAL.md declares them (leg 4 of
  verify_authority_conservation.py binds .jsonl artifacts row-wise);
- no absolute local filesystem paths in any row string (repo-guard
  [paths]): run roots are recorded as the portable
  "<custody-dir-name>:<root-name>" ref plus run_root_name, never as
  drive-letter paths. The issue's original `run_root` field is
  superseded by run_root_ref for exactly this law.

Modes
  append    one row for a live launch/exit boundary (certified launch
            chain: spawn leg outcome=running end_utc=null, exit leg
            outcome=completed|failed|aborted|killed). --fail-safe makes
            any defect non-fatal to the caller (#1489: a registry write
            failure must never kill the run) while still printing it.
  backfill  derive rows for an existing run root from what is on disk:
            telemetry train_step run_ids, checkpoint manifest, runner
            receipt, retained attempt-*/ dirs (failed attempts get rows
            too). Idempotent: re-running skips rows whose identity
            (run_id, attempt_id, source_receipt, outcome) already
            exists. Each row cites its source evidence.
  selftest  build a synthetic run root, backfill it, and check the
            produced file against a local copy of the consumer's rules
            (object rows + naming scan), plus negative cases.

Fail-closed: any defect exits nonzero (except under --fail-safe).
Append-only: this producer never rewrites or truncates the registry;
pre-existing corrupt lines are reported as defects, not repaired.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "run-attempt-registry/v1"
REGISTRY_REL = "receipts/run-attempts.jsonl"
REPO_ROOT = Path(__file__).resolve().parents[1]
OUTCOMES = ("running", "completed", "failed", "aborted", "killed")
TELEMETRY_SOURCE = "ember-restart-3b"
# Authority binding (verified against GOAL.md by the trusted kernel; a
# drifted copy fails the guard, which is the enforcement).
GOAL_ID = "EMBER-02"
# GOAL.md workstream_path_scopes: scripts/ and receipts/ (non-restart-3b
# prefixes) are EMBER-02A territory; only tools/ember-restart-3b/ is 02B.
WORKSTREAM_ID = "EMBER-02A"
NEXT_EXECUTED_OUTCOME = (
    "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
)
_ABS_LOCAL_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|/|\\\\)")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
ROW_FIELDS = frozenset(
    {
        "schema",
        "goal_id",
        "workstream_id",
        "next_executed_outcome",
        "run_id",
        "attempt_id",
        "run_root_ref",
        "run_root_name",
        "outcome",
        "outcome_basis",
        "start_utc",
        "end_utc",
        "checkpoint_manifest_sha256",
        "launch_receipt_ref",
        "source_receipt",
        "backfill",
        "recorded_utc",
        "producer",
        "issue",
    }
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _utc_from_mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _nonempty_str(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _row_strings(value: Any):
    """Mirror of the consumer's field-name-agnostic string walk."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _row_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _row_strings(v)


def validate_row(row: Any) -> list[str]:
    defects: list[str] = []
    if not isinstance(row, dict):
        return [f"row is not a JSON object: {row!r}"]
    missing = sorted(ROW_FIELDS - row.keys())
    unknown = sorted(row.keys() - ROW_FIELDS)
    if missing:
        defects.append(f"missing fields: {missing}")
    if unknown:
        defects.append(f"unknown fields: {unknown}")
    if row.get("schema") != SCHEMA:
        defects.append(f"schema must be {SCHEMA!r}, got {row.get('schema')!r}")
    if row.get("goal_id") != GOAL_ID:
        defects.append(f"goal_id must be {GOAL_ID!r} (authority leg 4)")
    if row.get("workstream_id") != WORKSTREAM_ID:
        defects.append(f"workstream_id must be {WORKSTREAM_ID!r} (authority leg 4)")
    if row.get("next_executed_outcome") != NEXT_EXECUTED_OUTCOME:
        defects.append("next_executed_outcome drifted from GOAL.md's declared outcome")
    if row.get("outcome") not in OUTCOMES:
        defects.append(f"outcome {row.get('outcome')!r} not in {OUTCOMES}")
    if not _nonempty_str(row.get("run_root_ref")):
        defects.append("run_root_ref missing/empty")
    if not _nonempty_str(row.get("run_root_name")):
        defects.append("run_root_name missing/empty (the consumer's naming scan needs it)")
    elif _nonempty_str(row.get("run_root_ref")):
        root_ref = row["run_root_ref"]
        prefix, separator, root_name = root_ref.partition(":")
        if not separator or not prefix or root_name != row["run_root_name"]:
            defects.append(
                "run_root_ref must be '<custody>:<run_root_name>' and bind the exact root name"
            )
    if not _nonempty_str(row.get("launch_receipt_ref")):
        defects.append("launch_receipt_ref missing/empty")
    if not _nonempty_str(row.get("source_receipt")):
        defects.append("source_receipt missing/empty")
    if not _nonempty_str(row.get("outcome_basis")):
        defects.append("outcome_basis missing/empty")
    if not _nonempty_str(row.get("recorded_utc")):
        defects.append("recorded_utc missing/empty")
    if row.get("producer") != "scripts/run_attempt_registry.py":
        defects.append("producer must name the canonical run-attempt registry producer")
    if row.get("issue") != "#1497":
        defects.append("issue must be '#1497'")
    if not isinstance(row.get("backfill"), bool):
        defects.append("backfill must be boolean")
    attempt_id = row.get("attempt_id")
    if not _nonempty_str(attempt_id):
        defects.append("attempt_id must be a non-empty stable attempt identity")
    checkpoint_sha = row.get("checkpoint_manifest_sha256")
    if checkpoint_sha is not None and (
        not isinstance(checkpoint_sha, str) or _SHA256.fullmatch(checkpoint_sha) is None
    ):
        defects.append("checkpoint_manifest_sha256 must be lowercase SHA-256 or null")
    for value in _row_strings(row):
        if _ABS_LOCAL_PATH.match(value):
            defects.append(
                f"absolute local path in row value (repo [paths] law): {value[:80]!r}"
            )
    if not _nonempty_str(row.get("start_utc")):
        defects.append("start_utc missing/empty")
    if row.get("outcome") == "running":
        if row.get("end_utc") is not None:
            defects.append("end_utc must be null while outcome=running")
    elif row.get("outcome") in OUTCOMES and not _nonempty_str(row.get("end_utc")):
        defects.append(f"end_utc required for outcome={row.get('outcome')!r}")
    run_id = row.get("run_id")
    if not _nonempty_str(run_id):
        defects.append("run_id must be a non-empty stable run identity")
    try:
        line = json.dumps(row, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as e:
        defects.append(f"row not JSON-serializable: {e}")
    else:
        if "\n" in line or "\r" in line:
            defects.append("serialized row contains a newline")
    return defects


def build_row(
    *,
    run_root: Path,
    outcome: str,
    run_id: str | None,
    attempt_id: str | None,
    start_utc: str,
    end_utc: str | None,
    checkpoint_manifest_sha256: str | None,
    launch_receipt_ref: str | None,
    source_receipt: str | None,
    outcome_basis: str | None,
    backfill: bool,
) -> dict[str, Any]:
    resolved = run_root.resolve()
    return {
        "schema": SCHEMA,
        "goal_id": GOAL_ID,
        "workstream_id": WORKSTREAM_ID,
        "next_executed_outcome": NEXT_EXECUTED_OUTCOME,
        "run_id": run_id,
        "attempt_id": attempt_id,
        "run_root_ref": f"{resolved.parent.name}:{resolved.name}",
        "run_root_name": resolved.name,
        "outcome": outcome,
        "outcome_basis": outcome_basis,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "checkpoint_manifest_sha256": checkpoint_manifest_sha256,
        "launch_receipt_ref": launch_receipt_ref,
        "source_receipt": source_receipt,
        "backfill": backfill,
        "recorded_utc": _utc_now(),
        "producer": "scripts/run_attempt_registry.py",
        "issue": "#1497",
    }


def _identity(row: dict[str, Any]) -> tuple:
    # The root ref is part of the identity: a resumed root shares its
    # predecessor's telemetry run_id and relative source paths, and without
    # the root in the tuple its backfill row dedupe-collides with a sibling
    # root's. Outcome remains part of the identity so a running spawn leg and
    # its terminal exit leg are distinct, while an exact leg cannot be counted
    # twice.
    return (
        row.get("run_root_ref"),
        row.get("run_id"),
        row.get("attempt_id"),
        row.get("source_receipt"),
        row.get("outcome"),
    )


def read_existing_rows(registry: Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Parse the registry as the consumer does. Corrupt lines are
    reported (never repaired -- append-only)."""
    rows: list[dict[str, Any]] = []
    defects: list[str] = []
    identity_lines: dict[tuple, int] = {}
    if not registry.is_file():
        return rows, defects
    for i, line in enumerate(registry.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as e:
            defects.append(f"pre-existing registry line {i + 1} unparseable: {e}")
            continue
        if not isinstance(row, dict):
            defects.append(f"pre-existing registry line {i + 1} is not a JSON object")
            continue
        row_defects = validate_row(row)
        defects.extend(
            f"pre-existing registry line {i + 1}: {defect}"
            for defect in row_defects
        )
        if not row_defects:
            identity = _identity(row)
            prior_line = identity_lines.get(identity)
            if prior_line is not None:
                defects.append(
                    f"pre-existing registry line {i + 1}: duplicate attempt identity "
                    f"already present on line {prior_line}"
                )
            else:
                identity_lines[identity] = i + 1
        rows.append(row)
    return rows, defects


def append_rows(registry: Path, new_rows: list[dict[str, Any]]) -> list[str]:
    """Validate then append rows (LF-terminated, compact JSON), then
    verify the appended tail round-trips. Never rewrites prior bytes."""
    existing, defects = read_existing_rows(registry)
    seen = {_identity(row) for row in existing}
    for index, row in enumerate(new_rows, start=1):
        row_defects = validate_row(row)
        defects.extend(row_defects)
        if row_defects:
            continue
        identity = _identity(row)
        if identity in seen:
            defects.append(
                f"new registry row {index}: duplicate attempt identity already present"
            )
        else:
            seen.add(identity)
    if defects:
        return defects
    registry.parent.mkdir(parents=True, exist_ok=True)
    payload = b"".join(
        json.dumps(r, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        for r in new_rows
    )
    with open(registry, "ab") as fh:
        fh.write(payload)
    tail = registry.read_bytes().splitlines()[-len(new_rows):]
    for want, got in zip(new_rows, tail):
        if json.loads(got.decode("utf-8")) != want:
            defects.append("post-append verification failed: tail bytes do not round-trip")
            break
    return defects

def _telemetry_run_ids(root: Path, *, exclude_attempt_dirs: bool) -> dict[str, list[Path]]:
    """Distinct train_step run_ids -> telemetry files, matching the
    consumer's shape: *.jsonl rows with kind=train_step and
    source=ember-restart-3b, run_id inside payload."""
    found: dict[str, list[Path]] = {}
    for p in sorted(root.rglob("*.jsonl")):
        rel_parts = p.relative_to(root).parts
        if ".checkpoint-quarantine" in rel_parts:
            continue
        if exclude_attempt_dirs and any(part.startswith("attempt-") for part in rel_parts):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("kind") != "train_step" or event.get("source") != TELEMETRY_SOURCE:
                continue
            payload = event.get("payload")
            rid = payload.get("run_id") if isinstance(payload, dict) else None
            if _nonempty_str(rid):
                found.setdefault(rid, [])
                if p not in found[rid]:
                    found[rid].append(p)
    return found


def _manifest_sha(run_root: Path) -> tuple[str | None, str | None]:
    ckpt = run_root / "artifacts" / "checkpoints"
    candidates = sorted(ckpt.glob("*/checkpoint-manifest.json")) if ckpt.is_dir() else []
    if not candidates:
        return None, None
    return _sha256_file(candidates[0]), candidates[0].relative_to(run_root).as_posix()


def cmd_append(args: argparse.Namespace) -> int:
    registry = Path(args.registry).resolve()
    run_root = Path(args.run_root)
    row = build_row(
        run_root=run_root,
        outcome=args.outcome,
        run_id=args.run_id,
        attempt_id=args.attempt_id,
        start_utc=args.start_utc or _utc_now(),
        end_utc=args.end_utc,
        checkpoint_manifest_sha256=args.checkpoint_manifest_sha,
        launch_receipt_ref=args.launch_receipt_ref,
        source_receipt=args.source_receipt,
        outcome_basis=args.outcome_basis,
        backfill=False,
    )
    _, pre_defects = read_existing_rows(registry)
    if pre_defects:
        for defect in pre_defects:
            print(f"DEFECT: {defect}", file=sys.stderr)
        return 1
    defects = append_rows(registry, [row])
    for d in pre_defects + defects:
        print(f"DEFECT: {d}", file=sys.stderr)
    if not defects:
        print(json.dumps({"appended": 1, "registry": registry.as_posix(),
                          "registry_sha256": _sha256_file(registry)}))
    return 1 if (defects or pre_defects) else 0


def cmd_backfill(args: argparse.Namespace) -> int:
    registry = Path(args.registry).resolve()
    run_root = Path(args.run_root).resolve()
    if not run_root.is_dir():
        print(f"DEFECT: run root does not exist: {run_root}", file=sys.stderr)
        return 2
    existing, pre_defects = read_existing_rows(registry)
    known = {_identity(r) for r in existing}
    manifest_sha, manifest_rel = _manifest_sha(run_root)
    runner_receipt = run_root / "disk-budget-runner-receipt.json"
    launch_ref = runner_receipt.relative_to(run_root).as_posix() if runner_receipt.is_file() else None

    new_rows: list[dict[str, Any]] = []

    # Primary attempt(s): one row per distinct telemetry run_id outside
    # retained attempt-*/ dirs.
    primary = _telemetry_run_ids(run_root, exclude_attempt_dirs=True)
    for rid, files in sorted(primary.items()):
        if manifest_sha is not None:
            outcome, basis = "completed", f"checkpoint manifest on disk: {manifest_rel}"
        else:
            outcome, basis = "aborted", "no checkpoint manifest under artifacts/checkpoints/"
        mtimes = sorted(_utc_from_mtime(f) for f in files)
        new_rows.append(build_row(
            run_root=run_root, outcome=outcome, run_id=rid, attempt_id="primary",
            start_utc=mtimes[0], end_utc=mtimes[-1],
            checkpoint_manifest_sha256=manifest_sha, launch_receipt_ref=launch_ref,
            source_receipt=files[0].relative_to(run_root).as_posix(),
            outcome_basis=basis, backfill=True,
        ))

    # Retained failed attempts: every attempt-*/ dir gets a row (prereg
    # 5.1 class 7: failed runs, aborted segments, restarts are charged).
    for attempt_dir in sorted(p for p in run_root.glob("attempt-*") if p.is_dir()):
        att_ids = _telemetry_run_ids(attempt_dir, exclude_attempt_dirs=False)
        rid = sorted(att_ids)[0] if att_ids else (
            sorted(primary)[0] if primary else run_root.name
        )
        new_rows.append(build_row(
            run_root=run_root, outcome="failed", run_id=rid,
            attempt_id=attempt_dir.name,
            start_utc=_utc_from_mtime(attempt_dir), end_utc=_utc_from_mtime(attempt_dir),
            checkpoint_manifest_sha256=manifest_sha, launch_receipt_ref=launch_ref,
            source_receipt=attempt_dir.relative_to(run_root).as_posix() + "/",
            outcome_basis=f"retained failed-attempt dir {attempt_dir.name}/",
            backfill=True,
        ))

    # Evidence floor: a root with a runner receipt or manifest but zero
    # telemetry still gets one row (the compute happened).
    if not new_rows and (launch_ref or manifest_sha):
        new_rows.append(build_row(
            run_root=run_root,
            outcome="completed" if manifest_sha else "aborted",
            run_id=run_root.name, attempt_id="evidence-floor",
            start_utc=_utc_from_mtime(run_root), end_utc=_utc_from_mtime(run_root),
            checkpoint_manifest_sha256=manifest_sha, launch_receipt_ref=launch_ref,
            source_receipt=launch_ref or manifest_rel,
            outcome_basis="no telemetry; row derived from receipt/manifest presence",
            backfill=True,
        ))

    fresh = [r for r in new_rows if _identity(r) not in known]
    skipped = len(new_rows) - len(fresh)
    if not new_rows:
        print(f"DEFECT: nothing derivable from {run_root} (no telemetry, "
              "no runner receipt, no checkpoint manifest)", file=sys.stderr)
        return 2
    defects = append_rows(registry, fresh) if fresh else []
    for d in pre_defects + defects:
        print(f"DEFECT: {d}", file=sys.stderr)
    if defects:
        return 1
    print(json.dumps({
        "appended": len(fresh), "skipped_existing": skipped,
        "registry": registry.as_posix(), "registry_sha256": _sha256_file(registry),
        "registry_rows": sum(1 for ln in registry.read_text(encoding="utf-8").splitlines() if ln.strip()),
    }))
    return 1 if pre_defects else 0


def cmd_selftest(args: argparse.Namespace) -> int:
    import tempfile

    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"{'PASS' if ok else 'FAIL'}: {name}" + (f" -- {detail}" if detail and not ok else ""))
        if not ok:
            failures.append(name)

    with tempfile.TemporaryDirectory(prefix="run-attempt-registry-selftest-") as td:
        tmp = Path(td)
        run_root = tmp / "runs" / "run-20260806-selftest"
        tele = run_root / "telemetry" / "train.jsonl"
        tele.parent.mkdir(parents=True)
        rid = "selftest-run-1"
        tele.write_text("".join(
            json.dumps({"kind": "train_step", "source": TELEMETRY_SOURCE,
                        "payload": {"run_id": rid, "step": i}}) + "\n"
            for i in range(1, 4)), encoding="utf-8")
        man = run_root / "artifacts" / "checkpoints" / "step-3" / "checkpoint-manifest.json"
        man.parent.mkdir(parents=True)
        man.write_text('{"steps": 3}\n', encoding="utf-8")
        (run_root / "disk-budget-runner-receipt.json").write_text('{"ok": true}\n', encoding="utf-8")
        att = run_root / "attempt-1" / "telemetry" / "train.jsonl"
        att.parent.mkdir(parents=True)
        att.write_text(json.dumps({"kind": "train_step", "source": TELEMETRY_SOURCE,
                                   "payload": {"run_id": rid, "step": 1}}) + "\n", encoding="utf-8")

        registry = tmp / "receipts" / "run-attempts.jsonl"
        ns = argparse.Namespace(registry=str(registry), run_root=str(run_root))
        rc = cmd_backfill(ns)
        check("backfill exits 0", rc == 0, f"rc={rc}")
        rows, defects = read_existing_rows(registry)
        check("registry parses with zero defects", not defects, str(defects))
        check("backfill produced primary + failed-attempt rows", len(rows) == 2, f"rows={len(rows)}")
        check("failed attempt has a row (5.1 class 7)",
              any(r.get("outcome") == "failed" and r.get("attempt_id") == "attempt-1" for r in rows))

        # Consumer naming scan: at least one row names the run by
        # run_id, run-root name, or manifest sha.
        tokens = {rid, run_root.name, _sha256_file(man)}
        check("naming scan hits (run_id/root-name/manifest-sha)",
              any(any(s in tokens for s in _row_strings(r)) for r in rows))

        rc = cmd_backfill(ns)
        rows2, _ = read_existing_rows(registry)
        check("backfill idempotent (re-run appends nothing)", rc == 0 and len(rows2) == 2,
              f"rc={rc} rows={len(rows2)}")

        # Resume shape: the SAME run_id under a DIFFERENT root, with every
        # other identity component identical (same rel source path, same
        # outcome via its own manifest), must still get its own row --
        # identity includes run_root_ref. Found live TWICE: the first fix
        # keyed on a field that was later renamed, and this case originally
        # differed by outcome, which masked the regression.
        run_root2 = tmp / "runs" / "run-20260806-selftest-resume"
        tele2 = run_root2 / "telemetry" / "train.jsonl"
        tele2.parent.mkdir(parents=True)
        tele2.write_text(json.dumps({"kind": "train_step", "source": TELEMETRY_SOURCE,
                                     "payload": {"run_id": rid, "step": 4}}) + "\n",
                         encoding="utf-8")
        man2 = run_root2 / "artifacts" / "checkpoints" / "step-4" / "checkpoint-manifest.json"
        man2.parent.mkdir(parents=True)
        man2.write_text('{"steps": 4}\n', encoding="utf-8")
        (run_root2 / "disk-budget-runner-receipt.json").write_text(
            '{"ok": true}\n', encoding="utf-8"
        )
        ns2 = argparse.Namespace(registry=str(registry), run_root=str(run_root2))
        rc = cmd_backfill(ns2)
        rows_resume, _ = read_existing_rows(registry)
        resume_rows = [r for r in rows_resume if r.get("run_root_name") == run_root2.name]
        check("same run_id under a different root still gets its own row (resume shape)",
              rc == 0 and len(rows_resume) == 3 and len(resume_rows) == 1
              and resume_rows[0].get("outcome") == "completed",
              f"rc={rc} rows={len(rows_resume)} resume_rows={len(resume_rows)}")

        ns_app = argparse.Namespace(
            registry=str(registry), run_root=str(run_root), outcome="running",
            run_id=rid, attempt_id="attempt-2", start_utc=None, end_utc=None,
            checkpoint_manifest_sha=None,
            launch_receipt_ref="disk-budget-runner-receipt.json",
            source_receipt="disk-budget-runner-receipt.json", outcome_basis="spawn leg")
        check("append spawn leg (running, end_utc null) exits 0", cmd_append(ns_app) == 0)
        ns_app.outcome, ns_app.end_utc = "killed", _utc_now()
        ns_app.outcome_basis = "exit leg"
        check("append exit leg (killed) exits 0", cmd_append(ns_app) == 0)
        rows3, defects3 = read_existing_rows(registry)
        check("registry still all-object rows after appends", len(rows3) == 5 and not defects3)

        # Negatives: the validator must fire.
        check("scalar row rejected", bool(validate_row(0)))
        check("bad outcome rejected", bool(validate_row(build_row(
            run_root=run_root, outcome="exploded", run_id=rid, attempt_id=None,
            start_utc=_utc_now(), end_utc=_utc_now(), checkpoint_manifest_sha256=None,
            launch_receipt_ref=None, source_receipt=None, outcome_basis=None, backfill=False))))
        check("running row with end_utc rejected", bool(validate_row(build_row(
            run_root=run_root, outcome="running", run_id=rid, attempt_id=None,
            start_utc=_utc_now(), end_utc=_utc_now(), checkpoint_manifest_sha256=None,
            launch_receipt_ref=None, source_receipt=None, outcome_basis=None, backfill=False))))
        foreign = build_row(
            run_root=tmp / "runs" / "someone-else", outcome="completed", run_id="other-run",
            attempt_id=None, start_utc=_utc_now(), end_utc=_utc_now(),
            checkpoint_manifest_sha256=None, launch_receipt_ref=None,
            source_receipt=None, outcome_basis=None, backfill=True)
        check("naming scan FIRES on a registry never naming the run",
              not any(s in tokens for s in _row_strings(foreign)))
        poisoned = dict(foreign)
        # Drive letter split from the path so this SOURCE file itself never
        # contains an absolute-path literal (the repo-guard [paths] scan
        # reads staged bytes, poison strings included).
        poisoned["source_receipt"] = "B" + ":/x/receipt.json"
        check("absolute drive-letter path in a row value rejected ([paths] law)",
              any("absolute local path" in d for d in validate_row(poisoned)))
        poisoned["source_receipt"] = "/tmp/receipt.json"
        check("absolute POSIX path in a row value rejected ([paths] law)",
              any("absolute local path" in d for d in validate_row(poisoned)))
        drifted = dict(foreign)
        drifted["goal_id"] = "EMBER-01"
        check("drifted goal_id rejected (authority leg 4)",
              any("goal_id" in d for d in validate_row(drifted)))

    print(f"selftest: {'PASS' if not failures else 'FAIL'} ({len(failures)} failures)")
    return 0 if not failures else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fail-safe", action="store_true",
                        help="never exit nonzero (launch-chain legs; #1489: a registry "
                             "write failure must never kill the run); defects still print")
    sub = parser.add_subparsers(dest="cmd", required=True)

    default_registry = str(REPO_ROOT / REGISTRY_REL)
    ap = sub.add_parser("append", help="append one launch/exit attempt row")
    ap.add_argument("--registry", default=default_registry)
    ap.add_argument("--run-root", required=True)
    ap.add_argument("--run-id", default=None)
    ap.add_argument("--attempt-id", default=None)
    ap.add_argument("--outcome", required=True, choices=OUTCOMES)
    ap.add_argument("--start-utc", default=None, help="default: now (UTC)")
    ap.add_argument("--end-utc", default=None, help="required unless outcome=running")
    ap.add_argument("--checkpoint-manifest-sha", default=None)
    ap.add_argument("--launch-receipt-ref", required=True)
    ap.add_argument("--source-receipt", default=None)
    ap.add_argument("--outcome-basis", default=None)
    ap.set_defaults(func=cmd_append)

    bp = sub.add_parser("backfill", help="derive rows for an existing run root from disk")
    bp.add_argument("--registry", default=default_registry)
    bp.add_argument("--run-root", required=True)
    bp.set_defaults(func=cmd_backfill)

    sp = sub.add_parser("selftest", help="synthetic run root end-to-end + negatives")
    sp.set_defaults(func=cmd_selftest)

    if argv is None:
        argv = sys.argv[1:]
    if argv == ["--selftest"]:
        argv = ["selftest"]
    args = parser.parse_args(argv)
    try:
        rc = args.func(args)
    except Exception as e:  # noqa: BLE001 -- fail-safe leg must swallow everything
        if args.fail_safe:
            print(f"FAIL-SAFE: suppressed defect (registry not updated): {e}", file=sys.stderr)
            return 0
        raise
    if rc != 0 and args.fail_safe:
        print(f"FAIL-SAFE: suppressed nonzero exit {rc} (defects printed above)", file=sys.stderr)
        return 0
    return rc


if __name__ == "__main__":
    sys.exit(main())
