#!/usr/bin/env python3
"""ember_c_scale_s3_producer.py -- C-SCALE S3 compute-protocol producer (issue #75).

Builds the three producers the FROZEN spec docs/spec/c-scale-s3-compute-
protocol-v1.md pins as issue #75's build target (section 4): the five
unproduced CHK fields test_c_scale.py (the frozen probe, zero edits here)
still needs -- measured_flops_to_capability, projected_dense_flops_to_
capability, capability_per_compute_ratio, contribution_deletion_collapses_
excess, active_working_set_bytes/device_working_set_floor_bytes.

Three modes (spec section 4):

  --flops         CPU-now: measured_flops_to_capability is pure receipt
                  arithmetic (6*N_active*T per segment, summed over every
                  receipted grow-path segment -- spec section 1). N_active
                  is the dedup-aware UNIQUE parameter count actually training
                  during that segment: rung>=1 receipts report params_unique
                  directly (D4's dual-reporting convention, authoritative);
                  the earlier v0/rung-0 segments (which predate that
                  convention) get it DERIVED -- never fabricated -- by
                  subtracting the SAME tied-embed/head duplicate the rung-1
                  receipt itself measured (data_ptr aliasing) from those
                  receipts' own param_count_before/after fields, with a
                  self-consistency assertion against rung-1's own
                  params_unique_before (refuses rather than silently
                  emitting a wrong number if they disagree).

                  T_dense (the W1 control-arm's tokens-to-match) depends on
                  the real W1 GPU control run (issue #53, maintainer-window-
                  scheduled). Until that lands, projected_dense_flops_to_
                  capability and capability_per_compute_ratio are honestly
                  emitted as UNPRODUCIBLE, citing the exact w1-collapse-
                  control receipt found and its dry_run/is_real_lineage
                  flags (today: dry_run=true, CPU pipeline-proof only). If a
                  real receipt lands with outcome=L3 (collapse REFUTED), the
                  S3 FLOPs arm is emitted as REFUTED alongside W1 (spec
                  section 1) -- never silently folded into "unmeasured".

                  --t-dense-override (selftest/mechanism-proof ONLY,
                  synthetic) proves the ratio math and its re-derivation
                  against test_c_scale._ratio_ok (imported directly, never
                  reimplemented) without claiming real evidence -- writes
                  under scratch/c-scale-s3/, never receipts/, and self-
                  declares _synthetic_control_fixture (the exact token
                  test_c_scale.py's own receipt scan already disqualifies).

  --deletion-arm  CPU eval-only at rung-1 scale (1.22B) -- spec section 2.
                  Re-slices the REAL rung-1 terminal checkpoint back to the
                  pre-grow FF width along the net2net growth map (the row-
                  duplicate/column-halve-duplicate construction
                  cbase_grow_dryrun.widen_state_dict already proved --
                  imported, never reimplemented), evaluates cross-entropy
                  loss on a fixed sha-pinned capability batch (same idiom as
                  this repo's own function_preservation_check), and checks
                  BOTH pre-registered criteria: (1) ablated_loss >=
                  pre_grow_terminal_loss, (2) a random-ablation control of
                  equal channel count (same seed, same layer-type
                  distribution) hurts strictly LESS than deleting the
                  specifically-grown channels -- the leg that attributes the
                  collapse to the grown structure, not to any equal-sized
                  cut. If the real rung-1/pre-grow checkpoints are
                  unreachable from this execution, falls back to a tiny
                  synthetic 2-layer fixture that proves the mechanism end-to-
                  end (labeled synthetic, never evidence) and reports the
                  reachability blocker verbatim.

  --working-set   GPU-window leg (spec section 3) -- instrumented-pass CUDA
                  peak-allocated measurement. Mirrors scripts/w1_collapse_
                  control_run.py's launch interlock exactly: refuses unless
                  EMBER_GATE_AUTHORIZED=1 (env) AND --live AND --device
                  cuda; NEVER fired by this builder. --dry-run (CPU, the
                  only supported mode from this workstation) measures HOST
                  peak working-set bytes (psutil) around a tiny instrumented
                  forward pass as a PIPELINE-PROOF ONLY receipt -- never
                  claims a device/CUDA measurement, labeled dry_run=true.

Selftest (--selftest): fixture-driven proof of all three modes' receipt
schemas, the ratio re-derivation (test_c_scale._ratio_ok, imported), the
FLOPs dedup self-consistency guard (both the matching AND the deliberately-
mismatched case), and the deletion-arm criteria logic in BOTH directions (a
fixture where the collapse holds, and one where the random-ablation control
defeats attribution). Prints C_SCALE_S3_PRODUCER_SELFTEST_PASS on success.

Rails (issue #75 / spec section 4): new files only, sandbox scratch/c-scale-
s3/, no network, no GPU ever touched by this script's own execution,
receipts born from execution, C(-1) declarations (api_spend_usd=0.0,
paid_api_surface_used=false) on every receipt, bare #NN issue refs, no
lineage terms.

Usage:
  python src/ember/governance/scripts/ember_c_scale_s3_producer.py --flops
  python src/ember/governance/scripts/ember_c_scale_s3_producer.py --flops --t-dense-override 3.0e7
  python src/ember/governance/scripts/ember_c_scale_s3_producer.py --deletion-arm
  python src/ember/governance/scripts/ember_c_scale_s3_producer.py --working-set --dry-run
  python src/ember/governance/scripts/ember_c_scale_s3_producer.py --working-set --live --device cuda   # refuses
  python src/ember/governance/scripts/ember_c_scale_s3_producer.py --selftest
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))                       # ember-goalforge/scripts
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))  # repository root
LEGACY_SCRIPTS = os.path.join(REPO, "scripts")
CROSS_REPO_DEFAULT = os.path.normpath(os.path.join(REPO, "..", "ember"))  # sibling work tree

sys.path.insert(0, HERE)
sys.path.insert(0, LEGACY_SCRIPTS)
sys.path.insert(0, os.path.join(LEGACY_SCRIPTS, "ember_totality"))

import test_c_scale as c_scale           # noqa: E402 -- frozen probe, reused not reimplemented
from receipt_write import checked_write  # noqa: E402

SPEC_REF = "docs/spec/c-scale-s3-compute-protocol-v1.md"
ISSUE_REF = "#75"
_ratio_ok = c_scale._ratio_ok  # imported directly -- never reimplemented

DEFAULT_PRICING_RECEIPT = os.path.join(REPO, "scratch", "w1-control", "w1-pricing-20260704T063236Z.json")
DEFAULT_RECEIPTS_DIR = os.path.join(REPO, "receipts", "ember-c-scale")
DEFAULT_SANDBOX = os.path.join(REPO, "scratch", "c-scale-s3")
DEFAULT_GROW_LIVE_RECEIPT = os.path.normpath(os.path.join(
    CROSS_REPO_DEFAULT, "receipts", "cbase-grow-live", "cbase-grow-live-live-20260703T053225Z.json"))
DEFAULT_V0_RECEIPT = os.path.normpath(os.path.join(
    CROSS_REPO_DEFAULT, "receipts", "v0-live-20260623T105829Z.json"))

_COMPACT_TS_RE = re.compile(r"\d{8}T\d{6}Z")
_RUNG_FILE_RE = re.compile(r"cbase-grow-rung(\d+)-")
_RUNG_SEG_RE = re.compile(r"^cbase-grow-rung(\d+)-stabilize$")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _latest_by_compact_ts(paths):
    scored = []
    for p in paths:
        m = _COMPACT_TS_RE.search(os.path.basename(p))
        if m:
            scored.append((m.group(0), p))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0])
    return scored[-1][1]


def discover_rung_receipts(cross_root: str):
    """Latest PASS receipt per rung number under cross_root/receipts/cbase-grow-rung/.
    Returns (data_by_rung: dict[int, dict], path_by_rung: dict[int, str])."""
    d = os.path.join(cross_root, "receipts", "cbase-grow-rung")
    cands = glob.glob(os.path.join(d, "**", "*.json"), recursive=True)
    by_rung = {}  # rung -> (ts_str, path, data)
    for p in cands:
        m = _RUNG_FILE_RE.search(os.path.basename(p))
        tsm = _COMPACT_TS_RE.search(os.path.basename(p))
        if not (m and tsm):
            continue
        rung_n = int(m.group(1))
        try:
            data = load_json(p)
        except Exception:
            continue
        if data.get("pass") is not True:
            continue
        cur = by_rung.get(rung_n)
        if cur is None or tsm.group(0) > cur[0]:
            by_rung[rung_n] = (tsm.group(0), p, data)
    data_by_rung = {n: v[2] for n, v in by_rung.items()}
    path_by_rung = {n: v[1] for n, v in by_rung.items()}
    return data_by_rung, path_by_rung


def find_latest_w1_control(receipts_dir: str):
    cands = glob.glob(os.path.join(receipts_dir, "w1-collapse-control-*.json"))
    return _latest_by_compact_ts(cands)


# ---------------------------------------------------------------------------
# --flops mode (spec section 1)
# ---------------------------------------------------------------------------

def build_flops_segments(pricing: dict, grow_live: dict, dedup_const: int,
                          rung_data_by_number: dict):
    """Per-segment N_active(seg)*T(seg) rows for measured_flops_to_capability.

    N_active is the dedup-aware unique parameter count (spec section 1: 'the
    rung receipts' own params_unique fields -- never nominal/duplicated
    counts'). Only rung>=1 receipts report params_unique directly. The
    earlier v0/rung-0 segments (which predate that convention) get it
    DERIVED by subtracting the tied-embed/head duplicate rung-1 itself
    measured from grow_live's own param_count_before/after (raw state-dict-
    sum) fields -- this duplicate is constant across every stage in this
    lineage (net2net FF-widening never touches embed_tokens/head/mtp_heads).
    Self-consistency is asserted, not merely assumed: the derived unique
    count for grow_live's post-grow width must equal rung-1's own directly-
    reported params_unique_before (same physical stage, two receipts) --
    refuses rather than silently emitting a bad number if they disagree.
    """
    n_seed = grow_live["param_count_before"] - dedup_const
    n_rung0_post = grow_live["param_count_after"] - dedup_const

    rung1 = rung_data_by_number.get(1)
    if rung1 is not None and n_rung0_post != rung1["params_unique_before"]:
        raise ValueError(
            "S3_FLOPS_DEDUP_CONSISTENCY_FAIL: grow-live post-grow derived unique "
            f"params ({n_rung0_post}) != rung-1 receipt's own params_unique_before "
            f"({rung1['params_unique_before']}) -- the constant tied-duplicate "
            "assumption does not hold; refusing rather than emitting a silently "
            "wrong N_active"
        )

    rows_out = []
    total_flops = 0.0
    for row in pricing["grow_arm"]["bill_aggregation_rows"]:
        seg = row["segment"]
        t = row["tokens_value"]
        if seg in ("v0-seed-pretrain", "cbase-grow-live-pre"):
            n_active = n_seed
            derivation = "grow_live.param_count_before - dedup_const (pre-grow-of-rung0 FF width)"
        elif seg == "cbase-grow-live-post":
            n_active = n_rung0_post
            derivation = "grow_live.param_count_after - dedup_const (post-grow-of-rung0 FF width)"
        else:
            m = _RUNG_SEG_RE.match(seg)
            if not m:
                raise ValueError(f"S3_FLOPS_UNKNOWN_SEGMENT: {seg!r} not in the known lineage map")
            rung_n = int(m.group(1))
            rr = rung_data_by_number.get(rung_n)
            if rr is None:
                raise ValueError(
                    f"S3_FLOPS_MISSING_RUNG_RECEIPT: rung {rung_n} receipt not "
                    f"loaded/available for segment {seg!r}")
            n_active = rr["params_unique_after"]
            derivation = f"rung{rung_n} receipt's own params_unique_after (D4 authoritative, direct field)"
        seg_flops = 6.0 * n_active * t
        total_flops += seg_flops
        rows_out.append({
            "segment": seg, "tokens_value": t, "n_active": n_active,
            "n_active_derivation": derivation, "flops_this_segment": seg_flops,
            "receipt_path": row["receipt_path"],
        })
    return total_flops, rows_out


def resolve_t_dense(w1_control_path):
    """Returns dict: status ('PRODUCED'|'UNPRODUCIBLE'|'REFUTED'), t_dense,
    detail, citation. Never fabricates T_dense (spec section 1)."""
    if w1_control_path is None:
        return {"status": "UNPRODUCIBLE", "t_dense": None,
                "detail": ("no w1-collapse-control-*.json receipt found under "
                           "receipts/ember-c-scale/ -- the W1 control run (issue #53, "
                           "maintainer GPU window) has not produced one yet"),
                "citation": None}
    data = load_json(w1_control_path)
    citation = {"path": w1_control_path, "sha256": sha256_file(w1_control_path)}
    dry_run = data.get("dry_run")
    is_real = data.get("is_real_lineage")
    outcome = data.get("outcome")
    if dry_run is not False or is_real is not True:
        return {"status": "UNPRODUCIBLE", "t_dense": None,
                "detail": (f"latest w1-collapse-control receipt "
                           f"({os.path.basename(w1_control_path)}) is dry_run={dry_run!r}/"
                           f"is_real_lineage={is_real!r} -- a CPU pipeline-proof only; its own "
                           "note discloses it carries NO physical claim about the real W1 "
                           "collapse ratio; the real GPU control run (issue #53 window) has "
                           "not executed yet -- per spec section 1, T_dense stays "
                           "UNPRODUCIBLE until then"),
                "citation": citation}
    if outcome == "L3":
        return {"status": "REFUTED", "t_dense": None,
                "detail": ("W1 collapse REFUTED at this scale (outcome=L3) -- per spec "
                           "section 1, 'the S3 FLOPs arm is REFUTED alongside W1 and no "
                           "compliant composite exists (lands as truth)'"),
                "citation": citation}
    if outcome not in ("L1", "L2"):
        return {"status": "UNPRODUCIBLE", "t_dense": None,
                "detail": f"unrecognized W1 outcome {outcome!r} (expected L1/L2/L3)",
                "citation": citation}
    control_arm = data.get("control_arm", {})
    t_dense = control_arm.get("tokens_to_match")
    lower_bound = False
    if t_dense is None:
        t_dense = control_arm.get("tokens_at_ceiling")
        lower_bound = True
    if t_dense is None:
        return {"status": "UNPRODUCIBLE", "t_dense": None,
                "detail": "real w1-collapse-control receipt carries neither tokens_to_match "
                          "nor tokens_at_ceiling", "citation": citation}
    return {"status": "PRODUCED", "t_dense": t_dense, "lower_bound": lower_bound,
            "outcome": outcome,
            "detail": (f"T_dense={t_dense} from real receipt (outcome={outcome}"
                       f"{', lower_bound carried' if lower_bound else ''})"),
            "citation": citation}


def find_latest_matched_continuation(receipts_dir: str):
    cands = glob.glob(os.path.join(receipts_dir, "c-scale-s3-matched-continuation-*.json"))
    return _latest_by_compact_ts(cands)


def resolve_matched_continuation_baseline(receipts_dir: str):
    """Issue #85 / spec section 2 v1.1 amendment. Returns dict: status
    ('PRODUCED'|'UNPRODUCIBLE'), baseline_loss, detail, citation -- mirrors
    resolve_t_dense's discover-latest-and-validate pattern exactly. Never
    fabricates a v1.1 baseline: UNPRODUCIBLE (with a disclosed reason) until
    scripts/s3_matched_continuation_control.py's real --live run has
    produced a dry_run=False/is_real_lineage=True receipt."""
    path = find_latest_matched_continuation(receipts_dir)
    if path is None:
        return {"status": "UNPRODUCIBLE", "baseline_loss": None,
                "detail": ("no c-scale-s3-matched-continuation-*.json receipt found under "
                           f"{receipts_dir} -- the matched-continuation control run (issue #85, "
                           "maintainer GPU window) has not produced one yet; criterion 1 falls "
                           "back to the v1 frozen pre-grow baseline (disclosed, not silent)"),
                "citation": None}
    data = load_json(path)
    citation = {"path": path, "sha256": sha256_file(path)}
    dry_run = data.get("dry_run")
    is_real = data.get("is_real_lineage")
    if dry_run is not False or is_real is not True:
        return {"status": "UNPRODUCIBLE", "baseline_loss": None,
                "detail": (f"latest c-scale-s3-matched-continuation receipt "
                           f"({os.path.basename(path)}) is dry_run={dry_run!r}/"
                           f"is_real_lineage={is_real!r} -- a CPU/tiny-fixture mechanism-proof "
                           "only; the real GPU continuation (issue #85 window) has not "
                           "executed yet -- criterion 1 falls back to the v1 frozen pre-grow "
                           "baseline until then"),
                "citation": citation}
    baseline_loss = (data.get("losses") or {}).get("matched_continuation_eval_loss")
    if baseline_loss is None:
        return {"status": "UNPRODUCIBLE", "baseline_loss": None,
                "detail": ("real matched-continuation receipt carries no "
                           "losses.matched_continuation_eval_loss"),
                "citation": citation}
    return {"status": "PRODUCED", "baseline_loss": baseline_loss,
            "detail": (f"matched_continuation_eval_loss={baseline_loss} from real receipt "
                       "(v1.1 criterion-1 baseline)"),
            "citation": citation}


def run_flops(args) -> int:
    pricing_path = args.pricing_receipt or DEFAULT_PRICING_RECEIPT
    grow_live_path = args.grow_live_receipt or DEFAULT_GROW_LIVE_RECEIPT
    cross_root = args.cross_root or CROSS_REPO_DEFAULT

    pricing = load_json(pricing_path)
    grow_live = load_json(grow_live_path)
    rung_data_by_number, rung_path_by_number = discover_rung_receipts(cross_root)
    if args.rung_receipt:
        # explicit override -- used by --selftest to point at fixture rungs
        rung_data_by_number = {1: load_json(args.rung_receipt)}
        rung_path_by_number = {1: args.rung_receipt}
    if not rung_data_by_number:
        raise SystemExit("S3_FLOPS_NO_RUNG_RECEIPT: no PASS cbase-grow-rung receipt discovered "
                          f"under {cross_root}/receipts/cbase-grow-rung/")

    rung1 = rung_data_by_number.get(1)
    if rung1 is None:
        raise SystemExit("S3_FLOPS_NO_RUNG1: rung-1 receipt required for the dedup constant "
                          "(params_dedup.measured_duplicate_numel)")
    dedup_const = rung1["params_dedup"]["measured_duplicate_numel"]

    measured_flops, rows = build_flops_segments(pricing, grow_live, dedup_const, rung_data_by_number)

    n_final_rung = max(rung_data_by_number)
    n_final = rung_data_by_number[n_final_rung]["params_unique_after"]

    receipts_dir = args.out_dir or DEFAULT_RECEIPTS_DIR
    w1_control_path = args.w1_control_receipt or find_latest_w1_control(receipts_dir)
    t_dense_info = resolve_t_dense(w1_control_path)

    stamp = ts()
    citations = {
        "pricing_receipt": {"path": pricing_path, "sha256": sha256_file(pricing_path)},
        "grow_live_receipt": {"path": grow_live_path, "sha256": sha256_file(grow_live_path)},
        "rung_receipts": {str(n): {"path": p, "sha256": sha256_file(p)}
                          for n, p in rung_path_by_number.items()},
    }

    receipt = {
        "ticket": "C-SCALE-S3-FLOPS",
        "ts": stamp,
        "issue": ISSUE_REF,
        "schema": "c-scale-s3-flops/v1",
        "spec_ref": f"{SPEC_REF} section 1",
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
        "mode": "flops",
        "measured_flops_to_capability": measured_flops,
        "measured_flops_segments": rows,
        "dedup_constant_tied_embed_head_numel": dedup_const,
        "dedup_constant_source": ("rung1 receipt's params_dedup.measured_duplicate_numel "
                                  "(data_ptr-aliasing measurement) -- constant across FF widths "
                                  "since net2net never touches embed/head/mtp_heads"),
        "operating_capability_point_n_final": n_final,
        "operating_capability_point_n_final_source_rung": n_final_rung,
        "t_dense_resolution": t_dense_info,
        "citations": citations,
        "api_spend_usd": 0.0,
        "paid_api_surface_used": False,
        "invalid_tokens_present": [],
    }

    if t_dense_info["status"] == "PRODUCED":
        t_dense = t_dense_info["t_dense"]
        projected = 6.0 * n_final * t_dense
        ratio = (projected / measured_flops) if measured_flops else None
        ok, why = _ratio_ok(ratio, projected, measured_flops)
        receipt["projected_dense_flops_to_capability"] = projected
        receipt["capability_per_compute_ratio"] = ratio
        receipt["capability_per_compute_ratio_rederivation"] = {"ok": ok, "detail": why}
        receipt["verdict"] = "S3_FLOPS_PRODUCED" if ok else "S3_FLOPS_RATIO_FAILS_REDERIVATION"
    elif t_dense_info["status"] == "REFUTED":
        receipt["projected_dense_flops_to_capability"] = None
        receipt["capability_per_compute_ratio"] = None
        receipt["verdict"] = "S3_FLOPS_REFUTED_ALONGSIDE_W1"
    else:
        receipt["projected_dense_flops_to_capability"] = "UNPRODUCIBLE"
        receipt["capability_per_compute_ratio"] = "UNPRODUCIBLE"
        receipt["verdict"] = "S3_FLOPS_PARTIAL_UNPRODUCIBLE_PENDING_W1"

    if args.t_dense_override is not None:
        t_dense = args.t_dense_override
        projected = 6.0 * n_final * t_dense
        ratio = (projected / measured_flops) if measured_flops else None
        ok, why = _ratio_ok(ratio, projected, measured_flops)
        override_receipt = dict(receipt)
        override_receipt.update({
            "ticket": "C-SCALE-S3-FLOPS-TDENSE-OVERRIDE",
            "_synthetic_control_fixture": True,
            "t_dense_override": True,
            "t_dense_override_value": t_dense,
            "projected_dense_flops_to_capability": projected,
            "capability_per_compute_ratio": ratio,
            "capability_per_compute_ratio_rederivation": {"ok": ok, "detail": why},
            "verdict": ("S3_FLOPS_TDENSE_OVERRIDE_RATIO_MATH_PROVEN" if ok
                        else "S3_FLOPS_TDENSE_OVERRIDE_RATIO_FAIL"),
            "note": ("SYNTHETIC t_dense override -- mechanism-proof ONLY, never real evidence; "
                     "written under scratch/, never receipts/, and self-declares "
                     "_synthetic_control_fixture so test_c_scale.py's own receipt scan would "
                     "reject it if ever misplaced under receipts/."),
        })
        out_dir = os.path.join(DEFAULT_SANDBOX, "flops-tdense-override")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"c-scale-s3-flops-tdense-override-{stamp}.json")
        with open(out_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(override_receipt, f, indent=2)
        print(f"[s3-flops] T_DENSE OVERRIDE (synthetic): {out_path}")
        print(f"[s3-flops] override ratio={ratio} rederives={ok} ({why})")
        receipt["t_dense_override_proof_path"] = out_path

    os.makedirs(receipts_dir, exist_ok=True)
    out_path = os.path.join(receipts_dir, f"c-scale-s3-flops-{stamp}.json")
    checked_write(out_path, receipt)
    print(f"[s3-flops] receipt written: {out_path}")
    print(f"[s3-flops] measured_flops_to_capability={measured_flops:.6g} "
          f"t_dense_status={t_dense_info['status']} verdict={receipt['verdict']}")
    return 0


# ---------------------------------------------------------------------------
# --deletion-arm mode (spec section 2)
# ---------------------------------------------------------------------------

def evaluate_deletion_criteria(loss_pre_grow: float, loss_ablated: float, loss_random: float,
                                baseline_loss: float | None = None):
    """The two pre-registered criteria (spec section 2), as a pure function
    so both the real and synthetic-fallback paths -- and the selftest -- use
    the SAME logic.

    baseline_loss (v1.1 amendment, issue #85): when given, criterion 1 is
    evaluated against THIS value instead of loss_pre_grow -- the matched-
    continuation control's eval loss (the same pre-grow checkpoint,
    continued the SAME 36 steps WITHOUT growth). This isolates "is growth
    load-bearing" from "did more training happen" -- the confound the v1
    frozen-baseline comparison exposed (the ablated arm inherits post-grow
    training steps the frozen pre-grow checkpoint never got). Backward
    compatible: omitted or None leaves criterion 1 keyed to loss_pre_grow,
    unchanged v1 behavior."""
    c1_baseline = loss_pre_grow if baseline_loss is None else baseline_loss
    criterion_1 = loss_ablated >= c1_baseline
    criterion_2 = loss_random < loss_ablated
    return criterion_1, criterion_2, bool(criterion_1 and criterion_2)


def slice_first_half(sd: dict, n_layers: int, ff_seed: int) -> dict:
    """Deletion-arm reconstruction: keep the FIRST ff_seed FF channels (the
    pre-existing ones), drop the grown SECOND HALF -- net2net's own growth
    map inverted. down_proj stays at its POST-GROW halved scale (cat([d*0.5,
    d*0.5])'s first half = d*0.5, not d), so this is NOT a rescale-corrected
    recovery of the true pre-grow model -- it is the deliberate ablation:
    whatever capability the grown half carried is removed, uncompensated."""
    out = dict(sd)
    for i in range(n_layers):
        p = f"backbone_model.layers.{i}.mlp."
        out[p + "gate_proj.weight"] = sd[p + "gate_proj.weight"][:ff_seed, :].clone()
        out[p + "up_proj.weight"] = sd[p + "up_proj.weight"][:ff_seed, :].clone()
        out[p + "down_proj.weight"] = sd[p + "down_proj.weight"][:, :ff_seed].clone()
    return out


def slice_random(sd: dict, n_layers: int, ff_seed: int, ff_grown: int, seed: int):
    """Random-ablation control (spec section 2 criterion 2): same COUNT of FF
    channels kept per layer (ff_seed out of ff_grown) and the same layer-type
    distribution as the delete-grown arm, but the kept indices are a RANDOM
    subset instead of specifically the pre-existing first half -- this is
    the leg that attributes the collapse to the GROWN structure specifically,
    not merely to any equal-sized cut."""
    import numpy as np
    import torch
    out = dict(sd)
    rng = np.random.default_rng(seed)
    kept_indices_per_layer = {}
    for i in range(n_layers):
        p = f"backbone_model.layers.{i}.mlp."
        keep = np.sort(rng.choice(ff_grown, size=ff_seed, replace=False))
        kept_indices_per_layer[i] = keep.tolist()
        idx = torch.as_tensor(keep, dtype=torch.long)
        out[p + "gate_proj.weight"] = sd[p + "gate_proj.weight"][idx, :].clone()
        out[p + "up_proj.weight"] = sd[p + "up_proj.weight"][idx, :].clone()
        out[p + "down_proj.weight"] = sd[p + "down_proj.weight"][:, idx].clone()
    return out, kept_indices_per_layer


def make_eval_batch(vocab: int, seq: int, batch: int, seed: int):
    import torch
    ids = torch.randint(0, vocab, (batch, seq + 1), generator=torch.Generator().manual_seed(seed))
    x = ids[:, :seq]
    y = ids[:, 1:seq + 1]
    combined_sha = hashlib.sha256(ids.numpy().tobytes()).hexdigest()
    return x, y, combined_sha


def eval_ce_loss(model, x, y) -> float:
    import torch
    model.eval()
    with torch.no_grad():
        logits = model.logits(x)
        loss = torch.nn.functional.cross_entropy(
            logits.reshape(-1, logits.shape[-1]), y.reshape(-1))
    return float(loss.item())


def load_real_corpus_window(shard_dir: str, seq: int, window_idx: int = 0):
    """Best-effort real-corpus eval window: concatenates every *.bin uint16
    packed shard in shard_dir (SAME <u2 dtype convention as timeshare_
    pretrain.PACK_DTYPE / PackedShardLoader, read directly here rather than
    importing that module's heavier dependency chain) and slices one fixed
    window. Returns (window: np.ndarray[int64] of length seq+1 or None,
    meta-or-error). Real text, but NOT verified to be the exact shard_dir
    this checkpoint trained on (the receipted real training shard_dir was
    state/cbase-mixture, not present on this machine) -- disclosed, never
    silently implied as held-out."""
    import numpy as np
    if not os.path.isdir(shard_dir):
        return None, f"{shard_dir} not present on this machine"
    files = sorted(f for f in os.listdir(shard_dir) if f.endswith(".bin"))
    if not files:
        return None, f"no .bin shard files found under {shard_dir}"
    arrs = [np.fromfile(os.path.join(shard_dir, f), dtype="<u2") for f in files]
    stream = np.concatenate(arrs) if len(arrs) > 1 else arrs[0]
    block_len = seq + 1
    if stream.shape[0] < block_len:
        return None, f"stream too short ({stream.shape[0]} tokens < {block_len} needed)"
    n_windows = (stream.shape[0] - block_len) // seq + 1
    idx = window_idx % n_windows
    start = idx * seq
    w = stream[start:start + block_len].astype("int64")
    meta = {
        "shard_dir": shard_dir, "files": files,
        "n_tokens_total": int(stream.shape[0]), "n_windows": int(n_windows),
        "window_idx": int(idx),
        "shard_sha256": {f: sha256_file(os.path.join(shard_dir, f)) for f in files},
    }
    return w, meta


def _verify_checkpoint(ckpt_dir: str):
    manifest_path = os.path.join(ckpt_dir, "manifest.json")
    if not os.path.isfile(manifest_path):
        return None, f"manifest.json missing at {ckpt_dir}"
    manifest = load_json(manifest_path)
    model_pt = os.path.join(ckpt_dir, "model.pt")
    if not os.path.isfile(model_pt):
        return None, f"model.pt missing at {ckpt_dir}"
    claimed = (manifest.get("files") or {}).get("model.pt")
    actual = sha256_file(model_pt)
    if not (isinstance(claimed, str) and actual == claimed):
        return None, f"model.pt sha256 mismatch at {ckpt_dir}: manifest={claimed} actual={actual}"
    return model_pt, None


def run_deletion_arm(args) -> int:
    cross_root = args.cross_root or CROSS_REPO_DEFAULT
    grow_live_path = args.grow_live_receipt or DEFAULT_GROW_LIVE_RECEIPT
    stamp = ts()
    blocker = None
    cfg_model = n_mtp = rung1 = rung1_path = pre_grow_ckpt_dir = grown_ckpt_dir = None
    pre_model_pt = grown_model_pt = None

    try:
        config_path = os.path.join(cross_root, "configs", "v0-pretrain-config.json")
        v0_config = load_json(config_path)
        cfg_model = v0_config["model"]
        n_mtp = v0_config["objective"]["mtp_aux_heads"]["n_heads"]

        grow_live = load_json(grow_live_path)
        rung_data_by_number, rung_path_by_number = discover_rung_receipts(cross_root)
        if args.rung_receipt:
            rung1 = load_json(args.rung_receipt)
            rung1_path = args.rung_receipt
        else:
            rung1 = rung_data_by_number.get(1)
            rung1_path = rung_path_by_number.get(1)
        if rung1 is None:
            blocker = f"no PASS rung-1 receipt discovered under {cross_root}/receipts/cbase-grow-rung/"
        else:
            pre_grow_ckpt_dir = grow_live["post_grow_segment"]["checkpoint"]
            grown_ckpt_dir = rung1["stabilization_segment"]["checkpoint"]
            pre_model_pt, err1 = _verify_checkpoint(pre_grow_ckpt_dir)
            grown_model_pt, err2 = _verify_checkpoint(grown_ckpt_dir)
            if err1 or err2:
                blocker = f"pre_grow: {err1}; grown: {err2}"
    except Exception as exc:
        blocker = f"{type(exc).__name__}: {exc}"

    if blocker:
        return _run_deletion_arm_synthetic_fallback(args, stamp, blocker)

    import torch
    sys.path.insert(0, os.path.join(cross_root, "scripts"))
    from cbase_grow_dryrun import build_model  # cross-tree, read-only reuse -- never reimplemented

    ff_seed = rung1["ff_seed"]
    ff_grown = rung1["ff_grown"]
    n_layers = cfg_model["layers"]
    vocab = cfg_model["vocab"]

    sd_pre_bf16 = torch.load(pre_model_pt, map_location="cpu", weights_only=True)
    sd_grown_bf16 = torch.load(grown_model_pt, map_location="cpu", weights_only=True)
    sd_pre = {k: v.float() for k, v in sd_pre_bf16.items()}
    sd_grown = {k: v.float() for k, v in sd_grown_bf16.items()}

    sd_ablated = slice_first_half(sd_grown, n_layers, ff_seed)
    random_seed = args.random_ablation_seed
    sd_random, kept_indices = slice_random(sd_grown, n_layers, ff_seed, ff_grown, random_seed)

    eval_seq = min(cfg_model["seq"], args.eval_seqlen)
    x, y, batch_sha = make_eval_batch(vocab, eval_seq, args.eval_batch, args.eval_seed)

    def build_and_eval(sd, intermediate):
        model = build_model(cfg_model, n_mtp, intermediate)
        missing, unexpected = model.load_state_dict(sd, strict=False)
        real_missing = [k for k in missing if k != "head.weight"]
        if real_missing or unexpected:
            raise SystemExit(
                f"S3_DELETION_ARM_LOAD_MISMATCH: missing={real_missing} unexpected={unexpected}")
        model.eval()
        return eval_ce_loss(model, x, y)

    loss_pre_grow = build_and_eval(sd_pre, ff_seed)
    loss_grown = build_and_eval(sd_grown, ff_grown)
    loss_ablated = build_and_eval(sd_ablated, ff_seed)
    loss_random = build_and_eval(sd_random, ff_seed)

    # v1.1 amendment (issue #85): resolve the matched-continuation baseline
    # if a real one has been produced; falls back to the v1 frozen pre-grow
    # baseline (disclosed, never silent) otherwise.
    mc_receipts_dir = args.out_dir or DEFAULT_RECEIPTS_DIR
    matched_continuation_info = resolve_matched_continuation_baseline(mc_receipts_dir)
    baseline_loss = matched_continuation_info["baseline_loss"]

    criterion_1_v1, _c2_v1, _collapses_v1 = evaluate_deletion_criteria(
        loss_pre_grow, loss_ablated, loss_random)  # legacy v1 form, always computed for disclosure
    criterion_1, criterion_2, collapses = evaluate_deletion_criteria(
        loss_pre_grow, loss_ablated, loss_random, baseline_loss=baseline_loss)

    # --- best-effort SECOND leg: real corpus text, informational only -------
    # The synthetic uniform-random batch above is fully reproducible and
    # matches this repo's own function_preservation_check idiom, but uniform-
    # random targets are a poor probe of LEARNED capability (a model that
    # learned real Zipfian token frequencies is measurably PENALIZED against
    # uniform targets, swamping any genuine collapse signal). Where real
    # corpus text is reachable in-tree (data/cbase_pretrain), run the exact
    # same four-way comparison against it too -- strictly more informative,
    # never authoritative for contribution_deletion_collapses_excess (that
    # field stays keyed to the primary synthetic-batch criteria above, the
    # one whose provenance is fully self-contained and reproducible).
    real_corpus_dir = os.path.join(cross_root, "data", "cbase_pretrain")
    window, window_meta_or_err = load_real_corpus_window(real_corpus_dir, eval_seq, window_idx=0)
    real_corpus_probe = None
    if window is None:
        real_corpus_probe = {"available": False, "reason": window_meta_or_err}
    elif int(window.max()) >= vocab:
        real_corpus_probe = {"available": False,
                             "reason": f"token id {int(window.max())} >= vocab {vocab}"}
    else:
        w_t = torch.as_tensor(window, dtype=torch.long)
        x_rc = w_t[:eval_seq].unsqueeze(0)
        y_rc = w_t[1:eval_seq + 1].unsqueeze(0)

        def build_and_eval_rc(sd, intermediate):
            model = build_model(cfg_model, n_mtp, intermediate)
            missing, unexpected = model.load_state_dict(sd, strict=False)
            real_missing = [k for k in missing if k != "head.weight"]
            if real_missing or unexpected:
                raise SystemExit(
                    f"S3_DELETION_ARM_LOAD_MISMATCH (real-corpus leg): "
                    f"missing={real_missing} unexpected={unexpected}")
            model.eval()
            return eval_ce_loss(model, x_rc, y_rc)

        rc_loss_pre_grow = build_and_eval_rc(sd_pre, ff_seed)
        rc_loss_grown = build_and_eval_rc(sd_grown, ff_grown)
        rc_loss_ablated = build_and_eval_rc(sd_ablated, ff_seed)
        rc_loss_random = build_and_eval_rc(sd_random, ff_seed)
        rc_c1, rc_c2, rc_collapses = evaluate_deletion_criteria(
            rc_loss_pre_grow, rc_loss_ablated, rc_loss_random)
        real_corpus_probe = {
            "available": True,
            "provenance_caveat": ("real corpus text (data/cbase_pretrain), reachability "
                                  "confirmed; NOT verified to be the exact shard_dir this "
                                  "checkpoint trained on (the receipted real training "
                                  "shard_dir was state/cbase-mixture, not present on this "
                                  "machine) -- still a strictly more meaningful language-"
                                  "modeling probe than the synthetic uniform-random batch "
                                  "above; informational only, does not drive the primary "
                                  "contribution_deletion_collapses_excess verdict"),
            "window_meta": window_meta_or_err,
            "losses": {"pre_grow_terminal_loss": rc_loss_pre_grow,
                       "grown_loss_informational": rc_loss_grown,
                       "ablated_loss": rc_loss_ablated,
                       "random_ablation_control_loss": rc_loss_random},
            "criteria": {"criterion_1_ablated_loss_gte_pre_grow": rc_c1,
                         "criterion_2_random_control_hurts_strictly_less": rc_c2},
            "contribution_deletion_collapses_excess_informational": rc_collapses,
        }

    receipt = {
        "ticket": "C-SCALE-S3-DELETION-ARM",
        "ts": stamp,
        "issue": ISSUE_REF,
        "schema": "c-scale-s3-deletion-arm/v1",
        "spec_ref": f"{SPEC_REF} section 2",
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
        "mode": "cpu_eval_only",
        "rung": 1,
        "operating_capability_point": rung1.get("params_unique_after"),
        "growth_map": {
            "mechanism": ("ff_widening_net2net (widen_state_dict, imported from "
                          "scripts/cbase_grow_dryrun.py, never reimplemented)"),
            "ff_seed": ff_seed, "ff_grown": ff_grown,
            "surgery_math": ("gate_proj/up_proj: cat([w,w],dim=0); down_proj: "
                             "cat([w*0.5,w*0.5],dim=1) -- per rung-1 receipt's own grow_step"),
            "citation": {"path": rung1_path, "sha256": sha256_file(rung1_path)},
        },
        "checkpoints": {
            "pre_grow": {"dir": pre_grow_ckpt_dir, "model_pt_sha256": sha256_file(pre_model_pt)},
            "grown": {"dir": grown_ckpt_dir, "model_pt_sha256": sha256_file(grown_model_pt)},
        },
        "eval_batch": {
            "note": ("sha-pinned SYNTHETIC capability probe (same idiom as this repo's own "
                     "function_preservation_check / w1-control capability_point) -- no real "
                     "held-out corpus is reachable in-tree at this scale (the receipted real "
                     "shard_dir, state/cbase-mixture, is not present on this machine); the "
                     "loss measures each model's deterministic computed function on a fixed "
                     "random token batch, not real-language capability."),
            "vocab": vocab, "batch": args.eval_batch, "seqlen": eval_seq,
            "token_ids_sha256": batch_sha, "generator_seed": args.eval_seed,
        },
        "random_ablation": {
            "seed": random_seed,
            "kept_indices_per_layer_sha256": hashlib.sha256(
                json.dumps(kept_indices, sort_keys=True).encode("utf-8")).hexdigest(),
            "note": ("same channel COUNT (ff_seed) and layer-type distribution as the "
                     "delete-grown arm, per layer, but a RANDOM subset of the ff_grown "
                     "channels kept instead of specifically the pre-existing first half"),
        },
        "losses": {
            "pre_grow_terminal_loss": loss_pre_grow,
            "grown_loss_informational": loss_grown,
            "ablated_loss": loss_ablated,
            "random_ablation_control_loss": loss_random,
        },
        "criteria": {
            "criterion_1_ablated_loss_gte_pre_grow": criterion_1_v1,
            "criterion_1_v1_1_ablated_loss_gte_matched_continuation_baseline": (
                criterion_1 if baseline_loss is not None else None),
            "criterion_1_active": criterion_1,
            "criterion_1_active_basis": (
                "v1.1 matched-continuation baseline" if baseline_loss is not None
                else "v1 frozen pre-grow baseline (v1.1 baseline not yet produced, disclosed)"),
            "criterion_2_random_control_hurts_strictly_less": criterion_2,
            "criterion_3_identical_code_path": True,
            "note_criterion_3": ("structurally true by construction -- all four losses computed "
                                 "via the SAME eval_ce_loss() function against the SAME eval batch"),
        },
        "matched_continuation_baseline": matched_continuation_info,
        "contribution_deletion_collapses_excess": collapses,
        "real_corpus_probe": real_corpus_probe,
        "api_spend_usd": 0.0,
        "paid_api_surface_used": False,
        "invalid_tokens_present": [],
        "verdict": "S3_DELETION_ARM_COLLAPSES" if collapses else "S3_DELETION_ARM_DOES_NOT_COLLAPSE",
    }

    out_dir = args.out_dir or DEFAULT_RECEIPTS_DIR
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"c-scale-s3-deletion-arm-{stamp}.json")
    checked_write(out_path, receipt)
    print(f"[s3-deletion-arm] receipt written: {out_path}")
    print(f"[s3-deletion-arm] pre_grow={loss_pre_grow:.6f} grown={loss_grown:.6f} "
          f"ablated={loss_ablated:.6f} random_control={loss_random:.6f} collapses={collapses}")
    return 0 if collapses else 4


def _run_deletion_arm_synthetic_fallback(args, stamp: str, blocker: str) -> int:
    """Real rung-1/pre-grow checkpoints unreachable -- proves the mechanism
    end-to-end on a tiny 2-layer synthetic fixture instead (never claims real
    evidence), and reports the reachability blocker verbatim."""
    import torch
    torch.manual_seed(0)
    n_layers, hidden, vocab, ff_seed, ff_grown = 2, 16, 32, 8, 16

    def build_tiny(intermediate):
        from transformers import LlamaConfig, LlamaModel

        class _Tiny(torch.nn.Module):
            def __init__(self):
                super().__init__()
                conf = LlamaConfig(
                    vocab_size=vocab, hidden_size=hidden, intermediate_size=intermediate,
                    num_hidden_layers=n_layers, num_attention_heads=2, num_key_value_heads=2,
                    max_position_embeddings=16, tie_word_embeddings=False)
                self.backbone_model = LlamaModel(conf)
                self.head = torch.nn.Linear(hidden, vocab, bias=False)

            def logits(self, ids):
                return self.head(self.backbone_model(input_ids=ids).last_hidden_state)

        return _Tiny()

    seed_model = build_tiny(ff_seed)
    sd_seed = seed_model.state_dict()

    def widen(sd):
        grown = dict(sd)
        for i in range(n_layers):
            p = f"backbone_model.layers.{i}.mlp."
            g, u, d = sd[p + "gate_proj.weight"], sd[p + "up_proj.weight"], sd[p + "down_proj.weight"]
            grown[p + "gate_proj.weight"] = torch.cat([g, g], dim=0)
            grown[p + "up_proj.weight"] = torch.cat([u, u], dim=0)
            grown[p + "down_proj.weight"] = torch.cat([d * 0.5, d * 0.5], dim=1)
        return grown

    sd_grown = widen(sd_seed)
    sd_ablated = slice_first_half(sd_grown, n_layers, ff_seed)
    random_seed = args.random_ablation_seed
    sd_random, kept_indices = slice_random(sd_grown, n_layers, ff_seed, ff_grown, random_seed)

    x, y, batch_sha = make_eval_batch(vocab, 8, 2, args.eval_seed)

    def build_and_eval(sd, intermediate):
        model = build_tiny(intermediate)
        model.load_state_dict(sd, strict=True)
        model.eval()
        return eval_ce_loss(model, x, y)

    loss_pre_grow = build_and_eval(sd_seed, ff_seed)
    loss_grown = build_and_eval(sd_grown, ff_grown)
    loss_ablated = build_and_eval(sd_ablated, ff_seed)
    loss_random = build_and_eval(sd_random, ff_seed)

    criterion_1, criterion_2, collapses = evaluate_deletion_criteria(
        loss_pre_grow, loss_ablated, loss_random)

    receipt = {
        "ticket": "C-SCALE-S3-DELETION-ARM-SYNTHETIC-FALLBACK",
        "ts": stamp,
        "issue": ISSUE_REF,
        "schema": "c-scale-s3-deletion-arm/v1",
        "spec_ref": f"{SPEC_REF} section 2",
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
        "mode": "cpu_synthetic_fallback",
        "_synthetic_control_fixture": True,
        "reachability_blocker": blocker,
        "note": ("The REAL rung-1 (1.22B) checkpoint / pre-grow checkpoint were UNREACHABLE "
                 "from this execution -- see reachability_blocker verbatim above. This receipt "
                 "proves the deletion-arm MECHANISM (net2net-map re-slicing, cross-entropy "
                 "eval, both criteria) end-to-end on a tiny synthetic 2-layer fixture; it "
                 "carries NO physical claim about the real rung-1 model and is never evidence "
                 "for contribution_deletion_collapses_excess."),
        "growth_map": {"ff_seed": ff_seed, "ff_grown": ff_grown, "n_layers": n_layers},
        "random_ablation": {"seed": random_seed},
        "losses": {"pre_grow_terminal_loss": loss_pre_grow, "grown_loss_informational": loss_grown,
                   "ablated_loss": loss_ablated, "random_ablation_control_loss": loss_random},
        "criteria": {"criterion_1_ablated_loss_gte_pre_grow": criterion_1,
                     "criterion_2_random_control_hurts_strictly_less": criterion_2},
        "contribution_deletion_collapses_excess": collapses,
        "api_spend_usd": 0.0, "paid_api_surface_used": False, "invalid_tokens_present": [],
        "verdict": "S3_DELETION_ARM_SYNTHETIC_FALLBACK",
    }
    out_dir = os.path.join(DEFAULT_SANDBOX, "deletion-arm-fallback")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"c-scale-s3-deletion-arm-synthetic-fallback-{stamp}.json")
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(receipt, f, indent=2)
    print(f"[s3-deletion-arm] REACHABILITY BLOCKER: {blocker}")
    print(f"[s3-deletion-arm] synthetic fallback receipt written: {out_path}")
    return 3


# ---------------------------------------------------------------------------
# --working-set mode (spec section 3)
# ---------------------------------------------------------------------------

def refuse_unless_gpu_authorized(args) -> None:
    """Mirrors scripts/w1_collapse_control_run.py's refuse_unless_dry_run_safe
    exactly -- the interlock idiom for GPU-real work this builder never fires."""
    if not args.live and args.device == "cpu":
        return
    authorized = os.environ.get("EMBER_GATE_AUTHORIZED", "") == "1"
    if not (authorized and args.live and args.device == "cuda"):
        msg = ("S3_WORKING_SET_LAUNCH_INTERLOCK_REFUSED: real/GPU path blocked. Requires "
               "EMBER_GATE_AUTHORIZED=1 (env) AND --live AND --device cuda. The real "
               "working-set measurement is a GPU-window leg (spec section 3), maintainer-"
               "window-scheduled; never fired by this builder. "
               f"[authorized={authorized}, live={args.live}, device={args.device}]")
        print(msg)
        raise SystemExit(msg)


def run_working_set(args) -> int:
    refuse_unless_gpu_authorized(args)
    # issue #83: reaching here with --live --device cuda means
    # EMBER_GATE_AUTHORIZED=1 was just verified above -- an authorized
    # invocation must run the REAL leg or hard-refuse with a named wall,
    # never silently fall through to the CPU dry-run receipt (the bug this
    # issue reports: this branch used to call run_working_set_dry_run()
    # unconditionally here).
    if args.live and args.device == "cuda":
        return run_working_set_live(args)
    # --live/--device cuda was never requested -- CPU dry-run only, ever,
    # from this path (byte-identical to the pre-#83 behavior).
    return run_working_set_dry_run(args)


def run_working_set_dry_run(args) -> int:
    import psutil
    import torch

    stamp = ts()
    proc = psutil.Process(os.getpid())

    # Instrumented pass proof: a small resident model + forward pass, so the
    # receipt measures something real (host RSS/peak-working-set delta), not
    # a fabricated number. Tiny by design -- PIPELINE PROOF, not a real
    # device working-set measurement (spec section 3 requires CUDA peak-
    # allocated tracking, GPU-window work, never fired here).
    torch.manual_seed(0)
    vocab, hidden, layers, seq, batch = 512, 64, 4, 64, 4
    embed = torch.nn.Embedding(vocab, hidden)
    blocks = [torch.nn.Linear(hidden, hidden) for _ in range(layers)]
    ids = torch.randint(0, vocab, (batch, seq))
    with torch.no_grad():
        h = embed(ids)
        for blk in blocks:
            h = torch.relu(blk(h))

    mem_info = proc.memory_info()
    host_peak_bytes = getattr(mem_info, "peak_wset", None)
    peak_source = "psutil Process.memory_info().peak_wset (Windows peak working-set)"
    if host_peak_bytes is None:
        host_peak_bytes = mem_info.rss
        peak_source = "psutil Process.memory_info().rss (peak_wset unavailable on this platform)"

    governor_cfg_path = os.path.join(args.cross_root or CROSS_REPO_DEFAULT,
                                      "configs", "v0-pretrain-config.json")
    governor_note = None
    if os.path.isfile(governor_cfg_path):
        gcfg = load_json(governor_cfg_path)
        vram_fraction = (gcfg.get("governor") or {}).get("vram_fraction")
        governor_note = (f"governor.vram_fraction={vram_fraction} from {governor_cfg_path} "
                         "(cited convention; NOT applied here -- no device is touched on this path)")

    receipt = {
        "ticket": "C-SCALE-S3-WORKING-SET-DRYRUN",
        "ts": stamp,
        "issue": ISSUE_REF,
        "schema": "c-scale-s3-working-set/v1",
        "spec_ref": f"{SPEC_REF} section 3",
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
        "mode": "cpu_dry_run",
        "dry_run": True,
        "device": "cpu",
        "note": ("PIPELINE-PROOF ONLY: measures HOST peak working-set bytes (psutil) around a "
                 "tiny instrumented forward pass -- never a device/CUDA measurement. The real "
                 "leg (spec section 3: resident weight bytes + peak activation bytes + KV "
                 "bytes, CUDA peak-allocated tracking around a governed serving forward pass) "
                 "is GPU-window work, maintainer-scheduled, never fired by this builder (see "
                 "the launch interlock refusal on the --live --device cuda path)."),
        "host_peak_working_set_bytes": host_peak_bytes,
        "host_peak_working_set_source": peak_source,
        "active_working_set_bytes": "UNPRODUCIBLE_DRY_RUN_ONLY",
        "device_working_set_floor_bytes": "UNPRODUCIBLE_DRY_RUN_ONLY",
        "device_working_set_floor_formula": ("cap_fraction * device_vram_total_bytes "
                                             "(torch.cuda.mem_get_info(), governor.env_limits() "
                                             "convention -- scripts/timeshare_pretrain.py "
                                             "_apply_governor()) -- formula only, never computed "
                                             "here (no device touched)"),
        "governor_config_citation": governor_note,
        "api_spend_usd": 0.0,
        "paid_api_surface_used": False,
        "invalid_tokens_present": [],
        "verdict": "S3_WORKING_SET_DRYRUN_PIPELINE_PROVEN",
    }
    out_dir = args.out_dir or DEFAULT_RECEIPTS_DIR
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"c-scale-s3-working-set-dryrun-{stamp}.json")
    checked_write(out_path, receipt)
    print(f"[s3-working-set] dry-run receipt written: {out_path}")
    print(f"[s3-working-set] host_peak_working_set_bytes={host_peak_bytes}")
    return 0


def _verify_config_and_governor(cross_root: str):
    """Fail-closed presence checks for the live leg's config dependencies.
    Returns (v0_config, vram_fraction, batch, seq, vocab) or raises
    SystemExit naming exactly which piece is missing -- never silently
    substitutes a default operating point."""
    config_path = os.path.join(cross_root, "configs", "v0-pretrain-config.json")
    if not os.path.isfile(config_path):
        raise SystemExit(
            f"S3_WORKING_SET_LIVE_CONFIG_MISSING: {config_path} not found -- "
            "refusing the real leg rather than fabricating an operating point")
    v0_config = load_json(config_path)
    gov = v0_config.get("governor") or {}
    vram_fraction = gov.get("vram_fraction")
    if vram_fraction is None:
        raise SystemExit(
            f"S3_WORKING_SET_LIVE_GOVERNOR_CONFIG_MISSING: {config_path} carries "
            "no governor.vram_fraction -- refusing rather than assuming a cap")
    try:
        batch = v0_config["throughput"]["batch"]
        seq = v0_config["model"]["seq"]
        vocab = v0_config["model"]["vocab"]
    except KeyError as exc:
        raise SystemExit(
            f"S3_WORKING_SET_LIVE_CONFIG_FIELD_MISSING: {config_path} missing "
            f"{exc} -- refusing rather than guessing the operating point")
    return v0_config, vram_fraction, batch, seq, vocab


def run_working_set_live(args) -> int:
    """The real leg (spec section 3, issue #83). Loads the terminal rung
    checkpoint via the SAME model-build path as training (cross-repo
    scripts/timeshare_pretrain.py's build_v0_model + _apply_governor,
    imported, never reimplemented), runs ONE governed no_grad forward pass
    at the operating point, and measures CUDA peak-allocated bytes.

    Every precondition below is fail-closed: the FIRST unmet one raises
    SystemExit with a named S3_WORKING_SET_LIVE_* wall and NOTHING is
    written -- no receipt of any kind, dry-run or live. This function is
    only ever reached from run_working_set() once refuse_unless_gpu_
    authorized() has already confirmed EMBER_GATE_AUTHORIZED=1 + --live +
    --device cuda; an authorized invocation must never silently fall
    through to the CPU dry-run receipt (the bug issue #83 reports).

    Checks are ordered cheapest/file-only first and real-CUDA-touching last,
    so every failure mode through the device assert is provable via a CPU-
    only selftest with zero CUDA allocation (see _selftest section 9)."""
    cross_root = args.cross_root or CROSS_REPO_DEFAULT
    stamp = ts()

    # 1. rung receipt discovery (terminal = highest rung number's PASS receipt)
    rung_data_by_number, rung_path_by_number = discover_rung_receipts(cross_root)
    if args.rung_receipt:
        rung_data_by_number = {1: load_json(args.rung_receipt)}
        rung_path_by_number = {1: args.rung_receipt}
    if not rung_data_by_number:
        raise SystemExit(
            "S3_WORKING_SET_LIVE_NO_RUNG_RECEIPT: no PASS cbase-grow-rung "
            f"receipt discovered under {cross_root}/receipts/cbase-grow-rung/ "
            "-- refusing the real leg rather than fabricating a measurement "
            "with no terminal checkpoint to load")
    rung_n = max(rung_data_by_number)
    rung_data = rung_data_by_number[rung_n]
    rung_path = rung_path_by_number[rung_n]

    # 2. checkpoint existence + sha (manifest.json + model.pt only -- cheap,
    #    file-based, no torch.load; reuses _verify_checkpoint unchanged)
    ckpt_dir = rung_data["stabilization_segment"]["checkpoint"]
    model_pt, err = _verify_checkpoint(ckpt_dir)
    if err:
        raise SystemExit(
            f"S3_WORKING_SET_LIVE_CHECKPOINT_INVALID: rung {rung_n} terminal "
            f"checkpoint at {ckpt_dir} failed verification: {err}")

    # 3. config + governor + operating-point presence
    v0_config, vram_fraction, batch, seq, vocab = _verify_config_and_governor(cross_root)

    # 4. device assert -- a query only, never allocates; safe to call even on
    #    a machine whose real GPU is window-occupied by another job right now
    import torch
    if not torch.cuda.is_available():
        raise SystemExit(
            "S3_WORKING_SET_LIVE_NO_CUDA_DEVICE: torch.cuda.is_available() is "
            "False on this execution -- refusing to fabricate a device "
            "measurement (the 'unreachable real inputs' wall; the real leg "
            "fires only from the maintainer's authorized GPU window)")

    # --- everything below touches real CUDA memory; never reached by this ---
    # --- builder's own selftest (blocked above at step 4), only by the    ---
    # --- maintainer's authorized GPU-window invocation.                  ---
    ff_grown = rung_data["ff_grown"]
    sys.path.insert(0, os.path.join(cross_root, "scripts"))
    import timeshare_pretrain as tsp  # cross-repo model-build path, never reimplemented

    m_state, o_state, r_state, ckpt_manifest = tsp.load_checkpoint(ckpt_dir)
    model, model_vocab, model_hidden, n_mtp = tsp.build_v0_model(
        v0_config, live=True, intermediate_override=ff_grown, device="cuda")
    missing, unexpected = model.load_state_dict(m_state, strict=False)
    real_missing = [k for k in missing if k != "head.weight"]  # tied-embedding alias, expected
    if real_missing or unexpected:
        raise SystemExit(
            f"S3_WORKING_SET_LIVE_STATE_DICT_MISMATCH: missing={real_missing} "
            f"unexpected={unexpected}")

    # governor convention, reused unchanged; raises SystemExit(TIMESHARE_
    # GOVERNOR_FAIL) on a headroom violation rather than proceeding.
    gov_receipt = tsp._apply_governor()

    model.eval()
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()
    mem_free_before, mem_total = torch.cuda.mem_get_info()
    ids = torch.randint(0, vocab, (batch, seq), device="cuda")
    with torch.no_grad():
        hidden_out = model.backbone(ids)
        _logits = model.head(hidden_out)  # full-vocab logits -- the serving shape
    torch.cuda.synchronize()
    mem_free_after, _ = torch.cuda.mem_get_info()
    active_working_set_bytes = int(torch.cuda.max_memory_allocated())

    if active_working_set_bytes <= 0:
        raise SystemExit(
            "S3_WORKING_SET_LIVE_MEASUREMENT_INVALID: torch.cuda."
            f"max_memory_allocated()={active_working_set_bytes} <= 0")

    weight_bytes = int(sum(p.numel() * p.element_size() for p in model.parameters()))
    eff_frac = gov_receipt["vram_fraction_applied"]
    device_working_set_floor_bytes = int(eff_frac * mem_total)
    fit = active_working_set_bytes <= device_working_set_floor_bytes

    receipt = {
        "ticket": "C-SCALE-S3-WORKING-SET-LIVE",
        "ts": stamp,
        "issue": ISSUE_REF,
        "schema": "c-scale-s3-working-set/v1",
        "spec_ref": f"{SPEC_REF} section 3",
        "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
        "mode": "gpu_live",
        "dry_run": False,
        "device": "cuda",
        "rung": rung_n,
        "rung_receipt_citation": {"path": rung_path, "sha256": sha256_file(rung_path)},
        "checkpoint": {"dir": ckpt_dir, "model_pt_sha256": sha256_file(model_pt)},
        "operating_point": {"batch": batch, "seq": seq, "vocab": vocab, "ff_grown": ff_grown,
                             "params_unique_after": rung_data.get("params_unique_after")},
        "note": ("ONE governed no_grad forward pass (model.eval(), full-vocab logits "
                 "materialized -- the serving shape, deliberately not training's "
                 "chunked-CE, per spec section 3's 'governed serving forward pass') "
                 "at the operating point (batch/seq from configs/v0-pretrain-"
                 "config.json); model built via cross-repo scripts/timeshare_"
                 "pretrain.py's build_v0_model(intermediate_override=ff_grown) -- "
                 "the SAME model-build path as training, never reimplemented; "
                 "governor applied via _apply_governor(), also reused unchanged."),
        "governor": gov_receipt,
        "device_mem_get_info": {"free_before_bytes": int(mem_free_before),
                                 "free_after_bytes": int(mem_free_after),
                                 "total_bytes": int(mem_total)},
        "resident_weight_bytes": weight_bytes,
        "resident_weight_bytes_derivation": ("sum(p.numel()*p.element_size() for p in "
                                              "model.parameters()) -- bf16, 2 bytes/element"),
        "active_working_set_bytes": active_working_set_bytes,
        "active_working_set_bytes_source": ("torch.cuda.max_memory_allocated(), reset via "
                                             "reset_peak_memory_stats() immediately before the "
                                             "forward pass (so the peak floor is the already-"
                                             "resident weights) -- resident weight bytes + peak "
                                             "activation/logit bytes, measured, never computed "
                                             "from shapes alone"),
        "device_working_set_floor_bytes": device_working_set_floor_bytes,
        "device_working_set_floor_formula": ("governor.vram_fraction_applied * device_vram_"
                                              "total_bytes (torch.cuda.mem_get_info()) -- the "
                                              "governor-capped budget in force during THIS "
                                              "measurement, never the raw device total"),
        "fit": fit,
        "api_spend_usd": 0.0,
        "paid_api_surface_used": False,
        "invalid_tokens_present": [],
        "verdict": "S3_WORKING_SET_LIVE_MEASURED_FIT" if fit else "S3_WORKING_SET_LIVE_MEASURED_OVER_FLOOR",
    }
    out_dir = args.out_dir or DEFAULT_RECEIPTS_DIR
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"c-scale-s3-working-set-{stamp}.json")
    checked_write(out_path, receipt)
    print(f"[s3-working-set] LIVE receipt written: {out_path}")
    print(f"[s3-working-set] active_working_set_bytes={active_working_set_bytes} "
          f"device_working_set_floor_bytes={device_working_set_floor_bytes} fit={fit}")
    return 0


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=2)


def _write_fixture_checkpoint(ckpt_dir: str, *, sha_ok: bool = True) -> None:
    """Writes a minimal manifest.json + model.pt pair for the
    run_working_set_live() assertion-ladder selftest. model.pt is arbitrary
    bytes, never a real torch tensor -- _verify_checkpoint() only checks
    manifest presence + model.pt sha256, never torch.load's it, so this stays
    torch-free and instantaneous (and is never reached past the sha check,
    since the config/device selftest fixtures below deliberately stop the
    live-leg dispatch before tsp.load_checkpoint's own torch.load calls)."""
    os.makedirs(ckpt_dir, exist_ok=True)
    model_pt_path = os.path.join(ckpt_dir, "model.pt")
    with open(model_pt_path, "wb") as f:
        f.write(b"fixture-model-bytes-not-a-real-checkpoint")
    actual_sha = sha256_file(model_pt_path)
    claimed_sha = actual_sha if sha_ok else ("0" * 64)
    with open(os.path.join(ckpt_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"files": {"model.pt": claimed_sha}}, f)


def _write_rung_fixture(receipts_dir: str, ckpt_dir: str, *, rung: int = 1,
                        ff_grown: int = 32) -> str:
    os.makedirs(receipts_dir, exist_ok=True)
    path = os.path.join(receipts_dir, f"cbase-grow-rung{rung}-live-{ts()}.json")
    _write(path, {
        "pass": True, "rung": rung, "ff_grown": ff_grown,
        "params_unique_after": 12345,
        "stabilization_segment": {"checkpoint": ckpt_dir},
    })
    return path


def _selftest() -> int:
    base = os.path.join(DEFAULT_SANDBOX, "selftest-fixtures")
    failures = []

    # ---- (1) _ratio_ok imported correctly + re-derivation both directions ----
    ok, why = _ratio_ok(2.0, 10.0, 5.0)
    if not ok:
        failures.append(f"(1a) FAIL: _ratio_ok(2.0, 10.0, 5.0) expected ok, got {why!r}")
    else:
        print("(1a) PASS: _ratio_ok re-derives a true 2x ratio")
    ok2, why2 = _ratio_ok(3.0, 10.0, 5.0)
    if ok2:
        failures.append("(1b) FAIL: _ratio_ok(3.0, 10.0, 5.0) should NOT re-derive (claimed!=derived)")
    else:
        print(f"(1b) PASS: _ratio_ok correctly rejects a non-re-deriving claim ({why2})")

    # ---- (2) FLOPs dedup self-consistency: matching case computes cleanly ----
    dedup_const = 1000
    grow_live_fixture = {"param_count_before": 5000, "param_count_after": 9000}
    rung1_fixture = {
        "params_dedup": {"measured_duplicate_numel": dedup_const},
        "params_unique_before": 9000 - dedup_const,   # matches grow_live post-grow derivation
        "params_unique_after": 15000,
    }
    pricing_fixture = {"grow_arm": {"bill_aggregation_rows": [
        {"segment": "v0-seed-pretrain", "tokens_value": 100, "receipt_path": "fixture-v0"},
        {"segment": "cbase-grow-live-pre", "tokens_value": 50, "receipt_path": "fixture-pre"},
        {"segment": "cbase-grow-live-post", "tokens_value": 50, "receipt_path": "fixture-post"},
        {"segment": "cbase-grow-rung1-stabilize", "tokens_value": 30, "receipt_path": "fixture-rung1"},
    ]}}
    rung_data = {1: rung1_fixture}
    total, rows = build_flops_segments(pricing_fixture, grow_live_fixture, dedup_const, rung_data)
    n_seed = 5000 - dedup_const
    n_post = 9000 - dedup_const
    n_rung1 = rung1_fixture["params_unique_after"]
    expected = 6.0 * n_seed * 100 + 6.0 * n_seed * 50 + 6.0 * n_post * 50 + 6.0 * n_rung1 * 30
    if abs(total - expected) > 1e-6:
        failures.append(f"(2a) FAIL: build_flops_segments total={total} != expected={expected}")
    else:
        print(f"(2a) PASS: FLOPs arithmetic matches hand-computed total ({total:.6g})")

    # ---- (2b) mismatched dedup constant refuses rather than silently emits ----
    bad_rung1 = dict(rung1_fixture)
    bad_rung1["params_unique_before"] = 999999  # deliberately inconsistent
    raised = False
    try:
        build_flops_segments(pricing_fixture, grow_live_fixture, dedup_const, {1: bad_rung1})
    except ValueError as exc:
        raised = "S3_FLOPS_DEDUP_CONSISTENCY_FAIL" in str(exc)
    if not raised:
        failures.append("(2b) FAIL: mismatched dedup constant should raise S3_FLOPS_DEDUP_CONSISTENCY_FAIL")
    else:
        print("(2b) PASS: dedup self-consistency guard refuses on a genuine mismatch")

    # ---- (3) resolve_t_dense: UNPRODUCIBLE (dry-run) / REFUTED (L3) / PRODUCED (L1) ----
    dryrun_path = os.path.join(base, "w1-collapse-control-dryrun-20990101T000000Z.json")
    _write(dryrun_path, {"dry_run": True, "is_real_lineage": False, "outcome": "L3", "ratio": 1.0})
    info_dry = resolve_t_dense(dryrun_path)
    if info_dry["status"] != "UNPRODUCIBLE":
        failures.append(f"(3a) FAIL: dry-run-only receipt should resolve UNPRODUCIBLE, got {info_dry['status']}")
    else:
        print("(3a) PASS: dry-run-only W1 receipt resolves T_dense as UNPRODUCIBLE")

    l3_path = os.path.join(base, "w1-collapse-control-l3-20990101T000001Z.json")
    _write(l3_path, {"dry_run": False, "is_real_lineage": True, "outcome": "L3", "ratio": 0.8,
                     "control_arm": {"tokens_to_match": 500}})
    info_l3 = resolve_t_dense(l3_path)
    if info_l3["status"] != "REFUTED":
        failures.append(f"(3b) FAIL: real L3 receipt should resolve REFUTED, got {info_l3['status']}")
    else:
        print("(3b) PASS: real L3-outcome W1 receipt resolves REFUTED (named negative, not unmeasured)")

    l1_path = os.path.join(base, "w1-collapse-control-l1-20990101T000002Z.json")
    _write(l1_path, {"dry_run": False, "is_real_lineage": True, "outcome": "L1", "ratio": 3.0,
                     "control_arm": {"tokens_to_match": 30000000, "tokens_at_ceiling": None}})
    info_l1 = resolve_t_dense(l1_path)
    if info_l1["status"] != "PRODUCED" or info_l1["t_dense"] != 30000000:
        failures.append(f"(3c) FAIL: real L1 receipt should resolve PRODUCED t_dense=30000000, got {info_l1}")
    else:
        print("(3c) PASS: real L1-outcome W1 receipt resolves PRODUCED with the correct T_dense")

    # ---- (3d-3g) resolve_matched_continuation_baseline (issue #85 v1.1 amendment):
    #      no-receipt / dry-run-only -> UNPRODUCIBLE; real -> PRODUCED with the loss.
    #      Each case gets its OWN dedicated subdirectory: resolve_matched_continuation_
    #      baseline globs its WHOLE receipts_dir, and `base` is a fixed scratch path that
    #      is never wiped between selftest invocations -- sharing one directory across
    #      cases let a stale fixture leak across RUNS (gate-caught defect: a leftover
    #      future-dated REAL fixture from a prior run's (3f) out-sorts a freshly-written
    #      (3e) dry-run fixture by timestamp on the next run, flipping (3e) to PRODUCED).
    #      Dedicated subdirs make every case hermetic under repeated execution.
    mc_empty_dir = os.path.join(base, "mc-3d-empty")
    os.makedirs(mc_empty_dir, exist_ok=True)
    info_mc_none = resolve_matched_continuation_baseline(mc_empty_dir)
    if info_mc_none["status"] != "UNPRODUCIBLE" or info_mc_none["baseline_loss"] is not None:
        failures.append(f"(3d) FAIL: no receipt should resolve UNPRODUCIBLE, got {info_mc_none}")
    else:
        print("(3d) PASS: no matched-continuation receipt resolves UNPRODUCIBLE")

    mc_dryrun_dir = os.path.join(base, "mc-3e-dryrun-only")
    mc_dryrun_path = os.path.join(mc_dryrun_dir, "c-scale-s3-matched-continuation-20990101T000000Z.json")
    _write(mc_dryrun_path, {"dry_run": True, "is_real_lineage": False,
                            "losses": {"matched_continuation_eval_loss": 1.23}})
    info_mc_dry = resolve_matched_continuation_baseline(mc_dryrun_dir)
    if info_mc_dry["status"] != "UNPRODUCIBLE":
        failures.append(f"(3e) FAIL: dry-run-only receipt should resolve UNPRODUCIBLE, got {info_mc_dry}")
    else:
        print("(3e) PASS: dry-run-only matched-continuation receipt resolves UNPRODUCIBLE")

    mc_real_dir = os.path.join(base, "mc-3f-real")
    mc_real_path = os.path.join(mc_real_dir, "c-scale-s3-matched-continuation-20990101T000001Z.json")
    _write(mc_real_path, {"dry_run": False, "is_real_lineage": True,
                          "losses": {"matched_continuation_eval_loss": 2.71}})
    info_mc_real = resolve_matched_continuation_baseline(mc_real_dir)
    if info_mc_real["status"] != "PRODUCED" or info_mc_real["baseline_loss"] != 2.71:
        failures.append(f"(3f) FAIL: real receipt should resolve PRODUCED baseline_loss=2.71, got {info_mc_real}")
    else:
        print("(3f) PASS: real matched-continuation receipt resolves PRODUCED with its eval loss")

    mc_multi_dir = os.path.join(base, "mc-3g-multi-picks-latest")
    _write(os.path.join(mc_multi_dir, "c-scale-s3-matched-continuation-20990101T000000Z.json"),
           {"dry_run": True, "is_real_lineage": False, "losses": {"matched_continuation_eval_loss": 1.23}})
    _write(os.path.join(mc_multi_dir, "c-scale-s3-matched-continuation-20990101T000001Z.json"),
           {"dry_run": False, "is_real_lineage": True, "losses": {"matched_continuation_eval_loss": 2.71}})
    info_mc_multi = resolve_matched_continuation_baseline(mc_multi_dir)
    if info_mc_multi["status"] != "PRODUCED" or info_mc_multi["baseline_loss"] != 2.71:
        failures.append(f"(3g) FAIL: with both a stale dry-run and a later real receipt present, "
                        f"the LATEST (real) one should win, got {info_mc_multi}")
    else:
        print("(3g) PASS: with both fixtures present in one directory, the LATEST-by-timestamp "
              "(real) receipt wins (_latest_by_compact_ts reuse confirmed) -- isolated to its own "
              "dedicated directory, never shared with (3e)/(3f) or across repeated selftest runs")

    # ---- (4) --flops end-to-end through a sandboxed fixture tree ----
    flops_root = os.path.join(base, "flops-e2e")
    fixture_pricing = os.path.join(flops_root, "w1-pricing-fixture.json")
    fixture_grow_live = os.path.join(flops_root, "cbase-grow-live-fixture.json")
    fixture_rung1 = os.path.join(flops_root, "cbase-grow-rung1-fixture.json")
    _write(fixture_pricing, pricing_fixture)
    _write(fixture_grow_live, grow_live_fixture)
    _write(fixture_rung1, rung1_fixture)

    class _Args:
        pass
    fargs = _Args()
    fargs.pricing_receipt = fixture_pricing
    fargs.grow_live_receipt = fixture_grow_live
    fargs.rung_receipt = fixture_rung1
    fargs.cross_root = flops_root
    fargs.out_dir = os.path.join(flops_root, "receipts")
    fargs.w1_control_receipt = l1_path
    fargs.t_dense_override = None
    rc = run_flops(fargs)
    out_receipts = glob.glob(os.path.join(fargs.out_dir, "c-scale-s3-flops-*.json"))
    if rc != 0 or not out_receipts:
        failures.append(f"(4) FAIL: --flops end-to-end did not produce a receipt (rc={rc})")
    else:
        rdata = load_json(out_receipts[-1])
        if rdata["verdict"] != "S3_FLOPS_PRODUCED" or not isinstance(rdata["capability_per_compute_ratio"], (int, float)):
            failures.append(f"(4) FAIL: --flops e2e receipt did not resolve PRODUCED as expected: {rdata['verdict']}")
        else:
            print(f"(4) PASS: --flops end-to-end fixture run resolves PRODUCED, "
                  f"ratio={rdata['capability_per_compute_ratio']}")

    # ---- (5) --t-dense-override writes a synthetic, never-receipts-dir proof ----
    fargs2 = _Args()
    fargs2.pricing_receipt = fixture_pricing
    fargs2.grow_live_receipt = fixture_grow_live
    fargs2.rung_receipt = fixture_rung1
    fargs2.cross_root = flops_root
    fargs2.out_dir = os.path.join(flops_root, "receipts")
    fargs2.w1_control_receipt = dryrun_path  # UNPRODUCIBLE via real discovery
    fargs2.t_dense_override = 12345.0
    run_flops(fargs2)
    override_paths = glob.glob(os.path.join(DEFAULT_SANDBOX, "flops-tdense-override", "*.json"))
    if not override_paths:
        failures.append("(5) FAIL: --t-dense-override did not write a synthetic proof file")
    else:
        odata = load_json(sorted(override_paths)[-1])
        if not odata.get("_synthetic_control_fixture") or not odata.get("t_dense_override"):
            failures.append("(5) FAIL: override receipt missing self-declaration flags")
        elif odata["verdict"] != "S3_FLOPS_TDENSE_OVERRIDE_RATIO_MATH_PROVEN":
            failures.append(f"(5) FAIL: override ratio math did not prove out: {odata['verdict']}")
        else:
            print("(5) PASS: --t-dense-override proves the ratio math, self-declares synthetic, "
                  "writes under scratch/ never receipts/")

    # ---- (6) deletion-arm criteria logic, BOTH directions ----
    c1, c2, collapses = evaluate_deletion_criteria(loss_pre_grow=2.0, loss_ablated=3.5, loss_random=2.2)
    if not (c1 and c2 and collapses):
        failures.append(f"(6a) FAIL: collapse-holds fixture should pass both criteria, got c1={c1} c2={c2}")
    else:
        print("(6a) PASS: collapse-holds fixture (ablated >> pre-grow, random << ablated) -> True")

    c1b, c2b, collapses_b = evaluate_deletion_criteria(loss_pre_grow=2.0, loss_ablated=3.5, loss_random=3.6)
    if collapses_b or c2b:
        failures.append(f"(6b) FAIL: attribution-defeated fixture should fail criterion 2, got c1={c1b} c2={c2b}")
    else:
        print("(6b) PASS: attribution-defeated fixture (random control hurts >= ablated) -> "
              "criterion_2 False, collapses False")

    # ---- (6c-6d) baseline_loss (issue #85 v1.1 amendment): overrides criterion 1
    #      when given; omitted/None leaves v1 behavior (loss_pre_grow) unchanged ----
    c1c, _c2c, collapses_c = evaluate_deletion_criteria(
        loss_pre_grow=2.0, loss_ablated=3.5, loss_random=2.2, baseline_loss=4.0)
    if c1c or collapses_c:
        failures.append(f"(6c) FAIL: baseline_loss=4.0 > loss_ablated=3.5 should flip criterion_1 "
                        f"False, got c1={c1c} collapses={collapses_c}")
    else:
        print("(6c) PASS: baseline_loss overrides criterion_1's comparison point "
              "(ablated < matched-continuation baseline -> criterion_1 False)")

    c1d, c2d, collapses_d = evaluate_deletion_criteria(
        loss_pre_grow=2.0, loss_ablated=3.5, loss_random=2.2, baseline_loss=None)
    if (c1d, c2d, collapses_d) != (c1, c2, collapses):
        failures.append(f"(6d) FAIL: baseline_loss=None should reproduce v1 (6a) result exactly, "
                        f"got {(c1d, c2d, collapses_d)} vs {(c1, c2, collapses)}")
    else:
        print("(6d) PASS: baseline_loss=None (or omitted) reproduces v1 behavior exactly -- backward compatible")

    # ---- (7) --deletion-arm end-to-end mechanism proof (synthetic fallback path) ----
    class _DArgs:
        pass
    dargs = _DArgs()
    dargs.cross_root = os.path.join(base, "nonexistent-cross-root")  # guaranteed unreachable
    dargs.grow_live_receipt = os.path.join(dargs.cross_root, "receipts", "cbase-grow-live", "none.json")
    dargs.rung_receipt = None
    dargs.out_dir = os.path.join(base, "deletion-arm-e2e", "receipts")
    dargs.eval_seed = 42
    dargs.eval_batch = 2
    dargs.eval_seqlen = 8
    dargs.random_ablation_seed = 1337
    rc_d = run_deletion_arm(dargs)
    fallback_paths = glob.glob(os.path.join(DEFAULT_SANDBOX, "deletion-arm-fallback", "*.json"))
    if not fallback_paths:
        failures.append("(7) FAIL: --deletion-arm synthetic-fallback did not write a receipt")
    else:
        ddata = load_json(sorted(fallback_paths)[-1])
        if not ddata.get("_synthetic_control_fixture") or "reachability_blocker" not in ddata:
            failures.append("(7) FAIL: deletion-arm fallback receipt missing synthetic/blocker disclosure")
        elif "criteria" not in ddata or "contribution_deletion_collapses_excess" not in ddata:
            failures.append("(7) FAIL: deletion-arm fallback receipt missing criteria/verdict fields")
        else:
            print(f"(7) PASS: --deletion-arm synthetic-fallback mechanism proof end-to-end "
                  f"(rc={rc_d}, collapses={ddata['contribution_deletion_collapses_excess']})")

    # ---- (8) --working-set: dry-run schema + GPU interlock refusal ----
    class _WArgs:
        pass
    wargs = _WArgs()
    wargs.live = False
    wargs.device = "cpu"
    wargs.cross_root = CROSS_REPO_DEFAULT
    wargs.out_dir = os.path.join(base, "working-set-e2e", "receipts")
    rc_w = run_working_set(wargs)
    wpaths = glob.glob(os.path.join(wargs.out_dir, "c-scale-s3-working-set-dryrun-*.json"))
    if rc_w != 0 or not wpaths:
        failures.append(f"(8a) FAIL: --working-set --dry-run did not produce a receipt (rc={rc_w})")
    else:
        wdata = load_json(wpaths[-1])
        if not wdata.get("dry_run") or not isinstance(wdata.get("host_peak_working_set_bytes"), int):
            failures.append("(8a) FAIL: working-set dry-run receipt missing dry_run/host_peak fields")
        else:
            print(f"(8a) PASS: --working-set --dry-run schema correct "
                  f"(host_peak_working_set_bytes={wdata['host_peak_working_set_bytes']})")

    wargs2 = _WArgs()
    wargs2.live = True
    wargs2.device = "cuda"
    wargs2.cross_root = CROSS_REPO_DEFAULT
    wargs2.out_dir = os.path.join(base, "working-set-e2e", "receipts")
    prior_env = os.environ.pop("EMBER_GATE_AUTHORIZED", None)
    raised_interlock = False
    try:
        run_working_set(wargs2)
    except SystemExit as exc:
        raised_interlock = "S3_WORKING_SET_LAUNCH_INTERLOCK_REFUSED" in str(exc)
    finally:
        if prior_env is not None:
            os.environ["EMBER_GATE_AUTHORIZED"] = prior_env
    if not raised_interlock:
        failures.append("(8b) FAIL: unauthorized --live --device cuda should refuse via SystemExit")
    else:
        print("(8b) PASS: --working-set --live --device cuda refuses without EMBER_GATE_AUTHORIZED=1")

    # ---- (9) --working-set --live --device cuda (issue #83): assertion ladder ----
    # fails closed at every precondition, CPU-only, ZERO real CUDA allocation --
    # the device-assert case is forced via a monkeypatch of torch.cuda.is_available
    # so it is deterministic regardless of this machine's real hardware state (the
    # real GPU may be window-occupied by another job right now).
    ws_live_base = os.path.join(base, "working-set-live")

    class _WLArgs:
        pass

    def _mk_wl_args(cross_root, out_dir, rung_receipt=None):
        a = _WLArgs()
        a.live = True
        a.device = "cuda"
        a.cross_root = cross_root
        a.out_dir = out_dir
        a.rung_receipt = rung_receipt
        return a

    def _run_and_capture(a):
        try:
            run_working_set(a)
            return False, ""
        except SystemExit as exc:
            return True, str(exc)

    prior_gate_env = os.environ.get("EMBER_GATE_AUTHORIZED")
    os.environ["EMBER_GATE_AUTHORIZED"] = "1"
    try:
        # (9a) no rung receipt discoverable under cross_root at all
        norung_root = os.path.join(ws_live_base, "no-rung-receipt")
        os.makedirs(os.path.join(norung_root, "receipts", "cbase-grow-rung"), exist_ok=True)
        raised, msg = _run_and_capture(_mk_wl_args(norung_root, os.path.join(norung_root, "out")))
        if not (raised and "S3_WORKING_SET_LIVE_NO_RUNG_RECEIPT" in msg):
            failures.append(f"(9a) FAIL: missing rung receipt should refuse named wall, got raised={raised} msg={msg!r}")
        else:
            print("(9a) PASS: no discoverable rung receipt -> S3_WORKING_SET_LIVE_NO_RUNG_RECEIPT")

        # (9b) bad checkpoint sha (manifest declares a sha the model.pt bytes don't match)
        badsha_root = os.path.join(ws_live_base, "bad-sha")
        ckpt_dir_b = os.path.join(badsha_root, "models", "ckpt")
        _write_fixture_checkpoint(ckpt_dir_b, sha_ok=False)
        rr_b = _write_rung_fixture(os.path.join(badsha_root, "receipts", "cbase-grow-rung"), ckpt_dir_b)
        raised, msg = _run_and_capture(
            _mk_wl_args(badsha_root, os.path.join(badsha_root, "out"), rung_receipt=rr_b))
        if not (raised and "S3_WORKING_SET_LIVE_CHECKPOINT_INVALID" in msg):
            failures.append(f"(9b) FAIL: bad checkpoint sha should refuse named wall, got raised={raised} msg={msg!r}")
        else:
            print("(9b) PASS: checkpoint sha mismatch -> S3_WORKING_SET_LIVE_CHECKPOINT_INVALID")

        # (9c) valid checkpoint, missing configs/v0-pretrain-config.json
        noconfig_root = os.path.join(ws_live_base, "no-config")
        ckpt_dir_c = os.path.join(noconfig_root, "models", "ckpt")
        _write_fixture_checkpoint(ckpt_dir_c, sha_ok=True)
        rr_c = _write_rung_fixture(os.path.join(noconfig_root, "receipts", "cbase-grow-rung"), ckpt_dir_c)
        raised, msg = _run_and_capture(
            _mk_wl_args(noconfig_root, os.path.join(noconfig_root, "out"), rung_receipt=rr_c))
        if not (raised and "S3_WORKING_SET_LIVE_CONFIG_MISSING" in msg):
            failures.append(f"(9c) FAIL: missing config should refuse named wall, got raised={raised} msg={msg!r}")
        else:
            print("(9c) PASS: missing configs/v0-pretrain-config.json -> S3_WORKING_SET_LIVE_CONFIG_MISSING")

        # (9d) valid checkpoint + valid config, but no CUDA device reachable --
        # forced via monkeypatch (never relies on this machine's real GPU state),
        # so this is the "unreachable real inputs" wall AND proves zero receipts
        # (dry-run or live) are ever written on a live-leg refusal -- no silent
        # downgrade.
        nocuda_root = os.path.join(ws_live_base, "no-cuda")
        ckpt_dir_d = os.path.join(nocuda_root, "models", "ckpt")
        _write_fixture_checkpoint(ckpt_dir_d, sha_ok=True)
        rr_d = _write_rung_fixture(os.path.join(nocuda_root, "receipts", "cbase-grow-rung"), ckpt_dir_d)
        _write(os.path.join(nocuda_root, "configs", "v0-pretrain-config.json"), {
            "governor": {"vram_fraction": 0.8},
            "throughput": {"batch": 2}, "model": {"seq": 8, "vocab": 32},
        })
        import torch as _torch_probe
        _orig_is_available = _torch_probe.cuda.is_available
        _torch_probe.cuda.is_available = lambda: False
        try:
            raised, msg = _run_and_capture(
                _mk_wl_args(nocuda_root, os.path.join(nocuda_root, "out"), rung_receipt=rr_d))
        finally:
            _torch_probe.cuda.is_available = _orig_is_available
        wrote_any = glob.glob(os.path.join(nocuda_root, "out", "*.json"))
        if not (raised and "S3_WORKING_SET_LIVE_NO_CUDA_DEVICE" in msg):
            failures.append(f"(9d) FAIL: unreachable CUDA device should refuse named wall, got raised={raised} msg={msg!r}")
        elif wrote_any:
            failures.append(f"(9d) FAIL: authorized-live refusal must never write ANY receipt "
                             f"(dry-run or live) -- silent downgrade banned; found {wrote_any}")
        else:
            print("(9d) PASS: no CUDA device reachable -> S3_WORKING_SET_LIVE_NO_CUDA_DEVICE, "
                  "zero receipts written (no silent dry-run downgrade)")
    finally:
        if prior_gate_env is not None:
            os.environ["EMBER_GATE_AUTHORIZED"] = prior_gate_env
        else:
            os.environ.pop("EMBER_GATE_AUTHORIZED", None)

    # ---- (10) dry-run regression: schema byte-identical to the pre-#83 reference ----
    dryrun_regression_dir = os.path.join(base, "working-set-dryrun-regression", "receipts")
    wargs3 = _WArgs()
    wargs3.live = False
    wargs3.device = "cpu"
    wargs3.cross_root = CROSS_REPO_DEFAULT
    wargs3.out_dir = dryrun_regression_dir
    rc_dry = run_working_set(wargs3)
    dry_paths = sorted(glob.glob(os.path.join(dryrun_regression_dir, "c-scale-s3-working-set-dryrun-*.json")))
    reference_path = os.path.join(REPO, "receipts", "ember-c-scale",
                                   "c-scale-s3-working-set-dryrun-20260704T085126Z.json")
    if rc_dry != 0 or not dry_paths:
        failures.append(f"(10) FAIL: --working-set --dry-run regression did not produce a receipt (rc={rc_dry})")
    elif not os.path.isfile(reference_path):
        failures.append(f"(10) FAIL: reference receipt not found at {reference_path}")
    else:
        new_data = load_json(dry_paths[-1])
        ref_data = load_json(reference_path)
        # Exclude the two fields that legitimately vary run-to-run (timestamp,
        # host peak working-set bytes) -- the FIELD SET is the schema.
        volatile = {"ts", "host_peak_working_set_bytes"}
        new_fields = set(new_data) - volatile
        ref_fields = set(ref_data) - volatile
        if new_fields != ref_fields:
            failures.append(
                f"(10) FAIL: dry-run receipt schema drifted -- only-in-new={new_fields - ref_fields} "
                f"only-in-reference={ref_fields - new_fields}")
        else:
            print(f"(10) PASS: --working-set --dry-run receipt schema byte-identical to the "
                  f"pre-#83 reference ({sorted(new_fields)})")

    if failures:
        for f in failures:
            print(f"SELFTEST: {f}")
        return 1
    print("C_SCALE_S3_PRODUCER_SELFTEST_PASS")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--flops", action="store_true")
    mode.add_argument("--deletion-arm", action="store_true")
    mode.add_argument("--working-set", action="store_true")
    mode.add_argument("--selftest", action="store_true")

    ap.add_argument("--root", default=REPO)
    ap.add_argument("--cross-root", default=CROSS_REPO_DEFAULT)
    ap.add_argument("--out-dir", default=None)

    # --flops
    ap.add_argument("--pricing-receipt", default=None)
    ap.add_argument("--rung-receipt", default=None)
    ap.add_argument("--grow-live-receipt", default=None)
    ap.add_argument("--v0-receipt", default=None)
    ap.add_argument("--w1-control-receipt", default=None)
    ap.add_argument("--t-dense-override", type=float, default=None,
                     help="SYNTHETIC/selftest-only: proves the ratio math, never real evidence")

    # --deletion-arm
    ap.add_argument("--eval-seed", type=int, default=42)
    ap.add_argument("--eval-batch", type=int, default=2)
    ap.add_argument("--eval-seqlen", type=int, default=128)
    ap.add_argument("--random-ablation-seed", type=int, default=1337)

    # --working-set
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    ap.add_argument("--dry-run", action="store_true")

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.selftest:
        return _selftest()
    if args.flops:
        return run_flops(args)
    if args.deletion_arm:
        return run_deletion_arm(args)
    if args.working_set:
        return run_working_set(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
