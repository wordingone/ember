# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Full-shape CIA3-R1-N61 decoder with explicit bounded candidate execution.

Parameters default to meta; full CPU materialization supplies the numerical
reference. Explicit CUDA activation retains CPU expert ownership and leases two
GPU bundles through recomputed backward. Runtime conformance, generation admission
and learning qualification require their own execution evidence.
"""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
import dataclasses
import hashlib
import os
from pathlib import Path
import torch
import torch.nn as nn
import torch.nn.functional as F
from .ember_v0_contract import census, cia_architecture_config, validate_cia_architecture
from .ember_v0_document_reduction import document_reduced_linear
from .ember_v0_inventory import equation_inventory, update_support
from .ember_v0_routing import (_global_scores, _local_scores, unit_task_gate, select_global,
                              select_local, observe_global, observe_local, ChunkSpec, StepRouting)


def _resident_geometry(lengths):
    from .ember_v0_residency import DeviceRouteGeometry
    if (type(lengths) is not tuple or not lengths or
            any(type(n) is not int or n <= 0 for n in lengths) or sum(lengths) > 4096):
        raise ValueError('resident segment geometry requires complete positive document lengths')
    chunks, offset, epoch = [], 0, 0
    for document, length in enumerate(lengths):
        for start in range(0, length, 1024):
            chunks.extend((document, offset, segment, min(256, length-segment), epoch)
                          for segment in range(start, min(start+1024, length), 256))
            epoch += 1
        offset += length
    return DeviceRouteGeometry(tuple(chunks), lengths)


def _document_sdpa(q, k, v, lengths):
    """One causal 4-D attention call with independent, possibly ragged documents."""
    if (not lengths or any(type(length) is not int or length <= 0 for length in lengths)
            or sum(lengths) != q.shape[0]
            or q.shape != k.shape or q.shape != v.shape or q.ndim != 3):
        raise ValueError('attention requires aligned QKV and complete positive document lengths')
    count, longest = len(lengths), max(lengths)
    if all(length == longest for length in lengths):
        packed = tuple(tensor.reshape(count, longest, *tensor.shape[1:]).transpose(1, 2)
                       for tensor in (q, k, v))
        result = F.scaled_dot_product_attention(*packed, is_causal=True)
        return result.transpose(1, 2).reshape_as(q)
    # Padding follows each document, so causal attention cannot see padded keys
    # from a valid query. Discarding padded queries also discards their gradients.
    packed = tuple(torch.stack(tuple(F.pad(piece, (0, 0, 0, 0, 0, longest - length))
                                    for piece, length in zip(tensor.split(lengths), lengths))).transpose(1, 2)
                   for tensor in (q, k, v))
    result = F.scaled_dot_product_attention(*packed, is_causal=True).transpose(1, 2)
    return torch.cat(tuple(result[index, :length] for index, length in enumerate(lengths)))


def rotate_three_axis(values, positions):
    """RoPE on disjoint temporal/vertical/horizontal dimensions 32/16/16.

    On CUDA the same function runs inductor-fused (see fused_elementwise); the eager body below is the
    reference and is what the compiled twin traces, so there is one definition of the rotation.
    """
    if values.ndim != 3 or values.shape[-1] != 64:
        raise ValueError("attention heads must have shape [positions,heads,64]")
    if tuple(positions.shape) != (len(values), 3) or positions.dtype != torch.long:
        raise ValueError("three integer axes required at every position")
    if positions.device != values.device:
        raise ValueError("positions and heads must share a device")
    if values.is_cuda and not torch.compiler.is_compiling():
        return fused_elementwise("rotate")(values, positions)
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


def _rms_norm(values, weight):
    """RMSNorm as the CPU reference computes it: fp32 statistics, cast back, then the bf16 scale."""
    scale = (values.float().square().mean(-1, keepdim=True) + 1e-6).rsqrt()
    return (values.float() * scale).to(values.dtype) * weight


_FUSED = {}
_C_COMPILER = None


def _windows():
    return os.name == "nt"


def bind_triton_c_compiler():
    """Bind the C compiler Triton uses to build inductor's launcher stubs: once per process, before the first compile.

    On Windows, Triton's own discovery looks for its bundled TinyCC under sysconfig's platlib and otherwise searches
    PATH for cl/gcc/clang. With Triton installed in the user site and no compiler on PATH it finds none (measurement 2,
    2026-09-11: "Failed to find C compiler"), while an interactive shell may pick up an unrelated compiler from PATH.
    On Windows this resolves the INSTALLED Triton package's own bundled tcc.exe (module-relative), records its sha256,
    and exports it as CC unless CC is already set. An explicit CC on any platform must itself name an existing file.
    On other platforms Triton's ordinary discovery is left untouched and the metadata says so. Refusal, never
    fallback: no PATH search, no substitute toolchain. Cached after the first call, so per-call use from
    fused_elementwise costs nothing on the step. The returned mapping is truthful runtime metadata at bind time,
    not a predeclared toolchain binding.
    """
    global _C_COMPILER
    if _C_COMPILER is None:
        explicit = os.environ.get("CC")
        if explicit:
            path = Path(explicit)
            if not path.is_file():
                raise RuntimeError("CC names a compiler that does not exist: " + explicit)
            binding = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "source": "explicit CC"}
        elif _windows():
            import triton
            path = Path(triton.__file__).resolve().parent / "runtime" / "tcc" / "tcc.exe"
            if not path.is_file():
                raise RuntimeError("installed Triton carries no bundled TinyCC at " + str(path) + "; set CC explicitly")
            os.environ["CC"] = str(path)
            binding = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                       "source": "triton bundled tcc"}
        else:
            binding = {"path": None, "sha256": None, "source": "triton default discovery"}
        _C_COMPILER = binding
    return dict(_C_COMPILER)


def fused_elementwise(name):
    """The torch.compile (inductor) twin of one elementwise chain, built once per process on first CUDA use.

    The eager functions are the CPU reference and stay definitional; on the CUDA candidate path the SAME
    Python function is compiled so each chain executes as fused kernels (forward and, through AOTAutograd,
    backward) instead of ~9 device launches per call (kernel census 2026-09-11: 7,832 elementwise/copy
    kernels per step at 19.7 us mean). Compilation introduces no arithmetic the reference does not declare;
    the per-call equivalence bar and the launch-count reduction are asserted by
    tests/test_issue1945_cia_fused_elementwise.py. Meta and CPU execution never reach this function.
    """
    if name not in _FUSED:
        bind_triton_c_compiler()  # before the first compile; cached, so later chains pay nothing
        _FUSED[name] = torch.compile({"norm": _rms_norm, "rotate": rotate_three_axis}[name])
    return _FUSED[name]


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
        self._resident_experts = ()
        self._resident_capacity = 2
        self._resident_groups = {}
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
        if type(self._resident_groups) is not dict or type(self._resident_capacity) is not int or self._resident_capacity < 2:
            raise ValueError('resident layout and capacity must retain their exact declarations')
        if type(self._resident_experts) is not tuple:
            raise ValueError('resident identities must retain their exact tuple declaration')
        resident_names = {spec.name for spec in equation_inventory() if spec.expert in self._resident_experts}
        if self._resident_experts:
            if self._parameter_device != 'cuda':
                raise ValueError('resident owners require declared CUDA placement')
            from .ember_v0_residency import validate_resident_layout
            validate_resident_layout(self, actual)
        elif self._resident_groups:
            raise ValueError('undeclared resident backing groups')
        def expected_device(name):
            return (torch.device('cpu') if self._parameter_device == 'cuda'
                    and name.startswith('experts.') and name not in resident_names else self._execution_device)
        if any(p.dtype != torch.bfloat16 or p.device != expected_device(name) for name, p in actual.items()):
            raise ValueError("candidate requires BF16 parameters on its declared device")
        if sum(p.numel() for p in actual.values()) != census(self.config).total_unique:
            raise ValueError("candidate census mismatch")
        if self._parameter_device != "meta":
            if any(not p.is_contiguous() or (name not in resident_names and
                   (p.storage_offset() != 0 or p.untyped_storage().nbytes() != p.numel() * p.element_size()))
                   for name, p in actual.items()):
                raise ValueError("physical parameter storage does not match declared elements")
            for device in {p.device for p in actual.values()}:
                ranges = sorted((p.data_ptr(), p.data_ptr() + p.numel() * p.element_size()) for p in actual.values() if p.device == device)
                if any(left[1] > right[0] for left, right in zip(ranges, ranges[1:])):
                    raise ValueError("physical parameter storage alias")
        return actual

    def live_parameters(self):
        """Live whole-model registered-parameter view under RAW registered names, without schema validation.

        Walks named_parameters(remove_duplicate=False) over the whole module tree at every call and keeps the raw
        registered name as the key (no normalization, so a root or child registration can never collide with a
        weights entry); a replaced, removed, re-pointed, duplicated, or newly registered Parameter anywhere is a
        key or object change at the next identity check. The immutable schema/census/alias validation runs at
        step bind and step end through parameter_inventory.
        """
        return dict(self.named_parameters(remove_duplicate=False))

    def owner_declaration(self):
        """Exact-type value snapshot of the non-tensor inputs to parameter_inventory: config and placement.

        Compared by the residency cache at every check. Types travel with the values, so a config replaced by
        its repr string, a placement replaced by a plain string, a different object, or a moved placement is
        refused at the next lease rather than at step end.
        """
        def typed(value):
            if dataclasses.is_dataclass(value) and not isinstance(value, type):
                fields = tuple((name, typed(item)) for name, item in sorted(dataclasses.asdict(value).items()))
            elif isinstance(value, dict):
                fields = tuple((repr(key), typed(item)) for key, item in sorted(value.items(), key=repr))
            elif isinstance(value, (list, tuple)):
                fields = tuple(typed(item) for item in value)
            else:
                fields = repr(value)
            return (type(value).__module__, type(value).__qualname__, fields)
        from .ember_v0_residency import resident_layout_declaration
        return (typed(self.config), typed(self._parameter_device), typed(self._execution_device),
                typed(self._resident_experts), typed(self._resident_capacity), resident_layout_declaration(self))

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

    def activate_cuda(self, device, *, resident_capacity=2, resident_experts=(), optimizer=None):
        """Activate bounded execution, optionally retaining an existing candidate optimizer.

        Caller must reserve the complete host/device envelope. This neither admits
        a generation nor grants launch, checkpoint, learning or throughput credit.
        `resident_capacity` bounds the device-resident expert bundles (int >= 2; default 2,
        the reference behaviour); it does not change per-document routing.
        """
        if self._parameter_device != 'cpu':
            raise ValueError('CUDA activation requires the complete CPU population')
        target = torch.device(device)
        if target.type != 'cuda' or target.index is None:
            raise ValueError('explicit indexed CUDA device required')
        parameters = self.parameter_inventory()
        if type(resident_experts) is not tuple:
            raise ValueError('resident expert identities must be a tuple')
        if resident_experts:
            if (type(resident_capacity) is not int or resident_capacity != 4 or len(resident_experts) != 4
                    or any(type(expert) is not int or not 0 <= expert < 25 for expert in resident_experts)
                    or tuple(sorted(set(resident_experts))) != resident_experts):
                raise ValueError('resident treatment requires capacity four and four ascending expert IDs')
            if any(parameter.requires_grad and spec.expert is not None and spec.expert not in resident_experts
                   for spec in equation_inventory() for parameter in (parameters[spec.name],)):
                raise ValueError('declare frozen non-resident expert support before CUDA activation')
        if any(value.grad is not None for value in parameters.values()):
            raise ValueError('CUDA activation requires a quiescent population without gradients')
        from .ember_v0_residency import CUDAExecution, ResidentExecution, _pack_resident_group
        shared = {name: value for name, value in parameters.items() if not name.startswith('experts.')}
        original = {name: value.data for name, value in shared.items()}
        moved, resident_groups = {}, {}
        old_states = ({parameter: dict(state) for parameter, state in optimizer.state.items()}
                      if optimizer is not None else None)
        staged_states = None
        if optimizer is not None:
            from .ember_v0_residency import _stage_optimizer_placement
            destinations = {id(parameter): (target if not name.startswith('experts.') or
                            int(name.split('.')[1]) in resident_experts else torch.device('cpu'))
                            for name, parameter in parameters.items()}
            staged_states = _stage_optimizer_placement(optimizer, parameters, destinations)
        if resident_experts:
            original.update({name: value.data for name, value in parameters.items()
                             if name.startswith('experts.') and int(name.split('.')[1]) in resident_experts})
        try:
            for name, value in shared.items():
                moved[name] = value.detach().to(target, copy=True)
            if resident_experts:
                for layer in range(1, 24, 2):
                    for projection in ('up', 'gate', 'down'):
                        names = tuple(f'experts.{expert}.layers.{layer}.{projection}.weight' for expert in resident_experts)
                        storage = _pack_resident_group(tuple(parameters[name] for name in names), target)
                        resident_groups[(layer, projection)] = storage
                        moved.update({name: storage[index] for index, name in enumerate(names)})
            torch.cuda.synchronize(target)
            for name, data in moved.items():
                parameters[name].data = data
            self._execution_device = target
            self._parameter_device = 'cuda'
            self._resident_experts = resident_experts
            self._resident_capacity = resident_capacity
            self._resident_groups = resident_groups
            self._cuda_execution = (ResidentExecution(self, target) if resident_experts else
                                    CUDAExecution(self, target, resident_capacity=resident_capacity))
            self.parameter_inventory()
            if optimizer is not None:
                for parameter, state in staged_states.items():
                    optimizer.state[parameter].clear()
                    optimizer.state[parameter].update(state)
        except BaseException:
            for name, data in original.items():
                parameters[name].data = data
            self._execution_device = torch.device('cpu')
            self._parameter_device = 'cpu'
            self._cuda_execution = None
            self._resident_experts, self._resident_capacity, self._resident_groups = (), 2, {}
            if optimizer is not None:
                for parameter, state in old_states.items():
                    optimizer.state[parameter].clear()
                    optimizer.state[parameter].update(state)
            raise
        finally:
            moved.clear()
            original.clear()
        return self

    def deactivate_cuda(self, optimizer=None):
        """Return actual owners and their one optimizer's tensors to CPU custody.

        The caller must clear gradients after the last completed update. This is
        a quiescent transition, not an automatic fallback from a refused step.
        """
        execution = self._cuda_execution
        if self._parameter_device != 'cuda' or execution is None or execution.cache.active:
            raise ValueError('CUDA deactivation requires a quiescent active placement')
        parameters = self.parameter_inventory()
        if any(parameter.grad is not None for parameter in parameters.values()):
            raise ValueError('clear gradients before returning owners to CPU custody')
        if optimizer is None and execution.cache.step_id:
            raise ValueError('completed-step deactivation requires the retained optimizer authority')
        if optimizer is not None:
            if type(optimizer) is not torch.optim.AdamW:
                raise ValueError('deactivation requires the declared AdamW optimizer')
            membership = [parameter for group in optimizer.param_groups for parameter in group['params']]
            if len(membership) != len(parameters) or {id(parameter) for parameter in membership} != {id(parameter) for parameter in parameters.values()}:
                raise ValueError('optimizer membership differs from the complete owner inventory')
            if any(id(parameter) not in {id(owner) for owner in membership} for parameter in optimizer.state):
                raise ValueError('optimizer moment state belongs to an unbound parameter')
            if any(not isinstance(value, (torch.Tensor, float, int))
                   for state in optimizer.state.values() for value in state.values()):
                raise ValueError('optimizer state contains an undeclared value type')
        torch.cuda.synchronize(self._execution_device)
        original = {name: parameter.data for name, parameter in parameters.items()}
        moved = {name: parameter.detach().to('cpu', copy=True)
                 for name, parameter in parameters.items() if parameter.device.type == 'cuda'}
        states = ({parameter: {key: value.to('cpu', copy=True) if isinstance(value, torch.Tensor) else value
                               for key, value in state.items()} for parameter, state in optimizer.state.items()}
                  if optimizer is not None else None)
        previous = (self._parameter_device, self._execution_device, self._resident_experts,
                    self._resident_capacity, self._resident_groups)
        old_states = ({parameter: dict(state) for parameter, state in optimizer.state.items()}
                      if optimizer is not None else None)
        old_options = ([{key: group.get(key) for key in ('capturable', 'foreach')} for group in optimizer.param_groups]
                       if optimizer is not None else None)
        try:
            for name, data in moved.items():
                parameters[name].data = data
            self._parameter_device, self._execution_device = 'cpu', torch.device('cpu')
            self._resident_experts, self._resident_capacity, self._resident_groups = (), 2, {}
            self._cuda_execution = None
            self.parameter_inventory()
            if optimizer is not None:
                for parameter, state in states.items():
                    optimizer.state[parameter].clear()
                    optimizer.state[parameter].update(state)
                for group in optimizer.param_groups:
                    group['capturable'], group['foreach'] = False, False
            if hasattr(execution, 'retired'):
                execution.retired = True
        except BaseException:
            for name, data in original.items():
                parameters[name].data = data
            (self._parameter_device, self._execution_device, self._resident_experts,
             self._resident_capacity, self._resident_groups) = previous
            self._cuda_execution = execution
            if optimizer is not None:
                for parameter, state in old_states.items():
                    optimizer.state[parameter].clear()
                    optimizer.state[parameter].update(state)
                for group, options in zip(optimizer.param_groups, old_options):
                    group.update(options)
            raise
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
        if self._resident_experts and any(spec.name in names and spec.expert is not None
                                         and spec.expert not in self._resident_experts for spec in equation_inventory()):
            raise ValueError('resident mode cannot enable non-resident expert gradients')
        parameters = self.parameter_inventory()
        segmented = getattr(self._cuda_execution, 'segmented', None)
        if segmented is not None:
            segmented.invalidate()
            segmented._cia_invalidated = True
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
        weight = self._weight(name)
        if self._cuda_execution is not None:
            return fused_elementwise("norm")(values, weight)
        return _rms_norm(values, weight)

    def _linear(self, values, name):
        return F.linear(values, self._weight(name))

    # The summation ORDER is a measured property of the reference, never a design choice: it
    # reproduces the saved actual R1 update-1 gradients bitwise on 24 of 24 weights on cuda:0, and
    # ascending reproduces none of them. bf16 reduction bytes are device-dependent -- the same check
    # on CPU returns a confident false negative on every weight -- so the receipts record the device.
    _DOCUMENT_REDUCTION_ORDER = "descending"

    def _document_linear(self, values, name, lengths):
        """Merged forward, weight gradient reduced per document in the measured reference order.

        The forward is byte-identical to the merged F.linear this branch already ran; the input
        gradient is unchanged. Only the weight-gradient reduction shape moves, because that is the
        term that differs from the reference even where the forward is bit-equal.
        """
        return document_reduced_linear(values, self._weight(name), lengths,
                                       self._DOCUMENT_REDUCTION_ORDER)

    def _document_swiglu(self, values, prefix, lengths):
        """Shared SwiGLU on merged rows with each weight gradient reduced per document.

        The resident segment runs this block on the concatenated rows, so all three shared
        projections carry the merged reduction; the reference reduces per document. Forward and
        input gradients are unchanged here -- up, gate and down are all bit-equal merged at this
        geometry -- and only the weight-gradient reduction shape is restored.
        """
        up = self._document_linear(values, prefix + ".up.weight", lengths)
        gate = self._document_linear(values, prefix + ".gate.weight", lengths)
        return self._document_linear(F.silu(gate) * up, prefix + ".down.weight", lengths)

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

    def _per_document(self, function, values, lengths):
        """Apply a GEMM-bearing function to each document's rows separately and concatenate.

        cuBLAS chooses its algorithm from M, so identical rows come back with different bf16 bytes when
        they are projected as part of a larger batch (receipt: linear-m-dependence, 2026-09-11). Row-wise
        work (norms, rotation) is shared on the concatenated tensor; every GEMM runs at the serial path's
        M so the batched forward is the serial computation, not an approximation of it.
        """
        return torch.cat([function(piece) for piece in torch.split(values, lengths)])

    def expert_block(self, values, *, expert, layer):
        self._input(values, 1024)
        if type(expert) is not int or not 0 <= expert < 25:
            raise ValueError("global expert identity outside [0,25)")
        if type(layer) is not int or layer not in range(1, 24, 2):
            raise ValueError("expert blocks exist only at sparse depths")
        if self._cuda_execution is not None:
            return self._cuda_execution.expert_block(values, expert, layer)
        return self._swiglu(values, f"experts.{expert}.layers.{layer}")

    def expert_block_group(self, values, *, expert, layer):
        """Same expert, several 256-row chunks (possibly from different documents), one lease."""
        if type(values) is not tuple or not values:
            raise ValueError("a non-empty tuple of chunk inputs is required")
        for value in values:
            self._input(value, 1024)
        if type(expert) is not int or not 0 <= expert < 25:
            raise ValueError("global expert identity outside [0,25)")
        if type(layer) is not int or layer not in range(1, 24, 2):
            raise ValueError("expert blocks exist only at sparse depths")
        if self._cuda_execution is not None:
            return self._cuda_execution.expert_block_group(values, expert, layer)
        return tuple(self._swiglu(value, f"experts.{expert}.layers.{layer}") for value in values)

    def _attention(self, values, positions, prefix):
        length = len(values)
        q = self._linear(values, prefix + ".q.weight").view(length, 16, 64)
        k = self._linear(values, prefix + ".k.weight").view(length, 4, 64)
        v = self._linear(values, prefix + ".v.weight").view(length, 4, 64)
        q = rotate_three_axis(self._norm(q, prefix + ".q_norm.weight"), positions)
        k = rotate_three_axis(self._norm(k, prefix + ".k_norm.weight"), positions)
        k = k.repeat_interleave(4, dim=1)
        v = v.repeat_interleave(4, dim=1)
        if self._resident_experts:
            out = _document_sdpa(q, k, v, (length,))
            return self._linear(out.reshape(length, 1024), prefix + ".o.weight")
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

    def _batched_attention(self, values, positions, lengths, prefix):
        """Attention over several documents at once; per-document causality is preserved exactly.

        Norms and the three-axis rotation are per-position, so they run once on the concatenated
        [total,1024] tensor; the projections run per document (_per_document: cuBLAS bytes depend on M).
        The CPU reference retains per-document projection and attention arithmetic.
        The CUDA candidate projects the complete batch and runs one 4-D causal
        attention call. Ragged documents use trailing padding; valid queries cannot
        attend to padded keys. Full-model numerical qualification remains required.
        """
        if self._resident_experts:
            total = len(values)
            # Query/output retain merged forwards and use descending document weight-gradient
            # reductions. Key/value use the reference per-document forward and backward below.
            # Order is DESCENDING, measured not chosen: it reproduces the saved actual R1 update-1
            # gradients bitwise on 24 of 24 weights across the attention and shared paths
            # (state/issue1945-receipts/core-dw-order-resolution-cuda.json and
            # shared-dw-order-resolution.json, cuda:0). Ascending matches none of them.
            # k and v carry a SECOND mechanism the merged forward cannot fix: their 1024->256
            # forward is not bit-equal merged (relative L2 .00283-.00289, ~37% of elements), because
            # cuBLAS selects its algorithm from M. So they are restored to the reference's own
            # _per_document construct, which reproduces both its forward AND its weight-gradient
            # reduction exactly rather than reimplementing either. q and o do not need it: their
            # forward is already bit-equal merged, so only their reduction shape moves.
            q = self._document_linear(values, prefix + ".q.weight", lengths).view(total, 16, 64)
            k = self._per_document(lambda piece: self._linear(piece, prefix + ".k.weight"),
                                   values, lengths).view(total, 4, 64)
            v = self._per_document(lambda piece: self._linear(piece, prefix + ".v.weight"),
                                   values, lengths).view(total, 4, 64)
            q = rotate_three_axis(self._norm(q, prefix + ".q_norm.weight"), positions)
            k = rotate_three_axis(self._norm(k, prefix + ".k_norm.weight"), positions)
            out = _document_sdpa(q, k.repeat_interleave(4, dim=1),
                                 v.repeat_interleave(4, dim=1), lengths)
            return self._document_linear(out.reshape(total, 1024), prefix + ".o.weight", lengths)
        total = len(values)
        q = self._per_document(lambda piece: self._linear(piece, prefix + ".q.weight"), values, lengths).view(total, 16, 64)
        k = self._per_document(lambda piece: self._linear(piece, prefix + ".k.weight"), values, lengths).view(total, 4, 64)
        v = self._per_document(lambda piece: self._linear(piece, prefix + ".v.weight"), values, lengths).view(total, 4, 64)
        q = rotate_three_axis(self._norm(q, prefix + ".q_norm.weight"), positions)
        k = rotate_three_axis(self._norm(k, prefix + ".k_norm.weight"), positions)
        k = k.repeat_interleave(4, dim=1)
        v = v.repeat_interleave(4, dim=1)
        pieces, offset = [], 0
        for length in lengths:
            piece = F.scaled_dot_product_attention(
                q[offset:offset + length].transpose(0, 1), k[offset:offset + length].transpose(0, 1),
                v[offset:offset + length].transpose(0, 1), is_causal=True)
            pieces.append(piece.transpose(0, 1).reshape(length, 1024))
            offset += length
        return self._per_document(lambda piece: self._linear(piece, prefix + ".o.weight"), torch.cat(pieces), lengths)

    def _route_local_layer(self, hidden, chunks, *, routing, sparse_depth, capture):
        """Local routing for every 256-row chunk of one sparse layer across all documents.

        One StepRouting.select_local_batch call per sparse layer: the winners of every chunk cross to the
        host in ONE transfer (the legacy select_local loop crossed once per chunk). Returns
        (experts, logits, gates, records): the winner per chunk, the [chunks,2] float logits in ascending
        global-ID order, the native unit_task_gate factor per chunk, and the per-chunk LocalSelection
        records (None unless capture). The decoder never reads anything else from routing.
        """
        batch = routing.select_local_batch(hidden, [chunk['spec'] for chunk in chunks],
                                           sparse_depth=sparse_depth, capture=capture)
        return batch.experts, batch.logits, batch.gates, (batch.locals() if capture else None)

    def bind_segmented_capture(self, *, collector=None, loss_fn=None, static_state=(), warmup_steps=2, capture_experts=False,
                               local_routing_mode='batched'):
        """Bind the actual dense segments and owner Parameters before an exemplar training step."""
        if type(capture_experts) is not bool:
            raise ValueError('capture_experts must be an explicit boolean')
        if type(local_routing_mode) is not str or local_routing_mode not in ('batched', 'per-chunk'):
            raise ValueError('capture binding requires a supported local routing mode')
        from functools import partial
        from .ember_v0_capture import SegmentSpec, SegmentedStep
        from .ember_v0_residency import route_index
        execution = self._cuda_execution
        if (not self._resident_experts or execution is None or execution.active
                or execution.poisoned or execution.retired):
            raise RuntimeError('segment binding requires quiescent current resident execution')
        if collector is not None and not callable(collector):
            raise ValueError('segment collector must be callable')
        lengths = execution._geometry_lengths
        geometry = _resident_geometry(lengths)
        repeats = execution._geometry_repeats
        # #1945: the local router's geometry index tensors are bound here, outside capture, and reused per segment.
        local_index = route_index(geometry, execution.device) if local_routing_mode == 'batched' else None
        index_state = (local_index.rows, local_index.started, local_index.epochs, local_index.zero) if local_index is not None else ()
        state, seen = [], set()
        expert_state = (execution.routing_valid, execution.id_tensor, execution.slot_tensor) if capture_experts else ()
        for value in (execution.input_valid, *expert_state, repeats, *index_state,
                      execution._plan_candidates, execution._plan_winners,
                      *static_state):
            if value is None:
                continue
            if (not isinstance(value, torch.Tensor) or value.requires_grad
                    or value.device != execution.device):
                raise ValueError('capture static state must be nondifferentiable tensors on the execution device')
            if id(value) not in seen:
                seen.add(id(value))
                state.append(value)
        specs = []
        for index in range(13):
            prefixes = (f'layers.{2*index}.', f'layers.{2*index+1}.')
            expert_names = ({f'experts.{expert}.layers.{2*index+1}.{projection}.weight'
                             for expert in self._resident_experts for projection in ('up', 'gate', 'down')}
                            if capture_experts and index < 12 else set())
            params, owners = [], set()
            for stored_name, parameter in self.weights.items():
                name = stored_name.replace('__', '.')
                selected = ((name in ('final_norm.weight', 'embedding.weight')) if index == 12 else
                    (name.startswith(prefixes) or name in expert_names or name == 'router.local_query.weight' or
                     (index == 0 and (name == 'router.global_query.weight' or name.startswith('router.layers.')))))
                if selected and parameter.requires_grad and id(parameter) not in owners:
                    owners.add(id(parameter))
                    params.append(parameter)
            fn = partial(self._resident_segment, index, lengths=lengths, geometry=geometry,
                         repeats=repeats, collector=collector, capture_experts=capture_experts,
                         local_index=local_index, local_routing_mode=local_routing_mode)
            specs.append(SegmentSpec(index, fn, tuple(params), tuple(state), f'dense-{index}'))
        step = SegmentedStep(specs, device=execution.device, warmup_steps=warmup_steps).bind(execution, loss_fn=loss_fn)
        step._cia_lengths, step._cia_collector, step._cia_invalidated = lengths, collector, False
        step._cia_capture_experts = capture_experts
        previous = getattr(execution, 'segmented', None)
        if previous is not None:
            previous.invalidate()
        execution.segmented = step
        return step

    def _resident_segment(self, index, *carry, lengths, geometry, repeats, collector=None, capture_experts=False,
                          local_index=None, local_routing_mode='batched'):
        """One dense forward segment; every differentiable cross-segment value is carried explicitly."""
        from .ember_v0_residency import resident_global_routes, resident_local_routes
        if type(index) is not int or not 0 <= index <= 12:
            raise ValueError('resident segment index must be 0..12')
        execution = self._cuda_execution
        if index == 0:
            embedded, positions = carry
            values = embedded
            keys = torch.stack([self._weight(f'router.layers.{layer}.keys') for layer in range(1, 24, 2)])
            actual_geometry, priors, ranked, candidates, valid = resident_global_routes(
                embedded, lengths, self._weight('router.global_query.weight'), keys)
            if actual_geometry != geometry:
                raise ValueError('resident segment geometry differs from its bound documents')
            execution.require_valid(valid, 'routing')
            if collector is not None:
                collector('global', dict(geometry=geometry, priors=priors.detach().clone(),
                                        ranked=ranked.detach().clone(), candidates=candidates.detach().clone()))
            history = None
        else:
            shared, residual, _, row_gates, positions, keys, priors, ranked, candidates, history = carry
            values = shared + residual * row_gates[:, None].to(residual.dtype)
            if index == 12:
                logits = self._linear(self._norm(values, 'final_norm.weight'), 'embedding.weight')
                return logits, ranked, history
        sizes = tuple(row[3] for row in geometry.chunks)
        equal = len(set(sizes)) == 1
        for layer in (2 * index, 2 * index + 1):
            prefix = f'layers.{layer}'
            values = values + self._batched_attention(
                self._norm(values, prefix + '.attention_norm.weight'), positions, lengths, prefix + '.attention')
            shared = values + self._document_swiglu(
                self._norm(values, prefix + '.shared_norm.weight'), prefix + '.shared', lengths)
            if layer % 2 == 0:
                values = shared
                continue
            winners, logits, gates, valid = resident_local_routes(
                shared, self._weight('router.local_query.weight'), keys, layer // 2,
                geometry, priors, candidates, index=local_index, local_routing_mode=local_routing_mode)
            execution.require_valid(valid, 'routing')
            native_winners = winners
            winners, gates = execution.planned_routes(layer//2, geometry, candidates, winners, logits, gates)
            if equal:
                row_experts = winners.repeat_interleave(sizes[0])
                row_gates = gates.repeat_interleave(sizes[0])
            else:
                row_experts = torch.repeat_interleave(winners, repeats, output_size=sum(lengths))
                row_gates = torch.repeat_interleave(gates, repeats, output_size=sum(lengths))
            normed = self._norm(shared, prefix + '.expert_norm.weight')
            history = (winners.detach()[None, :] if history is None else
                       torch.cat((history, winners.detach()[None, :]), dim=0))
            if collector is not None:
                collector('local', dict(layer=layer, winners=winners.detach().clone(), logits=logits.detach().clone(),
                                       gates=gates.detach().clone(), valid=valid.detach().clone(), native_winners=native_winners.detach().clone()))
        if capture_experts:
            normed = execution.grouped_block(normed, row_experts, 2 * index + 1, backend='dynamic')
        return shared, normed, row_experts, row_gates, positions, keys, priors, ranked, candidates, history

    def _resident_documents_forward(self, documents, *, collector=None, plan=None):
        from .ember_v0_residency import ResidentRouteTrace
        execution = self._cuda_execution
        execution.check()
        execution.check_route_plan(plan)
        lengths = tuple(len(embedded) for embedded, _, _ in documents)
        embedded = torch.cat([item[0] for item in documents])
        positions = torch.cat([item[1] for item in documents])
        geometry = _resident_geometry(lengths)
        repeats = execution.geometry_repeats(lengths, tuple(row[3] for row in geometry.chunks))
        step = getattr(execution, 'segmented', None)
        if step is not None:
            if step._cia_invalidated:
                raise ValueError('resident capture requires rebinding after a geometry, plan or support change')
            bound_collector = step._cia_collector
            same_collector = (collector is bound_collector or
                (getattr(collector, '__func__', None) is not None and
                 getattr(collector, '__func__', None) is getattr(bound_collector, '__func__', None) and
                 getattr(collector, '__self__', None) is getattr(bound_collector, '__self__', None)))
            if step._cia_lengths != lengths or not same_collector:
                raise ValueError('resident capture geometry or collector differs from its bound source')
        carry = (embedded, positions)
        for index in range(13):
            if step is None:
                carry = self._resident_segment(index, *carry, lengths=lengths, geometry=geometry,
                                               repeats=repeats, collector=collector)
            else:
                carry = step.run(index, *carry)
            if index < 12 and not (step is not None and step._cia_capture_experts):
                shared, normed, row_experts, *tail = carry
                residual = execution.grouped_block(normed, row_experts, 2 * index + 1)
                carry = (shared, residual, row_experts, *tail)
        logits, ranked, winners = carry
        outputs = logits.split(lengths)
        trace = ResidentRouteTrace(execution, execution.step_id, geometry, ranked.detach(), tuple(winners.unbind(0)))
        return outputs, trace

    def _batched_documents_forward(self, documents, *, observer=None, plan=None):
        """Document-batched core path with one expert call per expert per sparse layer.

        Per document the computation is the one _document_forward performs: norms and the three-axis
        rotation run once over the concatenation of all documents; every GEMM (q/k/v/o, shared SwiGLU,
        unembedding) runs per document at the serial path's M (_per_document); attention is one 3-D call
        per document. Routing goes through one StepRouting per step: select_global per document epoch,
        then ONE select_local_batch call per sparse layer for every chunk. At each sparse layer the chunks
        routed to an expert, across all documents, are the members of one expert_block_group call (one
        lease per expert per layer, per-chunk GEMMs at the serial 256-row shape) and the residual is
        scattered back under the per-chunk gate. Routes are returned in (document, layer, start) order,
        which is the serial order. Observer calls arrive layer-major rather than document-major.
        """
        keys = torch.stack([self._weight(f"router.layers.{layer}.keys") for layer in range(1, 24, 2)])
        generation = ('cpu-conformance' if self._cuda_execution is None else
                      f'cuda-candidate-step-{self._cuda_execution.cache.step_id}')
        lengths = [len(embedded) for embedded, _, _ in documents]
        total = sum(lengths)
        embedded_all = torch.cat([embedded for embedded, _, _ in documents])
        positions_all = torch.cat([positions for _, positions, _ in documents])
        device = embedded_all.device
        routing = StepRouting(self._weight("router.global_query.weight"),
                              self._weight("router.local_query.weight"), keys, generation)
        try:
            return self._batched_documents_body(
                documents, lengths, total, embedded_all, positions_all, device, keys, generation,
                routing, observer=observer, plan=plan)
        finally:
            routing.close()

    def _batched_documents_body(self, documents, lengths, total, embedded_all, positions_all, device,
                                keys, generation, routing, *, observer, plan):
        metas, offset = [], 0
        for (embedded, positions, document_index), length in zip(documents, lengths):
            request = f"{generation}-document-{document_index}"
            selections = {start: routing.select_global(
                embedded, position=start, document_start=0, request=request)
                for start in range(0, length, 1024)}
            if observer is not None:
                for start in sorted(selections):
                    observer(observe_global(selections[start], document=document_index))
            metas.append(dict(index=document_index, request=request, selections=selections,
                              offset=offset, length=length))
            offset += length
        chunk_specs = [dict(index=meta['index'], request=meta['request'], offset=meta['offset'],
                            length=meta['length'], start=start, size=min(256, meta['length'] - start),
                            selection=meta['selections'][(start // 1024) * 1024],
                            spec=ChunkSpec(document_offset=meta['offset'], start=start,
                                           selection=meta['selections'][(start // 1024) * 1024],
                                           request=meta['request']))
                       for meta in metas for start in range(0, meta['length'], 256)]
        sizes = [chunk['size'] for chunk in chunk_specs]
        uniform = len(set(sizes)) == 1
        size_tensor = None if uniform else torch.tensor(sizes, dtype=torch.long, device=device)
        values = embedded_all
        routes = []
        for layer in range(24):
            prefix = f"layers.{layer}"
            values = values + self._batched_attention(
                self._norm(values, prefix + ".attention_norm.weight"), positions_all, lengths, prefix + ".attention")
            shared = values + self._per_document(
                lambda piece: self._swiglu(piece, prefix + ".shared"),
                self._norm(values, prefix + ".shared_norm.weight"), lengths)
            if not layer % 2:
                values = shared
                continue
            experts, logits, gates, records = self._route_local_layer(
                shared, chunk_specs, routing=routing, sparse_depth=layer // 2,
                capture=observer is not None)
            if observer is not None:
                for chunk, record in zip(chunk_specs, records):
                    observer(observe_local(record, document=chunk['index'], layer=layer))
            chosen, slots = [], []
            for chunk, expert in zip(chunk_specs, experts):
                candidates = tuple(sorted(chunk['selection'].experts))
                # Ascending global-ID order, matching what select_local scores and what a plan records.
                winner = expert if plan is None else self._planned_expert(
                    plan, (chunk['index'], layer, chunk['start']), candidates)
                chosen.append(winner)
                slots.append(candidates.index(winner))
                routes.append((chunk['index'], layer, chunk['start'], chunk['selection'].experts, winner))
            normed = self._norm(shared, prefix + ".expert_norm.weight")
            # Grouped by expert, ONE lease per expert per layer; the members are the ORIGINAL contiguous
            # chunks (256 rows, tail shorter), so every per-chunk GEMM has the serial path's shape and its
            # accumulation. One concatenated member per expert was a different GEMM shape and missed the
            # post-step bar on CUDA (rel-L2 0.0505 at mixed lengths); chunk-shaped members keep the lease
            # saving and the serial numerics.
            order, outputs = [], []
            for expert in sorted(set(chosen)):
                members = []
                for chunk, winner in zip(chunk_specs, chosen):
                    if winner == expert:
                        first = chunk['offset'] + chunk['start']
                        order.extend(range(first, first + chunk['size']))
                        members.append(normed[first:first + chunk['size']])
                outputs.extend(self.expert_block_group(tuple(members), expert=expert, layer=layer))
            inverse = [0] * total
            for rank, row in enumerate(order):
                inverse[row] = rank
            inverse_tensor = torch.tensor(inverse, dtype=torch.long, device=device)
            residual = torch.cat(outputs).index_select(0, inverse_tensor)
            # The gate consumes the NATIVE logits per chunk (unit forward, selected-softmax derivative),
            # broadcast over that chunk's rows; only the discrete winner may come from a plan. Without a
            # plan the routing batch's own gates (row-wise, the scalar helper's arithmetic) are used; a
            # plan recomputes the factor at the planned slot from the same native logits.
            if plan is None:
                factor = gates
            else:
                working = logits if logits.dtype == torch.float64 else logits.float()
                probability = working.softmax(1).gather(
                    1, torch.tensor(slots, dtype=torch.long, device=device)[:, None])[:, 0]
                factor = (probability - probability.detach()) + 1.0
            if uniform:
                gate = factor.repeat_interleave(sizes[0])
            else:
                gate = torch.repeat_interleave(factor, size_tensor, output_size=total)
            values = shared + residual * gate[:, None].to(residual.dtype)
        outputs = [self._linear(piece, "embedding.weight")
                   for piece in torch.split(self._norm(values, "final_norm.weight"), lengths)]
        return outputs, sorted(routes, key=lambda row: row[:3])

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
                route_observer=None, route_plan=None, batch_documents=False,
                return_device_routes=False, device_route_collector=None):
        """Numerical execution over explicitly packed, unpadded documents.

        Every document is evaluated independently. There is no co-batch pooling,
        mutable route cache or caller-forced numerical expert. With batch_documents=True the same
        per-document computation runs document-batched: core ops once over the concatenation, attention
        batched per equal-length group, one expert call per expert per sparse layer (see
        _batched_documents_forward); the serial path remains the reference. Replaying a prefix
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
        if self._resident_experts:
            self._cuda_execution.require_valid(torch.isfinite(embedded).all() & (positions >= 0).all(), 'input')
        elif not torch.isfinite(embedded).all() or (positions < 0).any():
            raise ValueError("finite embeddings and nonnegative positions required")
        if (type(document_starts) is not tuple or not document_starts or document_starts[0] != 0
            or any(type(i) is not int or not 0 <= i < len(embedded) for i in document_starts)
            or any(a >= b for a, b in zip(document_starts, document_starts[1:]))):
            raise ValueError("strictly increasing document starts beginning at zero required")
        if type(batch_documents) is not bool:
            raise ValueError("batch_documents must be a bool")
        self.parameter_inventory()
        spans = list(zip(document_starts, document_starts[1:] + (len(embedded),)))
        if type(return_device_routes) is not bool:
            raise ValueError('return_device_routes must be a bool')
        if self._resident_experts:
            if not batch_documents or (return_routes and not return_device_routes):
                raise ValueError('resident execution requires batching and explicit device route returns')
            if route_observer is not None:
                raise ValueError('resident routing requires the device collector and boundary observer adapter')
            if device_route_collector is not None and not callable(device_route_collector):
                raise ValueError('device route collector must be callable')
            outputs, routes = self._resident_documents_forward(
                [(embedded[start:end], positions[start:end], index) for index, (start,end) in enumerate(spans)],
                collector=device_route_collector, plan=route_plan)
            logits = torch.cat(outputs)
            return (logits, routes) if return_routes else logits
        if return_device_routes or device_route_collector is not None:
            raise ValueError('device routing options require explicit resident execution')
        if batch_documents:
            outputs, routes = self._batched_documents_forward(
                [(embedded[start:end], positions[start:end], index) for index, (start, end) in enumerate(spans)],
                observer=route_observer, plan=route_plan)
        else:
            outputs, routes = [], []
            for index, (start, end) in enumerate(spans):
                result, document_routes = self._document_forward(
                    embedded[start:end], positions[start:end], index,
                    observer=route_observer, plan=route_plan)
                outputs.append(result)
                routes.extend(document_routes)
        logits = torch.cat(outputs)
        return (logits, tuple(routes)) if return_routes else logits
