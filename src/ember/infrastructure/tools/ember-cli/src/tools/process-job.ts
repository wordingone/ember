// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// tools/process-job.ts -- one Windows job object for every process the shell tools start.
//
// Blind test S27/S28: a process a tool call left running (`cmd &`, `start /b`, PowerShell
// `Start-Process -WindowStyle Hidden`) survived the tool call AND the death of ember itself, and
// kept running after the window closed. The tools already end their own process tree on a timeout
// or Esc; what nothing covered is the session ending.
//
// The job is created with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE and ember holds the only handle, so
// the OS ends every process in it the moment ember exits, however it exits (normal exit, crash,
// the console window being closed, a kill). A process the model starts in the background may
// outlive the single tool call (a dev server the next call talks to) but never the session.
// Children of a job member join the job on their own, so a shell's grandchildren are covered.
//
// Known gap, kept honest: a process is assigned right after spawn, so a descendant created in the
// few microseconds before the assignment is not in the job. A shell needs milliseconds to start
// its first child, so this does not happen in practice.
//
// Windows only, Bun only (bun:ffi). Anywhere else the module reports "unavailable" and the tools
// behave as before. This lives in the tool layer on purpose: the model-server holder in
// entrypoints/process-entry.ts is a separate mechanism with a separate lifetime.

import { harnessWarn } from "../utils/harness-warn.ts";

const JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9;
const JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000;
const PROCESS_TERMINATE = 0x0001;
const PROCESS_SET_QUOTA = 0x0100;
/** sizeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION) on x64; LimitFlags is the u32 at offset 16. */
const EXTENDED_LIMIT_INFO_BYTES = 144;
const LIMIT_FLAGS_OFFSET = 16;

type Handle = number | bigint;

interface Kernel32 {
  CreateJobObjectW(attrs: null, name: null): Handle | null;
  SetInformationJobObject(job: Handle, infoClass: number, info: unknown, size: number): number;
  AssignProcessToJobObject(job: Handle, process: Handle): number;
  OpenProcess(access: number, inherit: number, pid: number): Handle | null;
  CloseHandle(handle: Handle): number;
}

let kernel32: Kernel32 | null | undefined;
let ptrOf: ((view: Uint8Array) => unknown) | null = null;
let sessionJob: Handle | null | undefined;

function loadKernel32(): Kernel32 | null {
  if (kernel32 !== undefined) return kernel32;
  kernel32 = null;
  if (process.platform !== "win32") return kernel32;
  if (process.env["EMBER_DISABLE_PROCESS_JOB"] === "1") return kernel32;
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const ffi = require("bun:ffi") as typeof import("bun:ffi");
    const lib = ffi.dlopen("kernel32.dll", {
      CreateJobObjectW: { args: [ffi.FFIType.ptr, ffi.FFIType.ptr], returns: ffi.FFIType.ptr },
      SetInformationJobObject: { args: [ffi.FFIType.ptr, ffi.FFIType.i32, ffi.FFIType.ptr, ffi.FFIType.u32], returns: ffi.FFIType.i32 },
      AssignProcessToJobObject: { args: [ffi.FFIType.ptr, ffi.FFIType.ptr], returns: ffi.FFIType.i32 },
      OpenProcess: { args: [ffi.FFIType.u32, ffi.FFIType.i32, ffi.FFIType.u32], returns: ffi.FFIType.ptr },
      CloseHandle: { args: [ffi.FFIType.ptr], returns: ffi.FFIType.i32 },
    });
    ptrOf = (view) => ffi.ptr(view);
    kernel32 = lib.symbols as unknown as Kernel32;
  } catch (err) {
    harnessWarn(`[process-job] unavailable (${err instanceof Error ? err.message : String(err)}); background processes will not be ended with the session`);
    kernel32 = null;
  }
  return kernel32;
}

function createSessionJob(): Handle | null {
  const k = loadKernel32();
  if (!k || !ptrOf) return null;
  try {
    const job = k.CreateJobObjectW(null, null);
    if (!job) return null;
    const info = new Uint8Array(EXTENDED_LIMIT_INFO_BYTES);
    new DataView(info.buffer).setUint32(LIMIT_FLAGS_OFFSET, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, true);
    if (!k.SetInformationJobObject(job, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS, ptrOf(info), EXTENDED_LIMIT_INFO_BYTES)) {
      k.CloseHandle(job);
      return null;
    }
    return job;
  } catch (err) {
    harnessWarn(`[process-job] could not create the job object (${err instanceof Error ? err.message : String(err)})`);
    return null;
  }
}

/** True when this platform and runtime can end background processes with the session. */
export function sessionJobAvailable(): boolean {
  if (sessionJob === undefined) sessionJob = createSessionJob();
  return sessionJob !== null;
}

/**
 * Puts `pid` (a process this session just started) in the session job. Returns whether it is
 * now covered. Never throws: a failure means the process behaves as it did before this module.
 */
export function assignToSessionJob(pid: number | undefined): boolean {
  if (pid === undefined || !sessionJobAvailable()) return false;
  const k = kernel32;
  const job = sessionJob;
  if (!k || job === null || job === undefined) return false;
  try {
    const handle = k.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, 0, pid);
    if (!handle) return false;
    try {
      return k.AssignProcessToJobObject(job, handle) !== 0;
    } finally {
      k.CloseHandle(handle);
    }
  } catch {
    return false;
  }
}
