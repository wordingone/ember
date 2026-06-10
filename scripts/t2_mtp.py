"""t2_mtp.py — W-code MTP-aux SFT arm (eng #4; contract row 9, arm C).

Pre-registration (binding before first launch):
- SAME dataset as arm A (world-filtered mbpp:* ledger view, bits-weighted
  caps from eng #5, 294 examples) and same LoRA recipe/steps — the ONLY
  delta vs arm A is the auxiliary multi-token-prediction loss, so the arm
  comparison isolates the MTP effect at matched budget.
- MTP-as-auxiliary-objective (bottleneck-conversion doc, MTP re-open):
  at each position t, besides the standard next-token CE, predict tokens
  t+1+d for d=1..K_AUX through small trainable projections
  Linear(hidden,hidden,bias=False) feeding the FROZEN shared lm_head
  (DeepSeek-V3-style shared unembedding, depth-local projection only).
  loss = lm_loss + LAMBDA * mean_d(aux_ce_d). Aux heads are SCAFFOLD:
  saved beside the adapter for forensics but UNUSED at inference — the
  bet is densified training signal per episode (more supervision bits
  per verified program), not a new decode path.
- Defaults: K_AUX=3 aux depths, LAMBDA=0.3.
- Eval surface identical to arms A/B: G1 = w1_mbpp --split validation
  base vs arm-A vs MTP-arm vs control; t5 harm gate on the adapter.

Governor: same preconditions as train_lora + step throttle. Runtime API
risk: unsloth's patched forward must honor output_hidden_states=True
(use_cache disabled under gradient checkpointing); first launch is the
integration test — receipt or traceback decides.

Receipt: receipts/t2-r1w-q3-mtp-<ts>.json with per-component loss
trajectory (lm vs aux per depth).

Selftest (`--selftest`, Windows-safe, no torch): the label-shift indexing
that aligns aux depth d with target token t+1+d.
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
RECEIPTS = f"{NC}/receipts"
VIEWS = f"{NC}/ledger/views"
K_AUX = 3
LAMBDA = 0.3
IGNORE = -100


def shift_for_depth(labels, d, ignore=IGNORE):
    """Reference semantics for aux depth d (pure-python on lists).

    HF computes main CE as logits[t] vs labels[t+1] via its internal
    1-shift. Aux depth d predicts token t+1+d from position t, so the
    aux labels are the main labels shifted left by d more, right-padded
    with ignore. Torch runtime mirrors this exactly.
    """
    return labels[d:] + [ignore] * d


def _selftest():
    lab = [10, 11, 12, 13, 14]
    assert shift_for_depth(lab, 1) == [11, 12, 13, 14, IGNORE]
    assert shift_for_depth(lab, 3) == [13, 14, IGNORE, IGNORE, IGNORE]
    # masked positions stay masked wherever they land
    lab2 = [IGNORE, 11, 12, IGNORE, 14]
    assert shift_for_depth(lab2, 2) == [12, IGNORE, 14, IGNORE, IGNORE]
    # depth 0 would be the main loss itself — identity
    assert shift_for_depth(lab, 0) == lab
    print("T2_MTP_SELFTEST_PASS")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen2.5-Coder-3B-Instruct")
    ap.add_argument("--tag", default="r1w-q3-mtp")
    ap.add_argument("--k-aux", type=int, default=K_AUX)
    ap.add_argument("--lam", type=float, default=LAMBDA)
    args, _unknown = ap.parse_known_args()  # daemon appends args

    import sys
    sys.path.insert(0, f"{NC}/scripts")
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    frac = float(os.environ.get("EMBER_VRAM_FRACTION", "0.85"))
    torch.cuda.set_per_process_memory_fraction(frac)
    free, total = torch.cuda.mem_get_info()
    margin_gb = float(os.environ.get("EMBER_VRAM_MARGIN_GB", "4.0"))
    if free < margin_gb * 1e9:
        raise SystemExit(f"VRAM-PREFLIGHT: {free/1e9:.1f}GB free — refusing")

    from unsloth import FastLanguageModel
    from trl import SFTTrainer
    from transformers import TrainingArguments, TrainerCallback
    from datasets import Dataset
    from huggingface_hub import snapshot_download
    from frontier import caps_from_records
    from t2_round import ADAPTERS, LORA, build_dataset
    from t2_wcode import write_view

    class _Headroom(TrainerCallback):
        def on_step_end(self, targs, state, control, **kw):
            time.sleep(float(os.environ.get("EMBER_THROTTLE_S", "0.3")))

    # identical dataset to arm A — the arm delta is the aux loss only
    arm_recs = write_view(f"{NC}/ledger/episodes.jsonl",
                          f"{VIEWS}/wcode-r1.jsonl")
    caps = caps_from_records(arm_recs)
    examples, counts = build_dataset(f"{VIEWS}/wcode-r1.jsonl", cap=caps)
    if not examples:
        raise SystemExit("t2_mtp: empty dataset — ingest first")

    try:
        model_path = snapshot_download(args.model, local_files_only=True)
    except Exception:  # noqa: BLE001
        model_path = args.model
    model, tok = FastLanguageModel.from_pretrained(
        model_name=model_path, max_seq_length=LORA["max_seq"],
        dtype=torch.bfloat16, load_in_4bit=True)
    model = FastLanguageModel.get_peft_model(
        model, r=LORA["r"], lora_alpha=LORA["alpha"],
        lora_dropout=LORA["dropout"], bias="none",
        use_gradient_checkpointing="unsloth", random_state=3407,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"])

    hidden = model.config.hidden_size
    aux_heads = nn.ModuleList(
        [nn.Linear(hidden, hidden, bias=False) for _ in range(args.k_aux)]
    ).to("cuda", dtype=torch.bfloat16)
    for h in aux_heads:
        nn.init.zeros_(h.weight)  # start as no-op signal, grow from data
    model.mtp_aux_heads = aux_heads  # registered -> optimizer picks them up
    lm_head = model.get_output_embeddings()
    loss_log = {"lm": [], "aux": []}

    class MTPTrainer(SFTTrainer):
        def compute_loss(self, mdl, inputs, return_outputs=False,
                         **kwargs):
            labels = inputs["labels"]
            out = mdl(input_ids=inputs["input_ids"],
                      attention_mask=inputs.get("attention_mask"),
                      labels=labels, output_hidden_states=True,
                      use_cache=False)
            lm_loss = out.loss
            # unsloth emits hidden_states in float32; aux heads + lm_head
            # are bf16 (integration-test fix 474440aa: mat1 float vs bf16)
            h = out.hidden_states[-1].to(aux_heads[0].weight.dtype)
            aux_losses = []
            for d, head in enumerate(aux_heads, start=1):
                logits_d = lm_head(head(h))
                # main CE pairs logits[t] with labels[t+1] (internal HF
                # 1-shift); depth d pairs logits[t] with labels[t+1+d] ->
                # shift labels left by d more (shift_for_depth semantics)
                tgt = torch.full_like(labels, IGNORE)
                tgt[:, :-d] = labels[:, d:]
                aux_losses.append(F.cross_entropy(
                    logits_d[:, :-1].reshape(-1, logits_d.size(-1)).float(),
                    tgt[:, 1:].reshape(-1), ignore_index=IGNORE))
            aux = torch.stack(aux_losses).mean()
            loss_log["lm"].append(round(float(lm_loss.detach()), 4))
            loss_log["aux"].append(round(float(aux.detach()), 4))
            loss = lm_loss + args.lam * aux
            return (loss, out) if return_outputs else loss

    texts = [tok.apply_chat_template(e["messages"], tokenize=False)
             for e in examples]
    ds = Dataset.from_list([{"text": t} for t in texts])
    out_dir = f"{ADAPTERS}/{args.tag}"
    trainer = MTPTrainer(
        model=model, tokenizer=tok, train_dataset=ds,
        dataset_text_field="text", max_seq_length=LORA["max_seq"],
        dataset_num_proc=4, callbacks=[_Headroom()],
        args=TrainingArguments(
            output_dir=out_dir + "-ckpt", per_device_train_batch_size=1,
            gradient_accumulation_steps=16, num_train_epochs=LORA["epochs"],
            learning_rate=LORA["lr"], lr_scheduler_type="cosine",
            warmup_ratio=0.03, logging_steps=1, save_strategy="no",
            bf16=True, optim="adamw_8bit", seed=3407, report_to="none"))
    t0 = time.time()
    res = trainer.train()
    secs = round(time.time() - t0, 1)
    model.save_pretrained(out_dir)
    tok.save_pretrained(out_dir)
    torch.save(aux_heads.state_dict(), f"{out_dir}/mtp_aux_heads.pt")

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = {
        "ticket": "NC0-T2-MTP", "ts": ts, "args": vars(args),
        "world": "mbpp", "round": 1,
        "dataset": {"n_examples": len(examples), "n_tasks": len(counts),
                    "identical_to_arm_A": True},
        "train_loss": round(res.training_loss, 4),
        "lm_loss_first5": loss_log["lm"][:5],
        "lm_loss_last5": loss_log["lm"][-5:],
        "aux_loss_first5": loss_log["aux"][:5],
        "aux_loss_last5": loss_log["aux"][-5:],
        "train_secs": secs, "adapter": out_dir,
        "aux_heads_file": "mtp_aux_heads.pt (scaffold — unused at inference)",
    }
    os.makedirs(RECEIPTS, exist_ok=True)
    with open(f"{RECEIPTS}/t2-{args.tag}-{ts}.json", "w") as f:
        json.dump(receipt, f, indent=2)
    print(json.dumps(receipt, indent=2, default=str))
    print("T2_MTP_DONE")


if __name__ == "__main__":
    import sys as _sys
    if "--selftest" in _sys.argv:
        _selftest()
    else:
        main()
