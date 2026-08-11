#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Render private canonical Ember goals as public, clause-addressable contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


GOAL_ID_RE = re.compile(r"(?m)^goal_id:\s*(EMBER-\d{2})\s*$")
HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$")
LIST_RE = re.compile(r"^(\s*)(?:[-*]|\d+\.)\s+")
HOST_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/(?:Users|home)/)")
OPERATIONAL_HEADINGS = {"Agent allocation", "Transition"}
SECTION_CODES = {
    "Outcome": "OUTCOME",
    "Conserved Ember totality": "TOTALITY",
    "Starting truth": "START",
    "Required work": "WORK",
    "Prohibited substitutions": "PROHIBIT",
    "Completion certificate": "CERT",
    "Failure and reopening": "REOPEN",
}
PRIVATE_ROOT = "B:" + "\\M"
PRIMARY_FOUNDER = "K" + "ai"
SECONDARY_FOUNDER = "L" + "eo"
HOSTED_CODING_PRODUCT = "C" + "laude Code"
PRIVATE_TERM_REPLACEMENTS = (
    (
        f"The current {PRIMARY_FOUNDER} `goal.md` was a monolithic audit role "
        f"tied to a permanent {SECONDARY_FOUNDER}/{PRIMARY_FOUNDER} split.",
        "The former private coordination `goal.md` defined a monolithic audit "
        "role and a permanent split between two outside AI development agents.",
    ),
    (
        f"{PRIMARY_FOUNDER} and, when available, {SECONDARY_FOUNDER}",
        "outside AI development agents, when available,",
    ),
    (
        f"{PRIMARY_FOUNDER}, {SECONDARY_FOUNDER}",
        "outside AI development agents",
    ),
    (
        f"{PRIMARY_FOUNDER} or {SECONDARY_FOUNDER}",
        "outside AI development agents",
    ),
    (f"{PRIMARY_FOUNDER}/{SECONDARY_FOUNDER}", "outside AI development agents"),
    (f"{PRIMARY_FOUNDER}-authored", "externally authored"),
    (f"{PRIMARY_FOUNDER}'s role", "the outside development role"),
    (f"{PRIMARY_FOUNDER}'s", "an outside AI development agent's"),
    (f"{SECONDARY_FOUNDER}'s", "an outside AI development agent's"),
    (HOSTED_CODING_PRODUCT, "contemporary coding-agent software"),
    (PRIMARY_FOUNDER, "an outside AI development agent"),
    (SECONDARY_FOUNDER, "an outside AI development agent"),
    (". outside AI development agents", ". Outside AI development agents"),
)


TRANSLATIONS = {
    (
        "EMBER-00",
        f"Make Ember's governing surfaces describe one exact project: the sovereign foundation intelligence, the creation primitive, the organism, its body, and the general local AI laboratory. Reconcile the verified discrepancies in `{PRIVATE_ROOT}\\avir\\{PRIMARY_FOUNDER.lower()}\\state\\ember-dissonance-ledger.md` into the highest amendable Ember authority without weakening or rewriting `docs/authority/INVARIANT.md`.",
    ): (
        "Make Ember's governing surfaces describe one exact project: the sovereign foundation intelligence, the creation primitive, the organism, its body, and the general local AI laboratory. Reconcile every verified discrepancy in the preserved discrepancy ledger and its content-addressed evidence into the highest amendable Ember authority without weakening or rewriting `docs/authority/INVARIANT.md`."
    ),
    (
        "EMBER-00",
        f"- At authoring time Ember was paused. Activation is controlled only by `{PRIVATE_ROOT}\\avir\\{PRIMARY_FOUNDER.lower()}\\EMBER-GOAL-RESUME.md`; `state: active` with this exact goal selected is sufficient and creates no second approval, re-arm, resume, product, or peer gate. This authority-only goal does not authorize training, inference experiments, or runtime changes.",
    ): (
        "- At authoring time Ember was paused. Activation is controlled only by the current execution graph; an active selector naming this exact goal is sufficient and creates no second approval, re-arm, resume, product, or peer gate. This authority-only goal does not authorize training, inference experiments, or runtime changes."
    ),
    (
        "EMBER-01",
        f"- Unique Ember material is distributed across the public repository, private `ember-backup`, `{PRIVATE_ROOT}\\ember`, clean mirrors, ignored payloads, separate worktrees, checkpoint directories, `{PRIVATE_ROOT}\\ember-bench`, {PRIMARY_FOUNDER} and {SECONDARY_FOUNDER} state, and local-only receipts.",
    ): (
        "- Unique Ember material is distributed across the public repository, private backup refs, the canonical local development checkout, clean mirrors, ignored payloads, separate worktrees, checkpoint directories, the benchmark root, founder state, and local-only receipts."
    ),
    (
        "EMBER-01",
        f"1. Inventory public refs, private refs, `{PRIVATE_ROOT}\\ember`, `{PRIVATE_ROOT}\\ember-backup`, `{PRIVATE_ROOT}\\ember-public`, `{PRIVATE_ROOT}\\ember-bench`, all registered worktrees, ignored large payloads, checkpoint roots, serving state, benchmark assets, and relevant {PRIMARY_FOUNDER}/{SECONDARY_FOUNDER} evidence.",
    ): (
        "1. Inventory public refs, private refs, the canonical local development checkout, private backup root, clean public mirror, benchmark root, all registered worktrees, ignored large payloads, checkpoint roots, serving state, benchmark assets, and relevant founder evidence."
    ),
}

PUBLIC_INTRO = """\
> **Public milestone contract.** This document is the version-controlled,
> public form of the canonical milestone. `docs/authority/GOAL.md` remains the higher
> authority. GitHub milestones and issues only track work against this
> contract.
>
> **Plain-language reading guide.** *Clean genesis* means that the model
> lineage begins without borrowed model weights, outputs, teachers, judges, or
> hidden external cognition. *Sufficiently trained* means useful capability is
> demonstrated by the exact checkpoint, not merely that parameters were
> allocated or a smoke run completed. *Native* means the owned model itself
> performs the capability. *Checkpoint-bound evidence* ties a result to exact
> model, data, tokenizer, training, and evaluation identities. *Verified Expert
> Accretion* is Ember's hypothesis that independently trained, causally
> verified expert capacity can accumulate while episode-level active cost stays
> bounded.
"""

PUBLIC_EXECUTION_NOTE = """\
## Public execution note

<!-- clause-id: {goal_id}.EXECUTION.001 -->
Private founder assignments, session routing, and machine-local paths are
intentionally not milestone requirements. Implementation responsibility may
change without changing this contract.

<!-- clause-id: {goal_id}.EXECUTION.002 -->
Dependencies and scheduling are represented by the public roadmap index and
execution graph. They cannot waive this milestone's completion certificate.
"""


class ContractError(ValueError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    canonical = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return _sha256_bytes(canonical.encode("utf-8"))


def _section_ranges(text: str) -> list[tuple[str, int, int]]:
    matches = list(re.finditer(r"(?m)^## ([^\r\n]+)\r?$", text))
    return [
        (
            match.group(1).strip(),
            match.start(),
            matches[index + 1].start() if index + 1 < len(matches) else len(text),
        )
        for index, match in enumerate(matches)
    ]


def _split_public_source(
    text: str,
) -> tuple[str, list[dict[str, str]]]:
    ranges = _section_ranges(text)
    operational = [row for row in ranges if row[0] in OPERATIONAL_HEADINGS]
    if {row[0] for row in operational} != OPERATIONAL_HEADINGS:
        raise ContractError("missing Agent allocation or Transition section")
    cutoff = min(row[1] for row in operational)
    normative = text[:cutoff].rstrip() + "\n"
    excluded = [
        {
            "heading": heading,
            "relation": "non_normative_execution_metadata",
            "source_sha256": _sha256_text(text[start:end]),
            "reason": (
                "Private staffing, session routing, and machine-local scheduling "
                "are represented publicly by durable roles and the execution graph."
            ),
        }
        for heading, start, end in operational
    ]
    return normative, excluded


def _block_end(lines: list[str], start: int, is_list: bool, indent: int) -> int:
    index = start + 1
    while index < len(lines):
        line = lines[index]
        if not line.strip() or HEADING_RE.match(line):
            break
        list_match = LIST_RE.match(line)
        if is_list and list_match and len(list_match.group(1)) <= indent:
            break
        if not is_list and list_match:
            break
        index += 1
    return index


def _annotate(
    text: str, goal_id: str
) -> tuple[str, list[dict[str, Any]]]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    output: list[str] = []
    clauses: list[dict[str, Any]] = []
    counters: defaultdict[str, int] = defaultdict(int)
    current_code: str | None = None
    in_frontmatter = False
    frontmatter_seen = False
    index = 0

    while index < len(lines):
        line = lines[index]
        if line == "---" and not frontmatter_seen:
            in_frontmatter = True
            frontmatter_seen = True
            output.append(line)
            index += 1
            continue
        if line == "---" and in_frontmatter:
            in_frontmatter = False
            output.append(line)
            index += 1
            continue

        heading = HEADING_RE.match(line)
        if heading:
            if len(heading.group(1)) == 2:
                current_code = SECTION_CODES.get(heading.group(2).strip())
                if current_code is None:
                    raise ContractError(
                        f"unknown normative section: {heading.group(2).strip()}"
                    )
            output.append(line)
            index += 1
            continue

        if in_frontmatter or current_code is None or not line.strip():
            output.append(line)
            index += 1
            continue

        list_match = LIST_RE.match(line)
        end = _block_end(
            lines,
            index,
            is_list=list_match is not None,
            indent=len(list_match.group(1)) if list_match else 0,
        )
        block_lines = lines[index:end]
        block = "\n".join(block_lines).rstrip()
        counters[current_code] += 1
        translated = TRANSLATIONS.get((goal_id, block))
        if HOST_PATH_RE.search(block) and translated is None:
            raise ContractError("host-private path in normative text")
        public_block = translated if translated is not None else block
        clause_id = f"{goal_id}.{current_code}.{counters[current_code]:03d}"
        for private_term, public_term in PRIVATE_TERM_REPLACEMENTS:
            public_block = public_block.replace(private_term, public_term)
        public_block_lines = public_block.splitlines()
        was_translated = translated is not None or public_block != block
        source_digest = _sha256_text(block)
        public_digest = _sha256_text(public_block)
        output.append(f"<!-- clause-id: {clause_id} -->")
        output.extend(public_block_lines)
        clauses.append(
            {
                "clause_id": clause_id,
                "section": current_code,
                "relation": (
                    "translated_public_equivalent"
                    if was_translated
                    else "verbatim"
                ),
                "source_sha256": source_digest,
                "public_sha256": public_digest,
            }
        )
        index = end

    rendered = "\n".join(output).rstrip() + "\n"
    title_match = re.search(r"(?m)^# EMBER-\d{2}.+$", rendered)
    if title_match is None:
        raise ContractError(f"{goal_id}: missing title")
    insertion = title_match.end()
    rendered = (
        rendered[:insertion]
        + "\n\n"
        + PUBLIC_INTRO.rstrip()
        + "\n"
        + rendered[insertion:]
    )
    if HOST_PATH_RE.search(rendered):
        raise ContractError("host-private path remained after translation")
    return rendered, clauses


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def publish(
    source_dir: Path,
    output_dir: Path,
    crosswalk_path: Path,
    source_contracts_path: Path | None = None,
) -> dict[str, Any]:
    sources = sorted(source_dir.glob("ember-*/goal.md"))
    if not sources:
        raise ContractError(f"no canonical goal files under {source_dir}")
    seen_ids: set[str] = set()
    contracts: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    output_dir.mkdir(parents=True, exist_ok=True)

    for source in sources:
        raw = source.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ContractError(f"{source}: invalid UTF-8") from exc
        match = GOAL_ID_RE.search(text)
        if match is None:
            raise ContractError(f"{source}: missing goal_id")
        goal_id = match.group(1)
        if goal_id in seen_ids:
            raise ContractError(f"duplicate goal_id: {goal_id}")
        seen_ids.add(goal_id)

        normative, excluded = _split_public_source(text)
        rendered, clauses = _annotate(normative, goal_id)
        rendered = (
            rendered.rstrip()
            + "\n\n"
            + PUBLIC_EXECUTION_NOTE.format(goal_id=goal_id).rstrip()
            + "\n"
        )
        public_path = output_dir / f"{goal_id}.md"
        public_path.write_text(rendered, encoding="utf-8", newline="\n")

        relative_source = source.relative_to(source_dir).as_posix()
        contracts.append(
            {
                "goal_id": goal_id,
                "source_path": relative_source,
                "source_sha256": _sha256_bytes(raw),
                "public_path": public_path.as_posix(),
                "public_sha256": _sha256_bytes(public_path.read_bytes()),
                "clauses": clauses,
                "excluded_operational_sections": excluded,
            }
        )
        source_rows.append(
            {
                "goal_id": goal_id,
                "source_path": relative_source,
                "source_sha256": _sha256_bytes(raw),
                "normative_clause_count": len(clauses),
                "excluded_operational_sections": excluded,
            }
        )

    payload = {
        "schema_version": "ember-roadmap-clause-crosswalk-v1",
        "contracts": contracts,
    }
    _write_json(crosswalk_path, payload)
    if source_contracts_path is not None:
        _write_json(
            source_contracts_path,
            {
                "schema_version": "ember-roadmap-source-contracts-v1",
                "source_kind": "canonical_local_goal_files",
                "contracts": source_rows,
            },
        )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--crosswalk", type=Path, required=True)
    parser.add_argument("--source-contracts", type=Path)
    args = parser.parse_args()
    try:
        payload = publish(
            args.source_dir,
            args.output_dir,
            args.crosswalk,
            args.source_contracts,
        )
    except (ContractError, OSError) as exc:
        print(f"ROADMAP_PUBLICATION_REFUSED: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "contract_count": len(payload["contracts"]),
                "status": "PUBLIC_CONTRACTS_RENDERED",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
