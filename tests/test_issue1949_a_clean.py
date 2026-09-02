# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
import json
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
    return {
        "schema_version": "ember-issue1949-a-clean-plan-v1",
        "declared_head": "a" * 40,
        "setuptools": {
            "wheel": "setuptools-84.0.0-py3-none-any.whl",
            "wheel_sha256": "51a52592b3b99e102b609654876bd65f19f999935166d1352678931132b0c670",
            "refused_sdist": "setuptools-84.0.0.tar.gz",
            "refused_sdist_sha256": "f4695c21257f0d9b537ec2692c941d02ee143b7cc1276941349a546573b2ef73",
        },
        "legs": [
            {"id": name, "argv": ["C:/bound/tool.exe", "--verify"], "expected_exit": 0}
            for name in MODULE.REQUIRED_LEG_IDS
        ],
    }


class ACleanTests(unittest.TestCase):
    def test_plan_requires_every_terminal_leg_and_exact_dependency_artifacts(self) -> None:
        plan = valid_plan()
        validated = MODULE.validate_plan(plan)
        self.assertEqual(tuple(row["id"] for row in validated["legs"]), MODULE.REQUIRED_LEG_IDS)
        self.assertTrue(validated["setuptools"]["wheel_sha256"].startswith("51a52592"))

        plan["legs"] = plan["legs"][:-1]
        with self.assertRaisesRegex(MODULE.ACleanRefusal, "PLAN_LEG_SET_REFUSED"):
            MODULE.validate_plan(plan)

    def test_plan_refuses_shells_relative_executables_and_duplicate_leg_ids(self) -> None:
        for executable in ("python", "bash", "cmd.exe", "powershell.exe"):
            plan = valid_plan()
            plan["legs"][0]["argv"][0] = executable
            with self.assertRaisesRegex(MODULE.ACleanRefusal, "LEG_EXECUTABLE_REFUSED"):
                MODULE.validate_plan(plan)

        plan = valid_plan()
        plan["legs"][1]["id"] = plan["legs"][0]["id"]
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

    def test_platform_wrappers_bind_exact_head_and_hidden_windows_python(self) -> None:
        workflow = (ROOT / ".github/workflows/issue1949-a-clean-linux.yml").read_text(encoding="utf-8")
        windows = (ROOT / "scripts/issue1949-a-clean-windows.ps1").read_text(encoding="utf-8")
        self.assertIn("ref: ${{ inputs.declared_head }}", workflow)
        self.assertIn('test "$actual" = "${{ inputs.declared_head }}"', workflow)
        self.assertIn("fresh clone é", workflow)
        self.assertIn("working-directory: ${{ runner.temp }}", workflow)
        self.assertIn("scripts\\headless-python.ps1", windows)
        self.assertIn("-NoLogo -NoProfile -NonInteractive", windows)
        self.assertIn("--platform windows", windows)


if __name__ == "__main__":
    unittest.main()
