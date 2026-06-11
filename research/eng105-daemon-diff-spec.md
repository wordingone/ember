# eng-29 (#105) — train-daemon diff spec: per-job eval/export logs + train-live dispatch guard

Target: `B:/M/avir/infra/train-daemon/server.py` (366 lines, FastAPI). Cross-founder infra — this spec goes to Leo BEFORE any edit (mail condition, 14476). Minimal surface: 5 hunks, eval/export paths only, ZERO train-path behavior change.

## Hazard, verified in source

- `POST /jobs/{id}/eval` (lines 252-259): `log_path = Path(parent.output_dir) / "eval.log"`, opened `"w"` — every eval sub-job of the same parent TRUNCATES the shared eval.log, including a sibling eval still running. This is the STATE.md standing hazard and why all eng daemon legs are hand-serialized today.
- `POST /jobs/{id}/export` (lines 292-294): identical pattern, `export.log`.
- Readers resolve the log by job TYPE, not per job: `get_job` (209-214), `get_job_logs` (236-241), `wait_job` (328) — all read the one shared file.
- Persistence: `_save_jobs`/`_load_jobs` round-trip job dicts as JSON (`process`/`log_file` nulled on load, line 44-45) — adding a string field is persistence-compatible.
- `/shutdown` (354-361) already refuses while jobs run — satisfies the zero-in-flight restart condition mechanically.

## Diff (by hunk)

1. **eval_job, line 253 + sub_job dict (~267):**
   `log_path = Path(output_dir) / f"eval-{sub_id}.log"` ; add `"log_name": log_path.name` to `sub_job`.
2. **export_job, line 292 + sub_job dict (~302):**
   `log_path = Path(output_dir) / f"export-{sub_id}.log"` ; add `"log_name": log_path.name`.
3. **create_job (train), job dict (~173):** add `"log_name": "train.log"` — field only; train log path/behavior byte-identical.
4. **Readers (get_job 209-214, get_job_logs 236-241, wait_job 328):**
   `log_name = job.get("log_name") or <existing type-based selection>` — one-line change each; legacy persisted jobs (no field) keep resolving to the old shared names, so history stays readable.
5. **Dispatch guard (eval_job + export_job, top of handler):**
   if any OTHER job has `status=="running"` and `type=="train"` → HTTP 409: `"train job <id> live — dispatch refused (log/resource contention); set allow_during_train=true to override"`. New pydantic fields: `EvalConfig.allow_during_train: bool = False`, same on `ExportConfig`. Default-closed; per-dispatch opt-in for gate-authorized CPU-only evals. Train-path (`POST /jobs`) untouched.

## Non-changes (explicit)

- `read_log_tail` already takes `log_name` — no change.
- Train MCP binary: log resolution is server-side (`GET /jobs/{id}/logs`) — no MCP change.
- mode `"w"` stays — truncation is now scoped to each job's OWN fresh file.
- No schema change to receipts, no train hyperparam/path logic touched.

## Rollout

1. Leo signs off this spec (#105 condition).
2. Edit lands when `train_list` shows zero running jobs.
3. `POST /shutdown` (self-refusing if busy) → `train_daemon_start` relaunch.
4. Verification: dispatch two concurrent trivial CPU eval jobs against one parent → two distinct `eval-<id>.log` files, both complete, neither truncated; then dispatch an eval during a dummy "train" job → 409; with `allow_during_train=true` → runs. Receipt with the three outcomes; unblocks the deferred t1_chunked/w1 runtime-import checks.

## Post-edit record (2026-06-11)

- Edit landed in the zero-in-flight window; daemon restarted via self-refusing /shutdown + train_daemon_start (414 persisted jobs loaded).
- `server.py` post-edit sha256 = `433346ac7582cfdc24740e7921c8fbdfa0bff854c40d25d7933a7458030f8490` (raw on-disk bytes, LF endings); `py_compile` OK.
- server.py lives in shared infra OUTSIDE this repo (B:/M/avir/infra/train-daemon/); the change is committed in that repo — this file + the verification receipt are the in-repo record.
- Verification receipt: `receipts/eng105-verify-20260611T023239Z.json` (4 checks: legacy fallback, two concurrent per-job evals, 409 guard, allow_during_train override — all pass).
