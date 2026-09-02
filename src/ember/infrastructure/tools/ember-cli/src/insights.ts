// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// insights.ts — /insights command: 5-phase session analytics pipeline.

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface SessionMetadata {
  sessionId: string;
  startedAt?: string;
  endedAt?: string;
  turnCount?: number;
}

export interface SessionFacet {
  sessionId: string;
  themes?: string[];
  errorPatterns?: string[];
  toolUsage?: string[];
}

export interface InsightsReport {
  sessionCount: number;
  insights: string[];
  facets: SessionFacet[];
  multiClaudingDetected: boolean;
  reportPath?: string;
}

export interface InsightsDeps {
  enumerateSessions?: (opts: { homespaces: boolean }) => Promise<string[]>;
  loadSessionMetadata?: (ids: string[]) => Promise<SessionMetadata[]>;
  extractFacets?: (sessions: SessionMetadata[]) => Promise<SessionFacet[]>;
  generateInsights?: (facets: SessionFacet[], sessions: SessionMetadata[]) => Promise<string[]>;
  renderHtmlReport?: (report: InsightsReport) => Promise<string>;
}

// ---------------------------------------------------------------------------
// Mutable deps (test seams)
// ---------------------------------------------------------------------------

let _deps: InsightsDeps = {};

export function wireInsightsDeps(partial: Partial<InsightsDeps>): void {
  _deps = { ..._deps, ...partial };
}

export function _resetInsightsDepsForTests(): void {
  _deps = {};
}

export function _setInsightsDepsForTests(deps: InsightsDeps): void {
  _deps = deps;
}

// ---------------------------------------------------------------------------
// detectMultiClaudingDefault — AC2: finds overlapping sessions
// ---------------------------------------------------------------------------

export function detectMultiClaudingDefault(sessions: SessionMetadata[]): {
  detected: boolean;
  count: number;
  sessionIds: string[];
} {
  const timed = sessions.filter(s => s.startedAt && s.endedAt);
  const overlapping = new Set<string>();

  for (let i = 0; i < timed.length; i++) {
    for (let j = i + 1; j < timed.length; j++) {
      const a = timed[i]!;
      const b = timed[j]!;
      const aStart = new Date(a.startedAt!).getTime();
      const aEnd = new Date(a.endedAt!).getTime();
      const bStart = new Date(b.startedAt!).getTime();
      const bEnd = new Date(b.endedAt!).getTime();
      // Overlap: not (a ends before b starts or b ends before a starts)
      if (!(aEnd <= bStart || bEnd <= aStart)) {
        overlapping.add(a.sessionId);
        overlapping.add(b.sessionId);
      }
    }
  }

  return {
    detected: overlapping.size > 0,
    count: overlapping.size,
    sessionIds: Array.from(overlapping),
  };
}

// ---------------------------------------------------------------------------
// runInsightsPipeline — 5-phase pipeline
// ---------------------------------------------------------------------------

export async function runInsightsPipeline(opts: { homespaces: boolean }): Promise<InsightsReport> {
  // Phase 1: enumerate sessions
  const sessionIds = _deps.enumerateSessions
    ? await _deps.enumerateSessions(opts)
    : [];

  // Phase 2: load metadata
  const metadata: SessionMetadata[] = _deps.loadSessionMetadata && sessionIds.length > 0
    ? await _deps.loadSessionMetadata(sessionIds)
    : sessionIds.map(id => ({ sessionId: id }));

  // Phase 3: extract facets
  const facets: SessionFacet[] = _deps.extractFacets && metadata.length > 0
    ? await _deps.extractFacets(metadata)
    : metadata.map(m => ({ sessionId: m.sessionId }));

  // Phase 4: generate insights
  const insights: string[] = _deps.generateInsights && facets.length > 0
    ? await _deps.generateInsights(facets, metadata)
    : [];

  // AC2: detect multi-session
  const multiClauding = detectMultiClaudingDefault(metadata);

  const report: InsightsReport = {
    sessionCount: sessionIds.length,
    insights,
    facets,
    multiClaudingDetected: multiClauding.detected,
  };

  // Phase 5: render HTML report
  if (_deps.renderHtmlReport) {
    report.reportPath = await _deps.renderHtmlReport(report);
  }

  return report;
}

// ---------------------------------------------------------------------------
// insightsCommand — command interface
// ---------------------------------------------------------------------------

interface CommandContext {
  sessionId: string;
  mode: string;
  cwd: string;
}

interface CommandResult {
  type: 'message';
  message?: string;
}

export const insightsCommand = {
  name: 'insights',
  type: 'local-jsx' as const,

  isEnabled(): boolean {
    return true;
  },

  async execute(args: string, _ctx: CommandContext): Promise<CommandResult | undefined> {
    const parts = args.trim().split(/\s+/).filter(Boolean);
    const homespaces = parts.includes('--homespaces');
    const json = parts.includes('--json');

    const report = await runInsightsPipeline({ homespaces });

    if (json) {
      return { type: 'message', message: JSON.stringify(report) };
    }

    let message = `Sessions analyzed: ${report.sessionCount}\n`;
    if (report.multiClaudingDetected) {
      message += `Multi-session overlap detected (${report.facets.length} sessions).\n`;
    }
    if (report.insights.length > 0) {
      message += `\nInsights:\n${report.insights.map(i => `• ${i}`).join('\n')}`;
    }
    if (report.reportPath) {
      message += `\nReport saved to: ${report.reportPath}`;
    }

    return { type: 'message', message };
  },
};
