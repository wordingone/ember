#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression tests for issue #683: C-EFF execution-binding + C-GROW
field-read probe hardening (third self-declaration-blind instance).

Runs the hardened probes as subprocesses -- their real invocation contract
(`python3 <probe>.py`, single stdout status line, always exit 0) -- against:

  1. the LIVE seated receipts under this repo's own receipts/ tree: both
     C-EFF and C-GROW must stay GREEN post-fix (audit
     receipts/ember-totality-audit/audit-20260710T145200Z.json verified both
     receipts GENUINE; a hardening fix that flips a genuine receipt is a
     wrong fix).
  2. two negative-control fixtures under a scratch EMBER_TOTALITY_ROOT:
       (a) the auditor's reconstructed C-EFF cheap-pass JSON (verdict=
           PRICED_SCALEOUT_RESIDUAL, self-consistent effective-days
           arithmetic, one confirmation_run.sustained_tok_s key, no SHA/
           torch/telemetry) -- must REJECT.
       (b) a copy of the seated C-GROW receipt with every model_pt_sha256
           field stripped -- must near_miss reject.

CPU/file-only: no torch import, no model/checkpoint load, no GPU use.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
CEFF_PROBE = os.path.join(HERE, "test_c_eff.py")
CGROW_PROBE = os.path.join(HERE, "test_c_grow.py")


def _run_probe(probe_path, root, timeout=30):
    env = dict(os.environ)
    env["EMBER_TOTALITY_ROOT"] = root
    proc = subprocess.run(
        [sys.executable, probe_path], cwd=HERE, env=env,
        capture_output=True, text=True, timeout=timeout,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


class TestSeatedReceiptsStayGreen(unittest.TestCase):
    """Acceptance: both probes re-run against their SEATED receipts post-fix
    must remain GREEN -- the receipts are genuine, a fix that flips them is
    a wrong fix."""

    def test_ceff_seated_receipt_stays_green(self):
        rc, out, err = _run_probe(CEFF_PROBE, REPO_ROOT)
        self.assertEqual(rc, 0, f"probe did not exit 0: {err}")
        self.assertTrue(out.startswith("GREEN "), out)

    def test_cgrow_seated_receipt_stays_green(self):
        rc, out, err = _run_probe(CGROW_PROBE, REPO_ROOT)
        self.assertEqual(rc, 0, f"probe did not exit 0: {err}")
        self.assertTrue(out.startswith("GREEN "), out)


class TestCEffCheapPassRejected(unittest.TestCase):
    """Negative control (a): the auditor's reconstructed ~15-line hand-
    authored cheap-pass JSON must REJECT post-fix (pre-fix it turned C-EFF
    GREEN with no SHA, no torch, no telemetry -- see
    receipts/ember-totality-audit/audit-20260710T145200Z.json)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="c683-ceff-")
        os.makedirs(os.path.join(self.tmp, "receipts"), exist_ok=True)
        cheap_pass = {
            "verdict": "PRICED_SCALEOUT_RESIDUAL",
            "effective_days_basis": "useful_base_tokens_div_governed_day",
            "useful_base_tokens": 2200000000.0,
            "sustained_tok_s": 19213.78,
            "effective_days": 1.3252448483829296,
            "compound_speedup_over_anchor": 2.1472968398288312,
            "gate": "gate-9 efficiency-closure (C-EFF)",
            "confirmation_run": {"sustained_tok_s": 19213.78},
            "projected_tok_s": 20948.0843,
            "c04_deciding_axes": {
                "L10_optimizer_swap": "WAIVED-priced",
                "density_ab": "APPLIED",
            },
        }
        with open(
            os.path.join(self.tmp, "receipts",
                         "ceff-RESOLVED-cheappass-20260101T000000Z.json"),
            "w", encoding="utf-8",
        ) as fh:
            json.dump(cheap_pass, fh)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_cheap_pass_rejected(self):
        rc, out, err = _run_probe(CEFF_PROBE, self.tmp)
        self.assertEqual(rc, 0, f"probe did not exit 0: {err}")
        self.assertTrue(out.startswith("RED "), out)
        # Must reject specifically on execution-binding (dry_run/no_gpu/
        # synthetic never declared), not an unrelated defect.
        self.assertIn("dry_run", out)


class TestCGrowShaStrippedRejected(unittest.TestCase):
    """Negative control (b): a copy of the seated C-GROW receipt with every
    model_pt_sha256 field stripped must near_miss reject."""

    def setUp(self):
        seated = os.path.join(
            REPO_ROOT, "receipts", "cbase-grow-rung",
            "cbase-grow-measured-flops-20260710T005231Z.json")
        with open(seated, "r", encoding="utf-8") as fh:
            receipt = json.load(fh)

        def strip_shas(node):
            if isinstance(node, dict):
                for k in list(node.keys()):
                    if k == "model_pt_sha256":
                        node[k] = ""
                    else:
                        strip_shas(node[k])
            elif isinstance(node, list):
                for item in node:
                    strip_shas(item)

        strip_shas(receipt)

        self.tmp = tempfile.mkdtemp(prefix="c683-cgrow-")
        os.makedirs(os.path.join(self.tmp, "receipts", "cbase-grow-rung"),
                    exist_ok=True)
        with open(
            os.path.join(self.tmp, "receipts", "cbase-grow-rung",
                         "cbase-grow-measured-flops-sha-stripped.json"),
            "w", encoding="utf-8",
        ) as fh:
            json.dump(receipt, fh)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sha_stripped_rejected(self):
        rc, out, err = _run_probe(CGROW_PROBE, self.tmp)
        self.assertEqual(rc, 0, f"probe did not exit 0: {err}")
        self.assertTrue(out.startswith("RED "), out)
        self.assertIn("model_pt_sha256", out)


if __name__ == "__main__":
    unittest.main()
