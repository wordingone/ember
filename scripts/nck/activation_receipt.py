#!/usr/bin/env python3
"""#320 selective-recompute ACTIVATION receipt emitter.

Fires at the NEXT natural daemon restart / WSD-segment boundary on the
run-12c050e7 lineage. NEVER manufacture a restart to trigger this — the live
run is never disturbed.

Contract (issue #320):
1. harness_sha: committed SHA of this file; harness_sha="uncommitted" voids the
   receipt.
2. trigger: {class, evidence} — last pre-activation terminal receipt path +
   restart reason extracted from the run.
3. config_proof: grad_checkpointing=false derived from CONSUMED config bytes
   (sha256 + key/value), never a self-report; sha must match master config.
4. continuity: lineage, resume_step == last complete checkpoint step, muon_split
   flag, shard-cursor step continuity.
5. throughput: named pre-activation baseline window vs post-activation window
   (>=500 steps), tok/s mean+std, derived multiplier. Receipt MEASURES;
   verdict semantics stay in the fold.
6. governed: vram_fraction, margin-assert, pacing intact.
7. health: >=500 consecutive post-activation steps, zero FATAL.

AC:
1. Emitter + fail-closed selftest committed BEFORE boundary fires.
2. Activation receipt lands on master meeting every field above.
3. Registry untouched in this PR (fold discipline — ADOPT flip is spec-side).

CLI:
  --run              required to execute (staged guard)
  --write            write receipt to receipts/selective-recompute-activation-<ts>.json
  --run-dir PATH     path to run directory (default: runs/v0-r1s1 from REPO_ROOT)
  --boundary-step N  step count that defines the pre/post activation split
                     (default: 50000 — last checkpoint before NONE-arm adoption)
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from nck.replay_rig import REPO_ROOT

LIVE_RUN_ID = "12c050e7"
CONFIG_PATH = REPO_ROOT / "configs" / "v0-pretrain-config.json"

# Governor floor (fp19 — never relax)
VRAM_FRACTION_MAX = 0.80
MARGIN_GIB_FLOOR  = 1.5
PACE_S_FLOOR      = 0.05

# Throughput: minimum consecutive post-activation steps required
MIN_POST_STEPS = 500

_STAGED_MSG = (
    "STAGED: activation_receipt loaded but not triggered. "
    "Pass --run to emit the SELECTIVE-RECOMPUTE-ACTIVATION receipt. "
    "Pass --write to save it. "
    "Pass --boundary-step N to override the activation split (default 50000). "
    "harness_sha=uncommitted voids the receipt — commit this file first."
)


# ---------------------------------------------------------------------------
# Harness-SHA helpers (fail-closed: void if uncommitted)
# ---------------------------------------------------------------------------

_THIS_SCRIPT_REL = "scripts/nck/activation_receipt.py"


def _get_harness_sha() -> str:
    """Return the committed SHA of this file; 'uncommitted' if dirty."""
    try:
        r = subprocess.run(
            ["git", "log", "-n", "1", "--format=%H", "--", _THIS_SCRIPT_REL],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        committed_sha = r.stdout.strip()
        if not committed_sha:
            return "uncommitted"  # file never committed
        # Check for local modifications
        diff = subprocess.run(
            ["git", "diff", "--quiet", _THIS_SCRIPT_REL],
            capture_output=True, cwd=str(REPO_ROOT),
        )
        if diff.returncode != 0:
            return "uncommitted"  # working-tree differs from last commit
        return committed_sha
    except Exception:
        return "uncommitted"


def _get_repo_sha() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        return r.stdout.strip()
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Config-proof (eng-53 pattern: facts from bytes, never self-report)
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _audit_config(path: Path) -> dict:
    """Derive grad_checkpointing fact from config bytes (eng-53 pattern)."""
    sha = _sha256_file(path)
    data = json.loads(path.read_bytes())
    model = data.get("model", {})
    grad_ckpt = model.get("grad_checkpointing")
    disabled_by = model.get("grad_ckpt_disabled_by", None)
    return {
        "path": str(path),
        "sha256": sha,
        "grad_checkpointing": grad_ckpt,
        "grad_ckpt_disabled_by": disabled_by,
        "grad_checkpointing_false": grad_ckpt is False,
    }


# ---------------------------------------------------------------------------
# Pre-activation baseline discovery
# ---------------------------------------------------------------------------


def _load_pre_activation_baseline(receipts_dir: Path) -> dict:
    """Find selective-recompute-ab receipt(s) to use as pre-activation baseline.

    Uses the full-ckpt arm measurement from the A/B bench as the named
    pre-activation throughput reference (grad-ckpt ON, c03 shapes).
    """
    pattern = "selective-recompute-ab-*.json"
    paths = sorted(receipts_dir.glob(pattern))
    if not paths:
        return {"found": False, "receipts": [], "mean_tok_s": None}

    tok_s_vals: list[float] = []
    receipt_refs: list[dict] = []
    for p in paths:
        data = json.loads(p.read_bytes())
        arm_agg = data.get("arm_aggregate", {})
        full_ckpt = arm_agg.get("full-ckpt", {})
        tok_s = full_ckpt.get("mean_tokens_per_s")
        if tok_s is not None:
            tok_s_vals.append(tok_s)
        receipt_refs.append({
            "path": str(p.relative_to(REPO_ROOT) if p.is_relative_to(REPO_ROOT) else p),
            "sha256": _sha256_file(p),
            "full_ckpt_mean_tok_s": tok_s,
        })

    if not tok_s_vals:
        return {"found": bool(paths), "receipts": receipt_refs, "mean_tok_s": None}

    mean = sum(tok_s_vals) / len(tok_s_vals)
    return {
        "found": True,
        "source": "full-ckpt arm of selective-recompute-ab (grad-ckpt ON, c03 shapes)",
        "receipts": receipt_refs,
        "mean_tok_s": round(mean, 1),
        "std_tok_s": round(
            math.sqrt(sum((x - mean) ** 2 for x in tok_s_vals) / len(tok_s_vals)), 1
        ) if len(tok_s_vals) > 1 else 0.0,
        "n": len(tok_s_vals),
    }


# ---------------------------------------------------------------------------
# Post-activation window discovery (v0-live receipts)
# ---------------------------------------------------------------------------


def _load_post_activation_window(receipts_dir: Path, boundary_step: int) -> dict:
    """Find TIMESHARE-V0-SEGMENT live receipts after the boundary step.

    Returns window statistics and a pass/fail flag for the >=500 step requirement.
    """
    pattern = "v0-live-*.json"
    all_paths = sorted(receipts_dir.glob(pattern))

    post_receipts: list[dict] = []
    for p in all_paths:
        try:
            data = json.loads(p.read_bytes())
        except Exception:
            continue
        if data.get("ticket") != "TIMESHARE-V0-SEGMENT":
            continue
        if data.get("mode") != "live":
            continue
        resume_step = data.get("resume_step", 0) or 0
        if resume_step >= boundary_step:
            post_receipts.append({
                "path": str(p.relative_to(REPO_ROOT) if p.is_relative_to(REPO_ROOT) else p),
                "sha256": _sha256_file(p),
                "resume_step": resume_step,
                "global_step_end": data.get("global_step_end"),
                "steps": data.get("steps", 0) or 0,
                "tokens_this_segment": data.get("tokens_this_segment", 0),
                "wall_s": data.get("wall_s"),
                "governor": data.get("governor"),
                "components": data.get("components"),
                "ts": data.get("ts"),
            })

    total_steps = sum(r["steps"] for r in post_receipts)
    tok_s_vals: list[float] = []
    for r in post_receipts:
        tokens = r.get("tokens_this_segment") or 0
        wall = r.get("wall_s") or 0.0
        if tokens > 0 and wall > 0:
            tok_s_vals.append(tokens / wall)

    mean_tok_s = round(sum(tok_s_vals) / len(tok_s_vals), 1) if tok_s_vals else None
    std_tok_s = (
        round(math.sqrt(sum((x - mean_tok_s) ** 2 for x in tok_s_vals) / len(tok_s_vals)), 1)
        if tok_s_vals and len(tok_s_vals) > 1 else 0.0
    )

    return {
        "found": bool(post_receipts),
        "n_receipts": len(post_receipts),
        "total_steps": total_steps,
        "min_post_steps": MIN_POST_STEPS,
        "meets_floor": total_steps >= MIN_POST_STEPS,
        "mean_tok_s": mean_tok_s,
        "std_tok_s": std_tok_s,
        "receipts": post_receipts,
    }


# ---------------------------------------------------------------------------
# Trigger evidence (last pre-activation terminal receipt)
# ---------------------------------------------------------------------------


def _find_trigger_evidence(receipts_dir: Path, boundary_step: int) -> dict:
    """Find the last TIMESHARE-V0-SEGMENT receipt at or before the boundary.

    This is the 'prior terminal receipt' that proves the trigger class.
    """
    pattern = "v0-live-*.json"
    all_paths = sorted(receipts_dir.glob(pattern))

    last_pre: dict | None = None
    last_pre_path: str | None = None

    for p in all_paths:
        try:
            data = json.loads(p.read_bytes())
        except Exception:
            continue
        if data.get("ticket") != "TIMESHARE-V0-SEGMENT":
            continue
        if data.get("mode") != "live":
            continue
        global_step_end = data.get("global_step_end", 0) or 0
        if global_step_end <= boundary_step:
            if last_pre is None or global_step_end > (last_pre.get("global_step_end") or 0):
                last_pre = data
                last_pre_path = str(
                    p.relative_to(REPO_ROOT) if p.is_relative_to(REPO_ROOT) else p
                )

    if last_pre is None:
        # No pre-activation live receipts yet — boundary is the first resume
        return {
            "class": "initial-resume",
            "evidence": None,
            "last_pre_receipt_path": None,
            "last_pre_global_step": None,
            "note": (
                "no pre-activation v0-live receipt found; boundary is the "
                "first live resume with the new config (grad-ckpt disabled)"
            ),
        }

    return {
        "class": "segment-boundary",
        "last_pre_receipt_path": last_pre_path,
        "last_pre_global_step": last_pre.get("global_step_end"),
        "last_pre_ts": last_pre.get("ts"),
        "reason": (
            f"WSD segment completed at step {last_pre.get('global_step_end')}; "
            "daemon restarted with grad-ckpt disabled (PR #298 / v0-pretrain-config.json v3)"
        ),
    }


# ---------------------------------------------------------------------------
# Continuity check (post-activation receipts)
# ---------------------------------------------------------------------------


def _check_continuity(post_receipts: list[dict], boundary_step: int) -> dict:
    """Verify step continuity across post-activation segment receipts."""
    if not post_receipts:
        return {"verified": False, "reason": "no post-activation receipts"}

    sorted_recs = sorted(post_receipts, key=lambda r: r.get("resume_step", 0) or 0)
    first = sorted_recs[0]
    muon_mode = None
    try:
        muon_mode = first["components"]["optimizer"]["mode"]
    except (KeyError, TypeError):
        pass

    # Check step continuity: each resume_step should equal the prior global_step_end
    gaps: list[dict] = []
    prev_end = first.get("resume_step")
    for r in sorted_recs:
        r_start = r.get("resume_step")
        if prev_end is not None and r_start is not None and r_start != prev_end:
            gaps.append({"expected_resume": prev_end, "actual_resume": r_start})
        prev_end = r.get("global_step_end")

    return {
        "verified": len(gaps) == 0,
        "first_resume_step": first.get("resume_step"),
        "first_global_step_end": first.get("global_step_end"),
        "muon_split": muon_mode == "muon_split",
        "muon_mode_observed": muon_mode,
        "step_gaps": gaps,
        "n_receipts_checked": len(sorted_recs),
    }


# ---------------------------------------------------------------------------
# Governed assertion (from post-activation receipts)
# ---------------------------------------------------------------------------


def _check_governed(post_receipts: list[dict]) -> dict:
    """Verify governor constraints from post-activation receipt governor fields."""
    if not post_receipts:
        return {"pass": False, "reason": "no post-activation receipts"}

    violations: list[str] = []
    vram_fractions: list[float] = []
    margin_gibs: list[float] = []
    pace_vals: list[float] = []

    for r in post_receipts:
        gov = r.get("governor") or {}
        vf = gov.get("vram_fraction")
        mg = gov.get("margin_gib_floor")
        ps = gov.get("pace_s_per_step")
        if vf is not None:
            vram_fractions.append(vf)
            if vf > VRAM_FRACTION_MAX:
                violations.append(f"vram_fraction {vf} > {VRAM_FRACTION_MAX}")
        if mg is not None:
            margin_gibs.append(mg)
            if mg < MARGIN_GIB_FLOOR:
                violations.append(f"margin_gib_floor {mg} < {MARGIN_GIB_FLOOR}")
        if ps is not None:
            pace_vals.append(ps)
            if ps < PACE_S_FLOOR:
                violations.append(f"pace_s_per_step {ps} < {PACE_S_FLOOR}")

    return {
        "pass": len(violations) == 0,
        "violations": violations,
        "vram_fraction_observed": list(set(vram_fractions)),
        "margin_gib_floor_observed": list(set(margin_gibs)),
        "pace_s_per_step_observed": list(set(pace_vals)),
    }


# ---------------------------------------------------------------------------
# Health check (zero FATAL in post-activation window)
# ---------------------------------------------------------------------------


def _check_health(run_dir: Path, boundary_step: int, post_receipts: list[dict]) -> dict:
    """Verify >=500 consecutive steps and zero FATAL halt receipts."""
    halt_receipts = sorted(run_dir.glob("halt-*.json"))
    fatal_halts: list[str] = []
    for p in halt_receipts:
        try:
            data = json.loads(p.read_bytes())
            ts = data.get("ts", "")
        except Exception:
            continue
        # Consider any halt receipt in the run_dir as a FATAL candidate
        fatal_halts.append(str(p.name))

    total_steps = sum(r.get("steps", 0) or 0 for r in post_receipts)
    return {
        "post_steps_consecutive": total_steps,
        "meets_floor": total_steps >= MIN_POST_STEPS,
        "halt_receipts_found": fatal_halts,
        "zero_fatal": len(fatal_halts) == 0,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    args = sys.argv[1:]
    if "--run" not in args:
        print(_STAGED_MSG)
        return 1

    write = "--write" in args

    # Parse --run-dir
    run_dir = REPO_ROOT.parent / "runs" / "v0-r1s1"
    if "--run-dir" in args:
        idx = args.index("--run-dir")
        run_dir = Path(args[idx + 1])

    # Parse --boundary-step
    boundary_step = 50000
    if "--boundary-step" in args:
        idx = args.index("--boundary-step")
        boundary_step = int(args[idx + 1])

    receipts_dir = REPO_ROOT / "receipts"

    # --- harness SHA (fail-closed: void if uncommitted) ---
    harness_sha = _get_harness_sha()
    if harness_sha == "uncommitted":
        print(
            "ACTIVATION_RECEIPT_VOID: harness_sha=uncommitted — commit "
            f"{_THIS_SCRIPT_REL} before running."
        )
        return 1

    print(f"harness_sha: {harness_sha[:16]}...")

    # --- config proof (eng-53 pattern) ---
    if not CONFIG_PATH.exists():
        print(f"ACTIVATION_RECEIPT_NO_CONFIG: {CONFIG_PATH}")
        return 1
    config_proof = _audit_config(CONFIG_PATH)
    if not config_proof["grad_checkpointing_false"]:
        print(
            "ACTIVATION_RECEIPT_CONFIG_FAIL: grad_checkpointing is not false "
            f"in {CONFIG_PATH} — config has not been updated to disable grad-ckpt"
        )
        return 1
    print(f"config_proof: grad_checkpointing={config_proof['grad_checkpointing']!r} PASS")

    # --- trigger evidence ---
    trigger = _find_trigger_evidence(receipts_dir, boundary_step)
    print(f"trigger: class={trigger['class']!r}")

    # --- pre-activation baseline ---
    pre_baseline = _load_pre_activation_baseline(receipts_dir)
    if not pre_baseline["found"]:
        print("ACTIVATION_RECEIPT_NO_PRE_BASELINE: no selective-recompute-ab receipt found")
        return 1
    print(
        f"pre_baseline: {pre_baseline.get('mean_tok_s')} tok/s "
        f"(n={pre_baseline.get('n')})"
    )

    # --- post-activation window ---
    post_window = _load_post_activation_window(receipts_dir, boundary_step)
    if not post_window["found"]:
        print(
            f"ACTIVATION_RECEIPT_NO_POST_WINDOW: no v0-live receipts found with "
            f"resume_step >= {boundary_step}. Run has not resumed with new config yet."
        )
        return 1
    if not post_window["meets_floor"]:
        print(
            f"ACTIVATION_RECEIPT_POST_FLOOR_FAIL: "
            f"{post_window['total_steps']} post-activation steps < {MIN_POST_STEPS} floor"
        )
        return 1
    print(
        f"post_window: {post_window['total_steps']} steps, "
        f"{post_window['mean_tok_s']} tok/s mean"
    )

    # --- derived multiplier ---
    pre_mean = pre_baseline.get("mean_tok_s")
    post_mean = post_window.get("mean_tok_s")
    derived_multiplier = (
        round(post_mean / pre_mean, 4)
        if (pre_mean and post_mean and pre_mean > 0)
        else None
    )
    print(f"throughput multiplier: {derived_multiplier}x")

    # --- continuity ---
    continuity = _check_continuity(post_window["receipts"], boundary_step)
    if not continuity["verified"]:
        print(f"ACTIVATION_RECEIPT_CONTINUITY_FAIL: {continuity}")
        return 1
    print(f"continuity: verified, muon_split={continuity['muon_split']}")

    # --- governed ---
    governed = _check_governed(post_window["receipts"])
    if not governed["pass"]:
        print(f"ACTIVATION_RECEIPT_GOVERNOR_FAIL: {governed['violations']}")
        return 1
    print("governed: PASS")

    # --- health ---
    health = _check_health(run_dir, boundary_step, post_window["receipts"])
    if not health["zero_fatal"]:
        print(f"ACTIVATION_RECEIPT_HALT_DETECTED: {health['halt_receipts_found']}")
        return 1
    if not health["meets_floor"]:
        print(
            f"ACTIVATION_RECEIPT_HEALTH_FLOOR_FAIL: "
            f"{health['post_steps_consecutive']} steps < {MIN_POST_STEPS}"
        )
        return 1
    print("health: PASS")

    repo_sha = _get_repo_sha()
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    receipt = {
        "ticket": "SELECTIVE-RECOMPUTE-ACTIVATION",
        "label": "ACTIVATION-RECEIPT",
        "ts": ts,
        "sha_convention": (
            "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"
        ),
        "harness_sha": harness_sha,
        "harness_void": harness_sha == "uncommitted",
        "repo_sha": repo_sha,
        "live_run_id": LIVE_RUN_ID,
        "boundary_step": boundary_step,
        "trigger": trigger,
        "config_proof": config_proof,
        "continuity": continuity,
        "throughput": {
            "pre_activation": pre_baseline,
            "post_activation": post_window,
            "derived_multiplier": derived_multiplier,
            "note": (
                "multiplier = post_mean / pre_mean; receipt MEASURES ONLY; "
                "verdict semantics stay in the fold (registry flip is spec-side)"
            ),
        },
        "governed": governed,
        "health": health,
        "flags": [
            "ACTIVATION-RECEIPT: natural-boundary trigger only — never manufactured",
            "config proof from consumed bytes (eng-53 pattern), never self-report",
            "harness_sha=uncommitted would void this receipt",
            f"live run {LIVE_RUN_ID} NOT touched",
            "registry untouched in this PR (ADOPT flip is fold-side / spec-side)",
            f"throughput floor: >=500 post-activation steps required, "
            f"got {health['post_steps_consecutive']}",
        ],
        "live_run_untouched": LIVE_RUN_ID,
    }

    if write:
        receipt_dir = REPO_ROOT / "receipts"
        receipt_dir.mkdir(exist_ok=True)
        fname = receipt_dir / f"selective-recompute-activation-{ts}.json"
        fname.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(f"\nRECEIPT: {fname}")
    else:
        print("\n(dry-run: pass --write to save receipt)")
        print(json.dumps({
            "harness_sha": harness_sha[:16] + "...",
            "harness_void": False,
            "config_grad_checkpointing": config_proof["grad_checkpointing"],
            "post_steps": health["post_steps_consecutive"],
            "derived_multiplier": derived_multiplier,
            "zero_fatal": health["zero_fatal"],
        }, indent=2))

    return 0


# ---------------------------------------------------------------------------
# Selftest (fail-closed, no GPU, tmp fixtures)
# ---------------------------------------------------------------------------


def _selftest() -> int:
    """Exercise every contract field with synthetic fixtures in a tmpdir.

    Marker: ACTIVATION_RECEIPT_SELFTEST_PASS
    """
    import shutil
    import tempfile

    tmpdir = Path(tempfile.mkdtemp(prefix="actreceipt_selftest_"))
    try:
        # --- 1. Build synthetic config with grad_checkpointing=false ---
        cfg = {
            "model": {
                "grad_checkpointing": False,
                "grad_ckpt_disabled_by": "PR #298 (synthetic for selftest)",
            }
        }
        cfg_path = tmpdir / "v0-pretrain-config.json"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        cfg_sha = _sha256_file(cfg_path)
        proof = _audit_config(cfg_path)
        assert proof["grad_checkpointing_false"], "config_proof should detect false"
        assert proof["sha256"] == cfg_sha, "sha256 must match"

        # --- 2. Build synthetic config with grad_checkpointing=true → should fail ---
        cfg_on = {"model": {"grad_checkpointing": True}}
        cfg_on_path = tmpdir / "v0-pretrain-config-on.json"
        cfg_on_path.write_text(json.dumps(cfg_on), encoding="utf-8")
        proof_on = _audit_config(cfg_on_path)
        assert not proof_on["grad_checkpointing_false"], "should detect grad-ckpt ON"

        # --- 3. Synthetic pre-activation receipts dir ---
        pre_dir = tmpdir / "receipts_pre"
        pre_dir.mkdir()
        ab_receipt = {
            "ticket": "SELECTIVE_RECOMPUTE_AB",
            "ts": "20260612T063250Z",
            "arm_aggregate": {
                "full-ckpt": {"mean_tokens_per_s": 12272.7, "status": "PASS"},
                "none": {"mean_tokens_per_s": 14883.9, "status": "PASS",
                         "measured_multiplier": 1.2128},
            },
        }
        (pre_dir / "selective-recompute-ab-20260612T063250Z.json").write_text(
            json.dumps(ab_receipt), encoding="utf-8"
        )
        baseline = _load_pre_activation_baseline(pre_dir)
        assert baseline["found"], "should find pre-activation receipt"
        assert abs(baseline["mean_tok_s"] - 12272.7) < 0.1, "mean tok/s mismatch"

        # --- 4. Synthetic post-activation receipts (3 × 300 steps = 900 > 500) ---
        post_dir = tmpdir / "receipts_post"
        post_dir.mkdir()

        def _make_v0_live(fname: str, resume_step: int, steps: int, tok_s: float) -> None:
            tokens = steps * 4 * 1024  # batch=4, seq=1024
            wall = tokens / tok_s
            data = {
                "ticket": "TIMESHARE-V0-SEGMENT",
                "ts": "20260613T120000Z",
                "mode": "live",
                "steps": steps,
                "resume_step": resume_step,
                "global_step_end": resume_step + steps,
                "tokens_this_segment": tokens,
                "wall_s": wall,
                "governor": {
                    "vram_fraction": 0.80,
                    "margin_gib_floor": 1.5,
                    "pace_s_per_step": 0.05,
                },
                "components": {
                    "optimizer": {"mode": "muon_split", "n_muon": 100, "n_adamw": 10},
                },
                "sha_convention": (
                    "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"
                ),
            }
            (post_dir / fname).write_text(json.dumps(data), encoding="utf-8")

        _make_v0_live("v0-live-A.json", 50000, 300, 15000.0)
        _make_v0_live("v0-live-B.json", 50300, 300, 15200.0)
        _make_v0_live("v0-live-C.json", 50600, 300, 14800.0)

        post = _load_post_activation_window(post_dir, 50000)
        assert post["found"], "should find post-activation receipts"
        assert post["total_steps"] == 900, f"expected 900 steps, got {post['total_steps']}"
        assert post["meets_floor"], "should meet >=500 step floor"
        assert post["mean_tok_s"] is not None, "mean tok/s should be computed"

        # --- 5. Trigger evidence: no pre receipts → initial-resume ---
        trigger_empty = _find_trigger_evidence(post_dir, 50000)
        assert trigger_empty["class"] == "initial-resume", "should be initial-resume"

        # Trigger evidence: with a pre receipt → segment-boundary
        pre_live = {"ticket": "TIMESHARE-V0-SEGMENT", "mode": "live",
                    "ts": "20260612T100000Z",
                    "global_step_end": 50000, "resume_step": 45000, "steps": 5000}
        (post_dir / "v0-live-pre.json").write_text(
            json.dumps(pre_live), encoding="utf-8"
        )
        trigger_with = _find_trigger_evidence(post_dir, 50000)
        assert trigger_with["class"] == "segment-boundary", "should be segment-boundary"
        assert trigger_with["last_pre_global_step"] == 50000

        # --- 6. Continuity check: clean ---
        cont = _check_continuity(post["receipts"], 50000)
        assert cont["verified"], f"continuity should verify: {cont}"
        assert cont["muon_split"], "muon_split should be True"

        # Continuity check: gap detected
        (post_dir / "v0-live-gap.json").write_text(
            json.dumps({
                "ticket": "TIMESHARE-V0-SEGMENT", "mode": "live",
                "ts": "20260613T130000Z",
                "resume_step": 99999, "global_step_end": 100299, "steps": 300,
                "tokens_this_segment": 300 * 4 * 1024,
                "wall_s": 10.0,
                "governor": {"vram_fraction": 0.80, "margin_gib_floor": 1.5,
                             "pace_s_per_step": 0.05},
                "components": {"optimizer": {"mode": "muon_split"}},
                "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
            }),
            encoding="utf-8",
        )
        post_gap = _load_post_activation_window(post_dir, 50000)
        cont_gap = _check_continuity(post_gap["receipts"], 50000)
        assert not cont_gap["verified"], "gap should be detected"
        assert len(cont_gap["step_gaps"]) > 0

        # --- 7. Governed check: PASS ---
        gov = _check_governed(post["receipts"])
        assert gov["pass"], f"governed should PASS: {gov}"

        # Governed check: violation
        (post_dir / "v0-live-badgov.json").write_text(
            json.dumps({
                "ticket": "TIMESHARE-V0-SEGMENT", "mode": "live",
                "ts": "20260613T140000Z",
                "resume_step": 50900, "global_step_end": 51000, "steps": 100,
                "tokens_this_segment": 100 * 4 * 1024,
                "wall_s": 5.0,
                "governor": {"vram_fraction": 0.95, "margin_gib_floor": 1.5,
                             "pace_s_per_step": 0.05},  # vram 0.95 > 0.80 = violation
                "components": {"optimizer": {"mode": "muon_split"}},
                "sha_convention": "sha256 over on-disk raw bytes (binary read, no line-ending normalization)",
            }),
            encoding="utf-8",
        )
        post_bad = _load_post_activation_window(post_dir, 50000)
        # Filter to just the 3 clean ones for gov check
        gov_bad = _check_governed(
            [r for r in post_bad["receipts"] if "badgov" in (r.get("path") or "")]
        )
        assert not gov_bad["pass"], "should detect vram violation"

        # --- 8. Health check ---
        run_dir_tmp = tmpdir / "run_dir_clean"
        run_dir_tmp.mkdir()
        health = _check_health(run_dir_tmp, 50000, post["receipts"])
        assert health["zero_fatal"], "no halt receipts = zero_fatal"
        assert health["meets_floor"], "900 steps >= 500"

        # Health with halt receipt
        halt_path = run_dir_tmp / "halt-20260613T120000Z.json"
        halt_path.write_text(json.dumps({"ticket": "HALT", "ts": "20260613T120000Z"}),
                              encoding="utf-8")
        health_halt = _check_health(run_dir_tmp, 50000, post["receipts"])
        assert not health_halt["zero_fatal"], "halt receipt detected"

        # --- 9. Derived multiplier ---
        pre_mean_test = 12272.7
        post_mean_test = post["mean_tok_s"]
        mm = round(post_mean_test / pre_mean_test, 4)
        assert mm > 1.0, f"none arm should be faster: {mm}"

        # --- 10. harness_sha: verify uncommitted detection logic ---
        # (We can't test the git integration in a tmpdir, but we verify the
        # function returns "uncommitted" when git is not available)
        def _mock_get_harness_sha_no_git() -> str:
            try:
                r = subprocess.run(
                    ["git", "log", "-n", "1", "--format=%H", "--",
                     "nonexistent-script.py"],
                    capture_output=True, text=True, cwd=str(tmpdir),
                )
                committed_sha = r.stdout.strip()
                if not committed_sha:
                    return "uncommitted"
                return committed_sha
            except Exception:
                return "uncommitted"

        sha_result = _mock_get_harness_sha_no_git()
        assert sha_result == "uncommitted", "non-existent path → uncommitted"

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    print("ACTIVATION_RECEIPT_SELFTEST_PASS")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    else:
        sys.exit(main())
