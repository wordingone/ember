#!/usr/bin/env python3
"""Extract citation-like external references from an Ember checkout."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

TEXT_SUFFIXES = {
    ".md",
    ".txt",
    ".json",
    ".jsonl",
    ".py",
    ".yaml",
    ".yml",
    ".toml",
    ".ps1",
    ".sh",
}

DEFAULT_SKIP_PARTS = {
    ".git",
    "node_modules",
    "models",
    "results",
    "scratchpad",
    "__pycache__",
    ".venv",
    "venv",
}

KNOWN_TERMS = [
    "karpathy",
    "llm.c",
    "nanogpt",
    "modded-nanogpt",
    "autoresearch",
    "godel machine",
    "goedel machine",
    "sakana",
    "ai scientist",
    "darwin godel machine",
    "dgm",
    "cellular automata",
    "cellular automaton",
    "tribe",
    "tribev2",
    "iGRPO",
    "RLM",
    "BitNet",
    "1.58-bit",
    "QAT",
    "Muon",
    "BabyLM",
    "MLE-bench",
    "MLAgentBench",
    "ScienceAgentBench",
    "D3-Gym",
    "KernelBench",
    "AlgoPerf",
    "Chinchilla",
    "TinyStories",
    "ARC-AGI",
    "Voyager",
    "Reflexion",
    "E2B",
    "Kaggle",
    "OpenAI",
    "Codex",
    "OpenAI Codex",
    "external vendor B",
    "external coding agent B",
    "external coding agent B",
    "Hermes",
    "NemoClaw",
    "NeMo Agent Toolkit",
    "OpenReview",
    "Hugging Face",
    "FineWeb",
    "FineWeb-Edu",
    "Fuyu",
    "Gemma",
    "Qwen",
    "Llama",
    "DeepSeek",
    "DeepSeek-V3",
    "DeepSeek-R1",
    "DeepSpec",
    "Sapient",
    "HRM",
    "nanoTabPFN",
    "TabPFN",
    "DSpark",
    "DFlash",
    "Eagle3",
    "DeepGEMM",
    "DeepEP",
    "FlashMLA",
    "DualPipe",
    "EPLB",
    "3FS",
    "TileKernels",
    "MLA",
    "NSA",
    "MTP",
    "Flash Attention",
    "FlashAttention",
    "Triton",
    "FP8",
    "torchao",
    "LoRA",
    "SFT",
    "DPO",
    "GRPO",
    "AlphaZero",
    "AlphaGo",
    "Dreamer",
    "Mamba",
    "RWKV",
    "Hyena",
    "RetNet",
    "DeltaNet",
]

URL_RE = re.compile(r"https?://[^\s)>\]\"']+")
ARXIV_RE = re.compile(r"\barXiv[:/\s]*(\d{4}\.\d{4,5}(?:v\d+)?)\b", re.IGNORECASE)
GITHUB_RE = re.compile(r"\b([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)\b")


def should_scan(path: Path, skip_parts: set[str], max_bytes: int | None) -> bool:
    if any(part in skip_parts for part in path.parts):
        return False
    if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
        return False
    if max_bytes is not None:
        try:
            if path.stat().st_size > max_bytes:
                return False
        except OSError:
            return False
    return True


def add(rows: list[dict], root: Path, path: Path, kind: str, value: str, line_no: int, line: str) -> None:
    rows.append(
        {
            "kind": kind,
            "value": value,
            "path": path.relative_to(root).as_posix(),
            "line": line_no,
            "context": line.strip()[:500],
        }
    )


def extract(root: Path, skip_parts: set[str], max_bytes: int | None) -> list[dict]:
    rows: list[dict] = []
    term_patterns = [(term, re.compile(r"(?<![A-Za-z0-9_.-])" + re.escape(term) + r"(?![A-Za-z0-9_.-])", re.IGNORECASE)) for term in KNOWN_TERMS]
    for path in sorted(root.rglob("*")):
        if not should_scan(path, skip_parts, max_bytes):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for idx, line in enumerate(lines, start=1):
            for match in URL_RE.finditer(line):
                add(rows, root, path, "url", match.group(0).rstrip(".,;"), idx, line)
            for match in ARXIV_RE.finditer(line):
                add(rows, root, path, "arxiv", match.group(1), idx, line)
            for match in GITHUB_RE.finditer(line):
                token = match.group(1)
                if token.lower() not in {"http/1.1", "and/or"}:
                    add(rows, root, path, "github_like", token, idx, line)
            for term, pattern in term_patterns:
                if pattern.search(line):
                    add(rows, root, path, "known_term", term, idx, line)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--limit-summary", type=int, default=200)
    parser.add_argument("--skip-part", action="append", default=[], help="Additional path component to skip. Repeatable.")
    parser.add_argument("--max-bytes", type=int, help="Skip individual files larger than this many bytes.")
    args = parser.parse_args()

    root = args.root.resolve()
    skip_parts = set(DEFAULT_SKIP_PARTS)
    skip_parts.update(args.skip_part)
    rows = extract(root, skip_parts, args.max_bytes)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")

    if args.summary:
        counts = Counter((row["kind"], row["value"]) for row in rows)
        paths = Counter(row["path"] for row in rows)
        summary = {
            "root": str(root),
            "row_count": len(rows),
            "skip_parts": sorted(skip_parts),
            "max_bytes": args.max_bytes,
            "top_refs": [
                {"kind": kind, "value": value, "count": count}
                for (kind, value), count in counts.most_common(args.limit_summary)
            ],
            "top_paths": [
                {"path": path, "count": count}
                for path, count in paths.most_common(50)
            ],
        }
        args.summary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"root": str(root), "rows": len(rows), "out": str(args.out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())