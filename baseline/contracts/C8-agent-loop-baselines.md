# Contract C8: Local Agentic Research Baselines

Status: BASELINE_COMPLETE for the `local_agentic_research_sota` family only.
Claim family: `local_agentic_research_sota`.
Access date: 2026-06-29.

This contract locks the local-agentic-research comparator surface for Ember. It does not claim Ember has beaten the ruler, and it does not complete the overall `/baseline`.

## Uncheatable Claim Shape

Ember local research operator `X` beats or replaces baseline agent/research loop `Y` on frozen research-operation suite `Z` by threshold `T`, under identical files, tools, compute, wall-clock, cached receipts, network, token, GPU/CPU, and human-intervention budget `C`, verified by deterministic test runner, receipt parser, or predeclared reviewer rubric `V`, producing PASS, FAIL, or INVALID-RUN.

## Boundary Versus C5 And CLI/Goal Mode

This family is not a C5 self-improvement result and not an Ember CLI/goal-mode runtime claim.

- C5 asks whether Ember's loop finds and validates better experiment/code/data/architecture changes than a baseline loop.
- This family asks whether Ember's local research operator chooses experiments, avoids wasteful recompute, governs long jobs, parses receipts, preserves negative results, and makes defensible next-job decisions better than visible agent/research-loop baselines.
- Ember CLI/runtime and goal mode are separate families; this family may require their fixtures but cannot complete them.

## Locked Comparator Lanes Y

### Lane LAR-CODEX-LOCAL-OPERATOR

Comparator: `agent-openai-codex` source row.

Controls: visible Codex-class local research-operation behavior: reading repo state, selecting tools, editing code, running commands, handling permissions, preserving task context, and producing evidence-backed final audits.

Threshold: Ember must beat a pinned Codex-local replay fixture or official-doc-derived behavior fixture on the frozen research-operation suite under identical files, tools, budget, and receipts. Rumors of hidden model self-training are not accepted as comparator facts.

### Lane LAR-EXTERNAL-CODING-AGENT-B

Comparator: `agent-anthropic-claude-code` source row.

Controls: visible external coding agent B-class agentic coding/research behavior: codebase navigation, edits, terminal execution, development-tool integration, and continuation through local workflows.

Threshold: Ember must beat a clean-room/pinned behavior fixture under identical files, tools, budget, and receipts. Legal/public documentation and locally observed behavior are allowed comparator inputs; private source expression is not.

### Lane LAR-HERMES-NEMO-OPERATOR

Comparator: `agent-nvidia-nemo-agent-toolkit` source row.

Controls: Hermes/NemoClaw-class local/open agent substrate behavior: profiling, observability, evaluation, UI, MCP/A2A-style integration, and local tool orchestration.

Threshold: Ember must beat a resolved project/version fixture or record a sourced no-recompute exclusion before using this lane in a claim. The family baseline can pin the class; an Ember win must pin the exact executable fixture.

### Lane LAR-ML-RESEARCH-BENCHMARKS

Comparators: `mle-bench`, `mlagentbench`, `ai-scientist-v2`, and `kosmos-ai-scientist` source rows.

Controls: research-operation task selection, benchmark relevance, no-recompute decisions, negative-result treatment, and scientific-discovery overclaim guards.

Threshold: Ember must choose, execute, parse, and stop/retry research jobs at least as well as the frozen benchmark/research-loop fixture under identical budget. A small local C5-0 success cannot satisfy broad local-agentic research unless the research-operation suite itself passes.

### Lane LAR-NONAGENT-SCRIPTED-SEARCH

Comparator: deterministic scripted/search baseline.

Controls: cases where language-agent behavior is not required.

Threshold: Ember must beat a same-budget deterministic baseline on job selection quality, receipt correctness, and final decision quality. If the scripted baseline ties Ember, no agentic advantage claim is allowed.

## Metric Z

A valid local-agentic research run must report:

- task manifest and research-operation suite ID;
- allowed/denied tools, network policy, and cached receipt inventory before run;
- chosen next experiment and no-recompute justification;
- compute-spend packet for long jobs;
- stop rule, checkpoint/resume plan, and failure taxonomy;
- commands executed and receipts parsed;
- valid/invalid tool-call counts;
- negative-result preservation;
- final next-action decision and evidence map;
- human-intervention ledger;
- replay command and parser verdict.

## Constraints C

A valid claim must preserve:

- identical files, tools, budgets, receipts, and task statement across Ember and baselines;
- no denial of cached receipts to baselines when Ember received them;
- no paid/hosted judge as required authority when local rubric or human-authorized review can apply the same standard;
- no private model capability rumors as measured comparator facts;
- no hidden human steering or post-hoc task/metric changes;
- no obstacle-as-outcome: blockers must produce a changed approach, a valid FAIL/INVALID-RUN, or a better experiment-selection policy;
- no recomputing external results when exact published fields already satisfy the comparator contract;
- LF-only tracked baseline files;
- parser-readable PASS, FAIL, or INVALID-RUN receipt;
- public/private `/baseline` parity before any overall completion claim.

## Budget B

Short jobs may validate fixture availability, parser shape, receipt inventory, no-recompute decisions, line endings, and replay commands.

Long jobs require a compute-spend packet naming claim ID, expected new information, maximum GPU/CPU/network budget, stop rule, checkpoint/resume plan, energy/power method or explicit estimation method, and post-run parser. A long job is invalid if it can only rediscover a published external result already adequate for the contract.

## Verifier V

Family verifier:

```powershell
python baseline\scripts\validate_local_agentic_research.py --root baseline --out baseline\receipts\local-agentic-research-validation-2026-06-29.json
```

Overall verifier remains:

```powershell
python baseline\scripts\verify_completion.py --root baseline --pretty
```

The family verifier passes only when this contract, report, source ledger, and completion lock agree on comparator lanes, no-recompute policy, long-job governance, anti-cheat constraints, budget, verifier, and falsifiers.

## Falsifiers

The local-agentic research claim is downgraded or invalid if:

- Codex/external-agent-B/Hermes-class or deterministic baseline makes the same next-job decision with equal or better evidence;
- Ember recomputes a result already available from exact external sources without justification;
- long-job stop rules, resume plan, or parser are missing;
- negative results are dropped, hidden, or converted into success prose;
- a local C5 self-improvement result is used as the whole local-agentic research proof;
- a private model rumor or hidden human intervention is used as evidence;
- parser cannot reproduce the verdict from receipts;
- line-ending or manifest drift prevents replay.

## Completion Boundary For This File

This family is complete when `baseline/scripts/validate_local_agentic_research.py` emits `LOCAL_AGENTIC_RESEARCH_BASELINE_COMPLETE` and `completion-lock.json` references that receipt for `local_agentic_research_sota`.

This file's completion does not complete the overall baseline.