// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
// github-tools.test.ts — tool-surface unit tests for ember's native GitHub
// capability (issue #507). Every test mocks getInstallationToken + githubFetch
// + the receipt writer -- no network, no live-write, per the spec floor's
// "no live-write test until the App is installed."

import { describe, test, expect, beforeEach, afterEach, mock } from "bun:test";
import {
  GhIssueListTool,
  GhIssueViewTool,
  GhIssueCreateTool,
  GhIssueCommentTool,
  GhPrListTool,
  GhPrViewTool,
  GhPrCreateTool,
  GhPrChecksTool,
  GhRepoContentReadTool,
  GITHUB_TOOLS,
  getRepoScope,
  setGithubToolsDeps,
  _resetGithubToolsDepsForTests,
  type GithubFetchResult,
} from "./github-tools.ts";
import type { TokenResult } from "../github-app-auth.ts";
import type { GithubReceiptWriter } from "../services/github-receipts.ts";

const OK_TOKEN: TokenResult = { ok: true, state: "INSTALLATION_TOKEN_OK", token: "ghs_test", expiresAt: "2026-07-08T13:00:00.000Z", cached: false };
const NOT_CONFIGURED: TokenResult = { ok: false, state: "NOT_CONFIGURED", detail: "GitHub App identity is NOT_CONFIGURED -- set env vars." };

let receiptCalls: Array<{ action: string; target: string; ok: boolean }>;
let fakeReceiptWriter: GithubReceiptWriter;

function mockFetch(impl: (method: string, apiPath: string, token: string, body?: unknown) => Promise<GithubFetchResult>) {
  return mock(impl);
}

beforeEach(() => {
  receiptCalls = [];
  fakeReceiptWriter = {
    filePath: "/scratch/receipts.jsonl",
    append: (action, target, ok) => {
      receiptCalls.push({ action, target, ok });
    },
  };
});

afterEach(() => {
  _resetGithubToolsDepsForTests();
  delete process.env["EMBER_GH_OWNER"];
  delete process.env["EMBER_GH_REPO"];
});

describe("getRepoScope", () => {
  test("defaults to wordingone/ember", () => {
    expect(getRepoScope()).toEqual({ owner: "wordingone", repo: "ember" });
  });

  test("is overridable via EMBER_GH_OWNER / EMBER_GH_REPO", () => {
    process.env["EMBER_GH_OWNER"] = "acme";
    process.env["EMBER_GH_REPO"] = "widgets";
    expect(getRepoScope()).toEqual({ owner: "acme", repo: "widgets" });
  });
});

describe("auth-stage failure -- every tool degrades gracefully, no crash", () => {
  test("gh_issue_list returns {ok:false, state} without calling githubFetch", async () => {
    const fetchMock = mockFetch(async () => ({ status: 200, json: [] }));
    setGithubToolsDeps({ getInstallationToken: async () => NOT_CONFIGURED, githubFetch: fetchMock, getReceiptWriter: () => fakeReceiptWriter });

    const result = await GhIssueListTool.call({ state: "open" }, {} as never);
    expect(result.data).toMatchObject({ ok: false, state: "NOT_CONFIGURED" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test("gh_issue_create returns {ok:false, state} and does NOT write a receipt (never reached GitHub)", async () => {
    setGithubToolsDeps({ getInstallationToken: async () => NOT_CONFIGURED, getReceiptWriter: () => fakeReceiptWriter });

    const result = await GhIssueCreateTool.call({ title: "t" }, {} as never);
    expect(result.data).toMatchObject({ ok: false, state: "NOT_CONFIGURED" });
    expect(receiptCalls.length).toBe(0);
  });
});

describe("gh_issue_list", () => {
  test("filters out PR entries and returns genuine issues only", async () => {
    const fetchMock = mockFetch(async (method, apiPath) => {
      expect(method).toBe("GET");
      expect(apiPath).toContain("/repos/wordingone/ember/issues?");
      return {
        status: 200,
        json: [
          { number: 1, title: "a real issue" },
          { number: 2, title: "actually a PR", pull_request: { url: "x" } },
        ],
      };
    });
    setGithubToolsDeps({ getInstallationToken: async () => OK_TOKEN, githubFetch: fetchMock });

    const result = (await GhIssueListTool.call({}, {} as never)).data as { ok: boolean; issues: unknown[] };
    expect(result.ok).toBe(true);
    expect(result.issues).toEqual([{ number: 1, title: "a real issue" }]);
  });

  test("surfaces a non-2xx GitHub response as ok:false without throwing", async () => {
    setGithubToolsDeps({
      getInstallationToken: async () => OK_TOKEN,
      githubFetch: mockFetch(async () => ({ status: 403, json: { message: "rate limited" } })),
    });
    const result = (await GhIssueListTool.call({}, {} as never)).data as { ok: boolean; detail: string };
    expect(result.ok).toBe(false);
    expect(result.detail).toContain("403");
  });
});

describe("gh_issue_view", () => {
  test("reads a single issue by number", async () => {
    const fetchMock = mockFetch(async (_m, apiPath) => {
      expect(apiPath).toBe("/repos/wordingone/ember/issues/507");
      return { status: 200, json: { number: 507, title: "native GitHub identity" } };
    });
    setGithubToolsDeps({ getInstallationToken: async () => OK_TOKEN, githubFetch: fetchMock });

    const result = (await GhIssueViewTool.call({ number: 507 }, {} as never)).data as { ok: boolean; issue: { number: number } };
    expect(result.ok).toBe(true);
    expect(result.issue.number).toBe(507);
  });
});

describe("gh_issue_create", () => {
  test("creates an issue and receipts the success with the issue number as target", async () => {
    const fetchMock = mockFetch(async (method, apiPath, _token, body) => {
      expect(method).toBe("POST");
      expect(apiPath).toBe("/repos/wordingone/ember/issues");
      expect(body).toEqual({ title: "new issue", body: "details" });
      return { status: 201, json: { number: 42, html_url: "https://github.com/wordingone/ember/issues/42" } };
    });
    setGithubToolsDeps({ getInstallationToken: async () => OK_TOKEN, githubFetch: fetchMock, getReceiptWriter: () => fakeReceiptWriter });

    const result = (await GhIssueCreateTool.call({ title: "new issue", body: "details" }, {} as never)).data as { ok: boolean; number: number };
    expect(result.ok).toBe(true);
    expect(result.number).toBe(42);
    expect(receiptCalls).toEqual([{ action: "issue_create", target: "#42", ok: true }]);
  });

  test("receipts a failed creation (reached GitHub, GitHub rejected it) with the title as target", async () => {
    setGithubToolsDeps({
      getInstallationToken: async () => OK_TOKEN,
      githubFetch: mockFetch(async () => ({ status: 422, json: { message: "validation failed" } })),
      getReceiptWriter: () => fakeReceiptWriter,
    });

    const result = (await GhIssueCreateTool.call({ title: "bad issue" }, {} as never)).data as { ok: boolean };
    expect(result.ok).toBe(false);
    expect(receiptCalls).toEqual([{ action: "issue_create", target: "bad issue", ok: false }]);
  });
});

describe("gh_issue_comment", () => {
  test("comments on an issue and receipts against #<number>", async () => {
    const fetchMock = mockFetch(async (method, apiPath, _token, body) => {
      expect(method).toBe("POST");
      expect(apiPath).toBe("/repos/wordingone/ember/issues/507/comments");
      expect(body).toEqual({ body: "progress update" });
      return { status: 201, json: { html_url: "https://github.com/wordingone/ember/issues/507#comment" } };
    });
    setGithubToolsDeps({ getInstallationToken: async () => OK_TOKEN, githubFetch: fetchMock, getReceiptWriter: () => fakeReceiptWriter });

    const result = (await GhIssueCommentTool.call({ number: 507, body: "progress update" }, {} as never)).data as { ok: boolean };
    expect(result.ok).toBe(true);
    expect(receiptCalls).toEqual([{ action: "issue_comment", target: "#507", ok: true }]);
  });
});

describe("gh_pr_list / gh_pr_view", () => {
  test("gh_pr_list lists pull requests", async () => {
    const fetchMock = mockFetch(async (_m, apiPath) => {
      expect(apiPath).toContain("/repos/wordingone/ember/pulls?");
      return { status: 200, json: [{ number: 10 }] };
    });
    setGithubToolsDeps({ getInstallationToken: async () => OK_TOKEN, githubFetch: fetchMock });

    const result = (await GhPrListTool.call({}, {} as never)).data as { ok: boolean; pulls: unknown[] };
    expect(result.ok).toBe(true);
    expect(result.pulls).toEqual([{ number: 10 }]);
  });

  test("gh_pr_view reads a single PR", async () => {
    const fetchMock = mockFetch(async (_m, apiPath) => {
      expect(apiPath).toBe("/repos/wordingone/ember/pulls/10");
      return { status: 200, json: { number: 10, title: "a PR" } };
    });
    setGithubToolsDeps({ getInstallationToken: async () => OK_TOKEN, githubFetch: fetchMock });

    const result = (await GhPrViewTool.call({ number: 10 }, {} as never)).data as { ok: boolean; pull: { number: number } };
    expect(result.ok).toBe(true);
    expect(result.pull.number).toBe(10);
  });
});

describe("gh_pr_create", () => {
  test("opens a PR defaulting base to master, and receipts against #<number>", async () => {
    const fetchMock = mockFetch(async (method, apiPath, _token, body) => {
      expect(method).toBe("POST");
      expect(apiPath).toBe("/repos/wordingone/ember/pulls");
      expect(body).toMatchObject({ title: "feat", head: "feat/507-gh-identity", base: "master" });
      return { status: 201, json: { number: 508, html_url: "https://github.com/wordingone/ember/pull/508" } };
    });
    setGithubToolsDeps({ getInstallationToken: async () => OK_TOKEN, githubFetch: fetchMock, getReceiptWriter: () => fakeReceiptWriter });

    const result = (await GhPrCreateTool.call({ title: "feat", head: "feat/507-gh-identity" }, {} as never)).data as { ok: boolean; number: number };
    expect(result.ok).toBe(true);
    expect(result.number).toBe(508);
    expect(receiptCalls).toEqual([{ action: "pr_create", target: "#508", ok: true }]);
  });
});

describe("gh_pr_checks", () => {
  test("resolves the PR's head SHA, then fetches check-runs for that SHA", async () => {
    const calls: string[] = [];
    const fetchMock = mockFetch(async (_m, apiPath) => {
      calls.push(apiPath);
      if (apiPath === "/repos/wordingone/ember/pulls/508") {
        return { status: 200, json: { head: { sha: "abc123" } } };
      }
      if (apiPath === "/repos/wordingone/ember/commits/abc123/check-runs") {
        return { status: 200, json: { check_runs: [{ name: "test", conclusion: "success" }] } };
      }
      throw new Error(`unexpected path ${apiPath}`);
    });
    setGithubToolsDeps({ getInstallationToken: async () => OK_TOKEN, githubFetch: fetchMock });

    const result = (await GhPrChecksTool.call({ number: 508 }, {} as never)).data as { ok: boolean; sha: string; checks: { check_runs: unknown[] } };
    expect(result.ok).toBe(true);
    expect(result.sha).toBe("abc123");
    expect(result.checks.check_runs.length).toBe(1);
    expect(calls).toEqual(["/repos/wordingone/ember/pulls/508", "/repos/wordingone/ember/commits/abc123/check-runs"]);
  });

  test("reports ok:false when the PR itself can't be resolved, without a second fetch", async () => {
    const fetchMock = mockFetch(async () => ({ status: 404, json: { message: "not found" } }));
    setGithubToolsDeps({ getInstallationToken: async () => OK_TOKEN, githubFetch: fetchMock });

    const result = (await GhPrChecksTool.call({ number: 999 }, {} as never)).data as { ok: boolean };
    expect(result.ok).toBe(false);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("gh_repo_content_read", () => {
  test("decodes base64 file content", async () => {
    const encoded = Buffer.from("hello from docs/domains/governance/authority/GOAL.md", "utf8").toString("base64");
    const fetchMock = mockFetch(async (_m, apiPath) => {
      expect(apiPath).toBe("/repos/wordingone/ember/contents/docs/domains/governance/authority/GOAL.md");
      return { status: 200, json: { type: "file", encoding: "base64", content: encoded } };
    });
    setGithubToolsDeps({ getInstallationToken: async () => OK_TOKEN, githubFetch: fetchMock });

    const result = (await GhRepoContentReadTool.call({ path: "docs/domains/governance/authority/GOAL.md" }, {} as never)).data as { ok: boolean; content: string };
    expect(result.ok).toBe(true);
    expect(result.content).toBe("hello from docs/domains/governance/authority/GOAL.md");
  });

  test("passes ref through as a query param", async () => {
    const fetchMock = mockFetch(async (_m, apiPath) => {
      expect(apiPath).toBe("/repos/wordingone/ember/contents/docs/domains/governance/authority/GOAL.md?ref=feat%2F507-gh-identity");
      return { status: 200, json: { type: "file", encoding: "base64", content: Buffer.from("x").toString("base64") } };
    });
    setGithubToolsDeps({ getInstallationToken: async () => OK_TOKEN, githubFetch: fetchMock });

    await GhRepoContentReadTool.call({ path: "docs/domains/governance/authority/GOAL.md", ref: "feat/507-gh-identity" }, {} as never);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  test("returns the raw entry for a directory listing instead of guessing a decode", async () => {
    setGithubToolsDeps({
      getInstallationToken: async () => OK_TOKEN,
      githubFetch: mockFetch(async () => ({ status: 200, json: [{ name: "docs/domains/governance/authority/GOAL.md", type: "file" }] })),
    });
    const result = (await GhRepoContentReadTool.call({ path: "" }, {} as never)).data as { ok: boolean; raw: unknown };
    expect(result.ok).toBe(true);
    expect(result.raw).toEqual([{ name: "docs/domains/governance/authority/GOAL.md", type: "file" }]);
  });
});

describe("GITHUB_TOOLS registry", () => {
  test("exports exactly the 9 tools the spec floor names, all read-only-flagged correctly", () => {
    expect(GITHUB_TOOLS.map((t) => t.name).sort()).toEqual(
      [
        "gh_issue_list",
        "gh_issue_view",
        "gh_issue_create",
        "gh_issue_comment",
        "gh_pr_list",
        "gh_pr_view",
        "gh_pr_create",
        "gh_pr_checks",
        "gh_repo_content_read",
      ].sort(),
    );

    const writeTools = new Set(["gh_issue_create", "gh_issue_comment", "gh_pr_create"]);
    for (const tool of GITHUB_TOOLS) {
      expect(tool.isReadOnly()).toBe(!writeTools.has(tool.name));
    }
  });
});
