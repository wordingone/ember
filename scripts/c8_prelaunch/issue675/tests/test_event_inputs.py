# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import sys
from pathlib import Path

import pytest
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from q2_event_inputs import EventInputRefusal, admit_event_inputs


def _canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _write_json(path, value):
    value["manifest_sha256"] = hashlib.sha256(_canonical(value)).hexdigest()
    path.write_bytes(_canonical(value))


def _file(root, name, data=b"x"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"logical_path": name, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def _fixture(tmp_path):
    source = "a" * 40
    run = "q2-test"
    files = {name: _file(tmp_path, f"inputs/{name}.bin") for name in (
        "config", "seed_model", "seed_optimizer", "grown_model", "seed_manifest",
        "b1m_receipt", "b2_receipt", "pre_momentum", "grow_operator",
    )}
    refs = []
    hashes = []
    for name in ("x", "y0", "mtp"):
        path = tmp_path / f"batch/{name}.pt"
        path.parent.mkdir(exist_ok=True)
        torch.save(torch.tensor([[1, 2]], dtype=torch.int64), path)
        data = path.read_bytes()
        refs.append({"logical_path": f"batch/{name}.pt", "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)})
        hashes.append(hashlib.sha256(data).hexdigest())
    checkpoint = {"schema": "q2-event-checkpoint-input-v1", "source_commit": source, "run_id": run, "lineage_run_id": "historical-b1m", "target_name": "layers.0.gate_proj.weight", "intermediate_size": 8, "files": files}
    x = torch.tensor([[1, 2]], dtype=torch.int64)
    digest = hashlib.sha256()
    for tensor in (x, torch.ones_like(x), torch.arange(2, dtype=torch.int64).unsqueeze(0), x, x):
        digest.update(tensor.numpy().tobytes())
    content_sha = hashlib.sha256(digest.hexdigest().encode()).hexdigest()
    builder_sha = hashlib.sha256((ROOT / "q2_input_manifest_builder.py").read_bytes()).hexdigest()
    batch = {"schema": "q2-event-batch-input-v1", "source_commit": source, "run_id": run, "builder_sha256": builder_sha, "microsteps": [{"x": refs[0], "y0": refs[1], "y_mtp": [refs[2]]}], "payload_sha256": hashlib.sha256(_canonical([hashes])).hexdigest(), "batch_sha256": content_sha}
    cp = tmp_path / "checkpoint.json"; bp = tmp_path / "batch.json"
    _write_json(cp, checkpoint); _write_json(bp, batch)
    return source, run, cp, bp


def test_admits_closed_hash_bound_inputs(tmp_path):
    source, run, cp, bp = _fixture(tmp_path)
    result = admit_event_inputs(custody_root=tmp_path, checkpoint_manifest_path=cp, batch_manifest_path=bp, expected_source_commit=source, expected_run_id=run)
    assert result["microsteps"][0]["x"].tolist() == [[1, 2]]
    assert result["target_name"] == "layers.0.gate_proj.weight"
    assert result["lineage_run_id"] == "historical-b1m"


@pytest.mark.parametrize("mutation", ["tamper", "escape", "duplicate", "unknown", "identity"])
def test_refuses_nonclosed_or_foreign_inputs(tmp_path, mutation):
    source, run, cp, bp = _fixture(tmp_path)
    batch = json.loads(bp.read_text())
    if mutation == "tamper":
        (tmp_path / batch["microsteps"][0]["x"]["logical_path"]).write_bytes(b"tamper")
    elif mutation == "escape":
        row = batch["microsteps"][0]["x"]; row["logical_path"] = "../outside.pt"; batch.pop("manifest_sha256"); _write_json(bp, batch)
    elif mutation == "duplicate":
        batch["microsteps"][0]["y0"] = batch["microsteps"][0]["x"]; batch.pop("manifest_sha256"); _write_json(bp, batch)
    elif mutation == "unknown":
        batch["extra"] = True; batch.pop("manifest_sha256"); _write_json(bp, batch)
    else:
        batch["run_id"] = "foreign"; batch.pop("manifest_sha256"); _write_json(bp, batch)
    with pytest.raises(EventInputRefusal):
        admit_event_inputs(custody_root=tmp_path, checkpoint_manifest_path=cp, batch_manifest_path=bp, expected_source_commit=source, expected_run_id=run)


def test_refuses_valid_manifest_bytes_outside_custody(tmp_path):
    custody = tmp_path / "custody"
    custody.mkdir()
    source, run, cp, bp = _fixture(custody)
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    foreign_cp = foreign / "checkpoint.json"
    foreign_cp.write_bytes(cp.read_bytes())

    with pytest.raises(EventInputRefusal, match="EVENT_CHECKPOINT_OUTSIDE_CUSTODY"):
        admit_event_inputs(
            custody_root=custody,
            checkpoint_manifest_path=foreign_cp,
            batch_manifest_path=bp,
            expected_source_commit=source,
            expected_run_id=run,
        )
