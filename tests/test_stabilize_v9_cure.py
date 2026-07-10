"""test_stabilize_v9_cure.py — ember #627 stabilize v9 cure, reproduce-first.

Each audit ground the issue cites is a test here; every test is a FAILING test
against pre-cure source (reproduce-first) and passes after the cure. CPU-only:
small tensors / tiny CPU dry-runs / mocks. NEVER touches the GPU, NEVER starts a
training process, NEVER runs the pace-smoke on GPU.

Coverage (spec's 7 points):
  1. R2  in-process commit read (no subprocess in the step path)
  2. R3  shadow-grad persistence through zero_grad
  3. counters (grad_lazy_creates, governor_reads) + POSITIVE CONTROL
  4. R4  in-run 27-min pace gate (watchdog + cooperative clean self-abort)
  5. two-consecutive-step identity + Newton-Schulz heap-backed assert (+ guard control)
  6. AC2 pace-smoke banked (CPU precheck passes; GPU execution gated, never runs here)
  7. lineage pin block-04 step-806 (fail-closed on silent rollback)
"""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import torch  # noqa: E402
import timeshare_pretrain as ts       # noqa: E402
import cpu_offload_adamw as coa        # noqa: E402
import cbase_grow_rung2_stabilize as stab  # noqa: E402

# Importing the leg runner applies its module-level monkeypatches to ts/coa
# (frontload, governed memmap, stage-marker/shard-loader/governor wrappers).
# Restore the PRISTINE base callables so these unit tests exercise the base
# classes deterministically (no governor SystemExit risk, no repo-dir memmap
# cache writes). All _ORIG_* names pre-exist in the runner (pre- and post-cure),
# so this block is safe to collect against pre-cure source too.
coa.CPUOffloadOptimizer.__init__ = stab._ORIG_CPU_OFFLOAD_INIT
coa._memmap_zeros = stab._ORIG_MEMMAP_ZEROS
ts.PackedShardLoader.__init__ = stab._ORIG_PACKED_SHARD_LOADER_INIT
ts._apply_governor = stab._ORIG_APPLY_GOVERNOR
torch.nn.Module.load_state_dict = stab._ORIG_LOAD_STATE_DICT


# ---- helpers (reference cure symbols only when CALLED, so pre-cure collects) --

def _storage_ptr(t):
    try:
        return t.untyped_storage().data_ptr()
    except Exception:
        return t.storage().data_ptr()


def _memmap_ptrs(opt):
    """Storage pointers of every file-backed (memmap) tensor the optimizer holds."""
    ptrs = set()
    for sp in opt._shadow:
        ptrs.add(_storage_ptr(sp))
        if sp.grad is not None:
            ptrs.add(_storage_ptr(sp.grad))
    for st in opt._inner.state.values():
        for v in st.values():
            if torch.is_tensor(v):
                ptrs.add(_storage_ptr(v))
    return ptrs


def _is_heap(G, mmap_ptrs):
    """A tensor is heap-backed iff it shares storage with NO memmap tensor."""
    return _storage_ptr(G) not in mmap_ptrs


def _make_offload_muon_opt(optstate_dir, shape=(8, 16)):
    Muon = ts._muon_class()
    real_p = torch.nn.Parameter(torch.randn(*shape))
    opt = coa.CPUOffloadOptimizer(
        [("w", real_p)], lambda ps: Muon(ps, lr=0.02), optstate_dir=optstate_dir)
    return real_p, opt


def _make_tiny_shard(tmp):
    import numpy as np
    shard = os.path.join(tmp, "shards")
    os.makedirs(shard)
    rng = np.random.default_rng(7)
    toks = rng.integers(1, 64, size=4000, dtype=np.int64)
    toks[::24] = 0
    ts.write_packed_shard(os.path.join(shard, "s-00000.bin"),
                          toks.astype(np.uint16).tolist())
    return shard


class _Base(unittest.TestCase):
    def setUp(self):
        # Reset process-global counters between tests (no-op on pre-cure source).
        if hasattr(coa, "reset_counters"):
            coa.reset_counters()
        if hasattr(stab, "reset_governor_reads"):
            stab.reset_governor_reads()
        self._tmp = tempfile.mkdtemp(prefix="v9cure_test_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Point 1 — R2: in-process commit read, no subprocess in the step path
# ---------------------------------------------------------------------------
class TestR2InProcessCommitRead(_Base):
    def test_read_commit_gb_spawns_no_subprocess(self):
        # Spy (not raise): a raised subprocess error is swallowed by the read's
        # never-raises contract, so a raising stub cannot discriminate. Count the
        # calls instead. Pre-cure (powershell) => calls>0; post-cure (ctypes) => 0.
        import subprocess

        class _CP:
            returncode = 0
            stdout = "1.0,2.0"  # parseable by the pre-cure powershell path
            stderr = ""

        calls = {"n": 0}
        orig_run, orig_popen = subprocess.run, subprocess.Popen

        def _spy_run(*a, **k):
            calls["n"] += 1
            return _CP()

        def _spy_popen(*a, **k):
            calls["n"] += 1
            raise AssertionError("Popen in commit read")

        subprocess.run = _spy_run
        subprocess.Popen = _spy_popen
        try:
            r = stab._read_commit_gb()
        finally:
            subprocess.run, subprocess.Popen = orig_run, orig_popen
        self.assertEqual(calls["n"], 0, "R2: commit read must spawn NO subprocess")
        # Windows-native: returns the 3-key commit dict; elsewhere None.
        self.assertTrue(r is None or set(r) == {"committed_gb", "limit_gb", "free_gb"}, r)
        if r is not None:
            self.assertAlmostEqual(r["committed_gb"] + r["free_gb"], r["limit_gb"], places=1)

    def test_same_measurement_invariant_one_read_per_marker(self):
        # _stage_marker takes ONE commit read and hands it to the governor, so the
        # printed committed_gb and the governor's pass/fail decision are the SAME
        # measurement. Exactly one governor_read per stage marker proves it.
        stab.reset_governor_reads()
        stab._stage_marker("v9cure_same_measurement")
        self.assertEqual(stab.get_governor_reads(), 1)


# ---------------------------------------------------------------------------
# Point 2 — R3: shadow-grad persistence through zero_grad(set_to_none=True)
# ---------------------------------------------------------------------------
class TestR3ShadowGradPersistence(_Base):
    def test_zero_grad_preserves_shadow_grad_and_frees_real(self):
        real_p, opt = _make_offload_muon_opt(self._tmp)
        real_p.grad = torch.randn(8, 16)
        opt.step()
        shadow = opt._shadow[0]
        self.assertIsNotNone(shadow.grad, "shadow grad should exist after step 1")
        gid = id(shadow.grad)
        opt.zero_grad(set_to_none=True)
        # Real (GPU) grad IS freed — the VRAM contract is preserved.
        self.assertIsNone(real_p.grad)
        # Shadow (file-backed) grad PERSISTS with stable identity (R3).
        self.assertIsNotNone(shadow.grad, "R3: zero_grad must not tear down shadow grad")
        self.assertEqual(id(shadow.grad), gid, "R3: shadow grad object identity must be stable")


# ---------------------------------------------------------------------------
# Point 3 — counters + POSITIVE CONTROL
# ---------------------------------------------------------------------------
class TestCountersPositiveControl(_Base):
    def test_grad_lazy_creates_positive_control(self):
        # Deliberately trigger the failure the counter guards (a lazy re-create)
        # and assert the counter FIRES — proving it can detect the M1 regression,
        # never vacuously green.
        coa.reset_counters()
        real_p, opt = _make_offload_muon_opt(self._tmp)
        real_p.grad = torch.randn(8, 16)
        opt.step()  # first step lazily creates the grad memmap (base class)
        self.assertGreaterEqual(coa.get_counter("grad_lazy_creates"), 1)
        before = coa.get_counter("grad_lazy_creates")
        # Simulate the pre-cure zero_grad teardown, then step: a re-create MUST fire.
        opt._shadow[0].grad = None
        real_p.grad = torch.randn(8, 16)
        opt.step()
        self.assertEqual(coa.get_counter("grad_lazy_creates"), before + 1,
                         "counter failed to detect a forced lazy re-create")
        self.assertEqual(opt.grad_lazy_creates, coa.get_counter("grad_lazy_creates"),
                         "instance mirror and module counter disagree")

    def test_governor_reads_positive_control(self):
        stab.reset_governor_reads()
        for _ in range(5):
            stab._read_commit_gb()
        self.assertEqual(stab.get_governor_reads(), 5,
                         "governor_reads must count every commit read (falsifiable in the log)")


# ---------------------------------------------------------------------------
# Point 5 — two-consecutive-step identity + Newton-Schulz heap-backed assert
# ---------------------------------------------------------------------------
class TestTwoStepIdentityAndNSHeap(_Base):
    def test_identity_stable_and_ns_inputs_heap_backed(self):
        real_p, opt = _make_offload_muon_opt(self._tmp, shape=(8, 16))
        # Front-load the grad memmap (production wiring) so step 1 has 0 lazy creates.
        stem = opt._optstate_dir / coa._sanitize_name("w")
        opt._shadow[0].grad = coa._memmap_zeros(Path(str(stem) + ".grad.f32"), (8, 16))
        coa.reset_counters()

        mmap_ptrs = _memmap_ptrs(opt)
        ns_inputs_heap = []
        orig_ns = ts._zeropower_via_newtonschulz5

        def _ns_probe(G, steps=5, eps=1e-7):
            ns_inputs_heap.append(_is_heap(G, mmap_ptrs))
            return orig_ns(G, steps=steps, eps=eps)

        ts._zeropower_via_newtonschulz5 = _ns_probe
        try:
            real_p.grad = torch.randn(8, 16)
            opt.step()
            self.assertEqual(coa.get_counter("grad_lazy_creates"), 0,
                             "front-loaded grad must not lazy-create on step 1")
            gid = id(opt._shadow[0].grad)
            opt.zero_grad(set_to_none=True)
            real_p.grad = torch.randn(8, 16)
            opt.step()
            self.assertEqual(id(opt._shadow[0].grad), gid,
                             "shadow grad identity must be stable across steps")
            self.assertEqual(coa.get_counter("grad_lazy_creates"), 0,
                             "grad_lazy_creates must be 0 across two consecutive cured steps")
        finally:
            ts._zeropower_via_newtonschulz5 = orig_ns

        self.assertGreaterEqual(len(ns_inputs_heap), 2, "NS must run each step")
        self.assertTrue(all(ns_inputs_heap),
                        "Newton-Schulz input was memmap-backed (file-backed), not heap — "
                        "the v8 dominant crawl term")

    def test_ns_heap_guard_catches_memmap_input(self):
        # Positive control for the heap guard: it must flag a memmap tensor as
        # NOT heap-backed (else the point-5 assert could pass vacuously).
        real_p, opt = _make_offload_muon_opt(self._tmp, shape=(8, 16))
        mmap_ptrs = _memmap_ptrs(opt)
        self.assertFalse(_is_heap(opt._shadow[0], mmap_ptrs),
                         "guard must catch a memmap-backed tensor")
        self.assertTrue(_is_heap(torch.randn(8, 16), mmap_ptrs),
                        "guard must accept a fresh heap tensor")


# ---------------------------------------------------------------------------
# Point 4 — R4: in-run pace gate (cooperative abort + watchdog)
# ---------------------------------------------------------------------------
class TestR4PaceGateCooperativeAbort(_Base):
    def _tiny_dims(self):
        return {"vocab": 64, "hidden": 32, "depth": 2, "seq": 8}

    def test_run_v0_segment_aborts_when_event_preset(self):
        # abort_event pre-set -> breaks at the top of local_step=0, zero steps run.
        ev = threading.Event()
        ev.set()
        shard = _make_tiny_shard(self._tmp)
        cfg = ts.load_contract()
        rec = ts.run_v0_segment(
            os.path.join(self._tmp, "run0"), cfg, n_steps=5, total_steps=7,
            checkpoint_every=5, pace_s=0.0, shard_dir=shard,
            tiny_dims=self._tiny_dims(), batch_size=2, ce_chunk_tokens=8,
            abort_event=ev)
        self.assertTrue(rec["aborted_by_pace_gate"])
        self.assertEqual(len(rec["losses"]), 0)

    def test_run_v0_segment_checkpoints_completed_steps_on_midrun_abort(self):
        # Event flips True after 2 is_set() checks -> steps 0,1 run, abort at step 2,
        # completed work is checkpointed (clean self-abort, not force-kill).
        class _FlipEvent:
            def __init__(self, k):
                self.k, self.n = k, 0

            def is_set(self):
                self.n += 1
                return self.n > self.k

        shard = _make_tiny_shard(self._tmp)
        cfg = ts.load_contract()
        rec = ts.run_v0_segment(
            os.path.join(self._tmp, "runk"), cfg, n_steps=5, total_steps=7,
            checkpoint_every=5, pace_s=0.0, shard_dir=shard,
            tiny_dims=self._tiny_dims(), batch_size=2, ce_chunk_tokens=8,
            abort_event=_FlipEvent(2))
        self.assertTrue(rec["aborted_by_pace_gate"])
        self.assertEqual(len(rec["losses"]), 2, "exactly the completed steps")
        self.assertIsNotNone(rec["last_checkpoint"], "completed work must be checkpointed on abort")
        self.assertTrue(os.path.isdir(rec["last_checkpoint"]))

    def test_run_v0_segment_no_abort_when_event_none(self):
        # Default (no pace gate): full run, no behavior change.
        shard = _make_tiny_shard(self._tmp)
        cfg = ts.load_contract()
        rec = ts.run_v0_segment(
            os.path.join(self._tmp, "runfull"), cfg, n_steps=3, total_steps=7,
            checkpoint_every=3, pace_s=0.0, shard_dir=shard,
            tiny_dims=self._tiny_dims(), batch_size=2, ce_chunk_tokens=8)
        self.assertFalse(rec["aborted_by_pace_gate"])
        self.assertEqual(len(rec["losses"]), 3)


class TestR4WatchdogInRunBlock(_Base):
    """The named defect: _run_block computed wall_s only AFTER run_v0_segment
    returned, so no in-run gate could fire on a block that never returns. The
    watchdog + cooperative abort_event is that gate. Tested on the REAL
    _run_block with a CPU fake block (no GPU, no training)."""

    def _neutralize_telemetry(self):
        self._saved = (stab._stage_marker, stab.nvidia_smi_vram,
                       stab._nvidia_smi_power_watts, stab.momentum_norm_by_group)
        stab._stage_marker = lambda label: None
        stab.nvidia_smi_vram = lambda: {"used_gib": 0.0, "free_gib": 0.0, "total_gib": 0.0}
        stab._nvidia_smi_power_watts = lambda: None
        stab.momentum_norm_by_group = lambda _c: {"note": "test"}

    def _restore_telemetry(self):
        (stab._stage_marker, stab.nvidia_smi_vram,
         stab._nvidia_smi_power_watts, stab.momentum_norm_by_group) = self._saved

    def test_watchdog_fires_and_aborts_slow_block_cleanly(self):
        orig = ts.run_v0_segment
        self._neutralize_telemetry()
        observed = {"abort": False}

        def _slow(run_dir, cfg, *, n_steps, abort_event=None, **k):
            deadline = time.monotonic() + 20.0
            ckpt = os.path.join(run_dir, "checkpoints", "step-00000811")
            while time.monotonic() < deadline:
                if abort_event is not None and abort_event.is_set():
                    observed["abort"] = True
                    os.makedirs(ckpt, exist_ok=True)
                    with open(os.path.join(ckpt, "manifest.json"), "w",
                              encoding="utf-8", newline="\n") as f:
                        json.dump({"step": 811}, f)
                    return {"losses": [12.1], "loss_first": 12.1, "loss_last": 12.1,
                            "global_step_end": 811, "last_checkpoint": ckpt,
                            "aborted_by_pace_gate": True}
                time.sleep(0.02)
            return {"losses": [12.1], "loss_first": 12.1, "loss_last": 12.1,
                    "global_step_end": 900, "last_checkpoint": ckpt,
                    "aborted_by_pace_gate": False}

        ts.run_v0_segment = _slow
        try:
            t0 = time.monotonic()
            br, _ = stab._run_block(
                {"model": {"seq": 1024}}, os.path.join(self._tmp, "b05"), self._tmp,
                global_step_start=806, total_steps=1000, shard_dir=self._tmp,
                grad_accum_steps=1, block_idx=5, sample_interval_s=0.05,
                pace_gate_s=0.3)
            elapsed = time.monotonic() - t0
        finally:
            ts.run_v0_segment = orig
            self._restore_telemetry()

        self.assertTrue(br["pace_gate"]["armed"])
        self.assertTrue(br["pace_gate"]["aborted"], "watchdog must abort a slow block")
        self.assertTrue(observed["abort"], "block must observe the cooperative abort")
        self.assertLess(elapsed, 15.0, "abort must fire MID-block, not after it returns")
        self.assertTrue(br["checkpoint"] and os.path.isdir(br["checkpoint"]))

    def test_watchdog_does_not_fire_on_fast_block(self):
        orig = ts.run_v0_segment
        self._neutralize_telemetry()

        def _fast(run_dir, cfg, *, n_steps, abort_event=None, **k):
            ckpt = os.path.join(run_dir, "checkpoints", "step-00000816")
            os.makedirs(ckpt, exist_ok=True)
            with open(os.path.join(ckpt, "manifest.json"), "w",
                      encoding="utf-8", newline="\n") as f:
                json.dump({"step": 816}, f)
            return {"losses": [12.0], "loss_first": 12.0, "loss_last": 12.0,
                    "global_step_end": 816, "last_checkpoint": ckpt,
                    "aborted_by_pace_gate": False}

        ts.run_v0_segment = _fast
        try:
            br, _ = stab._run_block(
                {"model": {"seq": 1024}}, os.path.join(self._tmp, "b06"), self._tmp,
                global_step_start=806, total_steps=1000, shard_dir=self._tmp,
                grad_accum_steps=1, block_idx=6, sample_interval_s=0.05,
                pace_gate_s=5.0)
        finally:
            ts.run_v0_segment = orig
            self._restore_telemetry()
        self.assertFalse(br["pace_gate"]["aborted"], "a fast block must not be aborted")


# ---------------------------------------------------------------------------
# Point 7 — lineage pin: block-04 step-806
# ---------------------------------------------------------------------------
class TestLineagePin(_Base):
    def test_pin_passes_at_806(self):
        r = stab.assert_lineage_resume(806, stab.LINEAGE_LEG_START_BLOCK)
        self.assertTrue(r["lineage_pinned"])
        self.assertEqual(r["verdict"], "LINEAGE_OK")

    def test_pin_fails_closed_on_silent_rollback_to_block3_step796(self):
        with self.assertRaises(stab.LineageResumeMismatch):
            stab.assert_lineage_resume(796, stab.LINEAGE_LEG_START_BLOCK)

    def test_declared_dated_deviation_is_allowed(self):
        r = stab.assert_lineage_resume(
            796, stab.LINEAGE_LEG_START_BLOCK,
            deviation="2026-07-10: block-04 ckpt failed reverify; resume block-3 per coordinator")
        self.assertEqual(r["verdict"], "LINEAGE_DEVIATION_DECLARED")

    def test_not_pinned_off_the_frozen_leg_boundary(self):
        r = stab.assert_lineage_resume(500, 1)  # a fresh blocks-1-N run, unpinned
        self.assertFalse(r["lineage_pinned"])
        self.assertEqual(r["verdict"], "LINEAGE_OK")

    # -- #665 audit negative controls: malformed/impossible deviation dates
    # must fail closed, not be silently accepted as a declared deviation.
    def test_deviation_without_any_date_prefix_fails_closed(self):
        with self.assertRaises(stab.LineageResumeMismatch):
            stab.assert_lineage_resume(796, stab.LINEAGE_LEG_START_BLOCK, deviation="x")

    def test_deviation_with_non_date_prefix_fails_closed(self):
        with self.assertRaises(stab.LineageResumeMismatch):
            stab.assert_lineage_resume(
                796, stab.LINEAGE_LEG_START_BLOCK, deviation="not-a-date")

    def test_deviation_with_impossible_calendar_date_fails_closed(self):
        with self.assertRaises(stab.LineageResumeMismatch):
            stab.assert_lineage_resume(
                796, stab.LINEAGE_LEG_START_BLOCK, deviation="2026-99-99 nonsense")


# ---------------------------------------------------------------------------
# Point 6 — AC2 pace-smoke: banked, CPU-precheckable, GPU execution gated
# ---------------------------------------------------------------------------
class TestPaceSmokeBanked(_Base):
    def _import_ps(self):
        import cbase_grow_rung2_stabilize_pace_smoke as ps
        return ps

    def test_cpu_precheck_passes_no_gpu(self):
        ps = self._import_ps()
        res = ps.cpu_precheck()
        self.assertTrue(res["all_pass"], res)
        self.assertEqual(res["verdict"], "PACE_SMOKE_CPU_PRECHECK_PASS")
        self.assertEqual(res["deadline_s_real_leg"], stab.PACE_GATE_S)

    def test_default_mode_runs_nothing_on_gpu(self):
        ps = self._import_ps()
        rc = ps.main([])  # no mode flag -> prints invocation, exits 3, no GPU
        self.assertEqual(rc, 3)

    def test_gpu_go_refused_without_authorization(self):
        ps = self._import_ps()
        saved = os.environ.pop("EMBER_GATE_AUTHORIZED", None)
        try:
            rc = ps.main(["--confirm-gpu-go"])  # no auth -> refused before any GPU launch
            self.assertEqual(rc, 2)
        finally:
            if saved is not None:
                os.environ["EMBER_GATE_AUTHORIZED"] = saved


# ---------------------------------------------------------------------------
# #637 review cure — composed zero-step pace-gate abort (A1 + A2)
# ---------------------------------------------------------------------------
class TestZeroStepAbortComposed(_Base):
    """The review's composed path: watchdog fires during the SETUP phase (the
    v7 measured failure mode), run_v0_segment returns REAL losses=[] from its
    own abort branch (not a stubbed dict), and the runner must still emit the
    COUNTERS line, the block receipt, and the final-leg receipt, exiting via
    the clean ABORTED/exit-3 path with honest step counts. Drives the REAL
    stab.main() end to end; only telemetry is neutralized and run_v0_segment's
    launch args are redirected to the CPU dry-run harness (the segment CODE
    that produces the empty receipt is the real one). CPU-only."""

    def test_zero_step_abort_receipts_honest_no_crash(self):
        import contextlib
        import glob
        import io

        # -- fabricate the minimal on-disk inputs main() reads --------------
        seed = os.path.join(self._tmp, "seed-ckpt")
        override = os.path.join(self._tmp, "override-ckpt")
        out_dir = os.path.join(self._tmp, "out")
        rec_dir = os.path.join(self._tmp, "receipts")
        os.makedirs(seed)
        os.makedirs(override)
        with open(os.path.join(seed, "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump({"step": 806, "extra": {"total_steps": 1000}}, f)
        with open(os.path.join(override, "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump({"step": 806}, f)
        torch.save({"w": torch.zeros(4, 4)}, os.path.join(override, "model.pt"))
        shard = _make_tiny_shard(self._tmp)
        tiny = {"vocab": 64, "hidden": 32, "depth": 2, "seq": 8}

        orig_run_v0 = ts.run_v0_segment
        orig_pace_gate_s = stab.PACE_GATE_S
        orig_nvsmi = stab.nvidia_smi_vram
        orig_power = stab._nvidia_smi_power_watts
        orig_marker = stab._stage_marker
        orig_argv = sys.argv
        saved_env = os.environ.get("EMBER_GATE_AUTHORIZED")

        def _real_cpu_segment(run_dir, cfg, **kwargs):
            # Redirect the launch args to the CPU dry-run harness, wait until
            # the watchdog has ALREADY fired (deterministic setup-phase abort),
            # then run the REAL segment: its own abort branch produces the
            # genuine losses=[] receipt this test is about.
            ev = kwargs["abort_event"]
            self.assertTrue(ev.wait(10), "pace watchdog never fired")
            return orig_run_v0(
                run_dir, cfg, n_steps=5, total_steps=7, checkpoint_every=5,
                pace_s=0.0, shard_dir=shard, tiny_dims=tiny, batch_size=2,
                ce_chunk_tokens=8, abort_event=ev)

        try:
            ts.run_v0_segment = _real_cpu_segment
            stab.PACE_GATE_S = 0.05  # setup phase alone outlasts the deadline
            stab.nvidia_smi_vram = lambda: {"total_mib": 24564, "used_mib": 0,
                                            "free_mib": 24467, "total_gib": 23.988,
                                            "used_gib": 0.0, "free_gib": 23.893}
            stab._nvidia_smi_power_watts = lambda: None
            stab._stage_marker = lambda label: None
            sys.argv = ["cbase_grow_rung2_stabilize.py",
                        "--seed-ckpt", seed, "--shard-dir", shard,
                        "--resume-ckpt-dir-override", override,
                        "--out-dir", out_dir, "--receipt-dir", rec_dir,
                        "--start-block", "5", "--n-blocks", "5"]
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = stab.main()  # A1 pre-cure: ZeroDivisionError crashes here
            log = buf.getvalue()
        finally:
            ts.run_v0_segment = orig_run_v0
            stab.PACE_GATE_S = orig_pace_gate_s
            stab.nvidia_smi_vram = orig_nvsmi
            stab._nvidia_smi_power_watts = orig_power
            stab._stage_marker = orig_marker
            sys.argv = orig_argv
            if saved_env is None:
                os.environ.pop("EMBER_GATE_AUTHORIZED", None)
            else:
                os.environ["EMBER_GATE_AUTHORIZED"] = saved_env

        # clean ABORTED/exit-3 path, never a traceback
        self.assertEqual(rc, 3)
        self.assertIn("PACE_GATE_ABORT block05", log)
        self.assertIn("COUNTERS block05", log)
        self.assertIn("pace_gate_aborted=True", log)
        self.assertIn("CBASE_GROW_RUNG2_STABILIZE_LEG1_ABORTED", log)

        # final-leg receipt written, honest step counts
        finals = [p for p in glob.glob(os.path.join(rec_dir, "cbase-grow-rung2-stabilize-leg1-*.json"))
                  if "REFUSED" not in os.path.basename(p)]
        self.assertEqual(len(finals), 1, finals)
        with open(finals[0], encoding="utf-8") as f:
            final = json.load(f)
        self.assertEqual(final["verdict"], "ABORTED")
        self.assertIn("r4_pace_gate", final["abort_reason"])
        self.assertEqual(final["steps_completed"], 0,
                         "an aborted zero-step block must not count as 10 steps (A2)")
        br = final["block_receipts"][0]
        self.assertEqual(br["n_steps_completed"], 0)
        self.assertIsNone(br["loss_mean"])
        self.assertIsNone(br["s_per_step"])
        self.assertTrue(br["pace_gate"]["aborted"])
        # A2: the segment receipt cites the step actually REACHED (resume_step +
        # len(losses) == 0 for the fresh zero-step CPU segment), never
        # resume_step + n_steps (which would read 5 here).
        self.assertEqual(br["global_step_end"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
