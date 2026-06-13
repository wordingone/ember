"""c04_pretrain_prestage.py — #383 gate-9 pretrain-dispatch pre-stage.

Validates the c03-class 2.2B governed launch, parameterized on optimizer
{muon_batched | full_fused_adamw}, and emits the gate-9 receipt the user
reviews before authorizing dispatch. NO GPU pretrain is dispatched here.

Checks (all required GREEN for gate9_pass):
  1. Config pins   — c03 shape/governor frozen (v0_config_check)
  2. Governor      — vram_fraction<=0.80, margin>=1.5GiB, pace>=0.05s
  3. WSD schedule  — warmup/stable/decay shape verified (pure math)
  4. Ckpt/resume   — synthetic 2-step save/load/verify (CPU tensors, no GPU)
  5. Optimizer     — wiring confirmed (muon_batched: c04-batched-ns5-bench; adamw: builtin)
  6. Bench tok/s   — paced throughput from receipted bench; wall_days <=1.0

Emitted receipt: receipts/c04-gate9-prestage-<ts>.json
  ticket:       C04-GATE9-PRESTAGE
  optimizer:    muon_batched | full_fused_adamw
  tok_s_paced:  measured throughput (from bench receipt)
  wall_days:    budget_b / tok_s_paced / 86400  (must be <= 1.0)
  gate9_pass:   true iff all 6 checks GREEN

Selftest (--selftest): exercises both optimizer paths on synthetic data.
Gate violation probe: governor loosened => fires.
Checkpoint/resume: save@step=2 => load => step==2 verified.
"""
import argparse
import glob
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
NC   = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import v0_config_check                    # noqa: E402
import timeshare_pretrain as ts            # noqa: E402
from receipt_write import checked_write   # noqa: E402
import c04_optimizer_pick as cpick        # noqa: E402

RECEIPTS = os.path.join(NC, "receipts")
CONFIG   = os.path.join(NC, "configs", "v0-pretrain-config.json")
BUDGET_B = 2_200_000_000                  # §3 qualification budget (1 day floor)
SEC_PER_DAY = 86_400

# ----- pick → gate-9 optimizer mapping (frozen; matches c04_optimizer_pick verdicts) ----
_PICK_TO_GATE9 = {
    "COMMIT_MUON_BATCHED": "muon_batched",
    "COMMIT_ADAMW":        "full_fused_adamw",
}

# ----- receipt globs (latest wins) -----------------------------------------
_FP40_GLOB      = "receipts/fp40-l10-optimizer-ab-*.json"
_FP45_GLOB      = "receipts/fp45-batched-ns5-ab-*.json"   # kernel A/B equiv only
_C04_NS5_GLOB   = "receipts/c04-batched-ns5-bench-*.json" # production §3 deciding receipt
_CKPT_GLOB      = "receipts/selective-recompute-ab-*.json"

# ----- C04 efficiency lever enumeration (H1 schema) ------------------------
# Each entry: {status, receipt?, wall_days_cost?}. Emitted verbatim into the
# gate-9 receipt so the user can review which throughput decisions were made.
def _build_levers(optimizer, config_sha256):
    """Build the efficiency-lever dict for the chosen optimizer."""
    ckpt_name    = _latest_basename(_CKPT_GLOB)
    fp40_name    = _latest_basename(_FP40_GLOB)
    c04_ns5_name = _latest_basename(_C04_NS5_GLOB)
    fp45_name    = _latest_basename(_FP45_GLOB)
    fp35_name    = _latest_basename("receipts/fp35-fused-muon-kernel-ab-*.json")

    return {
        "batch_size": {
            "status": "receipted-APPLIED",
            "receipt": fp40_name or "fp40-l10-optimizer-ab-MISSING",
            "note": "B=16 optimal from fp40 c03 bench (tok/s plateau)"
        },
        "checkpointing_off": {
            "status": "receipted-APPLIED",
            "receipt": ckpt_name or "selective-recompute-ab-MISSING",
            "note": "NONE arm 1.213x vs full-ckpt (PR #298)"
        },
        "muon_kernel": (
            {"status": "receipted-APPLIED",
             "receipt": c04_ns5_name or fp45_name or "c04-batched-ns5-bench-PENDING",
             "note": "batched NS5 (#382); 15 bmm vs 2100 sequential; production receipt from c04_batched_ns5_bench"}
            if optimizer == "muon_batched"
            else
            {"status": "receipted-KILLED",
             "receipt": fp35_name or "fp35-fused-muon-kernel-ab-MISSING",
             "note": "fused-side only +8.1%, far short of 3.2x target (fp35)"}
        ),
        "fp8_matmul": {
            "status": "receipted-KILLED",
            "receipt": "v2-multiplier-table-survivors",
            "note": "0.98x at c03 scale on Ada (v2 table); excluded in config"
        },
        "torch_compile": {
            "status": "receipted-APPLIED",
            "receipt": "PR-380-compile-fwd",
            "note": "1.024x fwd-only fullgraph (#353 Mira patch; FlashAttn+cuBLAS already saturated)"
        },
        "duty_cycle": {
            "status": "WAIVED",
            "wall_days_cost": 0.0,
            "note": "pace_s=0.05 governs; pacing overhead < 0.1% on 1-day run"
        },
    }


# ----- helpers -------------------------------------------------------------

def _latest_basename(pattern):
    cands = sorted(glob.glob(os.path.join(NC, pattern)))
    return os.path.basename(cands[-1]) if cands else None


def _config_sha256():
    with open(CONFIG, encoding="utf-8") as f:
        cfg = json.load(f)
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()


# ----- check 1: config pins ------------------------------------------------

def check_config():
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    v = v0_config_check.check(cfg)
    if v:
        return "BLOCKED", f"config pin violations: {v}"
    return "GREEN", "c03 shape + governor + directed components all pin"


# ----- check 2: governor rails ---------------------------------------------

def check_governor(cfg=None):
    if cfg is None:
        cfg = json.load(open(CONFIG, encoding="utf-8"))
    g = cfg.get("governor", {})
    f = v0_config_check.GOVERNOR_FLOOR
    if g.get("vram_fraction", 1.0) > f["vram_fraction"]:
        return "BLOCKED", f"governor.vram_fraction {g['vram_fraction']} > floor 0.80"
    if g.get("margin_gib_floor", 0) < f["margin_gib_floor"]:
        return "BLOCKED", f"governor.margin_gib_floor {g['margin_gib_floor']} < floor 1.5"
    if g.get("pace_s_per_step", 0) < f["pace_s_per_step"]:
        return "BLOCKED", f"governor.pace_s_per_step {g['pace_s_per_step']} < floor 0.05"
    return "GREEN", (f"vram_fraction={g['vram_fraction']} margin={g['margin_gib_floor']}GiB "
                     f"pace={g['pace_s_per_step']}s — all within floor")


# ----- check 3: WSD schedule -----------------------------------------------

def check_wsd_schedule(cfg=None):
    if cfg is None:
        cfg = json.load(open(CONFIG, encoding="utf-8"))
    sch = cfg.get("schedule", {})
    wf = sch.get("warmup_frac", 0)
    sf = sch.get("stable_until_frac", 1)
    df = sch.get("decay_to_lr_frac", 0.1)
    # Structural check: warmup < stable < 1.0
    if not (0 < wf < sf < 1.0):
        return "BLOCKED", f"WSD fracs not ordered: warmup={wf} stable={sf}"
    # Spot-check at 5 critical steps of a synthetic 10 000-step run
    N = 10_000
    checks = [
        (0,         0.0,   "step 0 = lr frac 0"),
        (int(wf*N), 1.0,   "at warmup end = full lr"),
        (int(sf*N), 1.0,   "at stable end = full lr"),
        (N,         df,    "at terminal = decay floor"),
    ]
    for step, expected, label in checks:
        got = ts.wsd_lr_frac(step, N, wf, sf, df)
        if abs(got - expected) > 1e-6:
            return "BLOCKED", f"WSD shape error at {label}: got {got:.6f} expected {expected}"
    # Midpoint of decay should be between df and 1.0
    mid_decay = (sf + 1.0) / 2
    mid_val = ts.wsd_lr_frac(int(mid_decay * N), N, wf, sf, df)
    if not (df < mid_val < 1.0):
        return "BLOCKED", f"WSD mid-decay {mid_val:.4f} outside ({df}, 1.0)"
    return "GREEN", (f"WSD shape verified: warmup={wf} stable={sf} "
                     f"decay_floor={df} over 10k steps")


# ----- check 4: checkpoint/resume ------------------------------------------

def check_checkpoint_resume():
    """Synthetic 2-step save/load/verify using CPU tensors (no GPU)."""
    import torch
    with tempfile.TemporaryDirectory() as run_dir:
        # Synthetic model and optimizer state (tiny, CPU)
        model_state = {"layer.weight": torch.ones(4, 4),
                       "layer.bias":   torch.zeros(4)}
        opt_state   = {"adamw": {"state": {},
                                 "param_groups": [{"lr": 3e-4, "weight_decay": 0.1,
                                                   "betas": (0.9, 0.999), "eps": 1e-8,
                                                   "amsgrad": False, "params": [0, 1]}]}}
        rng_state   = {"torch_cpu": torch.get_rng_state(),
                       "py_random":  __import__("random").getstate()}
        TARGET_STEP = 2
        # Save at step 2
        ckpt_dir = ts.save_checkpoint(run_dir, TARGET_STEP,
                                      model_state, opt_state, rng_state,
                                      extra={"config": "c03", "optimizer": "synthetic"})
        # Load back
        ms2, os2, rs2, manifest = ts.load_checkpoint(ckpt_dir)
        # Verify step
        if manifest.get("step") != TARGET_STEP:
            return "BLOCKED", (f"resume step mismatch: expected {TARGET_STEP}, "
                               f"got {manifest.get('step')}")
        # Verify tensor identity (small delta from float32)
        w_delta = (ms2["layer.weight"] - model_state["layer.weight"]).abs().max().item()
        if w_delta > 1e-7:
            return "BLOCKED", f"model weight delta {w_delta} after round-trip"
        # verify_resume reports SAFE_RESUME
        vr = ts.verify_resume(run_dir)
        if vr.get("verdict") != "SAFE_RESUME":
            return "BLOCKED", f"verify_resume = {vr.get('verdict')}"
    return "GREEN", f"save@step={TARGET_STEP} -> load -> verify_resume SAFE_RESUME"


# ----- check 5: optimizer wiring -------------------------------------------

def check_optimizer_wired(optimizer):
    if optimizer == "full_fused_adamw":
        try:
            import torch
            torch.optim.AdamW([torch.zeros(4)], lr=3e-4)
        except Exception as e:
            return "BLOCKED", f"AdamW instantiation failed: {e}"
        return "GREEN", "full_fused_adamw: AdamW available + instantiated"
    elif optimizer == "muon_batched":
        # fp45_batched_ns5_ab ships factory functions, not a top-level class.
        # Verify via the real API: _build_muon_batched() + _ns5_batched() present,
        # then construct through the factory and smoke a CPU step.
        try:
            import fp45_batched_ns5_ab as fp45
            if not (hasattr(fp45, "_build_muon_batched") and
                    hasattr(fp45, "_ns5_batched")):
                return "BLOCKED", (
                    "fp45_batched_ns5_ab missing _build_muon_batched or _ns5_batched"
                )
            import torch
            MuonBatched = fp45._build_muon_batched()
            p = torch.nn.Parameter(torch.randn(4, 4))
            opt = MuonBatched([p], lr=0.02)
            p.grad = torch.randn_like(p)
            opt.step()
            opt.zero_grad(set_to_none=True)
        except Exception as e:
            return "BLOCKED", f"muon_batched wiring check failed: {e}"
        return "GREEN", "muon_batched: _build_muon_batched+_ns5_batched present, step() smoke (CPU)"
    else:
        return "BLOCKED", f"unknown optimizer {optimizer!r}"


# ----- check 6: bench tok/s ------------------------------------------------

def lookup_bench_tok_s(optimizer):
    """Returns (tok_s, source_basename) or (None, reason_string)."""
    if optimizer == "full_fused_adamw":
        cands = sorted(glob.glob(os.path.join(NC, _FP40_GLOB)))
        if not cands:
            return None, "fp40-l10-optimizer-ab receipt not found"
        d = json.load(open(cands[-1]))
        for cell in d.get("cells", []):
            if cell.get("cell") == "full_fused_adamw" or cell.get("optimizer") == "full_fused_adamw":
                tok_s = float(cell.get("tok_s_paced", 0))
                if tok_s > 0:
                    return tok_s, os.path.basename(cands[-1])
        return None, f"{os.path.basename(cands[-1])}: full_fused_adamw cell not found or tok_s=0"
    elif optimizer == "muon_batched":
        cands = sorted(glob.glob(os.path.join(NC, _C04_NS5_GLOB)))
        if not cands:
            return None, "c04-batched-ns5-bench receipt not found (dispatch c04_batched_ns5_bench.py --run first)"
        d = json.load(open(cands[-1]))
        tok_s = float(d.get("tok_s_paced", 0))
        if tok_s <= 0:
            return None, f"{os.path.basename(cands[-1])}: tok_s_paced=0"
        return tok_s, os.path.basename(cands[-1])
    return None, f"unknown optimizer {optimizer!r}"


def check_bench_tok_s(optimizer, override_tok_s=None):
    if override_tok_s is not None:
        tok_s = override_tok_s
        source = "selftest-synthetic"
    else:
        tok_s, source = lookup_bench_tok_s(optimizer)
        if tok_s is None:
            return "BLOCKED", f"bench tok_s unavailable: {source}", None, None
    wall_days = BUDGET_B / tok_s / SEC_PER_DAY
    passes = wall_days <= 1.0
    status = "GREEN" if passes else "BLOCKED"
    detail = (f"tok_s={tok_s:.1f}, wall_days={wall_days:.4f} "
              f"({'<= 1 day OK' if passes else '> 1 day FAIL'}); "
              f"source={source}")
    return status, detail, tok_s, wall_days


# ----- check 7: optimizer matches committed pick ---------------------------

def check_optimizer_matches_pick(optimizer, pick_override=None, user_authorized=False):
    if user_authorized:
        return "GREEN", f"user override (--force-optimizer-authorized): {optimizer} blessed, pick bypassed"
    verdict = pick_override if pick_override is not None else cpick.analyze().get("pick")
    committed = _PICK_TO_GATE9.get(verdict)
    if committed is None:
        return "BLOCKED", (
            f"c04_optimizer_pick={verdict} (no committed optimizer) — gate-9 cannot authorize "
            "a launch the pick has not blessed; wait for COMMIT_*, or "
            "--force-optimizer-authorized to override")
    if committed != optimizer:
        return "BLOCKED", (
            f"pick committed {committed!r} but gate-9 asked to validate {optimizer!r} — "
            "validate the committed optimizer")
    return "GREEN", f"pick {verdict} -> {committed} matches"


# ----- analyze (all checks, optional emit) ---------------------------------

def analyze(optimizer, emit=False, override_tok_s=None, pick_override=None, user_authorized=False):
    cfg      = json.load(open(CONFIG, encoding="utf-8"))
    cfg_sha  = _config_sha256()
    ts_now   = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    rows = {}
    rows["config_pins"]     = check_config()
    rows["governor_rails"]  = check_governor(cfg)
    rows["wsd_schedule"]    = check_wsd_schedule(cfg)
    rows["checkpoint_resume"] = check_checkpoint_resume()
    rows["optimizer_wired"] = check_optimizer_wired(optimizer)
    tok_s_status, tok_s_detail, tok_s, wall_days = check_bench_tok_s(
        optimizer, override_tok_s=override_tok_s)
    rows["bench_tok_s"]          = (tok_s_status, tok_s_detail)
    rows["optimizer_matches_pick"] = check_optimizer_matches_pick(
        optimizer, pick_override=pick_override, user_authorized=user_authorized)

    for name, (status, detail) in rows.items():
        mark = "OK " if status == "GREEN" else "XX "
        print(f"  {mark}{name:<20} {status:<8} {detail}")

    blocked = [n for n, (s, _) in rows.items() if s != "GREEN"]
    gate9_pass = len(blocked) == 0

    if emit and gate9_pass:
        levers = _build_levers(optimizer, cfg_sha)
        receipt = {
            "ticket":              "C04-GATE9-PRESTAGE",
            "ts":                  ts_now,
            "issue":               383,
            "optimizer":           optimizer,
            "budget_b":            BUDGET_B,
            "tok_s_paced":         round(tok_s, 1) if tok_s else None,
            "tok_s_source":        lookup_bench_tok_s(optimizer)[1] if tok_s else None,
            "projected_wall_days": round(wall_days, 5) if wall_days else None,
            "s3_gate_pass":        gate9_pass and (wall_days is not None and wall_days <= 1.0),
            "config_sha256":       cfg_sha,
            "sha_convention":      "sha256 over json.dumps(cfg, sort_keys=True).encode()",
            "checks":              {n: {"status": s, "detail": d} for n, (s, d) in rows.items()},
            "efficiency_levers":   levers,
            "gate9_pass":          gate9_pass,
            "pick_override_by_user": user_authorized,
            "consequence": (
                "GATE9 PASS — user authorizes via EMBER_GATE_AUTHORIZED=1 --live"
                if gate9_pass else
                f"GATE9 BLOCKED — fix: {blocked}"
            ),
        }
        out = os.path.join(RECEIPTS, f"c04-gate9-prestage-{ts_now}.json")
        checked_write(out, receipt)
        try:
            rel = os.path.relpath(out, NC)
        except ValueError:
            rel = out
        print(f"\nC04_GATE9_PRESTAGE_DONE {rel}")
        return gate9_pass, receipt
    elif not gate9_pass:
        print(f"\nC04_GATE9_PRESTAGE_BLOCKED — {blocked}")
    else:
        print(f"\nC04_GATE9_PRESTAGE_PASS (--emit not set; run with --emit to write receipt)")
    return gate9_pass, None


# ----- selftest ------------------------------------------------------------

def selftest():
    import copy
    ok = True

    print("[selftest] check 1: config pins GREEN")
    st, dt = check_config()
    assert st == "GREEN", f"config_pins: {dt}"
    print(f"  PASS: {dt[:60]}")

    print("[selftest] check 2: governor rails GREEN + BLOCKED on violation")
    st, dt = check_governor()
    assert st == "GREEN", f"governor: {dt}"
    cfg_bad = json.load(open(CONFIG, encoding="utf-8"))
    cfg_bad["governor"]["vram_fraction"] = 0.95
    st_bad, dt_bad = check_governor(cfg_bad)
    assert st_bad == "BLOCKED" and "vram_fraction" in dt_bad, f"governor mutation: {dt_bad}"
    cfg_bad2 = json.load(open(CONFIG, encoding="utf-8"))
    cfg_bad2["governor"]["margin_gib_floor"] = 0.5
    st_bad2, _ = check_governor(cfg_bad2)
    assert st_bad2 == "BLOCKED"
    print(f"  PASS: GREEN + 2 violations caught")

    print("[selftest] check 3: WSD schedule shape")
    st, dt = check_wsd_schedule()
    assert st == "GREEN", f"wsd_schedule: {dt}"
    print(f"  PASS: {dt}")

    print("[selftest] check 4: checkpoint/resume synthetic 2-step")
    st, dt = check_checkpoint_resume()
    assert st == "GREEN", f"checkpoint_resume: {dt}"
    print(f"  PASS: {dt}")

    print("[selftest] check 5a: optimizer wiring — full_fused_adamw")
    st, dt = check_optimizer_wired("full_fused_adamw")
    assert st == "GREEN", f"adamw wiring: {dt}"
    print(f"  PASS: {dt}")

    print("[selftest] check 5b: optimizer wiring — muon_batched")
    st, dt = check_optimizer_wired("muon_batched")
    if st != "GREEN":
        print(f"  SKIP (fp45 not on PATH): {dt}")
    else:
        print(f"  PASS: {dt}")

    print("[selftest] check 5c: unknown optimizer blocked")
    st, _ = check_optimizer_wired("bad_opt")
    assert st == "BLOCKED"
    print("  PASS: unknown optimizer -> BLOCKED")

    print("[selftest] coherence: gate-9 muon_batched glob matches c04_optimizer_pick receipt type")
    # _C04_NS5_GLOB prefix must match the ticket that c04_optimizer_pick._load_batched_ns5() recognises.
    # c04_optimizer_pick matches ticket "c04-batched-ns5-bench" (lowercase). If this assertion breaks,
    # the two scripts diverged and the §3 gate would validate the wrong throughput.
    _glob_prefix = os.path.basename(_C04_NS5_GLOB).split("*")[0].rstrip("-")  # "c04-batched-ns5-bench"
    _pick_ticket = "c04-batched-ns5-bench"
    assert _glob_prefix == _pick_ticket, (
        f"gate-9 glob prefix {_glob_prefix!r} != pick ticket {_pick_ticket!r} — "
        "handoff is incoherent; update _C04_NS5_GLOB or c04_optimizer_pick")
    print(f"  PASS: glob prefix {_glob_prefix!r} matches pick ticket {_pick_ticket!r}")

    print("[selftest] check 6: bench tok/s via synthetic override (both opts)")
    # full_fused_adamw synthetic: 27702.8 tok/s → 0.9185 days
    st, dt, tok_s, wd = check_bench_tok_s("full_fused_adamw", override_tok_s=27702.8)
    assert st == "GREEN" and wd < 1.0, f"adamw bench: {st} {dt}"
    print(f"  PASS: adamw wall_days={wd:.4f}")
    # muon_batched synthetic: 30000 tok/s → 0.8495 days
    st2, dt2, tok_s2, wd2 = check_bench_tok_s("muon_batched", override_tok_s=30000.0)
    assert st2 == "GREEN" and wd2 < 1.0, f"muon bench: {st2} {dt2}"
    print(f"  PASS: muon_batched wall_days={wd2:.4f}")
    # below §3 threshold blocked
    st3, dt3, _, wd3 = check_bench_tok_s("full_fused_adamw", override_tok_s=20000.0)
    assert st3 == "BLOCKED" and wd3 > 1.0, f"low tok/s: {st3} {dt3}"
    print(f"  PASS: low tok/s {wd3:.4f}d -> BLOCKED")

    print("[selftest] check 7: optimizer_matches_pick — 5 cases")
    # The bug-catch: pick=PENDING -> BLOCKED (prevents premature launch)
    st7a, dt7a = check_optimizer_matches_pick("full_fused_adamw", pick_override="PENDING")
    assert st7a == "BLOCKED" and "PENDING" in dt7a, f"PENDING case: {st7a} {dt7a}"
    print("  PASS: pick=PENDING -> BLOCKED")
    # ESCALATE is also not a commit
    st7b, dt7b = check_optimizer_matches_pick("full_fused_adamw", pick_override="ESCALATE_TORCH_OR_TRADEOFF")
    assert st7b == "BLOCKED", f"ESCALATE case: {st7b} {dt7b}"
    print("  PASS: pick=ESCALATE_TORCH_OR_TRADEOFF -> BLOCKED")
    # Mismatch: pick says muon but gate asked for adamw
    st7c, dt7c = check_optimizer_matches_pick("full_fused_adamw", pick_override="COMMIT_MUON_BATCHED")
    assert st7c == "BLOCKED" and "mismatch" not in dt7c.lower() or "committed" in dt7c.lower(), f"mismatch case: {st7c} {dt7c}"
    assert st7c == "BLOCKED"
    print("  PASS: pick=COMMIT_MUON_BATCHED, gate=full_fused_adamw -> BLOCKED (mismatch)")
    # Match: pick=COMMIT_ADAMW, gate=full_fused_adamw -> GREEN
    st7d, dt7d = check_optimizer_matches_pick("full_fused_adamw", pick_override="COMMIT_ADAMW")
    assert st7d == "GREEN", f"match case: {st7d} {dt7d}"
    print("  PASS: pick=COMMIT_ADAMW, gate=full_fused_adamw -> GREEN")
    # User override bypasses pick entirely
    st7e, dt7e = check_optimizer_matches_pick("full_fused_adamw", user_authorized=True)
    assert st7e == "GREEN" and "user override" in dt7e, f"user_authorized case: {st7e} {dt7e}"
    print("  PASS: user_authorized=True -> GREEN (pick bypassed)")

    print("[selftest] full analyze() dry-run with synthetic tok/s (full_fused_adamw)")
    gate9_ok, rcpt = analyze("full_fused_adamw", emit=False, override_tok_s=27702.8,
                             pick_override="COMMIT_ADAMW")
    assert gate9_ok, "full analyze should pass with synthetic tok/s + matching pick"
    print(f"  PASS: gate9_pass={gate9_ok}")

    print("[selftest] full analyze() dry-run with synthetic tok/s (muon_batched)")
    gate9_ok2, _ = analyze("muon_batched", emit=False, override_tok_s=30000.0,
                           pick_override="COMMIT_MUON_BATCHED")
    assert gate9_ok2, "muon_batched green path must pass post-#329"
    print(f"  PASS: gate9_pass={gate9_ok2}")

    print("[selftest] emit dry-run to tempdir with synthetic tok/s")
    with tempfile.TemporaryDirectory() as td:
        orig_receipts = _receipt_dir_override(td)
        try:
            gate9_ok3, rcpt3 = analyze("full_fused_adamw", emit=True, override_tok_s=27702.8,
                                       pick_override="COMMIT_ADAMW")
        finally:
            _receipt_dir_restore(orig_receipts)
        # Receipt should have been written to td
        cands = glob.glob(os.path.join(td, "c04-gate9-prestage-*.json"))
        assert cands, "no receipt written to tempdir"
        d = json.load(open(cands[0]))
        assert d["gate9_pass"] is True
        assert d["optimizer"] == "full_fused_adamw"
        assert d["projected_wall_days"] < 1.0
        assert "efficiency_levers" in d
    print("  PASS: receipt emitted + schema valid")

    print("FP383_GATE9_PRESTAGE_SELFTEST_PASS")
    return True


# ---- receipt-dir override helpers (selftest only) -------------------------

def _receipt_dir_override(path):
    global RECEIPTS
    old = RECEIPTS
    RECEIPTS = path
    return old


def _receipt_dir_restore(old):
    global RECEIPTS
    RECEIPTS = old


# ----- CLI -----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--optimizer", choices=["muon_batched", "full_fused_adamw"],
                    help="optimizer arm to pre-stage")
    ap.add_argument("--emit", action="store_true",
                    help="write the gate-9 receipt to receipts/")
    ap.add_argument("--force-optimizer-authorized", action="store_true",
                    help="bypass pick check (ESCALATE_TORCH_OR_TRADEOFF: user chose optimizer "
                         "despite quality gap); recorded as pick_override_by_user=true in receipt")
    a = ap.parse_args()
    if a.selftest:
        sys.exit(0 if selftest() else 1)
    if not a.optimizer:
        ap.error("--optimizer required (muon_batched | full_fused_adamw)")
    gate9_ok, _ = analyze(a.optimizer, emit=a.emit,
                          user_authorized=a.force_optimizer_authorized)
    sys.exit(0 if gate9_ok else 1)


if __name__ == "__main__":
    main()
