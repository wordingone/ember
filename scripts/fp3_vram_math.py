"""fp3_vram_math.py — full-FT feasibility ladder under the governor (#39).

DERIVATION RECEIPT, NOT A MEASUREMENT (the Kai-S2-A distinction): this
script executes the optimizer-memory arithmetic from stated, named
assumptions and receipted governor constants. The measured answer comes
from the 1.5B full-FT governed smoke this derivation stages (1 step,
VRAM receipt) — that receipt supersedes every ESTIMATE row here.

Inputs (receipted): governor block from the latest training receipt
(vram_fraction, total_gb, margin_gb — t2-r1w-q3-grpo-20260610T223426Z).
Assumptions (stated, standard mixed-precision accounting):
  - bf16 weights 2 B/param; bf16 grads 2 B/param.
  - AdamW fp32 moments: +8 B/param (m+v). With fp32 master copy: +4.
  - 8-bit Adam (bitsandbytes): moments ~2 B/param total.
  - Activation allowance band at our shapes (seq<=1024, micro-batch<=8,
    grad-checkpointing ON): 1-3 GB — band, not point (shape-dependent).
Param counts are the actual HF config totals for Qwen2.5 cores:
0.5B=0.494e9, 1.5B=1.544e9, 3B=3.086e9 (model cards).
`python fp3_vram_math.py --selftest` runs the fail-closed checks.
"""
import json
import os
from datetime import datetime, timezone

from receipt_write import checked_write

NC_WIN = "B:/M/avir/leo/state/nc-ladder"
RECEIPTS = f"{NC_WIN}/receipts"
GOV_SRC = f"{RECEIPTS}/t2-r1w-q3-grpo-20260610T223426Z.json"

CORES = {"qwen2.5-0.5b": 0.494e9, "qwen2.5-1.5b": 1.544e9,
         "qwen2.5-3b": 3.086e9}
# bytes/param for weights+grads+optimizer states (activations added as band)
REGIMES = {
    "adamw_fp32_moments": 2 + 2 + 8,        # bf16 w+g, fp32 m+v
    "adamw_fp32_moments_master": 2 + 2 + 8 + 4,
    "adamw_8bit": 2 + 2 + 2,                # bnb 8-bit m+v
}
ACT_BAND_GB = (1.0, 3.0)


def ladder(gov):
    cap_gb = round(gov["vram_fraction"] * gov["total_gb"], 2)
    rows = []
    for core, n in sorted(CORES.items(), key=lambda kv: kv[1]):
        for regime, bpp in REGIMES.items():
            states = n * bpp / 2**30
            lo = states + ACT_BAND_GB[0]
            hi = states + ACT_BAND_GB[1]
            verdict = ("FITS" if hi <= cap_gb else
                       "MARGINAL" if lo <= cap_gb else "NO")
            rows.append({"core": core, "params_b": round(n / 1e9, 3),
                         "regime": regime, "bytes_per_param": bpp,
                         "states_gb": round(states, 2),
                         "est_total_gb": [round(lo, 2), round(hi, 2)],
                         "verdict_at_cap": verdict})
    return cap_gb, rows


def main():
    with open(GOV_SRC, encoding="utf-8") as f:
        gov = json.load(f)["governor"]
    cap_gb, rows = ladder(gov)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "FP3-VRAM-DERIVATION", "ts": ts,
        "kind": "derivation (executed arithmetic from stated assumptions) "
                "— NOT a VRAM measurement; the 1.5B full-FT smoke receipt "
                "supersedes",
        "governor_source": os.path.basename(GOV_SRC),
        "governor": gov, "cap_gb": cap_gb,
        "activation_band_gb": list(ACT_BAND_GB),
        "ladder": rows,
        "receipted_lora_anchors": {
            "qlora_3b_train": "t2-r1w-q3-*: 57 steps 281-285s, adapter "
                              "239,536,272 B (r=32)",
            "qlora_7b_train_peak": "ember-r1: 16.4/24.5 GB held",
            "eval_3b_merged_peak": "t4 s14 health: 8,278/24,564 MiB",
        },
    }
    out = f"{RECEIPTS}/fp3-vram-derivation-{ts}.json"
    checked_write(out, receipt)
    print(json.dumps(receipt, indent=2))
    print(f"FP3_VRAM_DONE {out}")


def _selftest():
    gov = {"vram_fraction": 0.85, "total_gb": 25.76, "margin_gb": 4.0}
    cap, rows = ladder(gov)
    assert cap == 21.9, cap
    get = lambda c, r: next(x for x in rows  # noqa: E731
                            if x["core"] == c and x["regime"] == r)
    # 0.5B fits under every regime; 3B full-precision AdamW cannot fit
    for reg in REGIMES:
        assert get("qwen2.5-0.5b", reg)["verdict_at_cap"] == "FITS", reg
    assert get("qwen2.5-3b", "adamw_fp32_moments")["verdict_at_cap"] == "NO"
    assert get("qwen2.5-3b", "adamw_fp32_moments_master")[
        "verdict_at_cap"] == "NO"
    # ladder is monotonic in params within a regime
    for reg in REGIMES:
        ests = [x["est_total_gb"][1] for x in rows if x["regime"] == reg]
        assert ests == sorted(ests)
    print("FP3_VRAM_SELFTEST_PASS")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _selftest()
    else:
        main()
