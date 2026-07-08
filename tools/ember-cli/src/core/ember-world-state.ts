// core/ember-world-state.ts — real GOAL/ledger/receipts -> EmberWorldState adapter (gh issue #10,
// condition C-OBS, clause (a)).
//
// This is the ADAPTER: it binds the live goalforge contract tree's GOAL.md, its technical/
// cognitive debt ledger, and the newest totality-board receipt into one typed EmberWorldState
// snapshot. Nothing here is a hand-maintained mirror -- buildEmberWorldState() re-reads and
// re-parses the three real source files fresh on every call; every Claim it produces carries an
// EvidenceRef (repo-relative path + sha256 of the source file at read time) so a caller can
// resolve any rendered claim back to the exact bytes that produced it (the click-to-evidence
// contract, clause (b), lives one layer up in the REPL/command surfaces that render this state).
//
// Cross-tree read: this module reads from a separate CONTRACT tree (the goalforge repo whose
// GOAL.md is the authoritative goal surface -- "the GOVERNING CONTRACT is the goalforge contract
// repo's GOAL.md ... on any conflict, the contract wins"), never the tree this module itself
// executes from. Read-only; never writes into that tree. The contract tree's location is
// deployment-specific and is never hardcoded here -- see the EMBER_GOALFORGE_ROOT contract below.

import { readFile, readdir } from "fs/promises";
import { createHash } from "crypto";
import path from "path";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

// Repo-relative from this file is meaningless across trees, and the contract tree's location is
// operator/deployment-specific, so there is NO machine-specific default here -- every caller must
// supply it via EMBER_GOALFORGE_ROOT (or buildEmberWorldState({ goalforgeRoot }) directly, as the
// tests do). An empty string means "not configured"; the calling command surface
// (commands/world-state.ts) is responsible for treating that as a visible, honest status rather
// than attempting a read against it.
export const GOALFORGE_ROOT = process.env.EMBER_GOALFORGE_ROOT || "";

const GOAL_PATH = "GOAL.md";
const LEDGER_PATH = "docs/ember-debt-ledger.md";
const BOARD_DIR = "scripts/ember_totality/receipts-totality";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface EvidenceRef {
  path: string; // repo-relative path (goalforge-root-relative), forward-slashed
  sha256: string; // sha256 of the source file's bytes at read time
}

export interface Claim {
  id: string; // stable within one snapshot, e.g. "board.C-OBS", "ledger.DEBT-004", "goal.topology.3"
  label: string; // short label shown by a rendering surface
  detail: string; // the actual claim text (a status line, a table row, a heading)
  evidence: EvidenceRef; // where this claim traces to -- the click-to-evidence target
}

export interface EmberWorldState {
  ts: string; // ISO8601Z, when this snapshot was built
  monitor: {
    boardTs: string;
    total: number;
    green: number;
    red: number;
    pctComplete: number;
    conditions: Claim[]; // one per board row
  };
  understand: {
    goalTitle: string;
    topology: Claim[]; // one per "## " heading in GOAL.md -- organ anatomy + loop topology
  };
  interact: {
    ledgerRows: Claim[]; // one per active debt-ledger row -- query receipts/ledger
  };
  sources: {
    goal: EvidenceRef;
    ledger: EvidenceRef;
    board: EvidenceRef;
  };
}

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

export function sha256OfBytes(buf: Buffer): string {
  return createHash("sha256").update(buf).digest("hex");
}

/** Extracts the H1 title (first "# " line) from GOAL.md text. */
export function parseGoalTitle(text: string): string {
  const m = text.match(/^#\s+(.+)$/m);
  return m ? m[1]!.trim() : "(no title found)";
}

/** Extracts every "## " heading in document order -- the organ anatomy + loop topology view. */
export function parseTopologyHeadings(text: string): string[] {
  const headings: string[] = [];
  for (const line of text.split(/\r?\n/)) {
    const m = line.match(/^##\s+(.+)$/);
    if (m) headings.push(m[1]!.trim());
  }
  return headings;
}

/**
 * Extracts a named "## <heading>" section's body (up to the next "## " heading or EOF),
 * case-sensitive exact match on the heading text.
 */
export function extractSection(text: string, heading: string): string | null {
  const lines = text.split(/\r?\n/);
  const startIdx = lines.findIndex((l) => l.trim() === `## ${heading}`);
  if (startIdx === -1) return null;
  let endIdx = lines.length;
  for (let i = startIdx + 1; i < lines.length; i++) {
    if (/^##\s+/.test(lines[i]!)) {
      endIdx = i;
      break;
    }
  }
  return lines.slice(startIdx + 1, endIdx).join("\n");
}

export interface BlockerPacketItem {
  label: string;
  detail: string;
}

/** Parses the numbered "N. **Label:** detail" items of a "Current Blocker Packet" section body. */
export function parseBlockerPacket(sectionBody: string): BlockerPacketItem[] {
  const items: BlockerPacketItem[] = [];
  const re = /^\d+\.\s+\*\*(.+?):\*\*\s*(.+)$/gm;
  let m: RegExpExecArray | null;
  while ((m = re.exec(sectionBody)) !== null) {
    items.push({ label: m[1]!.trim(), detail: m[2]!.trim() });
  }
  return items;
}

export interface LedgerRow {
  id: string;
  cls: string;
  debt: string;
  status: string;
}

/** Parses a markdown table's data rows (skips header + separator rows) from a section body. */
export function parseLedgerTable(sectionBody: string): LedgerRow[] {
  const rows: LedgerRow[] = [];
  for (const line of sectionBody.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("|")) continue;
    const cells = trimmed
      .split("|")
      .slice(1, -1)
      .map((c) => c.trim());
    if (cells.length < 6) continue;
    const [id, cls, debt, , , status] = cells;
    if (!id || id === "ID" || /^-+$/.test(id)) continue; // header / separator row
    rows.push({ id, cls: cls ?? "", debt: debt ?? "", status: status ?? "" });
  }
  return rows;
}

export interface BoardRow {
  condition: string;
  status: string;
  reason: string;
}

export interface BoardReceipt {
  ts: string;
  rows: BoardRow[];
  summary: {
    total: number;
    green: number;
    red: number;
    // Legacy/flat location -- some receipts may carry it here directly.
    pct_complete?: number;
    // Actual location in the live totality-board receipt schema: the STATE-condition
    // completion percentage lives nested under completion_math, not on summary directly.
    completion_math?: {
      pct_complete?: number;
    };
  };
}

/** Lists the board-receipts directory's *.json filenames, lexicographically sorted (the board's
 * own <ts> naming sorts chronologically) -- the shared cheap-discovery step behind
 * findNewestBoardReceipt and the #420 live-badge poll below. Returns [] (never throws) when the
 * directory doesn't exist yet, matching this module's existing fail-open board reads. */
async function listBoardReceiptFilenamesSorted(goalforgeRoot: string): Promise<string[]> {
  const dir = path.join(goalforgeRoot, BOARD_DIR);
  try {
    const files = (await readdir(dir)).filter((f) => f.endsWith(".json"));
    files.sort();
    return files;
  } catch {
    return [];
  }
}

/** Picks the newest receipt filename lexicographically WITHOUT reading or parsing it -- the cheap
 * half of #420's live-badge poll (directory listing + name sort only, no JSON.parse). */
export async function peekNewestBoardReceiptFilename(goalforgeRoot: string): Promise<string | null> {
  const files = await listBoardReceiptFilenamesSorted(goalforgeRoot);
  return files.length > 0 ? files[files.length - 1]! : null;
}

/** Picks the newest receipt filename lexicographically (the board's own <ts> naming sorts
 * chronologically) and parses it. */
export async function findNewestBoardReceipt(
  goalforgeRoot: string,
): Promise<{ filename: string; parsed: BoardReceipt } | null> {
  const files = await listBoardReceiptFilenamesSorted(goalforgeRoot);
  if (files.length === 0) return null;
  const newest = files[files.length - 1]!;
  const raw = await readFile(path.join(goalforgeRoot, BOARD_DIR, newest), "utf-8");
  const parsed = JSON.parse(raw) as BoardReceipt;
  return { filename: newest, parsed };
}

export interface BoardTsPollResult {
  filename: string;
  boardTs: string;
}

/**
 * #420 cockpit live-badge poll: returns the newest receipt's `ts` field ONLY when the newest
 * filename differs from `lastKnownFilename` -- the cheap directory-listing discovery above runs
 * every call, but the receipt file itself is read and JSON.parse'd only when that comparison
 * finds an actual change. Returns null both when nothing is newer AND when the board dir is
 * empty/missing -- callers (screens/repl.ts's useBoardTsPoller) treat both the same way: keep the
 * last known boardTs, try again next tick. A genuine parse failure on a CHANGED file (a receipt
 * caught mid-write) is left to throw -- the caller wraps this call in its own try/catch, the same
 * fail-open contract every other poller in services/ uses (model-metrics-poller.ts,
 * circuit-breaker-banner-poller.ts).
 */
export async function pollForNewerBoardTs(
  goalforgeRoot: string,
  lastKnownFilename: string | undefined,
): Promise<BoardTsPollResult | null> {
  const filename = await peekNewestBoardReceiptFilename(goalforgeRoot);
  if (!filename || filename === lastKnownFilename) return null;

  const raw = await readFile(path.join(goalforgeRoot, BOARD_DIR, filename), "utf-8");
  const parsed = JSON.parse(raw) as BoardReceipt;
  return { filename, boardTs: parsed.ts };
}

// ---------------------------------------------------------------------------
// Adapter (real I/O)
// ---------------------------------------------------------------------------

async function readWithSha(
  goalforgeRoot: string,
  relPath: string,
): Promise<{ text: string; evidence: EvidenceRef }> {
  const abs = path.join(goalforgeRoot, relPath);
  const buf = await readFile(abs);
  return {
    text: buf.toString("utf-8"),
    evidence: { path: relPath.replace(/\\/g, "/"), sha256: sha256OfBytes(buf) },
  };
}

/**
 * Builds a fresh EmberWorldState by binding the real goalforge GOAL.md, docs/ember-debt-ledger.md,
 * and the newest scripts/ember_totality/receipts-totality board receipt. No caching, no mirror --
 * every call re-reads the three source files as they exist on disk right now.
 */
export async function buildEmberWorldState(
  opts: { goalforgeRoot?: string } = {},
): Promise<EmberWorldState> {
  const root = opts.goalforgeRoot ?? GOALFORGE_ROOT;

  const [goal, ledger] = await Promise.all([
    readWithSha(root, GOAL_PATH),
    readWithSha(root, LEDGER_PATH),
  ]);

  const board = await findNewestBoardReceipt(root);
  if (!board) {
    throw new Error(
      `ember-world-state adapter: no board receipt found under ${path.join(root, BOARD_DIR)}`,
    );
  }
  const boardBuf = await readFile(path.join(root, BOARD_DIR, board.filename));
  const boardEvidence: EvidenceRef = {
    path: `${BOARD_DIR}/${board.filename}`.replace(/\\/g, "/"),
    sha256: sha256OfBytes(boardBuf),
  };

  const goalTitle = parseGoalTitle(goal.text);
  const topologyHeadings = parseTopologyHeadings(goal.text);

  const blockerSection = extractSection(ledger.text, "Current Blocker Packet") ?? "";
  const blockerItems = parseBlockerPacket(blockerSection);

  const activeRowsSection = extractSection(ledger.text, "Active Rows") ?? "";
  const ledgerRows = parseLedgerTable(activeRowsSection);

  const conditions: Claim[] = board.parsed.rows.map((r, i) => ({
    id: `board.${r.condition}`,
    label: `[${i}] ${r.condition}`,
    detail: `${r.status}: ${r.reason}`,
    evidence: boardEvidence,
  }));

  const topology: Claim[] = topologyHeadings.map((h, i) => ({
    id: `goal.topology.${i}`,
    label: `[${i}] ${h}`,
    detail: h,
    evidence: goal.evidence,
  }));
  // Fold the Current Blocker Packet items in as additional UNDERSTAND claims -- the loop's
  // current focus, not just its static section topology.
  blockerItems.forEach((item, i) => {
    topology.push({
      id: `goal.blocker.${i}`,
      label: `[blocker:${i}] ${item.label}`,
      detail: item.detail,
      evidence: ledger.evidence,
    });
  });

  const ledgerClaims: Claim[] = ledgerRows.map((row, i) => ({
    id: `ledger.${row.id}`,
    label: `[${i}] ${row.id} (${row.cls}, ${row.status})`,
    detail: row.debt,
    evidence: ledger.evidence,
  }));

  return {
    ts: new Date().toISOString(),
    monitor: {
      boardTs: board.parsed.ts,
      total: board.parsed.summary?.total ?? board.parsed.rows.length,
      green: board.parsed.summary?.green ?? 0,
      red: board.parsed.summary?.red ?? 0,
      // Field-read bug fix: the receipt's real completion percentage lives at
      // summary.completion_math.pct_complete (verified against a live totality-board receipt --
      // summary.pct_complete does not exist there and always defaulted to 0). Flat summary.pct_complete
      // is kept as a fallback for any receipt shape that puts it there directly.
      pctComplete:
        board.parsed.summary?.completion_math?.pct_complete ??
        board.parsed.summary?.pct_complete ??
        0,
      conditions,
    },
    understand: {
      goalTitle,
      topology,
    },
    interact: {
      ledgerRows: ledgerClaims,
    },
    sources: {
      goal: goal.evidence,
      ledger: ledger.evidence,
      board: boardEvidence,
    },
  };
}
