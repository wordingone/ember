#!/usr/bin/env python3
# goal_id: EMBER-02
# workstream_id: EMBER-02A
# next_executed_outcome: EMBER-02 first sufficiently pretrained clean-genesis 3B Ember
"""
Accumulation Law Experiment -- four-arm continual self-improvement loop.

Research question:
  Does verified-experience accumulation compound into capability across many
  rounds WITHOUT catastrophic forgetting or stagnation?

Arms:
  A -- Pareto-ratchet + endogenous curriculum (candidate law)
  B -- Naive accumulation (no gate, no retained-battery check)
  C -- Frozen base (no updates, stagnation control)
  D -- Grounding-off (unverified self-generated experience)

Design decisions (concrete, no open items):
  - TIERS: 3 tiers by problem-text length (T0 <=68 chars, T1 68-86, T2 >86).
    Length is a reliable proxy for MBPP difficulty: short prompts = simpler tasks.
    Tier advance when pass@1 on current-tier held-out clears ADVANCE_THRESHOLD.
  - RETAINED BATTERY: pass@1 on held-out problems from all EARLIER tiers.
    One axis per tier: if on T1, axis-0 = T0 held-out pass@1; if on T2, axes 0+1.
    Battery is live -- evaluated every round.
  - eps = 0.05 (5 pp absolute): if any retained-battery axis drops > eps from its
    reference value (the value when that tier was first acquired), gate REJECTS.
  - FRONTIER GAIN THRESHOLD = 0.01 (1 pp): gate requires this minimum gain to
    click forward (prevents noisy acceptance of flat rounds).
  - LoRA config: rank=4/alpha=8 (smoke/CPU), rank=16/alpha=32 (GPU).
  - max_steps: 5 (smoke), 100 (GPU).
  - N_ROUNDS: 3 (smoke/mock), 8 (GPU).
  - N_CANDIDATES per round: 5/tier (smoke), 50/tier (GPU).
  - HELD_OUT per tier: 4 (smoke), 60 (GPU).
  - HELD_OUT_SEED: 42 (frozen, never reused).

Capacity hook (pluggable, arm E / growth support):
  --capacity_fn module:function  (default: identity -- no-op)
  Called between rounds: model = capacity_fn(model, tokenizer, round_idx, tier)
  Must return a model with the same weight names on the same device.
  Arm E (growth law) inserts a function-preserving width/depth expansion here.

JAM detection:
  If arm A gate rejects for JAM_WINDOW consecutive rounds, emit jam_detected=True
  in the receipt. This is the growth trigger signal for a future arm E.
  Reports a relaxed-ratchet secondary result (arm A' = accept on positive net
  held-out value even with bounded forgetting).

Modes:
  --mode mock   Synthetic trajectories, instant gate/curriculum/verdict logic proof
  --mode smoke  Tiny data, CPU, real model (validates end-to-end code path)
  --mode gpu    Full run, GPU required, reads EMBER_VRAM_FRACTION env var

Lineage isolation: zero internal project terms; public research language only.

Usage:
  python run_accumulation.py --mode mock
  python run_accumulation.py --mode smoke
  python run_accumulation.py --mode gpu --rounds 8
"""

# -- stdlib --------------------------------------------------------------------
import argparse
import copy
import importlib
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

# -- Governance constants ------------------------------------------------------
# Fractional VRAM cap for GPU mode.  Set lower or override via env.
EMBER_VRAM_FRACTION = float(os.environ.get("EMBER_VRAM_FRACTION", "0.80"))
assert EMBER_VRAM_FRACTION <= 0.80, (
    f"EMBER_VRAM_FRACTION={EMBER_VRAM_FRACTION} exceeds 0.80 -- governance violated"
)

# -- Mode-dependent constants --------------------------------------------------
# These get overridden per mode in main(); kept here for documentation.
N_ROUNDS          = 8         # GPU
N_CANDIDATES      = 50        # per round per active tier (GPU)
HELD_OUT_PER_TIER = 60        # problems held out per tier (GPU)
MAX_FINETUNE_STEPS = 100      # cap per round (GPU)
LORA_RANK         = 16        # GPU
LORA_ALPHA        = 32        # GPU

# -- Fixed experiment constants ------------------------------------------------
MODEL_ID          = "Qwen/Qwen2.5-0.5B-Instruct"
HELD_OUT_SEED     = 42        # frozen; never reused
VERIFY_TIMEOUT    = 5         # seconds per subprocess exec
MAX_NEW_TOKENS    = 256
GENERATION_TEMP   = 0.8
EVAL_TEMP         = 0.0

# Tier thresholds (text length in chars; proxy for MBPP difficulty)
TIER_BOUNDS       = (68, 86)  # T0 <=68, T1 68-86, T2 >86

# Gate thresholds
EPSILON           = 0.05      # retained-battery tolerance (5 pp absolute)
ADVANCE_THRESHOLD = 0.25      # curriculum advances when tier held-out >= this
FRONTIER_GAIN_MIN = 0.01      # minimum gain to click the Pareto ratchet

# JAM detection
# v4 calibration (2026-06-29): lowered from 3 to 2 after smoke v3 confirmed ARM G
# never grew in 8 rounds (JAM_WINDOW=3 — counter hit 2 consecutive rejects then reset
# at R6 on a frontier-0.217 spike, preventing JAM; with JAM_WINDOW=2, R4+R5 would
# have fired JAM and triggered growth before R6).
JAM_WINDOW        = 2         # consecutive rejected rounds = jam

# -- Paths ---------------------------------------------------------------------
SCRIPT_DIR  = Path(__file__).parent
RECEIPT_PATH = SCRIPT_DIR / "receipts" / "accumulation_law.jsonl"
CHECKPOINT_DIR = SCRIPT_DIR / "checkpoints"
DATA_DIR    = SCRIPT_DIR / "data"

# -- Verifier ------------------------------------------------------------------

def _strip_code_fences(text: str) -> str:
    """Strip markdown code fences from model output.

    Many instruction-tuned models emit ```python ... ``` regardless of system
    prompt.  Strip leading/trailing fence delimiters so the code is plain
    Python before we write it into a test script.
    """
    import re
    # Remove leading ```python or ``` fence
    text = re.sub(r"^\s*```(?:python)?\s*\n?", "", text)
    # Remove trailing ``` fence
    text = re.sub(r"\n?\s*```\s*$", "", text)
    return text.strip()


def _make_test_script(generated_code: str, test_list: list[str],
                      test_setup_code: str = "") -> str:
    """Wrap generated function code and test assertions into a runnable script."""
    setup = test_setup_code.strip() + "\n" if test_setup_code.strip() else ""
    assertions = "\n".join(f"    {t}" for t in test_list if t.strip())
    return f"""{setup}{generated_code}

def _run_tests():
{assertions}

_run_tests()
print("PASS")
"""


def execution_verify(generated_code: str, test_list: list[str],
                     test_setup_code: str = "") -> bool:
    """
    Return True iff generated_code passes all test assertions under Python interpreter.
    Verifier is the interpreter -- not the model.  Ungameable.
    """
    if not test_list:
        return False
    script = _make_test_script(generated_code, test_list, test_setup_code)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py",
                                     delete=False, encoding="utf-8") as f:
        f.write(script)
        tmppath = f.name
    try:
        result = subprocess.run(
            [sys.executable, tmppath],
            capture_output=True, text=True, timeout=VERIFY_TIMEOUT
        )
        return result.returncode == 0 and "PASS" in result.stdout
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return False
    finally:
        try:
            os.unlink(tmppath)
        except OSError:
            pass


# -- Data loading and tier partition ------------------------------------------

def assign_tier(text: str) -> int:
    n = len(text)
    if n <= TIER_BOUNDS[0]:
        return 0
    if n <= TIER_BOUNDS[1]:
        return 1
    return 2


_CUSTOM_CLASS_RE = re.compile(r'\b[A-Z][a-zA-Z]+\(')


def _is_clean_problem(p: dict) -> bool:
    """Filter out problems whose test_list uses custom CamelCase constructors."""
    for t in p.get("test_list", []):
        if _CUSTOM_CLASS_RE.search(t):
            return False
    return True


def load_and_partition(n_held_out_per_tier: int, n_train_per_tier: int,
                       seed: int = HELD_OUT_SEED) -> tuple[dict, dict, dict]:
    """
    Returns (train_pools, held_out_sets, baseline_info).
    train_pools[tier]  = list of problems for candidate generation
    held_out_sets[tier] = list of held-out problems (frozen eval)
    baseline_info      = metadata dict
    """
    from datasets import load_dataset
    mbpp = load_dataset("mbpp")

    rng = random.Random(seed)

    # Clean-filter
    clean_train = [p for p in mbpp["train"] if _is_clean_problem(p)]
    clean_test  = [p for p in mbpp["test"]  if _is_clean_problem(p)]

    # Check overlap by text content (contamination guard)
    train_texts = {p["text"] for p in clean_train}
    test_texts  = {p["text"] for p in clean_test}
    overlap_rate = len(train_texts & test_texts) / max(len(test_texts), 1)
    assert overlap_rate < 0.10, (
        f"Contamination: {overlap_rate:.1%} of held-out problems overlap training pool"
    )

    # Tier-partition
    train_by_tier: dict[int, list] = {0: [], 1: [], 2: []}
    for p in clean_train:
        train_by_tier[assign_tier(p["text"])].append(p)

    test_by_tier: dict[int, list] = {0: [], 1: [], 2: []}
    for p in clean_test:
        test_by_tier[assign_tier(p["text"])].append(p)

    # Shuffle (seed-stable) and cap
    train_pools: dict[int, list] = {}
    held_out_sets: dict[int, list] = {}
    for tier in range(3):
        tpool = list(train_by_tier[tier])
        rng.shuffle(tpool)
        train_pools[tier] = tpool[:n_train_per_tier]

        ttest = list(test_by_tier[tier])
        rng.shuffle(ttest)
        held_out_sets[tier] = ttest[:n_held_out_per_tier]

    baseline_info = {
        "clean_train_total": len(clean_train),
        "clean_test_total": len(clean_test),
        "overlap_rate": round(overlap_rate, 4),
        "tier_sizes": {
            t: {"train_pool": len(train_pools[t]),
                "held_out": len(held_out_sets[t])}
            for t in range(3)
        },
    }
    return train_pools, held_out_sets, baseline_info


# -- Model loading (GPU and CPU) -----------------------------------------------

def load_model_and_tokenizer(device: str, lora_rank: int, lora_alpha: int,
                              dtype_str: str = "auto"):
    """
    Load base model + tokenizer + LoRA adapter.
    Returns (model, tokenizer).
    capacity_fn can swap out model between rounds -- see capacity_step().
    """
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    from peft import LoraConfig, get_peft_model, TaskType

    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, padding_side="left")
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    if dtype_str == "auto":
        dtype = torch.bfloat16 if device.startswith("cuda") else torch.float32
    else:
        dtype = getattr(torch, dtype_str)

    if device.startswith("cuda"):
        torch.cuda.set_per_process_memory_fraction(EMBER_VRAM_FRACTION, device=0)
        device_map = "cuda:0"
    else:
        device_map = "cpu"

    base = AutoModelForCausalLM.from_pretrained(
        MODEL_ID, torch_dtype=dtype, device_map=device_map,
        low_cpu_mem_usage=True,
    )

    lora_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=lora_rank,
        lora_alpha=lora_alpha,
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        bias="none",
    )
    model = get_peft_model(base, lora_config)
    model.print_trainable_parameters()
    return model, tokenizer


# -- Capacity hook (pluggable for arm E / growth) ------------------------------

def identity_capacity(model, tokenizer, round_idx: int, tier: int):
    """
    Default capacity step: identity, returns model unchanged.
    Arm E (growth law) replaces this with a function-preserving
    width/depth expansion (Net2Net or similar).
    Signature contract:
      model, tokenizer = capacity_fn(model, tokenizer, round_idx, tier)
    """
    return model, tokenizer


def load_capacity_fn(spec: str | None):
    """Parse 'module:function' and return the callable."""
    if not spec:
        return identity_capacity
    parts = spec.split(":")
    if len(parts) != 2:
        raise ValueError(f"--capacity_fn must be 'module:function', got {spec!r}")
    mod = importlib.import_module(parts[0])
    return getattr(mod, parts[1])


# -- Adapter state management (for Pareto rollback) ---------------------------

def save_adapter_state(model) -> dict:
    """Deep-copy LoRA adapter weights for potential rollback."""
    state = {}
    for name, param in model.named_parameters():
        if "lora_" in name:
            state[name] = param.data.clone()
    return state


def restore_adapter_state(model, state: dict):
    """Restore LoRA adapter weights from a saved state (rollback)."""
    with __import__("torch").no_grad():
        for name, param in model.named_parameters():
            if name in state:
                param.data.copy_(state[name])


# -- Generation ----------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are a Python programming assistant. "
    "Complete the function body for the given specification. "
    "Output ONLY the complete Python function (no markdown fences, no explanation)."
)


def _extract_func_name(problem: dict) -> str:
    """Extract the expected function name from the first test assertion.

    MBPP tests look like: ``assert func_name(args) == expected``
    Returns the function name if extractable, else empty string.
    """
    import re
    for t in problem.get("test_list", []):
        m = re.match(r"assert\s+(\w+)\s*\(", t.strip())
        if m:
            return m.group(1)
    return ""


def _build_prompt(problem: dict, tokenizer) -> str:
    spec = problem.get("text", problem.get("prompt", ""))
    func_name = _extract_func_name(problem)
    if func_name:
        user_content = (
            f"Write a Python function named `{func_name}` for this task:\n\n{spec}"
        )
    else:
        user_content = f"Write a Python function for this task:\n\n{spec}"
    return tokenizer.apply_chat_template(
        [{"role": "system", "content": SYSTEM_PROMPT},
         {"role": "user", "content": user_content}],
        tokenize=False, add_generation_prompt=True,
    )


def generate_candidates(model, tokenizer, problems: list[dict],
                        device: str) -> list[dict]:
    """Generate one candidate solution per problem."""
    import torch
    model.eval()
    candidates = []
    with torch.no_grad():
        for prob in problems:
            prompt = _build_prompt(prob, tokenizer)
            inputs = tokenizer(prompt, return_tensors="pt",
                               truncation=True, max_length=1024)
            inputs = {k: v.to(model.device) for k, v in inputs.items()}
            try:
                out = model.generate(
                    **inputs,
                    max_new_tokens=MAX_NEW_TOKENS,
                    temperature=GENERATION_TEMP,
                    do_sample=True,
                    pad_token_id=tokenizer.eos_token_id,
                )
                generated = _strip_code_fences(tokenizer.decode(
                    out[0][inputs["input_ids"].shape[1]:],
                    skip_special_tokens=True,
                ).strip())
            except Exception:
                generated = ""
            candidates.append({
                "problem": prob,
                "generated_code": generated,
                "test_list": prob.get("test_list", [])[:3],
                "test_setup_code": prob.get("test_setup_code", ""),
            })
    return candidates


# -- Fine-tuning ----------------------------------------------------------------

class _CodeDS(__import__("torch").utils.data.Dataset):
    def __init__(self, items: list[dict], tokenizer, max_length: int = 512):
        self.items = items
        self.tok = tokenizer
        self.max_len = max_length

    def __len__(self):
        return len(self.items)

    def __getitem__(self, idx):
        item = self.items[idx]
        prompt = _build_prompt(item["problem"], self.tok)
        full   = prompt + item["generated_code"] + self.tok.eos_token
        enc    = self.tok(full, truncation=True, max_length=self.max_len,
                          return_tensors="pt")
        ids    = enc["input_ids"][0]
        return {"input_ids": ids, "labels": ids.clone()}


def fine_tune_round(model, tokenizer, items: list[dict],
                    max_steps: int, ckpt_dir: Path,
                    device: str) -> int:
    """Fine-tune model in-place on items.  Returns actual steps trained."""
    import torch
    from transformers import Trainer, TrainingArguments, DataCollatorForLanguageModeling

    if not items:
        return 0

    ds = _CodeDS(items, tokenizer)
    steps_per_epoch = max(1, len(ds) // 4)   # eff batch=4
    actual_steps = min(steps_per_epoch, max_steps)

    use_bf16 = device.startswith("cuda")
    use_fp16 = False

    ckpt_dir.mkdir(parents=True, exist_ok=True)
    args = TrainingArguments(
        output_dir=str(ckpt_dir),
        max_steps=actual_steps,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,
        learning_rate=2e-4,
        lr_scheduler_type="cosine",
        warmup_steps=min(5, actual_steps),
        weight_decay=0.01,
        max_grad_norm=1.0,
        bf16=use_bf16,
        fp16=use_fp16,
        logging_steps=max(1, actual_steps // 2),
        save_steps=actual_steps + 1,   # don't save mid-run
        report_to="none",
        dataloader_num_workers=0,
        use_cpu=(device == "cpu"),
    )
    model.train()
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=ds,
        data_collator=DataCollatorForLanguageModeling(tokenizer, mlm=False),
    )
    trainer.train()
    if device.startswith("cuda"):
        __import__("torch").cuda.empty_cache()
    return actual_steps


# -- Evaluation ----------------------------------------------------------------

def eval_pass_at_1(model, tokenizer, problems: list[dict],
                   device: str) -> float:
    """Greedy pass@1 on a frozen problem list.  100% deterministic."""
    import torch
    if not problems:
        return 0.0
    model.eval()
    correct = 0
    with torch.no_grad():
        for prob in problems:
            prompt = _build_prompt(prob, tokenizer)
            inputs = tokenizer(prompt, return_tensors="pt",
                               truncation=True, max_length=1024)
            inputs = {k: v.to(model.device) for k, v in inputs.items()}
            try:
                out = model.generate(
                    **inputs,
                    max_new_tokens=MAX_NEW_TOKENS,
                    temperature=EVAL_TEMP,
                    do_sample=False,
                    pad_token_id=tokenizer.eos_token_id,
                )
                generated = _strip_code_fences(tokenizer.decode(
                    out[0][inputs["input_ids"].shape[1]:],
                    skip_special_tokens=True,
                ).strip())
            except Exception:
                generated = ""
            if execution_verify(generated,
                                prob.get("test_list", [])[:3],
                                prob.get("test_setup_code", "")):
                correct += 1
    return correct / len(problems)


def eval_vram_fraction(device: str) -> float:
    """Return current VRAM fraction (0 for CPU)."""
    if not device.startswith("cuda"):
        return 0.0
    import torch
    torch.cuda.synchronize()
    total = torch.cuda.get_device_properties(0).total_memory
    used  = torch.cuda.memory_reserved(0)
    frac  = used / total
    if frac > EMBER_VRAM_FRACTION:
        raise RuntimeError(
            f"VRAM governance violation: {frac:.3f} > {EMBER_VRAM_FRACTION}. "
            "Halting experiment."
        )
    return frac


# -- Receipt -------------------------------------------------------------------

def write_receipt(r: dict, path: Path = RECEIPT_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(r) + "\n")
        f.flush()
    return r


def build_receipt(
    arm: str, round_idx: int, tier: int,
    frontier_pass: float, retained: dict[int, float],
    verified_count: int, total_candidates: int,
    accepted: bool | None,       # None for arms C/B/D (no gate)
    gate_rejected: bool,
    jam_detected: bool,
    frontier_stalled: bool,
    curriculum_advanced: bool,
    finetune_steps: int,
    vram_fraction: float,
    wall_seconds: int,
    extra: dict | None = None,
) -> dict:
    r = {
        "schema_version": 2,
        "experiment":     "accumulation-law",
        "arm":            arm,
        "round":          round_idx,
        "tier":           tier,
        "frontier_pass_at_1": round(frontier_pass, 6),
        "retained_pass_at_1": {str(k): round(v, 6) for k, v in retained.items()},
        "verified_count": verified_count,
        "total_candidates": total_candidates,
        "verified_fraction": (
            round(verified_count / total_candidates, 4)
            if total_candidates > 0 else 0.0
        ),
        "low_signal": verified_count < 5,
        "accepted":  accepted,
        "gate_rejected": gate_rejected,
        "jam_detected": jam_detected,
        "frontier_stalled": frontier_stalled,
        "curriculum_advanced": curriculum_advanced,
        "finetune_steps": finetune_steps,
        "vram_fraction": round(vram_fraction, 4),
        "vram_ok": vram_fraction <= EMBER_VRAM_FRACTION,
        "round_wall_seconds": wall_seconds,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        r.update(extra)
    return r


# -- Pareto gate ---------------------------------------------------------------

class ParetoGate:
    """
    Stateful gate for arm A.
    Accepts a round's adapter iff:
      (1) frontier improved by >= FRONTIER_GAIN_MIN over prior frontier, AND
      (2) all retained-battery axes are within EPSILON of their reference values.
    On rejection: caller must restore prior adapter state.
    Tracks consecutive rejections to detect JAM.
    """
    def __init__(self, epsilon: float = EPSILON,
                 gain_min: float = FRONTIER_GAIN_MIN,
                 jam_window: int = JAM_WINDOW):
        self.epsilon    = epsilon
        self.gain_min   = gain_min
        self.jam_window = jam_window
        # Reference values: set on first acquisition of each tier
        self._frontier_ref: dict[int, float] = {}      # tier -> best frontier accepted
        self._retained_ref: dict[int, float] = {}      # tier -> pass@1 at first acquire
        self._consecutive_rejects = 0
        self._stall_rounds = 0                          # rounds with no forward progress

    def evaluate(self, tier: int, frontier: float,
                 retained: dict[int, float]) -> tuple[bool, str]:
        """
        Returns (accept: bool, reason: str).
        retained = {tier_idx: pass@1} for all earlier tiers.
        """
        prior_frontier = self._frontier_ref.get(tier, -1.0)

        # Condition 1: frontier must improve
        if frontier - prior_frontier < self.gain_min:
            self._consecutive_rejects += 1
            self._stall_rounds += 1
            return False, (
                f"frontier {frontier:.4f} did not improve by >={self.gain_min:.3f} "
                f"over prior {prior_frontier:.4f}"
            )

        # Condition 2: retained battery -- each axis must stay within epsilon
        for t, val in retained.items():
            ref = self._retained_ref.get(t)
            if ref is None:
                continue  # no reference yet (shouldn't happen but guard it)
            if val < ref - self.epsilon:
                self._consecutive_rejects += 1
                return False, (
                    f"retained axis T{t} dropped: {val:.4f} < ref {ref:.4f} - "
                    f"eps={self.epsilon:.3f} = {ref - self.epsilon:.4f}"
                )

        # Accept: update references
        self._frontier_ref[tier] = max(self._frontier_ref.get(tier, -1.0), frontier)
        for t, val in retained.items():
            if t not in self._retained_ref:
                self._retained_ref[t] = val
        if tier not in self._retained_ref:
            self._retained_ref[tier] = frontier  # first acquisition of this tier

        self._consecutive_rejects = 0
        self._stall_rounds = 0
        return True, "accepted"

    def first_acquire_tier(self, tier: int, frontier: float):
        """Record the first time a tier is acquired (before any gate check)."""
        if tier not in self._retained_ref:
            self._retained_ref[tier] = frontier
        if tier not in self._frontier_ref:
            self._frontier_ref[tier] = frontier - self.gain_min  # allow first acceptance

    @property
    def jam_detected(self) -> bool:
        return self._consecutive_rejects >= self.jam_window

    @property
    def frontier_stalled(self) -> bool:
        return self._stall_rounds >= self.jam_window


# -- Curriculum state ----------------------------------------------------------

class Curriculum:
    """
    Endogenous curriculum for arm A.
    Starts at tier 0.  Advances when held-out pass@1 on current tier
    clears ADVANCE_THRESHOLD.
    """
    def __init__(self, n_tiers: int = 3, advance_threshold: float = ADVANCE_THRESHOLD):
        self.n_tiers   = n_tiers
        self.threshold = advance_threshold
        self.tier      = 0
        self.advanced_at_rounds: list[int] = []

    def check_advance(self, frontier: float, round_idx: int) -> bool:
        if self.tier < self.n_tiers - 1 and frontier >= self.threshold:
            self.tier += 1
            self.advanced_at_rounds.append(round_idx)
            return True
        return False

    @property
    def current_tier(self) -> int:
        return self.tier


# -- Arm runners ---------------------------------------------------------------

def run_arm_a(model, tokenizer, train_pools, held_out_sets,
              n_rounds, n_candidates, max_steps, device,
              capacity_fn, receipt_path) -> list[dict]:
    """
    Arm A: Pareto-ratchet + endogenous curriculum.
    """
    gate       = ParetoGate()
    curriculum = Curriculum()
    receipts   = []

    for rnd in range(1, n_rounds + 1):
        t0 = time.time()
        tier = curriculum.current_tier
        gate.first_acquire_tier(tier, 0.0)   # init ref if first visit

        # Sample from current tier's pool
        pool = train_pools[tier]
        rng = random.Random(f"arm_a_r{rnd}_t{tier}")
        sampled = rng.choices(pool, k=min(n_candidates, len(pool)))

        # Generate
        candidates = generate_candidates(model, tokenizer, sampled, device)

        # Verify (execution gate)
        verified = [
            c for c in candidates
            if execution_verify(c["generated_code"], c["test_list"],
                                c["test_setup_code"])
        ]
        verified_count = len(verified)

        # Fine-tune on verified set
        prev_state = save_adapter_state(model)
        ft_items = verified if verified else []
        steps = fine_tune_round(
            model, tokenizer, ft_items, max_steps,
            CHECKPOINT_DIR / f"arm_a_r{rnd}_t{tier}", device,
        )

        # Capacity hook (pluggable; default = identity)
        model, tokenizer = capacity_fn(model, tokenizer, rnd, tier)

        # Evaluate
        frontier = eval_pass_at_1(model, tokenizer, held_out_sets[tier], device)
        retained = {
            t: eval_pass_at_1(model, tokenizer, held_out_sets[t], device)
            for t in range(tier)   # all earlier tiers
        }
        vram_f = eval_vram_fraction(device)

        # Pareto gate
        accepted, gate_reason = gate.evaluate(tier, frontier, retained)
        gate_rejected = not accepted

        if gate_rejected:
            # Rollback: restore prior adapter weights
            restore_adapter_state(model, prev_state)

        # Curriculum advance (after gate so we use post-eval score)
        advanced = curriculum.check_advance(frontier, rnd) if accepted else False

        r = build_receipt(
            arm="A", round_idx=rnd, tier=tier,
            frontier_pass=frontier, retained=retained,
            verified_count=verified_count, total_candidates=len(sampled),
            accepted=accepted, gate_rejected=gate_rejected,
            jam_detected=gate.jam_detected,
            frontier_stalled=gate.frontier_stalled,
            curriculum_advanced=advanced,
            finetune_steps=steps, vram_fraction=vram_f,
            wall_seconds=int(time.time() - t0),
            extra={"gate_reason": gate_reason},
        )
        write_receipt(r, receipt_path)
        receipts.append(r)

        print(
            f"  A r{rnd:02d} T{tier} | frontier={frontier:.4f} | "
            f"retained={retained} | accepted={accepted} | "
            f"jam={gate.jam_detected} | advanced={advanced}"
        )

        # Pause between rounds on GPU
        if device.startswith("cuda"):
            time.sleep(10)

    return receipts


def run_arm_b(model, tokenizer, train_pools, held_out_sets,
              n_rounds, n_candidates, max_steps, device,
              capacity_fn, receipt_path) -> list[dict]:
    """
    Arm B: Naive accumulation -- unconditional merge, no gate.
    Expected trajectory: frontier may improve short-term, retention collapses.
    """
    receipts = []
    # B always runs on all tiers round-robin (no endogenous curriculum -- flat pool)
    all_pool = []
    for t in range(3):
        all_pool.extend(train_pools[t])

    for rnd in range(1, n_rounds + 1):
        t0 = time.time()
        tier = 0   # B has no curriculum; report tier=0 throughout

        rng = random.Random(f"arm_b_r{rnd}")
        sampled = rng.choices(all_pool, k=min(n_candidates, len(all_pool)))

        # Generate + verify (still filter for clean data -- naive means no gate,
        # not necessarily training on wrong answers; arm D is the unfiltered arm)
        candidates = generate_candidates(model, tokenizer, sampled, device)
        verified   = [
            c for c in candidates
            if execution_verify(c["generated_code"], c["test_list"],
                                c["test_setup_code"])
        ]
        verified_count = len(verified)

        # Unconditional fine-tune (no gate check, no rollback)
        steps = fine_tune_round(
            model, tokenizer, verified if verified else [], max_steps,
            CHECKPOINT_DIR / f"arm_b_r{rnd}", device,
        )
        model, tokenizer = capacity_fn(model, tokenizer, rnd, tier)

        # Evaluate all tiers to track retention
        frontier = eval_pass_at_1(model, tokenizer, held_out_sets[0], device)
        retained = {
            t: eval_pass_at_1(model, tokenizer, held_out_sets[t], device)
            for t in range(1, 3)
        }
        vram_f = eval_vram_fraction(device)

        r = build_receipt(
            arm="B", round_idx=rnd, tier=tier,
            frontier_pass=frontier, retained=retained,
            verified_count=verified_count, total_candidates=len(sampled),
            accepted=None, gate_rejected=False,
            jam_detected=False, frontier_stalled=False,
            curriculum_advanced=False,
            finetune_steps=steps, vram_fraction=vram_f,
            wall_seconds=int(time.time() - t0),
        )
        write_receipt(r, receipt_path)
        receipts.append(r)

        print(
            f"  B r{rnd:02d}    | frontier={frontier:.4f} | "
            f"retained={retained} | verified={verified_count}/{len(sampled)}"
        )

        if device.startswith("cuda"):
            time.sleep(10)

    return receipts


def run_arm_c(model, tokenizer, held_out_sets,
              n_rounds, device, receipt_path) -> list[dict]:
    """
    Arm C: Frozen base -- no updates.
    Expected trajectory: flat on all metrics.
    """
    receipts = []
    for rnd in range(1, n_rounds + 1):
        t0 = time.time()
        frontier = eval_pass_at_1(model, tokenizer, held_out_sets[0], device)
        retained = {
            t: eval_pass_at_1(model, tokenizer, held_out_sets[t], device)
            for t in range(1, 3)
        }
        vram_f = eval_vram_fraction(device)
        r = build_receipt(
            arm="C", round_idx=rnd, tier=0,
            frontier_pass=frontier, retained=retained,
            verified_count=0, total_candidates=0,
            accepted=None, gate_rejected=False,
            jam_detected=False, frontier_stalled=False,
            curriculum_advanced=False,
            finetune_steps=0, vram_fraction=vram_f,
            wall_seconds=int(time.time() - t0),
        )
        write_receipt(r, receipt_path)
        receipts.append(r)
        print(f"  C r{rnd:02d}    | frontier={frontier:.4f} (frozen)")
    return receipts


def run_arm_d(model, tokenizer, train_pools, held_out_sets,
              n_rounds, n_candidates, max_steps, device,
              capacity_fn, receipt_path) -> list[dict]:
    """
    Arm D: Grounding-off -- train on ALL generated candidates, no execution filter.
    Expected: low verified_fraction (random coincidences only); frontier collapses.
    """
    receipts = []
    all_pool = []
    for t in range(3):
        all_pool.extend(train_pools[t])

    for rnd in range(1, n_rounds + 1):
        t0 = time.time()
        rng = random.Random(f"arm_d_r{rnd}")
        sampled = rng.choices(all_pool, k=min(n_candidates, len(all_pool)))

        # Generate -- NO filtering
        candidates = generate_candidates(model, tokenizer, sampled, device)

        # Count how many would have passed (for receipt honesty; don't filter)
        actually_correct = sum(
            1 for c in candidates
            if execution_verify(c["generated_code"], c["test_list"],
                                c["test_setup_code"])
        )
        total = len(candidates)

        # Fine-tune on ALL candidates (includes wrong ones)
        steps = fine_tune_round(
            model, tokenizer, candidates, max_steps,
            CHECKPOINT_DIR / f"arm_d_r{rnd}", device,
        )
        model, tokenizer = capacity_fn(model, tokenizer, rnd, 0)

        frontier = eval_pass_at_1(model, tokenizer, held_out_sets[0], device)
        retained = {
            t: eval_pass_at_1(model, tokenizer, held_out_sets[t], device)
            for t in range(1, 3)
        }
        vram_f = eval_vram_fraction(device)

        r = build_receipt(
            arm="D", round_idx=rnd, tier=0,
            frontier_pass=frontier, retained=retained,
            verified_count=actually_correct,  # how many would have verified
            total_candidates=total,
            accepted=None, gate_rejected=False,
            jam_detected=False, frontier_stalled=False,
            curriculum_advanced=False,
            finetune_steps=steps, vram_fraction=vram_f,
            wall_seconds=int(time.time() - t0),
            extra={"note": "verified_count is informational; training used ALL candidates"},
        )
        write_receipt(r, receipt_path)
        receipts.append(r)

        print(
            f"  D r{rnd:02d}    | frontier={frontier:.4f} | "
            f"would-verify={actually_correct}/{total}"
        )

        if device.startswith("cuda"):
            time.sleep(10)

    return receipts


# -- Baseline measurement -------------------------------------------------------

def run_baseline(model, tokenizer, held_out_sets,
                 device, receipt_path) -> dict:
    """Measure baseline (round 0) for all metrics before any fine-tuning."""
    t0 = time.time()
    scores = {
        t: eval_pass_at_1(model, tokenizer, held_out_sets[t], device)
        for t in range(3)
    }
    vram_f = eval_vram_fraction(device)
    r = {
        "schema_version": 2,
        "experiment": "accumulation-law",
        "arm": "baseline",
        "round": 0,
        "tier_scores": {str(t): round(s, 6) for t, s in scores.items()},
        "vram_fraction": round(vram_f, 4),
        "round_wall_seconds": int(time.time() - t0),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    write_receipt(r, receipt_path)
    print(f"  Baseline | tier scores: {scores}")
    return r


# -- Verdict (deterministic) ---------------------------------------------------

def verdict(receipts: list[dict]) -> dict:
    """
    Deterministic verdict over all arm receipts.

    Returns dict with:
      result: LAW_HOLDS | JAM_DETECTED | INCONCLUSIVE | REJECT
      conditions: dict of individual condition evaluations
      summary: human-readable string
    """
    def arm_receipts(arm_name):
        return sorted(
            [r for r in receipts if r.get("arm") == arm_name],
            key=lambda r: r["round"],
        )

    def frontier_series(arm_name):
        return [r["frontier_pass_at_1"] for r in arm_receipts(arm_name)]

    def compounds_nsat(series: list[float], min_gain: float = FRONTIER_GAIN_MIN,
                       min_rounds: int = 4) -> bool:
        """Non-saturating compounding: sustained gain across >= min_rounds."""
        gains = [series[i] - series[i-1] for i in range(1, len(series))]
        positive_gains = [g for g in gains if g >= min_gain]
        return len(positive_gains) >= min_rounds

    def forgets(arm_name: str) -> bool:
        """Returns True if arm shows declining retention on earlier tiers."""
        rs = arm_receipts(arm_name)
        if len(rs) < 3:
            return False
        # Any retained axis that drops >= eps relative to round-1 value
        first_retained = {}
        for r in rs:
            for k, v in r.get("retained_pass_at_1", {}).items():
                if k not in first_retained:
                    first_retained[k] = v
        for r in rs[2:]:   # check from round 3 onward
            for k, v in r.get("retained_pass_at_1", {}).items():
                ref = first_retained.get(k)
                if ref is not None and v < ref - EPSILON:
                    return True
        return False

    def stagnates(arm_name: str) -> bool:
        """Returns True if arm shows no sustained gain (flat or declining)."""
        series = frontier_series(arm_name)
        if not series:
            return True
        gains = [series[i] - series[i-1] for i in range(1, len(series))]
        return sum(1 for g in gains if g >= FRONTIER_GAIN_MIN) < 2

    def jam_fired() -> bool:
        return any(r.get("jam_detected", False) for r in arm_receipts("A"))

    # -- Gather conditions ----------------------------------------------------
    a_series = frontier_series("A")
    b_series = frontier_series("B")
    c_series = frontier_series("C")
    d_series = frontier_series("D")

    n_rounds_a = len(a_series)
    min_rounds_for_compound = max(4, n_rounds_a // 2)
    _jam = jam_fired()

    def arm_a_retention_holds() -> bool:
        """
        Retention holds by gate contract: every ACCEPTED round passed the gate
        check (retained battery within epsilon).  Rejected rounds are rolled back
        so do not count.  The only structural failure is JAM (gate stuck).
        """
        if _jam:
            return False
        accepted = [r for r in arm_receipts("A") if r.get("accepted") is True]
        return len(accepted) > 0

    cond = {
        "A_compounds_nonsat": compounds_nsat(a_series, min_rounds=min_rounds_for_compound),
        "B_forgets":         forgets("B"),
        "C_stagnates":       stagnates("C"),
        "D_collapses":       stagnates("D") or (d_series and d_series[-1] < d_series[0]),
        "A_retention_holds": arm_a_retention_holds(),
        "jam_detected":      _jam,
        "n_rounds":          n_rounds_a,
    }

    if n_rounds_a < 4:
        result = "INCONCLUSIVE:insufficient_rounds"
        summary = (
            f"Only {n_rounds_a} rounds of arm A; need >=4 for compounding verdict. "
            "Run more rounds."
        )
    elif cond["jam_detected"]:
        result = "JAM_DETECTED"
        summary = (
            "Arm A Pareto gate jammed: every frontier gain regressed retention. "
            "Relaxed ratchet (arm A') is the valid result path. "
            "This is the saturation signal -- a growth event should follow."
        )
    elif (cond["A_compounds_nonsat"] and cond["B_forgets"]
          and cond["C_stagnates"] and cond["A_retention_holds"]):
        result = "LAW_HOLDS"
        summary = (
            "Accumulation law holds: arm A compounds non-saturatingly with full "
            "retention; arm B forgets; arm C stagnates. "
            "The candidate law is corroborated on this base."
        )
    elif (cond["A_compounds_nonsat"] and cond["A_retention_holds"]
          and not cond["B_forgets"]):
        result = "REJECT:ablation_also_holds"
        summary = (
            "Arm B also compounds without forgetting -- naive accumulation is "
            "sufficient. Grounded gate is not the differentiating element here. "
            "Investigate task difficulty / training signal distribution."
        )
    elif cond["A_compounds_nonsat"] and not cond["A_retention_holds"]:
        result = "INCONCLUSIVE:A_compounds_but_forgets"
        summary = (
            "Arm A gains on frontier but fails its own retention bar. "
            "The strict Pareto ratchet is catching self-induced forgetting. "
            "Consider tighter rollback strategy or wider epsilon."
        )
    else:
        result = "INCONCLUSIVE:partial"
        summary = f"Conditions met: {cond}"

    return {
        "result": result,
        "conditions": cond,
        "summary": summary,
        "epsilon": EPSILON,
        "advance_threshold": ADVANCE_THRESHOLD,
        "frontier_gain_min": FRONTIER_GAIN_MIN,
    }


# -- Mock mode (instant logic proof) ------------------------------------------

def run_mock(n_rounds: int, receipt_path: Path) -> list[dict]:
    """
    Synthetic trajectories demonstrating all gate / curriculum / verdict logic.
    No model or dataset required.

    Trajectory design (3 rounds shown; >=8 rounds extrapolated for GPU):
    Arm A:
      Round 1 T0: frontier 0.18 (+0.03 from 0.15 base) -- ACCEPTED; no retained battery
      Round 2 T0: frontier 0.22 (+0.04); curriculum ADVANCES to T1; retained={} -- ACCEPTED
      Round 3 T1: frontier 0.19 (T1 is harder, new tier); retained T0 = 0.09 (dropped from
                  0.22 by 0.13, > eps=0.05) -- GATE REJECTS; rollback; adapter stays at r2 state
      Round 4 T1: frontier 0.23 (re-attempt on T1 after rollback); retained T0 = 0.21 (OK)
                  -- ACCEPTED
      Rounds 5-8: gradual gains demonstrating non-saturating compounding

    Arm B: unconditional, T0 retention collapses by round 3
    Arm C: flat throughout
    Arm D: collapses (low verified_fraction, frontier declines)

    Gate rejection in round 3 of arm A is the KEY demonstrated mechanism.
    """
    receipts: list[dict] = []

    # -- Base trajectories ---------------------------------------------------
    # Arm A: designed to show gate rejection at round 3, then recovery
    arm_a_data = [
        # (round, tier, frontier, retained, accepted, gate_rejected, advanced, verified_count, total)
        (1, 0, 0.180, {},            True,  False, False, 8,  15),
        (2, 0, 0.220, {},            True,  False, True,  10, 15),  # curriculum advances
        (3, 1, 0.190, {0: 0.090},   False, True,  False, 6,  15),  # REJECTED: T0 dropped 0.22->0.09
        (4, 1, 0.230, {0: 0.210},   True,  False, False, 9,  15),  # recovered; ACCEPTED
        (5, 1, 0.260, {0: 0.215},   True,  False, False, 11, 15),
        (6, 1, 0.290, {0: 0.220},   True,  False, True,  12, 15),  # T1 clears; advances to T2
        (7, 2, 0.240, {0: 0.215, 1: 0.275}, True, False, False, 10, 15),
        (8, 2, 0.265, {0: 0.220, 1: 0.280}, True, False, False, 11, 15),
    ]

    # Arm B: naive -- retention collapses by round 3
    arm_b_data = [
        (1, 0, 0.175, {1: 0.150, 2: 0.120}, 15, 15),
        (2, 0, 0.195, {1: 0.140, 2: 0.110}, 14, 15),
        (3, 0, 0.180, {1: 0.110, 2: 0.080}, 12, 15),  # forgetting emerging
        (4, 0, 0.185, {1: 0.090, 2: 0.060}, 13, 15),  # clear forgetting
        (5, 0, 0.190, {1: 0.070, 2: 0.040}, 11, 15),
        (6, 0, 0.192, {1: 0.055, 2: 0.030}, 10, 15),
        (7, 0, 0.188, {1: 0.040, 2: 0.025}, 9,  15),
        (8, 0, 0.190, {1: 0.030, 2: 0.020}, 10, 15),
    ]

    # Arm C: flat (no updates)
    arm_c_fronts = [0.155, 0.155, 0.155, 0.155, 0.155, 0.155, 0.155, 0.155]

    # Arm D: collapses (trains on wrong code)
    arm_d_fronts         = [0.140, 0.120, 0.100, 0.085, 0.075, 0.068, 0.062, 0.058]
    arm_d_would_verified = [2,     1,     1,     0,     1,     0,     1,     0]

    # -- Write arm A receipts -------------------------------------------------
    gate      = ParetoGate()
    jam_count = 0
    for row in arm_a_data[:n_rounds]:
        rnd, tier, frontier, retained, accepted, gate_rejected, advanced, vc, tc = row
        gate.first_acquire_tier(tier, 0.0)
        if not accepted:
            gate._consecutive_rejects += 1
        else:
            gate._consecutive_rejects = 0

        r = build_receipt(
            arm="A", round_idx=rnd, tier=tier,
            frontier_pass=frontier, retained=retained,
            verified_count=vc, total_candidates=tc,
            accepted=accepted, gate_rejected=gate_rejected,
            jam_detected=gate.jam_detected,
            frontier_stalled=gate.frontier_stalled,
            curriculum_advanced=advanced,
            finetune_steps=5, vram_fraction=0.0,
            wall_seconds=3,
            extra={"mode": "mock",
                   "gate_reason": "retained axis T0 below threshold" if gate_rejected
                   else "accepted"},
        )
        write_receipt(r, receipt_path)
        receipts.append(r)

    # -- Write arm B receipts -------------------------------------------------
    for row in arm_b_data[:n_rounds]:
        rnd, tier, frontier, retained, vc, tc = row
        r = build_receipt(
            arm="B", round_idx=rnd, tier=tier,
            frontier_pass=frontier, retained=retained,
            verified_count=vc, total_candidates=tc,
            accepted=None, gate_rejected=False,
            jam_detected=False, frontier_stalled=False,
            curriculum_advanced=False,
            finetune_steps=5, vram_fraction=0.0,
            wall_seconds=3,
            extra={"mode": "mock"},
        )
        write_receipt(r, receipt_path)
        receipts.append(r)

    # -- Write arm C receipts -------------------------------------------------
    for rnd, fr in enumerate(arm_c_fronts[:n_rounds], start=1):
        r = build_receipt(
            arm="C", round_idx=rnd, tier=0,
            frontier_pass=fr, retained={1: 0.155, 2: 0.120},
            verified_count=0, total_candidates=0,
            accepted=None, gate_rejected=False,
            jam_detected=False, frontier_stalled=False,
            curriculum_advanced=False,
            finetune_steps=0, vram_fraction=0.0,
            wall_seconds=1,
            extra={"mode": "mock"},
        )
        write_receipt(r, receipt_path)
        receipts.append(r)

    # -- Write arm D receipts -------------------------------------------------
    for rnd, (fr, wv) in enumerate(
        zip(arm_d_fronts[:n_rounds], arm_d_would_verified[:n_rounds]), start=1
    ):
        r = build_receipt(
            arm="D", round_idx=rnd, tier=0,
            frontier_pass=fr, retained={1: fr - 0.02, 2: fr - 0.04},
            verified_count=wv, total_candidates=15,
            accepted=None, gate_rejected=False,
            jam_detected=False, frontier_stalled=False,
            curriculum_advanced=False,
            finetune_steps=5, vram_fraction=0.0,
            wall_seconds=3,
            extra={"mode": "mock",
                   "note": "verified_count = would-have-verified; trained on ALL 15"},
        )
        write_receipt(r, receipt_path)
        receipts.append(r)

    return receipts


# -- Smoke mode (real model, tiny data, CPU) -----------------------------------

def run_smoke(n_rounds: int, receipt_path: Path, capacity_fn) -> list[dict]:
    """
    CPU smoke: tiny data, all 4 arms, real model.
    Validates end-to-end code path.  Numbers will be noisy.
    """
    print("  Loading data (smoke: tiny partition)...")
    train_pools, held_out_sets, meta = load_and_partition(
        n_held_out_per_tier=4,
        n_train_per_tier=12,
    )
    print(f"  Partition: {meta}")

    print(f"  Loading model ({MODEL_ID}) on CPU...")
    device = "cpu"
    model, tokenizer = load_model_and_tokenizer(device, lora_rank=4, lora_alpha=8)

    print("  Baseline measurement...")
    receipts = []
    br = run_baseline(model, tokenizer, held_out_sets, device, receipt_path)
    receipts.append(br)

    # Arms A, B, C, D each get a FRESH copy of the base model
    import copy as _copy

    print("\n--- ARM A (Pareto-ratchet) ---")
    # Deep-copy state for arm A
    a_model = _copy.deepcopy(model)
    receipts.extend(run_arm_a(
        a_model, tokenizer, train_pools, held_out_sets,
        n_rounds=n_rounds, n_candidates=5, max_steps=3,
        device=device, capacity_fn=capacity_fn, receipt_path=receipt_path,
    ))

    print("\n--- ARM B (naive accumulation) ---")
    b_model = _copy.deepcopy(model)
    receipts.extend(run_arm_b(
        b_model, tokenizer, train_pools, held_out_sets,
        n_rounds=n_rounds, n_candidates=5, max_steps=3,
        device=device, capacity_fn=capacity_fn, receipt_path=receipt_path,
    ))

    print("\n--- ARM C (frozen base) ---")
    c_model = _copy.deepcopy(model)
    receipts.extend(run_arm_c(
        c_model, tokenizer, held_out_sets,
        n_rounds=n_rounds, device=device, receipt_path=receipt_path,
    ))

    print("\n--- ARM D (grounding-off) ---")
    d_model = _copy.deepcopy(model)
    receipts.extend(run_arm_d(
        d_model, tokenizer, train_pools, held_out_sets,
        n_rounds=n_rounds, n_candidates=5, max_steps=3,
        device=device, capacity_fn=capacity_fn, receipt_path=receipt_path,
    ))

    return receipts


# -- GPU mode -------------------------------------------------------------------

def run_gpu(n_rounds: int, n_candidates: int, receipt_path: Path,
            capacity_fn) -> list[dict]:
    """
    Full GPU run.  Requires EMBER_VRAM_FRACTION <= 0.80 headroom.
    """
    print("  Loading data (GPU: full partition)...")
    train_pools, held_out_sets, meta = load_and_partition(
        n_held_out_per_tier=HELD_OUT_PER_TIER,
        n_train_per_tier=100,
    )
    print(f"  Partition: {meta}")

    # gh issue #244: `total_memory - memory_reserved(0)` only sees THIS
    # process's own reservations. On WDDM, with a resident server holding
    # the GPU in a different process, this reports the full oversubscribable
    # pool as "free" and the assert below passes on a fully occupied GPU --
    # the exact fail-open this issue diagnosed. Ground truth is nvidia-smi,
    # queried cross-process; see scripts/vram_ground_truth.py.
    import sys
    from pathlib import Path as _Path
    sys.path.insert(0, str(_Path(__file__).resolve().parents[1]))
    from vram_ground_truth import nvidia_smi_free_mib, torch_self_report_free_mib

    free_mib = nvidia_smi_free_mib(0)
    try:
        free_torch_wddm_mib = torch_self_report_free_mib(0)
    except Exception:
        free_torch_wddm_mib = None
    print(f"  GPU free (nvidia-smi ground truth): {free_mib:.0f} MiB"
          + (f"  [torch self-report: {free_torch_wddm_mib:.0f} MiB, WDDM-blind]"
             if free_torch_wddm_mib is not None else ""))
    assert free_mib > 6000, (
        f"Insufficient GPU memory: {free_mib:.0f} MiB free (nvidia-smi); need >=6000 MiB. "
        "Free the resident model first."
    )

    device = "cuda:0"
    print(f"  Loading model ({MODEL_ID}) on {device}...")
    model, tokenizer = load_model_and_tokenizer(device, LORA_RANK, LORA_ALPHA)

    receipts = []
    br = run_baseline(model, tokenizer, held_out_sets, device, receipt_path)
    receipts.append(br)

    import copy as _copy

    print("\n--- ARM C (frozen, run first to calibrate) ---")
    c_model = _copy.deepcopy(model)
    receipts.extend(run_arm_c(
        c_model, tokenizer, held_out_sets, n_rounds, device, receipt_path,
    ))
    del c_model
    torch.cuda.empty_cache()

    print("\n--- ARM A (Pareto-ratchet) ---")
    a_model = _copy.deepcopy(model)
    receipts.extend(run_arm_a(
        a_model, tokenizer, train_pools, held_out_sets,
        n_rounds=n_rounds, n_candidates=n_candidates,
        max_steps=MAX_FINETUNE_STEPS, device=device,
        capacity_fn=capacity_fn, receipt_path=receipt_path,
    ))
    del a_model
    torch.cuda.empty_cache()

    print("\n--- ARM B (naive accumulation) ---")
    b_model = _copy.deepcopy(model)
    receipts.extend(run_arm_b(
        b_model, tokenizer, train_pools, held_out_sets,
        n_rounds=n_rounds, n_candidates=n_candidates,
        max_steps=MAX_FINETUNE_STEPS, device=device,
        capacity_fn=capacity_fn, receipt_path=receipt_path,
    ))
    del b_model
    torch.cuda.empty_cache()

    print("\n--- ARM D (grounding-off) ---")
    d_model = _copy.deepcopy(model)
    receipts.extend(run_arm_d(
        d_model, tokenizer, train_pools, held_out_sets,
        n_rounds=n_rounds, n_candidates=n_candidates,
        max_steps=MAX_FINETUNE_STEPS, device=device,
        capacity_fn=capacity_fn, receipt_path=receipt_path,
    ))
    del d_model
    torch.cuda.empty_cache()

    return receipts


# -- Entry point ---------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Accumulation Law Experiment")
    parser.add_argument(
        "--mode", choices=["mock", "smoke", "gpu"], default="mock",
        help="mock=synthetic logic proof; smoke=tiny CPU real-model; gpu=full run",
    )
    parser.add_argument(
        "--rounds", type=int, default=None,
        help="Override number of rounds (default: 3 smoke/mock, 8 gpu)",
    )
    parser.add_argument(
        "--candidates", type=int, default=50,
        help="Candidates per round per tier (GPU mode only)",
    )
    parser.add_argument(
        "--capacity_fn", type=str, default=None,
        help="Capacity hook: 'module:function' (default: identity/no-op). "
             "Plug arm E growth here.",
    )
    parser.add_argument(
        "--receipt_path", type=str, default=None,
        help="Override receipt JSONL path",
    )
    args = parser.parse_args()

    # -- Defaults per mode ----------------------------------------------------
    if args.mode == "gpu":
        default_rounds = 8
    else:
        default_rounds = 3

    n_rounds = args.rounds if args.rounds is not None else default_rounds
    receipt_path = Path(args.receipt_path) if args.receipt_path else RECEIPT_PATH

    # -- Capacity hook --------------------------------------------------------
    capacity_fn = load_capacity_fn(args.capacity_fn)

    # -- Run ------------------------------------------------------------------
    print(f"=== Accumulation Law Experiment | mode={args.mode} rounds={n_rounds} ===")
    print(f"    eps={EPSILON}  advance_threshold={ADVANCE_THRESHOLD}  "
          f"gain_min={FRONTIER_GAIN_MIN}  jam_window={JAM_WINDOW}")
    print(f"    capacity_fn={'custom:'+args.capacity_fn if args.capacity_fn else 'identity'}")
    print(f"    receipt_path={receipt_path}")

    if args.mode == "mock":
        print("\nMode: MOCK -- synthetic trajectories (gate/curriculum/verdict logic proof)")
        receipts = run_mock(n_rounds, receipt_path)

    elif args.mode == "smoke":
        print("\nMode: SMOKE -- tiny real-model run on CPU")
        receipts = run_smoke(n_rounds, receipt_path, capacity_fn)

    elif args.mode == "gpu":
        print("\nMode: GPU -- full experiment run")
        receipts = run_gpu(n_rounds, args.candidates, receipt_path, capacity_fn)

    # -- Verdict --------------------------------------------------------------
    arm_receipts = [r for r in receipts if r.get("arm") in ("A", "B", "C", "D")]
    v = verdict(arm_receipts)
    verdict_rec = {
        "schema_version": 2,
        "experiment": "accumulation-law",
        "arm": "verdict",
        "round": n_rounds,
        **v,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    write_receipt(verdict_rec, receipt_path)

    # -- Summary ---------------------------------------------------------------
    print("\n" + "=" * 60)
    print(f"VERDICT: {v['result']}")
    print(f"Summary: {v['summary']}")
    print(f"Conditions:")
    for k, val in v["conditions"].items():
        print(f"  {k}: {val}")
    print(f"\nReceipts written to: {receipt_path}")

    # Print per-arm per-round table
    print("\n--- Per-arm per-round frontier (pass@1) ---")
    for arm in ("A", "B", "C", "D"):
        rs = sorted(
            [r for r in arm_receipts if r["arm"] == arm],
            key=lambda r: r["round"],
        )
        if rs:
            row = "  " + arm + ": " + "  ".join(
                f"r{r['round']}={r['frontier_pass_at_1']:.3f}"
                + (f"[REJECT]" if r.get("gate_rejected") else "")
                + (f"[ADV->T{r['tier']+1}]" if r.get("curriculum_advanced") else "")
                for r in rs
            )
            print(row)

    # JAM summary
    a_jams = [r for r in arm_receipts if r["arm"] == "A" and r.get("jam_detected")]
    if a_jams:
        print(f"\nJAM DETECTED at rounds: {[r['round'] for r in a_jams]}")
        print("  [growth trigger] This is the signal for arm E (capacity expansion).")
        print("  [fallback] frontier_stalled flag set; relaxed ratchet (arm A') applies.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
