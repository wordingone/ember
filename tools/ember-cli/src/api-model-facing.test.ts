// Tests for api-model-facing surface (ACs from spec).

import { describe, test, expect, beforeEach, afterEach } from "bun:test";
import {
  T0_SAMPLING_PARAMS,
  MIN_CACHE_MISS_TOKENS,
  resolveEffort,
  buildPromptStateSnapshot,
  convertToolToApiSchema,
  convertToolsToApiSchemas,
  assembleSystemPrompt,
  mergeBetaHeaders,
  getExtraBodyParams,
  assembleModelRequest,
  type EmberToolDefinition,
} from "./api-model-facing.ts";

describe("T=0 sampling params", () => {
  test("AC1: T0_SAMPLING_PARAMS has the exact expected values", () => {
    expect(T0_SAMPLING_PARAMS.temperature).toBe(0.0);
    expect(T0_SAMPLING_PARAMS.top_k).toBe(1);
    expect(T0_SAMPLING_PARAMS.seed).toBe(42);
  });

  test("AC1: assembleModelRequest applies T=0 for tool-use-primary turns", () => {
    const req = assembleModelRequest({
      isToolUseTurn: true,
      model: "qwen-3.6-haiku",
      messages: [],
      maxTokens: 4096,
      thinkingMode: "disabled",
    });
    expect(req["temperature"]).toBe(0.0);
    expect(req["top_k"]).toBe(1);
    expect(req["seed"]).toBe(42);
  });

  test("AC1: assembleModelRequest does NOT apply T=0 for non-tool-use turns", () => {
    const req = assembleModelRequest({
      isToolUseTurn: false,
      model: "qwen-3.6-haiku",
      messages: [],
      maxTokens: 4096,
      thinkingMode: "disabled",
    });
    expect(req["temperature"]).toBeUndefined();
    expect(req["top_k"]).toBeUndefined();
    expect(req["seed"]).toBeUndefined();
  });
});

describe("prompt state snapshot", () => {
  test("AC2: significant cache miss when uncached > MIN_CACHE_MISS_TOKENS", () => {
    const snap = buildPromptStateSnapshot(500, MIN_CACHE_MISS_TOKENS + 1);
    expect(snap.isSignificantCacheMiss).toBe(true);
    expect(snap.uncachedTokens).toBe(MIN_CACHE_MISS_TOKENS + 1);
  });

  test("AC2: NOT a significant cache miss when uncached <= MIN_CACHE_MISS_TOKENS", () => {
    const snap = buildPromptStateSnapshot(1000, MIN_CACHE_MISS_TOKENS);
    expect(snap.isSignificantCacheMiss).toBe(false);
  });

  test("MIN_CACHE_MISS_TOKENS is 2000", () => {
    expect(MIN_CACHE_MISS_TOKENS).toBe(2000);
  });
});

describe("tool schema conversion", () => {
  test("AC3: basic tool converts to API schema format", () => {
    const tool: EmberToolDefinition = {
      name: "read_file",
      description: "Reads a file from disk",
      input_schema: {
        type: "object",
        properties: {
          path: { type: "string", description: "File path" },
        },
        required: ["path"],
      },
    };
    const schema = convertToolToApiSchema(tool);
    expect(schema.name).toBe("read_file");
    expect(schema.description).toBe("Reads a file from disk");
    expect(schema.input_schema.type).toBe("object");
    expect(schema.input_schema.properties).toEqual({ path: { type: "string", description: "File path" } });
    expect(schema.input_schema.required).toEqual(["path"]);
  });

  test("AC3: output_schema is NOT included in the API schema", () => {
    const tool: EmberToolDefinition = {
      name: "tool_with_output",
      description: "Has output schema",
      input_schema: { type: "object", properties: {} },
      output_schema: { type: "object", properties: { result: { type: "string" } } },
    };
    const schema = convertToolToApiSchema(tool);
    expect("output_schema" in schema).toBe(false);
  });

  test("converts multiple tools", () => {
    const tools: EmberToolDefinition[] = [
      { name: "a", description: "A", input_schema: { type: "object", properties: {} } },
      { name: "b", description: "B", input_schema: { type: "object", properties: { x: {} } } },
    ];
    const schemas = convertToolsToApiSchemas(tools);
    expect(schemas).toHaveLength(2);
    expect(schemas[0]?.name).toBe("a");
    expect(schemas[1]?.name).toBe("b");
  });
});

describe("system prompt assembly", () => {
  test("AC4: includes all four parts in order", () => {
    const result = assembleSystemPrompt({
      cliPrefix: "CLI_PREFIX",
      projectInstructions: "PROJECT_INSTR",
      userInstructions: "USER_INSTR",
      injectedContext: "CONTEXT",
    });
    const idx = (s: string) => result.indexOf(s);
    expect(idx("CLI_PREFIX")).toBeLessThan(idx("PROJECT_INSTR"));
    expect(idx("PROJECT_INSTR")).toBeLessThan(idx("USER_INSTR"));
    expect(idx("USER_INSTR")).toBeLessThan(idx("CONTEXT"));
  });

  test("AC4: null parts are omitted", () => {
    const result = assembleSystemPrompt({
      cliPrefix: "PREFIX",
      projectInstructions: null,
      userInstructions: null,
      injectedContext: "CTX",
    });
    expect(result).toContain("PREFIX");
    expect(result).toContain("CTX");
    expect(result).not.toContain("null");
  });

  test("empty string parts are omitted", () => {
    const result = assembleSystemPrompt({
      cliPrefix: "P",
      projectInstructions: "",
      userInstructions: "U",
      injectedContext: null,
    });
    // "" is falsy, so omitted
    expect(result).toBe("P\n\nU");
  });
});

describe("beta header merging", () => {
  test("AC6: deduplicates across model and request betas", () => {
    const merged = mergeBetaHeaders(["beta-a", "beta-b"], ["beta-b", "beta-c"]);
    expect(merged).toEqual(["beta-a", "beta-b", "beta-c"]);
  });

  test("preserves order of first occurrence", () => {
    const merged = mergeBetaHeaders(["x", "y"], ["y", "x", "z"]);
    expect(merged).toEqual(["x", "y", "z"]);
  });

  test("empty inputs produce empty output", () => {
    expect(mergeBetaHeaders([], [])).toEqual([]);
  });
});

describe("extra body params", () => {
  let origExtraBody: string | undefined;

  beforeEach(() => {
    origExtraBody = process.env["EMBER_EXTRA_BODY"];
  });

  afterEach(() => {
    if (origExtraBody === undefined) delete process.env["EMBER_EXTRA_BODY"];
    else process.env["EMBER_EXTRA_BODY"] = origExtraBody;
  });

  test("AC5: EMBER_EXTRA_BODY fields appear in request body", () => {
    process.env["EMBER_EXTRA_BODY"] = JSON.stringify({ custom_param: "hello", seed: 999 });
    const req = assembleModelRequest({
      isToolUseTurn: false,
      model: "qwen-3.6",
      messages: [],
      maxTokens: 4096,
      thinkingMode: "disabled",
    });
    expect(req["custom_param"]).toBe("hello");
    // AC5: extra body params overwrite colliding built-in fields
    expect(req["seed"]).toBe(999);
  });

  test("AC5: EMBER_EXTRA_BODY not set → no extra fields", () => {
    delete process.env["EMBER_EXTRA_BODY"];
    expect(getExtraBodyParams()).toBeNull();
  });

  test("AC5: EMBER_EXTRA_BODY with non-object value → null", () => {
    process.env["EMBER_EXTRA_BODY"] = '"just a string"';
    expect(getExtraBodyParams()).toBeNull();
  });

  test("AC5: EMBER_EXTRA_BODY with invalid JSON → null", () => {
    process.env["EMBER_EXTRA_BODY"] = "{bad json}";
    expect(getExtraBodyParams()).toBeNull();
  });
});

describe("effort resolution", () => {
  let origBudget: string | undefined;

  beforeEach(() => {
    origBudget = process.env["EMBER_THINKING_BUDGET"];
    delete process.env["EMBER_THINKING_BUDGET"];
  });

  afterEach(() => {
    if (origBudget === undefined) delete process.env["EMBER_THINKING_BUDGET"];
    else process.env["EMBER_THINKING_BUDGET"] = origBudget;
  });

  test("AC7: env override wins over explicit option and model default", () => {
    process.env["EMBER_THINKING_BUDGET"] = "0";
    expect(resolveEffort("enabled", "adaptive")).toBe("disabled");
  });

  test("AC7: explicit option wins over model default when no env override", () => {
    expect(resolveEffort("enabled", "disabled")).toBe("enabled");
  });

  test("AC7: model default is used when neither env nor explicit option set", () => {
    expect(resolveEffort(undefined, "adaptive")).toBe("adaptive");
  });

  test("AC7: non-zero EMBER_THINKING_BUDGET → 'enabled'", () => {
    process.env["EMBER_THINKING_BUDGET"] = "4096";
    expect(resolveEffort(undefined, "disabled")).toBe("enabled");
  });
});
