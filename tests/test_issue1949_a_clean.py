# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "issue1949_a_clean.py"
SPEC = importlib.util.spec_from_file_location("issue1949_a_clean", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def valid_plan() -> dict[str, object]:
    legs = []
    for name in MODULE.REQUIRED_LEG_IDS:
        argv = ["C:/bound/tool.exe", "--verify", name]
        contract_files = [{"path": f"contracts/{name}.txt", "raw_sha256": "a" * 64}]
        legs.append({
            "id": name,
            "argv": argv,
            "argv_sha256": MODULE.sha256_bytes(MODULE.canonical_json(argv)),
            "executable_raw_sha256": MODULE.sha256_bytes(("exe:" + name).encode()),
            "semantic_contract_id": name,
            "semantic_contract_files": contract_files,
            "semantic_contract_sha256": MODULE.sha256_bytes(MODULE.canonical_json(contract_files)),
            "expected_exit": 2 if name in MODULE.NEGATIVE_LEG_IDS else 0,
        })
    plan = {
        "schema_version": "ember-issue1949-a-clean-plan-v1",
        "declared_head": "a" * 40,
        "setuptools": {
            "wheel": "setuptools-84.0.0-py3-none-any.whl",
            "wheel_sha256": "51a52592b3b99e102b609654876bd65f19f999935166d1352678931132b0c670",
            "refused_sdist": "setuptools-84.0.0.tar.gz",
            "refused_sdist_sha256": "f4695c21257f0d9b537ec2692c941d02ee143b7cc1276941349a546573b2ef73",
        },
        "legs": legs,
    }
    plan["self_sha256"] = MODULE.derive_self(plan)
    return plan


class ACleanTests(unittest.TestCase):
    def test_plan_requires_every_terminal_leg_and_exact_dependency_artifacts(self) -> None:
        plan = valid_plan()
        validated = MODULE.validate_plan(plan)
        self.assertEqual(tuple(row["id"] for row in validated["legs"]), MODULE.REQUIRED_LEG_IDS)
        self.assertTrue(validated["setuptools"]["wheel_sha256"].startswith("51a52592"))

        plan["legs"] = plan["legs"][:-1]
        plan["self_sha256"] = MODULE.derive_self(plan)
        with self.assertRaisesRegex(MODULE.ACleanRefusal, "PLAN_LEG_SET_REFUSED"):
            MODULE.validate_plan(plan)

    def test_plan_refuses_shells_relative_executables_and_duplicate_leg_ids(self) -> None:
        for executable in ("python", "bash", "cmd.exe", "powershell.exe"):
            plan = valid_plan()
            plan["legs"][0]["argv"][0] = executable
            plan["legs"][0]["argv_sha256"] = MODULE.sha256_bytes(
                MODULE.canonical_json(plan["legs"][0]["argv"])
            )
            plan["self_sha256"] = MODULE.derive_self(plan)
            with self.assertRaisesRegex(MODULE.ACleanRefusal, "LEG_EXECUTABLE_REFUSED"):
                MODULE.validate_plan(plan)

        plan = valid_plan()
        plan["legs"][1]["id"] = plan["legs"][0]["id"]
        plan["self_sha256"] = MODULE.derive_self(plan)
        with self.assertRaisesRegex(MODULE.ACleanRefusal, "PLAN_LEG_SET_REFUSED"):
            MODULE.validate_plan(plan)

    def test_checkout_identity_refuses_sha_dirty_tree_inside_cwd_and_wrong_platform(self) -> None:
        defaults = {
            "declared_head": "a" * 40,
            "actual_head": "a" * 40,
            "porcelain": b"",
            "repo_root": Path("C:/fresh clone é"),
            "caller_cwd": Path("C:/outside"),
            "declared_platform": "windows",
            "actual_platform": "windows",
        }
        MODULE.validate_checkout_identity(**defaults)
        for change in (
            {"actual_head": "b" * 40},
            {"porcelain": b" M dirty"},
            {"caller_cwd": Path("C:/fresh clone é/subdir")},
            {"actual_platform": "linux"},
        ):
            with self.assertRaises(MODULE.ACleanRefusal):
                MODULE.validate_checkout_identity(**(defaults | change))

    def test_receipt_self_hash_and_no_overwrite_are_exact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receipt.json"
            receipt = MODULE.write_receipt_no_overwrite(
                output,
                {"schema_version": "ember-issue1949-a-clean-v1", "result": "PASS"},
            )
            unsigned = dict(receipt)
            claimed = unsigned.pop("self_sha256")
            self.assertEqual(claimed, MODULE.sha256_bytes(MODULE.canonical_json(unsigned)))
            self.assertEqual(output.read_bytes(), MODULE.canonical_json(receipt) + b"\n")
            with self.assertRaises(FileExistsError):
                MODULE.write_receipt_no_overwrite(output, {"result": "PASS"})

    def test_external_bound_plan_is_accepted_only_with_a_fresh_clone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "fresh clone é"
            root.mkdir()
            (root / ".git").mkdir()
            outside = Path(directory) / "outside.json"
            outside.write_text(json.dumps(valid_plan()), encoding="utf-8")
            self.assertIsNone(MODULE.validate_fresh_clone(root))
            self.assertEqual(MODULE.validate_plan(json.loads(outside.read_text()))["declared_head"], "a" * 40)
            (root / ".git").rmdir()
            (root / ".git").write_text("gitdir: linked-worktree", encoding="utf-8")
            with self.assertRaisesRegex(MODULE.ACleanRefusal, "FRESH_CLONE_IDENTITY_REFUSED"):
                MODULE.validate_fresh_clone(root)

    def test_leg_executable_bytes_must_match_the_plan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "bound-tool.exe"
            executable.write_bytes(b"tool-v1")
            row = {
                "id": "canonical_domain_imports",
                "argv": [str(executable)],
                "executable_raw_sha256": MODULE.sha256_file(executable),
            }
            MODULE.validate_executable_identity(row)
            row["executable_raw_sha256"] = "0" * 64
            with self.assertRaisesRegex(MODULE.ACleanRefusal, "LEG_EXECUTABLE_IDENTITY_REFUSED"):
                MODULE.validate_executable_identity(row)

    def test_semantic_contract_files_are_reopened_from_the_exact_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = root / "contracts" / "canonical.txt"
            contract.parent.mkdir()
            contract.write_bytes(b"contract-v1\n")
            row = {
                "id": "canonical_domain_imports",
                "semantic_contract_files": [{
                    "path": "contracts/canonical.txt",
                    "raw_sha256": MODULE.sha256_file(contract),
                }],
            }
            MODULE.validate_semantic_contract_identity(root, row)
            contract.write_bytes(b"contract-v2\n")
            with self.assertRaisesRegex(MODULE.ACleanRefusal, "LEG_CONTRACT_FILE_IDENTITY_REFUSED"):
                MODULE.validate_semantic_contract_identity(root, row)

    def test_mint_plan_resolves_platform_bytes_and_is_no_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "fresh clone é"
            root.mkdir()
            contract_files = []
            for leg_id in MODULE.REQUIRED_LEG_IDS:
                contract = root / "contracts" / f"{leg_id}.txt"
                contract.parent.mkdir(exist_ok=True)
                contract.write_text(leg_id)
                contract_files.append(contract.relative_to(root).as_posix())
            for command in (
                ["git", "init", str(root)],
                ["git", "-C", str(root), "config", "user.email", "test@example.invalid"],
                ["git", "-C", str(root), "config", "user.name", "test"],
                ["git", "-C", str(root), "add", "."],
                ["git", "-C", str(root), "commit", "-m", "fixture"],
                ["git", "-C", str(root), "remote", "add", "origin", "https://example.invalid/ember.git"],
            ):
                subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               creationflags=MODULE.NO_WINDOW)
            head = MODULE._git(root, "rev-parse", "HEAD").decode().strip()
            spec_path = base / "spec.json"
            spec = {
                "schema_version": "ember-issue1949-a-clean-leg-spec-v1",
                "platform": "windows",
                "legs": [{
                    "id": leg_id,
                    "argv": ["${PYTHON}", "--leg", leg_id],
                    "contract_files": [contract_files[index]],
                    "expected_exit": 2 if leg_id in MODULE.NEGATIVE_LEG_IDS else 0,
                } for index, leg_id in enumerate(MODULE.REQUIRED_LEG_IDS)],
            }
            spec["self_sha256"] = MODULE.derive_self(spec)
            spec_path.write_bytes(MODULE.canonical_json(spec) + b"\n")
            artifacts = base / "artifacts"
            artifacts.mkdir()
            install = artifacts / "install.json"
            sdist = artifacts / "setuptools-84.0.0.tar.gz"
            install.write_text("{}")
            sdist.write_text("fixture")
            output = artifacts / "plan.json"
            plan = MODULE.mint_plan(
                repo_root=root, leg_spec_path=spec_path, output=output,
                declared_head=head, platform_name="windows",
                python_executable=Path(sys.executable), cargo_executable=Path(sys.executable),
                artifact_root=artifacts, install_receipt=install, sdist_path=sdist,
            )
            self.assertEqual(plan["self_sha256"], MODULE.derive_self(plan))
            self.assertTrue(output.is_file())
            with self.assertRaises(FileExistsError):
                MODULE.mint_plan(
                    repo_root=root, leg_spec_path=spec_path, output=output,
                    declared_head=head, platform_name="windows",
                    python_executable=Path(sys.executable), cargo_executable=Path(sys.executable),
                    artifact_root=artifacts, install_receipt=install, sdist_path=sdist,
                )

    def test_refusal_receipt_preserves_named_class_plan_and_partial_streams(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "terminal.json"
            plan = root / "plan.json"
            plan.write_bytes(b"{}\n")
            streams = root / "terminal.streams"
            streams.mkdir()
            (streams / "leg.stderr.log").write_bytes(b"named failure\n")
            receipt = MODULE.write_refusal_receipt(
                output=output,
                repo_root=root / "fresh clone é",
                plan_path=plan,
                declared_platform="windows",
                refusal=MODULE.ACleanRefusal("LEG_EXIT_REFUSED:canonical_domain_imports:1"),
            )
            self.assertEqual(receipt["result"], "REFUSED")
            self.assertEqual(receipt["refusal_class"], "LEG_EXIT_REFUSED")
            self.assertEqual(receipt["plan"]["raw_sha256"], MODULE.sha256_file(plan))
            self.assertEqual(receipt["streams"][0]["raw_sha256"], MODULE.sha256_file(streams / "leg.stderr.log"))
            unsigned = dict(receipt)
            claimed = unsigned.pop("self_sha256")
            self.assertEqual(claimed, MODULE.sha256_bytes(MODULE.canonical_json(unsigned)))

    def test_platform_wrappers_bind_exact_head_and_hidden_windows_python(self) -> None:
        workflow = (ROOT / ".github/workflows/issue1949-a-clean-linux.yml").read_text(encoding="utf-8")
        windows = (ROOT / "scripts/issue1949-a-clean-windows.ps1").read_text(encoding="utf-8")
        self.assertIn("ref: ${{ inputs.declared_head }}", workflow)
        self.assertIn('test "$actual" = "$DECLARED_HEAD"', workflow)
        self.assertIn("LEG_SPEC_BASE64: ${{ inputs.leg_spec_base64 }}", workflow)
        self.assertIn("Mint and publish exact Linux platform plan identity", workflow)
        self.assertLess(
            workflow.index("Mint and publish exact Linux platform plan identity"),
            workflow.index("Run published Linux CPU clean-clone plan"),
        )
        self.assertIn("sha256sum --check --strict", workflow)
        self.assertNotIn('${{ inputs.declared_head }}"', workflow.split("run: |", 1)[1])
        self.assertIn("fresh clone é", workflow)
        self.assertIn("working-directory: ${{ runner.temp }}", workflow)
        self.assertIn("scripts\\headless-python.ps1", windows)
        self.assertIn("-NoLogo -NoProfile -NonInteractive", windows)
        self.assertIn("A_CLEAN_PLAN_RAW_HASH_REFUSED", windows)
        self.assertIn('ValidateSet("Mint", "Run")', windows)
        self.assertIn("A_CLEAN_WINDOWS_VERIFY_REFUSED", windows)
        self.assertIn("--platform windows", windows)


if __name__ == "__main__":
    unittest.main()
