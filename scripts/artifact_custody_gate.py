#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Shared custody-verify gate (#1721): the one path every preflight that names a
subject artifact by hash uses to fail closed on unverified custody.

Shells out to the real `ember-lab custody-verify` CLI
(``runtime/ember-lab/src/main.rs``) -- never reimplements the check in Python -- so
every Python-side gate consumes the exact same catalog logic the Rust suite proves
(``domains/runtime/runtime/ember-lab/tests/artifact_custody.rs``). The receipt is always written to
disk before the admission decision, mirroring the CLI's own convention: a refusal is
never reported without a receipt naming the exact per-hash verdict (``verified`` /
``size_mismatch`` / ``absent_at_registered_location`` / ``no_registered_location``).

This module never re-derives an "absence" verdict from a filesystem search -- it
only ever reports what the catalog itself resolved. That is the exact property
#1721 exists to establish: "searched and did not find" stops being an admissible
basis for a missing-verdict.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

#: The volume name a resume-checkpoint's location row is registered under. A fixed,
#: symbolic label -- never a host path -- so a preflight that only knows the
#: checkpoint directory it is about to load from can always name the one volume its
#: own root covers, without needing to discover which volume name the object's
#: original writer chose. Any checkpoint intended to be resumable must carry at
#: least one location row registered under this volume (locator = shard filename
#: relative to the checkpoint directory).
RESUME_CHECKPOINT_VOLUME = "resume-checkpoint"


class CustodyRefused(RuntimeError):
    """A custody-verify preflight refused. ``receipt`` carries the exact per-hash
    verdicts, so a caller can quote the catalog fact rather than restate a search."""

    def __init__(self, message: str, receipt: Mapping[str, Any]):
        super().__init__(message)
        self.receipt = receipt


def _durable_repo_root(repo_root: Path) -> Path:
    """The durable main-tree root for ``repo_root``'s repository, resolved via
    ``git rev-parse --path-format=absolute --git-common-dir`` -- never
    ``Path(__file__).resolve()``, which names whichever tree happens to be
    executing this module (#1741 Known Limitation B).

    Precedent: ``scripts/worktree_lifecycle.py::common_dir`` and
    ``scripts/ember_restart/source_authority.py::_common_dir``. A genuine main
    checkout's ``.git`` is a real directory that IS the common dir; a worktree's
    (lifecycle-managed or ad hoc) ``.git`` is a FILE pointing elsewhere -- so the
    common dir's parent always names the main tree, whichever tree issued the
    query. This is a purely local ``rev-parse`` (no remote contact), so the
    remote-config-injection hardening ``scripts/git_env_hardening.py`` exists for
    does not apply here; matches this module's own unhardened ``custody_verify``
    subprocess style.
    """
    root = repo_root.resolve(strict=True)
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(f"artifact custody gate: git identity is unavailable for {root}")
    common_dir = Path(result.stdout.strip()).resolve(strict=True)
    return common_dir.parent


def canonical_ember_lab_binary(repo_root: Path) -> Path | None:
    """The one repository-governed daemon/CLI binary -- never a caller-supplied path.

    Mirrors ``scripts/ember_dispatch_token.py::_canonical_ember_lab_binary`` exactly:
    the same two candidate build outputs, the same containment check. Always
    resolved against the durable main-tree root (``_durable_repo_root``), even
    when ``repo_root`` names a worktree -- there is exactly one governed build,
    never a per-worktree copy.
    """
    root = _durable_repo_root(repo_root)
    for candidate in (
        root / "runtime" / "ember-lab" / "target" / "release" / "ember-lab.exe",
        root / "runtime" / "ember-lab" / "target" / "debug" / "ember-lab.exe",
    ):
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_file() and resolved.is_relative_to(root):
            return resolved
    return None


def default_catalog_db(repo_root: Path) -> Path:
    """The one host-durable data-catalog database every custody gate reads.

    Lives under the gitignored ``state/`` directory at the repository root (never
    inside a worktree, which is retired and deleted independently of the catalog it
    would otherwise silently take with it) -- the same durability class as the
    other host-state ``state/`` carries today. Always resolved against the
    durable main-tree root (``_durable_repo_root``), even when ``repo_root``
    names a worktree.
    """
    return _durable_repo_root(repo_root) / "state" / "ember-lab-catalog.sqlite3"


def custody_verify(
    repo_root: Path,
    hashes: Sequence[str],
    roots: Mapping[str, Path],
    *,
    db: Path | None = None,
    rehash: bool = False,
    receipt_path: Path | None = None,
) -> dict[str, Any]:
    """Runs the real ``ember-lab custody-verify`` CLI and returns the parsed receipt.

    Raises :class:`CustodyRefused` -- never silently returns a non-admitted receipt --
    the instant any named hash is not verified. The receipt is always written to
    disk before this function raises or returns, so a caller that catches
    ``CustodyRefused`` can always quote ``error.receipt`` rather than re-derive one.

    ``rehash=False`` (the default) checks existence and declared byte count only --
    the fast check appropriate for gating a launch that will itself stream and use
    the bytes, which would otherwise re-detect any real corruption. Pass
    ``rehash=True`` for a standalone custody audit where no downstream read would
    catch a bit-flip.
    """
    if not hashes:
        raise ValueError("custody_verify requires at least one hash")
    binary = canonical_ember_lab_binary(repo_root)
    if binary is None:
        refusal = {
            "schema_version": "ember-custody-verify-receipt-v1",
            "admitted": False,
            "results": [],
            "refusal_reason": (
                "no canonical ember-lab binary is built under this repository "
                "(runtime/ember-lab/target/{release,debug}/ember-lab.exe)"
            ),
        }
        raise CustodyRefused(
            "custody-verify: no canonical ember-lab binary is built", refusal
        )
    db_path = db if db is not None else default_catalog_db(repo_root)

    owns_receipt_tmp = receipt_path is None
    if owns_receipt_tmp:
        # A path inside a fresh directory that is NOT itself pre-created: the
        # only way `receipt_path.exists()` below tells the truth about whether
        # the CLI actually wrote a receipt, rather than about whether this
        # function touched the filesystem first. `NamedTemporaryFile` creates
        # its file eagerly, which would make that check permanently vacuous.
        receipt_dir = Path(tempfile.mkdtemp(prefix="custody-verify-"))
        receipt_path = receipt_dir / "receipt.json"
    else:
        receipt_dir = None

    args = [str(binary), "custody-verify", "--db", str(db_path)]
    for one_hash in hashes:
        args += ["--hash", one_hash]
    for volume, root in roots.items():
        args += ["--root", f"{volume}={root}"]
    if rehash:
        args.append("--rehash")
    args += ["--receipt", str(receipt_path)]

    completed = subprocess.run(args, capture_output=True, text=True)

    if not receipt_path.exists():
        # The CLI never reached its own receipt-write step -- e.g. the catalog
        # database itself has never been initialized (custody-verify opens it
        # read-only and cannot bootstrap a schema; only a prior write such as
        # register-artifact creates one). Still fails closed, but with the
        # real process failure quoted rather than an opaque crash surfacing
        # from a caller that assumed a receipt always exists.
        refusal = {
            "schema_version": "ember-custody-verify-receipt-v1",
            "admitted": False,
            "results": [],
            "refusal_reason": (
                "custody-verify produced no receipt file "
                f"(exit={completed.returncode}): "
                f"{completed.stderr.strip() or completed.stdout.strip()}"
            ),
        }
        raise CustodyRefused(
            "custody-verify refused without writing a receipt; refusing without "
            "one is not an admissible refusal for this gate",
            refusal,
        )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if owns_receipt_tmp:
        try:
            receipt_path.unlink()
            if receipt_dir is not None:
                receipt_dir.rmdir()
        except OSError:
            pass
    if receipt.get("admitted") is not True:
        raise CustodyRefused(
            "custody-verify refused: " + json.dumps(receipt.get("results", [])),
            receipt,
        )
    return receipt


def checkpoint_manifest_hashes(manifest: Mapping[str, Any]) -> list[str]:
    """The full pinned-hash set for a checkpoint manifest's own bytes: every shard
    declared in ``manifest["shards"]``. Order is stable (manifest declaration order)
    so a receipt's per-hash results line up with the manifest for a human reader.

    Returns ``[]`` -- not an error -- when the manifest carries no ``shards`` key at
    all: every real checkpoint schema this repo writes (``ember-sparse-checkpoint-v3``,
    ``-v5``) always declares one, so an absent key means the manifest predates a real
    shard-hash contract (a synthetic/reduced fixture, e.g. in tests) rather than a
    checkpoint whose custody this gate should refuse to admit. A *present but
    malformed* ``shards`` entry (wrong type, missing ``sha256``) still raises: that is
    a real checkpoint manifest failing to honor its own declared contract.
    """
    shards = manifest.get("shards")
    if shards is None:
        return []
    if not isinstance(shards, list):
        raise ValueError("checkpoint manifest 'shards' must be a list")
    hashes: list[str] = []
    for shard in shards:
        sha256 = shard.get("sha256") if isinstance(shard, Mapping) else None
        if not isinstance(sha256, str) or not sha256:
            raise ValueError(f"checkpoint manifest shard entry has no sha256: {shard!r}")
        hashes.append(sha256)
    return hashes
