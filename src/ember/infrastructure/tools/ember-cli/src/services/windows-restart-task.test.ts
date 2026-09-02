// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

import { describe, expect, it } from "bun:test";
import { createHash } from "node:crypto";
import {
  buildWindowsRestartTaskXml,
  encodeWindowsRestartTaskXml,
  installWindowsRestartTask,
  type WindowsRestartTaskDeps,
} from "./windows-restart-task.ts";

const SID = "S-1-5-21-111-222-333-1001";
const EXE = "C:\\Program Files\\Ember\\ember.exe";

describe("Windows restart task contract", () => {
  it("binds the exact Ember executable to a least-privilege logon task with restart-on-failure", () => {
    const xml = buildWindowsRestartTaskXml({
      executablePath: EXE,
      userSid: SID,
    });

    expect(xml).toStartWith('<?xml version="1.0" encoding="UTF-16"?>');
    const encoded = encodeWindowsRestartTaskXml(xml);
    expect([...encoded.subarray(0, 2)]).toEqual([0xff, 0xfe]);
    expect(encoded.subarray(2).toString("utf16le")).toBe(xml);
    expect(xml).toContain("<UserId>" + SID + "</UserId>");
    expect(xml).toContain("<LogonType>InteractiveToken</LogonType>");
    expect(xml).toContain("<RunLevel>LeastPrivilege</RunLevel>");
    expect(xml).toContain("<Command>" + EXE + "</Command>");
    expect(xml).toContain("<RestartOnFailure>");
    expect(xml).toContain("<Interval>PT1M</Interval>");
    expect(xml).toContain("<Count>999</Count>");
    expect(xml).toContain("<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>");
    expect(xml).not.toContain("powershell");
    expect(xml).not.toContain("liveness-watchdog");
  });

  it("escapes XML metacharacters and rejects non-absolute or non-Ember executables", () => {
    expect(buildWindowsRestartTaskXml({
      executablePath: "C:\\Program Files\\Ember & Lab\\ember.exe",
      userSid: SID,
    })).toContain("Ember &amp; Lab");

    expect(() => buildWindowsRestartTaskXml({
      executablePath: "ember.exe",
      userSid: SID,
    })).toThrow("absolute");
    expect(() => buildWindowsRestartTaskXml({
      executablePath: "C:\\Windows\\System32\\cmd.exe",
      userSid: SID,
    })).toThrow("Ember executable");
  });

  it("installs trusted bytes, verifies queried XML, and emits a path-free receipt", async () => {
    const bytes = Buffer.from("ember-binary");
    const sha = createHash("sha256").update(bytes).digest("hex");
    const calls: Array<{ file: string; args: string[] }> = [];
    const writes = new Map<string, string>();
    let requestedXml = "";

    const deps: WindowsRestartTaskDeps = {
      platform: "win32",
      now: () => new Date("2026-07-30T18:00:00.000Z"),
      readFile: async (path) => {
        if (path === EXE) return bytes;
        throw new Error("unexpected read " + path);
      },
      writeFile: async (path, data) => {
        const text = Buffer.isBuffer(data)
          ? data.subarray(2).toString("utf16le")
          : String(data);
        writes.set(path, text);
        if (path.endsWith(".xml")) requestedXml = text;
      },
      makeTempDir: async () => "C:\\Temp\\ember-task-1",
      removeDir: async () => {},
      resolveCurrentUserSid: async () => SID,
      run: async (file, args) => {
        calls.push({ file, args });
        if (args[0] === "/Create") return { stdout: "SUCCESS", stderr: "", exitCode: 0 };
        if (args[0] === "/Query") return { stdout: requestedXml, stderr: "", exitCode: 0 };
        throw new Error("unexpected call");
      },
      receiptPath: "C:\\Ember\\state\\windows-restart-task.json",
    };

    const receipt = await installWindowsRestartTask({ executablePath: EXE }, deps);

    expect(calls).toHaveLength(2);
    expect(calls[0]).toEqual({
      file: "schtasks.exe",
      args: ["/Create", "/TN", "\\Ember\\Cockpit", "/XML", "C:\\Temp\\ember-task-1\\task.xml", "/F"],
    });
    expect(calls[1]?.args).toEqual(["/Query", "/TN", "\\Ember\\Cockpit", "/XML"]);
    expect(receipt.result).toBe("INSTALLED_VERIFIED");
    expect(receipt.executableSha256).toBe(sha);
    expect(JSON.stringify(receipt)).not.toContain("C:\\\\Program Files");
    expect(JSON.stringify(receipt)).not.toContain("C:\\\\Temp");
    expect(writes.get(deps.receiptPath!)).toBe(JSON.stringify(receipt, null, 2) + "\n");
  });

  it("fails closed when Task Scheduler does not return the requested executable/restart policy", async () => {
    const deps: WindowsRestartTaskDeps = {
      platform: "win32",
      readFile: async () => Buffer.from("ember-binary"),
      writeFile: async () => {},
      makeTempDir: async () => "C:\\Temp\\ember-task-2",
      removeDir: async () => {},
      resolveCurrentUserSid: async () => SID,
      run: async (_file, args) => args[0] === "/Create"
        ? { stdout: "SUCCESS", stderr: "", exitCode: 0 }
        : { stdout: "<Task><Actions><Exec><Command>C:\\bad.exe</Command></Exec></Actions></Task>", stderr: "", exitCode: 0 },
      receiptPath: "C:\\Ember\\state\\windows-restart-task.json",
    };

    await expect(installWindowsRestartTask({ executablePath: EXE }, deps))
      .rejects.toThrow("installed task does not preserve");
  });
});
