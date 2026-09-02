#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""a1_beacon_grindability_repro.py -- ember #631 deliverable 4, REPRODUCE-FIRST.

Demonstrates A1 machinery defect #4 (refs #123 finding 4): the post-freeze held-out
SELECTION beacon in PR #603 is the author-controlled commit sha itself
(`index = int(eval_freeze_hash[:8], 16) mod 8`). Because the author freely controls
the commit (message, author/committer timestamps, tree), they can GRIND an inert
nonce until the modulo lands on any chosen candidate -- so the rule is reproducible
but NOT non-discretionary.

This script builds a THROWAWAY git repo in a temp dir (never the live tree, per the
adversarial-agent-scoping rule: sandbox, reason-not-detonate), fixes a base tree +
parent, and varies ONLY an inert commit-message nonce, tabulating
`int(commit_sha[:8],16) mod 8` until all 8 pool indices have been produced. All 8
reachable (and index 7 = SciQ, PR #603's landed pick, reachable) is the defect.

Emits a receipt with the tries-to-cover-all-8 and the first nonce hitting each index.
Zero network, zero GPU.

Usage:
  python src/ember/governance/scripts/a1_beacon_grindability_repro.py \\
      --out receipts/eval-suite-freeze/a1-beacon-grindability-repro-<UTCts>.json \\
      [--max-tries 500] [--pool-size 8]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
import importlib.util as _ember_66ee9e91637922dc_importlib
import sys as _ember_66ee9e91637922dc_sys
from pathlib import Path as _ember_66ee9e91637922dc_Path
_ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
if not _ember_66ee9e91637922dc_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_write.py')
_ember_66ee9e91637922dc_aliases = ('_ember_issue2015_66ee9e91637922dc', 'receipt_write', 'scripts.receipt_write')
_ember_66ee9e91637922dc_existing = []
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_candidate = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_candidate is not None and all(_ember_66ee9e91637922dc_candidate is not item for item in _ember_66ee9e91637922dc_existing):
        _ember_66ee9e91637922dc_existing.append(_ember_66ee9e91637922dc_candidate)
if len(_ember_66ee9e91637922dc_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_write.py')
if _ember_66ee9e91637922dc_existing:
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_existing[0]
    _ember_66ee9e91637922dc_observed = getattr(_ember_66ee9e91637922dc_module, '__file__', None)
    if _ember_66ee9e91637922dc_observed is None or _ember_66ee9e91637922dc_Path(_ember_66ee9e91637922dc_observed).resolve() != _ember_66ee9e91637922dc_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_write.py')
else:
    _ember_66ee9e91637922dc_spec = _ember_66ee9e91637922dc_importlib.spec_from_file_location('_ember_issue2015_66ee9e91637922dc', _ember_66ee9e91637922dc_path)
    if _ember_66ee9e91637922dc_spec is None or _ember_66ee9e91637922dc_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_importlib.module_from_spec(_ember_66ee9e91637922dc_spec)
    for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
        _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
        if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
        _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
    try:
        _ember_66ee9e91637922dc_spec.loader.exec_module(_ember_66ee9e91637922dc_module)
    except BaseException:
        for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
            if _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias) is _ember_66ee9e91637922dc_module:
                _ember_66ee9e91637922dc_sys.modules.pop(_ember_66ee9e91637922dc_alias, None)
        raise
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
receipt_write = _ember_66ee9e91637922dc_module
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py  # noqa: E402

INVARIANT_SHA256 = "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6"
SHA_CONVENTION = "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"


def git(repo, *args, env=None):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True,
                          check=True, env=env).stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-tries", type=int, default=500)
    ap.add_argument("--pool-size", type=int, default=8)
    args = ap.parse_args()

    sandbox = tempfile.mkdtemp(prefix="a1_beacon_repro_")
    env = dict(os.environ)
    # deterministic fixed identity + base timestamp (only the nonce varies)
    env.update({
        "GIT_AUTHOR_NAME": "sandbox", "GIT_AUTHOR_EMAIL": "sandbox@example.invalid",
        "GIT_COMMITTER_NAME": "sandbox", "GIT_COMMITTER_EMAIL": "sandbox@example.invalid",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00 +0000",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00 +0000",
    })
    first_hit = {}
    tries = 0
    try:
        git(sandbox, "init", "-q")
        with open(os.path.join(sandbox, "pool.txt"), "w") as f:
            f.write("frozen pool + rule (fixed tree)\n")
        git(sandbox, "add", "pool.txt", env=env)
        git(sandbox, "commit", "-q", "-m", "base: frozen pool", env=env)
        base = git(sandbox, "rev-parse", "HEAD")

        for n in range(args.max_tries):
            tries += 1
            # reset to base each try so the parent + tree are FIXED; only the inert
            # commit-message nonce varies -> models an author grinding the message.
            git(sandbox, "reset", "-q", "--hard", base, env=env)
            sha = git(sandbox, "commit-tree", base + "^{tree}", "-p", base,
                      "-m", f"nonce-{n}", env=env)
            idx = int(sha[:8], 16) % args.pool_size
            if idx not in first_hit:
                first_hit[idx] = {"nonce": n, "commit_sha": sha}
            if len(first_hit) == args.pool_size:
                break
    finally:
        # best-effort sandbox teardown (throwaway repo)
        try:
            for root, dirs, files in os.walk(sandbox, topdown=False):
                for fn in files:
                    try:
                        os.chmod(os.path.join(root, fn), 0o700)
                    except OSError:
                        pass
                    os.unlink(os.path.join(root, fn))
                for dn in dirs:
                    try:
                        os.rmdir(os.path.join(root, dn))
                    except OSError:
                        pass
            os.rmdir(sandbox)
        except OSError:
            pass

    all_reachable = (len(first_hit) == args.pool_size)
    receipt = {
        "ticket": "A1-BEACON-GRINDABILITY-REPRO",
        "ts": datetime.now(timezone.utc).isoformat(),
        "schema": "a1-beacon-grindability-repro/v1",
        "invariant_sha256": INVARIANT_SHA256,
        "sha_convention": SHA_CONVENTION,
        "issue_refs": ["#631", "#123", "#593", "#582"],
        "defect": "the PR #603 held-out selection beacon is the author-controlled commit sha "
                  "(index = int(eval_freeze_hash[:8],16) mod 8); an author can grind an inert "
                  "commit-message nonce to land any pool index -> not non-discretionary",
        "method": "throwaway sandbox git repo (never the live tree); fixed base tree + parent; "
                  "vary only an inert commit-message nonce; tabulate int(sha[:8],16) mod pool_size",
        "pool_size": args.pool_size,
        "tries_to_cover_all_indices": tries,
        "all_indices_reachable": all_reachable,
        "index_7_reachable": (7 in first_hit),
        "index_7_note": "index 7 = SciQ, PR #603's landed selection",
        "first_nonce_per_index": {str(k): first_hit[k] for k in sorted(first_hit)},
        "verdict": ("DEFECT REPRODUCED: all pool indices reachable by grinding an inert nonce; "
                    "the commit-sha beacon cannot prove 'no discretionary pick'"
                    if all_reachable else "NOT ALL REACHABLE (increase --max-tries)"),
    }

    out_dir = os.path.dirname(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    receipt_write.checked_write(args.out, receipt)
    print(f"A1_BEACON_GRINDABILITY_REPRO: all_{args.pool_size}_indices_reachable={all_reachable} "
          f"in {tries} tries; index_7(SciQ)_reachable={7 in first_hit} -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
