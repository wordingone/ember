# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TOOLS = ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"
sys.path.insert(0, str(TOOLS))

from optimizer_transition import validate_optimizer_transition_registry, write_optimizer_transition_registry
from step2_realization_registry import write_step2_realization_registry


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class OptimizerTransitionTests(unittest.TestCase):
    def _source_authority(self, root: Path) -> tuple[Path, Path]:
        checkpoint = root / "checkpoint"
        checkpoint.mkdir()
        records = []
        for name in ("shared.pt", "replay-state.pt", "expert-vision.pt", "expert-audio.pt", "expert-reasoning.pt", "expert-tool.pt"):
            path = checkpoint / name
            path.write_bytes((name + "\n").encode("utf-8"))
            records.append({"path": name, "bytes": path.stat().st_size, "sha256": _sha(path), "role": name, "incremental_bytes": path.stat().st_size, "publication_mode": "written"})
        target_config = json.loads((ROOT / "configs" / "ember-restart-3b.json").read_bytes())
        source_config = json.loads(json.dumps(target_config))
        source_config["training"]["optimizer"] = {
            "name": "paged_8bit_adamw",
            "implementation": "bitsandbytes.optim.PagedAdamW8bit",
            "hyperparameters": dict(target_config["training"]["optimizer"]["hyperparameters"]),
            "state_format": "bitsandbytes-paged-8bit-adamw-state-dict-v1",
        }
        source_config_path = root / "source-config.json"
        source_config_path.write_text(json.dumps(source_config, sort_keys=True), encoding="utf-8")
        source_config_sha = _sha(source_config_path)
        genesis = {name: hashlib.sha256(name.encode()).hexdigest() for name in ("vision", "audio", "reasoning", "tool")}
        counts = {"allocated_parameters": 3839161856, "unique_parameters": 3839161856, "trainable_parameters": 3839161856, "served_parameters": 3839161856, "active_parameters": 1020589568, "episode_trainable_parameters": 1020589568}
        source_optimizer = source_config["training"]["optimizer"]
        manifest = {
            "schema_version": "ember-sparse-checkpoint-v3", "architecture_revision": "ember-sparse-3b-v2",
            "model_config_sha256": source_config_sha, "active_expert_ids": ["shared"], "architecture": counts,
            "expert_genesis_sha256": genesis, "expert_parameter_sha256": genesis,
            "expert_checkpoint_sha256": {name: next(row["sha256"] for row in records if row["path"] == f"expert-{name}.pt") for name in genesis},
            "optimizer_contract": source_optimizer,
            "optimizer_realization": {"implementation": source_optimizer["implementation"], "implementation_source_sha256": "a" * 64, "state_format": source_optimizer["state_format"], "optimizer_contract_sha256": hashlib.sha256(json.dumps(source_optimizer, sort_keys=True, separators=(",", ":")).encode()).hexdigest()},
            "shards": records,
        }
        manifest_path = checkpoint / "checkpoint-manifest.json"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
        counter = root / "parameter_counter.py"
        counter.write_text("# exact reviewed counter\n", encoding="utf-8")
        realization = root / "realization.json"
        realization.write_text(json.dumps({
            "schema_version": "ember-sparse-realization-receipt-v1", "verification_boundary": "VERIFIED_MEASURED", "result": "MEASURED",
            "subject_checkpoint_sha256": _sha(manifest_path), "model_config_sha256": source_config_sha, "counter_sha256": _sha(counter),
            "architecture_revision": "ember-sparse-3b-v2", "active_expert_ids": ["shared"], **counts,
            "expert_genesis_sha256": genesis, "expert_parameter_sha256": genesis,
        }, sort_keys=True), encoding="utf-8")
        source_registry = write_step2_realization_registry(root / "source-authority", receipt_path=realization, counter_path=counter, model_config_path=source_config_path)
        return checkpoint, source_registry

    def test_transition_binds_exact_model_shards_and_both_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint, source_registry = self._source_authority(root)
            registry = write_optimizer_transition_registry(root / "transition", source_registry_path=source_registry, checkpoint_root=checkpoint, target_config_path=ROOT / "configs" / "ember-restart-3b.json")
            admitted = validate_optimizer_transition_registry(registry, checkpoint_root=checkpoint, current_target_config_path=ROOT / "configs" / "ember-restart-3b.json")
            self.assertEqual(admitted["admission_kind"], "MODEL_ONLY_OPTIMIZER_CONTRACT_TRANSITION")
            self.assertFalse(admitted["optimizer_state_reused"])
            self.assertEqual(admitted["optimizer_state_disposition"], "MEMORY_MAPPED_WITH_SOURCE_SHARED_SHARD_AND_DISCARDED_WITHOUT_REUSE")
            self.assertTrue(admitted["model_state_reused"])
            self.assertEqual(admitted["source"]["optimizer_implementation"], "bitsandbytes.optim.PagedAdamW8bit")
            self.assertEqual(admitted["target"]["optimizer_implementation"], "bitsandbytes.optim.AdamW8bit")
            self.assertEqual(admitted["target"]["optimizer_placement"], "cuda_non_paged")
            target_config = json.loads((root / "transition" / "target-config.json").read_bytes())
            self.assertEqual(target_config["training"]["optimizer"]["placement"], "cuda_non_paged")
            self.assertEqual(set(admitted["model_shards"]), {"shared.pt", "replay-state.pt", "expert-vision.pt", "expert-audio.pt", "expert-reasoning.pt", "expert-tool.pt"})

    def test_transition_rejects_target_config_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint, source_registry = self._source_authority(root)
            registry = write_optimizer_transition_registry(root / "transition", source_registry_path=source_registry, checkpoint_root=checkpoint, target_config_path=ROOT / "configs" / "ember-restart-3b.json")
            drift = root / "drift.json"
            payload = json.loads((ROOT / "configs" / "ember-restart-3b.json").read_bytes())
            payload["training"]["optimizer"]["hyperparameters"]["learning_rate"] = 2e-5
            drift.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "target config"):
                validate_optimizer_transition_registry(registry, checkpoint_root=checkpoint, current_target_config_path=drift)

    def test_transition_requires_exact_parent_successor_hyperparameter_parity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint, source_registry = self._source_authority(root)
            target = json.loads((ROOT / "configs" / "ember-restart-3b.json").read_bytes())
            target["training"]["optimizer"]["hyperparameters"]["learning_rate"] = 2e-5
            target_path = root / "target-config.json"
            target_path.write_text(json.dumps(target, sort_keys=True), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hyperparameters"):
                write_optimizer_transition_registry(
                    root / "transition",
                    source_registry_path=source_registry,
                    checkpoint_root=checkpoint,
                    target_config_path=target_path,
                )

    def test_transition_writer_rejects_unrecorded_source_authority_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint, source_registry = self._source_authority(root)
            (source_registry.parent / "unrecorded.txt").write_text("not authority\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unrecorded files"):
                write_optimizer_transition_registry(root / "transition", source_registry_path=source_registry, checkpoint_root=checkpoint, target_config_path=ROOT / "configs" / "ember-restart-3b.json")
