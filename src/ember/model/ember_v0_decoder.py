# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Full-shape CIA3-R1-N61 decoder with explicit bounded candidate execution.

Parameters default to meta; full CPU materialization supplies the numerical
reference. Explicit CUDA activation retains CPU expert ownership and leases two
GPU bundles through recomputed backward. Runtime conformance, generation admission
and learning qualification require their own execution evidence.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
import torch
import torch.nn as nn
import torch.nn.functional as F
from .ember_v0_contract import census, cia_architecture_config, validate_cia_architecture
from .ember_v0_inventory import equation_inventory, update_support
from .ember_v0_routing import (_global_scores, _local_scores, unit_task_gate, select_global,
                              select_local, observe_global, observe_local)


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
    """Complete parameter ownership, CPU reference and guarded CUDA candidate path."""

    def __init__(self, *, architecture_config=None):
        # Reject undeclared semantics before any parameter storage is created.
        validated_config = validate_cia_architecture(
            cia_architecture_config() if architecture_config is None else architecture_config
        )
        super().__init__()
        self.config = validated_config
        self._parameter_device = "meta"
        self._execution_device = torch.device('meta')
        self._cuda_execution = None
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
        def expected_device(name):
            return torch.device('cpu') if self._parameter_device == 'cuda' and name.startswith('experts.') else self._execution_device
        if any(p.dtype != torch.bfloat16 or p.device != expected_device(name) for name, p in actual.items()):
            raise ValueError("candidate requires BF16 parameters on its declared device")
        if sum(p.numel() for p in actual.values()) != census(self.config).total_unique:
            raise ValueError("candidate census mismatch")
        if self._parameter_device != "meta":
            if any(not p.is_contiguous() or p.storage_offset() != 0 or p.untyped_storage().nbytes() != p.numel() * p.element_size() for p in actual.values()):
                raise ValueError("physical parameter storage does not match declared elements")
            for device in {p.device for p in actual.values()}:
                ranges = sorted((p.data_ptr(), p.data_ptr() + p.untyped_storage().nbytes()) for p in actual.values() if p.device == device)
                if any(left[1] > right[0] for left, right in zip(ranges, ranges[1:])):
                    raise ValueError("physical parameter storage alias")
        return actual

    def _apply(self, fn, recurse=True):
        raise ValueError('generic module migration cannot bypass explicit CIA placement')

    def float(self):
        # Retain the existing no-storage invalid-dtype fixture. Physical placement
        # and precision changes must use a separately validated execution path.
        if self._parameter_device != 'meta':
            raise ValueError('physical dtype migration cannot bypass CIA placement')
        return super()._apply(lambda value: value.float() if value.is_floating_point() else value)

    def materialize_cpu(self, *, seed):
        """Initialize the complete population for CPU conformance, never a smaller subject.

        BF16 storage/computation; norms start at one, other tensors at N(0,.02),
        residual output projections scaled by sqrt(48). No pretrained weights,
        paging, production optimizer, generation admission or GPU launch implied.
        A caller must reserve and enforce the full allocation envelope externally.
        """
        if type(seed) is not int or not 0 <= seed < 2**63:
            raise ValueError("seed must be an integer in [0,2**63)")
        if self._parameter_device != "meta":
            raise ValueError("initialization is allowed only once on a meta graph")
        self.parameter_inventory()
        generator = torch.Generator(device="cpu").manual_seed(seed)
        for spec in equation_inventory():
            value = torch.empty(spec.shape, dtype=torch.bfloat16, device="cpu")
            if len(spec.shape) == 1:
                value.fill_(1)
            else:
                std = 0.02 / (48**0.5) if spec.name.endswith(("down.weight", "attention.o.weight")) else 0.02
                value.normal_(0, std, generator=generator)
            self.weights[spec.name.replace(".", "__")] = nn.Parameter(value, requires_grad=self.weights[spec.name.replace(".", "__")].requires_grad)
        self._parameter_device = "cpu"
        self._execution_device = torch.device('cpu')
        self.parameter_inventory()
        return self

    def activate_cuda(self, device):
        """Activate bounded execution before constructing the candidate optimizer.

        Caller must reserve the complete host/device envelope. This neither admits
        a generation nor grants launch, checkpoint, learning or throughput credit.
        """
        if self._parameter_device != 'cpu':
            raise ValueError('CUDA activation requires the complete CPU population')
        target = torch.device(device)
        if target.type != 'cuda' or target.index is None:
            raise ValueError('explicit indexed CUDA device required')
        parameters = self.parameter_inventory()
        if any(value.grad is not None for value in parameters.values()):
            raise ValueError('CUDA activation requires a quiescent population without gradients')
        from .ember_v0_residency import CUDAExecution
        shared = {name: value for name, value in parameters.items() if not name.startswith('experts.')}
        original = {name: value.data for name, value in shared.items()}
        moved = {}
        try:
            for name, value in shared.items():
                moved[name] = value.detach().to(target, copy=True)
            torch.cuda.synchronize(target)
            for name, value in shared.items():
                value.data = moved[name]
            self._execution_device = target
            self._parameter_device = 'cuda'
            self._cuda_execution = CUDAExecution(self, target)
            self.parameter_inventory()
        except BaseException:
            for name, value in shared.items():
                value.data = original[name]
            self._execution_device = torch.device('cpu')
            self._parameter_device = 'cpu'
            self._cuda_execution = None
            raise
        finally:
            moved.clear()
            original.clear()
        return self

    def candidate_step(self):
        if self._cuda_execution is None:
            raise ValueError('candidate step requires CUDA activation')
        return self._cuda_execution.step()

    def apply_update_support(self, locus, *, experts=()):
        """Set exact parameter flags and clear stale gradients at a step boundary.

        Returned objects define prospective optimizer membership. This does not
        rebuild an optimizer or authorize dropping its retained moment state.
        """
        if self._cuda_execution is not None and self._cuda_execution.cache.active:
            raise RuntimeError('update support cannot change during a candidate step')
        names = update_support(locus, experts=experts)
        parameters = self.parameter_inventory()
        for name, parameter in parameters.items():
            parameter.grad = None
            parameter.requires_grad_(name in names)
        return tuple(parameter for name, parameter in parameters.items() if name in names)

    def _weight(self, name):
        value = self.weights[name.replace(".", "__")]
        if value.device != self._execution_device:
            raise ValueError("weight device differs from the declared model device")
        return value

    def _input(self, value, trailing=None):
        if self._cuda_execution is not None:
            self._cuda_execution.cache.check()
        if not isinstance(value, torch.Tensor) or value.device != self._execution_device:
            raise ValueError("input must share the declared model device")
        if trailing is not None and (value.ndim != 2 or value.shape[-1] != trailing):
            raise ValueError(f"expected [positions,{trailing}]")

    def _norm(self, values, name):
        scale = (values.float().square().mean(-1, keepdim=True) + 1e-6).rsqrt()
        return (values.float() * scale).to(values.dtype) * self._weight(name)

    def _linear(self, values, name):
        return F.linear(values, self._weight(name))

    def add_modality(self, values, modality):
        self._input(values, 1024)
        if type(modality) is not int or not 0 <= modality < 8:
            raise ValueError("modality must be an integer in [0,8)")
        return values + self._weight("modality.weight")[modality]

    def embed_text(self, tokens):
        self._input(tokens)
        if tokens.ndim != 1 or tokens.dtype != torch.long:
            raise ValueError("one document of integer token IDs is required")
        return self.add_modality(F.embedding(tokens, self._weight("embedding.weight")), 0)

    def embed_image(self, patches):
        self._input(patches, 768)
        return self.add_modality(self._linear(patches, "image.weight"), 1)

    def embed_audio(self, frames):
        self._input(frames, 640)
        return self.add_modality(self._linear(frames, "audio.weight"), 2)

    def _swiglu(self, values, prefix):
        up = self._linear(values, prefix + ".up.weight")
        gate = self._linear(values, prefix + ".gate.weight")
        return self._linear(F.silu(gate) * up, prefix + ".down.weight")

    def expert_block(self, values, *, expert, layer):
        self._input(values, 1024)
        if type(expert) is not int or not 0 <= expert < 25:
            raise ValueError("global expert identity outside [0,25)")
        if type(layer) is not int or layer not in range(1, 24, 2):
            raise ValueError("expert blocks exist only at sparse depths")
        if self._cuda_execution is not None:
            return self._cuda_execution.expert_block(values, expert, layer)
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
        if self._parameter_device != "meta":
            raise ValueError("fixed routes are metadata fixtures only")
        self._input(embedded, 1024)
        self._input(positions)
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
        if self._parameter_device != "meta":
            raise ValueError("routing traces require a meta graph")
        self._input(global_history, 1024)
        self._input(local_vector)
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

    def _document_forward(self, embedded, positions, document_index, *, observer=None, plan=None):
        keys = torch.stack([self._weight(f"router.layers.{layer}.keys") for layer in range(1, 24, 2)])
        generation = ('cpu-conformance' if self._cuda_execution is None else
                      f'cuda-candidate-step-{self._cuda_execution.cache.step_id}')
        request = f"{generation}-document-{document_index}"
        selections = {start: select_global(
            embedded, self._weight("router.global_query.weight"), keys,
            position=start, document_start=0, generation=generation, request=request)
            for start in range(0, len(embedded), 1024)}
        if observer is not None:
            for start in sorted(selections):
                observer(observe_global(selections[start], document=document_index))
        values = embedded
        routes = []
        for layer in range(24):
            prefix = f"layers.{layer}"
            values = values + self._attention(self._norm(values, prefix + ".attention_norm.weight"), positions, prefix + ".attention")
            shared = values + self._swiglu(self._norm(values, prefix + ".shared_norm.weight"), prefix + ".shared")
            if layer % 2:
                pieces = []
                for start in range(0, len(embedded), 256):
                    selection = selections[(start // 1024) * 1024]
                    local = select_local(shared, self._weight("router.local_query.weight"), keys,
                        selection, position=start, document_start=0, generation=generation,
                        request=request, sparse_depth=layer // 2, capture=observer is not None)
                    if observer is not None:
                        observer(observe_local(local, document=document_index, layer=layer))
                    candidates = tuple(sorted(selection.experts))
                    # Ascending global-ID order, matching what select_local scores and what a plan
                    # records. selection.experts is prior-descending, which is a ranking rather
                    # than an identity, and comparing a plan against it refuses on the ordering.
                    chosen = local.expert if plan is None else self._planned_expert(
                        plan, (document_index, layer, start), candidates)
                    slot = candidates.index(chosen)
                    residual = self.expert_block(
                        self._norm(shared[start:start + 256], prefix + ".expert_norm.weight"),
                        expert=chosen, layer=layer)
                    # The gate still consumes the NATIVE logits, so the selector gradient graph a
                    # planned execution builds is the one free execution would have built. Only the
                    # discrete winner comes from the plan.
                    pieces.append(shared[start:start + 256] + residual * unit_task_gate(local.logits, slot))
                    routes.append((document_index, layer, start, selection.experts, chosen))
                values = torch.cat(pieces)
            else:
                values = shared
        return self._linear(self._norm(values, "final_norm.weight"), "embedding.weight"), routes

    @staticmethod
    def _planned_expert(plan, key, candidates):
        """Consume one planned winner, refusing every way the plan could fail to describe this run.

        Candidate-pair drift is a refusal rather than a substitution: if the two executions did not
        even consider the same experts, a matching winner would be a coincidence and a differing one
        would be attributed to the selector, when in both cases the divergence is already upstream.
        """
        entry = plan.get(key)
        if entry is None:
            raise ValueError(f"fixed route plan has no entry for {key}")
        planned_candidates, planned_expert = entry
        if tuple(planned_candidates) != tuple(candidates):
            raise ValueError(f"candidate pair drift at {key}: plan {tuple(planned_candidates)} "
                             f"against measured {tuple(candidates)}")
        if planned_expert not in tuple(candidates):
            raise ValueError(f"planned expert {planned_expert} is not a candidate at {key}")
        return planned_expert

    def forward(self, embedded, positions, *, document_starts=(0,), return_routes=False,
                route_observer=None, route_plan=None):
        """Numerical execution over explicitly packed, unpadded documents.

        Every document is evaluated independently. There is no co-batch pooling,
        mutable route cache or caller-forced numerical expert. Replaying a prefix
        recomputes its routes; this is not an incremental KV-cache implementation.
        CPU reference holds the full population locally. CUDA execution requires
        a candidate_step context and leases expert bundles during both passes.
        Neither path constitutes an admitted immutable serving generation.
        """
        if self._parameter_device not in {'cpu', 'cuda'}:
            raise ValueError("numerical forward requires full physical materialization")
        self._input(embedded, 1024)
        self._input(positions)
        if embedded.dtype != torch.bfloat16 or not 1 <= len(embedded) <= 4096:
            raise ValueError("1..4096 unpadded BF16 positions required")
        if positions.dtype != torch.long or tuple(positions.shape) != (len(embedded), 3):
            raise ValueError("three integer axes required at every position")
        if not torch.isfinite(embedded).all() or (positions < 0).any():
            raise ValueError("finite embeddings and nonnegative positions required")
        if (type(document_starts) is not tuple or not document_starts or document_starts[0] != 0
            or any(type(i) is not int or not 0 <= i < len(embedded) for i in document_starts)
            or any(a >= b for a, b in zip(document_starts, document_starts[1:]))):
            raise ValueError("strictly increasing document starts beginning at zero required")
        self.parameter_inventory()
        outputs, routes = [], []
        for index, (start, end) in enumerate(zip(document_starts, document_starts[1:] + (len(embedded),))):
            result, document_routes = self._document_forward(
                embedded[start:end], positions[start:end], index,
                observer=route_observer, plan=route_plan)
            outputs.append(result)
            routes.extend(document_routes)
        logits = torch.cat(outputs)
        return (logits, tuple(routes)) if return_routes else logits
