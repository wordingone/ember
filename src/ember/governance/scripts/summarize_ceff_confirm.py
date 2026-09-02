#!/usr/bin/env python3
"""Derive a faithful summary receipt for the C-EFF confirm run from its checkpoint
manifests. The summary is the OUTPUT of this executed job over on-disk artifacts —
never hand-copied from prose. It reports the loss trajectory + run config + integrity
hashes that the manifests actually contain, and is explicit that the C-EFF efficiency
multiplier (the lever-stack vs baseline ratio) is NOT computed here: that lives in the
adjudication receipt (ceff-shatter-REPUDIATED-...), since a single run's manifests cannot
establish a comparison ratio.

Usage: python src/ember/governance/scripts/summarize_ceff_confirm.py
Writes: receipts/ceff-confirm-summary-bf16ns5-20260628T044638Z/summary.json
"""
import glob
import json
import os
import sys

RUN_DIR = "models/ceff-confirm-bf16ns5-20260628T044638Z"
OUT_DIR = "receipts/ceff-confirm-summary-bf16ns5-20260628T044638Z"


def main() -> int:
    manifests = sorted(glob.glob(os.path.join(RUN_DIR, "checkpoints", "step-*", "manifest.json")))
    if not manifests:
        print(f"NO MANIFESTS under {RUN_DIR}/checkpoints/ — nothing to summarize", file=sys.stderr)
        return 1

    ckpts = []
    for m in manifests:
        with open(m, "r", encoding="utf-8") as fh:
            d = json.load(fh)
        extra = d.get("extra", {})
        ckpts.append({
            "step": d.get("step"),
            "last_loss": extra.get("last_loss"),
            "ts": d.get("ts"),
            "model_sha256": d.get("files", {}).get("model.pt"),
            "ticket": d.get("ticket"),
        })
    ckpts.sort(key=lambda c: (c["step"] is None, c["step"]))

    first, last = ckpts[0], ckpts[-1]
    losses = [c["last_loss"] for c in ckpts if isinstance(c["last_loss"], (int, float))]
    # strict monotone-nonincreasing check across the checkpointed trajectory
    monotone_nonincreasing = all(losses[i] >= losses[i + 1] for i in range(len(losses) - 1)) if len(losses) > 1 else None

    sample = json.load(open(manifests[0], "r", encoding="utf-8")).get("extra", {})
    summary = {
        "schema_version": 1,
        "kind": "ceff-confirm-run-summary",
        "derived_from": f"{RUN_DIR}/checkpoints/step-*/manifest.json",
        "provenance": "output of src/ember/governance/scripts/summarize_ceff_confirm.py over on-disk checkpoint manifests; not hand-authored from prose",
        "run_config": {
            "segment_id": sample.get("segment_id"),
            "ce_impl": sample.get("ce_impl"),
            "optimizer_mode": sample.get("optimizer_mode"),
            "mtp_enabled": sample.get("mtp_enabled"),
            "total_steps_planned": sample.get("total_steps"),
        },
        "trajectory": {
            "n_checkpoints": len(ckpts),
            "first_step": first["step"],
            "first_loss": first["last_loss"],
            "last_step": last["step"],
            "last_loss": last["last_loss"],
            "loss_delta": (round(last["last_loss"] - first["last_loss"], 6)
                          if isinstance(first["last_loss"], (int, float)) and isinstance(last["last_loss"], (int, float)) else None),
            "monotone_nonincreasing": monotone_nonincreasing,
            "first_ts": first["ts"],
            "last_ts": last["ts"],
            "ticket": last.get("ticket"),
            "ran_to_planned_total": (last["step"] == sample.get("total_steps")),
        },
        "checkpoints": ckpts,
        "efficiency_multiplier_note": (
            "The C-EFF lever-stack efficiency multiplier (1.85x stated / 1.1826x measured bf16ns5, "
            "verdict PRICED_SCALEOUT_RESIDUAL) is a comparison ratio against a baseline run and is NOT "
            "derivable from this single confirm run's manifests. It is established by the adjudication "
            "receipt receipts/ceff-shatter-REPUDIATED-20260623T170000Z.json. This summary only attests "
            "the confirm run's own trajectory, config, and per-checkpoint model.pt integrity hashes."
        ),
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, "summary.json")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2)
    print(json.dumps(summary["trajectory"], indent=2))
    print(f"WROTE {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
