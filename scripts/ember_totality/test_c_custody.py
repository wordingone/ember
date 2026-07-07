#!/usr/bin/env python3
"""Ember totality test — Condition C-CUSTODY (status probe / TDD).

C-CUSTODY — Receipts custody and integrity.
  R: Every receipt in receipts/ must be git-tracked, parseable as JSON,
     and every receipts/ path cited in verdict-bearing receipts must exist.
  CHK: Untracked, unparseable, or cited-missing receipts -> RED. All pass -> GREEN.

This is a STATUS PROBE. It always exits 0 and prints exactly one line
beginning with "RED ", "GREEN ", or "UNEVALUABLE ". RED/GREEN is determined by
really inspecting state under <execution-root> — never hardcoded.

Three failure shapes (issue #381):
  (a) untracked-in-canonical: any file in receipts/ not tracked by git
  (b) unparseable: any file fails json.load (utf-8, then utf-8-sig)
  (c) cited-path-missing: any receipts/ path cited in verdict-bearing receipt
                          or board receipt that doesn't exist on disk

Disclosed allowlist mechanism: receipts may carry an "__allowlist_untracked"
field (array of basename patterns) to exempt specific files from tracking
requirement (staging files for future operations).
"""

import glob
import json
import os
import re
import subprocess
import sys

# --- Locate <execution-root> robustly ----------------------------------------
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CANDIDATE_ROOTS = [
    p for p in (os.environ.get("EMBER_TOTALITY_ROOT"), REPO_ROOT)
    if p
]
ROOT = next((r for r in CANDIDATE_ROOTS if os.path.isdir(r)), None)


def emit(color, reason):
    """Print the single status line and exit 0 (status-probe contract)."""
    print(f"{color} {reason}")
    sys.exit(0)


def _get_git_tracked_files(root):
    """Return set of all tracked file paths (relative to root) via git ls-files."""
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return set(p.replace("\\", "/") for p in result.stdout.strip().split("\n") if p)
        return set()
    except Exception:
        return set()


def _load_json_with_fallback(path):
    """Load JSON from path, trying utf-8 then utf-8-sig. Return (data, None) on success,
    (None, error_str) on failure."""
    for encoding in ["utf-8", "utf-8-sig"]:
        try:
            with open(path, "r", encoding=encoding) as fh:
                data = json.load(fh)
            return data, None
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            if encoding == "utf-8-sig":
                return None, str(e)
            continue
    return None, "Failed both utf-8 and utf-8-sig"


def _extract_citations(obj, citations=None):
    """Recursively extract all receipts/ paths cited in obj (dict/list).
    Returns set of normalized receipt paths."""
    if citations is None:
        citations = set()

    if isinstance(obj, dict):
        for k, v in obj.items():
            # Look for fields that might cite receipt paths
            if isinstance(v, str) and "receipts/" in v:
                # Extract path starting from receipts/
                m = re.search(r"(receipts/[^\s\"']+)", v)
                if m:
                    citations.add(m.group(1).rstrip(",;."))
            _extract_citations(v, citations)
    elif isinstance(obj, list):
        for item in obj:
            _extract_citations(item, citations)

    return citations


def _get_allowlist_for_receipt(receipt_data):
    """Extract __allowlist_untracked from receipt, if present. Returns set of basename patterns."""
    allowlist = receipt_data.get("__allowlist_untracked", [])
    if isinstance(allowlist, list):
        return set(allowlist)
    return set()


def _is_match_pattern(basename, patterns):
    """Check if basename matches any pattern in patterns (simple glob support)."""
    for pattern in patterns:
        if "*" in pattern or "?" in pattern:
            # Glob-style pattern
            if re.match(pattern.replace(".", r"\.").replace("*", ".*").replace("?", "."), basename):
                return True
        elif basename == pattern:
            return True
    return False


def main():
    if ROOT is None:
        emit("UNEVALUABLE", "C-CUSTODY: execution root not found")

    receipts_dir = os.path.join(ROOT, "receipts")
    if not os.path.isdir(receipts_dir):
        emit("RED", "C-CUSTODY: receipts/ directory not found")

    # --- (A) Enumerate all receipts/ files -------
    patterns = [
        os.path.join(receipts_dir, "*.json"),
        os.path.join(receipts_dir, "**", "*.json"),
    ]
    found_files = set()
    for pat in patterns:
        found_files.update(glob.glob(pat, recursive=True))

    if not found_files:
        emit("GREEN", "C-CUSTODY: receipts/ empty (nothing to custody-check)")

    # --- (B) Get git tracking info -------
    git_tracked = _get_git_tracked_files(ROOT)

    # Normalize paths for comparison (git uses forward slashes)
    git_tracked_normalized = set(p.replace("\\", "/") for p in git_tracked)

    # --- (C) Check three failure shapes -------
    failures = []
    citations_to_verify = set()

    for fpath in sorted(found_files):
        rel_path = os.path.relpath(fpath, ROOT).replace("\\", "/")
        basename = os.path.basename(fpath)

        # Shape (a): Untracked check (with allowlist)
        if rel_path not in git_tracked_normalized:
            # Check allowlist from any existing receipt file
            try:
                data, _ = _load_json_with_fallback(fpath)
                if data:
                    allowlist = _get_allowlist_for_receipt(data)
                    if _is_match_pattern(basename, allowlist):
                        pass  # Whitelisted, skip
                    else:
                        failures.append(f"UNTRACKED: {rel_path}")
                else:
                    failures.append(f"UNTRACKED: {rel_path}")
            except Exception:
                failures.append(f"UNTRACKED: {rel_path}")

        # Shape (b): Unparseable check
        data, json_error = _load_json_with_fallback(fpath)
        if data is None:
            failures.append(f"UNPARSEABLE: {rel_path} ({json_error})")
            continue

        # Shape (c): Extract citations for later verification
        _extract_citations(data, citations_to_verify)

    # --- (D) Check cited paths exist -------
    missing_citations = []
    for cited_path in sorted(citations_to_verify):
        full_path = os.path.join(ROOT, cited_path)
        if not os.path.isfile(full_path):
            missing_citations.append(cited_path)

    if missing_citations:
        failures.extend([f"CITED-MISSING: {p}" for p in missing_citations[:10]])

    # --- (E) Emit result -------
    if failures:
        # Try to find or create a custody receipt with findings
        receipt_obj = {
            "ticket": "C-CUSTODY-CHK",
            "ts": "",  # Caller will supply
            "failures": failures,
            "failure_count": len(failures),
            "offenders": {
                "untracked": [f for f in failures if f.startswith("UNTRACKED:")],
                "unparseable": [f for f in failures if f.startswith("UNPARSEABLE:")],
                "cited_missing": [f for f in failures if f.startswith("CITED-MISSING:")],
            },
        }
        emit("RED", f"C-CUSTODY: {len(failures)} custody violation(s) detected; "
                    f"untracked={len(receipt_obj['offenders']['untracked'])} "
                    f"unparseable={len(receipt_obj['offenders']['unparseable'])} "
                    f"cited_missing={len(receipt_obj['offenders']['cited_missing'])}")

    emit("GREEN", f"C-CUSTODY: all receipts in receipts/ are git-tracked, "
                  f"parseable as JSON, and cited paths exist "
                  f"({len(found_files)} files checked, 0 violations)")


if __name__ == "__main__":
    main()
