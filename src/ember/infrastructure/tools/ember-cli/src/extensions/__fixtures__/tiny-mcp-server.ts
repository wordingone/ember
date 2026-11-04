// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// A tiny stdio MCP server for tests and the visible-window acceptance run: newline-delimited
// JSON-RPC on stdin/stdout. Run: bun run tiny-mcp-server.ts
// Set TINY_MCP_HANG=1 for a server that is alive but never answers (startup-timeout test).

import { handleRpc } from "./tiny-mcp-handler.ts";

if (process.env["TINY_MCP_HANG"] === "1") {
  setInterval(() => {}, 1000);
} else {
  let buf = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk: string) => {
    buf += chunk;
    let nl: number;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (!line) continue;
      const reply = handleRpc(JSON.parse(line) as Record<string, unknown>);
      if (reply) process.stdout.write(JSON.stringify(reply) + "\n");
    }
  });
  process.stdin.on("end", () => process.exit(0));
}
