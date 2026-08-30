# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

"""The per-workstream training-closure supplement: parity, merge, refusals.

The base manifest is EMBER-02A guard metadata; a workstream whose code joins
the closure declares its members in a supplement file inside its own path
scope. Absent supplement must be byte-for-byte legacy behavior; a present but
invalid supplement must refuse, never be ignored; merged members join the
declared set, the audit, and the closure hash; and the supplement declares
itself so editing it moves the hash.
"""

import importlib.util
import json
import pathlib
import shutil
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
CLOSURE_MODULE_PATH = ROOT / "scripts" / "training_closure.py"
MANIFEST_RELATIVE_PATH = "manifests/training-dependency-closure.json"
SUPPLEMENT_RELATIVE_PATH = (
    "tools/ember-restart-3b/training-dependency-closure-supplement.json"
)


def load_closure():
    specification = importlib.util.spec_from_file_location(
        "training_closure_supplement_under_test", CLOSURE_MODULE_PATH
    )
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def write_text(path: pathlib.Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def build_sandbox_repo(root: pathlib.Path) -> pathlib.Path:
    repo = root / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copyfile(CLOSURE_MODULE_PATH, repo / "scripts" / "training_closure.py")
    write_text(repo / "tools" / "entrypoint.py", "import json\n")
    write_text(repo / "configs" / "training.json", '{"steps": 1}\n')
    write_text(
        repo / MANIFEST_RELATIVE_PATH,
        json.dumps(
            {
                "schema_version": "ember-training-dependency-closure-v1",
                "entrypoints": ["tools/entrypoint.py"],
                "dynamic_entrypoints": [],
                "code": ["scripts/training_closure.py"],
                "data": ["configs/training.json"],
                "dynamic_call_sites": {},
                "dynamic_call_site_notes": {},
            },
            indent=2,
        )
        + "\n",
    )
    return repo


def write_supplement(repo: pathlib.Path, document: dict) -> None:
    write_text(repo / SUPPLEMENT_RELATIVE_PATH, json.dumps(document, indent=2) + "\n")


def minimal_supplement(**overrides) -> dict:
    document = {
        "schema_version": "ember-training-dependency-closure-supplement-v1",
        "goal_id": "EMBER-02",
        "workstream_id": "EMBER-02B",
        "next_executed_outcome": (
            "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
        ),
        "entrypoints": [],
        "dynamic_entrypoints": [],
        "code": [],
        "data": [],
        "dynamic_call_sites": {},
        "dynamic_call_site_notes": {},
    }
    document.update(overrides)
    return document


class TrainingClosureSupplementTests(unittest.TestCase):
    def test_absent_supplement_is_exactly_legacy_behavior(self) -> None:
        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(pathlib.Path(directory))
            manifest = closure.load_manifest(repo)
            declared = closure.declared_paths(manifest)
            self.assertNotIn(SUPPLEMENT_RELATIVE_PATH, declared)
            audit = closure.audit_closure(repo, manifest)
            self.assertTrue(audit.ok, audit.failure_report())

    def test_supplement_members_join_declaration_audit_and_hash(self) -> None:
        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(pathlib.Path(directory))
            write_text(repo / "tools" / "member.py", "VALUE = 1\n")
            write_supplement(repo, minimal_supplement(code=["tools/member.py"]))
            manifest = closure.load_manifest(repo)
            declared = closure.declared_paths(manifest)
            self.assertIn("tools/member.py", declared)
            self.assertIn(SUPPLEMENT_RELATIVE_PATH, declared)
            audit = closure.audit_closure(repo, manifest)
            self.assertTrue(audit.ok, audit.failure_report())
            before = closure.compute_closure_hash(repo, manifest)
            write_text(repo / "tools" / "member.py", "VALUE = 2\n")
            after = closure.compute_closure_hash(repo, closure.load_manifest(repo))
            self.assertNotEqual(before, after)

    def test_editing_the_supplement_moves_the_closure_hash(self) -> None:
        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(pathlib.Path(directory))
            write_text(repo / "tools" / "member.py", "VALUE = 1\n")
            write_supplement(repo, minimal_supplement(code=["tools/member.py"]))
            before = closure.compute_closure_hash(repo)
            write_supplement(
                repo,
                minimal_supplement(
                    code=["tools/member.py"], purpose="edited declaration"
                ),
            )
            self.assertNotEqual(before, closure.compute_closure_hash(repo))

    def test_declared_supplement_member_must_exist(self) -> None:
        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(pathlib.Path(directory))
            write_supplement(repo, minimal_supplement(code=["tools/ghost.py"]))
            audit = closure.audit_closure(repo)
            self.assertFalse(audit.ok)
            self.assertIn("tools/ghost.py", audit.missing)

    def test_supplement_redeclaring_a_manifest_member_refuses(self) -> None:
        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(pathlib.Path(directory))
            write_supplement(
                repo, minimal_supplement(code=["scripts/training_closure.py"])
            )
            with self.assertRaisesRegex(ValueError, "re-declares a"):
                closure.load_manifest(repo)

    def test_supplement_declaring_a_member_twice_refuses(self) -> None:
        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(pathlib.Path(directory))
            write_supplement(
                repo,
                minimal_supplement(
                    code=["tools/member.py"], data=["tools/member.py"]
                ),
            )
            with self.assertRaisesRegex(ValueError, "twice"):
                closure.load_manifest(repo)

    def test_malformed_supplement_refuses_instead_of_being_ignored(self) -> None:
        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(pathlib.Path(directory))
            write_text(repo / SUPPLEMENT_RELATIVE_PATH, "{not json\n")
            with self.assertRaisesRegex(ValueError, "unreadable"):
                closure.load_manifest(repo)

    def test_wrong_supplement_schema_refuses(self) -> None:
        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(pathlib.Path(directory))
            write_supplement(repo, minimal_supplement(schema_version="wrong"))
            with self.assertRaisesRegex(ValueError, "supplement schema"):
                closure.load_manifest(repo)

    def test_unknown_supplement_key_refuses(self) -> None:
        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(pathlib.Path(directory))
            write_supplement(repo, minimal_supplement(smuggled=["x"]))
            with self.assertRaisesRegex(ValueError, "unknown keys"):
                closure.load_manifest(repo)

    def test_unsafe_supplement_path_refuses(self) -> None:
        closure = load_closure()
        unsafe_paths = ("/abs.py", "up/../and/out.py", "back\\slash.py", "c:drive.py")
        for unsafe in unsafe_paths:
            with tempfile.TemporaryDirectory() as directory:
                repo = build_sandbox_repo(pathlib.Path(directory))
                write_supplement(repo, minimal_supplement(code=[unsafe]))
                with self.assertRaisesRegex(ValueError, "safe repo-relative"):
                    closure.load_manifest(repo)

    def test_unsafe_dynamic_caller_key_refuses(self) -> None:
        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(pathlib.Path(directory))
            write_supplement(
                repo,
                minimal_supplement(
                    dynamic_call_sites={"/abs/caller.py": []},
                    dynamic_call_site_notes={"/abs/caller.py": "unsafe caller"},
                ),
            )
            with self.assertRaisesRegex(ValueError, "dynamic_call_sites"):
                closure.load_manifest(repo)

    def test_undeclared_supplement_dynamic_caller_refuses(self) -> None:
        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(pathlib.Path(directory))
            write_supplement(
                repo,
                minimal_supplement(
                    dynamic_call_sites={"tools/ghost_caller.py": []},
                    dynamic_call_site_notes={
                        "tools/ghost_caller.py": "caller never declared"
                    },
                ),
            )
            with self.assertRaisesRegex(ValueError, "must be declared members"):
                closure.load_manifest(repo)

    def test_supplement_dynamic_caller_declared_in_supplement_is_accepted(
        self,
    ) -> None:
        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(pathlib.Path(directory))
            write_text(repo / "tools" / "caller.py", "VALUE = 1\n")
            write_supplement(
                repo,
                minimal_supplement(
                    code=["tools/caller.py"],
                    dynamic_call_sites={"tools/caller.py": []},
                    dynamic_call_site_notes={"tools/caller.py": "declared caller"},
                ),
            )
            manifest = closure.load_manifest(repo)
            self.assertIn("tools/caller.py", manifest["dynamic_call_sites"])

    def test_supplement_listing_itself_refuses(self) -> None:
        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(pathlib.Path(directory))
            write_supplement(
                repo, minimal_supplement(data=[SUPPLEMENT_RELATIVE_PATH])
            )
            with self.assertRaisesRegex(ValueError, "must not list\s+itself"):
                closure.load_manifest(repo)

    def test_duplicate_dynamic_call_site_refuses(self) -> None:
        closure = load_closure()
        with tempfile.TemporaryDirectory() as directory:
            repo = build_sandbox_repo(pathlib.Path(directory))
            manifest_path = repo / MANIFEST_RELATIVE_PATH
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["dynamic_call_sites"] = {"scripts/training_closure.py": []}
            manifest["dynamic_call_site_notes"] = {
                "scripts/training_closure.py": "fixture declaration"
            }
            write_text(manifest_path, json.dumps(manifest, indent=2) + "\n")
            write_supplement(
                repo,
                minimal_supplement(
                    dynamic_call_sites={"scripts/training_closure.py": []},
                    dynamic_call_site_notes={
                        "scripts/training_closure.py": "duplicate declaration"
                    },
                ),
            )
            with self.assertRaisesRegex(
                ValueError, "re-declares dynamic_call_sites"
            ):
                closure.load_manifest(repo)


if __name__ == "__main__":
    unittest.main()
