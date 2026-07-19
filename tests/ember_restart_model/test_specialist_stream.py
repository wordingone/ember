# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Red/green contract for non-materialized owned specialist streams."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from unittest import mock
import unittest
from pathlib import Path

from tokenizers import Tokenizer, models, pre_tokenizers


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))


def _frozen_tokenizer(path: Path) -> Path:
    vocabulary = {"<unk>": 0, "red": 1, "is": 2, "left": 3, "of": 4, "green": 5,
                  "audio": 6, "signal": 7, "has": 8, "positive": 9, "negative": 10,
                  "silent": 11, "frames": 12, "reasoning": 13, "sum": 14, "plus": 15,
                  "equals": 16, "tool": 17, "calculator": 18,
                  **{f"filler-{index}": index for index in range(19, 32_000)}}
    tokenizer = Tokenizer(models.WordLevel(vocabulary, unk_token="<unk>"))
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.save(str(path))
    return path


class SpecialistStreamTests(unittest.TestCase):
    @staticmethod
    def _open_bound(manifest_path: Path, *, repo_root: Path = ROOT):
        from specialist_stream import open_specialist_stream

        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        return open_specialist_stream(
            repo_root=repo_root,
            manifest_path=manifest_path,
            expected_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            expected_corpus_root_sha256=manifest["corpus_root_sha256"],
        )

    @staticmethod
    def _bounded_stream_fixture(root: Path) -> tuple[Path, Path]:
        for relative in (
            "tools/ember-restart-3b/build_owned_vision_scenes.py",
            "tools/ember-restart-3b/build_owned_audio_frames.py",
            "tools/ember-restart-3b/build_owned_reasoning_tool_trajectories.py",
            "tools/ember-restart-3b/specialist_semantics.py",
            "tools/ember-restart-3b/verify_capability_record.py",
            "configs/ember-restart-3b.json",
        ):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / relative).read_bytes())
        tokenizer_path = root / "tokenizer.json"
        _frozen_tokenizer(tokenizer_path)
        return tokenizer_path, root / "configs/ember-restart-3b.json"
    def test_generators_expose_seekable_record_at_and_new_lineage_root(self) -> None:
        from build_owned_audio_frames import record_at as audio_record_at
        from build_owned_reasoning_tool_trajectories import record_at as trajectory_record_at
        from build_owned_vision_scenes import record_at as vision_record_at
        from specialist_stream import canonical_record_bytes, corpus_root_sha256

        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            tokenizer = Tokenizer.from_file(str(_frozen_tokenizer(Path(directory) / "tokenizer.json")))
            records = [vision_record_at(tokenizer, count=512, image_marker=31_998, index=index) for index in range(8)]
            self.assertEqual(canonical_record_bytes(records[0]), json.dumps(records[0], sort_keys=True, separators=(",", ":")).encode("utf-8"))
            self.assertEqual(audio_record_at(tokenizer, count=512, audio_marker=31_999, index=1)["active_expert"], "audio")
            self.assertEqual(trajectory_record_at(tokenizer, count=512, capability="tool", index=1)["active_expert"], "tool")
            hashes = [hashlib.sha256(canonical_record_bytes(record)).hexdigest() for record in records]
            self.assertEqual(corpus_root_sha256("image", hashes, chunk_size=2), corpus_root_sha256("image", hashes, chunk_size=7))

    def test_manifest_binds_generator_bytes_and_resumable_cursor(self) -> None:
        from specialist_stream import build_stream_manifest, open_specialist_stream

        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            manifest_path = root / "stream.json"
            manifest = build_stream_manifest(repo_root=ROOT, output_path=manifest_path, tokenizer_path=_frozen_tokenizer(root / "tokenizer.json"), model_config_path=ROOT / "configs" / "ember-restart-3b.json", record_count=512, chunk_size=64, data_class="MEASURED_RUNG")
            self.assertEqual(manifest["lineage"], "NEW_PREREGISTERED_STREAM")
            self.assertEqual(manifest["data_class"], "MEASURED_RUNG")
            self.assertEqual(set(manifest["generator_sources"]), {"image", "audio", "reasoning_tool"})
            stream = self._open_bound(manifest_path)
            records, cursor = stream.next_records(capability="tool", cursor=None, limit=2)
            self.assertEqual(cursor, {
                "schema_version": "ember-owned-specialist-stream-cursor-v1",
                "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                "capability": "tool",
                "next_index": 2,
            })
            self.assertEqual(stream.verify_record(records[0])["result"], "VERIFIED")
            self.assertEqual(stream.next_records(capability="tool", cursor=cursor, limit=1)[0][0]["sample_id"], stream.record_at("tool", 2)["sample_id"])
            with self.assertRaisesRegex(ValueError, "cursor capability"):
                stream.next_records(capability="reasoning", cursor=cursor, limit=1)


    def test_checked_in_stream_manifest_opens_and_replays_full_commitment(self) -> None:
        from specialist_stream import open_specialist_stream

        manifest_path = ROOT / "data" / "ember-restart-3b" / "owned-specialist-stream-v1-4096.json"
        receipt_path = ROOT / "data" / "ember-restart-3b" / "owned-specialist-stream-v1-4096-build-receipt.json"
        manifest_bytes = manifest_path.read_bytes()
        receipt_bytes = receipt_path.read_bytes()
        self.assertEqual(hashlib.sha256(manifest_bytes).hexdigest(), "857835d9722e5d6410f4c6c34c537ad2af12bfb98c4d3eb242b3a2c99e591427")
        self.assertEqual(hashlib.sha256(receipt_bytes).hexdigest(), "2e68402c914e842fe23c6ef69f1f8e957d858f7ad2de4d5467dfc65c949ead1e")
        manifest = json.loads(manifest_bytes)
        receipt = json.loads(receipt_bytes)
        self.assertEqual(receipt["stream_manifest_sha256"], hashlib.sha256(manifest_bytes).hexdigest())
        self.assertEqual(receipt_bytes, json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")
        stream = self._open_bound(manifest_path)
        measured = stream.validate_full_commitment(manifest["corpus_root_sha256"])
        self.assertEqual(set(measured), {"image", "audio", "reasoning", "tool"})
        self.assertTrue(all(item["records"] == 4096 for item in measured.values()))

    def test_next_records_verifies_each_touched_chunk_once_and_rejects_oversized_limit(self) -> None:
        from specialist_stream import build_stream_manifest, open_specialist_stream

        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            manifest_path = root / "stream.json"
            build_stream_manifest(
                repo_root=ROOT,
                output_path=manifest_path,
                tokenizer_path=_frozen_tokenizer(root / "tokenizer.json"),
                model_config_path=ROOT / "configs" / "ember-restart-3b.json",
                record_count=512,
                chunk_size=8,
                data_class="MEASURED_RUNG",
            )
            stream = self._open_bound(manifest_path)
            original = stream.record_at
            calls = 0

            def counted(capability: str, index: int):
                nonlocal calls
                calls += 1
                return original(capability, index)

            stream.record_at = counted  # type: ignore[method-assign]
            records, _cursor = stream.next_records(capability="tool", cursor=None, limit=8)
            self.assertEqual(len(records), 8)
            self.assertEqual(calls, 8)
            with self.assertRaisesRegex(ValueError, "chunk bound"):
                stream.next_records(capability="tool", cursor=None, limit=9)
            self.assertEqual(calls, 8)
    def test_reopen_rejects_bound_tokenizer_mutation(self) -> None:
        from specialist_stream import build_stream_manifest, open_specialist_stream
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            tokenizer = _frozen_tokenizer(root / "tokenizer.json")
            manifest_path = root / "stream.json"
            build_stream_manifest(repo_root=ROOT, output_path=manifest_path, tokenizer_path=tokenizer, model_config_path=ROOT / "configs" / "ember-restart-3b.json", record_count=512, chunk_size=64, data_class="MEASURED_RUNG")
            tokenizer.write_bytes(tokenizer.read_bytes() + b"mutation")
            with self.assertRaisesRegex(ValueError, "tokenizer"):
                self._open_bound(manifest_path)

    def test_raw_image_and_audio_targets_are_recomputed_at_consumption(self) -> None:
        from specialist_stream import SpecialistStream
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            tokenizer = Tokenizer.from_file(str(_frozen_tokenizer(Path(directory) / "tokenizer.json")))
            stream = SpecialistStream(tokenizer, 512, {})
            image = stream.record_at("image", 0)
            image["target_text"] = "forged image answer"
            with self.assertRaises(ValueError):
                stream.verify_record(image)
            audio = stream.record_at("audio", 0)
            audio["target_text"] = "forged audio answer"
            with self.assertRaises(ValueError):
                stream.verify_record(audio)


    def test_manifest_rejects_wrong_class_source_and_chunk_mutation(self) -> None:
        from specialist_stream import build_stream_manifest, open_specialist_stream
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            tokenizer = _frozen_tokenizer(root / "tokenizer.json")
            manifest_path = root / "stream.json"
            with self.assertRaisesRegex(ValueError, "SEMANTIC_PRETRAINING"):
                build_stream_manifest(repo_root=ROOT, output_path=manifest_path, tokenizer_path=tokenizer, model_config_path=ROOT / "configs" / "ember-restart-3b.json", record_count=512, chunk_size=64, data_class="SEMANTIC_PRETRAINING")
            manifest = build_stream_manifest(repo_root=ROOT, output_path=manifest_path, tokenizer_path=tokenizer, model_config_path=ROOT / "configs" / "ember-restart-3b.json", record_count=512, chunk_size=64, data_class="MEASURED_RUNG")
            manifest["generator_sources"]["image"]["sha256"] = "0" * 64
            manifest_path.write_bytes(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")
            with self.assertRaisesRegex(ValueError, "generator"):
                self._open_bound(manifest_path)

    def test_root_framing_rejects_reorder_duplicate_and_omission(self) -> None:
        from specialist_stream import corpus_root_sha256
        hashes = [hashlib.sha256(f"record-{index}".encode("ascii")).hexdigest() for index in range(8)]
        root = corpus_root_sha256("tool", hashes, chunk_size=2)
        self.assertEqual(root, corpus_root_sha256("tool", hashes, chunk_size=7))
        self.assertNotEqual(root, corpus_root_sha256("tool", list(reversed(hashes)), chunk_size=2))
        self.assertNotEqual(root, corpus_root_sha256("tool", hashes[:-1], chunk_size=2))
        self.assertNotEqual(root, corpus_root_sha256("tool", hashes[:3] + [hashes[2]] + hashes[3:], chunk_size=2))

    def test_consumption_rejects_chunk_mutation_and_full_replay_recomputes_root(self) -> None:
        from specialist_stream import build_stream_manifest, open_specialist_stream
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            manifest_path = root / "stream.json"
            manifest = build_stream_manifest(repo_root=ROOT, output_path=manifest_path, tokenizer_path=_frozen_tokenizer(root / "tokenizer.json"), model_config_path=ROOT / "configs" / "ember-restart-3b.json", record_count=512, chunk_size=64, data_class="MEASURED_RUNG")
            manifest["families"]["tool"]["chunks"][0]["sha256"] = "0" * 64
            manifest_path.write_bytes(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")
            stream = self._open_bound(manifest_path)
            with self.assertRaisesRegex(ValueError, "chunk commitment"):
                stream.next_records(capability="tool", cursor=None, limit=1)
            manifest = build_stream_manifest(repo_root=ROOT, output_path=manifest_path, tokenizer_path=_frozen_tokenizer(root / "tokenizer.json"), model_config_path=ROOT / "configs" / "ember-restart-3b.json", record_count=512, chunk_size=64, data_class="MEASURED_RUNG")
            stream = self._open_bound(manifest_path)
            measured = stream.validate_capability_commitment("tool")
            self.assertEqual(measured["records"], 512)
            self.assertGreater(measured["tokens"], 0)

    def test_reopen_rejects_same_root_config_mutation(self) -> None:
        from specialist_stream import build_stream_manifest, open_specialist_stream
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            config = root / "config.json"
            config.write_bytes((ROOT / "configs" / "ember-restart-3b.json").read_bytes())
            manifest_path = root / "stream.json"
            build_stream_manifest(repo_root=ROOT, output_path=manifest_path, tokenizer_path=_frozen_tokenizer(root / "tokenizer.json"), model_config_path=config, record_count=512, chunk_size=64, data_class="MEASURED_RUNG")
            config.write_bytes(config.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "model config"):
                self._open_bound(manifest_path)

    def test_chunk_layout_changes_not_corpus_root_or_record_bytes(self) -> None:
        from specialist_stream import build_stream_manifest
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            tokenizer = _frozen_tokenizer(root / "tokenizer.json")
            common = dict(repo_root=ROOT, tokenizer_path=tokenizer, model_config_path=ROOT / "configs" / "ember-restart-3b.json", record_count=512, data_class="MEASURED_RUNG")
            first = build_stream_manifest(output_path=root / "one.json", chunk_size=64, **common)
            second = build_stream_manifest(output_path=root / "two.json", chunk_size=127, **common)
            self.assertEqual(first["corpus_root_sha256"], second["corpus_root_sha256"])
            for capability in ("image", "audio", "reasoning", "tool"):
                self.assertEqual(first["families"][capability]["corpus_root_sha256"], second["families"][capability]["corpus_root_sha256"])
                self.assertNotEqual(first["families"][capability]["chunks"], second["families"][capability]["chunks"])

    def test_compact_build_receipt_reports_nonmaterialized_bytes(self) -> None:
        from specialist_stream import emit_stream_manifest, write_stream_build_receipt
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            manifest, elapsed_ms = emit_stream_manifest(repo_root=ROOT, output_path=root / "stream.json", tokenizer_path=_frozen_tokenizer(root / "tokenizer.json"), model_config_path=ROOT / "configs" / "ember-restart-3b.json", record_count=512, chunk_size=64, data_class="MEASURED_RUNG")
            receipt = write_stream_build_receipt(manifest_path=root / "stream.json", output_path=root / "receipt.json", elapsed_ms=elapsed_ms)
            self.assertEqual(receipt["result"], "MEASURED")
            self.assertIn("NOT_SUFFICIENT_PRETRAINING", receipt["boundary"])
            self.assertEqual(receipt["corpus_root_sha256"], manifest["corpus_root_sha256"])
            self.assertTrue(all(item["serialized_bytes_not_materialized"] > 0 for item in receipt["families"].values()))

    def test_bounded_legacy_serializer_fixture_matches_audio_and_trajectory_seek(self) -> None:
        from specialist_stream import canonical_record_bytes
        from build_owned_audio_frames import build_records as build_audio_records
        from build_owned_audio_frames import record_at as audio_record_at
        from build_owned_reasoning_tool_trajectories import build_records as build_trajectory_records
        from build_owned_reasoning_tool_trajectories import record_at as trajectory_record_at
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            tokenizer = Tokenizer.from_file(str(_frozen_tokenizer(Path(directory) / "tokenizer.json")))
            legacy_audio = build_audio_records(tokenizer, count=512, audio_marker=31_999)
            legacy_tool = build_trajectory_records(tokenizer, count=512, capability="tool")
            for index in (0, 1, 511):
                self.assertEqual(canonical_record_bytes(legacy_audio[index]), canonical_record_bytes(audio_record_at(tokenizer, count=512, audio_marker=31_999, index=index)))
                self.assertEqual(canonical_record_bytes(legacy_tool[index]), canonical_record_bytes(trajectory_record_at(tokenizer, count=512, capability="tool", index=index)))
    def test_cursor_cannot_resume_against_a_different_stream_manifest(self) -> None:
        from specialist_stream import build_stream_manifest, open_specialist_stream

        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            tokenizer = _frozen_tokenizer(root / "tokenizer.json")
            first_path = root / "first.json"
            second_path = root / "second.json"
            build_stream_manifest(
                repo_root=ROOT,
                output_path=first_path,
                tokenizer_path=tokenizer,
                model_config_path=ROOT / "configs" / "ember-restart-3b.json",
                record_count=512,
                chunk_size=64,
                data_class="MEASURED_RUNG",
            )
            build_stream_manifest(
                repo_root=ROOT,
                output_path=second_path,
                tokenizer_path=tokenizer,
                model_config_path=ROOT / "configs" / "ember-restart-3b.json",
                record_count=1024,
                chunk_size=64,
                data_class="MEASURED_RUNG",
            )
            _records, cursor = self._open_bound(first_path).next_records(
                capability="tool", cursor=None, limit=1
            )
            with self.assertRaisesRegex(ValueError, "cursor manifest"):
                self._open_bound(second_path).next_records(
                    capability="tool", cursor=cursor, limit=1
                )

    def test_manifest_rejects_oversized_range_and_chunk_before_record_materialization(self) -> None:
        import specialist_stream
        from specialist_stream import build_stream_manifest

        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            tokenizer = _frozen_tokenizer(root / "tokenizer.json")
            common = dict(
                repo_root=ROOT,
                output_path=root / "stream.json",
                tokenizer_path=tokenizer,
                model_config_path=ROOT / "configs" / "ember-restart-3b.json",
                data_class="MEASURED_RUNG",
            )
            with mock.patch.object(
                specialist_stream.SpecialistStream,
                "record_at",
                side_effect=AssertionError("oversized manifest reached record materialization"),
            ):
                with self.assertRaisesRegex(ValueError, "record count bound"):
                    build_stream_manifest(record_count=1_000_000_000, chunk_size=1, **common)
                with self.assertRaisesRegex(ValueError, "chunk bound"):
                    build_stream_manifest(record_count=512, chunk_size=1_000_000_000, **common)

            build_stream_manifest(record_count=512, chunk_size=64, **common)
            hostile = json.loads((root / "stream.json").read_bytes())
            hostile["range"]["record_count_per_family"] = 1_000_000_000
            hostile["chunk_size"] = 64
            (root / "stream.json").write_bytes(
                json.dumps(hostile, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
            )
            with mock.patch.object(
                specialist_stream.SpecialistStream,
                "_materialize_verified_chunk",
                side_effect=AssertionError("hostile manifest reached chunk materialization"),
            ):
                with self.assertRaisesRegex(ValueError, "record count bound"):
                    self._open_bound(root / "stream.json")
            hostile["range"]["record_count_per_family"] = 512
            hostile["chunk_size"] = 1_000_000_000
            (root / "stream.json").write_bytes(
                json.dumps(hostile, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
            )
            with mock.patch.object(
                specialist_stream.SpecialistStream,
                "_materialize_verified_chunk",
                side_effect=AssertionError("hostile manifest reached chunk materialization"),
            ):
                with self.assertRaisesRegex(ValueError, "chunk bound"):
                    self._open_bound(root / "stream.json")


    def test_open_requires_caller_bound_manifest_and_roots_before_consumption(self) -> None:
        from specialist_stream import build_stream_manifest

        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            manifest_path = root / "stream.json"
            manifest = build_stream_manifest(
                repo_root=ROOT,
                output_path=manifest_path,
                tokenizer_path=_frozen_tokenizer(root / "tokenizer.json"),
                model_config_path=ROOT / "configs" / "ember-restart-3b.json",
                record_count=512,
                chunk_size=64,
                data_class="MEASURED_RUNG",
            )
            with self.assertRaisesRegex(ValueError, "expected manifest"):
                __import__("specialist_stream").open_specialist_stream(repo_root=ROOT, manifest_path=manifest_path)
            trusted_manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            trusted_corpus_root_sha256 = manifest["corpus_root_sha256"]
            manifest["corpus_root_sha256"] = "0" * 64
            manifest_path.write_bytes(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")
            with self.assertRaisesRegex(ValueError, "manifest identity"):
                __import__("specialist_stream").open_specialist_stream(
                    repo_root=ROOT,
                    manifest_path=manifest_path,
                    expected_manifest_sha256=trusted_manifest_sha256,
                    expected_corpus_root_sha256=trusted_corpus_root_sha256,
                )

    def test_open_rejects_rebound_roles_and_noncanonical_family_chunk_schema(self) -> None:
        from specialist_stream import build_stream_manifest

        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            manifest_path = root / "stream.json"
            manifest = build_stream_manifest(
                repo_root=ROOT,
                output_path=manifest_path,
                tokenizer_path=_frozen_tokenizer(root / "tokenizer.json"),
                model_config_path=ROOT / "configs" / "ember-restart-3b.json",
                record_count=512,
                chunk_size=64,
                data_class="MEASURED_RUNG",
            )
            manifest["generator_sources"]["image"] = dict(manifest["generator_sources"]["audio"])
            manifest_path.write_bytes(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")
            with self.assertRaisesRegex(ValueError, "generator source role"):
                self._open_bound(manifest_path)

            manifest = build_stream_manifest(
                repo_root=ROOT,
                output_path=manifest_path,
                tokenizer_path=_frozen_tokenizer(root / "tokenizer.json"),
                model_config_path=ROOT / "configs" / "ember-restart-3b.json",
                record_count=512,
                chunk_size=64,
                data_class="MEASURED_RUNG",
            )
            manifest["verifier_sources"]["semantics"] = dict(manifest["verifier_sources"]["capability"])
            manifest_path.write_bytes(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")
            with self.assertRaisesRegex(ValueError, "verifier source role"):
                self._open_bound(manifest_path)
            manifest = build_stream_manifest(
                repo_root=ROOT,
                output_path=manifest_path,
                tokenizer_path=_frozen_tokenizer(root / "tokenizer.json"),
                model_config_path=ROOT / "configs" / "ember-restart-3b.json",
                record_count=512,
                chunk_size=64,
                data_class="MEASURED_RUNG",
            )
            manifest["families"]["tool"]["chunks"].pop()
            manifest["unexpected"] = "not closed"
            manifest_path.write_bytes(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")
            with self.assertRaisesRegex(ValueError, "stream manifest schema"):
                self._open_bound(manifest_path)
            manifest = build_stream_manifest(
                repo_root=ROOT,
                output_path=manifest_path,
                tokenizer_path=_frozen_tokenizer(root / "tokenizer.json"),
                model_config_path=ROOT / "configs" / "ember-restart-3b.json",
                record_count=512,
                chunk_size=64,
                data_class="MEASURED_RUNG",
            )
            manifest["families"]["tool"]["corpus_root_sha256"] = "0" * 64
            manifest_path.write_bytes(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")
            with self.assertRaisesRegex(ValueError, "family roots"):
                self._open_bound(manifest_path)

    def test_open_uses_bound_generator_when_loaded_callable_diverges(self) -> None:
        import specialist_stream

        manifest_path = ROOT / "data" / "ember-restart-3b" / "owned-specialist-stream-v1-4096.json"
        with mock.patch.object(specialist_stream, "vision_record_at", lambda *_args, **_kwargs: {}):
            record = self._open_bound(manifest_path).record_at("image", 0)
        self.assertEqual(record["active_expert"], "vision")
        self.assertIn("image_patches_u8_base64", record)

    def test_open_uses_bound_verifier_when_loaded_callable_diverges(self) -> None:
        import specialist_stream

        manifest_path = ROOT / "data" / "ember-restart-3b" / "owned-specialist-stream-v1-4096.json"
        with mock.patch.object(specialist_stream, "verify_image_supervision", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unbound verifier"))):
            stream = self._open_bound(manifest_path)
            record = stream.record_at("image", 0)
            receipt = stream.verify_record(record)
        self.assertEqual(receipt["result"], "VERIFIED")

    def test_open_uses_bound_generator_dependency_when_loaded_helper_diverges(self) -> None:
        import specialist_semantics

        manifest_path = ROOT / "data" / "ember-restart-3b" / "owned-specialist-stream-v1-4096.json"
        with mock.patch.object(specialist_semantics, "spatial_relation_caption", return_value="loaded helper divergence"):
            record = self._open_bound(manifest_path).record_at("image", 0)
        self.assertNotEqual(record["target_text"], "loaded helper divergence")

    def test_open_uses_bound_verifier_dependency_when_loaded_helper_diverges(self) -> None:
        import verify_capability_record

        manifest_path = ROOT / "data" / "ember-restart-3b" / "owned-specialist-stream-v1-4096.json"
        with mock.patch.object(verify_capability_record, "expected_receipt", return_value=None):
            stream = self._open_bound(manifest_path)
            record = stream.record_at("tool", 0)
            receipt = stream.verify_record(record)
        self.assertEqual(receipt["result"], "VERIFIED")
    def test_rebuilt_manifest_uses_exact_generator_dependency_bytes(self) -> None:
        from specialist_stream import build_stream_manifest
        import specialist_semantics

        real_source = ROOT / "tools" / "ember-restart-3b" / "specialist_semantics.py"
        real_sha256 = hashlib.sha256(real_source.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory) / "fixture"
            tokenizer_path, config_path = self._bounded_stream_fixture(root)
            source_path = root / "tools" / "ember-restart-3b" / "specialist_semantics.py"
            changed = source_path.read_bytes().replace(
                b'return f"red is {relation} of green" if relation in {"left", "right"} else f"red is {relation} green"',
                b'return "bound-helper-only-change"',
                1,
            )
            source_path.write_bytes(changed)
            manifest_path = root / "stream.json"
            manifest = build_stream_manifest(
                repo_root=root,
                output_path=manifest_path,
                tokenizer_path=tokenizer_path,
                model_config_path=config_path,
                record_count=512,
                chunk_size=64,
                data_class="MEASURED_RUNG",
            )
            stream = self._open_bound(manifest_path, repo_root=root)
            records, _cursor = stream.next_records(capability="image", cursor=None, limit=1)
            self.assertEqual(records[0]["target_text"], "bound-helper-only-change")
            self.assertEqual(manifest["verifier_sources"]["semantics"]["sha256"], hashlib.sha256(changed).hexdigest())
        self.assertEqual(hashlib.sha256(real_source.read_bytes()).hexdigest(), real_sha256)
        self.assertEqual(hashlib.sha256(Path(specialist_semantics.__file__).read_bytes()).hexdigest(), real_sha256)

    def test_rebuilt_manifest_uses_exact_verifier_dependency_bytes(self) -> None:
        from specialist_stream import build_stream_manifest
        import verify_capability_record

        real_source = ROOT / "tools" / "ember-restart-3b" / "verify_capability_record.py"
        real_sha256 = hashlib.sha256(real_source.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory) / "fixture"
            tokenizer_path, config_path = self._bounded_stream_fixture(root)
            source_path = root / "tools" / "ember-restart-3b" / "verify_capability_record.py"
            changed = source_path.read_bytes().replace(b'    return receipt\n\n\ndef verify_record', b'    return dict(receipt)\n\n\ndef verify_record', 1)
            source_path.write_bytes(changed)
            manifest_path = root / "stream.json"
            manifest = build_stream_manifest(
                repo_root=root,
                output_path=manifest_path,
                tokenizer_path=tokenizer_path,
                model_config_path=config_path,
                record_count=512,
                chunk_size=64,
                data_class="MEASURED_RUNG",
            )
            stream = self._open_bound(manifest_path, repo_root=root)
            records, _cursor = stream.next_records(capability="tool", cursor=None, limit=1)
            receipt = stream.verify_record(records[0])
            self.assertEqual(receipt["result"], "VERIFIED")
            self.assertEqual(records[0]["capability_receipt"]["verifier_sha256"], hashlib.sha256(changed).hexdigest())
            self.assertEqual(manifest["verifier_sources"]["capability"]["sha256"], hashlib.sha256(changed).hexdigest())
        self.assertEqual(hashlib.sha256(real_source.read_bytes()).hexdigest(), real_sha256)
        self.assertEqual(hashlib.sha256(Path(verify_capability_record.__file__).read_bytes()).hexdigest(), real_sha256)
    def test_bound_verifier_hash_remains_at_open_snapshot_after_source_change(self) -> None:
        from specialist_stream import build_stream_manifest

        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory) / "fixture"
            tokenizer_path, config_path = self._bounded_stream_fixture(root)
            source_path = root / "tools" / "ember-restart-3b" / "verify_capability_record.py"
            original = source_path.read_bytes()
            original_sha256 = hashlib.sha256(original).hexdigest()
            manifest_path = root / "stream.json"
            build_stream_manifest(
                repo_root=root,
                output_path=manifest_path,
                tokenizer_path=tokenizer_path,
                model_config_path=config_path,
                record_count=512,
                chunk_size=64,
                data_class="MEASURED_RUNG",
            )
            stream = self._open_bound(manifest_path, repo_root=root)
            changed = original + b"\n# copied verifier changed after open\n"
            source_path.write_bytes(changed)
            record = stream.record_at("tool", 0)
            stream.verify_record(record)
            self.assertEqual(record["capability_receipt"]["verifier_sha256"], original_sha256)
            rebuilt_path = root / "rebuilt.json"
            build_stream_manifest(
                repo_root=root,
                output_path=rebuilt_path,
                tokenizer_path=tokenizer_path,
                model_config_path=config_path,
                record_count=512,
                chunk_size=64,
                data_class="MEASURED_RUNG",
            )
            rebuilt = self._open_bound(rebuilt_path, repo_root=root)
            rebuilt_record = rebuilt.record_at("tool", 0)
            rebuilt.verify_record(rebuilt_record)
            self.assertEqual(rebuilt_record["capability_receipt"]["verifier_sha256"], hashlib.sha256(changed).hexdigest())
    def test_bound_module_rejects_dynamic_project_import(self) -> None:
        import specialist_stream

        source_path = ROOT / "tools" / "ember-restart-3b" / "build_owned_vision_scenes.py"
        with self.assertRaisesRegex(ValueError, "dynamic import"):
            specialist_stream._load_bound_module(
                ROOT,
                b"__import__('specialist_semantics')\n",
                source_path,
                source_kind="generator",
            )
    def test_bound_module_rejects_builtins_importer_access(self) -> None:
        import specialist_stream

        source_path = ROOT / "tools" / "ember-restart-3b" / "build_owned_vision_scenes.py"
        for source in (
            b"import builtins\nbuiltins.__import__('specialist_semantics')\n",
            b"import builtins\nvars(builtins)['__import__']('specialist_semantics')\n",
        ):
            with self.assertRaisesRegex(ValueError, "unrestricted importer"):
                specialist_stream._load_bound_module(ROOT, source, source_path, source_kind="generator")

    def test_bound_module_rejects_alias_importlib_and_ambient_registry(self) -> None:
        import specialist_stream

        source_path = ROOT / "tools" / "ember-restart-3b" / "build_owned_vision_scenes.py"
        with self.assertRaisesRegex(ValueError, "declared dependency contract"):
            specialist_stream._load_bound_module(
                ROOT,
                b"from importlib import import_module as loader\nloader('specialist_semantics')\n",
                source_path,
                source_kind="generator",
            )
        with self.assertRaisesRegex(ValueError, "ambient module registry"):
            specialist_stream._load_bound_module(
                ROOT,
                b"import sys\nsys.modules['specialist_semantics']\n",
                source_path,
                source_kind="generator",
            )
    def test_build_refuses_invalid_bound_record_before_manifest_or_receipt_publication(self) -> None:
        from specialist_stream import build_stream_manifest

        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory) / "fixture"
            tokenizer_path, config_path = self._bounded_stream_fixture(root)
            generator_path = root / "tools" / "ember-restart-3b" / "build_owned_vision_scenes.py"
            original = generator_path.read_bytes()
            marker = b"    return {\"schema_version\": \"ember-owned-semantic-record-v1\""
            offset = original.rfind(marker)
            self.assertGreaterEqual(offset, 0)
            generator_path.write_bytes(original[:offset] + b"    return {}\n")
            manifest_path = root / "stream.json"
            with self.assertRaisesRegex(ValueError, "record lacks a specialist capability"):
                build_stream_manifest(
                    repo_root=root,
                    output_path=manifest_path,
                    tokenizer_path=tokenizer_path,
                    model_config_path=config_path,
                    record_count=512,
                    chunk_size=64,
                    data_class="MEASURED_RUNG",
                )
            self.assertFalse(manifest_path.exists())
    def test_open_rejects_legacy_schema_alias(self) -> None:
        from specialist_stream import build_stream_manifest

        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            manifest_path = root / "stream.json"
            manifest = build_stream_manifest(
                repo_root=ROOT,
                output_path=manifest_path,
                tokenizer_path=_frozen_tokenizer(root / "tokenizer.json"),
                model_config_path=ROOT / "configs" / "ember-restart-3b.json",
                record_count=512,
                chunk_size=64,
                data_class="MEASURED_RUNG",
            )
            manifest["legacy_materialized_compatibility"] = None
            manifest_path.write_bytes(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")
            with self.assertRaisesRegex(ValueError, "stream manifest schema"):
                self._open_bound(manifest_path)

            manifest = build_stream_manifest(
                repo_root=ROOT,
                output_path=manifest_path,
                tokenizer_path=_frozen_tokenizer(root / "tokenizer.json"),
                model_config_path=ROOT / "configs" / "ember-restart-3b.json",
                record_count=512,
                chunk_size=64,
                data_class="MEASURED_RUNG",
            )
            manifest["range"]["start"] = False
            manifest_path.write_bytes(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")
            with self.assertRaisesRegex(ValueError, "invalid stream range"):
                self._open_bound(manifest_path)

    def test_open_reads_manifest_through_a_bounded_buffer_not_read_bytes(self) -> None:
        from specialist_stream import build_stream_manifest, open_specialist_stream

        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            root = Path(directory)
            manifest_path = root / "stream.json"
            manifest = build_stream_manifest(
                repo_root=ROOT,
                output_path=manifest_path,
                tokenizer_path=_frozen_tokenizer(root / "tokenizer.json"),
                model_config_path=ROOT / "configs" / "ember-restart-3b.json",
                record_count=512,
                chunk_size=64,
                data_class="MEASURED_RUNG",
            )
            expected_manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
            original_read_bytes = Path.read_bytes

            def reject_unbounded_manifest_read(path: Path) -> bytes:
                if path == manifest_path:
                    raise AssertionError("manifest read_bytes bypasses the bounded consumer buffer")
                return original_read_bytes(path)

            with mock.patch.object(Path, "read_bytes", autospec=True, side_effect=reject_unbounded_manifest_read):
                stream = open_specialist_stream(
                    repo_root=ROOT,
                    manifest_path=manifest_path,
                    expected_manifest_sha256=expected_manifest_sha256,
                    expected_corpus_root_sha256=manifest["corpus_root_sha256"],
                )
            self.assertEqual(stream.count, 512)
    def test_prepare_execution_selection_binds_closed_receipt_cursor_and_one_chunk_cache(self) -> None:
        """P2B derives an exact selection incrementally and opens it lazily."""
        manifest_path = ROOT / "data" / "ember-restart-3b" / "owned-specialist-stream-v1-4096.json"
        build_receipt_path = ROOT / "data" / "ember-restart-3b" / "owned-specialist-stream-v1-4096-build-receipt.json"
        stream = self._open_bound(manifest_path)
        materialized: list[int] = []
        original = stream._materialize_verified_chunk

        def counted(capability: str, start: int):
            materialized.append(start)
            return original(capability, start)

        stream._materialize_verified_chunk = counted  # type: ignore[method-assign]
        selection = stream.prepare_execution_selection(
            capability="image", selection_rule_id="image_scene_split_train_v1",
            build_receipt_path=build_receipt_path,
            expected_build_receipt_sha256="2e68402c914e842fe23c6ef69f1f8e957d858f7ad2de4d5467dfc65c949ead1e",
        )
        self.assertEqual(selection.receipt["stream_manifest_sha256"], "857835d9722e5d6410f4c6c34c537ad2af12bfb98c4d3eb242b3a2c99e591427")
        self.assertEqual(selection.receipt["stream_build_receipt_sha256"], "2e68402c914e842fe23c6ef69f1f8e957d858f7ad2de4d5467dfc65c949ead1e")
        self.assertEqual(selection.receipt["family_root_sha256"], stream.families["image"]["corpus_root_sha256"])
        self.assertEqual(selection.receipt["selection_rule_id"], "image_scene_split_train_v1")
        self.assertGreater(selection.receipt["selected_record_count"], 0)
        self.assertGreater(selection.receipt["selected_token_count"], 0)
        self.assertEqual(len(selection.receipt["selection_commitment_sha256"]), 64)
        self.assertGreaterEqual(len(materialized), 16)
        self.assertLessEqual(len(selection._chunk_cache), 1)
        self.assertFalse(hasattr(selection, "records"))
        materialized.clear()
        uninterrupted = selection.iter_from()
        first, cursor = next(uninterrupted)
        self.assertEqual(first["scene_split"], "train")
        self.assertLessEqual(len(materialized), 1)
        self.assertEqual(
            set(cursor),
            {"schema_version", "selection_receipt_sha256", "selection_rule_id", "selected_ordinal", "next_source_index", "global_step", "tokens_seen"},
        )
        self.assertEqual(cursor["selection_receipt_sha256"], hashlib.sha256(json.dumps(selection.receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest())
        self.assertEqual(cursor["selected_ordinal"], 1)
        self.assertGreater(cursor["next_source_index"], 0)
        selection._validate_cursor_progress(cursor)
        with self.assertRaisesRegex(ValueError, "selection cursor progress"):
            selection._validate_cursor_progress({**cursor, "selected_ordinal": 0})
        with self.assertRaisesRegex(ValueError, "selection cursor progress"):
            next(selection.iter_from({**cursor, "selected_ordinal": 0}))
        end_cursor = {**cursor, "selected_ordinal": selection.receipt["selected_record_count"], "next_source_index": stream.count}
        selection._validate_cursor_progress(end_cursor)
        with self.assertRaisesRegex(ValueError, "selection cursor progress"):
            selection._validate_cursor_progress({**end_cursor, "selected_ordinal": end_cursor["selected_ordinal"] - 1})
        uninterrupted_tail = [next(uninterrupted)[0]["sample_id"] for _ in range(3)]
        resumed = stream.open_execution_selection(receipt=selection.receipt, cursor=cursor)
        resumed_iterator = resumed.iter_from(cursor)
        resumed_tail = [next(resumed_iterator)[0]["sample_id"] for _ in range(3)]
        self.assertEqual(resumed_tail, uninterrupted_tail)
        with self.assertRaisesRegex(ValueError, "build receipt"):
            stream.prepare_execution_selection(capability="image", selection_rule_id="image_scene_split_train_v1", build_receipt_path=build_receipt_path, expected_build_receipt_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "selection cursor"):
            stream.open_execution_selection(receipt=selection.receipt, cursor={**cursor, "selection_receipt_sha256": "0" * 64})



    def test_execution_selection_supports_only_closed_capability_rules(self) -> None:
        manifest_path = ROOT / "data" / "ember-restart-3b" / "owned-specialist-stream-v1-4096.json"
        build_receipt_path = ROOT / "data" / "ember-restart-3b" / "owned-specialist-stream-v1-4096-build-receipt.json"
        stream = self._open_bound(manifest_path)
        for capability in ("audio", "reasoning", "tool"):
            selection = stream.prepare_execution_selection(
                capability=capability,
                selection_rule_id="all_records_semantic_pretraining_v1",
                build_receipt_path=build_receipt_path,
                expected_build_receipt_sha256="2e68402c914e842fe23c6ef69f1f8e957d858f7ad2de4d5467dfc65c949ead1e",
            )
            self.assertEqual(selection.receipt["capability"], capability)
            self.assertEqual(selection.receipt["selection_rule_id"], "all_records_semantic_pretraining_v1")
            self.assertEqual(selection.receipt["selected_record_count"], 4096)
            record, _cursor = next(selection.iter_from())
            self.assertEqual(record["active_expert"], capability)
        for capability, rule in (("image", "all_records_semantic_pretraining_v1"), ("audio", "image_scene_split_train_v1"), ("tool", "unknown")):
            with self.assertRaisesRegex(ValueError, "selection rule"):
                stream.prepare_execution_selection(
                    capability=capability,
                    selection_rule_id=rule,
                    build_receipt_path=build_receipt_path,
                    expected_build_receipt_sha256="2e68402c914e842fe23c6ef69f1f8e957d858f7ad2de4d5467dfc65c949ead1e",
                )

    def test_build_receipt_rejects_rehashed_internal_semantic_drift(self) -> None:
        from specialist_stream import SpecialistStream

        receipt_path = ROOT / "data" / "ember-restart-3b" / "owned-specialist-stream-v1-4096-build-receipt.json"
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            candidate = Path(directory) / "receipt.json"
            receipt = json.loads(receipt_path.read_bytes())
            receipt["data_class"] = "MEASURED_RUNG"
            candidate.write_bytes(json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")
            with self.assertRaisesRegex(ValueError, "data class"):
                SpecialistStream._read_bound_build_receipt(
                    candidate, hashlib.sha256(candidate.read_bytes()).hexdigest(),
                )

if __name__ == "__main__":
    unittest.main()
