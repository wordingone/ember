# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Full-shape CIA3-R1-N61 decoder graph for S0 metadata validation.

Parameters exist on meta only. Fixed-route traces exercise operation shapes
and autograd connectivity, not values, learned routing, causal logits or training.
Governed numerical allocation/initialization and paging integration remain required.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
import torch
import torch.nn as nn
import torch.nn.functional as F
from .cia_contract import CIA3R1N61, census
from .cia_inventory import equation_inventory, update_support
from .cia_routing import _global_scores, _local_scores, unit_task_gate


def rotate_three_axis(values, positions):
    """RoPE on disjoint temporal/vertical/horizontal dimensions 32/16/16."""
    if values.ndim != 3 or values.shape[-1] != 64:
        raise ValueError("attention heads must have shape [positions,heads,64]")
    if tuple(positions.shape) != (len(values), 3) or positions.dtype != torch.long:
        raise ValueError("three integer axes required at every position")
    if positions.device != values.device:
        raise ValueError("positions and heads must share a device")
    pieces = []
    offset = 0
    for axis, width in enumerate((32, 16, 16)):
        part = values[..., offset:offset + width]
        inverse = 10000.0 ** (-torch.arange(0, width, 2, device=values.device, dtype=torch.float32) / width)
        angle = positions[:, axis].float()[:, None, None] * inverse[None, None, :]
        even, odd = part[..., 0::2].float(), part[..., 1::2].float()
        rotated = torch.stack((even * angle.cos() - odd * angle.sin(),
                               even * angle.sin() + odd * angle.cos()), dim=-1)
        pieces.append(rotated.flatten(-2).to(values.dtype))
        offset += width
    return torch.cat(pieces, dim=-1)


class CIADecoder(nn.Module):
    """Complete parameter ownership with a deliberately explicit meta-only trace."""

    def __init__(self):
        super().__init__()
        self.config = CIA3R1N61()
        self.weights = nn.ParameterDict({
            spec.name.replace(".", "__"): nn.Parameter(torch.empty(spec.shape, device="meta", dtype=torch.bfloat16))
            for spec in equation_inventory()
        })
        self.parameter_inventory()

    def parameter_inventory(self):
        expected = {spec.name: spec.shape for spec in equation_inventory()}
        registered = {name for name, _ in self.named_parameters(remove_duplicate=False)}
        if registered != {"weights." + name.replace(".", "__") for name in expected}:
            raise ValueError("undeclared or missing registered model parameters")
        actual = {name.replace("__", "."): value for name, value in self.weights.items()}
        if set(actual) != set(expected):
            raise ValueError("candidate parameter names do not match equation inventory")
        if len({id(p) for p in actual.values()}) != len(actual):
            raise ValueError("unexpected parameter alias between distinct consumers")
        if any(tuple(actual[name].shape) != shape for name, shape in expected.items()):
            raise ValueError("candidate parameter shape mismatch")
        if any(p.dtype != torch.bfloat16 or p.device.type != "meta" for p in actual.values()):
            raise ValueError("this candidate trace requires BF16 meta parameters")
        if sum(p.numel() for p in actual.values()) != census(self.config).total_unique:
            raise ValueError("candidate census mismatch")
        return actual

    def apply_update_support(self, locus, *, experts=()):
        """Set exact parameter flags and clear stale gradients at a step boundary.

        Returned objects define prospective optimizer membership. This does not
        rebuild an optimizer or authorize dropping its retained moment state.
        """
        names = update_support(locus, experts=experts)
        parameters = self.parameter_inventory()
        for name, parameter in parameters.items():
            parameter.grad = None
            parameter.requires_grad_(name in names)
        return tuple(parameter for name, parameter in parameters.items() if name in names)

    def _weight(self, name):
        value = self.weights[name.replace(".", "__")]
        if value.device.type != "meta":
            raise ValueError("numerical allocation requires governed runtime integration")
        return value

    @staticmethod
    def _meta(value, trailing=None):
        if not isinstance(value, torch.Tensor) or value.device.type != "meta":
            raise ValueError("this S0 trace accepts metadata tensors only")
        if trailing is not None and (value.ndim != 2 or value.shape[-1] != trailing):
            raise ValueError(f"expected [positions,{trailing}]")

    def _norm(self, values, name):
        scale = (values.float().square().mean(-1, keepdim=True) + 1e-6).rsqrt()
        return (values.float() * scale).to(values.dtype) * self._weight(name)

    def _linear(self, values, name):
        return F.linear(values, self._weight(name))

    def add_modality(self, values, modality):
        self._meta(values, 1024)
        if type(modality) is not int or not 0 <= modality < 8:
            raise ValueError("modality must be an integer in [0,8)")
        return values + self._weight("modality.weight")[modality]

    def embed_text(self, tokens):
        self._meta(tokens)
        if tokens.ndim != 1 or tokens.dtype != torch.long:
            raise ValueError("one document of integer token IDs is required")
        return self.add_modality(F.embedding(tokens, self._weight("embedding.weight")), 0)

    def embed_image(self, patches):
        self._meta(patches, 768)
        return self.add_modality(self._linear(patches, "image.weight"), 1)

    def embed_audio(self, frames):
        self._meta(frames, 640)
        return self.add_modality(self._linear(frames, "audio.weight"), 2)

    def _swiglu(self, values, prefix):
        up = self._linear(values, prefix + ".up.weight")
        gate = self._linear(values, prefix + ".gate.weight")
        return self._linear(F.silu(gate) * up, prefix + ".down.weight")

    def expert_block(self, values, *, expert, layer):
        self._meta(values, 1024)
        if type(expert) is not int or not 0 <= expert < 25:
            raise ValueError("global expert identity outside [0,25)")
        if type(layer) is not int or layer not in range(1, 24, 2):
            raise ValueError("expert blocks exist only at sparse depths")
        return self._swiglu(values, f"experts.{expert}.layers.{layer}")

    def _attention(self, values, positions, prefix):
        length = len(values)
        q = self._linear(values, prefix + ".q.weight").view(length, 16, 64)
        k = self._linear(values, prefix + ".k.weight").view(length, 4, 64)
        v = self._linear(values, prefix + ".v.weight").view(length, 4, 64)
        q = rotate_three_axis(self._norm(q, prefix + ".q_norm.weight"), positions)
        k = rotate_three_axis(self._norm(k, prefix + ".k_norm.weight"), positions)
        k = k.repeat_interleave(4, dim=1)
        v = v.repeat_interleave(4, dim=1)
        out = F.scaled_dot_product_attention(q.transpose(0, 1), k.transpose(0, 1),
                                             v.transpose(0, 1), is_causal=True)
        return self._linear(out.transpose(0, 1).reshape(length, 1024), prefix + ".o.weight")

    def trace_fixed_route(self, embedded, positions, *, experts):
        """One unpadded document; forced IDs are shape fixtures, NOT semantic routing."""
        self._meta(embedded, 1024)
        self._meta(positions)
        if len(embedded) < 1 or len(embedded) > 4096:
            raise ValueError("trace context must contain 1..4096 positions")
        if type(experts) is not tuple or len(experts) != 12 or any(type(i) is not int or not 0 <= i < 25 for i in experts):
            raise ValueError("one fixed global expert ID is required per sparse depth")
        self.parameter_inventory()
        values = embedded
        for layer in range(24):
            prefix = f"layers.{layer}"
            values = values + self._attention(self._norm(values, prefix + ".attention_norm.weight"), positions, prefix + ".attention")
            values = values + self._swiglu(self._norm(values, prefix + ".shared_norm.weight"), prefix + ".shared")
            if layer % 2:
                values = values + self.expert_block(self._norm(values, prefix + ".expert_norm.weight"),
                                                     expert=experts[layer // 2], layer=layer)
        return self._linear(self._norm(values, "final_norm.weight"), "embedding.weight")

    def trace_routing_gate(self, global_history, local_vector, *, sparse_depth, experts, selected_slot):
        """Meta score/gate graph; caller-specified winners are NOT causal selections."""
        self.parameter_inventory()
        self._meta(global_history, 1024)
        self._meta(local_vector)
        if tuple(local_vector.shape) != (1024,) or len(global_history) > 1024:
            raise ValueError("one local vector and at most one global history epoch required")
        if type(sparse_depth) is not int or not 0 <= sparse_depth < 12:
            raise ValueError("invalid sparse depth")
        if type(experts) is not tuple or len(experts) != 2 or any(type(i) is not int or not 0 <= i < 25 for i in experts) or experts[0] >= experts[1]:
            raise ValueError("two distinct ascending global IDs required")
        keys = torch.stack([self._weight(f"router.layers.{layer}.keys") for layer in range(1, 24, 2)])
        summary = global_history.float().mean(0) if len(global_history) else torch.zeros(1024, device="meta")
        prior = _global_scores(summary, self._weight("router.global_query.weight"), keys)
        logits = _local_scores(local_vector, self._weight("router.local_query.weight"), keys[sparse_depth, list(experts)], prior[list(experts)])
        return unit_task_gate(logits, selected_slot)

    def forward(self, *args, **kwargs):
        raise ValueError("use trace_fixed_route for S0 metadata; governed numerical forward is not integrated")
