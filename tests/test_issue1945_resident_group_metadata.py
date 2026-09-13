# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Resident storage checks must retain exact owners without creating tensor views."""
import pytest
import torch
from torch.utils._python_dispatch import TorchDispatchMode
from ember.model.ember_v0_residency import _validate_resident_group


def owners(storage):
    return tuple(torch.nn.Parameter(storage[index]) for index in range(4))


@pytest.mark.parametrize('shape', [(4, 2, 3), (4, 1, 1), (4, 0, 3), (4, 2, 0)])
@pytest.mark.parametrize('device', ['cpu', 'meta'])
def test_exact_group_owners_need_no_tensor_operations(shape, device):
    storage = torch.empty(shape, dtype=torch.bfloat16, device=device)
    parameters = owners(storage)
    operations = []

    class RecordOperations(TorchDispatchMode):
        def __torch_dispatch__(self, func, types, args=(), kwargs=None):
            operations.append(str(func))
            return func(*args, **(kwargs or {}))

    with RecordOperations():
        _validate_resident_group(parameters, storage)
    assert operations == [], 'owner metadata validation created tensor operations: '+str(operations)


@pytest.mark.parametrize('change', ['wrong_row', 'independent_storage', 'wrong_stride', 'wrong_shape',
                                   'plain_tensor', 'owner_dtype', 'owner_offset'])
def test_changed_owner_is_rejected(change):
    storage = torch.empty((4, 2, 3), dtype=torch.bfloat16)
    parameters = list(owners(storage))
    if change == 'wrong_row':
        parameters[1] = torch.nn.Parameter(storage[2])
    elif change == 'independent_storage':
        parameters[1] = torch.nn.Parameter(storage[1].clone())
    elif change == 'wrong_stride':
        parameters[1] = torch.nn.Parameter(storage.as_strided((2, 3), (1, 2), 6))
    elif change == 'wrong_shape':
        parameters[1] = torch.nn.Parameter(storage[1].reshape(3, 2))
    elif change == 'plain_tensor':
        parameters[1] = storage[1]
    elif change == 'owner_dtype':
        parameters[1] = torch.nn.Parameter(storage[1].float())
    elif change == 'owner_offset':
        parameters[1] = torch.nn.Parameter(storage.as_strided((2, 3), (3, 1), 7))
    with pytest.raises(ValueError):
        _validate_resident_group(tuple(parameters), storage)


@pytest.mark.parametrize('change', ['extra_backing', 'backing_offset', 'backing_stride',
                                   'backing_dtype', 'rank', 'group_count', 'owner_list', 'owner_count'])
def test_changed_backing_or_owner_container_is_rejected(change):
    storage = torch.empty((4, 2, 3), dtype=torch.bfloat16)
    if change == 'extra_backing':
        storage = torch.empty((5, 2, 3), dtype=torch.bfloat16)[:4]
    elif change == 'backing_offset':
        storage = torch.empty((5, 2, 3), dtype=torch.bfloat16)[1:]
    elif change == 'backing_stride':
        storage = storage.transpose(1, 2)
    elif change == 'backing_dtype':
        storage = storage.float()
    elif change == 'rank':
        storage = storage.reshape(4, 6)
    elif change == 'group_count':
        storage = torch.empty((5, 2, 3), dtype=torch.bfloat16)
    parameters = owners(storage)
    if change == 'owner_list':
        parameters = list(parameters)
    elif change == 'owner_count':
        parameters = parameters[:3]
    with pytest.raises(ValueError):
        _validate_resident_group(parameters, storage)


def test_empty_slice_still_requires_its_declared_offset():
    storage = torch.empty((4, 0, 3), dtype=torch.bfloat16)
    parameters = list(owners(storage))
    assert parameters[1].data_ptr() == 0 and parameters[1].storage_offset() == 3
    parameters[1] = torch.nn.Parameter(storage[0])
    with pytest.raises(ValueError):
        _validate_resident_group(tuple(parameters), storage)
