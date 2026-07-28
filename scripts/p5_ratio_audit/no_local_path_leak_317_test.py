#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression for issue #317: checkpoint-discovery "consulted"/"checkpoint_path"
fields must never reach a tracked receipt as machine-local absolute paths.

discover_checkpoints() in run_p5_audit.py resolves EMBER_MODELS_ROOT (an
absolute, machine-local path) and stamps it -- by documented design --
into checkpoint_path ("absolute, only when found") and consulted (every
manifest/receipt path examined) so load_real_checkpoint() can actually
open the file. That absolute path is legitimate for in-memory use but must
never land in a receipts/*.json file: this is exactly the "checkpoint-
discovery consulted-lists" emitter named in issue #317's fix contract.

This test stubs `timeshare_pretrain` in sys.modules before importing
run_p5_audit -- that module is EMBER_ARTIFACT_CLASS=historical_only
(execution-denied at import, an unrelated frozen-trainer policy) and
importing run_p5_audit for real always raises through it. The stub lets
this test exercise run_p5_audit's OWN redaction wrapper
(_redact_models_root) against synthetic discovery payloads shaped exactly
like discover_checkpoints()'s real output, without ever touching the
frozen trainer path itself.

RED-first: before the #317 fix, run_and_emit_live() wrote discovery_summary
(and the failed-engagement `reasons` dict) straight to receipts/*.json with
the raw EMBER_MODELS_ROOT-resolved absolute path embedded in
checkpoint_path/consulted/reason. GREEN after: every one of those fields is
routed through _redact_models_root() before any checked_write() call, and
the redacted payload never matches repo-guard's own leak pattern (extracted
literally from tools/repo-guard.sh, same technique as issue #639's
receipt_no_local_path_test.py, so this test and the actual landing gate
can never drift apart).
"""

from __future__ import annotations

import os
import re
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))


def _extract_repo_guard_pathpat() -> str:
    guard_path = os.path.join(REPO_ROOT, "tools", "repo-guard.sh")
    with open(guard_path, "r", encoding="utf-8") as fh:
        text = fh.read()
    m = re.search(r"^PATHPAT='(.+)'$", text, re.MULTILINE)
    if not m:
        raise RuntimeError(
            "could not extract PATHPAT= from tools/repo-guard.sh -- the gate's "
            "pattern format changed; this regression MUST be updated to match "
            "rather than silently no-op (issue #317)"
        )
    return m.group(1)


def _load_run_p5_audit_with_stub():
    """Import run_p5_audit with a stub timeshare_pretrain so its module-level
    `import timeshare_pretrain as ts` (line ~336) resolves to a harmless
    stand-in instead of raising the historical_only execution-denial."""
    if "timeshare_pretrain" not in sys.modules:
        stub = types.ModuleType("timeshare_pretrain")
        stub.read_manifest = lambda *a, **k: None
        stub.load_checkpoint = lambda *a, **k: None
        sys.modules["timeshare_pretrain"] = stub
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import run_p5_audit  # noqa: E402
    return run_p5_audit


class TestNoLocalPathLeak317(unittest.TestCase):
    def setUp(self):
        self.m = _load_run_p5_audit_with_stub()
        self.pathpat = _extract_repo_guard_pathpat()
        # Synthetic root: drive-letter-absolute like a real EMBER_MODELS_ROOT,
        # but deliberately NOT shaped like repo-guard's own PATHPAT segments
        # (Users/M/Downloads/Windows-Temp) so this source file itself never
        # trips the tree-wide leak gate; the redaction logic under test does
        # not special-case those segment names, so this is still a faithful
        # exercise of the real code path.
        self.root = r"Q:\synthroot\synthetic-models-root"

    def _iter_strings(self, node):
        """Every string VALUE in the structure, decoded.

        The obvious implementation compares forms of the root against
        `json.dumps(payload)`, and it is wrong in a way that passes: dumps
        escapes each backslash, so a leak written by `repr()` -- which has
        already doubled them -- appears in the blob with four, matching none
        of the forms being searched for. The assertion runs, finds nothing,
        and reports clean over a receipt that carries the path. Verified by
        reverting the cure and watching the blob-based test stay green.

        Walking the decoded values removes the serialization layer from the
        comparison entirely, which is the point: the question is what the
        field HOLDS, not what one particular re-encoding of it looks like."""
        if isinstance(node, str):
            yield node
        elif isinstance(node, dict):
            for k, v in node.items():
                yield str(k)
                yield from self._iter_strings(v)
        elif isinstance(node, (list, tuple)):
            for v in node:
                yield from self._iter_strings(v)
        elif node is not None and not isinstance(node, (bool, int, float)):
            yield str(node)

    def _assert_no_leak(self, payload) -> None:
        root_norm = os.path.normpath(self.root)
        # repr() of a Windows path doubles the separators in the VALUE itself,
        # so the doubled form is a real distinct thing to look for here rather
        # than an artifact of encoding.
        forms = (
            root_norm,
            root_norm.replace("\\", "\\\\"),
            root_norm.replace("\\", "/"),
        )
        for s in self._iter_strings(payload):
            self.assertIsNone(
                re.search(self.pathpat, s),
                f"payload string matches repo-guard PATHPAT: {s!r}",
            )
            for form in forms:
                self.assertNotIn(
                    form, s,
                    f"payload string contains root form {form!r}: {s!r}",
                )

    def test_redact_models_root_all_forms(self):
        root = self.root
        payload = {
            "pre_grow_rung1": {
                "checkpoint_path": root + r"\rung1\pre\model.pt",
                "relative_path": "rung1/pre",
                "consulted": [
                    root + r"\rung1\pre\manifest.json",
                    root.replace("\\", "/") + "/rung1/pre/manifest.json",
                    root.replace("\\", "\\\\") + r"\\rung1\\pre\\manifest.json",
                ],
                "found": True,
            },
            "reason": "read_manifest failed at " + root + r"\rung1\pre\manifest.json: boom",
        }
        # Pre-condition: the synthetic payload DOES contain the raw root
        # before redaction (proves this test would have caught the
        # pre-#317 shape). Checked against the raw dict value, not a
        # json.dumps() re-encoding, since json.dumps doubles backslashes
        # and would make a plain substring check spuriously fail.
        self.assertIn(root, payload["pre_grow_rung1"]["checkpoint_path"])

        redacted = self.m._redact_models_root(payload, root)
        self._assert_no_leak(redacted)
        # Non-path content survives untouched.
        self.assertEqual(redacted["pre_grow_rung1"]["relative_path"], "rung1/pre")
        self.assertTrue(redacted["pre_grow_rung1"]["found"])
        self.assertIn("<MODELS_ROOT>", redacted["pre_grow_rung1"]["checkpoint_path"])

    def test_redact_models_root_none_is_noop(self):
        payload = {"a": "unrelated/relative/path.json"}
        self.assertEqual(self.m._redact_models_root(payload, None), payload)

    def test_run_and_emit_live_blocked_receipt_has_no_leak(self):
        """End-to-end: run_and_emit_live()'s BLOCKED receipt (the
        EMBER_GATE_AUTHORIZED != '1' path, reachable with zero env setup)
        must not leak EMBER_MODELS_ROOT even when it is set to a real-
        shaped absolute path and discover_checkpoints() resolves against
        it (stubbed manifest reads -- MISSING, never FOUND, so the BLOCKED
        branch's checkpoint_discovery summary still carries a `consulted`
        list built from the root)."""
        import json
        import tempfile

        old_env = dict(os.environ)
        old_receipts = self.m.RECEIPTS
        try:
            os.environ.pop("EMBER_GATE_AUTHORIZED", None)
            os.environ[self.m.MODELS_ROOT_ENV] = self.root
            with tempfile.TemporaryDirectory() as td:
                self.m.RECEIPTS = td
                path = self.m.run_and_emit_live()
                with open(path, "r", encoding="utf-8") as fh:
                    receipt = json.load(fh)
                self._assert_no_leak(receipt)
                self.assertEqual(receipt["status"], "BLOCKED")
        finally:
            os.environ.clear()
            os.environ.update(old_env)
            self.m.RECEIPTS = old_receipts

    def test_run_and_emit_live_authorized_missing_receipt_has_no_leak(self):
        """The BLOCKED test above short-circuits at the authorization check,
        so it never reaches the FAILED-ENGAGEMENT emitter -- which composes
        its own reason string naming EMBER_MODELS_ROOT directly. Covering
        only BLOCKED reads as covering run_and_emit_live, and does not: the
        authorized-but-checkpoints-missing branch is a different exit with a
        different emitter, and that is where the leak actually lived.

        This is the skip-path question asked of the test rather than of the
        code: on which input class does the existing assertion not run?"""
        import json
        import tempfile

        old_env = dict(os.environ)
        old_receipts = self.m.RECEIPTS
        try:
            os.environ["EMBER_GATE_AUTHORIZED"] = "1"
            os.environ[self.m.MODELS_ROOT_ENV] = self.root
            with tempfile.TemporaryDirectory() as td:
                self.m.RECEIPTS = td
                path = self.m.run_and_emit_live()
                with open(path, "r", encoding="utf-8") as fh:
                    receipt = json.load(fh)
                # Assert we actually reached the intended branch. Without this
                # the test passes vacuously if authorization is refused for an
                # unrelated reason and we land back on BLOCKED.
                self.assertEqual(
                    receipt["status"], "FAILED-ENGAGEMENT",
                    "expected the authorized checkpoints-missing path; the test "
                    f"never reached the FAILED-ENGAGEMENT emitter: {receipt!r}",
                )
                self._assert_no_leak(receipt)
        finally:
            os.environ.clear()
            os.environ.update(old_env)
            self.m.RECEIPTS = old_receipts


if __name__ == "__main__":
    unittest.main()
