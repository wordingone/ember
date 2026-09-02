# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import os
import ntpath
import re
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path


REPOSITORY = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
#: An 8.3 short-name component, e.g. the `RUNNER~1` GitHub's windows-latest puts in TEMP.
SHORT_NAME_COMPONENT = re.compile(r"~\d")


def canonical(path: str | Path) -> str:
    """One spelling per real directory: 8.3 short names expanded, casing normalized.
    `realpath` is what expands the short form on Windows -- `abspath` leaves it alone."""
    return os.path.normcase(os.path.realpath(path))
PUBLIC_LAUNCHER = REPOSITORY / "tools" / "launchers" / "Ember.cmd"
LAUNCH_IMPL = REPOSITORY / "scripts" / "prepare-ember-cockpit.ps1"
LAUNCH_STAGING = REPOSITORY / "scripts" / "ember-launch-staging.ps1"
WINDOW_PLACEMENT = REPOSITORY / "scripts" / "ember-window-placement.ps1"
START_HERE = REPOSITORY / "docs" / "domains" / "governance" / "guides" / "START-HERE.md"


class EmberRootLauncherTests(unittest.TestCase):
    def make_fixture(self) -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
        owner = tempfile.TemporaryDirectory(prefix="ember launcher ")
        root = Path(owner.name) / "Ember Repository With Spaces"
        (root / "scripts").mkdir(parents=True)
        source = root / "tools" / "ember-cli" / "src"
        (source / "entrypoints").mkdir(parents=True)
        launcher = root / "tools" / "launchers" / "Ember.cmd"
        launcher.parent.mkdir(parents=True)
        shutil.copy2(PUBLIC_LAUNCHER, launcher)
        shutil.copy2(LAUNCH_IMPL, root / "scripts" / "prepare-ember-cockpit.ps1")
        # The preparation helper dot-sources the staging sibling at startup; the
        # fixture mirrors the deployed scripts/ layout so the copy can actually run.
        shutil.copy2(LAUNCH_STAGING, root / "scripts" / "ember-launch-staging.ps1")
        shutil.copy2(WINDOW_PLACEMENT, root / "scripts" / "ember-window-placement.ps1")
        (source / "entrypoints" / "main.ts").write_text("throw new Error('fixture only');\n", encoding="utf-8")
        (source / "package.json").write_text('{"name":"ember-cli","type":"module"}\n', encoding="utf-8")
        (source / "bun.lock").write_text("fixture-lock\n", encoding="utf-8")
        runtime = root / "fake-bun.cmd"
        runtime.write_text(
            "@echo off\r\n"
            "> \"%EMBER_LAUNCH_TEST_LOG%\" echo cwd=%CD%\r\n"
            ">> \"%EMBER_LAUNCH_TEST_LOG%\" echo args=%*\r\n"
            ">> \"%EMBER_LAUNCH_TEST_LOG%\" echo gpu_free=%EMBER_GPU_FREE%\r\n"
            "exit /b 0\r\n",
            encoding="utf-8",
        )
        return owner, root, runtime

    def state_root(self, root: Path) -> Path:
        """Cockpit state root for a fixture — deliberately a SIBLING of the checkout, never
        inside it: the whole point of the relocation is that no launch writes into the tree
        the completion verifier censuses (issue #1330)."""
        return root.parent / "cockpit-state"

    def run_launcher(
        self,
        root: Path,
        runtime: Path,
        *arguments: str,
        include_runtime: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        log = root / "launch.log"
        env = os.environ.copy()
        env.update(
            {
                "EMBER_LAUNCH_NONINTERACTIVE": "1",
                "EMBER_LAUNCH_TEST_MODE": "1",
                "EMBER_LAUNCH_TEST_LOG": str(log),
                "EMBER_STATE_ROOT": str(self.state_root(root)),
            }
        )
        if include_runtime:
            env["EMBER_LAUNCH_TEST_RUNTIME"] = str(runtime)
        else:
            env.pop("EMBER_LAUNCH_TEST_RUNTIME", None)
        return subprocess.run(
            [
                "cmd.exe",
                "/d",
                "/c",
                str(root / "tools" / "launchers" / "Ember.cmd"),
                *arguments,
            ],
            cwd=Path(tempfile.gettempdir()),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
            check=False,
        )

    def assert_logged_cwd(self, log: str, expected: Path) -> None:
        """The fake runtime records %CD%, which Windows renders in the filesystem's own
        canonical spelling no matter how TEMP is spelled in the environment: canonical
        casing (#1395) and the long form of any 8.3 short name (#1390 -- GitHub's
        windows-latest sets TEMP under `RUNNER~1`, so the fixture path Python builds is
        short while the one the launcher reports is long). Compare path identity rather
        than spelling so the suite passes under any TEMP shape."""
        recorded = [line[len("cwd=") :] for line in log.splitlines() if line.startswith("cwd=")]
        self.assertEqual(len(recorded), 1, log)
        self.assertEqual(
            canonical(recorded[0]),
            canonical(expected),
            f"launcher ran in {recorded[0]}, expected {expected}",
        )
        # The launcher canonicalizes on its own (tools/launchers/Ember.cmd's
        # %~dp0 and PowerShell's
        # $PSScriptRoot both yield the long form), and callers see the path it reports.
        # Pin that here so a change that starts echoing the caller's spelling fails by
        # name instead of surfacing as an unexplained mismatch on one runner.
        self.assertIsNone(
            SHORT_NAME_COMPONENT.search(recorded[0]),
            f"launcher reported an 8.3 short path instead of canonicalizing: {recorded[0]}",
        )

    def test_public_launcher_and_implementation_are_visible(self) -> None:
        self.assertTrue(PUBLIC_LAUNCHER.is_file())
        self.assertTrue(LAUNCH_IMPL.is_file())
        self.assertTrue(WINDOW_PLACEMENT.is_file())
        documentation = START_HERE.read_text(encoding="utf-8")
        self.assertIn("`tools/launchers/Ember.cmd`", documentation)

    def test_no_argument_launch_discovers_repo_from_outside_and_handles_spaces(self) -> None:
        owner, root, runtime = self.make_fixture()
        self.addCleanup(owner.cleanup)
        result = self.run_launcher(root, runtime)
        self.assertEqual(result.returncode, 0, result.stdout)
        log = (root / "launch.log").read_text(encoding="utf-8")
        self.assert_logged_cwd(log, root / "tools" / "ember-cli" / "src")
        self.assertIn("args=run entrypoints/main.ts", log)
        self.assertIn("gpu_free=1", log)
        self.assertNotIn("entrypoints\\main.ts", result.stdout)

    def test_public_launcher_refuses_arguments_before_runtime_execution(self) -> None:
        owner, root, runtime = self.make_fixture()
        self.addCleanup(owner.cleanup)
        result = self.run_launcher(root, runtime, "--hidden-source-flag")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("does not accept arguments", result.stdout)
        self.assertFalse((root / "launch.log").exists())

    def test_missing_test_runtime_fails_once_with_actionable_human_message(self) -> None:
        owner, root, runtime = self.make_fixture()
        self.addCleanup(owner.cleanup)
        result = self.run_launcher(root, runtime, include_runtime=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Ember could not prepare its runtime", result.stdout)
        self.assertNotIn("At line:", result.stdout)
        self.assertNotIn("StackTrace", result.stdout)

    def test_bootstrap_is_version_and_digest_pinned_before_expansion(self) -> None:
        implementation = LAUNCH_IMPL.read_text(encoding="utf-8")
        self.assertIn("bun-v1.3.12/bun-windows-x64.zip", implementation)
        self.assertIn("841ff9c5dffcaa3a2620d1e3f87ee500f32a4ca830b001cade7a3479609d4a89", implementation)
        self.assertLess(implementation.index("Get-FileHash"), implementation.index("Expand-Archive"))

    def test_production_path_builds_commit_bound_application_and_governed_runtime(self) -> None:
        implementation = LAUNCH_IMPL.read_text(encoding="utf-8")
        self.assertIn("& $bun run build", implementation)
        self.assertIn('Join-Path $stateRoot "runtime\\ember\\$commit"', implementation)
        self.assertIn('cargo build --locked --release --manifest-path', implementation)
        self.assertNotIn('& $application', implementation)
        self.assertIn('$ErrorActionPreference = "Continue"', implementation)
        self.assertNotIn('$LASTEXITCODE -ne 0 -or $commit', implementation)
        self.assertNotIn('& $bun run entrypoints/main.ts\n    if ($LASTEXITCODE', implementation)

    def test_preparation_helper_only_returns_authenticated_build_paths(self) -> None:
        implementation = LAUNCH_IMPL.read_text(encoding="utf-8")
        self.assertIn('Write-Output ("EMBER_APPLICATION="', implementation)
        self.assertIn('Write-Output ("EMBER_LAB="', implementation)
        self.assertNotIn("$windowHandle = Get-EmberHostWindowHandle", implementation)
        self.assertNotIn("& $application", implementation)
    def run_library_command(self, body: str) -> subprocess.CompletedProcess[str]:
        script = str(LAUNCH_IMPL).replace("'", "''")
        command = f"$env:EMBER_LAUNCH_LIBRARY_ONLY='1'; . '{script}'; {body}"
        return subprocess.run(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
            check=False,
        )

    def test_left_half_geometry_uses_full_work_area_and_real_dimensions(self) -> None:
        placement_script = str(WINDOW_PLACEMENT).replace("'", "''")
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                f". '{placement_script}'; Get-EmberLeftHalfRectangle -Left -1920 -Top 40 -Right 0 -Bottom 1080 | ConvertTo-Json -Compress",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('{"X":-1920,"Y":40,"Width":960,"Height":1040}', result.stdout)
        placement = WINDOW_PLACEMENT.read_text(encoding="utf-8")
        self.assertIn("MonitorFromWindow", placement)
        self.assertIn("SetWindowPos", placement)
        self.assertIn("GetWindowRect", placement)
        self.assertIn("FindVisibleWindowsByTitle", placement)
        self.assertNotIn("0x0001", placement)  # SWP_NOSIZE is forbidden.

    def test_owned_stale_process_filter_cannot_target_foreign_executables(self) -> None:
        state = r"C:\fixture\cockpit-state"
        result = self.run_library_command(
            "$owned=Test-IsOwnedEmberExecutablePath "
            f"'{state}\\runtime\\ember\\abc\\Ember.exe' '{state}'; "
            "$foreign=Test-IsOwnedEmberExecutablePath 'C:\\Windows\\System32\\Ember.exe' "
            f"'{state}'; Write-Output \"$owned,$foreign\""
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("True,False", result.stdout)

    def test_named_launcher_lease_allows_exactly_one_live_owner(self) -> None:
        name = f"Local\\EmberLauncherContract-{uuid.uuid4().hex}"
        script = str(LAUNCH_IMPL).replace("'", "''")
        owner_command = (
            f"$env:EMBER_LAUNCH_LIBRARY_ONLY='1'; . '{script}'; "
            f"$m=Enter-EmberLauncherLease '{name}'; Write-Output 'ACQUIRED'; "
            "Start-Sleep -Seconds 3; $m.ReleaseMutex(); $m.Dispose()"
        )
        owner = subprocess.Popen(
            ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", owner_command],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.addCleanup(lambda: owner.kill() if owner.poll() is None else None)
        self.assertIsNotNone(owner.stdout)
        self.addCleanup(owner.stdout.close)
        self.assertEqual(owner.stdout.readline().strip(), "ACQUIRED")
        contender = self.run_library_command(
            f"try {{ $m=Enter-EmberLauncherLease '{name}'; Write-Output 'SECOND_OWNER'; "
            "$m.ReleaseMutex(); $m.Dispose() } catch { Write-Output $_.Exception.Message; exit 7 }"
        )
        self.assertEqual(contender.returncode, 7, contender.stdout)
        self.assertIn("already running", contender.stdout)
        owner.wait(timeout=10)
        self.assertEqual(owner.returncode, 0)

    # -- issue #1330: cockpit state lives outside the certified tree -----------------
    #
    # The completion verifier certifies the tree by TOTALITY -- every file, tracked and
    # untracked -- so a cockpit writing inside it reds the run. These pin the writer-side
    # cure: the state root resolves outside the checkout, an existing in-tree directory is
    # migrated out on launch, and a reappearing one refuses the launch outright.

    #: [repo root, expected key] -- mirrored verbatim by KEY_PARITY_VECTORS in
    #: src/ember/infrastructure/tools/ember-cli/src/utils/ember-state-root.test.ts. The launcher and the cockpit must
    #: derive the SAME default state directory; if either side drifts, one suite goes red.
    KEY_PARITY_VECTORS = [
        (r"C:\fixture\ember", "c-fixture-ember"),
        ("C:\\Fixture\\Ember\\", "c-fixture-ember"),
        (r"C:\fixture\ember repo", "c-fixture-ember-repo"),
        (r"C:\fixture\ember-wt\wt-1330", "c-fixture-ember-wt-wt-1330"),
    ]

    def test_state_root_key_matches_the_typescript_resolution_point(self) -> None:
        body = "; ".join(
            f"Write-Output (Get-EmberStateRootKey '{root}')" for root, _ in self.KEY_PARITY_VECTORS
        )
        result = self.run_library_command(f"$env:EMBER_STATE_ROOT=''; {body}")
        self.assertEqual(result.returncode, 0, result.stdout)
        produced = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        self.assertEqual(produced, [key for _, key in self.KEY_PARITY_VECTORS], result.stdout)

    def test_state_root_honours_the_override_and_never_defaults_into_the_tree(self) -> None:
        result = self.run_library_command(
            "$env:EMBER_STATE_ROOT='C:\\fixture\\cockpit-state'; "
            "Write-Output (Get-EmberStateRoot 'C:\\fixture\\ember'); "
            "$env:EMBER_STATE_ROOT=''; $env:EMBER_HOME='C:\\fixture\\home'; "
            "Write-Output (Get-EmberStateRoot 'C:\\fixture\\ember'); "
            "$env:EMBER_HOME=''; "
            "Write-Output (Get-EmberStateRoot 'C:\\fixture\\ember')"
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        override, explicit_home, windows_default = [
            l.strip() for l in result.stdout.splitlines() if l.strip()
        ][:3]
        self.assertEqual(override, r"C:\fixture\cockpit-state")
        self.assertEqual(explicit_home, r"C:\fixture\home\cockpit-state\c-fixture-ember")
        self.assertEqual(
            windows_default,
            ntpath.join("B:" + ntpath.sep, "M", "cockpit-state", "c-fixture-ember"),
        )
        self.assertNotIn(r"C:\fixture\ember\\", explicit_home)
        implementation = LAUNCH_IMPL.read_text(encoding="utf-8")
        self.assertNotIn('$env:OS -eq "Windows_NT"', implementation)
        self.assertIn("[System.Environment]::OSVersion.Platform", implementation)

    def test_launch_migrates_in_tree_state_out_and_leaves_nothing_behind(self) -> None:
        owner, root, runtime = self.make_fixture()
        self.addCleanup(owner.cleanup)
        resident = root / ".ember" / "runs"
        resident.mkdir(parents=True)
        (resident / "run-1.json").write_text('{"id":1}\n', encoding="utf-8")
        (root / ".ember" / "root-bindings.json").write_text("{}\n", encoding="utf-8")

        result = self.run_launcher(root, runtime)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertFalse((root / ".ember").exists(), "the in-tree state dir must be gone")
        moved = self.state_root(root)
        self.assertEqual((moved / "runs" / "run-1.json").read_text(encoding="utf-8"), '{"id":1}\n')
        self.assertTrue((moved / "root-bindings.json").is_file())

    def test_migration_refuses_to_dispose_of_cockpit_worktrees_itself(self) -> None:
        # Moving a registered worktree breaks its link to the repository and deleting one
        # destroys the work inside it, so migration names them and stops rather than
        # picking either. The rest of the state stays put too — a half-migrated tree is
        # not an improvement on an un-migrated one.
        owner, root, runtime = self.make_fixture()
        self.addCleanup(owner.cleanup)
        resident = root / ".ember" / "worktrees" / "wt-alpha"
        resident.mkdir(parents=True)
        (resident / "file.txt").write_text("work in progress\n", encoding="utf-8")
        (root / ".ember" / "root-bindings.json").write_text("{}\n", encoding="utf-8")

        result = self.run_launcher(root, runtime)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("wt-alpha", result.stdout)
        self.assertIn("worktree_lifecycle.py retire", result.stdout)
        self.assertTrue(resident.is_dir(), "the worktree must be left untouched")
        self.assertEqual((resident / "file.txt").read_text(encoding="utf-8"), "work in progress\n")
        self.assertTrue((root / ".ember" / "root-bindings.json").is_file())

    def test_migration_sweeps_an_empty_worktrees_directory(self) -> None:
        owner, root, runtime = self.make_fixture()
        self.addCleanup(owner.cleanup)
        (root / ".ember" / "worktrees").mkdir(parents=True)
        (root / ".ember" / "root-bindings.json").write_text("{}\n", encoding="utf-8")

        result = self.run_launcher(root, runtime)

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertFalse((root / ".ember").exists())
        self.assertTrue((self.state_root(root) / "root-bindings.json").is_file())

    def test_launch_refuses_when_in_tree_state_is_not_removable(self) -> None:
        # A directory that reappears non-empty must refuse the launch, not be certified
        # around. Simulated directly against the assertion so the test does not depend on
        # holding a real file lock.
        owner, root, _ = self.make_fixture()
        self.addCleanup(owner.cleanup)
        (root / ".ember").mkdir()
        (root / ".ember" / "runs.json").write_text("{}\n", encoding="utf-8")
        escaped = str(root).replace("'", "''")
        result = self.run_library_command(
            f"try {{ Assert-EmberStateIsExternal '{escaped}'; Write-Output 'ACCEPTED' }} "
            "catch { Write-Output $_.Exception.Message }"
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("ACCEPTED", result.stdout)
        self.assertIn("outside the certified tree", result.stdout)

    def test_empty_in_tree_state_dir_is_swept_rather_than_refused(self) -> None:
        owner, root, _ = self.make_fixture()
        self.addCleanup(owner.cleanup)
        (root / ".ember").mkdir()
        escaped = str(root).replace("'", "''")
        result = self.run_library_command(
            f"Assert-EmberStateIsExternal '{escaped}'; "
            f"Write-Output (Test-Path -LiteralPath (Join-Path '{escaped}' '.ember'))"
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("False", result.stdout)

    def test_state_root_guard_refuses_roots_a_census_would_read(self) -> None:
        # Writer-side and fail-closed, mirroring assertStateRootIsWritable in
        # src/ember/infrastructure/tools/ember-cli/src/utils/ember-state-root.ts. A verifier-only refusal finds the
        # regression at the NEXT census, by which time the run is already red.
        parent = r"C:\fixture"
        cases = [
            # (state root, named-root parent, expected verdict)
            (r"C:\fixture\ember\.ember", "", "REFUSED"),  # inside the checkout
            (r"C:\fixture\ember", "", "REFUSED"),  # the checkout itself
            (r"C:\fixture\ember-cockpit-state", parent, "REFUSED"),  # matches ember*
            (r"C:\fixture\ember-scratch\cockpit", parent, "REFUSED"),  # nested under a match
            (r"C:\fixture\wt-stab480-bench594-scratch", parent, "REFUSED"),  # literal pattern
            (r"C:\fixture\cockpit-state", parent, "OK"),  # the sanctioned name
            (r"C:\fixture\wt-stab480-bench594-scratch-2", parent, "OK"),  # prefix is not a match
            (r"C:\elsewhere\cockpit-state", "", "OK"),  # outside the parent entirely
        ]
        body = "; ".join(
            f"$env:EMBER_NAMED_ROOT_PARENT='{parent}'; "
            f"try {{ Assert-EmberStateRootIsWritable '{root}' 'C:\\fixture\\ember'; "
            "Write-Output 'OK' } catch { Write-Output 'REFUSED' }"
            for root, parent, _ in cases
        )
        result = self.run_library_command(body)
        self.assertEqual(result.returncode, 0, result.stdout)
        produced = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        self.assertEqual(produced, [expected for _, _, expected in cases], result.stdout)

    def test_in_tree_state_refusal_covers_every_entry_shape(self) -> None:
        # A junction pointing at the external root is the dangerous shape: the census walks
        # THROUGH it and hashes live cockpit state, so a compatibility shim would put the
        # contamination straight back. A plain file is refused for the same reason a
        # populated directory is — only a genuinely empty real directory may be swept.
        owner, root, _ = self.make_fixture()
        self.addCleanup(owner.cleanup)
        (root / ".ember").write_text("not a directory\n", encoding="utf-8")
        escaped = str(root).replace("'", "''")
        result = self.run_library_command(
            f"try {{ Assert-EmberStateIsExternal '{escaped}'; Write-Output 'ACCEPTED' }} "
            "catch { Write-Output $_.Exception.Message }"
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("ACCEPTED", result.stdout)
        self.assertIn("it is a file", result.stdout)

    def test_build_output_never_lands_inside_the_repository(self) -> None:
        # The build used to emit ember.exe beside the sources and then move it, putting a
        # transient writer inside the censused tree for the length of every build.
        implementation = LAUNCH_IMPL.read_text(encoding="utf-8")
        staging = LAUNCH_STAGING.read_text(encoding="utf-8")
        self.assertNotIn('Join-Path $sourceRoot "ember.exe"', implementation)
        # Staging is derived in one place, joined onto the state-root application dir,
        # and named so bun's forced win32 .exe suffix is a no-op (issue #1368) while
        # still not being the final Ember.exe.
        self.assertIn("$buildOutput = Get-EmberStagedBuildOutfile $applicationRoot", implementation)
        self.assertIn('Join-Path $ApplicationRoot "Ember.partial.exe"', staging)
        self.assertNotIn('"Ember.exe"', staging)
        self.assertIn("$env:EMBER_BUILD_OUTFILE = $buildOutput", implementation)
        # Publishing is write-partial-then-rename on the destination volume, moving the
        # artifact the build tool actually landed.
        self.assertLess(
            implementation.index("Get-EmberStagedBuildOutfile"),
            implementation.index("Move-Item -LiteralPath $stagedArtifact"),
        )

    def test_bun_package_cache_is_redirected_out_of_the_repository(self) -> None:
        implementation = LAUNCH_IMPL.read_text(encoding="utf-8")
        self.assertIn('$env:BUN_INSTALL_CACHE_DIR = Join-Path $stateRoot "bun-cache"', implementation)
        # node_modules cannot move (Bun resolves it by walking up from the importing file);
        # the launcher must say so out loud rather than let it look like steady state.
        self.assertIn("node_modules", implementation)

    def test_no_state_path_is_joined_onto_the_repository_root(self) -> None:
        # One resolution point: every state path derives from $stateRoot. A literal joined
        # onto the repository root is exactly the class this issue removed.
        implementation = LAUNCH_IMPL.read_text(encoding="utf-8")
        self.assertNotIn('Join-Path $repositoryRoot ".ember', implementation)
        self.assertNotIn('Join-Path $RepositoryRoot ".ember', implementation)
        self.assertIn("$env:EMBER_STATE_ROOT = $stateRoot", implementation)

    # -- issue #1330 secondary: a child that ran and exited is not a prepare failure --

    def test_child_exit_is_reported_as_an_exit_not_a_preparation_failure(self) -> None:
        owner, root, runtime = self.make_fixture()
        self.addCleanup(owner.cleanup)
        # Dependency preparation still succeeds — only the cockpit child fails, so the
        # message must not blame preparation.
        runtime.write_text(
            "@echo off\r\n"
            "if \"%1\"==\"install\" exit /b 0\r\n"
            "> \"%EMBER_LAUNCH_TEST_LOG%\" echo cwd=%CD%\r\n"
            "exit /b 3\r\n",
            encoding="utf-8",
        )
        result = self.run_launcher(root, runtime)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Ember CLI exited with code 3", result.stdout)
        self.assertNotIn("could not prepare its runtime", result.stdout)

    def test_production_entry_uses_only_the_governed_cockpit_command(self) -> None:
        implementation = LAUNCH_IMPL.read_text(encoding="utf-8")
        public = PUBLIC_LAUNCHER.read_text(encoding="utf-8")
        self.assertIn("Enter-EmberLauncherLease", implementation)
        self.assertNotIn("& $application", implementation)
        self.assertNotIn("Start-Process -FilePath $application", implementation)
        self.assertIn('"%EMBER_LAB%" cockpit', public)
        self.assertIn('--application "%EMBER_APPLICATION%"', public)

    def test_production_entry_parses_authority_and_invokes_exact_governed_argv(self) -> None:
        owner, root, _ = self.make_fixture()
        self.addCleanup(owner.cleanup)
        application = root / "dist" / "ember-cockpit.exe"
        state_root = root.parent / "governed state"
        source_commit = "a" * 40
        ember_lab = root / "fake-ember-lab.cmd"
        call_log = root / "governed-call.log"
        ember_lab.write_text(
            "@echo off\r\n"
            "> \"%EMBER_GOVERNED_CALL_LOG%\" echo %*\r\n"
            "exit /b 0\r\n",
            encoding="utf-8",
        )
        (root / "scripts" / "prepare-ember-cockpit.ps1").write_text(
            f'Write-Output "EMBER_APPLICATION={application}"\n'
            f'Write-Output "EMBER_LAB={ember_lab}"\n'
            f'Write-Output "EMBER_SOURCE_COMMIT={source_commit}"\n'
            f'Write-Output "EMBER_STATE_ROOT={state_root}"\n',
            encoding="utf-8",
        )
        env = os.environ.copy()
        env.update(
            {
                "EMBER_LAUNCH_NONINTERACTIVE": "1",
                "EMBER_GOVERNED_CALL_LOG": str(call_log),
            }
        )
        env.pop("EMBER_LAUNCH_TEST_MODE", None)
        result = subprocess.run(
            [
                "cmd.exe",
                "/d",
                "/c",
                str(root / "tools" / "launchers" / "Ember.cmd"),
            ],
            cwd=Path(tempfile.gettempdir()),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        actual = call_log.read_text(encoding="utf-8").strip()
        match = re.fullmatch(
            r'cockpit --root "(?P<root>.+\\)" --application "(?P<application>.+)" '
            r'--source-commit "(?P<source_commit>[^"]+)" --state-root "(?P<state_root>.+)"',
            actual,
        )
        self.assertIsNotNone(match, actual)
        assert match is not None
        self.assertTrue(match.group("root").endswith("\\"))
        self.assertEqual(
            canonical(match.group("root").removesuffix("\\")), canonical(root)
        )
        self.assertEqual(canonical(match.group("application")), canonical(application))
        self.assertEqual(match.group("source_commit"), source_commit)
        self.assertEqual(canonical(match.group("state_root")), canonical(state_root))

    def test_production_entry_names_preparation_failure_instead_of_closing_silently(self) -> None:
        owner, root, _ = self.make_fixture()
        self.addCleanup(owner.cleanup)
        (root / "scripts" / "prepare-ember-cockpit.ps1").write_text(
            'Write-Output "EMBER_APPLICATION=C:\\missing.exe"\n',
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["EMBER_LAUNCH_NONINTERACTIVE"] = "1"
        env.pop("EMBER_LAUNCH_TEST_MODE", None)
        result = subprocess.run(
            [
                "cmd.exe",
                "/d",
                "/c",
                str(root / "tools" / "launchers" / "Ember.cmd"),
            ],
            cwd=Path(tempfile.gettempdir()),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("Ember could not prepare the cockpit", result.stdout)


if __name__ == "__main__":
    unittest.main()
