# Fable 5 — what the public record gives ember, directly

*2026-06-10. Sources: the compiled technical report (Kai,
fable-5-model-card-technical-report-2026-06-09 — launch announcement + API
docs + secondary reporting; the full system card was not yet retrievable in
that pass), plus operational receipts from this repo's own sessions. Facts
below are labeled by source.*

## 1. The hard facts that matter operationally

- **Access window (docs-verified):** Fable 5 included on subscription plans
  June 9 → June 22, 2026; removed June 23 absent usage credits. The clock on
  Fable-grade judgment work is real: ~12 days at time of writing.
- **Mythos-class above Opus (Anthropic-stated):** same base model as
  Mythos 5; Fable is the safeguarded deployment. Post-June-22 the working
  models here revert to Opus 4.8 / Sonnet 4.6 class.
- **1M context / 128k output (docs-verified):** large single-pass reads and
  long autonomous turns are viable; cost discipline still applies.
- **Adaptive thinking always-on (docs-verified):** depth is allocated by the
  model per difficulty. Configuration implication: "think step by step"
  scaffolding and forced-reasoning prompts are dead weight for Fable-class
  configs — and still *useful* for Opus/Sonnet-class configs. This single
  fact justifies the model-split configuration design (below).
- **Persistent file-based memory is officially load-bearing (Anthropic-
  stated):** Fable "benefits substantially from persistent file-based memory
  in long-running tasks." Ember's existing discipline — STATE.md as single
  position ledger, receipts as ground truth, GOAL.md re-issued per session —
  is exactly this pattern; the model card retroactively endorses the
  architecture rather than suggesting a new one.
- **Minimal-harness autonomy (Anthropic-stated):** Pokemon FireRed completed
  on a vision-only minimal harness where prior models needed heavy
  scaffolding. Implication: delegate *larger, less-scripted* chunks to
  Fable-class subagents; reserve step-scripting for weaker models.

## 2. What this changes in ember's operation — applied today, not planned

1. **Wait-window queue (installed in the cron tick prompt + STATE.md):** the
   accumulation track is GPU-serial by design, which leaves the orchestrating
   session idle between receipts. That idleness is now structurally filled: a
   standing queue of CPU-side build items (formalization, invariant
   extraction, config split, world builds) that every tick advances after
   gate/launch. Waiting is the GPU's job, never the session's.
2. **Background fan-out as the standing pattern:** parallelizable reading
   (codebase sweeps, inventories, status checks) goes to background
   agents/workflows that run *beside* the GPU job; judgment work (math,
   world-choice, gating) stays in the main loop. First exercise: the
   avir-cli invariant-map workflow + config-inventory + LiteRT-status agents
   (2026-06-10).
3. **Compaction robustness by files, not prompt tuning:** the durable-file
   discipline (STATE.md, receipts, GOAL.md, this research/ tree) already
   makes session compaction lossless for operational state — the recovery
   anchor is on disk, re-read each tick. No fragile custom-compaction
   machinery needed; the rule is *every load-bearing fact lands in a file at
   the moment it's learned*.
4. **June-22 priority inversion:** spend Fable-class capacity on artifacts
   that OUTLIVE the access window — formalization, invariant contracts,
   world-choice analysis, kernel design — i.e., judgment crystallized into
   documents and code that Opus-class sessions can then execute against.
   Spend none of it on work a weaker model can do later.

## 3. Model-split configuration (design; per-founder rollout pending inventory)

Known risk (user-reported, matches the adaptive-thinking facts): configs
tailored *only* to Fable degrade Opus sessions — Opus needs the procedural
scaffolding Fable ignores.

Design:
- Per-founder `.claude/` splits always-loaded content into a **model-neutral
  core** (identity, safety, project facts, receipts discipline) and **model
  partials** (`fable`: high-autonomy, terse, no forced-reasoning crutches;
  `opus`/`sonnet`: explicit procedural scaffolding, anti-stall rules,
  step-gating).
- A session-start hook detects the running model and emits the matching
  partial as additional context. (An existing per-founder hot-swap mechanism
  is being located by the config inventory; adopt or generalize it rather
  than invent a parallel one.)
- Post-June-22 behavior is automatic: the detector stops matching `fable` and
  the opus partial loads — no config surgery on deadline day.

## 4. What the public record does NOT give

- No retrievable full system card in the research pass (launch page
  references it; docs index not yet updated) — so no machine-readable
  benchmark table and no harness best-practices appendix to harvest.
  Loop/hook/workflow technique therefore comes from operating receipts, not
  from the card.
- No public evidence yet on real-world fallback friction (the <5%-of-sessions
  classifier-fallback claim is Anthropic-stated, uncorroborated by user
  reports at the time of the pass). Operationally irrelevant to ember's local
  loop; relevant only to cloud-side scaffolding sessions.


## Citation status (added per Kai checkpoint 14418, FLAG S2-A)

Exact sources for the "docs-verified" claims above:
- Compiled report: `B:/M/avir/kai/state/fable-5-model-card-technical-report-2026-06-09.md` (Kai, 2026-06-09).
- Anthropic announcement: https://www.anthropic.com/news/claude-fable-5-mythos-5
- Product page: https://www.anthropic.com/claude/fable
- API docs: https://platform.claude.com/docs/en/about-claude/models/introducing-claude-fable-5-and-claude-mythos-5
- AWS availability: https://aws.amazon.com/blogs/aws/anthropic-claude-fable-5-on-aws-mythos-class-capabilities-with-built-in-safeguards-now-available/
- Third-party system-card coverage (failure modes, pp.37-216 quotes): https://www.digitalapplied.com/blog/claude-fable-5-mythos-5-agentic-coding-deep-dive-2026 (SECONDARY source quoting the 319-page system card; card itself is primary).
- News roundup: https://www.latent.space/p/ainews-anthropic-claude-fable-5-mythos
Claims sourced only from the compiled report and not re-fetched from a primary URL are attributable to that report file, not to independent verification in this note.
