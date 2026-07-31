# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CPU-only contract tests for issue #677 optimizer-transplant provenance."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import optimizer_transplant_provenance as provenance


def _state(value: torch.Tensor) -> dict:
    return {
        "muon": {
            "state": {0: {"momentum_buffer": value}},
            "param_groups": [{"params": [0], "lr": 0.02}],
        }
    }


def _build(
    source: dict,
    destination: dict,
    *,
    transforms: dict[str, str] | None = None,
    transform_errors: dict[str, float] | None = None,
    authorized_fresh: dict[str, str] | None = None,
) -> dict:
    return provenance.build_transplant_provenance(
        source_checkpoint_sha256="a" * 64,
        transplant_method="branch-a-momentum-pushforward-v1",
        cure_version="issue-677-v1",
        build_timestamp="20260730T120000Z",
        source_optimizer_state=source,
        destination_optimizer_state=destination,
        param_names={"muon": ["layer.weight"]},
        transforms=transforms or {},
        transform_errors=transform_errors or {},
        authorized_fresh=authorized_fresh or {},
        dropped={},
        global_step=7,
        scheduler_provenance={"kind": "cosine", "step": 7},
        scaler_provenance={"enabled": False},
    )


def test_equal_rms_direction_swap_is_not_identity() -> None:
    source = _state(torch.tensor([1.0, -1.0]))
    destination = _state(torch.tensor([-1.0, 1.0]))

    with pytest.raises(provenance.ProvenanceError, match="identity transform changed bytes"):
        _build(source, destination)


def test_mapping_is_exhaustive_unique_and_authorized_fresh_is_explicit() -> None:
    source = _state(torch.tensor([1.0]))
    destination = _state(torch.tensor([1.0]))
    destination["muon"]["state"][0]["exp_avg_sq"] = torch.tensor([0.0])

    with pytest.raises(provenance.ProvenanceError, match="unmapped destination slot"):
        _build(source, destination)

    fresh_key = "muon:layer.weight:exp_avg_sq"
    manifest = _build(source, destination, authorized_fresh={fresh_key: "new accumulator slot"})
    rows = {row["mapping_key"]: row for row in manifest["mapping_rows"]}
    assert rows[fresh_key]["status"] == "authorized_fresh"
    assert rows[fresh_key]["source"] is None

    dropped_destination = {
        "muon": {"state": {}, "param_groups": [{"params": [0], "lr": 0.02}]}
    }
    dropped = provenance.build_transplant_provenance(
        source_checkpoint_sha256="a" * 64,
        transplant_method="retirement",
        cure_version="issue-677-v1",
        build_timestamp="20260730T120000Z",
        source_optimizer_state=source,
        destination_optimizer_state=dropped_destination,
        param_names={"muon": ["layer.weight"]},
        transforms={},
        transform_errors={},
        authorized_fresh={},
        dropped={"muon:layer.weight:momentum_buffer": "slot retired by policy"},
        global_step=7,
        scheduler_provenance={"kind": "none"},
        scaler_provenance={"enabled": False},
    )
    assert dropped["mapping_rows"][0]["status_reason"] == "slot retired by policy"

    with pytest.raises(provenance.ProvenanceError, match="duplicate parameter name"):
        provenance.build_transplant_provenance(
            source_checkpoint_sha256="a" * 64,
            transplant_method="x",
            cure_version="y",
            build_timestamp="20260730T120000Z",
            source_optimizer_state=source,
            destination_optimizer_state=destination,
            param_names={"muon": ["layer.weight", "layer.weight"]},
            transforms={},
            transform_errors={},
            authorized_fresh={fresh_key: "new accumulator slot"},
            dropped={},
            global_step=7,
            scheduler_provenance={"kind": "none"},
            scaler_provenance={"enabled": False},
        )


def test_replay_and_stale_sidecar_fail_closed(tmp_path: Path) -> None:
    source = _state(torch.tensor([1.0, 2.0]))
    destination = _state(torch.tensor([1.0, 2.0, 1.0, 2.0]))
    key = "muon:layer.weight:momentum_buffer"
    manifest = _build(
        source,
        destination,
        transforms={key: "row-duplication"},
        transform_errors={key: 0.0},
    )

    replay = {key: torch.tensor([1.0, 2.0, 1.0, 2.0])}
    verified = provenance.verify_transplant_provenance(
        manifest,
        source_optimizer_state=source,
        destination_optimizer_state=destination,
        param_names={"muon": ["layer.weight"]},
        replay_tensors=replay,
    )
    assert verified["deterministic_replay"]["all_destination_hashes_reproduced"] is True

    sidecar = tmp_path / "transplant-provenance.json"
    provenance.write_transplant_provenance_atomic(sidecar, verified)
    malformed = copy.deepcopy(verified)
    malformed["mapping_rows"][0]["status"] = "maybe"
    with pytest.raises(provenance.ProvenanceError, match="status is invalid"):
        provenance.write_transplant_provenance_atomic(
            tmp_path / "malformed.json", malformed
        )
    loaded = provenance.load_transplant_provenance(sidecar)
    assert loaded["provenance_sha256"] == verified["provenance_sha256"]
    assert provenance.verify_destination_optimizer_binding(loaded, destination) == loaded["destination_optimizer_state_sha256"]
    with pytest.raises(provenance.ProvenanceError, match="stale transplant provenance"):
        provenance.load_transplant_provenance(
            sidecar, expected_build_timestamp="20260730T120001Z"
        )

    bad_replay = {key: torch.tensor([1.0, 2.0, 2.0, 1.0])}
    with pytest.raises(provenance.ProvenanceError, match="replay hash mismatch"):
        provenance.verify_transplant_provenance(
            manifest,
            source_optimizer_state=source,
            destination_optimizer_state=destination,
            param_names={"muon": ["layer.weight"]},
            replay_tensors=bad_replay,
        )

    stale_destination = copy.deepcopy(destination)
    stale_destination["muon"]["state"][0]["momentum_buffer"][0] = 9.0
    with pytest.raises(provenance.ProvenanceError, match="destination optimizer hash mismatch"):
        provenance.verify_transplant_provenance(
            loaded,
            source_optimizer_state=source,
            destination_optimizer_state=stale_destination,
            param_names={"muon": ["layer.weight"]},
            replay_tensors=replay,
        )


def test_custody_publish_is_content_addressed_and_source_is_unchanged(tmp_path: Path) -> None:
    worktree = tmp_path / "disposable"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    checkpoint = worktree / "checkpoints" / "step-00000007"
    checkpoint.mkdir(parents=True)
    payloads = {
        "model.pt": b"model",
        "optimizer.pt": b"optimizer",
        "rng.pt": b"rng",
        "transplant-provenance.json": b'{"fixture":true}\n',
    }
    for name, data in payloads.items():
        (checkpoint / name).write_bytes(data)
    manifest = {
        "ticket": "TIMESHARE-CHECKPOINT",
        "step": 7,
        "files": {
            name: provenance.sha256_file(checkpoint / name)
            for name in ("model.pt", "optimizer.pt", "rng.pt")
        },
    }
    (checkpoint / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )
    before = {path.name: path.read_bytes() for path in checkpoint.iterdir()}

    result = provenance.publish_checkpoint_to_custody(
        checkpoint, tmp_path / "durable-custody"
    )

    destination = Path(result["destination_path"])
    assert destination.parent == tmp_path / "durable-custody"
    assert destination.name == result["artifact_id"]
    assert result["source_mutated"] is False
    assert {path.name: path.read_bytes() for path in checkpoint.iterdir()} == before
    custody_manifest = json.loads(
        (destination / "manifest.json").read_text(encoding="utf-8")
    )
    assert custody_manifest["custody"]["source_worktree_disposable"] is True
    assert custody_manifest["custody"]["artifact_id"] == result["artifact_id"]
    assert custody_manifest["custody"]["all_payload_hashes_preserved"] is True

    with pytest.raises(provenance.ProvenanceError, match="outside the disposable worktree"):
        provenance.publish_checkpoint_to_custody(
            checkpoint, worktree / "still-disposable"
        )


def test_resume_consumer_requires_inline_sidecar_bytes_and_custody(tmp_path: Path) -> None:
    source_state = _state(torch.tensor([1.0, 2.0]))
    destination_state = _state(torch.tensor([1.0, 2.0, 1.0, 2.0]))
    key = "muon:layer.weight:momentum_buffer"
    built = _build(
        source_state,
        destination_state,
        transforms={key: "row-duplication"},
        transform_errors={key: 0.0},
    )
    verified = provenance.verify_transplant_provenance(
        built,
        source_optimizer_state=source_state,
        destination_optimizer_state=destination_state,
        param_names={"muon": ["layer.weight"]},
        replay_tensors={key: destination_state["muon"]["state"][0]["momentum_buffer"]},
    )

    worktree = tmp_path / "disposable"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    checkpoint = worktree / "checkpoint"
    checkpoint.mkdir()
    torch.save({"w": torch.zeros(1)}, checkpoint / "model.pt")
    torch.save(destination_state, checkpoint / "optimizer.pt")
    torch.save({"cpu": torch.zeros(1, dtype=torch.uint8)}, checkpoint / "rng.pt")
    provenance.write_transplant_provenance_atomic(
        checkpoint / "transplant-provenance.json", verified
    )
    manifest = {
        "ticket": "CBASE-GROW-RUNG2-STABILIZE-LEG1-OPTIMIZER-CURE",
        "ts": "20260730T120000Z",
        "step": 7,
        "transplant_provenance_path": "transplant-provenance.json",
        "transplant_provenance_file_sha256": provenance.sha256_file(
            checkpoint / "transplant-provenance.json"
        ),
        "transplant_provenance": verified,
        "files": {
            name: provenance.sha256_file(checkpoint / name)
            for name in (
                "model.pt",
                "optimizer.pt",
                "rng.pt",
                "transplant-provenance.json",
            )
        },
    }
    (checkpoint / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )
    custody = provenance.publish_checkpoint_to_custody(
        checkpoint, tmp_path / "custody"
    )

    consumed = provenance.load_verified_custody_checkpoint(
        custody["destination_path"]
    )
    assert consumed["transplant_provenance"] == verified
    assert consumed["custody"]["artifact_id"] == Path(
        custody["destination_path"]
    ).name

    destination_manifest = Path(custody["destination_path"], "manifest.json")
    tampered = json.loads(destination_manifest.read_text(encoding="utf-8"))
    tampered["transplant_provenance"]["cure_version"] = "tampered"
    destination_manifest.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(provenance.ProvenanceError, match="inline and sidecar"):
        provenance.load_verified_custody_checkpoint(custody["destination_path"])

def test_archived_launcher_wiring_has_no_unreceipted_resume_or_source_write() -> None:
    repo = Path(__file__).resolve().parents[1]
    launcher = (repo / "scripts" / "cbase_grow_rung2_stabilize.py").read_text(
        encoding="utf-8"
    )
    trainer = (repo / "scripts" / "timeshare_pretrain.py").read_text(
        encoding="utf-8"
    )
    assert 'os.path.join(staged_ckpt_dir, "optimizer-grown.pt")' not in launcher
    assert "publish_checkpoint_to_custody(out_ckpt_dir, custody_root)" in launcher
    disabled = launcher.index("UNRECEIPTED_TRANSPLANT_BUILD_DISABLED")
    unsafe_read = launcher.index(
        "m_state, o_state, r_state, manifest = ts.load_checkpoint(seed_ckpt_dir)"
    )
    assert disabled < unsafe_read
    assert "load_verified_custody_checkpoint(ckpt_dir)" in launcher
    assert 'transplant_provenance=build.get("transplant_provenance")' in launcher
    assert 'block_receipt["transplant_provenance"] = build.get(' in launcher
    assert "# EMBER_ARTIFACT_CLASS=historical_only" in trainer
    assert "historical_only:" in trainer
