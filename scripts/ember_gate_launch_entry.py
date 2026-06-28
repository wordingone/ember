#!/usr/bin/env python3
"""Clean-room Ember resident launch entrypoint.

This is a deliberately small executable surface: resolve the repo, verify the
resident goal/command/UI/backend receipts that make the harness usable, and emit
a machine-readable handshake. It is not a copy of the predecessor CLI's TypeScript entry.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_RECEIPTS = {
    "native_goal_organ": Path("receipts/ember-preloop-resident-gate/native-goal-organ-20260621T195504Z.json"),
    "function_slash_commands": Path("receipts/ember-preloop-resident-gate/function-slash-commands-20260621T221454Z.json"),
    "uiux_repl_components": Path("receipts/ember-preloop-resident-gate/uiux-repl-components-20260621T222342Z.json"),
    "backend_coordinator_agents": Path("receipts/ember-preloop-resident-gate/backend-coordinator-agents-20260621T224002Z.json"),
}

EXPECTED_VERDICTS = {
    "native_goal_organ": "NATIVE_GOAL_ORGAN_PASS",
    "function_slash_commands": "FUNCTION_SLASH_COMMANDS_GATE_PASS",
    "uiux_repl_components": "UIUX_REPL_COMPONENTS_GATE_PASS",
    "backend_coordinator_agents": "BACKEND_COORDINATOR_AGENTS_GATE_PASS",
}


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}


def resolve_surfaces(repo: Path) -> dict[str, Any]:
    surfaces: dict[str, Any] = {}
    for surface_id, rel in REQUIRED_RECEIPTS.items():
        path = repo / rel
        data = load_json(path)
        verdict = data.get("verdict")
        surfaces[surface_id] = {
            "path": str(path),
            "exists": path.exists(),
            "verdict": verdict,
            "status": "PASS" if verdict == EXPECTED_VERDICTS[surface_id] else "BLOCKED",
        }
    return surfaces


def build_handshake(repo: Path, argv: list[str]) -> dict[str, Any]:
    surfaces = resolve_surfaces(repo)
    return {
        "launcher": "ember_gate_launch_entry",
        "repo": str(repo),
        "argv": argv,
        "bin_name": "ember",
        "entrypoint": str(Path(__file__).resolve()),
        "resident_handoff": {
            "native_goal_organ": surfaces["native_goal_organ"]["status"] == "PASS",
            "slash_commands": surfaces["function_slash_commands"]["status"] == "PASS",
            "uiux_repl": surfaces["uiux_repl_components"]["status"] == "PASS",
            "backend_coordinator_agents": surfaces["backend_coordinator_agents"]["status"] == "PASS",
        },
        "surfaces": surfaces,
        "status": "PASS" if all(row["status"] == "PASS" for row in surfaces.values()) else "BLOCKED",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=str(repo_root()))
    parser.add_argument("--handshake", action="store_true")
    parser.add_argument("args", nargs="*")
    ns = parser.parse_args()
    repo = Path(ns.repo).resolve()
    handshake = build_handshake(repo, ns.args)
    print(json.dumps(handshake, indent=2))
    return 0 if handshake["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
