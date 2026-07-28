#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed verifier for Ember's inference-to-training translation table."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


TABLE_PATH = Path("docs/inference-to-training-translation-v1.md")
INTEGRATION_PATHS = (
    Path("docs/sota-stack-floor-spec.md"),
    Path("docs/sota-stack-floor.md"),
    Path("docs/design/scale-architecture-frontier-20260703.md"),
)
CANONICAL_LINK = TABLE_PATH.as_posix()
HEADER = (
    "| ID | Inference technique | Inference benefit | Training analog | "
    "Field maturity | Ember status | Candidate experiment |"
)
REQUIRED_TECHNIQUES = (
    "post-training quantization",
    "speculative decoding",
    "frozen low-bit residency",
    "mixture-of-experts partial activation",
    "kv-cache reduction",
    "pruning",
    "serving distillation",
    "ternary inference",
)
PRIMARY_SOURCE_HOSTS = frozenset({"arxiv.org", "openreview.net"})
ROW_RE = re.compile(r"^\|\s*(T\d{2})\s*\|(.+)\|$")
CITATION_RE = re.compile(r"\[(S\d{2})\]")
SOURCE_RE = re.compile(r"^-\s+\[(S\d{2})\]\s+(https://\S+)\s*$")


class ContractError(ValueError):
    pass


def _read_strict(path: Path) -> tuple[str, str]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ContractError(f"{path.as_posix()}: unreadable: {exc}") from exc
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ContractError(f"{path.as_posix()}: invalid UTF-8: {exc}") from exc
    return text, hashlib.sha256(data).hexdigest()


def _parse_sources(lines: list[str]) -> dict[str, str]:
    sources: dict[str, str] = {}
    for line in lines:
        match = SOURCE_RE.fullmatch(line.strip())
        if not match:
            continue
        citation, url = match.groups()
        if citation in sources:
            raise ContractError(f"duplicate source id {citation}")
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in PRIMARY_SOURCE_HOSTS:
            raise ContractError(f"{citation}: source is not an allowed primary source: {url}")
        if not parsed.path or parsed.path == "/":
            raise ContractError(f"{citation}: source URL has no artifact path: {url}")
        sources[citation] = url
    return sources


def verify(root: Path) -> dict[str, object]:
    table_file = root / TABLE_PATH
    text, table_sha = _read_strict(table_file)
    lines = text.splitlines()
    if HEADER not in lines:
        raise ContractError(f"{TABLE_PATH.as_posix()}: exact table header is missing")

    rows: list[dict[str, str]] = []
    row_ids: set[str] = set()
    for line in lines:
        match = ROW_RE.fullmatch(line)
        if not match:
            continue
        row_id, remainder = match.groups()
        cells = [cell.strip() for cell in remainder.split("|")]
        if len(cells) != 6 or any(not cell for cell in cells):
            raise ContractError(f"{row_id}: expected six nonempty data cells")
        if row_id in row_ids:
            raise ContractError(f"duplicate row id {row_id}")
        row_ids.add(row_id)
        technique, benefit, analog, maturity, ember_status, experiment = cells
        citations = CITATION_RE.findall(maturity)
        if not citations:
            raise ContractError(f"{row_id}: field maturity has no citation")
        rows.append(
            {
                "id": row_id,
                "technique": technique,
                "benefit": benefit,
                "analog": analog,
                "maturity": maturity,
                "ember_status": ember_status,
                "experiment": experiment,
                "citations": ",".join(citations),
            }
        )

    if len(rows) < 15:
        raise ContractError(f"{TABLE_PATH.as_posix()}: expected at least 15 rows, found {len(rows)}")

    technique_text = "\n".join(row["technique"].casefold() for row in rows)
    missing_techniques = [
        technique for technique in REQUIRED_TECHNIQUES if technique not in technique_text
    ]
    if missing_techniques:
        raise ContractError(
            "missing required technique rows: " + ", ".join(missing_techniques)
        )

    sources = _parse_sources(lines)
    cited = {
        citation
        for row in rows
        for citation in row["citations"].split(",")
        if citation
    }
    unresolved = sorted(cited - sources.keys())
    if unresolved:
        raise ContractError("unresolved field-maturity citations: " + ", ".join(unresolved))

    integration_hashes: dict[str, str] = {}
    for relative in INTEGRATION_PATHS:
        integration_text, integration_sha = _read_strict(root / relative)
        if CANONICAL_LINK not in integration_text:
            raise ContractError(
                f"{relative.as_posix()}: missing canonical link to {CANONICAL_LINK}"
            )
        integration_hashes[relative.as_posix()] = integration_sha

    frontier_text, _ = _read_strict(root / INTEGRATION_PATHS[-1])
    if "## 6." not in frontier_text or "C-SCALE(ii)" not in frontier_text:
        raise ContractError(
            f"{INTEGRATION_PATHS[-1].as_posix()}: section 6/C-SCALE(ii) linkage is missing"
        )

    return {
        "status": "PASS",
        "schema": "ember-inference-training-translation-check/v1",
        "table_path": TABLE_PATH.as_posix(),
        "table_sha256": table_sha,
        "row_count": len(rows),
        "resolved_citation_count": len(cited),
        "source_count": len(sources),
        "integration_sha256": integration_hashes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        receipt = verify(args.root.resolve())
    except ContractError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    else:
        print(
            f"PASS: {receipt['row_count']} rows; "
            f"{receipt['resolved_citation_count']} cited maturity claims resolved"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
