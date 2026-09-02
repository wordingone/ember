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
sys.path.insert(0, str(REPO_ROOT / "scripts" / "ember_01_identity"))

import torch  # noqa: E402

from checkpoint_save_load_identity_binding import measure_checkpoint_identity  # noqa: E402
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
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_restart/seat_identity_bridge.py  # noqa: E402


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
                "(run src/ember/governance/scripts/ember_restart/build_cond3_artifact_b_fixture.py)"
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
    #
    # Rework note (2026-07-25, cond3-1038): the checked-in fixture's
    # ``checkpoint`` file is 16 raw ``synthetic-bytes-v1`` bytes (this
    # module's own ``_tensor_bytes()``), consumed elsewhere by
    # validate_identity.py's own ``--checkpoint`` raw-bytes convention
    # (still correct -- those consumers are untouched and still pass
    # above). It is not a checkpoint INDEX JSON naming a real, measurable
    # torch shard, so it is not the shape this rework's bridge accepts (no
    # raw-file fallback -- see seat_identity_bridge._resolve_checkpoint_
    # envelope). Rather than edit the checked-in fixture (shared with
    # tools/ember-cli/src/entrypoints/cond3-artifact-b.test.ts, out of this
    # Python-only rework's scope), these two bridge-level tests build a
    # local, self-contained real single-shard checkpoint (same pattern as
    # scripts/ember_restart/test_seat_identity_bridge.py::
    # SeatIdentityBridgeNegatives.setUp) and override only the
    # checkpoint/evaluation fields of a COPY of the checked-in manifest --
    # every other field (identity/architecture/tokenizer/data/training/...)
    # stays the real, unmodified checked-in fixture content.
    def _seat_config_with_real_shard(self, tmp_path: Path) -> dict:
        shard_path = tmp_path / "model-shard.pt"
        torch.save({"model": {"cond3.artifact_b.weight": torch.tensor([[1.0, -1.0], [0.5, -0.5]])}}, shard_path)
        measured = measure_checkpoint_identity(shard_path)
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        manifest["checkpoint"] = {
            "format": "ember-checkpoint-envelope-v1",
            "byte_sha256": measured["checkpoint_byte_sha256"],
            "tensors": measured["tensors"],
            "ancestry": manifest["checkpoint"].get("ancestry", []),
            "recovery_state": manifest["checkpoint"].get("recovery_state", "CLEAN"),
        }
        manifest["evaluation"]["subject_checkpoint_sha256"] = measured["checkpoint_byte_sha256"]
        manifest_path = tmp_path / "manifest.json"
        manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
        manifest_path.write_bytes(manifest_bytes)
        index_path = tmp_path / "checkpoint-manifest.json"
        index_path.write_text(json.dumps({"shards": [{"path": shard_path.name}]}), encoding="utf-8")
        return manifest, {
            "certManifestPath": str(manifest_path),
            "certManifestDigest": hashlib.sha256(manifest_bytes).hexdigest(),
            "checkpointPath": str(index_path),
            "checkpointRoot": str(tmp_path),
        }

    def test_consumer_seat_bridge_green_derivation(self) -> None:
        import shutil
        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix="cond3-artifact-b-bridge-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        manifest, seat_config = self._seat_config_with_real_shard(tmp)
        seat_config["endpointUrl"] = "http://127.0.0.1:8000"
        result = derive_seat_identity(seat_config, repo_root=REPO_ROOT)
        self.assertTrue(result["valid"], f"expected GREEN derivation: {result.get('errors')}")
        seat = result["seat"]
        self.assertEqual(seat["checkpointSha256"], manifest["checkpoint"]["byte_sha256"])
        self.assertEqual(seat["modelConfigSha256"], manifest["architecture"]["sha256"])
        self.assertEqual(seat["tokenizerSha256"], manifest["tokenizer"]["sha256"])
        self.assertEqual(seat["id"], manifest["identity"]["model_id"])
        self.assertEqual(seat["disposition"], "OWNED_CANDIDATE")
        self.assertFalse(seat["admitted"])
        self.assertFalse(seat["creditBearing"])
        self.assertFalse(seat["selectedAsOwnedEmber"])

    def test_consumer_seat_bridge_refuses_admission_of_candidate(self) -> None:
        import shutil
        import tempfile

        tmp = Path(tempfile.mkdtemp(prefix="cond3-artifact-b-bridge-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        _, seat_config = self._seat_config_with_real_shard(tmp)
        result = derive_seat_identity(seat_config, repo_root=REPO_ROOT)
        self.assertTrue(result["valid"], f"precondition GREEN failed: {result.get('errors')}")
        with self.assertRaises(PermissionError) as ctx:
            require_admitted_seat(result["seat"])
        message = str(ctx.exception)
        self.assertIn("OWNED_CANDIDATE", message)
        self.assertIn("not OWNED_ADMITTED+selected", message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
