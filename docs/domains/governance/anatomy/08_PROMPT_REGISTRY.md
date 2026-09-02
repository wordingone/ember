# 08 — Prompt Registry

## Current status: does not exist yet

A search of this repository (`grep -ri "prompt_registry\|PromptRegistry" --include=*.py --include=*.ts .`)
finds **no** dedicated prompt-registry module, class, or directory. This is
stated plainly rather than invented, per this doc set's authoring rule
(never write aspirational anatomy).

## What exists instead: scattered, inline prompts

Prompt/instruction text that exists today lives inline, scattered across
call sites rather than centrally registered:
- Agent/tool instruction text embedded directly in TypeScript sources under
  `tools/ember-cli/src/` (e.g. `goal-continuation-prompt.ts`, whose name
  suggests a single-purpose prompt template, not a general registry).
- Evaluation-harness prompt/instruction construction inline inside the
  `scripts/ember_restart_eval_*.py` family (each evaluator builds its own
  prompt text for its benchmark, per-file, not from a shared source).
- Cognitive-mode / operator-protocol text embedded in
  `src/ember/governance/scripts/ember_cognitive_mode_policy.py` and related mode-selector modules.

None of these share a common loader, versioning scheme, or content-hash
binding — each is a standalone template owned by its call site.

## What a real prompt registry would need (design note, not a build claim)

If/when this is built, it should follow the same discipline as the rest of
this repo's evidence surfaces: a registry module that resolves prompts by a
stable id, returns byte-identical text for a given id+version, and is
sha256-pinned the same way `_lane14_common.check_path_sha_pairs` pins other
source files referenced by receipts (see 12_COCKPIT_OBSERVATORY.md for a
worked example of that pattern). This paragraph is a design note only — no
such module is claimed to exist.

## Current gaps — honestly stated

No board condition currently tracks a prompt registry directly. This doc
exists to satisfy C-ANAT's presence requirement for the `08_` prefix
honestly: by describing the real (scattered, unregistered) state of prompt
text in this repo, not by fabricating a registry that isn't there.
