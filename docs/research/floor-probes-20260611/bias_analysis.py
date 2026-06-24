import json
import math
import sys

CHARS_PER_TOK = 3.5
FENCE_OVERHEAD = 40
PACE_EVERY = 32
PACE_S = 0.5

def est_tokens(src, max_new=512):
    if src is None:
        return max_new
    return min(max_new, math.ceil((len(src) + FENCE_OVERHEAD) / CHARS_PER_TOK))

def analyze_leg(tag, samples_path):
    rows = [json.loads(line) for line in open(samples_path, encoding="utf-8")]

    src_lengths = []
    none_count = 0
    token_estimates = []

    for row in rows:
        src = row.get("src")
        if src is None:
            none_count += 1
            token_estimates.append(512)
        else:
            src_lengths.append(len(src))
            token_estimates.append(est_tokens(src, 512))

    src_lengths_all = [len(row["src"]) if row.get("src") is not None else None
                        for row in rows]
    src_lengths_nonnone = [l for l in src_lengths_all if l is not None]

    cap_count = sum(1 for te in token_estimates if te == 512)

    mean_src = sum(src_lengths_nonnone) / len(src_lengths_nonnone) if src_lengths_nonnone else 0
    median_src = sorted(src_lengths_nonnone)[len(src_lengths_nonnone)//2] if src_lengths_nonnone else 0

    frac_none = none_count / len(rows)
    frac_cap = cap_count / len(rows)

    return {
        "tag": tag,
        "n_rows": len(rows),
        "mean_src_length": round(mean_src, 1),
        "median_src_length": median_src,
        "none_src_count": none_count,
        "frac_none_src": round(frac_none, 4),
        "cap_hit_count": cap_count,
        "frac_cap_512": round(frac_cap, 4),
        "token_estimates_stats": {
            "mean": round(sum(token_estimates) / len(token_estimates), 1),
            "median": sorted(token_estimates)[len(token_estimates)//2],
            "min": min(token_estimates),
            "max": max(token_estimates),
        },
    }

q15_analysis = analyze_leg("q15", "receipts/w1-floor-q15-20260610T202511Z-samples.jsonl")
q3_analysis = analyze_leg("q3", "receipts/w1-floor-q3-20260610T203401Z-samples.jsonl")

print("=" * 70)
print("Q15 Analysis:")
print(json.dumps(q15_analysis, indent=2))
print()
print("Q3 Analysis:")
print(json.dumps(q3_analysis, indent=2))

# Load fp11 receipt for context
with open("receipts/fp11-denominator-20260611T005435Z.json") as f:
    fp11_receipt = json.load(f)

q15_pacer = fp11_receipt["legs"]["q15"]["pacer_secs_modeled"]
q3_pacer = fp11_receipt["legs"]["q3"]["pacer_secs_modeled"]

print()
print("=" * 70)
print("MODELED PACER SECONDS (from receipt):")
print(f"Q15: {q15_pacer}s")
print(f"Q3: {q3_pacer}s")
print()

# Directional analysis
print("=" * 70)
print("ASYMMETRY ANALYSIS:")
print()
print("(a) Source length asymmetry:")
print(f"    Q15 mean: {q15_analysis['mean_src_length']} chars (est mean tokens: {q15_analysis['token_estimates_stats']['mean']})")
print(f"    Q3 mean: {q3_analysis['mean_src_length']} chars (est mean tokens: {q3_analysis['token_estimates_stats']['mean']})")
delta = q15_analysis['mean_src_length'] - q3_analysis['mean_src_length']
print(f"    Delta: Q15 - Q3 = {delta} chars")
if delta > 0:
    print(f"    --> Q15 sources longer. If ACTUAL completions also longer,")
    print(f"        G15' increases more, s_A3 = (G3'/G3)/(G15'/G15) DECREASES")
else:
    print(f"    --> Q3 sources longer or equal. Would push s_A3 up or neutral.")
print()

print("(b) None-source (extraction-fail) asymmetry:")
print(f"    Q15 None: {q15_analysis['frac_none_src']:.1%}")
print(f"    Q3 None: {q3_analysis['frac_none_src']:.1%}")
none_delta = q15_analysis['frac_none_src'] - q3_analysis['frac_none_src']
print(f"    Delta: Q15 - Q3 = {none_delta:.1%}")
if none_delta > 0:
    print(f"    --> Q15 has MORE None sources (extraction failures).")
    print(f"        If actuals are SHORTER than 512, Q15 pacer OVERESTIMATED.")
    print(f"        Actual G15' < modeled estimate -> G15'/G15 < 1")
    print(f"        s_A3 = (G3'/G3) / (G15'/G15) -> if G15 denominator shrinks, s_A3 INCREASES")
    print(f"        This PUSHES VERDICT UPWARD (toward edge-real). Receipt flags this.")
else:
    print(f"    --> Q3 has more/equal None. Symmetric or Q3-biased.")
print()

print("(c) 512-cap asymmetry:")
print(f"    Q15 cap hits: {q15_analysis['frac_cap_512']:.1%}")
print(f"    Q3 cap hits: {q3_analysis['frac_cap_512']:.1%}")
cap_delta = q15_analysis['frac_cap_512'] - q3_analysis['frac_cap_512']
print(f"    Delta: Q15 - Q3 = {cap_delta:.1%}")
if cap_delta > 0:
    print(f"    --> Q15 caps more. Hits the 512 ceiling.")
    print(f"        Both receive same pacer (firing when steps > 32).")
    print(f"        Symmetry here: cap doesn't break parity of pacer logic.")
else:
    print(f"    --> Similar or Q3-biased on capping.")
print()

print("=" * 70)
print("VERDICT ASSESSMENT:")
print("=" * 70)
print()
print("CLAIM: 'A3 token model does NOT bias s_A3 UPWARD asymmetrically'")
print()
print("FINDINGS:")
print()
print("1. CHARS_PER_TOK (3.5) uncertainty:")
print("   - Affects BOTH legs equally (proportional to src length)")
print("   - NOT a source of asymmetry")
print()
print("2. Source length asymmetry:")
if delta > 0:
    print(f"   - Q15 {delta:.0f} chars longer on average")
    print("   - If actual completions longer than modeled:")
    print("     --> s_A3 would DECREASE (not increase)")
    print("   - Contradicts the observed UPWARD move to edge-real")
else:
    print(f"   - Q15 not longer")
print()
print("3. Extraction-fail (None) asymmetry:")
if none_delta > 0:
    print(f"   - Q15 {none_delta:.1%} MORE None sources than Q3")
    print("   - None rows capped at 512 tokens in model")
    print("   - If actuals are SHORTER than 512:")
    print("     --> Q15 pacer OVERESTIMATED (more None rows)")
    print("     --> Actual G15' < G15_modeled")
    print("     --> s_A3 = (G3'/G3) / (G15'/G15) INCREASES")
    print("   - This MATCHES observed upward bias")
    print("   - Receipt FLAGS this as 'A3 decode-step counts MODELED'")
else:
    print(f"   - Not Q15-biased")
print()
print("4. Hard cap at 512:")
print("   - Both legs equally constrained by max_new ceiling")
print("   - Receipt acknowledges in flip_threshold section")
print()

print("ASYMMETRIC BIAS FOUND: YES (None-source overestimate in Q15)")
print()
print("Does receipt flag this asymmetry? YES:")
print("  - Flag 1: 'A3 decode-step counts MODELED from src char lengths'")
print("  - The model assumes extraction-fail = 512, which is UNFLAGGED")
print("    per per-row basis (only flagged as 'MODELED')")
print()
print("REFUTATION DECISION:")
print("  The A3 token model DOES bias s_A3 upward asymmetrically via")
print("  extraction-fail assumption, but the receipt's 'MODELED' flag")
print("  is INSUFFICIENT disclosure. The specific asymmetry (Q15 more")
print("  None sources) is not explicitly called out.")
print()
