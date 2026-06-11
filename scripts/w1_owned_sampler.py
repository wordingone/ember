"""w1_owned_sampler.py — owned-core round-1 sampler economics (eng-57 / #230).

The borrowed-core round-1 loop (w1_humaneval.generate_chat) does WHOLE-BATCH
decode: streams are chunked into fixed batches and every slot in a chunk is held
until that chunk's longest stream finishes. Mean completion ran ~46-150 tok vs
max_new 512 (receipts/fp32-baselines-20260611T142515Z.json), so short streams
idle their slot waiting on a 512-token straggler. R6 names that waste
    slot_waste = 1 - mean(len) / max(len).

This module is the OWNED-CORE replacement's scheduler, designed model-free so its
economics are MEASURED, not hypothesized:

  * per-stream stop  — a stream frees its slot the step it emits EOS, not at the
                       chunk boundary;
  * batch refill     — a freed slot is backfilled from the queue the next step
                       (continuous / in-flight batching);
  * length buckets   — admission can group similar-length work (reported as a
                       sweep; the achievable, output-blind headline is FIFO).

WHY model-free is the right unit today (Leo, mail 14646/14648): the scheduler is
pure accounting over stream lengths — no GPU, no model. It is verifiable now and
off the #195 critical path. The live decode that turns lengths into tokens is the
round-1 seam (live_decode_contract below); the >=2x verified-episodes/gen-min
confirmation fires there.

fp-27 pins are CONTRACT, not mechanism (scripts/fp27_round1_prereg.py SAMPLING:
seed 31, k=8, 200 L1 + 56 L2, temp 0.8 / top_p 0.95 / max_new 512). This sampler
CITES them and never writes that file. The contract holds across the scheduling
change because the live seam gives each stream its OWN torch.Generator seeded
from (seed, stream_id): a stream's tokens are then invariant to which batch it
lands in or when it is admitted, so continuous batching produces the SAME
verified set as whole-batch decode. The model-free core proves the weaker, fully
checkable half of that invariance — per-stream EMITTED COUNT is invariant to
n_slots and admission order (T-invariance below).

Governor (AC5) is untouched: the live seam imports t1_probe.decode_pacer
(PACE_S / PACE_EVERY), t1_probe.THROTTLE_S, and the daemon VRAM fraction/margin
verbatim; none are redefined here, and the model-free core touches no GPU.
"""

import argparse
import hashlib
import json
import math
import os
import random
import sys
from collections import deque
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from receipt_write import checked_write  # noqa: E402

RECEIPTS = os.path.join(NC, "receipts")
SHA_CONVENTION = ("file shas = sha256 over the exact on-disk raw bytes, no "
                  "normalization")

# fp-27 frozen sampling pins — CONTRACT, mirrored for citation, never mutated.
# Source of truth is scripts/fp27_round1_prereg.py::SAMPLING; this module only
# reads these and refuses to own them.
FP27_PINS = {
    "seed": 31,
    "k": 8,
    "n_tasks_l1": 200,
    "n_tasks_l2": 56,
    "temperature": 0.8,
    "top_p": 0.95,
    "max_new_tokens": 512,
    "source": "scripts/fp27_round1_prereg.py::SAMPLING",
    "mutated_by_this_module": False,
}

# Governor (AC5) — reused unchanged at the live seam, never redefined here.
GOVERNOR = {
    "reused_unchanged": True,
    "decode_pace_source": "t1_probe.decode_pacer (PACE_S / PACE_EVERY)",
    "inter_wave_throttle": "t1_probe.THROTTLE_S (env EMBER_THROTTLE_S, default 0.6)",
    "vram": "EMBER_VRAM_FRACTION / EMBER_VRAM_MARGIN_GB (daemon env, governor.py)",
    "model_free_core_touches_gpu": False,
}

# Baseline verified-episodes/gen-min from the borrowed core (R6 baselines
# receipt). The owned core does not change the verified RATE (per-stream RNG =>
# identical outputs); it changes the gen WALL, so verified/gen-min scales with
# the wall speedup.
BASELINE_VERIFIED_PER_GEN_MIN = 38.9
BASELINE_SOURCE = "receipts/fp32-baselines-20260611T142515Z.json::rows.gen"
TWO_X = 2.0


# --------------------------------------------------------------------------
# Model-free scheduler core
# --------------------------------------------------------------------------

def whole_batch_decode(lengths, n_slots, max_new):
    """Naive baseline matching w1_humaneval.generate_chat.

    `lengths` are OUTPUT token counts per stream in ADMISSION order. They are
    chunked into fixed groups of n_slots; each chunk costs max(chunk) decode
    steps and holds all len(chunk) slots for the whole chunk (a short stream
    cannot release its slot early). The sort in generate_chat is on PROMPT
    length, which does not predict OUTPUT length, so within-chunk output
    variance — the straggler waste — is real and is what this models.
    """
    capped = [min(int(x), max_new) for x in lengths]
    wall = 0
    slot_steps = 0
    per_batch_waste = []
    for i in range(0, len(capped), n_slots):
        chunk = capped[i:i + n_slots]
        m = max(chunk)
        wall += m
        slot_steps += len(chunk) * m
        if m > 0:
            per_batch_waste.append(1.0 - (sum(chunk) / len(chunk)) / m)
    useful = sum(capped)
    waste = 1.0 - useful / slot_steps if slot_steps else 0.0
    return {
        "wall_steps": wall,
        "slot_steps": slot_steps,
        "useful_token_steps": useful,
        "slot_waste": round(waste, 6),
        "slot_waste_per_batch_mean": (
            round(sum(per_batch_waste) / len(per_batch_waste), 6)
            if per_batch_waste else 0.0),
        "n_batches": math.ceil(len(capped) / n_slots) if capped else 0,
    }


def continuous_batch_decode(lengths, n_slots, max_new, admission="fifo"):
    """Owned core: per-stream stop + batch refill + length-bucketed admission.

    Maintains <= n_slots active streams. Each decode step every active stream
    emits one token; a stream that reaches its target frees its slot that step,
    and the next step a queued stream backfills it. Returns the wall (decode
    steps), the per-step occupancy trace (R6's measurement surface), and the
    per-stream emitted count (the invariance check).

    admission:
      'fifo'   — queue order; OUTPUT-blind, same information the naive baseline
                 has. This is the ACHIEVABLE headline: it isolates the
                 per-stream-stop + refill win from any length foreknowledge.
      'oracle' — longest-first by TRUE output length. Unachievable pre-hoc
                 (output length is unknown at admission); reported only as an
                 UPPER BOUND on what a perfect prompt->output length predictor
                 could buy on top of refill.
    """
    capped = [min(int(x), max_new) for x in lengths]
    if admission == "oracle":
        order = sorted(range(len(capped)), key=lambda i: capped[i], reverse=True)
    else:
        order = list(range(len(capped)))
    q = deque(order)
    active = {}          # sid -> remaining tokens
    emitted = {}         # sid -> tokens emitted so far
    occ = []
    wall = 0
    while q or active:
        while len(active) < n_slots and q:        # batch refill
            sid = q.popleft()
            active[sid] = capped[sid]
            emitted.setdefault(sid, 0)
        if not active:
            break
        occ.append(len(active))
        finished = []
        for sid in active:                        # one decode step
            active[sid] -= 1
            emitted[sid] += 1
            if active[sid] <= 0:                  # per-stream stop
                finished.append(sid)
        for sid in finished:
            del active[sid]
        wall += 1
    useful = sum(capped)
    slot_steps_avail = n_slots * wall
    waste = 1.0 - useful / slot_steps_avail if slot_steps_avail else 0.0
    return {
        "wall_steps": wall,
        "slot_steps_available": slot_steps_avail,
        "useful_token_steps": useful,
        "slot_waste": round(waste, 6),
        "mean_occupancy": round(sum(occ) / len(occ), 4) if occ else 0.0,
        "min_occupancy": min(occ) if occ else 0,
        "max_occupancy": max(occ) if occ else 0,
        "admission": admission,
        "_emitted": emitted,
    }


def lower_bound_wall(lengths, n_slots, max_new):
    """Physical floor on owned-core wall: cannot beat the longest single stream
    (irreducible) nor pack Sum(len) into fewer than ceil(Sum/n_slots) steps."""
    capped = [min(int(x), max_new) for x in lengths]
    if not capped:
        return 0
    return max(max(capped), math.ceil(sum(capped) / n_slots))


def economics(lengths, n_slots, max_new):
    """Apples-to-apples, output-blind comparison: naive whole-batch vs owned
    FIFO continuous batching on the SAME stream order. Returns the two cost
    blocks, the oracle upper bound, and the wall speedup that drives the
    verified-episodes/gen-min projection."""
    naive = whole_batch_decode(lengths, n_slots, max_new)
    owned = continuous_batch_decode(lengths, n_slots, max_new, admission="fifo")
    oracle = continuous_batch_decode(lengths, n_slots, max_new, admission="oracle")
    speedup = (naive["wall_steps"] / owned["wall_steps"]
               if owned["wall_steps"] else 1.0)
    oracle_speedup = (naive["wall_steps"] / oracle["wall_steps"]
                      if oracle["wall_steps"] else 1.0)
    return naive, owned, oracle, round(speedup, 4), round(oracle_speedup, 4)


def synth_lengths(n, mean, cap, straggler_frac, seed):
    """Deterministic synthetic OUTPUT lengths calibrated to the baselines
    receipt: a `straggler_frac` tail pinned near `cap`, the rest short
    (exponential around `mean`). Uses random.Random(seed) — model-free,
    reproducible, no global RNG, no torch. Returned in generation order (the
    short/straggler mix is interleaved, i.e. OUTPUT-random — which is what a
    prompt-length sort yields)."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        if rng.random() < straggler_frac:
            out.append(min(cap, int(rng.uniform(0.85 * cap, cap))))
        else:
            v = int(rng.expovariate(1.0 / mean)) + 1
            out.append(min(cap, max(1, v)))
    return out


# --------------------------------------------------------------------------
# Live decode seam (round-1) — contract only; not executed in the model-free
# build. Documented so the round-1 leg implements against a fixed interface and
# the governor / pin wiring is unambiguous.
# --------------------------------------------------------------------------

def live_decode_contract():
    """Return the round-1 live-decode contract (no GPU work here).

    The live core runs the SAME scheduler (per-stream stop + refill) over a real
    model: each active slot is one row of a continuously-rebatched forward pass
    with a per-stream KV cache; a row that samples EOS frees its slot and the
    next queued prompt is prefilled into it. Reproducibility / fp-27 invariance
    is enforced by a per-stream torch.Generator seeded from
    (FP27_PINS['seed'], stream_id) so token VALUES — not just counts — are
    independent of batch composition and admission order. Governor is imported
    verbatim (GOVERNOR): decode_pacer cadence per step, THROTTLE_S between
    refill waves, daemon VRAM fraction/margin. The live >=2x verified-episodes/
    gen-min smoke (AC3) runs here and emits the confirm-or-kill receipt."""
    return {
        "scheduler": "continuous_batch_decode (this module)",
        "per_stream_rng": "torch.Generator(seed=(FP27_PINS.seed, stream_id))",
        "governor": GOVERNOR,
        "fires_at": "round-1 (off the #195 critical path; gated)",
        "smoke": "verified-episodes/gen-min >=2x vs whole-batch OR negative receipt",
    }


def _script_sha256():
    with open(os.path.abspath(__file__), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


# --------------------------------------------------------------------------
# Selftest — pure-logic scheduler invariants (no GPU, no model)
# --------------------------------------------------------------------------

def _selftest():
    fails = []
    MAXN = 512

    # T-conserve: owned core emits EXACTLY each stream's capped length; no token
    # is lost, duplicated, or invented. Busy slot-steps == useful == Sum(capped).
    L = [1, 1, 1, 7, 50, 200, 512, 3, 999]   # 999 exercises the max_new cap
    owned = continuous_batch_decode(L, n_slots=4, max_new=MAXN)
    capped = [min(x, MAXN) for x in L]
    if owned["useful_token_steps"] != sum(capped):
        fails.append(f"T-conserve useful {owned['useful_token_steps']} != {sum(capped)}")
    if sum(owned["_emitted"].values()) != sum(capped):
        fails.append("T-conserve Sum(emitted) != Sum(capped)")
    for sid, n in owned["_emitted"].items():
        if n != capped[sid]:
            fails.append(f"T-conserve stream {sid} emitted {n} != target {capped[sid]}")

    # T-sandwich: for any admission, the owned wall sits between the physical
    # floor and the naive wall (refill removes idle, never adds it).
    lb = lower_bound_wall(L, 4, MAXN)
    naive = whole_batch_decode(L, 4, MAXN)
    if not (lb <= owned["wall_steps"] <= naive["wall_steps"]):
        fails.append(f"T-sandwich {lb} <= {owned['wall_steps']} <= "
                     f"{naive['wall_steps']} violated")

    # T-stop-frees-slot: a long stream admitted early overlaps its tail with
    # short refills -> wall is straggler-bound, not serialized.
    L2 = [100] + [1] * 12            # straggler first (fifo admits it early)
    o2 = continuous_batch_decode(L2, n_slots=4, max_new=MAXN)
    if o2["wall_steps"] != 100:      # Sum=112, ceil/4=28, max=100 -> 100
        fails.append(f"T-stop-frees-slot wall {o2['wall_steps']} != 100")

    # T-invariance (fp-27 contract proxy): per-stream emitted count is invariant
    # to n_slots AND admission order. Scheduling never changes what a stream
    # produces — the model-free half of the per-stream-RNG output invariance.
    L3 = synth_lengths(64, mean=80, cap=MAXN, straggler_frac=0.12, seed=31)
    base = continuous_batch_decode(L3, 8, MAXN, "fifo")["_emitted"]
    for ns in (1, 4, 16, 64):
        for adm in ("fifo", "oracle"):
            e = continuous_batch_decode(L3, ns, MAXN, adm)["_emitted"]
            if e != base:
                fails.append(f"T-invariance emitted drift at n_slots={ns} adm={adm}")
                break

    # T-oracle-tight: with longest-first admission on a packable distribution,
    # owned wall hits the physical lower bound exactly.
    Lpack = [40] * 64
    op = continuous_batch_decode(Lpack, 8, MAXN, "oracle")
    if op["wall_steps"] != lower_bound_wall(Lpack, 8, MAXN):
        fails.append(f"T-oracle-tight wall {op['wall_steps']} != "
                     f"{lower_bound_wall(Lpack, 8, MAXN)}")

    # T-variance-win: on a high-variance OUTPUT-random distribution the
    # achievable FIFO owned core STRICTLY beats naive (the refill win is real,
    # not merely non-negative).
    Lv = synth_lengths(256, mean=70, cap=MAXN, straggler_frac=0.15, seed=31)
    _, ownv, _, spv, _ = economics(Lv, 8, MAXN)
    if spv <= 1.0:
        fails.append(f"T-variance-win speedup {spv} not > 1")

    # T-pins-immutable: the constant mirrors the prereg and is flagged not-owned;
    # nothing in this module opens the prereg file for write.
    if FP27_PINS["mutated_by_this_module"] is not False or FP27_PINS["seed"] != 31:
        fails.append("T-pins FP27_PINS drifted")

    if fails:
        for f in fails:
            print("SELFTEST_FAIL:", f)
        return 1
    print("W1_OWNED_SAMPLER_SELFTEST_PASS")
    return 0


# --------------------------------------------------------------------------
# Run — emit the economics receipt on a calibrated distribution
# --------------------------------------------------------------------------

def _run(args):
    lengths = synth_lengths(args.n_streams, args.mean, args.cap,
                            args.straggler_frac, args.seed_synth)
    naive, owned, oracle, speedup, oracle_speedup = economics(
        lengths, args.n_slots, args.cap)

    projected = round(BASELINE_VERIFIED_PER_GEN_MIN * speedup, 2)
    meets_2x = speedup >= TWO_X
    verdict = "PROJECTED-PASS" if meets_2x else "PROJECTED-NEGATIVE"

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "ENG-57-R6",
        "ts": ts,
        "issue": 230,
        "refs": [225, 205],
        "mode": "model-free-projection",
        "no_gpu": True,
        "sha_convention": SHA_CONVENTION,
        "script_sha256": _script_sha256(),
        "fp27_pins_cited": FP27_PINS,
        "governor": GOVERNOR,
        "distribution": {
            "calibrated_to": BASELINE_SOURCE,
            "n_streams": args.n_streams,
            "n_slots": args.n_slots,
            "mean_short_tok": args.mean,
            "cap_tok": args.cap,
            "straggler_frac": args.straggler_frac,
            "seed_synth": args.seed_synth,
            "observed_mean_len": round(sum(min(x, args.cap) for x in lengths)
                                       / len(lengths), 2),
            "observed_max_len": min(max(lengths), args.cap),
        },
        "naive_whole_batch": naive,
        "owned_continuous_fifo": {k: v for k, v in owned.items()
                                  if not k.startswith("_")},
        "owned_continuous_oracle_upper_bound": {
            k: v for k, v in oracle.items() if not k.startswith("_")},
        "projection": {
            "wall_speedup_fifo": speedup,
            "wall_speedup_oracle_upper_bound": oracle_speedup,
            "decode_dominated_assumption":
                "constant per-token tok/s (baselines: 18.7k paced); gen-wall "
                "dominates 9.78:1 over train (baselines rows.train)",
            "baseline_verified_per_gen_min": BASELINE_VERIFIED_PER_GEN_MIN,
            "projected_verified_per_gen_min_fifo": projected,
            "threshold": TWO_X,
            "meets_2x_projected": meets_2x,
            "verdict": verdict,
            "note": "model-free PROJECTION; the live >=2x-or-kill smoke fires "
                    "at round-1 (live_decode_contract).",
        },
        "live_seam": live_decode_contract(),
    }
    out = os.path.join(RECEIPTS, f"w1-owned-sampler-{ts}.json")
    checked_write(out, receipt)
    print(json.dumps({
        "naive_wall": naive["wall_steps"],
        "owned_fifo_wall": owned["wall_steps"],
        "oracle_wall": oracle["wall_steps"],
        "naive_slot_waste": naive["slot_waste"],
        "owned_fifo_slot_waste": owned["slot_waste"],
        "wall_speedup_fifo": speedup,
        "wall_speedup_oracle_ub": oracle_speedup,
        "projected_verified_per_gen_min": projected,
        "verdict": verdict,
    }, indent=2))
    print(f"receipt: {os.path.basename(out)}")
    print("W1_OWNED_SAMPLER_RUN_DONE")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--selftest", action="store_true",
                    help="pure-logic scheduler invariants; prints "
                         "W1_OWNED_SAMPLER_SELFTEST_PASS")
    ap.add_argument("--run", action="store_true",
                    help="emit the economics receipt on a calibrated distribution")
    ap.add_argument("--n-streams", type=int, default=256,
                    help="streams in the synthetic round (e.g. (200 L1+56 L2)*k "
                         "is the round-1 scale; default 256 keeps it cheap)")
    ap.add_argument("--n-slots", type=int, default=8,
                    help="concurrent decode slots (= borrowed-core batch size)")
    ap.add_argument("--mean", type=float, default=80.0,
                    help="mean short-completion length (baselines: ~46-150)")
    ap.add_argument("--cap", type=int, default=512, help="max_new (fp-27 pin)")
    ap.add_argument("--straggler-frac", type=float, default=0.12,
                    help="fraction of streams pinned near the cap")
    ap.add_argument("--seed-synth", type=int, default=31,
                    help="synthetic-length RNG seed (NOT the fp-27 sampling "
                         "seed; this only shapes the projection distribution)")
    args, _ = ap.parse_known_args()
    if args.selftest:
        sys.exit(_selftest())
    if args.run:
        sys.exit(_run(args))
    ap.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
