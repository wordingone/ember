#!/usr/bin/env python3
"""c5c_readout.py -- C5(c) W-statistic readout grammar (issue #628; spec refs:
issue #123 comment 4929556629 "C5 mechanism-readout pre-registration v1" (the
SUPERSEDED two-point marginal-CI grammar) and issue #123 comment 4928342201
"F1-F4 falsifier fill" (the shared CI/bootstrap machinery this reuses -- paired
cluster-resampled bootstrap, B=10000, rng_seed=20260709). CPU-only: no model
loads, no GPU, no torch import.

docs/authority/GOAL.md C5(c): "a receipted scaling trend shows the gap to the dense control
WIDENING with scale -- a shrinking gap is the toy-model failure state, named."

DEFECT (independent-audit disposition, issue #628, reproduced verbatim below):
the registered two-point rule -- "C5(c) HOLDS (directionally) iff gap_claim >
gap_cheap with both gaps individually CI-resolved (lower bound > 0)" (issue
#123, comment 4929556629) -- does not actually test WIDENING. Counterexample:

    cheap = 0.20, CI95 = [0.01, 0.39]
    claim = 0.21, CI95 = [0.01, 0.41]
    -> both individually CI-resolved AND claim > cheap -> old rule says HOLDS.

    But W = gap_claim - gap_cheap = 0.01 has its OWN CI95 = [-0.27, +0.29] --
    straddles zero. Marginal CIs omit cross-rung covariance/uncertainty; W is
    not identifiable from the two marginal fields alone.

FROZEN CURE (issue #628, adopted per the #123 audit-lane disposition):
  (1) two points report DIRECTIONAL-ONLY; C5(c) itself stays UNRESOLVED.
  (2) W = gap_claim - gap_cheap, with its OWN joint cluster/seed bootstrap CI95.
        CI95(W).lower > 0  -> endpoint WIDENING
        CI95(W).upper < 0  -> endpoint SHRINKING (kills C5(c) outright)
        straddle           -> INCONCLUSIVE
  (3) constitutional clearance (a real C5(c) HOLDS) additionally requires a
      THIRD preregistered rung + a positive-slope / monotone-widening
      criterion WITH uncertainty (every step's widening itself CI-resolved,
      never just point-compared). Strengthening-only, acting-operator default
      (weakening any existing threshold would need operator word; this does
      not weaken anything -- it only adds ways for C5(c) to fail to clear).
  (4) all F1/F2/F3 falsifier gates are UNCHANGED and untouched by this module
      -- this is a pure C5(c) sub-clause reading, orthogonal to F1-F3.

STATUS AT THIS PR: this module NEVER scores a real governed run -- none has
launched as of issue #628 (queue #591 row 5 remains BLOCKED on A1/A3/Q6). It
is pre-launch readout machinery, parallel to the other scripts/c8_prelaunch/
tools (O2 compute_mde.py, O4 f2_schedule_generator.py, O5 run_ledger.py).

INPUT CONTRACT (new -- no prior schema existed for this; documented here so
a future caller feeding real per-cluster deltas has an exact target): a rung
is a list of row dicts `{"cluster": <str>, "seed": <str|int>, "delta": <float>}`
where `delta` is the SIGNED paired per-row delta (positive = gated arm
better, matching the #123 fill's delta_i convention), `cluster` is the
document/shard-family resampling unit (#123 fill: "cluster-resampled at the
document/shard-family level"), and `seed` is the training seed the row came
from (nested seed x row resampling, #123 fill: "seed-clustered/nested
bootstrap over (seed x row)"). The joint W bootstrap (point 2) additionally
REQUIRES the cheap-rung and claim-rung row sets to share the same cluster ids
-- both rungs are scored on the identical frozen held-out suite (#123 fill
suite (a)), so cluster-level noise is correlated across rungs; resampling
clusters independently per rung would discard exactly the covariance the
issue #628 counterexample says the marginal-CI grammar omits.

USAGE
-----
    python c5c_readout.py --selftest
"""
import random
import sys

DEFAULT_N_RESAMPLES = 10000
DEFAULT_SEED = 20260709  # the #123 falsifier-fill's pinned bootstrap RNG seed


# ---------------------------------------------------------------------------
# SUPERSEDED v1 grammar (issue #123, comment 4929556629) -- kept ONLY to
# regression-test the counterexample it fails on (issue #628). Never call
# this for a real C5(c) verdict.
# ---------------------------------------------------------------------------

def marginal_two_point_rule_SUPERSEDED(gap_cheap, ci_cheap, gap_claim, ci_claim):
    """The registered v1 two-point rule (issue #123, comment 4929556629):
    'C5(c) HOLDS (directionally) iff gap_claim > gap_cheap with both gaps
    individually CI-resolved (lower bound > 0)'.

    SUPERSEDED by issue #628 -- this function is preserved verbatim, unused
    in any real verdict path, ONLY so the counterexample it fails on stays
    an executable regression test forever.
    """
    cheap_resolved = ci_cheap[0] > 0.0
    claim_resolved = ci_claim[0] > 0.0
    holds = bool(claim_resolved and cheap_resolved and gap_claim > gap_cheap)
    return "HOLDS" if holds else "UNRESOLVED"


# ---------------------------------------------------------------------------
# Point 2: the W-statistic decision rule (pure, given a precomputed CI)
# ---------------------------------------------------------------------------

def verdict_from_w(w_point: float, ci_lo: float, ci_hi: float) -> str:
    """issue #628 point 2, verbatim:
      CI95(W).lower > 0 -> WIDENING
      CI95(W).upper < 0 -> SHRINKING
      straddle          -> INCONCLUSIVE
    """
    if ci_lo > 0.0:
        return "WIDENING"
    if ci_hi < 0.0:
        return "SHRINKING"
    return "INCONCLUSIVE"


# ---------------------------------------------------------------------------
# Joint cluster/seed bootstrap (reuses the #123 falsifier-fill's own frozen
# CI procedure shape: cluster-resampled at the document/shard-family level,
# nested seed x row, B=10000, rng_seed=20260709).
# ---------------------------------------------------------------------------

def _group_by_cluster(rows):
    """rows: list of {'cluster': str, 'seed': str|int, 'delta': float}.
    Returns {cluster: {seed: [deltas]}} -- nested cluster -> seed -> values."""
    by_cluster = {}
    for r in rows:
        c = r["cluster"]
        s = r["seed"]
        by_cluster.setdefault(c, {}).setdefault(s, []).append(float(r["delta"]))
    return by_cluster


def _point_gap(rows) -> float:
    """Point estimate: mean over all rows' signed per-row deltas."""
    vals = [float(r["delta"]) for r in rows]
    if not vals:
        raise ValueError("_point_gap: no rows")
    return sum(vals) / len(vals)


def _resample_gap_for_clusters(by_cluster: dict, drawn_clusters: list, rng: random.Random) -> float:
    """Given a list of already-drawn cluster ids (with repeats), resample
    each cluster's seed groups (nested), then each seed's rows, and pool the
    result into one gap estimate. Shared by the marginal and joint bootstraps
    so both use the identical resampling unit (cluster, then seed, then row)."""
    pooled = []
    for c in drawn_clusters:
        seed_groups = by_cluster.get(c)
        if not seed_groups:
            continue
        seeds = list(seed_groups.keys())
        drawn_seeds = [rng.choice(seeds) for _ in range(len(seeds))]
        for s in drawn_seeds:
            vals = seed_groups[s]
            pooled.extend(rng.choice(vals) for _ in vals)
    if not pooled:
        return 0.0
    return sum(pooled) / len(pooled)


def bootstrap_gap_ci(rows, n_resamples=DEFAULT_N_RESAMPLES, seed=DEFAULT_SEED):
    """Marginal gap point + percentile bootstrap CI95 for ONE rung, in
    isolation (no cross-rung information). This is the DIRECTIONAL-ONLY
    reporting statistic (issue #628 point 1) -- never sufficient alone for
    a C5(c) verdict.

    Returns (point, ci_lo, ci_hi).
    """
    if not rows:
        raise ValueError("bootstrap_gap_ci: no rows")
    by_cluster = _group_by_cluster(rows)
    clusters = list(by_cluster.keys())
    n_clusters = len(clusters)
    point = _point_gap(rows)
    rng = random.Random(seed)
    resamples = []
    for _ in range(n_resamples):
        drawn = [rng.choice(clusters) for _ in range(n_clusters)]
        resamples.append(_resample_gap_for_clusters(by_cluster, drawn, rng))
    ordered = sorted(resamples)
    lo = ordered[int(0.025 * n_resamples)]
    hi = ordered[min(n_resamples - 1, int(0.975 * n_resamples))]
    return point, lo, hi


def w_statistic(cheap_rows, claim_rows, n_resamples=DEFAULT_N_RESAMPLES, seed=DEFAULT_SEED):
    """issue #628 point 2: W = gap_claim - gap_cheap, with its OWN JOINT
    cluster/seed bootstrap CI -- one shared cluster draw per iteration,
    applied to BOTH rungs (they are scored on the identical frozen suite),
    so cluster-level covariance across rungs is preserved rather than
    discarded (the exact gap the marginal-CI grammar left open).

    Requires cheap_rows and claim_rows to share cluster ids (same suite).
    """
    by_cluster_cheap = _group_by_cluster(cheap_rows)
    by_cluster_claim = _group_by_cluster(claim_rows)
    clusters_cheap = set(by_cluster_cheap)
    clusters_claim = set(by_cluster_claim)
    shared_clusters = sorted(clusters_cheap & clusters_claim)
    if not shared_clusters:
        raise ValueError(
            "w_statistic: cheap_rows and claim_rows share no cluster ids -- "
            "the joint bootstrap requires both rungs scored on the same "
            "frozen suite's clusters (issue #628 point 2)"
        )

    cheap_point = _point_gap(cheap_rows)
    claim_point = _point_gap(claim_rows)
    w_point = claim_point - cheap_point

    rng = random.Random(seed)
    w_resamples = []
    for _ in range(n_resamples):
        drawn = [rng.choice(shared_clusters) for _ in range(len(shared_clusters))]
        g_cheap = _resample_gap_for_clusters(by_cluster_cheap, drawn, rng)
        g_claim = _resample_gap_for_clusters(by_cluster_claim, drawn, rng)
        w_resamples.append(g_claim - g_cheap)

    ordered = sorted(w_resamples)
    w_lo = ordered[int(0.025 * n_resamples)]
    w_hi = ordered[min(n_resamples - 1, int(0.975 * n_resamples))]
    verdict = verdict_from_w(w_point, w_lo, w_hi)
    return {
        "gap_cheap_point": cheap_point,
        "gap_claim_point": claim_point,
        "w_point": w_point,
        "w_ci95": [w_lo, w_hi],
        "n_shared_clusters": len(shared_clusters),
        "n_resamples": n_resamples,
        "seed": seed,
        "verdict": verdict,
    }


# ---------------------------------------------------------------------------
# Point 3: third-rung monotone-widening criterion, WITH uncertainty
# ---------------------------------------------------------------------------

def third_rung_trend_criterion(rung_series, n_resamples=DEFAULT_N_RESAMPLES, seed=DEFAULT_SEED):
    """issue #628 point 3: constitutional clearance for C5(c) requires >=3
    preregistered rungs with a positive-slope / monotone-widening criterion
    WITH uncertainty -- never just a point comparison. Operationalized as:
    every CONSECUTIVE rung-pair must independently pass the same W-statistic
    joint-bootstrap widening test (point 2) -- each step's widening is
    itself CI-resolved, not merely point-increasing.

    rung_series: ordered list of (rung_id, rows) for >=3 rungs, ascending scale.
    Returns {"supported": bool, "pairwise": [...], "reason": str}.
    """
    if len(rung_series) < 3:
        return {
            "supported": False,
            "pairwise": [],
            "reason": f"third_rung_trend_criterion requires >=3 rungs, got {len(rung_series)}",
        }
    pairwise = []
    all_widen = True
    for (id_a, rows_a), (id_b, rows_b) in zip(rung_series, rung_series[1:]):
        w = w_statistic(rows_a, rows_b, n_resamples=n_resamples, seed=seed)
        step_widens = w["verdict"] == "WIDENING"
        all_widen = all_widen and step_widens
        pairwise.append({"from": id_a, "to": id_b, "step_widens": step_widens, **w})
    return {
        "supported": all_widen,
        "pairwise": pairwise,
        "reason": (
            "every consecutive rung-pair widens, each CI-resolved"
            if all_widen
            else "at least one consecutive rung-pair fails to widen with CI95 lower bound > 0"
        ),
    }


# ---------------------------------------------------------------------------
# Master orchestrator -- points 1-4 combined
# ---------------------------------------------------------------------------

def c5c_readout(cheap_rows, claim_rows, third_rung_series=None,
                 n_resamples=DEFAULT_N_RESAMPLES, seed=DEFAULT_SEED):
    """Master C5(c) verdict per the issue #628 frozen cure (points 1-4).

    Returns a dict: {directional_only, gap_*_marginal, w, third_rung, status,
    note, f1_f2_f3_gates}. `status` in {"HOLDS", "FAILS", "UNRESOLVED"} --
    HOLDS is the ONLY constitutional-clearance-grade result and REQUIRES a
    third preregistered rung (point 3); two rungs alone can never produce
    HOLDS (point 1), no matter how the W verdict reads.
    """
    cheap_point, cheap_lo, cheap_hi = bootstrap_gap_ci(cheap_rows, n_resamples, seed)
    claim_point, claim_lo, claim_hi = bootstrap_gap_ci(claim_rows, n_resamples, seed + 1)
    directional_only = bool(cheap_lo > 0.0 and claim_lo > 0.0 and claim_point > cheap_point)

    w = w_statistic(cheap_rows, claim_rows, n_resamples=n_resamples, seed=seed)

    third_rung = None
    if w["verdict"] == "SHRINKING":
        status = "FAILS"
        note = ("W CI95 upper < 0 -- shrinking gap is the named toy-model failure "
                "state (kills C5(c) outright, no rescue by rung selection)")
    elif third_rung_series is None:
        status = "UNRESOLVED"
        note = ("point 1: two points give DIRECTIONAL-ONLY information; C5(c) stays "
                "unresolved without a third preregistered rung (point 3), regardless "
                f"of the two-point W verdict ({w['verdict']})")
    else:
        third_rung = third_rung_trend_criterion(third_rung_series, n_resamples=n_resamples, seed=seed)
        if w["verdict"] == "WIDENING" and third_rung["supported"]:
            status = "HOLDS"
            note = ("W CI95 lower > 0 at the two-point read AND the third-rung "
                    "monotone-widening criterion is CI-resolved at every consecutive step")
        else:
            status = "UNRESOLVED"
            note = (f"two-point W verdict={w['verdict']!r}, third-rung trend "
                    f"supported={third_rung['supported']} -- constitutional clearance not met")

    return {
        "directional_only": directional_only,
        "gap_cheap_marginal": {"point": cheap_point, "ci95": [cheap_lo, cheap_hi]},
        "gap_claim_marginal": {"point": claim_point, "ci95": [claim_lo, claim_hi]},
        "w": w,
        "third_rung": third_rung,
        "status": status,
        "note": note,
        "f1_f2_f3_gates": ("unchanged -- this readout is a pure C5(c) sub-clause reading, "
                           "orthogonal to F1-F3 (issue #628 point 4)"),
    }


# ---------------------------------------------------------------------------
# Selftest
# ---------------------------------------------------------------------------

def _rows(cluster_delta_seed_map):
    """Build a rows list from {cluster: {seed: [deltas]}} for test fixtures."""
    out = []
    for cluster, seed_map in cluster_delta_seed_map.items():
        for seed, deltas in seed_map.items():
            for d in deltas:
                out.append({"cluster": cluster, "seed": seed, "delta": d})
    return out


def _selftest() -> int:
    failures = []

    # === REPRO: the SUPERSEDED marginal two-point rule reports HOLDS on the
    # issue #628 counterexample (the defect, executable, verbatim numbers). ===
    old_verdict = marginal_two_point_rule_SUPERSEDED(0.20, (0.01, 0.39), 0.21, (0.01, 0.41))
    if old_verdict != "HOLDS":
        failures.append(
            f"REPRO FAIL: expected the SUPERSEDED marginal rule to report HOLDS "
            f"on the issue #628 counterexample, got {old_verdict!r}"
        )

    # === CURE point 2: the same case resolves to INCONCLUSIVE under the
    # W-statistic verdict rule (verbatim issue #628 numbers: W=.01, CI95[-.27,.29]). ===
    new_verdict = verdict_from_w(0.01, -0.27, 0.29)
    if new_verdict != "INCONCLUSIVE":
        failures.append(
            f"CURE FAIL: expected W-statistic verdict INCONCLUSIVE on the issue "
            f"#628 counterexample, got {new_verdict!r}"
        )

    # === verdict_from_w boundary coverage ===
    if verdict_from_w(0.10, 0.01, 0.20) != "WIDENING":
        failures.append("verdict_from_w FAIL: lower>0 should be WIDENING")
    if verdict_from_w(-0.10, -0.20, -0.01) != "SHRINKING":
        failures.append("verdict_from_w FAIL: upper<0 should be SHRINKING")
    if verdict_from_w(0.0, 0.0, 0.0) != "INCONCLUSIVE":
        failures.append("verdict_from_w FAIL: exact-zero boundary should be INCONCLUSIVE (neither > nor <)")

    # === bootstrap_gap_ci: determinism (same seed -> identical CI) ===
    fixture_rows = _rows({
        "c1": {"s1": [0.10, 0.12, 0.11], "s2": [0.09, 0.11]},
        "c2": {"s1": [0.05, 0.06], "s2": [0.04, 0.05, 0.06]},
        "c3": {"s1": [0.15, 0.14, 0.16]},
    })
    p1, lo1, hi1 = bootstrap_gap_ci(fixture_rows, n_resamples=500, seed=42)
    p2, lo2, hi2 = bootstrap_gap_ci(fixture_rows, n_resamples=500, seed=42)
    if (p1, lo1, hi1) != (p2, lo2, hi2):
        failures.append("bootstrap_gap_ci FAIL: same seed must reproduce identical (point, lo, hi)")
    if not (lo1 <= p1 <= hi1):
        failures.append(f"bootstrap_gap_ci FAIL: point {p1} not within its own CI [{lo1},{hi1}]")

    # === bootstrap_gap_ci: cluster-level resampling sanity. Same 10 raw
    # values {0,0,.1,.1,.2,.2,.3,.3,.4,.4} (real between-value spread), but
    # organized as 5 clusters of 2 duplicated rows each vs 1 cluster holding
    # all 10 -- the 5-cluster case must show a WIDER CI: the correct
    # cluster-level bootstrap sees only 5 independent units (resampling
    # WHICH cluster is drawn), while the 1-cluster case degenerates into an
    # ordinary row-level bootstrap of n=10 raw values (narrower, because it
    # wrongly treats 10 duplicated rows as 10 independent units). This
    # proves the resampling unit is the CLUSTER, not the raw row.
    many_clusters = _rows({
        "c0": {"s1": [0.0, 0.0]}, "c1": {"s1": [0.1, 0.1]}, "c2": {"s1": [0.2, 0.2]},
        "c3": {"s1": [0.3, 0.3]}, "c4": {"s1": [0.4, 0.4]},
    })  # 5 clusters x 2 duplicated rows, cluster means spread 0.0..0.4
    one_cluster = _rows({"c0": {"s1": [0.0, 0.0, 0.1, 0.1, 0.2, 0.2, 0.3, 0.3, 0.4, 0.4]}})  # same 10 values, 1 cluster
    _, lo_many, hi_many = bootstrap_gap_ci(many_clusters, n_resamples=4000, seed=7)
    _, lo_one, hi_one = bootstrap_gap_ci(one_cluster, n_resamples=4000, seed=7)
    width_many = hi_many - lo_many
    width_one = hi_one - lo_one
    if not (width_many > width_one):
        failures.append(
            f"CLUSTER-GRANULARITY FAIL: 5-cluster CI width {width_many} should exceed "
            f"1-cluster CI width {width_one} (proves cluster-level, not row-level, resampling; "
            f"5-cluster correctly sees only 5 independent units, 1-cluster wrongly sees 10)"
        )

    # === w_statistic: no shared clusters -> raises ===
    try:
        w_statistic(_rows({"a": {"s1": [0.1]}}), _rows({"b": {"s1": [0.1]}}))
        failures.append("w_statistic FAIL: expected ValueError on disjoint cluster sets")
    except ValueError:
        pass

    # === w_statistic: zero true effect -> INCONCLUSIVE (CI straddles 0) ===
    same_rows = _rows({
        "c1": {"s1": [0.10, 0.12, 0.09, 0.11], "s2": [0.11, 0.10]},
        "c2": {"s1": [0.08, 0.09, 0.10]},
        "c3": {"s1": [0.12, 0.11, 0.13, 0.10]},
        "c4": {"s1": [0.09, 0.10]},
    })
    w_zero = w_statistic(same_rows, same_rows, n_resamples=2000, seed=DEFAULT_SEED)
    if w_zero["verdict"] != "INCONCLUSIVE":
        failures.append(f"w_statistic FAIL: identical rungs should be INCONCLUSIVE, got {w_zero['verdict']} (w={w_zero})")
    if abs(w_zero["w_point"]) > 1e-12:
        failures.append(f"w_statistic FAIL: identical rungs should have w_point==0, got {w_zero['w_point']}")

    # === w_statistic: strong systematic boost, LOW per-row variance -> WIDENING ===
    claim_boosted = _rows({
        "c1": {"s1": [0.60, 0.61, 0.59, 0.60], "s2": [0.60, 0.61]},
        "c2": {"s1": [0.61, 0.60, 0.60]},
        "c3": {"s1": [0.59, 0.60, 0.61, 0.60]},
        "c4": {"s1": [0.60, 0.61]},
    })
    w_wide = w_statistic(same_rows, claim_boosted, n_resamples=2000, seed=DEFAULT_SEED)
    if w_wide["verdict"] != "WIDENING":
        failures.append(f"w_statistic FAIL: strong low-variance boost should be WIDENING, got {w_wide['verdict']} (w={w_wide})")

    # === w_statistic: strong systematic DROP -> SHRINKING ===
    claim_dropped = _rows({
        "c1": {"s1": [-0.40, -0.41, -0.39, -0.40], "s2": [-0.40, -0.41]},
        "c2": {"s1": [-0.41, -0.40, -0.40]},
        "c3": {"s1": [-0.39, -0.40, -0.41, -0.40]},
        "c4": {"s1": [-0.40, -0.41]},
    })
    w_shrink = w_statistic(same_rows, claim_dropped, n_resamples=2000, seed=DEFAULT_SEED)
    if w_shrink["verdict"] != "SHRINKING":
        failures.append(f"w_statistic FAIL: strong drop should be SHRINKING, got {w_shrink['verdict']} (w={w_shrink})")

    # === third_rung_trend_criterion: <3 rungs -> not supported ===
    two_rung_trend = third_rung_trend_criterion([("r0", same_rows), ("r1", claim_boosted)], n_resamples=500)
    if two_rung_trend["supported"] is not False or two_rung_trend["pairwise"]:
        failures.append(f"third_rung_trend_criterion FAIL: <3 rungs must be unsupported with empty pairwise, got {two_rung_trend}")

    # === third_rung_trend_criterion: 3 monotonically widening rungs -> supported ===
    claim_boosted_more = _rows({
        "c1": {"s1": [1.10, 1.11, 1.09, 1.10], "s2": [1.10, 1.11]},
        "c2": {"s1": [1.11, 1.10, 1.10]},
        "c3": {"s1": [1.09, 1.10, 1.11, 1.10]},
        "c4": {"s1": [1.10, 1.11]},
    })
    trend3 = third_rung_trend_criterion(
        [("r0", same_rows), ("r1", claim_boosted), ("r2", claim_boosted_more)],
        n_resamples=1500, seed=DEFAULT_SEED,
    )
    if trend3["supported"] is not True:
        failures.append(f"third_rung_trend_criterion FAIL: 3 monotone-widening rungs should be supported, got {trend3}")

    # === third_rung_trend_criterion: a flat (non-widening) middle step breaks it ===
    trend_flat_step = third_rung_trend_criterion(
        [("r0", same_rows), ("r1", same_rows), ("r2", claim_boosted_more)],
        n_resamples=1500, seed=DEFAULT_SEED,
    )
    if trend_flat_step["supported"] is not False:
        failures.append(f"third_rung_trend_criterion FAIL: a flat first step should break the trend, got {trend_flat_step}")

    # === c5c_readout: two rungs only -> UNRESOLVED even with a widening W (point 1) ===
    ro_two = c5c_readout(same_rows, claim_boosted, third_rung_series=None, n_resamples=1500, seed=DEFAULT_SEED)
    if ro_two["status"] != "UNRESOLVED":
        failures.append(f"c5c_readout FAIL: two-rung-only must be UNRESOLVED regardless of W verdict, got {ro_two['status']} ({ro_two})")
    if ro_two["w"]["verdict"] != "WIDENING":
        failures.append(f"c5c_readout FAIL (setup): expected the two-rung W verdict to be WIDENING in this fixture, got {ro_two['w']['verdict']}")

    # === c5c_readout: shrinking gap -> FAILS outright (no rescue by rung selection) ===
    ro_shrink = c5c_readout(same_rows, claim_dropped,
                             third_rung_series=[("r0", same_rows), ("r1", claim_dropped), ("r2", claim_dropped)],
                             n_resamples=1500, seed=DEFAULT_SEED)
    if ro_shrink["status"] != "FAILS":
        failures.append(f"c5c_readout FAIL: shrinking gap must FAIL outright, got {ro_shrink['status']} ({ro_shrink})")

    # === c5c_readout: three monotone-widening rungs -> HOLDS (constitutional clearance) ===
    ro_holds = c5c_readout(same_rows, claim_boosted,
                            third_rung_series=[("r0", same_rows), ("r1", claim_boosted), ("r2", claim_boosted_more)],
                            n_resamples=1500, seed=DEFAULT_SEED)
    if ro_holds["status"] != "HOLDS":
        failures.append(f"c5c_readout FAIL: 3 monotone-widening rungs should HOLDS, got {ro_holds['status']} ({ro_holds})")

    # === c5c_readout: three rungs but a flat step -> stays UNRESOLVED, never HOLDS ===
    ro_flat3 = c5c_readout(same_rows, same_rows,
                            third_rung_series=[("r0", same_rows), ("r1", same_rows), ("r2", claim_boosted_more)],
                            n_resamples=1500, seed=DEFAULT_SEED)
    if ro_flat3["status"] == "HOLDS":
        failures.append(f"c5c_readout FAIL: a flat step among 3 rungs must never HOLDS, got {ro_flat3}")

    if failures:
        for f in failures:
            print(f"SELFTEST: {f}")
        return 1

    print("C5C_READOUT_SELFTEST_PASS")
    return 0


def main():
    import argparse
    ap = argparse.ArgumentParser(description="C5(c) W-statistic readout grammar (issue #628).")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        sys.exit(_selftest())
    ap.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
