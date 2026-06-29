# Agent-Loop Baselines V0

Status: DRAFT. No self-improvement claim is granted.
Claim family: C8-AGENT-LOOP.

## Purpose

Codex, Claude Code, and Hermes-class agent surfaces are baseline comparators for Ember because a large share of frontier improvement loops now pass through an agent that can read state, choose tools, edit code, run jobs, preserve goals, and continue across interruptions. Ember cannot claim a self-improvement loop, CLI, goal mode, or local research operator advantage unless it beats or replaces these agent-loop substrates under frozen, replayable tests.

## Baseline Objects

| Baseline | Current treatment | Required pin before use |
|---|---|---|
| OpenAI Codex | Agentic coding and task-execution comparator, especially goal execution, tool use, long-running task continuation, code modification, and reviewable receipts. | Official OpenAI/Codex documentation snapshot, exact local Codex version or app build when testing, transcript/replay fixture, allowed tools, compute and wall-clock budget. |
| Anthropic Claude Code | Agentic coding and CLI comparator, especially resident terminal UX, tool permission model, subagent/task dispatch, MCP/tool integration, and clean-room parity target for ember-cli. | Official Anthropic Claude Code documentation snapshot, exact local Claude Code or avir-cli behavior map where legally usable, clean-room boundary receipt, transcript/replay fixture. |
| Hermes / NemoClaw-class agent | Candidate local/open agent substrate comparator for sandboxed tool execution and autonomous research loops. | Identity must be pinned first: exact project, version, license, capabilities, hardware assumptions, and official docs. Until then Hermes is a named placeholder, not an executable baseline. |

## Hidden-Frontier Boundary

It is plausible that frontier coding agents are used internally to improve their own tools, prompts, evaluation harnesses, data pipelines, and successor models. Public evidence can support those as agent-loop comparators only where documented. Claims that Codex, Claude Code, or Hermes directly alters its own production weights, trains its next frontier model, or rewrites its own goals are not accepted as baseline facts without a public source, local receipt, or explicitly marked hypothesis.

The baseline may still test Ember against the visible capabilities of those systems: goal ingestion, blocker selection, planning, tool execution, code edits, test repair, long-job continuation, receipt preservation, memory use, and final audit discipline.

## Required Metrics

- task success on frozen external/local tasks;
- wall-clock and GPU/CPU budget consumed;
- number of valid tool calls and invalid/repeated calls;
- ability to preserve goal constraints across compaction, crash, resume, or handoff;
- ability to discover and use existing receipts rather than recomputing;
- code-change quality under deterministic tests;
- whether self-improvement claims survive deletion/replay checks;
- human-intervention count and scope.

## Anti-Cheat Gates

- no Ember win over an agent baseline unless Codex/Claude/Hermes receive the same files, tools, budgets, and task statement;
- no counting private model capability rumors as a measured comparator;
- no using Claude Code source expression inside Ember implementation unless legal/provenance receipts permit it;
- no treating Codex goal-mode transcripts as Ember goal-mode success unless Ember itself parses, selects, acts, verifies, and persists;
- no hosted paid judge as required authority when the same rubric can be applied locally;
- no success if the agent baseline was denied the same cached receipts Ember used.

## Current Verdict

NOT RUN. The next step is to pin official sources and build a replay suite that compares Ember goal mode and ember-cli against Codex, Claude Code, and a resolved Hermes-class agent under identical task and budget constraints.