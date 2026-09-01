# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Regression test for #406: cbase_grow_live._function_preservation_check
SIGSEGVs at real rung-2 scale (pre-grow ~1.19B + post-grow ~2.2B params held
resident simultaneously, uncollected). The fix bounds peak residency to one
model at a time (release pre_model before building post_model).

This test cannot reproduce a 3.4B-param combined residency in CI, so it
reproduces the CRASH SHAPE at reduced scale: it proves, via a weakref on the
pre-grow model, that pre_model is actually garbage-collected (refcount drops
to zero, no dangling resident copy) BEFORE post_model is constructed. That
is exactly the invariant the fix establishes and the segfault violated
(two full models simultaneously resident+uncollected). It also re-checks
the function's own math is unchanged (same tolerance, same comparison set,
still passes) so the memory fix did not alter the deterministic proof.

NOTE on module reachability (see PR body / issue #406 closing comment for
the full finding): scripts/timeshare_pretrain.py was locked to
EMBER_ARTIFACT_CLASS=historical_only (unconditional `raise SystemExit(...)`
at import time) by 4f758db "fix: lock Ember authority and totality"
(2026-07-12), four days after this issue was filed. cbase_grow_live.py does
`import timeshare_pretrain as ts` at module scope (line 84), so as of that
commit `import cbase_grow_live` itself unconditionally raises SystemExit
before ANY code in this file — including _function_preservation_check —
can execute, through any real entrypoint. The SIGSEGV this issue reports is
therefore no longer reachable in production; the fix below restores the
documented invariant anyway (defensive correctness for the frozen file) and
this test exercises the isolated function directly by stubbing the
timeshare_pretrain import (a pure test-isolation substitution — it does not
touch, weaken, or bypass the real historical_only guard file, which is never
executed here or in production).
"""
from __future__ import annotations

import gc
import importlib.util
import sys
import types
import unittest
import weakref
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# cbase_grow_live.py's only use of `import timeshare_pretrain as ts` is inside
# _run() (a live-training entrypoint this test never calls); the module-level
# import exists purely so `ts.run_v0_segment` etc. resolve at call time. Stub
# it so the frozen historical_only file (never executed here) doesn't need to
# be imported just to load this one already-dead-in-production function for
# testing.
_STUB = types.ModuleType("timeshare_pretrain")
_STUB.__file__ = str(
    Path(__file__).resolve().parents[4] / "scripts" / "timeshare_pretrain.py"
)
sys.modules.setdefault("timeshare_pretrain", _STUB)

SPEC = importlib.util.spec_from_file_location("cbase_grow_live", SCRIPTS / "cbase_grow_live.py")
assert SPEC is not None and SPEC.loader is not None
live_mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(live_mod)
for _alias in (
    "timeshare_pretrain",
    "scripts.timeshare_pretrain",
    "_ember_issue2015_d9c5c82c124e1dc8",
):
    if sys.modules.get(_alias) is _STUB:
        del sys.modules[_alias]

import torch  # noqa: E402
from cbase_grow_dryrun import widen_state_dict  # noqa: E402


def _tiny_cfg() -> dict:
    return {
        "vocab": 64, "hidden": 16, "layers": 1, "heads": 2, "seq": 8,
        "tied_embeddings": False,
    }


class FunctionPreservationCheckMemoryTests(unittest.TestCase):
    def test_pre_model_released_before_post_model_built(self) -> None:
        """The crash shape: pre_model must be dead (weakref cleared) before
        the post-grow model is constructed. Patches dryrun_build_model
        (as bound in cbase_grow_live's namespace) to assert this ordering
        on the SECOND call (post-grow build)."""
        cfg = _tiny_cfg()
        n_mtp = 1
        ff_seed = 8
        ff_grown = ff_seed * 2

        pre_model = live_mod.dryrun_build_model(cfg, n_mtp, ff_seed)
        sd_pre = pre_model.state_dict()
        sd_post = widen_state_dict(dict(sd_pre), n_layers=cfg["layers"])
        del pre_model

        real_build = live_mod.dryrun_build_model
        state = {"calls": 0, "pre_weakref": None}

        def tracking_build(cfg_model, n_mtp_, intermediate):
            state["calls"] += 1
            model = real_build(cfg_model, n_mtp_, intermediate)
            if state["calls"] == 1:
                state["pre_weakref"] = weakref.ref(model)
            elif state["calls"] == 2:
                gc.collect()
                self.assertIsNotNone(state["pre_weakref"])
                self.assertIsNone(
                    state["pre_weakref"](),
                    "pre-grow model still resident when post-grow model build "
                    "started — this is the #406 crash shape (both models "
                    "simultaneously resident, uncollected)",
                )
            return model

        live_mod.dryrun_build_model = tracking_build
        try:
            result = live_mod._function_preservation_check(
                cfg, n_mtp, sd_pre, sd_post, ff_seed, ff_grown)
        finally:
            live_mod.dryrun_build_model = real_build

        self.assertEqual(state["calls"], 2)
        self.assertTrue(result["function_preserving"], result)
        self.assertLessEqual(result["logit_max_abs_diff"], live_mod.PASS_TOL)


if __name__ == "__main__":
    unittest.main()
