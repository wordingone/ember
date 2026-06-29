#!/usr/bin/env python3
"""Check environment readiness for selected C5 baseline runs without launching training."""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
import sys
from pathlib import Path


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def torch_info() -> dict:
    if not has_module("torch"):
        return {"installed": False}
    import torch
    info = {
        "installed": True,
        "version": getattr(torch, "__version__", None),
        "cuda_available": torch.cuda.is_available(),
        "cuda_device_count": torch.cuda.device_count(),
    }
    if torch.cuda.is_available():
        info.update(
            {
                "cuda_device_0": torch.cuda.get_device_name(0),
                "bf16_supported": torch.cuda.is_bf16_supported(),
            }
        )
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mlagentbench", type=Path, required=True)
    parser.add_argument("--ai-scientist", type=Path, required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    ml_required = ["absl", "attrs", "chex", "haiku", "jax", "jaxlib", "numpy", "optax", "tensorflow", "clrs"]
    ai_required = ["torch", "numpy", "transformers", "datasets", "tiktoken", "tqdm"]
    ml_modules = {name: has_module(name) for name in ml_required}
    ai_modules = {name: has_module(name) for name in ai_required}
    torch = torch_info()

    clrs_train = args.mlagentbench / "MLAgentBench" / "benchmarks" / "CLRS" / "env" / "train.py"
    clrs_eval = args.mlagentbench / "MLAgentBench" / "benchmarks" / "CLRS" / "scripts" / "eval.py"
    ng_exp = args.ai_scientist / "templates" / "nanoGPT_lite" / "experiment.py"
    shakespeare_prepare = args.ai_scientist / "data" / "shakespeare_char" / "prepare.py"

    c5a_ready = all(ml_modules.values()) and clrs_train.exists() and clrs_eval.exists()
    c5b_ready = all(ai_modules.values()) and torch.get("cuda_available") and ng_exp.exists() and shakespeare_prepare.exists()

    result = {
        "verdict": "PASS" if c5a_ready and c5b_ready else "INVALID-RUN",
        "python": sys.version,
        "platform": platform.platform(),
        "tasks": {
            "C5-0A-MLAgentBench-CLRS": {
                "baseline_readiness": "PASS" if c5a_ready else "INVALID-RUN",
                "modules": ml_modules,
                "required_files_present": {
                    "train.py": clrs_train.exists(),
                    "eval.py": clrs_eval.exists(),
                },
                "next_repair": None if c5a_ready else "Create isolated environment with MLAgentBench CLRS requirements including dm-clrs/clrs before running baseline.",
            },
            "C5-0B-AI-Scientist-nanoGPT-lite": {
                "baseline_readiness": "PASS" if c5b_ready else "INVALID-RUN",
                "modules": ai_modules,
                "torch": torch,
                "required_files_present": {
                    "experiment.py": ng_exp.exists(),
                    "data/shakespeare_char/prepare.py": shakespeare_prepare.exists(),
                },
                "next_repair": None if c5b_ready else "Install missing nanoGPT_lite dependencies or repair CUDA visibility before baseline run.",
            },
        },
    }
    print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True))
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())