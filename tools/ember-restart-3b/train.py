# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Live clean-genesis launch caller: input identity reaches gate and validator."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from input_identity import build_launch_packet, emit_integration_receipt, validate_launch_packet


def _code_commit(repo_root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    value = completed.stdout.strip()
    if completed.returncode != 0 or len(value) != 40:
        raise RuntimeError("the live launch caller requires an exact Git commit")
    return value


def run_launch(
    *,
    repo_root: Path | None = None,
    input_identity_arg: str | None = None,
    code_commit: str | None = None,
) -> tuple[dict[str, Any], dict[str, str], dict[str, Any]]:
    """Resolve, forward, consume, and receipt the selected owned shard identity."""

    root = (repo_root or Path(__file__).resolve().parents[2]).resolve()
    config_path = root / "configs" / "ember-restart-3b.json"
    packet = build_launch_packet(
        repo_root=root,
        config_path=config_path,
        input_identity_arg=input_identity_arg,
    )
    validation = validate_launch_packet(packet, repo_root=root)
    receipt = emit_integration_receipt(
        packet,
        validation,
        code_commit=code_commit or _code_commit(root),
    )
    return packet, validation, receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the owned input identity for an Ember launch.")
    parser.add_argument("--input-identity", default=None, help="Repository-relative identity manifest; omit for the contract default.")
    parser.add_argument("--print-receipt", action="store_true", help="Print the path-free receipt JSON.")
    args = parser.parse_args(argv)
    _, validation, receipt = run_launch(input_identity_arg=args.input_identity)
    print(json.dumps(receipt if args.print_receipt else validation, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
