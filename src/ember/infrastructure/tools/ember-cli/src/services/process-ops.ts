// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// services/process-ops.ts -- the narrow process surface the model-server lease needs (#2378):
// who owns a LISTEN socket, what a PID's identity is (creation time + full command line), and
// "verify this identity on ONE handle, then terminate that handle".
//
// Everything is synchronous on purpose: the exit/SIGHUP paths cannot await.  The Windows
// implementation uses bun:ffi against kernel32/ntdll (about 1 ms per call, measured) instead of
// shelling out to PowerShell/wmic (wmic is gone on current Windows 11; PowerShell costs 300+ ms).
//
// Selection is by verified PID only, never by name.  terminate() opens the process once, reads
// its creation time and command line from THAT handle, compares them with what was recorded, and
// only then calls TerminateProcess on the same handle, so a recycled PID cannot be hit between
// the check and the kill.

import { spawnSync } from "node:child_process";
import { dlopen, FFIType } from "bun:ffi";

/** What pins a process: PID alone is reusable; PID + creation time + command line is not. */
export interface ProcessIdentity {
  pid: number;
  /** Creation time as the raw FILETIME tick count (decimal string, 100 ns units). */
  startTime: string;
  cmdline: string;
}

export type TerminateOutcome =
  | "terminated" // identity matched, process ended
  | "gone"       // no such process (already exited)
  | "mismatch"   // a process holds this PID but is not the recorded one: left alone
  | "failed";    // identity matched but the process could not be ended (access denied, timeout)

export interface ProcessOps {
  /** Identity of the live process with this PID, or null when it is gone or unreadable. */
  identify(pid: number): ProcessIdentity | null;
  /** PID owning the TCP LISTEN socket on `port`: null when none, "ambiguous" when several PIDs do. */
  listenerPid(port: number): number | null | "ambiguous";
  /** Verify on one handle, then terminate that handle.  `expected` is the recorded identity;
   *  `accept` re-checks the live identity (for example "still a llama-server on this port"). */
  terminate(expected: ProcessIdentity, accept: (live: ProcessIdentity) => boolean): TerminateOutcome;
  /** Identity of this process. */
  self(): ProcessIdentity | null;
}

/** Listening-socket owners for `port` in `netstat -ano -p TCP` output.  A listening row has an
 *  unspecified foreign address (0.0.0.0:0 or [::]:0); the state word is localized, so it is
 *  not used.  Returns the distinct owning PIDs. */
export function parseNetstatListeners(text: string, port: number): number[] {
  const pids = new Set<number>();
  for (const raw of text.split(/\r?\n/)) {
    const cols = raw.trim().split(/\s+/);
    if (cols.length < 5 || cols[0]!.toUpperCase() !== "TCP") continue;
    const local = cols[1]!;
    const foreign = cols[2]!;
    if (foreign !== "0.0.0.0:0" && foreign !== "[::]:0" && foreign !== "*:*") continue;
    if (!local.endsWith(`:${port}`)) continue;
    const pid = Number(cols[cols.length - 1]);
    if (Number.isInteger(pid) && pid > 0) pids.add(pid);
  }
  return [...pids];
}

const PROCESS_TERMINATE = 0x0001;
const PROCESS_QUERY_LIMITED_INFORMATION = 0x1000;
const SYNCHRONIZE = 0x00100000;
const ERROR_ACCESS_DENIED = 5;
const WAIT_OBJECT_0 = 0;
const PROCESS_COMMAND_LINE_INFORMATION = 60;

/** The Windows implementation, or null when this platform/runtime cannot provide it (the
 *  caller then keeps the pre-lease behavior). */
export function createWin32ProcessOps(): ProcessOps | null {
  if (process.platform !== "win32") return null;
  if (process.arch !== "x64" && process.arch !== "arm64") return null; // UNICODE_STRING layout below is the 64-bit one
  let k: ReturnType<typeof loadKernel32>;
  let nt: ReturnType<typeof loadNtdll>;
  try {
    k = loadKernel32();
    nt = loadNtdll();
  } catch {
    return null;
  }

  /** Read creation time + command line from an open handle; null when either is unreadable
   *  or the process has already exited. */
  const readIdentity = (pid: number, handle: NonNullable<ReturnType<typeof k.symbols.OpenProcess>>): ProcessIdentity | null => {
    const times = new BigUint64Array(4); // creation, exit, kernel, user
    const ok = k.symbols.GetProcessTimes(handle, times, times.subarray(1), times.subarray(2), times.subarray(3));
    if (!ok || times[1] !== 0n) return null; // a non-zero exit time means it already ended
    const buf = new Uint8Array(65536);
    const returned = new Uint32Array(1);
    const status = nt.symbols.NtQueryInformationProcess(handle, PROCESS_COMMAND_LINE_INFORMATION, buf, buf.length, returned);
    if (status !== 0) return null;
    // UNICODE_STRING header (16 bytes on 64-bit): Length u16, MaximumLength u16, pad, Buffer ptr;
    // the characters follow the header inside the same buffer.
    const len = new DataView(buf.buffer).getUint16(0, true);
    if (len === 0 || 16 + len > buf.length) return null;
    const cmdline = new TextDecoder("utf-16le").decode(buf.subarray(16, 16 + len));
    return { pid, startTime: times[0]!.toString(), cmdline };
  };

  const identify = (pid: number): ProcessIdentity | null => {
    if (!Number.isInteger(pid) || pid <= 0) return null;
    const handle = k.symbols.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
    if (!handle) return null;
    try {
      return readIdentity(pid, handle);
    } finally {
      k.symbols.CloseHandle(handle);
    }
  };

  return {
    identify,
    self: () => identify(process.pid),
    listenerPid(port) {
      const r = spawnSync("netstat", ["-ano", "-p", "TCP"], { encoding: "utf-8", windowsHide: true, timeout: 10_000 });
      if (r.status !== 0 || typeof r.stdout !== "string") return null;
      const pids = parseNetstatListeners(r.stdout, port);
      if (pids.length === 0) return null;
      return pids.length === 1 ? pids[0]! : "ambiguous";
    },
    terminate(expected, accept) {
      const handle = k.symbols.OpenProcess(
        PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE | SYNCHRONIZE, 0, expected.pid);
      if (!handle) return k.symbols.GetLastError() === ERROR_ACCESS_DENIED ? "failed" : "gone";
      try {
        const live = readIdentity(expected.pid, handle);
        if (live === null) return "gone";
        if (live.startTime !== expected.startTime || live.cmdline !== expected.cmdline || !accept(live)) return "mismatch";
        if (!k.symbols.TerminateProcess(handle, 1)) return "failed";
        return k.symbols.WaitForSingleObject(handle, 5000) === WAIT_OBJECT_0 ? "terminated" : "failed";
      } finally {
        k.symbols.CloseHandle(handle);
      }
    },
  };
}

// dlopen runs only inside createWin32ProcessOps(), so non-Windows runs and the unit tests never load a DLL.
function loadKernel32() {
  return dlopen("kernel32.dll", {
    OpenProcess: { args: [FFIType.u32, FFIType.i32, FFIType.u32], returns: FFIType.ptr },
    CloseHandle: { args: [FFIType.ptr], returns: FFIType.i32 },
    GetProcessTimes: { args: [FFIType.ptr, FFIType.ptr, FFIType.ptr, FFIType.ptr, FFIType.ptr], returns: FFIType.i32 },
    TerminateProcess: { args: [FFIType.ptr, FFIType.u32], returns: FFIType.i32 },
    WaitForSingleObject: { args: [FFIType.ptr, FFIType.u32], returns: FFIType.u32 },
    GetLastError: { args: [], returns: FFIType.u32 },
  });
}

function loadNtdll() {
  return dlopen("ntdll.dll", {
    NtQueryInformationProcess: {
      args: [FFIType.ptr, FFIType.u32, FFIType.ptr, FFIType.u32, FFIType.ptr],
      returns: FFIType.i32,
    },
  });
}
