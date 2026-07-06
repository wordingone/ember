// capture-286.mjs -- issue #286 before/after capture harness.
//
// Reuses the #242/#114 ConPTY (node-pty) + @xterm/headless pattern (see
// b114-resize-probe.mjs precedent in this same scratchpad dir): launches the
// app in DEV mode under a real ConPTY, feeds it through a live mid-session
// resize, and captures the rendered screen buffer at each named viewport --
// the same live-resize signal path a physical terminal resize takes.
//
// Viewports per issue #286 (operator's two real setups):
//   wide  : 208x22 (wide-short)
//   tall  : 105x55 (tall half-screen)
// Probe order: wide (boot) -> tall (live resize) -> wide (resize back) --
// the third leg is the reflow-reversibility check the last-leg-experience
// gate + issue #286 acceptance both name ("reflow required" on resize).
//
// Each frame is captured twice:
//   - <label>.txt  -- exact terminal text, one row per line (ground truth for
//     border/column/clip defect analysis -- this is what every other probe
//     in this dir already uses for pass/fail assertions).
//   - <label>.png  -- per-cell color raster (reusing the void-mockup-raster.mjs
//     approach: each character cell becomes a colored block using its REAL
//     live fg/bg/dim/inverse attributes read straight off the xterm buffer,
//     not parsed from saved ANSI text). Honest scope, same disclaimer as that
//     tool: a layout/color-density map, not a font-accurate render -- good
//     enough to see void-dominance, border shape, and status-bar coloring at
//     a glance, not meant to fake glyph shapes.
//
// EMBER_MODEL_URL set to an unreachable localhost port so process-entry.ts's
// detectNCtx skips spawning the owned Python model server (frozen spec: URL
// set -> external server, no spawn) -- boot proceeds straight to the TUI
// without touching GPU or spawning anything beyond bun+node-pty (b114
// precedent, same env shape).
import pty from "node-pty";
import pkg from "@xterm/headless";
import { writeFileSync, mkdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { encodePNG } from "./png-writer.mjs";
const { Terminal } = pkg;

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC_DIR = path.join(__dirname, "..", "src");
const OUT_DIR = path.join(__dirname, "..", "state", "captures-286");
mkdirSync(OUT_DIR, { recursive: true });

// "before" (unmodified master) or "after" (post-fix) -- selects filename prefix.
const TAG = process.argv[2] ?? "before";

const SIZES = [
  { label: "wide",       cols: 208, rows: 22 },
  { label: "tall",       cols: 105, rows: 55 },
  { label: "wide-again", cols: 208, rows: 22 },
];

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

// --- xterm-256 palette table (standard 16 + 6x6x6 cube + grayscale ramp) ---
const ANSI16 = [
  [0,0,0],[205,0,0],[0,205,0],[205,205,0],[0,0,238],[205,0,205],[0,205,205],[229,229,229],
  [127,127,127],[255,0,0],[0,255,0],[255,255,0],[92,92,255],[255,0,255],[0,255,255],[255,255,255],
];
function palette256(n) {
  if (n < 16) return ANSI16[n];
  if (n < 232) {
    const i = n - 16;
    const r = Math.floor(i / 36), g = Math.floor((i % 36) / 6), b = i % 6;
    const lvl = (v) => (v === 0 ? 0 : 55 + v * 40);
    return [lvl(r), lvl(g), lvl(b)];
  }
  const gray = 8 + (n - 232) * 10;
  return [gray, gray, gray];
}

const VOID_BG = [0x0a, 0x0a, 0x0e];
const DEFAULT_FG = [0xd0, 0xd0, 0xd4];
const DIM_SCALE = 0.55;

function scale(rgb, f) { return rgb.map((c) => Math.round(c * f)); }

function cellColors(cell) {
  let fg = DEFAULT_FG;
  if (cell.isFgRGB()) {
    const v = cell.getFgColor();
    fg = [(v >> 16) & 0xff, (v >> 8) & 0xff, v & 0xff];
  } else if (cell.isFgPalette()) {
    fg = palette256(cell.getFgColor());
  }
  let bg = null;
  if (cell.isBgRGB()) {
    const v = cell.getBgColor();
    bg = [(v >> 16) & 0xff, (v >> 8) & 0xff, v & 0xff];
  } else if (cell.isBgPalette()) {
    bg = palette256(cell.getBgColor());
  }
  if (cell.isInverse()) { const t = fg; fg = bg ?? VOID_BG; bg = t ?? DEFAULT_FG; }
  if (cell.isDim()) fg = scale(fg, DIM_SCALE);
  return { fg, bg };
}

const CELL_W = 7, CELL_H = 12;

function rasterizeFrame(term, cols, rows) {
  const cellGrid = [];
  for (let y = 0; y < rows; y++) {
    const line = term.buffer.active.getLine(y);
    const row = [];
    for (let x = 0; x < cols; x++) {
      const cell = line ? line.getCell(x) : undefined;
      if (!cell || cell.getChars() === "" || cell.getChars() === " ") {
        row.push(null);
        continue;
      }
      row.push(cellColors(cell));
    }
    cellGrid.push(row);
  }
  const pxW = cols * CELL_W, pxH = rows * CELL_H;
  return encodePNG(pxW, pxH, (px, py) => {
    const col = Math.floor(px / CELL_W);
    const rowIdx = Math.floor(py / CELL_H);
    const c = cellGrid[rowIdx]?.[col];
    if (!c) return VOID_BG;
    return c.bg ?? c.fg;
  });
}

async function main() {
  // node-pty's WindowsPtyAgent calls CreateProcess directly and cannot launch a
  // .cmd shim (bun on this box resolves to nvm4w's bun.cmd) -- wrap through
  // cmd.exe, same workaround as b114-resize-probe.mjs / visible-window-hygiene.
  const p = pty.spawn("cmd.exe", ["/c", "bun.cmd", "run", "./entrypoints/main.ts"], {
    name: "xterm-256color",
    cols: SIZES[0].cols,
    rows: SIZES[0].rows,
    cwd: SRC_DIR,
    env: {
      ...process.env,
      EMBER_MODEL_URL: "http://127.0.0.1:1",
      EMBER_DISABLE_TERMINAL_TITLE: "1",
      TERM: "xterm-256color",
    },
  });
  console.log(JSON.stringify({ event: "spawned", pid: p.pid, tag: TAG }));

  let raw = "";
  p.onData((d) => { raw += d; });

  const term = new Terminal({ cols: SIZES[0].cols, rows: SIZES[0].rows, allowProposedApi: true });

  let consumedLen = 0;
  await sleep(5000); // boot settle at initial size

  const receipts = [];
  for (let i = 0; i < SIZES.length; i++) {
    const size = SIZES[i];
    if (i > 0) {
      p.resize(size.cols, size.rows);
      await sleep(3000); // real resize event + poller fallback, several repaint cycles
    }

    const chunk = raw.slice(consumedLen);
    consumedLen = raw.length;
    if (i > 0) term.resize(size.cols, size.rows);
    await new Promise((resolve) => term.write(chunk, resolve));

    const lines = [];
    for (let y = 0; y < size.rows; y++) {
      const line = term.buffer.active.getLine(y);
      lines.push(line ? line.translateToString(true) : "");
    }
    // Receipts record repo-relative names only -- an absolute local path here would leak a
    // machine-specific worktree location into a tracked, committed manifest.
    const txtName = `${TAG}-${size.label}-${size.cols}x${size.rows}.txt`;
    const pngName = `${TAG}-${size.label}-${size.cols}x${size.rows}.png`;
    writeFileSync(path.join(OUT_DIR, txtName), lines.join("\n") + "\n");

    const png = rasterizeFrame(term, size.cols, size.rows);
    writeFileSync(path.join(OUT_DIR, pngName), png);

    receipts.push({ label: size.label, cols: size.cols, rows: size.rows, txtName, pngName });
    console.log(JSON.stringify({ event: "captured", label: size.label, cols: size.cols, rows: size.rows }));
  }

  p.kill();
  await sleep(300);
  term.dispose();

  writeFileSync(
    path.join(OUT_DIR, `${TAG}-manifest.json`),
    JSON.stringify({ ts: new Date().toISOString(), tag: TAG, pid: p.pid, receipts }, null, 2) + "\n",
  );
  console.log(JSON.stringify({ event: "done", tag: TAG, pid: p.pid }));
}

main().catch((err) => {
  console.error("FATAL:", err);
  process.exit(1);
});
