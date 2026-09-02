// remote-trigger.ts — DI version of the RemoteTrigger tool.
// Exports test seams: _overrideRemoteTriggerFeatureFlags, _setOAuthState, _setBaseApiUrl, _setHttpRequest.

import { buildTool } from './core/tool-interface.ts';
import type { ToolUseContext } from '../core/tool-use-context.ts';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface HttpResponse {
  status: number;
  data: unknown;
}

interface HttpRequestParams {
  method: string;
  url: string;
  headers: Record<string, string>;
  data?: unknown;
}

interface FeatureFlagOverrides {
  isRemoteTriggerActive?: () => boolean;
  isRemoteSessionsAllowed?: () => boolean;
}

interface OAuthState {
  needsRefresh: () => boolean;
  refresh: () => Promise<void>;
  accessToken: () => string;
  organizationUuid: () => string;
}

// ---------------------------------------------------------------------------
// Mutable state (seams for testing)
// ---------------------------------------------------------------------------

let _featureFlags: FeatureFlagOverrides = {};
let _oauthStateFactory: (() => OAuthState) | null = null;
let _baseApiUrlFactory: (() => string) | null = null;
let _httpRequestImpl: ((params: HttpRequestParams) => Promise<HttpResponse>) | null = null;

export function _overrideRemoteTriggerFeatureFlags(overrides: FeatureFlagOverrides): void {
  _featureFlags = { ..._featureFlags, ...overrides };
}

export function _setOAuthState(factory: () => OAuthState): void {
  _oauthStateFactory = factory;
}

export function _setBaseApiUrl(factory: () => string): void {
  _baseApiUrlFactory = factory;
}

export function _setHttpRequest(impl: (params: HttpRequestParams) => Promise<HttpResponse>): void {
  _httpRequestImpl = impl;
}

// ---------------------------------------------------------------------------
// Feature gate helpers
// ---------------------------------------------------------------------------

function isRemoteTriggerActive(): boolean {
  if (_featureFlags.isRemoteTriggerActive) return _featureFlags.isRemoteTriggerActive();
  return process.env['EMBER_SURREAL_DALI'] === '1';
}

function isRemoteSessionsAllowed(): boolean {
  if (_featureFlags.isRemoteSessionsAllowed) return _featureFlags.isRemoteSessionsAllowed();
  return process.env['EMBER_ALLOW_REMOTE_SESSIONS'] === '1';
}

function getBaseApiUrl(): string {
  if (_baseApiUrlFactory) return _baseApiUrlFactory();
  return process.env['EMBER_API_URL'] ?? 'https://api.ember.ai';
}

function getOAuthState(): OAuthState {
  if (_oauthStateFactory) return _oauthStateFactory();
  throw new Error('No OAuth state configured');
}

async function executeHttpRequest(params: HttpRequestParams): Promise<HttpResponse> {
  if (_httpRequestImpl) return _httpRequestImpl(params);
  const resp = await fetch(params.url, {
    method: params.method,
    headers: params.headers,
    body: params.data !== undefined ? JSON.stringify(params.data) : undefined,
  });
  const data = await resp.json().catch(() => null);
  return { status: resp.status, data };
}

// ---------------------------------------------------------------------------
// Input schema
// ---------------------------------------------------------------------------

type TriggerAction = 'list' | 'get' | 'create' | 'update' | 'run';

interface RemoteTriggerInput {
  action: TriggerAction;
  trigger_id?: string;
  body?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// RemoteTriggerTool
// ---------------------------------------------------------------------------

export const RemoteTriggerTool = buildTool<RemoteTriggerInput, { status: number; json: string }>({
  name: 'RemoteTrigger',
  description: () => 'Manage remote code triggers (list, get, create, update, run).',
  isEnabled: () => isRemoteTriggerActive() && isRemoteSessionsAllowed(),
  isReadOnly: (input?: RemoteTriggerInput) => {
    if (!input) return true;
    return input.action === 'list' || input.action === 'get';
  },
  mapToolResultToToolResultBlockParam: (content, id) => ({
    type: 'tool_result' as const,
    tool_use_id: id,
    content: JSON.stringify(content),
  }),
  call: async (args, _ctx, _canUse, _parent) => {
    const { action, trigger_id, body } = args;

    // AC6: validation
    if ((action === 'get' || action === 'update' || action === 'run') && !trigger_id) {
      throw new Error(`trigger_id is required for action "${action}"`);
    }
    if (action === 'create' && !body) {
      throw new Error('body is required for action "create"');
    }

    const oauth = getOAuthState();
    if (oauth.needsRefresh()) {
      await oauth.refresh();
    }

    const base = getBaseApiUrl();
    const baseTriggersUrl = `${base}/v1/code/triggers`;

    // Build URL and method
    let url: string;
    let method: string;
    let requestData: Record<string, unknown> | undefined;

    switch (action) {
      case 'list':
        url = baseTriggersUrl;
        method = 'GET';
        break;
      case 'get':
        url = `${baseTriggersUrl}/${trigger_id!}`;
        method = 'GET';
        break;
      case 'create':
        url = baseTriggersUrl;
        method = 'POST';
        requestData = body;
        break;
      case 'update':
        url = `${baseTriggersUrl}/${trigger_id!}`;
        method = 'POST';
        requestData = body;
        break;
      case 'run':
        url = `${baseTriggersUrl}/${trigger_id!}/run`;
        method = 'POST';
        requestData = {};
        break;
    }

    // AC7: headers (no api-beta, no api-version per W2-E removal)
    const headers: Record<string, string> = {
      'Authorization': `Bearer ${oauth.accessToken()}`,
      'X-Organization-UUID': oauth.organizationUuid(),
      'Content-Type': 'application/json',
    };

    // AC9: HTTP errors not raised as exceptions — just return in data
    const response = await executeHttpRequest({ method: method!, url: url!, headers, data: requestData });

    return {
      data: {
        status: response.status,
        json: JSON.stringify(response.data),
      },
    };
  },
});
