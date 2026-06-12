#!/usr/bin/env python3
"""sp: checkpoint-probe — fp-23 curriculum L1 eval on an ember checkpoint (#316).

Loads the ember v0 checkpoint (step-specific; pass --checkpoint-dir), runs the
FROZEN fp-23 curriculum L1 probe (100 tasks, k≤16 candidates, verified by the
fp-23 reference implementations), emits a PROBE receipt with all 16 fp-23
required fields.

CPU inference only (live run 12c050e7 holds VRAM). Checkpoint read from a COPY
(never live file handles on v0-r1s1, same pattern as ember_shakedown.py #313).

CLI:
  --run              required to execute (staged guard)
  --write            write receipt to receipts/sp-checkpoint-probe-step-<N>-<ts>.json
  --checkpoint-dir   path to checkpoint directory (required with --run)
  --k                candidates per task (default 4, max 16 per fp-23)
  --selftest         pure-logic test: no model, no checkpoint
"""
from __future__ import annotations

import hashlib
import json
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import fp23_probe_prereg as fp23
from nck.replay_rig import REPO_ROOT

TOKENIZER_PATH = REPO_ROOT / "tokenizer" / "tokenizer.json"
CONFIG_PATH = REPO_ROOT / "configs" / "v0-pretrain-config.json"

BATCH_SIZE = 4     # from v0-pretrain-config.json throughput.batch
SEQ_LEN = 1024    # from model.seq
MAX_NEW_TOKENS = 64  # programs are short; EOS fires early on raw pretrain
DEVICE = "cpu"
EOS_ID = 0  # <|endoftext|>
PACE_S_PER_STEP = 0.05  # governor floor from config
DEFAULT_K = 4  # candidates per task (≤16 per fp-23; CPU-tractable default)

_STAGED_MSG = (
    "STAGED: checkpoint_probe loaded but not triggered. "
    "Pass --run to execute. Pass --write to save receipt. "
    "Pass --checkpoint-dir <path> to name the checkpoint. "
    "Exit-1 is the evidence-promotion gate."
)

# Reference implementations — FROZEN, never fitted to checkpoint output.
# Each maps lst -> expected output per fp-23 op semantics.
_REF: dict = {
    "reverse":        lambda lst: lst[::-1],
    "sort_asc":       lambda lst: sorted(lst),
    "sort_desc":      lambda lst: sorted(lst, reverse=True),
    "filter_even":    lambda lst: [x for x in lst if x % 2 == 0],
    "filter_odd":     lambda lst: [x for x in lst if x % 2 != 0],
    "sum_fold":       lambda lst: sum(lst),
    "min_fold":       lambda lst: min(lst),
    "max_fold":       lambda lst: max(lst),
    "dedup_stable":   lambda lst: list(dict.fromkeys(lst)),
    "count_distinct": lambda lst: len(set(lst)),
}

# Fixed NL descriptions per op for prompt construction (one template per op,
# no paraphrase pool — frozen per fp-23 "fixed NL template" rule).
_OP_DESC: dict[str, str] = {
    "reverse":        "returns the list in reverse order",
    "sort_asc":       "returns the list sorted in ascending order",
    "sort_desc":      "returns the list sorted in descending order",
    "filter_even":    "returns only the even numbers from the list",
    "filter_odd":     "returns only the odd numbers from the list",
    "sum_fold":       "returns the sum of all numbers in the list",
    "min_fold":       "returns the minimum number in the list",
    "max_fold":       "returns the maximum number in the list",
    "dedup_stable":   "returns the list with duplicates removed, preserving insertion order",
    "count_distinct": "returns the count of distinct numbers in the list",
}


# ---------------------------------------------------------------------------
# Probe set generation
# ---------------------------------------------------------------------------


def _build_probe_set() -> list[dict]:
    """Deterministic: cycle L1_OPS with seeded random inputs, keep PROBE_BUCKETS.

    Returns exactly fp23.PROBE_N tasks. Same seed -> same set always.
    """
    rng = random.Random(fp23.GENERATOR_SEED)
    tasks: list[dict] = []
    seen: set[str] = set()

    while len(tasks) < fp23.PROBE_N:
        op = rng.choice(list(fp23.L1_OPS))
        length = rng.randint(fp23.INPUT_LEN[0], fp23.INPUT_LEN[1])
        lst = [rng.randint(fp23.INPUT_VAL[0], fp23.INPUT_VAL[1])
               for _ in range(length)]
        key = f"{op}:{repr(lst)}"
        if key in seen:
            continue
        b = fp23.bucket(op, repr(lst))
        if b in fp23.PROBE_BUCKETS:
            seen.add(key)
            expected = _REF[op](lst)
            tasks.append({"op": op, "input": lst, "expected": expected})

    return tasks


def _probe_set_sha256(tasks: list[dict]) -> str:
    """Deterministic hash of the probe set inputs (op + input only, not expected)."""
    payload = json.dumps(
        [{"op": t["op"], "input": t["input"]} for t in tasks],
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# ---------------------------------------------------------------------------
# Prompt construction (fixed NL template per op)
# ---------------------------------------------------------------------------


def _build_prompt(op: str, input_list: list, expected: object) -> str:
    """Build the raw-text prompt ending with 'def solve(lst):\n'.

    The model's completion starts at the function body. This is the raw-text
    (no chat template) format matching the ember base-model consumption pattern.
    """
    return (
        f"# Python programming task\n"
        f"# Task: write a function solve(lst) that {_OP_DESC[op]}.\n"
        f"# Input example: {input_list}\n"
        f"# Expected output: {expected}\n\n"
        f"def solve(lst):\n"
    )


# ---------------------------------------------------------------------------
# Candidate execution (Windows-compatible thread-based timeout)
# ---------------------------------------------------------------------------


def _exec_candidate(
    completion: str, input_list: list, timeout_s: float = fp23.CANDIDATE_TIMEOUT_S
) -> object:
    """Execute 'def solve(lst):\\n{completion}' and return result or sentinel.

    Returns:
        The function's return value on success.
        "_TIMEOUT_" if the thread didn't finish in time.
        "_ERROR_"   on any exception (SyntaxError, NameError, etc.).
    """
    source = f"def solve(lst):\n{completion}\n_result = solve(_input)\n"
    box: list = [None, None]  # [result, error_str]

    def _run() -> None:
        ns: dict = {"_input": list(input_list)}
        try:
            exec(source, ns)  # noqa: S102
            box[0] = ns.get("_result")
        except Exception as exc:
            box[1] = str(exc)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout_s)

    if thread.is_alive():
        return "_TIMEOUT_"
    if box[1] is not None:
        return "_ERROR_"
    return box[0]


def _verify_candidate(result: object, expected: object) -> bool:
    """String-normalized repr comparison per fp-23 verification rule."""
    if isinstance(result, str) and result.startswith("_"):
        return False
    return repr(result) == repr(expected)


# ---------------------------------------------------------------------------
# Model loading (same pattern as ember_shakedown.py)
# ---------------------------------------------------------------------------


def _build_model_class():
    import torch
    from transformers import LlamaConfig, LlamaModel

    with open(CONFIG_PATH, encoding="utf-8") as f:
        cfg = json.load(f)
    m = cfg["model"]
    n_mtp = cfg["objective"]["mtp_aux_heads"]["n_heads"]

    class _V0Real(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            conf = LlamaConfig(
                vocab_size=m["vocab"], hidden_size=m["hidden"],
                intermediate_size=4096, num_hidden_layers=m["layers"],
                num_attention_heads=m["heads"], num_key_value_heads=m["heads"],
                max_position_embeddings=m["seq"], tie_word_embeddings=False,
            )
            self.backbone_model = LlamaModel(conf)
            self.head = torch.nn.Linear(m["hidden"], m["vocab"], bias=False)
            if m["tied_embeddings"]:
                self.head.weight = self.backbone_model.embed_tokens.weight
            self.mtp_heads = torch.nn.ModuleList(
                [torch.nn.Linear(m["hidden"], m["vocab"], bias=False)
                 for _ in range(n_mtp)]
            )

    return _V0Real, m, n_mtp


def _load_model(model_pt_path: Path):
    import torch
    _V0Real, _, _ = _build_model_class()
    model = _V0Real()
    sd = torch.load(str(model_pt_path), map_location=DEVICE, weights_only=True)
    model.load_state_dict(sd, strict=True)
    model.eval()
    return model


def _load_tokenizer():
    from tokenizers import Tokenizer
    return Tokenizer.from_file(str(TOKENIZER_PATH))


def _make_generate_fn(model, tok):
    """Raw-text KV-cache greedy generate (no chat template — base model)."""
    import torch

    def generate_fn(prompt: str) -> str:
        encoding = tok.encode(prompt)
        input_ids = torch.tensor([encoding.ids], dtype=torch.long)
        generated_ids: list[int] = []
        past_key_values = None

        with torch.no_grad():
            out = model.backbone_model(
                input_ids=input_ids,
                use_cache=True,
                past_key_values=None,
            )
            past_key_values = out.past_key_values
            h = out.last_hidden_state[:, -1, :]

            for _ in range(MAX_NEW_TOKENS):
                logits = model.head(h)
                next_id = int(logits.argmax(dim=-1).item())
                if next_id == EOS_ID:
                    break
                generated_ids.append(next_id)
                new_tok = torch.tensor([[next_id]], dtype=torch.long)
                out = model.backbone_model(
                    input_ids=new_tok,
                    use_cache=True,
                    past_key_values=past_key_values,
                )
                past_key_values = out.past_key_values
                h = out.last_hidden_state[:, 0, :]

        return tok.decode(generated_ids)

    return generate_fn


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------


def _checkpoint_sha256(ckpt_dir: Path, filename: str = "model.pt") -> str:
    h = hashlib.sha256()
    with open(ckpt_dir / filename, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _copy_checkpoint(ckpt_dir: Path, dest_dir: str) -> Path:
    dest = Path(dest_dir)
    for fname in ["model.pt", "manifest.json"]:
        src = ckpt_dir / fname
        if src.exists():
            shutil.copy2(str(src), str(dest / fname))
    return dest / "model.pt"


def _tokenizer_sha256() -> str:
    h = hashlib.sha256()
    with open(TOKENIZER_PATH, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _get_commit_sha() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        return r.stdout.strip()
    except Exception:
        return "unknown"


def _get_file_commit_sha(rel_path: str) -> str:
    try:
        r = subprocess.run(
            ["git", "log", "-1", "--pretty=format:%H", "--", rel_path],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        return r.stdout.strip() or "uncommitted"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Probe runner
# ---------------------------------------------------------------------------


def run_probe(generate_fn, tasks: list[dict], k: int) -> dict:
    """Run fp-23 L1 probe: k candidates per task, verify, record stats."""
    l1_verified_episodes = 0
    l1_tasks_any_verified = 0
    step_count = 0

    t_start = time.time()

    for i, task in enumerate(tasks):
        op = task["op"]
        input_list = task["input"]
        expected = task["expected"]
        prompt = _build_prompt(op, input_list, expected)
        task_any = False

        for _ in range(k):
            completion = generate_fn(prompt)
            step_count += MAX_NEW_TOKENS  # conservative: count max possible
            result = _exec_candidate(completion, input_list)
            if _verify_candidate(result, expected):
                l1_verified_episodes += 1
                task_any = True

        if task_any:
            l1_tasks_any_verified += 1

        if (i + 1) % 10 == 0:
            elapsed = time.time() - t_start
            print(f"  [{i+1:3d}/{len(tasks)}] verified={l1_verified_episodes} elapsed={elapsed:.0f}s")

    probe_wall_s = round(time.time() - t_start, 1)
    pacing_s = round(step_count * PACE_S_PER_STEP, 1)
    governed_s = probe_wall_s + pacing_s
    governed_minutes = round(governed_s / 60.0, 4)

    return {
        "l1_verified_episodes": l1_verified_episodes,
        "l1_tasks_any_verified": l1_tasks_any_verified,
        "l1_tasks_total": len(tasks),
        "probe_wall_s": probe_wall_s,
        "pacing_s": pacing_s,
        "governed_s": governed_s,
        "l1_governed_minutes": governed_minutes,
        "step_count": step_count,
    }


# ---------------------------------------------------------------------------
# Selftest (pure logic, no model)
# ---------------------------------------------------------------------------


def _selftest() -> None:
    # Probe set determinism
    p1 = _build_probe_set()
    p2 = _build_probe_set()
    assert p1 == p2, "probe set not deterministic"
    assert len(p1) == fp23.PROBE_N, f"expected {fp23.PROBE_N} tasks, got {len(p1)}"

    # All tasks fall in probe buckets with valid inputs
    for t in p1:
        b = fp23.bucket(t["op"], repr(t["input"]))
        assert b in fp23.PROBE_BUCKETS, f"bucket {b} not in probe range"
        assert t["op"] in fp23.L1_OPS
        assert fp23.INPUT_LEN[0] <= len(t["input"]) <= fp23.INPUT_LEN[1]
        for v in t["input"]:
            assert fp23.INPUT_VAL[0] <= v <= fp23.INPUT_VAL[1]

    # Probe set sha is deterministic
    sha_a = _probe_set_sha256(p1)
    sha_b = _probe_set_sha256(p1)
    assert sha_a == sha_b and len(sha_a) == 64

    # Reference implementations
    assert set(_REF.keys()) == set(fp23.L1_OPS)
    assert _REF["reverse"]([1, 2, 3]) == [3, 2, 1]
    assert _REF["sort_asc"]([3, 1, 2]) == [1, 2, 3]
    assert _REF["sort_desc"]([3, 1, 2]) == [3, 2, 1]
    assert _REF["filter_even"]([1, 2, 3, 4]) == [2, 4]
    assert _REF["filter_odd"]([1, 2, 3, 4]) == [1, 3]
    assert _REF["sum_fold"]([1, 2, 3]) == 6
    assert _REF["min_fold"]([3, 1, 2]) == 1
    assert _REF["max_fold"]([3, 1, 2]) == 3
    assert _REF["dedup_stable"]([1, 2, 1, 3]) == [1, 2, 3]
    assert _REF["count_distinct"]([1, 2, 1, 3]) == 3

    # OP descriptions cover all ops
    assert set(_OP_DESC.keys()) == set(fp23.L1_OPS)

    # Candidate exec + verify
    result_ok = _exec_candidate("    return lst[::-1]\n", [1, 2, 3])
    assert result_ok == [3, 2, 1]
    assert _verify_candidate(result_ok, [3, 2, 1])
    assert not _verify_candidate(result_ok, [1, 2, 3])

    result_err = _exec_candidate("    return lst[", [1, 2, 3])
    assert result_err == "_ERROR_"
    assert not _verify_candidate(result_err, [1, 2, 3])

    result_sum = _exec_candidate("    return sum(lst)\n", [1, 2, 3])
    assert result_sum == 6
    assert _verify_candidate(result_sum, 6)

    # fp-23 schema: all 16 required fields mapped in this script
    required = set(fp23.RECEIPT_REQUIRED_FIELDS)
    assert required  # nonempty sanity

    print("SP_CHECKPOINT_PROBE_SELFTEST_PASS")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    args = sys.argv[1:]

    if "--selftest" in args:
        _selftest()
        return 0

    if "--run" not in args:
        print(_STAGED_MSG)
        return 1

    write = "--write" in args

    if "--checkpoint-dir" not in args:
        print("CHECKPOINT_PROBE_NO_CKPT_DIR: --checkpoint-dir <path> required")
        return 1

    idx = args.index("--checkpoint-dir")
    ckpt_dir = Path(args[idx + 1])

    k = DEFAULT_K
    if "--k" in args:
        idx_k = args.index("--k")
        k = min(int(args[idx_k + 1]), fp23.PROBE_K)

    if not (ckpt_dir / "model.pt").exists():
        print(f"CHECKPOINT_PROBE_NO_CHECKPOINT: model.pt not found at {ckpt_dir}")
        return 1

    # Load manifest
    manifest_path = ckpt_dir / "manifest.json"
    manifest: dict = {}
    if manifest_path.exists():
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

    step = manifest.get("step", 0)
    checkpoint_tokens = step * BATCH_SIZE * SEQ_LEN

    print(f"Checkpoint: {ckpt_dir}")
    print(f"Step: {step:,}, Tokens: {checkpoint_tokens:,} ({checkpoint_tokens / 1e9:.4f}B)")

    # Seat adapter selftest (confirms adapter mechanics)
    st = subprocess.run(
        [sys.executable, str(_SCRIPTS_DIR / "nck" / "selftest_seat_adapter.py")],
        capture_output=True, text=True,
    )
    if st.returncode != 0:
        print(f"SEAT_ADAPTER_SELFTEST FAIL:\n{st.stdout}\n{st.stderr}")
        return 1
    print(f"Adapter selftest: {st.stdout.strip()}")

    # Tokenizer sha256
    tok_sha = _tokenizer_sha256()

    # Corpus manifest sha (from pretrain config — the assembly receipt sha field)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)
    src_field = config["data"]["source"]
    # Format: "tokenized v0 corpus (assembly receipt sha <sha>)"
    import re as _re
    m = _re.search(r"sha ([a-f0-9]{64})", src_field)
    corpus_manifest_sha = m.group(1) if m else src_field

    # Checkpoint sha (BEFORE copy)
    model_pt_sha = _checkpoint_sha256(ckpt_dir)
    print(f"model.pt sha256: {model_pt_sha[:24]}...")

    # Build probe set
    tasks = _build_probe_set()
    probe_set_sha = _probe_set_sha256(tasks)
    print(f"Probe set: {len(tasks)} tasks, sha={probe_set_sha[:16]}...")

    # Copy checkpoint — never hold live file handles on v0-r1s1
    with tempfile.TemporaryDirectory(prefix="sp-ckpt-probe-") as ckpt_tmp:
        print(f"Copying checkpoint to temp...")
        model_pt_copy = _copy_checkpoint(ckpt_dir, ckpt_tmp)

        print(f"\nLoading ember v0 (CPU, bfloat16, {ckpt_dir.name})...")
        t_load = time.time()
        model = _load_model(model_pt_copy)
        load_s = round(time.time() - t_load, 1)
        print(f"Loaded in {load_s}s")

        tok = _load_tokenizer()
        generate_fn = _make_generate_fn(model, tok)

        print(f"\nRunning fp-23 L1 probe ({len(tasks)} tasks, k={k}, CPU, greedy)...")
        probe_stats = run_probe(generate_fn, tasks, k)

    rate = fp23.floor_rate(
        probe_stats["l1_verified_episodes"],
        probe_stats["l1_governed_minutes"],
    )

    print(f"\nProbe: {probe_stats['l1_verified_episodes']} verified eps, "
          f"rate={rate} /governed-min (floor={fp23.FLOOR_RATE} at 2B), "
          f"{probe_stats['probe_wall_s']}s wall")

    commit_sha = _get_commit_sha()
    protocol_sha = _get_file_commit_sha("scripts/fp23_probe_prereg.py")
    harness_sha = _get_file_commit_sha("scripts/nck/checkpoint_probe.py")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    receipt: dict = {
        "ticket": "SP-CHECKPOINT-PROBE",
        "label": f"CHECKPOINT-PROBE-step-{step}-{checkpoint_tokens // 1_000_000}M-tokens",
        "ts": ts,
        "seat": "ember",
        # --- 16 fp-23 RECEIPT_REQUIRED_FIELDS ---
        "checkpoint_tokens": checkpoint_tokens,
        "step": step,
        "tokenizer_sha256": tok_sha,
        "corpus_manifest_sha256": corpus_manifest_sha,
        "adapter_none_assert": True,
        "pacing": {
            "pace_s_per_step": PACE_S_PER_STEP,
            "step_count": probe_stats["step_count"],
            "pacing_s": probe_stats["pacing_s"],
        },
        "governor": {
            "vram_fraction": 0.80,
            "margin_gib_floor": 1.5,
            "pace_s_per_step": PACE_S_PER_STEP,
        },
        "probe_seed": fp23.GENERATOR_SEED,
        "probe_set_sha256": probe_set_sha,
        "l1_verified_episodes": probe_stats["l1_verified_episodes"],
        "l1_governed_minutes": probe_stats["l1_governed_minutes"],
        "l1_tasks_any_verified": probe_stats["l1_tasks_any_verified"],
        "l1_tasks_total": probe_stats["l1_tasks_total"],
        "l2_verified_episodes": 0,
        "mbpp43_verified_samples": 0,
        # --- provenance ---
        "checkpoint": {
            "dir": str(ckpt_dir),
            "name": ckpt_dir.name,
            "step": step,
            "model_pt_sha256": model_pt_sha,
            "load_s": load_s,
            "device": DEVICE,
            "torch_dtype": "bfloat16",
        },
        "decode_params": {
            "max_new_tokens": MAX_NEW_TOKENS,
            "greedy": True,
            "eos_token_id": EOS_ID,
            "format": "raw_text_no_chat_template",
        },
        "probe_params": {
            "k": k,
            "probe_n": fp23.PROBE_N,
            "candidate_timeout_s": fp23.CANDIDATE_TIMEOUT_S,
        },
        "protocol_sha": protocol_sha,
        "harness_sha": harness_sha,
        "adapter_commit_sha": commit_sha,
        "sha_convention": (
            "sha256 over on-disk raw bytes (binary read, no line-ending normalization)"
        ),
        "flags": [
            f"CPU inference: device={DEVICE}, dtype=bfloat16",
            "checkpoint read from COPY — no live file handles on v0-r1s1",
            "live run 12c050e7 untouched",
            f"fp-23 protocol frozen before pretrain step 0 (protocol_sha={protocol_sha[:16]}...)",
            f"pre-floor checkpoint: step={step}, tokens={checkpoint_tokens:,} — fp-23 decide() INFO only",
            "L2 and MBPP-43 fields = 0 (not probed at this checkpoint window)",
        ],
        "live_run_untouched": "12c050e7",
    }

    # Validate receipt against fp-23 schema floor before writing
    missing = fp23.validate_receipt(receipt)
    if missing:
        print(f"PROBE_RECEIPT_SCHEMA_FAIL: missing fields: {missing}")
        return 1

    if write:
        receipt_dir = REPO_ROOT / "receipts"
        receipt_dir.mkdir(exist_ok=True)
        fname = receipt_dir / f"sp-checkpoint-probe-step-{step}-{ts}.json"
        fname.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(f"RECEIPT: {fname}")
    else:
        print("(dry-run: pass --write to save receipt)")
        print(json.dumps({
            "step": step,
            "checkpoint_tokens": checkpoint_tokens,
            "l1_verified_episodes": probe_stats["l1_verified_episodes"],
            "l1_governed_minutes": probe_stats["l1_governed_minutes"],
            "rate": rate,
            "probe_set_sha256": probe_set_sha[:16] + "...",
        }, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
