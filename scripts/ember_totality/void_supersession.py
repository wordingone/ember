#!/usr/bin/env python3
"""Shared VOID-supersession exclusion logic (gh issue #358).

Factored out of spend_annex_scan.py (gh issue #353), where it first shipped
as an inline pre-pass, into a single module BOTH spend_annex_scan.py and
test_c_neg1.py's own decisive-claim corpus now consume. Before this, the
scanner excluded a VOID-superseded receipt from its annex row set while the
probe's own `_decisive_claim_files()` kept counting the exact same receipt as
undeclared+uncovered -- live instance (PR #350's own body): C(-1) read RED
1/264, and the 1 was precisely `reference-uiux-ax-observation-20260622T151722Z.json`,
formally disposed via the #349 VOID receipt, excluded by the scanner, still
counted by the probe. One set of semantics, one implementation, no drift
between the two consumers is the point of this module.

Semantics (unchanged from issue #353; this module is now the single source
of truth for them):
  - A receipt is excluded from the decisive-claim set iff some OTHER receipt
    in the same decisive corpus has verdict=="VOID" and a `supersedes` list
    containing an entry whose (filename, sha256) BOTH match this receipt's
    own basename and its CURRENT on-disk sha256.
  - Matched on (basename, sha256), never a directory-qualified path -- this
    repo's VOID convention records only a bare `filename` per supersedes
    entry.
  - A supersedes entry whose sha256 does not match ANY receipt's own
    on-disk hash excludes nothing. This is a real, live case, not a
    hypothetical: the pre-existing `cbase-gpu-verify-VOID-*.json` receipts'
    supersedes entries record the superseded CHECKPOINT's sha256, not
    either receipt FILE's own hash -- those two never match this module's
    (basename, sha256) key and so are never excluded (PR #350's body
    documents this exact case; those receipts still needed sidecar
    attestations rather than exclusion, which is the correct outcome).
  - The VOID receipt itself is never excluded by its own supersession list
    (it is not a key in any supersedes list unless some OTHER VOID receipt
    also names it).
"""
import os

from _lane14_common import sha256_file


def compute_superseded_targets(decisive, root):
    """decisive: list of (path, dict, raw_text) tuples over the FULL
    decisive-claim corpus (as returned by test_c_neg1._decisive_claim_files()
    -- both consumers pass that same list in). Returns
    {(filename, sha256): void_rel} built from every VOID receipt's
    `supersedes` list found in the corpus."""
    superseded_targets = {}
    for void_path, void_d, _void_raw in decisive:
        if not isinstance(void_d, dict) or void_d.get("verdict") != "VOID":
            continue
        supersedes = void_d.get("supersedes")
        if not isinstance(supersedes, list):
            continue
        void_rel = os.path.relpath(void_path, root).replace("\\", "/")
        for entry in supersedes:
            if not isinstance(entry, dict):
                continue
            fname, esha = entry.get("filename"), entry.get("sha256")
            if isinstance(fname, str) and isinstance(esha, str):
                superseded_targets[(fname, esha)] = void_rel
    return superseded_targets


def partition_superseded(decisive, root):
    """Split `decisive` into (kept, excluded_superseded).

    `kept` preserves original (path, dict, raw) tuple shape and order, minus
    every VOID-superseded entry. `excluded_superseded` is a list of dicts
    (path/sha256/superseded_by/reason) -- the disclosed shape
    spend_annex_scan.py has emitted since issue #353; test_c_neg1.py (issue
    #358) discloses the identical shape/count in its own reason text so an
    exclusion that shrinks its undeclared count is never silent."""
    superseded_targets = compute_superseded_targets(decisive, root)
    kept = []
    excluded = []
    for path, d, raw in decisive:
        rel = os.path.relpath(path, root).replace("\\", "/")
        receipt_sha = sha256_file(path)
        key = (os.path.basename(rel), receipt_sha)
        if key in superseded_targets:
            excluded.append({
                "path": rel,
                "sha256": receipt_sha,
                "superseded_by": superseded_targets[key],
                "reason": "named in a VOID receipt's supersedes list, matched by "
                          "(basename, sha256) -- formally disposed, excluded from the "
                          "decisive-claim set per issue #353/#358's VOID-supersession "
                          "semantics; never classified, never counted toward "
                          "unresolvable/uncovered/undeclared. The superseding VOID "
                          "receipt itself remains IN the decisive-claim set.",
            })
            continue
        kept.append((path, d, raw))
    return kept, excluded
