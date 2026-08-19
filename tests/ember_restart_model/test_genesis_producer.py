# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TDD coverage for the zero-step genesis-candidate producer."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

from run_vertical_slice import mint_genesis_candidate


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def _inventory(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    config = source / "config.json"
    _write_json(
        config,
        {
            "contract_name": "ember-restart-3b",
            "contract_version": 3,
            "architecture_revision": "ember-sparse-3b-v2",
            "model": {
                "hidden_size": 2048,
                "layers": 14,
                "attention_heads": 16,
                "vocab_size": 32000,
                "tied_embeddings": True,
                "image_projection": {"input_shape": [48, 48, 3]},
                "audio_projection": {"frame_samples": 640},
                "expert_routing": {
                    "expert_names": ["vision", "audio", "reasoning", "tool"],
                    "shared_text_ffn": "always_active_SwiGLU_4H",
                },
                "total_unique_trainable_parameters": 3839161856,
            },
        },
    )
    counter = source / "counter.py"
    counter.write_text(
        """import argparse, hashlib, json
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('--model-config'); p.add_argument('--checkpoint-manifest'); p.add_argument('--active-expert'); a=p.parse_args()
m=json.loads(Path(a.checkpoint_manifest).read_text(encoding='utf-8'))
print(json.dumps({'schema_version':'ember-sparse-realization-receipt-v1','verification_boundary':'VERIFIED_MEASURED','result':'MEASURED','model_config_sha256':hashlib.sha256(Path(a.model_config).read_bytes()).hexdigest(),'subject_checkpoint_sha256':hashlib.sha256(Path(a.checkpoint_manifest).read_bytes()).hexdigest(),'architecture_revision':'ember-sparse-3b-v2','counter_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'allocated_parameters':3839161856,'unique_parameters':3839161856,'trainable_parameters':3839161856,'served_parameters':3839161856,'active_parameters':1020589568,'episode_trainable_parameters':1020589568,'active_expert_ids':([a.active_expert] if a.active_expert else []),'expert_genesis_sha256':m['expert_genesis_sha256'],'expert_parameter_sha256':m['expert_genesis_sha256'],'runtime_authority':{'schema_version':'ember-counter-runtime-authority-v1','kind':'NONE'}},sort_keys=True))
""",
        encoding="utf-8",
    )
    names = (
        "shared-model.pt",
        "optimizer-state.pt",
        "replay-state.pt",
        "expert-vision.pt",
        "expert-audio.pt",
        "expert-reasoning.pt",
        "expert-tool.pt",
    )
    shards = []
    for ordinal, name in enumerate(names):
        path = source / "checkpoint" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"owned-init-{ordinal}-{name}".encode())
        shards.append({"path": f"checkpoint/{name}", "bytes": path.stat().st_size, "sha256": _sha256(path)})
    inventory = source / "inventory.json"
    _write_json(
        inventory,
        {
            "schema_version": "ember-genesis-inventory-v1",
            "launch_seed": 123,
            "active_expert": "shared",
            "model_config": {"path": "config.json", "sha256": _sha256(config)},
            "parameter_counter": {"path": "counter.py", "sha256": _sha256(counter)},
            "shards": shards,
        },
    )
    return inventory


def _register_custody(candidate: Path) -> Path:
    from scripts import artifact_custody_gate as gate

    binary = gate.canonical_ember_lab_binary(ROOT)
    if binary is None:
        pytest.skip("ember-lab binary is unavailable")
    checkpoint = json.loads((candidate / "checkpoint" / "checkpoint-manifest.json").read_text(encoding="utf-8"))
    database = candidate.parent / "custody.sqlite3"
    for shard in checkpoint["shards"]:
        completed = subprocess.run(
            [
                str(binary), "register-artifact", "--db", str(database),
                "--sha256", shard["sha256"], "--byte-count", str(shard["bytes"]),
                "--media-type", "application/octet-stream",
                "--location", f"{gate.RESUME_CHECKPOINT_VOLUME}={shard['path']}",
            ],
            capture_output=True,
            text=True,
            check=False,
            creationflags=(getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0),
        )
        assert completed.returncode == 0, completed.stderr
    return database


def test_genesis_producer_mints_physical_manifest_last_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inventory = _inventory(tmp_path)
    target = tmp_path / "custody" / "genesis"
    result = mint_genesis_candidate(
        inventory_path=inventory,
        output_root=target,
        source_commit="5" * 40,
        run_id="genesis-real-join-test",
    )

    manifest_path = Path(result["manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checkpoint = json.loads((target / manifest["checkpoint"]["manifest_path"]).read_text(encoding="utf-8"))
    assert result["result"] == "GENESIS_CANDIDATE_MINTED"
    assert manifest["stage"] == "GENESIS_CANDIDATE"
    assert checkpoint["data_cursor"] == {"shard": "GENESIS", "record_index": 0, "global_step": 0, "tokens_seen": 0}
    assert manifest["genesis_claim_boundary"]["optimizer_steps"] == 0
    assert not any(target.parent.glob(".genesis.staging-*"))

    from scripts.ember_restart import contract

    custody_db = _register_custody(target)
    validated = contract.validate_manifest(
        manifest_path,
        target / "trusted-verifiers.json",
        custody_db=custody_db,
    )
    assert validated == {"valid": True, "stage": "GENESIS_CANDIDATE", "errors": []}

    monkeypatch.setattr(contract, "_current_source_commit", lambda _root: "5" * 40)
    monkeypatch.setattr(contract, "_require_clean_source_tree", lambda _root: None)
    monkeypatch.setattr(
        contract,
        "_git_blob_sha256",
        lambda root, _commit, relative: _sha256(Path(root) / relative),
    )
    monkeypatch.setattr(
        contract.source_authority,
        "bind_source_identity",
        lambda *_args, **_kwargs: {"test_seam": "physical producer join"},
    )
    entry = contract.build_r1_warm100_entry(
        manifest_path,
        source_commit="5" * 40,
        source_root=ROOT,
        prereg_path=ROOT / "docs/spec/ember02-preregistration-v1.md",
        config_path=ROOT / "configs/ember-restart-3b.json",
        fixed_prior_path=ROOT / "manifests/ember-restart-3b/fixed-prior-manifest-v1.json",
        trusted_verifier_registry=target / "trusted-verifiers.json",
        custody_db=custody_db,
    )
    from scripts.ember_restart import r1_launch_packet

    r1_launch_packet._validate_entry_shape(entry)
    assert entry["result"] == "PREP_ONLY"
    assert entry["steps"] == 100


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload.update({"resume_checkpoint": "old"}), "closed schema"),
        (lambda payload: payload.update({"global_step": 1}), "closed schema"),
        (lambda payload: payload.update({"optimizer_steps": 1}), "closed schema"),
        (lambda payload: payload.update({"training_executed": True}), "closed schema"),
        (lambda payload: payload.update({"capability": True}), "closed schema"),
        (lambda payload: payload["shards"].pop(), "closed shard inventory"),
    ],
)
def test_genesis_producer_refuses_continuation_widening_and_incomplete_inventory(
    tmp_path: Path, mutation, message: str
) -> None:
    inventory = _inventory(tmp_path)
    payload = json.loads(inventory.read_text(encoding="utf-8"))
    mutation(payload)
    _write_json(inventory, payload)
    with pytest.raises(ValueError, match=message):
        mint_genesis_candidate(
            inventory_path=inventory,
            output_root=tmp_path / "custody" / "genesis",
            source_commit="5" * 40,
            run_id="refusal",
        )


def test_genesis_producer_refuses_foreign_shard_and_overwrite(tmp_path: Path) -> None:
    inventory = _inventory(tmp_path)
    foreign = inventory.parent / "checkpoint" / "foreign.pt"
    foreign.write_bytes(b"not-declared")
    with pytest.raises(ValueError, match="foreign shard"):
        mint_genesis_candidate(
            inventory_path=inventory,
            output_root=tmp_path / "custody" / "genesis",
            source_commit="5" * 40,
            run_id="foreign",
        )
    foreign.unlink()
    target = tmp_path / "custody" / "genesis"
    mint_genesis_candidate(
        inventory_path=inventory,
        output_root=target,
        source_commit="5" * 40,
        run_id="first",
    )
    with pytest.raises(FileExistsError):
        mint_genesis_candidate(
            inventory_path=inventory,
            output_root=target,
            source_commit="5" * 40,
            run_id="second",
        )
