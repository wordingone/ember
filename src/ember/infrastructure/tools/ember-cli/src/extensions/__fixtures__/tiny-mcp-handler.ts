// goal_id: EMBER-02
// workstream_id: EMBER-02A
// next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember

// A tiny MCP server's request handler, shared by the stdio fixture and the HTTP test server.
// Tools: echo {text}, add {a,b}, boom {} (isError). Prompt: greet {name}.

type Json = Record<string, unknown>;

export const TOOLS = [
  {
    name: "echo",
    description: "Echo the text back",
    inputSchema: { type: "object", properties: { text: { type: "string" } }, required: ["text"] },
  },
  {
    name: "add",
    description: "Add two numbers",
    annotations: { readOnlyHint: true },
    inputSchema: { type: "object", properties: { a: { type: "number" }, b: { type: "number" } }, required: ["a", "b"] },
  },
  { name: "boom", description: "Always fails", inputSchema: { type: "object", properties: {} } },
];

/** Returns the JSON-RPC response for a request, or null for a notification. */
export function handleRpc(msg: Json): Json | null {
  const id = msg["id"];
  const method = msg["method"] as string;
  const params = (msg["params"] ?? {}) as Json;
  if (id === undefined) return null;
  const ok = (result: Json): Json => ({ jsonrpc: "2.0", id, result });
  switch (method) {
    case "initialize":
      return ok({
        protocolVersion: "2025-03-26",
        capabilities: { tools: {}, prompts: {} },
        serverInfo: { name: "tiny", version: "1.0.0" },
      });
    case "tools/list":
      return ok({ tools: TOOLS });
    case "prompts/list":
      return ok({ prompts: [{ name: "greet", description: "Greet someone", arguments: [{ name: "name", required: true }] }] });
    case "prompts/get": {
      const args = (params["arguments"] ?? {}) as Json;
      return ok({ messages: [{ role: "user", content: { type: "text", text: `Say hello to ${String(args["name"] ?? "nobody")}` } }] });
    }
    case "tools/call": {
      const name = params["name"];
      const args = (params["arguments"] ?? {}) as Json;
      if (name === "echo") return ok({ content: [{ type: "text", text: `echo: ${String(args["text"])}` }] });
      if (name === "add") return ok({ content: [{ type: "text", text: String(Number(args["a"]) + Number(args["b"])) }] });
      if (name === "boom") return ok({ isError: true, content: [{ type: "text", text: "boom happened" }] });
      return { jsonrpc: "2.0", id, error: { code: -32602, message: `unknown tool ${String(name)}` } };
    }
    default:
      return { jsonrpc: "2.0", id, error: { code: -32601, message: `no method ${method}` } };
  }
}
