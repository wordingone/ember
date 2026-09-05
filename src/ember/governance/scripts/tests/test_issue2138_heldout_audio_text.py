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
SOURCE = ROOT / "src" / "ember" / "governance" / "scripts" / "issue2138_heldout_audio_text.py"
SPEC = importlib.util.spec_from_file_location("issue2138_heldout_audio_text", SOURCE)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# Three utterances across two chapters (two speakers); chapter 1837 carries an extra
# non-selected utterance so the transcript reader has to select by id, not by file.
UTTERANCES = {
    "1995-1837-0010": ("1995", "1837", b"flac-a", "HE BEGAN A CONFUSED  COMPLAINT"),
    "1995-1837-0011": ("1995", "1837", b"flac-b", "STUFF IT INTO YOU HIS BELLY COUNSELLED HIM"),
    "2300-131720-0000": ("2300", "131720", b"flac-c", "CONCORD RETURNED TO ITS PLACE"),
}
NOT_SELECTED = ("1995-1837-0012", "AN UNSELECTED LINE")
LICENSE_RAW = b"CC BY 4.0 fixture\n"


def _member(utterance_id: str) -> str:
    speaker, chapter = utterance_id.split("-")[:2]
    return f"LibriSpeech/test-clean/{speaker}/{chapter}/{utterance_id}.flac"


def _write_seed_tar(root: Path, *, drop_line: str | None = None, duplicate_line: str | None = None) -> Path:
    chapters: dict[tuple[str, str], list[str]] = {}
    for utterance_id, (speaker, chapter, _flac, text) in UTTERANCES.items():
        if utterance_id != drop_line:
            chapters.setdefault((speaker, chapter), []).append(f"{utterance_id} {text}")
        if utterance_id == duplicate_line:
            chapters.setdefault((speaker, chapter), []).append(f"{utterance_id} {text}")
    chapters[("1995", "1837")].append(f"{NOT_SELECTED[0]} {NOT_SELECTED[1]}")
    tar_path = root / "test-clean.tar.gz"
    with tarfile.open(tar_path, "w:gz") as archive:
        for utterance_id, (speaker, chapter, flac, _text) in UTTERANCES.items():
            info = tarfile.TarInfo(_member(utterance_id))
            info.size = len(flac)
            archive.addfile(info, io.BytesIO(flac))
        for (speaker, chapter), lines in chapters.items():
            raw = ("\n".join(lines) + "\n").encode()
            info = tarfile.TarInfo(f"LibriSpeech/test-clean/{speaker}/{chapter}/{speaker}-{chapter}.trans.txt")
            info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))
    return tar_path


def _audio_census_raw() -> bytes:
    selected = sorted(
        (
            {
                "byte_count": len(flac), "chapter_id": chapter, "exact_sha256": sha(flac),
                "member": _member(utterance_id), "speaker_id": speaker,
            }
            for utterance_id, (speaker, chapter, flac, _text) in UTTERANCES.items()
        ),
        key=lambda row: row["exact_sha256"],
    )
    census = {
        "schema_version": MODULE.AUDIO_CENSUS_SCHEMA,
        "result": "PASS",
        "selected": selected,
        "selected_count": len(selected),
        "selected_set_sha256": sha(canonical(sorted(row["exact_sha256"] for row in selected))),
    }
    census["self_sha256"] = sha(canonical(census))
    return json.dumps(census, sort_keys=True, indent=2).encode() + b"\n"


def _predecessor_connector(root: Path) -> tuple[Path, bytes]:
    custody = root / "audio-custody"
    files = []
    for _utterance_id, (_speaker, _chapter, flac, _text) in UTTERANCES.items():
        digest = sha(flac)
        path = custody / "objects" / digest[:2] / f"{digest}.flac"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(flac)
        files.append({"path": f"objects/{digest[:2]}/{digest}.flac", "bytes": len(flac), "sha256": digest})
    raw = json.dumps({
        "schema": "corpus-connector-receipt-v1",
        "source_id": MODULE.PREDECESSOR_AUDIO_SOURCE_ID,
        "dest_root": str(custody),
        "files": sorted(files, key=lambda row: row["sha256"]),
    }, sort_keys=True, indent=2).encode() + b"\n"
    receipt = root / "predecessor-connector.json"
    receipt.write_bytes(raw)
    return receipt, raw


def _predecessor_contract_raw(*, drop_one: bool = False) -> bytes:
    frozen = [
        {"byte_count": len(flac), "gold_object_sha256": sha(flac), "item_id": f"sha256:{sha(flac)}", "media_type": "audio/flac"}
        for _u, (_s, _c, flac, _t) in UTTERANCES.items()
    ]
    if drop_one:
        frozen = frozen[1:]
    n = len(UTTERANCES)
    contract = {
        "schema_version": MODULE.PREDECESSOR_CONTRACT_SCHEMA,
        "result": "PASS",
        "frozen_items": sorted(frozen, key=lambda row: row["gold_object_sha256"]),
        "totality": {"expected": n, "observed": n, "complete": True},
    }
    contract["self_sha256"] = sha(canonical(contract))
    return json.dumps(contract, sort_keys=True).encode()


@pytest.fixture
def inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    tar_path = _write_seed_tar(tmp_path)
    audio_census_raw = _audio_census_raw()
    audio_census = json.loads(audio_census_raw)
    monkeypatch.setattr(MODULE, "EXPECTED_ITEM_COUNT", len(UTTERANCES))
    monkeypatch.setattr(MODULE, "EXPECTED_ADMITTED_HELDOUT_AUDIO_COUNT", len(UTTERANCES))
    monkeypatch.setattr(MODULE, "SEED_TAR_SHA256", sha(tar_path.read_bytes()))
    monkeypatch.setattr(MODULE, "LICENSE_SHA256", sha(LICENSE_RAW))
    monkeypatch.setattr(MODULE, "AUDIO_CENSUS_RAW_SHA256", sha(audio_census_raw))
    monkeypatch.setattr(MODULE, "AUDIO_CENSUS_SELF_SHA256", audio_census["self_sha256"])
    monkeypatch.setattr(MODULE, "AUDIO_SELECTED_SET_SHA256", audio_census["selected_set_sha256"])
    predecessor_path, predecessor_raw = _predecessor_connector(tmp_path)
    audio_hashes = {sha(flac) for _u, (_s, _c, flac, _t) in UTTERANCES.items()}
    return {
        "tar": tar_path, "audio_census_raw": audio_census_raw, "predecessor_path": predecessor_path,
        "predecessor_raw": predecessor_raw, "audio_hashes": audio_hashes, "tmp": tmp_path,
    }


def _census(inputs, *, train: set[str] | None = None):
    items, read = MODULE.read_transcripts(inputs["tar"], inputs["audio_census_raw"])
    payloads = MODULE.read_predecessor_audio_payloads(inputs["predecessor_raw"], items)
    census = MODULE.build_census(
        items=items, trans_files_read=read, license_raw=LICENSE_RAW,
        audio_census_raw=inputs["audio_census_raw"], predecessor_connector_raw=inputs["predecessor_raw"],
        audio_payloads=payloads, admitted_train_object_hashes=train or {sha(b"some-train-object")},
        admitted_heldout_audio_hashes=inputs["audio_hashes"],
    )
    return items, census


def test_census_pairs_each_utterance_with_its_transcript_and_executes_train_exclusion(inputs) -> None:
    items, census = _census(inputs)
    MODULE.verify_census(census)
    assert census["trans_files_read"] == 2
    assert census["item_count"] == 3 and census["item_text_object_count"] == 3
    assert census["train_intersection"] == {"executed": True, "admitted_train_object_count": 1, "count": 0}
    by_id = {item["item_id"]: item for item in census["items"]}
    assert list(by_id) == sorted(UTTERANCES)
    for utterance_id, (speaker, chapter, flac, text) in UTTERANCES.items():
        row = by_id[utterance_id]
        expected_text = MODULE.transcript_text_object(utterance_id, " ".join(text.split()))
        assert json.loads(expected_text) == {"transcript": " ".join(text.split()), "utterance_id": utterance_id}
        assert row["audio_object"] == {"sha256": sha(flac), "byte_count": len(flac), "media_type": "audio/flac"}
        assert row["item_text_object"]["sha256"] == sha(expected_text)
        assert row["gold_item_sha256"] == sha(flac + expected_text)
        assert row["speaker_id"] == speaker and row["chapter_id"] == chapter
    assert census["admitted_object_set_sha256"] == sha(canonical(sorted(row["item_text_object"]["sha256"] for row in census["items"])))
    assert NOT_SELECTED[0] not in by_id


def test_planted_train_hash_refuses_the_census(inputs) -> None:
    items, _ = _census(inputs)
    planted = {items[0]["text_sha256"]}
    with pytest.raises(ValueError, match="TRAIN_HELDOUT_OBJECT_OVERLAP_REFUSED"):
        _census(inputs, train=planted)
    with pytest.raises(ValueError, match="TRAIN_HELDOUT_OBJECT_OVERLAP_REFUSED"):
        _census(inputs, train={items[0]["audio_sha256"]})


def test_missing_or_duplicated_transcript_line_refuses(tmp_path: Path, inputs, monkeypatch: pytest.MonkeyPatch) -> None:
    for kwargs, expected in (
        ({"drop_line": "1995-1837-0011"}, "TRANSCRIPT_LINE_TOTALITY_REFUSED:1995-1837-0011:0"),
        ({"duplicate_line": "2300-131720-0000"}, "TRANSCRIPT_LINE_TOTALITY_REFUSED:2300-131720-0000:2"),
    ):
        sub = tmp_path / next(iter(kwargs))
        sub.mkdir(parents=True)
        tar_path = _write_seed_tar(sub, **kwargs)
        monkeypatch.setattr(MODULE, "SEED_TAR_SHA256", sha(tar_path.read_bytes()))
        with pytest.raises(ValueError, match=expected):
            MODULE.read_transcripts(tar_path, inputs["audio_census_raw"])


def test_seed_tar_and_audio_census_drift_refuse_before_any_read(inputs, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(MODULE, "SEED_TAR_SHA256", "0" * 64)
    with pytest.raises(ValueError, match="SEED_TAR_SHA256_DRIFT_REFUSED"):
        MODULE.read_transcripts(inputs["tar"], inputs["audio_census_raw"])
    with pytest.raises(ValueError, match="AUDIO_CENSUS_RAW_SHA256_DRIFT_REFUSED"):
        MODULE.read_transcripts(inputs["tar"], inputs["audio_census_raw"] + b" ")


def test_plan_artifacts_projection_and_contract_bind_totality(inputs) -> None:
    tmp = inputs["tmp"]
    items, census = _census(inputs)
    payloads = MODULE.payloads_from_items(items)
    plan = MODULE.build_admission_plan(census, payloads_by_sha=payloads)
    assert plan["selected_set_sha256"] == census["admitted_object_set_sha256"]
    assert plan["rows"] == [{
        "domain": "text", "source_id": MODULE.TEXT_SOURCE_ID,
        "catalog_source_id": MODULE.CATALOG_TEXT_SOURCE_ID, "file_count": 3,
    }]
    out = tmp / "out"
    text_raw, admission_raw = MODULE.write_admission_artifacts(
        plan=plan, payloads_by_sha=payloads, license_raw=LICENSE_RAW, output_root=out / "custody",
        text_connector_path=out / "connector-transcripts.json", admission_receipt_path=out / "admission.json",
        fetched_at="2026-09-05T12:00:00Z",
    )
    connector = json.loads(text_raw)
    assert connector["source_id"] == MODULE.TEXT_SOURCE_ID and len(connector["files"]) == 3
    for row in connector["files"]:
        physical = Path(connector["dest_root"]) / row["path"]
        assert sha(physical.read_bytes()) == row["sha256"]
        assert set(json.loads(physical.read_bytes())) == {"utterance_id", "transcript"}
    admission = json.loads(admission_raw)
    assert admission["text_connector_receipt_raw_sha256"] == sha(text_raw)
    with pytest.raises(ValueError, match="NO_OVERWRITE_REFUSED"):
        MODULE.write_admission_artifacts(
            plan=plan, payloads_by_sha=payloads, license_raw=LICENSE_RAW, output_root=out / "custody",
            text_connector_path=out / "connector-transcripts.json", admission_receipt_path=out / "admission.json",
            fetched_at="2026-09-05T12:00:00Z",
        )
    spec = json.loads(MODULE.build_projection_spec(
        text_connector_path=out / "connector-transcripts.json", text_connector_raw=text_raw,
        admission_receipt_path=out / "admission.json", admission_receipt_raw=admission_raw,
        census_path=tmp / "census.json", census_raw=canonical(census), audio_census_path=tmp / "audio-census.json",
        license_path=tmp / "LICENSE", tokenizer_sha256="a" * 64, created_at_ms=1,
    ))
    assert [row["domain"] for row in spec["rows"]] == ["text"]
    assert spec["rows"][0]["expected_receipt_sha256"] == sha(text_raw)
    assert spec["rows"][0]["split"] == "heldout"

    contract = MODULE.build_audio_text_contract(
        census, text_connector_raw=text_raw, predecessor_connector_raw=inputs["predecessor_raw"],
        predecessor_contract_raw=_predecessor_contract_raw(),
    )
    assert contract["totality"] == {"expected": 3, "observed": 3, "complete": True}
    assert contract["task"]["id"] == MODULE.TASK_ID
    assert contract["task"]["forbidden_inputs"] == ["speaker_metadata", "chapter_metadata", "prediction_custody"]
    assert contract["source"]["connector_receipt_raw_sha256s"] == sorted([sha(text_raw), sha(inputs["predecessor_raw"])])
    for frozen in contract["frozen_items"]:
        assert set(frozen) == {"item_id", "gold_item_sha256", "audio_object", "item_text_object"}
    body = dict(contract)
    assert body.pop("self_sha256") == sha(canonical(body))

    with pytest.raises(ValueError, match="PREDECESSOR_AUDIO_COVERAGE_REFUSED"):
        MODULE.build_audio_text_contract(
            census, text_connector_raw=text_raw, predecessor_connector_raw=inputs["predecessor_raw"],
            predecessor_contract_raw=_predecessor_contract_raw(drop_one=True),
        )
    short = json.loads(text_raw)
    short["files"] = short["files"][1:]
    with pytest.raises(ValueError, match="AUDIO_TEXT_CONNECTOR_COVERAGE_REFUSED"):
        MODULE.build_audio_text_contract(
            census, text_connector_raw=json.dumps(short).encode(), predecessor_connector_raw=inputs["predecessor_raw"],
            predecessor_contract_raw=_predecessor_contract_raw(),
        )
    with pytest.raises(ValueError, match="AUDIO_TEXT_CATALOG_BINDING_ARGUMENT_TOTALITY_REFUSED"):
        MODULE.build_audio_text_contract(
            census, text_connector_raw=text_raw, predecessor_connector_raw=inputs["predecessor_raw"],
            predecessor_contract_raw=_predecessor_contract_raw(), dataset_ids=["dataset:x"],
        )


def test_catalog_binding_requires_both_dataset_memberships(inputs) -> None:
    items, census = _census(inputs)
    payloads = MODULE.payloads_from_items(items)
    text_raw = MODULE._connector(
        source_id=MODULE.TEXT_SOURCE_ID,
        files=MODULE.build_admission_plan(census, payloads_by_sha=payloads)["text_files"],
        dest_root=inputs["tmp"], license_raw=LICENSE_RAW, upstream_url=MODULE.SOURCE_URL,
        fetched_at="2026-09-05T12:00:00Z",
    )
    audio_ds, text_ds = "dataset:heldout:audio", "dataset:heldout:text"
    records = [
        {"kind": "dataset_version", "id": audio_ds, "state": "admitted"},
        {"kind": "dataset_version", "id": text_ds, "state": "admitted"},
    ]
    edges = []
    for index, item in enumerate(census["items"]):
        for domain, digest, dataset in (
            ("audio", item["audio_object"]["sha256"], audio_ds),
            ("text", item["item_text_object"]["sha256"], text_ds),
        ):
            membership = f"membership:{domain}:{index}"
            records.append({"kind": "membership", "id": membership, "split": "heldout", "admission_state": "admitted", "domain": domain})
            edges.append({"kind": "version_membership", "from_id": dataset, "to_id": membership})
            edges.append({"kind": "membership_object", "from_id": membership, "to_id": f"sha256:{digest}"})
    export = json.dumps({"records": records, "edges": edges}).encode()
    contract = MODULE.build_audio_text_contract(
        census, text_connector_raw=text_raw, predecessor_connector_raw=inputs["predecessor_raw"],
        predecessor_contract_raw=_predecessor_contract_raw(), catalog_export_raw=export,
        dataset_ids=[text_ds, audio_ds],
    )
    assert contract["catalog_binding"]["membership_count"] == 6
    assert contract["catalog_binding"]["referenced_object_count"] == 6
    with pytest.raises(ValueError, match="AUDIO_TEXT_HELDOUT_MEMBERSHIP_TOTALITY_REFUSED:3/6"):
        MODULE.build_audio_text_contract(
            census, text_connector_raw=text_raw, predecessor_connector_raw=inputs["predecessor_raw"],
            predecessor_contract_raw=_predecessor_contract_raw(), catalog_export_raw=export,
            dataset_ids=[text_ds],
        )
