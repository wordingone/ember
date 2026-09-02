# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#1464 regression: the a1-dense-tier1 route must bind the canonical disk
budget runner authority the same way every other production route does, not
the unconditional-refusal stub (`require_disk_budget_runner_contract`).

Receipted defect: a certified run dispatched through the real
certified_train_launch -> disk_budget_runner chain (run
issue1464-e8-a1-20260821T1944Z) failed with exactly the stub's message even
though it was invoked as the canonical runner's own child, per the run's
own child receipt log:

    File ".../run_vertical_slice.py", line 4357, in main
        require_disk_budget_runner_contract()
    RuntimeError: vertical production launch requires the disk budget runner

Three legs:
  1. A property that holds unchanged across the fix: invoking the route
     without the canonical runner environment always refuses (base: the
     stub's unconditional RuntimeError; fixed: the same
     canonical_disk_budget_runner_authority() refusal every other route
     already binds -- both messages share "disk budget runner").
  2. In-process proof the fix's point holds: with a REAL canonical runner
     child environment (assertion file + nonce, built the way
     disk_budget_runner._child_cache_environment does), the route clears the
     runner gate and reaches the next real validation -- run_dense_a1's
     certified source identity check -- never the stub message.
  3. Real-path leg (real-path-closure): the actual disk_budget_runner.py
     subprocess wraps the actual `run_vertical_slice.py a1-dense-tier1`
     invocation end to end, with no CUDA allocation crossed.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest
import torch

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
TOOLS_DIR = ROOT / "tools" / "ember-restart-3b"
sys.path.insert(0, str(TOOLS_DIR))

import run_vertical_slice  # noqa: E402


def _a1_argv(
    *,
    artifact_root: Path,
    token_shards_receipt: Path,
    shards_root: Path,
    comparison_authority: Path,
    telemetry_path: Path,
    telemetry_run_id: str,
) -> list[str]:
    return [
        "run_vertical_slice.py", "a1-dense-tier1",
        "--seed", "83",
        "--artifact-root", str(artifact_root),
        "--token-shards-receipt", str(token_shards_receipt),
        "--shards-root", str(shards_root),
        "--comparison-authority", str(comparison_authority),
        "--steps", "1",
        "--sequence-length", "8",
        "--checkpoint-interval", "1",
        # Above the ~50.1 GiB full-state checkpoint floor for the real
        # ember-restart-3b-a1.json parameter count (3_839_344_640 params *
        # (2 model + 12 optimizer) bytes) so dense_a1_resource_preflight
        # clears the write-budget floor on the real host and the route
        # reaches run_dense_a1's own checks instead of stopping early on an
        # under-declared budget. transient/host-commit-reserve are kept
        # small (not the production 4/8 GiB) so the real
        # available_host_commit_bytes() on this dev host -- ~54.4 GiB,
        # measured, shared with everything else running here -- clears
        # required_commit_bytes (~42.9 GiB optimizer + these two) with
        # margin; this is a test-scratch budget, never a production one.
        "--write-budget-gib", "64",
        "--transient-checkpoint-gib", "2",
        "--host-commit-reserve-gib", "2",
        "--gpu-free-margin-gib", "4",
        "--b-custody-floor-gib", "8",
        "--telemetry-path", str(telemetry_path),
        "--telemetry-run-id", telemetry_run_id,
    ]


class A1RouteRunnerGateTests(unittest.TestCase):
    def test_a1_dense_tier1_refuses_without_canonical_runner_env_on_both_sides(self) -> None:
        """Leg 1: refusal-without-env is a property that must hold either
        side of the fix, so this pins the shared substring both the stub's
        unconditional message and canonical_disk_budget_runner_authority()'s
        own refusal carry, rather than one exact literal that only matches
        one side."""

        with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
            custody = Path(directory)
            with patch.dict(os.environ, {}, clear=True):
                with patch.object(
                    sys, "argv",
                    _a1_argv(
                        artifact_root=custody / "artifacts",
                        token_shards_receipt=custody / "missing-token-shards.json",
                        shards_root=custody / "missing-shards",
                        comparison_authority=custody / "missing-comparison.json",
                        telemetry_path=custody / "telemetry.jsonl",
                        telemetry_run_id="test-1464-no-env",
                    ),
                ):
                    with self.assertRaisesRegex(RuntimeError, "disk budget runner"):
                        run_vertical_slice.main()

    def test_a1_dense_tier1_with_real_canonical_runner_env_reaches_data_refusal_not_stub(self) -> None:
        """Leg 2: a real canonical-runner child environment (assertion file
        + nonce bound to the live cache env vars, exactly what
        disk_budget_runner._child_cache_environment constructs) clears the
        runner gate. Execution must reach run_dense_a1's certified source
        identity check -- the stub's message must never appear, and the
        governor is proven reached (it sits strictly after the runner gate
        in the a1-dense-tier1 branch)."""

        with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
            custody = Path(directory) / "custody"
            artifact_root = custody / "artifacts"
            artifact_root.mkdir(parents=True)
            cache = custody / "tmp"
            cache.mkdir(parents=True)
            bindings = {
                "TEMP": str(cache.resolve()), "TMP": str(cache.resolve()),
                "TORCH_HOME": str((custody / "torch").resolve()),
                "TRITON_CACHE_DIR": str((custody / "triton").resolve()),
                "CUDA_CACHE_PATH": str((custody / "cuda").resolve()),
                "HF_HOME": str((custody / "hf").resolve()),
                "XDG_CACHE_HOME": str((custody / "xdg-cache").resolve()),
            }
            for value in set(bindings.values()):
                Path(value).mkdir(parents=True, exist_ok=True)
            nonce = "c" * 32
            assertion = custody / "child-env-startup.json"
            assertion_bytes = json.dumps(
                {"schema_version": 1, "nonce": nonce, "bindings": bindings},
                sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")
            assertion.write_bytes(assertion_bytes)
            environment = {
                **bindings,
                "EMBER_DISK_BUDGET_ENV_ASSERTION": str(assertion),
                "EMBER_DISK_BUDGET_ENV_NONCE": nonce,
            }
            with patch.dict(os.environ, environment, clear=True):
                with patch.object(
                    sys, "argv",
                    _a1_argv(
                        artifact_root=artifact_root,
                        token_shards_receipt=custody / "missing-token-shards.json",
                        shards_root=custody / "missing-shards",
                        comparison_authority=custody / "missing-comparison.json",
                        telemetry_path=custody / "telemetry.jsonl",
                        telemetry_run_id="test-1464-real-env",
                    ),
                ):
                    with patch.object(
                        run_vertical_slice, "governed_resource_preflight",
                        return_value={"free_gb": 32.0},
                    ) as governor:
                        with patch.object(
                            run_vertical_slice.torch.cuda, "mem_get_info",
                            return_value=(32 * 1024**3, 32 * 1024**3),
                        ):
                            with self.assertRaisesRegex(
                                RuntimeError, "certified source identity is unavailable"
                            ):
                                run_vertical_slice.main()
                    governor.assert_called_once_with()

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason=(
            "real-path leg: the actual disk_budget_runner.py subprocess "
            "wraps the actual a1-dense-tier1 CLI, and that branch queries "
            "torch.cuda.mem_get_info() unconditionally (a query, not an "
            "allocation) strictly before the certified-source-identity "
            "refusal this test pins. CI's windows-latest runner carries no "
            "CUDA device, so this leg is dev-host-only; it was executed and "
            "receipted at PR authorship time on a CUDA-equipped host "
            "(residual risk priced in the PR body, real-path-closure clause 3)."
        ),
    )
    def test_real_disk_budget_runner_subprocess_reaches_data_refusal_past_the_runner_gate(self) -> None:
        """Leg 3 (real-path-closure): the first real downstream consumer of
        this route is disk_budget_runner.py itself -- the exact wrapper the
        receipted failing run went through. Execute it for real, wrapping
        the real run_vertical_slice.py a1-dense-tier1 invocation, and assert
        the stub message never reaches the runner receipt or the child's
        stderr while the real data refusal does."""

        runner_script = TOOLS_DIR / "disk_budget_runner.py"
        target_script = TOOLS_DIR / "run_vertical_slice.py"
        with tempfile.TemporaryDirectory(dir="B:/tmp") as directory:
            custody = Path(directory) / "custody"
            custody.mkdir(parents=True)
            artifact_root = custody / "artifacts"
            receipt_path = custody / "disk-budget-runner-receipt.json"
            environment = os.environ.copy()
            for stale in (
                "EMBER_A1_SOURCE_COMMIT", "EMBER_A1_CERTIFIED_LAUNCH_SHA256",
                "EMBER_DISK_BUDGET_ENV_ASSERTION", "EMBER_DISK_BUDGET_ENV_NONCE",
            ):
                environment.pop(stale, None)
            a1_argv = _a1_argv(
                artifact_root=artifact_root,
                token_shards_receipt=custody / "missing-token-shards.json",
                shards_root=custody / "missing-shards",
                comparison_authority=custody / "missing-comparison.json",
                telemetry_path=custody / "telemetry.jsonl",
                telemetry_run_id="test-1464-real-disk-budget-runner",
            )[1:]  # drop the argv[0] placeholder; the real command owns its own
            command = [
                sys.executable, str(runner_script),
                "--max-write-gib", "0.05",
                "--receipt", str(receipt_path),
                "--write-root", f"custody={custody}",
                "--",
                sys.executable, str(target_script), *a1_argv,
            ]
            result = subprocess.run(
                command, env=environment, capture_output=True, text=True, timeout=180,
            )
            self.assertNotIn(
                "vertical production launch requires the disk budget runner",
                result.stderr,
            )
            self.assertIn("certified source identity is unavailable", result.stderr)
            self.assertNotEqual(result.returncode, 0)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["outcome"], "CHILD_FAILED")
            self.assertIsNone(receipt["child_cache_assertion_error"])


if __name__ == "__main__":
    unittest.main()
