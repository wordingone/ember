#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Fail-closed discovery and board attribution for quarantined receipt writes."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Iterable, MutableMapping, Sequence


QUARANTINE_SUFFIX = ".INVALID.quarantine"
_CONDITION_RE = re.compile(r"^C(?:\([−-]?1\)|-[A-Z0-9]+|[0-9]+)$")


def _condition_hint(path: Path) -> str | None:
    """Return a condition id from preserved JSON bytes when one is available."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    value = payload.get("condition")
    if isinstance(value, str) and _CONDITION_RE.fullmatch(value):
        return value
    return None


def discover_quarantines(
    labeled_roots: Iterable[tuple[str, str | Path]],
) -> list[dict[str, str | None]]:
    """Find files whose names end with the exact quarantine suffix."""
    findings: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for label, raw_root in labeled_roots:
        root = Path(raw_root)
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            for filename in sorted(filenames):
                if not filename.endswith(QUARANTINE_SUFFIX):
                    continue
                path = Path(dirpath) / filename
                relative = path.relative_to(root).as_posix()
                disclosed = f"{label}/{relative}"
                physical_key = os.path.normcase(str(path.resolve(strict=False)))
                if physical_key in seen:
                    continue
                seen.add(physical_key)
                findings.append(
                    {
                        "path": disclosed,
                        "condition_hint": _condition_hint(path),
                    }
                )
    findings.sort(key=lambda row: str(row["path"]))
    return findings


def apply_quarantine_flags(
    rows: Sequence[MutableMapping[str, object]],
    findings: Sequence[MutableMapping[str, object]],
    process_invariants: set[str],
) -> None:
    """Attach fail-closed audit outcomes to affected board rows."""
    by_condition = {
        row.get("condition"): row
        for row in rows
        if isinstance(row.get("condition"), str)
    }
    unattributed: list[str] = []
    for finding in findings:
        path = finding.get("path")
        hint = finding.get("condition_hint")
        if not isinstance(path, str):
            continue
        row = by_condition.get(hint)
        if row is None:
            unattributed.append(path)
            continue
        prior = str(row.get("reason", ""))
        row["status"] = (
            "AUDIT-INCIDENT" if hint in process_invariants else "UNEVALUABLE"
        )
        row["reason"] = (
            f"QUARANTINED RECEIPT ATTEMPT: {path} ends with "
            f"{QUARANTINE_SUFFIX}; stale fallback is forbidden. "
            f"Prior probe result: {prior}"
        )
        row["quarantine_audit"] = [path]

    if unattributed:
        audit_row = by_condition.get("C0")
        if audit_row is None:
            raise ValueError(
                "unattributed quarantined receipts require the C0 audit row"
            )
        prior = str(audit_row.get("reason", ""))
        audit_row["status"] = "AUDIT-INCIDENT"
        audit_row["reason"] = (
            "QUARANTINED RECEIPT ATTEMPT(S) unattributed to a consuming "
            f"condition: {', '.join(unattributed)}. Stale fallback is "
            f"forbidden. Prior probe result: {prior}"
        )
        audit_row["quarantine_audit"] = list(unattributed)
