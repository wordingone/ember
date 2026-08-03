# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Receipt indexer: append-only provenance rows, joinable back to execution
nodes by node_id.

gap-matrix.md's "Receipt reconstruction" gap: Ember's receipts/INDEX.jsonl
has 5,823 rows with a schema that varies row-to-row and no node_id field at
all -- reconstructing what happened for a given node means grepping raw
receipt files by convention. This module makes node_id mandatory (enforced
by schemas/loop-graph/provenance-receipt-v1.schema.json) and provides the
join query directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import validate as _validate
from ._atomic import atomic_append_jsonl, read_jsonl


def append_receipt(index_path: Path, receipt: dict[str, Any]) -> None:
    """Validate and append one receipt row. Append-only: never edits or
    removes an existing row."""
    _validate.validate_or_raise(receipt, "receipt")
    atomic_append_jsonl(Path(index_path), receipt)


def load_index(index_path: Path) -> list[dict[str, Any]]:
    return read_jsonl(Path(index_path))


def receipts_for_node(index_path: Path, node_id: str) -> list[dict[str, Any]]:
    """Reconstruct an execution node's receipt chain: every receipt row
    whose node_id matches, in append order (oldest first)."""
    return [row for row in load_index(index_path) if row.get("node_id") == node_id]


def latest_receipt_for_node(index_path: Path, node_id: str) -> dict[str, Any] | None:
    chain = receipts_for_node(index_path, node_id)
    return chain[-1] if chain else None
