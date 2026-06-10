# NC-K Invariant Contract v0

*Provenance: synthesized 2026-06-10 from an 8-subsystem clean-room audit (workflow wf_c8be6869-6d1, 9 agents); reviewed and gated by Leo. v0 — invariants are behavioral contracts, not file maps; the internal detailed map carries the per-subsystem evidence.*

A minimal, self-hostable agent kernel distilled from a ~142K-LOC reference harness. Fifteen invariants. Everything not listed under an invariant is either incidental mass (see "Deliberately excluded") or a borrowed organ (see inventory). An implementation that holds all fifteen is a conforming kernel regardless of language or backend.

## Process supervision

**1. Typed terminal, always.** Every submitted prompt yields exactly one typed terminal result (completed, aborted, max-turns, budget-exceeded, model-error, hook-stopped, ...) carrying the full accounting record — usage, cost, turn count, permission denials. Hard resource caps (max turns, max spend) terminate deterministically through this same path; the caller never gets zero results or two.

**2. One abort signal, checked at every boundary.** A single cancellation signal threads through model calls, retry sleeps, stream consumption, tool execution, and hook runs, composing with internal abort sources (watchdogs) by union. Abort still completes tool-call/result pairing, emits synthetic results for in-flight work, and surfaces as a typed terminal — never as an unstructured throw.

**3. One model narrow waist.** The entire kernel reaches any backend through one async method (system, messages, tools, max-tokens, signal) in one canonical message schema; all protocol differences live in adapters that must be semantically lossless on the agent-critical axes (tool-call mapping in both directions, tool-choice explicitly defaulted when tools are present, finish-reason fidelity, usage captured even when it arrives in a trailing content-free stream chunk). Backend errors become in-band messages the loop can continue past — only user cancellation throws — and usage accounting is monotone: trailing updates never zero out real token counts.

**4. Background work is registry entries, not loose processes.** Every background unit (shell process, sub-agent, monitor) is one record in a single typed task map with absorbing terminal states; every mutation is a read-modify-write against fresh state that re-checks status first (a finished kill is never resurrected; an offset patch never applies a stale full-record spread). Completion notification is exactly-once via an atomically checked-and-set flag; task output lives on disk behind a size-capped append queue and reaches the model as offset deltas; an owner-scoped reaper kills all tasks an agent spawned when that agent exits and purges notifications addressed to it. Terminal-but-unconsumed tasks are never evicted.

## Tool dispatch

**5. One uniform tool interface.** Every capability — built-in, remote-bridged, or skill-derived — implements the same shape: name, typed input schema, async call, and safety/permission predicates (concurrency-safe?, read-only?, permission check). Dispatch is name-based lookup over one registry; no tool gets a special execution path; defaults are conservative (not concurrency-safe, not read-only, defer to the general permission system).

**6. Every tool call pairs with exactly one result.** Unknown tool, schema-parse failure, validation failure, permission denial, hook block, abort, and runtime exception each short-circuit to an error result delivered to the model as data — never thrown into the loop. An orphaned tool call is an illegal state; message history is pairing-repaired (synthetic error results for orphans, stranded results stripped) before every request leaves the kernel.

**7. Fail-closed pre-execution pipeline.** Fixed order, no reordering: schema parse → tool-specific validation → pre-execution hooks → permission resolution → execute → post-execution hooks → result mapping. Any stage failing means the tool body never runs and the model receives an explanatory error result.

**8. Declared-safety concurrency; bounded results.** Only calls whose own predicate declares them concurrency-safe for their parsed input run in bounded parallel batches; anything unsafe, unparseable, or throwing runs serial, and context mutations from a parallel batch apply deterministically only after the batch completes. Results exceeding a per-tool size threshold spill to disk and the model receives a preview plus a path — context growth is bounded without destroying data.

## Hooks and gates

**9. Hooks speak one strict protocol.** Every hook receives one uniform JSON envelope on stdin (session id, transcript path, cwd, event name, event payload) so external processes can correlate with ground truth. Exit 0 = pass (stdout may inject context); exit 2 = block, with stderr becoming the model-visible reason; any other exit = non-blocking error. Malformed output degrades to a non-blocking error — never silent success, never accidental block. Crash or timeout fails open; only an explicit block fails closed. Every hook execution is observable and attributable in the session stream.

**10. Deny beats ask beats allow; hooks never escalate.** Parallel hook results for one event aggregate with strict precedence deny > ask > allow regardless of completion order, and a hook "allow" is re-checked against static configured policy afterward — a configuration deny always wins. Hooks may rewrite tool input before execution, but the model's original input round-trips into the transcript verbatim.

**11. The hook set is frozen at session start.** Hook configuration is snapshotted at startup with policy supremacy (managed config can restrict; unmanaged config can never disable managed hooks), so nothing — including the model — can add or alter gates mid-session. Stop hooks may veto turn end with a reason that re-enters the loop as input, carry a loop-breaker flag so they can detect their own re-entry, and never run when the last message is a backend error (the death-spiral rule).

## State and persistence

**12. Transcript first; everything replays from the log.** User input is durably appended to the session transcript before the model request is made, and buffers are flushed before the terminal result is emitted — the session is resumable from the instant input was accepted. Commands and skills operate purely by message injection into that same log (a visible metadata line plus a hidden expanded body); compaction boundaries are first-class logged events, and post-compaction requests include only post-boundary messages. There is no side channel: replaying the log reproduces the session.

**13. One observable store; memory is plain files capped at read time.** All mutable session state lives in a single store with snapshot reads, functional updates, identity short-circuit, and exactly one diff-based change hook as the sole side-effect channel. Persistent memory is plain files under a per-project directory — no daemon, no database — with size caps enforced when read, regardless of write-time discipline, and truncation notices delivered in-band naming the cap and the recovery action. The harness guarantees a state of the world (directory exists, snapshot taken) before the prompt asserts it.

## Scheduling

**14. Bounded recovery everywhere; input only at boundaries.** Context-window pressure is handled inside the loop — compaction before the call, recoverable-overflow retry after it — and recoverable errors are withheld from consumers until in-loop recovery is exhausted. Every retry or compaction path carries an explicit guard (per-turn fire-once flags that survive stop-hook re-entry, consecutive-failure circuit breakers, hard retry limits) so no recovery can spiral. Mid-turn input — queued messages, task notifications — enters only at tool-result boundaries between requests, scoped to the agent it addresses, never mid-stream.

**15. One permission gate, injected and delegable.** Every tool execution passes a single can-use-tool gate that is a parameter of the loop, not embedded in it, so it can be delegated outward (to a host process, a wire protocol, or a human prompt). The tool pool the model sees is permission-filtered at assembly time, not just call time. A permission decision may carry an input rewrite that reaches execution, but never mutates the model-bound original. Dangerous bypass modes are environment-gated eagerly at startup, before the first request — never checked lazily.

---

## Deliberately excluded

The reference implementation spends roughly 95% of its volume on things a kernel does not need:

- All terminal/graphical UI: rendering halves of tool interfaces, interactive command UIs, panels, pills, themes, onboarding.
- All telemetry, analytics, metrics, tracing, and feature-flag/experiment plumbing.
- Multi-cloud provider SDKs, billing/quota/subscription logic, account tiers.
- Plugin and marketplace systems; remote-control, bridge, and cloud-session transports; record/replay test fixtures.
- Tool-search/deferred-loading machinery, speculative permission classifiers, model-generated activity summaries.
- All compaction strategies but one (keep a single strategy plus its circuit breaker).
- All hook implementation types except external command hooks (and optionally an in-process callback); async/backgrounded hooks; the long tail of ~20 lifecycle events beyond the core 6–8.
- Embedded shell execution inside skill bodies (largest security surface, smallest payoff — re-addable later behind the existing tool-permission gate, never for remote-sourced skills); dynamic/conditional skill discovery (load once at startup); legacy tool-name aliases.
- Daemon/jobs stubs, dream/remote task types, stall-detection heuristics beyond a minimal "output stopped growing" advisory.
- Layered multi-source config with five coordinated memo caches — one settings file, loaded once.

## Borrowed-organ inventory

| Dependency | Role in kernel | Ownership path |
|---|---|---|
| zod (or equivalent) | Tool input contracts; hook output protocol; settings validation | **Keep** — with the hard rule: no transforms in any schema used for persisted files (validation and serialization strictly separable) |
| Model-provider SDK (message/stream wire types, error taxonomy) | The canonical message schema the whole kernel is written against | **Keep** types as canonical schema; thin client is replaceable with native fetch + a small adapter |
| MCP SDK | Bridging remote tools into the uniform tool interface | **Keep, optional** — one ~150-LOC adapter wrapping remote tools in the standard interface; no special-cased paths |
| Node/Bun builtins (crypto, fs, child_process, fetch, AbortSignal) | IDs, disk task output, hook/process spawn, HTTP | **Keep** — platform, not dependency |
| shell-quote | Positional argument parsing in skill templates | **Keep** (trivial, well-bounded) |
| proper-lockfile | Cross-process append lock on shared history | **Reimplement** — O_APPEND single-writer or mkdir-based lock (~30 LOC), or drop history in headless builds |
| lodash (memoize, uniqBy) | Registry caching, pool dedup | **Reimplement** — ~10-LOC memoize; kernel loads once and needs almost no caching |
| ignore (gitignore matching) | Conditional skill discovery | **Drop** — feature excluded |
| React/Ink, chalk, strip-ansi | All rendering | **Drop** — kernel is headless |
| OpenTelemetry, feature-flag SDKs | Telemetry, experiments | **Drop** |
| Multi-cloud auth SDKs | Cloud provider credentials | **Drop** — one backend at a time |
| Local inference server HTTP contract (health, model-properties endpoints) | Live discovery of true context window; never trust config files for it | **Keep as external contract** — owned by the server, consumed read-only |
| git CLI | Point-in-time environment snapshot at conversation start | **Keep** (subprocess; output truncated with in-band "fetch it yourself" notice) |
| Windows job-object native addon | Race-free child-process lifetime binding for managed local server | **Fork/keep** only if supervising a local model server on Windows; otherwise drop |
