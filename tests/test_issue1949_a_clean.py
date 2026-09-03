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
        "topology_canary": {
            "schema_version": "ember-issue1949-topology-canary-v1",
            "expected_receipt_path": "C:/artifacts/issue1949-a-clean-consumer-topology.json",
            "authority": MODULE.TOPOLOGY_AUTHORITY,
        },
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

    def test_topology_canary_is_required_and_every_bound_field_is_verified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "topology.json"
            payload = {
                "schema_version": "ember-issue1949-topology-canary-v1",
                "result": "PASS",
                "source_head": "a" * 40,
                "platform": "windows",
                "authority": MODULE.TOPOLOGY_AUTHORITY,
                "phases": [
                    "admission", "data_verify", "train", "checkpoint", "publish",
                    "selectable_checkpoint", "restore", "evaluation", "runtime_load",
                ],
                "entry_points": [f"owner:{index}" for index in range(7)],
                "raw_hashes": {"lab_operational_receipt": "b" * 64, "checkpoint": "c" * 64},
            }
            payload["self_sha256"] = MODULE.derive_self(payload)
            path.write_bytes(MODULE.canonical_json(payload) + b"\n")
            verified = MODULE.verify_topology_canary(
                path, source_head="a" * 40, platform_name="windows",
            )
            self.assertEqual(verified["result"], "PASS")
            planted = dict(payload)
            planted["phases"] = planted["phases"][:-1]
            planted["self_sha256"] = MODULE.derive_self(planted)
            path.write_bytes(MODULE.canonical_json(planted) + b"\n")
            with self.assertRaisesRegex(MODULE.ACleanRefusal, "TOPOLOGY_CANARY_CONTENT_REFUSED"):
                MODULE.verify_topology_canary(
                    path, source_head="a" * 40, platform_name="windows",
                )

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
            tool = root / MODULE.CANONICAL_TOOL_ROOT / "python_environment.py"
            tool.parent.mkdir(parents=True)
            tool.write_text("# canonical fixture tool\n")
            (tool.parent / "build_owned_curriculum.py").write_text("# canonical fixture builder\n")
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
                "schema_version": "ember-issue1949-a-clean-leg-spec-v4",
                "platform": "windows",
                "legs": [{
                    "id": leg_id,
                    "argv": ["${PYTHON}", "${PYENV}", "--leg", leg_id],
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
            for row in plan["legs"]:
                self.assertEqual(Path(row["argv"][1]), tool.resolve())
                self.assertTrue(Path(row["argv"][1]).is_file())
            with self.assertRaises(FileExistsError):
                MODULE.mint_plan(
                    repo_root=root, leg_spec_path=spec_path, output=output,
                    declared_head=head, platform_name="windows",
                    python_executable=Path(sys.executable), cargo_executable=Path(sys.executable),
                    artifact_root=artifacts, install_receipt=install, sdist_path=sdist,
                )

    def test_tool_path_prefers_canonical_root_and_accepts_legacy_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / MODULE.LEGACY_TOOL_ROOT / "python_environment.py"
            legacy.parent.mkdir(parents=True)
            legacy.write_bytes(b"legacy")
            self.assertEqual(
                MODULE.resolve_tool_path(root, "python_environment.py"), legacy
            )
            canonical = root / MODULE.CANONICAL_TOOL_ROOT / "python_environment.py"
            canonical.parent.mkdir(parents=True)
            canonical.write_bytes(b"canonical")
            self.assertEqual(
                MODULE.resolve_tool_path(root, "python_environment.py"), canonical
            )

    def test_tool_root_token_is_substitutable_and_binds_the_curriculum_builder_root(self) -> None:
        self.assertIn("${TOOL_ROOT}", MODULE.PLAN_TOKENS)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / MODULE.LEGACY_TOOL_ROOT / "build_owned_curriculum.py"
            legacy.parent.mkdir(parents=True)
            legacy.write_bytes(b"legacy")
            # A partial canonical directory without the exact builder must not win.
            (root / MODULE.CANONICAL_TOOL_ROOT).mkdir(parents=True)
            self.assertEqual(
                MODULE.resolve_tool_path(root, "build_owned_curriculum.py").parent,
                legacy.parent,
            )
            canonical = root / MODULE.CANONICAL_TOOL_ROOT / "build_owned_curriculum.py"
            canonical.write_bytes(b"canonical")
            self.assertEqual(
                MODULE.resolve_tool_path(root, "build_owned_curriculum.py").parent,
                canonical.parent,
            )
            spec = self._write_leg_spec(
                root,
                lambda leg_id: ["${PYTHON}", "${TOOL_ROOT}/build_owned_curriculum.py", leg_id],
            )
            self.assertEqual(
                MODULE.validate_leg_spec_file(spec, "linux")["platform"], "linux"
            )

    def test_external_present_is_positive_and_topology_binding_is_mandatory(self) -> None:
        self.assertNotIn("external_data_present", MODULE.NEGATIVE_LEG_IDS)
        plan = valid_plan()
        for row in plan["legs"]:
            if row["id"] == "external_data_present":
                self.assertEqual(row["expected_exit"], 0)
                row["expected_exit"] = 4
        plan["self_sha256"] = MODULE.derive_self(plan)
        with self.assertRaisesRegex(MODULE.ACleanRefusal, "POSITIVE_LEG_EXPECTED_EXIT_REFUSED"):
            MODULE.validate_plan(plan)
        plan = valid_plan()
        plan.pop("topology_canary")
        plan["self_sha256"] = MODULE.derive_self(plan)
        with self.assertRaisesRegex(MODULE.ACleanRefusal, "TOPOLOGY_CANARY_PLAN_REFUSED"):
            MODULE.validate_plan(plan)

    def test_tool_path_refuses_when_no_root_carries_the_tool(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(MODULE.ACleanRefusal) as caught:
                MODULE.resolve_tool_path(Path(directory), "python_environment.py")
            self.assertIn("TOOL_ROOT_UNRESOLVED", str(caught.exception))

    def _write_leg_spec(self, base, argv_for):
        spec = {
            "schema_version": "ember-issue1949-a-clean-leg-spec-v4",
            "platform": "linux",
            "legs": [{
                "id": leg_id,
                "argv": argv_for(leg_id),
                "contract_files": ["contracts/" + leg_id + ".txt"],
                "expected_exit": 2 if leg_id in MODULE.NEGATIVE_LEG_IDS else 0,
            } for leg_id in MODULE.REQUIRED_LEG_IDS],
        }
        spec["self_sha256"] = MODULE.derive_self(spec)
        path = base / "spec.json"
        path.write_bytes(MODULE.canonical_json(spec) + b"\n")
        return path

    def test_leg_spec_validator_accepts_a_fully_bound_specification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_leg_spec(
                Path(directory),
                lambda leg_id: ["${PYTHON}", "${REPO_ROOT}/run.py", "--leg", leg_id],
            )
            result = MODULE.validate_leg_spec_file(path, "linux")
            self.assertEqual(result["result"], "LEG_SPEC_BOUND")
            self.assertEqual(list(result["legs"]), list(MODULE.REQUIRED_LEG_IDS))

    def test_leg_spec_validator_refuses_an_unbound_consumer_placeholder(self) -> None:
        sentinel = MODULE.UNBOUND_LEG_SENTINEL + ":deterministic_data"

        def argv_for(leg_id):
            if leg_id == "deterministic_data":
                return ["${PYTHON}", "-c", "raise SystemExit(" + repr(sentinel) + ")"]
            return ["${PYTHON}", "${REPO_ROOT}/run.py", "--leg", leg_id]

        with tempfile.TemporaryDirectory() as directory:
            path = self._write_leg_spec(Path(directory), argv_for)
            with self.assertRaises(MODULE.ACleanRefusal) as caught:
                MODULE.validate_leg_spec_file(path, "linux")
            self.assertIn("LEG_SPEC_CONSUMER_UNBOUND_REFUSED", str(caught.exception))
            self.assertIn("deterministic_data", str(caught.exception))

    def test_leg_spec_validator_refuses_an_unsubstitutable_token(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_leg_spec(
                Path(directory),
                lambda leg_id: ["${PYTHON}", "${NOT_A_TOKEN}/run.py", "--leg", leg_id],
            )
            with self.assertRaises(MODULE.ACleanRefusal) as caught:
                MODULE.validate_leg_spec_file(path, "linux")
            self.assertIn("LEG_SPEC_TOKEN_REFUSED", str(caught.exception))

    def test_leg_spec_validator_cli_exits_nonzero_on_an_unbound_specification(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_leg_spec(
                Path(directory),
                lambda leg_id: [
                    "${PYTHON}", "-c",
                    "raise SystemExit(" + repr(MODULE.UNBOUND_LEG_SENTINEL + ":" + leg_id) + ")",
                ],
            )
            self.assertEqual(
                MODULE.main([
                    "validate-leg-spec", "--leg-spec", str(path), "--platform", "linux",
                ]),
                2,
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


class ACleanV2Tests(unittest.TestCase):
    """Review findings on the 02A harness (2026-09-03): refusal classes, lexical executables, missing paths."""

    def test_every_negative_leg_names_a_refusal_class(self) -> None:
        self.assertEqual(frozenset(MODULE.NEGATIVE_LEG_REFUSAL_MARKERS), MODULE.NEGATIVE_LEG_IDS)
        for leg_id, markers in MODULE.NEGATIVE_LEG_REFUSAL_MARKERS.items():
            self.assertTrue(markers, leg_id)

    def test_negative_leg_requires_its_refusal_class_not_just_the_exit_code(self) -> None:
        # Planted negative: the authorized exit status with unrelated output is refused.
        with self.assertRaises(MODULE.ACleanRefusal) as caught:
            MODULE.bind_negative_leg_refusal_class(
                "refused_dependency_sdist", b"", b"Traceback (most recent call last): KeyError"
            )
        self.assertIn("LEG_REFUSAL_CLASS_REFUSED:refused_dependency_sdist", str(caught.exception))
        bound = MODULE.bind_negative_leg_refusal_class(
            "refused_dependency_sdist", b"",
            b"refused: host-conditioned wheel differs from fixed manifest artifact\n",
        )
        self.assertEqual(bound, ["host-conditioned wheel differs from fixed manifest artifact"])
        # Every marker of a multi-marker class is required, in either stream.
        with self.assertRaises(MODULE.ACleanRefusal):
            MODULE.bind_negative_leg_refusal_class(
                "external_data_absent_refusal", b'{"result": "EXPECTED_REFUSAL"}', b""
            )
        self.assertEqual(
            len(MODULE.bind_negative_leg_refusal_class(
                "external_data_absent_refusal",
                b'{"refusal": "external authority root is absent", "result": "EXPECTED_REFUSAL"}', b"",
            )),
            2,
        )
        # Positive legs carry no class.
        self.assertEqual(MODULE.bind_negative_leg_refusal_class("deterministic_data", b"x", b"y"), [])

    def test_governed_positive_leg_requires_its_terminal_markers_not_just_exit_zero(self) -> None:
        # Planted negative: a successful process with no governed result cannot pass.
        with self.assertRaises(MODULE.ACleanRefusal) as caught:
            MODULE.bind_positive_leg_pass_markers(
                "external_data_present", b'{"result": "PASS"}', b""
            )
        self.assertIn("LEG_PASS_MARKER_REFUSED:external_data_present", str(caught.exception))
        self.assertEqual(
            MODULE.bind_positive_leg_pass_markers(
                "external_data_present",
                b'{"result": "PASS", "validator": {"result": "VERIFIED"}}',
                b"",
            ),
            ['"result": "PASS"', '"result": "VERIFIED"'],
        )
        self.assertEqual(
            MODULE.bind_positive_leg_pass_markers("deterministic_data", b"", b""), []
        )

    def _mint_fixture(self, base: Path, argv_for=None):
        root = base / "fresh clone"
        root.mkdir()
        tool = root / MODULE.CANONICAL_TOOL_ROOT / "python_environment.py"
        tool.parent.mkdir(parents=True)
        tool.write_text("# canonical fixture tool\n")
        (tool.parent / "build_owned_curriculum.py").write_text("# canonical fixture builder\n")
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
        if argv_for is None:
            argv_for = lambda leg_id: ["${PYTHON}", "${PYENV}", "--leg", leg_id]
        spec_path = base / "spec.json"
        spec = {
            "schema_version": "ember-issue1949-a-clean-leg-spec-v4",
            "platform": "linux",
            "legs": [{
                "id": leg_id,
                "argv": argv_for(leg_id),
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
        return root, head, spec_path, artifacts, install, sdist

    def _mint(self, base: Path, *, python_executable: Path, cargo_executable: Path, argv_for=None):
        root, head, spec_path, artifacts, install, sdist = self._mint_fixture(base, argv_for)
        return MODULE.mint_plan(
            repo_root=root, leg_spec_path=spec_path, output=artifacts / "plan.json",
            declared_head=head, platform_name="linux",
            python_executable=python_executable, cargo_executable=cargo_executable,
            artifact_root=artifacts, install_receipt=install, sdist_path=sdist,
        )

    @unittest.skipIf(sys.platform == "win32", "POSIX venv interpreters and cargo shims are symlinks")
    def test_mint_plan_keeps_lexical_paths_for_symlinked_python_and_cargo(self) -> None:
        # Regressions: resolving the venv symlink bound the plan to the provisioning interpreter
        # outside the repository root (Linux run 33796284009); resolving ~/.cargo/bin/cargo bound
        # the lab leg to the rustup shim target (Linux run 33805309876, exit 2).
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "venv" / "bin").mkdir(parents=True)
            (base / "cargo-home" / "bin").mkdir(parents=True)
            python_link = base / "venv" / "bin" / "python3"
            python_link.symlink_to(sys.executable)
            rustup = base / "cargo-home" / "bin" / "rustup"
            rustup.write_bytes(b"#!/bin/sh\nexit 7\n")
            cargo_link = base / "cargo-home" / "bin" / "cargo"
            cargo_link.symlink_to(rustup)
            plan = self._mint(
                base, python_executable=python_link, cargo_executable=cargo_link,
                argv_for=lambda leg_id: ["${PYTHON}", "${PYENV}", "--leg", leg_id, "--cargo", "${CARGO}"],
            )
            for row in plan["legs"]:
                self.assertEqual(row["argv"][0], str(python_link))
                self.assertNotEqual(row["argv"][0], str(Path(sys.executable).resolve()))
                self.assertEqual(row["executable_raw_sha256"], MODULE.sha256_file(python_link))
                self.assertEqual(row["argv"][-1], str(cargo_link))
                self.assertNotIn("rustup", row["argv"][-1])

    def test_mint_plan_refuses_missing_interpreter_cargo_and_leg_executable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            with self.assertRaises(MODULE.ACleanRefusal) as caught:
                self._mint(base, python_executable=base / "no-venv" / "bin" / "python3",
                           cargo_executable=Path(sys.executable))
            self.assertIn("PYTHON_EXECUTABLE_MISSING", str(caught.exception))
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            with self.assertRaises(MODULE.ACleanRefusal) as caught:
                self._mint(base, python_executable=Path(sys.executable),
                           cargo_executable=base / "no-cargo" / "bin" / "cargo")
            self.assertIn("CARGO_EXECUTABLE_MISSING", str(caught.exception))
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            gone = (base / "gone-tool").as_posix()
            with self.assertRaises(MODULE.ACleanRefusal) as caught:
                self._mint(base, python_executable=Path(sys.executable), cargo_executable=Path(sys.executable),
                           argv_for=lambda leg_id: [gone, "${PYENV}", "--leg", leg_id])
            self.assertIn("LEG_EXECUTABLE_MISSING", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
