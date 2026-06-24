# The conversion bottleneck — first-principles pass over the component list

*2026-06-10. Source: user, two concerns — (1) planned-work backlog size;
(2) what is ember's biggest non-hardware bottleneck, and can MTP /
turboquant / 1.58-bit be first-principled against it?*

---

## 1. The bottleneck, from receipts

Decompose the feed objective: **F = (samples per GPU-hour) × (verify rate) ×
(capability gained per verified episode)**. Three terms, three different
bottleneck claims. The receipts assign it unambiguously:

- **Throughput (term 1):** never the binding constraint yet — 65-98 tok/s at
  3B governed, eval chains complete in hours.
- **Verify rate (term 2):** the ARC binding constraint (floor ~1% at 3B ⇒
  F ≈ 0 regardless of throughput). Already attacked by world choice — W-code
  moves the floor to a rich regime. SOLVED-BY-ROUTING, pending w1 receipt.
- **Conversion (term 3): THE bottleneck.** Round 1 is the receipt: 1,909
  verified episodes, clean training (loss 0.81→0.13), and ZERO transfer lift
  (q3 final: trained 0.0% vs base 1.0%). Everything upstream of the weights
  worked; the experience→capability conversion returned nothing measurable.
  Plain SFT/LoRA on own-sampled correct programs taught the ledger's surface
  form (trained arms crash MORE on unseen tasks — both q15 and q3 sample
  taxonomies) and no composition.

Non-hardware bottleneck, named: **conversion efficiency — capability gained
per verified episode.** Hardware multiplies terms 1; it cannot rescue term 3.

## 2. First-principles pass over the named components

The user's itch: can the inventoried efficiency components attack this? Sorted
by which term they actually touch:

| Component | Term it attacks | First-principles verdict for the conversion bottleneck |
|---|---|---|
| **MTP** | **3 (conversion)** — RE-OPENS | The survey re-staged MTP on negative ≤1B PRETRAINING-quality evidence. That verdict does not cover our regime: episode-SFT with few high-value sequences, where supervision density per sequence is exactly what's starved. k-step auxiliary prediction heads extract ~k× more gradient signal per episode token. NEW probe shape (distinct from the survey's question): round-2 arm, MTP-aux-loss episode-SFT vs plain SFT, matched budget, w4 gate decides. Not ludicrous — the strongest re-derivation in the list. |
| **turboquant** | 1 (throughput) + context | Real but orthogonal to conversion: faster inference/KV compression = more samples and longer contexts per GPU-hour. Becomes binding only AFTER term 3 works (a conversion fix multiplies whatever throughput exists; throughput multiplies a zero today). Sequencing unchanged. |
| **1.58-bit** | 1 + NC2-own substrate cost | No path to term 3 found. The speculative angle (ternary = extreme regularization changing small-data learning dynamics) has zero published evidence at any scale and the survey's "training on 4090 saves nothing" stands. Stays RE-STAGED. |

**The components the question didn't name are the strongest term-3 attackers
already in the contract:**

- **GRPO / RL-on-verifier-reward (CN-stack row 7).** SFT imitates own correct
  outputs; RL extracts signal from the CONTRAST between verified and failed
  programs — and `w2_ingest` already banks failed-with-src to
  `control_pool.jsonl`, which is precisely the preference/contrast material
  GRPO-class methods eat. The STaR→ReST→RLVR lineage exists because
  imitation-on-own-outputs plateaus exactly the way round 1 just did. The
  survey's "GRPO floor ~1.5B" conflict was against the 0.5B OWNED core — the
  borrowed 3B is ABOVE the floor. A GRPO pilot is live as a round-2 arm in
  W-code, not parked at NC2.
- **SDEK fast-weights / sleep consolidation (row 6).** Episodic→parametric
  consolidation as a separate timescale from SFT — the named substrate
  (gated delta-rule SSM state) is the contract's middle-timescale bet on
  conversion. Stays at its pilot (340M GDN-hybrid), feeds NC2-own.

## 3. Consolidation, not proliferation (backlog concern, same pass)

The user's first concern is right as a growth-rate risk: 3 registry rows were
added today alone. Structural difference from the-search pattern: every row
carries a fire-condition, GPU-serial forces effective WIP≈1 (this week's
reachable chain is ~8 sequenced items; the other ~11 rows are parked behind
explicit conditions or user gates), and kills require the user. But the
discipline gets a mechanical floor now:

1. **Net-flow reporting:** verdict-class registry reports state rows
   added/retired since the last verdict, not just size.
2. **Consolidation rule:** a method-variant of an existing experiment is an
   ARM of that experiment's row, never a new row. Applied immediately: the
   MTP-aux and GRPO probes from §2 fold INTO registry row 9 (round-2
   self-generation) as its design arms — row 9's open design choice becomes
   "plain SFT vs MTP-aux-SFT vs GRPO-on-verifier-reward, k per verify%" —
   zero new rows.

## 4. Sequencing consequence

W-code round 1 (w1→w2→t2→w4) stays plain-SFT — it is the baseline arm the §2
methods must beat. Round 2 runs the method arms under matched budgets; w4
paired deltas decide. The first flywheel-turn attempt (June 13-15 window)
therefore doubles as the conversion-method selection experiment — one
experiment, both questions.
