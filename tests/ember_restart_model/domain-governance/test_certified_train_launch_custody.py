# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Issue #1721: certified_train_launch.py's resume-checkpoint preflight
(``_validate_resume_request``) must fail closed on unverified custody and pass
once the real ``ember-lab custody-verify`` CLI reports the shard bytes as
registered and verified.

Real end-to-end, no mocking of the mechanism under test: a real subprocess call
to the real compiled ``runtime/ember-lab/target/{release,debug}/ember-lab.exe``,
a real sqlite catalog, real shard bytes on disk. The only thing pinned is WHERE
the gate looks for the binary/catalog -- the fixture ``repo_root`` below is a
bare tempdir with no Cargo build or catalog of its own, so
``canonical_ember_lab_binary``/``default_catalog_db`` are redirected at the real
repository's build output and an isolated per-test database. ``custody_verify``,
``checkpoint_manifest_hashes``, ``CustodyRefused``, and ``RESUME_CHECKPOINT_VOLUME``
are the untouched real implementations from ``scripts/artifact_custody_gate.py``.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b" / "certified_train_launch.py"
GATE_MODULE_PATH = ROOT / "src" / "ember" / "governance" / "scripts" / "artifact_custody_gate.py"
ARCHITECTURE_REVISION = "ember-sparse-3b-v2"


def load_module():
    spec = importlib.util.spec_from_file_location(
        "certified_train_launch_custody_under_test", MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_gate_module():
    spec = importlib.util.spec_from_file_location(
        "artifact_custody_gate_under_test", GATE_MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_json(path: pathlib.Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class ResumeCheckpointCustodyGateTests(unittest.TestCase):
    """Exercises the real ``_validate_resume_request`` custody wiring
    end-to-end: an unregistered shard refuses naming custody; the same shard
    registered via the real ``ember-lab register-artifact`` CLI makes the same,
    unmodified preflight call pass."""

    def setUp(self) -> None:
        self.module = load_module()
        gate = load_gate_module()
        real_binary = gate.canonical_ember_lab_binary(ROOT)
        if real_binary is None:
            self.skipTest(
                "no built ember-lab binary under runtime/ember-lab/target/"
                "{release,debug}/ember-lab.exe; build it before running this test"
            )
        self._tmp = tempfile.TemporaryDirectory(dir="B:/tmp")
        self.addCleanup(self._tmp.cleanup)
        self.tmp_root = pathlib.Path(self._tmp.name)
        self.db_path = self.tmp_root / "custody-gate-test.sqlite3"
        # Point the gate at the REAL compiled binary but an ISOLATED per-test
        # sqlite catalog -- this fixture's repo_root has no real Cargo build or
        # catalog of its own, and this test must never touch the production
        # state/ember-lab-catalog.sqlite3.
        gate.canonical_ember_lab_binary = lambda _repo_root: real_binary
        gate.default_catalog_db = lambda _repo_root: self.db_path
        self.module.load_artifact_custody_gate_module = lambda: gate
        self.gate = gate
        self.ember_lab_binary = real_binary

    def _write_checkpoint(self) -> tuple[pathlib.Path, dict]:
        checkpoint = self.tmp_root / "checkpoint-000100"
        checkpoint.mkdir(parents=True)
        shard_bytes = b"real resume-checkpoint gate test shard bytes, issue #1721"
        shard_path = checkpoint / "shard.bin"
        shard_path.write_bytes(shard_bytes)
        shard_sha256 = hashlib.sha256(shard_bytes).hexdigest()
        manifest = {
            "architecture_revision": ARCHITECTURE_REVISION,
            "global_step": 100,
            "shards": [
                {
                    "path": "shard.bin",
                    "bytes": len(shard_bytes),
                    "sha256": shard_sha256,
                }
            ],
        }
        write_json(checkpoint / "checkpoint-manifest.json", manifest)
        return checkpoint, manifest

    def test_refuses_unregistered_shard_then_passes_after_real_backfill_registration(
        self,
    ) -> None:
        module = self.module
        checkpoint, manifest = self._write_checkpoint()
        evidence = self.tmp_root / "evidence.json"
        write_json(evidence, {"ok": True})
        repo_root = self.tmp_root / "repo"
        write_json(
            repo_root / "configs" / "ember-restart-3b.json",
            {"architecture_revision": ARCHITECTURE_REVISION},
        )

        run_spec = {
            "resume_checkpoint": str(checkpoint),
            "resume_counter_receipt": str(evidence),
        }
        run_spec_path = self.tmp_root / "run-spec.json"
        write_json(run_spec_path, run_spec)
        allowed_roots = [self.tmp_root.resolve()]

        # Pass 1: the shard was never registered -- the preflight must refuse,
        # and the refusal must name custody verification, not some other check.
        with self.assertRaisesRegex(ValueError, "custody verification"):
            module._validate_resume_request(
                run_spec, run_spec_path, repo_root, allowed_roots, None
            )

        # Backfill: register the real shard bytes at their real location,
        # through the real CLI -- exactly the shape the issue's acceptance
        # criterion names ("both executed on this host").
        shard = manifest["shards"][0]
        registration = subprocess.run(
            [
                str(self.ember_lab_binary),
                "register-artifact",
                "--db",
                str(self.db_path),
                "--sha256",
                shard["sha256"],
                "--byte-count",
                str(shard["bytes"]),
                "--media-type",
                "application/octet-stream",
                "--location",
                f"{self.gate.RESUME_CHECKPOINT_VOLUME}=shard.bin",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(registration.returncode, 0, registration.stderr)

        # Pass 2: the exact same preflight call, unmodified, now resolves and
        # passes -- the real ResumeRequest is returned, not a stubbed result.
        result = module._validate_resume_request(
            run_spec, run_spec_path, repo_root, allowed_roots, None
        )
        self.assertEqual(result.checkpoint, checkpoint)

    def test_manifest_without_shards_key_skips_custody_and_still_passes(self) -> None:
        """A manifest carrying no shard-hash contract (the legacy/synthetic
        shape the rest of this file's test suite uses) has nothing this gate
        can verify and must not newly refuse a resume that every other check
        already accepts."""
        module = self.module
        checkpoint = self.tmp_root / "checkpoint-legacy"
        checkpoint.mkdir(parents=True)
        write_json(
            checkpoint / "checkpoint-manifest.json",
            {"architecture_revision": ARCHITECTURE_REVISION, "global_step": 100},
        )
        evidence = self.tmp_root / "evidence-legacy.json"
        write_json(evidence, {"ok": True})
        repo_root = self.tmp_root / "repo-legacy"
        write_json(
            repo_root / "configs" / "ember-restart-3b.json",
            {"architecture_revision": ARCHITECTURE_REVISION},
        )
        run_spec = {
            "resume_checkpoint": str(checkpoint),
            "resume_counter_receipt": str(evidence),
        }
        run_spec_path = self.tmp_root / "run-spec-legacy.json"
        write_json(run_spec_path, run_spec)
        allowed_roots = [self.tmp_root.resolve()]

        result = module._validate_resume_request(
            run_spec, run_spec_path, repo_root, allowed_roots, None
        )
        self.assertEqual(result.checkpoint, checkpoint)


if __name__ == "__main__":
    unittest.main()
