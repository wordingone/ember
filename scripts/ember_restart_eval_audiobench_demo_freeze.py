#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Freeze deterministic AudioBench demo protocol bytes; never score capability."""
import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

SHA256 = re.compile(r"[0-9a-f]{64}")
SOURCE_COMMIT = "0fc7fef2709c00ac1e2eb2b372ec4c56362bb8c6"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def derived_protocol_sha256(split_sha256: str) -> str:
    return digest(f"audiobench-demo-procedural:{SOURCE_COMMIT}:{split_sha256}".encode("ascii"))


def atomic(path: Path, payload: dict) -> None:
    if path.exists():
        raise ValueError("frozen demo output must not pre-exist")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audiobench-root", type=Path, required=True)
    parser.add_argument("--protocol-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not SHA256.fullmatch(args.protocol_sha256):
        parser.error("protocol_sha256 must be lowercase SHA-256")
    root = args.audiobench_root
    paths = {
        "demo_pack": root / "src" / "audiobench" / "data" / "sound_id" / "packs" / "demo.json",
        "prompts": root / "src" / "audiobench" / "data" / "sound_id" / "prompts.yaml",
        "procedural": root / "src" / "audiobench" / "data" / "sound_id" / "procedural.py",
        "suite": root / "src" / "audiobench" / "suites" / "sound_id.py",
    }
    try:
        blobs = {role: path.read_bytes() for role, path in paths.items()}
        demo = json.loads(blobs["demo_pack"].decode("utf-8"))
        counts = demo.get("mixture_counts") if isinstance(demo, dict) else None
        if not isinstance(demo, dict) or demo.get("id") != "demo" or demo.get("source") != "procedural (bundled)" or demo.get("license") != "bundled" or demo.get("clip_resolver") != "procedural" or not isinstance(demo.get("labels"), list) or not demo["labels"] or not isinstance(counts, dict) or not counts or any(type(value) is not int or value <= 0 for value in counts.values()):
            raise ValueError("invalid bundled AudioBench demo pack")
        split = digest(b"\n".join(role.encode("utf-8") + b"\0" + blobs[role] for role in paths))
        files = [{"role": role, "bytes": len(blobs[role]), "sha256": digest(blobs[role])} for role in paths]
        atomic(args.output, {"goal_id": "EMBER-02", "workstream_id": "EMBER-02C", "next_executed_outcome": "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember", "schema_version": "ember-restart-audiobench-demo-freeze-v2", "result": "PREFLIGHT_ONLY", "claim_status": "SELFTEST_ONLY_PROCEDURAL_AUDIO", "benchmark_id": "audiobench-demo-procedural", "benchmark_version": SOURCE_COMMIT, "capability": "audio", "split_sha256": split, "protocol_sha256": derived_protocol_sha256(split), "source_files": files, "task_count": sum(counts.values())})
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        parser.error(f"invalid AudioBench demo source: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())