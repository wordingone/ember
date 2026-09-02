// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// github-doctor.ts — `ember gh doctor`: walks the GitHub App identity's live
// auth ladder end-to-end (credentials -> JWT -> installation token -> rate
// limit) and reports exactly how far it got. Diagnostic, never a gate --
// always exits 0 (ember issue #507 spec floor point 5). Bypasses the
// installation-token cache deliberately: a diagnostic command should always
// exercise the real path, not report a stale cached success.

import {
  resolveCredentials,
  mintJwt,
  exchangeInstallationToken,
  checkRateLimit,
} from "./github-app-auth.ts";

export interface GithubDoctorReport {
  configured: boolean;
  jwtMinted: boolean;
  installationTokenOk: boolean;
  rateLimitRemaining: number | null;
  detail: string;
}

/**
 * Runs the full ladder fresh (no cache) and reports the furthest stage
 * reached: NOT_CONFIGURED ("no creds") -> JWT_OK -> INSTALLATION_TOKEN_OK ->
 * rate-limit remaining.
 */
export async function runGithubDoctorCheck(): Promise<GithubDoctorReport> {
  const resolved = resolveCredentials();
  if (!resolved.ok) {
    return { configured: false, jwtMinted: false, installationTokenOk: false, rateLimitRemaining: null, detail: resolved.detail };
  }

  const jwtResult = mintJwt(resolved.creds, Date.now());
  if (!jwtResult.ok) {
    return { configured: true, jwtMinted: false, installationTokenOk: false, rateLimitRemaining: null, detail: jwtResult.detail };
  }

  const exchangeResult = await exchangeInstallationToken(resolved.creds.installationId, jwtResult.jwt);
  if (!exchangeResult.ok) {
    return { configured: true, jwtMinted: true, installationTokenOk: false, rateLimitRemaining: null, detail: exchangeResult.detail };
  }

  const rateLimitRemaining = await checkRateLimit(exchangeResult.token);
  return {
    configured: true,
    jwtMinted: true,
    installationTokenOk: true,
    rateLimitRemaining,
    detail: "GitHub App identity fully operational.",
  };
}

export function formatGithubDoctorReport(report: GithubDoctorReport): string {
  const lines: string[] = ["ember gh doctor -- GitHub App identity"];

  if (!report.configured) {
    lines.push("  auth state: NO_CREDS");
    lines.push(`  ${report.detail}`);
    return lines.join("\n") + "\n";
  }

  lines.push("  credentials: configured");
  lines.push(`  JWT mint: ${report.jwtMinted ? "JWT_OK" : "FAILED"}`);
  lines.push(`  installation token: ${report.installationTokenOk ? "INSTALLATION_TOKEN_OK" : "FAILED"}`);
  lines.push(`  rate limit remaining: ${report.rateLimitRemaining === null ? "unknown" : report.rateLimitRemaining}`);
  if (!report.jwtMinted || !report.installationTokenOk) {
    lines.push(`  detail: ${report.detail}`);
  }
  return lines.join("\n") + "\n";
}

// ---------------------------------------------------------------------------
// CLI command wrapper (DI so tests never touch the real process)
// ---------------------------------------------------------------------------

export interface GhDoctorCommandDeps {
  check: () => Promise<GithubDoctorReport>;
  write: (s: string) => void;
  exit: (code: number) => void;
}

const DEFAULT_COMMAND_DEPS: GhDoctorCommandDeps = {
  check: runGithubDoctorCheck,
  write: (s: string) => {
    process.stdout.write(s);
  },
  exit: (code: number) => {
    process.exit(code);
  },
};

/** `ember gh doctor` -- always exits 0 (diagnostic, never a gate: spec floor point 5). */
export async function runGhDoctorCommand(deps: GhDoctorCommandDeps = DEFAULT_COMMAND_DEPS): Promise<void> {
  try {
    const report = await deps.check();
    deps.write(formatGithubDoctorReport(report));
  } catch (err) {
    deps.write(
      `ember gh doctor -- GitHub App identity\n  auth state: ERROR\n  ${err instanceof Error ? err.message : String(err)}\n`,
    );
  }
  deps.exit(0);
}
