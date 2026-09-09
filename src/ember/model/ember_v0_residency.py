"""Bounded CIA expert execution; caller owns launch and candidate update authority."""
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
from collections import OrderedDict
from contextlib import contextmanager
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

    def __init__(self, bank, *, device, owner_parameters=None):
        self.validate_sources(bank)
        self.bank = bank
        self.device = device
        self.entries = OrderedDict()
        self.active = False
        self.pending = 0
        self.leased = set()
        self.peak_resident_bundles = 0
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
        if expert not in self.entries:
            if len(self.entries) == 2:
                available = next((key for key in self.entries if key not in self.leased), None)
                if available is None:
                    raise RuntimeError('two expert slots are already leased')
                self.synchronize()
                del self.entries[available]
            copied = {}
            try:
                for name, source in self.bank[expert].items():
                    copied[name] = source.detach().to(device=self.device, copy=True)
                self.synchronize()
                self.entries[expert] = copied
            except BaseException:
                self.synchronize()
                copied.clear()
                raise
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
    def __init__(self, model, device):
        device = torch.device(device)
        if device.type != 'cuda' or device.index is None:
            raise ValueError('an explicit indexed CUDA device is required')
        self.model = model
        self.device = device
        self.cache = ExpertCache(expert_bundles(model.parameter_inventory()), device=device,
                                 owner_parameters=model.parameter_inventory)

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
