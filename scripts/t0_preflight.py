"""t0_preflight.py — NC0 T0: WSL2 training-environment ground truth.

Emits one JSON receipt: GPU/CUDA state, training-stack versions, HF cache
inventory, ARC-AGI corpus check, disk space. No training, no downloads.

Receipt: /mnt/b/M/avir/leo/state/nc-ladder/receipts/t0-preflight.json
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

from receipt_write import checked_write

RECEIPT_PATH = "/mnt/b/M/avir/leo/state/nc-ladder/receipts/t0-preflight.json"
ARC_DIR = "/mnt/b/M/the-search/incoming/arc-agi1-visa/ARC-AGI"

receipt = {
    "ticket": "NC0-T0",
    "ts": datetime.now(timezone.utc).isoformat(),
    "python": sys.version,
    "checks": {},
}


def check(name, fn):
    try:
        receipt["checks"][name] = {"ok": True, "value": fn()}
    except Exception as e:  # noqa: BLE001 — receipt must record every failure
        receipt["checks"][name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}


def gpu():
    import torch

    info = {
        "torch": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
    }
    if torch.cuda.is_available():
        info["device"] = torch.cuda.get_device_name(0)
        free, total = torch.cuda.mem_get_info()
        info["vram_free_gb"] = round(free / 1e9, 2)
        info["vram_total_gb"] = round(total / 1e9, 2)
    return info


def versions():
    import importlib.metadata as md

    out = {}
    for pkg in ["transformers", "unsloth", "trl", "peft", "datasets",
                "vllm", "accelerate", "bitsandbytes", "xformers", "numpy"]:
        try:
            out[pkg] = md.version(pkg)
        except md.PackageNotFoundError:
            out[pkg] = None
    return out


def nvidia_smi():
    r = subprocess.run(
        ["nvidia-smi", "--query-gpu=name,memory.total,memory.used",
         "--format=csv,noheader"],
        capture_output=True, text=True, timeout=30,
    )
    return r.stdout.strip() or r.stderr.strip()


def hf_cache():
    hub = os.path.expanduser("~/.cache/huggingface/hub")
    if not os.path.isdir(hub):
        return {"path": hub, "exists": False}
    entries = []
    for name in sorted(os.listdir(hub)):
        p = os.path.join(hub, name)
        if not os.path.isdir(p) or not name.startswith("models--"):
            continue
        size = 0
        for root, _, files in os.walk(p):
            for f in files:
                try:
                    size += os.path.getsize(os.path.join(root, f))
                except OSError:
                    pass
        entries.append({"model": name, "size_gb": round(size / 1e9, 2)})
    return {"path": hub, "exists": True, "models": entries}


def arc_corpus():
    out = {"dir": ARC_DIR, "exists": os.path.isdir(ARC_DIR)}
    if out["exists"]:
        for split in ["training", "evaluation"]:
            for candidate in [os.path.join(ARC_DIR, "data", split),
                              os.path.join(ARC_DIR, split)]:
                if os.path.isdir(candidate):
                    n = len([f for f in os.listdir(candidate) if f.endswith(".json")])
                    out[split] = {"path": candidate, "json_count": n}
                    break
            else:
                out[split] = {"path": None, "json_count": 0}
    return out


def disk():
    out = {}
    for label, path in [("home", os.path.expanduser("~")), ("mnt_b", "/mnt/b")]:
        u = shutil.disk_usage(path)
        out[label] = {"free_gb": round(u.free / 1e9, 1), "total_gb": round(u.total / 1e9, 1)}
    return out


check("gpu", gpu)
check("versions", versions)
check("nvidia_smi", nvidia_smi)
check("hf_cache", hf_cache)
check("arc_corpus", arc_corpus)
check("disk", disk)

os.makedirs(os.path.dirname(RECEIPT_PATH), exist_ok=True)
checked_write(RECEIPT_PATH, receipt)

print(json.dumps(receipt, indent=2))
print("T0_PREFLIGHT_DONE")
