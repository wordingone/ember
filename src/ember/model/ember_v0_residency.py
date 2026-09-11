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

    def __init__(self, bank, *, device, owner_parameters=None, resident_capacity=2):
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

    def identity(self):
        signature = {(expert, name): (id(value), value._version, value.data_ptr(), tuple(value.shape), value.dtype,
                                     value.device, value.requires_grad)
                     for expert, row in self.bank.items() for name, value in row.items()}
        if self.owner_parameters is not None:
            owned = self.owner_parameters()
            owner_ids = {id(value) for value in owned.values()}
            if any(id(value) not in owner_ids for row in self.bank.values() for value in row.values()):
                raise RuntimeError('cache bank ownership changed')
            signature.update({('owner', name): (id(value), value._version, value.data_ptr(), tuple(value.shape),
                              value.dtype, value.device, value.requires_grad) for name, value in owned.items()})
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
        bound = self.identity()
        self.active = True
        self.step_id += 1
        self.bound = bound
        self.pending = 0
        try:
            yield
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


class _PagedSwiGLUGroup(torch.autograd.Function):
    """Several same-expert chunks under ONE lease per pass.

    Numerically each chunk is the identical per-chunk _swiglu the single-chunk path runs (same shapes,
    same kernels, same inputs), so forward outputs are bit-identical to separate calls; only the bundle
    transfer and the per-lease synchronize are shared. Weight gradients are the per-chunk gradients
    summed here rather than by autograd's accumulation, which is the one place a summation order
    differs from the serial path.
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
            for value, output_gradient in zip(values, output_gradients):
                with torch.enable_grad():
                    inputs = [value.detach().requires_grad_(True)]
                    inputs.extend(weights[name].detach().requires_grad_(True) for name in ctx.names)
                    result = _swiglu(*inputs)
                    gradients = torch.autograd.grad(result, inputs, output_gradient)
                value_gradients.append(gradients[0])
                for index, (gradient, source) in enumerate(zip(gradients[1:], (up, gate, down))):
                    if ctx.needs_input_grad[index]:
                        moved = gradient.to(source.device)
                        weight_gradients[index] = (moved if weight_gradients[index] is None
                                                   else weight_gradients[index] + moved)
                del result, inputs, gradients
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
    """One candidate's execution state, never a serving/admission generation."""
    def __init__(self, model, device, *, resident_capacity=2):
        device = torch.device(device)
        if device.type != 'cuda' or device.index is None:
            raise ValueError('an explicit indexed CUDA device is required')
        self.model = model
        self.device = device
        self.cache = ExpertCache(expert_bundles(model.parameter_inventory()), device=device,
                                 owner_parameters=model.parameter_inventory, resident_capacity=resident_capacity)

    @contextmanager
    def step(self):
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
