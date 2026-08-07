# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import hashlib
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_source(root: Path, name: str, rows: list[dict], *, license_name: str = "CC0-1.0") -> None:
    source = root / name
    source.mkdir(parents=True)
    payload = b"".join(
        (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        for row in rows
    )
    data_path = source / "records.jsonl"
    data_path.write_bytes(payload)
    receipt = {
        "relative_path": "records.jsonl",
        "source_url": f"https://example.invalid/{name}",
        "sha256": _sha(payload),
        "bytes": len(payload),
        "license": license_name,
        "human_provenance_basis": "fixture human-authored records",
        "fetched_ts": "2026-08-06T00:00:00Z",
        "selection_rule": "fixture-records-v1",
    }
    (source / "manifest.jsonl").write_text(json.dumps(receipt) + "\n", encoding="utf-8")


def _fixture(root: Path) -> Path:
    raw = root / "raw"
    _write_source(
        raw,
        "alpha",
        [
            {"id": "a0", "text": "alpha one"},
            {"id": "a1", "text": "alpha two"},
            {"id": "a2", "text": "shared duplicate"},
        ],
    )
    _write_source(
        raw,
        "beta",
        [
            {"id": "b0", "text": "beta one"},
            {"id": "b1", "text": "shared duplicate"},
            {"id": "b2", "text": "beta three"},
        ],
    )
    return raw


def test_missing_builder_api_is_the_first_red():
    from scripts.corpus.owned_v1 import build_owned_corpus

    assert build_owned_corpus is not None


def test_source_inventory_is_closed_and_rejects_unknown_license(tmp_path: Path):
    from scripts.corpus.owned_v1 import load_source_inventory

    raw = tmp_path / "raw"
    _write_source(raw, "bad", [{"id": "x", "text": "x"}], license_name="")
    with pytest.raises(ValueError, match="license"):
        load_source_inventory(raw, source_names=("bad",))


def test_build_is_byte_stable_and_split_roots_are_disjoint(tmp_path: Path):
    from scripts.corpus.owned_v1 import build_owned_corpus

    raw = _fixture(tmp_path)
    first = build_owned_corpus(raw_root=raw, output_root=tmp_path / "first", source_names=("alpha", "beta"), shard_records=2)
    second = build_owned_corpus(raw_root=raw, output_root=tmp_path / "second", source_names=("alpha", "beta"), shard_records=2)
    assert (tmp_path / "first" / "manifest.json").read_bytes() == (tmp_path / "second" / "manifest.json").read_bytes()
    assert first["train_root_sha256"] == second["train_root_sha256"]
    assert first["heldout_root_sha256"] == second["heldout_root_sha256"]
    assert set(first["train_content_sha256"]).isdisjoint(first["heldout_content_sha256"])
    assert "raw" not in (tmp_path / "first" / "manifest.json").read_text(encoding="utf-8")


def test_resume_from_completed_shard_matches_uninterrupted_build(tmp_path: Path):
    from scripts.corpus.owned_v1 import build_owned_corpus

    raw = _fixture(tmp_path)
    partial = tmp_path / "partial"
    receipt = build_owned_corpus(raw_root=raw, output_root=partial, source_names=("alpha", "beta"), shard_records=2, max_records=2)
    assert receipt["result"] == "INTERRUPTED"
    resumed = build_owned_corpus(raw_root=raw, output_root=partial, source_names=("alpha", "beta"), shard_records=2, resume=True)
    clean = build_owned_corpus(raw_root=raw, output_root=tmp_path / "clean", source_names=("alpha", "beta"), shard_records=2)
    assert resumed == clean
    assert (partial / "manifest.json").read_bytes() == (tmp_path / "clean" / "manifest.json").read_bytes()



def test_resume_rejects_heldout_modulus_drift(tmp_path: Path):
    from scripts.corpus.owned_v1 import build_owned_corpus

    raw = _fixture(tmp_path)
    partial = tmp_path / "partial"
    build_owned_corpus(
        raw_root=raw,
        output_root=partial,
        source_names=("alpha", "beta"),
        shard_records=2,
        heldout_modulus=2,
        max_records=2,
    )
    with pytest.raises(ValueError, match="resume authority|transform"):
        build_owned_corpus(
            raw_root=raw,
            output_root=partial,
            source_names=("alpha", "beta"),
            shard_records=2,
            heldout_modulus=3,
            resume=True,
        )


def test_validate_manifest_recomputes_deterministic_split_rule(tmp_path: Path):
    from scripts.corpus.owned_v1 import build_owned_corpus, validate_manifest

    raw = _fixture(tmp_path)
    out = tmp_path / "out"
    build_owned_corpus(
        raw_root=raw,
        output_root=out,
        source_names=("alpha", "beta"),
        shard_records=2,
        heldout_modulus=2,
    )
    path = out / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["heldout_modulus"] = 3
    path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="split|transform"):
        validate_manifest(path, output_root=out)

def test_malformed_record_and_path_escape_fail_closed(tmp_path: Path):
    from scripts.corpus.owned_v1 import build_owned_corpus

    raw = tmp_path / "raw"
    _write_source(raw, "alpha", [{"id": "a", "text": "ok"}])
    (raw / "alpha" / "manifest.jsonl").write_text(
        json.dumps({
            "relative_path": "../outside.jsonl",
            "source_url": "https://example.invalid/alpha",
            "sha256": "0" * 64,
            "bytes": 1,
            "license": "CC0-1.0",
            "human_provenance_basis": "fixture",
            "fetched_ts": "2026-08-06T00:00:00Z",
            "selection_rule": "fixture-records-v1",
        }) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="path"):
        build_owned_corpus(raw_root=raw, output_root=tmp_path / "out", source_names=("alpha",))



def test_uppercase_receipt_digest_is_canonicalized(tmp_path: Path):
    from scripts.corpus.owned_v1 import load_source_inventory

    raw = tmp_path / "raw"
    _write_source(raw, "alpha", [{"id": "a", "text": "ok"}])
    receipt_path = raw / "alpha" / "manifest.jsonl"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["sha256"] = receipt["sha256"].upper()
    receipt_path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    rows = load_source_inventory(raw, source_names=("alpha",))
    assert rows[0]["sha256"] == receipt["sha256"].lower()


def test_output_root_inside_raw_custody_is_rejected(tmp_path: Path):
    from scripts.corpus.owned_v1 import build_owned_corpus

    raw = _fixture(tmp_path)
    with pytest.raises(ValueError, match="raw|output|custody"):
        build_owned_corpus(raw_root=raw, output_root=raw / "assembled", source_names=("alpha", "beta"), shard_records=2)


def test_manifest_reopen_rejects_undeclared_extra_shard(tmp_path: Path):
    from scripts.corpus.owned_v1 import build_owned_corpus, validate_manifest

    raw = _fixture(tmp_path)
    out = tmp_path / "out"
    build_owned_corpus(raw_root=raw, output_root=out, source_names=("alpha", "beta"), shard_records=2)
    extra = out / "train" / "shard-extra.jsonl"
    extra.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="extra|unexpected|shard"):
        validate_manifest(out / "manifest.json", output_root=out)


def test_manifest_reopen_rejects_source_binding_drift(tmp_path: Path):
    from scripts.corpus.owned_v1 import build_owned_corpus, validate_manifest

    raw = _fixture(tmp_path)
    out = tmp_path / "out"
    build_owned_corpus(raw_root=raw, output_root=out, source_names=("alpha", "beta"), shard_records=2)
    manifest_path = out / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sources"][0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source|binding"):
        validate_manifest(manifest_path, output_root=out)


def test_truncated_gzip_record_fails_closed(tmp_path: Path):
    from scripts.corpus.owned_v1 import build_owned_corpus

    raw = tmp_path / "raw"
    source = raw / "alpha"
    source.mkdir(parents=True)
    data_path = source / "records.jsonl.gz"
    data_path.write_bytes(b"\x1f\x8b\x08\x00truncated")
    receipt = {
        "relative_path": "records.jsonl.gz",
        "source_url": "https://example.invalid/alpha",
        "sha256": _sha(data_path.read_bytes()),
        "bytes": data_path.stat().st_size,
        "license": "CC0-1.0",
        "human_provenance_basis": "fixture human-authored records",
        "fetched_ts": "2026-08-06T00:00:00Z",
        "selection_rule": "fixture-records-v1",
    }
    (source / "manifest.jsonl").write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="gzip|record|source"):
        build_owned_corpus(raw_root=raw, output_root=tmp_path / "out", source_names=("alpha",))


def test_manifest_reopen_rejects_shard_byte_drift(tmp_path: Path):
    from scripts.corpus.owned_v1 import build_owned_corpus, validate_manifest

    raw = _fixture(tmp_path)
    build_owned_corpus(raw_root=raw, output_root=tmp_path / "out", source_names=("alpha", "beta"), shard_records=2)
    manifest_path = tmp_path / "out" / "manifest.json"
    validate_manifest(manifest_path, output_root=tmp_path / "out")
    shard = next((tmp_path / "out" / "train").glob("*.jsonl"))
    shard.write_bytes(shard.read_bytes() + b"tamper")
    with pytest.raises(ValueError, match="shard"):
        validate_manifest(manifest_path, output_root=tmp_path / "out")


def test_receipt_manifest_utf8_bom_is_decoded_without_changing_bound_bytes(tmp_path: Path):
    from scripts.corpus.owned_v1 import load_source_inventory

    raw = tmp_path / "raw"
    _write_source(raw, "alpha", [{"id": "a", "text": "ok"}])
    receipt_path = raw / "alpha" / "manifest.jsonl"
    receipt_path.write_bytes(b"\xef\xbb\xbf" + receipt_path.read_bytes())
    rows = load_source_inventory(raw, source_names=("alpha",))
    assert len(rows) == 1
    assert rows[0]["manifest_sha256"] == _sha(receipt_path.read_bytes())


def test_duplicate_receipt_rows_are_rejected_before_build(tmp_path: Path):
    from scripts.corpus.owned_v1 import load_source_inventory

    raw = tmp_path / "raw"
    _write_source(raw, "alpha", [{"id": "a", "text": "ok"}])
    receipt_path = raw / "alpha" / "manifest.jsonl"
    line = receipt_path.read_bytes()
    receipt_path.write_bytes(line + line)
    with pytest.raises(ValueError, match="duplicated|duplicate"):
        load_source_inventory(raw, source_names=("alpha",))


def test_manifest_source_authority_hash_is_recomputed(tmp_path: Path):
    from scripts.corpus.owned_v1 import build_owned_corpus, validate_manifest

    raw = _fixture(tmp_path)
    out = tmp_path / "out"
    build_owned_corpus(raw_root=raw, output_root=out, source_names=("alpha", "beta"), shard_records=2)
    path = out / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["source_manifest_sha256"] = "0" * 64
    path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source authority|source manifest"):
        validate_manifest(path, output_root=out)


def test_owned_corpus_cursor_reopens_closed_manifest_and_streams_without_materializing(tmp_path: Path):
    from scripts.corpus.owned_v1 import build_owned_corpus, iter_owned_records

    raw = _fixture(tmp_path)
    out = tmp_path / "out"
    manifest = build_owned_corpus(raw_root=raw, output_root=out, source_names=("alpha", "beta"), shard_records=2)
    cursor = {
        "schema_version": "ember-owned-corpus-cursor-v1",
        "manifest_sha256": _sha((out / "manifest.json").read_bytes()),
        "split": "train",
        "root_sha256": manifest["train_root_sha256"],
        "record_index": 0,
    }
    first = list(iter_owned_records(out / "manifest.json", output_root=out, cursor=cursor, max_records=1))
    assert len(first) == 1
    assert first[0][1]["record_index"] == 1
    assert first[0][1]["manifest_sha256"] == cursor["manifest_sha256"]
    with pytest.raises(ValueError, match="manifest|cursor|root"):
        list(iter_owned_records(out / "manifest.json", output_root=out, cursor={**cursor, "manifest_sha256": "0" * 64}, max_records=1))


def test_owned_corpus_cursor_rejects_wrong_split_root_and_range(tmp_path: Path):
    from scripts.corpus.owned_v1 import build_owned_corpus, iter_owned_records

    raw = _fixture(tmp_path)
    out = tmp_path / "out"
    manifest = build_owned_corpus(raw_root=raw, output_root=out, source_names=("alpha", "beta"), shard_records=2)
    base = {"schema_version": "ember-owned-corpus-cursor-v1", "manifest_sha256": _sha((out / "manifest.json").read_bytes()), "split": "train", "root_sha256": manifest["train_root_sha256"], "record_index": 0}
    for cursor, message in (({**base, "split": "heldout", "root_sha256": base["root_sha256"]}, "root"), ({**base, "root_sha256": "0" * 64}, "root"), ({**base, "record_index": 10_000}, "cursor")):
        with pytest.raises(ValueError, match=message):
            list(iter_owned_records(out / "manifest.json", output_root=out, cursor=cursor, max_records=1))


def test_owned_corpus_selection_feeds_real_pretrain_consumer_and_advances_cursor(tmp_path: Path):
    """The governed selection consumer must consume owned-v1 rows without list slicing."""
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel

    from scripts.corpus.owned_v1 import OwnedCorpusSelection, build_owned_corpus

    raw = tmp_path / "raw"
    _write_source(
        raw,
        "alpha",
        [{"id": f"a{index}", "text": f"owned selection record {index}"} for index in range(12)],
    )
    out = tmp_path / "owned"
    manifest = build_owned_corpus(raw_root=raw, output_root=out, source_names=("alpha",), shard_records=2)
    tokenizer = Tokenizer(
        WordLevel(
            vocab={"[UNK]": 0, "owned": 1, "selection": 2, "record": 3},
            unk_token="[UNK]",
        )
    )
    tokenizer_path = tmp_path / "tokenizer.json"
    tokenizer.save(str(tokenizer_path))
    selection = OwnedCorpusSelection(
        out / "manifest.json",
        output_root=out,
        tokenizer_path=tokenizer_path,
        split="train",
        max_records=2,
    )
    assert selection.receipt["selected_record_count"] == 2
    assert selection.receipt["schema_version"] == "ember-owned-corpus-selection-receipt-v1"
    assert set(selection.receipt) == {
        "schema_version",
        "manifest_sha256",
        "split",
        "root_sha256",
        "selected_record_count",
        "tokenizer_sha256",
        "selection_rule_id",
    }

    tools_root = ROOT / "tools" / "ember-restart-3b"
    tests_root = ROOT / "tests"
    sys.path.insert(0, str(tests_root))
    sys.path.insert(0, str(tools_root))
    try:
        import torch
        import pretrain
        from model import RestartDecoderConfig, UnifiedDecoder

        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=101)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
        checkpoints: list[dict[str, object]] = []
        result = pretrain.run_selection_pretraining_segment(
            model=model,
            optimizer=optimizer,
            selection=selection,
            config=config,
            device=torch.device("cpu"),
            checkpoint_every=1,
            checkpoint_callback=lambda _step, state: checkpoints.append(state),
            max_records=1,
            require_complete_coverage=False,
        )
        first_cursor = dict(result["data_cursor"]["selection_cursor"])
        resumed_checkpoints: list[dict[str, object]] = []
        resumed = pretrain.run_selection_pretraining_segment(
            model=model,
            optimizer=optimizer,
            selection=selection,
            config=config,
            device=torch.device("cpu"),
            checkpoint_every=1,
            checkpoint_callback=lambda _step, state: resumed_checkpoints.append(state),
            initial_selection_cursor=first_cursor,
            initial_global_step=result["global_step"],
            initial_tokens_seen=result["tokens_seen"],
            require_complete_coverage=False,
        )
    finally:
        sys.path.remove(str(tools_root))
        sys.path.remove(str(tests_root))

    assert result["steps"] == 1
    assert checkpoints[0]["selection_receipt"] == selection.receipt
    assert [state["data_cursor"]["selection_cursor"]["selected_ordinal"] for state in checkpoints] == [1]
    assert resumed["steps"] == 1
    assert [state["data_cursor"]["selection_cursor"]["selected_ordinal"] for state in resumed_checkpoints] == [2]
    assert resumed["data_cursor"]["selection_cursor"]["selected_ordinal"] == 2
    assert resumed["data_cursor"]["global_step"] == 2



def test_owned_corpus_selection_rejects_legacy_cursor_schema(tmp_path: Path):
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel

    from scripts.corpus.owned_v1 import OwnedCorpusSelection, build_owned_corpus

    raw = tmp_path / "raw"
    _write_source(raw, "alpha", [{"id": "a0", "text": "record"}])
    out = tmp_path / "owned"
    manifest = build_owned_corpus(raw_root=raw, output_root=out, source_names=("alpha",), shard_records=1)
    tokenizer_path = tmp_path / "tokenizer.json"
    Tokenizer(WordLevel(vocab={"[UNK]": 0, "record": 1}, unk_token="[UNK]")).save(str(tokenizer_path))
    selection = OwnedCorpusSelection(out / "manifest.json", output_root=out, tokenizer_path=tokenizer_path, split="heldout", max_records=1)
    legacy_cursor = {
        "schema_version": "ember-owned-corpus-cursor-v1",
        "manifest_sha256": _sha((out / "manifest.json").read_bytes()),
        "split": "heldout",
        "root_sha256": manifest["heldout_root_sha256"],
        "record_index": 0,
    }
    with pytest.raises(ValueError, match="schema|cursor"):
        list(selection.iter_from(legacy_cursor))

def test_owned_corpus_selection_round_trips_real_p2b_checkpoint_and_resume(tmp_path: Path):
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel

    from scripts.corpus.owned_v1 import OwnedCorpusSelection, build_owned_corpus

    raw = tmp_path / "raw"
    _write_source(raw, "alpha", [{"id": f"a{index}", "text": f"record {index}"} for index in range(6)])
    out = tmp_path / "owned"
    build_owned_corpus(raw_root=raw, output_root=out, source_names=("alpha",), shard_records=2)
    tokenizer_path = tmp_path / "tokenizer.json"
    Tokenizer(WordLevel(vocab={"[UNK]": 0, "record": 1}, unk_token="[UNK]")).save(str(tokenizer_path))
    selection = OwnedCorpusSelection(out / "manifest.json", output_root=out, tokenizer_path=tokenizer_path, split="train", max_records=2)

    tools_root = ROOT / "tools" / "ember-restart-3b"
    tests_root = ROOT / "tests"
    sys.path.insert(0, str(tests_root))
    sys.path.insert(0, str(tools_root))
    try:
        import torch
        import checkpoint_artifacts
        import pretrain
        from ember_restart_model.checkpoint_fixture import write_checkpoint_artifacts
        from model import RestartDecoderConfig, UnifiedDecoder
        from specialist_stream import SELECTION_CURSOR_SCHEMA_VERSION, TRAINING_CURSOR_SCHEMA_VERSION
        from scripts.corpus.owned_v1 import OWNED_SELECTION_SCHEMA_VERSION

        config = RestartDecoderConfig.small_for_tests(hidden_size=32, layers=2, attention_heads=4, vocab_size=64)
        model = UnifiedDecoder(config, genesis_seed=101)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
        result = pretrain.run_selection_pretraining_segment(
            model=model,
            optimizer=optimizer,
            selection=selection,
            config=config,
            device=torch.device("cpu"),
            checkpoint_every=1,
            checkpoint_callback=lambda _step, _state: None,
            max_records=1,
            require_complete_coverage=False,
        )
        training_cursor = result["data_cursor"]
        assert training_cursor["schema_version"] == TRAINING_CURSOR_SCHEMA_VERSION
        selection_cursor = training_cursor["selection_cursor"]
        assert selection_cursor["schema_version"] == SELECTION_CURSOR_SCHEMA_VERSION
        assert set(selection_cursor) == {
            "schema_version",
            "selection_receipt_sha256",
            "selection_rule_id",
            "selected_ordinal",
            "next_source_index",
        }
        assert selection_cursor["selection_receipt_sha256"] == _sha(
            json.dumps(selection.receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        )
        assert selection.receipt["schema_version"] == OWNED_SELECTION_SCHEMA_VERSION
        checkpoint_root = tmp_path / "checkpoint"
        receipt = write_checkpoint_artifacts(
            model=model,
            optimizer=optimizer,
            root=checkpoint_root,
            launch_seed=101,
            rng_state={"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
            data_cursor=training_cursor,
            selection_receipt=selection.receipt,
            model_config_sha256="a" * 64,
            contract_sha256="b" * 64,
            expert_genesis_sha256={name: "c" * 64 for name in ("vision", "audio", "reasoning", "tool")},
            test_only_allow_unverified=True,
        )
        restored_model = UnifiedDecoder(config, genesis_seed=101)
        restored_optimizer = torch.optim.AdamW(restored_model.parameters(), lr=1e-3)
        restored = checkpoint_artifacts.load_checkpoint_artifacts(
            restored_model,
            restored_optimizer,
            checkpoint_root,
            receipt,
        )
        assert restored["data_cursor"] == training_cursor
        tampered_model = UnifiedDecoder(config, genesis_seed=101)
        tampered_optimizer = torch.optim.AdamW(tampered_model.parameters(), lr=1e-3)
        tampered_receipt = dict(receipt)
        tampered_receipt["selection_receipt"] = {**selection.receipt, "manifest_sha256": "0" * 64}
        with pytest.raises(ValueError, match="receipt"):
            checkpoint_artifacts.load_checkpoint_artifacts(
                tampered_model, tampered_optimizer, checkpoint_root, tampered_receipt
            )
        resumed = pretrain.run_selection_pretraining_segment(
            model=restored_model,
            optimizer=restored_optimizer,
            selection=selection,
            config=config,
            device=torch.device("cpu"),
            checkpoint_every=1,
            checkpoint_callback=lambda _step, _state: None,
            initial_selection_cursor=selection_cursor,
            initial_global_step=training_cursor["global_step"],
            initial_tokens_seen=training_cursor["tokens_seen"],
            require_complete_coverage=False,
        )
    finally:
        sys.path.remove(str(tools_root))
        sys.path.remove(str(tests_root))

    assert resumed["steps"] == 1
    assert resumed["data_cursor"]["selection_cursor"]["selected_ordinal"] == 2


def test_owned_selection_receipt_tamper_is_rejected_on_resume(tmp_path: Path):
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel

    from scripts.corpus.owned_v1 import OwnedCorpusSelection, build_owned_corpus

    raw = tmp_path / "raw"
    _write_source(raw, "alpha", [{"id": f"a{index}", "text": f"record {index}"} for index in range(4)])
    out = tmp_path / "owned"
    build_owned_corpus(raw_root=raw, output_root=out, source_names=("alpha",), shard_records=2)
    tokenizer_path = tmp_path / "tokenizer.json"
    Tokenizer(WordLevel(vocab={"[UNK]": 0, "record": 1}, unk_token="[UNK]")).save(str(tokenizer_path))
    selection = OwnedCorpusSelection(
        out / "manifest.json", output_root=out, tokenizer_path=tokenizer_path, split="train", max_records=1
    )
    selection.receipt["manifest_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="receipt|selection"):
        list(selection.iter_from())

def test_owned_selection_receipt_is_required_by_production_checkpoint_writer(tmp_path: Path):
    tools_root = ROOT / "tools" / "ember-restart-3b"
    tests_root = ROOT / "tests"
    sys.path.insert(0, str(tests_root))
    sys.path.insert(0, str(tools_root))
    try:
        import torch
        from ember_restart_model.checkpoint_fixture import write_checkpoint_artifacts
        from model import RestartDecoderConfig, UnifiedDecoder

        config = RestartDecoderConfig.small_for_tests(hidden_size=16, layers=1, attention_heads=2, vocab_size=32)
        model = UnifiedDecoder(config, genesis_seed=101)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
        selection_receipt = {
            "schema_version": "ember-owned-corpus-selection-receipt-v1",
            "manifest_sha256": "1" * 64,
            "split": "train",
            "root_sha256": "2" * 64,
            "selected_record_count": 1,
            "tokenizer_sha256": "3" * 64,
            "selection_rule_id": "owned_corpus_text_tokenize_v1",
        }
        receipt_hash = _sha(
            json.dumps(selection_receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        )
        data_cursor = {
            "schema_version": "ember-specialist-stream-training-cursor-v1",
            "selection_cursor": {
                "schema_version": "ember-owned-specialist-stream-selection-cursor-v1",
                "selection_receipt_sha256": receipt_hash,
                "selection_rule_id": "owned_corpus_text_tokenize_v1",
                "selected_ordinal": 1,
                "next_source_index": 1,
            },
            "global_step": 1,
            "tokens_seen": 2,
        }
        common = {
            "model": model,
            "optimizer": optimizer,
            "launch_seed": 101,
            "rng_state": {"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
            "data_cursor": data_cursor,
            "model_config_sha256": "a" * 64,
            "contract_sha256": "b" * 64,
            "expert_genesis_sha256": {name: "c" * 64 for name in ("vision", "audio", "reasoning", "tool")},
        }

        with pytest.raises(ValueError, match="receipt"):
            write_checkpoint_artifacts(root=tmp_path / "missing", **common)
        with pytest.raises(ValueError, match="receipt"):
            write_checkpoint_artifacts(root=tmp_path / "malformed", selection_receipt={}, **common)
        wrong_receipt = {**selection_receipt, "manifest_sha256": "4" * 64}
        with pytest.raises(ValueError, match="receipt"):
            write_checkpoint_artifacts(root=tmp_path / "wrong-bytes", selection_receipt=wrong_receipt, **common)
        forged_cursor = {**data_cursor, "selection_cursor": {**data_cursor["selection_cursor"], "selection_receipt_sha256": "f" * 64}}
        with pytest.raises(ValueError, match="receipt"):
            write_checkpoint_artifacts(
                root=tmp_path / "forged-cursor", selection_receipt=selection_receipt, data_cursor=forged_cursor, **{k: v for k, v in common.items() if k != "data_cursor"}
            )
    finally:
        sys.path.remove(str(tools_root))
        sys.path.remove(str(tests_root))


def test_owned_corpus_selection_rejects_tokenizer_drift(tmp_path: Path):
    from tokenizers import Tokenizer
    from tokenizers.models import WordLevel

    from scripts.corpus.owned_v1 import OwnedCorpusSelection, build_owned_corpus

    raw = tmp_path / "raw"
    _write_source(raw, "alpha", [{"id": f"a{index}", "text": f"record {index}"} for index in range(6)])
    out = tmp_path / "owned"
    build_owned_corpus(raw_root=raw, output_root=out, source_names=("alpha",), shard_records=2)
    tokenizer_path = tmp_path / "tokenizer.json"
    Tokenizer(WordLevel(vocab={"[UNK]": 0}, unk_token="[UNK]")).save(str(tokenizer_path))
    selection = OwnedCorpusSelection(out / "manifest.json", output_root=out, tokenizer_path=tokenizer_path, split="train", max_records=1)
    tokenizer_path.write_bytes(tokenizer_path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="tokenizer authority"):
        list(selection.iter_from())


def test_specialist_selection_receipt_family_round_trips_checkpoint_and_rejects_cross_family(tmp_path: Path):
    tools_root = ROOT / "tools" / "ember-restart-3b"
    tests_root = ROOT / "tests"
    sys.path.insert(0, str(tests_root))
    sys.path.insert(0, str(tools_root))
    try:
        import torch
        import checkpoint_artifacts
        from ember_restart_model.checkpoint_fixture import write_checkpoint_artifacts
        from model import RestartDecoderConfig, UnifiedDecoder
        from specialist_stream import (
            SELECTION_CURSOR_SCHEMA_VERSION,
            SELECTION_RECEIPT_SCHEMA_VERSION,
            TRAINING_CURSOR_SCHEMA_VERSION,
            canonical_record_bytes,
        )
        from scripts.corpus.owned_v1 import OWNED_SELECTION_SCHEMA_VERSION

        config = RestartDecoderConfig.small_for_tests(hidden_size=16, layers=1, attention_heads=2, vocab_size=32)
        model = UnifiedDecoder(config, genesis_seed=303)
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
        specialist_receipt = {
            "schema_version": SELECTION_RECEIPT_SCHEMA_VERSION,
            "stream_manifest_sha256": "1" * 64,
            "stream_build_receipt_sha256": "2" * 64,
            "corpus_root_sha256": "3" * 64,
            "family_root_sha256": "4" * 64,
            "capability": "image",
            "selection_rule_id": "image_scene_split_train_v1",
            "selected_record_count": 1,
            "selected_token_count": 2,
            "selected_records_sha256": "5" * 64,
            "selection_commitment_sha256": "6" * 64,
        }
        receipt_sha256 = _sha(canonical_record_bytes(specialist_receipt))
        data_cursor = {
            "schema_version": TRAINING_CURSOR_SCHEMA_VERSION,
            "selection_cursor": {
                "schema_version": SELECTION_CURSOR_SCHEMA_VERSION,
                "selection_receipt_sha256": receipt_sha256,
                "selection_rule_id": specialist_receipt["selection_rule_id"],
                "selected_ordinal": 1,
                "next_source_index": 1,
            },
            "global_step": 1,
            "tokens_seen": 2,
        }
        common = {
            "model": model,
            "optimizer": optimizer,
            "launch_seed": 303,
            "rng_state": {"cpu": torch.get_rng_state().clone(), "cuda": torch.tensor([1, 2, 3], dtype=torch.uint8)},
            "data_cursor": data_cursor,
            "model_config_sha256": "a" * 64,
            "contract_sha256": "b" * 64,
            "expert_genesis_sha256": {name: "c" * 64 for name in ("vision", "audio", "reasoning", "tool")},
            "test_only_allow_unverified": True,
        }
        checkpoint = write_checkpoint_artifacts(root=tmp_path / "specialist", selection_receipt=specialist_receipt, **common)
        restored_model = UnifiedDecoder(config, genesis_seed=303)
        restored_optimizer = torch.optim.AdamW(restored_model.parameters(), lr=1e-3)
        restored = checkpoint_artifacts.load_checkpoint_artifacts(restored_model, restored_optimizer, tmp_path / "specialist", checkpoint)
        assert restored["data_cursor"] == data_cursor
        assert checkpoint["selection_receipt"] == specialist_receipt

        owned_receipt = {
            "schema_version": OWNED_SELECTION_SCHEMA_VERSION,
            "manifest_sha256": "1" * 64,
            "split": "train",
            "root_sha256": "2" * 64,
            "selected_record_count": 1,
            "tokenizer_sha256": "3" * 64,
            "selection_rule_id": "owned_corpus_text_tokenize_v1",
        }
        owned_cursor = {**data_cursor, "selection_cursor": {**data_cursor["selection_cursor"], "selection_receipt_sha256": _sha(canonical_record_bytes(owned_receipt)), "selection_rule_id": owned_receipt["selection_rule_id"]}}
        with pytest.raises(ValueError, match="selection receipt|schema|rule"):
            write_checkpoint_artifacts(root=tmp_path / "cross-specialist-owned", data_cursor=data_cursor, selection_receipt=owned_receipt, **{key: value for key, value in common.items() if key != "data_cursor"})
        with pytest.raises(ValueError, match="selection receipt|schema|rule"):
            write_checkpoint_artifacts(root=tmp_path / "cross-owned-specialist", data_cursor=owned_cursor, selection_receipt=specialist_receipt, **{key: value for key, value in common.items() if key != "data_cursor"})
        wrong_schema = {**specialist_receipt, "schema_version": "ember-specialist-stream-selection-receipt-v0"}
        with pytest.raises(ValueError, match="selection receipt|schema"):
            write_checkpoint_artifacts(root=tmp_path / "wrong-schema", selection_receipt=wrong_schema, **common)
        with pytest.raises(ValueError, match="selection receipt"):
            write_checkpoint_artifacts(root=tmp_path / "missing-receipt", selection_receipt=None, **common)
    finally:
        sys.path.remove(str(tools_root))
        sys.path.remove(str(tests_root))
