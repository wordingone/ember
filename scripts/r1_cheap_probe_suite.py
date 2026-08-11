#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Build and admit the single #1498 R1/R2 cheap-probe suite authority.

The source manifest is derived only from already-frozen MMLU-Pro and
ARC-Challenge JSONL bytes after applying the accepted A1 exclusions.  It is
text-native so the R1 owned endpoint can execute it directly.  R2 token IDs
are a deterministic compilation whose identity binds the source manifest,
tokenizer, and compiler hashes; they are never an independent probe authority.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any


SUITE_SCHEMA = "ember02-r1-r2-cheap-probe-suite/v1"
SELECTION_ALGORITHM = "lowest-sha256(selection-domain||raw-row-bytes)/v1"
SELECTION_DOMAINS = {
    "MMLU-Pro": "ember02-r1-r2-cheap-probe-v1\0MMLU-Pro\0",
    "ARC-Challenge": "ember02-r1-r2-cheap-probe-v1\0ARC-Challenge\0",
}
FROZEN_SOURCE_SHA256S = {
    "MMLU-Pro": "5fdd1b7583302292e6d71ecf27cec521ad532bf24773beed7c5f9fd382a1b8f5",
    "ARC-Challenge": "c0e7635ee91b9ca47bf388f1f6cd5140fda083a71dccda44de72c364645df3f3",
}
FROZEN_EFFECTIVE_SHA256S = {
    "MMLU-Pro": "2ba1c758081f09317c86ad0c3f183596d4519cfef4dfdbaed04280929bef3627",
    "ARC-Challenge": "c0e7635ee91b9ca47bf388f1f6cd5140fda083a71dccda44de72c364645df3f3",
}
FROZEN_EXCLUSION_SHA256 = "9f4b11c82cd757429456c0d0a91797227c4aea6f943689852d6070b97249981c"
FROZEN_SUITE_SHA256 = "b08073b505581bd4cc634f9ca5c3a872755de867db26dd83fe27406f858288a3"
_DIGEST_CHARS = frozenset("0123456789abcdef")
_TOP_KEYS = {
    "schema",
    "issue",
    "suite_id",
    "selection",
    "runtime_mode",
    "tool_access",
    "context_limit_tokens",
    "output_budget_tokens",
    "retry_policy",
    "contamination_policy",
    "sources",
    "exclusions",
    "policy_sha256",
    "thresholds",
    "probes",
    "probes",
    "tasks",
    "claim_boundary",
}
_TASK_KEYS = {
    "row_id",
    "dataset",
    "probe_id",
    "source_row_index",
    "source_row_sha256",
    "selection_sha256",
    "prompt",
    "choice_labels",
    "choices",
    "correct_choice_index",
    "expected_output",
    "judge",
    "max_output_tokens",
}
_PROBES = {
    "MMLU-Pro": ("mmlu-pro-10choice", 10),
    "ARC-Challenge": ("arc-challenge-4choice", 4),
}
_PROBE_ROWS = [
    {
        "probe_id": "mmlu-pro-10choice",
        "dataset": "MMLU-Pro",
        "metric_type": "proportion",
        "judge": "exact_choice_label_v1",
        "cardinality": 10,
        "chance_rate": 0.1,
        "n_items": 32,
    },
    {
        "probe_id": "arc-challenge-4choice",
        "dataset": "ARC-Challenge",
        "metric_type": "proportion",
        "judge": "exact_choice_label_v1",
        "cardinality": 4,
        "chance_rate": 0.25,
        "n_items": 32,
    },
]
_PROBE_KEYS = {
    "probe_id",
    "dataset",
    "metric_type",
    "judge",
    "cardinality",
    "chance_rate",
    "n_items",
}


class SuiteRefusal(ValueError):
    """Named fail-closed suite admission error."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in _DIGEST_CHARS for character in value)
    )


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _decode_json(raw: bytes, refusal: str) -> Any:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SuiteRefusal(refusal) from exc


def _jsonl(raw: bytes, dataset: str) -> list[tuple[int, bytes, dict]]:
    rows: list[tuple[int, bytes, dict]] = []
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SuiteRefusal(f"SOURCE_SCHEMA_INVALID:{dataset}") from exc
    for index, line in enumerate(text.splitlines()):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SuiteRefusal(f"SOURCE_SCHEMA_INVALID:{dataset}:{index}") from exc
        if not isinstance(row, dict):
            raise SuiteRefusal(f"SOURCE_SCHEMA_INVALID:{dataset}:{index}")
        rows.append((index, line.encode("utf-8"), row))
    return rows


def _format_prompt(question: str, labels: list[str], choices: list[str]) -> str:
    rendered = "\n".join(f"{label}. {choice}" for label, choice in zip(labels, choices))
    return (
        f"Question: {question}\nChoices:\n{rendered}\n"
        f"Answer with exactly one letter from {labels[0]} through {labels[-1]}.\nAnswer:"
    )


def _task(dataset: str, source_index: int, raw_line: bytes, row: dict) -> dict:
    probe_id, cardinality = _PROBES[dataset]
    if dataset == "MMLU-Pro":
        question = row.get("question")
        choices = row.get("options")
        labels = list("ABCDEFGHIJ")
        correct = row.get("answer_index")
        native = row.get("question_id")
        row_id = f"mmlu-pro:{native}"
        if row.get("answer") != (labels[correct] if isinstance(correct, int) and 0 <= correct < len(labels) else None):
            raise SuiteRefusal(f"SOURCE_ANSWER_INVALID:{dataset}:{source_index}")
    else:
        question = row.get("question")
        choice_block = row.get("choices")
        choices = choice_block.get("text") if isinstance(choice_block, dict) else None
        labels = choice_block.get("label") if isinstance(choice_block, dict) else None
        answer = row.get("answerKey")
        native = row.get("id")
        row_id = f"arc-challenge:{native}"
        correct = labels.index(answer) if isinstance(labels, list) and answer in labels else None
    if (
        not isinstance(question, str)
        or not question
        or not isinstance(choices, list)
        or not all(isinstance(choice, str) and choice for choice in choices)
        or not isinstance(labels, list)
        or not all(isinstance(label, str) and len(label) == 1 for label in labels)
        or len(choices) != cardinality
        or len(labels) != cardinality
        or len(set(labels)) != cardinality
        or not isinstance(correct, int)
        or isinstance(correct, bool)
        or not 0 <= correct < cardinality
        or not isinstance(native, (str, int))
    ):
        raise SuiteRefusal(f"SOURCE_SCHEMA_INVALID:{dataset}:{source_index}")
    return {
        "row_id": row_id,
        "dataset": dataset,
        "probe_id": probe_id,
        "source_row_index": source_index,
        "source_row_sha256": _sha(raw_line),
        "prompt": _format_prompt(question, labels, choices),
        "choice_labels": labels,
        "choices": choices,
        "correct_choice_index": correct,
        "expected_output": labels[correct],
        "judge": "exact_choice_label_v1",
        "max_output_tokens": 4,
    }


def _validate_manifest(document: object) -> dict:
    if not isinstance(document, dict) or set(document) != _TOP_KEYS:
        raise SuiteRefusal("SUITE_SCHEMA_INVALID")
    policy = {
        "runtime_mode": document.get("runtime_mode"),
        "tool_access": document.get("tool_access"),
        "context_limit_tokens": document.get("context_limit_tokens"),
        "output_budget_tokens": document.get("output_budget_tokens"),
        "retry_policy": document.get("retry_policy"),
        "contamination_policy": document.get("contamination_policy"),
    }
    if (
        document.get("schema") != SUITE_SCHEMA
        or document.get("issue") != 1498
        or document.get("suite_id") != "ember02-r1-r2-cheap-probe-v1"
        or document.get("selection") != {"algorithm": SELECTION_ALGORITHM, "domains": SELECTION_DOMAINS}
        or policy != {
            "runtime_mode": "FROZEN_EVAL",
            "tool_access": "NONE",
            "context_limit_tokens": 4096,
            "output_budget_tokens": 4,
            "retry_policy": {"max_attempts": 1, "retry_on": []},
            "contamination_policy": {
                "authority": "a1-freeze-exclusion-amendment/v1",
                "contaminated_items_remaining": 0,
            },
        }
        or document.get("policy_sha256") != _sha(_canonical_bytes(policy))
        or document.get("thresholds") != {
            "method": "one-sided-wilson-no-continuity-correction",
            "confidence_level": 0.95,
            "strictly_exceeds_chance": True,
            "minimum_correct": {"MMLU-Pro": 6, "ARC-Challenge": 13},
        }
        or document.get("probes") != _PROBE_ROWS
    ):
        raise SuiteRefusal("SUITE_POLICY_INVALID")
    sources = document.get("sources")
    if not isinstance(sources, dict) or set(sources) != set(_PROBES):
        raise SuiteRefusal("SUITE_SOURCE_INVALID")
    for value in sources.values():
        if (
            not isinstance(value, dict)
            or set(value) != {"raw_sha256", "effective_rows_sha256"}
            or not all(_is_digest(digest) for digest in value.values())
        ):
            raise SuiteRefusal("SUITE_SOURCE_INVALID")
    exclusions = document.get("exclusions")
    if (
        not isinstance(exclusions, dict)
        or set(exclusions) != {"receipt_sha256", "identity_rows_sha256"}
        or not all(_is_digest(digest) for digest in exclusions.values())
    ):
        raise SuiteRefusal("SUITE_SOURCE_INVALID")
    tasks = document.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 64:
        raise SuiteRefusal("SUITE_TASKS_INVALID")
    counts = {dataset: 0 for dataset in _PROBES}
    seen_rows: set[str] = set()
    seen_source: set[tuple[str, int]] = set()
    for item in tasks:
        if not isinstance(item, dict) or set(item) != _TASK_KEYS:
            raise SuiteRefusal("SUITE_TASKS_INVALID")
        dataset = item.get("dataset")
        if dataset not in _PROBES:
            raise SuiteRefusal("SUITE_TASKS_INVALID")
        probe_id, cardinality = _PROBES[dataset]
        labels = item.get("choice_labels")
        choices = item.get("choices")
        correct = item.get("correct_choice_index")
        source_index = item.get("source_row_index")
        if (
            item.get("probe_id") != probe_id
            or not isinstance(labels, list)
            or not isinstance(choices, list)
            or len(labels) != cardinality
            or len(choices) != cardinality
            or len(set(labels)) != cardinality
            or not all(isinstance(x, str) and x for x in labels + choices)
            or not isinstance(correct, int)
            or isinstance(correct, bool)
            or not 0 <= correct < cardinality
            or item.get("expected_output") != labels[correct]
            or item.get("judge") != "exact_choice_label_v1"
            or item.get("max_output_tokens") != 4
            or not isinstance(item.get("prompt"), str)
            or not item["prompt"]
            or not isinstance(source_index, int)
            or isinstance(source_index, bool)
            or source_index < 0
            or not _is_digest(item.get("source_row_sha256"))
            or not _is_digest(item.get("selection_sha256"))
            or not isinstance(item.get("row_id"), str)
            or not item["row_id"]
            or item["row_id"] in seen_rows
            or (dataset, source_index) in seen_source
        ):
            raise SuiteRefusal("SUITE_TASKS_INVALID")
        seen_rows.add(item["row_id"])
        seen_source.add((dataset, source_index))
        counts[dataset] += 1
    if counts != {"MMLU-Pro": 32, "ARC-Challenge": 32}:
        raise SuiteRefusal("SUITE_TASKS_INVALID")
    return document


def build_source_manifest(
    *,
    mmlu_raw: bytes,
    arc_raw: bytes,
    exclusion_raw: bytes,
    expected_source_sha256s: Mapping[str, str],
    expected_effective_sha256s: Mapping[str, str] | None = None,
    expected_exclusion_sha256: str,
) -> dict:
    actual_source = {"MMLU-Pro": _sha(mmlu_raw), "ARC-Challenge": _sha(arc_raw)}
    if dict(expected_source_sha256s) != actual_source:
        raise SuiteRefusal("SOURCE_SHA_MISMATCH")
    if not _is_digest(expected_exclusion_sha256) or _sha(exclusion_raw) != expected_exclusion_sha256:
        raise SuiteRefusal("EXCLUSION_SHA_MISMATCH")
    exclusion = _decode_json(exclusion_raw, "EXCLUSION_SCHEMA_INVALID")
    try:
        items = exclusion["exclusions"]["items"]
        remaining = exclusion["post_exclusion_suite_b"]["contaminated_items_remaining"]
    except (KeyError, TypeError) as exc:
        raise SuiteRefusal("EXCLUSION_SCHEMA_INVALID") from exc
    if not isinstance(items, list) or remaining != 0:
        raise SuiteRefusal("EXCLUSION_SCHEMA_INVALID")
    excluded: dict[str, set[int]] = {dataset: set() for dataset in _PROBES}
    excluded_native: dict[str, dict[int, dict]] = {dataset: {} for dataset in _PROBES}
    exclusion_identities: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            raise SuiteRefusal("EXCLUSION_SCHEMA_INVALID")
        dataset = item.get("dataset")
        index = item.get("dataset_line")
        native_id = item.get("native_id")
        if not isinstance(dataset, str) or not isinstance(native_id, dict):
            raise SuiteRefusal("EXCLUSION_SCHEMA_INVALID")
        exclusion_identities.append({
            "dataset": dataset,
            "dataset_line": index,
            "native_id": native_id,
        })
        if dataset in excluded:
            if not isinstance(index, int) or isinstance(index, bool) or index < 0 or index in excluded[dataset]:
                raise SuiteRefusal("EXCLUSION_SCHEMA_INVALID")
            excluded[dataset].add(index)
            excluded_native[dataset][index] = native_id

    if expected_effective_sha256s is not None and (
        set(expected_effective_sha256s) != set(_PROBES)
        or not all(_is_digest(value) for value in expected_effective_sha256s.values())
    ):
        raise SuiteRefusal("EFFECTIVE_SHA_MISMATCH")

    tasks: list[dict] = []
    effective_sha256s: dict[str, str] = {}
    for dataset, raw in (("MMLU-Pro", mmlu_raw), ("ARC-Challenge", arc_raw)):
        candidates: list[tuple[bytes, dict]] = []
        parsed_rows = _jsonl(raw, dataset)
        parsed_by_index = {index: row for index, _raw_line, row in parsed_rows}
        for index, declared_native in excluded_native[dataset].items():
            row = parsed_by_index.get(index)
            actual_native = (
                {"question_id": row.get("question_id")}
                if dataset == "MMLU-Pro" and isinstance(row, dict)
                else {"id": row.get("id")} if isinstance(row, dict) else None
            )
            if actual_native != declared_native:
                raise SuiteRefusal(f"EXCLUSION_IDENTITY_MISMATCH:{dataset}:{index}")
        retained_lines = [raw_line for index, raw_line, _row in parsed_rows if index not in excluded[dataset]]
        effective_raw = b"\n".join(retained_lines) + b"\n"
        effective_sha256s[dataset] = _sha(effective_raw)
        if expected_effective_sha256s is not None and effective_sha256s[dataset] != expected_effective_sha256s[dataset]:
            raise SuiteRefusal(f"EFFECTIVE_SHA_MISMATCH:{dataset}")
        for index, raw_line, row in parsed_rows:
            if index in excluded[dataset]:
                continue
            if dataset == "MMLU-Pro":
                options = row.get("options")
                if isinstance(options, list) and len(options) != 10:
                    continue
            else:
                choice_block = row.get("choices")
                if isinstance(choice_block, dict):
                    texts = choice_block.get("text")
                    labels = choice_block.get("label")
                    if isinstance(texts, list) and isinstance(labels, list) and (len(texts) != 4 or len(labels) != 4):
                        continue
            task = _task(dataset, index, raw_line, row)
            selection_key = hashlib.sha256(SELECTION_DOMAINS[dataset].encode("utf-8") + raw_line).digest()
            task["selection_sha256"] = selection_key.hex()
            candidates.append((selection_key, task))
        if len(candidates) < 32:
            raise SuiteRefusal(f"SOURCE_POPULATION_TOO_SMALL:{dataset}")
        tasks.extend(task for _key, task in sorted(candidates, key=lambda pair: pair[0])[:32])

    policy = {
        "runtime_mode": "FROZEN_EVAL",
        "tool_access": "NONE",
        "context_limit_tokens": 4096,
        "output_budget_tokens": 4,
        "retry_policy": {"max_attempts": 1, "retry_on": []},
        "contamination_policy": {
            "authority": "a1-freeze-exclusion-amendment/v1",
            "contaminated_items_remaining": 0,
        },
    }
    manifest = {
        "schema": SUITE_SCHEMA,
        "issue": 1498,
        "suite_id": "ember02-r1-r2-cheap-probe-v1",
        "selection": {"algorithm": SELECTION_ALGORITHM, "domains": SELECTION_DOMAINS},
        **policy,
        "sources": {
            "MMLU-Pro": {
                "raw_sha256": actual_source["MMLU-Pro"],
                "effective_rows_sha256": effective_sha256s["MMLU-Pro"],
            },
            "ARC-Challenge": {
                "raw_sha256": actual_source["ARC-Challenge"],
                "effective_rows_sha256": effective_sha256s["ARC-Challenge"],
            },
        },
        "exclusions": {
            "receipt_sha256": expected_exclusion_sha256,
            "identity_rows_sha256": _sha(_canonical_bytes(sorted(
                exclusion_identities,
                key=lambda row: (row["dataset"], row["dataset_line"]),
            ))),
        },
        "policy_sha256": _sha(_canonical_bytes(policy)),
        "thresholds": {
            "method": "one-sided-wilson-no-continuity-correction",
            "confidence_level": 0.95,
            "strictly_exceeds_chance": True,
            "minimum_correct": {"MMLU-Pro": 6, "ARC-Challenge": 13},
        },
        "probes": _PROBE_ROWS,
        "tasks": tasks,
        "claim_boundary": (
            "FROZEN_ONLY; no model, GPU, capability, R1, R2, training, result, or issue-closure credit"
        ),
    }
    return _validate_manifest(manifest)


def load_source_manifest(path, expected_sha256: str) -> dict:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SuiteRefusal("SUITE_UNREADABLE") from exc
    if (
        expected_sha256 != FROZEN_SUITE_SHA256
        or _sha(raw) != FROZEN_SUITE_SHA256
    ):
        raise SuiteRefusal("SUITE_SHA_MISMATCH")
    document = _validate_manifest(_decode_json(raw, "SUITE_SCHEMA_INVALID"))
    if document["sources"] != {
        dataset: {
            "raw_sha256": FROZEN_SOURCE_SHA256S[dataset],
            "effective_rows_sha256": FROZEN_EFFECTIVE_SHA256S[dataset],
        }
        for dataset in ("MMLU-Pro", "ARC-Challenge")
    } or document["exclusions"] != {
        "receipt_sha256": FROZEN_EXCLUSION_SHA256,
        "identity_rows_sha256": "faf9d9b1b6af9f7092f73cf939730d35ac96b4b158386a7c1a8443e7515d23da",
    }:
        raise SuiteRefusal("SUITE_SOURCE_INVALID")
    return document


def publish_source_manifest(manifest: object, output: Path, *, check: bool) -> None:
    raw = _canonical_bytes(_validate_manifest(manifest))
    output = Path(output)
    if check:
        try:
            current = output.read_bytes()
        except OSError as exc:
            raise SuiteRefusal("SUITE_OUTPUT_DRIFT") from exc
        if current != raw:
            raise SuiteRefusal("SUITE_OUTPUT_DRIFT")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    except OSError as exc:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
        raise SuiteRefusal("SUITE_OUTPUT_WRITE_FAILED") from exc


def _token_ids(tokenizer: Any, text: str) -> list[int]:
    try:
        encoded = tokenizer.encode(text)
        ids = encoded.ids if hasattr(encoded, "ids") else encoded
    except Exception as exc:
        raise SuiteRefusal("TOKENIZER_ENCODING_FAILED") from exc
    if not isinstance(ids, (list, tuple)) or not ids or not all(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0 for value in ids
    ):
        raise SuiteRefusal("TOKENIZER_ENCODING_FAILED")
    return list(ids)


def compile_r2_registry(
    source_manifest: object,
    *,
    source_manifest_sha256: str,
    tokenizer: Any,
    tokenizer_sha256: str,
    compiler_sha256: str,
) -> tuple[list[dict], dict]:
    manifest = _validate_manifest(source_manifest)
    if not all(_is_digest(value) for value in (source_manifest_sha256, tokenizer_sha256, compiler_sha256)):
        raise SuiteRefusal("COMPILATION_IDENTITY_INVALID")
    registry: list[dict] = []
    for dataset in ("MMLU-Pro", "ARC-Challenge"):
        probe_id, cardinality = _PROBES[dataset]
        items = []
        for task in manifest["tasks"]:
            if task["dataset"] != dataset:
                continue
            items.append({
                "item_id": task["row_id"],
                "context_ids": _token_ids(tokenizer, task["prompt"]),
                "choices": [_token_ids(tokenizer, label) for label in task["choice_labels"]],
                "correct_choice_index": task["correct_choice_index"],
            })
        if len(items) != 32:
            raise SuiteRefusal("SUITE_TASKS_INVALID")
        registry.append({
            "probe_id": probe_id,
            "metric_id": "exact_choice_accuracy",
            "metric_type": "proportion",
            "chance_rate": 1.0 / cardinality,
            "source_note": f"source_manifest_sha256={source_manifest_sha256}",
            "items": items,
        })
    binding_payload = {
        "source_manifest_sha256": source_manifest_sha256,
        "tokenizer_sha256": tokenizer_sha256,
        "compiler_sha256": compiler_sha256,
        "registry": registry,
    }
    binding = {
        "source_manifest_sha256": source_manifest_sha256,
        "tokenizer_sha256": tokenizer_sha256,
        "compiler_sha256": compiler_sha256,
        "compiled_registry_sha256": _sha(_canonical_bytes(binding_payload)),
    }
    return registry, binding


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mmlu", required=True, type=Path)
    parser.add_argument("--arc", required=True, type=Path)
    parser.add_argument("--exclusions", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    manifest = build_source_manifest(
        mmlu_raw=args.mmlu.read_bytes(),
        arc_raw=args.arc.read_bytes(),
        exclusion_raw=args.exclusions.read_bytes(),
        expected_source_sha256s=FROZEN_SOURCE_SHA256S,
        expected_effective_sha256s=FROZEN_EFFECTIVE_SHA256S,
        expected_exclusion_sha256=FROZEN_EXCLUSION_SHA256,
    )
    publish_source_manifest(manifest, args.out, check=args.check)
    print(f"R1_R2_CHEAP_PROBE_SUITE_OK rows=64 sha256={_sha(_canonical_bytes(manifest))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
