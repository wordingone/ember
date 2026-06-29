# Contract C8: Agent-Loop Baselines

Status: DRAFT.
Claim family: C8-AGENT-LOOP.

## Uncheatable Claim Shape

Ember agent loop `X` beats or replaces baseline agent loop `Y` on frozen task suite `Z` by threshold `T`, under identical files, tools, compute, wall-clock, cached receipts, and human-intervention budget `C`, verified by deterministic test runner or predeclared reviewer rubric `V`, producing PASS, FAIL, or INVALID-RUN.

## Baseline Set

At minimum, `Y` must include:

1. OpenAI Codex or a pinned Codex-local replay surface.
2. Anthropic Claude Code or a clean-room behavior fixture derived from legal public/behavioral evidence.
3. Hermes-class agent only after the exact project identity and official source are pinned.
4. A non-agent scripted/search baseline where the task does not require language-agent behavior.

## Required Frozen Artifacts

- task manifest and expected outcome;
- allowed tool list;
- denied tool list;
- cache/receipt inventory available before run;
- wall-clock, CPU, GPU, network, and token budget;
- transcript schema;
- score schema;
- replay command;
- failure taxonomy;
- human-intervention ledger.

## PASS Conditions

A PASS requires all of the following:

- Ember's score exceeds every required baseline by the predeclared threshold;
- the same run is reproducible from checked-in commands and fixtures;
- every external baseline either ran locally or has a cited, exact, no-recompute reason;
- improvement survives deletion, replay, or ablation where the claim involves learning/self-improvement;
- the result is published inside `/baseline` in both public and private repos with matching manifest hashes or an explained public-safe redaction.

## INVALID-RUN Conditions

- baseline denied tools or context that Ember received;
- source/version of baseline agent not pinned;
- metric chosen after seeing outputs;
- hidden human steering changes next action;
- Codex/Claude transcript used as Ember proof without Ember execution;
- paid/hosted judge required when local rubric is available;
- line-ending or manifest drift prevents byte-level recreation.

## Current Verdict

INVALID-RUN. No C8 comparison suite has been frozen or executed yet.