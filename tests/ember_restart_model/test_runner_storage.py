# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Production runner storage preflight tests."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import posixpath
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

import checkpoint_artifacts
import durable_io
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

    def test_post_publication_retention_failure_preserves_safe_checkpoint_id(self) -> None:
        published = ({"published_checkpoint_id": "checkpoint-continue-seed-84-from-step-204"}, {"counter": "ok"})
        with unittest.mock.patch.object(run_vertical_slice, "_enforce_retention", side_effect=RuntimeError("retention failed")):
            with self.assertRaises(run_vertical_slice.PublishedHousekeepingError) as raised:
                run_vertical_slice._retain_after_success(Path("B:/checkpoints"), max_count=1, operation=lambda: published)
        self.assertEqual(raised.exception.published_checkpoint_id, "checkpoint-continue-seed-84-from-step-204")
        self.assertIsInstance(raised.exception.__cause__, RuntimeError)

        original = RuntimeError("ordinary trainer result has no published locator")
        with unittest.mock.patch.object(run_vertical_slice, "_enforce_retention", side_effect=original):
            with self.assertRaises(RuntimeError) as ordinary:
                run_vertical_slice._retain_after_success(Path("B:/checkpoints"), max_count=1, operation=lambda: ({}, {}))
        self.assertIs(ordinary.exception, original)
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
            pointer = ".checkpoint-quarantine/evidence-" + "a" * 64 + ".json"
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

    def test_prepared_external_transaction_aborts_when_ledger_is_still_old(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as receipt_directory:
            parent = Path(directory)
            prepared = run_vertical_slice._next_custody_ledger_frame({"event": "PREPARED", "pointer": ".checkpoint-quarantine/evidence-" + "a" * 64 + ".json", "bytes": 17, "sha256": "a" * 64, "reason": "transaction abort"}, [])
            old = (json.dumps(prepared, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            committed = run_vertical_slice._next_custody_ledger_frame({"event": "COMMITTED", "pointer": prepared["pointer"], "bytes": 17, "sha256": "a" * 64, "reason": "transaction abort"}, [prepared])
            new = old + (json.dumps(committed, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            ledger.write_bytes(old)
            transaction_path = Path(receipt_directory) / "ledger-transaction.json"
            run_vertical_slice.prepare_custody_ledger_transaction(receipt_path=transaction_path, old_ledger=old, new_ledger=new, operation_id="old-ledger-abort", subject=run_vertical_slice._custody_path_subject(parent.resolve()))
            receipt = run_vertical_slice.recover_torn_custody_ledger_tail(parent, transaction_receipt_path=transaction_path)
            self.assertEqual(ledger.read_bytes(), old)
            self.assertEqual(receipt["result"], "ABORTED")
            self.assertEqual(json.loads(transaction_path.read_text(encoding="utf-8"))["result"], "ABORTED")

    def test_direct_recovery_rejects_foreign_custody_subject_before_ledger_or_receipt_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as receipt_directory:
            root_a = Path(directory) / "root-a"
            root_b = Path(directory) / "root-b"
            root_a.mkdir()
            root_b.mkdir()
            prepared = run_vertical_slice._next_custody_ledger_frame(
                {"event": "PREPARED", "pointer": ".checkpoint-quarantine/evidence-" + "a" * 64 + ".json", "bytes": 17, "sha256": "a" * 64, "reason": "foreign-root"},
                [],
            )
            new = (json.dumps(prepared, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            (root_a / ".checkpoint-custody-deletion-ledger.jsonl").write_bytes(new)
            receipt_path = Path(receipt_directory) / "cross-root.json"
            run_vertical_slice.prepare_custody_ledger_transaction(
                receipt_path=receipt_path,
                old_ledger=b"",
                new_ledger=new,
                operation_id="cross-root",
                subject=run_vertical_slice._custody_path_subject(root_b.resolve()),
            )
            before_ledger = (root_a / ".checkpoint-custody-deletion-ledger.jsonl").read_bytes()
            before_receipt = receipt_path.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "subject"):
                run_vertical_slice.recover_torn_custody_ledger_tail(root_a, transaction_receipt_path=receipt_path)
            self.assertEqual((root_a / ".checkpoint-custody-deletion-ledger.jsonl").read_bytes(), before_ledger)
            self.assertEqual(receipt_path.read_bytes(), before_receipt)
    def test_direct_recovery_rejects_same_basename_cross_parent_subject_before_mutation(self) -> None:
        """Opaque path identity must distinguish separate custody roots named checkpoint."""
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as receipt_directory:
            root_a = Path(directory) / "a" / "checkpoint"
            root_b = Path(directory) / "b" / "checkpoint"
            root_a.mkdir(parents=True)
            root_b.mkdir(parents=True)
            prepared = run_vertical_slice._next_custody_ledger_frame(
                {"event": "PREPARED", "pointer": ".checkpoint-quarantine/evidence-" + "a" * 64 + ".json", "bytes": 17, "sha256": "a" * 64, "reason": "same-basename-cross-parent"},
                [],
            )
            new = (json.dumps(prepared, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            ledger = root_a / ".checkpoint-custody-deletion-ledger.jsonl"
            ledger.write_bytes(new)
            receipt_path = Path(receipt_directory) / "cross-parent.json"
            run_vertical_slice.prepare_custody_ledger_transaction(
                receipt_path=receipt_path,
                old_ledger=b"",
                new_ledger=new,
                operation_id="same-basename-cross-parent",
                subject=run_vertical_slice._custody_path_subject(root_b.resolve()),
            )
            before_ledger = ledger.read_bytes()
            before_receipt = receipt_path.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "subject"):
                run_vertical_slice.recover_torn_custody_ledger_tail(root_a, transaction_receipt_path=receipt_path)
            self.assertEqual(ledger.read_bytes(), before_ledger)
            self.assertEqual(receipt_path.read_bytes(), before_receipt)
    def test_transaction_recovery_commits_only_exact_prebound_new_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as receipt_directory:
            parent = Path(directory)
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            old = b""
            prepared = run_vertical_slice._next_custody_ledger_frame({"event": "PREPARED", "pointer": ".checkpoint-quarantine/evidence-" + "b" * 64 + ".json", "bytes": 17, "sha256": "b" * 64, "reason": "exact replay"}, [])
            new = (json.dumps(prepared, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            ledger.write_bytes(new)
            transaction_path = Path(receipt_directory) / "ledger-transaction.json"
            run_vertical_slice.prepare_custody_ledger_transaction(receipt_path=transaction_path, old_ledger=old, new_ledger=new, operation_id="new-ledger-commit", subject=run_vertical_slice._custody_path_subject(parent.resolve()))
            receipt = run_vertical_slice.recover_torn_custody_ledger_tail(parent, transaction_receipt_path=transaction_path)
            self.assertEqual(receipt["result"], "COMMITTED")
            self.assertEqual(ledger.read_bytes(), new)

    def test_concurrent_same_operation_receipt_has_one_authoritative_byteset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            receipt_path = Path(directory) / "operation.json"
            barrier = threading.Barrier(2)
            outcomes: list[object] = []
            def writer() -> None:
                barrier.wait()
                try:
                    outcomes.append(run_vertical_slice.prepare_custody_ledger_transaction(receipt_path=receipt_path, old_ledger=b"", new_ledger=b"", operation_id="concurrent-operation", subject="checkpoint"))
                except BaseException as error:
                    outcomes.append(error)
            first = threading.Thread(target=writer)
            second = threading.Thread(target=writer)
            first.start(); second.start(); first.join(timeout=5); second.join(timeout=5)
            self.assertFalse(first.is_alive() or second.is_alive())
            successes = [outcome for outcome in outcomes if isinstance(outcome, dict)]
            self.assertGreaterEqual(len(successes), 1)
            persisted = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted["operation_id"], "concurrent-operation")
            self.assertEqual(persisted["subject"], "checkpoint")
            self.assertTrue(all(outcome == successes[0] or isinstance(outcome, BaseException) for outcome in outcomes))
    def test_atomic_create_durable_has_one_cross_process_winner_and_no_temp(self) -> None:
        """The kernel no-replace create leaves one receipt payload under two processes."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "operation.json"
            start = root / "start"
            worker = (
                "import pathlib, sys, time\n"
                "sys.path.insert(0, sys.argv[1])\n"
                "from durable_io import atomic_create_durable\n"
                "target = pathlib.Path(sys.argv[2]); start = pathlib.Path(sys.argv[3])\n"
                "while not start.exists(): time.sleep(0.01)\n"
                "try:\n"
                "    atomic_create_durable(target, b'{\\\"winner\\\":true}\\n')\n"
                "except FileExistsError:\n"
                "    print('exists')\n"
                "else:\n"
                "    print('created')\n"
            )
            environment = os.environ.copy()
            processes = [
                subprocess.Popen([sys.executable, "-c", worker, str(ROOT / "tools" / "ember-restart-3b"), str(target), str(start)], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment)
                for _ in range(2)
            ]
            try:
                start.write_text("go", encoding="utf-8")
                results = [process.communicate(timeout=10) for process in processes]
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)
            self.assertEqual(sorted(stdout.strip() for stdout, _ in results), ["created", "exists"])
            self.assertTrue(all(stderr == "" for _, stderr in results))
            self.assertEqual(target.read_bytes(), b'{"winner":true}\n')
            self.assertEqual(list(root.glob(".*.tmp")), [])
    def test_same_operation_receipt_identity_cannot_be_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            receipt_path = Path(directory) / "operation.json"
            first = run_vertical_slice.prepare_custody_ledger_transaction(receipt_path=receipt_path, old_ledger=b"", new_ledger=b"", operation_id="same-operation", subject="checkpoint")
            resumed = run_vertical_slice.prepare_custody_ledger_transaction(receipt_path=receipt_path, old_ledger=b"", new_ledger=b"", operation_id="same-operation", subject="checkpoint")
            self.assertEqual(resumed, first)
            with self.assertRaisesRegex(RuntimeError, "collision"):
                run_vertical_slice.prepare_custody_ledger_transaction(receipt_path=receipt_path, old_ledger=b"", new_ledger=b"", operation_id="same-operation", subject="different-checkpoint")
            self.assertEqual(json.loads(receipt_path.read_text(encoding="utf-8"))["subject"], "checkpoint")
    def test_aborted_receipt_cannot_be_reused_for_append(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as receipts:
            parent = Path(directory)
            receipt_path = Path(receipts) / "aborted.json"
            run_vertical_slice.prepare_custody_ledger_transaction(receipt_path=receipt_path, old_ledger=b"", new_ledger=b"", operation_id="aborted-op", subject=run_vertical_slice._custody_path_subject(parent.resolve()))
            self.assertEqual(run_vertical_slice.finalize_custody_ledger_transaction(parent, receipt_path=receipt_path)["result"], "ABORTED")
            event = {"event": "PREPARED", "pointer": ".checkpoint-quarantine/evidence-" + "b" * 64 + ".json", "bytes": 1, "sha256": "b" * 64, "reason": "retry"}
            with self.assertRaisesRegex(RuntimeError, "collision|fresh nonterminal"):
                run_vertical_slice._append_custody_ledger_transition(parent, event, transaction_receipt_path=receipt_path, operation_id="aborted-op", subject=run_vertical_slice._custody_path_subject(parent.resolve()))
            self.assertEqual(json.loads(receipt_path.read_text(encoding="utf-8"))["result"], "ABORTED")
    def test_parent_scoped_recovery_rejects_foreign_subject_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            receipt_path = parent.parent / f"custody-append-{run_vertical_slice._custody_subject_token(parent.resolve())}-foreign.json"
            run_vertical_slice.prepare_custody_ledger_transaction(receipt_path=receipt_path, old_ledger=b"", new_ledger=b"", operation_id="foreign", subject="custody:another-root")
            with self.assertRaisesRegex(RuntimeError, "foreign subject"):
                run_vertical_slice._append_custody_ledger_transition(parent, {"event": "PREPARED", "pointer": ".checkpoint-quarantine/evidence-" + "a" * 64 + ".json", "bytes": 1, "sha256": "a" * 64, "reason": "foreign"})
    def test_next_append_commits_stranded_parent_scoped_prepared_transaction_first(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            first = run_vertical_slice._next_custody_ledger_frame({"event": "PREPARED", "pointer": ".checkpoint-quarantine/evidence-" + "c" * 64 + ".json", "bytes": 17, "sha256": "c" * 64, "reason": "stranded"}, [])
            old = b""
            new = (json.dumps(first, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            receipt_path = parent.parent / f"custody-append-{run_vertical_slice._custody_subject_token(parent.resolve())}-stranded.json"
            run_vertical_slice.prepare_custody_ledger_transaction(receipt_path=receipt_path, old_ledger=old, new_ledger=new, operation_id="stranded", subject=run_vertical_slice._custody_path_subject(parent.resolve()))
            ledger.write_bytes(new)
            run_vertical_slice._append_custody_ledger_transition(parent, {"event": "COMMITTED", "pointer": first["pointer"], "bytes": 17, "sha256": "c" * 64, "reason": "stranded"})
            self.assertEqual(json.loads(receipt_path.read_text(encoding="utf-8"))["result"], "COMMITTED")
            _, events = run_vertical_slice._custody_ledger_snapshot(parent)
            self.assertEqual([event["event"] for event in events], ["PREPARED", "COMMITTED"])
    def test_transaction_recovery_refuses_syntactically_valid_unterminated_tail_without_exact_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as receipt_directory:
            parent = Path(directory)
            (parent / ".checkpoint-custody-deletion-ledger.jsonl").write_bytes(b'{"schema_version":"valid-json-but-no-newline"}')
            with self.assertRaisesRegex((RuntimeError, ValueError), "transaction|ledger|newline|JSON"):
                run_vertical_slice.recover_torn_custody_ledger_tail(parent, transaction_receipt_path=Path(receipt_directory) / "missing.json")
    def test_offline_torn_tail_recovery_archives_binds_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as receipt_directory:
            parent = Path(directory)
            pointer = ".checkpoint-quarantine/evidence-" + "d" * 64 + ".json"
            prepared = run_vertical_slice._next_custody_ledger_frame(
                {"event": "PREPARED", "pointer": pointer, "bytes": 17, "sha256": "d" * 64, "reason": "offline recovery"},
                [],
            )
            committed = run_vertical_slice._next_custody_ledger_frame(
                {"event": "COMMITTED", "pointer": pointer, "bytes": 17, "sha256": "d" * 64, "reason": "offline recovery"},
                [prepared],
            )
            third = run_vertical_slice._next_custody_ledger_frame(
                {"event": "PREPARED", "pointer": ".checkpoint-quarantine/evidence-" + "e" * 64 + ".json", "bytes": 5, "sha256": "e" * 64, "reason": "torn frame"},
                [prepared, committed],
            )
            prefix = b"".join((json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8") for row in (prepared, committed))
            torn_line = json.dumps(third, sort_keys=True, separators=(",", ":")).encode("utf-8")
            tail = torn_line[: len(torn_line) // 2]
            original = prefix + tail
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            ledger.write_bytes(original)
            receipt_path = Path(receipt_directory) / "tail-recovery.json"

            receipt = run_vertical_slice.recover_torn_custody_ledger_tail(parent, transaction_receipt_path=receipt_path)

            self.assertEqual(receipt["schema_version"], "ember-custody-ledger-tail-recovery-v1")
            self.assertEqual(receipt["result"], "COMMITTED")
            self.assertEqual(receipt["original"], {"sha256": hashlib.sha256(original).hexdigest(), "bytes": len(original)})
            self.assertEqual(receipt["prefix"]["ledger_sha256"], hashlib.sha256(prefix).hexdigest())
            self.assertEqual(receipt["prefix"]["ledger_bytes"], len(prefix))
            self.assertEqual(receipt["prefix"]["frame_count"], 2)
            self.assertEqual(receipt["tail"], {"sha256": hashlib.sha256(tail).hexdigest(), "bytes": len(tail)})
            self.assertEqual(receipt["verification"]["before_publication"], receipt["prefix"])
            self.assertEqual(receipt["verification"]["after_publication"], receipt["prefix"])
            self.assertEqual(ledger.read_bytes(), prefix)
            archive = parent / receipt["archive"]
            self.assertEqual(archive.read_bytes(), original)
            self.assertEqual(run_vertical_slice._ledger_binding(ledger.read_bytes()), receipt["prefix"])
            self.assertEqual(
                run_vertical_slice.recover_torn_custody_ledger_tail(parent, transaction_receipt_path=receipt_path),
                receipt,
            )
            self.assertEqual(ledger.read_bytes(), prefix)
            self.assertEqual(archive.read_bytes(), original)

    def test_offline_torn_tail_recovery_resumes_after_commit_receipt_write_crash(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as receipt_directory:
            parent = Path(directory)
            frame = run_vertical_slice._next_custody_ledger_frame(
                {"event": "PREPARED", "pointer": ".checkpoint-quarantine/evidence-" + "a" * 64 + ".json", "bytes": 3, "sha256": "a" * 64, "reason": "crash recovery"},
                [],
            )
            prefix = (json.dumps(frame, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            original = prefix + b'{"torn"'
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            ledger.write_bytes(original)
            receipt_path = Path(receipt_directory) / "tail-recovery.json"

            with unittest.mock.patch.object(run_vertical_slice, "_atomic_json", side_effect=OSError("receipt commit crash")):
                with self.assertRaisesRegex(OSError, "receipt commit crash"):
                    run_vertical_slice.recover_torn_custody_ledger_tail(parent, transaction_receipt_path=receipt_path)

            self.assertEqual(ledger.read_bytes(), prefix)
            self.assertEqual(json.loads(receipt_path.read_text(encoding="utf-8"))["result"], "PREPARED")
            resumed = run_vertical_slice.recover_torn_custody_ledger_tail(parent, transaction_receipt_path=receipt_path)
            self.assertEqual(resumed["result"], "COMMITTED")
            self.assertEqual(ledger.read_bytes(), prefix)

    def test_offline_torn_tail_recovery_rejects_receipt_and_archive_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as receipt_directory:
            parent = Path(directory)
            frame = run_vertical_slice._next_custody_ledger_frame(
                {"event": "PREPARED", "pointer": ".checkpoint-quarantine/evidence-" + "b" * 64 + ".json", "bytes": 4, "sha256": "b" * 64, "reason": "tamper evidence"},
                [],
            )
            prefix = (json.dumps(frame, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            ledger.write_bytes(prefix + b'{"torn"')
            receipt_path = Path(receipt_directory) / "tail-recovery.json"
            receipt = run_vertical_slice.recover_torn_custody_ledger_tail(parent, transaction_receipt_path=receipt_path)
            stable_ledger = ledger.read_bytes()

            tampered_receipt = dict(receipt)
            tampered_receipt["tail"] = {"sha256": "0" * 64, "bytes": receipt["tail"]["bytes"]}
            receipt_path.write_text(json.dumps(tampered_receipt, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "archive|prefix|tail|binding"):
                run_vertical_slice.recover_torn_custody_ledger_tail(parent, transaction_receipt_path=receipt_path)
            self.assertEqual(ledger.read_bytes(), stable_ledger)

            receipt_path.write_text(json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            archive = parent / receipt["archive"]
            archive.write_bytes(archive.read_bytes() + b"tamper")
            with self.assertRaisesRegex(RuntimeError, "archive"):
                run_vertical_slice.recover_torn_custody_ledger_tail(parent, transaction_receipt_path=receipt_path)
            self.assertEqual(ledger.read_bytes(), stable_ledger)

    def test_offline_torn_tail_recovery_handles_multiple_mid_frame_cuts(self) -> None:
        for cut_fraction in (1, 2, 3):
            with self.subTest(cut_fraction=cut_fraction), tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as receipt_directory:
                parent = Path(directory)
                first = run_vertical_slice._next_custody_ledger_frame(
                    {"event": "PREPARED", "pointer": ".checkpoint-quarantine/evidence-" + "c" * 64 + ".json", "bytes": 5, "sha256": "c" * 64, "reason": "frame cut"},
                    [],
                )
                second = run_vertical_slice._next_custody_ledger_frame(
                    {"event": "COMMITTED", "pointer": first["pointer"], "bytes": 5, "sha256": "c" * 64, "reason": "frame cut"},
                    [first],
                )
                prefix = (json.dumps(first, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
                next_line = json.dumps(second, sort_keys=True, separators=(",", ":")).encode("utf-8")
                cut = max(1, min(len(next_line) - 1, len(next_line) * cut_fraction // 4))
                ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
                ledger.write_bytes(prefix + next_line[:cut])
                receipt = run_vertical_slice.recover_torn_custody_ledger_tail(
                    parent,
                    transaction_receipt_path=Path(receipt_directory) / "tail-recovery.json",
                )
                self.assertEqual(receipt["prefix"]["frame_count"], 1)
                self.assertEqual(ledger.read_bytes(), prefix)

    def test_two_offline_torn_tail_recoverers_converge_on_one_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as receipt_directory:
            parent = Path(directory)
            frame = run_vertical_slice._next_custody_ledger_frame(
                {"event": "PREPARED", "pointer": ".checkpoint-quarantine/evidence-" + "d" * 64 + ".json", "bytes": 6, "sha256": "d" * 64, "reason": "concurrent recovery"},
                [],
            )
            prefix = (json.dumps(frame, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            ledger.write_bytes(prefix + b'{"torn"')
            receipt_path = Path(receipt_directory) / "tail-recovery.json"
            barrier = threading.Barrier(2)
            outcomes: list[object] = []

            def recover() -> None:
                barrier.wait()
                try:
                    outcomes.append(run_vertical_slice.recover_torn_custody_ledger_tail(parent, transaction_receipt_path=receipt_path))
                except BaseException as error:
                    outcomes.append(error)

            threads = [threading.Thread(target=recover) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertTrue(all(isinstance(outcome, dict) for outcome in outcomes), outcomes)
            self.assertEqual(outcomes[0], outcomes[1])
            self.assertEqual(outcomes[0]["result"], "COMMITTED")
            self.assertEqual(ledger.read_bytes(), prefix)
    def test_offline_torn_tail_recovery_refuses_hash_corruption_in_complete_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as receipt_directory:
            parent = Path(directory)
            frame = run_vertical_slice._next_custody_ledger_frame(
                {"event": "PREPARED", "pointer": ".checkpoint-quarantine/evidence-" + "f" * 64 + ".json", "bytes": 9, "sha256": "f" * 64, "reason": "unaltered"},
                [],
            )
            frame["reason"] = "valid-json bit flip"
            original = (json.dumps(frame, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8") + b'{"torn"'
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            ledger.write_bytes(original)
            receipt_path = Path(receipt_directory) / "tail-recovery.json"

            with self.assertRaisesRegex(RuntimeError, "frame|chain|hash"):
                run_vertical_slice.recover_torn_custody_ledger_tail(parent, transaction_receipt_path=receipt_path)

            self.assertEqual(ledger.read_bytes(), original)
            refusal = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(refusal["schema_version"], "ember-custody-ledger-tail-recovery-refusal-v1")
            self.assertEqual(refusal["result"], "REFUSED")
            self.assertEqual(refusal["reason"], "PREFIX_INVALID")
            self.assertEqual(refusal["original"], {"sha256": hashlib.sha256(original).hexdigest(), "bytes": len(original)})
            self.assertEqual((parent / refusal["archive"]).read_bytes(), original)
            refusal["candidate_prefix"]["sha256"] = "0" * 64
            receipt_path.write_text(json.dumps(refusal, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "candidate prefix|tail"):
                run_vertical_slice.recover_torn_custody_ledger_tail(parent, transaction_receipt_path=receipt_path)
            self.assertEqual(ledger.read_bytes(), original)

    def test_custody_ledger_uses_shared_durable_replace_and_removes_dead_stale_helper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.jsonl"
            with unittest.mock.patch.object(run_vertical_slice, "atomic_replace_durable") as shared:
                run_vertical_slice._atomic_bytes(target, b"bound\n")
            self.assertEqual(shared.call_count, 1)
            self.assertEqual(shared.call_args.args[1], target)
        self.assertFalse(hasattr(run_vertical_slice, "_atomic_replace_durable"))
        self.assertFalse(hasattr(run_vertical_slice, "_windows_atomic_replace"))
        self.assertFalse(hasattr(run_vertical_slice, "_custody_ledger_lock_is_stale"))
    def test_custody_reconciliation_rejects_valid_json_v3_frame_tamper(self) -> None:
        """Frame hashes must catch a valid-JSON reason mutation after durable write."""
        def frame(*, event: str, sequence: int, previous: str, reason: str) -> dict[str, object]:
            body = {
                "schema_version": "ember-checkpoint-custody-deletion-v3",
                "event": event,
                "pointer": ".checkpoint-quarantine/evidence-" + "a" * 64 + ".json",
                "bytes": 17,
                "sha256": "a" * 64,
                "reason": reason,
                "sequence": sequence,
                "previous_frame_sha256": previous,
            }
            encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
            return {**body, "frame_sha256": hashlib.sha256(encoded).hexdigest()}

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            prepared = frame(event="PREPARED", sequence=0, previous="0" * 64, reason="bounded evidence retention")
            committed = frame(event="COMMITTED", sequence=1, previous=prepared["frame_sha256"], reason="bounded evidence retention")
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            ledger.write_text("\n".join(json.dumps(event, sort_keys=True, separators=(",", ":")) for event in (prepared, committed)) + "\n", encoding="utf-8")
            self.assertEqual(run_vertical_slice._custody_reconciliation(parent)["deleted_bytes"], 17)
            committed["reason"] = "valid-json bit flip"
            ledger.write_text("\n".join(json.dumps(event, sort_keys=True, separators=(",", ":")) for event in (prepared, committed)) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "frame|chain|hash|prepared"):
                run_vertical_slice._custody_reconciliation(parent)
    def test_missing_prepared_recovery_reconciles_and_commits_under_one_writer_lock(self) -> None:
        """Offline recovery cannot inspect/archive/publish against a concurrent writer window."""
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            prepared = run_vertical_slice._next_custody_ledger_frame({
                "event": "PREPARED", "pointer": ".checkpoint-quarantine/evidence-" + "c" * 64 + ".json",
                "bytes": 17, "sha256": "c" * 64, "reason": "recovery lock regression",
            }, [])
            (parent / ".checkpoint-custody-deletion-ledger.jsonl").write_text(json.dumps(prepared, sort_keys=True) + "\n", encoding="utf-8")
            held = False

            @contextlib.contextmanager
            def lock(_parent: Path):
                nonlocal held
                self.assertFalse(held)
                held = True
                try:
                    yield parent
                finally:
                    held = False

            def reconcile(_parent: Path) -> dict[str, object]:
                return {"reconciled_bytes": 0}

            with unittest.mock.patch.object(run_vertical_slice, "_custody_ledger_write_lock", lock), unittest.mock.patch.object(run_vertical_slice, "_custody_reconciliation", side_effect=reconcile) as reconciled:
                run_vertical_slice._recover_missing_prepared_evidence(parent)
            self.assertEqual(reconciled.call_count, 3)
            self.assertFalse(held)
            _, events = run_vertical_slice._custody_ledger_snapshot(parent)
            self.assertEqual([event["event"] for event in events], ["PREPARED", "COMMITTED"])
    def test_two_recoverers_commit_one_missing_prepared_transition(self) -> None:
        """Concurrent recovery observes one durable semantic COMMITTED transition."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / "custody"
            parent.mkdir()
            prepared = run_vertical_slice._next_custody_ledger_frame({
                "event": "PREPARED", "pointer": ".checkpoint-quarantine/evidence-" + "f" * 64 + ".json",
                "bytes": 17, "sha256": "f" * 64, "reason": "two recoverers",
            }, [])
            (parent / ".checkpoint-custody-deletion-ledger.jsonl").write_text(
                json.dumps(prepared, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8"
            )
            barrier = threading.Barrier(2)
            errors: list[BaseException] = []
            real_append = run_vertical_slice._append_custody_ledger_transition

            def synchronized_append(*args: object, **kwargs: object) -> None:
                barrier.wait(timeout=5)
                real_append(*args, **kwargs)

            def recover() -> None:
                try:
                    run_vertical_slice._recover_missing_prepared_evidence(parent)
                except BaseException as error:
                    errors.append(error)

            with unittest.mock.patch.object(run_vertical_slice, "_append_custody_ledger_transition", synchronized_append):
                first = threading.Thread(target=recover)
                second = threading.Thread(target=recover)
                first.start(); second.start(); first.join(timeout=10); second.join(timeout=10)
            self.assertFalse(first.is_alive() or second.is_alive())
            self.assertEqual(errors, [])
            _, events = run_vertical_slice._custody_ledger_snapshot(parent)
            self.assertEqual([event["event"] for event in events], ["PREPARED", "COMMITTED"])
            self.assertEqual(run_vertical_slice._custody_reconciliation(parent)["deleted_bytes"], 17)
            receipts = list(root.glob(f"custody-append-{run_vertical_slice._custody_subject_token(parent.resolve())}-*.json"))
            self.assertEqual(len(receipts), 1)
            self.assertEqual(json.loads(receipts[0].read_text(encoding="utf-8"))["result"], "COMMITTED")
            self.assertEqual(list(root.glob(".*.tmp")), [])
    def test_custody_reconciliation_rejects_reordered_or_replayed_v3_frames(self) -> None:
        def frame(event: str, previous: str, sequence: int) -> dict[str, object]:
            body = {
                "schema_version": "ember-checkpoint-custody-deletion-v3", "event": event,
                "pointer": ".checkpoint-quarantine/evidence-" + "d" * 64 + ".json",
                "bytes": 17, "sha256": "d" * 64, "reason": "chain attack",
                "sequence": sequence, "previous_frame_sha256": previous,
            }
            return {**body, "frame_sha256": hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()}

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            prepared = frame("PREPARED", "0" * 64, 0)
            committed = frame("COMMITTED", prepared["frame_sha256"], 1)
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            for attack in ((committed, prepared), (prepared, committed, committed)):
                with self.subTest(attack=len(attack)):
                    ledger.write_text("\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in attack) + "\n", encoding="utf-8")
                    with self.assertRaisesRegex(RuntimeError, "frame|chain|transition|COMMITTED"):
                        run_vertical_slice._custody_reconciliation(parent)
    def test_v4_frame_tamper_rejects_distinct_content_and_full_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            prepared = run_vertical_slice._next_custody_ledger_frame({"event": "PREPARED", "pointer": ".checkpoint-quarantine/evidence-" + "a" * 64 + ".json", "bytes": 17, "sha256": "a" * 64, "reason": "v4"}, [])
            committed = run_vertical_slice._next_custody_ledger_frame({"event": "COMMITTED", "pointer": prepared["pointer"], "bytes": 17, "sha256": "a" * 64, "reason": "v4"}, [prepared])
            self.assertNotEqual(committed["frame_content_sha256"], committed["frame_sha256"])
            committed["reason"] = "tampered"
            (parent / ".checkpoint-custody-deletion-ledger.jsonl").write_text("\n".join(json.dumps(row, sort_keys=True) for row in (prepared, committed)) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "frame|hash|chain"):
                run_vertical_slice._custody_reconciliation(parent)
    def test_v3_append_refuses_every_unchained_legacy_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            pointer = ".checkpoint-quarantine/evidence-" + "e" * 64 + ".json"
            for schema, event_name in (("ember-checkpoint-custody-deletion-v1", "DELETED"), ("ember-checkpoint-custody-deletion-v2", "PREPARED")):
                with self.subTest(schema=schema):
                    ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
                    ledger.write_text(json.dumps({"schema_version": schema, "event": event_name, "pointer": pointer, "bytes": 17, "sha256": "e" * 64, "reason": "legacy"}) + "\n", encoding="utf-8")
                    with self.assertRaisesRegex(RuntimeError, "legacy|migration"):
                        run_vertical_slice._append_custody_ledger_transition(parent, {"event": "PREPARED", "pointer": pointer, "bytes": 17, "sha256": "e" * 64, "reason": "new"})
    def test_reconciliation_rejects_mixed_v1_and_v3_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            pointer = ".checkpoint-quarantine/evidence-" + "a" * 64 + ".json"
            legacy = {"schema_version": "ember-checkpoint-custody-deletion-v1", "event": "DELETED", "pointer": pointer, "bytes": 17, "sha256": "a" * 64, "reason": "legacy mix"}
            chained = run_vertical_slice._next_custody_ledger_frame({"event": "PREPARED", "pointer": pointer, "bytes": 17, "sha256": "a" * 64, "reason": "new mix"}, [])
            (parent / ".checkpoint-custody-deletion-ledger.jsonl").write_text("\n".join(json.dumps(row, sort_keys=True) for row in (legacy, chained)) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "mixes|legacy|chained"):
                run_vertical_slice._custody_reconciliation(parent)
    def test_legacy_ordered_ledger_migration_is_explicit_and_receipted(self) -> None:
        """An unchained v2 ledger cannot be silently appended; migration archives and replays it under v3."""
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            pointer = ".checkpoint-quarantine/evidence-" + "b" * 64 + ".json"
            base = {"schema_version": "ember-checkpoint-custody-deletion-v2", "pointer": pointer, "bytes": 17, "sha256": "b" * 64, "reason": "legacy migration"}
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            ledger.write_text("\n".join(json.dumps({**base, "event": event}, sort_keys=True, separators=(",", ":")) for event in ("PREPARED", "COMMITTED")) + "\n", encoding="utf-8")
            receipt = run_vertical_slice.migrate_legacy_custody_ledger(parent)
            self.assertEqual(receipt["schema_version"], "ember-custody-ledger-migration-v2")
            self.assertEqual(receipt["result"], "MIGRATED")
            self.assertTrue((parent / receipt["legacy_archive"]).is_file())
            self.assertTrue(run_vertical_slice._is_sha256(receipt["new_ledger_sha256"]))
            self.assertTrue(run_vertical_slice._is_sha256(receipt["chain_head_sha256"]))
            self.assertEqual(json.loads((parent / receipt["migration_receipt"]).read_text(encoding="utf-8"))["new_ledger_sha256"], receipt["new_ledger_sha256"])
            _, events = run_vertical_slice._custody_ledger_snapshot(parent)
            self.assertEqual([event["schema_version"] for event in events], [run_vertical_slice._CUSTODY_LEDGER_SCHEMA, run_vertical_slice._CUSTODY_LEDGER_SCHEMA])
            self.assertEqual([event["event"] for event in events], ["PREPARED", "COMMITTED"])
            self.assertEqual(run_vertical_slice._custody_reconciliation(parent)["deleted_bytes"], 17)
    def test_migration_replays_external_prepared_receipt_after_v4_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as receipts:
            parent = Path(directory)
            pointer = ".checkpoint-quarantine/evidence-" + "c" * 64 + ".json"
            legacy = {"schema_version": "ember-checkpoint-custody-deletion-v2", "event": "PREPARED", "pointer": pointer, "bytes": 17, "sha256": "c" * 64, "reason": "crash replay"}
            old = (json.dumps(legacy, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            replay = run_vertical_slice._next_custody_ledger_frame({"event": "PREPARED", "pointer": pointer, "bytes": 17, "sha256": "c" * 64, "reason": "crash replay"}, [])
            new = (json.dumps(replay, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            ledger.write_bytes(new)
            digest = hashlib.sha256(old).hexdigest()
            (parent / f".checkpoint-custody-ledger-legacy-{digest}.jsonl").write_bytes(old)
            transaction_path = Path(receipts) / "migration.json"
            run_vertical_slice.prepare_custody_ledger_transaction(receipt_path=transaction_path, old_ledger=old, new_ledger=new, operation_id="migration-crash", subject=run_vertical_slice._custody_path_subject(parent.resolve()))
            receipt = run_vertical_slice.migrate_legacy_custody_ledger(parent, transaction_receipt_path=transaction_path)
            self.assertEqual(receipt["result"], "MIGRATED")
            self.assertEqual(json.loads(transaction_path.read_text(encoding="utf-8"))["result"], "COMMITTED")
            completion = Path(receipt["migration_receipt"])
            self.assertTrue(completion.is_file())
            self.assertEqual(json.loads(completion.read_text(encoding="utf-8"))["new_ledger_sha256"], hashlib.sha256(new).hexdigest())
            self.assertEqual(ledger.read_bytes(), new)
            replayed = run_vertical_slice.migrate_legacy_custody_ledger(parent, transaction_receipt_path=transaction_path)
            self.assertEqual(replayed["migration_receipt"], receipt["migration_receipt"])
    def test_migration_replay_converges_after_completion_receipt_publish_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as receipts:
            parent = Path(directory)
            pointer = ".checkpoint-quarantine/evidence-" + "f" * 64 + ".json"
            legacy = {"schema_version": "ember-checkpoint-custody-deletion-v2", "event": "PREPARED", "pointer": pointer, "bytes": 17, "sha256": "f" * 64, "reason": "completion crash"}
            old = (json.dumps(legacy, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            replay = run_vertical_slice._next_custody_ledger_frame({"event": "PREPARED", "pointer": pointer, "bytes": 17, "sha256": "f" * 64, "reason": "completion crash"}, [])
            new = (json.dumps(replay, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            ledger.write_bytes(new)
            digest = hashlib.sha256(old).hexdigest()
            (parent / f".checkpoint-custody-ledger-legacy-{digest}.jsonl").write_bytes(old)
            transaction_path = Path(receipts) / "completion.json"
            run_vertical_slice.prepare_custody_ledger_transaction(receipt_path=transaction_path, old_ledger=old, new_ledger=new, operation_id="completion-crash", subject=run_vertical_slice._custody_path_subject(parent.resolve()))
            real_atomic_json = run_vertical_slice._atomic_json
            def fail_completion(path: Path, payload: dict[str, object]) -> None:
                if path.name.endswith(f"-migration-{digest}.json"):
                    raise OSError("completion receipt fault")
                real_atomic_json(path, payload)
            with unittest.mock.patch.object(run_vertical_slice, "_atomic_json", side_effect=fail_completion):
                with self.assertRaisesRegex(OSError, "completion receipt fault"):
                    run_vertical_slice.migrate_legacy_custody_ledger(parent, transaction_receipt_path=transaction_path)
            self.assertEqual(json.loads(transaction_path.read_text(encoding="utf-8"))["result"], "COMMITTED")
            self.assertEqual(ledger.read_bytes(), new)
            recovered = run_vertical_slice.migrate_legacy_custody_ledger(parent, transaction_receipt_path=transaction_path)
            self.assertTrue(Path(recovered["migration_receipt"]).is_file())
            self.assertEqual(ledger.read_bytes(), new)
    def test_legacy_migration_publishes_archive_through_shared_durable_replace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            pointer = ".checkpoint-quarantine/evidence-" + "e" * 64 + ".json"
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            ledger.write_text(json.dumps({"schema_version": "ember-checkpoint-custody-deletion-v2", "event": "PREPARED", "pointer": pointer, "bytes": 17, "sha256": "e" * 64, "reason": "archive durability"}) + "\n", encoding="utf-8")
            real_atomic = run_vertical_slice._atomic_bytes
            published: list[Path] = []
            def record_atomic(path: Path, payload: bytes) -> None:
                published.append(path)
                real_atomic(path, payload)
            with unittest.mock.patch.object(run_vertical_slice, "_atomic_bytes", side_effect=record_atomic):
                run_vertical_slice.migrate_legacy_custody_ledger(parent)
            self.assertTrue(any(path.name.startswith(".checkpoint-custody-ledger-legacy-") for path in published))
    def test_legacy_v1_deleted_migration_is_explicit_and_receipted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            pointer = ".checkpoint-quarantine/evidence-" + "f" * 64 + ".json"
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            ledger.write_text(json.dumps({"schema_version": "ember-checkpoint-custody-deletion-v1", "event": "DELETED", "pointer": pointer, "bytes": 17, "sha256": "f" * 64, "reason": "legacy v1 migration"}) + "\n", encoding="utf-8")
            receipt = run_vertical_slice.migrate_legacy_custody_ledger(parent)
            self.assertEqual(receipt["result"], "MIGRATED")
            _, events = run_vertical_slice._custody_ledger_snapshot(parent)
            self.assertEqual([event["event"] for event in events], ["PREPARED", "COMMITTED"])
            self.assertEqual(run_vertical_slice._custody_reconciliation(parent)["deleted_bytes"], 17)
    def test_custody_reconciliation_rejects_lone_committed_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            ledger.write_text(json.dumps({"schema_version": "ember-checkpoint-custody-deletion-v1", "event": "COMMITTED", "pointer": ".checkpoint-quarantine/evidence-" + "a" * 64 + ".json", "bytes": 17, "sha256": "a" * 64, "reason": "test"}, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "COMMITTED|transition|legacy"):
                run_vertical_slice._custody_reconciliation(parent)

    def test_custody_reconciliation_rejects_duplicate_or_reversed_transitions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            base = {"schema_version": "ember-checkpoint-custody-deletion-v2", "pointer": ".checkpoint-quarantine/evidence-" + "a" * 64 + ".json", "bytes": 17, "sha256": "a" * 64, "reason": "test"}
            events = [{**base, "event": "PREPARED"}, {**base, "event": "COMMITTED"}, {**base, "event": "COMMITTED"}]
            ledger.write_text("\n".join(json.dumps(event, sort_keys=True, separators=(",", ":")) for event in events) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "duplicate|transition"):
                run_vertical_slice._custody_reconciliation(parent)

    def test_custody_reconciliation_rejects_cross_schema_transition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            pointer = ".checkpoint-quarantine/evidence-" + "a" * 64 + ".json"
            identity = {"pointer": pointer, "bytes": 17, "sha256": "a" * 64, "reason": "test"}
            cases = (
                (
                    {**identity, "schema_version": "ember-checkpoint-custody-deletion-v1", "event": "PREPARED"},
                    {**identity, "schema_version": "ember-checkpoint-custody-deletion-v2", "event": "COMMITTED"},
                ),
                (
                    {**identity, "schema_version": "ember-checkpoint-custody-deletion-v2", "event": "PREPARED"},
                    {**identity, "schema_version": "ember-checkpoint-custody-deletion-v1", "event": "COMMITTED"},
                ),
            )
            for prepared, committed in cases:
                with self.subTest(prepared=prepared["schema_version"], committed=committed["schema_version"]):
                    ledger.write_text(
                        "\n".join(json.dumps(event, sort_keys=True, separators=(",", ":")) for event in (prepared, committed)) + "\n",
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(RuntimeError, "schema|legacy|transition"):
                        run_vertical_slice._custody_reconciliation(parent)

    def test_custody_reconciliation_rejects_reason_mutation_within_v2_transition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            base = {
                "schema_version": "ember-checkpoint-custody-deletion-v2",
                "pointer": ".checkpoint-quarantine/evidence-" + "a" * 64 + ".json",
                "bytes": 17,
                "sha256": "a" * 64,
            }
            events = [{**base, "event": "PREPARED", "reason": "first"}, {**base, "event": "COMMITTED", "reason": "changed"}]
            ledger.write_text("\n".join(json.dumps(event, sort_keys=True, separators=(",", ":")) for event in events) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "identity|reason"):
                run_vertical_slice._custody_reconciliation(parent)

    def test_custody_reconciliation_rejects_windows_pointer_alias_pair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            base = {
                "schema_version": "ember-checkpoint-custody-deletion-v2",
                "bytes": 17,
                "sha256": "a" * 64,
                "reason": "test",
            }
            pairs = []
            for pointer in (".checkpoint-quarantine/evidence-" + "a" * 64 + ".json", ".checkpoint-quarantine\\evidence-" + "a" * 64 + ".json"):
                pairs.extend(({**base, "event": "PREPARED", "pointer": pointer}, {**base, "event": "COMMITTED", "pointer": pointer}))
            ledger.write_text("\n".join(json.dumps(event, sort_keys=True, separators=(",", ":")) for event in pairs) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "pointer|duplicate|canonical"):
                run_vertical_slice._custody_reconciliation(parent)

    def test_custody_reconciliation_rejects_noncanonical_or_case_alias_pointers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            base = {
                "schema_version": "ember-checkpoint-custody-deletion-v2",
                "event": "PREPARED",
                "bytes": 17,
                "sha256": "a" * 64,
                "reason": "test",
            }
            for pointer in (
                ".checkpoint-quarantine\\evidence-" + "a" * 64 + ".json",
                ".checkpoint-quarantine/./missing.json",
                "./.checkpoint-quarantine/missing.json",
                ".checkpoint-quarantine/../missing.json",
                "C:/checkpoint-quarantine/missing.json",
                ".checkpoint-QUARANTINE/missing.json",
                ".checkpoint-quarantine/MISSING.json",
                ".checkpoint-quarantine/c:foo",
                ".checkpoint-quarantine/evidence-" + "a" * 64 + ".json.",
                ".checkpoint-quarantine/con-" + "a" * 64 + ".json",
                ".checkpoint-quarantine/unicode-é-" + "a" * 64 + ".json",
                ".checkpoint-quarantine/nested/evidence-" + "a" * 64 + ".json",
            ):
                with self.subTest(pointer=pointer):
                    ledger.write_text(json.dumps({**base, "pointer": pointer}, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
                    with self.assertRaisesRegex(RuntimeError, "pointer|canonical|safe"):
                        run_vertical_slice._custody_reconciliation(parent)

    def test_generated_evidence_pointers_use_closed_portable_grammar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            for name in ("same-name", "Con", "unsafe name/with:punctuation"):
                evidence = run_vertical_slice._write_bounded_quarantine_evidence(parent, name, {"result": name})
                pointer = evidence.relative_to(parent).as_posix()
                self.assertEqual(run_vertical_slice._canonical_custody_deletion_pointer(pointer), pointer)

    def test_missing_prepared_evidence_pointer_is_never_recreated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            evidence_a = run_vertical_slice._write_bounded_quarantine_evidence(parent, "same-name", {"result": "A"})
            payload = evidence_a.read_bytes()
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            prepared = {
                "schema_version": "ember-checkpoint-custody-deletion-v2",
                "event": "PREPARED",
                "pointer": evidence_a.relative_to(parent).as_posix(),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "reason": "injected crash after unlink",
            }
            ledger.write_text(json.dumps(prepared, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            evidence_a.unlink()
            first = run_vertical_slice._custody_reconciliation(parent)
            self.assertEqual(first["deleted_bytes"], len(payload))
            recreated = run_vertical_slice._write_bounded_quarantine_evidence(parent, "same-name", {"result": "A"})
            self.assertNotEqual(recreated, evidence_a)
            self.assertTrue(recreated.name.endswith("-g1.json"))
            second = run_vertical_slice._custody_reconciliation(parent)
            self.assertEqual(second["deleted_bytes"], len(payload))

    def test_retention_byte_cap_excludes_quarantined_bundle_after_move(self) -> None:
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
            report = run_vertical_slice._enforce_retention(parent, max_serialized_bytes=8)
            self.assertFalse(old.exists())
            self.assertTrue(newest.exists())
            retained = [path for path in (parent / ".checkpoint-quarantine").iterdir() if path.is_dir() and path.name.startswith("candidate-")]
            self.assertEqual(len(retained), 1)
            self.assertEqual((retained[0] / "state.bin").read_bytes(), b"old!!")
            self.assertGreaterEqual(run_vertical_slice._custody_serialized_bytes(parent), 12)
            self.assertEqual(report["live_charged_bytes"], 7)
            self.assertEqual(report["quarantine_charged_bytes"], 5)

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
            report = run_vertical_slice._enforce_retention(parent, max_serialized_bytes=8)
            self.assertFalse(old.exists())
            self.assertTrue(newest.exists())
            self.assertEqual(run_vertical_slice._bundle_serialized_bytes(newest), 7)
            self.assertEqual(report["live_charged_bytes"], 7)
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

    def test_live_retention_excludes_preserved_quarantine_and_reports_separate_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            live = parent / "checkpoint-live"
            live.mkdir()
            (live / "state.bin").write_bytes(b"live")
            candidate = parent / ".checkpoint-quarantine" / "candidate-checkpoint-old-0123456789abcdef"
            candidate.mkdir(parents=True)
            (candidate / "state.bin").write_bytes(b"old-quarantine")

            report = run_vertical_slice._enforce_retention(
                parent, max_serialized_bytes=4, max_quarantine_serialized_bytes=14,
            )

            self.assertTrue(candidate.exists())
            self.assertEqual(report, {
                "schema_version": "ember-checkpoint-retention-accounting-v1",
                "live_budget_bytes": 4,
                "live_charged_bytes": 4,
                "quarantine_budget_bytes": 14,
                "quarantine_charged_bytes": 14,
            })

    def test_separate_quarantine_budget_fails_closed_without_deleting_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            live = parent / "checkpoint-live"
            live.mkdir()
            (live / "state.bin").write_bytes(b"live")
            candidate = parent / ".checkpoint-quarantine" / "candidate-checkpoint-old-0123456789abcdef"
            candidate.mkdir(parents=True)
            evidence = candidate / "refusal.json"
            evidence.write_bytes(b"preserve-evidence")

            with self.assertRaisesRegex(RuntimeError, "separate quarantine.*17.*15"):
                run_vertical_slice._enforce_retention(
                    parent, max_serialized_bytes=4, max_quarantine_serialized_bytes=15,
                )

            self.assertTrue(candidate.exists())
            self.assertEqual(evidence.read_bytes(), b"preserve-evidence")
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

    def test_dead_pid_is_not_kept_live_by_a_surviving_popen_handle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / ".checkpoint-dead.1.staging"
            root.mkdir()
            process = subprocess.Popen([sys.executable, "-c", "pass"])
            process.wait(timeout=10)
            self.assertIsNotNone(process.returncode)
            self.assertFalse(run_vertical_slice._writer_is_active(root))
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
    def test_bounded_evidence_retention_preserves_noncanonical_preexisting_leaf(self) -> None:
        """Only generator-valid evidence may enter the deletion ledger or retention set."""
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            with unittest.mock.patch.object(run_vertical_slice, "_MAX_QUARANTINE_FILES", 1):
                original = run_vertical_slice._write_bounded_quarantine_evidence(parent, "valid", {"result": "OLD"})
                invalid = parent / ".checkpoint-quarantine" / "UPPER.json"
                invalid.write_bytes(b"preserve-me")
                replacement = run_vertical_slice._write_bounded_quarantine_evidence(parent, "replacement", {"result": "NEW"})
            self.assertFalse(original.exists())
            self.assertTrue(replacement.exists())
            self.assertEqual(invalid.read_bytes(), b"preserve-me")
            events = [json.loads(line) for line in (parent / ".checkpoint-custody-deletion-ledger.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertTrue(all(event["pointer"] != ".checkpoint-quarantine/UPPER.json" for event in events))
            run_vertical_slice._custody_reconciliation(parent)

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

    def test_bounded_evidence_retention_revalidates_victim_before_unlink(self) -> None:
        """A post-PREPARED mutation must preserve the victim and never commit deletion."""
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            with unittest.mock.patch.object(run_vertical_slice, "_MAX_QUARANTINE_FILES", 1):
                victim = run_vertical_slice._write_bounded_quarantine_evidence(parent, "victim", {"result": "OLD"})
                real_identity = run_vertical_slice._quarantine_evidence_identity
                calls = 0

                def mutate_at_unlink_boundary(root: Path, path: Path):
                    nonlocal calls
                    if path == victim:
                        calls += 1
                        if calls == 3:
                            path.write_bytes(b"swapped-after-prepared")
                    return real_identity(root, path)

                with unittest.mock.patch.object(run_vertical_slice, "_quarantine_evidence_identity", side_effect=mutate_at_unlink_boundary):
                    with self.assertRaisesRegex(RuntimeError, "changed before unlink"):
                        run_vertical_slice._write_bounded_quarantine_evidence(parent, "replacement", {"result": "NEW"})
            self.assertEqual(victim.read_bytes(), b"swapped-after-prepared")
            events = [json.loads(line) for line in (parent / ".checkpoint-custody-deletion-ledger.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([event["event"] for event in events], ["PREPARED"])

    def test_retention_recovers_matching_prepared_evidence_without_duplicate_transition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            with unittest.mock.patch.object(run_vertical_slice, "_MAX_QUARANTINE_FILES", 1):
                victim = run_vertical_slice._write_bounded_quarantine_evidence(parent, "victim", {"result": "OLD"})
                pointer, size, digest, _ = run_vertical_slice._quarantine_evidence_identity(parent, victim)
                ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
                prepared = run_vertical_slice._next_custody_ledger_frame({"event": "PREPARED", "pointer": pointer, "bytes": size, "sha256": digest, "reason": "bounded evidence retention"}, [])
                ledger.write_text(json.dumps(prepared, sort_keys=True) + "\n", encoding="utf-8")
                run_vertical_slice._write_bounded_quarantine_evidence(parent, "replacement", {"result": "NEW"})
            events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([event["event"] for event in events], ["PREPARED", "COMMITTED"])
            self.assertFalse(victim.exists())
            self.assertEqual(run_vertical_slice._custody_reconciliation(parent)["deleted_bytes"], size)

    def test_retention_refuses_mutated_prepared_evidence_without_new_transition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            with unittest.mock.patch.object(run_vertical_slice, "_MAX_QUARANTINE_FILES", 1):
                victim = run_vertical_slice._write_bounded_quarantine_evidence(parent, "victim", {"result": "OLD"})
                pointer, size, digest, _ = run_vertical_slice._quarantine_evidence_identity(parent, victim)
                ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
                prepared = run_vertical_slice._next_custody_ledger_frame({"event": "PREPARED", "pointer": pointer, "bytes": size, "sha256": digest, "reason": "bounded evidence retention"}, [])
                ledger.write_text(json.dumps(prepared, sort_keys=True) + "\n", encoding="utf-8")
                victim.write_bytes(b"mutated")
                with self.assertRaisesRegex(RuntimeError, "prepared evidence identity"):
                    run_vertical_slice._write_bounded_quarantine_evidence(parent, "replacement", {"result": "NEW"})
            self.assertTrue(victim.exists())
            self.assertEqual([json.loads(line)["event"] for line in ledger.read_text(encoding="utf-8").splitlines()], ["PREPARED"])

    def test_evidence_deletion_prepared_failure_preserves_and_reconciles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            quarantine = parent / ".checkpoint-quarantine"
            quarantine.mkdir()
            for index in range(33):
                (quarantine / f"old-{index:02d}-{'a' * 64}.json").write_bytes(f"old-{index}".encode("ascii"))
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
            pointer = ".checkpoint-quarantine/evidence-" + "b" * 64 + ".json"
            payload = b"crashed-evidence"
            digest = __import__("hashlib").sha256(payload).hexdigest()
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            ledger.write_text(json.dumps({"schema_version": "ember-checkpoint-custody-deletion-v2", "event": "PREPARED", "pointer": pointer, "bytes": len(payload), "sha256": digest, "reason": "crash replay"}) + "\n", encoding="utf-8")
            (quarantine / ("evidence-" + "b" * 64 + ".json")).write_bytes(payload)
            self.assertEqual(run_vertical_slice._custody_reconciliation(parent)["deleted_bytes"], 0)
            (quarantine / ("evidence-" + "b" * 64 + ".json")).unlink()
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


    def test_evidence_retention_crash_matrix_reconciles_once_without_duplicate_prepare(self) -> None:
        """Every durable boundary is recoverable and never repeats a pointer PREPARED row."""

        def ledger_events(parent: Path) -> list[dict[str, object]]:
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            if not ledger.exists():
                return []
            return [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]

        for boundary in ("prepare", "unlink", "commit", "return"):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory() as directory:
                parent = Path(directory)
                with unittest.mock.patch.object(run_vertical_slice, "_MAX_QUARANTINE_FILES", 1):
                    victim = run_vertical_slice._write_bounded_quarantine_evidence(parent, "victim", {"result": "OLD"})
                    if boundary == "prepare":
                        real_unlink = Path.unlink

                        def crash_before_unlink(path: Path, *args: object, **kwargs: object) -> None:
                            if path == victim:
                                raise OSError("injected crash after PREPARED")
                            real_unlink(path, *args, **kwargs)

                        with unittest.mock.patch.object(Path, "unlink", crash_before_unlink):
                            with self.assertRaisesRegex(RuntimeError, "did not commit"):
                                run_vertical_slice._write_bounded_quarantine_evidence(parent, "replacement", {"result": "NEW"})
                    elif boundary == "unlink":
                        real_unlink = Path.unlink

                        def crash_after_unlink(path: Path, *args: object, **kwargs: object) -> None:
                            if path == victim:
                                real_unlink(path, *args, **kwargs)
                                raise OSError("injected crash after unlink")
                            real_unlink(path, *args, **kwargs)

                        with unittest.mock.patch.object(Path, "unlink", crash_after_unlink):
                            with self.assertRaisesRegex(RuntimeError, "did not commit"):
                                run_vertical_slice._write_bounded_quarantine_evidence(parent, "replacement", {"result": "NEW"})
                    elif boundary == "commit":
                        real_fsync = run_vertical_slice.os.fsync
                        calls = 0

                        def crash_after_commit_append(descriptor: int) -> None:
                            nonlocal calls
                            calls += 1
                            if calls == 3:
                                raise OSError("injected crash after COMMITTED append")
                            real_fsync(descriptor)

                        with unittest.mock.patch.object(run_vertical_slice.os, "fsync", crash_after_commit_append):
                            with self.assertRaises(OSError):
                                run_vertical_slice._write_bounded_quarantine_evidence(parent, "replacement", {"result": "NEW"})
                    else:
                        run_vertical_slice._write_bounded_quarantine_evidence(parent, "replacement", {"result": "NEW"})

                    if boundary != "return":
                        run_vertical_slice._write_bounded_quarantine_evidence(parent, "replacement", {"result": "NEW"})

                first = run_vertical_slice._custody_reconciliation(parent)
                second = run_vertical_slice._custody_reconciliation(parent)
                self.assertEqual(second, first)
                events = ledger_events(parent)
                prepared = [event for event in events if event.get("event") == "PREPARED"]
                pointers = [event["pointer"] for event in prepared]
                self.assertEqual(len(pointers), len(set(pointers)))
                victim_pointer = victim.relative_to(parent).as_posix()
                self.assertEqual(
                    [event["event"] for event in events if event.get("pointer") == victim_pointer],
                    ["PREPARED", "COMMITTED"],
                )
                self.assertFalse(victim.exists())


    def test_duplicate_prepared_pointer_is_fail_closed_and_preserves_raw_evidence(self) -> None:
        """A corrupt duplicate PREPARED row cannot authorize any deletion."""
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            with unittest.mock.patch.object(run_vertical_slice, "_MAX_QUARANTINE_FILES", 2):
                evidence = run_vertical_slice._write_bounded_quarantine_evidence(parent, "victim", {"result": "OLD"})
                replacement = run_vertical_slice._write_bounded_quarantine_evidence(parent, "replacement", {"result": "NEW"})
            os.utime(evidence, ns=(replacement.stat().st_mtime_ns - 1, replacement.stat().st_mtime_ns - 1))
            payload = evidence.read_bytes()
            row = {
                "schema_version": "ember-checkpoint-custody-deletion-v2",
                "event": "PREPARED",
                "pointer": evidence.relative_to(parent).as_posix(),
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "reason": "bounded evidence retention",
            }
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            ledger.write_text("\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for _ in range(2)) + "\n", encoding="utf-8")
            ledger_before = ledger.read_bytes()
            with unittest.mock.patch.object(run_vertical_slice, "_MAX_QUARANTINE_FILES", 2):
                with self.assertRaisesRegex(RuntimeError, "duplicate|transition"):
                    run_vertical_slice._write_bounded_quarantine_evidence(parent, "third", {"result": "THIRD"})
            self.assertEqual(evidence.read_bytes(), payload)
            self.assertEqual(ledger.read_bytes(), ledger_before)
            with self.assertRaisesRegex(RuntimeError, "duplicate|transition"):
                run_vertical_slice._custody_reconciliation(parent)

    def test_torn_or_unterminated_ledger_tails_are_refused_without_append(self) -> None:
        """A legacy torn tail is fail-closed; a new transition never splices bytes onto it."""

        def event(kind: str) -> dict[str, object]:
            payload = b'{"result":"old"}\n'
            return {
                "schema_version": "ember-checkpoint-custody-deletion-v2",
                "event": kind,
                "pointer": ".checkpoint-quarantine/evidence-" + "a" * 64 + ".json",
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "reason": "bounded evidence retention",
            }

        for kind in ("PREPARED", "COMMITTED"):
            for tail in ("truncated", "unterminated"):
                with self.subTest(kind=kind, tail=tail), tempfile.TemporaryDirectory() as directory:
                    parent = Path(directory)
                    ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
                    rows = [] if kind == "PREPARED" else [event("PREPARED")]
                    encoded = b"".join(
                        (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
                        for row in rows
                    )
                    final = json.dumps(event(kind), sort_keys=True, separators=(",", ":")).encode("utf-8")
                    ledger.write_bytes(encoded + (final[: len(final) // 2] if tail == "truncated" else final))
                    before = ledger.read_bytes()
                    with self.assertRaisesRegex(RuntimeError, "ledger|malformed|terminated"):
                        run_vertical_slice._write_bounded_quarantine_evidence(parent, "new", {"result": "new"})
                    self.assertEqual(ledger.read_bytes(), before)

    def test_atomic_ledger_replace_crash_converges_without_duplicate_transition(self) -> None:
        """A crash after atomic replacement leaves a complete PREPARED record that resumes once."""
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            with unittest.mock.patch.object(run_vertical_slice, "_MAX_QUARANTINE_FILES", 1):
                victim = run_vertical_slice._write_bounded_quarantine_evidence(parent, "victim", {"result": "old"})
                ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
                real_replace = run_vertical_slice.atomic_replace_durable
                replaced = False

                def crash_after_replace(source: object, target: object) -> None:
                    nonlocal replaced
                    real_replace(source, target)
                    if Path(target).name == ledger.name and not replaced:
                        replaced = True
                        raise OSError("injected crash after atomic ledger replace")

                with unittest.mock.patch.object(run_vertical_slice, "atomic_replace_durable", crash_after_replace):
                    with self.assertRaisesRegex(OSError, "atomic ledger replace"):
                        run_vertical_slice._write_bounded_quarantine_evidence(parent, "replacement", {"result": "new"})
                self.assertTrue(victim.exists())
                run_vertical_slice._write_bounded_quarantine_evidence(parent, "replacement", {"result": "new"})
            events = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()]
            pointer = victim.relative_to(parent).as_posix()
            self.assertEqual([row["event"] for row in events if row["pointer"] == pointer], ["PREPARED", "COMMITTED"])
            first = run_vertical_slice._custody_reconciliation(parent)
            self.assertEqual(run_vertical_slice._custody_reconciliation(parent), first)

    def test_append_replays_final_ledger_snapshot_while_writer_lock_is_held(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            held = False
            wrote = False
            real_lock = run_vertical_slice._custody_ledger_write_lock
            real_snapshot = run_vertical_slice._custody_ledger_snapshot
            real_atomic = run_vertical_slice._atomic_bytes
            @contextlib.contextmanager
            def lock(path: Path):
                nonlocal held
                with real_lock(path) as canonical:
                    held = True
                    try:
                        yield canonical
                    finally:
                        held = False
            def atomic(path: Path, payload: bytes) -> None:
                nonlocal wrote
                wrote = True
                real_atomic(path, payload)
            def snapshot(path: Path):
                if wrote:
                    self.assertTrue(held)
                return real_snapshot(path)
            event = {"event": "PREPARED", "pointer": ".checkpoint-quarantine/evidence-" + "d" * 64 + ".json", "bytes": 1, "sha256": "d" * 64, "reason": "post-write replay"}
            with unittest.mock.patch.object(run_vertical_slice, "_custody_ledger_write_lock", lock), unittest.mock.patch.object(run_vertical_slice, "_atomic_bytes", atomic), unittest.mock.patch.object(run_vertical_slice, "_custody_ledger_snapshot", snapshot):
                run_vertical_slice._append_custody_ledger_transition(parent, event)
    def test_invalid_semantic_transition_leaves_ledger_and_receipt_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as receipts:
            parent = Path(directory)
            pointer = ".checkpoint-quarantine/evidence-" + "d" * 64 + ".json"
            event = {"event": "COMMITTED", "pointer": pointer, "bytes": 1, "sha256": "d" * 64, "reason": "invalid"}
            receipt = Path(receipts) / "invalid.json"
            with self.assertRaisesRegex(RuntimeError, "requires exactly one prior PREPARED"):
                run_vertical_slice._append_custody_ledger_transition(parent, event, transaction_receipt_path=receipt, operation_id="invalid", subject=run_vertical_slice._custody_path_subject(parent.resolve()))
            self.assertFalse((parent / ".checkpoint-custody-deletion-ledger.jsonl").exists())
            self.assertFalse(receipt.exists())
            prepared = {**event, "event": "PREPARED"}
            run_vertical_slice._append_custody_ledger_transition(parent, prepared)
            before = (parent / ".checkpoint-custody-deletion-ledger.jsonl").read_bytes()
            mismatched = {**event, "reason": "mismatch"}
            with self.assertRaisesRegex(RuntimeError, "identity differs"):
                run_vertical_slice._append_custody_ledger_transition(parent, mismatched, transaction_receipt_path=receipt, operation_id="invalid-2", subject=run_vertical_slice._custody_path_subject(parent.resolve()))
            self.assertEqual((parent / ".checkpoint-custody-deletion-ledger.jsonl").read_bytes(), before)
            self.assertFalse(receipt.exists())
    def test_append_rejects_hash_valid_prior_semantic_poison_before_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as receipts:
            parent = Path(directory)
            poisoned = run_vertical_slice._next_custody_ledger_frame({
                "event": "COMMITTED", "pointer": ".checkpoint-quarantine/evidence-" + "a" * 64 + ".json",
                "bytes": 1, "sha256": "a" * 64, "reason": "poison",
            }, [])
            ledger = parent / ".checkpoint-custody-deletion-ledger.jsonl"
            ledger.write_text(json.dumps(poisoned, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            before = ledger.read_bytes()
            receipt = Path(receipts) / "must-not-exist.json"
            event = {"event": "PREPARED", "pointer": ".checkpoint-quarantine/evidence-" + "b" * 64 + ".json", "bytes": 1, "sha256": "b" * 64, "reason": "new"}
            with self.assertRaisesRegex(RuntimeError, "COMMITTED without PREPARED"):
                run_vertical_slice._append_custody_ledger_transition(parent, event, transaction_receipt_path=receipt)
            self.assertEqual(ledger.read_bytes(), before)
            self.assertFalse(receipt.exists())

    def test_append_rejects_foreign_subject_before_external_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as receipts:
            parent = Path(directory)
            receipt = Path(receipts) / "foreign.json"
            event = {"event": "PREPARED", "pointer": ".checkpoint-quarantine/evidence-" + "c" * 64 + ".json", "bytes": 1, "sha256": "c" * 64, "reason": "foreign"}
            with self.assertRaisesRegex(RuntimeError, "subject"):
                run_vertical_slice._append_custody_ledger_transition(parent, event, transaction_receipt_path=receipt, subject="custody:another-root")
            self.assertFalse((parent / ".checkpoint-custody-deletion-ledger.jsonl").exists())
            self.assertFalse(receipt.exists())
    def test_atomic_ledger_transition_serializes_distinct_concurrent_writers(self) -> None:
        """Concurrent transitions retain both rows rather than last-writer-wins replacement."""
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            events = [
                {
                    "schema_version": "ember-checkpoint-custody-deletion-v2",
                    "event": "PREPARED",
                    "pointer": f".checkpoint-quarantine/evidence-{letter * 64}.json",
                    "bytes": 1,
                    "sha256": letter * 64,
                    "reason": "concurrent test",
                }
                for letter in ("a", "b")
            ]
            real_atomic = run_vertical_slice._atomic_bytes
            gate = threading.Event()
            entered = 0
            entered_lock = threading.Lock()
            errors: list[BaseException] = []

            def delayed_atomic(path: Path, payload: bytes) -> None:
                nonlocal entered
                with entered_lock:
                    entered += 1
                    if entered == 2:
                        gate.set()
                gate.wait(timeout=0.1)
                real_atomic(path, payload)

            def writer(event: dict[str, object]) -> None:
                try:
                    run_vertical_slice._append_custody_ledger_transition(parent, event)
                except BaseException as error:
                    errors.append(error)

            with unittest.mock.patch.object(run_vertical_slice, "_atomic_bytes", delayed_atomic):
                threads = [threading.Thread(target=writer, args=(event,)) for event in events]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=2)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            _, recorded = run_vertical_slice._custody_ledger_snapshot(parent)
            self.assertEqual({row["pointer"] for row in recorded if isinstance(row, dict)}, {event["pointer"] for event in events})

    def test_atomic_bytes_fsyncs_parent_directory_after_replace_when_supported(self) -> None:
        """The replacement metadata is durably flushed through the containing directory on POSIX."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "ledger.jsonl"
            real_fsync = run_vertical_slice.os.fsync
            calls: list[int] = []

            def recording_fsync(descriptor: int) -> None:
                calls.append(descriptor)
                if descriptor != 913:
                    real_fsync(descriptor)

            with unittest.mock.patch.object(run_vertical_slice.os, "name", "posix"), \
                 unittest.mock.patch.object(run_vertical_slice.os, "open", return_value=913) as open_directory, \
                 unittest.mock.patch.object(run_vertical_slice.os, "close") as close_directory, \
                 unittest.mock.patch.object(run_vertical_slice.os, "fsync", recording_fsync):
                run_vertical_slice._atomic_bytes(target, b"ledger\n")
            open_directory.assert_called_once_with(str(target.parent), os.O_RDONLY)
            close_directory.assert_called_once_with(913)
            self.assertIn(913, calls)
    def test_atomic_ledger_transition_serializes_distinct_process_writers(self) -> None:
        """Independent Python processes retain both ledger rows under the rooted lock."""
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            ready = parent / "ready"
            release = parent / "release"
            module_root = ROOT / "tools" / "ember-restart-3b"
            worker = (
                "import json, os, pathlib, sys, time\n"
                f"sys.path.insert(0, {str(module_root)!r})\n"
                "import run_vertical_slice as runner\n"
                "parent = pathlib.Path(os.environ['LEDGER_PARENT'])\n"
                "ready = pathlib.Path(os.environ['LEDGER_READY'])\n"
                "release = pathlib.Path(os.environ['LEDGER_RELEASE'])\n"
                "event = json.loads(os.environ['LEDGER_EVENT'])\n"
                "real = runner._atomic_bytes\n"
                "def delayed(path, payload):\n"
                "    ready.mkdir(exist_ok=True)\n"
                "    (ready / str(os.getpid())).write_text('ready')\n"
                "    while not release.exists(): time.sleep(0.005)\n"
                "    real(path, payload)\n"
                "runner._atomic_bytes = delayed\n"
                "runner._append_custody_ledger_transition(parent, event)\n"
            )
            events = [
                {
                    "schema_version": "ember-checkpoint-custody-deletion-v2",
                    "event": "PREPARED",
                    "pointer": f".checkpoint-quarantine/evidence-{letter * 64}.json",
                    "bytes": 1,
                    "sha256": letter * 64,
                    "reason": "process writer test",
                }
                for letter in ("a", "b")
            ]
            processes: list[subprocess.Popen[str]] = []
            try:
                for event in events:
                    environment = os.environ.copy()
                    environment.update({"LEDGER_PARENT": str(parent), "LEDGER_READY": str(ready), "LEDGER_RELEASE": str(release), "LEDGER_EVENT": json.dumps(event)})
                    processes.append(subprocess.Popen([sys.executable, "-c", worker], env=environment, text=True))
                first_deadline = time.monotonic() + 5.0
                while (not ready.exists() or not list(ready.glob("*"))) and time.monotonic() < first_deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists() and list(ready.glob("*")), "first worker did not reach the serialized write boundary")
                overlap_deadline = time.monotonic() + 0.5
                while len(list(ready.glob("*"))) < 2 and time.monotonic() < overlap_deadline:
                    time.sleep(0.01)
                ready_workers = list(ready.glob("*"))
                self.assertEqual(len(ready_workers), 1, "the second process reached the snapshot/write boundary before the rooted lock")
                release.write_text("go", encoding="utf-8")
                for process in processes:
                    self.assertEqual(process.wait(timeout=10), 0)
            finally:
                release.touch(exist_ok=True)
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)
            _, recorded = run_vertical_slice._custody_ledger_snapshot(parent)
            self.assertEqual({row["pointer"] for row in recorded if isinstance(row, dict)}, {event["pointer"] for event in events})

    @unittest.skipUnless(os.name == "nt", "native Windows mutex contract")
    def test_windows_ledger_writer_lock_has_no_ownerless_custody_directory_gap(self) -> None:
        """Windows uses a kernel-owned mutex rather than a mkdir-then-attest lock directory."""
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            with run_vertical_slice._custody_ledger_write_lock(parent):
                self.assertFalse((parent / ".checkpoint-custody-deletion-ledger.lock").exists())
    def test_posix_custody_subject_preserves_case_distinct_canonical_paths(self) -> None:
        """Case-sensitive POSIX custody roots must not collapse into one opaque subject."""
        class CanonicalPath:
            def __init__(self, spelling: str) -> None:
                self.spelling = spelling

            def resolve(self, *, strict: bool = True) -> "CanonicalPath":
                self.assert_true(strict)
                return self

            def assert_true(self, value: bool) -> None:
                if not value:
                    raise AssertionError("custody subject must use a strict canonical path")

            def __str__(self) -> str:
                return self.spelling

        upper = CanonicalPath("case-root/CaseDistinct")
        lower = CanonicalPath("case-root/casedistinct")
        with unittest.mock.patch.object(run_vertical_slice.os, "name", "posix"), unittest.mock.patch.object(run_vertical_slice.os, "path", posixpath), unittest.mock.patch.object(run_vertical_slice, "Path", side_effect=lambda value: value):
            self.assertNotEqual(
                run_vertical_slice._custody_path_subject(upper),
                run_vertical_slice._custody_path_subject(lower),
            )
            self.assertEqual(
                run_vertical_slice._custody_path_subject(upper),
                run_vertical_slice._custody_path_subject(upper),
            )
    def test_posix_custody_ledger_lock_yields_canonical_parent_and_releases_flock(self) -> None:
        """The non-Windows lock must yield the canonical root consumed by custody subjects."""
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            flock_calls: list[tuple[int, int]] = []

            class FakeFcntl:
                LOCK_EX = 1
                LOCK_UN = 2

                @staticmethod
                def flock(descriptor: int, operation: int) -> None:
                    flock_calls.append((descriptor, operation))

            with unittest.mock.patch.object(run_vertical_slice.os, "name", "posix"), unittest.mock.patch.dict(sys.modules, {"fcntl": FakeFcntl}):
                with run_vertical_slice._custody_ledger_write_lock(parent) as canonical_parent:
                    self.assertEqual(canonical_parent, parent.resolve())
                    self.assertEqual(len(flock_calls), 1)
                    self.assertEqual(flock_calls[0][1], FakeFcntl.LOCK_EX)
            self.assertEqual([operation for _, operation in flock_calls], [FakeFcntl.LOCK_EX, FakeFcntl.LOCK_UN])
    def test_timed_out_ledger_waiter_preserves_live_owner_lock(self) -> None:
        """A native waiter cannot append while another process owns the kernel mutex."""
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            ready = parent / "owner-ready"
            release = parent / "owner-release"
            module_root = ROOT / "tools" / "ember-restart-3b"
            owner = (
                "import os, pathlib, sys, time\n"
                f"sys.path.insert(0, {str(module_root)!r})\n"
                "import run_vertical_slice as runner\n"
                "parent = pathlib.Path(os.environ['LEDGER_PARENT'])\n"
                "ready = pathlib.Path(os.environ['LEDGER_READY'])\n"
                "release = pathlib.Path(os.environ['LEDGER_RELEASE'])\n"
                "with runner._custody_ledger_write_lock(parent):\n"
                "    ready.write_text('held')\n"
                "    while not release.exists(): time.sleep(0.005)\n"
            )
            environment = os.environ.copy()
            environment.update({"LEDGER_PARENT": str(parent), "LEDGER_READY": str(ready), "LEDGER_RELEASE": str(release)})
            process = subprocess.Popen([sys.executable, "-c", owner], env=environment, text=True)
            try:
                deadline = time.monotonic() + 5.0
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists(), "owner process did not acquire the kernel mutex")
                event = {"schema_version": "ember-checkpoint-custody-deletion-v2", "event": "PREPARED", "pointer": ".checkpoint-quarantine/evidence-" + "c" * 64 + ".json", "bytes": 1, "sha256": "c" * 64, "reason": "timed out waiter test"}
                with unittest.mock.patch.object(run_vertical_slice, "_LEDGER_LOCK_WAIT_SECONDS", 0.0):
                    with self.assertRaisesRegex(RuntimeError, "timed out"):
                        run_vertical_slice._append_custody_ledger_transition(parent, event)
                self.assertFalse((parent / ".checkpoint-custody-deletion-ledger.jsonl").exists())
            finally:
                release.touch(exist_ok=True)
                if process.poll() is None:
                    self.assertEqual(process.wait(timeout=10), 0)
    @unittest.skipUnless(os.name == "nt", "native Windows mutex contract")
    def test_windows_ledger_mutex_recovers_an_abandoned_owner_without_lock_artifacts(self) -> None:
        """A dead mutex owner cannot strand custody or require a creator-attestation grace path."""
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            ready = parent / "owner-ready"
            module_root = ROOT / "tools" / "ember-restart-3b"
            owner = (
                "import os, pathlib, sys\n"
                f"sys.path.insert(0, {str(module_root)!r})\n"
                "import run_vertical_slice as runner\n"
                "parent = pathlib.Path(os.environ['LEDGER_PARENT'])\n"
                "ready = pathlib.Path(os.environ['LEDGER_READY'])\n"
                "with runner._custody_ledger_write_lock(parent):\n"
                "    ready.write_text('held', encoding='utf-8')\n"
                "    os._exit(0)\n"
            )
            environment = os.environ.copy()
            environment["LEDGER_PARENT"] = str(parent)
            environment["LEDGER_READY"] = str(ready)
            process = subprocess.Popen([sys.executable, "-c", owner], env=environment)
            try:
                deadline = time.monotonic() + 10
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists(), "owner never acquired the native mutex")
                self.assertEqual(process.wait(timeout=10), 0)
                event = {
                    "schema_version": "ember-checkpoint-custody-deletion-v2",
                    "event": "PREPARED",
                    "pointer": ".checkpoint-quarantine/evidence-" + "c" * 64 + ".json",
                    "bytes": 1,
                    "sha256": "c" * 64,
                    "reason": "abandoned native mutex owner test",
                }
                run_vertical_slice._append_custody_ledger_transition(parent, event)
                self.assertFalse((parent / ".checkpoint-custody-deletion-ledger.lock").exists())
                self.assertEqual(len(run_vertical_slice._custody_ledger_snapshot(parent)[1]), 1)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=10)
    def test_atomic_ledger_reclaims_crashed_owner_before_owner_attestation(self) -> None:
        """A POSIX request without fcntl fails closed instead of reclaiming an ownerless directory."""
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            event = {"schema_version": "ember-checkpoint-custody-deletion-v2", "event": "PREPARED", "pointer": ".checkpoint-quarantine/evidence-" + "b" * 64 + ".json", "bytes": 1, "sha256": "b" * 64, "reason": "unattested crashed owner test"}
            with unittest.mock.patch.object(run_vertical_slice.os, "name", "posix"):
                with self.assertRaisesRegex(RuntimeError, "requires fcntl"):
                    run_vertical_slice._append_custody_ledger_transition(parent, event)
    def test_custody_ledger_lock_namespace_is_not_custody_evidence(self) -> None:
        """The ephemeral cross-process lock is excluded from durable custody accounting."""
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            lock = parent / ".checkpoint-custody-deletion-ledger.lock"
            lock.mkdir()
            (lock / "owner.json").write_text("{\\\"pid\\\":1}\\n", encoding="utf-8")
            self.assertEqual(run_vertical_slice._custody_serialized_bytes(parent), 0)
    def test_atomic_ledger_reclaims_crashed_process_owner(self) -> None:
        """A POSIX request without fcntl fails closed instead of using PID or age metadata."""
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            event = {"schema_version": "ember-checkpoint-custody-deletion-v2", "event": "PREPARED", "pointer": ".checkpoint-quarantine/evidence-" + "a" * 64 + ".json", "bytes": 1, "sha256": "a" * 64, "reason": "crashed owner test"}
            with unittest.mock.patch.object(run_vertical_slice.os, "name", "posix"):
                with self.assertRaisesRegex(RuntimeError, "requires fcntl"):
                    run_vertical_slice._append_custody_ledger_transition(parent, event)
    def test_atomic_bytes_refuses_to_claim_a_windows_replace_failure(self) -> None:
        """A write-through failure leaves no target or temporary custody claim behind."""
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "ledger.jsonl"
            with unittest.mock.patch.object(run_vertical_slice, "atomic_replace_durable", side_effect=OSError("write-through failure")):
                with self.assertRaisesRegex(OSError, "write-through failure"):
                    run_vertical_slice._atomic_bytes(target, b"ledger\\n")
            self.assertFalse(target.exists())
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])
    def test_shared_windows_atomic_replace_requests_write_through_and_propagates_failure(self) -> None:
        """The one durable_io authority requests write-through and refuses an API failure."""
        calls: list[tuple[object, object, int]] = []

        class Kernel32:
            def MoveFileExW(self, source: object, target: object, flags: int) -> int:
                calls.append((source, target, flags))
                return 0

        with unittest.mock.patch.object(durable_io.os, "name", "nt"), \
                unittest.mock.patch.object(durable_io.ctypes, "WinDLL", return_value=Kernel32()), \
                unittest.mock.patch.object(durable_io.ctypes, "get_last_error", return_value=5), \
                unittest.mock.patch.object(durable_io.ctypes, "WinError", side_effect=OSError("write-through failed")):
            with self.assertRaisesRegex(OSError, "write-through failed"):
                durable_io.atomic_replace_durable(Path("source.tmp"), Path("target.json"))
        self.assertEqual(calls[0][2], 0x00000001 | 0x00000008)
    def test_windows_ledger_mutex_name_uses_global_handle_identity_not_path_spelling(self) -> None:
        """One opened-directory identity yields one Global mutex independent of spelling."""
        identity = (1234, 0x11111111, 0x22222222)
        expected = run_vertical_slice._windows_custody_ledger_mutex_name_from_identity(identity)
        self.assertTrue(expected.startswith("Global\\ember-checkpoint-custody-"))
        self.assertEqual(expected, run_vertical_slice._windows_custody_ledger_mutex_name_from_identity(identity))
        self.assertNotEqual(expected, run_vertical_slice._windows_custody_ledger_mutex_name_from_identity((1234, 0x11111111, 0x22222223)))
    def test_windows_handle_identity_keeps_unicode_distinct_roots_separate(self) -> None:
        """No Unicode/casefold path normalization can collapse distinct directory file IDs."""
        strasse = run_vertical_slice._windows_custody_ledger_mutex_name_from_identity((7, 1, 1))
        sharp_s = run_vertical_slice._windows_custody_ledger_mutex_name_from_identity((7, 1, 2))
        self.assertNotEqual(strasse, sharp_s)
        self.assertEqual(strasse, run_vertical_slice._windows_custody_ledger_mutex_name_from_identity((7, 1, 1)))
    @unittest.skipUnless(os.name == "nt", "native Windows mutex contract")
    def test_windows_mutex_namespace_failure_is_fail_closed(self) -> None:
        """A denied native mutex API cannot fall back to Local or filesystem ownership."""
        with tempfile.TemporaryDirectory() as directory:
            with unittest.mock.patch.object(run_vertical_slice.ctypes, "WinDLL", side_effect=OSError("Global denied")):
                with self.assertRaisesRegex(OSError, "Global denied"):
                    with run_vertical_slice._custody_ledger_write_lock(Path(directory)):
                        self.fail("fail-closed lock unexpectedly entered")
            self.assertFalse((Path(directory) / ".checkpoint-custody-deletion-ledger.lock").exists())
    @unittest.skipUnless(os.name == "nt", "native Windows mutex contract")
    def test_windows_directory_handle_identity_converges_drive_extended_and_case_aliases(self) -> None:
        """A real opened directory handle, not path spelling, controls the mutex identity."""
        with tempfile.TemporaryDirectory() as directory:
            drive = Path(directory)
            extended = Path("\\\\?\\" + str(drive.resolve()))
            case_alias = Path(str(drive).upper())
            identities = [run_vertical_slice._windows_directory_identity(path) for path in (drive, extended, case_alias)]
            names = [run_vertical_slice._windows_custody_ledger_mutex_name(path) for path in (drive, extended, case_alias)]
            self.assertEqual(identities[0], identities[1])
            self.assertEqual(identities[0], identities[2])
            self.assertEqual(names, [names[0], names[0], names[0]])
    @unittest.skipUnless(os.name == "nt", "native Windows mutex contract")
    def test_windows_bound_directory_handle_rejects_swap_and_preserves_ledger_row(self) -> None:
        """A path swap cannot redirect a locked snapshot/write to a replacement directory."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            parent = root / "custody"
            parent.mkdir()
            moved = root / "moved-custody"
            event = {
                "schema_version": "ember-checkpoint-custody-deletion-v2",
                "event": "PREPARED",
                "pointer": ".checkpoint-quarantine/evidence-" + "e" * 64 + ".json",
                "bytes": 1,
                "sha256": "e" * 64,
                "reason": "directory swap regression",
            }
            real_atomic = run_vertical_slice._atomic_bytes

            def swap_then_write(path: Path, payload: bytes) -> None:
                with self.assertRaises(PermissionError):
                    parent.rename(moved)
                real_atomic(path, payload)

            with unittest.mock.patch.object(run_vertical_slice, "_atomic_bytes", side_effect=swap_then_write):
                run_vertical_slice._append_custody_ledger_transition(parent, event)
            self.assertTrue((parent / ".checkpoint-custody-deletion-ledger.jsonl").is_file())
            self.assertFalse(moved.exists())
            _, rows = run_vertical_slice._custody_ledger_snapshot(parent)
            self.assertEqual(len(rows), 1)
            self.assertEqual({key: rows[0][key] for key in ("event", "pointer", "bytes", "sha256", "reason")}, {key: event[key] for key in ("event", "pointer", "bytes", "sha256", "reason")})
            self.assertEqual(rows[0]["schema_version"], run_vertical_slice._CUSTODY_LEDGER_SCHEMA)
            self.assertEqual(rows[0]["sequence"], 0)
            self.assertEqual(rows[0]["previous_frame_sha256"], "0" * 64)
            self.assertTrue(run_vertical_slice._is_sha256(rows[0]["frame_sha256"]))
    @unittest.skipUnless(os.name == "nt", "native Windows mutex contract")
    def test_windows_abandoned_mutex_recovers_while_another_process_survives(self) -> None:
        """Kernel abandoned-owner recovery is independent of unrelated live process/PID state."""
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            ready = parent / "ready"
            module_root = ROOT / "tools" / "ember-restart-3b"
            owner = "import os,pathlib,sys;sys.path.insert(0," + repr(str(module_root)) + ");import run_vertical_slice as r;p=pathlib.Path(os.environ['P']);q=pathlib.Path(os.environ['R']);\nwith r._custody_ledger_write_lock(p): q.write_text('held'); os._exit(0)"
            environment = os.environ.copy(); environment.update({"P": str(parent), "R": str(ready)})
            process = subprocess.Popen([sys.executable, "-c", owner], env=environment)
            self.assertEqual(process.wait(timeout=10), 0)
            self.assertTrue(ready.exists())
            event = {"schema_version":"ember-checkpoint-custody-deletion-v2","event":"PREPARED","pointer":".checkpoint-quarantine/evidence-" + "d" * 64 + ".json","bytes":1,"sha256":"d" * 64,"reason":"surviving-process abandoned mutex"}
            run_vertical_slice._append_custody_ledger_transition(parent, event)
            self.assertEqual(len(run_vertical_slice._custody_ledger_snapshot(parent)[1]), 1)
if __name__ == "__main__":
    unittest.main()
