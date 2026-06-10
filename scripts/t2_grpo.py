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


def shaped_reward_partial(extracted, frac):
    """Row-9 arm (eng #15): reward = fraction of asserts passed — denser
    training-only signal, same extremes as the binary table. THE GATE STAYS
    BINARY (verified/not); this never touches verification. Floor at
    R_RUNNABLE keeps the anti-degenerate shaping (a runnable program that
    fails every assert still beats no program); all asserts passed -> 1.0,
    identical to R_VERIFIED."""
    if extracted is None:
        return R_NONE
    return max(R_RUNNABLE, frac)


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


def make_reward_fn(problems_by_id, counter, mode="binary"):
    """Closure executing each completion in the t1_probe sandbox.

    mode="binary" (default, pre-registered eng #13 arm): one sandbox job
    per completion, all asserts joined — reward per shaped_reward.
    mode="partial" (row-9 arm, eng #15): one sandbox job PER ASSERT —
    reward per shaped_reward_partial (fraction passed). Sandbox cost
    multiplies by the assert count (~3x on MBPP); execute_batch pools."""
    from t1_probe import execute_batch, extract_code

    def verify_reward(prompts, completions, task_id=None, **kwargs):
        srcs = [extract_code(completion_text(c)) for c in completions]
        jobs, idx = [], []
        for i, src in enumerate(srcs):
            if src is None:
                continue
            p = problems_by_id[int(task_id[i])]
            # p["tests"] elements are top-level MBPP assert statements;
            # each is independently executable after imports + src.
            tests = p["tests"] if mode == "partial" \
                else ["\n".join(p["tests"])]
            for t in tests:
                harness = "\n".join(p["imports"]) + "\n" + src + "\n" + \
                    t + SOLVE_STUB
                jobs.append((harness, [], []))
                idx.append(i)
        results = execute_batch(jobs) if jobs else []
        passed, total = {}, {}
        for i, r in zip(idx, results):
            total[i] = total.get(i, 0) + 1
            passed[i] = passed.get(i, 0) + \
                (1 if bool(r.get("verified")) and not r.get("error") else 0)
        if mode == "partial":
            rewards = [shaped_reward_partial(
                srcs[i], passed.get(i, 0) / total[i] if total.get(i) else 0.0)
                for i in range(len(completions))]
            counter["asserts_passed"] = \
                counter.get("asserts_passed", 0) + sum(passed.values())
            counter["asserts_total"] = \
                counter.get("asserts_total", 0) + sum(total.values())
        else:
            ok = {i: total.get(i, 0) > 0 and passed[i] == total[i]
                  for i in idx}
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
    ap.add_argument("--reward", choices=["binary", "partial"],
                    default="binary",
                    help="binary = pre-registered eng #13 shaping table; "
                         "partial = per-assert fraction (row-9 arm, eng #15;"
                         " training-only — THE GATE STAYS BINARY)")
    args, _unknown = ap.parse_known_args()  # daemon appends args

    import sys
    sys.path.insert(0, f"{NC}/scripts")
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

    import torch  # noqa: F401 — cuda context for governor + trainer
    # Governor preconditions via the canonical module (eng #9); evidence
    # block rides on the receipt.
    from governor import preflight
    governor_block = preflight()

    # Attempt 3 (integration tests e8013346 + e68e6ae8 receipted): unsloth's
    # fast_lora kernels clash with TRL GRPO generation (fp16 inference path
    # vs fp32 LoRA re-upcast by PatchFastRL — both fixes confirmed applied
    # and both insufficient). Wall broken by REMOVING unsloth from this arm:
    # vanilla transformers + bnb-4bit(bf16 compute) + PEFT via TRL's
    # peft_config. Slower generation, standard stack, no custom kernels.
    # SFT arms keep unsloth (proven there).
    from trl import GRPOConfig, GRPOTrainer
    from transformers import (AutoModelForCausalLM, AutoTokenizer,
                              BitsAndBytesConfig, TrainerCallback)
    from peft import LoraConfig
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
    model = AutoModelForCausalLM.from_pretrained(
        model_path,
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True),
        torch_dtype=torch.bfloat16, device_map={"": 0})
    tok = AutoTokenizer.from_pretrained(model_path)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    # transformers 5.2 removed PreTrainedModel.warnings_issued; this TRL
    # still touches it in GRPOTrainer.__init__ (attempt-3 receipt 4b763324)
    if not hasattr(model, "warnings_issued"):
        model.warnings_issued = {}
    # Attempt 5 (v4 receipt dcfd0e53: TRL's internal kbit-prep upcasts
    # LN/lm_head to fp32 -> "expected BFloat16 but found Float" in the
    # vanilla forward). Wrap PEFT OURSELVES, then collapse every
    # non-quantized param back to bf16 — one dtype everywhere; pass the
    # wrapped model so TRL skips its own prep.
    from peft import get_peft_model, prepare_model_for_kbit_training
    peft_cfg = LoraConfig(
        r=LORA["r"], lora_alpha=LORA["alpha"], lora_dropout=0.0,
        bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"])
    model = prepare_model_for_kbit_training(
        model, use_gradient_checkpointing=True)
    model = get_peft_model(model, peft_cfg)
    n_cast = 0
    for _p in model.parameters():
        if _p.dtype == torch.float32:
            _p.data = _p.data.to(torch.bfloat16)
            n_cast += 1
    print(f"[t2_grpo] fp32 params collapsed to bf16: {n_cast}", flush=True)
    # Attempt 6 (eng #24; v5 receipt e75e2ae6: 686 fp32 params collapsed,
    # SAME lm_head seam => the Float input is an ACTIVATION upcast inside
    # TRL's forward path (logprob pass / autocast-off generation), not a
    # parameter dtype). Break the wall AT the seam: a forward pre-hook on
    # lm_head casts any floating-point input to the weight dtype before the
    # matmul (.to() is autograd-safe) — works wherever the upcast
    # originates, including code paths we don't control.
    _lm = model.get_output_embeddings()

    def _cast_to_weight_dtype(mod, inputs):
        wd = mod.weight.dtype
        return tuple(
            x.to(wd) if torch.is_tensor(x) and x.is_floating_point()
            and x.dtype != wd else x
            for x in inputs)

    _lm.register_forward_pre_hook(_cast_to_weight_dtype)
    print(f"[t2_grpo] lm_head pre-hook armed: activations -> "
          f"{_lm.weight.dtype}", flush=True)

    problems = load_split("train")
    problems_by_id = {p["id"]: p for p in problems}
    if args.reward == "partial":
        # Fail-closed (adversarial-review finding): a zero-assert problem in
        # partial mode would silently score extracted code at the floor and
        # void the asserts_total counter invariant. w1 MBPP rows always carry
        # asserts; if that ever changes, refuse the launch instead.
        empty = [p["id"] for p in problems if not p["tests"]]
        if empty:
            raise SystemExit(
                f"--reward partial requires asserts on every problem; "
                f"empty tests for ids {empty[:10]}")
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
        reward_funcs=[make_reward_fn(problems_by_id, counter,
                                     mode=args.reward)],
        args=config,  # model pre-wrapped: TRL must skip its own kbit prep
        train_dataset=Dataset.from_list(rows),
        callbacks=[_Headroom()])
    t0 = time.time()
    trainer.train()
    secs = round(time.time() - t0, 1)
    trainer.save_model(out_dir)  # PEFT adapter
    tok.save_pretrained(out_dir)

    rewards = [h["reward"] for h in trainer.state.log_history
               if "reward" in h]
    from receipt_fp import args_fingerprint  # eng #10
    # args_fp note: adding --reward shifts fingerprints for ALL runs vs
    # pre-eng-15 receipts (vars(args) gained a key). The invariant "same fp
    # == byte-identical args" still holds; cross-version joins pin tags,
    # not fingerprints.
    receipt = {
        "ticket": "NC0-T2-GRPO", "ts": ts, "args": vars(args),
        "args_fp": args_fingerprint(vars(args)),
        "governor": governor_block,
        "world": "mbpp", "round": 1, "reward_mode": args.reward,
        "prompt_rows": len(rows),
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
    # partial-credit variant (eng #15): same extremes, dense middle,
    # R_RUNNABLE floor preserved
    assert shaped_reward_partial(None, 1.0) == R_NONE
    assert shaped_reward_partial("def f(): pass", 0.0) == R_RUNNABLE
    assert shaped_reward_partial("def f(): pass", 1.0) == R_VERIFIED
    assert shaped_reward_partial("def f(): pass", 2 / 3) == 2 / 3
    assert shaped_reward_partial("def f(): pass", 0.01) == R_RUNNABLE
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
