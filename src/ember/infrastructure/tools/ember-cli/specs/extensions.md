# ember-cli extensions: MCP servers, plugins, skills, hooks, scheduled prompts, /loop

Issues #2375 (MCP client, plugins, skill slash commands) and #2376 (hooks, scheduled jobs that fire, `/loop`).
Code: `src/extensions/`. `$EMBER_HOME` defaults to `~/.ember`; `<project>` is the directory ember-cli runs in.

## MCP servers

Config files (both optional; a server defined in both is taken from the project file):

- `$EMBER_HOME/mcp.json` (user scope)
- `<project>/.ember/mcp.json` (project scope)

```json
{
  "mcpServers": {
    "files":  { "command": "npx", "args": ["-y", "some-mcp-server"], "env": { "TOKEN": "${MY_TOKEN}" } },
    "remote": { "type": "http", "url": "https://example.com/mcp", "headers": { "Authorization": "Bearer ${KEY}" } }
  }
}
```

- stdio: `command` (+ `args`, `env`) is spawned in the project directory; newline-delimited JSON-RPC.
- HTTP: `type: "http"` and `url`; streamable HTTP (JSON or SSE replies, `Mcp-Session-Id` honoured). Servers that only
  speak the legacy SSE transport are not supported.
- `${VAR}` and `${VAR:-default}` expand in `command`, `args` and `env` values. `"disabled": true` skips a server.
- Servers start in the background at session start, in parallel. A server that fails, exits or does not answer within
  `EMBER_MCP_CONNECT_TIMEOUT_MS` (default 30000) shows a `[extensions]` notice row and is marked failed; the session is
  never blocked. The first prompt waits at most 5 s for servers; a slower one adds its tools on a later turn.
- Tools reach the model as `mcp__<server>__<tool>` (server names keep letters, digits, `_`; spaces become `_`).
  A tool whose server declares `readOnlyHint` runs without an approval prompt; others follow the permission mode.
  A call is bounded by `EMBER_MCP_TOOL_TIMEOUT_MS` (default 120000).
- MCP prompts become `/mcp__<server>__<prompt> [args]` commands. If any server has resources, `mcp__list_resources`
  and `mcp__read_resource` are offered.
- `/mcp` lists servers and status; `/mcp <server>` lists its tools and prompts.
- Project-scope servers run commands from the repository; review `.ember/mcp.json` before opening an untrusted project.

## Skills

`SKILL.md` files under `<project>/.ember/skills/<name>/` and `$EMBER_HOME/skills/<name>/` (project wins) are offered to
the model by the `Skill` tool and typed as `/<name> [arguments]`. `$ARGUMENTS` in the body is replaced by the
arguments (otherwise they are appended as `ARGUMENTS: ...`). Frontmatter: `name`, `description`, `argument-hint`,
`disable-model-invocation: true` (hide from the model), `user-invocable: false` (hide from the slash menu).
A skill never shadows a builtin command. `/skills` lists them.

## Plugins

Each directory under `$EMBER_HOME/plugins/` is a plugin:

```
plugin.json                 optional: { "name", "version", "description", "mcpServers": {...} }
commands/<cmd>.md           /<plugin>:<cmd>   (frontmatter `description`; body is the prompt, $ARGUMENTS)
skills/<skill>/SKILL.md     merged into the skill list
mcp.json                    { "mcpServers": {...} }, started as `plugin_<plugin>_<server>`
```

`.ember-plugin/plugin.json` and `.claude-plugin/plugin.json` are accepted manifest locations. A broken plugin is a
notice, not a failure. `/plugins` lists what each plugin contributes.

## Hooks

Settings files merged for hooks (arrays concatenate): `$EMBER_HOME/settings.json`, the project and local settings in
the ember state root, `<project>/.ember/settings.json`, `<project>/.ember/settings.local.json`.

```json
{
  "hooks": {
    "PreToolUse":       [{ "matcher": "Bash", "hooks": [{ "type": "command", "command": "python check.py", "timeout": 10 }] }],
    "PostToolUse":      [{ "matcher": "Edit|Write", "hooks": [{ "type": "command", "command": "npm run lint" }] }],
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "git status --short" }] }],
    "Stop":             [{ "hooks": [{ "type": "command", "command": "python verify.py" }] }]
  }
}
```

A flat `{ "matcher": "Bash", "command": "..." }` entry is also accepted. `matcher` is a regex matched against the whole
tool name (`""` or `"*"` = every tool) and applies to the two tool events. `timeout` is seconds (default 60); a hook
that exceeds it is killed, reported, and ignored. Hooks run in the project directory through the platform shell
(`cmd.exe` on Windows) with `EMBER_PROJECT_DIR` set, and receive the event as JSON on stdin:
`session_id`, `cwd`, `hook_event_name`, plus `tool_name`/`tool_input` (and `tool_response` for PostToolUse), `prompt`
(UserPromptSubmit) or `stop_hook_active` (Stop).

| Exit code | Effect |
| --- | --- |
| 0 | success; stdout of a UserPromptSubmit hook is added to the prompt as context |
| 2 | block: PreToolUse refuses the call and its stderr is the reason the model reads; UserPromptSubmit refuses the prompt (stderr shown to the user); PostToolUse appends stderr to the tool result; Stop makes the model continue once, with stderr as the instruction |
| other | non-blocking error, shown as a notice and ignored |

A hook may instead print `{"decision":"block","reason":"..."}` (or `{"hookSpecificOutput":{"permissionDecision":"deny",
"permissionDecisionReason":"..."}}`) with exit code 0. A hook that cannot start never blocks anything. Hooks apply to
the main session and sub-agents; headless (`-p`) runs PreToolUse/PostToolUse too.

## Scheduled prompts and /loop

- `CronCreate` / `CronDelete` / `CronList` (model tools) keep jobs in memory for the session. A 1 s ticker in the REPL
  fires a due job as a normal prompt, **only while the TUI is idle** (no turn running, nothing typed, no queued
  operator input), one job per tick. A job that came due while busy fires once, late, never as a burst; a one-shot job is
  removed after it fires; a recurring job lives at most 14 days.
- `/loop <interval> <prompt>` (interval `30s`, `5m`, `2h`, `1d`; minimum 5 s) runs the prompt now and again every
  interval while idle. **Esc stops every loop** (and also interrupts a running turn). `/loop` lists loops,
  `/loop stop` stops them.
