# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Independently verify one owned semantic text training-data manifest."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

SEMANTIC_CHECKS = {
    "text": ["token_roundtrip", "source_target_pair"],
    "reasoning": ["token_roundtrip", "source_target_pair", "local_answer_execution"],
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bound_file(root: Path, record: object, name: str) -> Path:
    if not isinstance(record, Mapping):
        raise ValueError(f"{name} must be a path and sha256 record")
    relative = record.get("path")
    expected = record.get("sha256")
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError(f"{name} path must be nonempty and relative")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError(f"{name} sha256 is malformed")
    path = (root / relative).resolve()
    if root not in path.parents or not path.is_file():
        raise ValueError(f"{name} path escapes verifier root")
    if _sha256(path) != expected:
        raise ValueError(f"{name} sha256 does not match")
    return path


def _load_json(path: Path, name: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{name} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{name} must be an object")
    return payload


def verify(data_path: Path, tokenizer_path: Path, capability: str, *, root: Path) -> dict[str, Any]:
    if capability not in SEMANTIC_CHECKS:
        raise ValueError("unsupported semantic capability")
    data_path = data_path.resolve()
    if root not in data_path.parents:
        raise ValueError("data manifest escapes verifier root")
    data = _load_json(data_path, "data manifest")
    if data.get("schema_version") != "ember-owned-training-data-v1":
        raise ValueError("data manifest schema is invalid")
    if data.get("capability") != capability or data.get("data_class") != "SEMANTIC_PRETRAINING":
        raise ValueError("data manifest capability or class is invalid")
    if data.get("model_mediated") is not False or data.get("borrowed_labels") is not False:
        raise ValueError("data manifest provenance is invalid")
    tokenizer_hash = _sha256(tokenizer_path)
    if data.get("tokenizer_sha256") != tokenizer_hash:
        raise ValueError("data manifest tokenizer sha256 does not match")
    source_path = _bound_file(root, data.get("source_manifest"), "source manifest")
    records_path = _bound_file(root, data.get("records_artifact"), "records artifact")
    source = _load_json(source_path, "source manifest")
    if (
        source.get("schema_version") != "ember-owned-source-v1"
        or source.get("capability") != capability
        or source.get("model_mediated") is not False
        or source.get("borrowed_labels") is not False
    ):
        raise ValueError("source manifest provenance is invalid")
    tokenizer = _load_json(tokenizer_path, "tokenizer")
    vocab = tokenizer.get("model", {}).get("vocab") if isinstance(tokenizer.get("model"), dict) else None
    if not isinstance(vocab, dict) or not vocab:
        raise ValueError("tokenizer does not declare a vocabulary")
    vocab_size = max(vocab.values()) + 1 if all(isinstance(value, int) and value >= 0 for value in vocab.values()) else 0
    if vocab_size <= 0:
        raise ValueError("tokenizer vocabulary is invalid")
    records_payload = _load_json(records_path, "records artifact")
    records = records_payload.get("records")
    if records_payload.get("schema_version") != "ember-owned-semantic-records-v1" or not isinstance(records, list) or not records:
        raise ValueError("semantic records artifact is invalid")
    token_count = 0
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError("semantic record is invalid")
        token_ids, target_ids = record.get("token_ids"), record.get("target_ids")
        if (
            not isinstance(token_ids, list)
            or not isinstance(target_ids, list)
            or not token_ids
            or len(token_ids) != len(target_ids)
            or any(not isinstance(token, int) or token < 0 or token >= vocab_size for token in [*token_ids, *target_ids])
            or target_ids[:-1] != token_ids[1:]
        ):
            raise ValueError("semantic record does not satisfy token roundtrip and source-target pairing")
        if capability == "reasoning":
            if record.get("active_expert") != "reasoning":
                raise ValueError("reasoning semantic record must route to the reasoning expert")
            encoded = base64.b64encode(json.dumps(dict(record), sort_keys=True, separators=(",", ":")).encode("utf-8")).decode("ascii")
            completed = subprocess.run([sys.executable, "-I", str(Path(__file__).with_name("verify_capability_record.py")), "--record-json-base64", encoded], text=True, capture_output=True, timeout=15, check=False)
            if completed.returncode != 0:
                raise ValueError("reasoning semantic record local verifier failed")
            result = json.loads(completed.stdout)
            if not isinstance(result, dict) or result.get("result") != "PASSED" or not isinstance(result.get("receipt"), dict):
                raise ValueError("reasoning semantic record lacks an executed local receipt")
        token_count += len(token_ids)
    if data.get("record_count") != len(records) or data.get("token_count") != token_count:
        raise ValueError("data manifest counts do not match verified semantic records")
    return {
        "schema_version": "ember-training-data-verification-v1",
        "result": "VERIFIED",
        "capability": capability,
        "data_manifest_sha256": _sha256(data_path),
        "tokenizer_sha256": tokenizer_hash,
        "verifier_sha256": _sha256(Path(__file__)),
        "data_class": "SEMANTIC_PRETRAINING",
        "record_count": len(records),
        "token_count": token_count,
        "source_manifest_sha256": _sha256(source_path),
        "records_artifact_sha256": _sha256(records_path),
        "semantic_checks": SEMANTIC_CHECKS[capability],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-manifest", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--capability", required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(verify(args.data_manifest, args.tokenizer, args.capability, root=Path.cwd().resolve()), sort_keys=True))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

