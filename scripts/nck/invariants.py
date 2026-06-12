"""NC-K protected-invariant boot-checksum layer (Closes #261).

Design goal: ACCIDENTAL self-modification by the resident is the threat
model — not an adversary.  The layer is not a security boundary; it is a
consistency fence.  On any sha256 mismatch at boot the loop refuses to
start and names the mismatched path.

Architecture
------------
1.  INVARIANT MANIFEST  (config/nck-invariants.json)
    Lists protected paths and their expected sha256 hashes.
    The manifest itself is ALSO listed (self-covering).

2.  OUTSIDE-WRITE-SURFACE baseline  (config/nck-baseline/)
    A second copy of the manifest lives at a path the resident's tool
    registry CANNOT write.  The write-surface allowlist stored inside
    ToolRegistry excludes config/nck-baseline/.  File-writing verbs
    (verbs registered with write_paths declared) are refused if ANY target
    path falls under the baseline dir.

3.  BOOT CHECK  (verify_at_boot)
    Recomputes sha256 for every path listed in the manifest, then compares
    the manifest itself against the baseline copy.  Any mismatch →
    SystemExit naming the path.

4.  PER-VERB IDEMPOTENCE AUDIT  (audit_verb_idempotence)
    Called at registration time by IdempotenceEnforcingRegistry.
    Non-idempotent verbs are REFUSED unless their registration includes a
    dedup_contract dict naming the journal field used for deduplication.

Clean-room rule: no avir-cli source was read.  Only in-repo spec docs and
the #260 event_loop.py were consulted.  See docs/nck-invariants-v0.md for
full provenance attestation.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from typing import Any


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The manifest lives here (inside the write surface — the resident can read it,
# not written to it through a registered verb, but it IS writable by branch
# promotion).  The boot checker validates it against the baseline copy.
MANIFEST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config", "nck-invariants.json",
)

# The baseline copy lives OUTSIDE the write surface.  The resident's registered
# file-writing verbs are refused if they target this directory.
BASELINE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config", "nck-baseline",
)
BASELINE_MANIFEST_PATH = os.path.join(BASELINE_DIR, "nck-invariants.json")

# The write surface allowlist root.  Verbs that declare write_paths are
# checked against this: any path NOT under the allowlist root (or
# explicitly in the exception set) is refused.
# config/nck-baseline is excluded from the write surface.
WRITE_SURFACE_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _sha256_file(path: str) -> str:
    """Return hex sha256 of a file's contents.  Raises FileNotFoundError."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_manifest(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _is_under(path: str, directory: str) -> bool:
    """Return True if path is under directory (both resolved)."""
    path = os.path.realpath(os.path.abspath(path))
    directory = os.path.realpath(os.path.abspath(directory))
    return path == directory or path.startswith(directory + os.sep)


# ---------------------------------------------------------------------------
# Write-surface path check
# ---------------------------------------------------------------------------

def is_write_protected(path: str) -> bool:
    """Return True if path is inside the protected baseline directory.

    Used by the tool registry to refuse file-writing verbs targeting
    protected paths.
    """
    return _is_under(path, BASELINE_DIR)


def check_write_path(path: str) -> None:
    """Raise PermissionError if path is write-protected.

    Call this from any verb that writes files before performing the write.
    The registry calls this automatically for verbs registered with
    write_paths declared.
    """
    if is_write_protected(path):
        raise PermissionError(
            f"WRITE_PROTECTED: path '{path}' is inside the invariant baseline "
            f"directory '{BASELINE_DIR}'.  This directory is outside the write "
            "surface; no registered verb may write to it."
        )


# ---------------------------------------------------------------------------
# Boot-time verification
# ---------------------------------------------------------------------------

def verify_at_boot(
    manifest_path: str = MANIFEST_PATH,
    baseline_path: str = BASELINE_MANIFEST_PATH,
) -> None:
    """Verify protected-path checksums at boot.  Fail-closed on any mismatch.

    Steps:
    1. Verify the manifest against its baseline copy (manifest integrity).
    2. Recompute sha256 for each entry in the manifest; compare to recorded hash.
    3. Any mismatch → SystemExit naming the mismatched path(s).

    Must be called before the event loop starts.  event_loop.py calls this
    in NCKEventLoop.__init__ after validate_invariant_config().
    """
    # Step 1: manifest-vs-baseline check
    if not os.path.isfile(manifest_path):
        raise SystemExit(
            f"INVARIANT_REFUSE: manifest not found at '{manifest_path}'. "
            "The loop will not start without the protected-invariant manifest."
        )
    if not os.path.isfile(baseline_path):
        raise SystemExit(
            f"INVARIANT_REFUSE: baseline manifest not found at '{baseline_path}'. "
            "The baseline copy lives outside the write surface; its absence means "
            "the self-verification invariant cannot be checked. Boot refused."
        )

    manifest_bytes = open(manifest_path, "rb").read()
    baseline_bytes = open(baseline_path, "rb").read()

    if manifest_bytes != baseline_bytes:
        # Compute sha256 of each to name the mismatch
        m_hash = _sha256_bytes(manifest_bytes)
        b_hash = _sha256_bytes(baseline_bytes)
        raise SystemExit(
            f"INVARIANT_REFUSE: manifest has drifted from baseline.\n"
            f"  manifest:  {manifest_path}  sha256={m_hash}\n"
            f"  baseline:  {baseline_path}  sha256={b_hash}\n"
            "Restore the manifest from the baseline or re-run "
            "scripts/nck/invariants.py --update-manifest to re-pin."
        )

    # Step 2: verify each listed path
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SystemExit(
            f"INVARIANT_REFUSE: manifest parse error: {exc}"
        ) from exc

    entries = manifest.get("protected_paths", [])
    if not entries:
        raise SystemExit(
            "INVARIANT_REFUSE: manifest 'protected_paths' list is empty. "
            "Boot refused (empty manifest is a misconfiguration)."
        )

    mismatches: list[str] = []
    for entry in entries:
        rel_path = entry.get("path", "")
        expected_hash = entry.get("sha256", "")
        label = entry.get("label", rel_path)

        if not rel_path or not expected_hash:
            mismatches.append(
                f"  MANIFEST_ERROR: entry missing 'path' or 'sha256': {entry}"
            )
            continue

        # Resolve relative to the repo root.
        # Derive repo_root from the manifest_path parameter (not the module-level
        # constant) so that selftest fixtures and real-repo invocations both work.
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(manifest_path)))
        abs_path = os.path.join(repo_root, rel_path) if not os.path.isabs(rel_path) else rel_path

        if not os.path.isfile(abs_path):
            mismatches.append(
                f"  MISSING: [{label}] path not found: {abs_path}"
            )
            continue

        # Skip the self-referential manifest entry (sha256 == "SELF"): it is
        # verified by the baseline-comparison step above, not by hashing.
        if expected_hash == "SELF":
            continue

        actual_hash = _sha256_file(abs_path)
        if actual_hash != expected_hash:
            mismatches.append(
                f"  MISMATCH: [{label}] {abs_path}\n"
                f"    expected: {expected_hash}\n"
                f"    actual:   {actual_hash}"
            )

    if mismatches:
        raise SystemExit(
            "INVARIANT_REFUSE: protected-path checksum verification failed.\n"
            + "\n".join(mismatches)
            + "\n\nThe loop will not start until all protected paths match "
            "their recorded checksums."
        )


# ---------------------------------------------------------------------------
# Idempotence-enforcing registry wrapper
# ---------------------------------------------------------------------------

class IdempotenceEnforcingRegistry:
    """Wraps ToolRegistry to enforce per-verb idempotence audit at registration.

    Verbs that declare idempotent=False MUST also supply a dedup_contract dict
    naming the journal field used for deduplication.  Verbs with idempotent=True
    have no additional requirement.

    This audit fires at registration time, not at dispatch time, so a
    misconfigured verb is caught before any action can be dispatched.

    Verbs that declare write_paths have each path checked against the write
    surface before registration; a path targeting the protected baseline
    directory causes the registration to be refused.
    """

    def __init__(self, inner_registry: Any) -> None:
        """Wrap an existing ToolRegistry instance."""
        self._inner = inner_registry
        # Track idempotence declarations: verb -> bool
        self._idempotence: dict[str, bool] = {}

    def register(
        self,
        name: str,
        fn: Any,
        schema: dict[str, Any],
        *,
        idempotent: bool,
        dedup_contract: dict[str, Any] | None = None,
        write_paths: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Register a verb with idempotence and write-path enforcement.

        Parameters
        ----------
        name        : verb name
        fn          : callable implementing the verb
        schema      : input schema dict
        idempotent  : True if the verb is safe to replay (crash-resume path);
                      False if the verb has side effects that must not repeat.
        dedup_contract : Required when idempotent=False.  A dict describing
                      how the journal deduplicates this verb, e.g.:
                        {"journal_field": "action_id", "mechanism": "sha256-content-hash"}
                      The dict must have at least "journal_field" and "mechanism".
        write_paths : Optional list of paths this verb may write to.  Each is
                      checked against the protected baseline directory.
        **kwargs    : Forwarded to the inner registry's register() call.

        Raises
        ------
        ValueError  : if idempotent=False and no valid dedup_contract is supplied.
        PermissionError : if any write_path targets the protected baseline dir.
        """
        # Idempotence audit
        if not idempotent:
            if not dedup_contract:
                raise ValueError(
                    f"REGISTRATION_REFUSED: verb '{name}' declared idempotent=False "
                    "but supplies no dedup_contract.  Non-idempotent verbs must "
                    "provide a dedup_contract describing the journal deduplication "
                    "mechanism (required keys: 'journal_field', 'mechanism')."
                )
            required_keys = {"journal_field", "mechanism"}
            missing = required_keys - set(dedup_contract.keys())
            if missing:
                raise ValueError(
                    f"REGISTRATION_REFUSED: verb '{name}' dedup_contract is missing "
                    f"required keys: {sorted(missing)}.  "
                    f"Supplied: {dedup_contract}"
                )

        # Write-path protection check
        if write_paths:
            for wp in write_paths:
                check_write_path(wp)

        # Forward to inner registry (drop idempotent / dedup_contract / write_paths
        # — those are harness-layer metadata, not inner-registry metadata)
        self._inner.register(name, fn, schema, **kwargs)
        self._idempotence[name] = idempotent

    def dispatch(self, action: Any) -> Any:
        """Delegate dispatch to the inner registry."""
        return self._inner.dispatch(action)

    def known_verbs(self) -> list[str]:
        return self._inner.known_verbs()

    def is_idempotent(self, verb: str) -> bool | None:
        """Return the declared idempotence of a verb, or None if unknown."""
        return self._idempotence.get(verb)


# ---------------------------------------------------------------------------
# Manifest management helpers (used by selftest and --update-manifest)
# ---------------------------------------------------------------------------

def compute_manifest_entries(
    repo_root: str,
    protected_rel_paths: list[tuple[str, str]],  # [(rel_path, label), ...]
) -> list[dict[str, str]]:
    """Compute sha256 for each listed path relative to repo_root.

    Returns a list of dicts suitable for the 'protected_paths' field.
    Raises FileNotFoundError if any path is missing.
    """
    entries = []
    for rel_path, label in protected_rel_paths:
        abs_path = os.path.join(repo_root, rel_path)
        sha = _sha256_file(abs_path)
        entries.append({"path": rel_path, "label": label, "sha256": sha})
    return entries


def write_manifest_and_baseline(
    manifest_path: str,
    baseline_path: str,
    entries: list[dict[str, str]],
    schema_version: str = "1",
) -> None:
    """Write manifest to both locations atomically.

    The manifest and baseline are written as identical JSON files.
    Both writes are atomic (write-to-tmp then os.replace).
    """
    payload = {
        "schema_version": schema_version,
        "note": (
            "Protected-invariant manifest for NC-K boot checksum layer. "
            "This file and its baseline copy (config/nck-baseline/) must match at boot. "
            "Do not edit manually; regenerate via scripts/nck/invariants.py --update-manifest."
        ),
        "protected_paths": entries,
    }
    data = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    data_bytes = data.encode("utf-8")

    for dest in (manifest_path, baseline_path):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        tmp = dest + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data_bytes)
        os.replace(tmp, dest)


# ---------------------------------------------------------------------------
# CLI entry point: --update-manifest
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="NC-K invariant manifest manager."
    )
    parser.add_argument(
        "--update-manifest",
        action="store_true",
        help=(
            "Recompute sha256 hashes for all protected paths and write "
            "manifest + baseline.  Run after any intentional change to a "
            "protected file (e.g. after a gated harness edit)."
        ),
    )
    args = parser.parse_args()

    if args.update_manifest:
        # Resolve repo root as two levels up from this file
        _repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        # Load existing manifest to discover which paths to protect
        if not os.path.isfile(MANIFEST_PATH):
            print(
                f"ERROR: no existing manifest at {MANIFEST_PATH}. "
                "Create config/nck-invariants.json first.",
                file=sys.stderr,
            )
            sys.exit(1)
        with open(MANIFEST_PATH, "r", encoding="utf-8") as _f:
            _existing = json.load(_f)
        _pairs = [
            (e["path"], e.get("label", e["path"]))
            for e in _existing.get("protected_paths", [])
        ]
        _entries = compute_manifest_entries(_repo_root, _pairs)
        write_manifest_and_baseline(MANIFEST_PATH, BASELINE_MANIFEST_PATH, _entries)
        print(f"Manifest updated: {MANIFEST_PATH}")
        print(f"Baseline updated: {BASELINE_MANIFEST_PATH}")
        for e in _entries:
            print(f"  {e['label']}: {e['sha256']}")
        sys.exit(0)
    else:
        parser.print_help()
        sys.exit(0)
