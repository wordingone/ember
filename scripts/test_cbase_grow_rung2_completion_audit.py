# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "cbase_grow_rung2_completion_audit.py"
SPEC = importlib.util.spec_from_file_location("cbase_completion_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class CompletionReceiptTests(unittest.TestCase):
    def _sources(self) -> dict[str, Path]:
        return {
            "producer": SCRIPT,
            "probe": ROOT / "scripts" / "ember_totality" / "test_c_grow.py",
            "historical_receipt": (
                ROOT
                / "receipts"
                / "cbase-grow-rung"
                / "cbase-grow-rung2-completion-20260710T172500Z.json"
            ),
            "satisfying_receipt": (
                ROOT
                / "receipts"
                / "cbase-grow-rung"
                / "cbase-grow-measured-flops-20260710T005231Z.json"
            ),
        }

    def test_build_receipt_binds_authority_stamp_sources_and_probe(self) -> None:
        completed = mock.Mock(returncode=0, stdout="GREEN C-GROW: exact\n", stderr="")
        with mock.patch.object(audit.subprocess, "run", return_value=completed):
            receipt = audit.build_completion_receipt(
                timestamp="2026-07-29T10:30:00Z",
                sources=self._sources(),
            )

        self.assertEqual(receipt["ticket"], "CBASE-GROW-RUNG2-COMPLETION")
        self.assertEqual(receipt["goal_id"], "EMBER-02")
        self.assertEqual(receipt["workstream_id"], "EMBER-02A")
        self.assertEqual(
            receipt["next_executed_outcome"],
            "EMBER-02 first sufficiently pretrained clean-genesis 3B Ember",
        )
        self.assertEqual(
            receipt["invariant_sha256"],
            "08a0eb7418c09a8088be4658e10785107abbb7507fc2dbcdc789936aa54e02a6",
        )
        self.assertEqual(receipt["probe"]["verdict"], "GREEN")
        self.assertEqual(receipt["probe"]["stdout"], "GREEN C-GROW: exact")
        self.assertEqual(
            set(receipt["source_sha256"]),
            {"producer", "probe", "historical_receipt", "satisfying_receipt"},
        )
        self.assertTrue(
            all(len(value) == 64 for value in receipt["source_sha256"].values())
        )
        self.assertEqual(
            len(receipt["candidate_audit"]["candidate_rows_sha256"]), 64
        )
        self.assertNotIn("rows", receipt["candidate_audit"])

    def test_probe_failure_refuses_receipt(self) -> None:
        completed = mock.Mock(returncode=1, stdout="RED C-GROW\n", stderr="")
        with mock.patch.object(audit.subprocess, "run", return_value=completed):
            with self.assertRaisesRegex(RuntimeError, "C-GROW probe refused"):
                audit.build_completion_receipt(
                    timestamp="2026-07-29T10:30:00Z",
                    sources=self._sources(),
                )

    def test_publish_is_exclusive_lf_only_and_refuses_overwrite(self) -> None:
        receipt = {
            "ticket": "CBASE-GROW-RUNG2-COMPLETION",
            "ts": "2026-07-29T10:30:00Z",
        }
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "receipt.json"
            audit.publish_receipt(receipt, target)
            raw = target.read_bytes()
            self.assertNotIn(b"\r\n", raw)
            self.assertEqual(json.loads(raw), receipt)
            with self.assertRaises(FileExistsError):
                audit.publish_receipt(receipt, target)

    def test_supersession_identity_matches_historical_ticket(self) -> None:
        old = json.loads(self._sources()["historical_receipt"].read_text("utf-8"))
        completed = mock.Mock(returncode=0, stdout="GREEN C-GROW: exact\n", stderr="")
        with mock.patch.object(audit.subprocess, "run", return_value=completed):
            new = audit.build_completion_receipt(
                timestamp="2026-07-29T10:30:00Z",
                sources=self._sources(),
            )
        self.assertEqual(old["ticket"], new["ticket"])

    def test_candidate_audit_successor_is_current_compact_and_source_bound(self) -> None:

        completed = mock.Mock(returncode=0, stdout="GREEN C-GROW: exact\n", stderr="")
        with mock.patch.object(audit.subprocess, "run", return_value=completed):
            receipt = audit.build_candidate_audit_receipt(
                timestamp="2026-07-29T10:40:00Z",
            )

        self.assertEqual(receipt["ticket"], "C-GROW-CANDIDATE-AUDIT")
        self.assertEqual(receipt["probe"]["verdict"], "GREEN")
        self.assertEqual(receipt["goal_id"], "EMBER-02")
        self.assertEqual(receipt["workstream_id"], "EMBER-02A")
        self.assertEqual(len(receipt["candidate_audit"]["candidate_rows_sha256"]), 64)
        self.assertNotIn("rows", receipt["candidate_audit"])
        self.assertEqual(
            receipt["supersedes"],
            "receipts/cbase-grow-rung/c-grow-candidate-audit-20260710T172304Z.json",
        )
        self.assertEqual(
            set(receipt["source_sha256"]),
            {"producer", "probe", "historical_receipt", "satisfying_receipt"},
        )

if __name__ == "__main__":
    unittest.main()
