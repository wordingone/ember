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

import torch

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = (
    REPO_ROOT / "tools" / "ember-cli" / "src" / "commands" / "__fixtures__" / "model-identity"
)
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "ember_01_identity"))

# issue2015 exact-local-import:src/ember/governance/scripts/ember_restart/seat_identity_bridge.py
import importlib.util as _ember_26b6c24e1679e1f8_importlib
import sys as _ember_26b6c24e1679e1f8_sys
from pathlib import Path as _ember_26b6c24e1679e1f8_Path
_ember_26b6c24e1679e1f8_path = _ember_26b6c24e1679e1f8_Path(__file__).resolve().parents[2].joinpath('src', 'ember', 'governance', 'scripts', 'ember_restart', 'seat_identity_bridge.py')
if not _ember_26b6c24e1679e1f8_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_restart/seat_identity_bridge.py')
_ember_26b6c24e1679e1f8_aliases = ('_ember_issue2015_26b6c24e1679e1f8', 'scripts.ember_restart.seat_identity_bridge', 'seat_identity_bridge')
_ember_26b6c24e1679e1f8_existing = []
for _ember_26b6c24e1679e1f8_alias in _ember_26b6c24e1679e1f8_aliases:
    _ember_26b6c24e1679e1f8_candidate = _ember_26b6c24e1679e1f8_sys.modules.get(_ember_26b6c24e1679e1f8_alias)
    if _ember_26b6c24e1679e1f8_candidate is not None and all(_ember_26b6c24e1679e1f8_candidate is not item for item in _ember_26b6c24e1679e1f8_existing):
        _ember_26b6c24e1679e1f8_existing.append(_ember_26b6c24e1679e1f8_candidate)
if len(_ember_26b6c24e1679e1f8_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_restart/seat_identity_bridge.py')
if _ember_26b6c24e1679e1f8_existing:
    _ember_26b6c24e1679e1f8_module = _ember_26b6c24e1679e1f8_existing[0]
    _ember_26b6c24e1679e1f8_observed = getattr(_ember_26b6c24e1679e1f8_module, '__file__', None)
    if _ember_26b6c24e1679e1f8_observed is None or _ember_26b6c24e1679e1f8_Path(_ember_26b6c24e1679e1f8_observed).resolve() != _ember_26b6c24e1679e1f8_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_restart/seat_identity_bridge.py')
else:
    _ember_26b6c24e1679e1f8_spec = _ember_26b6c24e1679e1f8_importlib.spec_from_file_location('_ember_issue2015_26b6c24e1679e1f8', _ember_26b6c24e1679e1f8_path)
    if _ember_26b6c24e1679e1f8_spec is None or _ember_26b6c24e1679e1f8_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_restart/seat_identity_bridge.py')
    _ember_26b6c24e1679e1f8_module = _ember_26b6c24e1679e1f8_importlib.module_from_spec(_ember_26b6c24e1679e1f8_spec)
    for _ember_26b6c24e1679e1f8_alias in _ember_26b6c24e1679e1f8_aliases:
        _ember_26b6c24e1679e1f8_prior = _ember_26b6c24e1679e1f8_sys.modules.get(_ember_26b6c24e1679e1f8_alias)
        if _ember_26b6c24e1679e1f8_prior is not None and _ember_26b6c24e1679e1f8_prior is not _ember_26b6c24e1679e1f8_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_restart/seat_identity_bridge.py')
        _ember_26b6c24e1679e1f8_sys.modules[_ember_26b6c24e1679e1f8_alias] = _ember_26b6c24e1679e1f8_module
    try:
        _ember_26b6c24e1679e1f8_spec.loader.exec_module(_ember_26b6c24e1679e1f8_module)
    except BaseException:
        for _ember_26b6c24e1679e1f8_alias in _ember_26b6c24e1679e1f8_aliases:
            if _ember_26b6c24e1679e1f8_sys.modules.get(_ember_26b6c24e1679e1f8_alias) is _ember_26b6c24e1679e1f8_module:
                _ember_26b6c24e1679e1f8_sys.modules.pop(_ember_26b6c24e1679e1f8_alias, None)
        raise
for _ember_26b6c24e1679e1f8_alias in _ember_26b6c24e1679e1f8_aliases:
    _ember_26b6c24e1679e1f8_prior = _ember_26b6c24e1679e1f8_sys.modules.get(_ember_26b6c24e1679e1f8_alias)
    if _ember_26b6c24e1679e1f8_prior is not None and _ember_26b6c24e1679e1f8_prior is not _ember_26b6c24e1679e1f8_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_restart/seat_identity_bridge.py')
    _ember_26b6c24e1679e1f8_sys.modules[_ember_26b6c24e1679e1f8_alias] = _ember_26b6c24e1679e1f8_module
derive_seat_identity = getattr(_ember_26b6c24e1679e1f8_module, 'derive_seat_identity')
require_admitted_seat = getattr(_ember_26b6c24e1679e1f8_module, 'require_admitted_seat')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_restart/seat_identity_bridge.py
from checkpoint_save_load_identity_binding import measure_checkpoint_identity


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class SeatIdentityBridgeNegatives(unittest.TestCase):
    """The 6 required negatives + the GREEN derivation path.

    Rework (2026-07-25): the checked-in ``model-identity`` fixture's
    ``checkpoint`` object is a hand-typed ``synthetic-bytes-v1`` placeholder
    (``byte_sha256`` = sha256 of an unrelated Python source file's raw bytes)
    -- exactly the shape this rework's bridge now refuses (no raw-file
    fallback, no format the trusted counter cannot measure). Rather than edit
    that SHARED fixture (consumed by the TypeScript /model command tests
    too, out of this rework's scope), this suite overrides only the
    ``checkpoint``/``evaluation.subject_checkpoint_sha256`` fields with a
    genuinely-measured single real checkpoint shard -- the same pattern
    ``tests/ember_restart/test_cli_seat.py::_matching_cert`` already uses for
    the production-path suite. Every other field (identity/tokenizer/
    architecture/data/...) is the real, unmodified checked-in fixture.
    """

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="seat-bridge-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.manifest_src = FIXTURE_DIR / "manifest.json"
        self.cert_manifest = json.loads(self.manifest_src.read_text(encoding="utf-8"))

        # A REAL checkpoint shard (not the shared fixture's synthetic-bytes
        # placeholder), measured via the same trusted-counter producer the
        # cured bridge itself calls -- never resolve_checkpoint_byte_identity
        # (the function under test).
        self.shard_path = self.tmp / "model-shard.pt"
        torch.save({"model": {"fixture.weight": torch.zeros((2, 2), dtype=torch.float32)}}, self.shard_path)
        measured = measure_checkpoint_identity(self.shard_path)
        self.cert_manifest["checkpoint"] = {
            "format": "ember-checkpoint-envelope-v1",
            "byte_sha256": measured["checkpoint_byte_sha256"],
            "tensors": measured["tensors"],
            "ancestry": [
                {"checkpoint_sha256": "c" * 64, "relationship": "clean_genesis_parent"}
            ],
            "recovery_state": "CLEAN",
        }
        self.cert_manifest["evaluation"]["subject_checkpoint_sha256"] = measured[
            "checkpoint_byte_sha256"
        ]

        self.index_path = self.tmp / "checkpoint-manifest.json"
        self.index_path.write_text(
            json.dumps({"shards": [{"path": self.shard_path.name}]}, indent=2),
            encoding="utf-8",
        )
        self.checkpoint_path = self.index_path

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
            "checkpointRoot": str(self.tmp),
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

    def test_missing_shard_refused_naming_the_path(self) -> None:
        """Acceptance item 2 (cond3-1038-rework-2026-07-25): a single-shard
        checkpoint index naming a shard that is not actually present on disk
        is REFUSED, naming the missing path -- not a silent pass, not a
        generic error. This is the bridge's OWN missing-shard handling
        (_resolve_checkpoint_envelope -> measure_checkpoint_identity ->
        CheckpointSaveLoadIdentityMismatch), reached directly here because
        contract.py's mandatory architecture.expert_banks requirement
        (exactly vision/audio/reasoning/tool) means no manifest that can
        pass Stage 1 admission is ever single-shard, so this exact code path
        is not reachable through cli_seat.py for a real manifest -- see
        tests/ember_restart/test_missing_shard_refused_through_production_
        path_naming_the_path (contract.py's OWN, separate missing-shard
        check, which IS reachable there)."""
        self.shard_path.unlink()
        result = derive_seat_identity(self._seat(), repo_root=REPO_ROOT)
        self._refused(result, "missing shard file")
        # Path casing may be OS-normalized by .resolve() inside the bridge
        # (observed: the temp-dir allocator's uppercase drive/segment casing
        # differs from the resolved mixed-case form) -- match on the
        # shard's own filename, case-insensitively, plus the failure
        # phrase, rather than an exact-cased full-path substring.
        self.assertTrue(
            any(
                self.shard_path.name.lower() in error.lower() and "failed measurement" in error
                for error in result["errors"]
            ),
            result["errors"],
        )

    # Negative 1: cert/seat checkpoint byte mismatch -> REFUSE.
    def test_neg1_checkpoint_bytes_mismatch(self) -> None:
        # Tamper the real SHARD's tensor content, not the index -- the index
        # still names a real, readable checkpoint (a shape refusal would
        # prove nothing about this negative's actual target: measured bytes
        # diverging from the cert's declared checkpoint.byte_sha256).
        torch.save({"model": {"fixture.weight": torch.ones((2, 2), dtype=torch.float32)}}, self.shard_path)
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
    a checkpoint's byte identity is the verified, measured shard, never the
    checkpoint-manifest INDEX JSON's own self-consistency digest and never an
    aggregate invented inside the bridge. The production wiring (cli_seat.py)
    always passes a checkpoint index as checkpointPath
    (manifest["checkpoint"]["manifest_path"]) -- this exercises that exact
    shape directly against the bridge, isolating the bridge's own defect from
    contract.py's separate (and unrelated) run-manifest self-consistency
    check.
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
        """cond3-1038: cert.checkpoint.byte_sha256 is set to the
        checkpoint-manifest INDEX JSON's own digest -- exactly the wrong
        mapping PR #1038 shipped with at exact head 50f575a. The index JSON
        is left BYTE-IDENTICAL; ONE shard's actual bytes are then changed.
        The production derive_seat_identity call must REFUSE.

        Rework note (2026-07-25): this fixture's checkpointPath names TWO
        shards. Post-rework, that shape is refused outright (the schema has
        no multi-shard aggregate identity -- see the schema-gap tests below)
        BEFORE the bridge would ever reach a tamper check, so this test now
        passes for the shape-refusal reason, not the (retired) aggregate
        formula's digest mismatch. It is kept because it still proves a real
        invariant -- this exact historical defect shape is refused -- and
        the single-shard boundary's own tamper RED is exercised separately
        (test_neg1_checkpoint_bytes_mismatch above).
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

    def test_multi_shard_index_refused_as_schema_gap_not_invented_aggregate(self) -> None:
        """The hard boundary (rework 2026-07-25): a checkpoint index naming
        MORE than one shard is refused outright, naming the schema gap --
        never silently aggregated via a bridge-invented formula. This is the
        permanent regression for round 2's own defect: its
        ``path:sha256``-lines aggregate appeared nowhere else in the tree and
        made every legitimately-signed cert (which never used that formula)
        refuse for the SAME wrong reason as a genuinely tampered one, so this
        test also proves the untampered-but-multi-shard case is now refused
        for an HONEST, precise reason rather than an accidental one."""
        cert_path, cert_digest = self._write_cert("0" * 64)
        seat = {
            "certManifestPath": str(cert_path),
            "certManifestDigest": cert_digest,
            "checkpointPath": str(self.index_path),
        }
        result = derive_seat_identity(seat, repo_root=REPO_ROOT)
        self.assertFalse(result["valid"])
        self.assertIsNone(result["seat"])
        self.assertTrue(
            any("schema/contract gap" in error for error in result["errors"]),
            result["errors"],
        )

    def test_hostile_artifact_probe_non_checkpoint_blob_with_matching_declared_hash(self) -> None:
        """MANDATORY (acceptance item 3): the exact probe that parked both
        round-2 cures (#1038 and #1039). A single-shard index names a 3-byte
        non-checkpoint file whose sha256 the cert declares as
        checkpoint.byte_sha256. Must REFUSE. Round 2's singular branch
        (selected by sniffing the artifact's own bytes) hashed this file
        raw and admitted it -- served digest
        3608bca1e44ea6c4d268eb6db02260269892c0b42b86bbf1e77a6fa16c3c9282,
        identical to what parked #1039's round 1. Here there is no singular
        branch left to select: the shard is read only through the trusted
        counter's safe checkpoint reader, which cannot open a 3-byte file as
        a checkpoint archive at all."""
        blob = b"xyz"
        blob_path = self.tmp / "hostile.bin"
        blob_path.write_bytes(blob)
        index_path = self.tmp / "hostile-index.json"
        index_path.write_text(
            json.dumps({"shards": [{"path": blob_path.name}]}, indent=2), encoding="utf-8"
        )
        forged_sha256 = hashlib.sha256(blob).hexdigest()
        self.assertEqual(
            forged_sha256,
            "3608bca1e44ea6c4d268eb6db02260269892c0b42b86bbf1e77a6fa16c3c9282",
            "sanity: this must be the exact digest that parked round 2",
        )
        cert_path, cert_digest = self._write_cert(forged_sha256)
        seat = {
            "certManifestPath": str(cert_path),
            "certManifestDigest": cert_digest,
            "checkpointPath": str(index_path),
        }
        result = derive_seat_identity(seat, repo_root=REPO_ROOT)
        self.assertFalse(
            result["valid"],
            f"hostile-artifact probe was ADMITTED (the exact defect that parked round 2): {result}",
        )
        self.assertIsNone(result["seat"])

    # Retired (rework 2026-07-25): test_green_sharded_checkpoint_untampered_
    # verified_against_canonical_aggregate tested round 2's own invented
    # aggregate (resolve_checkpoint_byte_identity building its expected value
    # from itself -- the function under test, rule 4) and is superseded by
    # test_multi_shard_index_refused_as_schema_gap_not_invented_aggregate
    # above. The single-shard over-closure GREEN required by acceptance item
    # 4 lives in SeatIdentityBridgeNegatives.test_green_derivation_from_cert
    # (this file) -- it builds its expected checkpoint identity via
    # measure_checkpoint_identity, the trusted producer, never via the
    # bridge function under test. There is no equivalent GREEN reachable
    # through tests/ember_restart/test_cli_seat.py's real end-to-end
    # cli_seat.py production path: contract.py's mandatory
    # architecture.expert_banks requirement (exactly vision/audio/
    # reasoning/tool) means every manifest that can pass Stage 1 admission
    # is multi-shard, and this rework's bridge refuses every multi-shard
    # checkpoint -- so no manifest currently reaches a served OWNED seat
    # through cli_seat.py at all. See the rework report's ruling-request
    # section; no producer is reachable for that scenario, so it is
    # documented rather than forced.


if __name__ == "__main__":
    unittest.main(verbosity=2)
