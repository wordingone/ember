# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""Image-text training documents under #1945 mixture amendment A1 (state/issue1945-multimodal-mixture-amendment-20260923.md).

One document = exactly PAIRS_PER_DOCUMENT pairs, each [<boi>, patches, <eoi>, caption, <eos>], then <|endoftext|>
fill with no target. The pairs for pack index k are rows PAIRS*k .. PAIRS*k+PAIRS-1 of the manifest in a
seed-shuffled order, so the image cursor is a pure function of the update index and needs no checkpoint field.
Preprocessing is the protected evaluator's own image_patches, imported, so train and evaluation see identical pixels.

Loss-bearing targets: each caption token is predicted from the position before it (the first from <eoi>), and <eos>
from the last caption token. <boi>, patches, <eoi>'s own input slot beyond that, and fill carry IGNORE.
"""
import hashlib
import importlib.util
import json
import random
import sys
from pathlib import Path

PAIRS_PER_DOCUMENT = 8
MAX_CAPTION_TOKENS = 58          # 1 + 64 + 1 + 58 + 1 = 125; 8 x 125 = 1,000 <= 1,024
MAX_PATCHES = 64
IGNORE = -100
BOI, EOI, EOS, FILL = 1, 2, 0, 0
GRAMMAR = 'image-text-document-a1-v1'
MANIFEST_FIELDS = {'object_sha256', 'path', 'caption', 'dataset_id', 'licence'}


def _evaluator():
    name = 'ember_mmmu_cia_evaluation_for_training'
    module = sys.modules.get(name)
    if module is None:
        spec = importlib.util.spec_from_file_location(name, str(Path(__file__).with_name('mmmu_cia_evaluation.py')))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return module


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


class ImageTextStream:
    """Frozen manifest + tokenizer -> deterministic image-text documents by pack index."""

    def __init__(self, manifest_path, manifest_sha256, encode, *, seed, sequence):
        raw = Path(manifest_path).read_bytes()
        if _sha256(raw) != manifest_sha256:
            raise ValueError('image-text manifest bytes differ from the bound digest')
        rows = []
        for line in raw.decode('utf-8').splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if type(row) is not dict or set(row) != MANIFEST_FIELDS:
                raise ValueError('image-text manifest row fields differ')
            rows.append(row)
        if len(rows) < PAIRS_PER_DOCUMENT:
            raise ValueError('image-text manifest holds fewer rows than one document')
        order = list(range(len(rows)))
        random.Random(seed).shuffle(order)
        self.rows, self.order, self.encode = rows, order, encode
        self.sequence = sequence
        self.manifest_sha256 = manifest_sha256
        if (1 + MAX_PATCHES + 1 + MAX_CAPTION_TOKENS + 1) * PAIRS_PER_DOCUMENT > sequence:
            raise ValueError('worst-case image-text pairs exceed the document length')

    def pair_rows(self, pack_index):
        base = PAIRS_PER_DOCUMENT * pack_index
        return [self.rows[self.order[(base + k) % len(self.rows)]] for k in range(PAIRS_PER_DOCUMENT)]

    def document(self, pack_index):
        """token_ids/target_ids/positions of one document plus image spans (rows relative to the document)."""
        evaluator = _evaluator()
        tokens, targets, positions, images = [], [], [], []
        base = PAIRS_PER_DOCUMENT * pack_index
        for k, row in enumerate(self.pair_rows(pack_index)):
            raw = Path(row['path']).read_bytes()
            if _sha256(raw) != row['object_sha256']:
                raise ValueError('image object bytes differ from the manifest: ' + row['path'])
            _, coordinates, grid = evaluator.image_patches(raw)
            if not 0 < len(coordinates) <= MAX_PATCHES:
                raise ValueError('image patch count outside the frozen budget')
            caption = list(self.encode(row['caption']))[:MAX_CAPTION_TOKENS]
            if not caption:
                raise ValueError('empty caption: ' + row['object_sha256'])
            tokens.append(BOI); targets.append(IGNORE); positions.append([len(positions), 0, 0])
            images.append({'row': len(tokens), 'count': len(coordinates), 'grid': list(grid),
                           'path': row['path'], 'object_sha256': row['object_sha256'],
                           'manifest_row': self.order[(base + k) % len(self.rows)]})
            for x, y in coordinates:
                tokens.append(FILL); targets.append(IGNORE); positions.append([len(positions), x, y])
            tokens.append(EOI); targets.append(caption[0]); positions.append([len(positions), 0, 0])
            for index, token in enumerate(caption):
                tokens.append(token)
                targets.append(caption[index + 1] if index + 1 < len(caption) else EOS)
                positions.append([len(positions), 0, 0])
            tokens.append(EOS); targets.append(IGNORE); positions.append([len(positions), 0, 0])
        if len(tokens) > self.sequence:
            raise ValueError('image-text document overflows the sequence')
        while len(tokens) < self.sequence:
            tokens.append(FILL); targets.append(IGNORE); positions.append([len(positions), 0, 0])
        return {'token_ids': tokens, 'target_ids': targets, 'positions': positions, 'images': images,
                'wrapped': base + PAIRS_PER_DOCUMENT > len(self.rows)}


def append_document(pack, document):
    """Append one image-text document to a pack, rebasing its image rows to pack coordinates."""
    start = len(pack['token_ids'])
    pack['document_starts'].append(start)
    pack['token_ids'].extend(document['token_ids'])
    pack['target_ids'].extend(document['target_ids'])
    pack['positions'].extend(document['positions'])
    pack.setdefault('images', []).extend(dict(span, row=span['row'] + start) for span in document['images'])


def exposure(pack):
    """Counted separately and never converted: loss-bearing targets, patches, images, fill, total positions."""
    targets = pack['target_ids']
    patches = sum(span['count'] for span in pack.get('images', ()))
    loss_bearing = sum(1 for value in targets if value != IGNORE)
    return {'loss_bearing_positions': loss_bearing, 'image_patches': patches,
            'images': len(pack.get('images', ())), 'non_loss_positions': len(targets) - loss_bearing,
            'decoder_positions': len(targets)}


_POOL = None


def _decode_pool():
    global _POOL
    if _POOL is None:
        from concurrent.futures import ThreadPoolExecutor
        _POOL = ThreadPoolExecutor(max_workers=PAIRS_PER_DOCUMENT, thread_name_prefix='image-decode')
    return _POOL


def load_patches(pack, device):
    """Decode every image in the pack (inside the measured step) -> (rows LongTensor, patches bf16 [N,768])."""
    import torch
    evaluator = _evaluator()
    spans = list(pack.get('images', ()))

    def decode(span):
        raw = Path(span['path']).read_bytes()
        if _sha256(raw) != span['object_sha256']:
            raise ValueError('image object bytes changed after planning: ' + span['path'])
        patches, coordinates, _ = evaluator.image_patches(raw)
        if len(coordinates) != span['count']:
            raise ValueError('image patch count differs from the plan')
        return patches

    # The per-image decode is the evaluator's own function on each image independently, and file reads, hashing and
    # PIL decode/resize release the interpreter lock, so the images decode concurrently inside the step; map() preserves order,
    # so rows and patches are byte-identical to the serial loop.
    rows, pieces = [], list(_decode_pool().map(decode, spans)) if len(spans) > 1 else [decode(s) for s in spans]
    for span in spans:
        rows.extend(range(span['row'], span['row'] + span['count']))
    if not pieces:
        return None, None
    return (torch.tensor(rows, dtype=torch.long).to(device, non_blocking=True),
            torch.cat(pieces).to(device, non_blocking=True))


def self_test():
    import tempfile
    failures = []
    def check(name, ok):
        print(('ok   ' if ok else 'FAIL ') + name)
        if not ok:
            failures.append(name)
    from PIL import Image
    import io
    with tempfile.TemporaryDirectory() as root:
        rows = []
        for k in range(10):
            buffer = io.BytesIO()
            Image.new('RGB', (40 + 30 * k, 90), (k * 20, 50, 200)).save(buffer, format='PNG')
            path = Path(root) / f'{k}.png'
            path.write_bytes(buffer.getvalue())
            rows.append({'object_sha256': _sha256(buffer.getvalue()), 'path': str(path),
                         'caption': 'x' * (3 + k * 20), 'dataset_id': 'selftest', 'licence': 'CC0-1.0'})
        manifest = Path(root) / 'm.jsonl'
        manifest.write_bytes(''.join(json.dumps(r) + '\n' for r in rows).encode())
        encode = lambda text: [100 + (ord(c) % 50) for c in text]
        stream = ImageTextStream(manifest, _sha256(manifest.read_bytes()), encode, seed=2163, sequence=1024)
        doc = stream.document(0)
        check('document is exactly the sequence length', len(doc['token_ids']) == len(doc['target_ids'])
              == len(doc['positions']) == 1024)
        check('eight images per document', len(doc['images']) == PAIRS_PER_DOCUMENT)
        check('pure function of pack index', stream.document(3) == stream.document(3))
        check('different packs take different rows', stream.pair_rows(0) != stream.pair_rows(1))
        for span in doc['images']:
            ok = (doc['token_ids'][span['row'] - 1] == BOI and doc['token_ids'][span['row'] + span['count']] == EOI
                  and all(doc['target_ids'][r] == IGNORE for r in range(span['row'] - 1, span['row'] + span['count'])))
            if not ok:
                break
        check('patch rows sit between boi and eoi and carry no target', ok)
        eoi = doc['images'][0]['row'] + doc['images'][0]['count']
        check('first caption token is predicted from eoi', doc['target_ids'][eoi] == doc['token_ids'][eoi + 1])
        pack = {'token_ids': [7] * 1024, 'target_ids': [7] * 1024, 'positions': [[0, 0, 0]] * 1024,
                'document_starts': [0]}
        append_document(pack, doc)
        check('rows rebase to pack coordinates', pack['images'][0]['row'] == 1024 + doc['images'][0]['row'])
        seen = exposure(pack)
        check('exposure counts are separate and sum', seen['loss_bearing_positions'] + seen['non_loss_positions']
              == seen['decoder_positions'] == 2048 and seen['images'] == 8)
        try:
            ImageTextStream(manifest, '0' * 64, encode, seed=2163, sequence=1024)
            check('manifest digest mismatch refused', False)
        except ValueError:
            check('manifest digest mismatch refused', True)
        try:
            ImageTextStream(manifest, _sha256(manifest.read_bytes()), encode, seed=2163, sequence=512)
            check('short sequence refused', False)
        except ValueError:
            check('short sequence refused', True)
    return failures


if __name__ == '__main__':
    sys.exit(1 if self_test() else 0)
