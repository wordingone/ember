// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, expect, test, beforeEach } from 'bun:test';
import {
  PerfettoTraceWriter,
  MAX_PERFETTO_EVENTS,
  BetaSessionTracer,
  hashPluginId,
  getTelemetryPluginScope,
  recordPluginTelemetryEvent,
  logOTelEvent,
  setOTelEventSink,
  resetOTelSequence,
  runWithInteractionContext,
  runWithToolContext,
  interactionStorage,
  toolStorage,
  TRACER_NAME,
  TRACER_VERSION,
  BETA_TRACING_CONTENT_MAX_BYTES,
  getPerfettoTraceFilePath,
  type OTelEventRecord,
  type PerfettoEvent,
} from './telemetry.ts';

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  resetOTelSequence();
  setOTelEventSink(() => undefined); // reset to nop
  delete process.env['OTEL_LOG_USER_PROMPTS'];
  delete process.env['ENABLE_BETA_TRACING_DETAILED'];
  delete process.env['BETA_TRACING_ENDPOINT'];
});

// ---------------------------------------------------------------------------
// Constants / exports
// ---------------------------------------------------------------------------

describe('constants', () => {
  test('tracer name is correct', () => {
    expect(TRACER_NAME).toBe('com.ember.ember.tracing');
  });

  test('tracer version is 1.0.0', () => {
    expect(TRACER_VERSION).toBe('1.0.0');
  });

  test('MAX_PERFETTO_EVENTS is 100000', () => {
    expect(MAX_PERFETTO_EVENTS).toBe(100_000);
  });

  test('BETA_TRACING_CONTENT_MAX_BYTES is 60000', () => {
    expect(BETA_TRACING_CONTENT_MAX_BYTES).toBe(60_000);
  });

  test('getPerfettoTraceFilePath contains sessionId', () => {
    const path = getPerfettoTraceFilePath('my-session');
    expect(path).toContain('my-session');
    expect(path).toContain('trace-my-session.json');
  });
});

// ---------------------------------------------------------------------------
// OTel event logging (AC1–AC2)
// ---------------------------------------------------------------------------

describe('logOTelEvent', () => {
  test('attaches monotonically-increasing eventSequence', () => {
    const records: OTelEventRecord[] = [];
    setOTelEventSink((r) => records.push(r));

    logOTelEvent({ name: 'event.a' });
    logOTelEvent({ name: 'event.b' });
    logOTelEvent({ name: 'event.c' });

    expect(records.map((r) => r.eventSequence)).toEqual([1, 2, 3]);
  });

  test('AC1: prompt content is redacted without OTEL_LOG_USER_PROMPTS', () => {
    const records: OTelEventRecord[] = [];
    setOTelEventSink((r) => records.push(r));

    logOTelEvent({
      name: 'prompt.send',
      promptContent: 'secret user input',
      hasPromptContent: true,
    });

    expect(records[0]!.promptContent).toBe('[REDACTED]');
    expect(records[0]!.redacted).toBe(true);
  });

  test('AC2: prompt content visible with OTEL_LOG_USER_PROMPTS set', () => {
    process.env['OTEL_LOG_USER_PROMPTS'] = '1';
    const records: OTelEventRecord[] = [];
    setOTelEventSink((r) => records.push(r));

    logOTelEvent({
      name: 'prompt.send',
      promptContent: 'visible input',
      hasPromptContent: true,
    });

    expect(records[0]!.promptContent).toBe('visible input');
    expect(records[0]!.redacted).toBeUndefined();
    delete process.env['OTEL_LOG_USER_PROMPTS'];
  });

  test('non-prompt event is not redacted', () => {
    const records: OTelEventRecord[] = [];
    setOTelEventSink((r) => records.push(r));

    logOTelEvent({ name: 'tool.use', attributes: { tool: 'read' } });
    expect(records[0]!.redacted).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// PerfettoTraceWriter (AC4–AC5)
// ---------------------------------------------------------------------------

describe('PerfettoTraceWriter', () => {
  test('adds events correctly', () => {
    const writer = new PerfettoTraceWriter('test-session');
    writer.addEvent({ ph: 'i', name: 'marker', ts: 1000 });
    expect(writer.eventCount).toBe(1);
  });

  test('AC4: evicts oldest 50% when MAX_PERFETTO_EVENTS+1 events added', () => {
    const writer = new PerfettoTraceWriter('evict-test');
    for (let i = 0; i <= MAX_PERFETTO_EVENTS; i++) {
      writer.addEvent({ ph: 'i', name: 'e', ts: i });
    }
    // After MAX+1 events, eviction fires: removes oldest 50K → leaves 50K
    expect(writer.eventCount).toBe(MAX_PERFETTO_EVENTS / 2);
  });

  test('B/E events track open spans', () => {
    const writer = new PerfettoTraceWriter('span-test');
    writer.addEvent({ ph: 'B', name: 'mySpan', ts: 1000, id: 'span-1' });
    expect(writer.openSpanCount).toBe(1);
    writer.addEvent({ ph: 'E', name: 'mySpan', ts: 2000, id: 'span-1' });
    expect(writer.openSpanCount).toBe(0);
  });

  test('AC5: cleanupStaleSpans removes spans older than 30 min', () => {
    const writer = new PerfettoTraceWriter('stale-test');
    const nowMs = Date.now();
    const nowUs = nowMs * 1000;
    const staleTsUs = nowUs - 31 * 60 * 1_000_000; // 31 min ago in microseconds

    writer.addEvent({ ph: 'B', name: 'oldSpan', ts: staleTsUs, id: 'old-1' });
    writer.addEvent({ ph: 'B', name: 'freshSpan', ts: nowUs, id: 'fresh-1' });

    expect(writer.openSpanCount).toBe(2);
    writer.cleanupStaleSpans(nowMs);
    // Stale span removed, fresh span kept
    expect(writer.openSpanCount).toBe(1);
  });

  test('getEvents returns a copy', () => {
    const writer = new PerfettoTraceWriter('copy-test');
    writer.addEvent({ ph: 'i', name: 'e', ts: 1 });
    const events = writer.getEvents();
    expect(events).toHaveLength(1);
    // Modifying the copy does not affect the writer
    (events as PerfettoEvent[]).push({ ph: 'i', name: 'extra', ts: 2 });
    expect(writer.eventCount).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// BetaSessionTracer (AC3, AC8)
// ---------------------------------------------------------------------------

describe('BetaSessionTracer', () => {
  test('AC3: inactive for external user without env vars', () => {
    const tracer = new BetaSessionTracer({ isAntUser: false });
    expect(tracer.isActive()).toBe(false);
  });

  test('AC3: active for ant user unconditionally', () => {
    const tracer = new BetaSessionTracer({ isAntUser: true });
    expect(tracer.isActive()).toBe(true);
  });

  test('AC3: external user active when both env vars set', () => {
    process.env['ENABLE_BETA_TRACING_DETAILED'] = '1';
    process.env['BETA_TRACING_ENDPOINT'] = 'http://example.com';
    const tracer = new BetaSessionTracer({ isAntUser: false });
    expect(tracer.isActive()).toBe(true);
  });

  test('AC8: duplicate events (same content+name) are sent only once', async () => {
    process.env['BETA_TRACING_ENDPOINT'] = 'http://example.com';
    const posts: string[] = [];
    const tracer = new BetaSessionTracer({
      isAntUser: true,
      httpPost: async (url, body) => { posts.push(body); },
    });

    await tracer.record({ name: 'turn', content: 'hello world' });
    await tracer.record({ name: 'turn', content: 'hello world' }); // duplicate
    await tracer.record({ name: 'turn', content: 'hello world' }); // duplicate

    expect(posts).toHaveLength(1);
    expect(tracer.seenHashCount).toBe(1);
  });

  test('distinct events are each sent', async () => {
    process.env['BETA_TRACING_ENDPOINT'] = 'http://example.com';
    const posts: string[] = [];
    const tracer = new BetaSessionTracer({
      isAntUser: true,
      httpPost: async (_, body) => { posts.push(body); },
    });

    await tracer.record({ name: 'turn', content: 'message A' });
    await tracer.record({ name: 'turn', content: 'message B' });

    expect(posts).toHaveLength(2);
  });

  test('thinking blocks excluded for external users', async () => {
    process.env['ENABLE_BETA_TRACING_DETAILED'] = '1';
    process.env['BETA_TRACING_ENDPOINT'] = 'http://example.com';
    const posts: string[] = [];
    const tracer = new BetaSessionTracer({
      isAntUser: false,
      httpPost: async (_, body) => { posts.push(body); },
    });

    await tracer.record({ name: 'think', content: 'internal thoughts', isThinkingBlock: true });
    expect(posts).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Plugin telemetry (AC6–AC7)
// ---------------------------------------------------------------------------

describe('hashPluginId', () => {
  test('AC7: returns same 16-char hex for the same input', () => {
    const h1 = hashPluginId('my-plugin@builtin');
    const h2 = hashPluginId('my-plugin@builtin');
    expect(h1).toBe(h2);
    expect(h1).toHaveLength(16);
    expect(/^[0-9a-f]{16}$/.test(h1)).toBe(true);
  });

  test('different inputs produce different hashes', () => {
    expect(hashPluginId('plugin-a@builtin')).not.toBe(hashPluginId('plugin-b@builtin'));
  });
});

describe('getTelemetryPluginScope', () => {
  test('returns "ember" for @builtin plugins', () => {
    expect(getTelemetryPluginScope('my-plugin@builtin')).toBe('ember');
  });

  test('returns "third-party" for unknown plugins', () => {
    expect(getTelemetryPluginScope('evil-plugin@npm')).toBe('third-party');
    expect(getTelemetryPluginScope('some-plugin')).toBe('third-party');
  });

  test('returns "ember" for @ember-plugins-official plugins', () => {
    expect(getTelemetryPluginScope('helper@ember-plugins-official')).toBe('ember');
  });
});

describe('recordPluginTelemetryEvent', () => {
  test('AC6: third-party plugin install records "third-party" as pluginId', () => {
    const records: OTelEventRecord[] = [];
    setOTelEventSink((r) => records.push(r));

    recordPluginTelemetryEvent({
      type: 'install',
      pluginId: 'evil-plugin@npm',
    });

    expect(records).toHaveLength(1);
    expect(records[0]!.attributes?.['pluginId']).toBe('third-party');
    expect(records[0]!.attributes?.['scope']).toBe('third-party');
  });

  test('ember plugin install records a hashed ID', () => {
    const records: OTelEventRecord[] = [];
    setOTelEventSink((r) => records.push(r));

    recordPluginTelemetryEvent({
      type: 'install',
      pluginId: 'my-skill@builtin',
    });

    const reported = records[0]!.attributes?.['pluginId'] as string;
    expect(reported).not.toBe('my-skill@builtin'); // not the raw name
    expect(reported).not.toBe('third-party');
    expect(reported).toHaveLength(16); // 16-char hex from hashPluginId
  });
});

// ---------------------------------------------------------------------------
// AsyncLocalStorage context (session tracing)
// ---------------------------------------------------------------------------

describe('session tracing context', () => {
  test('runWithInteractionContext makes context accessible', async () => {
    const ctx = { promptId: 'p1', agentId: 'a1', querySource: 'api' };
    await runWithInteractionContext(ctx, async () => {
      const store = interactionStorage.getStore();
      expect(store?.promptId).toBe('p1');
      expect(store?.agentId).toBe('a1');
    });
  });

  test('runWithToolContext makes tool context accessible', async () => {
    const ctx = { toolName: 'read', toolCallId: 'tc1' };
    await runWithToolContext(ctx, async () => {
      const store = toolStorage.getStore();
      expect(store?.toolName).toBe('read');
    });
  });

  test('contexts are isolated from outer scope', () => {
    // Outside any run() call, stores are undefined
    expect(interactionStorage.getStore()).toBeUndefined();
    expect(toolStorage.getStore()).toBeUndefined();
  });
});
