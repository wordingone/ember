#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Admit or block a docs/research/journal benchmark for Ember MVP goal-clear loops.

cond3 GAP-4: this harness previously froze an independent BENCHMARK-side identity
(``ADMITTED_RESEARCH_BENCHMARK_IDS``, tasks/evaluator hashing below) but never validated
the SUBJECT being scored -- so a score measured against a borrowed/tampered/absent
checkpoint could launder into owned completion credit. ``resolve_subject_identity`` wires
in the production identity validator (``ember_01_identity.validate_identity.validate_manifest``,
reused, never reimplemented) with ``require_resolved=True`` and fails CLOSED -- raising
``SubjectIdentityRefused`` before any admission receipt is built -- on any
``IdentityValidationError``, missing/unreadable/invalid-JSON manifest, or unresolved
identity field. A RESULT/score projection (``--eval-result-receipt``) routes through
``evaluation_identity_binding.bind_evaluation_identity`` so a borrowed-subject receipt
cannot be bound as owned evidence either.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
import importlib.util as _ember_66ee9e91637922dc_importlib
import sys as _ember_66ee9e91637922dc_sys
from pathlib import Path as _ember_66ee9e91637922dc_Path
_ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
if not _ember_66ee9e91637922dc_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_write.py')
_ember_66ee9e91637922dc_aliases = ('_ember_issue2015_66ee9e91637922dc', 'receipt_write', 'scripts.receipt_write')
_ember_66ee9e91637922dc_existing = []
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_candidate = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_candidate is not None and all(_ember_66ee9e91637922dc_candidate is not item for item in _ember_66ee9e91637922dc_existing):
        _ember_66ee9e91637922dc_existing.append(_ember_66ee9e91637922dc_candidate)
if len(_ember_66ee9e91637922dc_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_write.py')
if _ember_66ee9e91637922dc_existing:
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_existing[0]
    _ember_66ee9e91637922dc_observed = getattr(_ember_66ee9e91637922dc_module, '__file__', None)
    if _ember_66ee9e91637922dc_observed is None or _ember_66ee9e91637922dc_Path(_ember_66ee9e91637922dc_observed).resolve() != _ember_66ee9e91637922dc_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_write.py')
else:
    _ember_66ee9e91637922dc_spec = _ember_66ee9e91637922dc_importlib.spec_from_file_location('_ember_issue2015_66ee9e91637922dc', _ember_66ee9e91637922dc_path)
    if _ember_66ee9e91637922dc_spec is None or _ember_66ee9e91637922dc_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_importlib.module_from_spec(_ember_66ee9e91637922dc_spec)
    for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
        _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
        if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
        _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
    try:
        _ember_66ee9e91637922dc_spec.loader.exec_module(_ember_66ee9e91637922dc_module)
    except BaseException:
        for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
            if _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias) is _ember_66ee9e91637922dc_module:
                _ember_66ee9e91637922dc_sys.modules.pop(_ember_66ee9e91637922dc_alias, None)
        raise
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
checked_write = getattr(_ember_66ee9e91637922dc_module, 'checked_write')
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py

_IDENTITY_DIR = Path(__file__).resolve().parent / "ember_01_identity"
if str(_IDENTITY_DIR) not in sys.path:
    sys.path.insert(0, str(_IDENTITY_DIR))

from validate_identity import IdentityValidationError, validate_manifest  # noqa: E402
from evaluation_identity_binding import (  # noqa: E402
    EvaluationIdentityMismatch,
    bind_evaluation_identity,
)

SHA_CONVENTION = "bytes on disk as-is (binary read, no line-ending normalization)"
TICKET = "EMBER-RESEARCH-BENCHMARK-ADMISSION"
ADMITTED_RESEARCH_BENCHMARK_IDS = {
    "ScienceAgentBench",
    "D3-Gym",
    "SciReplicate-Bench",
    "ResearchBench",
    "PaperBench",
}


class SubjectIdentityRefused(RuntimeError):
    """cond3 GAP-4: refuse admission -- the SUBJECT identity manifest failed validation.

    Raised instead of accumulating a soft error, so a borrowed/tampered/absent subject
    can never produce an admission receipt of any verdict -- not even BLOCKED. No owned
    completion credit is reachable from this branch.
    """


def _harness_self_sha256() -> str:
    return "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def resolve_subject_identity(subject_manifest_path: Path) -> dict[str, Any]:
    """Load + validate the SUBJECT identity manifest, fail-closed (cond3 GAP-4).

    Reuses the production validator
    (``ember_01_identity.validate_identity.validate_manifest``) with
    ``require_resolved=True`` -- never reimplements identity checking. Fails closed
    (raises ``SubjectIdentityRefused``) on: an unreadable/missing manifest file,
    invalid JSON, any ``IdentityValidationError`` from the validator (including an
    unresolved identity/disposition field, which ``require_resolved`` surfaces as
    ``field.unresolved`` findings).
    """
    try:
        raw = subject_manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SubjectIdentityRefused(
            f"subject manifest unreadable: {subject_manifest_path}: {exc}"
        ) from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SubjectIdentityRefused(
            f"subject manifest is not valid JSON: {subject_manifest_path}: {exc}"
        ) from exc
    try:
        validated = validate_manifest(payload, require_resolved=True)
    except IdentityValidationError as exc:
        codes = ", ".join(finding.get("code", "?") for finding in exc.findings)
        raise SubjectIdentityRefused(
            f"subject manifest failed identity validation (require_resolved): {codes}"
        ) from exc
    return validated


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _operator_routes_research(operator_receipt: dict[str, Any]) -> bool:
    action = operator_receipt.get("selected_next_action", {})
    return bool(
        operator_receipt.get("verdict") == "SELF_GROWTH_OPERATOR_READY"
        and operator_receipt.get("manual_selection") is False
        and action.get("kind") == "stronger_external_benchmark"
        and action.get("benchmark_family") == "research_journal"
    )


def _task_count(tasks_path: Path, errors: list[str]) -> int:
    try:
        tasks = _load_json(tasks_path)
    except json.JSONDecodeError:
        errors.append("tasks_path.invalid_json")
        return 0
    rows = tasks.get("tasks")
    if not isinstance(rows, list) or not rows:
        errors.append("tasks_path.no_tasks")
        return 0
    return len(rows)


def build_admission_receipt(
    manifest_path: Path,
    operator_receipt_path: Path,
    subject_manifest_path: Path,
    eval_result_receipt_path: Path | None = None,
) -> dict[str, Any]:
    # cond3 GAP-4: resolve + validate the SUBJECT identity FIRST and fail closed --
    # raises SubjectIdentityRefused, never reaching the errors-accumulation path below,
    # so no admission receipt of any verdict is ever built from a borrowed subject.
    subject = resolve_subject_identity(Path(subject_manifest_path))
    subject_checkpoint = subject.get("checkpoint")
    subject_checkpoint_sha256 = (
        subject_checkpoint.get("byte_sha256") if isinstance(subject_checkpoint, dict) else None
    )
    subject_evaluation = subject.get("evaluation")
    comparator_identity = (
        subject_evaluation.get("comparator_identity") if isinstance(subject_evaluation, dict) else None
    )
    comparator_sha256 = (
        subject_evaluation.get("comparator_sha256") if isinstance(subject_evaluation, dict) else None
    )

    # cond3 GAP-4 point 4: any RESULT/score projection routes through the production
    # binding module -- never a hand-typed score -- so a receipt measured on a
    # different checkpoint cannot be bound as this subject's owned evidence.
    evaluation_binding: dict[str, Any] | None = None
    if eval_result_receipt_path is not None:
        eval_receipt = _load_json(Path(eval_result_receipt_path))
        try:
            bound = bind_evaluation_identity(subject, eval_receipt)
        except EvaluationIdentityMismatch as exc:
            raise SubjectIdentityRefused(
                f"evaluation identity binding refused: {exc}"
            ) from exc
        evaluation_binding = bound.get("evaluation")

    errors: list[str] = []
    missing: list[str] = []
    manifest = _load_json(manifest_path)
    operator_receipt = _load_json(operator_receipt_path)

    tasks_path = Path(str(manifest.get("tasks_path", "")))
    evaluator_path = Path(str(manifest.get("evaluator_path", "")))

    if manifest.get("benchmark_id") not in ADMITTED_RESEARCH_BENCHMARK_IDS:
        errors.append("benchmark_id.not_admitted_research_benchmark")
    if manifest.get("family") != "research_journal":
        errors.append("family.not_research_journal")
    if not manifest.get("source_url"):
        errors.append("source_url.missing")
    if not manifest.get("license_or_access_basis"):
        errors.append("license_or_access_basis.missing")
    if manifest.get("heldout_frozen") is not True:
        errors.append("heldout_frozen")
    if not manifest.get("scoring_metric"):
        errors.append("scoring_metric.missing")
    requires_docker = manifest.get("requires_docker") is True
    if requires_docker and manifest.get("docker_daemon_ready") is not True:
        errors.append("docker_daemon.not_ready")
        missing.append("docker_daemon")
    if not tasks_path.exists():
        errors.append("tasks_path.missing")
        missing.append("tasks_path")
        task_count = 0
        tasks_sha256 = None
    else:
        task_count = _task_count(tasks_path, errors)
        tasks_sha256 = _sha256(tasks_path)
    if not evaluator_path.exists():
        errors.append("evaluator_path.missing")
        missing.append("evaluator_path")
        evaluator_sha256 = None
    else:
        evaluator_sha256 = _sha256(evaluator_path)

    operator_routed = _operator_routes_research(operator_receipt)
    if not operator_routed:
        errors.append("operator.not_research_routed")

    real_external_ready = not errors
    return {
        "ticket": TICKET,
        "ts": datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"),
        "sha_convention": SHA_CONVENTION,
        "manifest_path": str(manifest_path),
        "operator_receipt_path": str(operator_receipt_path),
        "benchmark_id": manifest.get("benchmark_id"),
        "benchmark_family": manifest.get("family"),
        "source_url": manifest.get("source_url"),
        "license_or_access_basis": manifest.get("license_or_access_basis"),
        "heldout_frozen": manifest.get("heldout_frozen") is True,
        "scoring_metric": manifest.get("scoring_metric"),
        "requires_docker": requires_docker,
        "docker_daemon_ready": manifest.get("docker_daemon_ready") is True,
        "tasks_path": str(tasks_path),
        "tasks_sha256": tasks_sha256,
        "task_count": task_count,
        "evaluator_path": str(evaluator_path),
        "evaluator_sha256": evaluator_sha256,
        "operator_routed": operator_routed,
        "manual_selection": False,
        "real_external_heldout_ready": real_external_ready,
        "subject_manifest_path": str(subject_manifest_path),
        "subject_checkpoint_sha256": subject_checkpoint_sha256,
        "comparator_identity": comparator_identity,
        "comparator_sha256": comparator_sha256,
        "harness_sha256": _harness_self_sha256(),
        "evaluation_binding": evaluation_binding,
        "missing_artifacts": missing,
        "errors": errors,
        "required_next_receipts": [
            "research-external-heldout-a-b-c-cycle",
            "research-score-rows",
            "operator-deletion-test",
            "readiness",
        ],
        "verdict": "RESEARCH_BENCHMARK_ADMITTED" if real_external_ready else "RESEARCH_BENCHMARK_BLOCKED",
    }


def validate_admission_receipt(receipt: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if receipt.get("ticket") != TICKET:
        errors.append("ticket")
    if receipt.get("verdict") not in {"RESEARCH_BENCHMARK_ADMITTED", "RESEARCH_BENCHMARK_BLOCKED"}:
        errors.append("verdict")
    if receipt.get("benchmark_family") != "research_journal":
        errors.append("benchmark_family")
    if receipt.get("operator_routed") is not True:
        errors.append("operator_routed")
    if receipt.get("manual_selection") is not False:
        errors.append("manual_selection")
    if receipt.get("verdict") == "RESEARCH_BENCHMARK_ADMITTED":
        if receipt.get("real_external_heldout_ready") is not True:
            errors.append("real_external_heldout_ready")
        if receipt.get("task_count", 0) <= 0:
            errors.append("task_count")
        if not receipt.get("tasks_sha256"):
            errors.append("tasks_sha256")
        if not receipt.get("evaluator_sha256"):
            errors.append("evaluator_sha256")
        if receipt.get("errors"):
            errors.append("errors")
        # cond3 GAP-4: no ADMITTED verdict without a validated, hashed SUBJECT identity.
        if not receipt.get("subject_checkpoint_sha256"):
            errors.append("subject_checkpoint_sha256")
        if not receipt.get("harness_sha256"):
            errors.append("harness_sha256")
    return errors


def write_admission_receipt(
    out_path: Path,
    manifest_path: Path,
    operator_receipt_path: Path,
    subject_manifest_path: Path,
    eval_result_receipt_path: Path | None = None,
) -> dict[str, Any]:
    receipt = build_admission_receipt(
        manifest_path, operator_receipt_path, subject_manifest_path, eval_result_receipt_path
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    checked_write(str(out_path), receipt)
    return receipt


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--manifest")
    ap.add_argument("--operator-receipt")
    ap.add_argument(
        "--subject-manifest",
        required=False,
        help=(
            "REQUIRED (except with --selftest): path to the SUBJECT identity manifest "
            "(ember_01_identity schema) whose checkpoint the benchmark is scored "
            "against. Validated via validate_identity.validate_manifest("
            "require_resolved=True); a borrowed/tampered/absent subject refuses "
            "admission outright (cond3 GAP-4)."
        ),
    )
    ap.add_argument("--eval-result-receipt", required=False)
    ap.add_argument("--out")
    args = ap.parse_args()

    if args.selftest:
        import ember_research_benchmark_harness_selftest

        return ember_research_benchmark_harness_selftest.main()

    if not (args.manifest and args.operator_receipt and args.subject_manifest and args.out):
        ap.print_help()
        return 1

    try:
        receipt = write_admission_receipt(
            Path(args.out),
            Path(args.manifest),
            Path(args.operator_receipt),
            Path(args.subject_manifest),
            Path(args.eval_result_receipt) if args.eval_result_receipt else None,
        )
    except SubjectIdentityRefused as exc:
        print(
            json.dumps(
                {
                    "ticket": TICKET,
                    "verdict": "RESEARCH_BENCHMARK_BLOCKED",
                    "errors": [f"subject_identity.refused: {exc}"],
                },
                indent=2,
            )
        )
        return 2

    print(json.dumps(receipt, indent=2))
    return 0 if receipt["verdict"] == "RESEARCH_BENCHMARK_ADMITTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
