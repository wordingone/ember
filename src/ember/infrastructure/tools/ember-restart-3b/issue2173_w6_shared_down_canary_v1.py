#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Issue #2173 (W6): paired matched-loss canary for the FP8 shared down site class.

The #2081 position-robust procedure is reused unchanged (eight position-balanced pairs,
excluded post-switch update, warm windows, boundary sync, measured window). What moves is
the ARM SWITCH: the base harness alternates arms by swapping ``SharedAttention.forward``
between two source heads; W6 binds both heads to the SAME rebased head and alternates the
forward kernel at the 14 installed ``layers.{i}.shared_ffn.down`` sites instead
(``control`` -> ``bf16`` = ``F.linear`` on the BF16 master weight, the original module
computation; ``treatment`` -> ``fp8`` = ``torch._scaled_mm``). Control and treatment share
one process, one model state per pair (the base snapshot/restore), one seed and cursor.

Hooks installed on the base harness (all module-global lookups, patched by name):
  * ``allocate_semantic_runtime``: install the W6 sites after allocation, arm ``bf16``.
  * ``_BASE_RUN_ONE_UPDATE`` (the per-update primitive under the windowed procedure):
    set the arm for this update, refresh stale FP8 buffers (the per-pair restore rewrites
    master weights), run the base update, refuse an FP8 dispatch in the control arm or any
    fallback, and account dispatches per arm.
  * ``write_receipt``: bind the ``w6_fp8`` block (installation receipt, per-arm dispatch
    counts, fallbacks, wrapper source sha) inside the self-hashed receipt.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any, Mapping

_ROBUST_PATH = Path(__file__).with_name("issue2081_position_robust_canary_v1.py")
_SPEC = importlib.util.spec_from_file_location("issue2081_robust", _ROBUST_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("ISSUE2081_ROBUST_IMPORT_REFUSED")
ROBUST = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ROBUST)
BASE = ROBUST.BASE

W6_ISSUE = 2167
W6_SCOPE = "all_decoder_layers_shared_swiglu_down_4h_to_h"
W6_SCHEMA_VERSION = "ember-issue2173-w6-shared-down-matched-loss-canary-v1"
W6_SITE_COUNT = 14
W6_ARM_KERNEL = {"control": "bf16", "treatment": "fp8"}
# #2173 scope item 5 names the governing matched-loss bar: "#1413 as written
# (treatment loss within 1% of control at matched tokens)". The base (#2071) and
# robust (#2081) harnesses gate the cross-arm loss at 1e-3 absolute / 1e-3 relative,
# because their treatments are algebraically equivalent reorderings whose two arms are
# required to agree to rounding noise (#2081 records its arms as bit-identical on the
# first post-switch update in all eight pairs). W6 changes the forward GEMM numeric
# format at 14 sites, so a cross-arm difference at that scale IS the treatment, not
# drift: the inherited gates assert a property this unit is not required to have and
# are ten times tighter than its own bar. Real-path finding at merged head 32b5b927
# (probe issue2167-w6-ab-probe-32b5b927-20260906T1110Z): the base row-loss gate refused
# pair 0 at absolute 2.0294e-3 / relative 2.1678e-4, and the robust measured-window
# gate would have refused pairs 0 and 6; worst observed relative delta across the eight
# pairs was 1.169e-3 (row loss) and 1.087e-3 (measured window), both inside #1413 by
# more than a factor of eight. The bar below is the issue's, adopted verbatim; it is
# applied only for the duration of the W6 adjudication and restored afterwards, so the
# base and robust harnesses keep their own limits for their own units.
W6_LOSS_RELATIVE_LIMIT = 0.01
# The written bar is relative only ("within 1% of control"); scope item 5 admits no
# other estimator, so the inherited absolute gate is not re-derived, it is stood down.
W6_LOSS_ABSOLUTE_LIMIT = float("inf")
W6_LOSS_BAR_SOURCE = "issue 1413 as written, adopted verbatim by issue 2173 scope item 5"
W6_LOSS_BAR_STATEMENT = "treatment loss within 1% of control at matched tokens"

W6_CLAIM_BOUNDARY = (
    "EIGHT-PAIR POSITION-BALANCED, BOUNDARY-SYNCED WINDOWED MATCHED-LOSS CANARY FOR ONE "
    "FP8 SITE CLASS (SHARED SWIGLU UP+GATE, 14 SITES) ONLY; NO 20K, CAPABILITY, "
    "SUFFICIENT-PRETRAINING, CAMPAIGN, EMBER-02, OR GOAL CREDIT"
)

_ORIGINAL_ALLOCATE = BASE.allocate_semantic_runtime
_ORIGINAL_UPDATE = ROBUST._BASE_RUN_ONE_UPDATE
_ORIGINAL_CONFIGURE = ROBUST.configure_base
BASE_DEFAULT_LOSS_ABSOLUTE_LIMIT = BASE.LOSS_ABSOLUTE_LIMIT
BASE_DEFAULT_LOSS_RELATIVE_LIMIT = BASE.LOSS_RELATIVE_LIMIT
ROBUST_DEFAULT_MEASURED_LOSS_RELATIVE_LIMIT = ROBUST.AA_MEASURED_LOSS_RELATIVE_LIMIT
_STATE: dict[str, Any] = {
    "installation": None,
    "inherited_adjudicate": None,
    "arm_fp8_dispatches": {"control": 0, "treatment": 0},
    "arm_updates": {"control": 0, "treatment": 0},
}


def wrapper_source_sha256() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _acceleration():
    # configure_base puts the rebased root's tools directory first on sys.path, so this
    # resolves to the SAME source tree the harness allocates the model from.
    return importlib.import_module("training_acceleration")


def arm_kernel(arm: str) -> str:
    if arm not in W6_ARM_KERNEL:
        raise ValueError(f"W6_ARM_REFUSED:{arm}")
    return W6_ARM_KERNEL[arm]


def install_w6(model: Any, *, acceleration: Any | None = None, **install_kwargs: Any) -> dict[str, object]:
    """Install the W6 scope on ``model`` and park every site on the ``bf16`` arm."""

    acceleration = acceleration or _acceleration()
    receipt = acceleration.install_fp8_shared_down_projections(
        model, installation_scope=W6_SCOPE, **install_kwargs,
    )
    if receipt.get("installed_sites") != W6_SITE_COUNT or receipt.get("fallbacks") != 0:
        raise RuntimeError("W6_INSTALLATION_RECEIPT_REFUSED")
    if acceleration.set_fp8_arm(model, "bf16") != W6_SITE_COUNT:
        raise RuntimeError("W6_SITE_COUNT_REFUSED")
    _STATE["installation"] = dict(receipt)
    return dict(receipt)


def _fp8_dispatches(acceleration: Any, model: Any) -> tuple[int, int]:
    receipt = acceleration.fp8_arm_receipt(model)
    return int(receipt["fp8_dispatches"]), int(receipt["fallbacks"])


def run_update_w6(*, acceleration: Any | None = None, base_update: Any | None = None, **kwargs: Any):
    """One base update under the W6 arm switch; refuses cross-arm dispatch and fallbacks."""

    acceleration = acceleration or _acceleration()
    base_update = base_update or _ORIGINAL_UPDATE
    arm = str(kwargs["arm"])
    kernel = arm_kernel(arm)
    model = kwargs["model"]
    if _STATE["installation"] is None:
        raise RuntimeError("W6_SITES_NOT_INSTALLED_REFUSED")
    if acceleration.set_fp8_arm(model, kernel) != W6_SITE_COUNT:
        raise RuntimeError("W6_SITE_COUNT_REFUSED")
    acceleration.refresh_fp8_after_optimizer_step(model)
    before, fallbacks_before = _fp8_dispatches(acceleration, model)
    row, cursor = base_update(**kwargs)
    after, fallbacks_after = _fp8_dispatches(acceleration, model)
    if fallbacks_after != fallbacks_before:
        raise RuntimeError(f"W6_FP8_FALLBACK_REFUSED:{arm}:{fallbacks_after - fallbacks_before}")
    dispatched = after - before
    if kernel == "bf16" and dispatched:
        raise RuntimeError(f"W6_CONTROL_ARM_DISPATCHED_FP8_REFUSED:{dispatched}")
    if kernel == "fp8" and not dispatched:
        raise RuntimeError("W6_TREATMENT_ARM_DISPATCHED_NO_FP8_REFUSED")
    _STATE["arm_fp8_dispatches"][arm] += dispatched
    _STATE["arm_updates"][arm] += 1
    return row, cursor


def w6_block() -> dict[str, object]:
    return {
        "schema_version": W6_SCHEMA_VERSION,
        "issue": W6_ISSUE,
        "installation_scope": W6_SCOPE,
        "site_count": W6_SITE_COUNT,
        "arm_kernel": dict(W6_ARM_KERNEL),
        "arm_switch": "fp8_kernel_at_14_shared_down_sites_same_head_same_process",
        "installation": _STATE["installation"],
        "arm_fp8_dispatches": dict(_STATE["arm_fp8_dispatches"]),
        "arm_updates": dict(_STATE["arm_updates"]),
        "fallbacks": 0,
        "matched_loss_bar": _w6_loss_bar_receipt(),
        "wrapper_source_sha256": wrapper_source_sha256(),
        "claim_boundary": W6_CLAIM_BOUNDARY,
    }


def bind_w6_receipt(value: Mapping[str, object]) -> dict[str, object]:
    bound = dict(value)
    bound["issue"] = W6_ISSUE
    bound["w6_fp8"] = w6_block()
    return bound


def _w6_loss_bar_receipt() -> dict[str, object]:
    return {
        "source": W6_LOSS_BAR_SOURCE,
        "statement": W6_LOSS_BAR_STATEMENT,
        "relative_limit": W6_LOSS_RELATIVE_LIMIT,
        "absolute_limit": "stood_down_written_bar_is_relative_only",
        "inherited_row_loss_absolute_limit": BASE_DEFAULT_LOSS_ABSOLUTE_LIMIT,
        "inherited_row_loss_relative_limit": BASE_DEFAULT_LOSS_RELATIVE_LIMIT,
        "inherited_measured_window_relative_limit": ROBUST_DEFAULT_MEASURED_LOSS_RELATIVE_LIMIT,
        "reason": (
            "the inherited gates are calibrated for algebraically equivalent arms; W6 "
            "alternates the forward GEMM numeric format, so a cross-arm loss difference "
            "at rounding scale is the treatment under test, not procedural drift"
        ),
    }


def adjudicate_pairs_w6(pairs: Any, _inner: Any = None) -> dict[str, object]:
    """Run the inherited adjudication with the issue's own loss bar, then restore.

    Only the two loss gates move. Every other refusal in the base and robust
    adjudicators (ABBA order, pair index, start identity, sampled parameters,
    optimizer structure, scheduler / scaler / cursor / RNG / backend identity,
    position balance) applies unchanged, at its own limit.
    """
    inner = _inner if _inner is not None else _STATE["inherited_adjudicate"]
    if inner is None:
        raise RuntimeError("W6_ADJUDICATION_NOT_CONFIGURED_REFUSED")
    saved = (BASE.LOSS_ABSOLUTE_LIMIT, BASE.LOSS_RELATIVE_LIMIT,
             ROBUST.AA_MEASURED_LOSS_RELATIVE_LIMIT)
    BASE.LOSS_ABSOLUTE_LIMIT = W6_LOSS_ABSOLUTE_LIMIT
    BASE.LOSS_RELATIVE_LIMIT = W6_LOSS_RELATIVE_LIMIT
    ROBUST.AA_MEASURED_LOSS_RELATIVE_LIMIT = W6_LOSS_RELATIVE_LIMIT
    try:
        decision = inner(pairs)
    finally:
        (BASE.LOSS_ABSOLUTE_LIMIT, BASE.LOSS_RELATIVE_LIMIT,
         ROBUST.AA_MEASURED_LOSS_RELATIVE_LIMIT) = saved
    bound = dict(decision)
    bound["w6_matched_loss_bar"] = _w6_loss_bar_receipt()
    return bound


def _allocate_w6(**kwargs: Any):
    config, model, optimizer, governor, memory = _ORIGINAL_ALLOCATE(**kwargs)
    install_w6(model)
    return config, model, optimizer, governor, memory


def _update_w6(**kwargs: Any):
    return run_update_w6(**kwargs)


def _configure_w6(**kwargs: Any) -> None:
    if kwargs.get("aa_mode"):
        raise ValueError("W6_AA_MODE_REFUSED")
    if kwargs["control_rebased_head"] != kwargs["treatment_rebased_head"]:
        # the arm difference is the kernel switch; two heads would confound it
        raise ValueError("W6_HEADS_MUST_MATCH_REFUSED")
    _ORIGINAL_CONFIGURE(**kwargs)
    bound_write_receipt = BASE.write_receipt

    def write_w6_receipt(path: Path, value: dict[str, object]):
        return bound_write_receipt(path, bind_w6_receipt(value))

    inherited_adjudicate = BASE.adjudicate_pairs
    _STATE["inherited_adjudicate"] = inherited_adjudicate
    BASE.adjudicate_pairs = adjudicate_pairs_w6
    BASE.allocate_semantic_runtime = _allocate_w6
    BASE.write_receipt = write_w6_receipt
    ROBUST._BASE_RUN_ONE_UPDATE = _update_w6


def main() -> int:
    if "--aa" in sys.argv:
        raise ValueError("W6_AA_MODE_REFUSED")
    ROBUST.configure_base = _configure_w6
    return ROBUST.main()


if __name__ == "__main__":
    raise SystemExit(main())
