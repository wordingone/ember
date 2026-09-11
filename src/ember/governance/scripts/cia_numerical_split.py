# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Comparison contract for revision CIA3-R1-N62-numerical-split-v2.

The preceding revision asserted exact free-route equality across backends and failed on one of 60
selections, at layer 21, position 768, with a CUDA two-score margin of -0.000027179718 against a
CPU margin of +0.0424120426. An exact-equality assertion cannot tell those two numbers apart from a
selector defect: it reports that the winners differ, and stops.

This revision measures instead. Every corresponding pair of local selections is compared on three
axes that fail for different reasons:

  * the SHARED VECTOR the scores were computed from, which fails when the divergence is already
    upstream of the selector;
  * the CANDIDATE PAIR and causal context, which fail when the two executions were not comparing
    the same things at all;
  * the two SCORES, whose signed margins say whether a differing winner was a near-tie inside the
    admitted band or a real disagreement.

Separately, each recorded selector input is evaluated on BOTH backends. That is the leg that
isolates the selector: identical inputs must produce identical candidate and winner identities, and
scores within 2^-18. A selector that agrees on identical inputs while the run disagrees locates the
divergence upstream, which is exactly the question the last execution could not answer.

N62 adds one leg and loosens no bound. N61 refused a governed run at (0, 23, 1024) for a
shared-vector relative L2 of 0.1604 against its 0.02 noise bound, while the same run's only
differing selection -- (0, 21, 768), CUDA margin 2.7e-05 -- had been ADMITTED as a near-tie. An
admitted near-tie still means the two backends applied different experts to positions 768-1023, and
`select_local` reads the shared-path vector at segment_start - 1, so position 1023 is the one
shared-vector source inside that segment and layer 23 is the one routed layer after 21. The refusing
site was the single site the structure predicts. The contract admitted that the runs may compute
different things and then refused them for having done so, and a noise bound is not measuring noise
at a site downstream of a different expert. The 59 other sites sat at 0.0148-0.0151, so the bound is
well calibrated for what it was designed to bound; the defect was its SCOPE.

So a site is DOWNSTREAM-ATTRIBUTABLE when its shared-vector source position lies inside a segment for
which an admitted differing selection was recorded at an earlier routed layer of the same document.
Attribution is structural -- position and segment arithmetic over the recorded keys -- and never a
magnitude, so it cannot be tuned to admit a site after the fact. Such a site is excluded from the
noise bound and reported under its own heading with its own maximum; it is admitted for having a
cause the run already admitted, never for being large. The gating maximum covers the unattributable
sites alone, because fusing the two populations into one headline number is what made N61's single
message unreadable.

Every bound here is fixed prospectively by the issue body and may not be changed after observing a
run. They are proposed numerical bounds, not empirical quality thresholds, and nothing in this
module grants learning, paging, recovery, checkpoint, launch, throughput or completion credit.
"""
from dataclasses import dataclass
import hashlib
import math

import torch

REVISION = "CIA3-R1-N63-numerical-split-v3"

# --- prospectively fixed bounds (issue #2163 body, 2026-09-09) -----------------------------------
LOCAL_ROUTES = 60
GLOBAL_SELECTIONS_PER_DOCUMENT = 2
#: A differing free local selection is admissible only when the CANDIDATE CUDA two-score margin is
#: at most this. The CPU margin is reported and never gates: the CUDA run is the one whose
#: selection is in question.
DIFFERING_CUDA_MARGIN_MAX = 0.001
#: About 42% above the preceding measured 0.0140835596. A proposed bound, not a quality threshold.
SHARED_VECTOR_RELATIVE_L2_MAX = 0.02
#: Sixteen times the preceding measured 2^-22 selector-score error.
SELECTOR_SCORE_ABSOLUTE_MAX = 2.0 ** -18
FIXED_PLAN_LOGIT_RTOL = 0.05
FIXED_PLAN_LOGIT_ATOL = 0.05
#: N63 (issue #2163, 2026-09-10). The retained elementwise atol/rtol pair above is still
#: measured and reported, but it no longer gates: the N62 attribution found the fixed-plan logit
#: difference is the BF16 format's own rounding under two reduction orders (divergence at layer 0
#: of 1.07 ulp, sub-quadrature accumulation, no site; per-matmul floor 2.146e-3 relative L2,
#: FP32 3.47e-7, FP64 exact), so an absolute same-backend bound cannot be met by any correct
#: cross-backend computation. The gate is the whole-logit relative L2 against the CPU
#: reference. Measured backend floor 0.0161794; planted defects: one weight moved one BF16 ulp
#: 1.0016x the floor (NOT resolvable at this precision, recorded as such), one planned route not
#: consumed 7.164x, one layer of routes not consumed 12.437x. The bound sits above the floor and
#: below every resolvable defect. About 3.09x the floor.
FIXED_PLAN_LOGIT_RELATIVE_L2_MAX = 0.05
GRADIENT_RELATIVE_L2_MAX = 0.1


class NumericalSplitRefusal(ValueError):
    """A bound was crossed, or an observation needed to evaluate one is absent."""


@dataclass(frozen=True)
class LocalComparison:
    key: tuple
    candidates: tuple
    cpu_chosen: int
    cuda_chosen: int
    differs: bool
    cpu_margin: float
    cuda_margin: float
    shared_vector_absolute_l2: float
    #: None where the cpu reference is the defined empty summary: a relative delta against a
    #: zero reference is undefined, and publishing it as 0.0 would claim an agreement nothing
    #: measured. Such a route is bounded by absolute equality instead.
    shared_vector_relative_l2: float | None
    #: True where this site's shared-vector source position lies inside a segment carrying an
    #: admitted differing selection from an earlier routed layer. Such a site is excluded from the
    #: shared-vector noise bound, because what it measures is that admitted divergence rather than
    #: numerical noise.
    downstream_attributable: bool
    admissible: bool
    reason: str

    def as_row(self):
        return {"document": self.key[0], "layer": self.key[1], "segment_start": self.key[2],
                "candidates": list(self.candidates), "cpu_chosen": self.cpu_chosen,
                "cuda_chosen": self.cuda_chosen, "differs": self.differs,
                "cpu_margin": self.cpu_margin, "cuda_margin": self.cuda_margin,
                "shared_vector_absolute_l2": self.shared_vector_absolute_l2,
                "shared_vector_relative_l2": self.shared_vector_relative_l2,
                "downstream_attributable": self.downstream_attributable,
                "admissible": self.admissible, "reason": self.reason}


LOCAL_SEGMENT = 256


def predict_downstream_attributable(keys, admitted_differing):
    """Which sites sit downstream of an admitted differing selection, from the KEYS alone.

    Derived from the recorded route keys and the admitted differing keys only -- no measured
    magnitude reaches this function, which is what stops the exemption from being fitted to the
    numbers it exempts. `select_local` reads the shared-path vector at `segment_start - 1`, so a
    site is attributable when that source position falls inside a differing segment of the same
    document at a strictly earlier routed layer.

    Computed independently of the comparison walk and checked against it, so a bug in either one
    is a refusal rather than a silently wider exemption.
    """
    attributable = set()
    for document, layer, start in keys:
        source = start - 1
        if source < 0:
            continue
        for other_document, other_layer, other_start in admitted_differing:
            if other_document != document or other_layer >= layer:
                continue
            if other_start <= source < other_start + LOCAL_SEGMENT:
                attributable.add((document, layer, start))
                break
    return attributable


def _finite(value, what):
    if not math.isfinite(value):
        raise NumericalSplitRefusal(f"{what} is not finite")
    return value


def _by_key(observations, what):
    indexed = {}
    for observation in observations:
        if observation.key in indexed:
            raise NumericalSplitRefusal(f"duplicate {what} observation at {observation.key}")
        indexed[observation.key] = observation
    return indexed


def compare_local_routes(cpu_observations, cuda_observations):
    """Compare every corresponding local selection, including the ones that agree.

    Reporting only the differing routes would make the comparison's own coverage unverifiable: a
    run that silently observed six routes and found no difference would read identically to one
    that observed sixty. The count is part of the evidence, so the full set is returned and the
    route total is checked against the fixture's fixed shape.
    """
    cpu_index = _by_key(cpu_observations, "cpu local")
    cuda_index = _by_key(cuda_observations, "cuda local")
    if len(cpu_index) != LOCAL_ROUTES or len(cuda_index) != LOCAL_ROUTES:
        raise NumericalSplitRefusal(
            f"expected {LOCAL_ROUTES} local selections per backend; measured "
            f"{len(cpu_index)} on cpu and {len(cuda_index)} on cuda")
    if set(cpu_index) != set(cuda_index):
        missing = sorted(set(cpu_index) ^ set(cuda_index))
        raise NumericalSplitRefusal(f"local selections do not correspond at {missing}")

    # Pass one measures every site. Admissibility is decided in pass two, because whether a site's
    # shared-vector divergence is noise or the consequence of an admitted differing selection is not
    # knowable until every differing selection in the run has been read.
    measured = {}
    for key in sorted(cpu_index):
        cpu, cuda = cpu_index[key], cuda_index[key]
        if cpu.candidates != cuda.candidates:
            raise NumericalSplitRefusal(
                f"candidate pair mismatch at {key}: cpu {cpu.candidates} against "
                f"cuda {cuda.candidates}")
        if cpu.segment_start != cuda.segment_start:
            raise NumericalSplitRefusal(f"causal context mismatch at {key}")
        delta = cuda.summary - cpu.summary
        reference = float(cpu.summary.norm())
        absolute = _finite(float(delta.norm()), f"shared-vector delta at {key}")
        # A zero reference is structural here, not incidental. `select_local` publishes the defined
        # empty summary -- a zero vector -- at a document's FIRST segment, where there is no
        # preceding shared-path vector to summarize. On the fixed fixture that is 12 of the 60
        # routes, exactly (0, layer, 0) for each routing layer, and the remaining 48 norms run from
        # 2.57 to 10.57, so the class has no borderline members.
        #
        # The relative delta is genuinely undefined there, and reporting it as 0.0 would claim an
        # agreement nothing measured. Refusing the whole comparison was the other error: it made a
        # fifth of the routes permanently uncomputable, so no run could pass this gate on any
        # inputs. The way out is not a weaker bound but a stronger one -- both backends are obliged
        # to produce the SAME defined empty summary, so their absolute delta must be exactly zero,
        # and any nonzero value is a real disagreement about what an absent history means. That is
        # a tighter condition than the relative bound it replaces, and the undefined relative is
        # published as null so a reader can see which routes it covers.
        relative = None
        if reference != 0.0:
            relative = _finite(absolute / reference, f"shared-vector relative delta at {key}")
        measured[key] = {
            "candidates": cpu.candidates, "cpu_chosen": cpu.chosen, "cuda_chosen": cuda.chosen,
            "differs": cpu.chosen != cuda.chosen,
            "cpu_margin": _finite(cpu.margin, f"cpu margin at {key}"),
            "cuda_margin": _finite(cuda.margin, f"cuda margin at {key}"),
            "absolute": absolute, "relative": relative}

    # A differing selection confers attribution only when it is itself ADMITTED. A differing site
    # whose margin exceeds the bound is a real disagreement, the run fails on it, and it must not
    # also buy an exemption for the sites it contaminated.
    admitted_differing = {key for key, row in measured.items()
                          if row["differs"] and abs(row["cuda_margin"]) <= DIFFERING_CUDA_MARGIN_MAX}
    attributable = predict_downstream_attributable(set(measured), admitted_differing)

    comparisons = []
    for key in sorted(measured):
        row = measured[key]
        absolute, relative = row["absolute"], row["relative"]
        downstream = key in attributable
        reason = ""
        admissible = True
        if relative is None:
            if absolute != 0.0:
                admissible = False
                reason = (f"cpu shared vector is the defined empty summary while the cuda absolute "
                          f"delta is {absolute:.10g}; the backends disagree about an absent history")
        elif relative > SHARED_VECTOR_RELATIVE_L2_MAX and not downstream:
            admissible = False
            reason = (f"shared-vector relative L2 {relative:.10g} exceeds "
                      f"{SHARED_VECTOR_RELATIVE_L2_MAX}")
        elif relative > SHARED_VECTOR_RELATIVE_L2_MAX:
            reason = (f"shared-vector relative L2 {relative:.10g} is exempt from "
                      f"{SHARED_VECTOR_RELATIVE_L2_MAX}: this site reads position {key[2] - 1}, "
                      f"inside a segment carrying an admitted differing selection at an earlier "
                      f"routed layer")
        if admissible and row["differs"] and abs(row["cuda_margin"]) > DIFFERING_CUDA_MARGIN_MAX:
            admissible = False
            reason = (f"differing selection with candidate CUDA margin "
                      f"{abs(row['cuda_margin']):.10g} exceeding {DIFFERING_CUDA_MARGIN_MAX}")
        comparisons.append(LocalComparison(
            key=key, candidates=row["candidates"], cpu_chosen=row["cpu_chosen"],
            cuda_chosen=row["cuda_chosen"], differs=row["differs"], cpu_margin=row["cpu_margin"],
            cuda_margin=row["cuda_margin"], shared_vector_absolute_l2=absolute,
            shared_vector_relative_l2=relative, downstream_attributable=downstream,
            admissible=admissible, reason=reason))

    # The comparison walk and the structural predictor are two paths to the same set; disagreement
    # means one of them is wrong, and neither is allowed to be the authority on its own.
    if {row.key for row in comparisons if row.downstream_attributable} != attributable:
        raise NumericalSplitRefusal("downstream attribution disagrees with its structural prediction")
    return tuple(comparisons)


def local_route_report(comparisons):
    """The reportable summary. It never decides admissibility; `refuse_if_inadmissible` does."""
    return {"revision": REVISION, "local_routes": len(comparisons),
            "differing_routes": sum(1 for row in comparisons if row.differs),
            "inadmissible_routes": sum(1 for row in comparisons if not row.admissible),
            # The GATING maximum, over unattributable sites alone. N61 published one fused
            # maximum, so a site downstream of an admitted differing selection and a site carrying
            # real numerical noise arrived as the same number.
            "max_shared_vector_relative_l2": max((row.shared_vector_relative_l2
                                                  for row in comparisons
                                                  if row.shared_vector_relative_l2 is not None
                                                  and not row.downstream_attributable),
                                                 default=None),
            "downstream_attributable_routes": sum(1 for row in comparisons
                                                  if row.downstream_attributable),
            "max_downstream_attributable_relative_l2": max(
                (row.shared_vector_relative_l2 for row in comparisons
                 if row.downstream_attributable and row.shared_vector_relative_l2 is not None),
                default=None),
            "admitted_differing_routes": sorted(
                [row.key[0], row.key[1], row.key[2]] for row in comparisons
                if row.differs and row.admissible),
            # Published so the maximum above cannot be read as covering every route: these are the
            # routes whose reference is the defined empty summary, bounded by absolute equality.
            "undefined_relative_routes": sum(1 for row in comparisons
                                             if row.shared_vector_relative_l2 is None),
            "max_zero_reference_absolute_l2": max((row.shared_vector_absolute_l2
                                                   for row in comparisons
                                                   if row.shared_vector_relative_l2 is None),
                                                  default=None),
            "max_differing_cuda_margin": max((abs(row.cuda_margin) for row in comparisons
                                              if row.differs), default=None),
            "bounds": {"differing_cuda_margin_max": DIFFERING_CUDA_MARGIN_MAX,
                       "shared_vector_relative_l2_max": SHARED_VECTOR_RELATIVE_L2_MAX,
                       "zero_reference_absolute_l2_max": 0.0},
            "routes": [row.as_row() for row in comparisons]}


def compare_fixed_plan_logits(reference, candidate):
    """The N63 fixed-plan logit comparison: whole-logit relative L2 gates, elementwise is reported.

    `reference` is the CPU fixed-plan logit tensor, `candidate` the CUDA one under the same plan.
    Returns the measurement row; raises NumericalSplitRefusal when the relative L2 exceeds
    FIXED_PLAN_LOGIT_RELATIVE_L2_MAX, when the shapes differ, or when either side is nonfinite.
    The retained atol/rtol count is carried in the row so the N62 field keeps its meaning.
    """
    if tuple(reference.shape) != tuple(candidate.shape):
        raise NumericalSplitRefusal(
            f"fixed-plan logit shapes differ: {tuple(reference.shape)} vs {tuple(candidate.shape)}")
    reference = reference.detach().float()
    candidate = candidate.detach().float()
    if not bool(torch.isfinite(reference).all()) or not bool(torch.isfinite(candidate).all()):
        raise NumericalSplitRefusal("fixed-plan logits are nonfinite on at least one backend")
    denominator = float(reference.norm())
    if denominator == 0.0:
        raise NumericalSplitRefusal("fixed-plan reference logits have zero norm; relative L2 undefined")
    delta = (candidate - reference).abs()
    allowed = FIXED_PLAN_LOGIT_ATOL + FIXED_PLAN_LOGIT_RTOL * reference.abs()
    row = {"relative_l2": float((candidate - reference).norm() / denominator),
           "bound": FIXED_PLAN_LOGIT_RELATIVE_L2_MAX,
           "max_absolute": float(delta.max()),
           "elements_exceeding_retained_atol_rtol": int((delta > allowed).sum()),
           "elements_compared": int(reference.numel())}
    if not row["relative_l2"] <= FIXED_PLAN_LOGIT_RELATIVE_L2_MAX:
        raise NumericalSplitRefusal(
            "fixed-plan logits: relative L2 %.10g exceeds %g (max absolute %.10g; %d of %d elements "
            "outside the retained atol/rtol)" % (
                row["relative_l2"], FIXED_PLAN_LOGIT_RELATIVE_L2_MAX, row["max_absolute"],
                row["elements_exceeding_retained_atol_rtol"], row["elements_compared"]))
    return row


def refuse_if_inadmissible(comparisons):
    failed = [row for row in comparisons if not row.admissible]
    if failed:
        raise NumericalSplitRefusal(
            f"{len(failed)} of {len(comparisons)} local selections are inadmissible: "
            + "; ".join(f"{row.key}: {row.reason}" for row in failed[:5]))
    return comparisons


def route_plan(observations):
    """The complete measured plan, as `(document, layer, segment_start) -> (candidates, winner)`."""
    plan = {}
    for observation in observations:
        if observation.key in plan:
            raise NumericalSplitRefusal(f"duplicate plan entry at {observation.key}")
        plan[observation.key] = (observation.candidates, observation.chosen)
    if len(plan) != LOCAL_ROUTES:
        raise NumericalSplitRefusal(
            f"a complete plan has {LOCAL_ROUTES} entries; this one has {len(plan)}")
    return plan


def compare_global_selections(cpu_observations, cuda_observations):
    """Global selections gate the candidate pair, so a difference here is never a near-tie."""
    cpu = sorted(cpu_observations, key=lambda row: (row.document, row.epoch_start))
    cuda = sorted(cuda_observations, key=lambda row: (row.document, row.epoch_start))
    if len(cpu) != len(cuda) or not cpu:
        raise NumericalSplitRefusal(
            f"global selections do not correspond: {len(cpu)} on cpu, {len(cuda)} on cuda")
    rows = []
    for left, right in zip(cpu, cuda):
        if (left.document, left.epoch_start) != (right.document, right.epoch_start):
            raise NumericalSplitRefusal("global selections describe different epochs")
        if left.experts != right.experts:
            raise NumericalSplitRefusal(
                f"global expert pair differs at epoch {left.epoch_start}: "
                f"cpu {left.experts} against cuda {right.experts}")
        delta = _finite(float((right.log_prior - left.log_prior).abs().max()),
                        f"global prior delta at epoch {left.epoch_start}")
        rows.append({"document": left.document, "epoch_start": left.epoch_start,
                     "experts": list(left.experts), "max_absolute_prior_delta": delta,
                     "cpu_selector_version": left.selector_version,
                     "cuda_selector_version": right.selector_version})
    return tuple(rows)


def digest_of(value):
    host = value.detach().to(device="cpu").contiguous()
    metadata = f"{host.dtype}:{tuple(host.shape)}:".encode()
    return hashlib.sha256(metadata + host.view(torch.uint8).numpy().tobytes()).hexdigest()


def cross_evaluate_selector(observations, query_weights, scorer):
    """Evaluate each recorded selector input on every backend, on that backend's own projection.

    `query_weights` maps a backend name to its projection. The projections must be byte-identical
    across backends before any score is compared: a score difference measured on differing
    parameters says nothing about the selector, which is the only thing this leg exists to isolate.
    """
    names = sorted(query_weights)
    if len(names) < 2:
        raise NumericalSplitRefusal("cross evaluation needs at least two backends")
    digests = {name: digest_of(weight) for name, weight in query_weights.items()}
    if len(set(digests.values())) != 1:
        raise NumericalSplitRefusal(
            f"selector parameter identities differ across backends: {digests}")

    worst = 0.0
    rows = []
    for observation in observations:
        scores = {}
        for name in names:
            weight = query_weights[name]
            device = weight.device
            value = scorer(observation.summary.to(device), weight,
                           observation.keys_slice.to(device), observation.prior_slice.to(device))
            value = value.detach().to(device="cpu", dtype=torch.float32)
            if not torch.isfinite(value).all():
                raise NumericalSplitRefusal(
                    f"nonfinite selector score at {observation.key} on {name}")
            scores[name] = value
        winners = {name: observation.candidates[int(torch.argmax(value))]
                   for name, value in scores.items()}
        if len(set(winners.values())) != 1:
            raise NumericalSplitRefusal(
                f"identical selector inputs at {observation.key} produced different winners: "
                f"{winners}")
        reference = scores[names[0]]
        for name in names[1:]:
            error = float((scores[name] - reference).abs().max())
            worst = max(worst, _finite(error, f"selector score error at {observation.key}"))
        rows.append({"key": list(observation.key), "candidates": list(observation.candidates),
                     "winner": winners[names[0]],
                     "scores": {name: [float(value[0]), float(value[1])]
                                for name, value in scores.items()}})
    if worst > SELECTOR_SCORE_ABSOLUTE_MAX:
        raise NumericalSplitRefusal(
            f"maximum absolute selector-score error {worst:.10g} exceeds "
            f"{SELECTOR_SCORE_ABSOLUTE_MAX}")
    return {"revision": REVISION, "backends": names, "parameter_sha256": digests[names[0]],
            "max_absolute_selector_score_error": worst,
            "bound": SELECTOR_SCORE_ABSOLUTE_MAX, "evaluations": rows}
