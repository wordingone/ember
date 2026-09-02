#!/usr/bin/env python3
"""Shared fail-closed VOID-supersession exclusion logic.

The scanner and C(-1) probe consume this one implementation so their decisive
receipt corpora cannot drift. A VOID receipt may identify a target by:

* its complete 64-character SHA-256; or
* an unambiguous hexadecimal SHA-256 prefix of at least 16 characters.

The filename must remain a bare basename. A malformed, short, non-hexadecimal,
or ambiguous reference excludes nothing. Historical append-only VOID receipts
therefore remain unchanged while the known 16-character-prefix convention can
be interpreted without weakening the hash binding.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

from __future__ import annotations

import os
import re
from typing import Any

from _lane14_common import sha256_file


_SHA256_REFERENCE_RE = re.compile(r"^[0-9a-fA-F]{16,64}$")


def _normalized_sha256_reference(value: Any) -> str | None:
    """Return a normalized full digest/prefix, or None for unsafe input."""
    if not isinstance(value, str) or _SHA256_REFERENCE_RE.fullmatch(value) is None:
        return None
    return value.lower()


def _receipt_records(decisive, root):
    """Materialize receipt identities once for deterministic resolution."""
    records = []
    for path, _data, _raw in decisive:
        rel = os.path.relpath(path, root).replace("\\", "/")
        records.append(
            {
                "path": path,
                "rel": rel,
                "basename": os.path.basename(rel),
                "sha256": sha256_file(path).lower(),
            }
        )
    return records


def compute_superseded_targets(decisive, root):
    """Resolve valid VOID entries to unique target receipt identities.

    Returns a mapping keyed by ``(basename, full_sha256)``. Each value records
    the superseding VOID receipt, the exact digest text it supplied, and whether
    that text was a full digest or an unambiguous prefix.

    A reference resolves only when exactly one *other* decisive receipt has the
    named basename and a full on-disk digest beginning with the supplied
    reference. Ambiguity fails closed, including duplicate same-basename files.
    """
    records = _receipt_records(decisive, root)
    superseded_targets = {}

    for (void_path, void_data, _void_raw), void_record in zip(decisive, records):
        if not isinstance(void_data, dict) or void_data.get("verdict") != "VOID":
            continue
        supersedes = void_data.get("supersedes")
        if not isinstance(supersedes, list):
            continue

        for entry in supersedes:
            if not isinstance(entry, dict):
                continue
            filename = entry.get("filename")
            digest_ref = _normalized_sha256_reference(entry.get("sha256"))
            if (
                not isinstance(filename, str)
                or not filename
                or filename != os.path.basename(filename)
                or digest_ref is None
            ):
                continue

            matches = [
                record
                for record in records
                if record["path"] != void_path
                and record["basename"] == filename
                and record["sha256"].startswith(digest_ref)
            ]
            if len(matches) != 1:
                continue

            target = matches[0]
            key = (target["basename"], target["sha256"])
            superseded_targets.setdefault(
                key,
                {
                    "superseded_by": void_record["rel"],
                    "matched_sha256": digest_ref,
                    "sha256_match_kind": (
                        "full" if len(digest_ref) == 64 else "unambiguous_prefix"
                    ),
                },
            )

    return superseded_targets


def partition_superseded(decisive, root):
    """Split ``decisive`` into kept and explicitly disclosed exclusions."""
    superseded_targets = compute_superseded_targets(decisive, root)
    kept = []
    excluded = []

    for path, data, raw in decisive:
        rel = os.path.relpath(path, root).replace("\\", "/")
        receipt_sha = sha256_file(path).lower()
        match = superseded_targets.get((os.path.basename(rel), receipt_sha))
        if match is None:
            kept.append((path, data, raw))
            continue

        excluded.append(
            {
                "path": rel,
                "sha256": receipt_sha,
                "superseded_by": match["superseded_by"],
                "matched_sha256": match["matched_sha256"],
                "sha256_match_kind": match["sha256_match_kind"],
                "reason": (
                    "named in another VOID receipt's supersedes list and "
                    "resolved by bare basename plus a full SHA-256 or an "
                    "unambiguous hexadecimal SHA-256 prefix of at least 16 "
                    "characters; formally disposed and excluded from the "
                    "decisive-claim set per issues #353/#358/#427. Malformed "
                    "or ambiguous references exclude nothing. The superseding "
                    "VOID receipt itself remains in the decisive-claim set."
                ),
            }
        )

    return kept, excluded
