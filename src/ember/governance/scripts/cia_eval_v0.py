# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""CIA eval v0: score one published CIA checkpoint on the frozen loglikelihood tasks (lead ruling 82032 E3).

What it is: the model-only checkpoint loader (checkpoint_artifacts.load_cia_checkpoint_model_only: one generation,
no lineage walk, no optimizer), a CIADecoder adopting those verified tensors, and CIALM, a LegBLM subclass whose
scoring core is the #757 exact-token-ID scorer, unmodified: CIALogitsAdapter turns a [1, L] id tensor into the
decoder's own path (embed_text, then forward over one document with positions [[p, 0, 0]] and batch_documents=True).
The frozen-task binding is the v5 scorer's (build_bound_task_specs / verify_frozen_task_runtime), so the scored split
and its source bytes are the same authority.

What it is not: no generate_until (E4), no claim about lineage (the receipt says parent_walk_skipped true), no
publication: every ledger row is publishable=false until the data seat's contamination check reads 0.

Device: cpu needs nothing. cuda* needs EMBER_GATE_AUTHORIZED=1 and EMBER_GPU_LOCK_PATH, and holds the GPU fence through
legb_inprocess_scorer.device_lease -> gpu_lock_guard.acquire, which waits (bounded, logged) for a live holder; the wait is
recorded in the receipt as a covariate. A CUDA run is a card window and is never started from this file's tests.

Results go to an append-only ledger (one JSON object per line, each row carrying the sha256 of the previous row). Zeros
are written as zeros. An abnormal forward exits 3 with the clause inference-forward-actually-ran.

Usage:
  python src/ember/governance/scripts/cia_eval_v0.py --checkpoint-dir <trained-child> --smoke-forward --out-dir <dir>
  python src/ember/governance/scripts/cia_eval_v0.py --checkpoint-dir <trained-child> --manifest-sha256 <pin> --tasks arc_challenge --limit 5 \\
      --device cpu --out-dir <dir> --ledger <dir>/results-ledger.jsonl
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
RESTART_3B = os.path.join(REPO_ROOT, "src", "ember", "infrastructure", "tools", "ember-restart-3b")
for _path in (HERE, REPO_ROOT, os.path.join(REPO_ROOT, "src"), RESTART_3B):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import torch  # noqa: E402

from legb_inprocess_scorer import (  # noqa: E402 -- reused, never edited
    LegBLM, LegBScorerRefusal, load_verified_tokenizer, device_lease,
    TOKENIZER_EXPECTED_SHA256, SHA_CONVENTION,
)
from legb_live_candidate_v5_scorer import (  # noqa: E402 -- the frozen-task binding, reused
    TOKENIZER_REL, FROZEN_SPLIT_BINDING, FROZEN_SUITE_SPEC, HELLASWAG_CONTAMINATION_AUTHORITY,
    load_bound_evaluator_tasks, verify_frozen_task_runtime, _prediction_row, _sha256_file,
)
from checkpoint_artifacts import load_cia_checkpoint_model_only  # noqa: E402

RECEIPT_SCHEMA = "ember-cia-eval-v0/v1"
LEDGER_SCHEMA = "ember-cia-eval-ledger-v1"
MAX_POSITIONS = 4096          # CIADecoder.forward packs 1..4096 unpadded positions
BOUND_TASKS = ("arc_challenge", "hellaswag")
EXIT_FORWARD_FAILED = 3


class CIAEvalRefusal(LegBScorerRefusal):
    """Fail-closed refusal of the CIA eval path; never a silent fallback."""


class ForwardFailed(CIAEvalRefusal):
    """The decoder forward raised; carries the clause the Fable verdict names."""
    clause = "inference-forward-actually-ran"


class CIALogitsAdapter:
    """model(input_ids [1, L]) -> logits [1, L, vocab] through the decoder's own path.

    Records what ran (device, whether candidate_step was entered, the last logits shape), not what was requested.
    """

    def __init__(self, decoder, *, device: str):
        self.decoder = decoder
        self.device = torch.device(device)
        self.executed = {"forward_calls": 0, "candidate_step_entered": False, "last_logits_shape": None,
                         "last_logits_dtype": None, "device": str(self.device)}

    def eval(self):
        return self

    def __call__(self, input_ids):
        if input_ids.ndim != 2 or input_ids.shape[0] != 1:
            raise CIAEvalRefusal("CIA_EVAL_BATCH_ONE_REQUIRED: the scoring core calls the adapter one item at a time")
        length = int(input_ids.shape[1])
        if not 1 <= length <= MAX_POSITIONS:
            raise CIAEvalRefusal(f"CIA_EVAL_POSITIONS_REFUSED: {length} not in [1, {MAX_POSITIONS}]")
        tokens = input_ids[0].to(self.device)
        positions = torch.zeros((length, 3), dtype=torch.long, device=self.device)
        positions[:, 0] = torch.arange(length, dtype=torch.long, device=self.device)
        try:
            with contextlib.ExitStack() as stack:
                if self.device.type == "cuda":
                    stack.enter_context(self.decoder.candidate_step())
                    self.executed["candidate_step_entered"] = True
                embedded = self.decoder.embed_text(tokens)
                logits = self.decoder(embedded, positions, document_starts=(0,), batch_documents=True)
        except Exception as error:  # noqa: BLE001 -- re-raised with the clause, never swallowed
            raise ForwardFailed(f"CIA_EVAL_FORWARD_FAILED: {type(error).__name__}: {error}") from error
        self.executed["forward_calls"] += 1
        self.executed["last_logits_shape"] = list(logits.shape)
        self.executed["last_logits_dtype"] = str(logits.dtype)
        self.executed["device"] = str(logits.device)
        return logits.unsqueeze(0)


class CIALM(LegBLM):
    """LegBLM over a CIA decoder: loglikelihood is the inherited exact-ID core; generation is not part of v0."""

    def generate_until(self, requests):
        raise CIAEvalRefusal("CIA_EVAL_V0_GENERATE_UNTIL_NOT_IMPLEMENTED: v0 scores loglikelihood members only (E4)")


def build_cia_scorer(*, checkpoint_dir: str, manifest_sha256: str | None = None, tokenizer_path: str | None = None,
                     device: str = "cpu", max_model_bytes: int | None = None) -> tuple:
    """Load one generation model-only, adopt it into a CIADecoder, return (CIALM, binding)."""
    from ember.model.ember_v0_decoder import CIADecoder
    tensors, load_receipt = load_cia_checkpoint_model_only(checkpoint_dir, expected_manifest_sha256=manifest_sha256,
                                                          max_model_bytes=max_model_bytes)
    decoder = CIADecoder()
    decoder.adopt_cpu_tensors(tensors)
    del tensors
    if device.startswith("cuda"):
        decoder.activate_cuda(device, resident_capacity=2, optimizer=None)
    tokenizer_path = tokenizer_path or os.path.join(REPO_ROOT, TOKENIZER_REL)
    tokenizer, tokenizer_info = load_verified_tokenizer(tokenizer_path, TOKENIZER_EXPECTED_SHA256)
    adapter = CIALogitsAdapter(decoder, device=device)
    scorer = CIALM(adapter, tokenizer, max_position_embeddings=MAX_POSITIONS, device=device)
    binding = {
        "checkpoint": load_receipt,
        "tokenizer": {key: tokenizer_info[key] for key in ("sha256", "n_dropped_orphan_merges", "n_merges_before")},
        "requested_device": device,
        "sha_convention": SHA_CONVENTION,
        "scoring_core_source": "legb_inprocess_scorer.LegBLM + score_ids_single, imported unmodified (#757 core)",
    }
    return scorer, binding


def smoke_forward(scorer) -> dict:
    """One real forward over a fixed short id sequence; the result records the executed path."""
    adapter = scorer.model
    ids = [101, 7, 4093, 12, 55, 900, 31, 2]
    started = time.monotonic()
    with torch.no_grad():
        logits = adapter(torch.as_tensor([ids], dtype=torch.long, device=adapter.device))
    finite = bool(torch.isfinite(logits.float()).all().item())
    return {"input_ids": ids, "wall_seconds": round(time.monotonic() - started, 3), "logits_finite": finite,
            "executed": dict(adapter.executed)}


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_sha256(row: dict) -> str:
    return hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def append_ledger_row(ledger_path: str, row: dict) -> dict:
    """Append one row to the results ledger; each row binds the sha256 of the row before it. Never rewrites a line."""
    previous = None
    if os.path.exists(ledger_path):
        with open(ledger_path, "rb") as handle:
            lines = [line for line in handle.read().split(b"\n") if line]
        if lines:
            try:
                last = json.loads(lines[-1])
            except ValueError as error:
                raise CIAEvalRefusal("CIA_EVAL_LEDGER_LAST_ROW_UNREADABLE") from error
            if type(last) is not dict or last.get("schema_version") != LEDGER_SCHEMA:
                raise CIAEvalRefusal("CIA_EVAL_LEDGER_LAST_ROW_SCHEMA")
            previous = _row_sha256(last)
    row = {**row, "schema_version": LEDGER_SCHEMA, "prev_row_sha256": previous}
    payload = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor = os.open(ledger_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return row


def verify_ledger(ledger_path: str) -> int:
    """Walk the ledger; every row must carry the sha256 of the row before it. Returns the row count."""
    previous = None
    count = 0
    with open(ledger_path, "rb") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("schema_version") != LEDGER_SCHEMA or row.get("prev_row_sha256") != previous:
                raise CIAEvalRefusal(f"CIA_EVAL_LEDGER_CHAIN_BROKEN at row {count}")
            previous = _row_sha256(row)
            count += 1
    return count


def run_evaluation(*, checkpoint_dir: str, manifest_sha256: str, tasks: list, limit, device: str, out_dir: str,
                   ledger_path: str, tokenizer_path: str | None = None, max_model_bytes: int | None = None) -> dict:
    """Dispatch the CIALM through the INSTALLED lm_eval.evaluator.simple_evaluate; the harness is not reimplemented."""
    unbound = [name for name in tasks if name not in BOUND_TASKS]
    if unbound:
        raise CIAEvalRefusal(f"UNBOUND_EVALUATOR_TASK: {unbound}")
    from lm_eval.evaluator import simple_evaluate
    from lm_eval.tasks import TaskManager
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    predictions_path = os.path.join(out_dir, f"predictions-{stamp}.jsonl")
    task_manager = TaskManager()
    loaded_tasks, loaded_by_name = load_bound_evaluator_tasks(tasks, task_manager)
    fence_wait = None
    started = time.monotonic()
    with device_lease(device):
        wait_module = sys.modules.get("gpu_lock_guard")
        fence_wait = wait_module.last_wait() if (device.startswith("cuda") and wait_module is not None) else None
        scorer, binding = build_cia_scorer(checkpoint_dir=checkpoint_dir, manifest_sha256=manifest_sha256,
                                           tokenizer_path=tokenizer_path, device=device, max_model_bytes=max_model_bytes)
        load_seconds = time.monotonic() - started
        eval_started = time.monotonic()
        results = simple_evaluate(model=scorer, tasks=loaded_tasks, task_manager=task_manager, limit=limit,
                                  bootstrap_iters=0, log_samples=True, verbosity="ERROR")
        eval_seconds = time.monotonic() - eval_started
    per_task = {name: {key: value for key, value in metrics.items()
                       if isinstance(value, (int, float, str, bool)) or value is None}
                for name, metrics in (results.get("results") or {}).items()}
    row_count = 0
    task_rows = {name: 0 for name in tasks}
    with open(predictions_path, "w", encoding="utf-8", newline="\n") as handle:
        for task_name, samples in sorted((results.get("samples") or {}).items()):
            if task_name not in task_rows:
                raise CIAEvalRefusal("UNBOUND_EVALUATOR_TASK_RESULT")
            for sample in samples:
                handle.write(json.dumps({"task": task_name, **_prediction_row(sample)}, sort_keys=True,
                                        ensure_ascii=False) + "\n")
                row_count += 1
                task_rows[task_name] += 1
    if row_count < 1:
        raise CIAEvalRefusal("RAW_PREDICTIONS_EMPTY")
    runtime_binding = {name: verify_frozen_task_runtime(name, loaded_by_name[name], limit=limit,
                                                        observed_rows=task_rows[name]) for name in tasks}
    items = sum(task_rows.values())
    receipt = {
        "schema_version": RECEIPT_SCHEMA, "ts": _utc(), "tasks": tasks, "limit": limit, "bounded": limit is not None,
        "binding": binding, "executed": dict(scorer.model.executed),
        "fence_wait": fence_wait, "publishable": False,
        "contamination": {"status": "NOT_RUN", "required_before_publication": True,
                          "authority": HELLASWAG_CONTAMINATION_AUTHORITY},
        "frozen_suite": {"spec": FROZEN_SUITE_SPEC,
                         "split_binding": {name: FROZEN_SPLIT_BINDING[name] for name in tasks},
                         "runtime_binding": runtime_binding},
        "timing": {"load_seconds": round(load_seconds, 3), "eval_seconds": round(eval_seconds, 3),
                   "items": items, "seconds_per_item": round(eval_seconds / items, 3) if items else None},
        "n_samples": results.get("n-samples"), "task_versions": results.get("versions"), "results": per_task,
        "raw_predictions": {"path": predictions_path, "rows": row_count, "sha256": _sha256_file(predictions_path)},
    }
    receipt_path = os.path.join(out_dir, f"receipt-{stamp}.json")
    with open(receipt_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True)
    receipt_sha256 = _sha256_file(receipt_path)
    for name in tasks:
        append_ledger_row(ledger_path, {
            "ts": receipt["ts"], "task": name, "limit": limit, "device": device,
            "checkpoint_manifest_sha256": binding["checkpoint"]["checkpoint_manifest_sha256"],
            "global_step": binding["checkpoint"]["global_step"], "tokens_seen": binding["checkpoint"]["tokens_seen"],
            "n": task_rows[name], "metrics": per_task.get(name, {}), "publishable": False,
            "contamination_status": "NOT_RUN", "receipt_path": receipt_path, "receipt_sha256": receipt_sha256})
    receipt["receipt_path"] = receipt_path
    receipt["receipt_sha256"] = receipt_sha256
    return receipt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--checkpoint-dir", required=True)
    parser.add_argument("--manifest-sha256", default=None,
                        help="pin: sha256 of checkpoint-manifest.json; required for a scored run, optional for --smoke-forward")
    parser.add_argument("--tasks", default="arc_challenge")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--ledger", default=None)
    parser.add_argument("--tokenizer-path", default=None)
    parser.add_argument("--max-model-bytes", type=int, default=None)
    parser.add_argument("--smoke-forward", action="store_true", help="load, run one forward, write the receipt, stop")
    args = parser.parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)
    try:
        if args.smoke_forward:
            with device_lease(args.device):
                scorer, binding = build_cia_scorer(checkpoint_dir=args.checkpoint_dir, manifest_sha256=args.manifest_sha256,
                                                   tokenizer_path=args.tokenizer_path, device=args.device,
                                                   max_model_bytes=args.max_model_bytes)
                forward = smoke_forward(scorer)
            receipt = {"schema_version": RECEIPT_SCHEMA + "-smoke", "ts": _utc(), "binding": binding, "forward": forward}
            path = os.path.join(args.out_dir, "smoke-receipt.json")
            with open(path, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(receipt, handle, indent=2, sort_keys=True)
            print(json.dumps({"smoke_receipt": path, "sha256": _sha256_file(path), "forward": forward}, sort_keys=True))
            return 0
        if not args.manifest_sha256:
            parser.error("a scored run requires --manifest-sha256 (the pin of the checkpoint under test)")
        ledger = args.ledger or os.path.join(args.out_dir, "results-ledger.jsonl")
        receipt = run_evaluation(checkpoint_dir=args.checkpoint_dir, manifest_sha256=args.manifest_sha256, tasks=[t for t in args.tasks.split(",") if t],
                                 limit=args.limit, device=args.device, out_dir=args.out_dir, ledger_path=ledger,
                                 tokenizer_path=args.tokenizer_path, max_model_bytes=args.max_model_bytes)
        print(json.dumps({"receipt": receipt["receipt_path"], "sha256": receipt["receipt_sha256"],
                          "results": receipt["results"], "timing": receipt["timing"]}, sort_keys=True))
        return 0
    except ForwardFailed as error:
        print(f"{error} [clause {ForwardFailed.clause}]", file=sys.stderr)
        return EXIT_FORWARD_FAILED


if __name__ == "__main__":
    sys.exit(main())
