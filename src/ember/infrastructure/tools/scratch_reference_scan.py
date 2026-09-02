#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Read-only reference/duplicate advisory scan for ``scratch/`` top-level entries (issue #1450).

This tool never moves, deletes, or authorizes moving/deleting a single byte, and it grants no
disposition. ``src/ember/infrastructure/tools/scratch_custody.py`` already enforces that: every disposition entry its
schema accepts is hard-locked to ``KEEP_UNRESOLVED`` (see its ``validate_disposition``), and its
``identical_copy`` enum has no ``PROVEN_IDENTICAL`` value at all -- "found a duplicate" and
"authorized to delete one" are kept structurally unable to collide, and that authorization does
not exist anywhere in this codebase yet. This tool exists one step upstream of that: it produces
the two evidence signals a future disposition author needs before ever proposing to widen that
schema, and it fails toward showing MORE candidate evidence rather than less.

Two signals, both advisory:

1. ``references`` -- every tracked repository file whose text contains either the entry's bare
   name (``name_hits``) or its literal ``scratch/<name>`` path (``path_hits``), reported
   SEPARATELY and then unioned. Do not read an empty ``path_hits`` as "unreferenced": a live
   consumer can build the path from separate segments at runtime
   (``Path(...) / "scratch" / "rung2-optstate"``) without the literal substring
   ``scratch/rung2-optstate`` ever appearing in its source, and grep cannot see that. This is
   not a hypothetical -- ``src/ember/governance/scripts/cpu_offload_adamw.py`` does exactly this for
   ``rung2-optstate`` (the single largest entry in the live census), and only ``name_hits``
   finds it; a scan that trusted ``path_hits`` alone would have called it unreferenced. Treat
   every field this tool reports as a FLOOR on what is referenced, never a ceiling: absence of
   a hit is proof grep found nothing, not proof no consumer exists. Manual reading of each
   ``name_hits`` file is still required before any entry can be adjudicated safe to move.

2. ``duplicate-check`` -- for a caller-supplied pair of entries, a whole-tree content hash
   (relative path + bytes, sorted, streamed) proving ``PROVEN_IDENTICAL`` or
   ``PROVEN_DIFFERENT``. Used to answer the census's explicit open question: whether the two
   byte-identical-sized ``screen792-*`` directories are actually duplicates (they are not --
   different file counts, different tree hash).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

# Reuse the canonical authority/invariant/convention constants rather than re-declaring them,
# so this tool's receipts cannot drift from scratch_custody.py's under repository schema
# changes -- both are read by the same repo-guard receipt-floor check. The two import forms
# cover this module's two run contexts: `python src/ember/infrastructure/tools/scratch_reference_scan.py` puts `tools/`
# itself on sys.path (no `tools` package visible), while `from tools import
# scratch_reference_scan` (pytest, run from the repo root) puts the repo root on sys.path (only
# the qualified form resolves).
try:
    from src.ember.infrastructure.tools.scratch_custody import AUTHORITY, INVARIANT_SHA256, SHA_CONVENTION
except ImportError:
    from scratch_custody import AUTHORITY, INVARIANT_SHA256, SHA_CONVENTION  # type: ignore[no-redef]

SCHEMA_VERSION = "ember-scratch-reference-scan-v1"
REFERENCE_TICKET = "ISSUE-1450-SCRATCH-REFERENCE-SCAN"
DUPLICATE_TICKET = "ISSUE-1450-SCRATCH-DUPLICATE-CHECK"

# Tracked paths that describe scratch/ itself (census manifests, disposition receipts, and
# their schema docs) are excluded from the reference scan. Every one of those documents lists
# every top-level entry name by design, so including them would make every entry spuriously
# "referenced" by its own inventory record rather than by a genuine consumer.
SELF_REFERENTIAL_PREFIXES: tuple[str, ...] = (
    "receipts/issue-1450/",
    "docs/hygiene/issue-1450-",
)


class ScanError(ValueError):
    """Raised for an unusable root, entry name, or output target."""


def _tracked_grep(root: Path, needle: str) -> list[str]:
    """Tracked files (relative, posix) whose content contains ``needle`` literally.

    ``git grep`` exits 1 for "ran fine, found nothing" -- an ordinary result, not a failure --
    and only other nonzero codes (bad revision, not a Git worktree, ...) are real errors. A
    generic ``check=True`` wrapper cannot tell these apart, so this reimplements the call
    directly instead of routing through ``_git``.
    """
    if not needle:
        raise ScanError("grep needle must be nonempty")
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "grep", "--fixed-strings", "--files-with-matches", "-z", "--", needle],
            capture_output=True,
            text=True,
            shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        raise ScanError(f"git grep could not run: {exc}") from exc
    if result.returncode not in (0, 1):
        raise ScanError(f"git grep failed: {result.stderr.strip() or result.returncode}")
    hits = sorted({raw.replace("\\", "/") for raw in result.stdout.split("\0") if raw})
    return [
        hit for hit in hits if not any(hit.startswith(prefix) for prefix in SELF_REFERENTIAL_PREFIXES)
    ]


def scan_entry(root: Path, name: str) -> dict[str, Any]:
    if not name or "/" in name or "\\" in name or name in {".", ".."}:
        raise ScanError(f"invalid top-level entry name: {name!r}")
    own_prefix = f"scratch/{name}/"
    own_path = f"scratch/{name}"
    name_hits = [hit for hit in _tracked_grep(root, name) if not hit.startswith(own_prefix) and hit != own_path]
    path_hits = [
        hit for hit in _tracked_grep(root, own_path) if not hit.startswith(own_prefix) and hit != own_path
    ]
    references = sorted(set(name_hits) | set(path_hits))
    return {
        "path": name,
        "name_hits": name_hits,
        "path_hits": path_hits,
        "references": references,
    }


def scan_all(root: Path, names: list[str]) -> dict[str, dict[str, Any]]:
    root = Path(root)
    if not root.is_dir():
        raise ScanError("scan root is not a directory")
    return {name: scan_entry(root, name) for name in names}


def _hash_tree(path: Path) -> tuple[str, int]:
    """Deterministic whole-tree digest: sorted (relative path, bytes) pairs, streamed."""
    if not path.is_dir():
        raise ScanError(f"duplicate-check target is not a directory: {path}")
    relatives: list[str] = []
    for current, _dirs, files in os.walk(path):
        for name in files:
            full = Path(current) / name
            relative = PurePosixPath(*full.relative_to(path).parts).as_posix()
            relatives.append(relative)
    relatives.sort()
    digest = hashlib.sha256()
    for relative in relatives:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with (path / relative).open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest(), len(relatives)


def duplicate_check(root: Path, name_a: str, name_b: str) -> dict[str, Any]:
    root = Path(root)
    for name in (name_a, name_b):
        if not name or "/" in name or "\\" in name or name in {".", ".."}:
            raise ScanError(f"invalid top-level entry name: {name!r}")
    if name_a == name_b:
        raise ScanError("duplicate-check requires two distinct entries")
    sha_a, files_a = _hash_tree(root / "scratch" / name_a)
    sha_b, files_b = _hash_tree(root / "scratch" / name_b)
    return {
        "a": {"path": name_a, "files": files_a, "tree_sha256": sha_a},
        "b": {"path": name_b, "files": files_b, "tree_sha256": sha_b},
        "result": "PROVEN_IDENTICAL" if sha_a == sha_b else "PROVEN_DIFFERENT",
    }


def _receipt(ticket: str, body: dict[str, Any]) -> dict[str, Any]:
    """Wrap ``body`` in the repository's receipt floor: ticket, ts, authority, invariant.

    ``src/ember/governance/scripts/receipt_check.py`` requires ``ticket``/``ts`` on every JSON file under
    ``receipts/``, requires ``invariant_sha256`` to equal the repository constant on receipts
    timestamped after the genesis cutover, and requires ``sha_convention`` whenever any KEY
    NAME matches the sha256 pattern anywhere in the first three levels of nesting -- which
    ``invariant_sha256`` itself always does, so every receipt carrying it needs
    ``sha_convention`` unconditionally, not only the ones with a content hash of their own.
    ``scripts/verify_authority_conservation.py`` separately requires a top-level ``authority``
    binding with the current goal/workstream/outcome. All four are satisfied here, once, so
    every caller gets a passing receipt instead of re-deriving the floor per output.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "ticket": ticket,
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "authority": dict(AUTHORITY),
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        **body,
    }


def _write_json(output: Path, payload: dict[str, Any]) -> Path:
    if output.exists():
        raise ScanError(f"output destination already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    temporary = output.with_name(output.name + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    references = subparsers.add_parser("references")
    references.add_argument("--root", required=True, type=Path)
    references.add_argument("--manifest", required=True, type=Path, help="scratch_custody.py census manifest")
    references.add_argument("--output", required=True, type=Path)

    dup = subparsers.add_parser("duplicate-check")
    dup.add_argument("--root", required=True, type=Path)
    dup.add_argument("--a", required=True, dest="name_a")
    dup.add_argument("--b", required=True, dest="name_b")
    dup.add_argument("--output", type=Path, default=None)

    args = parser.parse_args(argv)
    try:
        if args.command == "references":
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
            names = [row["path"] for row in manifest["top_level"]]
            result = scan_all(args.root, names)
            receipt = _receipt(REFERENCE_TICKET, {"entries": result})
            _write_json(args.output, receipt)
            print("REFERENCE_SCAN_WRITTEN")
        else:
            result = duplicate_check(args.root, args.name_a, args.name_b)
            receipt = _receipt(DUPLICATE_TICKET, result)
            if args.output is not None:
                _write_json(args.output, receipt)
            print(json.dumps(receipt, indent=2, sort_keys=True))
        return 0
    except (ScanError, OSError, json.JSONDecodeError, KeyError) as exc:
        print(f"SCAN_REFUSED: {exc}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_cli(os.sys.argv[1:]))
