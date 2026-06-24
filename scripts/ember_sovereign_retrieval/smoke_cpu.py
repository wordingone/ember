"""
CPU smoke test for Ember Sovereign Retrieval.
Exercises all four configs end-to-end with tiny t.
Asserts mass-recall is computed and finite.
Must pass under WSL python3 (CPU-only).
"""

import sys
import math
import os

# Ensure imports work from this dir
sys.path.insert(0, os.path.dirname(__file__))

import torch
import torch.nn.functional as F

from ivf_pq import IVFPQ
from harness import (
    make_key_stream,
    make_value_stream,
    make_drifted_keys,
    full_sdpa,
    softmax_weights,
    compute_mass_recall,
    associative_recall_task,
    exact_copy_task,
    needle_task,
    attention_entropy,
    fit_loglog_slope,
    Timer,
    D, M_PQ,
)

# Smoke parameters
T_SMOKE = [64, 256, 1024]
K_SMOKE = 16
W_SMOKE = 32
N_STEPS_SMOKE = 10
N_WARMUP_SMOKE = 3

DEVICE = torch.device("cpu")
DTYPE = torch.float32


def run_smoke():
    print("=== Ember Sovereign Retrieval CPU Smoke ===")
    print(f"d={D} m={M_PQ} t_checkpoints={T_SMOKE} top_k={K_SMOKE} W={W_SMOKE}")
    sys.stdout.flush()

    t_max_smoke = max(T_SMOKE)
    keys_all = make_key_stream(t_max_smoke, D, DEVICE, DTYPE, seed=1)
    vals_all = make_value_stream(t_max_smoke, D, DEVICE, DTYPE, seed=2)
    drifted_keys_all = make_drifted_keys(keys_all, rot_angle=0.15, noise_std=0.05)

    results = []

    for t_chk in T_SMOKE:
        t = t_chk
        keys_t = keys_all[:t]
        vals_t = vals_all[:t]

        torch.manual_seed(t_chk + 1)
        query = F.normalize(torch.randn(D, dtype=DTYPE), dim=-1)

        needle_idx = t // 4
        early_idx = min(10, t - 1)

        print(f"\n--- t={t} ---")

        # ----------------------------------------------------------------
        # Config A: full SDPA
        timer_A = Timer(use_cuda=False)
        times_A = []
        for step in range(N_WARMUP_SMOKE + N_STEPS_SMOKE):
            timer_A.start()
            out_A = full_sdpa(query, keys_t, vals_t)
            elapsed = timer_A.stop_ms()
            if step >= N_WARMUP_SMOKE:
                times_A.append(elapsed)

        assert out_A.shape == (D,), f"A output shape mismatch: {out_A.shape}"
        assert torch.all(torch.isfinite(out_A)), "A output has non-finite values"
        import statistics as stats_mod
        median_A = stats_mod.median(times_A)
        print(f"  [A] median={median_A:.3f}ms  shape={out_A.shape}  finite=True")

        # Oracle weights
        w_oracle = softmax_weights(query, keys_t)
        ent = attention_entropy(w_oracle)
        assert math.isfinite(ent), "attention entropy not finite"

        # ----------------------------------------------------------------
        # Config B: IVF-PQ + window
        idx_B = IVFPQ(D, m=M_PQ, device=DEVICE, dtype=DTYPE)
        for i in range(t):
            idx_B.insert(keys_t[i], vals_t[i])

        new_keys = make_key_stream(N_WARMUP_SMOKE + N_STEPS_SMOKE, D, DEVICE, DTYPE, seed=t_chk + 10)
        new_vals = make_value_stream(N_WARMUP_SMOKE + N_STEPS_SMOKE, D, DEVICE, DTYPE, seed=t_chk + 11)

        timer_B = Timer(use_cuda=False)
        times_B = []
        for step in range(N_WARMUP_SMOKE + N_STEPS_SMOKE):
            nk = new_keys[step]
            nv = new_vals[step]
            timer_B.start()
            if idx_B.t > 0:
                ret_vals_B, _ = idx_B.query(query, top_k=K_SMOKE)
            idx_B.insert(nk, nv)
            elapsed = timer_B.stop_ms()
            if step >= N_WARMUP_SMOKE:
                times_B.append(elapsed)

        median_B = stats_mod.median(times_B)

        # Recall
        ret_vals_B, _ = idx_B.query(query, top_k=K_SMOKE)
        assert ret_vals_B.shape[0] > 0, "B retrieved nothing"
        assert torch.all(torch.isfinite(ret_vals_B)), "B retrieved non-finite values"

        # Get retrieved indices
        if ret_vals_B.shape[0] > 0:
            sims = (keys_t.float() @ ret_vals_B.float().T)
            retrieved_idx_B = sims.argmax(dim=0)
        else:
            retrieved_idx_B = torch.empty(0, dtype=torch.long)

        mass_recall_B = compute_mass_recall(query, keys_t, retrieved_idx_B)
        assert math.isfinite(mass_recall_B), f"mass_recall_B not finite: {mass_recall_B}"
        assert 0.0 <= mass_recall_B <= 1.0, f"mass_recall_B out of [0,1]: {mass_recall_B}"

        # Drift recall
        drifted_keys_t = drifted_keys_all[:t]
        query_drifted = make_drifted_keys(query.unsqueeze(0), rot_angle=0.15, noise_std=0.05)[0]
        ret_vals_B_drift, _ = idx_B.query(query_drifted, top_k=K_SMOKE)
        if ret_vals_B_drift.shape[0] > 0:
            sims_d = (drifted_keys_t.float() @ ret_vals_B_drift.float().T)
            retrieved_idx_B_drift = sims_d.argmax(dim=0)
        else:
            retrieved_idx_B_drift = torch.empty(0, dtype=torch.long)
        mass_recall_B_drift = compute_mass_recall(query_drifted, drifted_keys_t, retrieved_idx_B_drift)
        assert math.isfinite(mass_recall_B_drift), "drift mass recall not finite"
        assert 0.0 <= mass_recall_B_drift <= 1.0, "drift mass recall out of range"

        print(f"  [B] median={median_B:.3f}ms  mass_recall={mass_recall_B:.4f}  drift={mass_recall_B_drift:.4f}")

        # ----------------------------------------------------------------
        # Config C: pure retrieval W=0
        idx_C = IVFPQ(D, m=M_PQ, device=DEVICE, dtype=DTYPE)
        for i in range(t):
            idx_C.insert(keys_t[i], vals_t[i])

        timer_C = Timer(use_cuda=False)
        times_C = []
        for step in range(N_WARMUP_SMOKE + N_STEPS_SMOKE):
            nk = new_keys[step]
            nv = new_vals[step]
            timer_C.start()
            if idx_C.t > 0:
                _, _ = idx_C.query(query, top_k=K_SMOKE)
            idx_C.insert(nk, nv)
            elapsed = timer_C.stop_ms()
            if step >= N_WARMUP_SMOKE:
                times_C.append(elapsed)

        median_C = stats_mod.median(times_C)
        ret_vals_C, _ = idx_C.query(query, top_k=K_SMOKE)
        assert torch.all(torch.isfinite(ret_vals_C)), "C retrieved non-finite values"
        print(f"  [C] median={median_C:.3f}ms  n_retrieved={ret_vals_C.shape[0]}")

        # ----------------------------------------------------------------
        # Config D: frozen index (no insert in clock)
        idx_D = IVFPQ(D, m=M_PQ, device=DEVICE, dtype=DTYPE)
        for i in range(t):
            idx_D.insert(keys_t[i], vals_t[i])

        timer_D = Timer(use_cuda=False)
        times_D = []
        for step in range(N_WARMUP_SMOKE + N_STEPS_SMOKE):
            timer_D.start()
            if idx_D.t > 0:
                ret_vals_D, _ = idx_D.query(query, top_k=K_SMOKE)
            elapsed = timer_D.stop_ms()
            if step >= N_WARMUP_SMOKE:
                times_D.append(elapsed)

        median_D = stats_mod.median(times_D)
        assert torch.all(torch.isfinite(ret_vals_D)), "D retrieved non-finite values"

        if ret_vals_D.shape[0] > 0:
            sims = (keys_t.float() @ ret_vals_D.float().T)
            retrieved_idx_D = sims.argmax(dim=0)
        else:
            retrieved_idx_D = torch.empty(0, dtype=torch.long)
        mass_recall_D = compute_mass_recall(query, keys_t, retrieved_idx_D)
        assert math.isfinite(mass_recall_D), "D mass recall not finite"
        print(f"  [D] median={median_D:.3f}ms  mass_recall={mass_recall_D:.4f}")

        # ----------------------------------------------------------------
        # Recall tasks
        assoc = associative_recall_task(query, keys_t, vals_t, ret_vals_B, retrieved_idx_B)
        copy = exact_copy_task(keys_t[early_idx], keys_t, retrieved_idx_B, early_idx)
        needle = needle_task(keys_t[needle_idx], keys_t, retrieved_idx_B, needle_idx)
        print(f"  [tasks] assoc={assoc:.2f} copy={copy:.2f} needle={needle:.2f} entropy={ent:.3f}")

        results.append({
            "t": t,
            "median_A": median_A,
            "median_B": median_B,
            "median_C": median_C,
            "median_D": median_D,
            "mass_recall_B": mass_recall_B,
            "mass_recall_B_drift": mass_recall_B_drift,
            "mass_recall_D": mass_recall_D,
        })

    # ----------------------------------------------------------------
    # Log-log slope
    ts = [r["t"] for r in results]
    ms_B = [r["median_B"] for r in results]
    slope_B = fit_loglog_slope(ts, ms_B)
    assert math.isfinite(slope_B), f"slope_B not finite: {slope_B}"

    ms_D = [r["median_D"] for r in results]
    slope_D = fit_loglog_slope(ts, ms_D)
    assert math.isfinite(slope_D), f"slope_D not finite: {slope_D}"

    insert_costs = [max(r["median_B"] - r["median_D"], 1e-9) for r in results]
    slope_insert = fit_loglog_slope(ts, insert_costs)

    print(f"\n[smoke] log-log slope B={slope_B:.4f}  D={slope_D:.4f}  insert-term={slope_insert:.4f}")

    # Final assertions
    for r in results:
        assert math.isfinite(r["mass_recall_B"]), "mass_recall_B not finite in final check"
        assert math.isfinite(r["mass_recall_B_drift"]), "mass_recall_B_drift not finite in final check"

    print("\n=== SMOKE PASSED ===")
    sys.stdout.flush()
    return True


if __name__ == "__main__":
    ok = run_smoke()
    sys.exit(0 if ok else 1)
