# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[5]
SOURCE = ROOT / "src" / "ember" / "governance" / "scripts" / "issue2145_trimodal_contract.py"
SPEC = importlib.util.spec_from_file_location("issue2145_trimodal_contract", SOURCE)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

ITEMS = 64
IMAGE_TEXT_ITEMS = 70  # more predecessor image items than triples: rank selection must pick the first 64 by gold
AUDIO_DATASET = "dataset:issue1581-bulk-heldout:audio-fixture"
TEXT_DATASET = "dataset:issue1581-bulk-heldout:text-fixture"
IMAGE_DATASET = "dataset:issue1581-bulk-heldout:image-fixture"
TRAIN_DATASET = "dataset:issue1581-bulk-train:fixture"


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _self_hashed(payload: dict) -> dict:
    body = dict(payload)
    body.pop("self_sha256", None)
    body["self_sha256"] = sha(canonical(body))
    return body


def _text_raw(item_id: str, transcript: str, extra: dict | None = None) -> bytes:
    payload = {"transcript": transcript, "utterance_id": item_id}
    if extra:
        payload.update(extra)
    return (json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


class Fixture:
    def __init__(self, root: Path, *, audio_text_items: int = ITEMS) -> None:
        self.root = root
        roots = {name: root / name for name in ("images", "audio", "transcripts")}
        for path in roots.values():
            path.mkdir(parents=True)
        files: dict[str, list[dict]] = {name: [] for name in roots}
        self.objects: dict[str, tuple[str, bytes]] = {}  # sha -> (domain, raw)

        def put(kind: str, raw: bytes, suffix: str) -> dict:
            digest = sha(raw)
            (roots[kind] / f"{digest}{suffix}").write_bytes(raw)
            files[kind].append({"path": f"{digest}{suffix}", "bytes": len(raw), "sha256": digest})
            self.objects[digest] = (kind, raw)
            media = {"images": "image/png", "audio": "audio/flac", "transcripts": "application/json"}[kind]
            return {"sha256": digest, "byte_count": len(raw), "media_type": media}

        at_frozen = []
        for index in range(audio_text_items):
            item_id = f"1995-1837-{index:04d}"
            audio_raw = f"flac-{index}".encode()
            text_raw = _text_raw(item_id, f"LINE {index} OF THE FIXTURE")
            at_frozen.append({
                "item_id": item_id,
                "audio_object": put("audio", audio_raw, ".flac"),
                "item_text_object": put("transcripts", text_raw, ".json"),
                "gold_item_sha256": sha(audio_raw + text_raw),
            })
        it_frozen = []
        for index in range(IMAGE_TEXT_ITEMS):
            image_raw = f"png-{index}".encode()
            second_raw = f"png-second-{index}".encode()
            it_frozen.append({
                "item_id": f"validation_Art_{index}",
                "image_objects": [put("images", image_raw, ".png"), put("images", second_raw, ".png")],
                "gold_item_sha256": sha(image_raw + f"question {index}".encode()),
            })
        self.receipts: list[Path] = []
        for kind, source_id in (
            ("images", "mmmu-validation-heldout-images"),
            ("audio", "librispeech-test-clean-heldout-audio-64"),
            ("transcripts", "librispeech-test-clean-heldout-audio-text-transcripts"),
        ):
            receipt = root / f"connector-{kind}.json"
            receipt.write_text(json.dumps({
                "schema": "corpus-connector-receipt-v1",
                "source_id": source_id,
                "dest_root": str(roots[kind]),
                "files": files[kind],
            }), encoding="utf-8")
            self.receipts.append(receipt)
        self.audio_text = root / "audio-text-contract.json"
        self.audio_text.write_bytes(canonical(_self_hashed({
            "schema_version": "ember-issue1947-protected-audio-text-contract-v1",
            "result": "PASS",
            "task_class": "adapter_totality",
            "source": {"license_sha256": sha(b"CC BY 4.0")},
            "frozen_items": at_frozen,
            "totality": {"expected": ITEMS, "observed": audio_text_items, "complete": audio_text_items == ITEMS},
            "catalog_binding": {"dataset_ids": [AUDIO_DATASET, TEXT_DATASET]},
        })))
        self.image_text = root / "image-text-contract.json"
        self.image_text.write_bytes(canonical(_self_hashed({
            "schema_version": "ember-protected-image-text-contract-v1",
            "result": "PASS",
            "task_class": "adapter_totality",
            "source": {"license_sha256": sha(b"Apache-2.0")},
            "frozen_items": it_frozen,
            "totality": {"expected": IMAGE_TEXT_ITEMS, "observed": IMAGE_TEXT_ITEMS, "complete": True},
            "catalog_binding": {"dataset_ids": [IMAGE_DATASET]},
        })))
        self.export = root / "catalog-export.json"
        self.write_export()

    def write_export(self, *, train_objects: list[str] | None = None) -> None:
        records = [{"kind": "dataset_version", "id": d, "state": "admitted"} for d in (AUDIO_DATASET, TEXT_DATASET, IMAGE_DATASET, TRAIN_DATASET)]
        edges = []
        domain_dataset = {"audio": AUDIO_DATASET, "transcripts": TEXT_DATASET, "images": IMAGE_DATASET}
        domain_name = {"audio": "audio", "transcripts": "text", "images": "image"}
        for digest, (kind, _raw) in self.objects.items():
            membership_id = f"membership:heldout:{digest[:16]}"
            records.append({"kind": "membership", "id": membership_id, "split": "heldout", "admission_state": "admitted", "domain": domain_name[kind]})
            edges.append({"kind": "version_membership", "from_id": domain_dataset[kind], "to_id": membership_id})
            edges.append({"kind": "membership_object", "from_id": membership_id, "to_id": f"sha256:{digest}"})
        for index, digest in enumerate(train_objects or [sha(f"train-{i}".encode()) for i in range(5)]):
            membership_id = f"membership:train:{index}"
            records.append({"kind": "membership", "id": membership_id, "split": "train", "admission_state": "admitted", "domain": "text"})
            edges.append({"kind": "version_membership", "from_id": TRAIN_DATASET, "to_id": membership_id})
            edges.append({"kind": "membership_object", "from_id": membership_id, "to_id": f"sha256:{digest}"})
        self.export.write_bytes(canonical({"records": records, "edges": edges}))

    def build(self, *, connectors: list[Path] | None = None, planted_negative: str | None = None) -> dict:
        return MODULE.build_contract(
            audio_text_contract_path=self.audio_text,
            image_text_contract_path=self.image_text,
            connector_paths=connectors if connectors is not None else self.receipts,
            catalog_export_path=self.export,
            planted_negative=planted_negative,
        )


def test_pairing_is_deterministic_and_restates_both_predecessors(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    first = fixture.build()
    second = fixture.build()
    assert canonical(first) == canonical(second)
    assert first["selected_set_sha256"] == second["selected_set_sha256"]
    assert first["totality"] == {"expected": ITEMS, "observed": ITEMS, "complete": True}
    assert first["task"]["id"] == "EXACT_IMAGE_AUDIO_TEXT_TRIPLE_IDENTITY"
    assert first["catalog_binding"]["train_exclusion"] == {"executed": True, "admitted_train_object_count": 5, "overlap_count": 0}
    assert first["catalog_binding"]["dataset_ids"] == sorted([AUDIO_DATASET, TEXT_DATASET, IMAGE_DATASET])
    image_text = json.loads(fixture.image_text.read_bytes())
    ranked = sorted(image_text["frozen_items"], key=lambda row: row["gold_item_sha256"])[:ITEMS]
    items = first["frozen_items"]
    assert [item["item_id"] for item in items] == sorted(item["item_id"] for item in items)
    assert [item["image_object"]["sha256"] for item in items] == [row["image_objects"][0]["sha256"] for row in ranked]
    for item in items:
        image_raw = fixture.objects[item["image_object"]["sha256"]][1]
        audio_raw = fixture.objects[item["audio_object"]["sha256"]][1]
        text_raw = fixture.objects[item["item_text_object"]["sha256"]][1]
        assert item["gold_item_sha256"] == sha(image_raw + audio_raw + text_raw)
    body = dict(first)
    assert body.pop("self_sha256") == sha(canonical(body))


def test_predecessor_pair_drift_refuses_with_receipt(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    with pytest.raises(ValueError, match=r"^TRIMODAL_PREDECESSOR_PAIR_DRIFT_REFUSED:1995-1837-0000$"):
        fixture.build(planted_negative="pair-drift")
    output = tmp_path / "out" / "contract.json"
    command = [
        sys.executable, str(SOURCE),
        "--audio-text-contract", str(fixture.audio_text),
        "--image-text-contract", str(fixture.image_text),
        "--catalog-export", str(fixture.export),
        "--output", str(output),
        "--planted-negative", "pair-drift",
    ]
    for receipt in fixture.receipts:
        command += ["--connector-receipt", str(receipt)]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    assert completed.returncode == 78, completed.stdout + completed.stderr
    refusal = json.loads(output.read_text(encoding="utf-8"))
    assert refusal["schema_version"] == "ember-issue2145-trimodal-contract-refusal-v1"
    assert refusal["result"] == "PLANTED_NEGATIVE_REFUSED"
    assert refusal["reason"].startswith("TRIMODAL_PREDECESSOR_PAIR_DRIFT_REFUSED:")
    body = dict(refusal)
    assert body.pop("self_sha256") == sha(canonical(body))


def test_totality_short_by_one_refuses(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path, audio_text_items=ITEMS - 1)
    with pytest.raises(ValueError, match=r"^AUDIO_TEXT_CONTRACT_TOTALITY_REFUSED$"):
        fixture.build()


def test_extraneous_receipt_and_train_overlap_refuse(tmp_path: Path) -> None:
    fixture = Fixture(tmp_path)
    extra_root = tmp_path / "extra"
    extra_root.mkdir()
    extra_raw = b"unrelated"
    (extra_root / f"{sha(extra_raw)}.bin").write_bytes(extra_raw)
    extra = tmp_path / "connector-extra.json"
    extra.write_text(json.dumps({
        "schema": "corpus-connector-receipt-v1",
        "source_id": "unrelated-source",
        "dest_root": str(extra_root),
        "files": [{"path": f"{sha(extra_raw)}.bin", "bytes": len(extra_raw), "sha256": sha(extra_raw)}],
    }), encoding="utf-8")
    with pytest.raises(ValueError, match=rf"^TRIMODAL_CONNECTOR_EXTRANEOUS_REFUSED:{sha(extra.read_bytes())}$"):
        fixture.build(connectors=[*fixture.receipts, extra])

    custody = tmp_path / "prediction-custody.json"
    custody.write_text(json.dumps({"schema_version": "ember-prediction-custody-v1", "rows": []}), encoding="utf-8")
    with pytest.raises(ValueError, match=r"^TRIMODAL_FORBIDDEN_INPUT_REFUSED:source_schema:ember-prediction-custody-v1$"):
        fixture.build(connectors=[*fixture.receipts, custody])

    good = fixture.build()
    leaked = good["frozen_items"][5]["audio_object"]["sha256"]
    fixture.write_export(train_objects=[leaked])
    with pytest.raises(ValueError, match=rf"^TRIMODAL_TRAIN_HELDOUT_OBJECT_OVERLAP_REFUSED:sha256:{leaked}$"):
        fixture.build()
