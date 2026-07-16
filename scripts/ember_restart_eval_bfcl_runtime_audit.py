#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed audit of BFCL runtime reproducibility; never runs BFCL."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

COMMIT = re.compile(r"[0-9a-f]{40}")
SHA256 = re.compile(r"#sha256=[0-9a-f]{64}\b")
DEPENDENCY = re.compile(r'["\']([^"\']+)["\']')
DEPENDENCY_BLOCK = re.compile(r'(?m)^dependencies\s*=\s*\[(.*?)\]', re.DOTALL)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bfcl-root", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        parser.error("output must not pre-exist")
    if not COMMIT.fullmatch(arguments.expected_commit):
        parser.error("expected commit must be lowercase sha1")
    try:
        project = arguments.bfcl_root / "berkeley-function-call-leaderboard" / "pyproject.toml"
        web_search = arguments.bfcl_root / "berkeley-function-call-leaderboard" / "bfcl_eval" / "eval_checker" / "multi_turn_eval" / "func_source_code" / "web_search.py"
        required = (arguments.bfcl_root / "LICENSE", project, web_search)
        if not arguments.bfcl_root.is_dir() or any(not path.is_file() for path in required):
            raise ValueError("pinned BFCL source is incomplete")
        actual = subprocess.run(["git", "-C", str(arguments.bfcl_root), "rev-parse", "HEAD"], text=True, capture_output=True, timeout=10, check=False)
        if actual.returncode or actual.stdout.strip() != arguments.expected_commit:
            raise ValueError("BFCL source commit does not match expected commit")
        project_bytes = project.read_bytes()
        web_bytes = web_search.read_bytes()
        dependency_block = DEPENDENCY_BLOCK.search(project_bytes.decode("utf-8"))
        if dependency_block is None:
            raise ValueError("BFCL pyproject requires a dependencies list")
        dependencies = DEPENDENCY.findall(dependency_block.group(1))
        mutable = sorted(item for item in dependencies if not SHA256.search(item))
        live_network = any(marker in web_bytes for marker in (b"requests.", b"urllib.request.", b"httpx.", b"aiohttp.", b"http://", b"https://"))
    except (OSError, UnicodeDecodeError, subprocess.SubprocessError, ValueError) as error:
        parser.error(str(error))
    payload = {
        "schema_version": "ember-restart-bfcl-runtime-audit-v1",
        "result": "PREFLIGHT_ONLY",
        "claim_status": "RUNTIME_HELD_UNPINNED_DEPENDENCY_AND_LIVE_TOOL_NETWORK",
        "benchmark_id": "bfcl",
        "source_commit": arguments.expected_commit,
        "pyproject_sha256": sha256(project_bytes),
        "web_search_sha256": sha256(web_bytes),
        "mutable_dependencies": mutable,
        "live_network_tool_source": live_network,
        "target_execution_permitted": False,
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=arguments.output.parent, prefix=arguments.output.name + ".", suffix=".tmp", delete=False) as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
        temporary = Path(handle.name)
    try:
        os.replace(temporary, arguments.output)
    finally:
        temporary.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
