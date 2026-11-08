# goal_id: EMBER-02
# workstream_id: EMBER-02B
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""SLEEP-1 teacher-only CUDA probe (#2119 ruling (b) follow-up).

Builds the frozen teacher exactly as sleep_direct_v1 does (paged activate_cuda, no student), then logs every dtype the
decoder guard reads and runs (1) the v13-scorer-style forward and (2) sleep.count_routes on one prefix. Each forward's
outcome is printed, success or refusal, so a refusal is diagnosed rather than bare. No write besides --out.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import traceback
from pathlib import Path

import torch

for _p in (Path(__file__).resolve().parent, Path(__file__).resolve().parents[4]):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import checkpoint_artifacts as artifacts  # noqa: E402
import sleep_consolidate_v1 as sleep  # noqa: E402
from ember.model.ember_v0_decoder import CIADecoder  # noqa: E402


def log(out, **row):
    row['t'] = round(time.monotonic() - T0, 2)
    line = json.dumps(row, default=str)
    print(line, flush=True)
    with open(out, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def attempt(out, name, fn):
    try:
        result = fn()
        log(out, stage=name, ok=True, result=result)
    except Exception as exc:  # noqa: BLE001 - the probe reports every refusal
        log(out, stage=name, ok=False, error=repr(exc), tb=traceback.format_exc()[-1500:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--teacher-root', required=True)
    ap.add_argument('--teacher-manifest-sha256', required=True)
    ap.add_argument('--prefixes', required=True)
    ap.add_argument('--prefixes-sha256', required=True)
    ap.add_argument('--device', default='cuda:0')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if hashlib.sha256(Path(args.prefixes).read_bytes()).hexdigest() != args.prefixes_sha256:
        raise ValueError('prefixes sha differs from its declaration')
    tok = json.loads(Path(args.prefixes).read_text(encoding='utf-8').splitlines()[0])['tokens']
    log(out, stage='start', env={k: v for k, v in os.environ.items() if k.startswith('EMBER_')}, prefix_len=len(tok),
        torch=torch.__version__, default_dtype=str(torch.get_default_dtype()))
    rec = artifacts.published_checkpoint_receipt(Path(args.teacher_root))
    tv, tensors, _o, _r = artifacts._cia_validated_checkpoint(Path(args.teacher_root), rec, retain_model=True,
                                                            max_restore_payload_bytes=40 * 2 ** 30)
    if tv['checkpoint_manifest_sha256'] != args.teacher_manifest_sha256:
        raise ValueError('teacher manifest differs')
    model = CIADecoder(architecture_config=tv['architecture_config']).materialize_cpu(seed=0)
    inv = model.parameter_inventory()
    mism = [n for n, v in tensors.items() if v.dtype != inv[n].dtype or tuple(v.shape) != tuple(inv[n].shape)]
    with torch.no_grad():
        for n, v in tensors.items():
            inv[n].copy_(v)
    del tensors
    sleep.freeze_except(inv, ())
    model.eval()
    log(out, stage='cpu_built', dtype_mismatch=mism[:10], non_bf16=[n for n, p in inv.items() if p.dtype != torch.bfloat16][:10])
    model.activate_cuda(args.device)
    w = {k: (str(v.dtype), str(v.device)) for k, v in model.weights.items() if 'embedding' in k or 'modality' in k}
    log(out, stage='activated', weights=w, execution_device=str(model._execution_device))
    device = args.device
    t = torch.tensor(tok, dtype=torch.long, device=device)
    pos = torch.tensor([[i, 0, 0] for i in range(len(tok))], dtype=torch.long, device=device)

    def embed_only():
        with model.candidate_step():
            e = model.embed_text(t)
        return dict(dtype=str(e.dtype), shape=tuple(e.shape), device=str(e.device))

    def scorer_style():
        with torch.no_grad(), model.candidate_step():
            e = model.embed_text(t)
            logits, _r = model(e, pos, document_starts=(0,), return_routes=True, batch_documents=True)
        return dict(logits=str(logits.dtype), shape=tuple(logits.shape))

    def plain():
        with torch.no_grad(), model.candidate_step():
            logits, _r = model(model.embed_text(t), pos, document_starts=(0,), return_routes=True)
        return dict(logits=str(logits.dtype), shape=tuple(logits.shape))

    attempt(out, 'embed_only', embed_only)
    attempt(out, 'forward_scorer_style', scorer_style)
    attempt(out, 'forward_plain', plain)
    attempt(out, 'count_routes', lambda: list(sleep.count_routes(model, [tok], device).items())[:4])
    log(out, stage='done', peak_cuda_gib=round(torch.cuda.max_memory_allocated(device) / 2 ** 30, 2))


T0 = time.monotonic()
if __name__ == '__main__':
    main()
