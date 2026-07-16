#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Freeze private BFCL v4 simple prompt/oracle pairs from pinned source bytes."""
import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

CATEGORIES = ("simple_python", "simple_java", "simple_javascript")
SOURCE_COMMIT = "6ea57973c7a6097fd7c5915698c54c17c5b1b6c8"
SHA = re.compile(r"[0-9a-f]{64}")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def rows(data: bytes) -> list[dict]:
    parsed = [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]
    if not parsed or any(not isinstance(item, dict) for item in parsed):
        raise ValueError("BFCL source file must contain non-empty JSONL objects")
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--protocol-sha256", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not SHA.fullmatch(args.protocol_sha256):
        parser.error("protocol_sha256 must be lowercase SHA-256")
    if args.output.exists():
        parser.error("output must not pre-exist")
    try:
        files = []
        tasks = []
        for category in CATEGORIES:
            prompt_path = args.data_root / f"BFCL_v4_{category}.json"
            answer_path = args.data_root / "possible_answer" / f"BFCL_v4_{category}.json"
            prompt_bytes = prompt_path.read_bytes()
            answer_bytes = answer_path.read_bytes()
            prompts = rows(prompt_bytes)
            answers = rows(answer_bytes)
            if len(prompts) != len(answers):
                raise ValueError(f"BFCL {category} prompt/oracle counts differ")
            for prompt, answer in zip(prompts, answers):
                if not isinstance(prompt.get("id"), str) or not isinstance(prompt.get("function"), list) or not isinstance(prompt.get("question"), list) or prompt["id"] != answer.get("id") or not isinstance(answer.get("ground_truth"), list) or len(answer["ground_truth"]) != 1 or not isinstance(answer["ground_truth"][0], dict) or len(answer["ground_truth"][0]) != 1:
                    raise ValueError(f"BFCL {category} prompt/oracle pairing is invalid")
                tasks.append({"id": prompt["id"], "category": category, "functions": prompt["function"], "question": prompt["question"], "ground_truth": answer["ground_truth"]})
            files.extend(({"category": category, "role": "prompts", "bytes": len(prompt_bytes), "sha256": digest(prompt_bytes)}, {"category": category, "role": "possible_answers", "bytes": len(answer_bytes), "sha256": digest(answer_bytes)}))
        if len({task["id"] for task in tasks}) != len(tasks):
            raise ValueError("BFCL task ids must be unique")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        parser.error(f"invalid BFCL simple source: {error}")
    tree = digest(b"".join(f"{item['category']}\0{item['role']}\0{item['bytes']}\0{item['sha256']}\n".encode("utf-8") for item in files))
    payload = {"schema_version": "ember-restart-bfcl-simple-frozen-v1", "result": "PREFLIGHT_ONLY", "benchmark_id": "bfcl-static-simple", "benchmark_version": SOURCE_COMMIT, "capability": "tool", "split_sha256": tree, "protocol_sha256": args.protocol_sha256, "source_files": files, "task_count": len(tasks), "tasks": tasks}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=args.output.parent, delete=False) as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    try:
        os.replace(temporary, args.output)
    finally:
        temporary.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())