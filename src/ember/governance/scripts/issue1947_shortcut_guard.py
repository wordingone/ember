#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""G2: refuse confirmed shortcut rows and unapproved row origins (spec v6, 9169818b).

Only two confirmed controls refuse: a constant prediction over >= 2 distinct golds (S1) and a
keyed captured-record replay whose predictions or scores move with position (S2). Skew and
neighbour echo are diagnostic flags only: a correct-but-skewed row is valid.

Origin: the approved row-contract, producer-contract and producer-receipt identities are pinned
in THIS source. A sidecar only names which approved pin applies; the guard re-hashes the bytes
itself. A forged set that is internally consistent and fully rehashed still refuses, because its
digests are not in the pins. Changing the pins is a reviewed source change, never a runtime input.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

# Approved identities (full 64-hex). Empty until an independently reviewed source change adds them;
# an empty set refuses every row, which is the correct state before approval.
APPROVED_ROW_CONTRACTS: frozenset[str] = frozenset()
APPROVED_PRODUCER_RECEIPTS: frozenset[str] = frozenset()
PRODUCER_CONTRACTS_SHA256 = "ed99bae67b646f2f9973b70f8f58a9a49cb7b70bef7db3b05dfa8b159da547ec"

# Exact allowlist of FILE paths a sidecar may name (posix form). No directories, no globs.
ALLOWED_ORIGIN_PATHS: frozenset[str] = frozenset()


class ShortcutRefusal(ValueError):
    pass


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_pinned(path_text: str, approved: frozenset[str], label: str) -> bytes:
    path = Path(path_text)
    if path.as_posix() not in ALLOWED_ORIGIN_PATHS:
        raise ShortcutRefusal(f"ORIGIN_PATH_NOT_ALLOWED:{label}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ShortcutRefusal(f"ORIGIN_UNREADABLE:{label}") from exc
    if _sha(raw) not in approved:
        raise ShortcutRefusal(f"ORIGIN_UNAPPROVED:{label}")
    return raw


def verify_origin(
    row: dict[str, Any],
    sidecar: dict[str, Any],
    derive: Callable[[dict[str, Any], dict[str, Any]], dict[str, tuple[str, Any]]],
) -> None:
    """derive(contract, receipt) -> {item_id: (gold_item_sha256, prediction)} is the adapter's own
    derivation (adapt_text for text rows); the guard compares it item by item."""
    row_id = row.get("row_id")
    contract = json.loads(_read_pinned(sidecar.get("row_contract_path", ""), APPROVED_ROW_CONTRACTS, "row_contract"))
    receipt_raw = _read_pinned(sidecar.get("producer_receipt_path", ""), APPROVED_PRODUCER_RECEIPTS, "producer_receipt")
    receipt = json.loads(receipt_raw)
    body = dict(receipt)
    claimed = body.pop("self_sha256", None)
    if claimed != _sha(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()):
        raise ShortcutRefusal(f"ORIGIN_RECEIPT_SELF_HASH:{row_id}")
    if contract.get("producer_contracts_sha256") != PRODUCER_CONTRACTS_SHA256:
        raise ShortcutRefusal(f"ORIGIN_PRODUCER_CONTRACT_UNBOUND:{row_id}")
    expected = derive(contract, receipt)
    _keyed(row["items"], row_id)  # refuses duplicate item ids; a dict would collapse them
    items = {item["item_id"]: item for item in row["items"]}
    if set(expected) != set(items):
        raise ShortcutRefusal(f"ORIGIN_ITEMSET_MISMATCH:{row_id}")
    for item_id, (gold, prediction) in expected.items():
        if items[item_id]["gold_item_sha256"] != gold or items[item_id]["prediction"] != prediction:
            raise ShortcutRefusal(f"ORIGIN_ITEM_MISMATCH:{row_id}:{item_id}")


def _keyed(items: list[dict[str, Any]], row_id: Any) -> dict[str, tuple[Any, Any, Any]]:
    keyed: dict[str, tuple[Any, Any, Any]] = {}
    for item in items:
        if item["item_id"] in keyed:
            raise ShortcutRefusal(f"DUPLICATE_ITEM_ID:{row_id}:{item['item_id']}")
        keyed[item["item_id"]] = (item["gold_item_sha256"], item["prediction"], item["score"])
    return keyed


def check_shortcuts(row: dict[str, Any], *, replay: tuple[list, list] | None, model_row: bool) -> dict[str, Any]:
    row_id = row["row_id"]
    items = row["items"]
    flags: dict[str, Any] = {}

    # S1: distinct gold digests are compared directly (spec v4 G-F4).
    reviewed = _keyed(items, row_id)  # refuses duplicate item ids before any comparison
    golds = {item["gold_item_sha256"] for item in items}
    preds = [json.dumps(item["prediction"], sort_keys=True) for item in items]
    if len(items) >= 2 and len(golds) >= 2 and len(set(preds)) == 1:
        raise ShortcutRefusal(f"CONSTANT_PREDICTION:{row_id}:{len(items)}")

    # S2, mode A: captured-record permutation. Predictions AND scores keyed by item_id must persist.
    status = "ORDER_INVARIANCE_PROVEN_CAPTURED"
    if replay is None:
        status = "ORDER_INVARIANCE_UNPROVEN" if model_row else "ORDER_INVARIANCE_NOT_REPLAYED"
    else:
        original, permuted = (_keyed(r, row_id) for r in replay)
        if set(original) != set(reviewed) or set(permuted) != set(reviewed):
            raise ShortcutRefusal(f"REPLAY_ITEMSET_MISMATCH:{row_id}")
        # The pair must replay the REVIEWED row: a pair that agrees with itself but not with the
        # row under review proves nothing about that row.
        for item_id in sorted(reviewed):
            if original[item_id] != reviewed[item_id]:
                raise ShortcutRefusal(f"REPLAY_NOT_THE_REVIEWED_ROW:{row_id}:{item_id}")
        for item_id in sorted(original):
            if original[item_id] != permuted[item_id]:
                raise ShortcutRefusal(f"ORDER_DEPENDENT_PREDICTION:{row_id}:{item_id}")

    # Diagnostic flags: never refuse.
    counts: dict[str, int] = {}
    for p in preds:
        counts[p] = counts.get(p, 0) + 1
    flags["D1_near_constant_share"] = max(counts.values()) / len(preds)
    return {"status": "ACCEPTED", "order_invariance": status, "flags": flags}
