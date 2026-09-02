#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import ember_gate_launch_packaging as gate


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    if not (shutil.which("powershell") or shutil.which("pwsh")):
        print("EMBER_GATE_LAUNCH_PACKAGING_SELFTEST_SKIP_NO_POWERSHELL")
        return 0
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        launcher = repo / "tools" / "reference-launch" / "launch.ps1"
        entry = repo / "scripts" / "ember_gate_launch_entry.py"
        backend = repo / "receipts" / "ember-preloop-resident-gate" / "backend.json"
        package_json = repo / "reference" / "package.json"
        reference_exe = repo / "reference" / "predecessor-cli.exe"
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
python (Join-Path $repo "scripts\\ember_gate_launch_entry.py") @Args
""",
        )
        _write(backend, json.dumps({"ticket": "EMBER-GATE-BACKEND-COORDINATOR-AGENTS", "verdict": "BACKEND_COORDINATOR_AGENTS_GATE_PASS"}))
        _write(package_json, json.dumps({"name": "the predecessor CLI", "bin": {"ember": "src/entrypoints/cli.tsx"}, "scripts": {"start": "bun run cli", "build": "bun build"}}))
        _write(reference_exe, "reference-binary-placeholder")

        receipt = gate.build_receipt(repo=repo, launcher=launcher, backend_receipt=backend, package_json=package_json, reference_exe=reference_exe, out=out)
        assert receipt["verdict"] == "LAUNCH_PACKAGING_GATE_PASS"
        assert receipt["verification"]["checks"]["launcher_executes"] is True
        assert receipt["verification"]["checks"]["handoff_reaches_all_resident_surfaces"] is True
        assert receipt["launch_packaging"]["uses_reference_exe"] is False
        assert receipt["deletion_ablation"]["launcher_deleted_blocks_invocation"] is True
        assert receipt["deletion_ablation"]["package_metadata_alone_insufficient"] is True

    print("EMBER_GATE_LAUNCH_PACKAGING_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
