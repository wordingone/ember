# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Owned non-smoke vision-scene generator regressions."""

from __future__ import annotations

import base64
from collections import Counter
import sys
import unittest
from pathlib import Path

from tokenizers import Tokenizer, models, pre_tokenizers

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))
import build_owned_vision_scenes
from build_owned_vision_scenes import build_records, spatial_relation_caption, structural_scene_sha256


class OwnedVisionSceneTests(unittest.TestCase):
    def test_index_zero_and_131072_have_distinct_exact_raw_structure(self) -> None:
        """The old 32,768-variation cycle duplicated a train/test raw scene at these exact indices."""
        first_patches, first_coordinates = build_owned_vision_scenes._scene(0)
        repeated_patches, repeated_coordinates = build_owned_vision_scenes._scene(131_072)
        self.assertNotEqual(
            structural_scene_sha256(first_patches, first_coordinates),
            structural_scene_sha256(repeated_patches, repeated_coordinates),
        )

    def test_default_scale_grid_cycle_changes_coordinate_blind_raw_content(self) -> None:
        """The 65,536-record grid dimension must not recreate one four-label content group."""
        first_patches, _ = build_owned_vision_scenes._scene(0)
        grid_cycle_patches, _ = build_owned_vision_scenes._scene(4_096)
        self.assertNotEqual(
            build_owned_vision_scenes.coordinate_blind_content_sha256(first_patches),
            build_owned_vision_scenes.coordinate_blind_content_sha256(grid_cycle_patches),
        )
    def test_grouping_rejects_the_planted_0_131072_duplicate_before_split(self) -> None:
        """A structural duplicate cannot silently land in two independently assigned splits."""
        first_patches, first_coordinates = build_owned_vision_scenes._scene(0)
        first = build_owned_vision_scenes.SceneDescriptor(
            index=0, patches=first_patches, coordinates=first_coordinates,
            caption=spatial_relation_caption(first_patches, first_coordinates),
        )
        repeated = build_owned_vision_scenes.SceneDescriptor(
            index=131_072, patches=first_patches, coordinates=first_coordinates,
            caption=spatial_relation_caption(first_patches, first_coordinates),
        )
        with self.assertRaisesRegex(ValueError, "duplicate raw structure"):
            build_owned_vision_scenes.group_and_split_scenes((first, repeated))

    def test_grouping_rejects_conflicting_labels_for_identical_raw_structure(self) -> None:
        patches, coordinates = build_owned_vision_scenes._scene(0)
        first = build_owned_vision_scenes.SceneDescriptor(
            index=0, patches=patches, coordinates=coordinates,
            caption=spatial_relation_caption(patches, coordinates),
        )
        conflicting = build_owned_vision_scenes.SceneDescriptor(
            index=1, patches=patches, coordinates=coordinates,
            caption="red is above green",
        )
        with self.assertRaisesRegex(ValueError, "conflicting labels"):
            build_owned_vision_scenes.group_and_split_scenes((first, conflicting))
    def test_each_split_preserves_all_24_patch_permutation_classes(self) -> None:
        tokenizer = Tokenizer(models.WordLevel({"<unk>": 0, "red": 1, "is": 2, "left": 3, "of": 4, "green": 5, "right": 6, "above": 7, "below": 8}, unk_token="<unk>"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        records = build_records(tokenizer, count=512, image_marker=31_998)
        support = {"train": set(), "validation": set(), "test": set()}
        split_hashes = {name: set() for name in support}
        for record in records:
            index = int(record["sample_id"].rsplit("-", 1)[1])
            support[record["scene_split"]].add(build_owned_vision_scenes.patch_permutation_class(index))
            split_hashes[record["scene_split"]].add(record["capability_evidence"]["image"]["scene_sha256"])
        self.assertEqual(set(range(24)), support["train"])
        self.assertEqual(set(range(24)), support["validation"])
        self.assertEqual(set(range(24)), support["test"])
        self.assertFalse(split_hashes["train"] & split_hashes["validation"])
        self.assertFalse(split_hashes["train"] & split_hashes["test"])
        self.assertFalse(split_hashes["validation"] & split_hashes["test"])

    def test_structural_key_distinguishes_same_mean_raw_patch_bytes(self) -> None:
        patches, coordinates = build_owned_vision_scenes._scene(0)
        changed = list(patches)
        payload = bytearray(changed[0])
        pixels = [bytes(payload[offset : offset + 3]) for offset in range(0, len(payload), 3)]
        first = next(index for index, pixel in enumerate(pixels) if pixel != bytes(3))
        second = next(index for index, pixel in enumerate(pixels) if pixel == bytes(3))
        first_offset, second_offset = first * 3, second * 3
        payload[first_offset : first_offset + 3], payload[second_offset : second_offset + 3] = (
            payload[second_offset : second_offset + 3], payload[first_offset : first_offset + 3]
        )
        changed[0] = bytes(payload)
        self.assertEqual(sum(changed[0]), sum(patches[0]))
        self.assertNotEqual(
            structural_scene_sha256(patches, coordinates),
            structural_scene_sha256(changed, coordinates),
        )
    def test_records_are_multisample_raw_scenes_with_derived_spatial_targets(self) -> None:
        tokenizer = Tokenizer(models.WordLevel({"<unk>": 0, "red": 1, "is": 2, "left": 3, "of": 4, "green": 5, "right": 6, "above": 7, "below": 8}, unk_token="<unk>"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        records = build_records(tokenizer, count=512, image_marker=31_998)
        self.assertEqual(len(records), 512)
        captions = set()
        for record in records:
            self.assertEqual(record["active_expert"], "vision")
            self.assertEqual(len(record["image_patches_u8_base64"]), 4)
            self.assertEqual(sorted(record["image_coordinates"]), [[0, 0], [0, 1], [1, 0], [1, 1]])
            self.assertEqual(record["multimodal_spans"], [{"start": 0, "length": 4, "modality": "image", "attention_mode": "isolated"}])
            self.assertEqual(record["capability_evidence"]["image"]["derivation"], "raw_image_spatial_relation_execution")
            captions.add(record["target_text"])
        self.assertEqual(captions, {"red is left of green", "red is right of green", "red is above green", "red is below green"})
    def test_coordinate_only_relation_grouping_shares_raw_content_across_all_labels(self) -> None:
        tokenizer = Tokenizer(models.WordLevel({"<unk>": 0, "red": 1, "is": 2, "left": 3, "of": 4, "green": 5, "right": 6, "above": 7, "below": 8}, unk_token="<unk>"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        records = build_records(tokenizer, count=512, image_marker=31_998)
        labels_by_raw_scene: dict[tuple[object, ...], set[object]] = {}
        for record in records:
            raw_scene = tuple(record["image_patches_u8_base64"])
            labels_by_raw_scene.setdefault(raw_scene, set()).add(record["target_text"])
        self.assertEqual(len(labels_by_raw_scene), 128)
        self.assertTrue(all(labels == {
            "red is left of green", "red is right of green", "red is above green", "red is below green",
        } for labels in labels_by_raw_scene.values()))
    def test_spatial_records_balance_relations_preserve_histograms_and_require_coordinate_binding(self) -> None:
        """Owned vision labels must be raw-spatial, balanced, structurally unique, and coordinate-sensitive."""
        vocabulary = {"<unk>": 0, "red": 1, "is": 2, "left": 3, "of": 4, "green": 5, "right": 6, "above": 7, "below": 8}
        tokenizer = Tokenizer(models.WordLevel(vocabulary, unk_token="<unk>"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        records = build_records(tokenizer, count=512, image_marker=31_998)
        targets = Counter(record["target_text"] for record in records)
        self.assertEqual(targets, Counter({
            "red is left of green": 128,
            "red is right of green": 128,
            "red is above green": 128,
            "red is below green": 128,
        }))
        histograms = set()
        structures = set()
        shuffled_targets = []
        for record in records:
            patches = [base64.b64decode(value, validate=True) for value in record["image_patches_u8_base64"]]
            coordinates = record["image_coordinates"]
            self.assertEqual(spatial_relation_caption(patches, coordinates), record["target_text"])
            histograms.add(tuple(sorted(Counter(byte for patch in patches for byte in patch).items())))
            structures.add(structural_scene_sha256(patches, coordinates))
            permutation = (3, 2, 1, 0)
            shuffled_patches = [patches[index] for index in permutation]
            shuffled_targets.append(spatial_relation_caption(shuffled_patches, coordinates))
            paired_coordinates = [coordinates[index] for index in permutation]
            self.assertEqual(spatial_relation_caption(shuffled_patches, paired_coordinates), record["target_text"])
        self.assertEqual(len(histograms), 1)
        self.assertEqual(len(structures), len(records))
        self.assertGreaterEqual(sum(shuffled != record["target_text"] for shuffled, record in zip(shuffled_targets, records)), len(records) * 2 // 3)
    def test_spatial_scene_splits_are_deterministic_relation_balanced_and_structurally_disjoint(self) -> None:
        """The generator assigns whole counterfactual relation groups to one split without scene overlap."""
        tokenizer = Tokenizer(models.WordLevel({"<unk>": 0, "red": 1, "is": 2, "left": 3, "of": 4, "green": 5, "right": 6, "above": 7, "below": 8}, unk_token="<unk>"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        records = build_records(tokenizer, count=512, image_marker=31_998)
        split_hashes = {"train": set(), "validation": set(), "test": set()}
        split_targets = {name: Counter() for name in split_hashes}
        for record in records:
            split = record["scene_split"]
            scene_sha256 = record["capability_evidence"]["image"]["scene_sha256"]
            split_hashes[split].add(scene_sha256)
            split_targets[split][record["target_text"]] += 1
        self.assertEqual(sum(len(values) for values in split_hashes.values()), len(records))
        self.assertTrue(all(len(values) > 0 for values in split_hashes.values()))
        self.assertTrue(all(len(targets) == 4 and len(set(targets.values())) == 1 for targets in split_targets.values()))

    def test_coordinate_blind_counterfactual_groups_are_whole_and_ratio_stratified(self) -> None:
        """A raw-content group contains all labels and is assigned to exactly one declared split."""
        tokenizer = Tokenizer(models.WordLevel({"<unk>": 0, "red": 1, "is": 2, "left": 3, "of": 4, "green": 5, "right": 6, "above": 7, "below": 8}, unk_token="<unk>"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        records = build_records(tokenizer, count=512, image_marker=31_998)
        groups: dict[tuple[str, ...], list[dict[str, object]]] = {}
        for record in records:
            key = tuple(sorted(record["image_patches_u8_base64"]))
            groups.setdefault(key, []).append(record)
        self.assertEqual(len(groups), 128)
        split_counts = Counter()
        for members in groups.values():
            self.assertEqual(len(members), 4)
            self.assertEqual({member["target_text"] for member in members}, {
                "red is left of green", "red is right of green", "red is above green", "red is below green",
            })
            self.assertEqual({member["scene_split"] for member in members}, {members[0]["scene_split"]})
            split_counts[members[0]["scene_split"]] += 1
        self.assertEqual(split_counts, Counter({"train": 64, "validation": 32, "test": 32}))

    def test_default_scale_split_plan_is_declared_without_materializing_records(self) -> None:
        plan = build_owned_vision_scenes.declared_split_plan()
        self.assertEqual(plan["record_count"], 65_536)
        self.assertEqual(plan["group_count"], 16_384)
        self.assertEqual(plan["group_counts"], {"train": 8192, "validation": 4096, "test": 4096})
    def test_serialized_split_order_is_deterministically_shuffled_from_record_content(self) -> None:
        """Final per-split serialization cannot retain source-index relation cycles."""
        tokenizer = Tokenizer(models.WordLevel({"<unk>": 0, "red": 1, "is": 2, "left": 3, "of": 4, "green": 5, "right": 6, "above": 7, "below": 8}, unk_token="<unk>"))
        tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
        first = build_records(tokenizer, count=512, image_marker=31_998)
        second = build_records(tokenizer, count=512, image_marker=31_998)
        self.assertEqual(
            [record["sample_id"] for record in first],
            [record["sample_id"] for record in second],
        )
        for split in ("train", "validation", "test"):
            sample_ids = [record["sample_id"] for record in first if record["scene_split"] == split]
            self.assertNotEqual(sample_ids, sorted(sample_ids))

    def test_serialized_order_helpers_have_one_source_authority_each(self) -> None:
        """Python must not silently shadow a prior content-bound ordering helper."""
        source = (ROOT / "tools" / "ember-restart-3b" / "build_owned_vision_scenes.py").read_text(
            encoding="utf-8",
        )
        self.assertEqual(source.count("def _serialized_order_content_sha256("), 1)
        self.assertEqual(source.count("def _shuffle_serialized_records_within_splits("), 1)
if __name__ == "__main__":
    unittest.main()
