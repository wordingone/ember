# math500 retry2 receipt (already-executed run, receipted here as part of the eval scoring-window swap)

**Claim:** hendrycks_math500, full 500/500 sample set, exact_match = 0.138 +/- 0.0154 (stderr), against
Qwen3.6-27B-Q4_K_M.gguf served locally.

**Executed:** 2026-07-09T22:44:08Z - 23:03:49Z (total_evaluation_time_seconds = 1254.99, per the native
lm_eval output below), by a prior eval lane (evalref47 worktree) under the eval-lane-playbook contract
(<COORDINATOR_STATE>/state/eval-lane-playbook.md). This receipt was authored by evalswap50 (2026-07-10) to
land the already-completed result -- no re-run performed; raw outputs and run log are copied byte-for-byte
from the evalref47 worktree into this PR.

**Generator invocation (from the native lm_eval results JSON, `config.model_args` + `model_source`):**

```
model_source: local-completions
model_args: {'model': 'Qwen3.6-27B-Q4_K_M.gguf', 'base_url': 'http://127.0.0.1:8082/v1/completions',
             'num_concurrent': 2, 'max_retries': 6, 'tokenizer_backend': None}
task: hendrycks_math500
gen_kwargs: {'until': ['Problem:'], 'do_sample': False, 'temperature': 0.0}
limit: None (full 500-sample set)
```

**Environment (drive/OS, provenance):** run executed on Windows (drive B:, this repo's standard host),
`lm_eval_version = 0.4.12`, `git_hash = invariant-genesis-184-g5a0f441` (this repo's own commit at run
time per lm_eval's git-hash field), `pretty_env_info = "N/A (torch not installed)"` (expected -- this is
an API-mode run against a locally-served llama.cpp-family server, no local torch/transformers model load).

**Result (from `math500-proof/Qwen3.6-27B-Q4_K_M.gguf/results_2026-07-09T23-03-49.194110.json`):**

```json
"hendrycks_math500": {
  "name": "hendrycks_math500",
  "alias": "hendrycks_math500",
  "sample_len": 500,
  "exact_match,none": 0.138,
  "exact_match_stderr,none": 0.015439843831953457
}
```
n-samples: `{"hendrycks_math500": {"original": 500, "effective": 500}}` -- confirms 500/500, no truncation.

**Referenced artifacts in this PR (same directory):**
- `math500-proof/Qwen3.6-27B-Q4_K_M.gguf/results_2026-07-09T23-03-49.194110.json` -- native lm_eval
  aggregated results (full config, versions, git_hash, timing).
- `math500-proof/Qwen3.6-27B-Q4_K_M.gguf/samples_hendrycks_math500_2026-07-09T23-03-49.194110.jsonl` --
  per-sample records (prompt, target, model output, exact_match per row).
- `math500-retry2-run-log-20260710.txt` -- full foreground run log (teed stdout), per eval-lane-playbook
  clause 2 ("foreground, teed, quoted").

refs #487 #591
