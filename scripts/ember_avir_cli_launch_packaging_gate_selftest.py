#!/usr/bin/env python3
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import ember_avir_cli_launch_packaging_gate as gate


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    if not (shutil.which("powershell") or shutil.which("pwsh")):
        print("EMBER_AVIR_CLI_LAUNCH_PACKAGING_GATE_SELFTEST_SKIP_NO_POWERSHELL")
        return 0
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        launcher = repo / "tools" / "avir-launch" / "avir.ps1"
        entry = repo / "scripts" / "ember_avir_cli_launch_entry.py"
        backend = repo / "receipts" / "ember-preloop-resident-gate" / "backend.json"
        package_json = repo / "reference" / "package.json"
        avir_exe = repo / "reference" / "avir.exe"
        out = repo / "launch.json"

        _write(
            entry,
            """#!/usr/bin/env python3
import json
print(json.dumps({
  "status": "PASS",
  "resident_handoff": {
    "native_goal_organ": True,
    "slash_commands": True,
    "uiux_repl": True,
    "backend_coordinator_agents": True
  }
}))
""",
        )
        _write(
            launcher,
            """param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
python (Join-Path $repo "scripts\\ember_avir_cli_launch_entry.py") @Args
""",
        )
        _write(backend, json.dumps({"ticket": "EMBER-AVIR-CLI-BACKEND-COORDINATOR-AGENTS-GATE", "verdict": "BACKEND_COORDINATOR_AGENTS_GATE_PASS"}))
        _write(package_json, json.dumps({"name": "avir-cli", "bin": {"avir": "src/entrypoints/cli.tsx"}, "scripts": {"start": "bun run cli", "build": "bun build"}}))
        _write(avir_exe, "reference-binary-placeholder")

        receipt = gate.build_receipt(repo=repo, launcher=launcher, backend_receipt=backend, package_json=package_json, avir_exe=avir_exe, out=out)
        assert receipt["verdict"] == "LAUNCH_PACKAGING_GATE_PASS"
        assert receipt["verification"]["checks"]["launcher_executes"] is True
        assert receipt["verification"]["checks"]["handoff_reaches_all_resident_surfaces"] is True
        assert receipt["launch_packaging"]["uses_reference_avir_exe"] is False
        assert receipt["deletion_ablation"]["launcher_deleted_blocks_invocation"] is True
        assert receipt["deletion_ablation"]["package_metadata_alone_insufficient"] is True

    print("EMBER_AVIR_CLI_LAUNCH_PACKAGING_GATE_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
