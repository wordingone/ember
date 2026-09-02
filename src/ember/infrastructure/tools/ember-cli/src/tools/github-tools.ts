// tools/github-tools.ts — ember's native GitHub tool surface (issue #507),
// scoped to the App installation's repo (default wordingone/ember,
// overridable via EMBER_GH_OWNER / EMBER_GH_REPO for tests or another
// install). Every WRITE tool appends a JSONL receipt row (spec floor point
// 4) once the call actually reaches GitHub -- a call blocked at the auth
// stage (no creds / JWT-mint / token-exchange failure) never reached GitHub,
// so it is not receipted as an action; the tool's own {ok:false, state,
// detail} return is the record of that.

import { z } from "zod";
import { buildTool } from "../core/tool-interface.ts";
import { GITHUB_API_BASE, getInstallationToken } from "../github-app-auth.ts";
import { getGithubReceiptWriter, type GithubReceiptWriter } from "../services/github-receipts.ts";

// ---------------------------------------------------------------------------
// Repo scope
// ---------------------------------------------------------------------------

export function getRepoScope(): { owner: string; repo: string } {
  return {
    owner: process.env["EMBER_GH_OWNER"] ?? "wordingone",
    repo: process.env["EMBER_GH_REPO"] ?? "ember",
  };
}

// ---------------------------------------------------------------------------
// Fetch (DI)
// ---------------------------------------------------------------------------

export interface GithubFetchResult {
  status: number;
  json: unknown;
}

async function defaultGithubFetch(
  method: string,
  apiPath: string,
  token: string,
  body?: unknown,
): Promise<GithubFetchResult> {
  const res = await fetch(`${GITHUB_API_BASE}${apiPath}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
    },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  const json = await res.json().catch(() => null);
  return { status: res.status, json };
}

export interface GithubToolsDeps {
  githubFetch: (method: string, apiPath: string, token: string, body?: unknown) => Promise<GithubFetchResult>;
  getInstallationToken: typeof getInstallationToken;
  getReceiptWriter: () => GithubReceiptWriter;
}

const DEFAULT_TOOLS_DEPS: GithubToolsDeps = {
  githubFetch: defaultGithubFetch,
  getInstallationToken,
  getReceiptWriter: getGithubReceiptWriter,
};

let toolsDeps: GithubToolsDeps = { ...DEFAULT_TOOLS_DEPS };

export function setGithubToolsDeps(overrides: Partial<GithubToolsDeps>): void {
  toolsDeps = { ...toolsDeps, ...overrides };
}

export function _resetGithubToolsDepsForTests(): void {
  toolsDeps = { ...DEFAULT_TOOLS_DEPS };
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

type AuthedResult<T> =
  | { ok: true; data: T }
  | { ok: false; state: "NOT_CONFIGURED" | "JWT_MINT_FAILED" | "EXCHANGE_FAILED"; detail: string };

async function withToken<T>(fn: (token: string) => Promise<T>): Promise<AuthedResult<T>> {
  const tokenResult = await toolsDeps.getInstallationToken();
  if (!tokenResult.ok) {
    return { ok: false, state: tokenResult.state, detail: tokenResult.detail };
  }
  const data = await fn(tokenResult.token);
  return { ok: true, data };
}

function jsonResultMapper(content: unknown, toolUseId: string) {
  return {
    type: "tool_result" as const,
    tool_use_id: toolUseId,
    content: JSON.stringify(content),
  };
}

// ---------------------------------------------------------------------------
// gh_issue_list — read-only
// ---------------------------------------------------------------------------

const IssueListInputSchema = z
  .object({
    state: z.enum(["open", "closed", "all"]).optional(),
    perPage: z.number().int().positive().max(100).optional(),
  })
  .strict();
export type IssueListInput = z.infer<typeof IssueListInputSchema>;

export const GhIssueListTool = buildTool<IssueListInput, unknown>({
  name: "gh_issue_list",
  inputSchema: IssueListInputSchema,
  isReadOnly: () => true,
  isConcurrencySafe: () => true,
  call: async (rawArgs: unknown) => {
    const args = rawArgs as IssueListInput;
    const { owner, repo } = getRepoScope();
    const params = new URLSearchParams();
    params.set("state", args.state ?? "open");
    params.set("per_page", String(args.perPage ?? 30));

    const result = await withToken((token) =>
      toolsDeps.githubFetch("GET", `/repos/${owner}/${repo}/issues?${params.toString()}`, token),
    );
    if (!result.ok) return { data: { ok: false, state: result.state, detail: result.detail } };

    const { status, json } = result.data;
    if (status < 200 || status >= 300) {
      return { data: { ok: false, detail: `GitHub API ${status}`, response: json } };
    }

    const raw = Array.isArray(json) ? json : [];
    // /issues also returns PRs (they share the issue numbering space) --
    // filter those out so this tool returns genuine issues only.
    const issues = raw.filter((i: unknown) => (i as { pull_request?: unknown } | null)?.pull_request === undefined);
    return { data: { ok: true, issues } };
  },
  description: () =>
    `Lists issues in ${getRepoScope().owner}/${getRepoScope().repo} (excludes pull requests). ` +
    `Args: state ("open"|"closed"|"all", default open), perPage (max 100).`,
  mapToolResultToToolResultBlockParam: jsonResultMapper,
});

// ---------------------------------------------------------------------------
// gh_issue_view — read-only
// ---------------------------------------------------------------------------

const IssueViewInputSchema = z.object({ number: z.number().int().positive() }).strict();
export type IssueViewInput = z.infer<typeof IssueViewInputSchema>;

export const GhIssueViewTool = buildTool<IssueViewInput, unknown>({
  name: "gh_issue_view",
  inputSchema: IssueViewInputSchema,
  isReadOnly: () => true,
  isConcurrencySafe: () => true,
  call: async (rawArgs: unknown) => {
    const args = rawArgs as IssueViewInput;
    const { owner, repo } = getRepoScope();

    const result = await withToken((token) =>
      toolsDeps.githubFetch("GET", `/repos/${owner}/${repo}/issues/${args.number}`, token),
    );
    if (!result.ok) return { data: { ok: false, state: result.state, detail: result.detail } };

    const { status, json } = result.data;
    if (status < 200 || status >= 300) {
      return { data: { ok: false, detail: `GitHub API ${status}`, response: json } };
    }
    return { data: { ok: true, issue: json } };
  },
  description: () => `Reads a single issue by number from ${getRepoScope().owner}/${getRepoScope().repo}.`,
  mapToolResultToToolResultBlockParam: jsonResultMapper,
});

// ---------------------------------------------------------------------------
// gh_issue_create — write, receipted
// ---------------------------------------------------------------------------

const IssueCreateInputSchema = z.object({ title: z.string().min(1), body: z.string().optional() }).strict();
export type IssueCreateInput = z.infer<typeof IssueCreateInputSchema>;

export const GhIssueCreateTool = buildTool<IssueCreateInput, unknown>({
  name: "gh_issue_create",
  inputSchema: IssueCreateInputSchema,
  isReadOnly: () => false,
  isConcurrencySafe: () => false,
  call: async (rawArgs: unknown) => {
    const args = rawArgs as IssueCreateInput;
    const { owner, repo } = getRepoScope();

    const result = await withToken((token) =>
      toolsDeps.githubFetch("POST", `/repos/${owner}/${repo}/issues`, token, {
        title: args.title,
        ...(args.body !== undefined ? { body: args.body } : {}),
      }),
    );
    if (!result.ok) return { data: { ok: false, state: result.state, detail: result.detail } };

    const { status, json } = result.data;
    const ok = status >= 200 && status < 300;
    const number = ok && json && typeof json === "object" && "number" in json ? (json as { number: number }).number : undefined;
    toolsDeps.getReceiptWriter().append("issue_create", number !== undefined ? `#${number}` : args.title, ok);

    if (!ok) return { data: { ok: false, detail: `GitHub API ${status}`, response: json } };
    return { data: { ok: true, number, url: (json as { html_url?: string }).html_url } };
  },
  description: () =>
    `Creates an issue in ${getRepoScope().owner}/${getRepoScope().repo}. Args: title, body (optional). Receipted.`,
  mapToolResultToToolResultBlockParam: jsonResultMapper,
});

// ---------------------------------------------------------------------------
// gh_issue_comment — write, receipted
// ---------------------------------------------------------------------------

const IssueCommentInputSchema = z.object({ number: z.number().int().positive(), body: z.string().min(1) }).strict();
export type IssueCommentInput = z.infer<typeof IssueCommentInputSchema>;

export const GhIssueCommentTool = buildTool<IssueCommentInput, unknown>({
  name: "gh_issue_comment",
  inputSchema: IssueCommentInputSchema,
  isReadOnly: () => false,
  isConcurrencySafe: () => false,
  call: async (rawArgs: unknown) => {
    const args = rawArgs as IssueCommentInput;
    const { owner, repo } = getRepoScope();

    const result = await withToken((token) =>
      toolsDeps.githubFetch("POST", `/repos/${owner}/${repo}/issues/${args.number}/comments`, token, {
        body: args.body,
      }),
    );
    if (!result.ok) return { data: { ok: false, state: result.state, detail: result.detail } };

    const { status, json } = result.data;
    const ok = status >= 200 && status < 300;
    toolsDeps.getReceiptWriter().append("issue_comment", `#${args.number}`, ok);

    if (!ok) return { data: { ok: false, detail: `GitHub API ${status}`, response: json } };
    return { data: { ok: true, url: (json as { html_url?: string }).html_url } };
  },
  description: () => `Comments on an issue in ${getRepoScope().owner}/${getRepoScope().repo}. Receipted.`,
  mapToolResultToToolResultBlockParam: jsonResultMapper,
});

// ---------------------------------------------------------------------------
// gh_pr_list — read-only
// ---------------------------------------------------------------------------

const PrListInputSchema = z
  .object({
    state: z.enum(["open", "closed", "all"]).optional(),
    perPage: z.number().int().positive().max(100).optional(),
  })
  .strict();
export type PrListInput = z.infer<typeof PrListInputSchema>;

export const GhPrListTool = buildTool<PrListInput, unknown>({
  name: "gh_pr_list",
  inputSchema: PrListInputSchema,
  isReadOnly: () => true,
  isConcurrencySafe: () => true,
  call: async (rawArgs: unknown) => {
    const args = rawArgs as PrListInput;
    const { owner, repo } = getRepoScope();
    const params = new URLSearchParams();
    params.set("state", args.state ?? "open");
    params.set("per_page", String(args.perPage ?? 30));

    const result = await withToken((token) =>
      toolsDeps.githubFetch("GET", `/repos/${owner}/${repo}/pulls?${params.toString()}`, token),
    );
    if (!result.ok) return { data: { ok: false, state: result.state, detail: result.detail } };

    const { status, json } = result.data;
    if (status < 200 || status >= 300) {
      return { data: { ok: false, detail: `GitHub API ${status}`, response: json } };
    }
    return { data: { ok: true, pulls: Array.isArray(json) ? json : [] } };
  },
  description: () =>
    `Lists pull requests in ${getRepoScope().owner}/${getRepoScope().repo}. Args: state, perPage.`,
  mapToolResultToToolResultBlockParam: jsonResultMapper,
});

// ---------------------------------------------------------------------------
// gh_pr_view — read-only
// ---------------------------------------------------------------------------

const PrViewInputSchema = z.object({ number: z.number().int().positive() }).strict();
export type PrViewInput = z.infer<typeof PrViewInputSchema>;

export const GhPrViewTool = buildTool<PrViewInput, unknown>({
  name: "gh_pr_view",
  inputSchema: PrViewInputSchema,
  isReadOnly: () => true,
  isConcurrencySafe: () => true,
  call: async (rawArgs: unknown) => {
    const args = rawArgs as PrViewInput;
    const { owner, repo } = getRepoScope();

    const result = await withToken((token) =>
      toolsDeps.githubFetch("GET", `/repos/${owner}/${repo}/pulls/${args.number}`, token),
    );
    if (!result.ok) return { data: { ok: false, state: result.state, detail: result.detail } };

    const { status, json } = result.data;
    if (status < 200 || status >= 300) {
      return { data: { ok: false, detail: `GitHub API ${status}`, response: json } };
    }
    return { data: { ok: true, pull: json } };
  },
  description: () => `Reads a single pull request by number from ${getRepoScope().owner}/${getRepoScope().repo}.`,
  mapToolResultToToolResultBlockParam: jsonResultMapper,
});

// ---------------------------------------------------------------------------
// gh_pr_create — write, receipted
// ---------------------------------------------------------------------------

const PrCreateInputSchema = z
  .object({
    title: z.string().min(1),
    head: z.string().min(1),
    base: z.string().optional(),
    body: z.string().optional(),
    draft: z.boolean().optional(),
  })
  .strict();
export type PrCreateInput = z.infer<typeof PrCreateInputSchema>;

export const GhPrCreateTool = buildTool<PrCreateInput, unknown>({
  name: "gh_pr_create",
  inputSchema: PrCreateInputSchema,
  isReadOnly: () => false,
  isConcurrencySafe: () => false,
  call: async (rawArgs: unknown) => {
    const args = rawArgs as PrCreateInput;
    const { owner, repo } = getRepoScope();

    const result = await withToken((token) =>
      toolsDeps.githubFetch("POST", `/repos/${owner}/${repo}/pulls`, token, {
        title: args.title,
        head: args.head,
        base: args.base ?? "master",
        ...(args.body !== undefined ? { body: args.body } : {}),
        ...(args.draft !== undefined ? { draft: args.draft } : {}),
      }),
    );
    if (!result.ok) return { data: { ok: false, state: result.state, detail: result.detail } };

    const { status, json } = result.data;
    const ok = status >= 200 && status < 300;
    const number = ok && json && typeof json === "object" && "number" in json ? (json as { number: number }).number : undefined;
    toolsDeps.getReceiptWriter().append("pr_create", number !== undefined ? `#${number}` : args.head, ok);

    if (!ok) return { data: { ok: false, detail: `GitHub API ${status}`, response: json } };
    return { data: { ok: true, number, url: (json as { html_url?: string }).html_url } };
  },
  description: () =>
    `Opens a pull request in ${getRepoScope().owner}/${getRepoScope().repo}. Args: title, head, base (default master), body, draft. Receipted.`,
  mapToolResultToToolResultBlockParam: jsonResultMapper,
});

// ---------------------------------------------------------------------------
// gh_pr_checks — read-only
// ---------------------------------------------------------------------------

const PrChecksInputSchema = z.object({ number: z.number().int().positive() }).strict();
export type PrChecksInput = z.infer<typeof PrChecksInputSchema>;

export const GhPrChecksTool = buildTool<PrChecksInput, unknown>({
  name: "gh_pr_checks",
  inputSchema: PrChecksInputSchema,
  isReadOnly: () => true,
  isConcurrencySafe: () => true,
  call: async (rawArgs: unknown) => {
    const args = rawArgs as PrChecksInput;
    const { owner, repo } = getRepoScope();

    const result = await withToken(async (token) => {
      const prRes = await toolsDeps.githubFetch("GET", `/repos/${owner}/${repo}/pulls/${args.number}`, token);
      if (prRes.status < 200 || prRes.status >= 300) {
        return { prStatus: prRes.status, sha: null as string | null, checks: null as unknown };
      }
      const sha = (prRes.json as { head?: { sha?: string } } | null)?.head?.sha ?? null;
      if (!sha) return { prStatus: prRes.status, sha: null, checks: null };
      const checksRes = await toolsDeps.githubFetch("GET", `/repos/${owner}/${repo}/commits/${sha}/check-runs`, token);
      return { prStatus: prRes.status, sha, checks: checksRes.json };
    });
    if (!result.ok) return { data: { ok: false, state: result.state, detail: result.detail } };

    if (result.data.sha === null) {
      return {
        data: { ok: false, detail: `could not resolve head SHA for PR #${args.number} (status ${result.data.prStatus})` },
      };
    }
    return { data: { ok: true, sha: result.data.sha, checks: result.data.checks } };
  },
  description: () =>
    `Reads CI check-run status for a pull request's head commit in ${getRepoScope().owner}/${getRepoScope().repo}.`,
  mapToolResultToToolResultBlockParam: jsonResultMapper,
});

// ---------------------------------------------------------------------------
// gh_repo_content_read — read-only
// ---------------------------------------------------------------------------

const RepoContentReadInputSchema = z.object({ path: z.string().min(1), ref: z.string().optional() }).strict();
export type RepoContentReadInput = z.infer<typeof RepoContentReadInputSchema>;

export const GhRepoContentReadTool = buildTool<RepoContentReadInput, unknown>({
  name: "gh_repo_content_read",
  inputSchema: RepoContentReadInputSchema,
  isReadOnly: () => true,
  isConcurrencySafe: () => true,
  call: async (rawArgs: unknown) => {
    const args = rawArgs as RepoContentReadInput;
    const { owner, repo } = getRepoScope();
    const query = args.ref ? `?ref=${encodeURIComponent(args.ref)}` : "";

    const result = await withToken((token) =>
      toolsDeps.githubFetch("GET", `/repos/${owner}/${repo}/contents/${args.path}${query}`, token),
    );
    if (!result.ok) return { data: { ok: false, state: result.state, detail: result.detail } };

    const { status, json } = result.data;
    if (status < 200 || status >= 300) {
      return { data: { ok: false, detail: `GitHub API ${status}`, response: json } };
    }

    const entry = json as { type?: string; content?: string; encoding?: string } | null;
    if (!entry || entry.type !== "file" || entry.encoding !== "base64" || entry.content === undefined) {
      // Directory listing or an encoding this tool doesn't decode -- return
      // the raw entry rather than guessing at a decode.
      return { data: { ok: true, raw: json } };
    }
    const content = Buffer.from(entry.content, "base64").toString("utf8");
    return { data: { ok: true, path: args.path, content } };
  },
  description: () =>
    `Reads a file's content from ${getRepoScope().owner}/${getRepoScope().repo} via the GitHub contents API. Args: path, ref (optional).`,
  mapToolResultToToolResultBlockParam: jsonResultMapper,
});

// ---------------------------------------------------------------------------
// Registry
// ---------------------------------------------------------------------------

export const GITHUB_TOOLS = [
  GhIssueListTool,
  GhIssueViewTool,
  GhIssueCreateTool,
  GhIssueCommentTool,
  GhPrListTool,
  GhPrViewTool,
  GhPrCreateTool,
  GhPrChecksTool,
  GhRepoContentReadTool,
];
