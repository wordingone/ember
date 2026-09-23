# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
#!/usr/bin/env python3
"""CIA checkpoint -> MMMU predictions -> cached exact scorer, as the Evaluation minimum gate's entrypoint.

The gate (`evaluation_minimum_gate.run_evaluation`) resolves `module:function` and calls
`function(checkpoint_root=<str>, protected_manifest=<str>)`, expecting a dict carrying `score`.
This module is that function for the MMMU row of the protected registry, on a CIA checkpoint.

What it does, in order, refusing at the first failure:

1. Reads the protected registry (`protected_manifest`), finds the MMMU row, and binds the on-disk
   MMMU custody to it BY DIGEST: the frozen answer dictionary, the validation freeze, the
   image-inputs freeze, the custody manifest, the upstream license, the parquet index -- every
   digest is the one `scripts/ember_restart/mmmu_front_unit.py` already pins, so this producer
   reads the same bytes the front unit certified and nothing else.
2. Opens the CIA checkpoint through the repository's own validator
   (`checkpoint_artifacts._cia_validated_checkpoint`, retain_model=True) and rebuilds the CPU
   reference with `eval_cia_checkpoint_gate.build_reference`. No CUDA. No parameter count of its
   own; the authority's verdict is the only structural claim.
3. For every one of the 847 eligible multiple-choice items builds ONE document under the protocol
   in `mmmu-cia-protocol-v1.md` beside this file (images as raw 16x16x3 patches through
   `embed_image`, then the question and options as text through `embed_text`), runs the reference
   forward, and takes the argmax over the item's option-label token ids at the final position.
   The unconstrained argmax token is recorded beside it so a reader can see what free generation
   would have produced.
4. Emits the owned-predictions envelope (`ember-owned-predictions-v1`, claim status
   NON_ADMISSIBLE_RAW_PREDICTIONS), materializes it through the repository's prediction contract
   into the MMMU adapter shape, and scores it with `scripts/ember_restart_eval_mmmu.py` against the
   cached upstream `main_eval_only.py`. The accuracy that comes back is `score`.

Claim boundary, stated in the receipt and here: an EXECUTABLE protected-evaluation producer. It
grants no image capability, evaluation tier, learning or qualification credit. The CIA governed
runner embeds text only (`cia_step_runner.py` calls `model.embed_text` and never `embed_image`),
so on every checkpoint the runner has produced the image projection is genesis-initialized; the
receipt says so under `image_projection_trained_by_runner: false`, sourced from that census.

Configuration is by environment, because the gate's entrypoint contract carries only the two
arguments above. Every variable is required and refused when absent; nothing is defaulted:

  EMBER_REPO_ROOT              a checked-out ember tree (imports come from here)
  EMBER_MMMU_VALIDATION_ROOT   directory holding <subject>/validation-*.parquet
  EMBER_MMMU_UPSTREAM_ROOT     the cached MMMU repository (LICENSE, mmmu/main_eval_only.py,
                               mmmu/answer_dict_val.json)
  EMBER_MMMU_FREEZE            mmmu-validation-<id>-freeze-v2.json
  EMBER_MMMU_IMAGE_INPUTS      mmmu-validation-<id>-image-inputs-v1.json
  EMBER_MMMU_CHECKPOINT_RECEIPT  the independent admission receipt for the checkpoint
  EMBER_MMMU_TOKENIZER         the frozen tokenizer json (its sha256 is recorded, never assumed)
  EMBER_MMMU_OUTPUT_DIR        where predictions, the envelope, the score and the receipt land
  EMBER_MMMU_THREADS           torch CPU thread count (host headroom is the caller's duty)

One OPTIONAL variable selects a declared image-dependence control; it never changes scoring:

  EMBER_MMMU_IMAGE_CONDITION   real (default) | missing | wrong
                               missing: no image blocks at all, question and options only
                               wrong:   each item receives the images of the item IMAGE_SHIFT places later in
                                        the frozen eligible order (a derangement, since 0 < shift < n), so the
                                        image is real but belongs to a different question
                               The condition is recorded in the receipt and in the gate's return dict.

`python mmmu_cia_evaluation.py --self-test` runs the protocol and the refusals against a stub
model with no checkpoint and no scorer, and is what the deliberate red is proved with.
"""
from __future__ import annotations

import ast
import base64
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROTOCOL_NAME = 'mmmu-cia-protocol-v1'
ENVELOPE_SCHEMA = 'ember-owned-predictions-v1'
CLAIM_STATUS = 'NON_ADMISSIBLE_RAW_PREDICTIONS'
BENCHMARK_VERSION = 'bc168a9119d986d7cdf1e07b1eeb96ed3e8f92fa'

# The front unit's pinned custody digests, copied so this producer binds the identical bytes.
ANSWER_SHA256 = '76080f5597b8f4d29abba8551489c4b82e4a285b9d62b946fd67a1952e95502c'
ELIGIBLE_ID_SET_SHA256 = '7a8800c96f0a6003b004d4bc3dfc089b8d6d5aa56a5f85e8c4719fbadd63ecc6'
CUSTODY_SHA256 = '20af6ef398cd7913ea0ba5b53025dbf568eab6d74f7290d01ceda30c4a206b03'
FREEZE_SHA256 = '2f1f5ab0e961e8eb3f7082277dc354f0d503f775fb177a385585444ccd5110b4'
IMAGE_INPUTS_SHA256 = '719619b79f85e56d42552d2935de3bf43e9bd5dee9529f037a7e32dc228d0ebd'
SCORER_SHA256 = '07cc41149073066441379d69bfa51afe1e10644701fc3d0d0a7fb74833ecd5f3'
LICENSE_SHA256 = 'c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4'
ELIGIBLE_COUNT = 847

# Protocol constants (see mmmu-cia-protocol-v1.md; changing any of these is a protocol change).
PATCH = 16
MAX_GRID = 8                # at most 8x8 patches per image
MAX_IMAGES = 7              # MMMU carries image_1..image_7
MAX_POSITIONS = 4096        # the decoder's hard bound
BOI, EOI, EOS = 1, 2, 0     # tokenizer-2c557 added tokens
LABEL_TOKEN_IDS = {chr(ord('A') + i): 40 + i for i in range(9)}   # 'A'..'I' -> 40..48 in tokenizer-2c557

REQUIRED_ENV = ('EMBER_REPO_ROOT', 'EMBER_MMMU_VALIDATION_ROOT', 'EMBER_MMMU_UPSTREAM_ROOT',
                'EMBER_MMMU_FREEZE', 'EMBER_MMMU_IMAGE_INPUTS', 'EMBER_MMMU_CHECKPOINT_RECEIPT',
                'EMBER_MMMU_TOKENIZER', 'EMBER_MMMU_OUTPUT_DIR', 'EMBER_MMMU_THREADS')


class ProducerRefusal(ValueError):
    def __init__(self, token: str, detail: str = ''):
        super().__init__(f'{token}:{detail}' if detail else token)
        self.token = token


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def canonical_digest(value) -> str:
    return sha256_bytes(canonical(value))


def frozen_input_digest(value) -> str:
    """The image-inputs freeze v1 (719619b7...) digested its rows with json.dumps' DEFAULT ensure_ascii=True;
    36 of 900 rows carry non-ASCII text and only this form reproduces their frozen input_sha256."""
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(',', ':')).encode('utf-8'))


def _bound_json(path: Path, expected: str, token: str) -> dict:
    raw = Path(path).read_bytes()
    if sha256_bytes(raw) != expected:
        raise ProducerRefusal(token, f'{path} sha256 {sha256_bytes(raw)[:16]} != pinned {expected[:16]}')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ProducerRefusal(token, f'{path} is not a JSON object')
    return value


def eligible_identity(answers: dict) -> tuple[list[str], str]:
    ids = sorted(key for key, value in answers.items()
                 if isinstance(value, dict) and value.get('question_type') == 'multiple-choice')
    return ids, sha256_bytes(('\n'.join(ids) + '\n').encode('utf-8'))


def parse_options(raw: str) -> list[str]:
    try:
        value = ast.literal_eval(raw)
    except (SyntaxError, ValueError) as exc:
        raise ProducerRefusal('OPTION_SHAPE', repr(raw)[:80]) from exc
    if not isinstance(value, list) or len(value) < 2 or any(not isinstance(item, str) or not item for item in value):
        raise ProducerRefusal('OPTION_SHAPE', repr(raw)[:80])
    return value


# ---------------------------------------------------------------- protocol: document construction

def image_grid(width: int, height: int, max_grid: int = MAX_GRID) -> tuple[int, int]:
    """Patch grid (gx, gy) with gx*gy <= max_grid*max_grid, aspect preserved, each axis >= 1."""
    if width <= 0 or height <= 0:
        raise ProducerRefusal('IMAGE_SHAPE', f'{width}x{height}')
    longest = max(width, height)
    scale = (max_grid * PATCH) / longest
    gx = max(1, min(max_grid, round(width * scale / PATCH)))
    gy = max(1, min(max_grid, round(height * scale / PATCH)))
    return gx, gy


def image_patches(png_bytes: bytes):
    """Raw 16x16x3 uint8 patches, row-major over the resized grid, plus their (x, y) coordinates."""
    import torch
    from PIL import Image
    with Image.open(io.BytesIO(png_bytes)) as image:
        image = image.convert('RGB')
        gx, gy = image_grid(*image.size)
        resized = image.resize((gx * PATCH, gy * PATCH), Image.BILINEAR)
        raw = torch.frombuffer(bytearray(resized.tobytes()), dtype=torch.uint8).reshape(gy * PATCH, gx * PATCH, 3)
    patches = raw.reshape(gy, PATCH, gx, PATCH, 3).permute(0, 2, 1, 3, 4).reshape(gy * gx, PATCH * PATCH * 3)
    coordinates = [(x, y) for y in range(gy) for x in range(gx)]
    return patches.to(torch.float32).div_(255.0).to(torch.bfloat16), coordinates, (gx, gy)


def prompt_text(question: str, options: list[str]) -> str:
    lines = ['Question: ' + question.strip(), 'Options:']
    for index, option in enumerate(options):
        lines.append(f'{chr(ord("A") + index)}. {option}')
    lines.append('Answer:')
    return '\n'.join(lines)


def build_document(model, tokenizer_encode, item: dict, images: list[bytes]):
    """One packed document: [<boi> patches <eoi>]* then text. Returns (embedded, positions, meta)."""
    import torch
    pieces, positions, cursor = [], [], 0
    image_meta = []
    for png in images:
        patches, coordinates, grid = image_patches(png)
        pieces.append(model.embed_text(torch.tensor([BOI], dtype=torch.long)))
        positions.append((cursor, 0, 0)); cursor += 1
        pieces.append(model.embed_image(patches))
        for x, y in coordinates:
            positions.append((cursor, x, y)); cursor += 1
        pieces.append(model.embed_text(torch.tensor([EOI], dtype=torch.long)))
        positions.append((cursor, 0, 0)); cursor += 1
        image_meta.append({'grid': grid, 'patches': len(coordinates)})
    text_ids = tokenizer_encode(prompt_text(item['question'], item['options']))
    if not text_ids:
        raise ProducerRefusal('EMPTY_PROMPT', item['id'])
    pieces.append(model.embed_text(torch.tensor(text_ids, dtype=torch.long)))
    for _ in text_ids:
        positions.append((cursor, 0, 0)); cursor += 1
    if cursor > MAX_POSITIONS:
        raise ProducerRefusal('DOCUMENT_TOO_LONG', f'{item["id"]} {cursor} > {MAX_POSITIONS}')
    embedded = torch.cat(pieces, dim=0)
    if embedded.dtype != torch.bfloat16:
        embedded = embedded.to(torch.bfloat16)
    return embedded, torch.tensor(positions, dtype=torch.long), {'positions': cursor, 'text_tokens': len(text_ids), 'images': image_meta}


def choose(model, embedded, positions, labels: list[str]) -> tuple[str, int, list[float]]:
    """Constrained argmax over the option-label token ids at the final position; the free argmax beside it."""
    import torch
    with torch.no_grad():
        logits = model(embedded, positions, document_starts=(0,))
    last = logits[-1].float()
    if not torch.isfinite(last).all():
        raise ProducerRefusal('NONFINITE_LOGITS')
    ids = [LABEL_TOKEN_IDS[label] for label in labels]
    scores = last[ids]
    choice = labels[int(scores.argmax().item())]
    return choice, int(last.argmax().item()), [float(v) for v in scores]


# ---------------------------------------------------------------- repository imports

def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def bind_protocol(protocol_path: Path = None) -> tuple[Path, str]:
    """Open and digest the protocol document BEFORE any repository, checkpoint or scoring work.

    The protocol digest is bound into the envelope and the receipt; a run whose protocol document is absent
    refuses here, in milliseconds, rather than after the checkpoint is opened and every item is scored (an
    absent sibling once cost a full 350 s run before the receipt-time read refused it).
    """
    path = Path(__file__).with_name(PROTOCOL_NAME + '.md') if protocol_path is None else Path(protocol_path)
    if not path.is_file():
        raise ProducerRefusal('PROTOCOL_ABSENT', str(path))
    return path, sha256_path(path)


def repository(repo_root: Path):
    tools = repo_root / 'src' / 'ember' / 'infrastructure' / 'tools' / 'ember-restart-3b'
    for entry in (repo_root / 'src', tools, repo_root / 'src' / 'ember' / 'governance' / 'scripts'):
        if not entry.is_dir():
            raise ProducerRefusal('REPO_LAYOUT', str(entry))
        if str(entry) not in sys.path:
            sys.path.insert(0, str(entry))
    os.environ.setdefault('PYTHONDONTWRITEBYTECODE', '1')
    sys.dont_write_bytecode = True
    import checkpoint_artifacts
    gate = _load_module('eval_cia_checkpoint_gate', tools / 'eval_cia_checkpoint_gate.py')
    contract = _load_module('ember_restart_prediction_contract',
                            repo_root / 'src' / 'ember' / 'governance' / 'scripts' / 'ember_restart' / 'prediction_contract.py')
    scorer = repo_root / 'scripts' / 'ember_restart_eval_mmmu.py'
    if sha256_path(scorer) != SCORER_SHA256:
        raise ProducerRefusal('SCORER_SUBSTITUTION', str(scorer))
    runner = (tools / 'cia_step_runner.py').read_text(encoding='utf-8')
    projection_trained = 'embed_image' in runner
    return checkpoint_artifacts, gate, contract, scorer, projection_trained


def open_reference(checkpoint_artifacts, gate, checkpoint_root: Path, receipt_path: Path):
    receipt = json.loads(Path(receipt_path).read_bytes())
    if not isinstance(receipt, dict) or 'checkpoint_manifest_sha256' not in receipt:
        raise ProducerRefusal('RECEIPT_SHAPE', str(receipt_path))
    try:
        verified, tensors, optimizer, replay = checkpoint_artifacts._cia_validated_checkpoint(
            Path(checkpoint_root), receipt, retain_model=True, max_restore_payload_bytes=32 * 1024 ** 3)
    except (ValueError, OSError, KeyError, TypeError) as error:
        raise ProducerRefusal('CHECKPOINT_REFUSED', f'{type(error).__name__}: {error}') from error
    del optimizer, replay
    if verified['checkpoint_manifest_sha256'] != receipt['checkpoint_manifest_sha256']:
        raise ProducerRefusal('CHECKPOINT_REFUSED', 'validated manifest digest differs from the receipt')
    model, architecture_sha256 = gate.build_reference(verified, tensors)
    del tensors
    return model, verified, architecture_sha256


# ---------------------------------------------------------------- custody binding

def bind_custody(env: dict, registry_path: Path) -> dict:
    registry = json.loads(Path(registry_path).read_bytes())
    rows = registry.get('protected') if isinstance(registry, dict) else None
    row = next((r for r in rows or [] if isinstance(r, dict) and r.get('benchmark_id') == 'MMMU'), None)
    if row is None:
        raise ProducerRefusal('REGISTRY_NO_MMMU_ROW', str(registry_path))
    evidence = row.get('evidence') or {}
    if evidence.get('answer_dictionary_sha256') != ANSWER_SHA256 or evidence.get('eligible_id_set_sha256') != ELIGIBLE_ID_SET_SHA256:
        raise ProducerRefusal('REGISTRY_IDENTITY', 'registry MMMU evidence differs from the pinned custody')
    upstream = Path(env['EMBER_MMMU_UPSTREAM_ROOT'])
    answers_path = upstream / 'mmmu' / 'answer_dict_val.json'
    answers = _bound_json(answers_path, ANSWER_SHA256, 'WRONG_GOLD')
    if sha256_path(upstream / 'LICENSE') != LICENSE_SHA256:
        raise ProducerRefusal('LICENSE_DRIFT', str(upstream / 'LICENSE'))
    if not (upstream / 'mmmu' / 'main_eval_only.py').is_file():
        raise ProducerRefusal('UPSTREAM_SCORER_ABSENT', str(upstream / 'mmmu' / 'main_eval_only.py'))
    freeze = _bound_json(Path(env['EMBER_MMMU_FREEZE']), FREEZE_SHA256, 'FREEZE_DRIFT')
    image_inputs = _bound_json(Path(env['EMBER_MMMU_IMAGE_INPUTS']), IMAGE_INPUTS_SHA256, 'IMAGE_INPUT_DRIFT')
    ids, id_sha = eligible_identity(answers)
    if len(ids) != ELIGIBLE_COUNT or id_sha != ELIGIBLE_ID_SET_SHA256:
        raise ProducerRefusal('ELIGIBLE_ID_SET_DRIFT', f'{len(ids)} {id_sha[:16]}')
    if freeze.get('validation_row_count') != 900 or freeze.get('eligible_multiple_choice_count') != ELIGIBLE_COUNT:
        raise ProducerRefusal('FREEZE_COUNT_DRIFT')
    frozen_inputs = {r.get('id'): r for r in image_inputs.get('rows', []) if isinstance(r, dict)}
    if len(frozen_inputs) != 900:
        raise ProducerRefusal('IMAGE_INPUT_COUNT_DRIFT', str(len(frozen_inputs)))
    root = Path(env['EMBER_MMMU_VALIDATION_ROOT'])
    files = sorted(root.glob('*/validation-*.parquet'))
    expected = freeze.get('validation_parquet_files', [])
    relative = [p.relative_to(root).as_posix() for p in files]
    if not files or relative != [r.get('path') for r in expected if isinstance(r, dict)]:
        raise ProducerRefusal('PARQUET_PATH_DRIFT')
    for path, r in zip(files, expected):
        if sha256_path(path) != r.get('sha256'):
            raise ProducerRefusal('PARQUET_BYTES_DRIFT', path.name)
    return {'answers': answers, 'answers_path': answers_path, 'ids': ids, 'frozen_inputs': frozen_inputs,
            'parquet_files': files, 'upstream': upstream, 'registry_sha256': sha256_path(registry_path),
            'custody_manifest_sha256': row.get('custody_manifest_sha256')}


def load_items(custody: dict) -> list[dict]:
    import pyarrow.parquet as parquet
    wanted = set(custody['ids'])
    items, seen = [], set()
    for path in custody['parquet_files']:
        for row in parquet.read_table(path).to_pylist():
            identifier = row.get('id')
            if identifier not in wanted:
                continue
            if identifier in seen:
                raise ProducerRefusal('DUPLICATE_ID', identifier)
            seen.add(identifier)
            question, options_raw = row.get('question'), row.get('options')
            if not isinstance(question, str) or not question:
                raise ProducerRefusal('QUESTION_SHAPE', identifier)
            options = parse_options(options_raw)
            image_columns = sorted((k for k in row if k.startswith('image_') and row.get(k) is not None),
                                   key=lambda k: int(k.split('_', 1)[1]))
            images = [row[k]['bytes'] for k in image_columns]
            image_hashes = [sha256_bytes(b) for b in images]
            input_sha = frozen_input_digest({'id': identifier, 'question': question, 'options': options_raw, 'image_sha256s': image_hashes})
            frozen = custody['frozen_inputs'].get(identifier)
            if frozen is None or frozen.get('image_sha256s') != image_hashes or frozen.get('input_sha256') != input_sha:
                raise ProducerRefusal('PREPROCESSING_DRIFT', identifier)
            labels = [chr(ord('A') + i) for i in range(len(options))]
            if any(label not in LABEL_TOKEN_IDS for label in labels):
                raise ProducerRefusal('TOO_MANY_OPTIONS', identifier)
            truth = custody['answers'][identifier].get('ground_truth')
            if truth not in labels:
                raise ProducerRefusal('GROUND_TRUTH_OUT_OF_RANGE', identifier)
            items.append({'id': identifier, 'question': question, 'options': options, 'options_raw': options_raw,
                          'images': images, 'image_sha256s': image_hashes, 'input_sha256': input_sha, 'labels': labels})
    if len(items) != ELIGIBLE_COUNT or seen != wanted:
        raise ProducerRefusal('COVERAGE', f'{len(items)} of {ELIGIBLE_COUNT}')
    items.sort(key=lambda item: item['id'])
    return items


# ---------------------------------------------------------------- the entrypoint

def _env() -> dict:
    missing = [name for name in REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        raise ProducerRefusal('CONFIG_ABSENT', ','.join(missing))
    return {name: os.environ[name] for name in REQUIRED_ENV}


def _tokenizer(path: Path):
    from tokenizers import Tokenizer
    tokenizer = Tokenizer.from_file(str(path))
    for label, token_id in LABEL_TOKEN_IDS.items():
        if tokenizer.token_to_id(label) != token_id:
            raise ProducerRefusal('LABEL_TOKEN_DRIFT', f'{label} -> {tokenizer.token_to_id(label)} != {token_id}')
    for token, token_id in (('<boi>', BOI), ('<eoi>', EOI), ('<|endoftext|>', EOS)):
        if tokenizer.token_to_id(token) != token_id:
            raise ProducerRefusal('SPECIAL_TOKEN_DRIFT', token)

    def encode(text: str) -> list[int]:
        return list(tokenizer.encode(text, add_special_tokens=False).ids)
    return encode, sha256_path(path)


IMAGE_CONDITIONS = ('real', 'missing', 'wrong')


def image_shift(count: int) -> int:
    """Half the eligible set: a derangement for any count >= 2, and far from each item's own subject block."""
    if count < 2:
        raise ProducerRefusal('IMAGE_CONDITION_UNDEFINED', 'wrong-image control needs at least two items')
    return count // 2


def condition_images(items: list[dict], index: int, condition: str) -> list[bytes]:
    if condition == 'real':
        return items[index]['images']
    if condition == 'missing':
        return []
    if condition == 'wrong':
        donor = items[(index + image_shift(len(items))) % len(items)]
        if donor['id'] == items[index]['id']:
            raise ProducerRefusal('IMAGE_CONDITION_SELF', items[index]['id'])
        return donor['images']
    raise ProducerRefusal('IMAGE_CONDITION_UNKNOWN', condition)


def run_items(model, encode, items: list[dict], *, progress=None, condition: str = 'real') -> list[dict]:
    rows = []
    first_repeat = None
    for index, item in enumerate(items):
        embedded, positions, meta = build_document(model, encode, item, condition_images(items, index, condition))
        choice, free_token, scores = choose(model, embedded, positions, item['labels'])
        if index == 0:
            repeat_choice, repeat_free, repeat_scores = choose(model, embedded, positions, item['labels'])
            first_repeat = (repeat_choice == choice and repeat_free == free_token and repeat_scores == scores)
            if not first_repeat:
                raise ProducerRefusal('NONDETERMINISTIC_SCORE', item['id'])
        rows.append({'id': item['id'], 'input_sha256': item['input_sha256'], 'generated_token_ids': [LABEL_TOKEN_IDS[choice]],
                     'stop_reason': 'max_new_tokens', 'output': {'kind': 'choice', 'value': choice},
                     'free_argmax_token_id': free_token, 'label_logits': scores, 'document': meta})
        if progress and (index % 25 == 0 or index + 1 == len(items)):
            progress(index + 1, len(items))
    return rows


def envelope_for(rows: list[dict], *, checkpoint_manifest_sha256: str, model_config_sha256: str,
                 tokenizer_sha256: str, implementation_sha256: str, protocol_sha256: str) -> dict:
    return {
        'schema_version': ENVELOPE_SCHEMA, 'claim_status': CLAIM_STATUS,
        'checkpoint_manifest_sha256': checkpoint_manifest_sha256, 'model_config_sha256': model_config_sha256,
        'tokenizer_sha256': tokenizer_sha256, 'inference_implementation_sha256': implementation_sha256,
        'benchmark': {'id': 'MMMU', 'version': BENCHMARK_VERSION, 'capability': 'image',
                      'split_sha256': ANSWER_SHA256, 'protocol_sha256': protocol_sha256},
        'decoding': {'strategy': 'GREEDY_AUTOREGRESSIVE', 'teacher_forcing': False, 'max_new_tokens': 1,
                     'temperature': 0, 'top_p': 1, 'stop_token_ids': [EOS]},
        'rows': [{k: row[k] for k in ('id', 'input_sha256', 'generated_token_ids', 'stop_reason', 'output')} for row in rows],
    }


HEADLESS_PYTHON_WRAPPER = str(Path.home() / '.codex' / 'headless-python.ps1')


def child_python_argv(python_args: list[str]) -> tuple[list[str], dict]:
    """The argv for a Python child of this evaluator, and the environment it needs.

    On Windows every Python child is routed through the mandatory no-console launcher (standing instruction of
    the counterpart seat, 2026-09-21): `powershell.exe -NoLogo -NoProfile -NonInteractive -File <wrapper> -- <args>`.
    The wrapper defaults to a fixed interpreter; CODEX_PYTHON pins it to THIS interpreter so the child runs the
    same Python as its parent. An absent wrapper REFUSES rather than falling back to a visible child. Elsewhere the
    child is `sys.executable <args>`.
    """
    if os.name != 'nt':
        return [sys.executable, *python_args], {}
    wrapper = Path(os.environ.get('EMBER_HEADLESS_PYTHON', HEADLESS_PYTHON_WRAPPER))
    if not wrapper.is_file():
        raise ProducerRefusal('HEADLESS_WRAPPER_ABSENT', str(wrapper))
    return (['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-File', str(wrapper), '--', *python_args],
            {'CODEX_PYTHON': sys.executable})


def score_predictions(scorer: Path, upstream: Path, answers_path: Path, predictions: list[dict], out_dir: Path) -> dict:
    predictions_path = out_dir / 'mmmu-predictions.json'
    score_path = out_dir / 'mmmu-score.json'
    if score_path.exists():
        raise ProducerRefusal('OUTPUT_EXISTS', str(score_path))
    predictions_path.write_bytes(canonical(predictions) + b'\n')
    # The repository scorer admits an answer dictionary of multiple-choice rows ONLY; the digest-bound upstream
    # dictionary carries 900 rows (847 multiple-choice + 53 open). Filter to the eligible rows, materialize the
    # filtered dictionary beside the predictions, and score against that. Its digest lands in the receipt.
    full = json.loads(answers_path.read_bytes())
    eligible = {k: v for k, v in full.items() if isinstance(v, dict) and v.get('question_type') == 'multiple-choice'}
    if len(eligible) != 847:
        raise ProducerRefusal('ANSWER_FILTER_DRIFT', f'{len(eligible)} multiple-choice rows, expected 847')
    eligible_path = out_dir / 'mmmu-answers-eligible.json'
    eligible_path.write_bytes(canonical(eligible) + b'\n')
    # The nested scorer spawn is headless at ITS OWN boundary: no shell, no console window, hidden startup
    # info on Windows. An outer bootstrap can protect one particular run; the permanent rule is that the
    # actual spawn site is explicit, so a scorer invoked from any caller never raises a visible window.
    spawn = {}
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        spawn = {'creationflags': subprocess.CREATE_NO_WINDOW, 'startupinfo': startupinfo}
    argv, child_env = child_python_argv(['-B', str(scorer), '--mmmu-root', str(upstream), '--answers', str(eligible_path),
                                         '--predictions', str(predictions_path), '--score-output', str(score_path),
                                         '--timeout-seconds', '120'])
    run = subprocess.run(argv, shell=False, stdin=subprocess.DEVNULL, text=True, capture_output=True, check=False,
                         env={**os.environ, **child_env}, **spawn)
    if run.returncode != 0 or not score_path.is_file():
        raise ProducerRefusal('SCORER_FAILED', (run.stderr or run.stdout).strip()[-400:])
    score = json.loads(score_path.read_bytes())
    metrics = score.get('metrics') or {}
    if not isinstance(metrics.get('accuracy'), (int, float)) or score.get('sample_count') != ELIGIBLE_COUNT:
        raise ProducerRefusal('SCORER_SHAPE', json.dumps(score)[:200])
    return {'accuracy': float(metrics['accuracy']), 'sample_count': int(score['sample_count']),
            'predictions_sha256': sha256_path(predictions_path), 'score_sha256': sha256_path(score_path),
            'eligible_answers_sha256': sha256_path(eligible_path),
            'scorer_stdout_sha256': sha256_bytes(run.stdout.encode('utf-8'))}


def evaluate(checkpoint_root: str, protected_manifest: str) -> dict:
    """The gate's entrypoint. Returns a dict whose `score` is MMMU accuracy over the 847 eligible items."""
    started = time.monotonic()
    env = _env()
    condition = os.environ.get('EMBER_MMMU_IMAGE_CONDITION', 'real')
    if condition not in IMAGE_CONDITIONS:
        raise ProducerRefusal('IMAGE_CONDITION_UNKNOWN', condition)
    # Protocol first: opened and digested before the repository, the checkpoint, the tokenizer or any item.
    protocol_path, protocol_sha256 = bind_protocol()
    import torch
    torch.set_num_threads(int(env['EMBER_MMMU_THREADS']))
    repo_root = Path(env['EMBER_REPO_ROOT'])
    checkpoint_artifacts, gate, contract, scorer, projection_trained = repository(repo_root)
    custody = bind_custody(env, Path(protected_manifest))
    items = load_items(custody)
    encode, tokenizer_sha256 = _tokenizer(Path(env['EMBER_MMMU_TOKENIZER']))
    out_dir = Path(env['EMBER_MMMU_OUTPUT_DIR'])
    out_dir.mkdir(parents=True, exist_ok=True)
    model, verified, architecture_sha256 = open_reference(checkpoint_artifacts, gate, Path(checkpoint_root), Path(env['EMBER_MMMU_CHECKPOINT_RECEIPT']))
    opened = time.monotonic()
    progress_path = out_dir / 'progress.jsonl'

    def progress(done, total):
        with progress_path.open('ab') as handle:
            handle.write(canonical({'done': done, 'total': total, 'elapsed_seconds': time.monotonic() - opened}) + b'\n')

    rows = run_items(model, encode, items, progress=progress, condition=condition)
    if sha256_path(protocol_path) != protocol_sha256:
        raise ProducerRefusal('PROTOCOL_DRIFT', 'the protocol document changed while the items were scored')
    envelope = contract.validate_predictions(envelope_for(
        rows, checkpoint_manifest_sha256=verified['checkpoint_manifest_sha256'],
        model_config_sha256=verified['model_config_sha256'], tokenizer_sha256=tokenizer_sha256,
        implementation_sha256=sha256_path(Path(__file__)), protocol_sha256=protocol_sha256))
    (out_dir / 'mmmu-envelope.json').write_bytes(canonical(envelope) + b'\n')
    predictions = contract.materialize(envelope, 'mmmu')
    scored = score_predictions(scorer, custody['upstream'], custody['answers_path'], predictions, out_dir)
    free_valid = sum(1 for row in rows if row['free_argmax_token_id'] in LABEL_TOKEN_IDS.values())
    receipt = {
        'schema': 'ember-mmmu-cia-evaluation-receipt-v1', 'protocol': PROTOCOL_NAME, 'protocol_sha256': protocol_sha256,
        'claim_boundary': 'EXECUTABLE_PROTECTED_EVALUATION_PRODUCER; NO_IMAGE_CAPABILITY_TIER_LEARNING_OR_QUALIFICATION_CREDIT',
        'score': scored['accuracy'], 'sample_count': scored['sample_count'],
        'image_condition': condition,
        'image_condition_shift': image_shift(len(items)) if condition == 'wrong' else None,
        'checkpoint': {'root': str(Path(checkpoint_root).resolve()), 'manifest_sha256': verified['checkpoint_manifest_sha256'],
                       'architecture_revision': verified['architecture_revision'], 'architecture_sha256': architecture_sha256,
                       'data_cursor': verified['data_cursor'], 'model_config_sha256': verified['model_config_sha256'],
                       'receipt_path': str(Path(env['EMBER_MMMU_CHECKPOINT_RECEIPT']).resolve())},
        'image_projection_trained_by_runner': projection_trained,
        'image_projection_note': ('cia_step_runner.py embeds text only (no embed_image call at the read commit), so the image '
                                  'projection this producer exercises is genesis-initialized in every runner-produced checkpoint'),
        'custody': {'registry_sha256': custody['registry_sha256'], 'custody_manifest_sha256': custody['custody_manifest_sha256'],
                    'answer_sha256': ANSWER_SHA256, 'eligible_id_set_sha256': ELIGIBLE_ID_SET_SHA256, 'freeze_sha256': FREEZE_SHA256,
                    'image_inputs_sha256': IMAGE_INPUTS_SHA256, 'scorer_sha256': SCORER_SHA256, 'license_sha256': LICENSE_SHA256,
                    'tokenizer_sha256': tokenizer_sha256},
        'predictions': {k: scored[k] for k in ('predictions_sha256', 'score_sha256', 'scorer_stdout_sha256')},
        'free_generation': {'rows_whose_free_argmax_is_a_label_token': free_valid, 'rows': len(rows)},
        'determinism': {'first_item_repeat_identical': True},
        'per_item': [{k: row[k] for k in ('id', 'output', 'free_argmax_token_id', 'label_logits', 'document')} for row in rows],
        'environment': {'device': 'cpu', 'threads': int(env['EMBER_MMMU_THREADS']), 'torch': torch.__version__,
                        'python': sys.version.split()[0], 'open_seconds': opened - started, 'wall_seconds': time.monotonic() - started},
        'implementation_sha256': sha256_path(Path(__file__)),
    }
    # Two digests, named for what each covers: `self_sha256` is the canonical digest of the receipt's content
    # EXCLUDING this field (recomputable from the parsed receipt); `receipt_sha256` in the return value is the
    # digest of the FILE BYTES actually written, which is what a consumer hashing the file on disk observes.
    receipt['self_sha256'] = sha256_bytes(canonical(receipt))
    receipt_path = out_dir / 'mmmu-cia-evaluation-receipt.json'
    receipt_path.write_bytes(json.dumps(receipt, sort_keys=True, indent=1).encode('utf-8'))
    return {'score': scored['accuracy'], 'sample_count': scored['sample_count'], 'receipt': str(receipt_path),
            'receipt_sha256': sha256_path(receipt_path), 'receipt_self_sha256': receipt['self_sha256'],
            'protocol_sha256': protocol_sha256, 'image_condition': condition,
            'image_projection_trained_by_runner': projection_trained,
            'checkpoint_manifest_sha256': verified['checkpoint_manifest_sha256']}


# ---------------------------------------------------------------- self-test (deliberate red)

class _StubModel:
    """Embeds by table lookup and returns logits that prefer a fixed label unless the document is long."""

    def __init__(self, vocab=32000, hidden=1024, prefer='B'):
        import torch
        g = torch.Generator().manual_seed(0)
        self.table = torch.randn(vocab, hidden, generator=g).to(torch.bfloat16)
        self.image = torch.randn(768, hidden, generator=g).to(torch.bfloat16)
        self.prefer = prefer
        self.calls = []

    def embed_text(self, tokens):
        return self.table[tokens]

    def embed_image(self, patches):
        import torch
        if patches.shape[-1] != 768:
            raise ValueError('expected [positions,768]')
        return (patches.float() @ self.image.float()).to(torch.bfloat16)

    def __call__(self, embedded, positions, *, document_starts=(0,)):
        import torch
        if embedded.dtype != torch.bfloat16 or positions.shape != (len(embedded), 3):
            raise ValueError('stub received a malformed document')
        self.calls.append((len(embedded), tuple(positions[-1].tolist())))
        logits = torch.zeros(len(embedded), self.table.shape[0])
        logits[-1, LABEL_TOKEN_IDS[self.prefer]] = 5.0
        logits[-1, 7] = 9.0   # a non-label token wins the free argmax, as it did on every 09-01 row
        return logits


def self_test() -> int:
    import torch
    from PIL import Image
    failures = []

    def check(name, condition):
        (failures if not condition else []).append(name)
        print(('PASS ' if condition else 'FAIL ') + name)

    buffer = io.BytesIO(); Image.new('RGB', (733, 237), (200, 30, 30)).save(buffer, format='PNG'); png = buffer.getvalue()
    patches, coordinates, grid = image_patches(png)
    check('grid preserves aspect within 8x8', grid == (8, 3) and len(coordinates) == 24 and patches.shape == (24, 768))
    check('patch values are unit-scaled bf16', patches.dtype == torch.bfloat16 and float(patches.max()) <= 1.0)
    model = _StubModel(prefer='B')
    encode = lambda text: [100 + (i % 50) for i in range(len(text.split()))]
    item = {'id': 'validation_Test_1', 'question': 'What is <image 1>?', 'options': ['x', 'y', 'z', 'w']}
    embedded, positions, meta = build_document(model, encode, item, [png])
    check('document = <boi> + patches + <eoi> + text', meta['positions'] == 1 + 24 + 1 + meta['text_tokens'])
    check('image axes carry patch coordinates', tuple(positions[2].tolist()) == (2, 1, 0) and tuple(positions[-1].tolist())[1:] == (0, 0))
    choice, free_token, scores = choose(model, embedded, positions, ['A', 'B', 'C', 'D'])
    check('constrained choice is the preferred label', choice == 'B' and free_token == 7 and len(scores) == 4)
    # image-dependence control: real keeps the item's own images, missing drops them, wrong is a derangement
    trio = [{'id': 'i%d' % k, 'images': [bytes([k])]} for k in range(5)]
    check('real condition keeps own images', [condition_images(trio, k, 'real') for k in range(5)] == [x['images'] for x in trio])
    check('missing condition drops every image', all(condition_images(trio, k, 'missing') == [] for k in range(5)))
    wrong = [condition_images(trio, k, 'wrong') for k in range(5)]
    check('wrong condition is a derangement over real images',
          all(w != trio[k]['images'] for k, w in enumerate(wrong)) and sorted(wrong) == sorted(x['images'] for x in trio))
    embedded_missing, _, meta_missing = build_document(model, encode, item, condition_images([dict(item, images=[png])] * 1, 0, 'missing'))
    check('missing-image document is text only', meta_missing['images'] == [] and meta_missing['positions'] == meta_missing['text_tokens'])
    # deliberate reds: each refusal must fire
    try:
        condition_images(trio, 0, 'blurred')
        check('unknown image condition refused', False)
    except ProducerRefusal as exc:
        check('unknown image condition refused', exc.token == 'IMAGE_CONDITION_UNKNOWN')
    try:
        condition_images(trio[:1], 0, 'wrong')
        check('wrong-image control with one item refused', False)
    except ProducerRefusal as exc:
        check('wrong-image control with one item refused', exc.token == 'IMAGE_CONDITION_UNDEFINED')
    try:
        choose(model, embedded, positions, ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J'])
        check('too many labels refused', False)
    except KeyError:
        check('too many labels refused', True)
    try:
        build_document(model, lambda text: [], item, [])
        check('empty prompt refused', False)
    except ProducerRefusal as exc:
        check('empty prompt refused', exc.token == 'EMPTY_PROMPT')
    try:
        _bound_json(Path(__file__), ANSWER_SHA256, 'WRONG_GOLD')
        check('digest-bound read refuses foreign bytes', False)
    except ProducerRefusal as exc:
        check('digest-bound read refuses foreign bytes', exc.token == 'WRONG_GOLD')
    try:
        os.environ.pop('EMBER_MMMU_THREADS', None); _env()
        check('absent configuration refused', False)
    except ProducerRefusal as exc:
        check('absent configuration refused', exc.token == 'CONFIG_ABSENT')
    # the envelope this producer emits validates under the repository's own prediction contract
    repo = os.environ.get('EMBER_REPO_ROOT')
    if repo:
        contract = _load_module('ember_restart_prediction_contract',
                                Path(repo) / 'src' / 'ember' / 'governance' / 'scripts' / 'ember_restart' / 'prediction_contract.py')
        rows = [{'id': item['id'], 'input_sha256': '0' * 64, 'generated_token_ids': [41], 'stop_reason': 'max_new_tokens',
                 'output': {'kind': 'choice', 'value': 'B'}}]
        env = envelope_for(rows, checkpoint_manifest_sha256='1' * 64, model_config_sha256='2' * 64, tokenizer_sha256='3' * 64,
                           implementation_sha256='4' * 64, protocol_sha256='5' * 64)
        try:
            materialized = contract.materialize(contract.validate_predictions(env), 'mmmu')
            check('envelope validates and materializes to the mmmu adapter shape', materialized == [{'id': item['id'], 'prediction': 'B'}])
        except Exception as exc:
            check('envelope validates and materializes to the mmmu adapter shape (%s)' % exc, False)
        bad = dict(env, rows=[dict(rows[0], output={'kind': 'text', 'text': 'B'})])
        try:
            contract.materialize(contract.validate_predictions(bad), 'mmmu')
            check('a text output is refused by the mmmu adapter', False)
        except Exception:
            check('a text output is refused by the mmmu adapter', True)
    else:
        print('SKIP envelope contract checks (EMBER_REPO_ROOT unset)')
    print('SELF-TEST ' + ('PASS' if not failures else 'FAIL ' + ','.join(failures)))
    return 0 if not failures else 1


if __name__ == '__main__':
    if '--self-test' in sys.argv:
        raise SystemExit(self_test())
    print(__doc__)
    raise SystemExit(2)
