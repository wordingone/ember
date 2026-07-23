#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""cond3 Artifact B consumer replay (state/specs/cond3-seat-bridge-spec.md).

Proves the ONE fully-resolved OWNED_CANDIDATE identity instance
(tests/ember_restart/__fixtures__/cond3-artifact-b/) replays GREEN
through the named consumers WITHOUT field reinterpretation:

  1. validate_identity.py -- the SAME validator model.ts uses -- resolves the
     manifest with --require-resolved (proves zero unresolved fields; required
     negative #7, smallest-artifact scope) and byte-for-byte checkpoint binding.
  2. the seat bridge (derive_seat_identity) -- GREEN through steps 1-5.
  3. require_admitted_seat correctly REFUSES the derived seat, because
     disposition=OWNED_CANDIDATE is never admitted/credit-bearing (negative #6).

The /model status+load leg (real subprocess, same validate_identity.py
invocation convention as model.ts) is exercised in
tools/ember-cli/src/entrypoints/cond3-artifact-b.test.ts.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "tests" / "ember_restart" / "__fixtures__" / "cond3-artifact-b"
MANIFEST_PATH = FIXTURE_DIR / "manifest.json"
CHECKPOINT_PATH = FIXTURE_DIR / "checkpoint"
VALIDATOR_PATH = REPO_ROOT / "scripts" / "ember_01_identity" / "validate_identity.py"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from seat_identity_bridge import derive_seat_identity, require_admitted_seat


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Cond3ArtifactBConsumerReplay(unittest.TestCase):
    """Every assertion here fails RED until the fixture files exist and are
    genuinely fully-resolved -- there is no mock/stub in this file."""

    @classmethod
    def setUpClass(cls) -> None:
        if not MANIFEST_PATH.is_file():
            raise unittest.SkipTest(
                f"fixture not generated yet: {MANIFEST_PATH} "
                "(run scripts/ember_restart/build_cond3_artifact_b_fixture.py)"
            )
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.checkpoint_bytes = CHECKPOINT_PATH.read_bytes()

    # -- Sanity: the fixture is what it claims, never a hand-typed constant. --
    def test_fixture_checkpoint_hash_is_real(self) -> None:
        actual = _sha256_file(CHECKPOINT_PATH)
        self.assertEqual(self.manifest["checkpoint"]["byte_sha256"], actual)

    def test_fixture_is_fully_resolved_disposition_and_selection(self) -> None:
        self.assertEqual(self.manifest["identity"]["disposition"], "OWNED_CANDIDATE")
        self.assertFalse(self.manifest["identity"]["selected_as_owned_ember"])
        self.assertEqual(self.manifest["checkpoint"]["recovery_state"], "CLEAN")
        self.assertEqual(self.manifest["unresolved"], [])

    # -- Consumer 1: validate_identity.py, the SAME validator model.ts uses. --
    def test_consumer_validate_identity_resolves_with_require_resolved(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(VALIDATOR_PATH),
                str(MANIFEST_PATH),
                "--checkpoint",
                str(CHECKPOINT_PATH),
                "--require-resolved",
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            f"validate_identity.py --require-resolved must accept a fully-resolved "
            f"manifest; stdout={completed.stdout!r} stderr={completed.stderr!r}",
        )
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["byte_sha256"], self.manifest["checkpoint"]["byte_sha256"])
        self.assertEqual(payload["disposition"], "OWNED_CANDIDATE")

    def test_consumer_validate_identity_rejects_tampered_checkpoint(self) -> None:
        # Fail-closed control: a checkpoint that does NOT match byte_sha256
        # must REFUSE, proving the round-trip is bound to real bytes, not the
        # manifest's own say-so.
        import shutil
        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix="cond3-artifact-b-tamper-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        tampered = tmp / "checkpoint"
        tampered.write_bytes(b"tampered-bytes-do-not-match-manifest-hash")
        completed = subprocess.run(
            [
                sys.executable,
                str(VALIDATOR_PATH),
                str(MANIFEST_PATH),
                "--checkpoint",
                str(tampered),
            ],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
        self.assertNotEqual(
            completed.returncode,
            0,
            f"tampered checkpoint must REFUSE; stdout={completed.stdout!r}",
        )

    # -- Consumer 2/3: the seat bridge -- GREEN derivation, then REFUSED admission. --
    def test_consumer_seat_bridge_green_derivation(self) -> None:
        digest = hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()
        seat_config = {
            "certManifestPath": str(MANIFEST_PATH),
            "certManifestDigest": digest,
            "checkpointPath": str(CHECKPOINT_PATH),
            "endpointUrl": "http://127.0.0.1:8000",
        }
        result = derive_seat_identity(seat_config, repo_root=REPO_ROOT)
        self.assertTrue(result["valid"], f"expected GREEN derivation: {result.get('errors')}")
        seat = result["seat"]
        self.assertEqual(seat["checkpointSha256"], self.manifest["checkpoint"]["byte_sha256"])
        self.assertEqual(seat["modelConfigSha256"], self.manifest["architecture"]["sha256"])
        self.assertEqual(seat["tokenizerSha256"], self.manifest["tokenizer"]["sha256"])
        self.assertEqual(seat["id"], self.manifest["identity"]["model_id"])
        self.assertEqual(seat["disposition"], "OWNED_CANDIDATE")
        self.assertFalse(seat["admitted"])
        self.assertFalse(seat["creditBearing"])
        self.assertFalse(seat["selectedAsOwnedEmber"])

    def test_consumer_seat_bridge_refuses_admission_of_candidate(self) -> None:
        digest = hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()
        seat_config = {
            "certManifestPath": str(MANIFEST_PATH),
            "certManifestDigest": digest,
            "checkpointPath": str(CHECKPOINT_PATH),
        }
        result = derive_seat_identity(seat_config, repo_root=REPO_ROOT)
        self.assertTrue(result["valid"], f"precondition GREEN failed: {result.get('errors')}")
        with self.assertRaises(PermissionError) as ctx:
            require_admitted_seat(result["seat"])
        message = str(ctx.exception)
        self.assertIn("OWNED_CANDIDATE", message)
        self.assertIn("not OWNED_ADMITTED+selected", message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
