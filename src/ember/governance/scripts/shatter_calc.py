# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""
shatter_calc.py — SHATTER computation for Ember keystone optimizer lever.

Method frozen 2026-06-23 in the operator's state tree
(shatter-method-frozen-20260623.md, 2026-06-23 freeze — not part of this repo).

FROZEN PARAMETERS:
  K = 5            (trailing-K window mean smoothing)
  epsilon = 0.50   (loss tolerance ~ 1.1 * sigma_raw_late / sqrt(K))
  BUDGET_B = 2.2e9 (full C-BASE pretrain budget, tokens)
  BUDGET_TOKENS = 60_000_000 (convergence segment budget)
  SHATTER = some variant has effective_days <= 1 AND smoothed_final <= ref + epsilon

Usage:
  python shatter_calc.py [--loss-dir <dir>] [--out <out.json>]

  Reads {loss_dir}/conv-{variant}-seed42/loss_log.jsonl for each known variant.
  Missing logs are skipped (partial run); muon_split must be present for SHATTER.

Provenance: landed from stage dryrun-20260704T211712Z (ember issue #210 Tier 2)
with a portability fix over the staged original — the staged copy's loss_dir
default (run() and --loss-dir) and its two frozen-spec citations carried an
absolute drive-letter-rooted path wrapping already-redacted segments, which
made the default non-functional off the export machine and tripped the repo's
leak-gate on the path shape. Replaced with a repo-relative DEFAULT_LOSS_DIR
constant (functional) and a descriptive citation (informational, no path).
No other lines changed. See receipts/ember-c-scale/land210e-*.
"""

import json
import math
import sys
import os
import argparse
from pathlib import Path
from typing import Optional

# Repo-relative default; overridden via --loss-dir/loss_dir for any real run.
# Falls under *scratch*/ (.gitignore line 27) so a default-path run never
# tracks its own output.
DEFAULT_LOSS_DIR = str(Path(__file__).resolve().parent.parent / "scratch" / "shatter-loss-logs")

# ── FROZEN METHOD CONSTANTS ──────────────────────────────────────────────────
K = 5                        # trailing-window width
EPSILON = 0.50               # a-priori loss tolerance (1.1 * sigma_raw_late / sqrt(K))
BUDGET_B = 2.2e9             # full pretrain budget (tokens)
BUDGET_TOKENS = 60_000_000   # convergence segment budget (tokens)
SECS_PER_DAY = 86_400

# Bench steady-state paced throughputs (from keystone-optimizer-lever-result-20260623.json).
# These are the BENCH numbers, NOT the convergence-run average.
TOK_S_PACED = {
    "full_fused_adamw": 29598.7,
    "muon_ns3":         23068.8,
    "muon_split":       19874.8,
}

VARIANTS = ["full_fused_adamw", "muon_ns3", "muon_split"]
SEED = 42


# ── SMOOTHING ────────────────────────────────────────────────────────────────

def trailing_k_mean(losses: list[float], K: int) -> list[float]:
    """Apply trailing-K window mean to a loss sequence.
    For i < K-1 the window is [0..i] (all available entries).
    Returns a list of the same length as losses.
    """
    smoothed = []
    for i in range(len(losses)):
        start = max(0, i - K + 1)
        window = losses[start : i + 1]
        smoothed.append(sum(window) / len(window))
    return smoothed


# ── TOKENS-TO-MATCH-REF ──────────────────────────────────────────────────────

def tokens_to_match_ref(
    tokens: list[int],
    smoothed: list[float],
    ref_loss: float,
    budget_tokens: int = BUDGET_TOKENS,
) -> int:
    """Return the token count at which smoothed loss FIRST reaches <= ref_loss.
    If it never reaches ref_loss within the budget, returns budget_tokens (cap).
    """
    for t, s in zip(tokens, smoothed):
        if s <= ref_loss:
            return t
    return budget_tokens


# ── EFFECTIVE DAYS ───────────────────────────────────────────────────────────

def effective_days(
    tok_to_match: int,
    tok_s: float,
    budget_b: float = BUDGET_B,
    budget_tokens: int = BUDGET_TOKENS,
) -> float:
    """Compute effective_days = (budget_b * tok_to_match / budget_tokens) / tok_s / secs_per_day."""
    scaled_tokens = budget_b * (tok_to_match / budget_tokens)
    seconds = scaled_tokens / tok_s
    return seconds / SECS_PER_DAY


# ── LOSS LOG READER ───────────────────────────────────────────────────────────

def load_loss_log(path: str) -> tuple[list[int], list[float]]:
    """Load a loss_log.jsonl file. Returns (tokens, losses) lists in order."""
    tokens = []
    losses = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            tokens.append(int(entry["tokens"]))
            losses.append(float(entry["loss"]))
    return tokens, losses


# ── PER-VARIANT COMPUTATION ───────────────────────────────────────────────────

def compute_variant(
    variant: str,
    tokens: list[int],
    losses: list[float],
    ref_loss: Optional[float],
) -> dict:
    """Compute SHATTER metrics for one variant.

    ref_loss: smoothed final loss of the muon_split reference.
              If None (muon_split not yet complete), tokens_to_match_ref and
              effective_days are set to None.
    """
    smoothed = trailing_k_mean(losses, K)
    smoothed_final = smoothed[-1]
    tok_s = TOK_S_PACED[variant]

    # Borderline annotation threshold: within 0.05 of the quality threshold
    BORDERLINE_MARGIN = 0.05

    if ref_loss is not None:
        ttm = tokens_to_match_ref(tokens, smoothed, ref_loss)
        ed = effective_days(ttm, tok_s)
        quality_ok = smoothed_final <= ref_loss + EPSILON
        quality_threshold = ref_loss + EPSILON
        quality_margin = quality_threshold - smoothed_final  # positive = inside (passing), negative = outside (failing)
        borderline = abs(quality_margin) < BORDERLINE_MARGIN
    else:
        ttm = None
        ed = None
        quality_ok = None
        borderline = None
        quality_margin = None

    result = {
        "variant": variant,
        "n_entries": len(tokens),
        "tokens_trained": tokens[-1],
        "smoothed_final_loss": round(smoothed_final, 6),
        "tok_s_paced": tok_s,
        "tokens_to_match_ref": ttm,
        "effective_days": round(ed, 6) if ed is not None else None,
        "quality_ok": quality_ok,
        "smoothed": [round(s, 6) for s in smoothed],
        "tokens": tokens,
    }

    # Annotate borderline only when ref_loss is available and the variant is near the threshold
    if borderline is not None and borderline:
        result["borderline"] = True
        result["quality_margin"] = round(quality_margin, 6)

    return result


# ── MAIN ──────────────────────────────────────────────────────────────────────

def run(
    loss_dir: str = DEFAULT_LOSS_DIR,
    out_path: Optional[str] = None,
    seed: int = SEED,
) -> dict:
    """Run the full SHATTER computation.

    Returns a result dict with per-variant stats and the SHATTER verdict.
    """
    variant_results = {}

    for variant in VARIANTS:
        log_path = os.path.join(loss_dir, f"conv-{variant}-seed{seed}", "loss_log.jsonl")
        if not os.path.exists(log_path):
            print(f"[shatter_calc] SKIP {variant}: {log_path} not found", file=sys.stderr)
            continue
        try:
            tokens, losses = load_loss_log(log_path)
            if len(tokens) == 0:
                print(f"[shatter_calc] SKIP {variant}: empty loss_log", file=sys.stderr)
                continue
            variant_results[variant] = {"tokens": tokens, "losses": losses}
            print(f"[shatter_calc] Loaded {variant}: {len(tokens)} entries, last_loss={losses[-1]}", file=sys.stderr)
        except Exception as e:
            print(f"[shatter_calc] ERROR loading {variant}: {e}", file=sys.stderr)

    # Determine ref_loss from muon_split (if complete)
    ref_loss = None
    if "muon_split" in variant_results:
        ms = variant_results["muon_split"]
        ms_smoothed = trailing_k_mean(ms["losses"], K)
        ref_loss = ms_smoothed[-1]
        print(f"[shatter_calc] muon_split ref_loss (smoothed_final) = {ref_loss:.6f}", file=sys.stderr)
    else:
        print("[shatter_calc] muon_split not loaded — ref_loss=None; SHATTER verdict deferred", file=sys.stderr)

    # Compute per-variant metrics
    results = {}
    for variant, data in variant_results.items():
        results[variant] = compute_variant(variant, data["tokens"], data["losses"], ref_loss)

    # SHATTER verdict
    shatter = False
    shatter_variant = None
    shatter_reason = "ref_loss not yet available" if ref_loss is None else "no variant meets both conditions"

    if ref_loss is not None:
        for variant, r in results.items():
            ed = r["effective_days"]
            qok = r["quality_ok"]
            if ed is not None and qok is not None and ed <= 1.0 and qok:
                shatter = True
                shatter_variant = variant
                shatter_reason = (
                    f"{variant}: effective_days={ed:.4f} <= 1.0 AND "
                    f"smoothed_final={r['smoothed_final_loss']:.5f} <= "
                    f"ref_loss({ref_loss:.5f}) + epsilon({EPSILON}) = {ref_loss + EPSILON:.5f}"
                )
                break

    # Propagate borderline flag to top-level if the SHATTER-deciding variant is borderline
    shatter_borderline = False
    shatter_quality_margin = None
    if shatter_variant is not None:
        sv_result = results.get(shatter_variant, {})
        if sv_result.get("borderline"):
            shatter_borderline = True
            shatter_quality_margin = sv_result.get("quality_margin")

    output = {
        "method": {
            "K": K,
            "epsilon": EPSILON,
            "budget_b": BUDGET_B,
            "budget_tokens": BUDGET_TOKENS,
            "tok_s_paced": TOK_S_PACED,
            "frozen_spec": "operator state tree: shatter-method-frozen-20260623.md (2026-06-23 freeze; not part of this repo)",
        },
        "ref_loss": round(ref_loss, 6) if ref_loss is not None else None,
        "variants": {
            v: {k: val for k, val in r.items() if k not in ("smoothed", "tokens")}
            for v, r in results.items()
        },
        "SHATTER": shatter,
        "shatter_variant": shatter_variant,
        "shatter_reason": shatter_reason,
    }

    if shatter_borderline:
        output["borderline"] = True
        output["quality_margin"] = shatter_quality_margin

    if out_path:
        with open(out_path, "w") as f:
            json.dump(output, f, indent=2)
        print(f"[shatter_calc] Output written to {out_path}", file=sys.stderr)

    return output


def main():
    parser = argparse.ArgumentParser(description="Compute SHATTER verdict for Ember optimizer lever")
    parser.add_argument(
        "--loss-dir",
        default=DEFAULT_LOSS_DIR,
        help="Directory containing conv-<variant>-seed<N>/loss_log.jsonl files",
    )
    parser.add_argument("--out", default=None, help="Path to write JSON output")
    args = parser.parse_args()

    result = run(loss_dir=args.loss_dir, out_path=args.out)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
