// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// tools/remote-trigger.ts — RemoteTrigger tool for scheduled remote agent sessions.
// De-transpiled from bundle lines 307842–307989. bundle=Y
//
// Manages remote trigger resources via the Ember API.
// Actions: list | get | create | update | run
//
// Guards:
//   EMBER_SURREAL_DALI=1  → isRemoteTriggerActive()
//   EMBER_ALLOW_REMOTE_SESSIONS=1 → isRemoteSessionsAllowed()
// Both must be set for the tool to be enabled.

import { z } from "zod";
import { buildTool } from "../core/tool-interface.ts";
import type { ToolUseContext } from "../core/tool-interface.ts";

// ---------------------------------------------------------------------------
// Feature flags
// ---------------------------------------------------------------------------

const isRemoteTriggerActive = (): boolean =>
  process.env["EMBER_SURREAL_DALI"] === "1";

const isRemoteSessionsAllowed = (): boolean =>
  process.env["EMBER_ALLOW_REMOTE_SESSIONS"] === "1";

// ---------------------------------------------------------------------------
// Base URL
// ---------------------------------------------------------------------------

const getBaseApiUrl = (): string =>
  process.env["EMBER_API_BASE_URL"] ?? "https://api.ember.ai";

// ---------------------------------------------------------------------------
// OAuth state (injectable for testing)
// ---------------------------------------------------------------------------

interface OAuthState {
  needsRefresh(): boolean;
  refresh(): Promise<void>;
  accessToken(): string;
  organizationUuid(): string;
}

const NULL_OAUTH: OAuthState = {
  needsRefresh: () => false,
  refresh: async () => {},
  accessToken: () => "",
  organizationUuid: () => "",
};

let _oauthState: OAuthState = NULL_OAUTH;
const getOAuthState = (): OAuthState => _oauthState;

/** For testing: override the OAuth state. */
export function _setOAuthState(state: OAuthState): void {
  _oauthState = state;
}

// ---------------------------------------------------------------------------
// HTTP layer (injectable for testing)
// ---------------------------------------------------------------------------

interface HttpRequestParams {
  method: string;
  url: string;
  headers: Record<string, string>;
  data?: unknown;
  timeout?: number;
  signal?: AbortSignal;
}

interface HttpResponse {
  status: number;
  data: unknown;
}

const REQUEST_TIMEOUT_MS = 20_000;

const defaultHttpRequest = async ({
  method,
  url,
  headers,
  data,
  timeout,
  signal,
}: HttpRequestParams): Promise<HttpResponse> => {
  const controller = new AbortController();
  let timeoutHandle: ReturnType<typeof setTimeout> | undefined;
  if (timeout) {
    timeoutHandle = setTimeout(() => controller.abort(), timeout);
  }
  const combinedSignal = signal ?? controller.signal;
  try {
    const response = await fetch(url, {
      method,
      headers,
      body: data !== undefined ? JSON.stringify(data) : undefined,
      signal: combinedSignal,
    });
    const responseData = await response.json().catch(() => null);
    return { status: response.status, data: responseData };
  } finally {
    if (timeoutHandle) clearTimeout(timeoutHandle);
  }
};

/** Overrideable in tests. */
export let httpRequest: (params: HttpRequestParams) => Promise<HttpResponse> =
  defaultHttpRequest;

/** For testing: replace the HTTP implementation. */
export function _setHttpRequest(
  impl: (params: HttpRequestParams) => Promise<HttpResponse>,
): void {
  httpRequest = impl;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

async function prepareAuth(): Promise<{ accessToken: string; orgUuid: string }> {
  const oauth = getOAuthState();
  if (oauth.needsRefresh()) {
    await oauth.refresh();
  }
  return {
    accessToken: oauth.accessToken(),
    orgUuid: oauth.organizationUuid(),
  };
}

function buildHeaders(
  accessToken: string,
  orgUuid: string,
): Record<string, string> {
  return {
    Authorization: `Bearer ${accessToken}`,
    "Content-Type": "application/json",
    "X-Organization-UUID": orgUuid,
  };
}

// ---------------------------------------------------------------------------
// Input schema
// ---------------------------------------------------------------------------

const RemoteTriggerInputSchema = z
  .object({
    action: z.enum(["list", "get", "create", "update", "run"]),
    trigger_id: z.string().optional(),
    body: z.record(z.string(), z.unknown()).optional(),
  })
  .strict();

type RemoteTriggerInput = z.infer<typeof RemoteTriggerInputSchema>;

// ---------------------------------------------------------------------------
// Output type
// ---------------------------------------------------------------------------

interface RemoteTriggerOutput {
  status: number;
  json: string;
}

// ---------------------------------------------------------------------------
// Tool definition
// ---------------------------------------------------------------------------

export const RemoteTriggerTool = Object.assign(
  buildTool<RemoteTriggerInput, RemoteTriggerOutput>({
  name: "RemoteTrigger",
  inputSchema: RemoteTriggerInputSchema,

  isEnabled: () => isRemoteTriggerActive() && isRemoteSessionsAllowed(),
  isConcurrencySafe: () => true,
  maxResultSizeChars: 1e5,

  validateInput: (rawInput) => {
    const input = rawInput as RemoteTriggerInput;
    if (
      ["get", "update", "run"].includes(input.action) &&
      !input.trigger_id
    ) {
      return {
        result: false,
        message: `trigger_id is required for action '${input.action}'.`,
        errorCode: "MISSING_TRIGGER_ID",
      };
    }
    if (["create", "update"].includes(input.action) && !input.body) {
      return {
        result: false,
        message: `body is required for action '${input.action}'.`,
        errorCode: "MISSING_BODY",
      };
    }
    return { result: true };
  },

  call: async (
    rawArgs: RemoteTriggerInput,
    context: ToolUseContext,
  ) => {
    const args = rawArgs;

    if (
      ["get", "update", "run"].includes(args.action) &&
      !args.trigger_id
    ) {
      throw new Error(`trigger_id is required for action '${args.action}'.`);
    }
    if (["create", "update"].includes(args.action) && !args.body) {
      throw new Error(`body is required for action '${args.action}'.`);
    }

    const { accessToken, orgUuid } = await prepareAuth();
    const headers = buildHeaders(accessToken, orgUuid);
    const baseUrl = getBaseApiUrl();
    const baseTriggersUrl = `${baseUrl}/v1/code/triggers`;

    let method: string;
    let url: string;
    let requestBody: unknown;

    switch (args.action) {
      case "list":
        method = "GET";
        url = baseTriggersUrl;
        break;
      case "get":
        method = "GET";
        url = `${baseTriggersUrl}/${args.trigger_id}`;
        break;
      case "create":
        method = "POST";
        url = baseTriggersUrl;
        requestBody = args.body;
        break;
      case "update":
        method = "POST";
        url = `${baseTriggersUrl}/${args.trigger_id}`;
        requestBody = args.body;
        break;
      case "run":
        method = "POST";
        url = `${baseTriggersUrl}/${args.trigger_id}/run`;
        requestBody = {};
        break;
    }

    const response = await httpRequest({
      method,
      url,
      headers,
      data: requestBody,
      timeout: REQUEST_TIMEOUT_MS,
      signal: context.abortController.signal,
    });

    return {
      data: {
        status: response.status,
        json: JSON.stringify(response.data),
      },
    };
  },

  description: () =>
    "Manage scheduled remote agent triggers via the Ember API. Supports list, get, create, update, and run actions.",

  prompt: () =>
    "Use RemoteTrigger to manage scheduled remote agent sessions. Supports: list (all triggers), get (single trigger), create (new trigger), update (modify trigger), run (manually trigger).",

  isReadOnly: (rawInput?: RemoteTriggerInput) => {
    const input = rawInput;
    return input?.action === "list" || input?.action === "get";
  },

  mapToolResultToToolResultBlockParam: (content, toolUseId) => ({
    type: "tool_result",
    tool_use_id: toolUseId,
    content: JSON.stringify(content),
  }),
  }),
  { searchHint: "manage scheduled remote agent triggers" } as const,
);
