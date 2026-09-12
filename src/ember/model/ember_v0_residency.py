"""Bounded CIA expert execution; caller owns launch and candidate update authority."""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from collections import OrderedDict
from contextlib import contextmanager
import time
import torch
import torch.nn.functional as F
from torch.autograd.function import once_differentiable
from .ember_v0_inventory import equation_inventory


class ExpertCache:
    @staticmethod
    def validate_sources(bank):
        parameters = [value for row in bank.values() for value in row.values()]
        if any(not isinstance(value, torch.nn.Parameter) or value.device.type != 'cpu'
               for value in parameters):
            raise ValueError('expert source ownership requires CPU Parameters')
        if any(not value.is_contiguous() or value.storage_offset() != 0
               or value.untyped_storage().nbytes() != value.numel() * value.element_size()
               for value in parameters):
            raise ValueError('expert source requires complete contiguous storage')
        ranges = sorted((value.data_ptr(), value.data_ptr() + value.untyped_storage().nbytes())
                        for value in parameters)
        if any(left[1] > right[0] for left, right in zip(ranges, ranges[1:])):
            raise ValueError('expert source storage alias')

    def __init__(self, bank, *, device, owner_parameters=None, resident_capacity=2, owner_validate=None,
                 owner_declaration=None):
        self.validate_sources(bank)
        # Device-resident bundle slots: an execution bound, not a routing quantity. Per-document routing
        # still selects two of the global experts per epoch regardless of how many bundles may stay resident.
        if type(resident_capacity) is not int or resident_capacity < 2:
            raise ValueError('resident_capacity must be an int >= 2')
        self.resident_capacity = resident_capacity
        self.bank = bank
        self.device = device
        self.entries = OrderedDict()
        self.active = False
        self.pending = 0
        self.leased = set()
        self.peak_resident_bundles = 0
        # Dispatch accounting for the bound phase decomposition; never a performance claim.
        self.lease_count = 0
        self.miss_count = 0
        self.eviction_count = 0
        self.transfer_bytes = 0
        self.transfer_seconds = 0.0
        self.step_id = 0
        self.owner_parameters = owner_parameters
        # Full owner validation (schema, census, alias) runs at step bind and step end; per-lease identity reads
        # the live owner registry through owner_parameters and compares the per-tensor signature below.
        self.owner_validate = owner_validate
        # Snapshot of the owner's non-tensor validation inputs (declared config and placement); compared at
        # every check like the tensor signature, because those declarations are inputs to owner_validate.
        self.owner_declaration = owner_declaration
        self.poisoned = False

    @property
    def resident_count(self):
        return len(self.entries)

    def synchronize(self):
        if self.device.type == 'cuda':
            try:
                torch.cuda.synchronize(self.device)
            except RuntimeError:
                self.poisoned = True
                raise

    @staticmethod
    def _signature(value):
        # Every field a between-lease mutation can move: object, in-place version, storage address/offset/size,
        # shape, layout (stride), dtype, device, grad requirement. Read from the live object at every check.
        return (id(value), value._version, value.data_ptr(), value.storage_offset(), value.untyped_storage().nbytes(),
                tuple(value.shape), tuple(value.stride()), value.dtype, value.device, value.requires_grad)

    def identity(self):
        signature = {(expert, name): self._signature(value)
                     for expert, row in self.bank.items() for name, value in row.items()}
        if self.owner_parameters is not None:
            owned = self.owner_parameters()
            owner_ids = {id(value) for value in owned.values()}
            if any(id(value) not in owner_ids for row in self.bank.values() for value in row.values()):
                raise RuntimeError('cache bank ownership changed')
            signature.update({('owner', name): self._signature(value) for name, value in owned.items()})
        if self.owner_declaration is not None:
            signature[('declaration', 'owner')] = self.owner_declaration()
        return signature

    def check(self):
        if not self.active:
            raise RuntimeError('expert execution requires a candidate step')
        if self.identity() != self.bound:
            raise RuntimeError('candidate parameters changed during the step')

    @contextmanager
    def step(self):
        if self.poisoned:
            raise RuntimeError('failed CUDA completion requires fresh execution state')
        if self.active:
            raise RuntimeError('candidate step is already active')
        self.validate_sources(self.bank)
        if self.owner_validate is not None:
            self.owner_validate()
        bound = self.identity()
        self.active = True
        self.step_id += 1
        self.bound = bound
        self.pending = 0
        try:
            yield
            self.check()
            if self.owner_validate is not None:
                self.owner_validate()
                self.check()
            if self.pending:
                raise RuntimeError('incomplete expert backward')
        finally:
            try:
                self.synchronize()
            finally:
                self.entries.clear()
                self.leased.clear()
                self.active = False

    @contextmanager
    def lease(self, expert):
        self.check()
        if type(expert) is not int or expert not in self.bank:
            raise ValueError('unknown global expert identity')
        if expert in self.leased:
            raise RuntimeError('reentrant expert lease')
        self.lease_count += 1
        if expert not in self.entries:
            self.miss_count += 1
            started = time.perf_counter()
            if len(self.entries) >= self.resident_capacity:
                available = next((key for key in self.entries if key not in self.leased), None)
                if available is None:
                    raise RuntimeError('all expert slots are already leased')
                self.synchronize()
                self.eviction_count += 1
                del self.entries[available]
            copied = {}
            try:
                for name, source in self.bank[expert].items():
                    copied[name] = source.detach().to(device=self.device, copy=True)
                    self.transfer_bytes += source.numel() * source.element_size()
                # Timed with the synchronize inside: an asynchronous copy whose cost is measured
                # before it lands is not a measurement of the transfer.
                self.synchronize()
                self.entries[expert] = copied
            except BaseException:
                self.synchronize()
                copied.clear()
                raise
            finally:
                self.transfer_seconds += time.perf_counter() - started
            self.peak_resident_bundles = max(self.peak_resident_bundles, len(self.entries))
        self.entries.move_to_end(expert)
        self.leased.add(expert)
        try:
            yield self.entries[expert]
        finally:
            self.synchronize()
            self.leased.remove(expert)


def _swiglu(value, up, gate, down):
    return F.linear(F.silu(F.linear(value, gate)) * F.linear(value, up), down)


class _PagedSwiGLU(torch.autograd.Function):
    @staticmethod
    def forward(ctx, value, up, gate, down, cache, expert, names):
        cache.check()
        ctx.cache = cache
        ctx.expert = expert
        ctx.step_id = cache.step_id
        ctx.completed = False
        ctx.names = names
        ctx.save_for_backward(value, up, gate, down)
        with cache.lease(expert) as weights:
            result = _swiglu(value, *(weights[name] for name in names))
        ctx.counted = any(ctx.needs_input_grad[:4])
        if ctx.counted:
            cache.pending += 1
        return result

    @staticmethod
    @once_differentiable
    def backward(ctx, output_gradient):
        cache = ctx.cache
        cache.check()
        if ctx.step_id != cache.step_id or ctx.completed:
            raise RuntimeError('stale or repeated expert backward')
        value, up, gate, down = ctx.saved_tensors
        with cache.lease(ctx.expert) as weights:
            with torch.enable_grad():
                inputs = [value.detach().requires_grad_(True)]
                inputs.extend(weights[name].detach().requires_grad_(True) for name in ctx.names)
                result = _swiglu(*inputs)
                gradients = torch.autograd.grad(result, inputs, output_gradient)
            returned = tuple(gradient.to(source.device) if required else None
                             for gradient, source, required in zip(gradients, (value, up, gate, down), ctx.needs_input_grad[:4]))
            del result, inputs, gradients
        if ctx.counted:
            cache.pending -= 1
        ctx.completed = True
        return *returned, None, None, None


def paged_swiglu(value, cache, expert, *, names=('up', 'gate', 'down')):
    cache.check()
    if value.device != cache.device:
        raise ValueError('input device differs from the expert cache')
    row = cache.bank[expert]
    if not torch.is_grad_enabled():
        with cache.lease(expert) as weights:
            return _swiglu(value, *(weights[name] for name in names))
    return _PagedSwiGLU.apply(value, *(row[name] for name in names), cache, expert, names)


def _swiglu_group_gradients(value, bundle, output_gradient):
    """First-order chunk derivatives, retaining native BF16 operation shapes.

    Contiguous matrices use the same native derivative operations directly. The
    final down projection need not be recomputed: its derivative uses the hidden
    product and upstream gradient. Other ranks/layouts retain framework backward.
    """
    up, gate, down = bundle
    if all(tensor.ndim == 2 and tensor.is_contiguous()
           for tensor in (value, output_gradient, *bundle)):
        gate_projection = F.linear(value, gate)
        activated = F.silu(gate_projection)
        up_projection = F.linear(value, up)
        hidden = activated * up_projection
        hidden_gradient = output_gradient.mm(down)
        up_gradient = hidden_gradient * activated
        gate_gradient = torch.ops.aten.silu_backward.default(
            hidden_gradient * up_projection, gate_projection)
        value_gradient = up_gradient.mm(up) + gate_gradient.mm(gate)
        return (value_gradient, up_gradient.t().mm(value), gate_gradient.t().mm(value),
                output_gradient.t().mm(hidden))
    with torch.enable_grad():
        inputs = [value.detach().requires_grad_(True)]
        inputs.extend(weight.detach().requires_grad_(True) for weight in bundle)
        result = _swiglu(*inputs)
        return torch.autograd.grad(result, inputs, output_gradient)


class _PagedSwiGLUGroup(torch.autograd.Function):
    """Several same-expert chunks under ONE lease per pass.

    Numerically each chunk is the identical per-chunk _swiglu the single-chunk path runs (same shapes,
    same kernels, same inputs), so forward outputs are bit-identical to separate calls; only the bundle
    transfer and the per-lease synchronize are shared. Weight gradients retain their native dtype
    and per-chunk summation order on the execution device, then transfer once per required weight
    to its source device. This explicit order differs from the serial path's autograd accumulation.
    """
    @staticmethod
    def forward(ctx, up, gate, down, cache, expert, names, *values):
        cache.check()
        ctx.cache = cache
        ctx.expert = expert
        ctx.step_id = cache.step_id
        ctx.completed = False
        ctx.names = names
        ctx.save_for_backward(up, gate, down, *values)
        with cache.lease(expert) as weights:
            bundle = tuple(weights[name] for name in names)
            results = tuple(_swiglu(value, *bundle) for value in values)
        ctx.counted = any(ctx.needs_input_grad[:3]) or any(ctx.needs_input_grad[6:])
        if ctx.counted:
            cache.pending += 1
        return results

    @staticmethod
    @once_differentiable
    def backward(ctx, *output_gradients):
        cache = ctx.cache
        cache.check()
        if ctx.step_id != cache.step_id or ctx.completed:
            raise RuntimeError('stale or repeated expert backward')
        up, gate, down, *values = ctx.saved_tensors
        value_gradients = []
        weight_gradients = [None, None, None]
        with cache.lease(ctx.expert) as weights:
            bundle = tuple(weights[name] for name in ctx.names)
            for value, output_gradient in zip(values, output_gradients):
                gradients = _swiglu_group_gradients(value, bundle, output_gradient)
                value_gradients.append(gradients[0])
                for index, gradient in enumerate(gradients[1:]):
                    if ctx.needs_input_grad[index]:
                        weight_gradients[index] = (gradient if weight_gradients[index] is None
                                                   else weight_gradients[index] + gradient)
                del gradients
            for index, source in enumerate((up, gate, down)):
                if weight_gradients[index] is not None:
                    weight_gradients[index] = weight_gradients[index].to(source.device)
        if ctx.counted:
            cache.pending -= 1
        ctx.completed = True
        returned_values = tuple(gradient if required else None
                                for gradient, required in zip(value_gradients, ctx.needs_input_grad[6:]))
        return (*weight_gradients, None, None, None, *returned_values)


def paged_swiglu_group(values, cache, expert, *, names=('up', 'gate', 'down')):
    """One expert, several chunks, one lease per pass. Same per-chunk numerics as paged_swiglu."""
    cache.check()
    if type(values) is not tuple or not values:
        raise ValueError('a non-empty tuple of chunk inputs is required')
    if any(value.device != cache.device for value in values):
        raise ValueError('input device differs from the expert cache')
    row = cache.bank[expert]
    if not torch.is_grad_enabled():
        with cache.lease(expert) as weights:
            bundle = tuple(weights[name] for name in names)
            return tuple(_swiglu(value, *bundle) for value in values)
    return _PagedSwiGLUGroup.apply(*(row[name] for name in names), cache, expert, names, *values)


def expert_bundles(parameters):
    """Bind the complete25x36 inventory; no caller-selected reduced population."""
    specs = equation_inventory()
    if set(parameters) != {spec.name for spec in specs}:
        raise ValueError('complete CIA parameter inventory required')
    bundles = {expert: {} for expert in range(25)}
    for spec in specs:
        value = parameters[spec.name]
        if tuple(value.shape) != spec.shape or value.dtype != torch.bfloat16:
            raise ValueError('CIA parameter shape or dtype differs from inventory')
        if spec.expert is not None:
            bundles[spec.expert][spec.name] = value
    if any(len(row) != 36 for row in bundles.values()):
        raise ValueError('each global expert must own36 tensors')
    return bundles


class CUDAExecution:
    mode = 'paged'
    retired = False
    """One candidate's execution state, never a serving/admission generation."""
    def __init__(self, model, device, *, resident_capacity=2):
        device = torch.device(device)
        if device.type != 'cuda' or device.index is None:
            raise ValueError('an explicit indexed CUDA device is required')
        self.model = model
        self.device = device
        self.cache = ExpertCache(expert_bundles(model.parameter_inventory()), device=device,
                                 owner_parameters=model.live_parameters, owner_validate=model.parameter_inventory,
                                 owner_declaration=model.owner_declaration, resident_capacity=resident_capacity)

    @contextmanager
    def step(self):
        if self.retired or self.model._cuda_execution is not self:
            raise RuntimeError('CUDA execution is no longer the active owner placement')
        current = expert_bundles(self.model.parameter_inventory())
        if any(current[expert][name] is not value
               for expert, row in self.cache.bank.items() for name, value in row.items()):
            raise RuntimeError('expert ownership changed after CUDA activation')
        with self.cache.step():
            yield

    def expert_block(self, values, expert, layer):
        names = tuple(f'experts.{expert}.layers.{layer}.{name}.weight' for name in ('up', 'gate', 'down'))
        return paged_swiglu(values, self.cache, expert, names=names)

    def expert_block_group(self, values, expert, layer):
        names = tuple(f'experts.{expert}.layers.{layer}.{name}.weight' for name in ('up', 'gate', 'down'))
        return paged_swiglu_group(values, self.cache, expert, names=names)


def _pack_resident_group(parameters, device):
    """Stage one complete disjoint group before changing any Parameter owner."""
    if (type(parameters) is not tuple or len(parameters) != 4
            or any(type(value) is not torch.nn.Parameter for value in parameters)
            or len({id(value) for value in parameters}) != 4):
        raise ValueError('four distinct resident Parameter owners required')
    shape = parameters[0].shape
    if any(value.device.type != 'cpu' or value.dtype != torch.bfloat16
           or value.shape != shape or value.ndim != 2 or not value.is_contiguous()
           or value.storage_offset() != 0
           or value.untyped_storage().nbytes() != value.numel() * value.element_size()
           or value.grad is not None for value in parameters):
        raise ValueError('resident activation requires complete quiescent CPU matrices')
    ranges = sorted((value.data_ptr(), value.data_ptr() + value.numel() * value.element_size())
                    for value in parameters)
    if any(left[1] > right[0] for left, right in zip(ranges, ranges[1:])):
        raise ValueError('resident source storage overlap')
    return torch.stack(tuple(value.detach() for value in parameters)).to(device)


def _validate_resident_group(parameters, storage):
    """Every declared owner must cover exactly its disjoint row of the group."""
    if (type(parameters) is not tuple or len(parameters) != 4
            or not isinstance(storage, torch.Tensor) or storage.ndim != 3
            or storage.shape[0] != 4 or not storage.is_contiguous()
            or storage.storage_offset() != 0 or storage.dtype != torch.bfloat16
            or storage.untyped_storage().nbytes() != storage.numel() * storage.element_size()):
        raise ValueError('resident group backing storage declaration differs')
    for index, parameter in enumerate(parameters):
        expected = storage[index]
        if (type(parameter) is not torch.nn.Parameter or parameter.device != storage.device
                or parameter.dtype != storage.dtype or parameter.shape != expected.shape
                or parameter.stride() != expected.stride()
                or parameter.data_ptr() != expected.data_ptr()
                or parameter.storage_offset() != expected.storage_offset()
                or parameter.untyped_storage().data_ptr() != storage.untyped_storage().data_ptr()
                or parameter.untyped_storage().nbytes() != storage.untyped_storage().nbytes()):
            raise ValueError('resident Parameter does not own its exact declared group slice')


def _grouped_swiglu(value, up, gate, down, offsets, backend='native'):
    if backend == 'dynamic':
        from .ember_v0_grouped_capture import grouped_mm
        hidden = F.silu(grouped_mm(value, gate.transpose(1, 2), offsets))
        hidden = hidden * grouped_mm(value, up.transpose(1, 2), offsets)
        return grouped_mm(hidden, down.transpose(1, 2), offsets)
    if backend != 'native':
        raise ValueError('unknown resident grouped backend')
    hidden = F.silu(F.grouped_mm(value, gate.transpose(1, 2), offs=offsets))
    hidden = hidden * F.grouped_mm(value, up.transpose(1, 2), offs=offsets)
    return F.grouped_mm(hidden, down.transpose(1, 2), offs=offsets)


class _ResidentGroupedSwiGLU(torch.autograd.Function):
    """Grouped kernels share storage; gradients belong to the actual Parameters."""
    @staticmethod
    def forward(ctx, value, offsets, execution, layer, backend, *parameters):
        execution.check()
        ctx.execution, ctx.layer, ctx.step_id = execution, layer, execution.step_id
        ctx.completed = False
        ctx.backend = backend
        ctx.save_for_backward(value, offsets, *parameters)
        ctx.counted = ctx.needs_input_grad[0] or any(ctx.needs_input_grad[5:])
        ctx.retained = None
        if ctx.counted:
            execution.pending += 1
            if backend == 'dynamic':
                # Retain the identical operation graph rather than repeat the
                # three projections during backward. The outer Function still
                # returns each gradient to its exact resident Parameter owner.
                with torch.enable_grad():
                    inputs = [value.detach().requires_grad_(True)]
                    inputs.extend(group.detach().requires_grad_(True)
                                  for group in execution.layer_groups(layer))
                    result = _grouped_swiglu(*inputs, offsets, backend)
                ctx.retained = (result, inputs)
                return result.detach()
        return _grouped_swiglu(value, *execution.layer_groups(layer), offsets, backend)

    @staticmethod
    @once_differentiable
    def backward(ctx, output_gradient):
        execution = ctx.execution
        execution.check()
        if execution.step_id != ctx.step_id or ctx.completed:
            raise RuntimeError('stale or repeated resident grouped backward')
        value, offsets, *parameters = ctx.saved_tensors
        if ctx.retained is not None:
            result, inputs = ctx.retained
        else:
            with torch.enable_grad():
                inputs = [value.detach().requires_grad_(True)]
                inputs.extend(group.detach().requires_grad_(True) for group in execution.layer_groups(ctx.layer))
                result = _grouped_swiglu(*inputs, offsets, ctx.backend)
        gradients = torch.autograd.grad(result, inputs, output_gradient)
        ctx.retained = None
        returned = tuple(gradient[index] if required else None
                         for gradient, requirements in zip(gradients[1:],
                             (ctx.needs_input_grad[5:9], ctx.needs_input_grad[9:13], ctx.needs_input_grad[13:17]))
                         for index, required in enumerate(requirements))
        if ctx.counted:
            execution.pending -= 1
        ctx.completed = True
        return (gradients[0] if ctx.needs_input_grad[0] else None, None, None, None, None, *returned)


def _resident_bindings(model, parameters):
    ids = model._resident_experts
    if (type(ids) is not tuple or len(ids) != 4 or any(type(expert) is not int or not 0 <= expert < 25 for expert in ids)
            or tuple(sorted(set(ids))) != ids or type(model._resident_capacity) is not int
            or model._resident_capacity != 4):
        raise ValueError('resident mode requires four ascending declared expert identities and capacity four')
    return {(layer, projection): tuple(parameters[f'experts.{expert}.layers.{layer}.{projection}.weight']
                                      for expert in ids)
            for layer in range(1, 24, 2) for projection in ('up', 'gate', 'down')}


def validate_resident_layout(model, parameters):
    groups = _resident_bindings(model, parameters)
    if type(model._resident_groups) is not dict or model._resident_groups.keys() != groups.keys():
        raise ValueError('resident group declaration does not cover every sparse layer and projection')
    for key, owners in groups.items():
        storage = model._resident_groups[key]
        if storage.device != model._execution_device:
            raise ValueError('resident group placement differs from the declared execution device')
        _validate_resident_group(owners, storage)


def resident_layout_declaration(model):
    """Metadata only: declaring a CUDA tensor must not read its values on the host."""
    if type(model._resident_groups) is not dict:
        return (type(model._resident_groups).__name__, 'invalid resident group container')
    return tuple((key, type(value).__module__, type(value).__qualname__, id(value), value._version,
                  tuple(value.shape), tuple(value.stride()), str(value.device), str(value.dtype),
                  value.data_ptr(), value.storage_offset(), value.untyped_storage().nbytes())
                 if isinstance(value, torch.Tensor) else (key, type(value).__name__, 'invalid group')
                 for key, value in sorted(model._resident_groups.items()))


class ResidentRoutingRefusal(ValueError):
    def __init__(self, step_id, unknown):
        self.receipt = {'schema': 'cia-resident-routing-refusal-v1', 'status': 'refused',
                        'step_id': step_id, 'unknown_experts': sorted(set(unknown)),
                        'applied_positions': 0}
        super().__init__('routed expert is outside the admitted resident set')


class ResidentExecution:
    """Actual CUDA Parameter owners; ordinary step exit validates before an update.

    Capture consumers must separately call begin_step/end_step around graph replay
    and accept routing before an optimizer update. This object owns no optimizer.
    """
    mode = 'resident'

    def __init__(self, model, device):
        self.model, self.device = model, torch.device(device)
        validate_resident_layout(model, model.parameter_inventory())
        self.cache = self
        self.resident_capacity = 4
        self.active = self.poisoned = self.retired = False
        self.pending = self.step_id = 0
        self.lease_count = self.miss_count = self.eviction_count = 0
        self.transfer_bytes = 0
        self.transfer_seconds = 0.0
        self.peak_resident_bundles = 4
        self.ids = model._resident_experts
        self.id_tensor = torch.tensor(self.ids, dtype=torch.long, device=self.device)
        self.slot_tensor = torch.arange(4, device=self.device)
        self.routing_valid = torch.ones((), dtype=torch.bool, device=self.device)
        self.routed = []
        self.input_valid = torch.ones(3, dtype=torch.bool, device=self.device)
        self._geometry_lengths, self._geometry_sizes, self._geometry_repeats = (), (), None
        self._plan_declaration, self._plan_candidates, self._plan_winners = None, None, None
        self.segmented = None

    def bind_geometry(self, lengths):
        """Allocate fixed ragged geometry before entering a captured step."""
        if self.active or self.retired or self.poisoned:
            raise RuntimeError('geometry binding requires a quiescent current execution')
        if (type(lengths) is not tuple or not lengths
                or any(type(n) is not int or n <= 0 for n in lengths) or sum(lengths) > 4096):
            raise ValueError('complete positive document geometry within context required')
        sizes = tuple(min(256, n-start) for n in lengths for start in range(0,n,256))
        self._geometry_lengths = lengths
        self._geometry_sizes = sizes
        self._geometry_repeats = torch.tensor(sizes, dtype=torch.long, device=self.device)
        self.bind_route_plan(None)

    def bind_route_plan(self, plan):
        """Prepare an explicit diagnostic plan outside the step; native gates remain live."""
        if self.active or self.retired or self.poisoned or not self._geometry_lengths:
            raise RuntimeError('route-plan binding requires quiescent bound geometry')
        if getattr(self, 'segmented', None) is not None:
            self.segmented.invalidate()
            self.segmented._cia_invalidated = True
        if plan is None:
            self._plan_declaration, self._plan_candidates, self._plan_winners = None, None, None
            return
        expected = tuple((doc, layer, start) for layer in range(1,24,2)
                         for doc,length in enumerate(self._geometry_lengths) for start in range(0,length,256))
        declaration = self._plan_value(plan, expected)
        count = len(expected)//12
        self._plan_declaration = declaration
        self._plan_candidates = torch.tensor([row[1] for row in declaration],dtype=torch.long,device=self.device).reshape(12,count,2)
        self._plan_winners = torch.tensor([row[2] for row in declaration],dtype=torch.long,device=self.device).reshape(12,count)

    @staticmethod
    def _plan_value(plan, expected):
        if (type(plan) is not dict or any(type(key) is not tuple or len(key)!=3
                or any(type(value) is not int for value in key) for key in plan)
                or set(plan) != set(expected)):
            raise ValueError('route plan must describe every document, sparse layer and segment exactly')
        rows=[]
        for key in expected:
            if type(key) is not tuple or any(type(value) is not int for value in key):
                raise ValueError('route plan keys must be exact integer tuples')
            entry=plan[key]
            if type(entry) is not tuple or len(entry)!=2:
                raise ValueError('route plan entry must be a candidate tuple and winner')
            pair,winner=entry
            if (type(pair) is not tuple or len(pair)!=2 or any(type(value) is not int or not 0<=value<25 for value in pair)
                    or pair[0]>=pair[1] or type(winner) is not int or winner not in pair):
                raise ValueError('route plan requires two ascending global IDs and a member winner')
            rows.append((key,pair,winner))
        return tuple(rows)

    def check_route_plan(self, plan):
        self.check()
        if self._plan_declaration is None:
            if plan is not None:
                raise ValueError('route plan must be bound before the resident step')
        elif self._plan_value(plan, tuple(row[0] for row in self._plan_declaration)) != self._plan_declaration:
            raise ValueError('route plan differs from its prebound declaration')

    def planned_routes(self, depth, geometry, candidates, native_winners, logits, gates):
        self.check()
        if self._plan_declaration is None:
            return native_winners,gates
        actual=torch.stack([candidates[row[4]] for row in geometry.chunks])
        self.require_valid((actual==self._plan_candidates[depth]).all(),'plan')
        winners=self._plan_winners[depth]
        membership=actual==winners[:,None]
        self.require_valid(membership.any(1).all(),'plan')
        slots=membership.to(torch.int64).argmax(1)
        working=logits if logits.dtype==torch.float64 else logits.float()
        probability=working.softmax(1).gather(1,slots[:,None])[:,0]
        return winners,(probability-probability.detach())+1.0

    def geometry_repeats(self, lengths, sizes):
        self.check()
        if lengths != self._geometry_lengths or sizes != self._geometry_sizes:
            raise ValueError('resident forward requires its prebound document geometry')
        return self._geometry_repeats

    def require_valid(self, predicate, reason):
        self.check()
        if (reason not in ('input', 'routing', 'plan') or not isinstance(predicate, torch.Tensor)
                or predicate.shape != () or predicate.dtype != torch.bool or predicate.device != self.device):
            raise ValueError('declared scalar device validity predicate required')
        self.input_valid[('input','routing','plan').index(reason)].logical_and_(predicate)

    @property
    def resident_count(self):
        return 4 if not self.retired else 0

    def resident_set(self):
        return self.ids

    def identity(self):
        # ExpertCache supplies the existing metadata signature; no tensor value copy.
        return (self.model.owner_declaration(), tuple((name, ExpertCache._signature(value))
                 for name, value in self.model.live_parameters().items()))

    def check(self):
        if not self.active or self.retired or self.poisoned or self.model._cuda_execution is not self:
            raise RuntimeError('resident execution requires its current active candidate step')
        if self.identity() != self.bound:
            raise RuntimeError('resident candidate owner changed during the step')

    @contextmanager
    def capture_region(self):
        """Temporarily admit synthetic dense-segment work without advancing a real training step."""
        if (self.active or self.retired or self.poisoned or self.pending
                or self.model._cuda_execution is not self):
            raise RuntimeError('capture requires a quiescent current resident execution')
        self.model.parameter_inventory()
        owner = self.identity()
        saved = (self.bound, self.step_id, self.routed,
                 self.routing_valid.clone(), self.input_valid.clone())
        self.bound = owner
        self.routed = []
        self.active = True
        try:
            yield
            if self.pending or self.identity() != owner:
                raise RuntimeError('capture changed owner identity or left expert backward incomplete')
        except BaseException:
            self.poisoned = True
            raise
        finally:
            self.active = False
            self.bound, self.step_id, self.routed = saved[:3]
            self.routing_valid.copy_(saved[3])
            self.input_valid.copy_(saved[4])

    def begin_step(self):
        if self.active or self.retired or self.poisoned or self.model._cuda_execution is not self:
            raise RuntimeError('resident execution is not available for a new step')
        self.model.parameter_inventory()
        self.bound = self.identity()
        self.step_id += 1
        self.pending = 0
        self.routed = []
        self.routing_valid.fill_(True)
        self.input_valid.fill_(True)
        self.active = True

    def end_step(self):
        try:
            self.check()
            if self.pending:
                raise RuntimeError('incomplete resident expert backward')
            self.model.parameter_inventory()
            torch.cuda.synchronize(self.device)
            predicates = self.input_valid.detach().cpu().tolist()
            if not all(predicates):
                raise ResidentInputRefusal(self.step_id, [reason for reason, ok in
                    zip(('input', 'routing', 'plan'), predicates) if not ok])
            if not bool(self.routing_valid):
                unknown = [int(expert) for values in self.routed for expert in values.detach().cpu().tolist()
                           if int(expert) not in self.ids]
                raise ResidentRoutingRefusal(self.step_id, unknown)
        except BaseException:
            self.poisoned = True
            raise
        finally:
            self.active = False

    @contextmanager
    def step(self):
        self.begin_step()
        try:
            yield
        except BaseException:
            self.poisoned = True
            self.active = False
            torch.cuda.synchronize(self.device)
            raise
        else:
            self.end_step()

    def validate_routed(self, experts):
        """Accumulate a device validity predicate and return safe local group slots."""
        self.check()
        if (not isinstance(experts, torch.Tensor) or experts.ndim != 1 or experts.dtype != torch.long
                or experts.device != self.device or not len(experts)):
            raise ValueError('one nonempty same-device integer expert vector required')
        membership = experts[:, None] == self.id_tensor[None, :]
        self.routing_valid.logical_and_(membership.any(1).all())
        self.routed.append(experts.detach())
        return membership.to(torch.int32).argmax(1)

    def layer_groups(self, layer):
        return tuple(self.model._resident_groups[(layer, projection)] for projection in ('up', 'gate', 'down'))

    def grouped_block(self, values, experts, layer, *, backend='native'):
        self.check()
        if (type(layer) is not int or layer not in range(1, 24, 2)
                or values.ndim != 2 or values.shape[1] != 1024 or values.dtype != torch.bfloat16
                or values.device != self.device or len(experts) != len(values)):
            raise ValueError('resident grouped block requires aligned full-width rows at a sparse layer')
        if backend not in ('native', 'dynamic'):
            raise ValueError('unknown resident grouped backend')
        slots = self.validate_routed(experts)
        order = torch.argsort(slots, stable=True)
        offsets = (slots[:, None] == self.slot_tensor[None, :]).sum(0, dtype=torch.int32).cumsum(0, dtype=torch.int32)
        ordered = values.index_select(0, order)
        parameters = tuple(self.model.weights[f'experts.{expert}.layers.{layer}.{projection}.weight'.replace('.', '__')]
                           for projection in ('up', 'gate', 'down') for expert in self.ids)
        result = _ResidentGroupedSwiGLU.apply(ordered, offsets, self, layer, backend, *parameters)
        return result.index_select(0, torch.argsort(order))

    def expert_block(self, values, expert, layer):
        self.check()
        if type(expert) is not int or expert not in self.ids:
            raise ResidentRoutingRefusal(self.step_id, (expert,))
        return self.model._swiglu(values, f'experts.{expert}.layers.{layer}')

    def expert_block_group(self, values, expert, layer):
        sizes = tuple(len(value) for value in values)
        return self.expert_block(torch.cat(values), expert, layer).split(sizes)


from dataclasses import dataclass
import torch
from ember.model.ember_v0_routing import _global_scores, _local_scores, _unit_task_gate_rows


@dataclass(frozen=True)
class DeviceRouteGeometry:
    # document index, document offset, segment start, segment length, epoch index
    chunks: tuple
    lengths: tuple


def resident_global_routes(embedded, lengths, global_query, keys):
    if (not isinstance(embedded, torch.Tensor) or embedded.ndim != 2 or embedded.shape[1] != 1024
            or not embedded.is_floating_point() or type(lengths) is not tuple or not lengths
            or any(type(n) is not int or n <= 0 for n in lengths) or sum(lengths) != len(embedded)):
        raise ValueError('complete positive document geometry and floating embeddings required')
    if (global_query.shape != (1024,1024) or keys.shape != (12,25,1024)
            or global_query.device != embedded.device or keys.device != embedded.device
            or not global_query.is_floating_point() or not keys.is_floating_point()):
        raise ValueError('same-device complete routing sources required')
    priors,ranked,sorted_ids,chunks,flags=[],[],[],[],[]
    flags.extend((torch.isfinite(global_query).all(),torch.isfinite(keys).all(),torch.isfinite(embedded).all()))
    offset=0
    for document,length in enumerate(lengths):
        for start in range(0,length,1024):
            history=embedded[offset+max(0,start-1024):offset+start].detach()
            summary=history.float().mean(0) if len(history) else torch.zeros(1024,device=embedded.device)
            prior=_global_scores(summary,global_query,keys)
            ids=torch.argsort(prior,descending=True,stable=True)[:2]
            epoch=len(priors)
            priors.append(prior)
            ranked.append(ids)
            sorted_ids.append(torch.sort(ids).values)
            flags.append(torch.isfinite(prior).all())
            chunks.extend((document,offset,segment,min(256,length-segment),epoch)
                          for segment in range(start,min(start+1024,length),256))
        offset+=length
    return (DeviceRouteGeometry(tuple(chunks),lengths),torch.stack(priors),
            torch.stack(ranked),torch.stack(sorted_ids),torch.stack(flags).all())


def resident_local_routes(hidden, local_query, keys, sparse_depth, geometry, priors, candidates):
    if (type(geometry) is not DeviceRouteGeometry or type(sparse_depth) is not int
            or not 0 <= sparse_depth < 12 or hidden.shape != (sum(geometry.lengths),1024)
            or local_query.shape != (1024,1024) or keys.shape != (12,25,1024)
            or local_query.device != hidden.device or keys.device != hidden.device
            or priors.device != hidden.device or candidates.device != hidden.device
            or candidates.dtype != torch.long or candidates.shape != (len(priors),2)
            or priors.shape[1:] != (25,)):
        raise ValueError('local routing requires its complete same-device global geometry')
    flags=[torch.isfinite(local_query).all(),torch.isfinite(keys).all(),torch.isfinite(priors).all()]
    rows,ids=[] ,[]
    for document,offset,start,size,epoch in geometry.chunks:
        summary=hidden[offset+start-1].float() if start else torch.zeros(1024,device=hidden.device)
        pair=candidates[epoch]
        # Same vector GEMM and two-key score shape as the reference.
        logits=_local_scores(summary,local_query,keys[sparse_depth].index_select(0,pair),
                             priors[epoch].index_select(0,pair))
        flags.extend((torch.isfinite(summary).all(),torch.isfinite(logits).all()))
        rows.append(logits)
        ids.append(pair)
    logits=torch.stack(rows)
    slots=torch.argmax(logits,dim=1)
    winners=torch.stack(ids).gather(1,slots[:,None])[:,0]
    gates=_unit_task_gate_rows(logits,slots)
    flags.append(torch.isfinite(gates).all())
    return winners,logits,gates,torch.stack(flags).all()


class ResidentInputRefusal(ValueError):
    def __init__(self, step_id, reasons):
        self.receipt = dict(schema='cia-resident-input-refusal-v1', status='refused',
                            step_id=step_id, reasons=tuple(reasons), applied_positions=0)
        super().__init__('resident input or routing predicate failed before optimizer application')


class ResidentRouteTrace:
    """Provisional device records; only an accepted completed step can materialize."""
    def __init__(self, execution, step_id, geometry, ranked, winners):
        self._execution, self._step_id = execution, step_id
        self._geometry, self._ranked, self._winners = geometry, ranked, winners

    def materialize(self):
        execution = self._execution
        if execution.active or execution.poisoned or execution.retired or execution.step_id != self._step_id:
            raise RuntimeError('device routes require their accepted completed step')
        ranked = self._ranked.cpu().tolist()
        winners = torch.stack(self._winners).cpu().tolist()
        rows = [(document, 2 * depth + 1, start, tuple(ranked[epoch]), winners[depth][index])
                for depth in range(12)
                for index, (document, offset, start, size, epoch) in enumerate(self._geometry.chunks)]
        return tuple(sorted(rows, key=lambda row: row[:3]))



def _stage_optimizer_placement(optimizer, parameters, destinations):
    """Stage the retained AdamW tensors without changing owners or optimizer state."""
    if type(optimizer) is not torch.optim.AdamW:
        raise ValueError('placement transition requires the declared AdamW optimizer')
    membership = [p for group in optimizer.param_groups for p in group['params']]
    owners = {id(p): p for p in parameters.values()}
    if len(membership) != len(owners) or {id(p) for p in membership} != set(owners):
        raise ValueError('optimizer membership differs from the complete owner inventory')
    options = {id(p): group for group in optimizer.param_groups for p in group['params']}
    staged = {}
    for parameter, state in optimizer.state.items():
        if id(parameter) not in owners:
            raise ValueError('optimizer state belongs to an unbound owner')
        if not state:
            staged[parameter] = {}
            continue
        expected = {'step', 'exp_avg', 'exp_avg_sq'}
        if options[id(parameter)].get('amsgrad', False):
            expected.add('max_exp_avg_sq')
        if set(state) != expected:
            raise ValueError('optimizer moment state is incomplete or undeclared')
        row = {}
        for key, value in state.items():
            if not isinstance(value, torch.Tensor):
                raise ValueError('AdamW state must retain its tensor representation')
            if key == 'step':
                if value.ndim != 0 or not value.is_floating_point():
                    raise ValueError('AdamW step must retain its scalar floating representation')
                destination = (destinations[id(parameter)] if options[id(parameter)].get('capturable', False)
                               else torch.device('cpu'))
            else:
                if value.shape != parameter.shape or value.dtype != parameter.dtype:
                    raise ValueError('AdamW moment shape and parameter dtype must agree')
                destination = destinations[id(parameter)]
            row[key] = value if value.device == destination else value.to(destination, copy=True)
        staged[parameter] = row
    return staged
