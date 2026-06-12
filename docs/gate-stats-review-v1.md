# Gate-stats correctness review v1 (wait-window queue item, 2026-06-12)

Scope: the statistical machinery every verdict gate uses on our actual regime —
paired multi-arm evals over n≈100 tasks with NEAR-ZERO success counts (round-1
q15: 0 successes × 4 arms × 100 tasks; W-code floors: 0-2 successes typical).
Audit §6 flagged power-notes missing from fire-conditions. This doc fixes the
method choices BEFORE round-1 per-task stats land (1B checkpoint, ~09:00Z
06-13) so the round-1 verdict and every later gain gate use correct intervals.

## 1. Bootstrap CIs are the wrong tool in this regime — retired

Percentile bootstrap on zero-inflated binary data degenerates: with 0-2
successes in n=100, most resamples contain 0-1 successes, the CI collapses
toward {0} and undercovers badly (documented small-p failure of the
percentile method). Any gate clause that says "bootstrap CI" on a success
rate is replaced as below. Bootstrap remains acceptable ONLY for continuous
per-task quantities (e.g. bits/episode), never for the binary pass rates.

## 2. Replacements (exact/score methods, all closed-form)

- **Single-arm success rate:** Wilson score interval. Anchor case: 0/100
  successes → 95% Wilson upper bound ≈ 3.6% (rule-of-three gives 3.0%) —
  i.e. "all-zero" certifies the TRUE rate only below ~4%, which is why
  all-zero floors are reported as "≤3.6% at 95%" and never as "0%".
- **Paired arm difference (same tasks, two arms):** Newcombe paired
  square-and-add on Wilson bounds, or exact McNemar on the discordant pairs.
  The discordant count is the ONLY information-bearing quantity — report
  b (arm A only) and c (arm B only) in every verdict receipt, not just the
  marginal rates.
- **Win declaration:** a gain gate fires only if the McNemar exact p < 0.05
  AND the Newcombe lower bound > 0. Two-sided unless the prereg names the
  direction.

## 3. Power floor (the missing audit §6 note)

With n=100 paired tasks and baseline ~2%, only LARGE deltas are detectable:
roughly, the discordant-pair binomial needs b+c ≥ ~8 with strong asymmetry
before exact McNemar can reach p<0.05 — so deltas under ~6pp are invisible
at this n. Consequence, binding: **a null verdict at n=100 near p≈0 is a
power statement, not an equivalence claim.** Every null gate must say
"underpowered below Xpp" with X from the helper (§4). Round-2 eval sizing
uses the helper BEFORE launch: pick n so the prereg'd minimum interesting
delta clears 80% power, or the prereg must state the verdict is one-sided
evidence-of-presence only.

## 4. Helper script (eng-tracker mint)

`scripts/power_helper.py` — inputs (n, p0, alpha, power) → MDE table for
Wilson/Newcombe/McNemar; selftest fixtures pin the anchor cases (0/100 →
3.57% Wilson upper; rule-of-three parity; McNemar b+c minimum at p<0.05).
All gate receipts citing power MUST cite a helper receipt, never hand
arithmetic (mine included — the §3 numbers above are design anchors and are
superseded by the first helper receipt).

## 5. Retrofit rule (binding on me)

Every fire-condition in the branch registry that contains a stats clause
gains one power-note line citing this doc + a helper receipt at next touch.
New preregs include the power note at freeze time — a prereg without one
does not freeze.
