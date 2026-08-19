# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""TDD coverage for the zero-step genesis-candidate producer."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import torch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

import run_vertical_slice
import parameter_counter
from model import RestartDecoderConfig
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
                "image_projection": {"input_shape": [48, 48, 3], "output_size": 2048},
                "audio_projection": {"frame_samples": 640, "output_size": 2048},
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
    model = run_vertical_slice.UnifiedDecoder(
        RestartDecoderConfig.small_for_tests(
            hidden_size=16, layers=1, attention_heads=2, vocab_size=32
        ),
        genesis_seed=123,
    )
    model_state = model.state_dict()
    shards = []
    for ordinal, name in enumerate(names):
        path = source / "checkpoint" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if name.startswith("expert-"):
            expert = name[len("expert-") : -len(".pt")]
            torch.save(
                {
                    "expert": expert,
                    "model": {
                        key: value.detach()
                        for key, value in model_state.items()
                        if f".experts.{expert}." in key
                    },
                },
                path,
            )
        else:
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


def _inventory_expert_file_hashes(inventory: Path) -> dict[str, str]:
    payload = json.loads(inventory.read_text(encoding="utf-8"))
    return {
        Path(record["path"]).stem[len("expert-") :]: record["sha256"]
        for record in payload["shards"]
        if Path(record["path"]).name.startswith("expert-")
    }


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
    monkeypatch.setattr(
        run_vertical_slice,
        "derive_expert_genesis_sha256",
        lambda **_kwargs: _inventory_expert_file_hashes(inventory),
    )
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
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation, message: str
) -> None:
    inventory = _inventory(tmp_path)
    monkeypatch.setattr(
        run_vertical_slice,
        "derive_expert_genesis_sha256",
        lambda **_kwargs: _inventory_expert_file_hashes(inventory),
    )
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


def test_genesis_producer_refuses_foreign_shard_and_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inventory = _inventory(tmp_path)
    monkeypatch.setattr(
        run_vertical_slice,
        "derive_expert_genesis_sha256",
        lambda **_kwargs: _inventory_expert_file_hashes(inventory),
    )
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


def _small_initialized_inventory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    config = RestartDecoderConfig.small_for_tests(hidden_size=16, layers=1, attention_heads=2, vocab_size=32)
    monkeypatch.setattr(
        run_vertical_slice.RestartDecoderConfig,
        "from_contract",
        classmethod(lambda _cls, _path=None: config),
    )
    config_path = tmp_path / "fixture-config.json"
    _write_json(
        config_path,
        {
            "architecture_revision": "ember-sparse-3b-v2",
            "model": {
                "hidden_size": 16,
                "layers": 1,
                "attention_heads": 2,
                "vocab_size": 32,
                "tied_embeddings": True,
                "image_projection": {"input_shape": [48, 48, 3], "output_size": 16},
                "audio_projection": {"frame_samples": 640, "output_size": 16},
                "expert_routing": {
                    "expert_names": ["vision", "audio", "reasoning", "tool"]
                },
            },
        },
    )

    initialized = run_vertical_slice.initialize_genesis_inventory(
        config_path=config_path,
        seed=83,
        output_root=tmp_path / "initialized",
    )
    assert initialized["result"] == "GENESIS_INVENTORY_INITIALIZED"
    return Path(initialized["inventory_path"])


def test_genesis_init_writes_exact_zero_step_inventory_and_joins_real_minter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        run_vertical_slice.UnifiedDecoder,
        "forward",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("forward executed")),
    )
    monkeypatch.setattr(
        torch.optim.AdamW,
        "step",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("optimizer step executed")),
    )
    inventory_path = _small_initialized_inventory(tmp_path, monkeypatch)
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    expected_names = {
        "shared-model.pt",
        "optimizer-state.pt",
        "replay-state.pt",
        "expert-vision.pt",
        "expert-audio.pt",
        "expert-reasoning.pt",
        "expert-tool.pt",
    }
    assert inventory["schema_version"] == "ember-genesis-inventory-v1"
    assert inventory["launch_seed"] == 83
    assert inventory["active_expert"] == "shared"
    assert {Path(record["path"]).name for record in inventory["shards"]} == expected_names
    for record in inventory["shards"]:
        path = inventory_path.parent / record["path"]
        assert path.stat().st_size == record["bytes"]
        assert _sha256(path) == record["sha256"]
    optimizer_payload = torch.load(
        inventory_path.parent / "checkpoint" / "optimizer-state.pt",
        map_location="cpu",
        weights_only=False,
    )
    replay_payload = torch.load(
        inventory_path.parent / "checkpoint" / "replay-state.pt",
        map_location="cpu",
        weights_only=False,
    )
    assert optimizer_payload["optimizer"]["state"] == {}
    assert replay_payload["data_cursor"] == {
        "shard": "GENESIS",
        "record_index": 0,
        "global_step": 0,
        "tokens_seen": 0,
    }
    assert set(replay_payload["rng_state"]) == {"cpu", "cuda"}

    candidate = tmp_path / "candidate"
    result = mint_genesis_candidate(
        inventory_path=inventory_path,
        output_root=candidate,
        source_commit="5" * 40,
        run_id="genesis-init-real-join",
    )
    assert result["result"] == "GENESIS_CANDIDATE_MINTED"
    assert Path(result["manifest_path"]) == candidate / "run.json"
    checkpoint = json.loads(
        (candidate / "checkpoint" / "checkpoint-manifest.json").read_text(encoding="utf-8")
    )
    assert {record["path"] for record in checkpoint["shards"]} == expected_names

    bad_root = tmp_path / "prefixed-checkpoint"
    shutil.copytree(candidate / "checkpoint", bad_root)
    bad_manifest = bad_root / "checkpoint-manifest.json"
    payload = json.loads(bad_manifest.read_text(encoding="utf-8"))
    for record in payload["shards"]:
        record["path"] = f"checkpoint/{record['path']}"
    _write_json(bad_manifest, payload)
    assert parameter_counter.main(
        [
            "--model-config",
            str(candidate / "configs" / "ember-restart-3b.json"),
            "--checkpoint-manifest",
            str(bad_manifest),
            "--active-expert",
            "shared",
        ]
    ) == 2


def test_genesis_tensor_hash_inspector_changes_on_valid_archive_mutation_and_mint_crossbinds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inventory_path = _small_initialized_inventory(tmp_path, monkeypatch)
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    config_path = inventory_path.parent / inventory["model_config"]["path"]
    checkpoint_root = inventory_path.parent / "checkpoint"
    original = parameter_counter.derive_expert_genesis_sha256(
        model_config_path=config_path,
        checkpoint_root=checkpoint_root,
    )
    audio_path = checkpoint_root / "expert-audio.pt"
    payload = torch.load(audio_path, map_location="cpu", weights_only=False)
    key = sorted(payload["model"])[0]
    payload["model"][key].view(-1)[0] += 1
    torch.save(payload, audio_path)
    changed = parameter_counter.derive_expert_genesis_sha256(
        model_config_path=config_path,
        checkpoint_root=checkpoint_root,
    )
    assert changed["audio"] != original["audio"]
    assert {name: digest for name, digest in changed.items() if name != "audio"} == {
        name: digest for name, digest in original.items() if name != "audio"
    }
    for record in inventory["shards"]:
        if record["path"] == "checkpoint/expert-audio.pt":
            record["bytes"] = audio_path.stat().st_size
            record["sha256"] = _sha256(audio_path)
    _write_json(inventory_path, inventory)
    monkeypatch.setattr(
        run_vertical_slice,
        "derive_expert_genesis_sha256",
        lambda **_kwargs: original,
    )
    with pytest.raises(ValueError, match="shared expert genesis hash mismatch: audio"):
        mint_genesis_candidate(
            inventory_path=inventory_path,
            output_root=tmp_path / "candidate",
            source_commit="5" * 40,
            run_id="stale-tensor-crossbind",
        )


def test_genesis_init_refuses_overwrite_before_model_allocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "initialized"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_text("owned", encoding="utf-8")
    monkeypatch.setattr(
        run_vertical_slice.RestartDecoderConfig,
        "from_contract",
        classmethod(
            lambda _cls, _path=None: (_ for _ in ()).throw(
                AssertionError("model allocation boundary reached")
            )
        ),
    )

    with pytest.raises(FileExistsError):
        run_vertical_slice.initialize_genesis_inventory(
            config_path=ROOT / "configs" / "ember-restart-3b.json",
            seed=83,
            output_root=target,
        )
    assert sentinel.read_text(encoding="utf-8") == "owned"


def test_genesis_init_cli_refuses_training_surface() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_vertical_slice.add_genesis_init_parser(subparsers)
    with pytest.raises(SystemExit) as error:
        parser.parse_args(
            [
                "genesis-init",
                "--config",
                str(ROOT / "configs" / "ember-restart-3b.json"),
                "--seed",
                "83",
                "--output-root",
                "unused",
                "--steps",
                "1",
            ]
        )
    assert error.value.code == 2
