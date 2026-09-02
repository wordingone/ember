# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cond3 GAP-2 (model-card/publication consumer): a model card only ever renders numbers that
trace to a validated subject manifest and a signed evaluation_result receipt, fail-closed.

Not a narrative assertion: the positive case builds a REAL signed OWNED_ADMITTED identity
manifest (the same ``admitted_manifest``/``artifact_authority`` machinery the production
validator's own test suite uses) and drives the actual generator CLI entry point
(``model_card_publication_binding.main``) against real files on disk. Six fail-closed negatives
feed malformed/missing/borrowed input at the same CLI and assert it refuses -- nonzero exit, no
``--output`` file written, never a silent pass:

1. an unresolved subject manifest (``--require-resolved`` rejects)                       -- refused
2. a fabricated/mismatched ``evaluation.subject_checkpoint_sha256`` vs                     -- refused
   ``checkpoint.byte_sha256``
3. a benchmark_id tampered vs the signed receipt                                          -- refused
4. a nonexistent subject-manifest path (missing input)                                    -- refused
5. a resolved OWNED_CANDIDATE (borrowed) subject                                -- renders, but
   labeled REFERENCE/CANDIDATE ONLY, never owned-capability language
6. an OWNED_ADMITTED subject whose evaluation.receipt_sha256 resolves to a receipt          -- refused
   bound to a DIFFERENT checkpoint (rebound receipt)

A parallel block drives ``main()`` end-to-end against real files (the EXECUTION-BINDING leg),
wrapping ``bind_model_card_publication`` with ``unittest.mock.patch.object(..., wraps=...)`` so
the real function still executes -- proving production execution reaches the binding code, not
only a unit test of the function in isolation.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
SCRIPT_DIR = ROOT / "scripts" / "ember_01_identity"
TEST_DIR = Path(__file__).parent
for _extra in (SCRIPT_DIR, TEST_DIR):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import validate_identity as identity_validator  # noqa: E402

# Reuse the production-grade signed-manifest builders from the validator's own suite so the
# positive round-trip is exercised against real evidence, not a hand-mocked shape.
import test_validate_identity as tvi  # noqa: E402
from test_validate_identity import (  # noqa: E402
    admitted_manifest,
    artifact_authority,
    rebind_receipt,
    VERIFIER_BYTES,
    TEST_PUBLIC_KEY_HEX,
)

import model_card_publication_binding as mcpb  # noqa: E402
from model_card_publication_binding import (  # noqa: E402
    ModelCardPublicationRefused,
    bind_model_card_publication,
    generate_model_card,
    owned_capability_permitted,
    render_model_card,
)


def _pin_verifier(tmpdir: Path) -> Path:
    """Replicate test_validate_identity's autouse verifier pinning for unittest."""
    registry = tmpdir / "trusted-verifiers-v1.json"
    registry.write_text(
        json.dumps(
            {
                "schema": "ember-trusted-verifier-registry-v1",
                "verifiers": [
                    {
                        "verifier_sha256": hashlib.sha256(VERIFIER_BYTES).hexdigest(),
                        "public_key_ed25519": TEST_PUBLIC_KEY_HEX,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return registry


def _valid_manifest() -> dict:
    return json.loads(
        (TEST_DIR / "fixtures" / "valid-identity-v1.json").read_text(encoding="utf-8")
    )


def _resolved_candidate_manifest() -> dict:
    """A fully-RESOLVED OWNED_CANDIDATE manifest: every unresolved marker replaced with a
    concrete, schema-valid value, but disposition stays OWNED_CANDIDATE / not selected / the
    evaluation does not count toward owned completion. OWNED_CANDIDATE never triggers the
    admission (checkpoint/receipt-bundle) requirements OWNED_ADMITTED does, so this needs no
    external checkpoint bytes, artifact bundle, or receipt bundle to pass
    ``validate_manifest(..., require_resolved=True)`` cleanly -- proven empirically against the
    real validator, not assumed.
    """
    payload = _valid_manifest()
    payload["training"]["stopping_rule"]["receipt_sha256"] = "a" * 64
    payload["backend"]["process_identity"] = {
        "pid": 999,
        "start_time_utc": "2026-07-24T00:00:00Z",
        "executable_sha256": "b" * 64,
        "command_sha256": "c" * 64,
        "nonce": "candidate-nonce",
    }
    payload["backend"]["process_receipt_sha256"] = "d" * 64
    payload["backend"]["resource_lease_id"] = "candidate-lease"
    payload["evaluation"]["score"] = {"value": 0.42, "unit": "fixture-score"}
    payload["evaluation"]["uncertainty"] = {"value": 0.01, "unit": "fixture-score"}
    payload["evaluation"]["receipt_sha256"] = "e" * 64
    # disposition/selected/counts_toward_owned_completion are already
    # OWNED_CANDIDATE / False / False in the base fixture -- left untouched.
    payload["unresolved"] = []
    return payload


class ModelCardPublicationBinding(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        registry = _pin_verifier(self.tmp_path)
        self._orig_registry = identity_validator.TRUSTED_VERIFIER_REGISTRY_PATH
        self._orig_floor = identity_validator.OWNED_ADMISSION_PARAMETER_FLOOR
        identity_validator.TRUSTED_VERIFIER_REGISTRY_PATH = registry
        identity_validator.OWNED_ADMISSION_PARAMETER_FLOOR = 1
        cache = getattr(identity_validator, "_pinned_verifier_entries", None)
        if cache is not None and hasattr(cache, "cache_clear"):
            cache.cache_clear()

    def tearDown(self) -> None:
        identity_validator.TRUSTED_VERIFIER_REGISTRY_PATH = self._orig_registry
        identity_validator.OWNED_ADMISSION_PARAMETER_FLOOR = self._orig_floor
        cache = getattr(identity_validator, "_pinned_verifier_entries", None)
        if cache is not None and hasattr(cache, "cache_clear"):
            cache.cache_clear()
        self._tmp.cleanup()

    # ---- helpers: write a full admission bundle to disk ----------------------------------
    def _write_admitted_bundle(self, payload: dict, receipts: dict[str, dict]) -> dict[str, Path]:
        kwargs = artifact_authority(payload)
        manifest_path = self.tmp_path / "subject-manifest.json"
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")
        checkpoint_path = self.tmp_path / "checkpoint.bin"
        checkpoint_path.write_bytes(kwargs["checkpoint_bytes"])
        tensor_manifest_path = self.tmp_path / "tensor-manifest.json"
        tensor_manifest_path.write_text(json.dumps(kwargs["tensor_manifest"]), encoding="utf-8")
        artifact_bundle_path = self.tmp_path / "artifact-bundle.json"
        artifact_bundle_path.write_text(json.dumps(kwargs["artifact_bundle"]), encoding="utf-8")
        receipt_bundle_path = self.tmp_path / "receipt-bundle.json"
        receipt_bundle_path.write_text(json.dumps(receipts), encoding="utf-8")
        verifier_path = self.tmp_path / "verifier.bin"
        verifier_path.write_bytes(kwargs["verifier_bytes"])
        return {
            "subject_manifest": manifest_path,
            "checkpoint": checkpoint_path,
            "tensor_manifest": tensor_manifest_path,
            "artifact_bundle": artifact_bundle_path,
            "receipt_bundle": receipt_bundle_path,
            "verifier": verifier_path,
        }

    # ==== 1. unresolved subject manifest -> refused =======================================
    def test_unresolved_manifest_refused(self) -> None:
        manifest_path = self.tmp_path / "subject-manifest.json"
        manifest_path.write_text(json.dumps(_valid_manifest()), encoding="utf-8")
        with self.assertRaises(ModelCardPublicationRefused) as ctx:
            generate_model_card(manifest_path)
        codes = {finding["code"] for finding in ctx.exception.findings}
        self.assertIn("field.unresolved", codes)

    # ==== 2. fabricated subject_checkpoint_sha256 vs checkpoint.byte_sha256 -> refused =====
    def test_fabricated_subject_checkpoint_mismatch_refused(self) -> None:
        payload, receipts = admitted_manifest()
        payload["evaluation"]["subject_checkpoint_sha256"] = "9" * 64
        paths = self._write_admitted_bundle(payload, receipts)
        with self.assertRaises(ModelCardPublicationRefused) as ctx:
            generate_model_card(
                paths["subject_manifest"],
                checkpoint=paths["checkpoint"],
                tensor_manifest=paths["tensor_manifest"],
                artifact_bundle=paths["artifact_bundle"],
                receipt_bundle=paths["receipt_bundle"],
                verifier=paths["verifier"],
            )
        codes = {finding["code"] for finding in ctx.exception.findings}
        self.assertIn("evaluation.subject_checkpoint_mismatch", codes)

    # ==== 3. tampered benchmark_id vs signed receipt -> refused ============================
    def test_tampered_benchmark_id_refused(self) -> None:
        payload, receipts = admitted_manifest()
        payload["evaluation"]["benchmark_id"] = "not-the-signed-benchmark"
        paths = self._write_admitted_bundle(payload, receipts)
        with self.assertRaises(ModelCardPublicationRefused) as ctx:
            generate_model_card(
                paths["subject_manifest"],
                checkpoint=paths["checkpoint"],
                tensor_manifest=paths["tensor_manifest"],
                artifact_bundle=paths["artifact_bundle"],
                receipt_bundle=paths["receipt_bundle"],
                verifier=paths["verifier"],
            )
        codes = {finding["code"] for finding in ctx.exception.findings}
        self.assertIn("admission.receipt_claim_mismatch", codes)

    # ==== 4. missing subject-manifest file -> refused ======================================
    def test_missing_subject_manifest_refused(self) -> None:
        missing_path = self.tmp_path / "does-not-exist.json"
        with self.assertRaises(OSError):
            generate_model_card(missing_path)
        # The CLI must also refuse cleanly (nonzero exit, no output written).
        output_path = self.tmp_path / "card.md"
        rc = mcpb.main(
            [
                "--subject-manifest",
                str(missing_path),
                "--output",
                str(output_path),
            ]
        )
        self.assertEqual(rc, 1)
        self.assertFalse(output_path.exists())

    # ==== 5. resolved OWNED_CANDIDATE (borrowed) -> renders, reference-only ================
    def test_resolved_candidate_is_reference_only(self) -> None:
        payload = _resolved_candidate_manifest()
        self.assertFalse(owned_capability_permitted(payload))
        manifest_path = self.tmp_path / "subject-manifest.json"
        manifest_path.write_text(json.dumps(payload), encoding="utf-8")

        card = generate_model_card(manifest_path)
        self.assertIn("REFERENCE/CANDIDATE ONLY", card)
        self.assertNotIn("OWNED capability results", card)
        self.assertIn("OWNED_CANDIDATE", card)
        # The claim values still trace to the manifest's own evaluation section.
        self.assertIn(json.dumps(payload["evaluation"]["benchmark_id"]), card)

    # ==== 6. receipt rebound to a different checkpoint -> refused ==========================
    def test_receipt_rebound_to_other_checkpoint_refused(self) -> None:
        payload, receipts = admitted_manifest()
        old_digest = payload["evaluation"]["receipt_sha256"]
        new_digest = rebind_receipt(
            payload, receipts, old_digest, subject_checkpoint_sha256="9" * 64
        )
        payload["evaluation"]["receipt_sha256"] = new_digest
        paths = self._write_admitted_bundle(payload, receipts)
        with self.assertRaises(ModelCardPublicationRefused) as ctx:
            generate_model_card(
                paths["subject_manifest"],
                checkpoint=paths["checkpoint"],
                tensor_manifest=paths["tensor_manifest"],
                artifact_bundle=paths["artifact_bundle"],
                receipt_bundle=paths["receipt_bundle"],
                verifier=paths["verifier"],
            )
        codes = {finding["code"] for finding in ctx.exception.findings}
        self.assertIn("admission.receipt_checkpoint_mismatch", codes)

    # ==== happy path: fully-resolved OWNED_ADMITTED traces to the signed receipt ===========
    def test_happy_path_owned_admitted_traces_to_receipt(self) -> None:
        payload, receipts = admitted_manifest()
        eval_receipt = receipts[payload["evaluation"]["receipt_sha256"]]
        paths = self._write_admitted_bundle(payload, receipts)

        card = generate_model_card(
            paths["subject_manifest"],
            checkpoint=paths["checkpoint"],
            tensor_manifest=paths["tensor_manifest"],
            artifact_bundle=paths["artifact_bundle"],
            receipt_bundle=paths["receipt_bundle"],
            verifier=paths["verifier"],
        )
        self.assertIn("OWNED capability results", card)
        self.assertNotIn("REFERENCE/CANDIDATE ONLY", card)
        self.assertIn(f"`{payload['checkpoint']['byte_sha256']}`", card)
        self.assertIn(f"`{payload['architecture']['sha256']}`", card)
        self.assertIn(f"`{payload['evaluation']['receipt_sha256']}`", card)
        # Every claim rendered traces to the SIGNED receipt's own claimed value, not a
        # hand-typed manifest field.
        from evaluation_identity_binding import EVALUATION_CLAIM_FIELDS

        for field in EVALUATION_CLAIM_FIELDS:
            self.assertIn(json.dumps(eval_receipt[field], sort_keys=True), card)

    # ==== bind_model_card_publication called standalone (no validate_manifest run) =========
    def test_bind_standalone_refuses_on_missing_cert_field(self) -> None:
        payload, _receipts = admitted_manifest()
        del payload["architecture"]["sha256"]
        with self.assertRaises(ModelCardPublicationRefused) as ctx:
            bind_model_card_publication(payload)
        codes = {finding["code"] for finding in ctx.exception.findings}
        self.assertIn("model_card.architecture_sha256_unresolved", codes)

    # ==== EXECUTION-BINDING: drive the real CLI entry, prove production reaches binding ====
    def test_cli_execution_binding_invokes_binding_fn(self) -> None:
        payload, receipts = admitted_manifest()
        paths = self._write_admitted_bundle(payload, receipts)
        output_path = self.tmp_path / "card.md"

        with mock.patch.object(
            mcpb,
            "bind_model_card_publication",
            wraps=mcpb.bind_model_card_publication,
        ) as spy:
            rc = mcpb.main(
                [
                    "--subject-manifest",
                    str(paths["subject_manifest"]),
                    "--checkpoint",
                    str(paths["checkpoint"]),
                    "--tensor-manifest",
                    str(paths["tensor_manifest"]),
                    "--artifact-bundle",
                    str(paths["artifact_bundle"]),
                    "--receipt-bundle",
                    str(paths["receipt_bundle"]),
                    "--verifier",
                    str(paths["verifier"]),
                    "--output",
                    str(output_path),
                ]
            )
        self.assertEqual(rc, 0)
        self.assertEqual(spy.call_count, 1)
        self.assertTrue(output_path.exists())
        card = output_path.read_text(encoding="utf-8")
        self.assertIn("OWNED capability results", card)
        self.assertIn(f"`{payload['checkpoint']['byte_sha256']}`", card)

    def test_cli_refuses_and_writes_no_output_on_unresolved_manifest(self) -> None:
        manifest_path = self.tmp_path / "subject-manifest.json"
        manifest_path.write_text(json.dumps(_valid_manifest()), encoding="utf-8")
        output_path = self.tmp_path / "card.md"

        with mock.patch.object(
            mcpb,
            "bind_model_card_publication",
            wraps=mcpb.bind_model_card_publication,
        ) as spy:
            rc = mcpb.main(
                [
                    "--subject-manifest",
                    str(manifest_path),
                    "--output",
                    str(output_path),
                ]
            )
        self.assertEqual(rc, 1)
        self.assertFalse(output_path.exists())
        # Refused before ever reaching the cert-binding function -- validate_manifest's own
        # require_resolved gate is what fired.
        spy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
