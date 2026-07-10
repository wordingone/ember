#!/usr/bin/env python3
"""Regression for issue #639.

The 2026-07-10 totality re-render (post-#633) produced a board receipt that
repo-guard's no-local-paths landing gate BLOCKED from commit: the C-BASE
row's status line embedded the resolved local absolute artifact root
(EMBER_ARTIFACT_ROOT / --artifact-root, introduced by #633) instead of only
disclosing its `artifact_root_source` token. PR #638 could land only the
process-visibility receipt, not the board receipt itself.

This test runs test_c_base.py's C-BASE probe directly, in the exact
configuration that produced the leak (an explicit artifact root distinct
from the probe's own repo root, with a real owned-pretrain checkpoint
receipt naming a RELATIVE checkpoint path resolved against it), and asserts
the probe's own status line never matches repo-guard's OWN no-local-paths
pattern -- extracted LITERALLY from tools/repo-guard.sh so this test and
the actual landing gate can never drift apart (frozen spec item 3, issue
#639).

RED-first: before the #639 emitter-side fix, this test fails --
test_c_base.py's GREEN status line embeds the artifact-root-resolved
absolute checkpoint path, which matches repo-guard's PATHPAT.
GREEN after: the probe discloses only the receipt-declared (relative)
checkpoint path plus the pre-existing artifact_root_source token; no local
path reaches the printed line.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))


def _extract_repo_guard_pathpat() -> str:
    """Read tools/repo-guard.sh and extract its literal PATHPAT regex, so
    this regression can never drift from the actual landing gate (issue
    #639 frozen spec item 3: 'reuse repo-guard's own pattern set so the
    test and the gate cannot drift apart'). Fails loudly, never silently,
    if repo-guard.sh's pattern shape ever changes underneath this test.
    """
    guard_path = os.path.join(REPO_ROOT, "tools", "repo-guard.sh")
    with open(guard_path, "r", encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r"^PATHPAT='(.+)'$", text, re.MULTILINE)
    if not m:
        raise RuntimeError(
            "could not extract PATHPAT= from tools/repo-guard.sh -- the gate's "
            "pattern format changed; this regression MUST be updated to match "
            "rather than silently no-op (issue #639)"
        )
    # repo-guard.sh's PATHPAT is a POSIX extended-regex string built only from
    # character classes and alternation -- no bash-specific extensions -- so
    # it is valid as a Python `re` pattern verbatim.
    return m.group(1)


class TestCBaseReceiptNeverEmbedsLocalPath(unittest.TestCase):
    """RED-first regression for issue #639."""

    def setUp(self):
        self.pathpat = re.compile(_extract_repo_guard_pathpat())

        # A REAL local absolute artifact root, deliberately under the
        # platform temp dir so it exercises the exact same drive-letter /
        # Users-or-Temp shape repo-guard's pattern targets -- not a
        # synthetic placeholder the pattern wouldn't match.
        self.tmp = tempfile.mkdtemp(prefix="c639-artifact-root-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

        # Fixture self-check: if the platform temp dir doesn't even match
        # repo-guard's own pattern, this test cannot exercise the defect at
        # all -- fail loudly rather than silently pass for the wrong reason.
        self.assertIsNotNone(
            self.pathpat.search(self.tmp),
            f"fixture root {self.tmp!r} does not match repo-guard's own "
            "PATHPAT on this platform -- this regression cannot exercise "
            "the #639 defect here; fixture needs a platform-specific root",
        )

        ckpt_rel = os.path.join("models", "c639-smoke", "checkpoints", "step-1")
        ckpt_dir = os.path.join(self.tmp, ckpt_rel)
        os.makedirs(ckpt_dir, exist_ok=True)
        model_bytes = b"synthetic-checkpoint-bytes-for-c639-regression"
        with open(os.path.join(ckpt_dir, "model.pt"), "wb") as fh:
            fh.write(model_bytes)
        model_hash = hashlib.sha256(model_bytes).hexdigest()
        with open(os.path.join(ckpt_dir, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump({"files": {"model.pt": model_hash}}, fh)

        receipts_dir = os.path.join(self.tmp, "receipts", "c639-regression")
        os.makedirs(receipts_dir, exist_ok=True)

        # Grow-operator dry-run receipt (CHK clause d), self-referencing its
        # own evidence pointer so a single fixture file satisfies
        # _validate_grow_operator_evidence().
        grow_receipt = {
            "grow_operator_dry_run": True,
            "grow_operator_replays": True,
            "grow_operator_evidence": "receipts/c639-regression/grow-dryrun.json",
            "verdict": "PASS",
        }
        with open(os.path.join(receipts_dir, "grow-dryrun.json"), "w", encoding="utf-8") as fh:
            json.dump(grow_receipt, fh)

        # Owned from-scratch checkpoint receipt naming a RELATIVE checkpoint
        # path (the authored convention) that resolves under the artifact
        # root -- exactly the #633 shape.
        ckpt_receipt = {
            "cbase": True,
            "from_scratch": True,
            "last_checkpoint": ckpt_rel.replace("\\", "/"),
        }
        with open(os.path.join(receipts_dir, "cbase-owned.json"), "w", encoding="utf-8") as fh:
            json.dump(ckpt_receipt, fh)

    def _run_probe(self) -> str:
        env = dict(os.environ)
        env["EMBER_TOTALITY_ROOT"] = self.tmp
        env["EMBER_ARTIFACT_ROOT"] = self.tmp
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(
            [sys.executable, os.path.join(HERE, "test_c_base.py")],
            capture_output=True, text=True, env=env, timeout=30,
        )
        return proc.stdout

    def test_c_base_status_line_never_embeds_local_path(self):
        stdout = self._run_probe()
        leak = self.pathpat.search(stdout)
        leaked_text = leak.group(0) if leak else ""
        self.assertIsNone(
            leak,
            "C-BASE probe status line embeds a local absolute path matching "
            f"repo-guard's own PATHPAT ({leaked_text!r}): "
            f"{stdout!r} -- this is exactly the #639 defect (repo-guard would "
            "block a receipt carrying this line from landing)"
        )
        # Sanity: the probe actually reached a real verdict (not a vacuous
        # UNEVALUABLE with nothing to leak, which would make the assertion
        # above trivially true for the wrong reason).
        self.assertTrue(
            stdout.startswith("GREEN C-BASE") or stdout.startswith("RED C-BASE"),
            f"probe did not reach a real C-BASE verdict; fixture is broken: {stdout!r}",
        )
        # The pre-existing #633 disclosure token must still be present and
        # unredacted -- the cure removes the PATH, never the token.
        self.assertIn("[artifact_root_source=env]", stdout)


if __name__ == "__main__":
    unittest.main()
