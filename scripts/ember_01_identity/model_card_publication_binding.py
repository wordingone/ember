#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Bind a model-card/publication's identity to a validated subject manifest, fail-closed.

cond3 increment (GAP-2, publication consumer): ``docs/domains/governance/charter/ember-01-identity-contract-consumer-map.md``
names the model-card/paper boundary as a REQUIRED-and-missing consumer (line 229: "No tracked
file named as a model card was found ... Publication can proceed from ad hoc receipts/docs. No
consumer guarantees published results bind the exact subject manifest.") and the integration
checklist requires generating "model-card/paper/demo identity from validated evidence only"
(line 274) plus running ``--require-resolved`` for every "launch, save/load promotion, serve,
benchmark, and PUBLICATION action" (line 276).

This module IS that consumer. It never invents a card from ad hoc receipts/docs: every field a
rendered card carries is read back from a subject manifest that has already been run through the
real production validator, ``scripts/ember_01_identity/validate_identity.validate_manifest``,
with ``require_resolved=True`` -- the same fail-closed gate every other admission/launch/serve
consumer in this category runs (validate_identity.py ~line 1216-1218: any unresolved field
becomes a ``field.unresolved`` finding). A subject manifest that fails that gate produces no
card at all -- no output, nonzero exit.

Two further, EXPLICIT (never assumed from validate_manifest alone) cert bindings this module
enforces before it will render anything:

1. ``bind_model_card_publication`` re-derives -- independently of validate_manifest's own
   universal cross-check (validate_identity.py ~line 1021-1023,
   ``evaluation.subject_checkpoint_mismatch``) -- that ``evaluation.subject_checkpoint_sha256 ==
   checkpoint.byte_sha256``, plus that ``architecture.sha256``, ``tokenizer.sha256``,
   ``data.sha256``, ``data.ordering_sha256``, ``data.curriculum_sha256``, and
   ``evaluation.receipt_sha256`` are all resolved sha256 values, plus that every one of the nine
   benchmark claim fields the sibling wiring module already names is present. Nothing here is
   reinvented: the nine fields are ``evaluation_identity_binding.EVALUATION_CLAIM_FIELDS`` (that
   module's own comment: "the benchmark-identity fields ... the signed evaluation_result receipt
   must independently claim"), imported directly.
2. When a signed ``evaluation_result`` receipt is available (the receipt bundle's own copy,
   resolved by ``evaluation.receipt_sha256``), ``render_model_card`` additionally re-runs
   ``evaluation_identity_binding.verify_evaluation_identity_binding`` against it -- the SAME
   independent re-derivation that module's own docstring describes -- before rendering a single
   number. A receipt that diverges from the manifest's claimed evaluation identity refuses the
   card, naming the exact field, rather than silently trusting the earlier validator pass.

Owned-capability language ("owned", "our model achieves", or similar framing) is gated on
``owned_capability_permitted``: the manifest's ``identity.disposition`` must be
``OWNED_ADMITTED`` AND its ``evaluation.counts_toward_owned_completion`` must be ``True``.
Every other disposition (``OWNED_CANDIDATE``, ``REFERENCE_ONLY``, ``HISTORICAL_ONLY``, or an
``OWNED_ADMITTED`` subject whose evaluation does not count toward completion) renders a card
labeled REFERENCE/CANDIDATE ONLY -- the numbers are still shown (traced to the same signed
receipt), but never dressed as owned capability.

CLI entry point (``main`` / ``__main__``): ``--subject-manifest`` is required; the remaining
flags (``--checkpoint``, ``--tensor-manifest``, ``--artifact-bundle``, ``--receipt-bundle``,
``--verifier``, ``--trusted-verifier-registry``) are the SAME admission-bundle inputs
``validate_identity.py``'s own CLI accepts, passed straight through to the same
``validate_manifest`` call -- an ``OWNED_ADMITTED`` subject cannot resolve without them, exactly
as the real validator requires. ``--require-resolved`` is not a flag here; it is always forced
on, because a publication action can never accept an unresolved subject.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

_SCRIPT_DIR = Path(__file__).resolve().parent  # ember/scripts/ember_01_identity
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

# The REAL runtime consumers this module wires into. Imported directly so the binding is
# provably against the same objects those consumers key on -- never a re-implementation that
# could drift from them.
# issue2015 exact-local-import:scripts/ember_01_identity/validate_identity.py
import importlib.util as _ember_f289ed8a6472ef21_importlib
import sys as _ember_f289ed8a6472ef21_sys
from pathlib import Path as _ember_f289ed8a6472ef21_Path
_ember_f289ed8a6472ef21_path = _ember_f289ed8a6472ef21_Path(__file__).resolve().parents[2].joinpath('scripts', 'ember_01_identity', 'validate_identity.py')
if not _ember_f289ed8a6472ef21_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/ember_01_identity/validate_identity.py')
_ember_f289ed8a6472ef21_aliases = ('_ember_issue2015_f289ed8a6472ef21', 'scripts.ember_01_identity.validate_identity', 'validate_identity')
_ember_f289ed8a6472ef21_existing = []
for _ember_f289ed8a6472ef21_alias in _ember_f289ed8a6472ef21_aliases:
    _ember_f289ed8a6472ef21_candidate = _ember_f289ed8a6472ef21_sys.modules.get(_ember_f289ed8a6472ef21_alias)
    if _ember_f289ed8a6472ef21_candidate is not None and all(_ember_f289ed8a6472ef21_candidate is not item for item in _ember_f289ed8a6472ef21_existing):
        _ember_f289ed8a6472ef21_existing.append(_ember_f289ed8a6472ef21_candidate)
if len(_ember_f289ed8a6472ef21_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/ember_01_identity/validate_identity.py')
if _ember_f289ed8a6472ef21_existing:
    _ember_f289ed8a6472ef21_module = _ember_f289ed8a6472ef21_existing[0]
    _ember_f289ed8a6472ef21_observed = getattr(_ember_f289ed8a6472ef21_module, '__file__', None)
    if _ember_f289ed8a6472ef21_observed is None or _ember_f289ed8a6472ef21_Path(_ember_f289ed8a6472ef21_observed).resolve() != _ember_f289ed8a6472ef21_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/ember_01_identity/validate_identity.py')
else:
    _ember_f289ed8a6472ef21_spec = _ember_f289ed8a6472ef21_importlib.spec_from_file_location('_ember_issue2015_f289ed8a6472ef21', _ember_f289ed8a6472ef21_path)
    if _ember_f289ed8a6472ef21_spec is None or _ember_f289ed8a6472ef21_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/ember_01_identity/validate_identity.py')
    _ember_f289ed8a6472ef21_module = _ember_f289ed8a6472ef21_importlib.module_from_spec(_ember_f289ed8a6472ef21_spec)
    for _ember_f289ed8a6472ef21_alias in _ember_f289ed8a6472ef21_aliases:
        _ember_f289ed8a6472ef21_prior = _ember_f289ed8a6472ef21_sys.modules.get(_ember_f289ed8a6472ef21_alias)
        if _ember_f289ed8a6472ef21_prior is not None and _ember_f289ed8a6472ef21_prior is not _ember_f289ed8a6472ef21_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/ember_01_identity/validate_identity.py')
        _ember_f289ed8a6472ef21_sys.modules[_ember_f289ed8a6472ef21_alias] = _ember_f289ed8a6472ef21_module
    try:
        _ember_f289ed8a6472ef21_spec.loader.exec_module(_ember_f289ed8a6472ef21_module)
    except BaseException:
        for _ember_f289ed8a6472ef21_alias in _ember_f289ed8a6472ef21_aliases:
            if _ember_f289ed8a6472ef21_sys.modules.get(_ember_f289ed8a6472ef21_alias) is _ember_f289ed8a6472ef21_module:
                _ember_f289ed8a6472ef21_sys.modules.pop(_ember_f289ed8a6472ef21_alias, None)
        raise
for _ember_f289ed8a6472ef21_alias in _ember_f289ed8a6472ef21_aliases:
    _ember_f289ed8a6472ef21_prior = _ember_f289ed8a6472ef21_sys.modules.get(_ember_f289ed8a6472ef21_alias)
    if _ember_f289ed8a6472ef21_prior is not None and _ember_f289ed8a6472ef21_prior is not _ember_f289ed8a6472ef21_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/ember_01_identity/validate_identity.py')
    _ember_f289ed8a6472ef21_sys.modules[_ember_f289ed8a6472ef21_alias] = _ember_f289ed8a6472ef21_module
validate_identity = _ember_f289ed8a6472ef21_module
# issue2015 exact-local-import-end:scripts/ember_01_identity/validate_identity.py  # noqa: E402
# issue2015 exact-local-import:scripts/ember_01_identity/validate_identity.py
import importlib.util as _ember_f289ed8a6472ef21_importlib
import sys as _ember_f289ed8a6472ef21_sys
from pathlib import Path as _ember_f289ed8a6472ef21_Path
_ember_f289ed8a6472ef21_path = _ember_f289ed8a6472ef21_Path(__file__).resolve().parents[2].joinpath('scripts', 'ember_01_identity', 'validate_identity.py')
if not _ember_f289ed8a6472ef21_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:scripts/ember_01_identity/validate_identity.py')
_ember_f289ed8a6472ef21_aliases = ('_ember_issue2015_f289ed8a6472ef21', 'scripts.ember_01_identity.validate_identity', 'validate_identity')
_ember_f289ed8a6472ef21_existing = []
for _ember_f289ed8a6472ef21_alias in _ember_f289ed8a6472ef21_aliases:
    _ember_f289ed8a6472ef21_candidate = _ember_f289ed8a6472ef21_sys.modules.get(_ember_f289ed8a6472ef21_alias)
    if _ember_f289ed8a6472ef21_candidate is not None and all(_ember_f289ed8a6472ef21_candidate is not item for item in _ember_f289ed8a6472ef21_existing):
        _ember_f289ed8a6472ef21_existing.append(_ember_f289ed8a6472ef21_candidate)
if len(_ember_f289ed8a6472ef21_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:scripts/ember_01_identity/validate_identity.py')
if _ember_f289ed8a6472ef21_existing:
    _ember_f289ed8a6472ef21_module = _ember_f289ed8a6472ef21_existing[0]
    _ember_f289ed8a6472ef21_observed = getattr(_ember_f289ed8a6472ef21_module, '__file__', None)
    if _ember_f289ed8a6472ef21_observed is None or _ember_f289ed8a6472ef21_Path(_ember_f289ed8a6472ef21_observed).resolve() != _ember_f289ed8a6472ef21_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:scripts/ember_01_identity/validate_identity.py')
else:
    _ember_f289ed8a6472ef21_spec = _ember_f289ed8a6472ef21_importlib.spec_from_file_location('_ember_issue2015_f289ed8a6472ef21', _ember_f289ed8a6472ef21_path)
    if _ember_f289ed8a6472ef21_spec is None or _ember_f289ed8a6472ef21_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:scripts/ember_01_identity/validate_identity.py')
    _ember_f289ed8a6472ef21_module = _ember_f289ed8a6472ef21_importlib.module_from_spec(_ember_f289ed8a6472ef21_spec)
    for _ember_f289ed8a6472ef21_alias in _ember_f289ed8a6472ef21_aliases:
        _ember_f289ed8a6472ef21_prior = _ember_f289ed8a6472ef21_sys.modules.get(_ember_f289ed8a6472ef21_alias)
        if _ember_f289ed8a6472ef21_prior is not None and _ember_f289ed8a6472ef21_prior is not _ember_f289ed8a6472ef21_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/ember_01_identity/validate_identity.py')
        _ember_f289ed8a6472ef21_sys.modules[_ember_f289ed8a6472ef21_alias] = _ember_f289ed8a6472ef21_module
    try:
        _ember_f289ed8a6472ef21_spec.loader.exec_module(_ember_f289ed8a6472ef21_module)
    except BaseException:
        for _ember_f289ed8a6472ef21_alias in _ember_f289ed8a6472ef21_aliases:
            if _ember_f289ed8a6472ef21_sys.modules.get(_ember_f289ed8a6472ef21_alias) is _ember_f289ed8a6472ef21_module:
                _ember_f289ed8a6472ef21_sys.modules.pop(_ember_f289ed8a6472ef21_alias, None)
        raise
for _ember_f289ed8a6472ef21_alias in _ember_f289ed8a6472ef21_aliases:
    _ember_f289ed8a6472ef21_prior = _ember_f289ed8a6472ef21_sys.modules.get(_ember_f289ed8a6472ef21_alias)
    if _ember_f289ed8a6472ef21_prior is not None and _ember_f289ed8a6472ef21_prior is not _ember_f289ed8a6472ef21_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:scripts/ember_01_identity/validate_identity.py')
    _ember_f289ed8a6472ef21_sys.modules[_ember_f289ed8a6472ef21_alias] = _ember_f289ed8a6472ef21_module
IdentityValidationError = getattr(_ember_f289ed8a6472ef21_module, 'IdentityValidationError')
validate_manifest = getattr(_ember_f289ed8a6472ef21_module, 'validate_manifest')
# issue2015 exact-local-import-end:scripts/ember_01_identity/validate_identity.py  # noqa: E402
from evaluation_identity_binding import (  # noqa: E402
    EVALUATION_CLAIM_FIELDS,
    EvaluationIdentityMismatch,
    verify_evaluation_identity_binding,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# The manifest paths this card's cert-bindings table publishes. Label -> dotted manifest path.
CERT_HASH_BINDINGS: tuple[tuple[str, str], ...] = (
    ("checkpoint_sha256", "checkpoint.byte_sha256"),
    ("architecture_sha256", "architecture.sha256"),
    ("tokenizer_sha256", "tokenizer.sha256"),
    ("data_corpus_sha256", "data.sha256"),
    ("data_ordering_sha256", "data.ordering_sha256"),
    ("data_curriculum_sha256", "data.curriculum_sha256"),
)

OWNED_ADMITTED_DISPOSITION = "OWNED_ADMITTED"


class ModelCardPublicationRefused(ValueError):
    """A publication action was refused -- no card was rendered.

    ``findings`` mirrors ``IdentityValidationError.findings`` shape
    (``[{"code": ..., "detail": ...}, ...]``) so a caller (the CLI, or an upstream publication
    pipeline) gets one consistent fail-closed contract regardless of which layer refused.
    """

    def __init__(
        self, message: str, findings: list[dict[str, str]] | None = None
    ) -> None:
        super().__init__(message)
        self.findings = (
            list(findings)
            if findings is not None
            else [{"code": "model_card.refused", "detail": message}]
        )


def _get_path(payload: Mapping[str, Any], dotted: str) -> Any:
    node: Any = payload
    for part in dotted.split("."):
        if not isinstance(node, Mapping) or part not in node:
            return None
        node = node[part]
    return node


def owned_capability_permitted(manifest: Mapping[str, Any]) -> bool:
    """True only when this subject may carry owned-capability language.

    Both conditions are required: ``identity.disposition == "OWNED_ADMITTED"`` AND
    ``evaluation.counts_toward_owned_completion is True``. A borrowed/candidate subject, or an
    admitted subject whose evaluation does not itself count toward owned completion, is False --
    the card must then label its results reference/candidate only.
    """
    disposition = _get_path(manifest, "identity.disposition")
    counts = _get_path(manifest, "evaluation.counts_toward_owned_completion")
    return disposition == OWNED_ADMITTED_DISPOSITION and counts is True


def bind_model_card_publication(manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Project the cert-bound fields a model card MUST publish, or refuse.

    Re-derives every value directly from ``manifest`` -- never assumes an earlier
    ``validate_manifest`` pass already proved it, so this function is safe to call standalone.
    Raises ``ModelCardPublicationRefused`` naming the exact missing/mismatched field the instant
    any cert binding is absent, unresolved, or diverges.
    """
    bound: dict[str, Any] = {}
    for label, path in CERT_HASH_BINDINGS:
        value = _get_path(manifest, path)
        if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
            raise ModelCardPublicationRefused(
                f"{path} is missing or not a resolved sha256; refusing to publish",
                findings=[
                    {"code": f"model_card.{label}_unresolved", "detail": path}
                ],
            )
        bound[label] = value

    checkpoint_hash = bound["checkpoint_sha256"]
    subject_hash = _get_path(manifest, "evaluation.subject_checkpoint_sha256")
    if subject_hash != checkpoint_hash:
        raise ModelCardPublicationRefused(
            "evaluation.subject_checkpoint_sha256 does not match checkpoint.byte_sha256; "
            "refusing to publish a benchmark whose subject is not this checkpoint",
            findings=[
                {
                    "code": "model_card.subject_checkpoint_mismatch",
                    "detail": f"{subject_hash!r} != {checkpoint_hash!r}",
                }
            ],
        )
    bound["evaluation_subject_checkpoint_sha256"] = subject_hash

    receipt_digest = _get_path(manifest, "evaluation.receipt_sha256")
    if not isinstance(receipt_digest, str) or not _SHA256_RE.fullmatch(receipt_digest):
        raise ModelCardPublicationRefused(
            "evaluation.receipt_sha256 is missing or unresolved; refusing to publish results "
            "not traced to a signed evaluation_result receipt",
            findings=[
                {
                    "code": "model_card.evaluation_receipt_unresolved",
                    "detail": str(receipt_digest),
                }
            ],
        )
    bound["evaluation_receipt_sha256"] = receipt_digest

    evaluation = manifest.get("evaluation")
    if not isinstance(evaluation, Mapping):
        raise ModelCardPublicationRefused(
            "manifest has no evaluation section; refusing to publish",
            findings=[{"code": "model_card.evaluation_missing", "detail": "evaluation"}],
        )
    claims: dict[str, Any] = {}
    for field in EVALUATION_CLAIM_FIELDS:
        if field not in evaluation:
            raise ModelCardPublicationRefused(
                f"evaluation.{field} is missing; refusing to publish an incomplete "
                "benchmark claim",
                findings=[
                    {"code": "model_card.evaluation_claim_missing", "detail": field}
                ],
            )
        claims[field] = evaluation[field]
    bound["evaluation_claims"] = claims
    return bound


def render_model_card(
    manifest: Mapping[str, Any], *, receipt: Mapping[str, Any] | None = None
) -> str:
    """Render a model card from an already-validated subject manifest, fail-closed.

    ``manifest`` must already be the object ``validate_manifest`` returned (or an equivalent
    fully-resolved manifest) -- this function does not itself run the identity validator; that is
    ``generate_model_card``'s job. When ``receipt`` is supplied (the signed evaluation_result
    receipt named by ``evaluation.receipt_sha256``, resolved out of a receipt bundle), this
    function independently re-verifies the evaluation binding via
    ``evaluation_identity_binding.verify_evaluation_identity_binding`` before rendering a single
    number -- defense in depth, never trusting a single consumer's pass alone.
    """
    bound = bind_model_card_publication(manifest)

    if receipt is not None:
        try:
            verify_evaluation_identity_binding(manifest, receipt)
        except EvaluationIdentityMismatch as exc:
            raise ModelCardPublicationRefused(
                f"signed evaluation_result receipt diverges from the manifest: {exc}",
                findings=[
                    {"code": "model_card.receipt_binding_mismatch", "detail": str(exc)}
                ],
            ) from exc

    owned = owned_capability_permitted(manifest)
    disposition = _get_path(manifest, "identity.disposition")
    model_id = _get_path(manifest, "identity.model_id")
    claims = bound["evaluation_claims"]

    lines: list[str] = []
    lines.append(f"# Model card: {model_id}")
    lines.append("")
    lines.append(f"Disposition: `{disposition}`")
    lines.append("")
    if owned:
        lines.append(
            "This card reports OWNED capability results: the benchmark score below was "
            "measured against this exact OWNED_ADMITTED checkpoint's byte identity, by a "
            "signed evaluation_result receipt, and counts toward owned completion."
        )
    else:
        lines.append(
            "REFERENCE/CANDIDATE ONLY. This subject is not an OWNED_ADMITTED checkpoint "
            "with completion-crediting evaluation evidence. No owned-capability language "
            '("owned", "our model achieves", or similar) may attach to the results below; '
            "they are reported strictly as reference/candidate measurements."
        )
    lines.append("")
    lines.append("## Cert bindings")
    lines.append("")
    lines.append("| Field | SHA-256 |")
    lines.append("|---|---|")
    lines.append(f"| checkpoint.byte_sha256 | `{bound['checkpoint_sha256']}` |")
    lines.append(f"| architecture.sha256 | `{bound['architecture_sha256']}` |")
    lines.append(f"| tokenizer.sha256 | `{bound['tokenizer_sha256']}` |")
    lines.append(f"| data.sha256 | `{bound['data_corpus_sha256']}` |")
    lines.append(f"| data.ordering_sha256 | `{bound['data_ordering_sha256']}` |")
    lines.append(f"| data.curriculum_sha256 | `{bound['data_curriculum_sha256']}` |")
    lines.append(
        f"| evaluation.subject_checkpoint_sha256 | `{bound['evaluation_subject_checkpoint_sha256']}` |"
    )
    lines.append(f"| evaluation.receipt_sha256 | `{bound['evaluation_receipt_sha256']}` |")
    lines.append("")
    lines.append("## Evaluation" + ("" if owned else " (reference/candidate)"))
    lines.append("")
    lines.append("| Claim | Value |")
    lines.append("|---|---|")
    for field in EVALUATION_CLAIM_FIELDS:
        lines.append(f"| {field} | {json.dumps(claims[field], sort_keys=True)} |")
    lines.append("")
    return "\n".join(lines)


def _load_json(path: Path | None) -> Any | None:
    return json.loads(path.read_text(encoding="utf-8")) if path is not None else None


def generate_model_card(
    subject_manifest: Path,
    *,
    checkpoint: Path | None = None,
    tensor_manifest: Path | None = None,
    artifact_bundle: Path | None = None,
    receipt_bundle: Path | None = None,
    verifier: Path | None = None,
    trusted_verifier_registry: Path | None = None,
) -> str:
    """Validate ``subject_manifest`` (fail-closed) and render its model card.

    Runs the real production validator, ``validate_identity.validate_manifest``, with
    ``require_resolved=True`` -- the identical admission-bundle arguments
    ``validate_identity.py``'s own CLI accepts are threaded straight through. ANY validation
    finding refuses publication: no card is returned, and the caller (the CLI) writes no output.
    """
    payload = json.loads(subject_manifest.read_text(encoding="utf-8"))
    receipt_bundle_data = _load_json(receipt_bundle)
    try:
        validated = validate_manifest(
            payload,
            checkpoint_bytes=checkpoint.read_bytes() if checkpoint is not None else None,
            tensor_manifest=_load_json(tensor_manifest),
            artifact_bundle=_load_json(artifact_bundle),
            receipt_bundle=receipt_bundle_data,
            verifier_bytes=verifier.read_bytes() if verifier is not None else None,
            trusted_verifier_registry=_load_json(trusted_verifier_registry),
            require_resolved=True,
        )
    except IdentityValidationError as exc:
        raise ModelCardPublicationRefused(
            "subject manifest failed identity validation; refusing to publish",
            findings=list(exc.findings),
        ) from exc

    receipt: Mapping[str, Any] | None = None
    if isinstance(receipt_bundle_data, Mapping):
        digest = _get_path(validated, "evaluation.receipt_sha256")
        candidate = receipt_bundle_data.get(digest) if isinstance(digest, str) else None
        if isinstance(candidate, Mapping):
            receipt = candidate

    return render_model_card(validated, receipt=receipt)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subject-manifest", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--tensor-manifest", type=Path)
    parser.add_argument("--artifact-bundle", type=Path)
    parser.add_argument("--receipt-bundle", type=Path)
    parser.add_argument("--verifier", type=Path)
    parser.add_argument("--trusted-verifier-registry", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        card = generate_model_card(
            args.subject_manifest,
            checkpoint=args.checkpoint,
            tensor_manifest=args.tensor_manifest,
            artifact_bundle=args.artifact_bundle,
            receipt_bundle=args.receipt_bundle,
            verifier=args.verifier,
            trusted_verifier_registry=args.trusted_verifier_registry,
        )
    except (ModelCardPublicationRefused, OSError, json.JSONDecodeError) as exc:
        findings = getattr(exc, "findings", None) or [
            {"code": "model_card.error", "detail": str(exc)}
        ]
        print(
            json.dumps({"ok": False, "findings": findings}, indent=2, sort_keys=True),
            file=sys.stderr,
        )
        return 1

    if args.output is not None:
        args.output.write_text(card, encoding="utf-8")
    else:
        print(card)
    return 0


if __name__ == "__main__":
    sys.exit(main())
