# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""A synthetic torch-format optimizer-state component for the post-train memory reds (#2119).

Standard library only: the pickle is assembled opcode by opcode, so a test child that imports the stdlib-only
parameter counter never imports torch (its memory is then the counter's own). The file is a ZIP_STORED archive with
the member layout torch.save writes (`archive/data.pkl`, `archive/data/<key>`), holding a v3-shaped payload (fp32
master weights plus fp32 moments), so it is read by the real `_cia_counter_component` and the real
`_cia_counter_optimizer_facts`. The expected facts are computed here independently of the counter: sha256 of the raw
fp32 bytes, and a plain-python round-to-nearest-even bf16 narrowing of one tile, hashed as the tile repeats.
"""
from __future__ import annotations

import hashlib
import struct
import zipfile
from pathlib import Path

V3_SCHEMA = 'ember-cia-placed-optimizer-state-v3'
MIB = 1024 * 1024


def _unicode(text):
    data = text.encode('utf-8')
    return b'X' + struct.pack('<I', len(data)) + data


def _int(value):
    return b'J' + struct.pack('<i', value)


def _ints(values):
    values = tuple(values)
    if not values:
        return b')'
    body = b''.join(_int(v) for v in values)
    return body + {1: b'\x85', 2: b'\x86', 3: b'\x87'}.get(len(values), b'')


def _tensor(key, numel, shape):
    """torch._utils._rebuild_tensor_v2(persistent storage, 0, shape, stride, False, ()), exactly as torch.save pickles it."""
    stride, running = [], 1
    for dimension in reversed(shape):
        stride.append(running)
        running *= dimension
    storage = (b'(' + _unicode('storage') + b'ctorch\nFloatStorage\n' + _unicode(str(key)) + _unicode('cpu')
               + _int(numel) + b't' + b'Q')
    return (b'ctorch._utils\n_rebuild_tensor_v2\n' + b'(' + storage + _int(0) + _ints(shape) + _ints(reversed(stride))
            + b'\x89' + b')' + b't' + b'R')


def _mapping(items):
    body = b'}(' + b''.join(_unicode(name) + value for name, value in items) + b'u'
    return body


def fp32_tile(words, *, exact, salt):
    """`words` finite positive little-endian fp32 values. exact=True zeroes every low half (bf16-representable)."""
    raw = bytearray(struct.pack('<%df' % words, *[((i * 37 + salt) % 100003) * 0.0123 + 1.0 for i in range(words)]))
    if exact:
        raw[0::4] = bytes(words)
        raw[1::4] = bytes(words)
    return bytes(raw)


def _rne_bf16_tile(tile):
    out = bytearray(len(tile) // 2)
    for index in range(len(tile) // 4):
        word = struct.unpack_from('<I', tile, 4 * index)[0]
        word += 0x7FFF + ((word >> 16) & 1)
        struct.pack_into('<H', out, 2 * index, (word >> 16) & 0xFFFF)
    return bytes(out)


def _high_halves(tile):
    high = bytearray(len(tile) // 2)
    high[0::2] = tile[2::4]
    high[1::2] = tile[3::4]
    return bytes(high)


def _repeat_sha(tile, repeats):
    digest = hashlib.sha256()
    for _ in range(repeats):
        digest.update(tile)
    return digest.hexdigest()


def build_component(path, owners, *, tile_words=262144, step=7):
    """Write a v3-shaped optimizer-state.pt. owners = [(name, shape, exact)] with numel a multiple of tile_words.

    Returns dict(record, inventory, groups, expected): `record` is the manifest record, `expected` is
    (optimizer facts, master facts) as `_cia_counter_optimizer_facts` must return them."""
    path = Path(path)
    members, master_items, state_items = [], [], []
    optimizer, extra = {}, {'optimizer_schema': 'fp32_master_v1', 'master': {}, 'master_bf16': {},
                            'master_exact': {}, 'optimizer_view': {}}
    inventory, groups = {}, {}
    key = 0
    step_tile = struct.pack('<f', float(step))
    for index, (name, shape, exact) in enumerate(owners):
        numel = 1
        for dimension in shape:
            numel *= dimension
        if numel % tile_words:
            raise ValueError('owner size must be a whole number of tiles')
        repeats = numel // tile_words
        inventory[name], groups[name] = tuple(shape), {'amsgrad': False}
        digests = {}
        entries = {}
        for role, salt in (('master', 1), ('exp_avg', 2), ('exp_avg_sq', 3)):
            tile = fp32_tile(tile_words, exact=exact, salt=salt + index)
            entries[role] = (key, tile, repeats, numel)
            digests[role] = (_repeat_sha(tile, repeats), tile)
            members.append((key, tile, repeats))
            key += 1
        step_key = key
        key += 1
        members.append((step_key, step_tile, 1))
        master_items.append((name, _tensor(entries['master'][0], numel, shape)))
        state_items.append((name, _mapping([('step', _tensor(step_key, 1, ())),
                                            ('exp_avg', _tensor(entries['exp_avg'][0], numel, shape)),
                                            ('exp_avg_sq', _tensor(entries['exp_avg_sq'][0], numel, shape))])))
        optimizer[name] = {'step': step, 'exp_avg': digests['exp_avg'][0], 'exp_avg_sq': digests['exp_avg_sq'][0]}
        master_tile = digests['master'][1]
        extra['master'][name] = digests['master'][0]
        extra['master_bf16'][name] = _repeat_sha(_rne_bf16_tile(master_tile), repeats)
        extra['master_exact'][name] = exact
        extra['optimizer_view'][name] = {'step': step, **{
            role: (_repeat_sha(_high_halves(digests[role][1]), repeats) if exact else None)
            for role in ('exp_avg', 'exp_avg_sq')}}
    pickle_bytes = (b'\x80\x02' + _mapping([('schema_version', _unicode(V3_SCHEMA)),
                                             ('master_weights', _mapping(master_items)),
                                             ('state', _mapping(state_items))]) + b'.')
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        archive.writestr(zipfile.ZipInfo('archive/data.pkl'), pickle_bytes)
        for member_key, tile, repeats in members:
            with archive.open(zipfile.ZipInfo('archive/data/%d' % member_key), 'w', force_zip64=True) as stream:
                for _ in range(repeats):
                    stream.write(tile)
        archive.writestr(zipfile.ZipInfo('archive/version'), b'3\n')
    digest, total = hashlib.sha256(), 0
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(8 * MIB), b''):
            digest.update(block)
            total += len(block)
    return dict(record={'path': path.name, 'sha256': digest.hexdigest(), 'bytes': total}, inventory=inventory,
                groups=groups, expected=(optimizer, extra))
