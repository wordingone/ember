#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Required negatives for the cond3 seat-chain identity bridge (frozen spec).

Each test is a REFUSE gate: the seat loader must derive identity from the cert
schema-v1 manifest, fail-closed, never as an independent authority.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = (
    REPO_ROOT / "tools" / "ember-cli" / "src" / "commands" / "__fixtures__" / "model-identity"
)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from seat_identity_bridge import derive_seat_identity, require_admitted_seat


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SeatIdentityBridgeNegatives(unittest.TestCase):
    """The 6 required negatives + the GREEN derivation path."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="seat-bridge-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.manifest_src = FIXTURE_DIR / "manifest.json"
        self.cert_manifest = json.loads(self.manifest_src.read_text(encoding="utf-8"))
        self.checkpoint_src = FIXTURE_DIR / "checkpoint"
        self.checkpoint_path = self.tmp / "checkpoint"
        shutil.copyfile(self.checkpoint_src, self.checkpoint_path)

    def _write_cert(self, manifest: dict, name: str = "cert-manifest.json") -> tuple[Path, str]:
        path = self.tmp / name
        data = json.dumps(manifest, indent=2).encode("utf-8")
        path.write_bytes(data)
        return path, _sha256_bytes(data)

    def _seat(self, **overrides) -> dict:
        cert_path, digest = self._write_cert(self.cert_manifest)
        seat = {
            "certManifestPath": str(cert_path),
            "certManifestDigest": digest,
            "checkpointPath": str(self.checkpoint_path),
            "endpointUrl": "http://127.0.0.1:8000",
        }
        seat.update(overrides)
        return seat

    def _refused(self, result: dict, why: str) -> None:
        self.assertFalse(result["valid"], f"expected REFUSE ({why}); got: {result}")
        self.assertIsNone(result.get("seat"), f"REFUSE must carry no seat ({why})")
        self.assertTrue(result.get("errors"), f"REFUSE must name errors ({why})")

    # GREEN: honest derivation from cert manifest + exact checkpoint bytes.
    def test_green_derivation_from_cert(self) -> None:
        result = derive_seat_identity(self._seat(), repo_root=REPO_ROOT)
        self.assertTrue(result["valid"], f"expected GREEN: {result.get('errors')}")
        derived = result["seat"]
        self.assertEqual(
            derived["checkpointSha256"], self.cert_manifest["checkpoint"]["byte_sha256"]
        )
        self.assertEqual(
            derived["modelConfigSha256"], self.cert_manifest["architecture"]["sha256"]
        )
        self.assertEqual(derived["tokenizerSha256"], self.cert_manifest["tokenizer"]["sha256"])
        self.assertEqual(derived["id"], self.cert_manifest["identity"]["model_id"])
        self.assertEqual(derived["disposition"], "OWNED_CANDIDATE")
        self.assertFalse(derived["admitted"])
        self.assertFalse(derived["creditBearing"])
        # Operational-only fields are kept, not cert-derived.
        self.assertEqual(derived["endpointUrl"], "http://127.0.0.1:8000")

    # Negative 1: cert/seat checkpoint byte mismatch -> REFUSE.
    def test_neg1_checkpoint_bytes_mismatch(self) -> None:
        self.checkpoint_path.write_bytes(b"not the certified checkpoint bytes")
        result = derive_seat_identity(self._seat(), repo_root=REPO_ROOT)
        self._refused(result, "checkpoint bytes != cert checkpoint.byte_sha256")

    # Negative 2: overlapping seat field != cert-derived value -> REFUSE.
    def test_neg2_overlapping_field_mismatch(self) -> None:
        for field, wrong in (
            ("checkpointSha256", "0" * 64),
            ("modelConfigSha256", "1" * 64),
            ("tokenizerSha256", "2" * 64),
            ("id", "some-other-model"),
            ("disposition", "OWNED_ADMITTED"),
        ):
            with self.subTest(field=field):
                result = derive_seat_identity(
                    self._seat(**{field: wrong}), repo_root=REPO_ROOT
                )
                self._refused(result, f"seat.{field} != cert-derived")

    # Negative 3: missing certManifestDigest -> REFUSE.
    def test_neg3_missing_cert_digest(self) -> None:
        seat = self._seat()
        del seat["certManifestDigest"]
        result = derive_seat_identity(seat, repo_root=REPO_ROOT)
        self._refused(result, "missing certManifestDigest")

    # Negative 4: cert manifest mutated after digest pinned -> REFUSE.
    def test_neg4_cert_manifest_mutated(self) -> None:
        seat = self._seat()
        mutated = dict(self.cert_manifest)
        mutated["identity"] = dict(mutated["identity"], model_id="mutated-after-pin")
        Path(seat["certManifestPath"]).write_bytes(
            json.dumps(mutated, indent=2).encode("utf-8")
        )
        result = derive_seat_identity(seat, repo_root=REPO_ROOT)
        self._refused(result, "cert bytes != pinned digest")

    # Negative 5: seat asserting independent identity (own fields, no cert ref) -> REFUSE.
    def test_neg5_independent_seat_identity(self) -> None:
        seat = {
            "checkpointPath": str(self.checkpoint_path),
            "checkpointSha256": self.cert_manifest["checkpoint"]["byte_sha256"],
            "modelConfigSha256": self.cert_manifest["architecture"]["sha256"],
            "tokenizerSha256": self.cert_manifest["tokenizer"]["sha256"],
            "id": self.cert_manifest["identity"]["model_id"],
            "disposition": "OWNED_CANDIDATE",
            "endpointUrl": "http://127.0.0.1:8000",
        }
        result = derive_seat_identity(seat, repo_root=REPO_ROOT)
        self._refused(result, "no cert reference: independent identity authority")

    # Negative 6: selecting/counting the OWNED_CANDIDATE as admitted -> REFUSE.
    def test_neg6_candidate_selected_as_admitted(self) -> None:
        result = derive_seat_identity(self._seat(), repo_root=REPO_ROOT)
        self.assertTrue(result["valid"], f"precondition GREEN failed: {result.get('errors')}")
        with self.assertRaises(PermissionError):
            require_admitted_seat(result["seat"])


class SeatIdentityBridgeShardedCheckpoint(unittest.TestCase):
    """cond3-1038 (state/failure-classes/semantic-validation-without-bytes-2026-07-25.md):
    a SHARDED checkpoint's byte identity is the verified shards, never the
    checkpoint-manifest INDEX JSON's own self-consistency digest. The
    production wiring (cli_seat.py) always passes a sharded checkpoint
    index as checkpointPath (manifest["checkpoint"]["manifest_path"]) --
    this exercises that exact shape directly against the bridge, isolating
    the bridge's own defect from contract.py's separate (and unrelated)
    run-manifest self-consistency check.
    """

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="seat-bridge-sharded-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.cert_manifest = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))
        self.shard_a = self.tmp / "model-00001.safetensors"
        self.shard_a.write_bytes(b"owned-random-init-checkpoint")
        self.shard_b = self.tmp / "expert-vision.safetensors"
        self.shard_b.write_bytes(b"owned-vision-expert-genesis-0")
        self.index_path = self.tmp / "checkpoint-manifest.json"
        self._write_index()

    def _write_index(self) -> None:
        shards = [
            {
                "path": shard.name,
                "sha256": _sha256_bytes(shard.read_bytes()),
                "bytes": shard.stat().st_size,
            }
            for shard in (self.shard_a, self.shard_b)
        ]
        self.index_path.write_text(json.dumps({"shards": shards}, indent=2), encoding="utf-8")

    def _write_cert(self, byte_sha256: str) -> tuple[Path, str]:
        cert = dict(self.cert_manifest)
        cert["checkpoint"] = dict(cert["checkpoint"], byte_sha256=byte_sha256)
        # validate_identity.py cross-checks evaluation.subject_checkpoint_sha256
        # against checkpoint.byte_sha256 (unrelated to the bridge's own Step 5
        # bytes check) -- keep it in sync so Step 2 doesn't refuse for a
        # different reason than the one this test targets.
        cert["evaluation"] = dict(cert["evaluation"], subject_checkpoint_sha256=byte_sha256)
        data = json.dumps(cert, indent=2).encode("utf-8")
        path = self.tmp / "cert-manifest.json"
        path.write_bytes(data)
        return path, _sha256_bytes(data)

    def test_defect_repro_index_digest_as_checkpoint_byte_sha256_then_shard_tampered(self) -> None:
        """THE discriminating test (cond3-1038): cert.checkpoint.byte_sha256 is
        set to the checkpoint-manifest INDEX JSON's own digest -- exactly the
        wrong mapping seat_identity_bridge.py:157-171 shipped with (and what
        tests/test_cli_seat.py:42-46 encoded into its fixture, PR #1038 exact
        head 50f575a). The index JSON is left BYTE-IDENTICAL; ONE shard's
        actual bytes are then changed. The production derive_seat_identity
        call must REFUSE.
        """
        index_digest = hashlib.sha256(self.index_path.read_bytes()).hexdigest()
        cert_path, cert_digest = self._write_cert(index_digest)
        index_bytes_before = self.index_path.read_bytes()

        # Tamper one shard. The index JSON is NOT touched.
        self.shard_a.write_bytes(b"TAMPERED-SHARD-BYTES-not-the-certified-checkpoint")
        self.assertEqual(self.index_path.read_bytes(), index_bytes_before)

        seat = {
            "certManifestPath": str(cert_path),
            "certManifestDigest": cert_digest,
            "checkpointPath": str(self.index_path),
        }
        result = derive_seat_identity(seat, repo_root=REPO_ROOT)
        self.assertFalse(
            result["valid"],
            "derive_seat_identity served a checkpoint with a tampered shard "
            f"while the checkpoint-manifest index stayed byte-identical: {result}",
        )
        self.assertIsNone(result["seat"])

    def test_green_sharded_checkpoint_untampered_verified_against_canonical_aggregate(self) -> None:
        """Over-closure guard: an UNTAMPERED sharded checkpoint, certified
        with the real canonical aggregate identity (resolve_checkpoint_byte_identity),
        must still verify GREEN through Step 5 -- the cure must not false-RED
        real unmodified sharded checkpoints."""
        from seat_identity_bridge import resolve_checkpoint_byte_identity

        canonical, errors = resolve_checkpoint_byte_identity(self.index_path)
        self.assertFalse(errors, errors)
        cert_path, cert_digest = self._write_cert(canonical)
        seat = {
            "certManifestPath": str(cert_path),
            "certManifestDigest": cert_digest,
            "checkpointPath": str(self.index_path),
        }
        result = derive_seat_identity(seat, repo_root=REPO_ROOT)
        self.assertTrue(result["valid"], f"expected GREEN: {result.get('errors')}")
        self.assertEqual(result["seat"]["checkpointSha256"], canonical)


if __name__ == "__main__":
    unittest.main(verbosity=2)
