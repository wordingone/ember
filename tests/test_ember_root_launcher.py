# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
PUBLIC_LAUNCHER = REPOSITORY / "Ember.cmd"
LAUNCH_IMPL = REPOSITORY / "scripts" / "launch-ember-cli.ps1"
START_HERE = REPOSITORY / "docs" / "START-HERE.md"


class EmberRootLauncherTests(unittest.TestCase):
    def make_fixture(self) -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
        owner = tempfile.TemporaryDirectory(prefix="ember launcher ")
        root = Path(owner.name) / "Ember Repository With Spaces"
        (root / "scripts").mkdir(parents=True)
        source = root / "tools" / "ember-cli" / "src"
        (source / "entrypoints").mkdir(parents=True)
        shutil.copy2(PUBLIC_LAUNCHER, root / "Ember.cmd")
        shutil.copy2(LAUNCH_IMPL, root / "scripts" / "launch-ember-cli.ps1")
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
            }
        )
        if include_runtime:
            env["EMBER_LAUNCH_TEST_RUNTIME"] = str(runtime)
        else:
            env.pop("EMBER_LAUNCH_TEST_RUNTIME", None)
        return subprocess.run(
            ["cmd.exe", "/d", "/c", str(root / "Ember.cmd"), *arguments],
            cwd=Path(tempfile.gettempdir()),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
            check=False,
        )

    def test_public_launcher_and_implementation_are_visible(self) -> None:
        self.assertTrue(PUBLIC_LAUNCHER.is_file())
        self.assertTrue(LAUNCH_IMPL.is_file())
        documentation = START_HERE.read_text(encoding="utf-8")
        self.assertIn("repository root", documentation)
        self.assertIn("`Ember.cmd`", documentation)

    def test_no_argument_launch_discovers_repo_from_outside_and_handles_spaces(self) -> None:
        owner, root, runtime = self.make_fixture()
        self.addCleanup(owner.cleanup)
        result = self.run_launcher(root, runtime)
        self.assertEqual(result.returncode, 0, result.stdout)
        log = (root / "launch.log").read_text(encoding="utf-8")
        self.assertIn(f"cwd={root / 'tools' / 'ember-cli' / 'src'}", log)
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

    def test_production_path_builds_and_runs_a_commit_bound_executable(self) -> None:
        implementation = LAUNCH_IMPL.read_text(encoding="utf-8")
        self.assertIn("& $bun run build", implementation)
        self.assertIn('".ember\\runtime\\ember\\$commit"', implementation)
        self.assertIn('& $application', implementation)
        self.assertIn('$ErrorActionPreference = "Continue"', implementation)
        self.assertNotIn('$LASTEXITCODE -ne 0 -or $commit', implementation)
        self.assertNotIn('& $bun run entrypoints/main.ts\n    if ($LASTEXITCODE', implementation)
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
        result = self.run_library_command(
            "Get-EmberLeftHalfRectangle -Left -1920 -Top 40 -Right 0 -Bottom 1080 | ConvertTo-Json -Compress"
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('{"X":-1920,"Y":40,"Width":960,"Height":1040}', result.stdout)
        implementation = LAUNCH_IMPL.read_text(encoding="utf-8")
        self.assertIn("MonitorFromWindow", implementation)
        self.assertIn("SetWindowPos", implementation)
        self.assertIn("GetWindowRect", implementation)
        self.assertIn("FindVisibleWindowsByTitle", implementation)
        self.assertNotIn("0x0001", implementation)  # SWP_NOSIZE is forbidden.

    def test_owned_stale_process_filter_cannot_target_foreign_executables(self) -> None:
        root = r"C:\fixture\ember"
        result = self.run_library_command(
            "$owned=Test-IsOwnedEmberExecutablePath "
            f"'{root}\\.ember\\runtime\\ember\\abc\\Ember.exe' '{root}'; "
            "$foreign=Test-IsOwnedEmberExecutablePath 'C:\\Windows\\System32\\Ember.exe' "
            f"'{root}'; Write-Output \"$owned,$foreign\""
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

    def test_production_launcher_stays_in_one_shell_and_verifies_geometry(self) -> None:
        implementation = LAUNCH_IMPL.read_text(encoding="utf-8")
        self.assertIn("Enter-EmberLauncherLease", implementation)
        self.assertIn("Stop-StaleOwnedEmberApplications", implementation)
        self.assertIn("Set-EmberWindowToLeftWorkArea", implementation)
        self.assertIn("& $application", implementation)
        self.assertNotIn("Start-Process -FilePath $application", implementation)


if __name__ == "__main__":
    unittest.main()
