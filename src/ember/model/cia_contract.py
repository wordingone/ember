# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CIA3-R1-N61 planning contracts, correcting the unassigned-norm census.

These helpers do not instantiate a model, select an expert, certify capacity,
or authorize learning. Actual tensor census and causal decoder integration are
separate qualification obligations. Existing v2 production admission is untouched.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
from dataclasses import dataclass, field


def _integer(value: int, name: str, minimum: int) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


@dataclass(frozen=True)
class Capacity:
    core: int
    expert_bundle: int
    total_unique: int
    active_envelope: int
    resident_envelope: int


@dataclass(frozen=True)
class CIA3R1N61:
    """R1 equations with 61 evidenced norms; other shapes require a new revision."""

    revision: str = field(default="CIA3-R1-N61", init=False)
    global_experts: int = 25
    resident_experts: int = 2
    selected_experts: int = 1

    def __post_init__(self) -> None:
        for name in ("global_experts", "resident_experts", "selected_experts"):
            _integer(getattr(self, name), name, 1)
        if not self.selected_experts <= self.resident_experts <= self.global_experts:
            raise ValueError("selected <= resident <= global experts is required")
        if _counts(self).total_unique < 3_000_000_000:
            raise ValueError("reference census is below 3,000,000,000 unique parameters")
        if (self.global_experts, self.resident_experts, self.selected_experts) != (25, 2, 1):
            raise ValueError("changing CIA3-R1 requires a separate candidate revision")


def _counts(config: CIA3R1N61) -> Capacity:
    width, layers, sparse_depths, head_width = 1024, 24, 12, 64
    kv_width = 4 * head_width
    attention = layers * (2 * width * width + 2 * width * kv_width + 2 * head_width)
    shared_ffn = layers * 3 * width * 2048
    embedding = 32768 * width  # tied input/output counted once
    routing = 2 * width * width + sparse_depths * config.global_experts * width
    # N61 correction to issue #2163: 61 equation-supported RMSNorm vectors, eight modality
    # embeddings and the raw image/audio projections. This is a formula,
    # not evidence that an executable decoder has realized these tensors.
    norms_and_adapters = (61 + 8 + 768 + 640) * width
    core = attention + shared_ffn + embedding + routing + norms_and_adapters
    bundle = sparse_depths * 3 * width * 3072
    return Capacity(
        core, bundle, core + config.global_experts * bundle,
        core + config.selected_experts * bundle,
        core + config.resident_experts * bundle,
    )


def census(config: CIA3R1N61) -> Capacity:
    """Recompute reference counts; never report these as realized/trained counts."""
    if type(config) is not CIA3R1N61:
        raise ValueError("an exact CIA3R1N61 contract is required")
    return _counts(config)


def history_window(*, position: int, document_start: int, period: int) -> tuple[int, int]:
    """Half-open preceding routing epoch/segment within ONE packed document.

    The current interval is excluded in its entirety. The first interval has
    empty history and requires the caller's fixed beginning-of-sequence state.
    Call per request/document; never pool returned histories across requests.
    Global selection consumes embeddings under the candidate identity. Local
    selection consumes preceding-segment hidden state at the required depth.
    This bounds permissible history only; it is not a routing implementation.
    """
    _integer(position, "position", 0)
    _integer(document_start, "document_start", 0)
    _integer(period, "period", 1)
    if position < document_start:
        raise ValueError("position precedes its document")
    boundary = document_start + ((position - document_start) // period) * period
    return max(document_start, boundary - period), boundary
