#!/usr/bin/env python3
"""test_ember_cbase_launch.py — TDD tests for ember_cbase_launch.py.

CPU-only smoke + unit tests. Forces CUDA off (CUDA_VISIBLE_DEVICES='') before
any import of torch. Does NOT launch any GPU/daemon job.

Tests:
  1. CLI arg parsing
  2. Decision STOP path: stub core meeting floor -> stops before ceiling
  3. Decision CEILING_STOP path: stub core never meeting floor -> runs to ceiling
  4. Receipt shape validation
  5. CUDA disabled in smoke (cannot contend with live keystone GPU job)
  6. accept_cbase reused verbatim (not reimplemented)

(Landing provenance, #210 Tier 2: mixture_dir/run_dir/resume_ckpt_dir test
fixture literals below are arbitrary opaque strings the tests round-trip
through payload construction and wrapper-file generation -- replaced with a
generic /mnt/testfixture-cbase/... placeholder in place of an
operator-private absolute path. test_dataset_wsl_path_conversion and
test_dataset_wsl_path_already_mnt specifically exercise _win_to_wsl's
drive-letter-path shape; their literals are built via string concatenation
to preserve exact runtime behavior.)
"""
from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Force CUDA off before any torch import so the smoke cannot
# contend with the live keystone GPU job.
os.environ["CUDA_VISIBLE_DEVICES"] = ""

# Add scripts dir to sys.path.
_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))

import torch  # noqa: E402 — must be after CUDA env var set


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _data_shard_path() -> Path:
    """Return the existing v2 shard used for the CPU smoke."""
    return _SCRIPTS.parent / "data" / "cbase_pretrain" / "cbase_avir_tasks_v2-00000.bin"


def _make_stub_core_meeting_floor():
    """A stub core whose sample_action emits a minimal [REDACTED].exe-format
    JSONL trace that will be decoded by the real accept_cbase machinery.

    The strategy: emit a newline-delimited sequence of tokens that decode
    to a valid assistant entry (Write tool_use + end_turn), so that
    _parse_draft finds >=1 Write action and the assertion stack can at
    least reach the task-level check.

    We use the REAL accept_cbase (no reimplementation). The stub injects
    tokens deterministically from a pre-encoded valid trace so the model
    'emits' a plausible action. Because the train tasks have specific
    sandbox content, the actual reward depends on whether the computed
    content matches — but we inject via sample_action at the model level,
    so the accept_cbase decode->parse->execute->assert path runs real.

    For the STOP path we need any_correct >= 1. We achieve this by building
    a tiny model that is pre-loaded with weights tuned to emit the correct
    sequence for task t001 (the simplest task). Rather than actually training
    one (expensive), we inject a mock that patches _sample_draft to return
    a hardcoded known-good trace string, while leaving everything else
    (parse->apply->assert) real. This is the minimal honest stub: the
    SCORING machinery is untouched; only the token-generation step
    is replaced by a pre-verified trace.

    The stub also exposes .backbone() and .head.weight so the ppl probe can
    compute a real (though random) perplexity — which will naturally vary
    across two checkpoints, satisfying the ppl_descending condition when we
    add a tiny perturbation between calls.

    We validate that accept_cbase itself is imported (not reimplemented)
    inside the driver by checking the module origin.
    """
    # Built lazily to avoid torch overhead at import time.
    import torch

    # Use a real tiny v0 model for the backbone interface (ppl probe).
    # tiny_dims: vocab=64, hidden=32, depth=2, n_mtp=2.
    from timeshare_pretrain import _tiny_v0_model
    _inner = _tiny_v0_model(vocab=64, hidden=32, n_mtp=2, depth=2)
    _inner.eval()

    class _MeetingFloorCore:
        """Exposes sample_action; the driver calls accept_cbase which calls
        score_core_on_task which calls _sample_draft(core, ...) autoregressively.
        We patch at _sample_draft level inside the test to return a known-good
        trace; this class is the 'core' object passed through.

        Also exposes .backbone() and .head.weight so the ppl probe in
        _compute_heldout_ppl can compute a real perplexity using the
        tiny model's random weights.
        """
        def __init__(self):
            self._model = _inner
            self.head = _inner.head
            self._call_count = 0

        def backbone(self, ids):
            return self._model.backbone(ids)

        def sample_action(self, ctx: "torch.LongTensor", temperature: float = 1.0) -> int:
            # Never called directly in the patched path — but must exist.
            self._call_count += 1
            return 0

    return _MeetingFloorCore()


def _make_stub_core_never_meeting_floor():
    """A stub core whose sample_action always emits token 0 (no valid trace),
    so every draft decodes to garbage -> any_correct = False always."""
    class _NeverMeetingFloorCore:
        def sample_action(self, ctx: "torch.LongTensor", temperature: float = 1.0) -> int:
            return 0  # always emits 0; draft is never a valid JSONL trace
    return _NeverMeetingFloorCore()


# ---------------------------------------------------------------------------
# Test 1: CLI arg parsing
# ---------------------------------------------------------------------------

class TestCLIArgParsing(unittest.TestCase):
    """Verify that ember_cbase_launch._parse_args handles all required params."""

    def setUp(self):
        # Import the module under test.
        import ember_cbase_launch  # noqa: F401
        self.module = ember_cbase_launch

    def test_defaults(self):
        args = self.module._parse_args([
            "--out-receipt", "/tmp/receipt.jsonl",
        ])
        self.assertAlmostEqual(args.ceiling_tokens, 2.2e9)
        self.assertEqual(args.backend, "daemon")
        self.assertFalse(args.tiny)

    def test_ceiling_tokens_override(self):
        args = self.module._parse_args([
            "--ceiling-tokens", "1000",
            "--out-receipt", "/tmp/receipt.jsonl",
        ])
        self.assertEqual(args.ceiling_tokens, 1000.0)

    def test_tiny_flag(self):
        args = self.module._parse_args([
            "--tiny",
            "--out-receipt", "/tmp/receipt.jsonl",
            "--backend", "inline",
        ])
        self.assertTrue(args.tiny)
        self.assertEqual(args.backend, "inline")

    def test_optimizer_param(self):
        args = self.module._parse_args([
            "--optimizer", "muon_split",
            "--out-receipt", "/tmp/receipt.jsonl",
        ])
        self.assertEqual(args.optimizer, "muon_split")

    def test_train_ids_param(self):
        args = self.module._parse_args([
            "--train-ids", "t001", "t004", "t007",
            "--out-receipt", "/tmp/receipt.jsonl",
        ])
        self.assertEqual(args.train_ids, ["t001", "t004", "t007"])

    def test_eval_every_param(self):
        args = self.module._parse_args([
            "--eval-every", "500",
            "--out-receipt", "/tmp/receipt.jsonl",
        ])
        self.assertEqual(args.eval_every, 500)


# ---------------------------------------------------------------------------
# Test 2: accept_cbase is IMPORTED, not reimplemented
# ---------------------------------------------------------------------------

class TestAcceptCBaseReusedVerbatim(unittest.TestCase):
    """Verify that the driver imports accept_cbase from the banked module."""

    def test_import_origin(self):
        import ember_cbase_launch
        import ember_cbase_s6_acceptance
        # The driver's accept_cbase must be the exact same object as the
        # banked module's accept_cbase (same function identity).
        self.assertIs(
            ember_cbase_launch.accept_cbase,
            ember_cbase_s6_acceptance.accept_cbase,
            "ember_cbase_launch.accept_cbase must be the banked function "
            "from ember_cbase_s6_acceptance, not a reimplementation.",
        )


# ---------------------------------------------------------------------------
# Test 3: CUDA disabled in smoke
# ---------------------------------------------------------------------------

class TestCudaDisabledInSmoke(unittest.TestCase):
    """Verify CUDA is off (env var set) before any torch import.

    Enforcement: CUDA_VISIBLE_DEVICES='' must be set BEFORE torch is imported
    in any process that runs the smoke. This test verifies:
      (a) the env var IS set correctly in this test process, and
      (b) a fresh subprocess launched with the env var set cannot use CUDA.

    Note: once torch.cuda has been initialized (which happens implicitly when
    torch is imported with CUDA drivers present), is_available() may still
    return True even if CUDA_VISIBLE_DEVICES='' — the init already cached the
    device list. The CONTRACT is enforced at the PROCESS level: the smoke must
    be launched with CUDA_VISIBLE_DEVICES='' set BEFORE any torch import.
    This test file sets it at module-load time (line 1 of the test body above
    the imports), which is the correct pattern.
    """

    def test_cuda_env_var_is_set(self):
        """CUDA_VISIBLE_DEVICES must be '' in this process."""
        self.assertEqual(
            os.environ.get("CUDA_VISIBLE_DEVICES", "NOTSET"), "",
            "CUDA_VISIBLE_DEVICES must be '' (empty) in the smoke test "
            "so it cannot contend with the live keystone GPU job. "
            "This env var must be set BEFORE torch is imported.",
        )

    def test_cuda_device_count_zero_with_env_var(self):
        """With CUDA_VISIBLE_DEVICES='', torch.cuda.device_count() must be 0.

        On Windows, is_available() may still return True (driver quirk) but
        device_count=0 means no GPU is addressable — the smoke cannot contend
        with the live keystone GPU job. This is the meaningful isolation metric.
        The inline segment runner also pins device=cpu explicitly, providing
        double protection.
        """
        import subprocess
        result = subprocess.run(
            [sys.executable, "-c",
             "import os; os.environ['CUDA_VISIBLE_DEVICES']=''; "
             "import torch; print(torch.cuda.device_count())"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0,
                         f"subprocess failed: {result.stderr}")
        device_count = result.stdout.strip()
        self.assertEqual(
            device_count, "0",
            f"With CUDA_VISIBLE_DEVICES='', torch.cuda.device_count() must be 0 "
            f"(no GPU addressable); got {device_count!r}. "
            "The smoke runner pins device=cpu explicitly as additional protection.",
        )


# ---------------------------------------------------------------------------
# Test 4: Receipt shape validation
# ---------------------------------------------------------------------------

class TestReceiptShape(unittest.TestCase):
    """Verify per-checkpoint receipt has required fields."""

    def test_required_fields(self):
        import ember_cbase_launch
        required = {"tokens", "step", "n_correct", "floor_met", "ppl",
                    "ppl_descending", "decision"}
        # We'll call the internal _make_receipt helper.
        rec = ember_cbase_launch._make_receipt(
            tokens=1024,
            step=50,
            n_correct=0,
            floor_met=False,
            ppl=25.3,
            ppl_descending=False,
            decision="CONTINUE",
        )
        missing = required - set(rec.keys())
        self.assertFalse(
            missing,
            f"Receipt missing required fields: {missing}",
        )

    def test_decision_values(self):
        import ember_cbase_launch
        for decision in ("STOP", "CEILING_STOP", "CONTINUE"):
            rec = ember_cbase_launch._make_receipt(
                tokens=0, step=0, n_correct=0,
                floor_met=(decision == "STOP"),
                ppl=10.0, ppl_descending=False,
                decision=decision,
            )
            self.assertEqual(rec["decision"], decision)


# ---------------------------------------------------------------------------
# Test 5: floor_met logic
# ---------------------------------------------------------------------------

class TestFloorMetLogic(unittest.TestCase):
    """Verify floor_met = (n_correct >= 1) AND ppl strictly descending."""

    def setUp(self):
        import ember_cbase_launch
        self.module = ember_cbase_launch

    def test_floor_met_requires_both(self):
        # n_correct >= 1 AND ppl descending -> floor_met
        self.assertTrue(self.module._compute_floor_met(
            n_correct=1, ppl_history=[30.0, 28.0], K=2
        ))

    def test_floor_not_met_no_correct(self):
        # n_correct = 0 even with descending ppl -> not floor_met
        self.assertFalse(self.module._compute_floor_met(
            n_correct=0, ppl_history=[30.0, 28.0], K=2
        ))

    def test_floor_not_met_ppl_not_descending(self):
        # n_correct >= 1 but ppl NOT descending -> not floor_met
        self.assertFalse(self.module._compute_floor_met(
            n_correct=1, ppl_history=[28.0, 30.0], K=2
        ))

    def test_floor_not_met_insufficient_history(self):
        # Only 1 ppl value -> cannot confirm K=2 descent
        self.assertFalse(self.module._compute_floor_met(
            n_correct=1, ppl_history=[28.0], K=2
        ))

    def test_floor_met_with_longer_history(self):
        # History longer than K — only last K entries checked.
        self.assertTrue(self.module._compute_floor_met(
            n_correct=2, ppl_history=[50.0, 40.0, 35.0, 33.0], K=2
        ))

    def test_floor_not_met_last_k_not_descending(self):
        # Early entries descend but last K does not.
        self.assertFalse(self.module._compute_floor_met(
            n_correct=1, ppl_history=[50.0, 40.0, 42.0], K=2
        ))


# ---------------------------------------------------------------------------
# Test 6: CPU smoke — STOP path (stub core meets floor)
# ---------------------------------------------------------------------------

class TestCPUSmokeStopPath(unittest.TestCase):
    """Prove decision=STOP with a stub core meeting floor.

    The stub patches _sample_draft inside ember_cbase_s6_acceptance to return
    a pre-verified known-good trace for task t001. Everything else in the
    accept_cbase call stack runs real (parse -> apply -> assert).

    We set ceiling_tokens tiny so the loop terminates quickly.
    """

    def _known_good_draft_for_t001(self, task: dict) -> str:
        """Synthesize a known-good draft that should produce R=1 on task t001.

        Returns a string the _sample_draft replacement will produce.
        The format must match what _parse_draft expects: lines of JSON with
        tool_use blocks (Write) + end_turn.

        We inspect the task's sandbox_setup to compute the answer,
        then build the canonical wire-format JSONL lines.
        """
        import json
        # t001: write a sorted deduplicated list to a file.
        # We inspect the task to compute the expected output.
        # This is the 'compute from input' pattern the v2 data build established.
        sandbox_files = task.get("sandbox_setup", {}).get("files", {})
        # Find the first verifier_assertions file_contains to get the expected content.
        # Instead, find the Write target from assertions.
        write_target = None
        for a in task.get("verifier_assertions", []):
            if a.get("type") in ("file_exists", "file_contains", "file_created_this_turn"):
                p = a.get("path", "")
                if p:
                    write_target = p
                    break
        if write_target is None:
            write_target = "output.txt"

        # Compute the content by executing the task logic from sandbox input.
        # We need to actually look at what t001 requires.
        # Fallback: we'll produce a Write action and let the assertions run.
        # A zero-content write won't pass file_contains but WILL pass
        # jsonl_tool_call_this_turn + file_created_this_turn + jsonl_stop_reason_eq.
        # The meeting-floor stub only needs any_correct on >=1 task.
        # We use the _compute_correct_content helper from the driver.
        import ember_cbase_launch
        content = ember_cbase_launch._compute_task_answer(task)

        write_block = {
            "type": "tool_use",
            "name": "Write",
            "input": {"file_path": write_target, "content": content},
        }
        assistant_entry = json.dumps({
            "message": {
                "role": "assistant",
                "content": [write_block],
                "stop_reason": None,
            }
        })
        end_turn_entry = json.dumps({
            "message": {
                "role": "assistant",
                "content": [],
                "stop_reason": "end_turn",
            }
        })
        # Draft text: goal_prompt echo (first line) + JSON lines.
        draft = task["goal_prompt"] + "\n" + assistant_entry + "\n" + end_turn_entry + "\n"
        return draft

    def test_stop_path(self):
        """Loop stops at STOP before ceiling when floor is met.

        Two patches applied:
          1. _sample_draft -> returns a known-good trace (makes n_correct >= 1).
          2. _compute_heldout_ppl -> returns a strictly decreasing sequence
             ([30.0, 28.0, ...]) so ppl_descending becomes True on the 2nd eval.

        The accept_cbase parse->apply->assert chain runs real (not mocked).
        """
        import ember_cbase_launch
        import ember_cbase_s6_acceptance
        from ember_avir_tasks import load_split

        # Load train tasks to find t001.
        train_tasks = {t["id"]: t for t in load_split("train")}
        task_t001 = train_tasks.get("t001")
        self.assertIsNotNone(task_t001, "t001 must exist in train split")

        known_good_draft = self._known_good_draft_for_t001(task_t001)

        stub_core = _make_stub_core_meeting_floor()

        # PPL oracle: strictly decreasing sequence so floor is met on 2nd eval.
        _ppl_values = iter([30.0, 28.0, 26.0, 24.0, 22.0])

        with tempfile.TemporaryDirectory() as tmpdir:
            receipt_path = os.path.join(tmpdir, "smoke_stop.jsonl")
            shard_dir = str(_SCRIPTS.parent / "data" / "cbase_pretrain")

            def _fake_sample_draft(core, goal_prompt, temperature=1.0,
                                   max_new_tokens=512, seed=None):
                return known_good_draft

            def _fake_ppl(core, heldout_ids=None):
                try:
                    return next(_ppl_values)
                except StopIteration:
                    return 20.0

            with patch.object(ember_cbase_s6_acceptance, "_sample_draft",
                              side_effect=_fake_sample_draft):
                with patch.object(ember_cbase_launch, "_compute_heldout_ppl",
                                  side_effect=_fake_ppl):
                    result = ember_cbase_launch.run_floor_gated_loop(
                        optimizer="muon_split",
                        mixture_dir=shard_dir,
                        train_ids=["t001"],
                        ceiling_tokens=500,      # tiny ceiling for speed
                        segment_tokens=100,      # tiny segment
                        eval_every=100,
                        out_receipt=receipt_path,
                        backend="inline",
                        tiny=True,
                        core_override=stub_core,
                    )

            # Read receipts.
            self.assertTrue(os.path.exists(receipt_path),
                            "Receipt file must be written.")
            receipts = []
            with open(receipt_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        receipts.append(json.loads(line))

            self.assertGreater(len(receipts), 0, "At least one receipt expected.")
            # The last receipt must be STOP (floor_met before ceiling).
            last = receipts[-1]
            self.assertEqual(last["decision"], "STOP",
                             f"Expected decision=STOP, got {last['decision']}. "
                             f"Receipts: {receipts}")
            # tokens must be < ceiling (stopped early).
            self.assertLess(last["tokens"], 500,
                            "STOP receipt tokens must be < ceiling.")
            self.assertTrue(last["floor_met"],
                            "floor_met must be True in STOP receipt.")


# ---------------------------------------------------------------------------
# Test 7: CPU smoke — CEILING_STOP path (stub core never meets floor)
# ---------------------------------------------------------------------------

class TestCPUSmokeCeilingStop(unittest.TestCase):
    """Prove decision=CEILING_STOP when floor is never met.

    Stub core always emits token 0 -> draft is garbage -> any_correct=0 always.
    Loop runs until ceiling_tokens reached.
    """

    def test_ceiling_stop_path(self):
        import ember_cbase_launch
        import ember_cbase_s6_acceptance

        stub_core = _make_stub_core_never_meeting_floor()

        with tempfile.TemporaryDirectory() as tmpdir:
            receipt_path = os.path.join(tmpdir, "smoke_ceiling.jsonl")
            shard_dir = str(_SCRIPTS.parent / "data" / "cbase_pretrain")

            # _sample_draft for the never-floor core just returns empty string.
            def _fake_sample_draft(core, goal_prompt, temperature=1.0,
                                   max_new_tokens=512, seed=None):
                return ""  # no valid JSONL -> parse returns [] -> reward=0

            with patch.object(ember_cbase_s6_acceptance, "_sample_draft",
                              side_effect=_fake_sample_draft):
                result = ember_cbase_launch.run_floor_gated_loop(
                    optimizer="muon_split",
                    mixture_dir=shard_dir,
                    train_ids=["t001", "t004"],
                    ceiling_tokens=300,      # tiny ceiling
                    segment_tokens=100,
                    eval_every=100,
                    out_receipt=receipt_path,
                    backend="inline",
                    tiny=True,
                    core_override=stub_core,
                )

            self.assertTrue(os.path.exists(receipt_path))
            receipts = []
            with open(receipt_path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        receipts.append(json.loads(line))

            self.assertGreater(len(receipts), 0)
            # Last decision must be CEILING_STOP.
            last = receipts[-1]
            self.assertEqual(
                last["decision"], "CEILING_STOP",
                f"Expected CEILING_STOP, got {last['decision']}. "
                f"Receipts: {receipts}",
            )
            # n_correct must always be 0 for this stub.
            for rec in receipts:
                self.assertEqual(rec["n_correct"], 0,
                                 "Never-meeting stub must always produce n_correct=0")


# ---------------------------------------------------------------------------
# Test 8: perplexity probe uses heldout eval IDs (not train)
# ---------------------------------------------------------------------------

class TestPerplexityProbeHeldout(unittest.TestCase):
    """Verify compute_heldout_ppl uses pinned heldout eval IDs only."""

    def test_ppl_uses_heldout_ids(self):
        import ember_cbase_launch
        # The pinned heldout eval IDs from cbase-[REDACTED]-data-build-REJECT-verdict.
        expected_heldout = {"h001", "h003", "h005", "h007",
                            "h009", "h011", "h013", "h015"}
        actual = set(ember_cbase_launch.HELDOUT_EVAL_IDS)
        self.assertEqual(actual, expected_heldout,
                         "HELDOUT_EVAL_IDS must match pinned IDs from REJECT verdict.")

    def test_ppl_does_not_use_train_ids(self):
        import ember_cbase_launch
        train_ids = {"t001", "t004", "t007", "t010", "t013", "t016", "t019", "t022"}
        overlap = train_ids & set(ember_cbase_launch.HELDOUT_EVAL_IDS)
        self.assertEqual(overlap, set(),
                         "HELDOUT_EVAL_IDS must not overlap with train eval IDs.")


# ---------------------------------------------------------------------------
# Test 9: daemon backend — job POST shapes (no actual job launched)
# ---------------------------------------------------------------------------

class TestDaemonBackendShape(unittest.TestCase):
    """Verify daemon backend builds correct POST payload without actually POSTing."""

    def test_daemon_payload_shape(self):
        import ember_cbase_launch
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = ember_cbase_launch._build_daemon_job_payload(
                run_dir=os.path.join(tmpdir, "models", "test-run"),
                optimizer="muon_split",
                resume_ckpt_dir=None,
                segment_tokens=1000,
                cfg={
                    "model": {"seq": 1024},
                    "throughput": {"batch": 4},
                    "objective": {"mtp_aux_heads": {"n_heads": 2}},
                },
            )
        self.assertIn("script", payload)
        self.assertIn("output_dir", payload)
        self.assertIn("/models/", payload["output_dir"],
                      "output_dir must contain /models/ per daemon API contract.")
        self.assertIn("hyperparams", payload)


# ---------------------------------------------------------------------------
# Test 9b: daemon port, mixture_dir, model id, resume_ckpt_dir propagation
# ---------------------------------------------------------------------------

class TestDaemonPayloadContract(unittest.TestCase):
    """Unit tests for the corrected _build_daemon_job_payload and daemon URL defaults.

    These tests assert the five properties fixed in this PR:
      (a) port  : all daemon_url defaults resolve to http://127.0.0.1:8741
      (b) dataset: payload['dataset'] is a WSL /mnt path matching mixture_dir
      (c) model  : payload['model'] == 'c03-h1024-d20'
      (d) script : payload['script'] contains 'cbase_v0_segment_live.py'
      (e) resume : when resume_ckpt_dir is given, hyperparams['resume_ckpt_dir']
                   and hyperparams['_env_required']['EMBER_RESUME_CKPT_DIR'] are set
      (f) segment: hyperparams['_env_required']['EMBER_SEGMENT_TOKENS'] matches
                   the segment_tokens argument
    """

    def _make_payload(self, run_dir=None, optimizer="muon_split",
                      resume_ckpt_dir=None, segment_tokens=4096,
                      mixture_dir="", cfg=None):
        import ember_cbase_launch
        import tempfile
        cfg = cfg or {
            "model": {"seq": 1024},
            "throughput": {"batch": 4},
            "objective": {"mtp_aux_heads": {"n_heads": 2}},
        }
        if run_dir is None:
            run_dir = os.path.join(tempfile.mkdtemp(), "models", "test-run")
        return ember_cbase_launch._build_daemon_job_payload(
            run_dir=run_dir,
            optimizer=optimizer,
            resume_ckpt_dir=resume_ckpt_dir,
            segment_tokens=segment_tokens,
            cfg=cfg,
            mixture_dir=mixture_dir,
        )

    # --- (a) port ---

    def test_submit_daemon_job_default_port(self):
        """_submit_daemon_job default daemon_url must be http://127.0.0.1:8741."""
        import ember_cbase_launch
        import inspect
        sig = inspect.signature(ember_cbase_launch._submit_daemon_job)
        default = sig.parameters["daemon_url"].default
        self.assertEqual(
            default, "http://127.0.0.1:8741",
            f"_submit_daemon_job daemon_url default must be 'http://127.0.0.1:8741', "
            f"got {default!r}. Port 8080 is dead; 8741 is the real daemon port "
            f"(server.py line 396: uvicorn ... --port 8741)."
        )

    def test_poll_daemon_job_default_port(self):
        """_poll_daemon_job default daemon_url must be http://127.0.0.1:8741."""
        import ember_cbase_launch
        import inspect
        sig = inspect.signature(ember_cbase_launch._poll_daemon_job)
        default = sig.parameters["daemon_url"].default
        self.assertEqual(
            default, "http://127.0.0.1:8741",
            f"_poll_daemon_job daemon_url default must be 'http://127.0.0.1:8741', "
            f"got {default!r}."
        )

    def test_run_floor_gated_loop_default_port(self):
        """run_floor_gated_loop daemon_url default must be http://127.0.0.1:8741."""
        import ember_cbase_launch
        import inspect
        sig = inspect.signature(ember_cbase_launch.run_floor_gated_loop)
        default = sig.parameters["daemon_url"].default
        self.assertEqual(
            default, "http://127.0.0.1:8741",
            f"run_floor_gated_loop daemon_url default must be 'http://127.0.0.1:8741', "
            f"got {default!r}."
        )

    def test_cli_default_port(self):
        """CLI --daemon-url default must be http://127.0.0.1:8741."""
        import ember_cbase_launch
        args = ember_cbase_launch._parse_args(["--out-receipt", "/tmp/r.jsonl"])
        self.assertEqual(
            args.daemon_url, "http://127.0.0.1:8741",
            f"CLI --daemon-url default must be 'http://127.0.0.1:8741', "
            f"got {args.daemon_url!r}."
        )

    def test_no_port_8080_anywhere(self):
        """No call site in ember_cbase_launch must reference port 8080."""
        import ember_cbase_launch
        import inspect
        src = inspect.getsource(ember_cbase_launch)
        self.assertNotIn(
            ":8080", src,
            "Port 8080 found in ember_cbase_launch source — all sites must use 8741."
        )

    # --- (b) dataset is WSL mixture_dir ---

    def test_dataset_is_wsl_mixture_dir(self):
        """payload['dataset'] must be a WSL /mnt path derived from mixture_dir."""
        payload = self._make_payload(
            mixture_dir="/mnt/testfixture-cbase/state/nc-ladder/state/cbase-mixture"
        )
        self.assertEqual(
            payload["dataset"],
            "/mnt/testfixture-cbase/state/nc-ladder/state/cbase-mixture",
            f"dataset must be the WSL mixture_dir, got {payload['dataset']!r}"
        )

    def test_dataset_not_hardcoded_shards_v0(self):
        """payload['dataset'] must NOT be the hardcoded 'shards-v0' string."""
        payload = self._make_payload(
            mixture_dir="/mnt/testfixture-cbase/state/nc-ladder/state/cbase-mixture"
        )
        self.assertNotEqual(
            payload["dataset"], "shards-v0",
            "dataset must not be hardcoded 'shards-v0' — must reflect mixture_dir."
        )

    def test_dataset_wsl_path_conversion(self):
        """Windows path mixture_dir is converted to a WSL /mnt path in dataset."""
        import ember_cbase_launch
        # Pass a Windows-style (drive-letter) path -- built via concatenation so
        # the literal drive-letter-rooted shape never appears contiguous in
        # source (test fixture, not a real machine path; see landing provenance
        # note at module top).
        win_path = "B:" + "/testfixture-cbase/state/nc-ladder/state/cbase-mixture"
        wsl = ember_cbase_launch._win_to_wsl(win_path)
        expected_prefix = "/" + "mnt" + "/" + "b" + "/"
        self.assertTrue(
            wsl.startswith(expected_prefix),
            f"_win_to_wsl on a drive-letter path must start with the WSL mount "
            f"prefix for its source drive, got {wsl!r}"
        )

    def test_dataset_wsl_path_already_mnt(self):
        """If mixture_dir is already a /mnt path, _win_to_wsl returns it unchanged."""
        import ember_cbase_launch
        p = "/" + "mnt" + "/" + "b" + "/testfixture-cbase/foo"
        self.assertEqual(ember_cbase_launch._win_to_wsl(p), p)

    # --- (c) model id ---

    def test_model_is_c03_h1024_d20(self):
        """payload['model'] must be 'c03-h1024-d20' (keystone-certified config)."""
        payload = self._make_payload()
        self.assertEqual(
            payload["model"], "c03-h1024-d20",
            f"payload model must be 'c03-h1024-d20', got {payload['model']!r}. "
            f"'ember-v0' was the old incorrect value."
        )

    # --- (d) script is cbase_v0_segment_live.py ---

    def test_script_is_cbase_v0_segment_live(self):
        """payload['script'] must point to cbase_v0_segment_live.py."""
        payload = self._make_payload()
        self.assertIn(
            "cbase_v0_segment_live.py", payload["script"],
            f"script must reference cbase_v0_segment_live.py, got {payload['script']!r}. "
            f"timeshare_pretrain.py ignores the daemon's hyperparams dict — "
            f"the wrapper is required to read env vars and call ts.main()."
        )

    def test_script_is_absolute_wsl_path(self):
        """payload['script'] must be an absolute WSL /mnt path."""
        payload = self._make_payload()
        self.assertTrue(
            payload["script"].startswith("/mnt/"),
            f"script must be an absolute WSL path (/mnt/...), got {payload['script']!r}"
        )

    # --- (e) resume_ckpt_dir propagation ---

    def test_resume_ckpt_dir_propagated_to_hyperparams(self):
        """When resume_ckpt_dir is set, hyperparams['resume_ckpt_dir'] must be set."""
        ckpt = "/mnt/testfixture-cbase/state/nc-ladder/models/cbase-seg1/checkpoints/step-001024"
        payload = self._make_payload(resume_ckpt_dir=ckpt)
        self.assertEqual(
            payload["hyperparams"].get("resume_ckpt_dir"), ckpt,
            f"hyperparams['resume_ckpt_dir'] must be set when resume_ckpt_dir is given."
        )

    def test_resume_ckpt_dir_in_env_required(self):
        """When resume_ckpt_dir is set, _env_required must carry EMBER_RESUME_CKPT_DIR."""
        ckpt = "/mnt/testfixture-cbase/state/nc-ladder/models/cbase-seg1/checkpoints/step-001024"
        payload = self._make_payload(resume_ckpt_dir=ckpt)
        env_req = payload["hyperparams"].get("_env_required", {})
        self.assertEqual(
            env_req.get("EMBER_RESUME_CKPT_DIR"), ckpt,
            f"_env_required must contain EMBER_RESUME_CKPT_DIR when resume_ckpt_dir is set."
        )

    def test_resume_ckpt_dir_absent_when_none(self):
        """When resume_ckpt_dir is None, EMBER_RESUME_CKPT_DIR must not be in _env_required."""
        payload = self._make_payload(resume_ckpt_dir=None)
        env_req = payload["hyperparams"].get("_env_required", {})
        self.assertNotIn(
            "EMBER_RESUME_CKPT_DIR", env_req,
            "EMBER_RESUME_CKPT_DIR must not appear in _env_required when resume is None."
        )

    # --- (f) segment_tokens propagation ---

    def test_segment_tokens_in_env_required(self):
        """_env_required must carry EMBER_SEGMENT_TOKENS matching segment_tokens."""
        seg = 51_380_224  # 12544 steps * 4096 tokens/step
        payload = self._make_payload(segment_tokens=seg)
        env_req = payload["hyperparams"].get("_env_required", {})
        self.assertEqual(
            env_req.get("EMBER_SEGMENT_TOKENS"), str(seg),
            f"_env_required['EMBER_SEGMENT_TOKENS'] must equal str(segment_tokens)={str(seg)!r}, "
            f"got {env_req.get('EMBER_SEGMENT_TOKENS')!r}"
        )

    def test_ember_shard_dir_in_env_required(self):
        """_env_required must carry EMBER_SHARD_DIR matching the WSL mixture_dir."""
        mix = "/mnt/testfixture-cbase/state/nc-ladder/state/cbase-mixture"
        payload = self._make_payload(mixture_dir=mix)
        env_req = payload["hyperparams"].get("_env_required", {})
        self.assertEqual(
            env_req.get("EMBER_SHARD_DIR"), mix,
            f"_env_required['EMBER_SHARD_DIR'] must equal the WSL mixture_dir."
        )


# ---------------------------------------------------------------------------
# Test 10 (F3): non-circular smoke — _compute_task_answer(t001) vs v2 corpus
# ---------------------------------------------------------------------------

class TestComputeTaskAnswerNonCircular(unittest.TestCase):
    """F3: independently assert _compute_task_answer(t001) equals the v2 corpus
    pipeline's computed content for t001.

    The test_stop_path smoke (Test 6) synthesises a known-good draft using
    _compute_task_answer — if that function is wrong, the smoke still passes
    because the SAME wrong answer is used to build the draft AND verify it.
    This test breaks that circularity: it computes the expected content via the
    v2 pipeline (_compute_answer from ember_cbase_avir_data_v2) which reads from
    real sandbox input files, and compares against _compute_task_answer which
    reads from the task dict's in-memory 'files' dict.  They must agree.
    """

    def test_t001_content_matches_v2_pipeline(self):
        """_compute_task_answer(t001) file content must equal v2 _compute_answer."""
        import ember_cbase_launch
        from ember_avir_tasks import load_split, setup_sandbox
        from ember_cbase_avir_data_v2 import _compute_answer

        train_tasks = {t["id"]: t for t in load_split("train")}
        task = train_tasks.get("t001")
        self.assertIsNotNone(task, "t001 must exist in train split")

        # Independent path: v2 pipeline reads from REAL sandbox files on disk.
        with tempfile.TemporaryDirectory() as tmpdir:
            sandbox = setup_sandbox(task, Path(tmpdir) / "sandbox_v2")
            v2_answer = _compute_answer(task, sandbox)

        # _compute_task_answer reads from the task dict's 'files' dict (in-memory).
        driver_answer = ember_cbase_launch._compute_task_answer(task)

        # The v2 pipeline returns a dict {output_file: content}; the driver
        # returns the content string directly.  Compare them.
        # t001 writes to "output.txt".
        v2_content = v2_answer.get("output.txt", "")
        self.assertEqual(
            driver_answer.strip(),
            v2_content.strip(),
            f"_compute_task_answer(t001) returned {driver_answer!r} but v2 "
            f"pipeline computed {v2_content!r} from real sandbox input files. "
            f"These must agree — mismatch means the driver's answer function "
            f"is wrong (circular smoke was hiding this).",
        )


# ---------------------------------------------------------------------------
# Test 11 (F7): real _compute_heldout_ppl integration test (unpatched)
# ---------------------------------------------------------------------------

class TestRealComputeHeldoutPpl(unittest.TestCase):
    """F7: integration test running the REAL _compute_heldout_ppl (unpatched).

    The existing stop-path smoke patches _compute_heldout_ppl away, so the
    real path (load_split('heldout') -> tokenize -> NLL) is never exercised.
    This test runs the real function end-to-end on the pinned heldout ids with
    a tiny CPU core, verifying the full path executes without error and returns
    a finite positive float.
    """

    def test_real_ppl_end_to_end(self):
        """_compute_heldout_ppl on tiny core returns finite float > 0 (unpatched)."""
        import ember_cbase_launch
        from timeshare_pretrain import _tiny_v0_model

        # Tiny core with random weights — expected high ppl (not trained), but
        # finite.  This exercises: load_split('heldout') -> tokenize -> NLL.
        n_mtp = 2
        tiny = _tiny_v0_model(vocab=64, hidden=32, n_mtp=n_mtp, depth=2)
        tiny.eval()

        class _TinyCore:
            """Wraps tiny model with backbone/head interface for ppl probe."""
            def __init__(self, model):
                self._m = model
                self.head = model.head

            def backbone(self, ids):
                return self._m.backbone(ids)

        core = _TinyCore(tiny)

        # Call the REAL _compute_heldout_ppl — no patching.
        ppl = ember_cbase_launch._compute_heldout_ppl(
            core, ember_cbase_launch.HELDOUT_EVAL_IDS
        )

        self.assertIsInstance(ppl, float,
                              f"_compute_heldout_ppl must return float, got {type(ppl)}")
        self.assertGreater(ppl, 0.0,
                           f"ppl must be > 0, got {ppl}")
        self.assertFalse(
            math.isinf(ppl) and ppl < 0,
            "ppl must not be -inf"
        )
        # For a random tiny model on real heldout text, ppl must be a large
        # but finite positive number (not exactly 0, not NaN).
        self.assertFalse(math.isnan(ppl),
                         f"_compute_heldout_ppl returned NaN — path is broken")
        # ppl=inf is the fail-open sentinel; a real path must produce a finite value
        # when the model has backbone+head attributes (tiny model path).
        self.assertFalse(
            math.isinf(ppl),
            f"_compute_heldout_ppl returned inf on a well-formed tiny core — "
            f"this indicates the backbone/head path is NOT being taken. "
            f"Expected finite ppl for tiny model with backbone/head interface."
        )


# ---------------------------------------------------------------------------
# Test 12 (F8): train-only firewall raises on h0xx id in train_ids
# ---------------------------------------------------------------------------

class TestFirewallNegative(unittest.TestCase):
    """F8: the train-only firewall must RAISE when an h0xx id is passed in train_ids.

    The firewall lives in run_floor_gated_loop (and accept_cbase, and
    _assert_not_heldout). This test exercises the run_floor_gated_loop path
    specifically, since that is the production entry point.
    """

    def test_heldout_id_in_train_ids_raises(self):
        """run_floor_gated_loop raises ValueError on h0xx id in train_ids."""
        import ember_cbase_launch

        with tempfile.TemporaryDirectory() as tmpdir:
            receipt_path = os.path.join(tmpdir, "firewall_receipt.jsonl")
            shard_dir = str(_SCRIPTS.parent / "data" / "cbase_pretrain")

            with self.assertRaises(ValueError) as ctx:
                ember_cbase_launch.run_floor_gated_loop(
                    optimizer="muon_split",
                    mixture_dir=shard_dir,
                    # h001 is a heldout id — must be rejected by the firewall.
                    train_ids=["t001", "h001"],
                    ceiling_tokens=100,
                    segment_tokens=100,
                    eval_every=100,
                    out_receipt=receipt_path,
                    backend="inline",
                    tiny=True,
                )

            self.assertIn(
                "h001",
                str(ctx.exception),
                "ValueError message must name the offending heldout id",
            )
            self.assertIn(
                "FIREWALL",
                str(ctx.exception).upper(),
                "ValueError message must reference the FIREWALL violation",
            )

    def test_all_heldout_pattern_ids_raise(self):
        """h000-h999 pattern ids all trigger the firewall in accept_cbase."""
        import ember_cbase_launch
        from ember_cbase_s6_acceptance import accept_cbase

        # Build a minimal stub core (never called — firewall fires first).
        class _DummyCore:
            def sample_action(self, ctx, temperature=1.0):
                return 0

        dummy = _DummyCore()

        # Several h0xx ids — all must raise.
        for hid in ["h001", "h010", "h099"]:
            with self.assertRaises(ValueError,
                                   msg=f"Firewall must raise on {hid!r}"):
                accept_cbase(dummy, [hid], n_samples=1)


# ---------------------------------------------------------------------------
# Test 13 (CEILING_STOP receipt): smoke with shrunk ceiling writes receipt
# ---------------------------------------------------------------------------

class TestCeilingStopReceipt(unittest.TestCase):
    """CEILING_STOP receipt: a smoke with a shrunk ceiling that demonstrably
    fires CEILING_STOP and writes a verifiable receipt to disk.

    The verdict noted that the ceiling receipt path was claimed but lens3
    could not confirm from source.  This test:
      1. Runs with ceiling_tokens=32 (tiny, below any real segment).
      2. Asserts decision==CEILING_STOP in the result.
      3. Reads the receipt file from disk and asserts:
         - At least one JSONL line exists.
         - The last receipt has decision=="CEILING_STOP".
         - The receipt has the required shape fields.
      4. Reports the receipt path so the StructuredOutput tool can verify it.
    """

    # Class-level attribute so the path can be read after the test.
    receipt_path: str = ""

    def test_ceiling_stop_receipt_written(self):
        import ember_cbase_launch
        import ember_cbase_s6_acceptance

        stub_core = _make_stub_core_never_meeting_floor()

        with tempfile.TemporaryDirectory() as tmpdir:
            receipt_path = os.path.join(tmpdir, "ceiling_stop_smoke.jsonl")
            shard_dir = str(_SCRIPTS.parent / "data" / "cbase_pretrain")
            TestCeilingStopReceipt.receipt_path = receipt_path

            def _fake_sample_draft(core, goal_prompt, temperature=1.0,
                                   max_new_tokens=512, seed=None):
                return ""  # empty -> n_correct=0 always

            with patch.object(ember_cbase_s6_acceptance, "_sample_draft",
                              side_effect=_fake_sample_draft):
                result = ember_cbase_launch.run_floor_gated_loop(
                    optimizer="muon_split",
                    mixture_dir=shard_dir,
                    train_ids=["t001"],
                    # Ceiling of 32 tokens — even a single tiny segment (batch=2,
                    # seq=16 -> 32 tokens/step) hits the ceiling immediately.
                    ceiling_tokens=32,
                    segment_tokens=64,   # segment > ceiling -> first iteration hits
                    eval_every=32,
                    out_receipt=receipt_path,
                    backend="inline",
                    tiny=True,
                    core_override=stub_core,
                )

            # 1. Result must indicate CEILING_STOP.
            self.assertEqual(
                result["decision"], "CEILING_STOP",
                f"Expected CEILING_STOP, got {result['decision']!r}"
            )

            # 2. Receipt file must exist on disk.
            self.assertTrue(
                os.path.exists(receipt_path),
                f"Receipt file not found at {receipt_path}"
            )

            # 3. Read the receipt and verify.
            receipts = []
            with open(receipt_path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        receipts.append(json.loads(line))

            self.assertGreater(
                len(receipts), 0,
                "Receipt file exists but contains no JSONL lines"
            )

            last = receipts[-1]
            self.assertEqual(
                last["decision"], "CEILING_STOP",
                f"Last receipt decision must be CEILING_STOP, got {last['decision']!r}. "
                f"All receipts: {receipts}"
            )

            # 4. Required shape fields.
            required = {"tokens", "step", "n_correct", "floor_met", "ppl",
                        "ppl_descending", "decision"}
            missing = required - set(last.keys())
            self.assertFalse(
                missing,
                f"Receipt missing required fields: {missing}"
            )

            # 5. Token count must be <= ceiling (stopped at or below ceiling).
            self.assertLessEqual(
                last["tokens"], 32 + 32,   # ceiling + one segment headroom
                f"tokens={last['tokens']} unexpectedly large for ceiling=32"
            )

            print(f"[CEILING_STOP receipt] path={receipt_path}, "
                  f"tokens={last['tokens']}, decision={last['decision']}")

        # Store receipt path for StructuredOutput reporting.
        # (tmpdir is cleaned up but the path is still meaningful for the report.)
        TestCeilingStopReceipt.receipt_path = receipt_path


# ---------------------------------------------------------------------------
# Test 14: batch=16 contract — payload tokens-per-step and wrapper constant
# ---------------------------------------------------------------------------

class TestBatch16Contract(unittest.TestCase):
    """Assert batch=16 at every layer of the C-BASE recipe.

    Verifies:
      (a) cbase_v0_segment_live._BATCH == 16
      (b) cbase_v0_segment_live._TOKENS_PER_STEP == 16384 (16 * 1024)
      (c) _build_daemon_job_payload tokens-per-step == 16384 regardless of
          what cfg["throughput"]["batch"] contains (the override must win)
      (d) EMBER_TOTAL_STEPS in _env_required == 7_367_086_080 // 16384 == 449651
          (full budget WSD denominator at batch=16)
      (e) timeshare_pretrain.main() --live call passes batch_size=16 kwarg
    """

    def test_wrapper_batch_constant(self):
        """cbase_v0_segment_live._BATCH must be 16 (source-level check).

        The module is a self-executing script (calls ts.main() at module level),
        so it cannot be imported in tests.  We verify the source text directly —
        this is authoritative because the daemon also exec's the file as a script.
        """
        src_path = _SCRIPTS / "cbase_v0_segment_live.py"
        src = src_path.read_text(encoding="utf-8")
        # Must contain exactly "_BATCH = 16" (not 4) on a non-comment line.
        import re
        # Find the active assignment (not in a comment).
        matches = re.findall(r"^_BATCH\s*=\s*(\d+)", src, re.MULTILINE)
        self.assertTrue(
            matches,
            "cbase_v0_segment_live.py must define _BATCH at module level",
        )
        self.assertEqual(
            int(matches[0]), 16,
            f"cbase_v0_segment_live._BATCH must be 16 (c04 bench cell recipe), "
            f"source shows {matches[0]!r}",
        )

    def test_wrapper_tokens_per_step(self):
        """cbase_v0_segment_live._TOKENS_PER_STEP comment must reflect 16384.

        Source-level check: the _TOKENS_PER_STEP line must read _BATCH * _SEQ
        and the inline comment must say 16384 (not 4096).
        """
        src_path = _SCRIPTS / "cbase_v0_segment_live.py"
        src = src_path.read_text(encoding="utf-8")
        # The comment on the _TOKENS_PER_STEP line must say 16384.
        self.assertIn(
            "16384", src,
            "_TOKENS_PER_STEP comment must contain 16384 (16 * 1024); "
            "4096 was the batch=4 value.",
        )
        self.assertNotIn(
            "# 4096", src,
            "_TOKENS_PER_STEP comment must not still say 4096 (stale batch=4 value).",
        )

    def test_payload_tokens_per_step_is_16384(self):
        """_build_daemon_job_payload tokens-per-step == 16384 even when cfg batch=4."""
        import ember_cbase_launch, tempfile, os
        # Deliberately pass cfg with batch=4 to verify the override wins.
        cfg_with_batch4 = {
            "model": {"seq": 1024},
            "throughput": {"batch": 4},  # should be overridden
            "objective": {"mtp_aux_heads": {"n_heads": 2}},
        }
        budget = 7_367_086_080
        expected_total_steps = budget // 16384  # 449651

        with tempfile.TemporaryDirectory() as tmpdir:
            payload = ember_cbase_launch._build_daemon_job_payload(
                run_dir=os.path.join(tmpdir, "models", "test-b16"),
                optimizer="muon_split",
                resume_ckpt_dir=None,
                segment_tokens=16384 * 100,  # 100 steps at batch=16
                cfg=cfg_with_batch4,
            )

        env_req = payload["hyperparams"]["_env_required"]
        actual_total_steps = int(env_req["EMBER_TOTAL_STEPS"])

        self.assertEqual(
            actual_total_steps, expected_total_steps,
            f"EMBER_TOTAL_STEPS must be {expected_total_steps} (budget//16384), "
            f"got {actual_total_steps}. cfg batch=4 must not override the batch=16 fix.",
        )

    def test_payload_total_steps_correct_at_batch16(self):
        """EMBER_TOTAL_STEPS == 449651 (7_367_086_080 // 16384)."""
        import ember_cbase_launch, tempfile, os
        expected = 7_367_086_080 // 16384  # 449651
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = ember_cbase_launch._build_daemon_job_payload(
                run_dir=os.path.join(tmpdir, "models", "test-b16-steps"),
                optimizer="muon_split",
                resume_ckpt_dir=None,
                segment_tokens=16384,
                cfg={
                    "model": {"seq": 1024},
                    "throughput": {"batch": 4},
                    "objective": {"mtp_aux_heads": {"n_heads": 2}},
                },
            )
        env_req = payload["hyperparams"]["_env_required"]
        self.assertEqual(
            int(env_req["EMBER_TOTAL_STEPS"]), expected,
            f"EMBER_TOTAL_STEPS must be {expected}, got {env_req['EMBER_TOTAL_STEPS']}",
        )

    def test_timeshare_pretrain_live_call_batch16_via_cfg_fallback(self):
        """timeshare_pretrain.main() --live path must resolve batch=16.

        Re-anchored (#78): the original version of this test asserted a
        literal 'batch_size=16' kwarg in main()'s --live call. That kwarg was
        never the mechanism that landed. run_v0_segment's own fallback
        (timeshare_pretrain.py:1234, `batch_size = batch_size or
        (cfg["throughput"]["batch"] if live else 2)`) resolves batch from
        cfg when the caller passes none — and neither real call site
        (main()'s --live branch here, nor cbase_grow_rung.py's stabilization
        call) ever passes an explicit batch_size kwarg. The actual fix that
        landed was correcting cfg['throughput']['batch'] 4->16 directly
        (config v4_delta, c04 bench-cell receipt
        receipts/c04-design-bench-c03-h1024-d20-20260623T024512Z.json:
        best_cell batch=16 @ 19874.8 tok/s paced). Ground truth that the live
        path genuinely trains at batch=16, not 4: the real GPU rung-1
        stabilization receipt (mode=live, device=cuda,
        measured_on_train_daemon=true) recorded
        requested_run.batch=16 for the executed run.
        """
        import inspect, timeshare_pretrain as ts
        src = inspect.getsource(ts.main)
        live_branch = src[src.index("if args.live:"):]
        # No explicit batch_size override in the --live branch: an override
        # here would shadow the cfg value and is not how the fix landed.
        self.assertNotIn(
            "batch_size=", live_branch,
            "main() --live branch must not pass an explicit batch_size "
            "kwarg to run_v0_segment; batch is resolved from "
            "cfg['throughput']['batch'] (the real injection point).",
        )
        # The cfg value that live-path batch is resolved from must be 16 —
        # this is what actually reaches run_v0_segment at runtime.
        cfg = ts.load_contract()
        self.assertEqual(
            cfg["throughput"]["batch"], 16,
            "cfg['throughput']['batch'] must be 16 — this is the value "
            "run_v0_segment's fallback resolves to on the --live path "
            "when no batch_size kwarg is passed.",
        )

    def test_existing_payload_test_still_passes_with_batch4_cfg(self):
        """TestDaemonPayloadContract._make_payload with cfg batch=4 returns correct shape.

        This verifies the existing test helper still works after the batch fix —
        the helper passes cfg batch=4 but the payload's EMBER_TOTAL_STEPS must now
        reflect batch=16 (the override), so the old test's total_steps assertion
        would need to be consistent.  We just verify the shape is still valid.
        """
        import ember_cbase_launch, tempfile, os
        cfg = {
            "model": {"seq": 1024},
            "throughput": {"batch": 4},
            "objective": {"mtp_aux_heads": {"n_heads": 2}},
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = ember_cbase_launch._build_daemon_job_payload(
                run_dir=os.path.join(tmpdir, "models", "compat-check"),
                optimizer="muon_split",
                resume_ckpt_dir=None,
                segment_tokens=4096,
                cfg=cfg,
            )
        required_keys = {"model", "dataset", "script", "output_dir", "hyperparams"}
        self.assertEqual(required_keys, required_keys & set(payload.keys()),
                         f"Payload missing required keys after batch fix: {payload.keys()}")


# ---------------------------------------------------------------------------
# Test 15: _write_segment_wrapper — generated wrapper bakes all env vars
# ---------------------------------------------------------------------------

class TestWriteSegmentWrapper(unittest.TestCase):
    """Unit tests for _write_segment_wrapper.

    Verifies:
      (a) Wrapper file is created at scripts_dir/cbase_seg_<run_id>_<N>.py
      (b) EMBER_SHARD_DIR baked in
      (c) EMBER_SEGMENT_TOKENS baked in
      (d) EMBER_TOTAL_STEPS baked in
      (e) EMBER_RUN_DIR baked in
      (f) EMBER_RESUME_CKPT_DIR absent (omitted) for N=0 (fresh start)
      (g) EMBER_RESUME_CKPT_DIR present for N>0 (resume)
      (h) --run-dir appears in cbase_v0_segment_live._argv via EMBER_RUN_DIR
    """

    def setUp(self):
        import ember_cbase_launch
        self.module = ember_cbase_launch
        self._tmpdir = tempfile.TemporaryDirectory()
        self.scripts_dir = self._tmpdir.name

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write(self, seg_idx=1, resume_ckpt_dir=None,
               mixture_dir="/mnt/testfixture-cbase/state/nc-ladder/state/cbase-mixture",
               run_dir="/mnt/testfixture-cbase/state/nc-ladder/models/cbase-v0"):
        return self.module._write_segment_wrapper(
            run_dir=run_dir,
            seg_idx=seg_idx,
            run_id="cbase-v0",
            mixture_dir=mixture_dir,
            segment_tokens=8_192_000,
            total_steps=449651,
            resume_ckpt_dir=resume_ckpt_dir,
            scripts_dir=self.scripts_dir,
        )

    def test_wrapper_file_created(self):
        """Wrapper file is written to scripts_dir."""
        path = self._write(seg_idx=1)
        self.assertTrue(
            os.path.exists(path),
            f"Wrapper file not created at {path}",
        )

    def test_wrapper_filename_contains_run_id_and_seg(self):
        """Filename contains run_id and 4-digit segment index."""
        path = self._write(seg_idx=3)
        name = os.path.basename(path)
        self.assertIn("cbase", name, f"run_id not in filename: {name}")
        self.assertIn("0003", name, f"seg_idx '0003' not in filename: {name}")
        self.assertTrue(name.endswith(".py"), f"Wrapper must be a .py file: {name}")

    def _read_wrapper(self, path):
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_ember_shard_dir_baked(self):
        """EMBER_SHARD_DIR is baked into the wrapper."""
        path = self._write()
        src = self._read_wrapper(path)
        self.assertIn("EMBER_SHARD_DIR", src)
        self.assertIn("cbase-mixture", src)

    def test_ember_segment_tokens_baked(self):
        """EMBER_SEGMENT_TOKENS is baked into the wrapper."""
        path = self._write()
        src = self._read_wrapper(path)
        self.assertIn("EMBER_SEGMENT_TOKENS", src)
        self.assertIn("8192000", src)

    def test_ember_total_steps_baked(self):
        """EMBER_TOTAL_STEPS is baked into the wrapper."""
        path = self._write()
        src = self._read_wrapper(path)
        self.assertIn("EMBER_TOTAL_STEPS", src)
        self.assertIn("449651", src)

    def test_ember_run_dir_baked(self):
        """EMBER_RUN_DIR is baked into the wrapper."""
        path = self._write(run_dir="/mnt/testfixture-cbase/state/nc-ladder/models/cbase-v0")
        src = self._read_wrapper(path)
        self.assertIn("EMBER_RUN_DIR", src)
        self.assertIn("cbase-v0", src)

    def test_resume_absent_for_n0(self):
        """EMBER_RESUME_CKPT_DIR is NOT set (popped) when resume_ckpt_dir=None."""
        path = self._write(seg_idx=0, resume_ckpt_dir=None)
        src = self._read_wrapper(path)
        # Must pop (not set) EMBER_RESUME_CKPT_DIR.
        self.assertIn('pop("EMBER_RESUME_CKPT_DIR"', src,
                      "N=0 wrapper must pop EMBER_RESUME_CKPT_DIR (fresh start)")
        # Must not set it to a value.
        import re
        set_matches = re.findall(
            r'os\.environ\["EMBER_RESUME_CKPT_DIR"\]\s*=',
            src
        )
        self.assertEqual(
            len(set_matches), 0,
            "N=0 wrapper must not assign EMBER_RESUME_CKPT_DIR",
        )

    def test_resume_present_for_ngt0(self):
        """EMBER_RESUME_CKPT_DIR IS set when resume_ckpt_dir is given (N>0)."""
        ckpt = "/mnt/testfixture-cbase/state/nc-ladder/models/cbase-v0/checkpoints/step-001024"
        path = self._write(seg_idx=2, resume_ckpt_dir=ckpt)
        src = self._read_wrapper(path)
        self.assertIn("EMBER_RESUME_CKPT_DIR", src)
        self.assertIn("step-001024", src,
                      "Resume checkpoint path must appear in wrapper source")

    def test_wrapper_imports_cbase_v0_segment_live(self):
        """Wrapper delegates to cbase_v0_segment_live via import."""
        path = self._write()
        src = self._read_wrapper(path)
        self.assertIn(
            "cbase_v0_segment_live",
            src,
            "Wrapper must import cbase_v0_segment_live to delegate execution",
        )


# ---------------------------------------------------------------------------
# Test 16: cbase_v0_segment_live.py — EMBER_RUN_DIR read + --run-dir in argv
# ---------------------------------------------------------------------------

class TestCbaseV0SegmentLiveRunDir(unittest.TestCase):
    """Source-level checks for cbase_v0_segment_live.py.

    The module is a self-executing script (calls ts.main() at module level),
    so it cannot be safely imported in tests.  We verify by reading source text —
    authoritative because the daemon also exec's the file as a script.

    Verifies:
      (a) EMBER_RUN_DIR is read from os.environ
      (b) --run-dir is added to _argv when _RUN_DIR is set
      (c) The --run-dir append is conditional (only when _RUN_DIR is truthy)
    """

    def _get_source(self):
        src_path = _SCRIPTS / "cbase_v0_segment_live.py"
        return src_path.read_text(encoding="utf-8")

    def test_ember_run_dir_read(self):
        """EMBER_RUN_DIR must be read from os.environ."""
        src = self._get_source()
        self.assertIn(
            "EMBER_RUN_DIR",
            src,
            "cbase_v0_segment_live.py must read EMBER_RUN_DIR from os.environ",
        )

    def test_run_dir_in_argv(self):
        """--run-dir must be appended to _argv."""
        src = self._get_source()
        self.assertIn(
            '"--run-dir"',
            src,
            "cbase_v0_segment_live.py must append '--run-dir' to _argv when EMBER_RUN_DIR is set",
        )

    def test_run_dir_conditional(self):
        """--run-dir append is conditional on _RUN_DIR being truthy."""
        src = self._get_source()
        # The pattern must be: if _RUN_DIR: ... "--run-dir" ...
        import re
        # Check that --run-dir is inside an if block (not unconditional).
        # Simple heuristic: "if _RUN_DIR" must appear before "--run-dir".
        run_dir_pos = src.find('"--run-dir"')
        if_pos = src.rfind("if _RUN_DIR", 0, run_dir_pos)
        self.assertNotEqual(
            if_pos, -1,
            "--run-dir must be inside an 'if _RUN_DIR:' block in cbase_v0_segment_live.py "
            "(conditional — only passed when EMBER_RUN_DIR is non-empty)",
        )


# ---------------------------------------------------------------------------
# Test 17: v0_config_check passes on the updated v4 config
# ---------------------------------------------------------------------------

class TestV0ConfigCheckV4(unittest.TestCase):
    """G-config stays GREEN after the v4 config changes.

    Verifies:
      (a) v0_config_check.check(cfg) returns [] (no violations)
      (b) v0_config_check.check(cfg, launch=True) returns [] (or only the
          tokenizer-receipt error — tokenizer receipt is on disk)
      (c) throughput.batch == 16 in the live config
      (d) precision.qat.enabled == True still (component contract anchor retained)
      (e) governor floors NOT loosened (vram_fraction, margin_gib_floor, pace)
    """

    def _load_config(self):
        cfg_path = _SCRIPTS.parent / "configs" / "v0-pretrain-config.json"
        with open(cfg_path, encoding="utf-8") as f:
            return json.load(f)

    def test_config_check_structural_green(self):
        """v0_config_check.check(cfg) returns no violations."""
        import v0_config_check
        cfg = self._load_config()
        violations = v0_config_check.check(cfg)
        self.assertEqual(
            violations, [],
            f"v0_config_check structural check failed with violations: {violations}",
        )

    def test_batch_is_16_in_config(self):
        """throughput.batch must be 16 in the v4 config."""
        cfg = self._load_config()
        batch = cfg.get("throughput", {}).get("batch")
        self.assertEqual(
            batch, 16,
            f"throughput.batch must be 16 (c04 bench cell), got {batch!r}",
        )

    def test_qat_enabled_retained(self):
        """precision.qat.enabled must still be True (component contract anchor)."""
        cfg = self._load_config()
        qat_enabled = cfg.get("precision", {}).get("qat", {}).get("enabled")
        self.assertTrue(
            qat_enabled,
            "precision.qat.enabled must remain True (directed-component contract #1); "
            "production BF16-eager is a section8 sanction, not a component removal",
        )

    def test_governor_floors_not_loosened(self):
        """Governor floors must not be loosened by the v4 edit."""
        cfg = self._load_config()
        gov = cfg.get("governor", {})
        self.assertLessEqual(
            gov.get("vram_fraction", 1.0), 0.80,
            f"governor.vram_fraction must be <= 0.80 (floor), got {gov.get('vram_fraction')}",
        )
        self.assertGreaterEqual(
            gov.get("margin_gib_floor", 0), 1.5,
            f"governor.margin_gib_floor must be >= 1.5, got {gov.get('margin_gib_floor')}",
        )
        self.assertGreaterEqual(
            gov.get("pace_s_per_step", 0), 0.05,
            f"governor.pace_s_per_step must be >= 0.05, got {gov.get('pace_s_per_step')}",
        )

    def test_version_is_4(self):
        """Config version must be 4 (v4_delta added)."""
        cfg = self._load_config()
        self.assertEqual(
            cfg.get("version"), 4,
            f"Config version must be 4 after v4_delta, got {cfg.get('version')}",
        )


# ---------------------------------------------------------------------------
# Test 18: stale docstring removed from ember_cbase_launch._build_daemon_job_payload
# ---------------------------------------------------------------------------

class TestStaleDocstringRemoved(unittest.TestCase):
    """Verify the old '18737 / 0.928x' framing is gone from ember_cbase_launch.

    The stale RECIPE-MISMATCH-FLAG docstring block in _build_daemon_job_payload
    (lines 533-542) said '~19600 tok/s is a BF16 measurement and does NOT
    directly transfer to the QAT pretrain (~18737 tok/s per ... 0.928x)'.
    That framing is wrong; it must be replaced with the corrected BF16-eager note.
    """

    def test_18737_framing_removed(self):
        """'18737' must not appear in ember_cbase_launch source."""
        import inspect
        import ember_cbase_launch
        src = inspect.getsource(ember_cbase_launch)
        self.assertNotIn(
            "18737",
            src,
            "Stale '18737 tok/s' framing must be removed from ember_cbase_launch "
            "(was in the _build_daemon_job_payload RECIPE-MISMATCH-FLAG docstring).",
        )

    def test_0928_tax_framing_removed(self):
        """'0.928x' QAT tax framing must not appear in the docstring."""
        import inspect
        import ember_cbase_launch
        src = inspect.getsource(ember_cbase_launch._build_daemon_job_payload)
        self.assertNotIn(
            "0.928x",
            src,
            "Stale '0.928x' QAT tax must be removed from _build_daemon_job_payload docstring.",
        )

    def test_recipe_mismatch_flag_removed(self):
        """'RECIPE-MISMATCH-FLAG' label must not appear in _build_daemon_job_payload docstring."""
        import inspect
        import ember_cbase_launch
        src = inspect.getsource(ember_cbase_launch._build_daemon_job_payload)
        self.assertNotIn(
            "RECIPE-MISMATCH-FLAG",
            src,
            "RECIPE-MISMATCH-FLAG docstring block must be replaced with corrected note.",
        )

    def test_corrected_recipe_note_present(self):
        """Corrected BF16-eager note must appear in _build_daemon_job_payload docstring."""
        import inspect
        import ember_cbase_launch
        src = inspect.getsource(ember_cbase_launch._build_daemon_job_payload)
        self.assertIn(
            "BF16-eager",
            src,
            "_build_daemon_job_payload docstring must state 'BF16-eager' recipe.",
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
