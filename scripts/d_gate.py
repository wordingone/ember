"""d_gate.py — D-gate: artifact quarantine falsifier (eng-32, issue #114).

Claim shape: "gain G on surface S is carried by artifact A."
If G survives A's deletion, G was never A's — contamination, env drift,
or harness leak. The gate is the goal's own falsifier, run every round.

Protocol (adapter class):
  Arms: {base, adapter, adapter-quarantined-rerun, adapter-restored}
  - base: no adapter (zero gain baseline)
  - adapter: normal eval with adapter loaded (measures gain_with)
  - adapter-quarantined-rerun: adapter file moved to state/quarantine/,
    unloaded, eval re-run; gain must collapse (measures gain_without)
  - adapter-restored: adapter moved back, reload, re-eval;
    gain must reproduce within CI

Quarantine: shutil.move (never deletes bytes). Byte-identity verified
via sha256 pre-move == post-restore hash. Fail-closed on mismatch.

Receipt: d-gate-<artifact>-<ts>.json with exact spec fields.

LAUNCH INTERLOCK: any real eval/train leg is gated behind
  EMBER_GATE_AUTHORIZED=1 (env) AND --live (flag).
Default invocation and --selftest run 100% CPU-only on synthetic fixtures.

Spec: research/persistence-gates-spec.md §D-gate (frozen 2026-06-11, #36).
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# receipt_write is in the same scripts/ dir; path inserted below at call site.
from receipt_write import checked_write

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
_QUARANTINE = _REPO / "state" / "quarantine"
_RECEIPTS = _REPO / "receipts"


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    """SHA-256 hex digest of file bytes at path. Fail-closed on missing."""
    if not path.is_file():
        raise FileNotFoundError(f"d_gate sha256: file not found: {path}")
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


SHA_CONVENTION = (
    "sha256 over raw file bytes in 65536-byte read chunks; "
    "hex-encoded lowercase; no header, no encoding, no metadata"
)


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _quarantine_move(artifact: Path) -> Path:
    """Move artifact to quarantine dir. Returns destination path."""
    ts = _utc_ts()
    dest_dir = _QUARANTINE / ts
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / artifact.name
    shutil.move(str(artifact), str(dest))
    return dest


def _restore_move(quarantine_path: Path, artifact: Path) -> None:
    """Move artifact back from quarantine to original path."""
    artifact.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(quarantine_path), str(artifact))


# ---------------------------------------------------------------------------
# Stats helpers (pure, no I/O)
# ---------------------------------------------------------------------------

def _bootstrap_ci(vec_a: list, vec_b: list, n_boot: int = 2000,
                  seed: int = 42, conf: float = 0.95) -> dict:
    """Paired delta bootstrap CI. Pure, no torch dependency."""
    import random
    rng = random.Random(seed)
    n = len(vec_a)
    diffs = [a - b for a, b in zip(vec_a, vec_b)]
    observed = sum(diffs) / n
    boot = []
    for _ in range(n_boot):
        sample = [diffs[rng.randrange(n)] for _ in range(n)]
        boot.append(sum(sample) / n)
    boot.sort()
    alpha = 1.0 - conf
    lo_idx = int(n_boot * alpha / 2)
    hi_idx = int(n_boot * (1 - alpha / 2))
    lo = boot[lo_idx]
    hi = boot[min(hi_idx, n_boot - 1)]
    return {"observed": round(observed, 6),
            "lo": round(lo, 6), "hi": round(hi, 6),
            "n_boot": n_boot, "conf": conf}


def _exact_paired_ci(vec_a: list, vec_b: list, conf: float = 0.95) -> dict:
    """Newcombe paired CI via stats_exact (BINDING). Returns dict."""
    # Import from same scripts/ dir — add parent if not already on path
    scripts_dir = str(_HERE)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from stats_exact import newcombe_paired_ci  # noqa: E402

    n = len(vec_a)
    b = sum(1 for a_, b_ in zip(vec_a, vec_b) if a_ and not b_)
    c = sum(1 for a_, b_ in zip(vec_a, vec_b) if b_ and not a_)
    lo, hi = newcombe_paired_ci(b, c, n, conf=conf)
    return {"method": "newcombe_paired_1998", "b": b, "c": c, "n": n,
            "lo": round(lo, 6), "hi": round(hi, 6), "conf": conf}


def _point_in_ci(point: float, ci: dict) -> bool:
    """True iff point is inside (lo, hi) inclusive."""
    return ci["lo"] <= point <= ci["hi"]


def _ci_excludes_point(ci: dict, point: float) -> bool:
    """True iff the CI does NOT contain the point (exclusive)."""
    return point < ci["lo"] or point > ci["hi"]


# ---------------------------------------------------------------------------
# Synthetic evaluation (CPU-only, used in selftest and dry-run)
# ---------------------------------------------------------------------------

def _synthetic_arm_eval(n_tasks: int, pass_rate: float, seed: int) -> list:
    """Return a 0/1 pass vector via reproducible synthetic fixture."""
    import random
    rng = random.Random(seed)
    return [1 if rng.random() < pass_rate else 0 for _ in range(n_tasks)]


def _compute_gain(arm_vec: list, base_vec: list) -> float:
    """Paired gain: mean(arm - base)."""
    n = len(arm_vec)
    return sum(a - b for a, b in zip(arm_vec, base_vec)) / n


# ---------------------------------------------------------------------------
# Real eval dispatch (INTERLOCK-gated)
# ---------------------------------------------------------------------------

def _check_interlock(args) -> None:
    """Fail-closed: refuse unless EMBER_GATE_AUTHORIZED=1 AND --live."""
    authorized = os.environ.get("EMBER_GATE_AUTHORIZED", "") == "1"
    live = getattr(args, "live", False)
    if not (authorized and live):
        print(
            "D_GATE_INTERLOCK_BLOCKED: real eval refused — "
            "EMBER_GATE_AUTHORIZED=1 env var not set AND/OR --live flag missing. "
            "Default invocation is CPU-only synthetic. "
            "Set EMBER_GATE_AUTHORIZED=1 and pass --live for real GPU eval.",
            file=sys.stderr)
        raise SystemExit(1)


def _run_real_arm(arm_name: str, adapter_path, model: str, n_tasks: int,
                  k: int, seed: int, args) -> list:
    """Run a real w4_eval arm leg. REQUIRES interlock clearance."""
    _check_interlock(args)
    # Import w4_eval machinery (same scripts dir)
    scripts_dir = str(_HERE)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import w4_eval  # noqa: E402

    # Build minimal args object mirroring w4_eval.run_arm expectations
    class _A:
        pass
    a = _A()
    a.k = k
    a.batch_size = 8
    a.max_new = 512
    a.temp = 0.8
    a.seed = seed
    from w4_eval import load_split, task_pass_vector  # noqa: E402
    problems = load_split("validation", n_tasks or None)
    order = [p["id"] for p in problems]
    rows, _ = w4_eval.run_arm(arm_name, adapter_path or None, model,
                              problems, a)
    return task_pass_vector(rows, order)


# ---------------------------------------------------------------------------
# Gate logic
# ---------------------------------------------------------------------------

def run_d_gate(artifact_path: Path, args) -> dict:
    """Execute the full D-gate protocol. Returns the receipt dict."""
    _RECEIPTS.mkdir(parents=True, exist_ok=True)
    _QUARANTINE.mkdir(parents=True, exist_ok=True)
    ts = _utc_ts()

    # ---- 1. Pre-move sha256 ----
    pre_sha = _sha256_file(artifact_path)
    print(f"[d_gate] artifact: {artifact_path}")
    print(f"[d_gate] sha256 pre-move: {pre_sha}")

    n_tasks = getattr(args, "n_tasks", 20)
    k = getattr(args, "k", 4)
    seed = getattr(args, "seed", 14)
    model = getattr(args, "model", "Qwen/Qwen2.5-Coder-3B-Instruct")
    surface = getattr(args, "surface", "mbpp-validation")

    use_real = getattr(args, "live", False) and \
        os.environ.get("EMBER_GATE_AUTHORIZED", "") == "1"

    if use_real:
        _check_interlock(args)

    # ---- 2. Arm: base (no adapter) ----
    print("[d_gate] arm: base", flush=True)
    if use_real:
        vec_base = _run_real_arm("base", None, model, n_tasks, k, seed, args)
    else:
        vec_base = _synthetic_arm_eval(n_tasks, 0.40, seed)

    # ---- 3. Arm: adapter (with artifact) ----
    print("[d_gate] arm: adapter", flush=True)
    adapter_path_str = str(artifact_path) if use_real else None
    if use_real:
        vec_adapter = _run_real_arm("adapter", artifact_path, model,
                                    n_tasks, k, seed + 1, args)
    else:
        # Synthetic: adapter arm improves pass rate meaningfully
        vec_adapter = _synthetic_arm_eval(n_tasks, 0.60, seed + 1)

    gain_with_raw = _compute_gain(vec_adapter, vec_base)
    gain_with_exact_ci = _exact_paired_ci(vec_adapter, vec_base)
    gain_with_boot = _bootstrap_ci(vec_adapter, vec_base, seed=seed)

    # ---- 4. Quarantine move + sha256 assertion ----
    print(f"[d_gate] quarantining {artifact_path.name} ...", flush=True)
    quarantine_dest = _quarantine_move(artifact_path)
    print(f"[d_gate] moved to: {quarantine_dest}")

    # ---- 5. Arm: adapter-quarantined-rerun (without artifact) ----
    print("[d_gate] arm: adapter-quarantined-rerun", flush=True)
    if use_real:
        vec_quarantined = _run_real_arm("adapter-quarantined-rerun", None,
                                        model, n_tasks, k, seed + 2, args)
    else:
        # Synthetic: gain should collapse (env drift scenario not present)
        vec_quarantined = _synthetic_arm_eval(n_tasks, 0.41, seed + 2)

    gain_without_raw = _compute_gain(vec_quarantined, vec_base)
    gain_without_exact_ci = _exact_paired_ci(vec_quarantined, vec_base)
    gain_without_boot = _bootstrap_ci(vec_quarantined, vec_base, seed=seed + 2)

    # ---- 6. Restore + byte-identity check ----
    print("[d_gate] restoring artifact ...", flush=True)
    _restore_move(quarantine_dest, artifact_path)
    post_sha = _sha256_file(artifact_path)
    byte_identity_ok = (pre_sha == post_sha)
    print(f"[d_gate] sha256 post-restore: {post_sha}")
    print(f"[d_gate] byte-identity: {byte_identity_ok}")

    # FAIL-CLOSED: byte identity is mandatory
    if not byte_identity_ok:
        raise SystemExit(
            f"D_GATE_FAIL_CLOSED: restore byte-identity check FAILED — "
            f"pre={pre_sha} post={post_sha}; receipt not written.")

    # ---- 7. Arm: adapter-restored ----
    print("[d_gate] arm: adapter-restored", flush=True)
    if use_real:
        vec_restored = _run_real_arm("adapter-restored", artifact_path,
                                     model, n_tasks, k, seed + 3, args)
    else:
        # Synthetic: matches adapter arm (reproduces within CI)
        vec_restored = _synthetic_arm_eval(n_tasks, 0.60, seed + 3)

    gain_restored_raw = _compute_gain(vec_restored, vec_base)
    gain_restored_exact_ci = _exact_paired_ci(vec_restored, vec_base)
    gain_restored_boot = _bootstrap_ci(vec_restored, vec_base, seed=seed + 3)

    # ---- 8. Verdict computation ----
    # PASS iff:
    #   (a) gain_without's CI excludes gain_with point (gain collapsed)
    #   AND
    #   (b) gain_with point is within gain_restored's CI (gain reproduced)
    collapse_ok = _ci_excludes_point(gain_without_exact_ci, gain_with_raw)
    restore_ok = _point_in_ci(gain_with_raw, gain_restored_exact_ci)
    verdict_pass = collapse_ok and restore_ok and byte_identity_ok

    # All assertions BEFORE receipt write (fail-closed)
    verdict = "PASS" if verdict_pass else "FAIL"
    print(f"[d_gate] collapse_ok={collapse_ok} restore_ok={restore_ok} "
          f"byte_identity_ok={byte_identity_ok} verdict={verdict}", flush=True)

    # ---- 9. Build receipt ----
    receipt = {
        "ticket": "D-GATE",
        "issue": "#114",
        "scope": "artifact-quarantine-falsifier",
        "ts": ts,
        "sha_convention": SHA_CONVENTION,
        "artifact_path": str(artifact_path),
        "artifact_sha256_pre_move": pre_sha,
        "artifact_sha256_post_restore": post_sha,
        "byte_identity_verified": byte_identity_ok,
        "quarantine_path": str(quarantine_dest),
        "surface": surface,
        "seed_protocol": {
            "base": seed, "adapter": seed + 1,
            "adapter-quarantined-rerun": seed + 2,
            "adapter-restored": seed + 3},
        "n_tasks": n_tasks,
        "k": k,
        "arms": {
            "base": {"pass_sum": sum(vec_base), "pass_rate": sum(vec_base) / n_tasks},
            "adapter": {"pass_sum": sum(vec_adapter), "pass_rate": sum(vec_adapter) / n_tasks},
            "adapter-quarantined-rerun": {
                "pass_sum": sum(vec_quarantined),
                "pass_rate": sum(vec_quarantined) / n_tasks},
            "adapter-restored": {
                "pass_sum": sum(vec_restored),
                "pass_rate": sum(vec_restored) / n_tasks},
        },
        "gain_with": {
            "value": round(gain_with_raw, 6),
            "exact_ci": gain_with_exact_ci,
            "bootstrap_ci": gain_with_boot,
        },
        "gain_without": {
            "value": round(gain_without_raw, 6),
            "exact_ci": gain_without_exact_ci,
            "bootstrap_ci": gain_without_boot,
        },
        "gain_restored": {
            "value": round(gain_restored_raw, 6),
            "exact_ci": gain_restored_exact_ci,
            "bootstrap_ci": gain_restored_boot,
        },
        "verdict_components": {
            "collapse_ok": collapse_ok,
            "restore_ok": restore_ok,
            "byte_identity_ok": byte_identity_ok,
            "gain_with_point": round(gain_with_raw, 6),
            "gain_without_ci_lo": gain_without_exact_ci["lo"],
            "gain_without_ci_hi": gain_without_exact_ci["hi"],
            "gain_restored_ci_lo": gain_restored_exact_ci["lo"],
            "gain_restored_ci_hi": gain_restored_exact_ci["hi"],
        },
        "verdict": verdict,
        "pass": verdict_pass,
    }

    artifact_stem = artifact_path.stem[:32].replace("/", "_").replace("\\", "_")
    receipt_path = _RECEIPTS / f"d-gate-{artifact_stem}-{ts}.json"
    checked_write(receipt_path, receipt)
    print(f"[d_gate] receipt: {receipt_path}", flush=True)
    return receipt


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

def _selftest():
    """CPU-only selftest. Drives both PASS and FAIL verdict branches.

    Tests:
      1. PASS case: gain collapses on quarantine, reproduces on restore.
      2. FAIL case (false-accept guard): gain survives quarantine
         (the scenario the gate exists to catch).
      3. Real quarantine round-trip on a temp file (byte-identity verified).
      4. Exact CI numbers pinned against stats_exact values.
    Final marker: D_GATE_SELFTEST_PASS
    """
    print("[d_gate selftest] starting ...", flush=True)
    fails = []

    def check(name: str, condition: bool, detail: str = ""):
        if not condition:
            fails.append(f"FAIL {name}: {detail}")
            print(f"FAIL {name}: {detail}", flush=True)
        else:
            print(f"ok   {name}", flush=True)

    # ---- Pin exact CI from stats_exact ----
    scripts_dir = str(_HERE)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from stats_exact import newcombe_paired_ci, wilson_ci  # noqa: E402

    # Pin: newcombe_paired_ci(b=0, c=10, n=20) — all discordant pairs favor base
    # Expected: both bounds negative (base strictly dominated arm2)
    lo_nc_collapse, hi_nc_collapse = newcombe_paired_ci(0, 10, 20)
    check("pin_newcombe_collapse_lo_negative",
          lo_nc_collapse < -0.60,
          f"got lo={lo_nc_collapse:.4f}; expected < -0.60")
    check("pin_newcombe_collapse_hi_negative",
          hi_nc_collapse < 0.0,
          f"got hi={hi_nc_collapse:.4f}; expected < 0 (both bounds negative)")

    # Pin: newcombe_paired_ci(b=8, c=0, n=20) — gain is positive
    lo_nc_gain, hi_nc_gain = newcombe_paired_ci(8, 0, 20)
    check("pin_newcombe_gain_lo_positive", lo_nc_gain > 0.10,
          f"got lo={lo_nc_gain:.4f}; expected > 0.10")
    check("pin_newcombe_gain_hi_lte1", hi_nc_gain <= 1.0,
          f"got hi={hi_nc_gain:.4f}")

    # Pin: wilson_ci(0, 20) upper bound < 0.2
    lo_w0, hi_w0 = wilson_ci(0, 20)
    check("pin_wilson_zero_n20_lo", lo_w0 == 0.0, f"got lo={lo_w0}")
    check("pin_wilson_zero_n20_hi", hi_w0 < 0.2, f"got hi={hi_w0:.4f}")

    # ---- Construct synthetic vectors for PASS case ----
    # Seeds chosen (verified) so gain_with is excluded from ci_without
    # and included in ci_restored.
    # n=30, base~0.40, adapter~0.70, quarantined~0.38 (collapse), restored~0.70
    n = 30
    import random

    def _make_vec(rate, seed_val, size=30):
        r = random.Random(seed_val)
        return [1 if r.random() < rate else 0 for _ in range(size)]

    # seed=50: verified PASS case (see selftest pin derivation 2026-06-11)
    vec_base_p = _make_vec(0.40, 50, n)
    vec_adapter_p = _make_vec(0.70, 51, n)   # real gain
    vec_quarant_p = _make_vec(0.38, 52, n)   # gain collapses at quarantine
    vec_restore_p = _make_vec(0.70, 53, n)   # gain reproduces on restore

    gain_with_p = _compute_gain(vec_adapter_p, vec_base_p)
    ci_without_p = _exact_paired_ci(vec_quarant_p, vec_base_p)
    ci_restored_p = _exact_paired_ci(vec_restore_p, vec_base_p)

    collapse_ok_p = _ci_excludes_point(ci_without_p, gain_with_p)
    restore_ok_p = _point_in_ci(gain_with_p, ci_restored_p)
    verdict_pass_case = collapse_ok_p and restore_ok_p

    check("pass_case_collapse_ok", collapse_ok_p,
          f"gain_with={gain_with_p:.3f} without_ci=({ci_without_p['lo']:.3f},{ci_without_p['hi']:.3f})")
    check("pass_case_restore_ok", restore_ok_p,
          f"gain_with={gain_with_p:.3f} restored_ci=({ci_restored_p['lo']:.3f},{ci_restored_p['hi']:.3f})")
    check("pass_case_verdict", verdict_pass_case,
          "expected PASS verdict")

    # ---- FAIL case (false-accept guard): gain survives quarantine ----
    # Gain remains present even after artifact removed — gate catches it
    # seeds offset by 10 from PASS case; quarantine uses same rate as adapter
    vec_base_f = _make_vec(0.40, 60, n)
    vec_adapter_f = _make_vec(0.70, 61, n)   # gain present
    vec_quarant_f = _make_vec(0.70, 62, n)   # gain PERSISTS (false-accept scenario)
    vec_restore_f = _make_vec(0.70, 63, n)   # restore also gains

    gain_with_f = _compute_gain(vec_adapter_f, vec_base_f)
    ci_without_f = _exact_paired_ci(vec_quarant_f, vec_base_f)
    ci_restored_f = _exact_paired_ci(vec_restore_f, vec_base_f)

    collapse_ok_f = _ci_excludes_point(ci_without_f, gain_with_f)
    restore_ok_f = _point_in_ci(gain_with_f, ci_restored_f)
    verdict_fail_case = collapse_ok_f and restore_ok_f

    # In the false-accept scenario: gain survives → collapse check FAILS
    check("fail_case_collapse_not_ok", not collapse_ok_f,
          f"gain_with={gain_with_f:.3f} without_ci=({ci_without_f['lo']:.3f},{ci_without_f['hi']:.3f}); "
          f"expected gate to detect false-accept (collapse_ok should be False)")
    check("fail_case_verdict_is_fail", not verdict_fail_case,
          "expected FAIL verdict on false-accept scenario")

    # ---- Quarantine round-trip on temp file (real byte-identity) ----
    (_REPO / "state").mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".bin",
                                     dir=str(_REPO / "state")) as tf:
        test_bytes = b"d_gate_selftest_probe_bytes_" + b"\xde\xad\xbe\xef" * 16
        tf.write(test_bytes)
        temp_path = Path(tf.name)

    try:
        pre_hash = _sha256_file(temp_path)
        q_dest = _quarantine_move(temp_path)
        check("quarantine_file_moved", not temp_path.exists(),
              "artifact should not exist after quarantine move")
        check("quarantine_dest_exists", q_dest.is_file(),
              f"quarantine dest {q_dest} should exist")
        _restore_move(q_dest, temp_path)
        post_hash = _sha256_file(temp_path)
        check("roundtrip_byte_identity", pre_hash == post_hash,
              f"pre={pre_hash} post={post_hash}")
        check("roundtrip_content_correct",
              temp_path.read_bytes() == test_bytes,
              "bytes should match original")
    finally:
        if temp_path.exists():
            temp_path.unlink()

    # ---- Summary ----
    if fails:
        for f in fails:
            print(f)
        print("D_GATE_SELFTEST_FAIL", flush=True)
        raise SystemExit(1)

    print("\nD_GATE_SELFTEST_PASS", flush=True)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main():
    ap = argparse.ArgumentParser(
        description="D-gate: artifact quarantine falsifier (eng-32 #114)")
    ap.add_argument("--selftest", action="store_true",
                    help="CPU-only selftest; no GPU/network required")
    ap.add_argument("--artifact", default=None,
                    help="Path to the adapter artifact to quarantine-test")
    ap.add_argument("--model",
                    default="Qwen/Qwen2.5-Coder-3B-Instruct")
    ap.add_argument("--surface", default="mbpp-validation")
    ap.add_argument("--n-tasks", type=int, default=0,
                    help="0 = full validation split")
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--seed", type=int, default=14)
    ap.add_argument("--live", action="store_true",
                    help="Enable real GPU eval legs (also requires "
                         "EMBER_GATE_AUTHORIZED=1 env var)")
    args = ap.parse_args()

    if args.selftest:
        _selftest()
        return

    if args.artifact is None:
        print("d_gate: --artifact <path> is required for non-selftest runs",
              file=sys.stderr)
        raise SystemExit(1)

    artifact = Path(args.artifact)
    if not artifact.is_file():
        print(f"d_gate: artifact not found: {artifact}", file=sys.stderr)
        raise SystemExit(1)

    # Interlock check before any live eval
    if not (getattr(args, "live", False) and
            os.environ.get("EMBER_GATE_AUTHORIZED", "") == "1"):
        print(
            "D_GATE_INTERLOCK_BLOCKED: dry-run mode — no GPU eval will execute. "
            "Pass --live and set EMBER_GATE_AUTHORIZED=1 to run real eval legs.",
            flush=True)
        # In dry-run mode without --live, run a synthetic demonstration
        args.live = False
        receipt = run_d_gate(artifact, args)
    else:
        _check_interlock(args)
        receipt = run_d_gate(artifact, args)

    print(f"\n[d_gate] verdict: {receipt['verdict']}", flush=True)


if __name__ == "__main__":
    _main()
