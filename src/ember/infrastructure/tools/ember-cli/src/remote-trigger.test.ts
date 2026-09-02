// Tests for remote-trigger.ts — covers AC1–AC9 from remote-trigger.md spec.
import { test, expect, describe, beforeEach } from "bun:test";
import {
  RemoteTriggerTool,
  _overrideRemoteTriggerFeatureFlags,
  _setOAuthState,
  _setBaseApiUrl,
  _setHttpRequest,
  type HttpResponse,
} from "./remote-trigger.ts";
import type { ToolUseContext } from "../core/tool-use-context.ts";

// Typed result accessor (Tool interface returns data: unknown)
type TriggerData = { status: number; json: string };
function triggerData(r: { data: unknown }): TriggerData { return r.data as TriggerData; }

// --- Context factory ---

function makeCtx(): ToolUseContext {
  let appState: Record<string, unknown> = {};
  return {
    options: {},
    abortController: new AbortController(),
    getAppState: () => appState,
    setAppState: async (updater) => {
      appState = updater(appState) as Record<string, unknown>;
    },
    setAppStateForTasks: (updater) => {
      appState = updater(appState) as Record<string, unknown>;
    },
    readFileState: new Map(),
    messages: [],
    appendSystemMessage: () => {},
    nestedMemoryAttachmentTriggers: new Set(),
    loadedNestedMemoryPaths: new Set(),
    dynamicSkillDirTriggers: new Set(),
    discoveredSkillNames: new Set(),
    fileReadingLimits: { maxTokens: 100_000, maxSizeBytes: 10_000_000 },
    globLimits: { maxResults: 1000 },
    toolUseId: "trigger_test_id",
  } as ToolUseContext;
}

// --- Capture HTTP calls ---

type CapturedRequest = {
  method: string;
  url: string;
  headers: Record<string, string>;
  data?: unknown;
};

let capturedRequests: CapturedRequest[] = [];
let mockResponseStatus = 200;
let mockResponseData: unknown = { items: [] };

beforeEach(() => {
  capturedRequests = [];
  mockResponseStatus = 200;
  mockResponseData = { items: [] };

  _overrideRemoteTriggerFeatureFlags({
    isRemoteTriggerActive: () => true,
    isRemoteSessionsAllowed: () => true,
  });

  _setOAuthState(() => ({
    needsRefresh: () => false,
    refresh: async () => {},
    accessToken: () => "test_token",
    organizationUuid: () => "test_org_uuid",
  }));

  _setBaseApiUrl(() => "https://api.ember.test");

  _setHttpRequest(async ({ method, url, headers, data }) => {
    capturedRequests.push({ method, url, headers, data });
    return { status: mockResponseStatus, data: mockResponseData } as HttpResponse;
  });
});

// --- AC1: list issues GET to base endpoint ---

describe("AC1: action list", () => {
  test("issues GET to base triggers endpoint", async () => {
    const ctx = makeCtx();
    const result = await RemoteTriggerTool.call(
      { action: "list" },
      ctx,
      async () => true,
      undefined
    );
    expect(capturedRequests).toHaveLength(1);
    expect(capturedRequests[0]!.method).toBe("GET");
    expect(capturedRequests[0]!.url).toBe("https://api.ember.test/v1/code/triggers");
    expect(triggerData(result).status).toBe(200);
  });

  test("result contains status and json fields", async () => {
    mockResponseData = { items: [{ id: "t1" }] };
    const ctx = makeCtx();
    const result = await RemoteTriggerTool.call(
      { action: "list" },
      ctx,
      async () => true,
      undefined
    );
    expect(triggerData(result).status).toBe(200);
    expect(typeof triggerData(result).json).toBe("string");
    expect(JSON.parse(triggerData(result).json)).toEqual({ items: [{ id: "t1" }] });
  });
});

// --- AC2: get issues GET with trigger_id ---

describe("AC2: action get", () => {
  test("issues GET to specific trigger endpoint", async () => {
    const ctx = makeCtx();
    await RemoteTriggerTool.call(
      { action: "get", trigger_id: "trig_123" },
      ctx,
      async () => true,
      undefined
    );
    expect(capturedRequests[0]!.method).toBe("GET");
    expect(capturedRequests[0]!.url).toBe(
      "https://api.ember.test/v1/code/triggers/trig_123"
    );
  });
});

// --- AC3: create issues POST with body ---

describe("AC3: action create", () => {
  test("issues POST with body as JSON", async () => {
    const ctx = makeCtx();
    const bodyData = { name: "nightly", schedule: "0 2 * * *" };
    await RemoteTriggerTool.call(
      { action: "create", body: bodyData },
      ctx,
      async () => true,
      undefined
    );
    expect(capturedRequests[0]!.method).toBe("POST");
    expect(capturedRequests[0]!.url).toBe("https://api.ember.test/v1/code/triggers");
    expect(capturedRequests[0]!.data).toEqual(bodyData);
  });
});

// --- AC4: update issues POST to specific trigger with body ---

describe("AC4: action update", () => {
  test("issues POST to trigger endpoint with body", async () => {
    const ctx = makeCtx();
    await RemoteTriggerTool.call(
      { action: "update", trigger_id: "trig_456", body: { active: false } },
      ctx,
      async () => true,
      undefined
    );
    expect(capturedRequests[0]!.method).toBe("POST");
    expect(capturedRequests[0]!.url).toBe(
      "https://api.ember.test/v1/code/triggers/trig_456"
    );
    expect(capturedRequests[0]!.data).toEqual({ active: false });
  });
});

// --- AC5: run issues POST to {trigger_id}/run with empty body ---

describe("AC5: action run", () => {
  test("issues POST to /run with empty body", async () => {
    const ctx = makeCtx();
    await RemoteTriggerTool.call(
      { action: "run", trigger_id: "trig_789" },
      ctx,
      async () => true,
      undefined
    );
    expect(capturedRequests[0]!.method).toBe("POST");
    expect(capturedRequests[0]!.url).toBe(
      "https://api.ember.test/v1/code/triggers/trig_789/run"
    );
    expect(capturedRequests[0]!.data).toEqual({});
  });
});

// --- AC6: missing trigger_id returns validation error ---

describe("AC6: missing trigger_id validation", () => {
  test("get without trigger_id throws", async () => {
    const ctx = makeCtx();
    await expect(
      RemoteTriggerTool.call({ action: "get" }, ctx, async () => true, undefined)
    ).rejects.toThrow(/trigger_id.*required/i);
  });

  test("update without trigger_id throws", async () => {
    const ctx = makeCtx();
    await expect(
      RemoteTriggerTool.call(
        { action: "update", body: { name: "x" } },
        ctx,
        async () => true,
        undefined
      )
    ).rejects.toThrow(/trigger_id.*required/i);
  });

  test("run without trigger_id throws", async () => {
    const ctx = makeCtx();
    await expect(
      RemoteTriggerTool.call({ action: "run" }, ctx, async () => true, undefined)
    ).rejects.toThrow(/trigger_id.*required/i);
  });

  test("create without body throws", async () => {
    const ctx = makeCtx();
    await expect(
      RemoteTriggerTool.call({ action: "create" }, ctx, async () => true, undefined)
    ).rejects.toThrow(/body.*required/i);
  });
});

// --- AC7: headers sent on every request ---

describe("AC7: request headers", () => {
  test("api-beta header is NOT sent (removed in W2-E)", async () => {
    const ctx = makeCtx();
    await RemoteTriggerTool.call({ action: "list" }, ctx, async () => true, undefined);
    expect(capturedRequests[0]!.headers["api-beta"]).toBeUndefined();
  });

  test("api-version header is NOT sent (removed in W2-E)", async () => {
    const ctx = makeCtx();
    await RemoteTriggerTool.call({ action: "list" }, ctx, async () => true, undefined);
    expect(capturedRequests[0]!.headers["api-version"]).toBeUndefined();
  });

  test("Authorization header uses OAuth access token", async () => {
    const ctx = makeCtx();
    await RemoteTriggerTool.call({ action: "list" }, ctx, async () => true, undefined);
    expect(capturedRequests[0]!.headers["Authorization"]).toBe("Bearer test_token");
  });

  test("X-Organization-UUID header present", async () => {
    const ctx = makeCtx();
    await RemoteTriggerTool.call({ action: "list" }, ctx, async () => true, undefined);
    expect(capturedRequests[0]!.headers["X-Organization-UUID"]).toBe("test_org_uuid");
  });
});

// --- AC8: tool unavailable when feature flags absent ---

describe("AC8: feature gates", () => {
  test("unavailable when tengu_surreal_dali is inactive", () => {
    _overrideRemoteTriggerFeatureFlags({ isRemoteTriggerActive: () => false });
    expect(RemoteTriggerTool.isEnabled()).toBe(false);
  });

  test("unavailable when allow_remote_sessions is inactive", () => {
    _overrideRemoteTriggerFeatureFlags({ isRemoteSessionsAllowed: () => false });
    expect(RemoteTriggerTool.isEnabled()).toBe(false);
  });

  test("available when both flags are active", () => {
    _overrideRemoteTriggerFeatureFlags({
      isRemoteTriggerActive: () => true,
      isRemoteSessionsAllowed: () => true,
    });
    expect(RemoteTriggerTool.isEnabled()).toBe(true);
  });
});

// --- AC9: HTTP errors NOT raised as exceptions ---

describe("AC9: HTTP errors not raised as exceptions", () => {
  test("404 response is returned as status in output", async () => {
    mockResponseStatus = 404;
    mockResponseData = { error: "not found" };
    const ctx = makeCtx();
    const result = await RemoteTriggerTool.call(
      { action: "get", trigger_id: "nonexistent" },
      ctx,
      async () => true,
      undefined
    );
    // No throw — status is returned in data
    expect(triggerData(result).status).toBe(404);
    expect(triggerData(result).json).toContain("not found");
  });

  test("500 response is returned as status in output", async () => {
    mockResponseStatus = 500;
    mockResponseData = { error: "internal server error" };
    const ctx = makeCtx();
    const result = await RemoteTriggerTool.call(
      { action: "list" },
      ctx,
      async () => true,
      undefined
    );
    expect(triggerData(result).status).toBe(500);
  });
});

// --- Tool metadata ---

describe("tool metadata", () => {
  test("name is 'RemoteTrigger'", () => {
    expect(RemoteTriggerTool.name).toBe("RemoteTrigger");
  });

  test("list/get are read-only", () => {
    expect(RemoteTriggerTool.isReadOnly({ action: "list" })).toBe(true);
    expect(RemoteTriggerTool.isReadOnly({ action: "get", trigger_id: "x" })).toBe(true);
  });

  test("create/update/run are NOT read-only", () => {
    expect(RemoteTriggerTool.isReadOnly({ action: "create", body: {} })).toBe(false);
    expect(RemoteTriggerTool.isReadOnly({ action: "update", trigger_id: "x", body: {} })).toBe(false);
    expect(RemoteTriggerTool.isReadOnly({ action: "run", trigger_id: "x" })).toBe(false);
  });
});
