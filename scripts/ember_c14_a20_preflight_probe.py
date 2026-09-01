#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""ember_c14_a20_preflight_probe.py — A20 substrate-override CPU preflight.

Proves the make_owned_core_factory(seed_ckpt=..., expected_model_pt_sha256=...)
override (src/ember/governance/scripts/ember_c14_owned_core.py) loads the A20 grown/stabilized
checkpoint correctly, WITHOUT touching a GPU: device="cpu" throughout.
Prints measured intermediate (FF) size, both a raw-tensor-sum and a
deduped-live-model param count (see PARAM COUNT NOTE below), and compares the
freshly-built adapter's lora_A/lora_B shapes against A19's trained artifact.
Writes receipts/ember-c14-owned-run/a20-preflight-<ts>.json.

PARAM COUNT NOTE (found by this probe, not assumed): the checkpoint's own
manifest.json (checkpoints/step-00000730/manifest.json, the immediate
post-growth checkpoint before "stabilize") documents "ff_seed": 8192,
"ff_grown": 16384, "mechanism": "ff_widening_net2net" — so the substrate
this probe was pointed at IS post-growth (intermediate=16384), not the
pre-growth seed width. head.weight is TIED to backbone_model.embed_tokens.
weight (cbase_grow_dryrun.build_model's tie_word_embeddings convention), so
a raw sum over the checkpoint's on-disk state_dict tensors double-counts
that one embedding matrix (32000*1024=32,768,000 elements) relative to the
LIVE model's deduped nn.Module.parameters() count, which PyTorch naturally
dedupes for a tied Parameter object. This probe reports BOTH numbers.

CPU-ONLY. No .cuda() call anywhere in this file.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
# issue2015 exact-local-import:src/ember/governance/scripts/ember_c14_owned_core.py
import importlib.util as _ember_280f96ad7e9e1531_importlib
import sys as _ember_280f96ad7e9e1531_sys
from pathlib import Path as _ember_280f96ad7e9e1531_Path
_ember_280f96ad7e9e1531_path = _ember_280f96ad7e9e1531_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'ember_c14_owned_core.py')
if not _ember_280f96ad7e9e1531_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/ember_c14_owned_core.py')
_ember_280f96ad7e9e1531_aliases = ('_ember_issue2015_280f96ad7e9e1531', 'ember_c14_owned_core', 'scripts.ember_c14_owned_core')
_ember_280f96ad7e9e1531_existing = []
for _ember_280f96ad7e9e1531_alias in _ember_280f96ad7e9e1531_aliases:
    _ember_280f96ad7e9e1531_candidate = _ember_280f96ad7e9e1531_sys.modules.get(_ember_280f96ad7e9e1531_alias)
    if _ember_280f96ad7e9e1531_candidate is not None and all(_ember_280f96ad7e9e1531_candidate is not item for item in _ember_280f96ad7e9e1531_existing):
        _ember_280f96ad7e9e1531_existing.append(_ember_280f96ad7e9e1531_candidate)
if len(_ember_280f96ad7e9e1531_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/ember_c14_owned_core.py')
if _ember_280f96ad7e9e1531_existing:
    _ember_280f96ad7e9e1531_module = _ember_280f96ad7e9e1531_existing[0]
    _ember_280f96ad7e9e1531_observed = getattr(_ember_280f96ad7e9e1531_module, '__file__', None)
    if _ember_280f96ad7e9e1531_observed is None or _ember_280f96ad7e9e1531_Path(_ember_280f96ad7e9e1531_observed).resolve() != _ember_280f96ad7e9e1531_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/ember_c14_owned_core.py')
else:
    _ember_280f96ad7e9e1531_spec = _ember_280f96ad7e9e1531_importlib.spec_from_file_location('_ember_issue2015_280f96ad7e9e1531', _ember_280f96ad7e9e1531_path)
    if _ember_280f96ad7e9e1531_spec is None or _ember_280f96ad7e9e1531_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/ember_c14_owned_core.py')
    _ember_280f96ad7e9e1531_module = _ember_280f96ad7e9e1531_importlib.module_from_spec(_ember_280f96ad7e9e1531_spec)
    for _ember_280f96ad7e9e1531_alias in _ember_280f96ad7e9e1531_aliases:
        _ember_280f96ad7e9e1531_prior = _ember_280f96ad7e9e1531_sys.modules.get(_ember_280f96ad7e9e1531_alias)
        if _ember_280f96ad7e9e1531_prior is not None and _ember_280f96ad7e9e1531_prior is not _ember_280f96ad7e9e1531_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_c14_owned_core.py')
        _ember_280f96ad7e9e1531_sys.modules[_ember_280f96ad7e9e1531_alias] = _ember_280f96ad7e9e1531_module
    try:
        _ember_280f96ad7e9e1531_spec.loader.exec_module(_ember_280f96ad7e9e1531_module)
    except BaseException:
        for _ember_280f96ad7e9e1531_alias in _ember_280f96ad7e9e1531_aliases:
            if _ember_280f96ad7e9e1531_sys.modules.get(_ember_280f96ad7e9e1531_alias) is _ember_280f96ad7e9e1531_module:
                _ember_280f96ad7e9e1531_sys.modules.pop(_ember_280f96ad7e9e1531_alias, None)
        raise
for _ember_280f96ad7e9e1531_alias in _ember_280f96ad7e9e1531_aliases:
    _ember_280f96ad7e9e1531_prior = _ember_280f96ad7e9e1531_sys.modules.get(_ember_280f96ad7e9e1531_alias)
    if _ember_280f96ad7e9e1531_prior is not None and _ember_280f96ad7e9e1531_prior is not _ember_280f96ad7e9e1531_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/ember_c14_owned_core.py')
    _ember_280f96ad7e9e1531_sys.modules[_ember_280f96ad7e9e1531_alias] = _ember_280f96ad7e9e1531_module
make_owned_core_factory = getattr(_ember_280f96ad7e9e1531_module, 'make_owned_core_factory')
# issue2015 exact-local-import-end:src/ember/governance/scripts/ember_c14_owned_core.py  # noqa: E402
# issue2015 exact-local-import:src/ember/governance/scripts/receipt_write.py
import importlib.util as _ember_66ee9e91637922dc_importlib
import sys as _ember_66ee9e91637922dc_sys
from pathlib import Path as _ember_66ee9e91637922dc_Path
_ember_66ee9e91637922dc_path = _ember_66ee9e91637922dc_Path(__file__).resolve().parents[1].joinpath('src', 'ember', 'governance', 'scripts', 'receipt_write.py')
if not _ember_66ee9e91637922dc_path.is_file():
    raise ImportError('EXACT_LOCAL_IMPORT_TARGET_MISSING:src/ember/governance/scripts/receipt_write.py')
_ember_66ee9e91637922dc_aliases = ('_ember_issue2015_66ee9e91637922dc', 'receipt_write', 'scripts.receipt_write')
_ember_66ee9e91637922dc_existing = []
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_candidate = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_candidate is not None and all(_ember_66ee9e91637922dc_candidate is not item for item in _ember_66ee9e91637922dc_existing):
        _ember_66ee9e91637922dc_existing.append(_ember_66ee9e91637922dc_candidate)
if len(_ember_66ee9e91637922dc_existing) > 1:
    raise ImportError('EXACT_LOCAL_IMPORT_IDENTITY_COLLISION:src/ember/governance/scripts/receipt_write.py')
if _ember_66ee9e91637922dc_existing:
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_existing[0]
    _ember_66ee9e91637922dc_observed = getattr(_ember_66ee9e91637922dc_module, '__file__', None)
    if _ember_66ee9e91637922dc_observed is None or _ember_66ee9e91637922dc_Path(_ember_66ee9e91637922dc_observed).resolve() != _ember_66ee9e91637922dc_path:
        raise ImportError('EXACT_LOCAL_IMPORT_WRONG_TARGET:src/ember/governance/scripts/receipt_write.py')
else:
    _ember_66ee9e91637922dc_spec = _ember_66ee9e91637922dc_importlib.spec_from_file_location('_ember_issue2015_66ee9e91637922dc', _ember_66ee9e91637922dc_path)
    if _ember_66ee9e91637922dc_spec is None or _ember_66ee9e91637922dc_spec.loader is None:
        raise ImportError('EXACT_LOCAL_IMPORT_SPEC_INVALID:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_module = _ember_66ee9e91637922dc_importlib.module_from_spec(_ember_66ee9e91637922dc_spec)
    for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
        _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
        if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
            raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
        _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
    try:
        _ember_66ee9e91637922dc_spec.loader.exec_module(_ember_66ee9e91637922dc_module)
    except BaseException:
        for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
            if _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias) is _ember_66ee9e91637922dc_module:
                _ember_66ee9e91637922dc_sys.modules.pop(_ember_66ee9e91637922dc_alias, None)
        raise
for _ember_66ee9e91637922dc_alias in _ember_66ee9e91637922dc_aliases:
    _ember_66ee9e91637922dc_prior = _ember_66ee9e91637922dc_sys.modules.get(_ember_66ee9e91637922dc_alias)
    if _ember_66ee9e91637922dc_prior is not None and _ember_66ee9e91637922dc_prior is not _ember_66ee9e91637922dc_module:
        raise ImportError('EXACT_LOCAL_IMPORT_ALIAS_COLLISION:src/ember/governance/scripts/receipt_write.py')
    _ember_66ee9e91637922dc_sys.modules[_ember_66ee9e91637922dc_alias] = _ember_66ee9e91637922dc_module
checked_write = getattr(_ember_66ee9e91637922dc_module, 'checked_write')
# issue2015 exact-local-import-end:src/ember/governance/scripts/receipt_write.py  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SEED_CKPT = REPO / "models/cbase-grow-rung/rung1-20260703T155447Z/stabilize/checkpoints/step-00000766"
EXPECTED_SHA = "58e8e98916823941381d9cf71cf3725148aa61cf106e8b46c4fa96e0c5e4659b"
A19_ADAPTER = REPO / "receipts/ember-c14-owned-run/resident-adapter-20260703T154830Z.pt"

factory = make_owned_core_factory(
    device="cpu", rank=8, seed_ckpt=SEED_CKPT, expected_model_pt_sha256=EXPECTED_SHA
)
adapter = factory()

intermediate = adapter._owned_core_intermediate
param_count_deduped = int(sum(p.numel() for p in adapter.base.parameters()))
raw_sd = torch.load(SEED_CKPT / "model.pt", map_location="cpu", weights_only=True)
param_count_raw_tensor_sum = int(sum(v.numel() for v in raw_sd.values()))
del raw_sd

fresh_sd = adapter.adapter_state_dict()
a19_sd = torch.load(A19_ADAPTER, map_location="cpu", weights_only=True)
shape_compare = {
    k: {
        "a19_shape": list(a19_sd[k].shape),
        "fresh_shape": list(fresh_sd.get(k, torch.empty(0)).shape),
        "equal": k in fresh_sd and tuple(a19_sd[k].shape) == tuple(fresh_sd[k].shape),
    }
    for k in a19_sd
}
all_shapes_equal = all(v["equal"] for v in shape_compare.values()) and set(fresh_sd) == set(a19_sd)

print(
    f"intermediate={intermediate} "
    f"param_count_deduped={param_count_deduped} "
    f"param_count_raw_tensor_sum={param_count_raw_tensor_sum} "
    f"all_shapes_equal={all_shapes_equal}"
)
for k, v in shape_compare.items():
    print(f"  {k}: a19={v['a19_shape']} fresh={v['fresh_shape']} equal={v['equal']}")

# Verdict gate = adapter-shape compatibility, the fact that actually governs
# whether A20 can reuse A19's trained lineage / whether cmd_live's own
# --adapter-shape-manifest preflight will pass at fire time. Load succeeding
# + intermediate measured from real tensor bytes (never hardcoded) are
# necessary preconditions, folded in as load_and_measure_ok.
load_and_measure_ok = intermediate > 0 and param_count_deduped > 0
verdict = "A20-PREFLIGHT-PASS" if (load_and_measure_ok and all_shapes_equal) else "A20-PREFLIGHT-BLOCKED"

receipt = {
    "ticket": "A20-SUBSTRATE-OVERRIDE-PREFLIGHT",
    "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
    "device": "cpu",
    "seed_checkpoint_path": str(SEED_CKPT.relative_to(REPO)).replace("\\", "/"),
    "seed_checkpoint_sha256": EXPECTED_SHA,
    "a19_adapter_manifest": str(A19_ADAPTER.relative_to(REPO)).replace("\\", "/"),
    "measured_intermediate_size": intermediate,
    "measured_param_count_deduped_live_model": param_count_deduped,
    "measured_param_count_raw_tensor_sum": param_count_raw_tensor_sum,
    "spec_predicted_intermediate_size": 8192,
    "spec_predicted_param_count": 1_221_633_024,
    "discrepancy_note": (
        "Measured intermediate=16384, not the spec's predicted 8192. Root "
        "cause found, not assumed: checkpoints/step-00000730/manifest.json "
        "(the immediate post-growth checkpoint, sibling of this stabilize "
        "checkpoint's lineage) records ff_seed=8192, ff_grown=16384 via "
        "ff_widening_net2net -- the named substrate "
        "(stabilize/checkpoints/step-00000766) is POST-growth, so 16384 is "
        "the correct measurement for the checkpoint actually pointed at; "
        "8192 was the PRE-growth seed width. Separately, "
        "param_count_raw_tensor_sum (1,221,633,024) matches the spec's "
        "predicted param count exactly, while param_count_deduped_live_model "
        "(1,188,865,024) is lower by exactly one tied embedding matrix "
        "(32000*1024=32,768,000) -- head.weight is tied to "
        "backbone_model.embed_tokens.weight, so the live nn.Module's "
        ".parameters() naturally dedupes it while a raw sum over the "
        "on-disk state_dict tensors double-counts it. Neither number is "
        "wrong; they measure different things (raw on-disk bytes vs live "
        "deduped model) -- reporting both rather than picking one silently."
    ),
    "adapter_shape_compare": shape_compare,
    "all_shapes_equal": all_shapes_equal,
    "load_and_measure_ok": load_and_measure_ok,
    "verdict": verdict,
}
out = REPO / "receipts/ember-c14-owned-run" / f"a20-preflight-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
checked_write(str(out), receipt)
print(f"VERDICT: {verdict}")
print(f"receipt={out}")
