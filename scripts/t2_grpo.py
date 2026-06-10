"""t2_grpo.py — W-code GRPO arm (eng #3; contract row 9, arm B).

Pre-registration (binding before first launch):
- ON-POLICY RL with the verifier as reward: the core samples programs for
  MBPP train tasks INSIDE training; each completion is executed in the
  t1_probe sandbox against the task's own asserts. Reward = 1.0 verified,
  0.05 extraction-OK-but-failed (anti-degenerate shaping: emitting runnable
  code > emitting prose), 0.0 otherwise. No model-judged reward anywhere —
  V stays the only oracle (receipts-only truth).
- KL anti-forgetting: GRPO's built-in KL to the frozen reference policy
  (beta) IS the round-2 anti-forgetting AC for this arm — the t5 harm
  receipt (adapter −16pp on general coding) motivates it; t5 non-regression
  gates the adapter after training.
- Bits-weighted prompt mix (eng #5 strata from the pooled w1 posterior):
  easy ×1 / mid ×2 / frontier ×4 / dead ×4 — GPU spends gradient steps
  where bits live; dead tasks stay in the mix (RL can crack what SFT
  can't imitate: nothing to imitate at p̂≈0).
- Eval surface unchanged: G1 = w1_mbpp --split validation (43 heldout
  tasks) base vs adapter vs SFT-arm vs control; t5 harm = MBPP-50 test.
  GRPO trains on TRAIN split only (K3 discipline).

Governor: same launch preconditions as train_lora (VRAM fraction cap +
free-margin assert) + step throttle callback. Runtime API risk: TRL
GRPOConfig arg names vary by version — first launch is the integration
test; receipt or traceback decides (kernel discipline: receipts, not
prose). Receipt: receipts/t2-<tag>-<ts>.json with reward trajectory.

Selftest (`--selftest`, Windows-safe, no torch): prompt-mix weighting,
completion-text extraction across TRL's two completion shapes, reward
shaping table.
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
RECEIPTS = f"{NC}/receipts"
SOLVE_STUB = "\n\ndef solve(grid):\n    return [[0]]\n"  # sandbox gadget

STRATUM_REPEATS = {"easy": 1, "mid": 2, "frontier": 4, "dead": 4}
R_VERIFIED = 1.0
R_RUNNABLE = 0.05
R_NONE = 0.0


def completion_text(completion):
    """TRL passes completions as plain strings (standard format) or
    [{'role','content'}] lists (conversational). Normalize to text."""
    if isinstance(completion, str):
        return completion
    if isinstance(completion, list) and completion \
            and isinstance(completion[0], dict):
        return completion[0].get("content", "")
    return str(completion)


def shaped_reward(extracted, verified):
    if extracted is None:
        return R_NONE
    return R_VERIFIED if verified else R_RUNNABLE


def build_prompt_rows(problems, stats, repeats=None):
    """MBPP problems + pooled (s,n) stats -> GRPO dataset rows with
    bits-weighted repetition. Row: conversational prompt + task_id column
    (TRL forwards extra columns to the reward fn as kwargs)."""
    import sys
    sys.path.insert(0, f"{NC}/scripts")
    from frontier import stratum
    from w1_mbpp import problem_prompt
    repeats = repeats or STRATUM_REPEATS
    rows = []
    for p in problems:
        s, n = stats.get(f"mbpp:{p['id']}", (0, 0))
        st = stratum(s, n)
        for _ in range(repeats[st]):
            rows.append({"prompt": [{"role": "user",
                                     "content": problem_prompt(p)}],
                         "task_id": p["id"], "stratum": st})
    return rows


def make_reward_fn(problems_by_id, counter):
    """Closure executing each completion in the t1_probe sandbox."""
    from t1_probe import execute_batch, extract_code

    def verify_reward(prompts, completions, task_id=None, **kwargs):
        srcs = [extract_code(completion_text(c)) for c in completions]
        jobs, idx = [], []
        for i, src in enumerate(srcs):
            if src is None:
                continue
            p = problems_by_id[int(task_id[i])]
            harness = "\n".join(p["imports"]) + "\n" + src + "\n" + \
                "\n".join(p["tests"]) + SOLVE_STUB
            jobs.append((harness, [], []))
            idx.append(i)
        results = execute_batch(jobs) if jobs else []
        ok = {i: bool(r.get("verified")) and not r.get("error")
              for i, r in zip(idx, results)}
        rewards = [shaped_reward(srcs[i], ok.get(i, False))
                   for i in range(len(completions))]
        counter["batches"] += 1
        counter["completions"] += len(rewards)
        counter["verified"] += sum(1 for r in rewards if r == R_VERIFIED)
        return rewards

    return verify_reward


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen2.5-Coder-3B-Instruct")
    ap.add_argument("--tag", default="r1w-q3-grpo")
    ap.add_argument("--stats-from", nargs="+", default=[
        f"{RECEIPTS}/w1-floor-q3-20260610T203401Z-samples.jsonl",
        f"{RECEIPTS}/w1-floor-q3-focus-20260610T210228Z-samples.jsonl"])
    ap.add_argument("--num-generations", type=int, default=8)
    ap.add_argument("--max-steps", type=int, default=60)
    ap.add_argument("--max-completion", type=int, default=512)
    ap.add_argument("--beta", type=float, default=0.04)
    ap.add_argument("--lr", type=float, default=5e-6)
    ap.add_argument("--temp", type=float, default=0.8)
    ap.add_argument("--seed", type=int, default=3407)
    args, _unknown = ap.parse_known_args()  # daemon appends args

    import sys
    sys.path.insert(0, f"{NC}/scripts")
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

    import torch  # noqa: F401 — cuda context for governor + trainer
    # Governor preconditions via the canonical module (eng #9); evidence
    # block rides on the receipt.
    from governor import preflight
    governor_block = preflight()

    from unsloth import FastLanguageModel
    patched = False
    try:  # unsloth GRPO patch (older recipes need it; newer absorb it)
        from unsloth import PatchFastRL
        PatchFastRL("GRPO", FastLanguageModel)
        patched = True
    except ImportError:
        pass
    print(f"[t2_grpo] PatchFastRL applied: {patched}", flush=True)
    from trl import GRPOConfig, GRPOTrainer
    from transformers import TrainerCallback
    from datasets import Dataset
    from huggingface_hub import snapshot_download
    from t2_round import ADAPTERS, LORA
    from frontier import outcome_stats
    from w1_mbpp import load_split

    class _Headroom(TrainerCallback):
        def on_step_end(self, targs, state, control, **kw):
            time.sleep(float(os.environ.get("EMBER_THROTTLE_S", "0.3")))

    try:
        model_path = snapshot_download(args.model, local_files_only=True)
    except Exception:  # noqa: BLE001
        model_path = args.model
    model, tok = FastLanguageModel.from_pretrained(
        model_name=model_path, max_seq_length=LORA["max_seq"],
        dtype=torch.bfloat16, load_in_4bit=True)
    model = FastLanguageModel.get_peft_model(
        model, r=LORA["r"], lora_alpha=LORA["alpha"],
        lora_dropout=0.0,  # GRPO: dropout off, policy = sampled policy
        bias="none", use_gradient_checkpointing="unsloth",
        random_state=args.seed,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"])
    # Integration fix (e8013346 attempt 1): unsloth keeps LoRA params in
    # float32; vanilla-TRL generation under autocast hits the fast_lora
    # kernel with mismatched dtypes ("Half and Float"). One dtype everywhere:
    n_cast = 0
    for _n, _p in model.named_parameters():
        if "lora_" in _n and _p.dtype == torch.float32:
            _p.data = _p.data.to(torch.bfloat16)
            n_cast += 1
    print(f"[t2_grpo] lora params cast fp32->bf16: {n_cast}", flush=True)

    problems = load_split("train")
    problems_by_id = {p["id"]: p for p in problems}
    rows = []
    with_stats = []
    for path in args.stats_from:
        with open(path) as f:
            with_stats.extend(json.loads(line) for line in f if line.strip())
    stats = outcome_stats(with_stats)
    rows = build_prompt_rows(problems, stats)
    counter = {"batches": 0, "completions": 0, "verified": 0}

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = f"{ADAPTERS}/{args.tag}"
    config = GRPOConfig(
        output_dir=out_dir + "-ckpt",
        per_device_train_batch_size=args.num_generations,
        num_generations=args.num_generations,
        gradient_accumulation_steps=2,
        max_steps=args.max_steps,
        learning_rate=args.lr,
        beta=args.beta,
        temperature=args.temp,
        max_completion_length=args.max_completion,
        max_prompt_length=LORA["max_seq"] - args.max_completion,
        logging_steps=1, save_strategy="no", report_to="none",
        bf16=True, seed=args.seed)
    trainer = GRPOTrainer(
        model=model, processing_class=tok,
        reward_funcs=[make_reward_fn(problems_by_id, counter)],
        args=config,
        train_dataset=Dataset.from_list(rows),
        callbacks=[_Headroom()])
    t0 = time.time()
    trainer.train()
    secs = round(time.time() - t0, 1)
    model.save_pretrained(out_dir)
    tok.save_pretrained(out_dir)

    rewards = [h["reward"] for h in trainer.state.log_history
               if "reward" in h]
    from receipt_fp import args_fingerprint  # eng #10
    receipt = {
        "ticket": "NC0-T2-GRPO", "ts": ts, "args": vars(args),
        "args_fp": args_fingerprint(vars(args)),
        "governor": governor_block,
        "world": "mbpp", "round": 1, "prompt_rows": len(rows),
        "prompt_mix": {st: sum(1 for r in rows if r["stratum"] == st)
                       for st in STRATUM_REPEATS},
        "sandbox": counter,
        "reward_first5_mean": round(sum(rewards[:5]) / max(len(rewards[:5]), 1), 4),
        "reward_last5_mean": round(sum(rewards[-5:]) / max(len(rewards[-5:]), 1), 4),
        "reward_trajectory": [round(r, 4) for r in rewards],
        "train_secs": secs, "adapter": out_dir,
    }
    os.makedirs(RECEIPTS, exist_ok=True)
    with open(f"{RECEIPTS}/t2-{args.tag}-{ts}.json", "w") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps({k: v for k, v in receipt.items()
                      if k != "reward_trajectory"}, indent=2, default=str))
    print("T2_GRPO_DONE")


def _selftest():
    # completion shapes
    assert completion_text("abc") == "abc"
    assert completion_text([{"role": "assistant", "content": "x"}]) == "x"
    # reward shaping table
    assert shaped_reward(None, False) == R_NONE
    assert shaped_reward("def f(): pass", False) == R_RUNNABLE
    assert shaped_reward("def f(): pass", True) == R_VERIFIED
    # prompt-mix weighting (pure parts of build_prompt_rows, inlined to stay
    # Windows-safe: w1_mbpp imports t1_probe -> POSIX resource)
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from frontier import stratum
    stats = {"mbpp:1": (8, 8), "mbpp:2": (1, 32), "mbpp:3": (0, 8),
             "mbpp:4": (4, 8)}
    mix = {}
    for tid in (1, 2, 3, 4):
        st = stratum(*stats[f"mbpp:{tid}"])
        mix[tid] = STRATUM_REPEATS[st]
    assert mix == {1: 1, 2: 4, 3: 4, 4: 2}
    print("T2_GRPO_SELFTEST_PASS")


if __name__ == "__main__":
    import sys as _sys
    if "--selftest" in _sys.argv:
        _selftest()
    else:
        main()
