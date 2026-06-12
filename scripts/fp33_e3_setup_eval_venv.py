"""fp33_e3_setup_eval_venv.py — create csi-eval venv for Gemma 4 E2B support.

Creates /mnt/c/Users/Admin/.venvs/csi-eval with --system-site-packages
(inherits torch/datasets/etc. from csi-train env), then upgrades transformers
so gemma4 architecture is in CONFIG_MAPPING.

csi-train is NEVER touched. Leo approval: mail 14736.
"""
from __future__ import annotations

import subprocess
import sys
import os

VENV_PATH   = "/mnt/c/Users/Admin/.venvs/csi-eval"
VENV_PYTHON = f"{VENV_PATH}/bin/python"
VENV_PIP    = f"{VENV_PATH}/bin/pip"


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
    print(f"[SETUP] $ {' '.join(cmd)}", flush=True)
    r = subprocess.run(cmd, capture_output=False, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"command failed (rc={r.returncode}): {' '.join(cmd)}")
    return r


def main():
    print(f"[SETUP] base Python: {sys.executable}", flush=True)

    if not os.path.exists(VENV_PYTHON):
        print(f"[SETUP] creating venv at {VENV_PATH}", flush=True)
        run([sys.executable, "-m", "venv", "--system-site-packages", VENV_PATH])
    else:
        print(f"[SETUP] venv already exists — skipping creation", flush=True)

    run([VENV_PIP, "install", "--upgrade", "pip"])
    run([VENV_PIP, "install", "--upgrade", "transformers"])

    # Verify gemma4 support
    check = subprocess.run(
        [VENV_PYTHON, "-c",
         "import transformers; "
         "from transformers.models.auto.configuration_auto import CONFIG_MAPPING; "
         "keys = [k for k in CONFIG_MAPPING.keys() if 'gemma4' in k]; "
         "print(f'transformers={transformers.__version__} gemma4_keys={keys}'); "
         "assert keys, 'gemma4 NOT in CONFIG_MAPPING after upgrade'"],
        capture_output=True, text=True,
    )
    print(f"[SETUP] verify stdout: {check.stdout.strip()}", flush=True)
    if check.returncode != 0:
        print(f"[SETUP] verify stderr: {check.stderr.strip()}", flush=True)
        raise RuntimeError("gemma4 not found after transformers upgrade")

    print("FP33_E3_SETUP_EVAL_VENV_DONE", flush=True)


if __name__ == "__main__":
    main()
