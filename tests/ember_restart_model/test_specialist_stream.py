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
    def _open_bound(manifest_path: Path):
        from specialist_stream import open_specialist_stream

        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes)
        return open_specialist_stream(
            repo_root=ROOT,
            manifest_path=manifest_path,
            expected_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
            expected_corpus_root_sha256=manifest["corpus_root_sha256"],
        )
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
        manifest = json.loads(manifest_path.read_bytes())
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

if __name__ == "__main__":
    unittest.main()
