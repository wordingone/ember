#!/usr/bin/env python3
# goal_id: EMBER-01
# workstream_id: EMBER-01C
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Build a deterministic, evidence-linked census of Ember identity surfaces."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Iterable


SCHEMA = "ember-identity-consumer-census-v1"
GOAL_ID = "EMBER-01"
WORKSTREAM_ID = "EMBER-01C"
NEXT_EXECUTED_OUTCOME = "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember"
SOURCE_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cu",
    ".h",
    ".hpp",
    ".js",
    ".json",
    ".jsonl",
    ".md",
    ".ps1",
    ".py",
    ".rs",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
}

EXCLUDED_PREFIXES = (
    ".git/",
    "node_modules/",
    "receipts/",
    "tests/",
    "scripts/tests/",
    "scripts/ember_01_identity/",
    "docs/ember-01-identity/",
    "manifests/ember-01-identity/",
    "tests/fixtures/",
    "docs/verification/receipts-",
    "scripts/ember_totality/receipts-",
)

CATEGORY_PATTERNS: dict[str, tuple[str, ...]] = {
    "architecture_config": (
        r"\b(?:LlamaConfig|AutoConfig|model_config|architecture(?:_id|_hash)?|hidden_size|intermediate_size|num_hidden_layers)\b",
    ),
    "training_optimizer": (
        r"\b(?:optimizer(?:_state)?|effective_tokens|trained_tokens|training_steps|global_step|backward\(|\.step\(\))\b",
    ),
    "checkpoint_save_load": (
        r"\b(?:torch\.save|torch\.load|save_pretrained|from_pretrained|load_state_dict|state_dict|checkpoint(?:_[a-z0-9]+)*)\b",
    ),
    "serving_runtime": (
        r"\b(?:EMBER_MODEL_URL|serving[-_]registry|model_path|llama-server|brain[-_]server|/v1/models|/v1/chat/completions|serverUrl|model endpoint)\b",
    ),
    "cli_operator_surface": (
        r"\b(?:LOCAL_MODEL_ID|EMBER_MODEL_NAME|models\.json|modelName|model loaded|model unloaded|model endpoint|provider)\b",
    ),
    "evaluation_benchmark": (
        r"\b(?:benchmark_id|benchmark[-_]name|subject_checkpoint|comparator|counts_toward|completion_count|eval(?:uation)?_result|score)\b",
    ),
    "publication_report": (
        r"\b(?:model[-_ ]card|research[-_ ]paper|paper(?:_path|_id|_draft)?|recorded[-_ ]demo|demo(?:_path|_id)?|dashboard)\b",
    ),
    "borrowed_reference": (
        r"\b(?:qwen|reference_only|borrowed_reference|frozen_reference|reference server)\b",
    ),
    "process_registry_watchdog": (
        r"\b(?:planned[-_]outage|watchdog|process_identity|resource_lease|pid|launched_by|kill_receipt)\b",
    ),
    "parameter_identity": (
        r"\b(?:parameter_count|param_count|total_parameters|unique_parameters|active_parameters|trainable_parameters|served_parameters|actually_trained)\b",
    ),
    "tokenizer_data_lineage": (
        r"\b(?:tokenizer(?:_path|_id|_hash)?|corpus(?:_id|_hash)?|curriculum|sample_order|data_lineage|clean_genesis)\b",
    ),
    "mechanism_identity": (
        r"\b(?:expert(?:_id|_bank)?|router|memory_substrate|world_model|deletion_object|mechanism_id)\b",
    ),
}

COMPILED = {
    category: tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)
    for category, patterns in CATEGORY_PATTERNS.items()
}


def _excluded(rel: str) -> bool:
    normalized = rel.replace("\\", "/")
    name = Path(normalized).name.lower()
    return (
        any(normalized.startswith(prefix) for prefix in EXCLUDED_PREFIXES)
        or ".test." in name
        or name.startswith("test_")
        or name.endswith("_test.py")
    )


def tracked_files(root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.decode("utf-8", errors="replace").strip())
    return sorted(
        raw.decode("utf-8", errors="strict")
        for raw in completed.stdout.split(b"\0")
        if raw
    )


def build_census(root: Path, *, tracked_files: Iterable[str] | None = None) -> dict:
    root = root.resolve()
    candidates = sorted(set(tracked_files if tracked_files is not None else globals()["tracked_files"](root)))
    evidence: list[dict[str, object]] = []
    scanned = 0
    excluded = 0
    evidence_files: set[str] = set()
    category_files: dict[str, set[str]] = {category: set() for category in COMPILED}
    raw_match_counts: dict[str, int] = {category: 0 for category in COMPILED}
    kept_counts: dict[tuple[str, str], int] = {}

    for raw_rel in candidates:
        rel = raw_rel.replace("\\", "/")
        path = root / rel
        if _excluded(rel) or path.suffix.lower() not in SOURCE_SUFFIXES:
            excluded += 1
            continue
        if not path.is_file():
            continue
        scanned += 1
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            excluded += 1
            scanned -= 1
            continue
        for line_number, line in enumerate(lines, start=1):
            excerpt = line.strip()
            if not excerpt:
                continue
            for category, patterns in COMPILED.items():
                if any(pattern.search(line) for pattern in patterns):
                    raw_match_counts[category] += 1
                    key = (rel, category)
                    if kept_counts.get(key, 0) < 3:
                        evidence.append(
                            {
                                "category": category,
                                "path": rel,
                                "line": line_number,
                                "line_sha256": hashlib.sha256(
                                    line.encode("utf-8")
                                ).hexdigest(),
                            }
                        )
                        kept_counts[key] = kept_counts.get(key, 0) + 1
                    evidence_files.add(rel)
                    category_files[category].add(rel)

    evidence.sort(key=lambda row: (str(row["path"]), int(row["line"]), str(row["category"])))
    categories = {
        category: {
            "files": sorted(paths),
            "file_count": len(paths),
            "evidence_count": sum(1 for row in evidence if row["category"] == category),
            "raw_match_count": raw_match_counts[category],
        }
        for category, paths in sorted(category_files.items())
    }
    return {
        "schema": SCHEMA,
        "goal_id": GOAL_ID,
        "workstream_id": WORKSTREAM_ID,
        "next_executed_outcome": NEXT_EXECUTED_OUTCOME,
        "coverage": {
            "tracked_candidates": len(candidates),
            "files_scanned": scanned,
            "files_excluded": excluded,
            "files_with_identity_evidence": len(evidence_files),
            "identity_evidence_rows": len(evidence),
            "exclusion_prefixes": list(EXCLUDED_PREFIXES),
            "source_suffixes": sorted(SOURCE_SUFFIXES),
        },
        "categories": categories,
        "evidence": evidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = build_census(args.root)
    rendered = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
