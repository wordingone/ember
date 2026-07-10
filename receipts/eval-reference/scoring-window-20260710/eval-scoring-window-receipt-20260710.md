# Eval scoring-window swap — receipt (2026-07-10)

Owner: evalswap50 lane. Window: llama-server outage 13:03Z-14:51Z for a GPU scoring pass.

## 1. Outcome summary

| Phase | Task | Result |
|---|---|---|
| 2 | Kill llama-server (receipt-first) | Done — kill-receipts.jsonl, `evalswap50-phase2`, PID 39600 |
| 3 | AC2 pace-smoke (block05, resume from step-806) | GOVERNED-ABORT-PARTIAL — see [ac2-pace-smoke-maintree-log.txt](ac2-pace-smoke-maintree-log.txt) |
| 4 | grad_post rider (#482) | Already complete pre-window; no action taken |
| 5 | Direct llama-cpp-python load (arc_challenge/hellaswag) | Blocked — architecture + ABI incompatible; see [direct-llamacpp-load-attempt-log.txt](direct-llamacpp-load-attempt-log.txt) |
| 5b | local-completions fallback, arc_challenge one-task proof | Blocked — no local HF tokenizer for this model; see [arc-challenge-one-task-proof-log.txt](arc-challenge-one-task-proof-log.txt) |
| 6 | mmlu_pro 20-sample rate-check | Blocked — same tokenizer root cause, different failure mode; see [mmlu-pro-rate-check-log.txt](mmlu-pro-rate-check-log.txt) |
| 7 | Restore llama-server | Done — PID 34824, cmdline-verified, health 200 |
| 8 | Archive outage marker | Done — coordinator-side (planned-outage marker archived by coordinator 2026-07-10T15:17:00Z to `tools/ember-cli/state/archive/planned-outage-20260710T130240Z.json`, outage closed, server health-200) |

## 2. AC2 pace-smoke (block05) — GOVERNED-ABORT-PARTIAL

Relaunched from the main tree per coordinator ruling (worktree-first rule protects against
mutation, not execution; outputs redirected to this lane's worktree). Checkpoint produced:

```
<REPO_ROOT>/.claude/worktrees/evalswap50-ac2/models/cbase-grow-rung/rung2-stabilize-leg1-smoke/block-05/checkpoints/step-00000816/
  manifest.json, model.pt, optimizer.pt, rng.pt
```

manifest.json:
```json
{"extra": {"ce_impl": "cut_ce_chunked", "last_loss": 11.65234375, "mtp_enabled": true,
  "optimizer_mode": "muon_split", "segment_id": "cbase-grow-rung2-stabilize-leg1-block05",
  "total_steps": 449651}, "step": 816, "ticket": "TIMESHARE-CHECKPOINT", "ts": "20260710T143612Z"}
```

**Condition 1 (BUILD-line guard): SATISFIED.** `BUILD done: transplanted checkpoint=.../step-00000806
... issue #577 cure` captured at 14:24:48Z.

**Condition 2 (loss continuity): UNRESOLVED-STRUCTURAL, not a lane gap.** manifest.last_loss went
11.1640625 (step 806, pre-resume) -> 11.65234375 (step 816, +10 steps), a +4.4% single-point delta.
No per-step trace exists to distinguish segment-boundary jitter from a real defect: the run's own
stdout capture has a genuine platform gap (`torch.distributed.elastic.multiprocessing.redirects:29]
NOTE: Redirects are currently not supported in Windows or MacOs` — worker-subprocess stdout, where
per-step loss prints originate, never reaches the parent tee on Windows). No independent structured
receipt file exists either (checked both this lane's receipt dir and the main-tree receipts/ by
mtime). Filed against #627 by the coordinator: v8 must write a structured per-step trace file
(loss/step/ts) to the receipt dir, since stdout is not a reliable channel on this platform.

**Condition 3 (disclosure): this section.** manifest.json for step-00000816 carries no
`momentum_provenance` and no per-tensor RMS fields — the same gap tracked in #677 on the parent
step-806 checkpoint. Expected: this smoke run forward-computed 10 steps from the already-broken
transplant; it never had an opportunity to repair the provenance gap. #677 propagates to this
checkpoint too.

**Terminal event:** `GOVERNOR_COMMIT_FAIL label=POST_RUN_V0_SEGMENT_BLOCK_DONE_block05
committed_gb=74.514 limit_gb=79.603 free_gb=5.09 floor_gb=6.0` — abort-not-degrade, no fix-forward,
no widened floor. The #619 in-run commit governor worked exactly as designed: clean stop, no OOM
crash, no cascading process kill. PIDs 50584/41588 confirmed terminated post-abort
(Get-CimInstance returns empty).

## 3. Eval scoring blockers (phases 5/5b/6)

Direct llama-cpp-python load of the GGUF fails two independent ways: stock builds reject the custom
`qwen35` architecture (`unknown model architecture: 'qwen35'`); loading avir-cli's own fork DLL via
`LLAMA_CPP_LIB_PATH` gets past the architecture check but fails at Python ctypes bind time
(`AttributeError: function 'llama_rope_type' not found`) — a genuine C ABI mismatch with no
matching pip wheel. Full tracebacks in the linked log.

Fallback to lm_eval's `local-completions` HTTP path (against the restored llama-server) works for
generate_until tasks (math500, banked separately — see `math500-retry2-receipt-20260710.md` in the
parent directory) but not for loglikelihood-scored tasks:

- **arc_challenge** (tokenizer_backend=None): `AssertionError: Tokenizer is required for
  loglikelihood tasks to compute context lengths.` — deterministic, client-side, on the first
  request.
- **mmlu_pro** (tokenizer_backend=None, 20-sample rate-check): 20/20 requests failed server-side —
  `{"error":{"code":500,"message":"Invalid input batch.","type":"server_error"}}` — same root
  cause (no real tokenizer to shape the loglikelihood request), different failure surface
  (llama-server's batch scorer rejects the malformed request rather than lm_eval catching it
  client-side). Run stopped after 20 consecutive failures rather than exhausting the full 280-item
  batch on a confirmed-dead configuration; server remained healthy throughout (health-200
  reconfirmed post-stop).
- **hellaswag**: not attempted — same task family/client path as arc_challenge, same blocker
  expected; not worth an identical proof run.

**Tokenizer search (why no fallback exists):** searched the full avir-cli repo (all worktrees) for
a matching `tokenizer.json`/`tokenizer_config.json` — only found a chat template
(`chat-templates/qwen36_chat_template.jinja`, not a vocab/merges file). Searched the local HF cache
— only an unrelated `Qwen/Qwen2.5-0.5B-Instruct` tokenizer present. No source HF checkpoint for this
qwen35-architecture 27B model exists on this machine; it exists only as this GGUF. Did not
substitute the 0.5B tokenizer (wrong vocab, would silently corrupt context-length math).

**Verdict:** arc_challenge, hellaswag, and mmlu_pro are structurally blocked on this server without
a matching local HF-format tokenizer for the qwen35 architecture. Producing one (e.g. via gguf-py
vocab extraction from the GGUF's own embedded tokenizer metadata) would very likely unblock all
three — not attempted this window; that is a build, not a diagnosis, and is out of this lane's
scope. Unblock path filed as ember issue #685 (HF tokenizer extraction from the GGUF via gguf-py,
round-trip acceptance against llama-server `/tokenize`).

## 4. Server restore

```
PID 34824, cmdline-verified: "<AVIR_CLI_ROOT>\vendor\llama-turboquant\build\bin\llama-server.exe"
  --model <AVIR_CLI_ROOT>\models\Qwen3.6-27B-Q4_K_M.gguf --port 8082
health: {"status":"ok"} at first probe (14:51:49Z) and reconfirmed at +2min and post-mmlu_pro-abort
```

## 5. Outage marker disposition

Planned-outage marker archived by coordinator 2026-07-10T15:17:00Z to
`tools/ember-cli/state/archive/planned-outage-20260710T130240Z.json`. Outage closed, server
health-200. The #464 watchdog existence-gate is clear (watchdog free to act on this file going
forward).

## 6. TREE-INTEGRITY

Main-tree `git status --porcelain` diffed against a pre-window baseline (279 lines ->
282 lines): the 3 new lines are `receipts/registry-gate.jsonl` (mod) plus two receipt files
(audit, process-visibility) authored by other in-flight lanes, none attributable to this window's
AC2/eval work.

refs #487 #591
