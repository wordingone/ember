"""t_native_smoke.py — Probe (b): native-Windows torch + triton-windows smoke.

Issue context: wordingone/ember #27
Purpose: first-principles audit §8.8 — WSL inherited, never questioned.
This script is the IDLE-WINDOW-ONLY probe for whether native-Windows
torch/triton/bitsandbytes can execute a real LoRA SFT step.  Do NOT launch
while a round is active.

Governor semantics replicated inline, byte-equivalent to
leo/state/nc-ladder/scripts/governor.py (provenance: read 2026-06-10,
extraction changes WHERE the floor lives, never what it asserts):

  1. torch.cuda.set_per_process_memory_fraction(EMBER_VRAM_FRACTION, dflt 0.85)
  2. free-VRAM >= EMBER_VRAM_MARGIN_GB (dflt 4.0 GB) asserted BEFORE model load
     — SystemExit on violation, never fix-forward
  3. EMBER_THROTTLE_S (dflt 0.3) sleep AFTER the single optimizer step

Usage:
  # selftest (no torch required):
  python t_native_smoke.py --selftest

  # actual smoke (idle window only):
  python t_native_smoke.py [--output PATH]
"""

import argparse
import json
import os
import platform
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Governor constants (inline copy — byte-equivalent to governor.py)
# ---------------------------------------------------------------------------
_DEFAULT_VRAM_FRACTION = 0.85
_DEFAULT_MARGIN_GB = 4.0
_DEFAULT_THROTTLE_S = 0.3

MODEL_ID = "Qwen/Qwen2.5-Coder-3B-Instruct"
LORA_R = 32
LORA_ALPHA = 32
LORA_TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj",
                "gate_proj", "up_proj", "down_proj"]

# Three hard-coded prompt/completion pairs (tiny SFT dataset)
BUILTIN_DATASET = [
    {"prompt": "Write a Python function that returns the sum of two integers.",
     "completion": "def add(a: int, b: int) -> int:\n    return a + b"},
    {"prompt": "Write a Python one-liner to flatten a list of lists.",
     "completion": "flat = [x for sub in lst for x in sub]"},
    {"prompt": "Write a Python function that checks if a string is a palindrome.",
     "completion": "def is_palindrome(s: str) -> bool:\n    return s == s[::-1]"},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env_limits():
    """Return (vram_fraction, margin_gb, throttle_s) — matches governor.env_limits()."""
    return (
        float(os.environ.get("EMBER_VRAM_FRACTION", str(_DEFAULT_VRAM_FRACTION))),
        float(os.environ.get("EMBER_VRAM_MARGIN_GB", str(_DEFAULT_MARGIN_GB))),
        float(os.environ.get("EMBER_THROTTLE_S", str(_DEFAULT_THROTTLE_S))),
    )


def _governor_preflight(torch):
    """Apply VRAM cap + assert margin. Returns governor receipt block.
    Semantics byte-equivalent to governor.preflight().
    Raises SystemExit on margin violation — never fix-forward."""
    frac, margin_gb, _ = _env_limits()
    torch.cuda.set_per_process_memory_fraction(frac)
    free, total = torch.cuda.mem_get_info()
    if free < margin_gb * 1e9:
        raise SystemExit(
            f"VRAM-PREFLIGHT: {free/1e9:.1f}GB free of {total/1e9:.1f}GB — "
            f"need >= {margin_gb}GB free before load; refusing launch"
        )
    return {
        "vram_fraction": frac,
        "free_gb": round(free / 1e9, 2),
        "total_gb": round(total / 1e9, 2),
        "margin_gb": margin_gb,
    }


def _default_output_path():
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipts_dir = Path(__file__).parent / "receipts"
    receipts_dir.mkdir(parents=True, exist_ok=True)
    return receipts_dir / f"native-smoke-{ts}.json"


def _write_receipt(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2)
    print(f"RECEIPT: {path}")


# ---------------------------------------------------------------------------
# Selftest — no torch import, validates receipt shape + env parsing
# ---------------------------------------------------------------------------

def run_selftest():
    """--selftest: receipt-shape + env-parsing checks. No torch required."""
    errors = []

    # 1. env parsing: frozen defaults
    saved = {k: os.environ.pop(k, None)
             for k in ("EMBER_VRAM_FRACTION", "EMBER_VRAM_MARGIN_GB", "EMBER_THROTTLE_S")}
    try:
        frac, margin, throttle = _env_limits()
        if frac != 0.85:
            errors.append(f"default VRAM fraction wrong: {frac}")
        if margin != 4.0:
            errors.append(f"default margin wrong: {margin}")
        if throttle != 0.3:
            errors.append(f"default throttle wrong: {throttle}")

        # env override
        os.environ["EMBER_VRAM_FRACTION"] = "0.7"
        os.environ["EMBER_VRAM_MARGIN_GB"] = "6.0"
        os.environ["EMBER_THROTTLE_S"] = "0.1"
        frac2, margin2, throttle2 = _env_limits()
        if frac2 != 0.7:
            errors.append(f"env override VRAM fraction wrong: {frac2}")
        if margin2 != 6.0:
            errors.append(f"env override margin wrong: {margin2}")
        if throttle2 != 0.1:
            errors.append(f"env override throttle wrong: {throttle2}")
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # 2. receipt shape — validate required keys exist in a mock PASS receipt
    mock_pass = _build_mock_receipt("NATIVE_SMOKE_PASS")
    required_keys = [
        "verdict", "error", "platform", "python_version",
        "torch_version", "triton_version", "bnb_version",
        "cuda_device_name", "governor",
        "model_load_secs", "weights_source", "weights_bytes",
        "step_loss", "step_secs", "peak_vram_bytes",
    ]
    for k in required_keys:
        if k not in mock_pass:
            errors.append(f"receipt missing key: {k}")

    # 3. builtin dataset has exactly 3 entries with prompt + completion
    if len(BUILTIN_DATASET) != 3:
        errors.append(f"BUILTIN_DATASET length wrong: {len(BUILTIN_DATASET)}")
    for i, row in enumerate(BUILTIN_DATASET):
        if "prompt" not in row or "completion" not in row:
            errors.append(f"BUILTIN_DATASET[{i}] missing prompt/completion")

    # 4. LoRA config sanity
    if LORA_R != 32 or LORA_ALPHA != 32:
        errors.append(f"LoRA r/alpha wrong: r={LORA_R} alpha={LORA_ALPHA}")
    if len(LORA_TARGETS) != 7:
        errors.append(f"LORA_TARGETS count wrong: {len(LORA_TARGETS)}")

    # 5. model ID
    if MODEL_ID != "Qwen/Qwen2.5-Coder-3B-Instruct":
        errors.append(f"MODEL_ID wrong: {MODEL_ID}")

    if errors:
        for e in errors:
            print(f"  FAIL: {e}")
        print("NATIVE_SMOKE_SELFTEST_FAIL")
        sys.exit(1)
    else:
        print("NATIVE_SMOKE_SELFTEST_PASS")


def _build_mock_receipt(verdict: str, error: str = None) -> dict:
    """Construct a receipt skeleton with all required keys (for selftest shape check)."""
    return {
        "verdict": verdict,
        "error": error,
        "platform": None,
        "python_version": None,
        "torch_version": None,
        "triton_version": None,
        "bnb_version": None,
        "cuda_device_name": None,
        "governor": None,
        "model_load_secs": None,
        "weights_source": None,   # "cache" | "downloaded"
        "weights_bytes": None,
        "step_loss": None,
        "step_secs": None,
        "peak_vram_bytes": None,
    }


# ---------------------------------------------------------------------------
# Main smoke run
# ---------------------------------------------------------------------------

def run_smoke(output_path: Path):
    receipt = _build_mock_receipt("NATIVE_SMOKE_FAIL")

    try:
        # -- platform / python --
        receipt["platform"] = platform.platform()
        receipt["python_version"] = sys.version

        # -- torch --
        import torch
        receipt["torch_version"] = torch.__version__

        # -- triton (optional on Windows — record absence, don't fail) --
        try:
            import triton
            receipt["triton_version"] = triton.__version__
        except ImportError:
            receipt["triton_version"] = "NOT_INSTALLED"

        # -- bitsandbytes --
        import bitsandbytes as bnb
        receipt["bnb_version"] = bnb.__version__

        # -- CUDA device --
        if not torch.cuda.is_available():
            raise RuntimeError("torch.cuda.is_available() returned False")
        receipt["cuda_device_name"] = torch.cuda.get_device_name(0)

        # -- Governor preflight (inline, byte-equivalent to governor.preflight) --
        governor_block = _governor_preflight(torch)
        receipt["governor"] = governor_block
        _, _, throttle_s = _env_limits()

        # -- Model load --
        from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
        from peft import LoraConfig, get_peft_model

        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=False,
        )

        # Detect whether weights are already cached
        hf_cache = Path(os.environ.get(
            "HF_HOME",
            Path.home() / ".cache" / "huggingface"
        ))
        # Check for the model directory under hub/models--<org>--<name>/
        model_slug = MODEL_ID.replace("/", "--")
        model_cache_dir = hf_cache / "hub" / f"models--{model_slug}"
        already_cached = model_cache_dir.exists()

        t_load_start = time.perf_counter()
        tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_ID,
            quantization_config=bnb_config,
            device_map="auto",
            trust_remote_code=True,
        )
        t_load_end = time.perf_counter()
        receipt["model_load_secs"] = round(t_load_end - t_load_start, 2)

        # Weights source + bytes (estimate from cache size if cached)
        if already_cached:
            receipt["weights_source"] = "cache"
            try:
                total_bytes = sum(
                    f.stat().st_size
                    for f in model_cache_dir.rglob("*")
                    if f.is_file()
                )
                receipt["weights_bytes"] = total_bytes
            except Exception:
                receipt["weights_bytes"] = None
        else:
            receipt["weights_source"] = "downloaded"
            # Post-download: measure cache size
            try:
                total_bytes = sum(
                    f.stat().st_size
                    for f in model_cache_dir.rglob("*")
                    if f.is_file()
                )
                receipt["weights_bytes"] = total_bytes
            except Exception:
                receipt["weights_bytes"] = None

        # -- LoRA wrap --
        lora_config = LoraConfig(
            r=LORA_R,
            lora_alpha=LORA_ALPHA,
            target_modules=LORA_TARGETS,
            lora_dropout=0.05,
            bias="none",
            task_type="CAUSAL_LM",
        )
        model = get_peft_model(model, lora_config)
        model.train()

        # -- Tiny SFT dataset: tokenize 3 built-in pairs --
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token

        # Build a single concatenated batch (prompt + completion, shifted labels)
        texts = [row["prompt"] + "\n" + row["completion"] for row in BUILTIN_DATASET]
        enc = tokenizer(
            texts,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=128,
        )
        input_ids = enc["input_ids"].to("cuda")
        attention_mask = enc["attention_mask"].to("cuda")
        # Labels: -100 for padding tokens
        labels = input_ids.clone()
        labels[attention_mask == 0] = -100

        # -- Optimizer --
        optimizer = torch.optim.AdamW(
            filter(lambda p: p.requires_grad, model.parameters()),
            lr=2e-4,
        )
        torch.cuda.reset_peak_memory_stats()

        # -- Single step --
        optimizer.zero_grad()
        t_step_start = time.perf_counter()
        outputs = model(input_ids=input_ids, attention_mask=attention_mask, labels=labels)
        loss = outputs.loss
        loss.backward()
        optimizer.step()
        t_step_end = time.perf_counter()

        # -- Governor throttle (byte-equivalent to governor.throttle_step) --
        time.sleep(throttle_s)

        receipt["step_loss"] = round(loss.item(), 6)
        receipt["step_secs"] = round(t_step_end - t_step_start, 3)
        receipt["peak_vram_bytes"] = torch.cuda.max_memory_allocated()
        receipt["verdict"] = "NATIVE_SMOKE_PASS"
        receipt["error"] = None

    except SystemExit as e:
        # Governor preflight refused launch — still a valid receipt
        receipt["verdict"] = "NATIVE_SMOKE_FAIL"
        receipt["error"] = f"GOVERNOR_REFUSED: {e}"
    except Exception:
        receipt["verdict"] = "NATIVE_SMOKE_FAIL"
        receipt["error"] = traceback.format_exc()

    _write_receipt(output_path, receipt)
    print(f"VERDICT: {receipt['verdict']}")
    if receipt["error"]:
        print(f"ERROR:\n{receipt['error']}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Native-Windows torch smoke (ember #27 probe-b)")
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Receipt JSON path. Default: ember-eng/receipts/native-smoke-<UTC>.json"
    )
    parser.add_argument(
        "--selftest", action="store_true",
        help="Run shape + env-parsing checks without importing torch. "
             "Prints NATIVE_SMOKE_SELFTEST_PASS on success."
    )
    args = parser.parse_args()

    if args.selftest:
        run_selftest()
        return

    output = args.output if args.output else _default_output_path()
    run_smoke(Path(output))


if __name__ == "__main__":
    main()
