# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Issue #2119 section 5: manifests/ember-current-subject-v1.json already had a
closed-schema reader (gen_readme_status.load_current_subject) and no writer.
update_current_subject.py is that writer -- these tests exercise its three
mechanisms against the REAL reader and the REAL checkpoint-identity function,
not mocks of either: a stale-parent compare-and-swap, a pre-write round-trip
validation, and the atomic replace, each with the target file's bytes
compared before/after to prove a refusal changes nothing on disk.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[5]
MODULE_PATH = (
    ROOT / "src" / "ember" / "governance" / "scripts" / "update_current_subject.py"
)


def load_module():
    sys.path.insert(0, str(ROOT / "src" / "ember" / "governance" / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "update_current_subject_under_test", MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_checkpoint(root: pathlib.Path, tag: str) -> pathlib.Path:
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "checkpoint-manifest.json"
    manifest_path.write_text(
        json.dumps({"schema_version": "ember-sparse-checkpoint-v5", "tag": tag}),
        encoding="utf-8",
    )
    return manifest_path


def manifest_sha256(manifest_path: pathlib.Path) -> str:
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def full_candidate_payload(
    *,
    predecessor_sha256: str,
    tokens_seen: int,
    predecessor_tokens_seen: int,
    served: int = 20,
) -> dict[str, object]:
    """A complete, otherwise-valid ember-current-subject-v1 payload.

    checkpoint_manifest_sha256 is a placeholder -- update_current_subject
    always overwrites it with the freshly re-derived value, so the input
    value here is deliberately wrong (all-zero) to prove that.
    """

    return {
        "schema_version": "ember-current-subject-v1",
        "authority": {
            "goal_id": "EMBER-02",
            "workstream_id": "EMBER-02A",
            "next_executed_outcome": (
                "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
            ),
        },
        "subject": {
            "active_route": "governed-vertical",
            "capability_credit": "none",
            "checkpoint_custody": {
                "class": "private_checkpoint_bytes",
                "locator_id": "test-locator",
                "public_manifest_bytes_present": False,
            },
            "checkpoint_manifest_sha256": "0" * 64,
            "disposition": "CHECKPOINT_CANDIDATE_NOT_ADMITTED",
            "evidence_paths": ["receipts/test/evidence.json"],
            "model_config_sha256": sha256_text("model-config"),
            "optimizer_state_sha256": sha256_text("optimizer-state"),
            "parameters": {
                "active": 10,
                "allocated": 100,
                "episode_trainable": 5,
                "served": served,
                "trainable": 50,
                "unique": 80,
            },
            "predecessor": {
                "checkpoint_manifest_sha256": predecessor_sha256,
                "relationship": "historical_step1_predecessor",
                "tokens_seen": predecessor_tokens_seen,
            },
            "sufficient_pretraining_proven": False,
            "token_cursor": {
                "global_step": 100,
                "record_index": 5,
                "token_offset": 7,
                "tokens_seen": tokens_seen,
            },
            "tokenizer_sha256": sha256_text("tokenizer"),
        },
    }


class UpdateCurrentSubjectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_module()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_root = pathlib.Path(self._tmp.name)
        self.target = self.tmp_root / "manifests" / "ember-current-subject-v1.json"

    def _bootstrap(self) -> tuple[pathlib.Path, str]:
        checkpoint_root = self.tmp_root / "ckpt-1"
        manifest = write_checkpoint(checkpoint_root, "one")
        step1_sha256 = sha256_text("step-1-genesis")
        payload = full_candidate_payload(
            predecessor_sha256=step1_sha256,
            tokens_seen=1000,
            predecessor_tokens_seen=0,
        )
        self.module.update_current_subject(
            repo_root=ROOT,
            published_checkpoint_root=checkpoint_root,
            candidate_payload=payload,
            expected_parent_checkpoint_manifest_sha256=self.module.GENESIS_SENTINEL,
            current_subject_path=self.target,
        )
        return checkpoint_root, manifest_sha256(manifest)

    def test_bootstrap_write_binds_the_real_checkpoint_identity(self) -> None:
        _, checkpoint1_sha256 = self._bootstrap()
        self.assertTrue(self.target.exists())
        written = json.loads(self.target.read_text(encoding="utf-8"))
        self.assertEqual(
            written["subject"]["checkpoint_manifest_sha256"], checkpoint1_sha256
        )
        # The candidate's own placeholder ("0" * 64) was never trusted.
        self.assertNotEqual(
            written["subject"]["checkpoint_manifest_sha256"], "0" * 64
        )

    def test_bootstrap_without_genesis_sentinel_is_refused(self) -> None:
        """A bootstrap write (no prior record) with a real-looking expected
        parent is refused -- GENESIS must be named explicitly, never guessed."""

        checkpoint_root = self.tmp_root / "ckpt-1"
        write_checkpoint(checkpoint_root, "one")
        payload = full_candidate_payload(
            predecessor_sha256=sha256_text("step-1-genesis"),
            tokens_seen=1000,
            predecessor_tokens_seen=0,
        )
        with self.assertRaises(self.module.StaleParentError):
            self.module.update_current_subject(
                repo_root=ROOT,
                published_checkpoint_root=checkpoint_root,
                candidate_payload=payload,
                expected_parent_checkpoint_manifest_sha256="a" * 64,
                current_subject_path=self.target,
            )
        self.assertFalse(self.target.exists())

    def test_stale_parent_is_refused_and_target_is_provably_unchanged(self) -> None:
        """The exact deliberate red the issue's test-requirements section
        names: a planted stale-parent fixture must refuse, real gate, real
        checkpoint bytes -- not a mock of the compare-and-swap."""

        _, checkpoint1_sha256 = self._bootstrap()
        before_bytes = self.target.read_bytes()

        checkpoint2_root = self.tmp_root / "ckpt-2"
        write_checkpoint(checkpoint2_root, "two")
        payload = full_candidate_payload(
            predecessor_sha256="f" * 64,  # irrelevant: preserved from current, not read
            tokens_seen=2000,
            predecessor_tokens_seen=0,
        )

        with self.assertRaises(self.module.StaleParentError):
            self.module.update_current_subject(
                repo_root=ROOT,
                published_checkpoint_root=checkpoint2_root,
                candidate_payload=payload,
                # Deliberately wrong: the real current parent is
                # checkpoint1_sha256, not this value.
                expected_parent_checkpoint_manifest_sha256="a" * 64,
                current_subject_path=self.target,
            )

        after_bytes = self.target.read_bytes()
        self.assertEqual(before_bytes, after_bytes)
        self.assertNotEqual("a" * 64, checkpoint1_sha256)
        self._assert_no_leftover_temp_files()

    def test_correct_parent_advances_and_preserves_the_fixed_predecessor(self) -> None:
        """load_current_subject pins subject.predecessor to the lineage's
        fixed step-1 anchor (relationship == historical_step1_predecessor,
        never equal to the subject's own identity) -- it is not a rolling
        pointer to the outgoing subject. This is the corrected reading of
        the issue's own worked example (see update_current_subject.py's
        module docstring): the writer must PRESERVE predecessor across a
        non-bootstrap advance, not overwrite it with the prior head."""

        checkpoint1_root, checkpoint1_sha256 = self._bootstrap()
        original = json.loads(self.target.read_text(encoding="utf-8"))
        original_predecessor = original["subject"]["predecessor"]

        checkpoint2_root = self.tmp_root / "ckpt-2"
        manifest2 = write_checkpoint(checkpoint2_root, "two")
        payload = full_candidate_payload(
            # A naive writer might set this to checkpoint1's own identity;
            # the real writer must ignore it and preserve the original.
            predecessor_sha256=checkpoint1_sha256,
            tokens_seen=2000,
            predecessor_tokens_seen=0,
        )

        written = self.module.update_current_subject(
            repo_root=ROOT,
            published_checkpoint_root=checkpoint2_root,
            candidate_payload=payload,
            expected_parent_checkpoint_manifest_sha256=checkpoint1_sha256,
            current_subject_path=self.target,
        )

        self.assertEqual(
            written["subject"]["checkpoint_manifest_sha256"],
            manifest_sha256(manifest2),
        )
        self.assertEqual(written["subject"]["predecessor"], original_predecessor)
        self.assertNotEqual(
            written["subject"]["predecessor"]["checkpoint_manifest_sha256"],
            checkpoint1_sha256,
        )

    def test_invalid_candidate_is_refused_pre_write_and_target_is_unchanged(
        self,
    ) -> None:
        """A payload that fails load_current_subject's own round-trip
        validation is refused before the atomic replace, and the target file
        is provably unchanged (byte-compare before/after), never discovered
        post-write."""

        _, checkpoint1_sha256 = self._bootstrap()
        before_bytes = self.target.read_bytes()

        checkpoint2_root = self.tmp_root / "ckpt-2"
        write_checkpoint(checkpoint2_root, "two")
        # served (1) violates the reader's active(10) <= served <= allocated
        # invariant -- a real closed-schema refusal, not a synthetic one.
        payload = full_candidate_payload(
            predecessor_sha256="e" * 64,
            tokens_seen=3000,
            predecessor_tokens_seen=0,
            served=1,
        )

        with self.assertRaisesRegex(
            ValueError, "current subject parameter relationships are invalid"
        ):
            self.module.update_current_subject(
                repo_root=ROOT,
                published_checkpoint_root=checkpoint2_root,
                candidate_payload=payload,
                expected_parent_checkpoint_manifest_sha256=checkpoint1_sha256,
                current_subject_path=self.target,
            )

        after_bytes = self.target.read_bytes()
        self.assertEqual(before_bytes, after_bytes)
        self._assert_no_leftover_temp_files()

    def test_missing_subject_object_is_refused(self) -> None:
        checkpoint_root = self.tmp_root / "ckpt-1"
        write_checkpoint(checkpoint_root, "one")
        with self.assertRaisesRegex(ValueError, "missing its subject object"):
            self.module.update_current_subject(
                repo_root=ROOT,
                published_checkpoint_root=checkpoint_root,
                candidate_payload={"schema_version": "ember-current-subject-v1"},
                expected_parent_checkpoint_manifest_sha256=self.module.GENESIS_SENTINEL,
                current_subject_path=self.target,
            )
        self.assertFalse(self.target.exists())

    def _assert_no_leftover_temp_files(self) -> None:
        leftovers = list(self.target.parent.glob(f".{self.target.name}.*.tmp"))
        self.assertEqual(leftovers, [], f"leftover staged temp files: {leftovers}")


if __name__ == "__main__":
    unittest.main()
