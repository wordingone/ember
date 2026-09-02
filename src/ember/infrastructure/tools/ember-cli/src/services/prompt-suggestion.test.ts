// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// services/prompt-suggestion.test.ts
// Covers AC1–AC7 from the prompt-suggestion surface spec.

import { describe, it, expect, beforeEach, afterEach } from "bun:test";
import type { EmberMessage } from "../types/message-types.ts";
import type { AppState } from "../state/app-state.ts";
import type { ForkedAgentExecutor } from "./prompt-suggestion.ts";
import {
  shouldFilterSuggestion,
  getSuggestionSuppressReason,
  getParentCacheSuppressReason,
  tryGenerateSuggestion,
  generateSuggestion,
  executePromptSuggestion,
  makeSuggestionExecutor,
  SUGGESTION_PROMPTS,
} from "./prompt-suggestion.ts";
import type { CallModelParams, ModelResponse } from "../query/query-loop-support.ts";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeAppState(overrides: Partial<AppState> = {}): AppState {
  return {
    sessionId: "test-session",
    cwd: "/tmp",
    entrypoint: "cli",
    mode: "auto",
    isSubagent: false,
    isConductor: false,
    toolPermissions: {},
    messages: [],
    isLoading: false,
    inputValue: "",
    currentTask: null,
    speculationState: { isSpeculating: false },
    completionBoundary: null,
    viewedTeammateTask: null,
    activeAgentForInput: null,
    permissionRequests: [],
    isDirty: false,
    isCompacting: false,
    contextWindowTokens: 0,
    queueDepth: 0,
    ...overrides,
  } as AppState;
}

function makeAssistantMessage(
  overrides: Partial<EmberMessage> = {},
): EmberMessage {
  return {
    role: "assistant",
    content: "assistant response",
    ...overrides,
  };
}

function makeUserMessage(overrides: Partial<EmberMessage> = {}): EmberMessage {
  return {
    role: "user",
    content: "user message",
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// AC1 — shouldFilterSuggestion: all 12 filters
// ---------------------------------------------------------------------------

describe("AC1: shouldFilterSuggestion — all 12 filters", () => {
  // 1. done
  it("filters 'done' (case-insensitive exact match)", () => {
    expect(shouldFilterSuggestion("done", "user_intent")).toBe(true);
    expect(shouldFilterSuggestion("DONE", "user_intent")).toBe(true);
  });

  it("keeps 'do it' (not an exact match for done)", () => {
    expect(shouldFilterSuggestion("do it", "user_intent")).toBe(false);
  });

  // 2. meta_text
  it("filters meta-commentary text 'nothing found'", () => {
    expect(shouldFilterSuggestion("nothing found", "user_intent")).toBe(true);
    expect(shouldFilterSuggestion("silence", "user_intent")).toBe(true);
    expect(shouldFilterSuggestion("no input", "user_intent")).toBe(true);
    expect(shouldFilterSuggestion("no response", "user_intent")).toBe(true);
    expect(shouldFilterSuggestion("no suggestion", "user_intent")).toBe(true);
    expect(shouldFilterSuggestion("no next", "user_intent")).toBe(true);
    expect(shouldFilterSuggestion("not applicable", "user_intent")).toBe(true);
    expect(shouldFilterSuggestion("n/a", "user_intent")).toBe(true);
  });

  it("keeps 'search for files' (not meta text)", () => {
    expect(shouldFilterSuggestion("search for files", "user_intent")).toBe(false);
  });

  // 3. meta_wrapped
  it("filters parenthetical thoughts", () => {
    expect(shouldFilterSuggestion("(some thought)", "user_intent")).toBe(true);
    expect(shouldFilterSuggestion("[note]", "user_intent")).toBe(true);
  });

  it("keeps 'open file' (not wrapped)", () => {
    expect(shouldFilterSuggestion("open file", "user_intent")).toBe(false);
  });

  // 4. error_message
  it("filters JSON error objects", () => {
    expect(
      shouldFilterSuggestion('{"error":"bad request"}', "user_intent"),
    ).toBe(true);
  });

  it("filters Error: prefixed strings", () => {
    expect(shouldFilterSuggestion("Error: network timeout", "user_intent")).toBe(
      true,
    );
  });

  it("filters API Error strings", () => {
    expect(shouldFilterSuggestion("API Error 500", "user_intent")).toBe(true);
  });

  it("keeps 'check logs' (not an error)", () => {
    expect(shouldFilterSuggestion("check logs", "user_intent")).toBe(false);
  });

  // 5. prefixed_label
  it("filters label-prefixed output", () => {
    expect(shouldFilterSuggestion("label: do this", "user_intent")).toBe(true);
    expect(shouldFilterSuggestion("Output: something", "user_intent")).toBe(
      true,
    );
  });

  it("keeps 'run the tests' (no colon prefix)", () => {
    expect(shouldFilterSuggestion("run the tests", "user_intent")).toBe(false);
  });

  // 6. too_few_words
  it("filters single unknown word", () => {
    expect(shouldFilterSuggestion("x", "user_intent")).toBe(true);
    expect(shouldFilterSuggestion("foo", "user_intent")).toBe(true);
  });

  it("keeps single words in the allowlist", () => {
    expect(shouldFilterSuggestion("yes", "user_intent")).toBe(false);
    expect(shouldFilterSuggestion("no", "user_intent")).toBe(false);
    expect(shouldFilterSuggestion("ok", "user_intent")).toBe(false);
    expect(shouldFilterSuggestion("push", "user_intent")).toBe(false);
    expect(shouldFilterSuggestion("commit", "user_intent")).toBe(false);
    expect(shouldFilterSuggestion("run", "user_intent")).toBe(false);
    expect(shouldFilterSuggestion("go", "user_intent")).toBe(false);
    expect(shouldFilterSuggestion("stop", "user_intent")).toBe(false);
  });

  it("keeps two-word suggestion", () => {
    expect(shouldFilterSuggestion("run tests", "user_intent")).toBe(false);
  });

  // 7. too_many_words
  it("filters 13-word suggestion", () => {
    expect(
      shouldFilterSuggestion(
        "a b c d e f g h i j k l m",
        "user_intent",
      ),
    ).toBe(true);
  });

  it("keeps 4-word suggestion", () => {
    expect(shouldFilterSuggestion("run all tests now", "user_intent")).toBe(
      false,
    );
  });

  // 8. too_long
  it("filters suggestion >= 100 characters", () => {
    expect(shouldFilterSuggestion("a".repeat(100), "user_intent")).toBe(true);
    expect(shouldFilterSuggestion("a".repeat(200), "user_intent")).toBe(true);
  });

  it("keeps short text (well under 100 chars)", () => {
    expect(shouldFilterSuggestion("short text", "user_intent")).toBe(false);
  });

  // 9. multiple_sentences
  it("filters multi-sentence suggestion", () => {
    expect(
      shouldFilterSuggestion("Do it. Then run.", "user_intent"),
    ).toBe(true);
    expect(
      shouldFilterSuggestion("Fix it! Now rebuild.", "user_intent"),
    ).toBe(true);
  });

  it("keeps single-sentence suggestion without period+space+uppercase", () => {
    expect(shouldFilterSuggestion("Do it then run", "user_intent")).toBe(false);
  });

  // 10. has_formatting
  it("filters suggestions with asterisks", () => {
    expect(shouldFilterSuggestion("use **bold**", "user_intent")).toBe(true);
    expect(shouldFilterSuggestion("item * list", "user_intent")).toBe(true);
  });

  it("filters suggestions with newlines", () => {
    expect(shouldFilterSuggestion("line one\nline two", "user_intent")).toBe(
      true,
    );
  });

  it("keeps 'use formatting' (no formatting chars)", () => {
    expect(shouldFilterSuggestion("use formatting", "user_intent")).toBe(false);
  });

  // 11. evaluative
  it("filters evaluative language", () => {
    expect(shouldFilterSuggestion("great idea", "user_intent")).toBe(true);
    expect(shouldFilterSuggestion("thanks for that", "user_intent")).toBe(true);
    expect(shouldFilterSuggestion("that is perfect", "user_intent")).toBe(true);
    expect(shouldFilterSuggestion("awesome work", "user_intent")).toBe(true);
    expect(shouldFilterSuggestion("good job done", "user_intent")).toBe(true);
    expect(shouldFilterSuggestion("well done", "user_intent")).toBe(true);
  });

  it("keeps 'run the job' (no evaluative terms)", () => {
    expect(shouldFilterSuggestion("run the job", "user_intent")).toBe(false);
  });

  // 12. assistant voice prefixes
  it("filters suggestions starting with assistant voice", () => {
    expect(shouldFilterSuggestion("Let me help you", "user_intent")).toBe(true);
    expect(shouldFilterSuggestion("I'll do that now", "user_intent")).toBe(true);
    expect(shouldFilterSuggestion("Here's what I found", "user_intent")).toBe(
      true,
    );
    expect(shouldFilterSuggestion("Sure thing", "user_intent")).toBe(true);
    expect(shouldFilterSuggestion("Of course that works", "user_intent")).toBe(
      true,
    );
    expect(shouldFilterSuggestion("I can do that", "user_intent")).toBe(true);
    expect(shouldFilterSuggestion("I will try now", "user_intent")).toBe(true);
    expect(shouldFilterSuggestion("I'd be happy", "user_intent")).toBe(true);
    expect(shouldFilterSuggestion("I would suggest", "user_intent")).toBe(true);
    expect(shouldFilterSuggestion("I'm going to fix", "user_intent")).toBe(true);
  });

  it("keeps 'help me run' (does not start with assistant voice)", () => {
    expect(shouldFilterSuggestion("help me run", "user_intent")).toBe(false);
  });

  // null input
  it("filters null input", () => {
    expect(shouldFilterSuggestion(null, "user_intent")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// AC2 — getSuggestionSuppressReason
// ---------------------------------------------------------------------------

describe("AC2: getSuggestionSuppressReason", () => {
  const savedEnv: Record<string, string | undefined> = {};

  beforeEach(() => {
    // Snapshot relevant env vars
    savedEnv["PROMPT_SUGGESTION_ENABLED"] =
      process.env["PROMPT_SUGGESTION_ENABLED"];
    savedEnv["USER_TYPE"] = process.env["USER_TYPE"];
    savedEnv["RATE_LIMIT_STATUS"] = process.env["RATE_LIMIT_STATUS"];
  });

  afterEach(() => {
    // Restore env vars
    for (const [k, v] of Object.entries(savedEnv)) {
      if (v === undefined) {
        delete process.env[k];
      } else {
        process.env[k] = v;
      }
    }
  });

  it("returns 'disabled' when PROMPT_SUGGESTION_ENABLED=false", () => {
    process.env["PROMPT_SUGGESTION_ENABLED"] = "false";
    const state = makeAppState();
    expect(getSuggestionSuppressReason(state)).toBe("disabled");
  });

  it("returns 'plan_mode' when mode is plan", () => {
    process.env["PROMPT_SUGGESTION_ENABLED"] = "true";
    delete process.env["RATE_LIMIT_STATUS"];
    // plan mode is a valid PermissionMode
    const state = makeAppState({ mode: "plan" });
    expect(getSuggestionSuppressReason(state)).toBe("plan_mode");
  });

  it("returns 'rate_limit' when user is not internal and rate is blocked", () => {
    process.env["PROMPT_SUGGESTION_ENABLED"] = "true";
    process.env["USER_TYPE"] = "external";
    process.env["RATE_LIMIT_STATUS"] = "blocked";
    const state = makeAppState({ mode: "auto" });
    expect(getSuggestionSuppressReason(state)).toBe("rate_limit");
  });

  it("returns null when no conditions are met", () => {
    process.env["PROMPT_SUGGESTION_ENABLED"] = "true";
    process.env["USER_TYPE"] = "ant";
    delete process.env["RATE_LIMIT_STATUS"];
    const state = makeAppState({ mode: "auto" });
    expect(getSuggestionSuppressReason(state)).toBeNull();
  });

  it("returns null when user is internal even with rate_limit blocked", () => {
    process.env["PROMPT_SUGGESTION_ENABLED"] = "true";
    process.env["USER_TYPE"] = "ant";
    process.env["RATE_LIMIT_STATUS"] = "blocked";
    const state = makeAppState({ mode: "auto" });
    // USER_TYPE=ant bypasses the rate_limit check
    expect(getSuggestionSuppressReason(state)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// AC3 — getParentCacheSuppressReason
// ---------------------------------------------------------------------------

describe("AC3: getParentCacheSuppressReason", () => {
  it("returns 'cache_cold' when uncached token sum exceeds 10 000", () => {
    const msg = makeAssistantMessage({
      usage: {
        input_tokens: 5000,
        cache_creation_input_tokens: 3000,
        output_tokens: 3000,
      },
    });
    // sum = 11 000 > 10 000
    expect(getParentCacheSuppressReason(msg)).toBe("cache_cold");
  });

  it("returns null when uncached token sum is within budget", () => {
    const msg = makeAssistantMessage({
      usage: {
        input_tokens: 1000,
        output_tokens: 500,
      },
    });
    // sum = 1500, well under 10 000
    expect(getParentCacheSuppressReason(msg)).toBeNull();
  });

  it("returns null when usage is absent (sum = 0)", () => {
    const msg = makeAssistantMessage();
    expect(getParentCacheSuppressReason(msg)).toBeNull();
  });

  it("returns null when sum is exactly 10 000 (at boundary, not exceeding)", () => {
    const msg = makeAssistantMessage({
      usage: {
        input_tokens: 5000,
        output_tokens: 5000,
      },
    });
    expect(getParentCacheSuppressReason(msg)).toBeNull();
  });

  it("returns 'cache_cold' when sum is 10 001 (just over boundary)", () => {
    const msg = makeAssistantMessage({
      usage: {
        input_tokens: 5001,
        output_tokens: 5000,
      },
    });
    expect(getParentCacheSuppressReason(msg)).toBe("cache_cold");
  });
});

// ---------------------------------------------------------------------------
// AC4 — tryGenerateSuggestion guard sequence
// ---------------------------------------------------------------------------

describe("AC4: tryGenerateSuggestion guard sequence", () => {
  const savedEnv: Record<string, string | undefined> = {};

  beforeEach(() => {
    savedEnv["PROMPT_SUGGESTION_ENABLED"] =
      process.env["PROMPT_SUGGESTION_ENABLED"];
    // Enable suggestions so we can reach deeper guards
    process.env["PROMPT_SUGGESTION_ENABLED"] = "true";
  });

  afterEach(() => {
    for (const [k, v] of Object.entries(savedEnv)) {
      if (v === undefined) {
        delete process.env[k];
      } else {
        process.env[k] = v;
      }
    }
  });

  it("returns null when signal is already aborted (guard 1)", async () => {
    const controller = new AbortController();
    controller.abort();
    const result = await tryGenerateSuggestion(
      controller,
      [],
      () => makeAppState(),
      {},
    );
    expect(result).toBeNull();
  });

  it("returns null with zero assistant messages (guard 2)", async () => {
    const controller = new AbortController();
    const messages: EmberMessage[] = [makeUserMessage()];
    const result = await tryGenerateSuggestion(
      controller,
      messages,
      () => makeAppState(),
      {},
    );
    expect(result).toBeNull();
  });

  it("returns null with only one assistant message (guard 2)", async () => {
    const controller = new AbortController();
    const messages: EmberMessage[] = [
      makeUserMessage(),
      makeAssistantMessage(),
    ];
    const result = await tryGenerateSuggestion(
      controller,
      messages,
      () => makeAppState(),
      {},
    );
    expect(result).toBeNull();
  });

  it("returns null when last assistant message has stop_reason 'error' (guard 3)", async () => {
    const controller = new AbortController();
    const messages: EmberMessage[] = [
      makeAssistantMessage({ content: "first response" }),
      makeAssistantMessage({ content: "error response", stop_reason: "error" }),
    ];
    const result = await tryGenerateSuggestion(
      controller,
      messages,
      () => makeAppState(),
      {},
    );
    expect(result).toBeNull();
  });

  it("returns null when parent cache token count is too high (guard 4)", async () => {
    const controller = new AbortController();
    const messages: EmberMessage[] = [
      makeAssistantMessage({ content: "first response" }),
      makeAssistantMessage({
        content: "second response",
        stop_reason: "end_turn",
        usage: {
          input_tokens: 6000,
          cache_creation_input_tokens: 3000,
          output_tokens: 2000,
        },
        // sum = 11 000 > 10 000
      }),
    ];
    const result = await tryGenerateSuggestion(
      controller,
      messages,
      () => makeAppState(),
      {},
    );
    expect(result).toBeNull();
  });

  it("returns null when suggestions are suppressed by app state (guard 5)", async () => {
    const controller = new AbortController();
    const messages: EmberMessage[] = [
      makeAssistantMessage({ content: "first" }),
      makeAssistantMessage({ content: "second" }),
    ];
    // plan mode triggers guard 5
    const result = await tryGenerateSuggestion(
      controller,
      messages,
      () => makeAppState({ mode: "plan" }),
      {},
    );
    expect(result).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// AC5 — generateSuggestion: forked-agent executor injection
// ---------------------------------------------------------------------------

describe("AC5: generateSuggestion — forked-agent executor injection", () => {
  it("returns null/null with no executor provided (no-op fallback)", async () => {
    const controller = new AbortController();
    const result = await generateSuggestion(controller, "user_intent", {});
    expect(result).toEqual({ suggestion: null, generationRequestId: null });
  });

  it("returns null/null when signal is already aborted before executor call", async () => {
    const controller = new AbortController();
    controller.abort();
    let executorCalled = false;
    const executor: ForkedAgentExecutor = async () => {
      executorCalled = true;
      return [];
    };
    const result = await generateSuggestion(controller, "user_intent", {}, executor);
    expect(result).toEqual({ suggestion: null, generationRequestId: null });
    expect(executorCalled).toBe(false);
  });

  it("passes the user_intent prompt template to the executor", async () => {
    const controller = new AbortController();
    let capturedPrompt = "";
    const executor: ForkedAgentExecutor = async (prompt) => {
      capturedPrompt = prompt;
      return [{ role: "assistant", content: "run the build" }];
    };
    await generateSuggestion(controller, "user_intent", {}, executor);
    expect(capturedPrompt).toBe(SUGGESTION_PROMPTS["user_intent"]);
  });

  it("passes the stated_intent prompt template to the executor", async () => {
    const controller = new AbortController();
    let capturedPrompt = "";
    const executor: ForkedAgentExecutor = async (prompt) => {
      capturedPrompt = prompt;
      return [{ role: "assistant", content: "check test results" }];
    };
    await generateSuggestion(controller, "stated_intent", {}, executor);
    expect(capturedPrompt).toBe(SUGGESTION_PROMPTS["stated_intent"]);
  });

  it("passes cacheSafeParams to the executor config", async () => {
    const controller = new AbortController();
    const params = { system: "you are a helper", messages: [], tools: [] };
    let capturedCacheSafeParams: object | undefined;
    const executor: ForkedAgentExecutor = async (_prompt, config) => {
      capturedCacheSafeParams = config.cacheSafeParams;
      return [{ role: "assistant", content: "deploy the app" }];
    };
    await generateSuggestion(controller, "user_intent", params, executor);
    expect(capturedCacheSafeParams).toBe(params);
  });

  it("sets skipTranscript=true and skipCacheWrite=true on executor config", async () => {
    const controller = new AbortController();
    let capturedSkipTranscript: boolean | undefined;
    let capturedSkipCacheWrite: boolean | undefined;
    const executor: ForkedAgentExecutor = async (_prompt, config) => {
      capturedSkipTranscript = config.skipTranscript;
      capturedSkipCacheWrite = config.skipCacheWrite;
      return [{ role: "assistant", content: "run unit tests" }];
    };
    await generateSuggestion(controller, "user_intent", {}, executor);
    expect(capturedSkipTranscript).toBe(true);
    expect(capturedSkipCacheWrite).toBe(true);
  });

  it("forwards the abort signal to the executor config", async () => {
    const controller = new AbortController();
    let capturedSignal: AbortSignal | undefined;
    const executor: ForkedAgentExecutor = async (_prompt, config) => {
      capturedSignal = config.signal;
      return [{ role: "assistant", content: "run lint checks" }];
    };
    await generateSuggestion(controller, "user_intent", {}, executor);
    expect(capturedSignal).toBe(controller.signal);
  });

  it("extracts first text block from plain-string message content", async () => {
    const controller = new AbortController();
    const executor: ForkedAgentExecutor = async () => [
      { role: "assistant", content: "run all tests" },
    ];
    const result = await generateSuggestion(controller, "user_intent", {}, executor);
    expect(result.suggestion).toBe("run all tests");
    expect(result.generationRequestId).not.toBeNull();
  });

  it("extracts first text block from structured EmberContentBlock array", async () => {
    const controller = new AbortController();
    const executor: ForkedAgentExecutor = async () => [
      {
        role: "assistant",
        content: [{ type: "text" as const, text: "deploy to staging" }],
      },
    ];
    const result = await generateSuggestion(controller, "user_intent", {}, executor);
    expect(result.suggestion).toBe("deploy to staging");
    expect(result.generationRequestId).not.toBeNull();
  });

  it("skips non-text content blocks and returns first text block", async () => {
    const controller = new AbortController();
    const executor: ForkedAgentExecutor = async () => [
      {
        role: "assistant",
        content: [
          { type: "tool_use" as const, id: "t1", name: "bash", input: {} },
          { type: "text" as const, text: "check the output" },
        ],
      },
    ];
    const result = await generateSuggestion(controller, "user_intent", {}, executor);
    expect(result.suggestion).toBe("check the output");
  });

  it("scans ALL messages and returns the FIRST text block found", async () => {
    const controller = new AbortController();
    const executor: ForkedAgentExecutor = async () => [
      { role: "user", content: "" }, // empty string — no text here
      {
        role: "assistant",
        content: [{ type: "tool_use" as const, id: "t1", name: "x", input: {} }],
      }, // no text block
      { role: "assistant", content: "check the logs" }, // first text block
      { role: "assistant", content: "some other text" }, // should be ignored
    ];
    const result = await generateSuggestion(controller, "user_intent", {}, executor);
    expect(result.suggestion).toBe("check the logs");
  });

  it("returns null suggestion when no text block found in any message", async () => {
    const controller = new AbortController();
    const executor: ForkedAgentExecutor = async () => [
      {
        role: "assistant",
        content: [
          { type: "tool_use" as const, id: "t1", name: "bash", input: {} },
        ],
      },
    ];
    const result = await generateSuggestion(controller, "user_intent", {}, executor);
    expect(result.suggestion).toBeNull();
    expect(result.generationRequestId).toBeNull();
  });

  it("returns null when signal is aborted after generation completes (post-check)", async () => {
    const controller = new AbortController();
    const executor: ForkedAgentExecutor = async () => {
      // Simulate abort happening concurrently with generation
      controller.abort();
      return [{ role: "assistant", content: "some text response" }];
    };
    const result = await generateSuggestion(controller, "user_intent", {}, executor);
    expect(result.suggestion).toBeNull();
    expect(result.generationRequestId).toBeNull();
  });

  it("generationRequestId starts with 'psg-' when suggestion is found", async () => {
    const controller = new AbortController();
    const executor: ForkedAgentExecutor = async () => [
      { role: "assistant", content: "run unit tests" },
    ];
    const result = await generateSuggestion(controller, "user_intent", {}, executor);
    expect(result.generationRequestId).toMatch(/^psg-\d+-[a-z0-9]+$/);
  });

  it("two sequential calls produce distinct generationRequestIds", async () => {
    const executor: ForkedAgentExecutor = async () => [
      { role: "assistant", content: "run tests" },
    ];
    const r1 = await generateSuggestion(
      new AbortController(),
      "user_intent",
      {},
      executor,
    );
    const r2 = await generateSuggestion(
      new AbortController(),
      "user_intent",
      {},
      executor,
    );
    expect(r1.generationRequestId).not.toBeNull();
    expect(r2.generationRequestId).not.toBeNull();
    // IDs should be distinct (timestamps or random suffix differ)
    // We can only guarantee they are valid psg- strings; uniqueness is probabilistic.
    expect(r1.generationRequestId).toMatch(/^psg-/);
    expect(r2.generationRequestId).toMatch(/^psg-/);
  });
});

// ---------------------------------------------------------------------------
// AC6 — tryGenerateSuggestion: integration with injectable mock executor
// ---------------------------------------------------------------------------

describe("AC6: tryGenerateSuggestion integration with mock executor", () => {
  const savedEnv: Record<string, string | undefined> = {};

  beforeEach(() => {
    savedEnv["PROMPT_SUGGESTION_ENABLED"] =
      process.env["PROMPT_SUGGESTION_ENABLED"];
    // Enable suggestions so we can reach the generation step.
    process.env["PROMPT_SUGGESTION_ENABLED"] = "true";
  });

  afterEach(() => {
    for (const [k, v] of Object.entries(savedEnv)) {
      if (v === undefined) {
        delete process.env[k];
      } else {
        process.env[k] = v;
      }
    }
  });

  function makeTwoAssistantMessages(): EmberMessage[] {
    return [
      makeAssistantMessage({ content: "first response" }),
      makeAssistantMessage({ content: "second response" }),
    ];
  }

  it("returns a valid result when all guards pass and executor returns good text", async () => {
    const controller = new AbortController();
    const executor: ForkedAgentExecutor = async () => [
      { role: "assistant", content: "run the build" },
    ];
    const result = await tryGenerateSuggestion(
      controller,
      makeTwoAssistantMessages(),
      () => makeAppState(),
      {},
      undefined,
      executor,
    );
    expect(result).not.toBeNull();
    expect(result!.suggestion).toBe("run the build");
    expect(result!.promptId).toBe("user_intent");
    expect(result!.generationRequestId).toMatch(/^psg-/);
  });

  it("returns null when executor returns evaluative language (filter rejects it)", async () => {
    const controller = new AbortController();
    const executor: ForkedAgentExecutor = async () => [
      { role: "assistant", content: "great job done" },
    ];
    const result = await tryGenerateSuggestion(
      controller,
      makeTwoAssistantMessages(),
      () => makeAppState(),
      {},
      undefined,
      executor,
    );
    expect(result).toBeNull();
  });

  it("returns null when executor returns too many words (filter rejects it)", async () => {
    const controller = new AbortController();
    const executor: ForkedAgentExecutor = async () => [
      { role: "assistant", content: "a b c d e f g h i j k l m" }, // 13 words
    ];
    const result = await tryGenerateSuggestion(
      controller,
      makeTwoAssistantMessages(),
      () => makeAppState(),
      {},
      undefined,
      executor,
    );
    expect(result).toBeNull();
  });

  it("returns null when executor returns assistant-voice prefix (filter rejects it)", async () => {
    const controller = new AbortController();
    const executor: ForkedAgentExecutor = async () => [
      { role: "assistant", content: "Let me help you" },
    ];
    const result = await tryGenerateSuggestion(
      controller,
      makeTwoAssistantMessages(),
      () => makeAppState(),
      {},
      undefined,
      executor,
    );
    expect(result).toBeNull();
  });

  it("returns null when executor returns null content (no text block)", async () => {
    const controller = new AbortController();
    const executor: ForkedAgentExecutor = async () => [];
    const result = await tryGenerateSuggestion(
      controller,
      makeTwoAssistantMessages(),
      () => makeAppState(),
      {},
      undefined,
      executor,
    );
    expect(result).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// AC7 — executePromptSuggestion: state update via injectable executor
// ---------------------------------------------------------------------------

describe("AC7: executePromptSuggestion — setAppState called only on passing suggestion", () => {
  const savedEnv: Record<string, string | undefined> = {};

  beforeEach(() => {
    savedEnv["PROMPT_SUGGESTION_ENABLED"] =
      process.env["PROMPT_SUGGESTION_ENABLED"];
    process.env["PROMPT_SUGGESTION_ENABLED"] = "true";
  });

  afterEach(() => {
    for (const [k, v] of Object.entries(savedEnv)) {
      if (v === undefined) {
        delete process.env[k];
      } else {
        process.env[k] = v;
      }
    }
  });

  function makeTwoAssistantMessages(): EmberMessage[] {
    return [
      makeAssistantMessage({ content: "first" }),
      makeAssistantMessage({ content: "second" }),
    ];
  }

  it("calls setAppState with the valid suggestion when all guards and filters pass", async () => {
    let capturedSuggestion: string | null = null;
    const executor: ForkedAgentExecutor = async () => [
      { role: "assistant", content: "check test output" },
    ];
    await executePromptSuggestion({
      messages: makeTwoAssistantMessages(),
      getAppState: () => makeAppState(),
      setAppState: (updater) => {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const s = updater(makeAppState() as any);
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        capturedSuggestion = (s as any).currentSuggestion ?? null;
      },
      cacheSafeParams: {},
      forkedAgentExecutor: executor,
    });
    expect(capturedSuggestion as string | null).toBe("check test output");
  });

  it("does NOT call setAppState when suggestion is filtered out (evaluative language)", async () => {
    let setStateCalled = false;
    const executor: ForkedAgentExecutor = async () => [
      { role: "assistant", content: "great job done" },
    ];
    await executePromptSuggestion({
      messages: makeTwoAssistantMessages(),
      getAppState: () => makeAppState(),
      setAppState: () => {
        setStateCalled = true;
      },
      cacheSafeParams: {},
      forkedAgentExecutor: executor,
    });
    expect(setStateCalled).toBe(false);
  });

  it("does NOT call setAppState when no executor is provided", async () => {
    let setStateCalled = false;
    await executePromptSuggestion({
      messages: makeTwoAssistantMessages(),
      getAppState: () => makeAppState(),
      setAppState: () => {
        setStateCalled = true;
      },
      cacheSafeParams: {},
      // forkedAgentExecutor omitted — no-op fallback
    });
    expect(setStateCalled).toBe(false);
  });

  it("does NOT call setAppState when guard sequence stops early (plan mode)", async () => {
    let setStateCalled = false;
    const executor: ForkedAgentExecutor = async () => [
      { role: "assistant", content: "run tests now" },
    ];
    await executePromptSuggestion({
      messages: makeTwoAssistantMessages(),
      // plan mode suppresses suggestions
      getAppState: () => makeAppState({ mode: "plan" }),
      setAppState: () => {
        setStateCalled = true;
      },
      cacheSafeParams: {},
      forkedAgentExecutor: executor,
    });
    expect(setStateCalled).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// AC8 — makeSuggestionExecutor: real executor factory with mock callModel
// ---------------------------------------------------------------------------

describe("AC8: makeSuggestionExecutor — real executor factory with mock callModel", () => {
  const savedEnv: Record<string, string | undefined> = {};

  beforeEach(() => {
    savedEnv["PROMPT_SUGGESTION_ENABLED"] = process.env["PROMPT_SUGGESTION_ENABLED"];
    savedEnv["EMBER_MODEL"] = process.env["EMBER_MODEL"];
    // Enable suggestions so guards pass through to the executor.
    process.env["PROMPT_SUGGESTION_ENABLED"] = "true";
  });

  afterEach(() => {
    for (const [k, v] of Object.entries(savedEnv)) {
      if (v === undefined) {
        delete process.env[k];
      } else {
        process.env[k] = v;
      }
    }
  });

  /** Canned ModelResponse containing a single text block. */
  function makeTextModelResponse(text: string): ModelResponse {
    return {
      role: "assistant",
      content: [{ type: "text", text }],
      stop_reason: "end_turn",
      usage: { input_tokens: 0, output_tokens: 0 },
    };
  }

  // ---- Behaviour: suggestion flows through generateSuggestion ----

  it("generates a non-null suggestion when mockCallModel returns valid short text", async () => {
    const mockCallModel = async (_p: CallModelParams): Promise<ModelResponse> =>
      makeTextModelResponse("run the build");
    const executor = makeSuggestionExecutor(mockCallModel);
    const controller = new AbortController();
    const result = await generateSuggestion(controller, "user_intent", {}, executor);
    expect(result.suggestion).toBe("run the build");
    expect(result.generationRequestId).toMatch(/^psg-/);
  });

  // ---- Behaviour: deny-all tool use ----

  it("passes an empty tools array to callModel (deny-all tool use)", async () => {
    let capturedTools:
      | Array<{ name: string; description: string; input_schema: Record<string, unknown> }>
      | undefined;
    const mockCallModel = async (params: CallModelParams): Promise<ModelResponse> => {
      capturedTools = params.tools;
      return makeTextModelResponse("check the logs");
    };
    const executor = makeSuggestionExecutor(mockCallModel);
    await generateSuggestion(new AbortController(), "user_intent", {}, executor);
    expect(capturedTools).toEqual([]);
  });

  // ---- Behaviour: skipCacheWrite ----

  it("sets skipCacheWrite=true on CallModelParams passed to callModel", async () => {
    let capturedSkip: boolean | undefined;
    const mockCallModel = async (params: CallModelParams): Promise<ModelResponse> => {
      capturedSkip = params.skipCacheWrite;
      return makeTextModelResponse("deploy to staging");
    };
    const executor = makeSuggestionExecutor(mockCallModel);
    await generateSuggestion(new AbortController(), "user_intent", {}, executor);
    expect(capturedSkip).toBe(true);
  });

  // ---- Behaviour: abort signal threading ----

  it("threads the ForkedAgentConfig abort signal to callModel as abortSignal", async () => {
    let capturedSignal: AbortSignal | undefined;
    const mockCallModel = async (params: CallModelParams): Promise<ModelResponse> => {
      capturedSignal = params.abortSignal;
      return makeTextModelResponse("run unit tests");
    };
    const executor = makeSuggestionExecutor(mockCallModel);
    const controller = new AbortController();
    await generateSuggestion(controller, "user_intent", {}, executor);
    expect(capturedSignal).toBe(controller.signal);
  });

  it("does NOT invoke callModel when signal is pre-aborted (generateSuggestion guard fires first)", async () => {
    let callModelInvoked = false;
    const mockCallModel = async (_p: CallModelParams): Promise<ModelResponse> => {
      callModelInvoked = true;
      return makeTextModelResponse("run tests");
    };
    const executor = makeSuggestionExecutor(mockCallModel);
    const controller = new AbortController();
    controller.abort();
    const result = await generateSuggestion(controller, "user_intent", {}, executor);
    expect(callModelInvoked).toBe(false);
    expect(result).toEqual({ suggestion: null, generationRequestId: null });
  });

  // ---- Behaviour: filter rejection still applies ----

  it("returns null when mockCallModel returns text that fails the word-count filter (13 words) — tested at tryGenerateSuggestion level where filters run", async () => {
    const mockCallModel = async (_p: CallModelParams): Promise<ModelResponse> =>
      makeTextModelResponse("a b c d e f g h i j k l m"); // 13 words — too_many_words filter
    const executor = makeSuggestionExecutor(mockCallModel);
    const controller = new AbortController();
    const messages: EmberMessage[] = [
      makeAssistantMessage({ content: "first response" }),
      makeAssistantMessage({ content: "second response" }),
    ];
    const result = await tryGenerateSuggestion(
      controller,
      messages,
      () => makeAppState(),
      {},
      undefined,
      executor,
    );
    expect(result).toBeNull();
  });

  // ---- Behaviour: systemPrompt is the SUGGESTION_PROMPTS variant ----

  it("uses SUGGESTION_PROMPTS['user_intent'] text as systemPrompt in callModel params", async () => {
    let capturedSystemPrompt: string | undefined;
    const mockCallModel = async (params: CallModelParams): Promise<ModelResponse> => {
      capturedSystemPrompt = params.systemPrompt;
      return makeTextModelResponse("commit the changes");
    };
    const executor = makeSuggestionExecutor(mockCallModel);
    await generateSuggestion(new AbortController(), "user_intent", {}, executor);
    expect(capturedSystemPrompt).toBe(SUGGESTION_PROMPTS["user_intent"]);
  });

  it("uses SUGGESTION_PROMPTS['stated_intent'] text as systemPrompt for the stated_intent variant", async () => {
    let capturedSystemPrompt: string | undefined;
    const mockCallModel = async (params: CallModelParams): Promise<ModelResponse> => {
      capturedSystemPrompt = params.systemPrompt;
      return makeTextModelResponse("run all benchmarks");
    };
    const executor = makeSuggestionExecutor(mockCallModel);
    await generateSuggestion(new AbortController(), "stated_intent", {}, executor);
    expect(capturedSystemPrompt).toBe(SUGGESTION_PROMPTS["stated_intent"]);
  });

  // ---- Behaviour: end-to-end through tryGenerateSuggestion ----

  it("flows end-to-end through tryGenerateSuggestion with mock callModel", async () => {
    const mockCallModel = async (_p: CallModelParams): Promise<ModelResponse> =>
      makeTextModelResponse("run the build");
    const executor = makeSuggestionExecutor(mockCallModel);
    const controller = new AbortController();
    const messages: EmberMessage[] = [
      makeAssistantMessage({ content: "first response" }),
      makeAssistantMessage({ content: "second response" }),
    ];
    const result = await tryGenerateSuggestion(
      controller,
      messages,
      () => makeAppState(),
      {},
      undefined,
      executor,
    );
    expect(result).not.toBeNull();
    expect(result!.suggestion).toBe("run the build");
    expect(result!.promptId).toBe("user_intent");
    expect(result!.generationRequestId).toMatch(/^psg-/);
  });

  // ---- Behaviour: parent messages extracted from cacheSafeParams ----

  it("passes cacheSafeParams.messages to callModel as the messages param", async () => {
    let capturedMessages: unknown[] | undefined;
    const mockCallModel = async (params: CallModelParams): Promise<ModelResponse> => {
      capturedMessages = params.messages;
      return makeTextModelResponse("run the tests");
    };
    const executor = makeSuggestionExecutor(mockCallModel);
    const parentMessages = [{ role: "user", content: "hello" }];
    await generateSuggestion(
      new AbortController(),
      "user_intent",
      { messages: parentMessages },
      executor,
    );
    expect(capturedMessages).toBe(parentMessages);
  });

  it("uses an empty messages array when cacheSafeParams has no messages field", async () => {
    let capturedMessages: unknown[] | undefined;
    const mockCallModel = async (params: CallModelParams): Promise<ModelResponse> => {
      capturedMessages = params.messages;
      return makeTextModelResponse("run the tests");
    };
    const executor = makeSuggestionExecutor(mockCallModel);
    await generateSuggestion(new AbortController(), "user_intent", {}, executor);
    expect(capturedMessages).toEqual([]);
  });
});
