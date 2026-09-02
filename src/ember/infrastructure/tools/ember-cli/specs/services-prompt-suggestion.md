<!--
goal_id: EMBER-02
workstream_id: EMBER-02A
next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
-->

# Spec — prompt-suggestion service (task #48)

Status: SHIPPED — implemented as src/services/prompt-suggestion.ts (+ prompt-suggestion.test.ts), landed via PR #199. Spec retained as the component's spec node per issue #567. The original avir-cli had 29 features across these two files (promptSuggestion.ts:
11, speculation.ts: 18). This spec derives behavior from the behavioral mapping only —
never from the predecessor source tree.

Consumer: `src/ember/infrastructure/tools/ember-cli/src/services/prompt-suggestion.ts`
Consumer: `src/ember/infrastructure/tools/ember-cli/src/services/speculation.ts`

Clean-room: build from THIS spec + existing ember-cli interfaces only. No founder/user
names, no predecessor-stack lineage, no avir-cli vendor names in code or comments.

Coordination: this service is POST-SAMPLING ONLY. The query engine calls
`executePromptSuggestion` as a background fire-and-forget hook after each assistant
response. No upstream wiring changes are needed today; wire into the query post-sampling
hook in a follow-on task.

---

## File 1 — `services/prompt-suggestion.ts`

### Types / constants

```ts
export type PromptVariant = "user_intent" | "stated_intent";

// Maximum uncached parent tokens before we skip suggestion generation.
const MAX_PARENT_UNCACHED_TOKENS = 10_000;

// Module-level abort controller for the current in-flight suggestion.
let currentAbortController: AbortController | null = null;

// Prompt strings keyed by PromptVariant — predict the user's natural next input.
// Must reject evaluative text, meta-commentary, and Claude-voice phrasing.
const SUGGESTION_PROMPTS: Record<PromptVariant, string> = {
  user_intent: "<system prompt asking model to predict next user input as user_intent>",
  stated_intent: "<alternate prompt>",
};
```

### `getPromptVariant(): PromptVariant`
Returns `"user_intent"` (currently hardcoded; `"stated_intent"` available for future
A/B testing). Pure function, no side effects.

### `shouldEnablePromptSuggestion(): boolean`
Feature gate. Checks in order:
1. Env override: `PROMPT_SUGGESTION_ENABLED` (truthy/falsy string) → return early.
2. Feature flag: `tengu_chomp_inflection` from globalConfig (default false) → disabled.
3. Session type: not in non-interactive modes (print/piped/SDK) → disabled.
4. Team context: not a swarm teammate (only the leader shows suggestions) → disabled.
5. User settings: `promptSuggestionEnabled` (from config store, default true).
Logs an event for each enable/disable reason. Returns boolean.

### `abortPromptSuggestion(): void`
Cancels any in-flight suggestion. Calls `currentAbortController.abort()` if the
controller exists, then nullifies it. Idempotent.

### `getParentCacheSuppressReason(lastAssistantMessage: Message): string | null`
Checks whether the parent request's uncached tokens exceed the threshold.
- Extracts `message.usage` from the last assistant message.
- Computes `input_tokens + cache_creation_input_tokens + output_tokens`.
- Returns `"cache_cold"` if the sum > `MAX_PARENT_UNCACHED_TOKENS`, else `null`.

### `getSuggestionSuppressReason(appState: AppState): string | null`
Returns the suppression reason string if suggestions should be skipped, else null.
Suppression conditions (checked in order):
- `"disabled"`: feature disabled in settings.
- `"pending_permission"`: worker or sandbox permission request is pending.
- `"elicitation_active"`: elicitation queue has items.
- `"plan_mode"`: tool permission mode is `"plan"`.
- `"rate_limit"`: user is external and rate limit status is not `"allowed"`.

### `shouldFilterSuggestion(suggestion: string | null, promptId: PromptVariant, source?: string): boolean`
Returns true (filter out) if the suggestion fails any quality criterion. Checked in order:
1. `done` — exact string `"done"`.
2. `meta_text` — matches patterns like "nothing found", "silence", "no input", etc.
3. `meta_wrapped` — wrapped in parentheses or square brackets.
4. `error_message` — looks like an API error response.
5. `prefixed_label` — starts with `"label: "` or similar prefix.
6. `too_few_words` — fewer than 2 words, EXCEPT single-word affirmatives (`"yes"`, `"ok"`),
   actions (`"push"`, `"commit"`), negations (`"no"`).
7. `too_many_words` — more than 12 words.
8. `too_long` — 100 or more characters.
9. `multiple_sentences` — contains sentence-ending punctuation followed by an uppercase letter.
10. `has_formatting` — contains newlines, asterisks, or bold markers.
11. `evaluative` — contains gratitude/approval words (great, thanks, nice, perfect, etc.).
12. `claude_voice` — starts with model-speaking phrases: "Let me", "I'll", "Here's",
    "Sure", "Of course", "I can", "I will", "I'd", etc.
Logs the suppression reason. Returns boolean.

### `generateSuggestion(abortController: AbortController, promptId: PromptVariant, cacheSafeParams: object): Promise<{ suggestion: string | null; generationRequestId: string | null }>`
Async. Runs a forked agent to generate the next predicted user input.
- Agent config: `SUGGESTION_PROMPTS[promptId]` as system prompt.
- Tool callback: denies all tools unconditionally.
- NO `effortValue` or `maxOutputTokens` overrides (would bust the cache).
- `skipTranscript: true`, `skipCacheWrite: true`.
- Scans ALL returned messages for the first text block (model may loop on denied tools).
- Returns `{ suggestion, generationRequestId }` from the first non-empty text block found.
- Returns `{ suggestion: null, generationRequestId: null }` if no text found.

### `tryGenerateSuggestion(abortController: AbortController, messages: Message[], getAppState: () => AppState, cacheSafeParams: object, source?: string): Promise<{ suggestion: string; promptId: PromptVariant; generationRequestId: string } | null>`
Main entry point. Guards + shared logic for CLI/SDK paths.
Guard sequence (abort on first failure, returns null):
1. Check `abortController.signal.aborted`.
2. Require ≥ 2 assistant turns in messages (early conversation).
3. Check if last assistant message is an error.
4. Check `getParentCacheSuppressReason(lastAssistantMessage)`.
5. Check `getSuggestionSuppressReason(getAppState())`.
6. Apply any additional filter rules.
If all guards pass:
- Call `generateSuggestion(abortController, promptId, cacheSafeParams)`.
- Re-check `abortController.signal.aborted`.
- Apply `shouldFilterSuggestion(result.suggestion, promptId, source)`.
- Return the result object or null.
Logs suppression events for diagnostics.

### `executePromptSuggestion(context: REPLHookContext): Promise<void>`
Post-sampling hook. CLI entry point.
- Creates a new `AbortController`; stores as `currentAbortController`.
- Calls `tryGenerateSuggestion(...)`.
- On success: updates app state with the suggestion.
- If suggestion is valid and speculation is enabled: calls `startSpeculation()`.
- Error handling: silently ignores `AbortError`; logs all other errors via `logError`.
- Fire-and-forget: the caller does not await this.

### `logSuggestionOutcome(suggestion: string, userInput: string, emittedAt: number, promptId: PromptVariant, generationRequestId: string): void`
Analytics event. Records whether the user accepted or ignored the suggestion.
- `outcome`: `"accepted"` if `userInput === suggestion`, else `"ignored"`.
- `timeToAcceptMs` / `timeToIgnoreMs`: `Date.now() - emittedAt`.
- `similarity`: `userInput.length / suggestion.length`.
- Internal-only (ant): also logs the raw suggestion and userInput strings.

### `logSuggestionSuppressed(reason: string, suggestion?: string, promptId?: PromptVariant, source?: string): void`
Analytics event. Records suppression reason.
- Fields: `outcome: "suppressed"`, `reason`.
- Resolves `promptId` to current variant if omitted.

---

## File 2 — `services/speculation.ts`

Speculation is a pre-execution overlay: after a suggestion is shown and accepted by the
user, the system has already speculatively run the agent on the predicted input in a
copy-on-write filesystem overlay. If the speculation completed before the user confirmed,
the response is instant.

### Types

```ts
export type ActiveSpeculationState = Extract<SpeculationState, { status: 'active' }>;
```

### `safeRemoveOverlay(overlayPath: string): void`
Safely removes the speculation overlay directory. Uses `fs.rm()` with
`{ recursive: true, force: true, maxRetries: 3, retryDelay: 100 }`. Errors are silently
ignored (overlay cleanup is best-effort).

### `getOverlayPath(id: string): string`
Computes the overlay directory: `{claudeTempDir}/speculation/{pid}/{id}`.

### `denySpeculation(message: string, reason: string): { behavior: 'deny'; message: string; decisionReason: string }`
Constructs the tool-denial response used inside speculation. Pure function.

### `copyOverlayToMain(overlayPath: string, writtenPaths: Set<string>, cwd: string): Promise<boolean>`
Copies files written during speculation back to the main working directory.
- For each path in `writtenPaths`: copies `overlayPath/path` → `cwd/path`.
- Creates parent directories as needed.
- Returns `true` if all copies succeeded; `false` if any failed.
- Logs individual copy failures but does not throw.

### `logSpeculation(id: string, outcome: 'accepted' | 'aborted' | 'error', startTime: number, suggestionLength: number, messages: Message[], boundary: SpeculationBoundary | null, extras?: object): void`
Analytics. Records speculation metrics:
- `duration_ms`: elapsed since `startTime`.
- `suggestion_length`: `suggestionLength`.
- `tools_executed`: count of successful tool results in messages.
- `completed`: `boundary !== null`.
- `boundary_type`, `boundary_tool`, `boundary_detail`: extracted from boundary if present.
- `extras`: merged into the log event (e.g. `error_type`, `error_phase`, `is_pipelined`).

### `countToolsInMessages(messages: Message[]): number`
Counts successful tool result blocks across all messages.
Filters for blocks where `type === 'tool_result'` and `!is_error`.

### `getBoundaryTool(boundary: SpeculationBoundary): string | null`
Extracts tool name from a speculation boundary object. Returns null for non-tool
boundaries.

### `getBoundaryDetail(boundary: SpeculationBoundary): string | null`
Extracts boundary detail (command, path, etc.) from the boundary object.

### `isUserMessageWithArrayContent(m: Message): boolean`
Type guard. Returns true if `m.role === 'user'` and `Array.isArray(m.content)`.

### `isSpeculationEnabled(): boolean`
Feature gate.
- `USER_TYPE === 'ant'` AND `globalConfig.speculationEnabled ?? true`.
- Logs a debug message with the result.

### `resetSpeculationState(setAppState: AppStateSetter): void`
Clears speculation state: calls `setAppState` with `IDLE_SPECULATION_STATE`.

### `updateActiveSpeculationState(setAppState: AppStateSetter, updater: (s: ActiveSpeculationState) => ActiveSpeculationState): void`
Updates active speculation state only if current status is `'active'`. Checks for
no-op updates (deep equality) before triggering re-render.

### `prepareMessagesForInjection(messages: Message[]): Message[]`
Cleans messages before injecting speculation results into the main conversation.
Filtering rules (applied in order):
- Remove all `thinking` and `redacted_thinking` blocks.
- Remove `tool_use` blocks that have no matching successful `tool_result`.
- Remove `tool_result` blocks whose corresponding `tool_use` was removed.
- Remove interrupt messages (`INTERRUPT_MESSAGE`, `INTERRUPT_MESSAGE_FOR_TOOL_USE`).
- Drop messages that contain only whitespace text after filtering.
Returns the array of non-null, non-empty messages.

### `createSpeculationFeedbackMessage(messages: Message[], boundary: SpeculationBoundary | null, timeSavedMs: number, sessionTotalMs: number): Message | null`
Builds a system message showing speculation stats (internal-only feature).
Format: `"Speculated N tool uses · M tokens · +Xs saved (Ys this session)"`.
Returns `null` for non-internal users or when message count is zero.

### `generatePipelinedSuggestion(context: REPLHookContext, suggestionText: string, speculatedMessages: Message[], setAppState: AppStateSetter, parentAbortController: AbortController): Promise<void>`
Generates the next suggestion while the user decides whether to accept the current
speculation. Fire-and-forget.
- Creates augmented context: current messages + suggestion + speculated messages.
- Checks suppression reasons; skips if suppressed.
- Calls `tryGenerateSuggestion()` on the augmented context.
- Applies `shouldFilterSuggestion()`.
- On success: updates app state with pipelined suggestion.
- Logs but does not rethrow errors.

### `startSpeculation(suggestionText: string, context: REPLHookContext, setAppState: AppStateSetter, isPipelined?: boolean, cacheSafeParams?: object): Promise<void>`
Async task initiator. Starts a forked agent on the predicted user input.
**Abort conditions before start:**
- Existing speculation is running → abort it first.
- ≥ 100 messages accumulated → skip.
- ≥ 20 turns → skip (maxTurns).
**Overlay:**
- Creates directory at `getOverlayPath(id)`.
- Sets active speculation state with the new abort controller.
**canUseTool logic (overlay-aware):**
- `Read`, `Glob`, `Grep`, `ToolSearch`, `LSP`, `TaskGet`, `TaskList` → allowed with
  the main CWD (reads see main tree; do not redirect to overlay).
- `Edit`, `Write`, `NotebookEdit` → allowed only if permission mode permits or in plan
  mode with bypassPermissions; first read of a path sees the main tree; subsequent writes
  go into the overlay and are tracked in `writtenPaths`.
- `Bash` → allowed only if the command is read-only (no `cd`, no writes, no network).
- All other tools → denied via `denySpeculation()`.
**Boundary detection (stops speculation):**
- Non-readonly Bash → set boundary `{ type: 'bash' }`, abort.
- File edit in non-acceptEdits mode → set boundary `{ type: 'edit', ... }`, abort.
- Any other non-read tool → set boundary `{ type: tool }`, abort.
**Onmessage callback:** tracks messages and tool use count for UI display.
**On completion:**
- Calls `generatePipelinedSuggestion()` with the speculated messages.
**Error handling:** catches `AbortError` (expected), logs others, removes overlay, resets
state.

### `acceptSpeculation(state: SpeculationState, setAppState: AppStateSetter, cleanMessageCount: number): Promise<SpeculationResult | null>`
Finalizes and accepts the current speculation.
- Returns `null` if `state.status !== 'active'`.
- Aborts the speculation abort controller.
- If `cleanMessageCount > 0`: calls `copyOverlayToMain(state.overlayPath, state.writtenPaths, cwd)`.
- Removes overlay directory.
- Appends a `speculation-accept` entry to the transcript.
- Resets speculation state.
- Updates session time-saved counter.
Returns `SpeculationResult { messages, boundary, timeSavedMs }`.
Logs event with message count, time saved, and completion boundary.

### `abortSpeculation(setAppState: AppStateSetter): void`
Aborts current speculation (user typed before it was accepted).
- Calls `state.abortController.abort()`.
- Removes overlay directory.
- Logs speculation event with `abort_reason: 'user_typed'`.
- Resets speculation state.

### `handleSpeculationAccept(speculationState: SpeculationState, speculationSessionTimeSavedMs: number, setAppState: AppStateSetter, input: string, deps: { setMessages, readFileState, cwd }): Promise<{ queryRequired: boolean }>`
Integrates accepted speculation into the main conversation.
Message injection order:
1. User message (instant visual feedback).
2. Speculated messages (cleaned via `prepareMessagesForInjection`).
3. Feedback message (from `createSpeculationFeedbackMessage`).
Completion detection:
- If `boundary.type === 'complete'` → no API call needed; return `{ queryRequired: false }`.
- Otherwise → drop trailing assistant messages (model cannot prefill last assistant turn);
  return `{ queryRequired: true }`.
Pipelined promotion:
- If speculation completed AND has a pipelined suggestion → promote to active suggestion
  state + start new speculation on the pipelined suggestion.
Error handling: logs error, resets state, returns `{ queryRequired: true }` (safe fallback).
**Side effects:** clears prompt suggestion state, merges file-state caches from speculation.

---

## Tests

Files: `prompt-suggestion.test.ts`, `speculation.test.ts`.
- CPU-only. No model, no GPU, no real agent execution.
- Drive channels with fixture JSONL at temp paths.
- Existing suite must remain green (tsc=0, no new failures beyond the known AC1 process-entry failure).

### AC1 — `shouldFilterSuggestion` (prompt-suggestion.test.ts)
All 12 filter rules fire on matching inputs and pass on non-matching inputs.
One assertion per rule per direction (12 × 2 = 24 assertions minimum).

### AC2 — `getSuggestionSuppressReason` (prompt-suggestion.test.ts)
Each of the 5 suppression conditions returns the correct reason string.
Returns null when none apply.

### AC3 — `getParentCacheSuppressReason` (prompt-suggestion.test.ts)
Returns `"cache_cold"` when uncached sum > 10k; null otherwise.

### AC4 — `tryGenerateSuggestion` guard sequence (prompt-suggestion.test.ts)
Mock `generateSuggestion` to return a fixture suggestion. Verify each guard returns
null when the guard condition is true (aborted signal, <2 turns, error message, etc.).

### AC5 — `prepareMessagesForInjection` (speculation.test.ts)
Fixture messages with thinking blocks, orphan tool_use/result pairs, interrupt messages,
whitespace-only content. Verify the output is clean.

### AC6 — `copyOverlayToMain` (speculation.test.ts)
Creates temp overlay with one file; verifies it is copied to a temp main dir.

### AC7 — `shouldFilterSuggestion` on speculation output (speculation.test.ts)
Verify `claude_voice` and `evaluative` filters fire on speculation-produced text.

---

## NOT in this spec (follow-on)

- Wiring: integrating `executePromptSuggestion` into the query engine's post-sampling hook.
- The real `generateSuggestion` forked-agent implementation (requires the agent API).
- The `startSpeculation` integration with the real overlay filesystem at live GPU time.
- Pipelining performance tuning.
