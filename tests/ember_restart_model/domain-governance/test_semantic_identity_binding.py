# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""#1091 cure: run_semantic's closed identity join.

A green launch-packet identity-manifest preflight used to carry NO binding
into the bytes run_semantic actually consumes -- named_launch_command emitted
literal placeholders for --receipt/--shards-root/--tokenizer, so an operator
could substitute a different, individually valid, receipt/shard/tokenizer set
after the green preflight and train on bytes the preflight never represented.

These tests exercise ONLY the new identity guard in run_vertical_slice.run_semantic
(inserted immediately after the receipt-bound stream is built, before any model
construction or training step). Everything downstream of the guard is mocked
off with a sentinel exception so a test can distinguish "the guard refused"
from "the guard passed and execution moved on" without needing the full
checkpoint/segment machinery.
"""

from __future__ import annotations

import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = next(parent for parent in Path(__file__).resolve().parents if (parent / 'pyproject.toml').is_file())
sys.path.insert(0, str(ROOT / "tools" / "ember-restart-3b"))

import run_vertical_slice  # noqa: E402


class _PastGuardSentinel(Exception):
    """Raised by the mocked UnifiedDecoder to prove the guard let execution proceed."""


REAL_RECEIPT_SHA = "r" * 64
REAL_TOKENIZER_SHA = "t" * 64
REAL_ARCHITECTURE_SHA = "a" * 64


class SemanticIdentityBindingTests(unittest.TestCase):
    def _call(self, *, expected_receipt_sha256, expected_tokenizer_sha256, expected_architecture_sha256,
               stream_receipt_sha256=REAL_RECEIPT_SHA, stream_tokenizer_sha256=REAL_TOKENIZER_SHA):
        stream = SimpleNamespace(
            vocab_size=None,  # set below to match the real config, so the vocab check never fires
            receipt_sha256=stream_receipt_sha256,
            tokenizer_sha256=stream_tokenizer_sha256,
        )
        with ExitStack() as stack:
            stack.enter_context(patch.object(run_vertical_slice, "run_text_lab_preflight", return_value={"result": "VERIFIED"}))
            stack.enter_context(patch.object(run_vertical_slice, "production_artifact_root", side_effect=lambda path, **_kwargs: path))
            stack.enter_context(patch.object(run_vertical_slice, "governed_resource_preflight", return_value={"free_gb": 32.0}))
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "is_available", return_value=True))
            stack.enter_context(patch.object(run_vertical_slice.torch.cuda, "mem_get_info", return_value=(32 * 1024**3, 32 * 1024**3)))

            real_config = run_vertical_slice.RestartDecoderConfig.from_contract(ROOT / "configs" / "ember-restart-3b.json")
            stream.vocab_size = real_config.vocab_size

            stack.enter_context(patch.object(run_vertical_slice.ManifestBoundTokenStream, "from_receipt", return_value=stream))
            stack.enter_context(patch.object(run_vertical_slice, "_sha256", return_value=REAL_ARCHITECTURE_SHA))
            stack.enter_context(patch.object(run_vertical_slice, "UnifiedDecoder", side_effect=AssertionError("model construction reached")))
            with self.assertRaises(Exception) as excinfo:
                run_vertical_slice.run_semantic(
                    seed=1, artifact_root=Path("B:/semantic-artifacts"),
                    receipt_path=Path("receipt.json"), shards_root=Path("shards"), tokenizer_path=Path("tokenizer.json"),
                    expected_receipt_sha256=expected_receipt_sha256,
                    expected_tokenizer_sha256=expected_tokenizer_sha256,
                    expected_architecture_sha256=expected_architecture_sha256,
                    steps=1, sequence_length=8, checkpoint_interval=1, write_budget_bytes=1,
                )
            return excinfo.exception

    # ---- C1: the intended path still proceeds -------------------------------

    def test_c1_matching_expectations_proceed_past_the_guard(self):
        exc = self._call(
            expected_receipt_sha256=REAL_RECEIPT_SHA,
            expected_tokenizer_sha256=REAL_TOKENIZER_SHA,
            expected_architecture_sha256=REAL_ARCHITECTURE_SHA,
        )
        self.assertIsInstance(exc, AssertionError)
        self.assertIn("model construction reached", str(exc))

    # ---- C2/C3: a different but individually valid receipt/shard set --------
    # (a substituted receipt/shard set changes stream.receipt_sha256, since the
    # receipt's own bytes are the digest-of-record over its declared shards)

    def test_c2_c3_different_receipt_or_shard_set_is_refused(self):
        exc = self._call(
            expected_receipt_sha256=REAL_RECEIPT_SHA,
            expected_tokenizer_sha256=REAL_TOKENIZER_SHA,
            expected_architecture_sha256=REAL_ARCHITECTURE_SHA,
            stream_receipt_sha256="different-receipt-sha".ljust(64, "0"),
        )
        self.assertIsInstance(exc, RuntimeError)
        self.assertIn("semantic launch identity mismatch", str(exc))
        self.assertNotIsInstance(exc, AssertionError)

    # ---- C4: a different but valid tokenizer ---------------------------------

    def test_c4_different_tokenizer_is_refused(self):
        exc = self._call(
            expected_receipt_sha256=REAL_RECEIPT_SHA,
            expected_tokenizer_sha256=REAL_TOKENIZER_SHA,
            expected_architecture_sha256=REAL_ARCHITECTURE_SHA,
            stream_tokenizer_sha256="different-tokenizer-sha".ljust(64, "0"),
        )
        self.assertIsInstance(exc, RuntimeError)
        self.assertIn("semantic launch identity mismatch", str(exc))

    # ---- C5: config/architecture altered after the preflight -----------------

    def test_c5_architecture_drift_after_preflight_is_refused(self):
        exc = self._call(
            expected_receipt_sha256=REAL_RECEIPT_SHA,
            expected_tokenizer_sha256=REAL_TOKENIZER_SHA,
            expected_architecture_sha256="stale-architecture-sha".ljust(64, "0"),
        )
        self.assertIsInstance(exc, RuntimeError)
        self.assertIn("semantic launch identity mismatch", str(exc))

    # ---- S1: the expected-identity argument is ABSENT from the invocation ---
    # A guard that only runs when an optional argument is present is not a
    # guard: run_semantic's three expected_* parameters carry no default, so
    # omission is refused at the call boundary itself, before the function
    # body (and therefore this guard) ever executes.

    def test_s1_absent_expectation_is_refused_not_silently_accepted(self):
        with self.assertRaises(TypeError):
            run_vertical_slice.run_semantic(  # type: ignore[call-arg]
                seed=1, artifact_root=Path("B:/semantic-artifacts"),
                receipt_path=Path("receipt.json"), shards_root=Path("shards"), tokenizer_path=Path("tokenizer.json"),
                steps=1, sequence_length=8, checkpoint_interval=1, write_budget_bytes=1,
            )

    def test_s1_blank_expectation_string_is_refused(self):
        # Even if a caller passes an empty string rather than omitting the
        # argument, that must never read as "no expectation, therefore fine".
        exc = self._call(
            expected_receipt_sha256="",
            expected_tokenizer_sha256=REAL_TOKENIZER_SHA,
            expected_architecture_sha256=REAL_ARCHITECTURE_SHA,
        )
        self.assertIsInstance(exc, RuntimeError)
        self.assertIn("semantic launch identity mismatch", str(exc))

    # ---- O1/O2: the guard runs before model construction, and only every ----
    # comparison passing reaches the lenient (proceed) outcome -- exercised
    # directly by C1 (proceeds) vs C2-C5 (each refuses) above: every one of
    # those tests reaches the guard before UnifiedDecoder, and only the
    # all-match case (C1) is the one that reaches past it.


if __name__ == "__main__":
    unittest.main()
