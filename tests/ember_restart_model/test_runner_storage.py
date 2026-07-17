# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Production runner storage preflight tests."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

import checkpoint_artifacts
import run_vertical_slice


class RunnerStorageTests(unittest.TestCase):
    def test_quarantine_collision_preserves_existing_and_source_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            source = parent / "checkpoint-source"
            source.mkdir()
            source.joinpath("shared.pt").write_bytes(b"source-bytes")
            quarantine = parent / ".checkpoint-quarantine"
            quarantine.mkdir()
            real_publish = checkpoint_artifacts._atomic_publish_no_replace
            seen_targets: list[Path] = []

            def collide(candidate: Path, destination: Path) -> None:
                seen_targets.append(destination)
                destination.mkdir()
                destination.joinpath("existing-sentinel").write_bytes(b"preserved")
                real_publish(candidate, destination)

            with unittest.mock.patch("run_vertical_slice._atomic_publish_no_replace", side_effect=collide, create=True):
                with self.assertRaises(FileExistsError):
                    run_vertical_slice._move_bundle_to_quarantine(source, prefix="candidate")
            self.assertEqual(source.joinpath("shared.pt").read_bytes(), b"source-bytes")
            self.assertEqual(len(seen_targets), 1)
            self.assertEqual(seen_targets[0].joinpath("existing-sentinel").read_bytes(), b"preserved")

    def test_quarantine_move_rejects_lexical_symlink_source_before_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            outside = parent / "outside-bundle"
            outside.mkdir()
            outside.joinpath("shared.pt").write_bytes(b"outside-bytes")
            escape = parent / "checkpoint-escape"
            try:
                escape.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")
            with unittest.mock.patch("run_vertical_slice._atomic_publish_no_replace", side_effect=AssertionError("must not mutate link target")) as publish:
                with self.assertRaisesRegex(ValueError, "link|reparse"):
                    run_vertical_slice._move_bundle_to_quarantine(escape)
            publish.assert_not_called()
            self.assertTrue(escape.is_symlink())
            self.assertEqual(outside.joinpath("shared.pt").read_bytes(), b"outside-bytes")

    def test_quarantine_move_rejects_symlink_component_before_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            outside_parent = parent / "outside-parent"
            outside = outside_parent / "checkpoint-outside"
            outside.mkdir(parents=True)
            outside.joinpath("shared.pt").write_bytes(b"outside-bytes")
            alias = parent / "alias"
            try:
                alias.symlink_to(outside_parent, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")
            with unittest.mock.patch("run_vertical_slice._atomic_publish_no_replace", side_effect=AssertionError("must not mutate link target")) as publish:
                with self.assertRaisesRegex(ValueError, "link|reparse"):
                    run_vertical_slice._move_bundle_to_quarantine(alias / "checkpoint-outside")
            publish.assert_not_called()
            self.assertEqual(outside.joinpath("shared.pt").read_bytes(), b"outside-bytes")

    def test_retention_prunes_only_after_successful_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            oldest = parent / "checkpoint-oldest"; oldest.mkdir()
            middle = parent / "checkpoint-middle"; middle.mkdir()
            now = time.time_ns(); os.utime(oldest, ns=(now - 2_000_000_000, now - 2_000_000_000)); os.utime(middle, ns=(now - 1_000_000_000, now - 1_000_000_000))
            with self.assertRaisesRegex(RuntimeError, "writer failed"):
                run_vertical_slice._retain_after_success(parent, max_count=2, operation=lambda: (_ for _ in ()).throw(RuntimeError("writer failed")))
            self.assertTrue(oldest.exists())
            self.assertTrue(middle.exists())
            newest = parent / "checkpoint-newest"
            with self.assertRaisesRegex(RuntimeError, "selectable checkpoint count"):
                run_vertical_slice._retain_after_success(parent, max_count=2, operation=lambda: (newest.mkdir(), "published")[1])
            self.assertTrue(oldest.exists())
            self.assertTrue(middle.exists())
            self.assertTrue(newest.exists())
            self.assertFalse((parent / ".checkpoint-quarantine").exists())
    def test_max_count_never_claims_capacity_from_quarantine_move(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            old = parent / "checkpoint-old"
            newest = parent / "checkpoint-new"
            old.mkdir()
            newest.mkdir()
            (old / "state.bin").write_bytes(b"old")
            (newest / "state.bin").write_bytes(b"new")
            with self.assertRaisesRegex(RuntimeError, "selectable checkpoint count"):
                run_vertical_slice._enforce_retention(parent, max_count=1)
            self.assertTrue(old.exists())
            self.assertTrue(newest.exists())

    def test_custody_reconciliation_covers_live_quarantine_and_deleted_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            live = parent / "checkpoint-live"
            quarantine = parent / ".checkpoint-quarantine" / "candidate-old"
            live.mkdir()
            quarantine.mkdir(parents=True)
            (live / "shared.pt").write_bytes(b"live")
            (quarantine / "shared.pt").write_bytes(b"quarantine")
            pointer = ".checkpoint-quarantine/deleted-evidence.json"
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            ledger.write_text(
                json.dumps(
                    {"schema_version": "ember-checkpoint-custody-deletion-v1", "event": "DELETED", "pointer": pointer, "bytes": 17, "sha256": "a" * 64, "reason": "test"},
                    sort_keys=True,
                    separators=(",", ":"),
                ) + "\n",
                encoding="utf-8",
            )
            reconciliation = run_vertical_slice._custody_reconciliation(parent)
            self.assertEqual(reconciliation["schema_version"], "ember-checkpoint-custody-reconciliation-v1")
            self.assertEqual(reconciliation["live_bytes"], 4)
            self.assertEqual(reconciliation["quarantine_bytes"], 10)
            self.assertEqual(reconciliation["deleted_bytes"], 17)
            self.assertEqual(reconciliation["reconciled_bytes"], reconciliation["physical_bytes"] + 17)

    def test_custody_reconciliation_rejects_lone_committed_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            ledger.write_text(json.dumps({"schema_version": "ember-checkpoint-custody-deletion-v1", "event": "COMMITTED", "pointer": ".checkpoint-quarantine/missing.json", "bytes": 17, "sha256": "a" * 64, "reason": "test"}, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "COMMITTED|transition"):
                run_vertical_slice._custody_reconciliation(parent)

    def test_custody_reconciliation_rejects_duplicate_or_reversed_transitions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            base = {"schema_version": "ember-checkpoint-custody-deletion-v1", "pointer": ".checkpoint-quarantine/missing.json", "bytes": 17, "sha256": "a" * 64, "reason": "test"}
            events = [{**base, "event": "PREPARED"}, {**base, "event": "COMMITTED"}, {**base, "event": "COMMITTED"}]
            ledger.write_text("\n".join(json.dumps(event, sort_keys=True, separators=(",", ":")) for event in events) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "duplicate|transition"):
                run_vertical_slice._custody_reconciliation(parent)

    def test_retention_byte_cap_charges_quarantined_bundle_after_move(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            old = parent / "checkpoint-old"
            newest = parent / "checkpoint-new"
            old.mkdir()
            newest.mkdir()
            old.joinpath("state.bin").write_bytes(b"old!!")
            newest.joinpath("state.bin").write_bytes(b"newest!")
            now = time.time_ns()
            os.utime(old, ns=(now - 2_000_000_000, now - 2_000_000_000))
            os.utime(newest, ns=(now - 1_000_000_000, now - 1_000_000_000))
            with self.assertRaisesRegex(RuntimeError, "custody"):
                run_vertical_slice._enforce_retention(parent, max_serialized_bytes=8)
            self.assertFalse(old.exists())
            self.assertTrue(newest.exists())
            retained = [path for path in (parent / ".checkpoint-quarantine").iterdir() if path.is_dir() and path.name.startswith("candidate-")]
            self.assertEqual(len(retained), 1)
            self.assertEqual((retained[0] / "state.bin").read_bytes(), b"old!!")
            self.assertGreaterEqual(run_vertical_slice._custody_serialized_bytes(parent), 12)

    def test_custody_charge_uses_zero_increment_for_external_hardlink(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            anchor = parent / "anchor.pt"
            anchor.write_bytes(b"anchor-bytes")
            bundle = parent / "checkpoint-hardlink"
            bundle.mkdir()
            os.link(anchor, bundle / "expert-vision.pt")
            manifest = {
                "shards": [{"path": "expert-vision.pt", "bytes": len(b"anchor-bytes"), "publication_mode": "hardlink", "incremental_bytes": 0}],
            }
            manifest_path = bundle / "checkpoint-manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(
                run_vertical_slice._custody_serialized_bytes(parent),
                anchor.stat().st_size + manifest_path.stat().st_size,
            )

    def test_zero_increment_receipt_cannot_zero_original_or_unique_inode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            first = parent / "checkpoint-a"
            second = parent / "checkpoint-b"
            forged = parent / "checkpoint-forged"
            first.mkdir()
            second.mkdir()
            forged.mkdir()
            original = first / "expert-vision.pt"
            original.write_bytes(b"original-shard")
            os.link(original, second / "expert-vision.pt")
            forged_shard = forged / "expert-tool.pt"
            forged_shard.write_bytes(b"forged-single")
            for bundle, shard in ((first, "expert-vision.pt"), (second, "expert-vision.pt"), (forged, "expert-tool.pt")):
                (bundle / "checkpoint-manifest.json").write_text(
                    json.dumps(
                        {"shards": [{"path": shard, "bytes": (bundle / shard).stat().st_size, "publication_mode": "hardlink", "incremental_bytes": 0}]}
                    ),
                    encoding="utf-8",
                )
            unique_ids: set[tuple[int, int] | str] = set()
            expected = 0
            for path in parent.rglob("*"):
                if not path.is_file():
                    continue
                identity = run_vertical_slice._file_identity(path)
                if identity in unique_ids:
                    continue
                unique_ids.add(identity)
                expected += path.stat().st_size
            measured = run_vertical_slice._custody_serialized_bytes(parent)
            self.assertEqual(measured, expected)
            self.assertGreaterEqual(measured, original.stat().st_size + forged_shard.stat().st_size)


    def test_retention_prunes_measured_bytes_but_keeps_a_known_good_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            old = parent / "checkpoint-old"; old.mkdir()
            newest = parent / "checkpoint-new"; newest.mkdir()
            (old / "state.bin").write_bytes(b"old!!")
            (newest / "state.bin").write_bytes(b"newest!")
            now = time.time_ns(); os.utime(old, ns=(now - 1_000_000_000, now - 1_000_000_000))
            self.assertTrue(hasattr(run_vertical_slice, "_bundle_serialized_bytes"))
            with self.assertRaisesRegex(RuntimeError, "custody"):
                run_vertical_slice._enforce_retention(parent, max_serialized_bytes=8)
            self.assertFalse(old.exists())
            self.assertTrue(newest.exists())
            self.assertEqual(run_vertical_slice._bundle_serialized_bytes(newest), 7)
            retained = [path for path in (parent / ".checkpoint-quarantine").iterdir() if path.is_dir() and path.name.startswith("candidate-")]
            self.assertEqual(len(retained), 1)
            self.assertEqual((retained[0] / "state.bin").read_bytes(), b"old!!")

    def test_receipt_aware_retention_ignores_unverified_orphans(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            orphan = parent / "checkpoint-orphan"
            orphan.mkdir()
            (orphan / "checkpoint-manifest.json").write_text("{}", encoding="utf-8")
            run_vertical_slice._enforce_retention(parent, max_count=1, receipt_aware=True)
            self.assertFalse(orphan.exists())
            retained = [path for path in (parent / ".checkpoint-quarantine").iterdir() if path.is_dir() and path.name.startswith("candidate-")]
            self.assertEqual(len(retained), 1)
            self.assertEqual((retained[0] / "checkpoint-manifest.json").read_text(encoding="utf-8"), "{}")
            evidence = list((parent / ".checkpoint-quarantine").glob("*.json"))
            self.assertEqual(len(evidence), 1)
            self.assertEqual(json.loads(evidence[0].read_text(encoding="utf-8"))["result"], "UNSELECTABLE")
    def test_receiptless_final_orphan_is_reclaimed_before_new_publication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            orphan = parent / "checkpoint-next"
            orphan.mkdir()
            (orphan / "checkpoint-manifest.json").write_text("{}", encoding="utf-8")
            observed: list[bool] = []
            run_vertical_slice._retain_after_success(parent, max_count=1, receipt_aware=True, operation=lambda: observed.append(orphan.exists()))
            self.assertEqual(observed, [False])
            self.assertFalse(orphan.exists())
            retained = [path for path in (parent / ".checkpoint-quarantine").iterdir() if path.is_dir() and path.name.startswith("candidate-")]
            self.assertEqual(len(retained), 1)

    def test_live_pid_staging_is_never_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            staging = parent / f".checkpoint-active.{os.getpid()}.abc.staging"
            staging.mkdir()
            (staging / "bulk.bin").write_bytes(b"active")
            run_vertical_slice._retain_after_success(parent, max_count=1, receipt_aware=True, operation=lambda: "ok")
            self.assertTrue(staging.exists())

    def test_stale_staging_is_reclaimed_to_bounded_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            staging = parent / ".checkpoint-dead.999999.abc.staging"
            staging.mkdir()
            (staging / "checkpoint-manifest.json").write_text("{}", encoding="utf-8")
            (staging / "bulk.bin").write_bytes(b"bulk")
            run_vertical_slice._retain_after_success(parent, max_count=1, receipt_aware=True, operation=lambda: "ok")
            self.assertFalse(staging.exists())
            retained = [path for path in (parent / ".checkpoint-quarantine").iterdir() if path.is_dir() and path.name.startswith("candidate-")]
            self.assertEqual(len(retained), 1)
            self.assertEqual((retained[0] / "bulk.bin").read_bytes(), b"bulk")
            evidence = list((parent / ".checkpoint-quarantine").glob("*.json"))
            self.assertTrue(any("staging" in path.name for path in evidence))
            self.assertLessEqual(len(evidence), 32)
            self.assertLessEqual(sum(path.stat().st_size for path in evidence), 1024 * 1024)

    def test_quarantine_evidence_is_bounded_across_many_orphans(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            for index in range(40):
                orphan = parent / f"checkpoint-orphan-{index:02d}"
                orphan.mkdir()
                (orphan / "checkpoint-manifest.json").write_text("{}", encoding="utf-8")
            run_vertical_slice._enforce_retention(parent, max_count=1, receipt_aware=True)
            evidence = list((parent / ".checkpoint-quarantine").glob("*.json"))
            self.assertLessEqual(len(evidence), 32)
            self.assertLessEqual(sum(path.stat().st_size for path in evidence), 1024 * 1024)
    def test_production_artifact_root_requires_b_unless_c_relocation_is_explicitly_runner_bound(self) -> None:
        with self.assertRaisesRegex(ValueError, "B:"):
            run_vertical_slice.production_artifact_root(Path("C:/tmp/ember-restart-niko-3b/production-artifacts/vision"))
        with self.assertRaisesRegex(ValueError, "runner-bound"):
            run_vertical_slice.production_artifact_root(Path("C:/tmp/ember-restart-niko-3b/production-artifacts/vision"), c_relocated_under_disk_budget_runner=False)
        accepted = run_vertical_slice.production_artifact_root(Path("B:/ember-checkpoint"))
        self.assertEqual(accepted.drive.upper(), "B:")
        custody = Path("C:/tmp/ember-restart-niko-3b/production-artifacts")
        with self.assertRaisesRegex(ValueError, "custody root"):
            run_vertical_slice.production_artifact_root(Path("C:/tmp/ember-restart-niko-3b/production-artifacts/vision"), c_relocated_under_disk_budget_runner=True)
        relocated = run_vertical_slice.production_artifact_root(
            Path("C:/tmp/ember-restart-niko-3b/production-artifacts/vision"),
            c_relocated_under_disk_budget_runner=True,
            relocation_custody_root=custody,
        )
        self.assertEqual(relocated.drive.upper(), "C:")
        with self.assertRaisesRegex(ValueError, "C:"):
            run_vertical_slice.production_artifact_root(Path("B:/ember-checkpoint"), c_relocated_under_disk_budget_runner=True, relocation_custody_root=custody)
        with self.assertRaisesRegex(ValueError, "custody root"):
            run_vertical_slice.production_artifact_root(Path("C:/tmp/outside"), c_relocated_under_disk_budget_runner=True, relocation_custody_root=custody)

    def test_quarantine_candidates_are_never_valid_production_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            custody = Path(directory) / "custody"
            candidate = custody / ".checkpoint-quarantine" / "candidate-checkpoint-failed"
            candidate.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "quarantine"):
                run_vertical_slice.production_artifact_root(
                    candidate,
                    c_relocated_under_disk_budget_runner=True,
                    relocation_custody_root=custody,
                )

    def test_custody_accounting_rejects_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            outside = parent / "outside.bin"
            outside.write_bytes(b"outside")
            bundle = parent / "checkpoint-escape"
            bundle.mkdir()
            link = bundle / "shared.pt"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")
            with self.assertRaisesRegex(RuntimeError, "symlink or reparse"):
                run_vertical_slice._custody_serialized_bytes(parent)

    def test_evidence_deletion_prepared_failure_preserves_and_reconciles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            quarantine = parent / ".checkpoint-quarantine"
            quarantine.mkdir()
            for index in range(33):
                (quarantine / f"old-{index:02d}.json").write_bytes(f"old-{index}".encode("ascii"))
            real_unlink = Path.unlink
            def fail_old(path: Path, *args: object, **kwargs: object) -> None:
                if path.name.startswith("old-"):
                    raise OSError("injected unlink failure")
                real_unlink(path, *args, **kwargs)
            with unittest.mock.patch.object(Path, "unlink", new=fail_old):
                with self.assertRaisesRegex(RuntimeError, "did not commit"):
                    run_vertical_slice._write_bounded_quarantine_evidence(parent, "new", {"result": "UNSELECTABLE"})
            self.assertEqual(len(list(quarantine.glob("old-*.json"))), 33)
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([event["event"] for event in events], ["PREPARED"])
            reconciliation = run_vertical_slice._custody_reconciliation(parent)
            self.assertEqual(reconciliation["deleted_bytes"], 0)
            self.assertEqual(reconciliation["reconciled_bytes"], run_vertical_slice._custody_serialized_bytes(parent))

    def test_prepared_unlink_crash_replays_once_without_false_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            quarantine = parent / ".checkpoint-quarantine"
            quarantine.mkdir()
            pointer = ".checkpoint-quarantine/crashed.json"
            payload = b"crashed-evidence"
            digest = __import__("hashlib").sha256(payload).hexdigest()
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            ledger.write_text(json.dumps({"schema_version": "ember-checkpoint-custody-deletion-v1", "event": "PREPARED", "pointer": pointer, "bytes": len(payload), "sha256": digest, "reason": "crash replay"}) + "\n", encoding="utf-8")
            (quarantine / "crashed.json").write_bytes(payload)
            self.assertEqual(run_vertical_slice._custody_reconciliation(parent)["deleted_bytes"], 0)
            (quarantine / "crashed.json").unlink()
            first = run_vertical_slice._custody_reconciliation(parent)
            second = run_vertical_slice._custody_reconciliation(parent)
            self.assertEqual(first["deleted_bytes"], len(payload))
            self.assertEqual(second["deleted_bytes"], len(payload))

    def test_repeated_evidence_name_never_overwrites_prior_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            first = run_vertical_slice._write_bounded_quarantine_evidence(parent, "same-name", {"result": "FIRST"})
            second = run_vertical_slice._write_bounded_quarantine_evidence(parent, "same-name", {"result": "SECOND"})
            self.assertNotEqual(first, second)
            self.assertEqual(json.loads(first.read_text(encoding="utf-8"))["result"], "FIRST")
            self.assertEqual(json.loads(second.read_text(encoding="utf-8"))["result"], "SECOND")
            self.assertEqual(len(list((parent / ".checkpoint-quarantine").glob("same-name*.json"))), 2)

    def test_pruned_evidence_name_is_never_reused_after_committed_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            with unittest.mock.patch.object(run_vertical_slice, "_MAX_QUARANTINE_FILES", 1):
                first = run_vertical_slice._write_bounded_quarantine_evidence(parent, "same-name", {"result": "FIRST"})
                first_size = first.stat().st_size
                run_vertical_slice._write_bounded_quarantine_evidence(parent, "other-name", {"result": "OTHER"})
                third = run_vertical_slice._write_bounded_quarantine_evidence(parent, "same-name", {"result": "THIRD"})
            self.assertNotEqual(first, third)
            self.assertEqual(json.loads(third.read_text(encoding="utf-8"))["result"], "THIRD")
            reconciliation = run_vertical_slice._custody_reconciliation(parent)
            self.assertGreaterEqual(reconciliation["deleted_bytes"], first_size)

    def test_prune_then_recreate_identical_payload_uses_new_generation_and_reconciles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            with unittest.mock.patch.object(run_vertical_slice, "_MAX_QUARANTINE_FILES", 1):
                evidence_a = run_vertical_slice._write_bounded_quarantine_evidence(parent, "same-name", {"result": "A"})
                first_size = evidence_a.stat().st_size
                run_vertical_slice._write_bounded_quarantine_evidence(parent, "other-name", {"result": "B"})
                self.assertFalse(evidence_a.exists())
                recreated_a = run_vertical_slice._write_bounded_quarantine_evidence(parent, "same-name", {"result": "A"})
            self.assertNotEqual(recreated_a, evidence_a)
            self.assertTrue(recreated_a.name.endswith("-g1.json"))
            self.assertEqual(json.loads(recreated_a.read_text(encoding="utf-8"))["result"], "A")
            reconciliation = run_vertical_slice._custody_reconciliation(parent)
            self.assertGreaterEqual(reconciliation["deleted_bytes"], first_size)
            self.assertEqual(reconciliation["physical_bytes"], run_vertical_slice._custody_serialized_bytes(parent))

    def test_existing_content_addressed_evidence_is_never_returned_after_prune(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            with unittest.mock.patch.object(run_vertical_slice, "_MAX_QUARANTINE_FILES", 2):
                evidence_a = run_vertical_slice._write_bounded_quarantine_evidence(parent, "same-name", {"result": "A"})
                evidence_b = run_vertical_slice._write_bounded_quarantine_evidence(parent, "other-name", {"result": "B"})
            os.utime(evidence_b, ns=(evidence_a.stat().st_mtime_ns + 1, evidence_a.stat().st_mtime_ns + 1))
            with unittest.mock.patch.object(run_vertical_slice, "_MAX_QUARANTINE_FILES", 1):
                repeated_a = run_vertical_slice._write_bounded_quarantine_evidence(parent, "same-name", {"result": "A"})
            self.assertEqual(repeated_a, evidence_a)
            self.assertTrue(repeated_a.exists())
            self.assertEqual(json.loads(repeated_a.read_text(encoding="utf-8"))["result"], "A")
            run_vertical_slice._custody_reconciliation(parent)

if __name__ == "__main__":
    unittest.main()
