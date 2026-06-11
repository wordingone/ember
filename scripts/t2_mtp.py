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
import hashlib
import json
import os
import time
from datetime import datetime, timezone

from receipt_write import checked_write

NC = "/mnt/b/M/avir/leo/state/nc-ladder"
RECEIPTS = f"{NC}/receipts"
VIEWS = f"{NC}/ledger/views"
K_AUX = 3
LAMBDA = 0.3
IGNORE = -100

SHA_CONVENTION = ("sha256 over on-disk raw bytes "
                  "(binary read, no line-ending normalization)")


def load_view_records(path):
    """Load ledger records from an explicit view file (eng #140).

    Pure JSONL reader — no regeneration, no ledger access. Used when the
    caller (e.g. the round-2 wrapper) installs a pre-filtered view and the
    arm must train on exactly that set."""
    records = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    if not records:
        raise SystemExit(f"t2_mtp: --view-path {path} is empty — refusing")
    return records


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


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
    # eng #140 (Kai r2 audit): the round-2 wrapper installed its filtered
    # view at wcode-r1.jsonl, but this script regenerated that file from the
    # full ledger before building — the filtered set never reached training.
    # --view-path makes the caller's view explicit and load-bearing.
    # args_fp note: these new keys shift fingerprints for ALL runs vs
    # pre-#140 receipts (same acknowledged class as eng #26/#70);
    # comparisons pin tags, not fingerprints.
    ap.add_argument("--view-path", default=None,
                    help="explicit view file to train on (no regeneration); "
                         "default None = legacy behavior (regenerate "
                         "wcode-r1.jsonl from the ledger)")
    ap.add_argument("--round", type=int, default=1,
                    help="round number recorded in the receipt")
    ap.add_argument("--wrapper-receipt", default=None,
                    help="path of the dispatching wrapper's receipt, "
                         "recorded for linkage")
    ap.add_argument("--gate-token-present", action="store_true",
                    help="set by the round-2 wrapper after its interlock")
    ap.add_argument("--license-allow", default=None,
                    help="license allow-list (ledger_license.parse_allow "
                         "format) passed to build_dataset — set by the r2 "
                         "wrapper to mirror the sft arm's build exactly")
    ap.add_argument("--sft-receipt", default=None,
                    help="path of the certified sft arm receipt; with "
                         "--expected-view-sha256, identity with the sft arm "
                         "is ASSERTED fail-closed (rows + n_examples cross-"
                         "checked against this receipt) and claimed true")
    ap.add_argument("--expected-view-sha256", default=None,
                    help="the dispatcher's sha pin of the view file; the "
                         "build-time hash must match or we refuse (catches "
                         "mutation between dispatch and training start)")
    args, _unknown = ap.parse_known_args()  # daemon appends args
    if (args.sft_receipt or args.expected_view_sha256) and not args.view_path:
        raise SystemExit(
            "t2_mtp: --sft-receipt/--expected-view-sha256 declare an "
            "identity intent only --view-path can honor; the legacy path "
            "regenerates from the ledger. Refusing.")

    import sys
    sys.path.insert(0, f"{NC}/scripts")
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    # Resource governor — canonical copy in governor.py since eng #14
    # (cap + margin assert before load; per-step throttle via callback).
    from governor import make_headroom_callback, preflight
    governor_block = preflight()

    from unsloth import FastLanguageModel
    from trl import SFTTrainer
    from transformers import TrainingArguments
    from datasets import Dataset
    from huggingface_hub import snapshot_download
    from frontier import caps_from_records
    from t2_round import ADAPTERS, LORA, build_dataset
    from t2_wcode import write_view

    # eng #11: same ext-clean quarantine at build as t2_wcode.
    # eng #140 (gate rework, option b): with --view-path the caller's view
    # is load-bearing AND already clean — the installer (sft arm or wrapper
    # pinning the sft view) ran ext_clean before writing it. Here ext_clean
    # is a fail-closed GUARD only: if it would drop rows, the pinned view
    # no longer matches the quarantine state and we refuse rather than
    # silently train on a different dataset than the pinned sha. The view
    # file is never rewritten in this mode. Build mirrors t2_r2w's sft
    # shape exactly: flat default cap + license_allow (NOT
    # caps_from_records — that was the residual build-shape delta).
    # Legacy path (no --view-path) keeps the round-1 behavior unchanged:
    # regenerate from the ledger, ext-clean in place, caps_from_records
    # (identical dataset to arm A — the arm delta is the aux loss).
    from frontier import ext_clean, load_ext_flags
    from ledger_license import parse_allow
    allow = parse_allow(args.license_allow) if args.license_allow else None
    sft_anchor = None
    if args.view_path:
        view_path = args.view_path
        arm_recs = load_view_records(view_path)
        n_pre_ext = len(arm_recs)
        cleaned = ext_clean(arm_recs,
                            load_ext_flags([f"{RECEIPTS}/v-ext-flags-*.jsonl"]))
        if len(cleaned) != n_pre_ext:
            raise SystemExit(
                f"t2_mtp: ext-clean guard — caller view {view_path} contains "
                f"{n_pre_ext - len(cleaned)} quarantined row(s); the pinned "
                "view must be ext-clean at install time. Refusing to train "
                "on a dataset that differs from the pinned sha.")
        arm_recs = cleaned
        view_sha = file_sha256(view_path)
        if (args.expected_view_sha256
                and view_sha != args.expected_view_sha256):
            raise SystemExit(
                f"t2_mtp: view sha mismatch — {view_path} hashes to "
                f"{view_sha} at build time but the dispatcher pinned "
                f"{args.expected_view_sha256}. The file changed between "
                "dispatch and training start. Refusing.")
        if args.sft_receipt:
            with open(args.sft_receipt, encoding="utf-8") as sf:
                sft_rec = json.load(sf)
            ff = sft_rec.get("frontier_filter", {})
            sft_anchor = {
                "receipt": args.sft_receipt,
                "tag": sft_rec.get("tag"),
                "view_rows_after_theta": ff.get("view_rows_after_theta"),
                "dataset_examples": ff.get("dataset_examples"),
            }
            if len(arm_recs) != sft_anchor["view_rows_after_theta"]:
                raise SystemExit(
                    f"t2_mtp: identity assert failed — view has "
                    f"{len(arm_recs)} rows but the sft receipt certified "
                    f"{sft_anchor['view_rows_after_theta']} "
                    f"(view_rows_after_theta, {args.sft_receipt}). Refusing.")
        examples, counts = build_dataset(view_path, license_allow=allow)
        if (sft_anchor
                and len(examples) != sft_anchor["dataset_examples"]):
            raise SystemExit(
                f"t2_mtp: identity assert failed — build produced "
                f"{len(examples)} examples but the sft receipt certified "
                f"{sft_anchor['dataset_examples']} (dataset_examples). "
                "Same view + same build shape must give the same dataset; "
                "check --license-allow matches the sft run. Refusing.")
        build_shape = "sft-mirror: flat default cap + license_allow"
    else:
        view_path = f"{VIEWS}/wcode-r1.jsonl"
        arm_recs = write_view(f"{NC}/ledger/episodes.jsonl", view_path)
        n_pre_ext = len(arm_recs)
        arm_recs = ext_clean(arm_recs,
                             load_ext_flags([f"{RECEIPTS}/v-ext-flags-*.jsonl"]))
        with open(view_path, "w", encoding="utf-8", newline="\n") as vf:
            for r in arm_recs:
                vf.write(json.dumps(r) + "\n")
        caps = caps_from_records(arm_recs)
        examples, counts = build_dataset(view_path, cap=caps,
                                         license_allow=allow)
        build_shape = "legacy round-1: caps_from_records per-task caps"
        view_sha = file_sha256(view_path)
    if not examples:
        raise SystemExit("t2_mtp: empty dataset — ingest first")
    view_block = {
        "path": view_path,
        "source": ("explicit --view-path (caller-installed view, "
                   "no regeneration, no rewrite; ext-clean guard passed)")
                  if args.view_path
                  else "regenerated from ledger (legacy round-1 path)",
        "rows_pre_ext_clean": n_pre_ext,
        "rows_built": len(arm_recs),
        "ext_clean_dropped": n_pre_ext - len(arm_recs),
        "build_shape": build_shape,
        "license_allow": args.license_allow,
        "sha256": view_sha,
    }

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
        dataset_num_proc=4, callbacks=[make_headroom_callback()],
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
    from receipt_fp import args_fingerprint  # eng #10
    # eng #140: dataset-identity is a NAMED claim with a basis, never an
    # unconditional literal. Legacy path = by-construction identical to
    # arm A (same write_view -> ext_clean -> caps build). View-path with
    # BOTH identity anchors (--sft-receipt + --expected-view-sha256):
    # claim TRUE — the asserts above already failed closed unless the
    # build-time hash matched the dispatch pin and rows/n_examples matched
    # the certified sft receipt. View-path without anchors: honest False
    # (generic caller view, no named arm to claim against).
    if args.view_path and sft_anchor and args.expected_view_sha256:
        identity_claim = {
            "claim": True,
            "arm": sft_anchor["tag"] or "r2 sft arm (t2_r2w)",
            "basis": ("sha-pinned to sft arm view wcode-r2-sft.jsonl: "
                      "build-time training_view_sha256 == dispatcher pin; "
                      "view rows == sft receipt view_rows_after_theta; "
                      "n_examples == sft receipt dataset_examples — all "
                      "asserted fail-closed before training"),
            "training_view_sha256": view_sha,
            "expected_view_sha256": args.expected_view_sha256,
            "sft_receipt": sft_anchor["receipt"],
            "sft_view_rows_after_theta":
                sft_anchor["view_rows_after_theta"],
            "sft_dataset_examples": sft_anchor["dataset_examples"],
        }
    elif args.view_path:
        identity_claim = {
            "claim": False,
            "basis": ("explicit --view-path without identity anchors "
                      "(--sft-receipt + --expected-view-sha256): dataset "
                      "is the caller-installed view consumed as-is "
                      "(ext-clean guard, no rewrite), sft build shape; "
                      "no named-arm identity asserted"),
        }
    else:
        identity_claim = {
            "claim": True, "arm": "A (t2_wcode r1w)",
            "basis": ("by-construction: same "
                      "write_view(ledger)->ext_clean->caps_from_records->"
                      "build_dataset path as arm A"),
        }
    receipt = {
        "ticket": "NC0-T2-MTP", "ts": ts, "args": vars(args),
        "args_fp": args_fingerprint(vars(args)),
        "world": "mbpp", "round": args.round,
        "sha_convention": SHA_CONVENTION,
        "gate_token_present": args.gate_token_present,
        "wrapper_receipt": args.wrapper_receipt,
        "governor": governor_block,
        "view": view_block,
        "dataset": {"n_examples": len(examples), "n_tasks": len(counts),
                    "identity_claim": identity_claim},
        "train_loss": round(res.training_loss, 4),
        "lm_loss_first5": loss_log["lm"][:5],
        "lm_loss_last5": loss_log["lm"][-5:],
        "aux_loss_first5": loss_log["aux"][:5],
        "aux_loss_last5": loss_log["aux"][-5:],
        "train_secs": secs, "adapter": out_dir,
        "aux_heads_file": "mtp_aux_heads.pt (scaffold — unused at inference)",
    }
    os.makedirs(RECEIPTS, exist_ok=True)
    checked_write(f"{RECEIPTS}/t2-{args.tag}-{ts}.json", receipt)
    print(json.dumps(receipt, indent=2, default=str))
    print("T2_MTP_DONE")


if __name__ == "__main__":
    import sys as _sys
    if "--selftest" in _sys.argv:
        _selftest()
    else:
        main()
