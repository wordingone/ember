# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Coverage for the #1461 class-kill: the text-lab input-identity re-mint script.

Proves the tool that is supposed to prevent recurrence actually detects and
cures the exact drift #1461 describes (a code_files pin stranded by a source
edit), and that --write touches only the code-hash-derived fields.
"""
from __future__ import annotations
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "ember-restart-3b" / "remint_text_lab_input_identity.py"
IDENTITY_REL = Path("data/ember-restart-3b/owned-text-lab-input-identity-v2.json")
INDEX_REL = Path("data/ember-restart-3b/text-lab-authority-index-v1.json")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RemintTextLabInputIdentityTests(unittest.TestCase):
    def _sandbox(self, tmp: Path) -> Path:
        root = tmp / "repo"
        shutil.copytree(ROOT / "data", root / "data")
        shutil.copytree(ROOT / "tools", root / "tools")
        return root

    def test_check_passes_on_the_checked_in_pristine_tree(self):
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--check"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("all code_files pins match live bytes", result.stdout)

    def test_check_fails_for_each_pinned_module_when_edited(self):
        pinned = {
            "run_vertical_slice": "run_vertical_slice.py",
            "text_lab_corpus": "text_lab_corpus.py",
            "train": "train.py",
        }
        for name, filename in pinned.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = self._sandbox(Path(tmp))
                module = root / "tools/ember-restart-3b" / filename
                module.write_bytes(module.read_bytes() + b"\n# drift injected by test\n")
                check = subprocess.run(
                    [sys.executable, "-B", str(root / "tools/ember-restart-3b/remint_text_lab_input_identity.py"), "--check"],
                    cwd=root, capture_output=True, text=True,
                )
                self.assertEqual(check.returncode, 1)
                self.assertIn("STALE PIN", check.stdout)
                self.assertIn(name, check.stdout)

    def test_check_rejects_unknown_or_missing_code_file_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._sandbox(Path(tmp))
            identity_path = root / IDENTITY_REL
            identity = json.loads(identity_path.read_bytes())
            identity["code_files"]["unexpected"] = "0" * 64
            identity_path.write_bytes(json.dumps(identity).encode("utf-8"))
            check = subprocess.run(
                [sys.executable, "-B", str(root / "tools/ember-restart-3b/remint_text_lab_input_identity.py"), "--check"],
                cwd=root, capture_output=True, text=True,
            )
            self.assertEqual(check.returncode, 2)
            self.assertIn("closed schema", check.stdout)

    def test_check_rejects_a_stale_downstream_index_pin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._sandbox(Path(tmp))
            index_path = root / INDEX_REL
            index = json.loads(index_path.read_bytes())
            index["input_identity"]["sha256"] = "0" * 64
            index_path.write_bytes(json.dumps(index).encode("utf-8"))
            check = subprocess.run(
                [sys.executable, "-B", str(root / "tools/ember-restart-3b/remint_text_lab_input_identity.py"), "--check"],
                cwd=root, capture_output=True, text=True,
            )
            self.assertEqual(check.returncode, 1)
            self.assertIn("authority-index-v1", check.stdout)

    def test_write_cures_the_drift_and_check_then_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._sandbox(Path(tmp))
            module = root / "tools/ember-restart-3b/run_vertical_slice.py"
            module.write_bytes(module.read_bytes() + b"\n# drift injected by test\n")
            script = root / "tools/ember-restart-3b/remint_text_lab_input_identity.py"
            write = subprocess.run(
                [sys.executable, "-B", str(script), "--write"],
                cwd=root, capture_output=True, text=True,
            )
            self.assertEqual(write.returncode, 0, write.stdout + write.stderr)
            check = subprocess.run(
                [sys.executable, "-B", str(script), "--check"],
                cwd=root, capture_output=True, text=True,
            )
            self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

    def test_write_touches_only_code_hash_derived_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._sandbox(Path(tmp))
            identity_path = root / IDENTITY_REL
            index_path = root / INDEX_REL
            before_identity = json.loads(identity_path.read_bytes())
            before_index = json.loads(index_path.read_bytes())

            module = root / "tools/ember-restart-3b/run_vertical_slice.py"
            module.write_bytes(module.read_bytes() + b"\n# drift injected by test\n")
            new_hash = sha(module.read_bytes())

            script = root / "tools/ember-restart-3b/remint_text_lab_input_identity.py"
            subprocess.run([sys.executable, "-B", str(script), "--write"], cwd=root, check=True, capture_output=True)

            after_identity = json.loads(identity_path.read_bytes())
            after_index = json.loads(index_path.read_bytes())

            for key in ("corpus_sha256", "schema_version", "source_base_commit"):
                self.assertEqual(after_identity[key], before_identity[key])
            self.assertEqual(after_identity["code_files"]["run_vertical_slice"], new_hash)
            self.assertEqual(after_identity["code_files"]["text_lab_corpus"], before_identity["code_files"]["text_lab_corpus"])
            self.assertEqual(after_identity["code_files"]["train"], before_identity["code_files"]["train"])

            for key in before_index:
                if key == "input_identity":
                    continue
                self.assertEqual(after_index[key], before_index[key])
            self.assertEqual(after_index["input_identity"]["path"], before_index["input_identity"]["path"])
            self.assertEqual(after_index["input_identity"]["schema"], before_index["input_identity"]["schema"])
            self.assertNotEqual(after_index["input_identity"]["sha256"], before_index["input_identity"]["sha256"])

    def test_write_is_a_no_op_when_already_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._sandbox(Path(tmp))
            script = root / "tools/ember-restart-3b/remint_text_lab_input_identity.py"
            identity_path = root / IDENTITY_REL
            before = identity_path.read_bytes()
            result = subprocess.run(
                [sys.executable, "-B", str(script), "--write"],
                cwd=root, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn("already fresh", result.stdout)
            self.assertEqual(identity_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
