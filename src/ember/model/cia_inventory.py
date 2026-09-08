# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Equation-derived CIA tensor inventory; NOT a model or admission certificate.

Issue #2163's reference arithmetic has three unassigned width-sized norms.
This inventory names only equation-supported tensors (61 such norms), exposing
the 3,072-parameter discrepancy. CIA3-R1-N61 adopts this evidenced inventory;
the three unassigned reference norms remain specification item CIA-NORM-001.
Meta tensors carry shapes only: no values, initialization, reachability,
causal execution, gradient, or learning evidence is established here.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
from dataclasses import dataclass
from math import prod


@dataclass(frozen=True)
class TensorSpec:
    name: str
    shape: tuple[int, ...]
    role: str
    expert: int | None = None

    @property
    def numel(self) -> int:
        return prod(self.shape)


def equation_inventory() -> tuple[TensorSpec, ...]:
    specs = []

    def add(name, shape, role="core", expert=None):
        specs.append(TensorSpec(name, shape, role, expert))

    add("embedding.weight", (32768, 1024))  # output head is tied, not another tensor
    add("modality.weight", (8, 1024), "adapter")
    add("image.weight", (1024, 768), "adapter")
    add("audio.weight", (1024, 640), "adapter")
    add("final_norm.weight", (1024,))
    add("router.global_query.weight", (1024, 1024), "router")
    add("router.local_query.weight", (1024, 1024), "router")
    for layer in range(24):
        prefix = f"layers.{layer}"
        add(f"{prefix}.attention_norm.weight", (1024,))
        add(f"{prefix}.shared_norm.weight", (1024,))
        for projection, out in (("q", 1024), ("k", 256), ("v", 256), ("o", 1024)):
            add(f"{prefix}.attention.{projection}.weight", (out, 1024))
        for name in ("q_norm", "k_norm"):
            add(f"{prefix}.attention.{name}.weight", (64,))
        for name, shape in (("up", (2048, 1024)), ("gate", (2048, 1024)), ("down", (1024, 2048))):
            add(f"{prefix}.shared.{name}.weight", shape)
        if layer % 2 == 1:
            add(f"{prefix}.expert_norm.weight", (1024,))
            add(f"router.layers.{layer}.keys", (25, 1024), "router")
            for expert in range(25):
                for name, shape in (("up", (3072, 1024)), ("gate", (3072, 1024)), ("down", (1024, 3072))):
                    add(f"experts.{expert}.layers.{layer}.{name}.weight", shape, "expert", expert)
    return tuple(specs)


def meta_inventory():
    """Materialize only metadata; intentionally has no allocation-device option."""
    import torch
    return {spec.name: torch.empty(spec.shape, dtype=torch.bfloat16, device="meta")
            for spec in equation_inventory()}


def update_support(locus: str, *, experts: tuple[int, ...] = ()) -> frozenset[str]:
    """Explicit prospective support, not proof of actual optimizer mutations."""
    allowed = {"memory-only", "expert-set", "router-only", "core-only", "core+expert-set"}
    if locus not in allowed:
        raise ValueError("unknown update locus; topology requires its own transaction")
    if type(experts) is not tuple or any(type(e) is not int or not 0 <= e < 25 for e in experts):
        raise ValueError("expert identities must be an immutable tuple of integers in [0,25)")
    if len(set(experts)) != len(experts):
        raise ValueError("duplicate expert identities")
    needs_experts = locus in {"expert-set", "core+expert-set"}
    if bool(experts) != needs_experts:
        raise ValueError("only expert loci require a nonempty expert set")
    return frozenset(
        spec.name for spec in equation_inventory()
        if (locus == "router-only" and spec.role == "router")
        or (locus in {"core-only", "core+expert-set"} and spec.role in {"core", "adapter"})
        or (needs_experts and spec.expert in experts)
    )
