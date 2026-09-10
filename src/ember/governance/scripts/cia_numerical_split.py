# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Comparison contract for revision CIA3-R1-N61-numerical-split-v1.

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

Every bound here is fixed prospectively by the issue body and may not be changed after observing a
run. They are proposed numerical bounds, not empirical quality thresholds, and nothing in this
module grants learning, paging, recovery, checkpoint, launch, throughput or completion credit.
"""
from dataclasses import dataclass
import hashlib
import math

import torch

REVISION = "CIA3-R1-N61-numerical-split-v1"

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
    admissible: bool
    reason: str

    def as_row(self):
        return {"document": self.key[0], "layer": self.key[1], "segment_start": self.key[2],
                "candidates": list(self.candidates), "cpu_chosen": self.cpu_chosen,
                "cuda_chosen": self.cuda_chosen, "differs": self.differs,
                "cpu_margin": self.cpu_margin, "cuda_margin": self.cuda_margin,
                "shared_vector_absolute_l2": self.shared_vector_absolute_l2,
                "shared_vector_relative_l2": self.shared_vector_relative_l2,
                "admissible": self.admissible, "reason": self.reason}


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

    comparisons = []
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
        cpu_margin = _finite(cpu.margin, f"cpu margin at {key}")
        cuda_margin = _finite(cuda.margin, f"cuda margin at {key}")
        differs = cpu.chosen != cuda.chosen
        reason = ""
        admissible = True
        if relative is None:
            if absolute != 0.0:
                admissible = False
                reason = (f"cpu shared vector is the defined empty summary while the cuda absolute "
                          f"delta is {absolute:.10g}; the backends disagree about an absent history")
        elif relative > SHARED_VECTOR_RELATIVE_L2_MAX:
            admissible = False
            reason = (f"shared-vector relative L2 {relative:.10g} exceeds "
                      f"{SHARED_VECTOR_RELATIVE_L2_MAX}")
        if admissible and differs and abs(cuda_margin) > DIFFERING_CUDA_MARGIN_MAX:
            admissible = False
            reason = (f"differing selection with candidate CUDA margin {abs(cuda_margin):.10g} "
                      f"exceeding {DIFFERING_CUDA_MARGIN_MAX}")
        comparisons.append(LocalComparison(
            key=key, candidates=cpu.candidates, cpu_chosen=cpu.chosen, cuda_chosen=cuda.chosen,
            differs=differs, cpu_margin=cpu_margin, cuda_margin=cuda_margin,
            shared_vector_absolute_l2=absolute, shared_vector_relative_l2=relative,
            admissible=admissible, reason=reason))
    return tuple(comparisons)


def local_route_report(comparisons):
    """The reportable summary. It never decides admissibility; `refuse_if_inadmissible` does."""
    return {"revision": REVISION, "local_routes": len(comparisons),
            "differing_routes": sum(1 for row in comparisons if row.differs),
            "inadmissible_routes": sum(1 for row in comparisons if not row.admissible),
            "max_shared_vector_relative_l2": max((row.shared_vector_relative_l2
                                                  for row in comparisons
                                                  if row.shared_vector_relative_l2 is not None),
                                                 default=None),
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
