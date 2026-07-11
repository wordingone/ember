#!/usr/bin/env python3
"""ember_c14_a20_preflight_probe.py — A20 substrate-override CPU preflight.

Proves the make_owned_core_factory(seed_ckpt=..., expected_model_pt_sha256=...)
override (scripts/ember_c14_owned_core.py) loads the A20 grown/stabilized
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
from ember_c14_owned_core import make_owned_core_factory  # noqa: E402
from receipt_write import checked_write  # noqa: E402

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
