# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
SOURCE = ROOT / "src" / "ember" / "governance" / "scripts" / "issue1947_heldout_audio.py"
SPEC = importlib.util.spec_from_file_location("issue1947_heldout_audio", SOURCE)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def make_inputs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> tuple[bytes, bytes, Path, dict[str, bytes]]:
    """A fake seed tar with 64 flac members, transcripts beside them, and a census
    whose pins are monkeypatched onto the module (the real pins bind the live seed)."""

    license_raw = b"CC-BY 4.0 fixture license\n"
    license_sha = sha(license_raw)
    selected = []
    payloads: dict[str, bytes] = {}
    members: list[tuple[str, bytes]] = []
    for index in range(64):
        raw = f"flac-{index}".encode()
        speaker, chapter = f"{1000 + index // 4}", f"{5000 + index % 4}"
        member = f"LibriSpeech/test-clean/{speaker}/{chapter}/{speaker}-{chapter}-{index:04d}.flac"
        selected.append({
            "member": member,
            "byte_count": len(raw),
            "exact_sha256": sha(raw),
            "speaker_id": speaker,
            "chapter_id": chapter,
        })
        payloads[member] = raw
        members.append((member, raw))
    members.append(("LibriSpeech/test-clean/1000/5000/1000-5000.trans.txt", b"1000-5000-0000 HELLO\n"))
    members.append(("LibriSpeech/LICENSE.TXT", license_raw))
    selected.sort(key=lambda row: row["exact_sha256"])
    seed_tar = tmp_path / "test-clean.tar.gz"
    with tarfile.open(seed_tar, "w:gz") as archive:
        for name, raw in members:
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))
    seed_tar_sha = sha(seed_tar.read_bytes())
    manifest_sha = sha(b"manifest\n")
    census = {
        "schema_version": MODULE.CENSUS_SCHEMA,
        "result": "PASS",
        "source": {
            "name": "LibriSpeech",
            "subset": "test-clean",
            "source_url": "https://example.test/test-clean.tar.gz",
            "seed_tar_sha256": seed_tar_sha,
            "seed_manifest_sha256": manifest_sha,
            "license_sha256": license_sha,
        },
        "flac_count": MODULE.EXPECTED_FLAC_COUNT,
        "unique_flac_count": MODULE.EXPECTED_UNIQUE_FLAC_COUNT,
        "trans_file_count": MODULE.EXPECTED_TRANS_FILE_COUNT,
        "trans_files_read": False,
        "speaker_count": MODULE.EXPECTED_SPEAKER_COUNT,
        "chapter_count": MODULE.EXPECTED_CHAPTER_COUNT,
        "selection_rule": MODULE.SELECTION_RULE,
        "selected_count": 64,
        "selected": selected,
    }
    census["selected_set_sha256"] = sha(canonical(selected))
    census["self_sha256"] = sha(canonical(census))
    census_raw = json.dumps(census, sort_keys=True, indent=2).encode() + b"\n"
    monkeypatch.setattr(MODULE, "CENSUS_RAW_SHA256", sha(census_raw))
    monkeypatch.setattr(MODULE, "CENSUS_SELF_SHA256", census["self_sha256"])
    monkeypatch.setattr(MODULE, "SELECTED_SET_SHA256", census["selected_set_sha256"])
    monkeypatch.setattr(MODULE, "LICENSE_SHA256", license_sha)
    monkeypatch.setattr(MODULE, "SEED_TAR_SHA256", seed_tar_sha)
    monkeypatch.setattr(MODULE, "SEED_MANIFEST_SHA256", manifest_sha)
    return census_raw, license_raw, seed_tar, payloads


def test_selected_payloads_come_only_from_flac_members(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    census_raw, _license_raw, seed_tar, payloads = make_inputs(monkeypatch, tmp_path)
    read = MODULE.read_selected_payloads(seed_tar, census_raw)
    assert read == payloads
    assert all(name.endswith(".flac") for name in read)


def test_tar_drift_refuses_before_any_member_is_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    census_raw, _license_raw, seed_tar, _payloads = make_inputs(monkeypatch, tmp_path)
    with seed_tar.open("ab") as stream:
        stream.write(b"\x00")
    with pytest.raises(ValueError, match="SEED_TAR_SHA256_DRIFT_REFUSED"):
        MODULE.read_selected_payloads(seed_tar, census_raw)


def test_admission_plan_binds_exact_64_and_never_reads_transcripts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    census_raw, license_raw, _seed_tar, payloads = make_inputs(monkeypatch, tmp_path)
    plan = MODULE.build_admission_plan(
        census_raw=census_raw,
        license_raw=license_raw,
        admitted_train_audio_hashes=set(),
        payloads_by_member=payloads,
    )
    assert plan["result"] == "PASS"
    assert plan["domain"] == "audio" and plan["split"] == "heldout"
    assert plan["transcripts_read"] is False
    assert plan["train_exclusion_assertion"] == "executed_pass"
    assert len(plan["files"]) == 64
    assert [row["sha256"] for row in plan["files"]] == sorted(row["sha256"] for row in plan["files"])
    assert all(row["path"] == f"objects/{row['sha256'][:2]}/{row['sha256']}.flac" for row in plan["files"])
    assert plan["selected_set_sha256"] == MODULE.SELECTED_SET_SHA256


def test_planted_train_overlap_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    census_raw, license_raw, _seed_tar, payloads = make_inputs(monkeypatch, tmp_path)
    planted = sha(next(iter(payloads.values())))
    with pytest.raises(ValueError, match=f"TRAIN_HELDOUT_AUDIO_OVERLAP_REFUSED:{planted}"):
        MODULE.build_admission_plan(
            census_raw=census_raw,
            license_raw=license_raw,
            admitted_train_audio_hashes={planted},
            payloads_by_member=payloads,
        )


def test_payload_drift_and_census_drift_refuse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    census_raw, license_raw, _seed_tar, payloads = make_inputs(monkeypatch, tmp_path)
    member = next(iter(payloads))
    drifted = dict(payloads)
    drifted[member] = drifted[member] + b"x"
    with pytest.raises(ValueError, match="SELECTED_AUDIO_PAYLOAD_DRIFT_REFUSED"):
        MODULE.build_admission_plan(
            census_raw=census_raw,
            license_raw=license_raw,
            admitted_train_audio_hashes=set(),
            payloads_by_member=drifted,
        )
    with pytest.raises(ValueError, match="CENSUS_RAW_SHA256_DRIFT_REFUSED"):
        MODULE.build_admission_plan(
            census_raw=census_raw + b"\n",
            license_raw=license_raw,
            admitted_train_audio_hashes=set(),
            payloads_by_member=payloads,
        )
    with pytest.raises(ValueError, match="LICENSE_SHA256_DRIFT_REFUSED"):
        MODULE.build_admission_plan(
            census_raw=census_raw,
            license_raw=license_raw + b"!",
            admitted_train_audio_hashes=set(),
            payloads_by_member=payloads,
        )


def test_artifacts_projection_and_contract_bind_the_same_64(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    census_raw, license_raw, _seed_tar, payloads = make_inputs(monkeypatch, tmp_path)
    plan = MODULE.build_admission_plan(
        census_raw=census_raw,
        license_raw=license_raw,
        admitted_train_audio_hashes=set(),
        payloads_by_member=payloads,
    )
    custody = tmp_path / "custody"
    connector_path = tmp_path / "connector.json"
    admission_path = tmp_path / "admission.json"
    connector_raw, admission_raw = MODULE.write_admission_artifacts(
        plan=plan,
        payloads_by_member=payloads,
        license_raw=license_raw,
        output_root=custody / "objects-root",
        connector_receipt_path=connector_path,
        admission_receipt_path=admission_path,
        fetched_at="2026-09-05T06:00:00Z",
    )
    connector = json.loads(connector_raw)
    assert connector["schema"] == "corpus-connector-receipt-v1"
    assert connector["source_id"] == MODULE.SOURCE_SELECTOR
    assert sha(connector["license"].encode()) == MODULE.LICENSE_SHA256
    assert len(connector["files"]) == 64
    for row in connector["files"]:
        physical = Path(connector["dest_root"]) / row["path"]
        assert sha(physical.read_bytes()) == row["sha256"]
        assert physical.stat().st_size == row["bytes"]
    admission = json.loads(admission_raw)
    assert admission["connector_receipt_raw_sha256"] == sha(connector_raw)
    with pytest.raises(ValueError, match="NO_OVERWRITE_REFUSED"):
        MODULE.write_admission_artifacts(
            plan=plan,
            payloads_by_member=payloads,
            license_raw=license_raw,
            output_root=custody / "objects-root",
            connector_receipt_path=connector_path,
            admission_receipt_path=admission_path,
            fetched_at="2026-09-05T06:00:00Z",
        )

    census_path = tmp_path / "census.json"
    census_path.write_bytes(census_raw)
    license_path = tmp_path / "LICENSE.TXT"
    license_path.write_bytes(license_raw)
    spec = json.loads(MODULE.build_projection_spec(
        connector_receipt_path=connector_path,
        connector_receipt_raw=connector_raw,
        admission_receipt_path=admission_path,
        admission_receipt_raw=admission_raw,
        census_path=census_path,
        license_path=license_path,
        tokenizer_sha256="ab" * 32,
        created_at_ms=1,
    ))
    row = spec["rows"][0]
    assert row["domain"] == "audio" and row["split"] == "heldout"
    assert row["source_id"] == MODULE.CATALOG_SOURCE_ID
    assert row["expected_source_selector"] == MODULE.SOURCE_SELECTOR
    assert row["expected_receipt_sha256"] == sha(connector_raw)
    assert row["expected_license_text_sha256"] == MODULE.LICENSE_SHA256

    dataset_id = "dataset:issue1581-bulk-heldout:" + "cd" * 32
    membership_ids = [f"membership:{MODULE.CATALOG_SOURCE_ID}:{r['sha256']}" for r in plan["files"]]
    export = {
        "records": [
            {"kind": "dataset_version", "id": dataset_id, "state": "admitted"},
            *[
                {"kind": "membership", "id": mid, "split": "heldout", "domain": "audio",
                 "admission_state": "admitted", "exact_sha256": r["sha256"]}
                for mid, r in zip(membership_ids, plan["files"])
            ],
        ],
        "edges": [
            *[{"kind": "version_membership", "from_id": dataset_id, "to_id": mid} for mid in membership_ids],
            *[{"kind": "membership_object", "from_id": mid, "to_id": f"sha256:{r['sha256']}"}
              for mid, r in zip(membership_ids, plan["files"])],
        ],
    }
    export_raw = canonical(export)
    contract = MODULE.build_audio_only_contract(
        plan, connector_receipt_raw=connector_raw,
        catalog_export_raw=export_raw, dataset_id=dataset_id,
    )
    body = dict(contract)
    assert body.pop("self_sha256") == sha(canonical(body))
    assert contract["task"]["id"] == "EXACT_AUDIO_PAYLOAD_SHA256_IDENTITY"
    assert contract["task"]["forbidden_inputs"] == MODULE.FORBIDDEN_INPUTS
    assert contract["totality"] == {"expected": 64, "observed": 64, "complete": True}
    assert {item["media_type"] for item in contract["frozen_items"]} == {"audio/flac"}
    assert contract["catalog_binding"]["membership_count"] == 64
    assert contract["source"]["connector_receipt_raw_sha256"] == sha(connector_raw)

    # A membership whose domain drifted (image instead of audio) refuses the binding.
    export["records"][1]["domain"] = "image"
    with pytest.raises(ValueError, match="AUDIO_HELDOUT_MEMBERSHIP_TOTALITY_REFUSED"):
        MODULE.build_audio_only_contract(
            plan, connector_receipt_raw=connector_raw,
            catalog_export_raw=canonical(export), dataset_id=dataset_id,
        )
