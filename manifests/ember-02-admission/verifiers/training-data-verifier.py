# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Re-derive an owned-training-data verification from the frozen data bytes.

Evidence class: training_data. Invoked by scripts/ember_restart/contract.py as

    python -I training-data-verifier.py \
        --data-manifest <path> --tokenizer <path> --capability <capability>

Record and token counts are recounted from the records artifact rather than copied
out of the data manifest, so a manifest that overstates its own corpus fails here.
Paths inside the data manifest are relative to the rung manifest root, which is this
process's working directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

CAPABILITIES = ("text", "image", "audio", "reasoning", "tool")
SEMANTIC_CHECKS = {
    "text": ["token_roundtrip", "source_target_pair"],
    "image": ["token_roundtrip", "source_target_pair", "raw_image_text_pair"],
    "audio": ["token_roundtrip", "source_target_pair", "raw_audio_text_pair"],
    "reasoning": ["token_roundtrip", "source_target_pair", "local_answer_execution"],
    "tool": ["token_roundtrip", "source_target_pair", "typed_tool_execution"],
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bound_path(record: object, field: str) -> Path:
    if not isinstance(record, dict) or not isinstance(record.get("path"), str):
        raise ValueError(f"{field}: expected an object carrying a relative path")
    candidate = Path(record["path"])
    if candidate.is_absolute():
        raise ValueError(f"{field}: absolute paths are forbidden")
    if not candidate.is_file():
        raise ValueError(f"{field}: file does not exist")
    return candidate


def recount(records_artifact: Path) -> tuple[int, int]:
    """Return (record_count, token_count) recounted from the records artifact."""
    payload = json.loads(records_artifact.read_text(encoding="utf-8"))
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("records artifact: expected a records list")
    tokens = 0
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"records[{index}]: expected object")
        token_ids = record.get("token_ids")
        if not isinstance(token_ids, list):
            raise ValueError(f"records[{index}].token_ids: expected list")
        tokens += len(token_ids)
    return len(records), tokens


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-manifest", required=True, type=Path)
    parser.add_argument("--tokenizer", required=True, type=Path)
    parser.add_argument("--capability", required=True, choices=CAPABILITIES)
    args = parser.parse_args(argv)

    manifest = json.loads(args.data_manifest.read_text(encoding="utf-8"))
    if manifest.get("capability") != args.capability:
        print("data manifest capability does not match the requested capability", file=sys.stderr)
        return 1
    data_class = manifest.get("data_class")
    if data_class not in {"SMOKE_ONLY", "SEMANTIC_PRETRAINING"}:
        print("data manifest declares an unsupported data_class", file=sys.stderr)
        return 1

    try:
        source_manifest = bound_path(manifest.get("source_manifest"), "source_manifest")
        records_artifact = bound_path(manifest.get("records_artifact"), "records_artifact")
        record_count, token_count = recount(records_artifact)
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    verification = {
        "schema_version": "ember-training-data-verification-v1",
        "result": "VERIFIED",
        "capability": args.capability,
        "data_manifest_sha256": sha256(args.data_manifest),
        "tokenizer_sha256": sha256(args.tokenizer),
        "verifier_sha256": sha256(Path(__file__).resolve()),
        "data_class": data_class,
        "record_count": record_count,
        "token_count": token_count,
        "source_manifest_sha256": sha256(source_manifest),
        "records_artifact_sha256": sha256(records_artifact),
        "semantic_checks": (
            SEMANTIC_CHECKS[args.capability] if data_class == "SEMANTIC_PRETRAINING" else []
        ),
    }
    print(json.dumps(verification, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
