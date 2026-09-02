#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Execute every protected E-RELEASE row locally and emit a redacted immutable bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any


ROWS = (
    "E-MATRIX-TEXT-LANGUAGE", "E-MATRIX-IMAGE", "E-MATRIX-AUDIO",
    "E-MATRIX-IMAGE-TEXT", "E-MATRIX-AUDIO-TEXT", "E-MATRIX-IMAGE-AUDIO-TEXT",
    "E-MATRIX-REASONING", "E-MATRIX-TOOL-USE", "E-MATRIX-ROUTING-PATHWAY",
)
FORBIDDEN_KEYS = {"gold", "answer", "reference", "gold_bytes", "protected_bytes", "reference_bytes"}
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class ReleaseExecutionRefusal(ValueError):
    pass


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_self(value: dict[str, Any], label: str) -> None:
    body = dict(value)
    claimed = body.pop("self_sha256", None)
    if claimed != sha(canonical(body)):
        raise ReleaseExecutionRefusal(f"SELF_HASH_DRIFT:{label}")


def forbid_protected_bytes(value: object, path: str = "bundle") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in FORBIDDEN_KEYS:
                raise ReleaseExecutionRefusal(f"PROTECTED_BYTES_IN_BUNDLE:{path}.{key}")
            forbid_protected_bytes(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            forbid_protected_bytes(child, f"{path}[{index}]")


def validate_row(row: object, row_id: str) -> dict[str, Any]:
    if not isinstance(row, dict) or row.get("row_id") != row_id:
        raise ReleaseExecutionRefusal(f"ROW_IDENTITY_DRIFT:{row_id}")
    items = row.get("items")
    if not isinstance(items, list) or not items:
        raise ReleaseExecutionRefusal(f"EMPTY_ROW:{row_id}")
    forbid_protected_bytes(row, row_id)
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {"item_id", "gold_item_sha256", "prediction", "score"}:
            raise ReleaseExecutionRefusal(f"ITEM_SCHEMA_DRIFT:{row_id}")
        item_id = item["item_id"]
        digest = item["gold_item_sha256"]
        if not isinstance(item_id, str) or not item_id or item_id in seen:
            raise ReleaseExecutionRefusal(f"ITEM_ID_DRIFT:{row_id}")
        if not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
            raise ReleaseExecutionRefusal(f"GOLD_ITEM_HASH_DRIFT:{row_id}:{item_id}")
        if not isinstance(item["score"], (int, float)) or isinstance(item["score"], bool):
            raise ReleaseExecutionRefusal(f"ITEM_SCORE_DRIFT:{row_id}:{item_id}")
        if not math.isfinite(float(item["score"])):
            raise ReleaseExecutionRefusal(f"ITEM_SCORE_NONFINITE:{row_id}:{item_id}")
        seen.add(item_id)
    return row


def execute(
    spec: dict[str, Any],
    preflight: dict[str, Any],
    output: Path,
    *,
    spec_raw_sha256: str,
) -> dict[str, Any]:
    if preflight.get("result") != "PASS" or preflight.get("schema_version") != "ember-issue1947-release-tier-preflight-v1":
        raise ReleaseExecutionRefusal("PREFLIGHT_NOT_PASS")
    verify_self(preflight, "preflight")
    tiers = preflight.get("tiers")
    release_tiers = (
        [row for row in tiers if isinstance(row, dict) and row.get("tier") == "release"]
        if isinstance(tiers, list)
        else []
    )
    if len(release_tiers) != 1 or not isinstance(release_tiers[0].get("execution_spec"), dict):
        raise ReleaseExecutionRefusal("EXECUTION_SPEC_AUTHORITY_MISSING")
    binding = release_tiers[0]["execution_spec"]
    if binding.get("raw_sha256") != spec_raw_sha256:
        raise ReleaseExecutionRefusal("EXECUTION_SPEC_RAW_HASH_DRIFT")
    if spec.get("schema_version") != "ember-issue1947-release-execution-spec-v1":
        raise ReleaseExecutionRefusal("EXECUTION_SPEC_SCHEMA_DRIFT")
    verify_self(spec, "execution_spec")
    if binding.get("self_sha256") != spec.get("self_sha256"):
        raise ReleaseExecutionRefusal("EXECUTION_SPEC_SELF_HASH_BINDING_DRIFT")
    rows = spec.get("rows")
    if not isinstance(rows, list) or tuple(row.get("row_id") for row in rows if isinstance(row, dict)) != ROWS:
        raise ReleaseExecutionRefusal("MISSING_DUPLICATE_EXTRA_OR_REORDERED_MATRIX_ROW")
    for spec_row in rows:
        row_id = spec_row["row_id"]
        command = spec_row.get("command")
        result_path = spec_row.get("result_path")
        threshold = spec_row.get("threshold")
        if not isinstance(command, list) or not command or not all(isinstance(value, str) and value for value in command):
            raise ReleaseExecutionRefusal(f"RUNNER_COMMAND_DRIFT:{row_id}")
        if not isinstance(result_path, str) or not result_path:
            raise ReleaseExecutionRefusal(f"ROW_RESULT_PATH_DRIFT:{row_id}")
        if not isinstance(threshold, (int, float)) or isinstance(threshold, bool):
            raise ReleaseExecutionRefusal(f"THRESHOLD_DRIFT:{row_id}")
        if not math.isfinite(float(threshold)):
            raise ReleaseExecutionRefusal(f"THRESHOLD_NONFINITE:{row_id}")
    output.mkdir(parents=True, exist_ok=False)
    row_bindings = []
    for spec_row in rows:
        row_id = spec_row["row_id"]
        command = spec_row.get("command")
        result_path = Path(spec_row.get("result_path", ""))
        if result_path.exists():
            raise ReleaseExecutionRefusal(f"ROW_RESULT_EXISTS_REFUSED:{row_id}")
        completed = subprocess.run(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=NO_WINDOW, check=False,
        )
        if completed.returncode:
            raise ReleaseExecutionRefusal(f"ROW_EXECUTION_REFUSED:{row_id}:{completed.returncode}")
        row = validate_row(load(result_path), row_id)
        row["self_sha256"] = sha(canonical(row))
        raw = json.dumps(row, indent=2, sort_keys=True).encode() + b"\n"
        destination = output / f"{row_id}.json"
        with destination.open("xb") as stream:
            stream.write(raw)
        threshold = spec_row.get("threshold")
        row_bindings.append({"row_id": row_id, "path": destination.name, "bytes": len(raw), "raw_sha256": sha(raw), "self_sha256": row["self_sha256"], "threshold": float(threshold)})
    bundle = {
        "schema_version": "ember-issue1947-redacted-release-bundle-v1",
        "result": "COMPLETE",
        "designation_manifest_raw_sha256": preflight["checkpoint_manifest"]["raw_sha256"],
        "matrix_self_sha256": preflight["matrix"]["self_sha256"],
        "analysis_self_sha256": preflight["analysis"]["self_sha256"],
        "execution_spec_raw_sha256": spec_raw_sha256,
        "execution_spec_self_sha256": spec["self_sha256"],
        "rows": row_bindings,
        "protected_bytes_present": False,
        "claim_boundary": "RAW_ROW_EXECUTION_BUNDLE_ONLY; NO CERT ISSUE_OR_GOAL_CREDIT",
    }
    bundle["self_sha256"] = sha(canonical(bundle))
    with (output / "release-bundle.json").open("xb") as stream:
        stream.write(json.dumps(bundle, indent=2, sort_keys=True).encode() + b"\n")
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execution-spec", type=Path, required=True)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    spec_raw = args.execution_spec.read_bytes()
    bundle = execute(
        json.loads(spec_raw),
        load(args.preflight),
        args.output,
        spec_raw_sha256=sha(spec_raw),
    )
    print(json.dumps({"result": bundle["result"], "self_sha256": bundle["self_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
