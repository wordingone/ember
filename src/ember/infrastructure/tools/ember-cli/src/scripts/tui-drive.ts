// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
//
// tui-drive: drive a REAL interactive terminal program (ember-cli's Ink cockpit, cmd, powershell)
// the way a person at a terminal does -- type, press keys, read the rendered screen -- without
// touching the operator's mouse or keyboard. One shell command per action, so agents use it from
// Bash. See TUI-DRIVE.md next to this file.
//
//   bun run tui-drive.ts start --name S --cwd DIR [--cols 120 --rows 40] [--env K=V ...] -- cmd args...
//   bun run tui-drive.ts send S --text "hi" [--enter] [--paste: one write, like a terminal paste]     |  send S --keys "enter|esc|up|ctrl+c"
//   bun run tui-drive.ts screen S [--all]                 |  wait S --for REGEX [--timeout 120]
//   bun run tui-drive.ts log S [--bytes N]                |  stop S  |  list
//
// ARCHITECTURE. `start` spawns a detached background DAEMON (this same file, `__daemon`) which owns
// the node-pty child and an @xterm/headless terminal, and serves JSON-lines requests on the Windows
// named pipe \\.\pipe\tui-drive-<name>. Every other command is a short-lived client of that pipe.
//
// THE DAEMON RUNS UNDER NODE, NOT BUN. Under bun node-pty's output works but every input write
// throws ERR_SOCKET_CLOSED (documented in build-tools/drive-train-frame.ts). The client side runs
// under either runtime; `start` always launches the daemon with `node --experimental-strip-types`.
// So this file must stay strip-types clean: no enums, no parameter properties, `import type` for types.

import { spawn as spawnProc, spawnSync } from "node:child_process";
import {
  appendFileSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync,
} from "node:fs";
import net from "node:net";
import { join, resolve, delimiter, isAbsolute } from "node:path";
import { fileURLToPath } from "node:url";
import xtermHeadless from "@xterm/headless";
import { spawn as spawnPty } from "node-pty";
import type { IPty } from "node-pty";

const { Terminal } = xtermHeadless as unknown as { Terminal: new (opts: unknown) => any };

const SESSIONS_ROOT = process.env.TUI_DRIVE_ROOT ?? "A:/ember-wt/tui-sessions";
const KILL_RECEIPTS = process.env.TUI_DRIVE_KILL_RECEIPTS ?? ""; // path of the fleet kill-receipts JSONL; unset = no receipt written
const SELF = fileURLToPath(import.meta.url);
const LOG_CAP = 4 * 1024 * 1024; // raw.log keeps the last ~4 MiB in memory; the file is append-only
const DEFAULT_TTL_MIN = 120;

type Json = Record<string, any>;

// ----------------------------------------------------------------------------- helpers

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}
function sessDir(name: string): string {
  return join(SESSIONS_ROOT, name);
}
function pipePath(name: string): string {
  return `\\\\.\\pipe\\tui-drive-${name}`;
}
function checkName(name: string | undefined): string {
  if (!name || !/^[A-Za-z0-9_.-]{1,64}$/u.test(name)) {
    throw new Error(`bad session name ${JSON.stringify(name)} (allowed: A-Z a-z 0-9 _ . -)`);
  }
  return name;
}
function readJson(path: string): Json | undefined {
  try { return JSON.parse(readFileSync(path, "utf8")); } catch { return undefined; }
}
function pidAlive(pid: number): boolean {
  try { process.kill(pid, 0); return true; } catch (e: any) { return e?.code === "EPERM"; }
}
function nowIso(): string {
  return new Date().toISOString();
}

/** Resolve a bare command name via PATH + PATHEXT (node-pty/ConPTY wants a real path). */
function resolveExe(cmd: string, cwd: string): string {
  const exts = (process.env.PATHEXT ?? ".EXE;.CMD;.BAT;.COM").split(";").filter(Boolean);
  const hasExt = /\.[A-Za-z0-9]{1,4}$/u.test(cmd);
  const candidates = (base: string): string[] => (hasExt ? [base] : [...exts.map((e) => base + e), base]);
  if (isAbsolute(cmd) || cmd.includes("/") || cmd.includes("\\")) {
    for (const c of candidates(resolve(cwd, cmd))) if (existsSync(c)) return c;
    return cmd;
  }
  for (const dir of (process.env.PATH ?? "").split(delimiter)) {
    if (!dir) continue;
    for (const c of candidates(join(dir, cmd))) if (existsSync(c)) return c;
  }
  return cmd;
}

/** Append one kill receipt (JSON serializer, UTF-8) BEFORE a kill, per kill-discipline. */
function writeKillReceipt(pids: number[], matchRule: string): void {
  if (!KILL_RECEIPTS) {
    console.error("[tui-drive] NOTE: TUI_DRIVE_KILL_RECEIPTS unset; no kill receipt written (write one yourself if your rules require it)");
    return;
  }
  try {
    mkdirSync(join(KILL_RECEIPTS, ".."), { recursive: true });
    const row = {
      ts: nowIso(), script: "tui-drive.ts", pids, match_rule: matchRule, survivors_expected: "none",
    };
    appendFileSync(KILL_RECEIPTS, `${JSON.stringify(row)}\n`, "utf8");
  } catch (e: any) {
    console.error(`[tui-drive] WARNING: could not write kill receipt: ${e?.message ?? e}`);
  }
}

function killTree(pid: number): void {
  spawnSync("taskkill", ["/PID", String(pid), "/T", "/F"], { windowsHide: true, stdio: "ignore", timeout: 10_000 });
}

// ----------------------------------------------------------------------------- keys

const KEY_MAP: Record<string, string> = {
  enter: "\r", return: "\r", esc: "\x1b", escape: "\x1b", tab: "\t", "shift+tab": "\x1b[Z", backtab: "\x1b[Z",
  space: " ", backspace: "\x7f", bs: "\x7f", delete: "\x1b[3~", del: "\x1b[3~", insert: "\x1b[2~",
  up: "\x1b[A", down: "\x1b[B", right: "\x1b[C", left: "\x1b[D",
  home: "\x1b[H", end: "\x1b[F", pageup: "\x1b[5~", pgup: "\x1b[5~", pagedown: "\x1b[6~", pgdn: "\x1b[6~",
  f1: "\x1bOP", f2: "\x1bOQ", f3: "\x1bOR", f4: "\x1bOS", f5: "\x1b[15~", f6: "\x1b[17~", f7: "\x1b[18~",
  f8: "\x1b[19~", f9: "\x1b[20~", f10: "\x1b[21~", f11: "\x1b[23~", f12: "\x1b[24~",
  "ctrl+up": "\x1b[1;5A", "ctrl+down": "\x1b[1;5B", "ctrl+right": "\x1b[1;5C", "ctrl+left": "\x1b[1;5D",
  "alt+enter": "\x1b\r", "alt+backspace": "\x1b\x7f",
};

/** "up up enter" / "up|enter" / "down*3" -> list of raw sequences. */
export function parseKeys(spec: string): string[] {
  const out: string[] = [];
  for (const rawTok of spec.split(/[\s|,]+/u).filter(Boolean)) {
    let tok = rawTok.toLowerCase();
    let times = 1;
    const m = /^(.*)\*(\d+)$/u.exec(tok);
    if (m) { tok = m[1]; times = Math.min(500, Number(m[2])); }
    let seq = KEY_MAP[tok];
    if (seq === undefined) {
      const ctrl = /^ctrl\+([a-z\[\]\\^_@])$/u.exec(tok);
      const alt = /^alt\+(.)$/u.exec(tok);
      if (ctrl) {
        const c = ctrl[1];
        seq = c === "@" ? "\x00" : String.fromCharCode(c.toUpperCase().charCodeAt(0) - 64);
      } else if (alt) {
        seq = `\x1b${alt[1]}`;
      } else if (tok.length === 1) {
        seq = rawTok; // a literal single character
      } else {
        throw new Error(`unknown key ${JSON.stringify(rawTok)}`);
      }
    }
    for (let i = 0; i < times; i++) out.push(seq);
  }
  return out;
}

// ----------------------------------------------------------------------------- daemon

async function daemonMain(name: string): Promise<void> {
  const dir = sessDir(name);
  const cfg = readJson(join(dir, "session.json"));
  if (!cfg) throw new Error("daemon: missing session.json");
  const cols: number = cfg.cols;
  const rows: number = cfg.rows;
  const term: any = new Terminal({ cols, rows, allowProposedApi: true, scrollback: 2000 });
  let writes: Promise<void> = Promise.resolve();
  let raw = "";
  let rawBytesTotal = 0;
  let lastOutputAt = Date.now();
  let gotOutput = false;
  let exit: { code: number | null; signal: number | null; at: string } | undefined;
  let lastRequestAt = Date.now();
  let inputChain: Promise<void> = Promise.resolve();
  const startedAt = Date.now();
  let dirty = false;

  const viewport = (): string[] => {
    const b = term.buffer.active;
    const lines: string[] = [];
    for (let y = 0; y < term.rows; y++) lines.push(b.getLine(b.viewportY + y)?.translateToString(true) ?? "");
    return lines;
  };
  const allLines = (): string[] => {
    const b = term.buffer.active;
    const lines: string[] = [];
    for (let y = 0; y < b.length; y++) lines.push(b.getLine(y)?.translateToString(true) ?? "");
    return lines;
  };
  const trimEnd = (lines: string[]): string[] => {
    let n = lines.length;
    while (n > 0 && lines[n - 1].trim() === "") n--;
    return lines.slice(0, n);
  };
  const flushScreen = (): void => {
    try { writeFileSync(join(dir, "screen.txt"), `${trimEnd(viewport()).join("\n")}\n`, "utf8"); } catch { /* best effort */ }
    dirty = false;
  };

  const exe = resolveExe(cfg.command[0], cfg.cwd);
  const env = { ...process.env, ...cfg.env, TERM: "xterm-256color" } as Record<string, string>;
  delete env.TUI_DRIVE_DAEMON;

  let pty: IPty;
  try {
    pty = spawnPty(exe, cfg.command.slice(1), { name: "xterm-256color", cols, rows, cwd: cfg.cwd, env, useConpty: true });
  } catch (e: any) {
    writeFileSync(join(dir, "exit.json"), JSON.stringify({ spawn_error: String(e?.message ?? e), at: nowIso() }, null, 2));
    throw e;
  }
  const meta = {
    name, daemon_pid: process.pid, child_pid: pty.pid, command: cfg.command, resolved_exe: exe, cwd: cfg.cwd,
    cols, rows, pipe: pipePath(name), started_at: nowIso(), ttl_min: cfg.ttl_min,
  };
  writeFileSync(join(dir, "meta.json"), JSON.stringify(meta, null, 2));

  pty.onData((data: string) => {
    gotOutput = true;
    lastOutputAt = Date.now();
    raw += data;
    rawBytesTotal += data.length;
    if (raw.length > LOG_CAP) raw = raw.slice(raw.length - LOG_CAP);
    try { appendFileSync(join(dir, "raw.log"), data, "utf8"); } catch { /* best effort */ }
    writes = writes.then(() => new Promise<void>((done) => term.write(data, done)));
    dirty = true;
  });
  pty.onExit(({ exitCode, signal }: { exitCode: number; signal?: number }) => {
    exit = { code: exitCode, signal: signal ?? null, at: nowIso() };
    writeFileSync(join(dir, "exit.json"), JSON.stringify(exit, null, 2));
    writes.then(flushScreen);
  });
  const flusher = setInterval(() => { if (dirty) writes.then(flushScreen); }, 300);

  const settle = async (): Promise<void> => { await writes; };

  const sendInput = (chunks: string[], delayMs: number): Promise<void> => {
    const job = inputChain.then(async () => {
      // A write before the child attaches to ConPTY fails like a dead child; wait for first output.
      const deadline = Date.now() + 3000;
      while (!gotOutput && !exit && Date.now() < deadline) await sleep(50);
      for (const c of chunks) {
        if (exit) throw new Error("child has exited");
        pty.write(c);
        if (delayMs > 0) await sleep(delayMs);
      }
    });
    inputChain = job.catch(() => undefined);
    return job;
  };

  const status = (): Json => ({
    name, daemon_pid: process.pid, child_pid: pty.pid, cols, rows,
    child: exit ? "exited" : "running", exit: exit ?? null,
    idle_ms: Date.now() - lastOutputAt, uptime_s: Math.round((Date.now() - startedAt) / 1000),
    raw_chars: rawBytesTotal,
  });

  const handle = async (req: Json): Promise<Json> => {
    lastRequestAt = Date.now();
    switch (req.op) {
      case "ping": return { ok: true, ...status() };
      case "send": {
        const chunks: string[] = [];
        if (typeof req.text === "string") for (const ch of Array.from(req.text as string)) chunks.push(ch === "\n" ? "\r" : ch);
        if (Array.isArray(req.seqs)) chunks.push(...(req.seqs as string[]));
        await sendInput(chunks, typeof req.delay_ms === "number" ? req.delay_ms : 15);
        await sleep(typeof req.settle_ms === "number" ? req.settle_ms : 250);
        await settle();
        return { ok: true, sent: chunks.length, ...status() };
      }
      case "screen": {
        // Wait out an in-flight burst so the screen is a consistent frame, not a half-painted one.
        const quiet = typeof req.quiet_ms === "number" ? req.quiet_ms : 120;
        const until = Date.now() + 1500;
        while (Date.now() - lastOutputAt < quiet && Date.now() < until) await sleep(30);
        await settle();
        const lines = req.all ? trimEnd(allLines()) : trimEnd(viewport());
        const b = term.buffer.active;
        return {
          ok: true, lines, cursor: { row: b.cursorY + 1, col: b.cursorX + 1 }, ...status(),
        };
      }
      case "log": {
        const n = typeof req.bytes === "number" ? req.bytes : 4000;
        return { ok: true, text: raw.slice(Math.max(0, raw.length - n)), ...status() };
      }
      case "stop": {
        const pid = pty.pid;
        const wasRunning = !exit;
        if (wasRunning) {
          writeKillReceipt([pid], `tui-drive stop ${name}: pty child spawned by this session daemon (pid ${process.pid}); tree kill via taskkill /T`);
          killTree(pid);
        }
        await sleep(300);
        await settle();
        flushScreen();
        const rec = { stopped_at: nowIso(), child_pid: pid, daemon_pid: process.pid, was_running: wasRunning, exit: exit ?? null };
        writeFileSync(join(dir, "stopped.json"), JSON.stringify(rec, null, 2));
        setTimeout(() => process.exit(0), 150);
        return { ok: true, ...rec };
      }
      default: return { ok: false, error: `unknown op ${req.op}` };
    }
  };

  const server = net.createServer((sock) => {
    let buf = "";
    sock.setEncoding("utf8");
    sock.on("error", () => undefined);
    sock.on("data", (d: string) => {
      buf += d;
      let i: number;
      while ((i = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, i);
        buf = buf.slice(i + 1);
        let req: Json;
        try { req = JSON.parse(line); } catch { sock.write(`${JSON.stringify({ ok: false, error: "bad json" })}\n`); continue; }
        handle(req).then(
          (res) => sock.write(`${JSON.stringify(res)}\n`),
          (err) => sock.write(`${JSON.stringify({ ok: false, error: String(err?.message ?? err) })}\n`),
        );
      }
    });
  });
  server.listen(pipePath(name));

  // TTL: never leak a session (and its model server) if the agent forgets `stop`.
  const ttlMs = (cfg.ttl_min ?? DEFAULT_TTL_MIN) * 60_000;
  setInterval(() => {
    if (Date.now() - lastRequestAt > ttlMs) {
      void handle({ op: "stop" }).then(() => undefined);
    }
  }, 30_000).unref?.();
  void flusher;
}

// ----------------------------------------------------------------------------- client

function request(name: string, req: Json, timeoutMs = 30_000): Promise<Json> {
  return new Promise((resolveP, reject) => {
    const sock = net.connect(pipePath(name));
    let buf = "";
    const timer = setTimeout(() => { sock.destroy(); reject(new Error(`timeout talking to session ${name}`)); }, timeoutMs);
    sock.setEncoding("utf8");
    sock.on("connect", () => sock.write(`${JSON.stringify(req)}\n`));
    sock.on("data", (d: string) => {
      buf += d;
      const i = buf.indexOf("\n");
      if (i >= 0) {
        clearTimeout(timer);
        sock.end();
        try { resolveP(JSON.parse(buf.slice(0, i))); } catch (e) { reject(e); }
      }
    });
    sock.on("error", (e) => { clearTimeout(timer); reject(e); });
  });
}

async function alive(name: string): Promise<boolean> {
  try { return Boolean((await request(name, { op: "ping" }, 3000)).ok); } catch { return false; }
}

interface Args { pos: string[]; opts: Record<string, string[]>; flags: Set<string>; rest: string[] }
const BOOL_FLAGS = new Set(["enter", "all", "json", "paste"]);
function parseArgs(argv: string[]): Args {
  const a: Args = { pos: [], opts: {}, flags: new Set(), rest: [] };
  for (let i = 0; i < argv.length; i++) {
    const t = argv[i];
    if (t === "--") { a.rest = argv.slice(i + 1); break; }
    if (t.startsWith("--")) {
      const k = t.slice(2);
      if (BOOL_FLAGS.has(k)) a.flags.add(k);
      else { (a.opts[k] ??= []).push(argv[++i] ?? ""); }
    } else a.pos.push(t);
  }
  return a;
}
const opt = (a: Args, k: string): string | undefined => a.opts[k]?.[a.opts[k].length - 1];

function printScreen(res: Json, name: string): void {
  process.stdout.write(`${res.lines.join("\n")}\n`);
  const idle = res.idle_ms;
  process.stdout.write(
    `[tui-drive ${name} ${res.cols}x${res.rows} cursor row=${res.cursor.row} col=${res.cursor.col} child=${res.child}`
    + `${res.exit ? ` exit=${res.exit.code}` : ""} idle=${idle}ms]\n`,
  );
}

async function cmdStart(a: Args): Promise<number> {
  const name = checkName(opt(a, "name"));
  if (a.rest.length === 0) throw new Error("start needs a command after `--`");
  const cwd = resolve(opt(a, "cwd") ?? process.cwd());
  if (!existsSync(cwd)) throw new Error(`cwd does not exist: ${cwd}`);
  const cols = Number(opt(a, "cols") ?? 120);
  const rows = Number(opt(a, "rows") ?? 40);
  const env: Record<string, string> = {};
  for (const kv of a.opts.env ?? []) {
    const i = kv.indexOf("=");
    if (i <= 0) throw new Error(`--env wants K=V, got ${kv}`);
    env[kv.slice(0, i)] = kv.slice(i + 1);
  }
  const dir = sessDir(name);
  if (existsSync(dir)) {
    if (await alive(name)) throw new Error(`session ${name} is already running (stop it first)`);
    rmSync(dir, { recursive: true, force: true });
  }
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "session.json"), JSON.stringify({
    command: a.rest, cwd, cols, rows, env, ttl_min: Number(opt(a, "ttl") ?? DEFAULT_TTL_MIN),
  }, null, 2));
  const out = join(dir, "daemon.log");
  const node = process.env.TUI_DRIVE_NODE ?? "node";
  const d = spawnProc(node, ["--experimental-strip-types", "--no-warnings", SELF, "__daemon", name], {
    detached: true, stdio: ["ignore", "ignore", "ignore"], windowsHide: true, cwd: dir,
    env: { ...process.env, TUI_DRIVE_DAEMON_LOG: out },
  });
  d.unref();
  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline) {
    if (await alive(name)) {
      const meta = readJson(join(dir, "meta.json")) ?? {};
      console.log(`started ${name}: daemon_pid=${meta.daemon_pid} child_pid=${meta.child_pid} ${cols}x${rows} dir=${dir}`);
      return 0;
    }
    const ex = readJson(join(dir, "exit.json"));
    if (ex?.spawn_error) throw new Error(`spawn failed: ${ex.spawn_error}`);
    await sleep(150);
  }
  throw new Error(`daemon for ${name} did not come up in 20s (check ${out}; node on PATH?)`);
}

async function cmdSend(a: Args): Promise<number> {
  const name = checkName(a.pos[0]);
  const text = opt(a, "text");
  const keys = opt(a, "keys");
  if (text === undefined && keys === undefined) throw new Error("send needs --text and/or --keys");
  const seqs: string[] = [];
  if (keys !== undefined) seqs.push(...parseKeys(keys));
  if (a.flags.has("enter")) seqs.push("\r");
  // --paste: deliver the text as ONE write, the way a terminal delivers a paste
  // (newlines as CR), instead of typing it a character at a time.
  if (a.flags.has("paste") && text !== undefined) {
    const res = await request(name, { op: "send", text: "", seqs: [text.replace(/\r?\n/g, "\r"), ...seqs], delay_ms: 15 });
    if (!res.ok) { console.error(res.error); return 2; }
    console.log(`sent ok (paste); child=${res.child}`);
    return 0;
  }
  const res = await request(name, { op: "send", text: text ?? "", seqs: text !== undefined && keys !== undefined ? [] : seqs, delay_ms: 15 });
  if (text !== undefined && keys !== undefined) {
    // text first, then keys (+enter) as a second ordered request
    const r2 = await request(name, { op: "send", seqs });
    if (!r2.ok) { console.error(r2.error); return 2; }
  }
  if (!res.ok) { console.error(res.error); return 2; }
  console.log(`sent ok; child=${res.child}${res.exit ? ` exit=${res.exit.code}` : ""}`);
  return 0;
}

async function offlineScreen(name: string): Promise<boolean> {
  const f = join(sessDir(name), "screen.txt");
  if (!existsSync(f)) return false;
  process.stdout.write(readFileSync(f, "utf8"));
  const ex = readJson(join(sessDir(name), "exit.json"));
  console.log(`[tui-drive ${name} SESSION ENDED (daemon gone); last saved screen above${ex ? `; exit=${ex.code}` : ""}]`);
  return true;
}

async function cmdScreen(a: Args): Promise<number> {
  const name = checkName(a.pos[0]);
  let res: Json;
  try { res = await request(name, { op: "screen", all: a.flags.has("all") }); } catch (e) {
    if (await offlineScreen(name)) return 3;
    throw e;
  }
  printScreen(res, name);
  return 0;
}

async function cmdWait(a: Args): Promise<number> {
  const name = checkName(a.pos[0]);
  const pattern = opt(a, "for");
  if (!pattern) throw new Error("wait needs --for REGEX");
  const re = new RegExp(pattern, "m");
  const timeoutS = Number(opt(a, "timeout") ?? 120);
  const deadline = Date.now() + timeoutS * 1000;
  let last: Json | undefined;
  for (;;) {
    try {
      last = await request(name, { op: "screen", quiet_ms: 60 });
    } catch (e) {
      console.error(`session ${name} unreachable (ended?)`);
      await offlineScreen(name);
      return 3;
    }
    if (re.test(last.lines.join("\n"))) { printScreen(last, name); return 0; }
    if (last.child === "exited") {
      console.error(`child exited (code ${last.exit?.code}) without the screen matching /${pattern}/`);
      printScreen(last, name);
      return 3;
    }
    if (Date.now() >= deadline) {
      console.error(`TIMEOUT after ${timeoutS}s waiting for /${pattern}/ ; last screen:`);
      printScreen(last, name);
      return 1;
    }
    await sleep(250);
  }
}

async function cmdLog(a: Args): Promise<number> {
  const name = checkName(a.pos[0]);
  const bytes = Number(opt(a, "bytes") ?? 4000);
  try {
    const res = await request(name, { op: "log", bytes });
    process.stdout.write(res.text);
  } catch {
    const f = join(sessDir(name), "raw.log");
    if (!existsSync(f)) throw new Error(`no such session ${name}`);
    const t = readFileSync(f, "utf8");
    process.stdout.write(t.slice(Math.max(0, t.length - bytes)));
  }
  process.stdout.write("\n");
  return 0;
}

async function cmdStop(a: Args): Promise<number> {
  const name = checkName(a.pos[0]);
  if (!(await alive(name))) {
    const st = readJson(join(sessDir(name), "stopped.json"));
    const meta = readJson(join(sessDir(name), "meta.json"));
    if (st) { console.log(`${name} already stopped (child_pid=${st.child_pid})`); return 0; }
    console.log(`${name}: daemon not reachable. child_pid=${meta?.child_pid ?? "?"} daemon_pid=${meta?.daemon_pid ?? "?"}`
      + ` (daemon alive=${meta?.daemon_pid ? pidAlive(meta.daemon_pid) : false}). Not killing blindly; verify PID cmdline and kill by hand with a receipt.`);
    return 2;
  }
  const res = await request(name, { op: "stop" }, 30_000);
  console.log(`stopped ${name}: child_pid=${res.child_pid} was_running=${res.was_running}`
    + `${res.exit ? ` exit=${res.exit.code}` : ""} (record: ${join(sessDir(name), "stopped.json")})`);
  return 0;
}

async function cmdList(): Promise<number> {
  if (!existsSync(SESSIONS_ROOT)) { console.log("(no sessions)"); return 0; }
  for (const name of readdirSync(SESSIONS_ROOT)) {
    const dir = join(SESSIONS_ROOT, name);
    const meta = readJson(join(dir, "meta.json"));
    if (!meta) continue;
    let state: string;
    try {
      const r = await request(name, { op: "ping" }, 2000);
      state = r.child === "running" ? "running" : `child-exited(code=${r.exit?.code})`;
    } catch {
      state = existsSync(join(dir, "stopped.json")) ? "stopped" : "daemon-dead";
    }
    console.log(`${name}\t${state}\tchild_pid=${meta.child_pid}\t${meta.cols}x${meta.rows}\t${(meta.command as string[]).join(" ")}`);
  }
  return 0;
}

async function main(): Promise<number> {
  const [cmd, ...rest] = process.argv.slice(2);
  if (cmd === "__daemon") {
    const name = checkName(rest[0]);
    try { await daemonMain(name); } catch (e: any) {
      try { appendFileSync(join(sessDir(name), "daemon.log"), `${nowIso()} ${e?.stack ?? e}\n`); } catch { /* ignore */ }
      process.exit(1);
    }
    return -1; // keep alive
  }
  const a = parseArgs(rest);
  switch (cmd) {
    case "start": return cmdStart(a);
    case "send": return cmdSend(a);
    case "screen": return cmdScreen(a);
    case "wait": return cmdWait(a);
    case "log": return cmdLog(a);
    case "stop": return cmdStop(a);
    case "list": return cmdList();
    default:
      console.error("usage: tui-drive <start|send|screen|wait|log|stop|list> ...  (see TUI-DRIVE.md)");
      return 64;
  }
}

if (process.argv[1] && resolve(process.argv[1]) === resolve(SELF)) {
  main().then(
    (code) => { if (code >= 0) process.exit(code); },
    (e) => { console.error(`tui-drive: ${e?.message ?? e}`); process.exit(2); },
  );
}
