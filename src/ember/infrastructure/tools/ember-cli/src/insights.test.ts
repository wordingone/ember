// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
import { describe, it, expect, beforeEach, afterEach } from 'bun:test';
import {
  insightsCommand,
  runInsightsPipeline,
  detectMultiClaudingDefault,
  wireInsightsDeps,
  _resetInsightsDepsForTests,
  _setInsightsDepsForTests,
  type SessionMetadata,
} from './insights.ts';

const CTX = { sessionId: 'sess-abc', mode: 'default', cwd: '/tmp' } as const;

describe('insights command', () => {
  beforeEach(() => {
    _resetInsightsDepsForTests();
  });

  afterEach(() => {
    _resetInsightsDepsForTests();
  });

  // AC2: multi-session detection
  describe('detectMultiClaudingDefault', () => {
    it('detects overlapping sessions', () => {
      const sessions: SessionMetadata[] = [
        { sessionId: 's1', startedAt: '2026-06-01T10:00:00Z', endedAt: '2026-06-01T12:00:00Z' },
        { sessionId: 's2', startedAt: '2026-06-01T11:00:00Z', endedAt: '2026-06-01T13:00:00Z' },
      ];
      const result = detectMultiClaudingDefault(sessions);
      expect(result.detected).toBe(true);
      expect(result.count).toBe(2);
      expect(result.sessionIds).toContain('s1');
      expect(result.sessionIds).toContain('s2');
    });

    it('does not flag non-overlapping sessions', () => {
      const sessions: SessionMetadata[] = [
        { sessionId: 's1', startedAt: '2026-06-01T10:00:00Z', endedAt: '2026-06-01T11:00:00Z' },
        { sessionId: 's2', startedAt: '2026-06-01T12:00:00Z', endedAt: '2026-06-01T13:00:00Z' },
      ];
      const result = detectMultiClaudingDefault(sessions);
      expect(result.detected).toBe(false);
      expect(result.count).toBe(0);
    });

    it('skips sessions without time data', () => {
      const sessions: SessionMetadata[] = [
        { sessionId: 's1' },
        { sessionId: 's2' },
      ];
      const result = detectMultiClaudingDefault(sessions);
      expect(result.detected).toBe(false);
    });
  });

  // 5-phase pipeline
  describe('runInsightsPipeline', () => {
    it('returns report with 0 sessions when no enumerator is wired', async () => {
      const report = await runInsightsPipeline({ homespaces: false });
      expect(report.sessionCount).toBe(0);
      expect(Array.isArray(report.insights)).toBe(true);
      expect(report.facets).toHaveLength(0);
    });

    it('Phase 1: uses enumerateSessions dep', async () => {
      wireInsightsDeps({
        enumerateSessions: async () => ['sess-1', 'sess-2', 'sess-3'],
      });
      const report = await runInsightsPipeline({ homespaces: false });
      expect(report.sessionCount).toBe(3);
    });

    it('Phase 1: passes homespaces flag to enumerator', async () => {
      const captured = { opts: null as { homespaces: boolean } | null };
      wireInsightsDeps({
        enumerateSessions: async (opts) => { captured.opts = opts; return []; },
      });
      await runInsightsPipeline({ homespaces: true });
      expect(captured.opts?.homespaces).toBe(true);
    });

    it('Phase 2: loads metadata for enumerated sessions', async () => {
      wireInsightsDeps({
        enumerateSessions: async () => ['sess-1'],
        loadSessionMetadata: async (ids) => ids.map(id => ({
          sessionId: id,
          turnCount: 10,
        })),
      });
      const report = await runInsightsPipeline({ homespaces: false });
      expect(report.facets[0]?.sessionId).toBe('sess-1');
    });

    it('Phase 3: extracts facets via dep', async () => {
      wireInsightsDeps({
        enumerateSessions: async () => ['sess-1'],
        extractFacets: async (sessions) => sessions.map(s => ({
          sessionId: s.sessionId,
          themes: ['coding', 'debugging'],
          errorPatterns: [],
          toolUsage: ['Read', 'Edit'],
        })),
      });
      const report = await runInsightsPipeline({ homespaces: false });
      expect(report.facets[0]?.themes).toContain('coding');
    });

    it('Phase 4: generates insights via dep', async () => {
      wireInsightsDeps({
        enumerateSessions: async () => ['sess-1'],
        extractFacets: async (sessions) => sessions.map(s => ({
          sessionId: s.sessionId, themes: ['debugging'], errorPatterns: [], toolUsage: [],
        })),
        generateInsights: async (_facets, _sessions) => ['You debug a lot!'],
      });
      const report = await runInsightsPipeline({ homespaces: false });
      expect(report.insights).toContain('You debug a lot!');
    });

    it('AC2: detects multi-session in report', async () => {
      wireInsightsDeps({
        enumerateSessions: async () => ['s1', 's2'],
        loadSessionMetadata: async (ids) => [
          { sessionId: ids[0] ?? 's1', startedAt: '2026-06-01T10:00:00Z', endedAt: '2026-06-01T12:00:00Z' },
          { sessionId: ids[1] ?? 's2', startedAt: '2026-06-01T11:00:00Z', endedAt: '2026-06-01T13:00:00Z' },
        ],
      });
      const report = await runInsightsPipeline({ homespaces: false });
      expect(report.multiClaudingDetected).toBe(true);
    });
  });

  // Command interface
  it('has name "insights" and type "local-jsx"', () => {
    expect(insightsCommand.name).toBe('insights');
    expect(insightsCommand.type).toBe('local-jsx');
  });

  it('isEnabled returns true', () => {
    expect(insightsCommand.isEnabled()).toBe(true);
  });

  it('execute returns message with text summary', async () => {
    const result = await insightsCommand.execute('', CTX);
    expect(result?.type).toBe('message');
  });

  it('execute with --json returns JSON report', async () => {
    const result = await insightsCommand.execute('--json', CTX);
    const msg = (result as { message?: string }).message ?? '';
    const parsed = JSON.parse(msg) as { sessionCount: number };
    expect(typeof parsed.sessionCount).toBe('number');
  });

  it('AC1: --homespaces flag is passed through to enumerator', async () => {
    const captured = { opts: null as { homespaces: boolean } | null };
    wireInsightsDeps({
      enumerateSessions: async (opts) => { captured.opts = opts; return []; },
    });
    await insightsCommand.execute('--homespaces', CTX);
    expect(captured.opts?.homespaces).toBe(true);
  });

  it('Phase 5: uses renderHtmlReport when wired', async () => {
    wireInsightsDeps({
      renderHtmlReport: async (_report) => '/tmp/insights-report.html',
    });
    const result = await insightsCommand.execute('', CTX);
    const msg = (result as { message?: string }).message ?? '';
    expect(msg).toContain('/tmp/insights-report.html');
  });
});
