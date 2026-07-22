#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Canonicalize issue references across the legacy and github tracker eras.

Reference implementation for docs/spec/issue-reference-v1.md (R4 / cond9).

Two issue-numbering eras share the bare ``#N`` notation, so an unqualified
``#N`` is ambiguous whenever ``N`` falls inside the legacy range. This module
resolves a raw reference to exactly one canonical token — ``legacy:<n>`` /
``github:<n>`` / ``unknown:<n>`` — via an explicit qualifier or a sidecar
mapping, and FAILS CLOSED in strict mode on an unqualified ambiguous reference.

Historical bytes are never rewritten: resolution is layered on via the sidecar,
never by mutating the files that cite ``#N``.

Library:
    from normalize_issue_reference import Sidecar, normalize
    sidecar = Sidecar.from_path("path/to/sidecar.json")   # or Sidecar.empty()
    normalize("#207", sidecar, strict=True)               # raises if ambiguous
    normalize("gh#207", sidecar)                           # -> "github:207"

CLI:
    PYTHONIOENCODING=utf-8 python scripts/normalize_issue_reference.py \
        --sidecar sidecar.json --strict '#207'
    # prints the canonical form, or exits nonzero + stderr on fail-closed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

LEGACY = "legacy"
GITHUB = "github"
UNKNOWN = "unknown"
_ERAS = (LEGACY, GITHUB, UNKNOWN)

# A qualifier followed by a bare number, e.g. "legacy:207" or "github: 29".
_QUALIFIED = re.compile(r"^(legacy|github|unknown)\s*:\s*(\d+)$", re.IGNORECASE)
# Accepted aliases -> era.
_ALIASES = (
    (re.compile(r"^l\s*#\s*(\d+)$", re.IGNORECASE), LEGACY),
    (re.compile(r"^(?:gh\s*#|gh-)\s*(\d+)$", re.IGNORECASE), GITHUB),
)
# A bare reference: optional leading '#', then digits only.
_BARE = re.compile(r"^#?\s*(\d+)$")


class AmbiguousReferenceError(ValueError):
    """Raised in strict mode when a reference cannot be resolved to an era."""


class Sidecar:
    """Resolution authority: a genesis boundary plus a per-number era map.

    ``genesis_boundary`` is the highest issue number the legacy tracker ever
    assigned. ``None`` means +infinity — every bare number is ambiguous (the
    safe default when no sidecar is supplied).
    """

    def __init__(self, genesis_boundary: "int | None" = None, mapping: "dict | None" = None):
        if genesis_boundary is not None:
            if not isinstance(genesis_boundary, int) or isinstance(genesis_boundary, bool) or genesis_boundary < 0:
                raise ValueError("genesis_boundary must be a non-negative integer or None")
        self.genesis_boundary = genesis_boundary
        self._map: "dict[str, str]" = {}
        for key, era in (mapping or {}).items():
            era_l = str(era).strip().lower()
            if era_l not in (LEGACY, GITHUB):
                raise ValueError(f"sidecar map era must be 'legacy' or 'github', got {era!r} for {key!r}")
            self._map[str(key).lstrip("#").strip()] = era_l

    @classmethod
    def empty(cls) -> "Sidecar":
        return cls(genesis_boundary=None, mapping=None)

    @classmethod
    def from_dict(cls, data: dict) -> "Sidecar":
        if not isinstance(data, dict):
            raise ValueError("sidecar document must be a JSON object")
        return cls(genesis_boundary=data.get("genesis_boundary"), mapping=data.get("map"))

    @classmethod
    def from_path(cls, path) -> "Sidecar":
        raw = Path(path).read_text(encoding="utf-8")
        return cls.from_dict(json.loads(raw))

    def era_for(self, number: int) -> "str | None":
        """Return the mapped era for a bare number, or None if unmapped."""
        return self._map.get(str(number))


def _canon(era: str, number: int) -> str:
    return f"{era}:{number}"


def normalize(raw, sidecar: "Sidecar | None" = None, strict: bool = False) -> str:
    """Resolve ``raw`` to a canonical ``era:number`` token.

    Order: explicit qualifier -> alias -> sidecar map -> boundary heuristic ->
    ambiguous (fail closed in strict mode, ``unknown:<n>`` in lenient mode).
    """
    if sidecar is None:
        sidecar = Sidecar.empty()
    text = str(raw).strip()

    # 1a. Explicit canonical qualifier.
    m = _QUALIFIED.match(text)
    if m:
        return _canon(m.group(1).lower(), int(m.group(2)))

    # 1b. Accepted aliases.
    for pattern, era in _ALIASES:
        m = pattern.match(text)
        if m:
            return _canon(era, int(m.group(1)))

    # Extract the bare number; anything else is malformed.
    m = _BARE.match(text)
    if not m:
        if strict:
            raise AmbiguousReferenceError(f"unparseable issue reference: {raw!r}")
        return f"{UNKNOWN}:{text}" if text else f"{UNKNOWN}:"
    number = int(m.group(1))

    # 2. Sidecar per-number entry.
    mapped = sidecar.era_for(number)
    if mapped is not None:
        return _canon(mapped, number)

    # 3. Boundary heuristic: above the legacy range -> unambiguously github.
    if sidecar.genesis_boundary is not None and number > sidecar.genesis_boundary:
        return _canon(GITHUB, number)

    # 4. Ambiguous.
    if strict:
        raise AmbiguousReferenceError(
            f"unqualified ambiguous issue reference {raw!r}: number {number} is within the "
            f"legacy overlap range and has no qualifier or sidecar entry"
        )
    return _canon(UNKNOWN, number)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("reference", help="raw issue reference, e.g. '#207', 'gh#29', 'legacy:12'")
    p.add_argument("--sidecar", default=None, help="path to a sidecar JSON mapping (see spec)")
    p.add_argument("--strict", action="store_true", help="fail closed on an unqualified ambiguous reference")
    return p


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    sidecar = Sidecar.from_path(args.sidecar) if args.sidecar else Sidecar.empty()
    try:
        print(normalize(args.reference, sidecar, strict=args.strict))
    except AmbiguousReferenceError as exc:
        print(f"FAIL-CLOSED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
