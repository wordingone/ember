# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Protected evaluation registry v3: the MMMU row binds an evaluator FILE in this repository by content
digest, through the production validator, and the artifacts gate E's corpus identity pins stay byte-identical.

Red/green through the REAL consumer (`text_lab_corpus._protected_identifier_sets`), never a reimplementation:
  green  v3 validates; v2 still validates; the MMMU evaluator digest equals the file's content sha256;
         the custody manifest v2 pre-registers a finite floor strictly inside (0, 1).
  red    a v3 whose MMMU evaluator digest is altered is refused by the validator as an evidence mismatch.
  pins   manifest v1 and registry v2 are unchanged (their digests are consumed by owned-text-lab-corpus-v4
         and the MMMU front unit; a supersession that rewrote them would rewrite the frozen mixture identity).
"""
from __future__ import annotations
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src" / "ember" / "infrastructure" / "tools" / "ember-restart-3b"))

V1_MANIFEST = ROOT / "manifests" / "ember-restart-mmmu-validation-custody-v1.json"
V2_REGISTRY = ROOT / "data" / "ember-restart-3b" / "protected-eval-registry-v2.json"
V3_REGISTRY = ROOT / "data" / "ember-restart-3b" / "protected-eval-registry-v3.json"
V1_MANIFEST_SHA256 = "20af6ef398cd7913ea0ba5b53025dbf568eab6d74f7290d01ceda30c4a206b03"
V2_REGISTRY_SHA256 = "7c370c6c71ce30d4714846c2089220571b44d92d1bc6f745e8b7adf6841312fb"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ProtectedEvalRegistryV3(unittest.TestCase):
    def setUp(self):
        from text_lab_corpus import _protected_identifier_sets
        self.validate = _protected_identifier_sets
        self.v3 = json.loads(V3_REGISTRY.read_bytes())

    def test_pinned_predecessors_unchanged(self):
        self.assertEqual(_sha(V1_MANIFEST), V1_MANIFEST_SHA256)
        self.assertEqual(_sha(V2_REGISTRY), V2_REGISTRY_SHA256)

    def test_v2_and_v3_validate_through_the_production_consumer(self):
        self.validate(ROOT, json.loads(V2_REGISTRY.read_bytes())["protected"])
        sets = self.validate(ROOT, self.v3["protected"])
        self.assertEqual(len(sets["content_sha256"]), 2)
        self.assertEqual(self.v3["schema_version"], "ember-protected-eval-registry-v3")

    def test_mmmu_row_binds_a_repository_file_by_content_digest(self):
        row = next(r for r in self.v3["protected"] if r["benchmark_id"] == "MMMU")
        manifest = json.loads((ROOT / row["custody_manifest_path"]).read_bytes())
        evaluator = manifest["evaluator"]
        self.assertEqual(row["evidence"]["evaluator_sha256"], evaluator["sha256"])
        self.assertEqual(_sha(ROOT / evaluator["path"]), evaluator["sha256"])
        self.assertEqual(evaluator["entrypoint"], "mmmu_cia_evaluation:evaluate")
        self.assertEqual(Path(evaluator["path"]).stem, "mmmu_cia_evaluation")
        self.assertTrue(0.0 < evaluator["floor"] < 1.0)
        self.assertEqual(row["custody_state"], "EXECUTABLE_OWNED_CHECKPOINT")
        self.assertEqual(manifest["admission"], "EXECUTABLE_OWNED_CHECKPOINT")
        self.assertEqual(manifest["supersedes"]["sha256"], V1_MANIFEST_SHA256)
        # the data identity is v1's, unchanged: same split digests, same upstream tree, same license
        v1 = json.loads(V1_MANIFEST.read_bytes())
        for key in ("upstream_tree_git_sha1", "license_sha256"):
            self.assertEqual(manifest[key], v1[key])
        self.assertEqual(manifest["split"], v1["split"])

    def test_red_altered_evaluator_digest_is_refused(self):
        red = json.loads(json.dumps(self.v3))
        row = next(r for r in red["protected"] if r["benchmark_id"] == "MMMU")
        row["evidence"]["evaluator_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "does not match its manifest"):
            self.validate(ROOT, red["protected"])


if __name__ == "__main__":
    unittest.main()


class MmmuEvaluatorCallerBinding(unittest.TestCase):
    """The evaluator the registry binds is CALLED, so the binding and the refusal order are executed facts,
    not read from a docstring (counterpart seat's REDO, 2026-09-21): the protocol document is opened and
    digested before the repository, the checkpoint or any item; an absent protocol refuses in milliseconds.
    """

    def setUp(self):
        import mmmu_cia_evaluation
        self.mod = mmmu_cia_evaluation
        self.registry_row = next(r for r in json.loads(V3_REGISTRY.read_bytes())["protected"]
                                 if r["benchmark_id"] == "MMMU")

    def test_registry_binds_the_manifest_and_the_evaluator_that_is_imported(self):
        manifest_path = ROOT / self.registry_row["custody_manifest_path"]
        self.assertEqual(_sha(manifest_path), self.registry_row["custody_manifest_sha256"])
        manifest = json.loads(manifest_path.read_bytes())
        imported = Path(self.mod.__file__).resolve()
        self.assertEqual(imported, (ROOT / manifest["evaluator"]["path"]).resolve())
        self.assertEqual(_sha(imported), manifest["evaluator"]["sha256"])
        self.assertEqual(manifest["workstream_id"], "EMBER-02B")

    def test_bind_protocol_digests_the_sibling_document(self):
        path, digest = self.mod.bind_protocol()
        self.assertEqual(path, Path(self.mod.__file__).with_name(self.mod.PROTOCOL_NAME + ".md"))
        self.assertEqual(digest, _sha(path))

    def test_bind_protocol_refuses_an_absent_document(self):
        with self.assertRaises(self.mod.ProducerRefusal) as ctx:
            self.mod.bind_protocol(ROOT / "no-such-protocol.md")
        self.assertEqual(ctx.exception.token, "PROTOCOL_ABSENT")

    def _bogus_env(self):
        import os
        from unittest import mock
        env = {name: "not-a-real-value" for name in self.mod.REQUIRED_ENV}
        env["EMBER_REPO_ROOT"] = str(ROOT / "no-such-repository-root")
        env["EMBER_MMMU_THREADS"] = "1"
        return mock.patch.dict(os.environ, env)

    def test_evaluate_refuses_an_absent_protocol_before_the_repository(self):
        from unittest import mock
        with self._bogus_env(), mock.patch.object(self.mod, "PROTOCOL_NAME", "no-such-protocol"):
            with self.assertRaises(self.mod.ProducerRefusal) as ctx:
                self.mod.evaluate(str(ROOT / "no-such-checkpoint"), str(ROOT / "no-such-manifest.json"))
        self.assertEqual(ctx.exception.token, "PROTOCOL_ABSENT")

    def test_evaluate_with_the_protocol_present_refuses_later_on_the_repository(self):
        # Same bogus environment, real protocol: the refusal moves PAST the protocol leg to the repository
        # layout, which proves the order rather than merely that some refusal fires.
        with self._bogus_env():
            with self.assertRaises(self.mod.ProducerRefusal) as ctx:
                self.mod.evaluate(str(ROOT / "no-such-checkpoint"), str(ROOT / "no-such-manifest.json"))
        self.assertEqual(ctx.exception.token, "REPO_LAYOUT")


class MmmuScorerChildInvocation(unittest.TestCase):
    """The scorer child is spawned through the mandatory headless launcher on Windows (mocked subprocess, no
    scorer executed): argv shape, hidden-window flags, no shell, no stdin, and the interpreter pinned to the
    parent's. An absent wrapper refuses instead of falling back to a visible child."""

    def setUp(self):
        import mmmu_cia_evaluation
        self.mod = mmmu_cia_evaluation

    def test_windows_argv_routes_through_the_wrapper_with_the_parent_interpreter(self):
        import os
        import sys
        from unittest import mock
        if os.name != "nt":
            self.skipTest("Windows-only invocation contract")
        argv, env = self.mod.child_python_argv(["-B", "scorer.py", "--x", "1"])
        self.assertEqual(argv[:5], ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-File"])
        self.assertTrue(argv[5].lower().endswith("headless-python.ps1"))
        self.assertEqual(argv[6:], ["--", "-B", "scorer.py", "--x", "1"])
        self.assertEqual(env, {"CODEX_PYTHON": sys.executable})
        with mock.patch.dict(os.environ, {"EMBER_HEADLESS_PYTHON": str(ROOT / "no-such-wrapper.ps1")}):
            with self.assertRaises(self.mod.ProducerRefusal) as ctx:
                self.mod.child_python_argv(["-B", "scorer.py"])
        self.assertEqual(ctx.exception.token, "HEADLESS_WRAPPER_ABSENT")

    def test_score_predictions_spawns_headless_through_the_wrapper(self):
        import os
        import subprocess
        import tempfile
        from unittest import mock
        if os.name != "nt":
            self.skipTest("Windows-only invocation contract")
        seen = {}

        def fake_run(argv, **kw):
            seen["argv"], seen["kw"] = argv, kw
            score_path = Path(argv[argv.index("--score-output") + 1])
            score_path.write_bytes(json.dumps({"metrics": {"accuracy": 0.25}, "sample_count": 847}).encode())
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        answers = {f"q{i}": {"question_type": "multiple-choice", "answer": "A"} for i in range(847)}
        answers["open1"] = {"question_type": "open", "answer": "x"}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            out.mkdir()
            answers_path = Path(tmp) / "answers.json"
            answers_path.write_bytes(json.dumps(answers).encode())
            with mock.patch.object(self.mod.subprocess, "run", side_effect=fake_run):
                result = self.mod.score_predictions(Path(tmp) / "scorer.py", Path(tmp), answers_path, [], out)
        self.assertEqual(result["sample_count"], 847)
        argv, kw = seen["argv"], seen["kw"]
        self.assertEqual(argv[0], "powershell.exe")
        self.assertIn("-File", argv)
        self.assertEqual(argv[argv.index("--") + 1:argv.index("--") + 3], ["-B", str(Path(tmp) / "scorer.py")])
        self.assertIs(kw["shell"], False)
        self.assertIs(kw["stdin"], subprocess.DEVNULL)
        self.assertEqual(kw["creationflags"], subprocess.CREATE_NO_WINDOW)
        self.assertEqual(kw["startupinfo"].wShowWindow, subprocess.SW_HIDE)
        self.assertEqual(kw["env"]["CODEX_PYTHON"], self.mod.sys.executable)
