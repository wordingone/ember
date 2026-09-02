import { describe, expect, test, afterEach } from 'bun:test';
import {
  toSDKMessages,
  toInternalMessages,
  buildSystemInitMessage,
  sdkCompatToolName,
  PRIMARY_AGENT_TOOL_NAME,
  LEGACY_AGENT_TOOL_NAME,
  stripAnsi,
  type InternalMessage,
} from './message-mappers';

describe('sdkCompatToolName', () => {
  test('AC4: primary tool name → legacy alias', () => {
    expect(sdkCompatToolName(PRIMARY_AGENT_TOOL_NAME)).toBe(LEGACY_AGENT_TOOL_NAME);
  });

  test('other tool names pass through unchanged', () => {
    expect(sdkCompatToolName('bash')).toBe('bash');
    expect(sdkCompatToolName('read')).toBe('read');
  });

  test('primary and legacy names are distinct', () => {
    expect(PRIMARY_AGENT_TOOL_NAME).not.toBe(LEGACY_AGENT_TOOL_NAME);
  });
});

describe('stripAnsi', () => {
  test('strips color codes', () => {
    expect(stripAnsi('\x1b[32mgreen\x1b[0m')).toBe('green');
  });

  test('passes through plain text', () => {
    expect(stripAnsi('hello world')).toBe('hello world');
  });
});

describe('toSDKMessages', () => {
  test('AC1: compact_boundary is stripped from output', () => {
    const messages: InternalMessage[] = [
      { role: 'user', content: 'hello', uuid: 'u1' },
      { role: 'user', content: '', isCompactBoundary: true, uuid: 'u2' },
      { role: 'assistant', content: 'world', uuid: 'u3' },
    ];
    const result = toSDKMessages(messages);
    expect(result.length).toBe(2);
    expect(result.some((m) => (m as { isCompactBoundary?: boolean }).isCompactBoundary)).toBe(false);
  });

  test('AC2: local_command entry becomes assistant turn with ANSI stripped', () => {
    const messages: InternalMessage[] = [
      { role: 'user', content: 'run cmd', uuid: 'u1', isLocalCommand: true, localCommandOutput: '\x1b[32mok\x1b[0m' },
    ];
    const result = toSDKMessages(messages);
    expect(result.length).toBe(1);
    expect(result[0]!.role).toBe('assistant');
    const content = result[0]!.content;
    if (Array.isArray(content)) {
      expect((content[0] as { type: string; text: string }).text).toBe('ok');
    }
  });

  test('AC3: every message in output has a UUID', () => {
    const messages: InternalMessage[] = [
      { role: 'user', content: 'hello' }, // no uuid
      { role: 'assistant', content: 'world' }, // no uuid
    ];
    const result = toSDKMessages(messages);
    for (const msg of result) {
      expect(msg.uuid).toBeTruthy();
      expect(typeof msg.uuid).toBe('string');
    }
  });

  test('existing UUIDs are preserved', () => {
    const messages: InternalMessage[] = [
      { role: 'user', content: 'hello', uuid: 'my-uuid' },
    ];
    const result = toSDKMessages(messages);
    expect(result[0]!.uuid).toBe('my-uuid');
  });

  test('empty messages list returns empty array', () => {
    expect(toSDKMessages([])).toEqual([]);
  });
});

describe('buildSystemInitMessage', () => {
  afterEach(() => {
    delete process.env['UDS_INBOX'];
  });

  test('AC5: empty tools + default settings returns non-empty object with model field', () => {
    const result = buildSystemInitMessage({ tools: [], activeModel: 'claude-test' });
    expect(typeof result).toBe('object');
    expect(result.model).toBe('claude-test');
    expect(Array.isArray(result.tools)).toBe(true);
  });

  test('AC6: UDS_INBOX set + feature flag on → udsInboxPath in result', () => {
    process.env['UDS_INBOX'] = '/tmp/uds.sock';
    const result = buildSystemInitMessage({ udsInboxFeatureEnabled: true });
    expect(result.udsInboxPath).toBe('/tmp/uds.sock');
  });

  test('UDS_INBOX set but feature flag off → udsInboxPath absent', () => {
    process.env['UDS_INBOX'] = '/tmp/uds.sock';
    const result = buildSystemInitMessage({ udsInboxFeatureEnabled: false });
    expect(result.udsInboxPath).toBeUndefined();
  });

  test('tools list appears in output', () => {
    const result = buildSystemInitMessage({
      tools: [{ name: 'bash' }, { name: 'read' }],
    });
    expect(result.tools).toContain('bash');
    expect(result.tools).toContain('read');
  });

  test('mcp servers appear in output', () => {
    const result = buildSystemInitMessage({ mcpServers: ['my-mcp'] });
    expect(result.mcpServers).toContain('my-mcp');
  });
});

describe('toInternalMessages', () => {
  test('assigns UUIDs to messages without them', () => {
    const sdk = [{ role: 'user' as const, content: 'hi' }];
    const result = toInternalMessages(sdk);
    expect(result[0]!.uuid).toBeTruthy();
  });
});
