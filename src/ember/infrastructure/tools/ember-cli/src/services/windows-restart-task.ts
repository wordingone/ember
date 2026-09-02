// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import {
  mkdir,
  mkdtemp,
  readFile,
  rename,
  rm,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { basename, dirname, join, win32 } from "node:path";
import { promisify } from "node:util";
import { getEmberConfigHomeDir } from "../utils/env-detection.ts";

export const WINDOWS_RESTART_TASK_NAME = "\\Ember\\Cockpit";

export interface WindowsRestartTaskOptions {
  executablePath: string;
}

export interface WindowsRestartTaskReceipt {
  schemaVersion: "ember-windows-restart-task/v1";
  result: "INSTALLED_VERIFIED";
  installedAt: string;
  taskName: typeof WINDOWS_RESTART_TASK_NAME;
  executableName: "ember.exe";
  executableSha256: string;
  userSidSha256: string;
  requestedTaskXmlSha256: string;
  installedTaskXmlSha256: string;
  restartInterval: "PT1M";
  restartCount: 999;
  multipleInstancesPolicy: "IgnoreNew";
  runLevel: "LeastPrivilege";
}

interface CommandResult {
  stdout: string;
  stderr: string;
  exitCode: number;
}

type ReadFile = (path: string) => Promise<Buffer>;
type WriteFile = (path: string, data: string | Buffer) => Promise<void>;

export interface WindowsRestartTaskDeps {
  platform?: NodeJS.Platform;
  now?: () => Date;
  readFile?: ReadFile;
  writeFile?: WriteFile;
  makeTempDir?: () => Promise<string>;
  removeDir?: (path: string) => Promise<void>;
  resolveCurrentUserSid?: () => Promise<string>;
  run?: (file: string, args: string[]) => Promise<CommandResult>;
  receiptPath?: string;
}

function sha256(bytes: string | Buffer): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function xmlEscape(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function requireWindowsExecutable(executablePath: string): void {
  if (!win32.isAbsolute(executablePath)) {
    throw new Error("Ember restart task executable path must be absolute");
  }
  if (basename(executablePath).toLowerCase() !== "ember.exe") {
    throw new Error("restart task may execute only the exact Ember executable (ember.exe)");
  }
  if (/[\u0000-\u001f]/.test(executablePath)) {
    throw new Error("Ember executable path contains a control character");
  }
}

function requireSid(userSid: string): void {
  if (!/^S-1-\d+(?:-\d+)+$/.test(userSid)) {
    throw new Error("current Windows user SID is malformed");
  }
}

export function buildWindowsRestartTaskXml(input: {
  executablePath: string;
  userSid: string;
}): string {
  requireWindowsExecutable(input.executablePath);
  requireSid(input.userSid);
  const executable = xmlEscape(input.executablePath);
  const workingDirectory = xmlEscape(dirname(input.executablePath));
  const sid = xmlEscape(input.userSid);
  return [
    '<?xml version="1.0" encoding="UTF-16"?>',
    '<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">',
    "  <RegistrationInfo><Description>Ember cockpit native restart policy</Description></RegistrationInfo>",
    `  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>${sid}</UserId></LogonTrigger></Triggers>`,
    `  <Principals><Principal id="Author"><UserId>${sid}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>`,
    "  <Settings>",
    "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>",
    "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>",
    "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>",
    "    <AllowHardTerminate>true</AllowHardTerminate>",
    "    <StartWhenAvailable>true</StartWhenAvailable>",
    "    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>",
    "    <IdleSettings><StopOnIdleEnd>false</StopOnIdleEnd><RestartOnIdle>false</RestartOnIdle></IdleSettings>",
    "    <AllowStartOnDemand>true</AllowStartOnDemand>",
    "    <Enabled>true</Enabled>",
    "    <Hidden>false</Hidden>",
    "    <RunOnlyIfIdle>false</RunOnlyIfIdle>",
    "    <WakeToRun>false</WakeToRun>",
    "    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>",
    "    <Priority>7</Priority>",
    "    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>",
    "  </Settings>",
    `  <Actions Context="Author"><Exec><Command>${executable}</Command><WorkingDirectory>${workingDirectory}</WorkingDirectory></Exec></Actions>`,
    "</Task>",
    "",
  ].join("\r\n");
}

export function encodeWindowsRestartTaskXml(xml: string): Buffer {
  return Buffer.concat([
    Buffer.from([0xff, 0xfe]),
    Buffer.from(xml, "utf16le"),
  ]);
}

const execFileAsync = promisify(execFile);

async function defaultRun(file: string, args: string[]): Promise<CommandResult> {
  try {
    const result = await execFileAsync(file, args, {
      windowsHide: true,
      encoding: "utf8",
      maxBuffer: 4 * 1024 * 1024,
    });
    return { stdout: result.stdout, stderr: result.stderr, exitCode: 0 };
  } catch (error) {
    const failure = error as Error & { stdout?: string; stderr?: string; code?: number };
    return {
      stdout: failure.stdout ?? "",
      stderr: failure.stderr ?? failure.message,
      exitCode: typeof failure.code === "number" ? failure.code : 1,
    };
  }
}

async function defaultResolveCurrentUserSid(): Promise<string> {
  const result = await defaultRun("whoami.exe", ["/user", "/fo", "csv", "/nh"]);
  if (result.exitCode !== 0) {
    throw new Error("could not resolve current Windows user SID: " + result.stderr.trim());
  }
  const match = result.stdout.match(/S-1-\d+(?:-\d+)+/);
  if (!match) throw new Error("whoami output did not contain a Windows user SID");
  return match[0];
}

async function defaultWriteReceipt(path: string, data: string | Buffer): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  const temp = path + ".tmp-" + process.pid;
  await writeFile(temp, data);
  await rename(temp, path);
}

function verifyInstalledXml(xml: string, executablePath: string, userSid: string): void {
  const required = [
    `<Command>${xmlEscape(executablePath)}</Command>`,
    `<UserId>${xmlEscape(userSid)}</UserId>`,
    "<LogonType>InteractiveToken</LogonType>",
    "<RunLevel>LeastPrivilege</RunLevel>",
    "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>",
    "<RestartOnFailure>",
    "<Interval>PT1M</Interval>",
    "<Count>999</Count>",
  ];
  if (required.some((fragment) => !xml.includes(fragment))) {
    throw new Error("installed task does not preserve the requested executable/restart policy");
  }
  if (/powershell|liveness-watchdog/i.test(xml)) {
    throw new Error("installed task contains forbidden legacy watchdog authority");
  }
}

export async function installWindowsRestartTask(
  options: WindowsRestartTaskOptions,
  deps: WindowsRestartTaskDeps = {},
): Promise<WindowsRestartTaskReceipt> {
  if ((deps.platform ?? process.platform) !== "win32") {
    throw new Error("Ember OS-native restart registration is supported only on Windows");
  }
  requireWindowsExecutable(options.executablePath);

  const read = deps.readFile ?? (async (path) => readFile(path));
  const write = deps.writeFile ?? defaultWriteReceipt;
  const makeTempDir = deps.makeTempDir ?? (() => mkdtemp(join(tmpdir(), "ember-restart-task-")));
  const removeDir = deps.removeDir ?? ((path) => rm(path, { recursive: true, force: true }));
  const run = deps.run ?? defaultRun;
  const resolveSid = deps.resolveCurrentUserSid ?? defaultResolveCurrentUserSid;
  const receiptPath = deps.receiptPath ??
    join(getEmberConfigHomeDir(), "state", "windows-restart-task.json");

  const beforeBytes = await read(options.executablePath);
  const executableSha256 = sha256(beforeBytes);
  const userSid = await resolveSid();
  requireSid(userSid);
  const xml = buildWindowsRestartTaskXml({
    executablePath: options.executablePath,
    userSid,
  });
  const xmlBytes = encodeWindowsRestartTaskXml(xml);
  const tempDir = await makeTempDir();
  const xmlPath = join(tempDir, "task.xml");

  try {
    await write(xmlPath, xmlBytes);
    const created = await run("schtasks.exe", [
      "/Create", "/TN", WINDOWS_RESTART_TASK_NAME, "/XML", xmlPath, "/F",
    ]);
    if (created.exitCode !== 0) {
      throw new Error("Task Scheduler registration failed: " + created.stderr.trim());
    }

    const queried = await run("schtasks.exe", [
      "/Query", "/TN", WINDOWS_RESTART_TASK_NAME, "/XML",
    ]);
    if (queried.exitCode !== 0) {
      throw new Error("Task Scheduler verification failed: " + queried.stderr.trim());
    }
    verifyInstalledXml(queried.stdout, options.executablePath, userSid);

    const afterBytes = await read(options.executablePath);
    if (sha256(afterBytes) !== executableSha256) {
      throw new Error("Ember executable changed during restart-task registration");
    }

    const receipt: WindowsRestartTaskReceipt = {
      schemaVersion: "ember-windows-restart-task/v1",
      result: "INSTALLED_VERIFIED",
      installedAt: (deps.now ?? (() => new Date()))().toISOString(),
      taskName: WINDOWS_RESTART_TASK_NAME,
      executableName: "ember.exe",
      executableSha256,
      userSidSha256: sha256(userSid),
      requestedTaskXmlSha256: sha256(xmlBytes),
      installedTaskXmlSha256: sha256(queried.stdout),
      restartInterval: "PT1M",
      restartCount: 999,
      multipleInstancesPolicy: "IgnoreNew",
      runLevel: "LeastPrivilege",
    };
    await write(receiptPath, JSON.stringify(receipt, null, 2) + "\n");
    return receipt;
  } finally {
    await removeDir(tempDir);
  }
}
