#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail closed unless target and pinned open comparator share evaluator pins."""
import argparse
import hashlib
import json
import re
from pathlib import Path

FIELDS = ("capability", "benchmark_id", "benchmark_version", "split_sha256", "harness_sha256", "protocol_sha256")
MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*")


def load(path: Path) -> tuple[bytes, object]:
    data = path.read_bytes()
    return data, json.loads(data.decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--comparator", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must not pre-exist")
    try:
        target_bytes, target = load(args.target)
        comparator_bytes, comparator = load(args.comparator)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        parser.error(f"invalid preflight JSON: {error}")
    for name, payload in (("target", target), ("comparator", comparator)):
        if not isinstance(payload, dict) or payload.get("result") != "PREFLIGHT_ONLY" or payload.get("admission") != "NOT_ELIGIBLE":
            parser.error(f"{name} must be a non-admissible evaluator preflight")
        if not isinstance(payload.get("subject_checkpoint_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", payload["subject_checkpoint_sha256"]):
            parser.error(f"{name} requires a checkpoint hash")
    if comparator.get("subject_kind") != "open_comparator" or not isinstance(comparator.get("comparator_model_id"), str) or MODEL_ID.fullmatch(comparator["comparator_model_id"]) is None or comparator.get("comparator_size_class") not in ("open_3b", "open_27b_or_31b") or not isinstance(comparator.get("comparator_revision"), str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", comparator["comparator_revision"]):
        parser.error("comparator requires pinned open identity and required size class")
    if target["subject_checkpoint_sha256"] == comparator["subject_checkpoint_sha256"]:
        parser.error("comparator must be a different checkpoint")
    for field in FIELDS:
        if target.get(field) != comparator.get(field) or not target.get(field):
            parser.error(f"target and comparator must share {field}")
    payload = {"result": "COMPARISON_PREFLIGHT", "admission": "NOT_ELIGIBLE", "comparator_model_id": comparator["comparator_model_id"], "target_preflight_sha256": hashlib.sha256(target_bytes).hexdigest(), "comparator_preflight_sha256": hashlib.sha256(comparator_bytes).hexdigest(), **{field: target[field] for field in FIELDS}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())