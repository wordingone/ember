# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Receipt-bound, same-byte runtime successor regressions."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import torch


ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
SCRIPT = ROOT / "scripts" / "ember_restart_eval_raw_forward.py"
COUNTS = {
    "allocated_parameters": 3_839_161_856,
    "unique_parameters": 3_839_161_856,
    "trainable_parameters": 3_839_161_856,
    "served_parameters": 3_839_161_856,
    "active_parameters": 1_020_589_568,
    "episode_trainable_parameters": 1_020_589_568,
}
EXPERTS = ("vision", "audio", "reasoning", "tool")


def _load_module():
    sys.path.insert(0, str(SCRIPT.parent))
    specification = importlib.util.spec_from_file_location("raw_forward_runtime_authority", SCRIPT)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _write_json(path: Path, value: object) -> str:
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path):
    module = _load_module()
    config = tmp_path / "config.json"
    config_sha = _write_json(config, {"architecture_revision": "ember-sparse-3b-v2"})
    genesis = {name: hashlib.sha256(f"genesis:{name}".encode()).hexdigest() for name in EXPERTS}
    manifest = tmp_path / "checkpoint-manifest.json"
    manifest_payload = {
        "schema_version": "ember-sparse-checkpoint-v3",
        "architecture_revision": "ember-sparse-3b-v2",
        "model_config_sha256": config_sha,
        "active_expert_ids": ["shared"],
        "expert_genesis_sha256": genesis,
        "expert_checkpoint_sha256": {name: hashlib.sha256(f"file:{name}".encode()).hexdigest() for name in EXPERTS},
        "shards": [
            {"path": "shared.pt", "role": "shared_model_and_optimizer", "bytes": 7, "sha256": hashlib.sha256(b"shared").hexdigest()},
            {"path": "replay-state.pt", "role": "replay_state", "bytes": 6, "sha256": hashlib.sha256(b"replay").hexdigest()},
            *[
                {"path": f"expert-{name}.pt", "role": f"expert_{name}", "bytes": len(name), "sha256": hashlib.sha256(name.encode()).hexdigest()}
                for name in EXPERTS
            ],
        ],
    }
    manifest_sha = _write_json(manifest, manifest_payload)
    counter = tmp_path / "parameter_counter.py"
    counter.write_bytes(b"independent counter source")
    counter_sha = hashlib.sha256(counter.read_bytes()).hexdigest()
    registry = tmp_path / "trusted-verifiers.json"
    _write_json(
        registry,
        {
            "schema_version": "ember-trusted-verifiers-v1",
            "verifiers": [
                {
                    "path": counter.name,
                    "sha256": counter_sha,
                    "evidence_classes": ["parameter_realization"],
                    "criterion_ids": ["ember-sparse-step2-realization-v1"],
                }
            ],
        },
    )
    receipt = tmp_path / "parameter-receipt.json"
    receipt_payload = {
        "schema_version": "ember-sparse-realization-receipt-v1",
        "verification_boundary": "VERIFIED_MEASURED",
        "result": "MEASURED",
        "model_config_sha256": config_sha,
        "subject_checkpoint_sha256": manifest_sha,
        "architecture_revision": "ember-sparse-3b-v2",
        "counter_sha256": counter_sha,
        **COUNTS,
        "active_expert_ids": ["shared"],
        "expert_genesis_sha256": genesis,
        "expert_parameter_sha256": genesis,
    }
    receipt_sha = _write_json(receipt, receipt_payload)
    _write_json(
        registry,
        {
            "schema_version": "ember-trusted-verifiers-v1",
            "verifiers": [
                {
                    "path": counter.name,
                    "sha256": counter_sha,
                    "evidence_classes": ["parameter_realization"],
                    "criterion_ids": ["ember-sparse-step2-realization-v1"],
                }
            ],
            "realization_receipts": [
                {
                    "path": receipt.name,
                    "sha256": receipt_sha,
                    "subject_checkpoint_sha256": manifest_sha,
                    "model_config_sha256": config_sha,
                    "counter_sha256": counter_sha,
                    "active_expert": "shared",
                }
            ],
        },
    )
    return module, manifest, config, receipt, counter, registry


def test_runtime_receipt_binds_checkpoint_config_counter_counts_route_and_expert_content(tmp_path):
    module, manifest, config, receipt, counter, registry = _fixture(tmp_path)
    verified = module.load_verified_runtime_contract(
        manifest_path=manifest,
        model_config_path=config,
        parameter_receipt_path=receipt,
        counter_source_path=counter,
        trusted_verifier_registry_path=registry,
        requested_route="shared",
    )
    assert verified["checkpoint_manifest_sha256"] == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert verified["model_config_sha256"] == hashlib.sha256(config.read_bytes()).hexdigest()
    assert verified["active_expert_ids"] == ["shared"]
    assert verified["required_shards"] == {"shared.pt": hashlib.sha256(b"shared").hexdigest()}


def test_runtime_contract_reads_each_authority_input_once(tmp_path, monkeypatch):
    module, manifest, config, receipt, counter, registry = _fixture(tmp_path)
    paths = (manifest, config, receipt, counter, registry)
    reads = {path: 0 for path in paths}
    original = Path.read_bytes

    def counted(path):
        if path in reads:
            reads[path] += 1
            if reads[path] > 1:
                raise AssertionError(f"runtime reopened authority input: {path.name}")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", counted)
    module.load_verified_runtime_contract(
        manifest_path=manifest,
        model_config_path=config,
        parameter_receipt_path=receipt,
        counter_source_path=counter,
        trusted_verifier_registry_path=registry,
        requested_route="shared",
    )
    assert reads == {path: 1 for path in paths}


def test_execution_authority_binds_exact_checkpoint_and_parameter_receipt(tmp_path, monkeypatch):
    module = _load_module()
    identities = {
        "model_source_sha256": "1" * 64,
        "model_config_sha256": "2" * 64,
        "tokenizer_sha256": "3" * 64,
        "checkpoint_manifest_sha256": "4" * 64,
        "parameter_receipt_sha256": "5" * 64,
        "parameter_counter_sha256": "6" * 64,
        "trusted_verifier_registry_sha256": "7" * 64,
    }
    expected = {
        **identities,
        "inference_implementation_sha256": hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
    }
    authority = tmp_path / "authority.json"
    _write_json(authority, {
        "schema_version": "ember-restart-execution-authorities-v1",
        "goal_id": "EMBER-02",
        "workstream_id": "EMBER-02C",
        "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
        "authorities": [expected],
        "disposition": "EXACT_OWNED_SHARED_ROUTE_EXECUTION_AUTHORIZED",
    })
    monkeypatch.setattr(module, "EXECUTION_AUTHORITY", authority)
    assert module.require_execution_authority(object(), identities) == expected
    missing_receipt = dict(identities)
    missing_receipt.pop("parameter_receipt_sha256")
    with pytest.raises(ValueError, match="does not authorize"):
        module.require_execution_authority(object(), missing_receipt)


def test_exact_model_source_and_config_construct_the_declared_production_shape_from_captured_bytes():
    module = _load_module()
    source_path = ROOT / "tools" / "ember-restart-3b" / "model.py"
    config_path = ROOT / "configs" / "ember-restart-3b.json"
    loaded = module._load_model_module(source_path.read_bytes(), source_path)
    contract = json.loads(config_path.read_bytes())
    config = module._config_from_payload(loaded, contract)
    default_dtype = torch.get_default_dtype()
    model = module.construct_runtime_model(torch, loaded, config, contract)
    assert torch.get_default_dtype() == default_dtype
    assert config.production is True
    assert config.structural_parameter_count() == 3_839_161_856
    assert config.declared_total_unique_trainable_parameters == 3_839_161_856
    assert {value.dtype for value in model.state_dict().values()} == {torch.bfloat16}


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update({"verification_boundary": "PROVISIONAL_NOT_TRUSTED_FOR_EXECUTION"}), "verified measured"),
        (lambda value: value.update({"subject_checkpoint_sha256": "0" * 64}), "checkpoint"),
        (lambda value: value.update({"model_config_sha256": "0" * 64}), "config"),
        (lambda value: value.update({"counter_sha256": "0" * 64}), "counter"),
        (lambda value: value.update({"active_expert_ids": ["tool"]}), "route"),
        (lambda value: value.update({"active_parameters": 1}), "count"),
        (lambda value: value["expert_genesis_sha256"].update({"vision": "0" * 64}), "genesis"),
        (lambda value: value["expert_parameter_sha256"].update({"vision": "0" * 64}), "parameter"),
    ],
)
def test_runtime_receipt_rejects_untrusted_or_mismatched_evidence(tmp_path, mutation, message):
    module, manifest, config, receipt, counter, registry = _fixture(tmp_path)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    mutation(payload)
    _write_json(receipt, payload)
    with pytest.raises(ValueError, match=message):
        module.load_verified_runtime_contract(
            manifest_path=manifest,
            model_config_path=config,
            parameter_receipt_path=receipt,
            counter_source_path=counter,
            trusted_verifier_registry_path=registry,
            requested_route="shared",
        )


def test_runtime_receipt_rejects_counter_not_admitted_by_registry(tmp_path):
    module, manifest, config, receipt, counter, registry = _fixture(tmp_path)
    payload = json.loads(registry.read_text(encoding="utf-8"))
    payload["verifiers"][0]["evidence_classes"] = ["training_data"]
    _write_json(registry, payload)
    with pytest.raises(ValueError, match="trusted parameter-realization counter"):
        module.load_verified_runtime_contract(
            manifest_path=manifest,
            model_config_path=config,
            parameter_receipt_path=receipt,
            counter_source_path=counter,
            trusted_verifier_registry_path=registry,
            requested_route="shared",
        )


@pytest.mark.parametrize("mutation", [
    lambda registry: registry.pop("realization_receipts"),
    lambda registry: registry["realization_receipts"][0].update({"sha256": "0" * 64}),
    lambda registry: registry["realization_receipts"][0].update({"subject_checkpoint_sha256": "0" * 64}),
    lambda registry: registry["realization_receipts"][0].update({"active_expert": "tool"}),
])
def test_runtime_rejects_missing_or_mismatched_content_addressed_receipt_binding(tmp_path, mutation):
    module, manifest, config, receipt, counter, registry = _fixture(tmp_path)
    payload = json.loads(registry.read_text(encoding="utf-8"))
    mutation(payload)
    _write_json(registry, payload)
    with pytest.raises(ValueError, match="content-addressed realization receipt"):
        module.load_verified_runtime_contract(
            manifest_path=manifest,
            model_config_path=config,
            parameter_receipt_path=receipt,
            counter_source_path=counter,
            trusted_verifier_registry_path=registry,
            requested_route="shared",
        )


def test_hash_and_load_uses_one_open_handle_for_digest_and_torch_load(tmp_path, monkeypatch):
    module = _load_module()
    shard = tmp_path / "shared.pt"
    shard.write_bytes(b"same bytes")
    expected = hashlib.sha256(shard.read_bytes()).hexdigest()
    opens = 0
    original_open = Path.open
    captured = {}

    def counted_open(path, *args, **kwargs):
        nonlocal opens
        if path == shard:
            opens += 1
        return original_open(path, *args, **kwargs)

    class FakeTorch:
        @staticmethod
        def load(source, **kwargs):
            assert hasattr(source, "read")
            captured["position"] = source.tell()
            captured["bytes"] = source.read()
            captured["kwargs"] = kwargs
            return {"model": {}}

    monkeypatch.setattr(Path, "open", counted_open)
    assert module.hash_and_load_torch(FakeTorch, shard, expected, device="cuda") == {"model": {}}
    assert opens == 1
    assert captured == {"position": 0, "bytes": b"same bytes", "kwargs": {"map_location": "cpu", "weights_only": True}}



def test_runtime_rejects_counter_registry_path_escape(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    module, manifest, config, receipt, counter, registry = _fixture(bundle)
    escaped_counter = tmp_path / counter.name
    counter.replace(escaped_counter)
    payload = json.loads(registry.read_text(encoding="utf-8"))
    payload["verifiers"][0]["path"] = "../parameter_counter.py"
    _write_json(registry, payload)
    with pytest.raises(ValueError, match="trusted parameter-realization counter"):
        module.load_verified_runtime_contract(
            manifest_path=manifest,
            model_config_path=config,
            parameter_receipt_path=receipt,
            counter_source_path=escaped_counter,
            trusted_verifier_registry_path=registry,
            requested_route="shared",
        )

def test_execute_rejects_out_of_vocabulary_tokens_before_model_allocation(tmp_path, monkeypatch):
    module = _load_module()
    source_bytes = b"exact source"
    constructed = []

    class FakeModelModule:
        class UnifiedDecoder:
            def __init__(self, *args, **kwargs):
                constructed.append(True)
                raise AssertionError("model allocation must not occur")

    config = type("Config", (), {"vocab_size": 4})()
    monkeypatch.setattr(module, "require_execution_authority", lambda arguments, identities: {"inference_implementation_sha256": "8" * 64})
    monkeypatch.setattr(module, "_load_model_module", lambda source, path: FakeModelModule)
    monkeypatch.setattr(module, "_config_from_payload", lambda loaded, contract: config)
    arguments = type(
        "Arguments",
        (),
        {
            "model_source": tmp_path / "model.py",
            "model_source_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "input_token_id": 4,
            "max_new_tokens": 1,
            "active_expert": "shared",
            "checkpoint_manifest": tmp_path / "checkpoint-manifest.json",
            "device": "cpu",
            "stop_token_id": 2,
        },
    )()
    checkpoint = {
        "model_config_sha256": "2" * 64,
        "tokenizer_sha256": "3" * 64,
        "checkpoint_manifest_sha256": "4" * 64,
        "parameter_receipt_sha256": "5" * 64,
        "counter_sha256": "6" * 64,
        "trusted_verifier_registry_sha256": "7" * 64,
        "model_config": {},
        "required_shards": {"shared.pt": "9" * 64},
        "active_expert_ids": ["shared"],
    }
    with pytest.raises(ValueError, match="outside model vocabulary"):
        module.execute(
            arguments,
            checkpoint,
            {"token_ids": [4], "active_expert": "shared"},
            model_source_bytes=source_bytes,
        )
    assert constructed == []

def test_materialize_state_map_moves_only_selected_model_tensors_to_execution_device():
    module = _load_module()
    moves = []

    class FakeTensor:
        def to(self, **kwargs):
            moves.append(kwargs)
            return ("moved", kwargs["device"])

    state = {"weight": FakeTensor()}
    assert module.materialize_state_map(state, "cuda") == {"weight": ("moved", "cuda")}
    assert moves == [{"device": "cuda"}]


def test_tied_embedding_checkpoint_copies_must_match_exactly():
    module = _load_module()
    state = {
        "token_embedding.weight": torch.tensor([[1.0, 2.0]], dtype=torch.bfloat16),
        "lm_head.weight": torch.tensor([[1.0, 3.0]], dtype=torch.bfloat16),
    }

    with pytest.raises(ValueError, match="tied embedding checkpoint tensors differ"):
        module.canonicalize_tied_embedding_state(torch, state, tied_embeddings=True)


def test_tied_embedding_checkpoint_copy_is_materialized_once_and_reused():
    module = _load_module()
    moves = []

    class FakeTensor:
        shape = (2, 3)
        dtype = "bfloat16"

        def __init__(self, value):
            self.value = value

        def to(self, **kwargs):
            moves.append((self.value, kwargs))
            return object()

    embedding = FakeTensor("embedding")
    state = module.canonicalize_tied_embedding_state(
        type("Torch", (), {"equal": staticmethod(lambda left, right: left.value == right.value)}),
        {
            "token_embedding.weight": embedding,
            "lm_head.weight": FakeTensor("embedding"),
            "final_norm.weight": FakeTensor("norm"),
        },
        tied_embeddings=True,
    )
    materialized = module.materialize_state_map(state, "cuda")

    assert materialized["token_embedding.weight"] is materialized["lm_head.weight"]
    assert moves == [
        ("embedding", {"device": "cuda"}),
        ("norm", {"device": "cuda"}),
    ]


def test_rebind_tied_embeddings_preserves_one_parameter_after_assign_load():
    module = _load_module()

    class TinyModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.token_embedding = torch.nn.Embedding(2, 3, device="meta")
            self.lm_head = torch.nn.Linear(3, 2, bias=False, device="meta")
            self.lm_head.weight = self.token_embedding.weight

    model = TinyModel()
    weight = torch.arange(6, dtype=torch.bfloat16).reshape(2, 3)
    state = {
        "token_embedding.weight": weight,
        "lm_head.weight": weight,
    }
    model.load_state_dict(state, strict=True, assign=True)
    module.rebind_tied_embeddings(model, tied_embeddings=True)

    assert model.token_embedding.weight is model.lm_head.weight
    assert model.token_embedding.weight.data_ptr() == model.lm_head.weight.data_ptr()
