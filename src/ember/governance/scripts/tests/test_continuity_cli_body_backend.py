#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Production-shaped assertion on the docs/domains/governance/authority/CONTINUITY.md identity resolver's
`ember-cli-body` row (EMBER-01 R8 Part-B).

The row must NOT carry the bare `qwen_reference_default` backend fallback.
The owned seat is default-but-offline pre-birth; the reference seat used by
the CLI body must be recorded EXPLICITLY (mirroring the qwen36-reference-
backend row's `borrowed_reference` honesty), and the evidence cell must cite
the four-state SOURCE/BUILT/INSTALLED/LIVE reverification receipt that
established this — never a silent default with no receipt trail.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
CONTINUITY = REPO_ROOT / "docs/domains/governance/authority/CONTINUITY.md"

EXPECTED_BACKEND = "reference_seat_explicit"
FORBIDDEN_BACKEND = "qwen_reference_default"
EXPECTED_EVIDENCE_FRAGMENT = (
    "receipts/ember-01-custody/cli-body-reverification-v1.json"
)


def _find_resolver_row(row_id: str) -> list[str]:
    """Parse the 9-column identity resolver table in docs/domains/governance/authority/CONTINUITY.md and return
    the cells for the row whose id == row_id. Raises AssertionError if the
    row is absent so a missing/renamed row fails loudly rather than
    silently passing."""
    text = CONTINUITY.read_text(encoding="utf-8")
    lines = text.splitlines()
    header_idx = None
    for idx, raw in enumerate(lines):
        if not raw.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in raw.strip().strip("|").split("|")]
        if cells and cells[0] == "id" and "evidence" in cells:
            header_idx = idx
            break
    assert header_idx is not None, "docs/domains/governance/authority/CONTINUITY.md identity resolver header not found"

    for raw in lines[header_idx + 1 :]:
        if not raw.strip():
            break
        if not raw.lstrip().startswith("|"):
            break
        cells = [cell.strip() for cell in raw.strip().strip("|").split("|")]
        if all(set(cell) <= {"-", ":"} for cell in cells):
            continue
        if cells and cells[0] == row_id:
            return cells
    raise AssertionError(f"docs/domains/governance/authority/CONTINUITY.md resolver row {row_id!r} not found")


def test_ember_cli_body_backend_is_explicit_reference_seat() -> None:
    row = _find_resolver_row("ember-cli-body")
    # id, object_type, canonical_identity, artifact_class, parameter_count,
    # trained_tokens, backend, capability_credit, evidence
    assert len(row) == 9, f"expected a 9-column row, got {len(row)}: {row}"
    backend = row[6]
    evidence = row[8]

    assert backend != FORBIDDEN_BACKEND, (
        "ember-cli-body backend must not be the bare "
        f"{FORBIDDEN_BACKEND!r} fallback; the reference seat must be "
        "recorded explicitly"
    )
    assert backend == EXPECTED_BACKEND, (
        f"ember-cli-body backend must be {EXPECTED_BACKEND!r}, got {backend!r}"
    )
    assert EXPECTED_EVIDENCE_FRAGMENT in evidence, (
        "ember-cli-body evidence must cite the four-state reverification "
        f"receipt ({EXPECTED_EVIDENCE_FRAGMENT!r}); got {evidence!r}"
    )
    assert row[3] == "research_prototype", "artifact_class must stay research_prototype"
    assert row[2] == "source:tools/ember-cli", "canonical_identity must stay source:tools/ember-cli"
    assert row[7] == "none", "capability_credit must stay none"
