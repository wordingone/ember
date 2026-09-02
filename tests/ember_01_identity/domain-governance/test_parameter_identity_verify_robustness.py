# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cond3 increment-1c: harden ``verify_parameter_identity_binding`` (fburst-0955 gaps).

Three robustness gaps found by an adversarial red-team on the just-landed verify
(no bypass, but fail-closed-but-incomplete):

(b) the re-measure re-derivation only caught ``ValueError``/``OSError`` from
    ``measure_live_checkpoint``; any other exception (e.g. a ``KeyError`` from a
    malformed counter receipt) escaped uncaught instead of failing closed with a
    named ``ParameterIdentityMismatch``.
(c) ``model_config`` bytes were never explicitly re-hashed and bound to the
    receipt's ``model_config_sha256`` -- only the implicit counts cross-check
    covered it.
(a) specialist-routed receipts (``active_expert_ids != ["shared"]``) had no
    passing verify path (the counter demands external parent/root manifests this
    function never supplies) and fell through to an unlabelled failure inside the
    re-measure re-derivation. This module adds an explicit, named guard instead.

Each is exercised against a REAL live checkpoint (same tiny UnifiedDecoder fixture
as ``test_parameter_identity_roundtrip.py``), never a mock counter.
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

import torch

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
_FIXTURE_DIR = ROOT / "tests" / "ember_restart_model" / "domain-governance"
if not (_FIXTURE_DIR / "checkpoint_fixture.py").is_file():
    _fixture_candidates = sorted(
        (ROOT / "tests" / "ember_restart_model").glob("**/checkpoint_fixture.py")
    )
    if len(_fixture_candidates) != 1:
        raise RuntimeError("checkpoint_fixture.py must have exactly one migration location")
    _FIXTURE_DIR = _fixture_candidates[0].parent
for _extra in (
    ROOT / "tools" / "ember-restart-3b",
    _FIXTURE_DIR,
    ROOT / "scripts" / "ember_01_identity",
):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from model import RestartDecoderConfig, UnifiedDecoder  # noqa: E402
from checkpoint_fixture import write_checkpoint_artifacts  # noqa: E402

import parameter_identity_binding as pib  # noqa: E402
from parameter_identity_binding import (  # noqa: E402
    ParameterIdentityMismatch,
    bind_parameter_identity,
    measure_live_checkpoint,
    verify_parameter_identity_binding,
)

from test_parameter_identity_roundtrip import _base_manifest  # noqa: E402


def _write_live_checkpoint(directory: Path, *, seed: int) -> tuple[Path, Path]:
    """Write a REAL tiny checkpoint and return (model_config_path, checkpoint_manifest_path).

    Mirrors ``test_parameter_identity_roundtrip._write_live_checkpoint`` -- kept
    local (not imported) so this file stands alone against the counter's public
    surface only.
    """
    config = RestartDecoderConfig.small_for_tests(
        hidden_size=32, layers=2, attention_heads=4, vocab_size=64
    )
    model = UnifiedDecoder(config, genesis_seed=seed)
    model._activate_expert("shared")
    optimizer = torch.optim.AdamW(
        (p for p in model.parameters() if p.requires_grad), lr=1e-4
    )
    config_path = directory / "config.json"
    config_path.write_text(
        json.dumps({
            "architecture_revision": "ember-sparse-3b-v2",
            "model": {
                "hidden_size": 32, "layers": 2, "attention_heads": 4, "vocab_size": 64,
                "tied_embeddings": True,
                "image_projection": {"input_shape": [48, 48, 3], "output_size": 32},
                "audio_projection": {"frame_samples": 640, "output_size": 32},
                "expert_routing": {"expert_names": ["vision", "audio", "reasoning", "tool"]},
            },
        }),
        encoding="utf-8",
    )
    write_checkpoint_artifacts(
        model, optimizer, directory / "checkpoint", launch_seed=seed,
        rng_state={
            "cpu": torch.get_rng_state().clone(),
            "cuda": (torch.cuda.get_rng_state().clone() if torch.cuda.is_available() else torch.tensor([1, 2, 3], dtype=torch.uint8)),
        },
        data_cursor={"shard": f"cond3-inc1c-seed-{seed}", "record_index": 0, "global_step": 0, "tokens_seen": 0},
        model_config_sha256=hashlib.sha256(config_path.read_bytes()).hexdigest(),
        contract_sha256="d" * 64,
        expert_genesis_sha256=model.expert_bank_genesis_hashes(),
    )
    manifest_path = directory / "checkpoint" / "checkpoint-manifest.json"
    return config_path, manifest_path


def _tensors_from_shards(manifest_path: Path) -> list[dict]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return [
        {
            "name": record["path"],
            "shape": [int(record["bytes"])],
            "dtype": "ember-checkpoint-shard-v1",
            "sha256": record["sha256"],
        }
        for record in manifest["shards"]
    ]


class VerifyRobustnessTests(unittest.TestCase):
    def _bound_fixture(self, directory: Path, *, seed: int):
        config_path, manifest_path = _write_live_checkpoint(directory, seed=seed)
        receipt = measure_live_checkpoint(
            model_config=config_path, checkpoint_manifest=manifest_path, active_expert="shared"
        )
        manifest = _base_manifest()
        manifest["checkpoint"]["tensors"] = _tensors_from_shards(manifest_path)
        bound = bind_parameter_identity(manifest, receipt)
        return bound, receipt, config_path, manifest_path

    # (b) any re-measure exception fails closed as ParameterIdentityMismatch,
    # not just ValueError/OSError.
    def test_non_valueerror_from_remeasure_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bound, receipt, config_path, manifest_path = self._bound_fixture(root, seed=606)

            def _raise_key_error(**_kwargs):
                raise KeyError("simulated non-ValueError counter failure")

            with mock.patch.object(pib, "measure_live_checkpoint", side_effect=_raise_key_error):
                with self.assertRaises(ParameterIdentityMismatch) as ctx:
                    verify_parameter_identity_binding(
                        bound, receipt,
                        checkpoint_manifest=manifest_path, model_config=config_path,
                    )
            # The original error type/message is preserved in the mismatch, never
            # swallowed silently.
            self.assertIn("KeyError", str(ctx.exception))
            self.assertIn("simulated non-ValueError counter failure", str(ctx.exception))

    # (c) explicit model_config_sha256 binding: positive (matching) case is the
    # ordinary round-trip; negative (tampered) case must fail closed here.
    def test_model_config_sha256_matches_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bound, receipt, config_path, manifest_path = self._bound_fixture(root, seed=707)
            self.assertIn("model_config_sha256", receipt)
            completed_loads = verify_parameter_identity_binding(
                bound, receipt,
                checkpoint_manifest=manifest_path, model_config=config_path,
            )
            self.assertEqual(completed_loads, 1)

    def test_tampered_model_config_sha256_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bound, receipt, config_path, manifest_path = self._bound_fixture(root, seed=808)
            tampered_receipt = dict(receipt)
            tampered_receipt["model_config_sha256"] = "0" * 64
            with self.assertRaisesRegex(ParameterIdentityMismatch, "model_config_sha256"):
                verify_parameter_identity_binding(
                    bound, tampered_receipt,
                    checkpoint_manifest=manifest_path, model_config=config_path,
                )

    def test_missing_model_config_sha256_field_skips_gracefully(self) -> None:
        """Back-compat: a receipt that omits model_config_sha256 entirely must not
        raise on that account (the field is checked only when present)."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bound, receipt, config_path, manifest_path = self._bound_fixture(root, seed=909)
            receipt_without_field = dict(receipt)
            del receipt_without_field["model_config_sha256"]
            # Should not raise (falls through to the rest of verification, which
            # still passes against the same real checkpoint/config).
            verify_parameter_identity_binding(
                bound, receipt_without_field,
                checkpoint_manifest=manifest_path, model_config=config_path,
            )

    # (a) specialist-routed receipts: explicit, named shared-only guard.
    def test_specialist_routed_receipt_is_explicitly_out_of_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bound, receipt, config_path, manifest_path = self._bound_fixture(root, seed=1010)
            specialist_receipt = dict(receipt)
            specialist_receipt["active_expert_ids"] = ["vision"]
            with self.assertRaisesRegex(
                ParameterIdentityMismatch, "shared-routed receipts only"
            ):
                verify_parameter_identity_binding(
                    bound, specialist_receipt,
                    checkpoint_manifest=manifest_path, model_config=config_path,
                )

    def test_explicit_specialist_active_expert_argument_is_also_rejected(self) -> None:
        """The guard covers the explicit active_expert= override too, not only the
        receipt's active_expert_ids inference."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bound, receipt, config_path, manifest_path = self._bound_fixture(root, seed=1111)
            with self.assertRaisesRegex(
                ParameterIdentityMismatch, "shared-routed receipts only"
            ):
                verify_parameter_identity_binding(
                    bound, receipt,
                    checkpoint_manifest=manifest_path, model_config=config_path,
                    active_expert="vision",
                )


if __name__ == "__main__":
    unittest.main()
