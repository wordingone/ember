# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "q2_producer_contract.py"
COMPONENT_KEYS = (
    "adapter",
    "event_inputs",
    "input_builder",
    "host_commit_probe",
    "host_commit_simulation",
    "measured_dry_run",
    "gradient_lineage",
    "model_lineage",
    "momentum_lineage",
    "muon",
    "rung2_runtime",
    "writer",
)


def _load():
    assert MODULE_PATH.exists(), "q2_producer_contract.py is not implemented"
    spec = importlib.util.spec_from_file_location("q2_producer_contract", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _fixture(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    producer = root / "producer.py"
    producer.write_text(
        'GOVERNED_VERTICAL_MODE = "governed-vertical"\n'
        "def run_governed_vertical(args):\n    return 0\n"
        "def main():\n    return run_governed_vertical(None)\n",
        encoding="utf-8",
    )
    components = {}
    for key in COMPONENT_KEYS:
        path = root / f"{key}.py"
        path.write_text(f"COMPONENT = {key!r}\n", encoding="utf-8")
        components[key] = path
    contract = {
        "schema_version": "q2-governed-producer-contract-v1",
        "source_commit": "f3c92ba984711ee34e91c6bea90713e6c89b4b4d",
        "mode": "governed-vertical",
        "producer_sha256": _sha(producer),
        "component_sha256": {key: _sha(path) for key, path in components.items()},
        "scope": "TARGET_TENSOR_COUNTERFACTUAL",
        "historical_dependencies": [],
        "claims": {
            "actual_event": False,
            "scientific_result": False,
            "whole_step": False,
            "material_loss_bridge": False,
        },
        "no_new_parallel_authority": True,
    }
    contract["contract_sha256"] = hashlib.sha256(_canonical(contract)).hexdigest()
    contract_path = root / "producer-contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    return contract_path, producer, components


def _validate(module, contract: Path, producer: Path, components: dict[str, Path]):
    return module.validate_producer_contract(
        contract_path=contract,
        source_commit="f3c92ba984711ee34e91c6bea90713e6c89b4b4d",
        producer_path=producer,
        component_paths=components,
    )


def test_validates_closed_current_governed_producer_contract(tmp_path: Path):
    module = _load()
    contract, producer, components = _fixture(tmp_path)
    result = _validate(module, contract, producer, components)
    assert result["mode"] == "governed-vertical"
    assert result["scope"] == "TARGET_TENSOR_COUNTERFACTUAL"
    assert result["claims"] == {
        "actual_event": False,
        "scientific_result": False,
        "whole_step": False,
        "material_loss_bridge": False,
    }


def test_builder_round_trips_through_independent_validator(tmp_path: Path):
    module=_load(); _contract,producer,components=_fixture(tmp_path)
    body=module.build_producer_contract(source_commit="f3c92ba984711ee34e91c6bea90713e6c89b4b4d",producer_path=producer,component_paths=components)
    path=tmp_path/"built-contract.json"; path.write_text(json.dumps(body),encoding="utf-8")
    result=_validate(module,path,producer,components)
    assert result["contract_sha256"]==body["contract_sha256"]


def test_refuses_component_or_contract_tampering(tmp_path: Path):
    module = _load()
    contract, producer, components = _fixture(tmp_path)
    components["gradient_lineage"].write_text("tampered\n", encoding="utf-8")
    with pytest.raises(module.ProducerContractRefusal, match="PRODUCER_COMPONENT_HASH_MISMATCH"):
        _validate(module, contract, producer, components)

    contract, producer, components = _fixture(tmp_path / "second")
    body = json.loads(contract.read_text(encoding="utf-8"))
    body["scope"] = "WHOLE_STEP"
    contract.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(module.ProducerContractRefusal, match="PRODUCER_CONTRACT_TAMPERED"):
        _validate(module, contract, producer, components)


@pytest.mark.parametrize(
    ("source", "code"),
    [
        (
            'import timeshare_pretrain\nGOVERNED_VERTICAL_MODE = "governed-vertical"\n'
            "def run_governed_vertical(args): return 0\ndef main(): return 0\n",
            "PRODUCER_HISTORICAL_DEPENDENCY",
        ),
        (
            'GOVERNED_VERTICAL_MODE = "governed-vertical"\ndef main(): return 0\n',
            "PRODUCER_ENTRYPOINT_INVALID",
        ),
    ],
)
def test_refuses_historical_import_or_missing_entrypoint(
    tmp_path: Path, source: str, code: str
):
    module = _load()
    contract, producer, components = _fixture(tmp_path)
    producer.write_text(source, encoding="utf-8")
    body = json.loads(contract.read_text(encoding="utf-8"))
    body["producer_sha256"] = _sha(producer)
    body.pop("contract_sha256")
    body["contract_sha256"] = hashlib.sha256(_canonical(body)).hexdigest()
    contract.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(module.ProducerContractRefusal, match=code):
        _validate(module, contract, producer, components)
