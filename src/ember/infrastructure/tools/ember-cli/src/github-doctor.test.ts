// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// github-doctor.test.ts — tests for `ember gh doctor` (ember issue #507).
// Every scenario drives the real ladder (resolveCredentials -> mintJwt ->
// exchangeInstallationToken -> checkRateLimit) through github-app-auth's DI
// seam, so this exercises the actual integration path, not a stub of it.

import { describe, test, expect, afterEach, mock } from "bun:test";
import crypto from "node:crypto";
import { setGithubAppAuthDeps, _resetGithubAppAuthDepsForTests, _clearTokenCacheForTests, type GithubAppCredentialsRaw } from "./github-app-auth.ts";
import { runGithubDoctorCheck, formatGithubDoctorReport, runGhDoctorCommand } from "./github-doctor.ts";

const testKeyPair = crypto.generateKeyPairSync("rsa", {
  modulusLength: 2048,
  publicKeyEncoding: { type: "spki", format: "pem" },
  privateKeyEncoding: { type: "pkcs8", format: "pem" },
});

afterEach(() => {
  _resetGithubAppAuthDepsForTests();
  _clearTokenCacheForTests();
});

describe("runGithubDoctorCheck", () => {
  test("reports NO_CREDS (configured:false) when env vars are absent", async () => {
    setGithubAppAuthDeps({ readEnv: (): GithubAppCredentialsRaw => ({ appId: undefined, installationId: undefined, privateKeyPath: undefined }) });

    const report = await runGithubDoctorCheck();
    expect(report.configured).toBe(false);
    expect(report.jwtMinted).toBe(false);
    expect(report.installationTokenOk).toBe(false);
    expect(report.rateLimitRemaining).toBeNull();
    expect(formatGithubDoctorReport(report)).toContain("NO_CREDS");
  });

  test("reports jwtMinted:false when signing fails despite creds being present", async () => {
    setGithubAppAuthDeps({
      readEnv: (): GithubAppCredentialsRaw => ({ appId: "1", installationId: "2", privateKeyPath: "/key.pem" }),
      readPrivateKeyFile: () => testKeyPair.privateKey,
      signJwt: () => {
        throw new Error("corrupt key");
      },
    });

    const report = await runGithubDoctorCheck();
    expect(report.configured).toBe(true);
    expect(report.jwtMinted).toBe(false);
    expect(report.installationTokenOk).toBe(false);
    expect(report.detail).toContain("corrupt key");
  });

  test("reports jwtMinted:true, installationTokenOk:false when the exchange fails", async () => {
    setGithubAppAuthDeps({
      readEnv: (): GithubAppCredentialsRaw => ({ appId: "1", installationId: "2", privateKeyPath: "/key.pem" }),
      readPrivateKeyFile: () => testKeyPair.privateKey,
      fetchInstallationToken: async () => {
        throw new Error("installation not found");
      },
    });

    const report = await runGithubDoctorCheck();
    expect(report.jwtMinted).toBe(true);
    expect(report.installationTokenOk).toBe(false);
    expect(report.detail).toContain("installation not found");

    const text = formatGithubDoctorReport(report);
    expect(text).toContain("JWT_OK");
    expect(text).toContain("FAILED");
  });

  test("reports full success with rate-limit remaining once everything checks out", async () => {
    setGithubAppAuthDeps({
      readEnv: (): GithubAppCredentialsRaw => ({ appId: "1", installationId: "2", privateKeyPath: "/key.pem" }),
      readPrivateKeyFile: () => testKeyPair.privateKey,
      fetchInstallationToken: async () => ({ token: "ghs_x", expiresAt: "2026-07-08T13:00:00.000Z" }),
      fetchRateLimit: async () => 4987,
    });

    const report = await runGithubDoctorCheck();
    expect(report.configured).toBe(true);
    expect(report.jwtMinted).toBe(true);
    expect(report.installationTokenOk).toBe(true);
    expect(report.rateLimitRemaining).toBe(4987);

    const text = formatGithubDoctorReport(report);
    expect(text).toContain("INSTALLATION_TOKEN_OK");
    expect(text).toContain("4987");
  });
});

describe("runGhDoctorCommand", () => {
  test("always exits 0, even when check() throws", async () => {
    const writeMock = mock((_s: string) => {});
    const exitMock = mock((_code: number) => {});

    await runGhDoctorCommand({
      check: async () => {
        throw new Error("unexpected");
      },
      write: writeMock,
      exit: exitMock,
    });

    expect(exitMock).toHaveBeenCalledWith(0);
    expect(writeMock).toHaveBeenCalledTimes(1);
    expect(writeMock.mock.calls[0]?.[0]).toContain("ERROR");
  });

  test("exits 0 on the happy path too, having written the formatted report", async () => {
    const writeMock = mock((_s: string) => {});
    const exitMock = mock((_code: number) => {});

    await runGhDoctorCommand({
      check: async () => ({ configured: false, jwtMinted: false, installationTokenOk: false, rateLimitRemaining: null, detail: "no creds set" }),
      write: writeMock,
      exit: exitMock,
    });

    expect(exitMock).toHaveBeenCalledWith(0);
    expect(writeMock.mock.calls[0]?.[0]).toContain("NO_CREDS");
  });
});
