# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cond3 increment-3 (checkpoint_save_load): the save/load path binds the cond3
identity manifest (``checkpoint.byte_sha256``) fail-closed, additive to the
existing optimizer-contract / expert-hash / ``_validated_records`` checks.

Every checkpoint in this file is a REAL tiny (non-fixture) checkpoint written by
the production ``write_checkpoint_artifacts`` path against a real
``RestartDecoderConfig.small_for_tests`` model -- never a fixture constant sha256.
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from checkpoint_artifacts import CheckpointIdentityMismatch, load_checkpoint_artifacts
from model import RestartDecoderConfig, UnifiedDecoder

# issue2015 exact-local-import:tests/ember_restart_model/domain-governance/checkpoint_fixture.py
import importlib.util as _ember_c22d7dabcd875f5a_importlib
import sys as _ember_c22d7dabcd875f5a_sys
from pathlib import Path as _ember_c22d7dabcd875f5a_Path
_ember_c22d7dabcd875f5a_path = _ember_c22d7dabcd875f5a_Path(__file__).resolve().parents[2].joinpath('tests', 'ember_restart_model', 'domain-governance', 'checkpoint_fixture.py')
if not _ember_c22d7dabcd875f5a_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:tests/ember_restart_model/domain-governance/checkpoint_fixture.py')
_ember_c22d7dabcd875f5a_aliases = ('_ember_issue2015_c22d7dabcd875f5a', 'checkpoint_fixture', 'tests.ember_restart_model.checkpoint_fixture')
_ember_c22d7dabcd875f5a_existing = []
for _ember_c22d7dabcd875f5a_alias in _ember_c22d7dabcd875f5a_aliases:
    _ember_c22d7dabcd875f5a_candidate = _ember_c22d7dabcd875f5a_sys.modules.get(_ember_c22d7dabcd875f5a_alias)
    if _ember_c22d7dabcd875f5a_candidate is not None and all(_ember_c22d7dabcd875f5a_candidate is not item for item in _ember_c22d7dabcd875f5a_existing):
        _ember_c22d7dabcd875f5a_existing.append(_ember_c22d7dabcd875f5a_candidate)
if len(_ember_c22d7dabcd875f5a_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:tests/ember_restart_model/domain-governance/checkpoint_fixture.py')
if _ember_c22d7dabcd875f5a_existing:
    _ember_c22d7dabcd875f5a_module = _ember_c22d7dabcd875f5a_existing[0]
    _ember_c22d7dabcd875f5a_observed = getattr(_ember_c22d7dabcd875f5a_module, '__file__', None)
    if _ember_c22d7dabcd875f5a_observed is None or _ember_c22d7dabcd875f5a_Path(_ember_c22d7dabcd875f5a_observed).resolve() != _ember_c22d7dabcd875f5a_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:tests/ember_restart_model/domain-governance/checkpoint_fixture.py')
else:
    _ember_c22d7dabcd875f5a_spec = _ember_c22d7dabcd875f5a_importlib.spec_from_file_location('_ember_issue2015_c22d7dabcd875f5a', _ember_c22d7dabcd875f5a_path)
    if _ember_c22d7dabcd875f5a_spec is None or _ember_c22d7dabcd875f5a_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:tests/ember_restart_model/domain-governance/checkpoint_fixture.py')
    _ember_c22d7dabcd875f5a_module = _ember_c22d7dabcd875f5a_importlib.module_from_spec(_ember_c22d7dabcd875f5a_spec)
    for _ember_c22d7dabcd875f5a_alias in _ember_c22d7dabcd875f5a_aliases:
        _ember_c22d7dabcd875f5a_prior = _ember_c22d7dabcd875f5a_sys.modules.get(_ember_c22d7dabcd875f5a_alias)
        if _ember_c22d7dabcd875f5a_prior is not None and _ember_c22d7dabcd875f5a_prior is not _ember_c22d7dabcd875f5a_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:tests/ember_restart_model/domain-governance/checkpoint_fixture.py')
        _ember_c22d7dabcd875f5a_sys.modules[_ember_c22d7dabcd875f5a_alias] = _ember_c22d7dabcd875f5a_module
    try:
        _ember_c22d7dabcd875f5a_spec.loader.exec_module(_ember_c22d7dabcd875f5a_module)
    except BaseException:
        for _ember_c22d7dabcd875f5a_alias in _ember_c22d7dabcd875f5a_aliases:
            if _ember_c22d7dabcd875f5a_sys.modules.get(_ember_c22d7dabcd875f5a_alias) is _ember_c22d7dabcd875f5a_module:
                _ember_c22d7dabcd875f5a_sys.modules.pop(_ember_c22d7dabcd875f5a_alias, None)
        raise
for _ember_c22d7dabcd875f5a_alias in _ember_c22d7dabcd875f5a_aliases:
    _ember_c22d7dabcd875f5a_prior = _ember_c22d7dabcd875f5a_sys.modules.get(_ember_c22d7dabcd875f5a_alias)
    if _ember_c22d7dabcd875f5a_prior is not None and _ember_c22d7dabcd875f5a_prior is not _ember_c22d7dabcd875f5a_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:tests/ember_restart_model/domain-governance/checkpoint_fixture.py')
    _ember_c22d7dabcd875f5a_sys.modules[_ember_c22d7dabcd875f5a_alias] = _ember_c22d7dabcd875f5a_module
write_checkpoint_artifacts = getattr(_ember_c22d7dabcd875f5a_module, 'write_checkpoint_artifacts')
# issue2015 exact-local-import-end:tests/ember_restart_model/domain-governance/checkpoint_fixture.py


def _tiny_config() -> RestartDecoderConfig:
    return RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)


def _write_real_checkpoint(root: Path, *, launch_seed: int) -> dict:
    """Write one real tiny checkpoint via the production save path. Returns its receipt."""
    config = _tiny_config()
    model = UnifiedDecoder(config, genesis_seed=launch_seed)
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
    return write_checkpoint_artifacts(
        model,
        optimizer,
        root,
        launch_seed=launch_seed,
        rng_state={
            "cpu": torch.get_rng_state().clone(),
            "cuda": (torch.cuda.get_rng_state().clone() if torch.cuda.is_available() else torch.tensor([1, 2, 3], dtype=torch.uint8)),
        },
        data_cursor={"shard": "cond3-identity-roundtrip", "record_index": 0, "global_step": 0, "tokens_seen": 0},
        model_config_sha256="c" * 64,
        contract_sha256="d" * 64,
        expert_genesis_sha256=model.expert_bank_genesis_hashes(),
    )


class CheckpointIdentityRoundtripTests(unittest.TestCase):
    def test_save_emits_a_disk_rederived_byte_sha256_and_load_passes(self) -> None:
        """Write a real checkpoint -> the emitted manifest's byte_sha256 equals an
        INDEPENDENT disk re-hash (never the value the module happens to carry
        in-process) -> load succeeds and does not disturb the existing checks."""
        config = _tiny_config()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "checkpoint-0001"
            receipt = _write_real_checkpoint(root, launch_seed=11)

            self.assertIn("checkpoint", receipt)
            self.assertIn("byte_sha256", receipt["checkpoint"])
            emitted = receipt["checkpoint"]["byte_sha256"]
            self.assertRegex(emitted, r"^[0-9a-f]{64}$")

            # Independent re-derivation: re-open the published manifest bytes from
            # disk with a fresh hashlib instance, never reusing any in-process value.
            independent_rehash = hashlib.sha256((root / "checkpoint-manifest.json").read_bytes()).hexdigest()
            self.assertEqual(emitted, independent_rehash)

            restored = UnifiedDecoder(config, genesis_seed=99)
            restore_optimizer = torch.optim.AdamW(restored.parameters(), lr=1e-4)
            load_checkpoint_artifacts(restored, restore_optimizer, root, receipt)
            self.assertEqual(restored.active_expert, receipt["active_expert_ids"][0])

    def test_load_fails_closed_when_a_payload_byte_is_tampered_on_disk(self) -> None:
        """(a) Tamper one on-disk payload byte -> load raises before any mutation."""
        config = _tiny_config()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "checkpoint-0001"
            receipt = _write_real_checkpoint(root, launch_seed=13)

            shared_record = next(
                record for record in receipt["shards"] if record["role"] == "shared_model"
            )
            shared_path = root / shared_record["path"]
            raw = bytearray(shared_path.read_bytes())
            raw[0] ^= 0xFF
            shared_path.write_bytes(bytes(raw))

            restored = UnifiedDecoder(config, genesis_seed=100)
            restore_optimizer = torch.optim.AdamW(restored.parameters(), lr=1e-4)
            pristine_state = {name: tensor.clone() for name, tensor in restored.state_dict().items()}
            with self.assertRaises(ValueError):
                load_checkpoint_artifacts(restored, restore_optimizer, root, receipt)
            for name, tensor in restored.state_dict().items():
                self.assertTrue(torch.equal(tensor, pristine_state[name]), f"{name} mutated despite fail-closed tamper")

    def test_load_fails_closed_when_the_recorded_byte_sha256_is_forged(self) -> None:
        """(b) Forge the recorded checkpoint.byte_sha256 -> load raises
        CheckpointIdentityMismatch even though every OTHER existing check
        (optimizer contract, expert hashes, per-shard _validated_records,
        checkpoint_manifest_sha256) still independently passes -- this isolates
        the NEW identity-binding mechanism from the pre-existing ones."""
        config = _tiny_config()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "checkpoint-0001"
            receipt = _write_real_checkpoint(root, launch_seed=17)

            forged_receipt = dict(receipt)
            forged_receipt["checkpoint"] = {"byte_sha256": "0" * 64}
            self.assertNotEqual(forged_receipt["checkpoint"]["byte_sha256"], receipt["checkpoint"]["byte_sha256"])

            restored = UnifiedDecoder(config, genesis_seed=101)
            restore_optimizer = torch.optim.AdamW(restored.parameters(), lr=1e-4)
            pristine_state = {name: tensor.clone() for name, tensor in restored.state_dict().items()}
            with self.assertRaisesRegex(CheckpointIdentityMismatch, "checkpoint identity mismatch"):
                load_checkpoint_artifacts(restored, restore_optimizer, root, forged_receipt)
            for name, tensor in restored.state_dict().items():
                self.assertTrue(torch.equal(tensor, pristine_state[name]), f"{name} mutated despite fail-closed forged identity")

    def test_load_fails_closed_when_the_identity_manifest_binding_is_deleted(self) -> None:
        """(c) Delete the manifest binding (the receipt's ``checkpoint`` key) ->
        load raises CheckpointIdentityMismatch naming the absence, never a
        silent load-as-unverified."""
        config = _tiny_config()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "checkpoint-0001"
            receipt = _write_real_checkpoint(root, launch_seed=19)

            stripped_receipt = dict(receipt)
            del stripped_receipt["checkpoint"]
            self.assertNotIn("checkpoint", stripped_receipt)

            restored = UnifiedDecoder(config, genesis_seed=102)
            restore_optimizer = torch.optim.AdamW(restored.parameters(), lr=1e-4)
            pristine_state = {name: tensor.clone() for name, tensor in restored.state_dict().items()}
            with self.assertRaisesRegex(CheckpointIdentityMismatch, "missing a cond3 identity manifest binding"):
                load_checkpoint_artifacts(restored, restore_optimizer, root, stripped_receipt)
            for name, tensor in restored.state_dict().items():
                self.assertTrue(torch.equal(tensor, pristine_state[name]), f"{name} mutated despite fail-closed missing identity")

    def test_existing_optimizer_and_expert_hash_validation_is_untouched(self) -> None:
        """The existing v3/v4 receipt checks (optimizer contract required, expert
        hashes required) still fire exactly as before -- the identity binding is
        additive, not a replacement."""
        config = _tiny_config()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "checkpoint-0001"
            receipt = _write_real_checkpoint(root, launch_seed=23)

            missing_contract_receipt = dict(receipt)
            del missing_contract_receipt["optimizer_contract"]
            restored = UnifiedDecoder(config, genesis_seed=103)
            restore_optimizer = torch.optim.AdamW(restored.parameters(), lr=1e-4)
            with self.assertRaisesRegex(ValueError, "optimizer contract"):
                load_checkpoint_artifacts(restored, restore_optimizer, root, missing_contract_receipt)


if __name__ == "__main__":
    unittest.main()
