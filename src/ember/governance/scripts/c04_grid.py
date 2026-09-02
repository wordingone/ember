#!/usr/bin/env python
"""c04_grid.py - fp-37 (#352): c04 candidate-grid arithmetic.

Every constant is receipt-pinned (named in CONSTANTS). Closed-form only -
the design bench (#353) measures truth; this prunes the grid and exposes
the budget equation. Emits receipts/c04-grid-<ts>.json with --emit.

Selftest anchors reproduce c03 receipted facts before any projection is
trusted: params, FLOP/token, the compiled-cell sustained-FLOPS anchor, and
the b16-nockpt OOM boundary (S^2 attention term dominates - c03 has no
flash path; that finding is itself a c04 lever candidate, C-7).
"""
import argparse, json, sys, time

CONSTANTS = {
    # receipt-pinned
    "V": 32000,                 # tokenizer-freeze-20260611T154111Z.json
    "S": 1024,                  # v0-pretrain-config.json model.seq
    "tied_embeddings": True,    # v0-pretrain-config.json
    "c03": {"h": 1024, "d": 20, "heads": 16},
    "gov_cap_gib": 24.0 * 0.80, # governor vram_fraction 0.80 (all receipts)
    "margin_gib": 1.5,          # governor margin floor
    "anchor_tok_s_compiled": 31377.0,   # fp32-l6-compile-ab-20260612T215844Z (b16-ckpt-compile)
    "anchor_mode": "ckpt",
    "governed_day_s": 86400,
    # model-side estimates (bytes); bench gate supersedes
    "act_linear_bytes_per_unit": 20.0,  # bf16 activations ~20 B per (B*S*h) per layer
    "attn_scores_bytes": 2.0,           # bf16 S^2 scores+probs term (no flash on c03)
    "muon_state_bytes": 4.0,            # fp32 momentum on 2D params
    "adamw_state_bytes": 8.0,           # fp32 m+v on emb/norm params
}

def params(h, d, V, tied=True):
    core = 12 * h * h * d            # attn 4h^2 + mlp 8h^2 per layer
    emb = V * h * (1 if tied else 2)
    return core, emb, core + emb

def flop_per_tok(core, emb, mode):
    # fwd 2P + bwd 4P; ckpt adds ~one extra fwd over core only
    base = 6 * (core + emb)
    return base + (2 * core if mode == "ckpt" else 0)

def static_gib(core, emb):
    c = CONSTANTS
    w_g = 4.0 * (core + emb)                      # bf16 weights + grads
    opt = c["muon_state_bytes"] * core + c["adamw_state_bytes"] * emb
    return (w_g + opt) / 2**30

def act_gib(h, d, B, heads, flash=False):
    c = CONSTANTS; S = c["S"]
    linear = c["act_linear_bytes_per_unit"] * B * S * h * d
    attn = 0.0 if flash else c["attn_scores_bytes"] * B * heads * S * S * d * 2
    return (linear + attn) / 2**30

def knee_batch(h, d, heads, core, emb, flash, mode):
    c = CONSTANTS
    budget = c["gov_cap_gib"] - c["margin_gib"] - static_gib(core, emb)
    if mode == "ckpt":  # checkpointing stores ~1 boundary act per layer
        per_b = (2.0 * c["S"] * h * d) / 2**30
        b = int(budget / per_b) if per_b > 0 else 0
        return min(b, 48)
    for B in range(48, 0, -1):
        if act_gib(h, d, B, heads, flash) <= budget:
            return B
    return 0

def sustained_flops():
    c = CONSTANTS
    core, emb, _ = params(**c["c03"] | {} ) if False else params(c["c03"]["h"], c["c03"]["d"], c["V"])
    return c["anchor_tok_s_compiled"] * flop_per_tok(core, emb, c["anchor_mode"])

def grid(flash=False):
    c = CONSTANTS
    F = sustained_flops()
    rows = []
    for h in (1024, 2048, 2304, 2560):
        for d in ((20,) if h == 1024 else (12, 14, 16)):
            heads = h // 64
            core, emb, P = params(h, d, c["V"])
            for mode in ("nockpt", "ckpt"):
                B = knee_batch(h, d, heads, core, emb, flash, mode)
                if B < 4:
                    continue
                ft = flop_per_tok(core, emb, mode)
                tok_s = F / ft
                rows.append({
                    "h": h, "d": d, "params_m": round(P / 1e6, 1), "mode": mode,
                    "flash": flash, "B_knee": B,
                    "flop_per_tok_g": round(ft / 1e9, 2),
                    "proj_tok_s": round(tok_s),
                    "tokens_per_governed_day_b": round(tok_s * c["governed_day_s"] / 1e9, 2),
                    "days_for_7b_budget": round(7e9 / (tok_s * c["governed_day_s"]), 2),
                })
    return rows, F

def selftest():
    c = CONSTANTS
    core, emb, P = params(c["c03"]["h"], c["c03"]["d"], c["V"])
    assert abs(core - 251.66e6) / 251.66e6 < 0.01, core      # 12*1024^2*20
    assert abs(P - 284.4e6) / 284.4e6 < 0.01, P
    ft = flop_per_tok(core, emb, "ckpt")
    assert 2.1e9 < ft < 2.3e9, ft
    F = sustained_flops()
    assert 6.5e13 < F < 7.5e13, F                            # ~69 TFLOPS anchor
    # b16-nockpt OOM boundary reproduces (L5 cells, fp32-step-econ-213856Z):
    budget = c["gov_cap_gib"] - c["margin_gib"] - static_gib(core, emb)
    assert act_gib(1024, 20, 16, c["c03"]["heads"], flash=False) > budget
    # ...and the live run's B=4 no-ckpt config fits (it ran):
    assert act_gib(1024, 20, 4, c["c03"]["heads"], flash=False) < budget
    print("C04_GRID_SELFTEST_PASS  (c03 anchors: P=%.1fM, flop/tok=%.2fG, F=%.1fTFLOPS)"
          % (P / 1e6, ft / 1e9, F / 1e12))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--emit", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest(); return
    out = {"ticket": "FP-37", "ts": time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()),
           "issue": 352, "constants": CONSTANTS,
           "sustained_flops_anchor": sustained_flops()}
    for flash in (False, True):
        rows, _ = grid(flash)
        out["grid_flash" if flash else "grid_noflash"] = rows
    out["budget_equation"] = ("tokens_per_governed_day = 86400 * F_sustained / flop_per_tok; "
                              "the <=1-day gate binds (P, budget) JOINTLY")
    s = json.dumps(out, indent=1)
    print(s[:2000])
    if a.emit:
        p = "receipts/c04-grid-%s.json" % out["ts"]
        open(p, "w").write(s)
        print("RECEIPT:", p)

if __name__ == "__main__":
    main()
